// Constants
const POLLING_INTERVAL = 1000; // 1 second
const CHART_UPDATE_INTERVAL = 1000; // 1 second
const MAX_DATA_POINTS = 3600; // 60 hours at 1 minute interval
const ANIMATION_DURATION = 350; // milliseconds

let straddlePriceFromSocket = 0;
let lastKnownStraddlePrice = 0;
let pendingChartUpdate = false;
let lastChartUpdate = Date.now();
let currentSelectedIndex = 'nifty';
let openOptionPositions = [];
const SPLITTER_STORAGE_KEY = 'dashboardSplitterWidth_v1';
let observedStraddleLow = null;
let observedStraddleHigh = null;
const STRIKE_STEP_BY_INDEX = {
    nifty: 50,
    sensex: 100,
    banknifty: 100
};

function isValidNumber(value) {
    return typeof value === 'number' && Number.isFinite(value);
}

function formatChange(val) {
    if (!isValidNumber(val)) return `<span class="neutral">-</span>`;
    if (val > 0) return `<span class="positive">+${val}</span>`;
    if (val < 0) return `<span class="negative">${val}</span>`;
    return `<span class="neutral">${val}</span>`;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderRecommendation(legs, net_delta, strangle_credit, future_price, skew) {
    let html = `<div class="recommendation-title"><h2 class="recommendation-title">Iron Condor Recommendation</h2></div>`;
    html += `<table class="recommendation-table" border="1">
        <tr><th>Leg</th><th>Strike</th><th>Type</th><th>LTP</th><th>Delta</th></tr>`;

    const hasLegs = legs && typeof legs === 'object';
    const orderedLegs = ['hedge_pe', 'short_pe', 'short_ce', 'hedge_ce'];
    let availableRows = 0;
    orderedLegs.forEach(leg => {
        const data = hasLegs ? legs[leg] : null;
        if (!data) return;  // skip if data is missing
        availableRows += 1;
        const strike = data.strike ?? '-';
        const type = data.type ?? '-';
        const ltp = isValidNumber(Number(data.ltp)) ? `₹${formatIndianNumber(Number(data.ltp))}` : '-';
        const legDelta = isValidNumber(Number(data.delta)) ? Number(data.delta).toFixed(2) : '-';
        html += `<tr>
            <td>${leg.replace('_', ' ').toUpperCase()}</td>
            <td>${strike}</td>
            <td>${type}</td>
            <td>${ltp}</td>
            <td>${legDelta}</td>
        </tr>`;
    });
    if (availableRows === 0) {
        html += `<tr><td colspan="5">No legs data available.</td></tr>`;
    }
    html += `</table>`;

    const metrics = [
        isValidNumber(Number(net_delta)) ? { label: 'Net Delta', value: Number(net_delta).toFixed(3) } : null,
        isValidNumber(Number(strangle_credit)) ? { label: 'Straddle Price', value: `₹${formatIndianNumber(Number(strangle_credit))}` } : null,
        isValidNumber(Number(future_price)) ? { label: 'Synth Fut Price', value: `₹${formatIndianNumber(Number(future_price))}` } : null,
        isValidNumber(Number(skew)) ? { label: 'Skew', value: Number(skew).toFixed(2) } : null
    ].filter(Boolean);

    if (metrics.length > 0) {
        html += `<div class="metrics-row">`;
        metrics.forEach(metric => {
            html += `
                <div class="metric">
                    <span class="label">${metric.label}:</span>
                    <span class="value"><strong>${metric.value}</strong></span>
                </div>
            `;
        });
        html += `</div>`;
    }
    return html;
}


function updateSpotDisplay(spotPrice, previousClose) {
    const spotValueEl = document.getElementById('spot-value');
    const spotChangeEl = document.getElementById('spot-change');
    const container = document.getElementById('spot-price');

    // Calculate point and percent change
    const validSpot = isValidNumber(Number(spotPrice)) ? Number(spotPrice) : null;
    const validPrevClose = isValidNumber(Number(previousClose)) ? Number(previousClose) : null;

    if (validSpot === null || validPrevClose === null || validPrevClose === 0) {
        spotValueEl.textContent = validSpot !== null ? validSpot.toFixed(2) : '--';
        spotChangeEl.textContent = '(--%)';
        container.className = 'price neutral';
        return;
    }

    const pointChange = validSpot - validPrevClose;
    const percentChange = (pointChange / validPrevClose) * 100;
    const isPositive = pointChange >= 0;

    // Update display
    spotValueEl.textContent = validSpot.toFixed(2);
    const sign = isPositive ? "+" : "";
    spotChangeEl.textContent = `${sign}${pointChange.toFixed(2)} (${sign}${percentChange.toFixed(2)}%)`;

    // Update color
    container.className = "price " + (isPositive ? "positive" : "negative");
}

function setVitalValue(cardId, valueId, valueText, isAvailable = true) {
    const card = document.getElementById(cardId);
    const valueEl = document.getElementById(valueId);
    if (!card || !valueEl) return;

    if (!isAvailable) {
        card.classList.add('is-hidden');
        return;
    }

    card.classList.remove('is-hidden');
    valueEl.textContent = valueText;
}

function updateTopCockpit(json, atmStrike = null) {
    const symbol = json.symbol || currentSelectedIndex?.toUpperCase() || '--';
    const spot = isValidNumber(Number(json.spot_price)) ? `₹${formatIndianNumber(Number(json.spot_price))}` : '--';
    const synthFutNum = isValidNumber(Number(json.future_price)) ? Number(json.future_price) : null;
    const priceNum = isValidNumber(Number(json.strangle_credit)) ? Number(json.strangle_credit) : null;
    if (isValidNumber(priceNum)) {
        observedStraddleLow = observedStraddleLow === null ? priceNum : Math.min(observedStraddleLow, priceNum);
        observedStraddleHigh = observedStraddleHigh === null ? priceNum : Math.max(observedStraddleHigh, priceNum);
    }
    const lowNum = isValidNumber(Number(json.low)) ? Number(json.low) : observedStraddleLow;
    const highNum = isValidNumber(Number(json.high)) ? Number(json.high) : observedStraddleHigh;
    const updated = new Date().toLocaleString('en-IN', { hour12: true });

    setVitalValue('vital-card-symbol', 'vital-symbol', symbol, true);
    setVitalValue('vital-card-spot', 'vital-spot', spot, spot !== '--');
    setVitalValue('vital-card-synth', 'vital-synth', synthFutNum !== null ? `₹${formatIndianNumber(synthFutNum)}` : '--', synthFutNum !== null);
    setVitalValue('vital-card-atm', 'vital-atm', atmStrike !== null ? String(atmStrike) : '--', atmStrike !== null);
    setVitalValue('vital-card-price', 'vital-price', priceNum !== null ? `₹${formatIndianNumber(priceNum)}` : '--', priceNum !== null);
    setVitalValue('vital-card-low', 'vital-low', lowNum !== null ? `₹${formatIndianNumber(lowNum)}` : '--', lowNum !== null);
    setVitalValue('vital-card-high', 'vital-high', highNum !== null ? `₹${formatIndianNumber(highNum)}` : '--', highNum !== null);
    setVitalValue('vital-card-updated', 'vital-updated', updated, true);
}

function setMainViewMode(mode) {
    const liveCard = document.getElementById('live-pnl-card');
    const strategyCard = document.getElementById('strategy-card');
    const splitter = document.getElementById('main-splitter');
    if (!liveCard || !strategyCard || !splitter) return;

    if (mode === 'chart') {
        liveCard.style.display = '';
        strategyCard.style.display = 'none';
        splitter.style.display = 'none';
    } else if (mode === 'table') {
        liveCard.style.display = 'none';
        strategyCard.style.display = '';
        splitter.style.display = 'none';
    } else {
        liveCard.style.display = '';
        strategyCard.style.display = '';
        splitter.style.display = '';
    }
}

function initializePanelSplitter() {
    const mainContent = document.querySelector('.main-content');
    const splitter = document.getElementById('main-splitter');
    if (!mainContent || !splitter) return;

    const savedWidth = Number(localStorage.getItem(SPLITTER_STORAGE_KEY));
    if (isValidNumber(savedWidth) && savedWidth >= 50 && savedWidth <= 80) {
        document.documentElement.style.setProperty('--live-panel-size', `${savedWidth}%`);
    }

    let dragging = false;

    const onMove = (clientX) => {
        const rect = mainContent.getBoundingClientRect();
        const rawPercent = ((clientX - rect.left) / rect.width) * 100;
        const clampedPercent = Math.min(80, Math.max(50, rawPercent));
        document.documentElement.style.setProperty('--live-panel-size', `${clampedPercent}%`);
        localStorage.setItem(SPLITTER_STORAGE_KEY, String(clampedPercent));
    };

    const stopDrag = () => {
        if (!dragging) return;
        dragging = false;
        splitter.classList.remove('dragging');
        document.body.style.userSelect = '';
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', stopDrag);
    };

    const onMouseMove = (event) => {
        if (!dragging) return;
        onMove(event.clientX);
    };

    splitter.addEventListener('mousedown', (event) => {
        if (window.innerWidth <= 1200) return;
        dragging = true;
        splitter.classList.add('dragging');
        document.body.style.userSelect = 'none';
        onMove(event.clientX);
        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', stopDrag);
    });
}

function initializeCockpitControls() {
    const viewSelect = document.getElementById('cockpit-view');

    if (viewSelect) {
        viewSelect.addEventListener('change', (event) => setMainViewMode(event.target.value));
        setMainViewMode(viewSelect.value);
    }
}





// Polling-based fetching of option data from Flask endpoint
async function fetchOptionData() {
    try {
        const res = await fetch('/option_data');
        const json = await res.json();


        console.log(`Fetched option data at ${new Date().toISOString()}:`, json);

        straddlePriceFromSocket = json.strangle_credit ?? null;
        future_price = json.future_price ?? null;
        skew = json.skew ?? null;
        delta = json.delta ?? null;


        spot_price = json.spot_price ?? null;
        previous_close = json.previous_close ?? null;
        if (json.selected_index) {
            currentSelectedIndex = String(json.selected_index).toLowerCase();
        }
        updateSpotDisplay(json.spot_price, json.previous_close);
        document.getElementById('symbol').textContent = json.symbol || "Index";
        document.getElementById("recommendation").innerHTML = renderRecommendation(
            json.legs,
            json.net_delta,
            json.strangle_credit,
            json.future_price,
            json.skew
        );

        const strikeStep = STRIKE_STEP_BY_INDEX[currentSelectedIndex] || null;
        const atmStrike = (strikeStep && typeof spot_price === 'number')
            ? Math.round(spot_price / strikeStep) * strikeStep
            : null;
        updateTopCockpit(json, atmStrike);

    } catch (error) {
        console.error('Error fetching option data:', error);
    }
}


let pnlChart;
let pnlData = {
    pnlSeries: [],
    straddleSeries: [],
};

// Add these functions for localStorage management
function saveToLocalStorage() {
    try {
        localStorage.setItem('pnlData_v2', JSON.stringify(pnlData));
    } catch (error) {
        console.error('Error saving to localStorage:', error);
    }
}

function loadFromLocalStorage() {
    try {
        const savedData = localStorage.getItem('pnlData_v2');
        if (savedData) {
            const parsed = JSON.parse(savedData);
            if (Array.isArray(parsed.pnlSeries) && Array.isArray(parsed.straddleSeries)) {
                
                // Deduplicate and bucket to exact minutes to fix overlap bugs from old data
                const minuteMapPnl = new Map();
                parsed.pnlSeries.forEach(pt => {
                    const tsm = Math.floor(pt[0] / 60000) * 60000;
                    minuteMapPnl.set(tsm, pt[1]);
                });
                
                const minuteMapStraddle = new Map();
                parsed.straddleSeries.forEach(pt => {
                    const tsm = Math.floor(pt[0] / 60000) * 60000;
                    minuteMapStraddle.set(tsm, pt[1]);
                });

                const cleanPnl = Array.from(minuteMapPnl.entries()).sort((a,b) => a[0] - b[0]);
                const cleanStraddle = Array.from(minuteMapStraddle.entries()).sort((a,b) => a[0] - b[0]);

                return { pnlSeries: cleanPnl, straddleSeries: cleanStraddle };
            }
        }
    } catch (error) {
        console.error('Error loading from localStorage:', error);
    }
    return null;
}

// Modify initializeChart to use localStorage
function initializeChart() {
    const savedData = loadFromLocalStorage();
    if (savedData) {
        pnlData = savedData;
    } else {
        pnlData.pnlSeries = [];
        pnlData.straddleSeries = [];
    }

    renderPnlChart();
}

async function fetchPnl() {
    try {
        const res = await fetch('/pnl');
        const json = await res.json();

        const ts = Date.now();
        const netPnl = Number(json.net_pnl);
        const apiStraddle = Number(json.straddle_price);
        const socketStraddle = Number(straddlePriceFromSocket);

        let straddlePrice = Number.isFinite(apiStraddle) ? apiStraddle : null;
        if (!Number.isFinite(straddlePrice)) {
            straddlePrice = Number.isFinite(socketStraddle) ? socketStraddle : null;
        }
        if (Number.isFinite(straddlePrice)) {
            lastKnownStraddlePrice = straddlePrice;
        } else {
            straddlePrice = lastKnownStraddlePrice;
        }

        if (!Number.isFinite(netPnl) || !Number.isFinite(straddlePrice)) {
            return;
        }

        // Group points by minute for 1-minute historical data gap
        const tsMinute = Math.floor(ts / 60000) * 60000;

        if (pnlData.pnlSeries.length > 0 && pnlData.pnlSeries[pnlData.pnlSeries.length - 1][0] === tsMinute) {
            // Update current minute's point
            pnlData.pnlSeries[pnlData.pnlSeries.length - 1][1] = netPnl;
            pnlData.straddleSeries[pnlData.straddleSeries.length - 1][1] = straddlePrice;
        } else {
            // New minute, add new point
            pnlData.pnlSeries.push([tsMinute, netPnl]);
            pnlData.straddleSeries.push([tsMinute, straddlePrice]);
        }

        if (pnlData.pnlSeries.length > MAX_DATA_POINTS) {
            pnlData.pnlSeries = pnlData.pnlSeries.slice(-MAX_DATA_POINTS);
            pnlData.straddleSeries = pnlData.straddleSeries.slice(-MAX_DATA_POINTS);
        }

        saveToLocalStorage();
        updatePnLDisplay(json, netPnl, straddlePrice);

        if (!pendingChartUpdate) {
            pendingChartUpdate = true;
            requestAnimationFrame(updateChart);
        }
    } catch (error) {
        console.error('Error fetching PnL data:', error);
    }
}

// Separate function for chart updates
function updateChart() {
    const now = Date.now();
    if (now - lastChartUpdate >= CHART_UPDATE_INTERVAL) {
        if (pnlChart) {
            pnlChart.updateSeries([
                {
                    name: 'Net P&L',
                    data: [...pnlData.pnlSeries]
                },
                {
                    name: 'Straddle Price',
                    data: [...pnlData.straddleSeries]
                }
            ], false);
            pnlChart.updateOptions({
                annotations: { points: buildLatestAnnotations() }
            }, false, false);
        }
        lastChartUpdate = now;
    }
    pendingChartUpdate = false;
}

function buildLatestAnnotations() {
    const points = [];

    const lastStraddle = pnlData.straddleSeries[pnlData.straddleSeries.length - 1];
    if (lastStraddle) {
        points.push({
            x: lastStraddle[0],
            y: lastStraddle[1],
            seriesIndex: 1,
            yAxisIndex: 0,
            marker: { size: 0 },
            label: {
                borderColor: '#21c55d',
                style: {
                    background: '#21c55d',
                    color: '#0b1220',
                    fontSize: '12px',
                    fontWeight: 600,
                    padding: { left: 8, right: 8, top: 4, bottom: 4 }
                },
                text: formatIndianNumber(lastStraddle[1])
            }
        });
    }

    const lastPnl = pnlData.pnlSeries[pnlData.pnlSeries.length - 1];
    if (lastPnl) {
        const pnlColor = lastPnl[1] >= 0 ? '#1f8bff' : '#ff5b5b';
        points.push({
            x: lastPnl[0],
            y: lastPnl[1],
            seriesIndex: 0,
            yAxisIndex: 1,
            marker: { size: 0 },
            label: {
                borderColor: pnlColor,
                style: {
                    background: pnlColor,
                    color: '#0b1220',
                    fontSize: '12px',
                    fontWeight: 600,
                    padding: { left: 8, right: 8, top: 4, bottom: 4 }
                },
                text: formatIndianNumber(lastPnl[1])
            }
        });
    }

    return points;
}

function updatePnLDisplay(json, netPnl, straddlePrice) {
    const availableMargin = json.available_margin ?? 0;
    document.getElementById("available-margin").textContent =
        `Margin: ₹${formatIndianNumber(availableMargin)}`;

    const margin = json.margin;
    const netPnlClass = netPnl === 0.0 ? 'neutral' : (netPnl > 0 ? 'positive' : 'negative');
    const marginRatio = margin !== 0 ? netPnl / margin : 0;
    const marginClass = marginRatio === 0.0 ? 'neutral' : (marginRatio > 0 ? 'positive' : 'negative');

    const netPnlFormatted = `₹${formatIndianNumber(netPnl)}`;
    const creditFormatted = json.Current_pos_credit !== null ?
        `₹${formatIndianNumber(json.Current_pos_credit)}` : '₹0.00';
    const pnlPercentFormatted = `${margin !== 0 ? (marginRatio * 100).toFixed(2) : '0.00'}%`;
    const deltaFormatted = (typeof delta === 'number' && Number.isFinite(delta)) ? delta.toFixed(2) : '-';

    document.getElementById('net-pnl').innerHTML = `
        <span class="pnl-group">
            <span class="label">Net P&amp;L:</span>
            <span id="pnl-combined" class="value ${netPnlClass}">${netPnlFormatted} 
                <span class="${marginClass}">(${pnlPercentFormatted})</span>
            </span>
        </span>
        <span class="credit-group">
            <span class="label">Current Strangle Price:</span>
            <span id="credit-value" class="value">${creditFormatted}</span>
        </span>
        <span class="delta-group">
            <span class="label">Delta:</span>
            <span id="delta-value" class="value">${deltaFormatted}</span>
        </span>
    `;
}

// Update the chart options for better real-time visualization
function renderPnlChart() {
    const chartContainer = document.querySelector('#pnl-chart');
    if (!chartContainer) return;

    if (chartContainer._resizeObserver) {
        chartContainer._resizeObserver.disconnect();
        chartContainer._resizeObserver = null;
    }
    chartContainer.innerHTML = '';

    const options = {
        chart: {
            type: 'line',
            height: '100%',
            sparkline: { enabled: false },
            parentHeightOffset: 0,
            offsetY: 0,
            redrawOnParentResize: true,
            zoom: { enabled: true, type: 'x', autoScaleYaxis: true },
            animations: {
                enabled: true,
                easing: 'easeinout',
                dynamicAnimation: {
                    speed: ANIMATION_DURATION
                }
            },
            toolbar: {
                show: true,
                tools: {
                    download: false,
                    selection: true,
                    zoom: true,
                    zoomin: true,
                    zoomout: true,
                    pan: true,
                    reset: true
                }
            },
            background: '#0b1220',
            foreColor: '#aeb7c6'
        },
        stroke: {
            width: [2.5, 2],
            curve: 'straight',
            dashArray: [0, 6]
        },
        markers: {
            size: 0,
            hover: { sizeOffset: 2 }
        },
        series: [
            {
                name: 'Net P&L',
                data: pnlData.pnlSeries,
                color: '#1f8bff'
            },
            {
                name: 'Straddle Price',
                data: pnlData.straddleSeries,
                color: '#21c55d'
            }
        ],
        xaxis: {
            type: 'datetime',
            labels: {
                datetimeUTC: false,
                format: 'HH:mm',
                style: { colors: '#8fa2c1' }
            },
            title: {
                text: 'Time',
                style: { color: '#8fa2c1' }
            }
        },
        yaxis: [
            {
                seriesName: 'Straddle Price',
                title: { text: 'Straddle Price (₹)', style: { color: '#21c55d' } },
                labels: {
                    style: { colors: '#8fa2c1' },
                    formatter: val => val != null ? val.toFixed(2) : ''
                },
                tickAmount: 6,
                forceNiceScale: true
            },
            {
                seriesName: 'Net P&L',
                opposite: true,
                title: { text: 'Net P&L (₹)', style: { color: '#1f8bff' } },
                labels: {
                    style: { colors: '#8fa2c1' },
                    formatter: val => val != null ? val.toFixed(2) : ''
                },
                tickAmount: 6,
                forceNiceScale: true
            }
        ],
        plotOptions: {
            line: {
                isSlopeChart: false
            }
        },
        grid: {
            borderColor: '#223049',
            strokeDashArray: 3,
            padding: {
                top: 0,
                right: 16,
                bottom: 0,
                left: 8
            }
        },
        tooltip: {
            theme: 'dark',
            shared: true,
            x: { format: 'HH:mm:ss' }
        },
        annotations: {
            points: buildLatestAnnotations()
        },
        legend: {
            position: 'top',
            horizontalAlign: 'center',
            labels: { colors: '#d6e0f0' }
        }
    };

    const chart = new ApexCharts(chartContainer, options);
    chart.render().then(() => {
        requestAnimationFrame(() => chart.updateOptions({}));
        if (typeof ResizeObserver !== 'undefined') {
            const resizeObserver = new ResizeObserver(() => {
                requestAnimationFrame(() => chart.updateOptions({}));
            });
            resizeObserver.observe(chartContainer);
            chartContainer._resizeObserver = resizeObserver;
        }
    });
    pnlChart = chart;
}

// Update the clear chart function to also clear localStorage
function clearChartData() {
    localStorage.removeItem('pnlData_v2');
    pnlData.pnlSeries = [];
    pnlData.straddleSeries = [];
    pnlChart.updateSeries([
        { name: 'Net P&L', data: [] },
        { name: 'Straddle Price', data: [] }
    ]);
    pnlChart.updateOptions({
        annotations: { points: [] }
    }, false, false);
    console.log("Chart data cleared.");
}

function exportChartData() {
    let csvContent = "data:text/csv;charset=utf-8,Time,Net P&L,Straddle Price\n";
    pnlData.pnlSeries.forEach((point, i) => {
        const time = new Date(point[0]).toISOString();
        const pnl = point[1];
        const straddle = pnlData.straddleSeries[i]?.[1] ?? '';
        csvContent += `${time},${pnl},${straddle}\n`;
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "pnl_chart_data.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function formatIndianNumber(x) {
    const value = Number.isFinite(Number(x)) ? Number(x) : 0;
    const parts = value.toFixed(2).split('.');
    let num = parts[0];
    let lastThree = num.substring(num.length - 3);
    let otherNumbers = num.substring(0, num.length - 3);
    if (otherNumbers !== '')
        lastThree = ',' + lastThree;
    let formatted = otherNumbers.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + lastThree;
    return formatted + '.' + parts[1];
}

function showToast(title, message, type = 'success', durationMs = 2500) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type === 'error' ? 'error' : ''}`;
    toast.innerHTML = `
        <div class="toast-bar"></div>
        <div>
            <div class="toast-title">${title}</div>
            <div class="toast-message">${message}</div>
        </div>
        <button class="toast-close" aria-label="Dismiss">×</button>
    `;

    container.appendChild(toast);
    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => toast.remove());

    requestAnimationFrame(() => toast.classList.add('show'));

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 200);
    }, durationMs);
}

async function triggerManualExit() {
    const exitButton = document.getElementById('manual-exit-btn');
    if (!exitButton) return;

    if (exitButton.disabled) return;
    exitButton.disabled = true;

    try {
        const response = await fetch('/manual_exit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const payload = await response.json();

        if (!response.ok) {
            throw new Error(payload.message || 'Failed to start manual exit');
        }
        showToast('Complete', payload.message || 'Manual exit started');
    } catch (error) {
        console.error('Error triggering manual exit:', error);
        showToast('Error', error.message || 'Error triggering manual exit', 'error', 3000);
    } finally {
        exitButton.disabled = false;
    }
}

async function triggerManualStoploss() {
    const slButton = document.getElementById('manual-sl-btn');
    if (!slButton) return;

    if (slButton.disabled) return;
    slButton.disabled = true;

    try {
        const response = await fetch('/manual_stoploss', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const payload = await response.json();

        if (!response.ok) {
            throw new Error(payload.message || 'Failed to start manual stoploss');
        }
        showToast('Complete', payload.message || 'Manual stoploss started');
    } catch (error) {
        console.error('Error triggering manual stoploss:', error);
        showToast('Error', error.message || 'Error triggering manual stoploss', 'error', 3000);
    } finally {
        slButton.disabled = false;
    }
}

async function triggerManualCancelSL() {
    const cancelButton = document.getElementById('cancel-sl-btn');
    if (!cancelButton) return;

    if (cancelButton.disabled) return;
    cancelButton.disabled = true;

    try {
        const response = await fetch('/manual_cancel_sl', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const payload = await response.json();

        if (!response.ok) {
            throw new Error(payload.message || 'Failed to cancel SL orders');
        }
        showToast('Complete', payload.message || 'Manual SL cancel started');
    } catch (error) {
        console.error('Error cancelling SL orders:', error);
        showToast('Error', error.message || 'Error cancelling SL orders', 'error', 3000);
    } finally {
        cancelButton.disabled = false;
    }
}

function renderOpenOptionPositions() {
    const container = document.getElementById('shift-legs-list');
    if (!container) return;

    // Preserve checked state across re-renders
    const prevState = {};
    container.querySelectorAll('.shift-leg-item').forEach(item => {
        const cb = item.querySelector('input[type="checkbox"]');
        if (cb) prevState[cb.value] = {
            checked: cb.checked
        };
    });

    if (!Array.isArray(openOptionPositions) || openOptionPositions.length === 0) {
        container.innerHTML = `<div class="shift-empty">No open option legs found.</div>`;
        return;
    }

    const rows = openOptionPositions.map((leg) => {
        const key = `${leg.exchange}::${leg.tradingsymbol}`;
        const prev = prevState[key] || {};
        const checked = prev.checked ? 'checked' : '';
        const currentQty = Math.abs(Number(leg.quantity || 0));
        const isShort = String(leg.side || '').toUpperCase() === 'SHORT';
        const sideClass = isShort ? 'short' : 'long';
        const sideLabel = isShort ? 'SHORT' : 'LONG';

        return `
            <div class="shift-leg-item">
                <input
                    type="checkbox"
                    value="${escapeHtml(key)}"
                    data-symbol="${escapeHtml(leg.tradingsymbol)}"
                    data-exchange="${escapeHtml(leg.exchange)}"
                    data-product="${escapeHtml(leg.product || '')}"
                    data-current-qty="${currentQty}"
                    ${checked}
                />
                <span class="shift-leg-symbol" title="${escapeHtml(leg.tradingsymbol)}">
                    ${escapeHtml(leg.tradingsymbol)}
                </span>
                <span class="shift-leg-side ${sideClass}">${sideLabel}</span>
                <span class="shift-leg-qty-label">×${currentQty}</span>
            </div>
        `;
    });

    container.innerHTML = rows.join('');
    container.querySelectorAll('.shift-leg-item').forEach((item) => {
        item.addEventListener('click', (event) => {
            if (event.target && event.target.closest('input[type="checkbox"]')) return;
            const checkbox = item.querySelector('input[type="checkbox"]');
            if (!checkbox) return;
            checkbox.checked = !checkbox.checked;
            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
        });
    });
}

async function fetchOpenOptionPositions() {
    try {
        const response = await fetch('/open_option_positions');
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.message || 'Failed to load open positions');
        }
        openOptionPositions = Array.isArray(payload.positions) ? payload.positions : [];
        renderOpenOptionPositions();
    } catch (error) {
        console.error('Error loading open option positions:', error);
        const container = document.getElementById('shift-legs-list');
        if (container) {
            container.innerHTML = `<div class="shift-empty">${escapeHtml(error.message || 'Error loading open positions')}</div>`;
        }
    }
}

function getShiftCount() {
    const countInput = document.getElementById('shift-count-input');
    if (!countInput) return null;
    const parsed = Number.parseInt(countInput.value, 10);
    if (!Number.isInteger(parsed) || parsed <= 0) {
        return null;
    }
    return parsed;
}

function getSelectedLegsFromList() {
    const listContainer = document.getElementById('shift-legs-list');
    if (!listContainer) return [];
    const checked = Array.from(listContainer.querySelectorAll('input[type="checkbox"]:checked'));
    return checked.map((el) => ({
        element: el,
        tradingsymbol: el.dataset.symbol,
        exchange: el.dataset.exchange,
        product: el.dataset.product || undefined,
        currentQty: Number(el.dataset.currentQty || 0),
    }));
}

function getGlobalNewQtyIfEnabled() {
    const useQtyCheckbox = document.getElementById('shift-use-qty');
    const qtyInput = document.getElementById('shift-qty-input');
    if (!useQtyCheckbox || !qtyInput || !useQtyCheckbox.checked) {
        return null;
    }
    const newQty = Number.parseInt(qtyInput.value, 10);
    if (!Number.isInteger(newQty) || newQty <= 0) {
        return null;
    }
    return newQty;
}

async function exitSelectedLegs() {
    const nearBtn = document.getElementById('shift-near-btn');
    const awayBtn = document.getElementById('shift-away-btn');
    const exitSelectedBtn = document.getElementById('shift-exit-selected-btn');
    if (!nearBtn || !awayBtn || !exitSelectedBtn) return;
    if (nearBtn.disabled || awayBtn.disabled) return;

    const selectedLegs = getSelectedLegsFromList();
    if (selectedLegs.length === 0) {
        showToast('Error', 'Select at least one leg to exit', 'error', 2800);
        return;
    }

    nearBtn.disabled = true;
    awayBtn.disabled = true;
    exitSelectedBtn.disabled = true;
    try {
        const response = await fetch('/exit_selected_legs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                legs: selectedLegs.map((leg) => ({
                    tradingsymbol: leg.tradingsymbol,
                    exchange: leg.exchange,
                    product: leg.product,
                }))
            })
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.message || 'Exit selected legs failed');
        }
        showToast('Complete', payload.message || 'Selected legs exited', 'success', 3500);
        await fetchOpenOptionPositions();
        await fetchOptionData();
        await fetchPnl();
    } catch (error) {
        console.error('Error exiting selected legs:', error);
        showToast('Error', error.message || 'Exit selected legs failed', 'error', 3200);
    } finally {
        nearBtn.disabled = false;
        awayBtn.disabled = false;
        exitSelectedBtn.disabled = false;
    }
}

async function triggerShiftLegs(direction) {
    const nearBtn = document.getElementById('shift-near-btn');
    const awayBtn = document.getElementById('shift-away-btn');
    const exitSelectedBtn = document.getElementById('shift-exit-selected-btn');
    if (!nearBtn || !awayBtn || !exitSelectedBtn) return;
    if (nearBtn.disabled || awayBtn.disabled) return;

    const selectedLegs = getSelectedLegsFromList();
    if (selectedLegs.length === 0) {
        showToast('Error', 'Select at least one leg to shift', 'error', 2800);
        return;
    }

    const count = getShiftCount();
    if (count === null) {
        showToast('Error', 'Strikes must be a positive integer', 'error', 2800);
        return;
    }
    const globalNewQty = getGlobalNewQtyIfEnabled();
    const useQtyCheckbox = document.getElementById('shift-use-qty');
    if (useQtyCheckbox && useQtyCheckbox.checked && globalNewQty === null) {
        showToast('Error', 'Qty must be a positive integer', 'error', 2800);
        return;
    }
    const shift = direction === 'near' ? -count : count;

    const legs = selectedLegs.map((leg) => ({
        tradingsymbol: leg.tradingsymbol,
        exchange: leg.exchange,
        product: leg.product,
        ...(globalNewQty !== null && { new_qty: globalNewQty }),
    }));

    nearBtn.disabled = true;
    awayBtn.disabled = true;
    exitSelectedBtn.disabled = true;
    try {
        const response = await fetch('/shift_legs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ legs, shift })
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.message || 'Leg shift failed');
        }

        const details = payload.details || {};
        const failures = Array.isArray(details.results)
            ? details.results.filter((item) => item.status === 'failed')
            : [];
        let message = payload.message || 'Leg shift complete';
        if (failures.length > 0) {
            const first = failures[0];
            message += ` | First error: ${first.old_symbol || 'leg'} - ${first.error || 'unknown error'}`;
        }
        showToast('Complete', message, failures.length > 0 ? 'error' : 'success', 4000);

        await fetchOpenOptionPositions();
        await fetchOptionData();
        await fetchPnl();
    } catch (error) {
        console.error('Error shifting legs:', error);
        showToast('Error', error.message || 'Error shifting legs', 'error', 3200);
    } finally {
        nearBtn.disabled = false;
        awayBtn.disabled = false;
        exitSelectedBtn.disabled = false;
    }
}

async function loadIndexOptions() {
    const indexSelect = document.getElementById('index-select');
    if (!indexSelect) return;

    try {
        const response = await fetch('/indices');
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || 'Failed to load index options');
        }

        const available = Array.isArray(payload.available) ? payload.available : [];
        if (available.length > 0) {
            indexSelect.innerHTML = available
                .map(indexName => `<option value="${indexName}">${indexName.toUpperCase()}</option>`)
                .join('');
        }
        currentSelectedIndex = String(payload.selected || 'nifty').toLowerCase();
        indexSelect.value = currentSelectedIndex;
    } catch (error) {
        console.error('Error loading index options:', error);
        showToast('Error', error.message || 'Could not load index options', 'error', 3000);
    }
}

async function handleIndexChange(event) {
    const indexSelect = event.target;
    const requestedIndex = String(indexSelect.value || '').toLowerCase();
    if (!requestedIndex || requestedIndex === currentSelectedIndex) return;

    const previousIndex = currentSelectedIndex;
    indexSelect.disabled = true;
    try {
        const response = await fetch('/set_index', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ index: requestedIndex })
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.message || 'Failed to switch index');
        }
        currentSelectedIndex = String(payload.selected || requestedIndex).toLowerCase();
        indexSelect.value = currentSelectedIndex;
        showToast('Complete', payload.message || 'Index switched');
        fetchOptionData();
    } catch (error) {
        console.error('Error switching index:', error);
        indexSelect.value = previousIndex;
        showToast('Error', error.message || 'Could not switch index', 'error', 3000);
    } finally {
        indexSelect.disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const exitButton = document.getElementById('manual-exit-btn');
    if (exitButton) {
        exitButton.addEventListener('click', triggerManualExit);
    }
    const slButton = document.getElementById('manual-sl-btn');
    if (slButton) {
        slButton.addEventListener('click', triggerManualStoploss);
    }
    const cancelSlButton = document.getElementById('cancel-sl-btn');
    if (cancelSlButton) {
        cancelSlButton.addEventListener('click', triggerManualCancelSL);
    }
    const shiftNearButton = document.getElementById('shift-near-btn');
    if (shiftNearButton) {
        shiftNearButton.addEventListener('click', () => triggerShiftLegs('near'));
    }
    const shiftAwayButton = document.getElementById('shift-away-btn');
    if (shiftAwayButton) {
        shiftAwayButton.addEventListener('click', () => triggerShiftLegs('away'));
    }
    const shiftExitSelectedButton = document.getElementById('shift-exit-selected-btn');
    if (shiftExitSelectedButton) {
        shiftExitSelectedButton.addEventListener('click', exitSelectedLegs);
    }
    const useQtyCheckbox = document.getElementById('shift-use-qty');
    const shiftQtyInput = document.getElementById('shift-qty-input');
    if (useQtyCheckbox && shiftQtyInput) {
        const syncQtyEnabledState = () => {
            shiftQtyInput.disabled = !useQtyCheckbox.checked;
        };
        useQtyCheckbox.addEventListener('change', syncQtyEnabledState);
        syncQtyEnabledState();
    }
    const indexSelect = document.getElementById('index-select');
    if (indexSelect) {
        indexSelect.addEventListener('change', handleIndexChange);
        loadIndexOptions();
    }
    initializePanelSplitter();
    initializeCockpitControls();

    initializeChart();
    setTimeout(() => { if (pnlChart) pnlChart.updateOptions({}); }, 150);
    fetchOptionData();
    fetchPnl();
    fetchOpenOptionPositions();
    setInterval(fetchOptionData, POLLING_INTERVAL);
    setInterval(fetchPnl, POLLING_INTERVAL);
    setInterval(fetchOpenOptionPositions, 5000);
});
