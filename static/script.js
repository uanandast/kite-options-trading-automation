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

function formatChange(val) {
    if (val > 0) return `<span class="positive">+${val}</span>`;
    if (val < 0) return `<span class="negative">${val}</span>`;
    return `<span class="neutral">${val}</span>`;
}

function renderRecommendation(legs, net_delta, strangle_credit, future_price, skew) {
    let html = `<div class="recommendation-title"><h2 class="recommendation-title">Iron Condor Recommendation</h2></div>`;
    html += `<table class="recommendation-table" border="1">
        <tr><th>Leg</th><th>Strike</th><th>Type</th><th>LTP</th><th>Delta</th></tr>`;

    if (!legs || typeof legs !== 'object') {
        console.warn("Invalid or missing legs data:", legs);
        html += `<tr><td colspan="5">No legs data available.</td></tr></table>`;
        return html;
    }


    const orderedLegs = ['hedge_pe', 'short_pe', 'short_ce', 'hedge_ce'];
    orderedLegs.forEach(leg => {
        const data = legs[leg];
        if (!data) return;  // skip if data is missing
        html += `<tr>
            <td>${leg.replace('_', ' ').toUpperCase()}</td>
            <td>${data.strike}</td>
            <td>${data.type}</td>
            <td>₹${data.ltp}</td>
            <td>${data.delta.toFixed(2)}</td>
        </tr>`;
    });
    html += `</table>`;
    html += `
     <div class="metrics-row">
      <div class="metric">
        <span class="label">Net Delta:</span>
        <span class="value"><strong>${net_delta !== undefined && net_delta !== null ? net_delta.toFixed(3) : '-'}</strong></span>
      </div>
      <div class="metric">
        <span class="label">Straddle Price:</span>
        <span class="value"><strong>₹${strangle_credit !== undefined && strangle_credit !== null ? formatIndianNumber(strangle_credit) : '-'}</strong></span>
      </div>
      <div class="metric">
        <span class="label">Synth Fut Price:</span>
        <span class="value"><strong>₹${future_price !== undefined && future_price !== null ? formatIndianNumber(future_price) : '-'}</strong></span>
      </div>
      <div class="metric">
        <span class="label">Skew:</span>
        <span class="value"><strong>${skew !== undefined && skew !== null ? skew.toFixed(2) : '-'}</strong></span>
      </div>
    </div>
  `;
    return html;
}


function updateSpotDisplay(spotPrice, previousClose) {
    const spotValueEl = document.getElementById('spot-value');
    const spotChangeEl = document.getElementById('spot-change');
    const container = document.getElementById('spot-price');

    // Calculate point and percent change
    const pointChange = spotPrice - previousClose;
    const percentChange = (pointChange / previousClose) * 100;
    const isPositive = pointChange >= 0;

    // Update display
    spotValueEl.textContent = spotPrice.toFixed(2);
    const sign = isPositive ? "+" : "";
    spotChangeEl.textContent = `${sign}${pointChange.toFixed(2)} (${sign}${percentChange.toFixed(2)}%)`;

    // Update color
    container.className = "price " + (isPositive ? "positive" : "negative");
}





// Polling-based fetching of option data from Flask endpoint
async function fetchOptionData() {
    try {
        const res = await fetch('/option_data');
        const json = await res.json();


        console.log(`Fetched option data at ${new Date().toISOString()}:`, json);

        const chain = json.chain || [];
        straddlePriceFromSocket = json.strangle_credit ?? null;
        future_price = json.future_price ?? null;
        skew = json.skew ?? null;
        delta = json.delta ?? null;


        spot_price = json.spot_price ?? null;
        previous_close = json.previous_close ?? null;
        if (json.selected_index) {
            currentSelectedIndex = String(json.selected_index).toLowerCase();
            const indexSelect = document.getElementById('index-select');
            if (indexSelect && !indexSelect.disabled && indexSelect.value !== currentSelectedIndex) {
                indexSelect.value = currentSelectedIndex;
            }
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

        const strikes = {};
        chain.forEach(row => {
            if (!strikes[row.strike]) strikes[row.strike] = {};
            strikes[row.strike][row.type] = row;
        });

        let html = `
            <table>
                <thead>
                    <tr>
                        <th colspan="6" class="call-header">CALLS</th>
                        <th class="strike">Strike</th>
                        <th colspan="6" class="put-header">PUTS</th>
                    </tr>
                    <tr>
                        <th>Delta</th>
                        <th>OI Chg%</th>
                        <th>OI-lakh</th>
                        <th>OI</th>
                        <th>LTP(chg%)</th>
                        <th>IV(chg)</th>
                        <th class="strike"></th>
                        <th>IV(chg)</th>
                        <th>LTP(chg%)</th>
                        <th>OI</th>
                        <th>OI-lakh</th>
                        <th>OI Chg%</th>
                        <th>Delta</th>
                    </tr>
                </thead>
                <tbody>
        `;
        const sortedStrikes = Object.keys(strikes).map(Number).sort((a, b) => a - b);
        let minDiff = Infinity;
        let atmStrike = null;
        if (typeof spot_price === 'number') {
            sortedStrikes.forEach(strike => {
                const diff = Math.abs(strike - spot_price);
                if (diff < minDiff) {
                    minDiff = diff;
                    atmStrike = strike;
                }
            });
        }

        sortedStrikes.forEach(strike => {
            const ce = strikes[strike]['CE'] || {};
            const pe = strikes[strike]['PE'] || {};
            const isAtm = (strike === atmStrike);
            const rowClass = isAtm ? 'atm-row' : '';
            const strikeClass = isAtm ? 'strike atm-strike' : 'strike';
            
            html += `
                <tr class="${rowClass}">
                    <td class="calls small">${ce.delta !== undefined ? ce.delta.toFixed(2) : ''}</td>
                    <td class="calls small">${ce.oi_chg_pct !== undefined ? formatChange(ce.oi_chg_pct) : ''}</td>
                    <td class="calls small">${ce.oi_lakh !== undefined ? ce.oi_lakh : ''}</td>
                    <td class="calls small">${ce.oi !== undefined ? (ce.oi / 100000).toFixed(2) + ' L' : ''}</td>
                    <td class="calls small">${ce.ltp !== undefined ? `₹${ce.ltp} ${ce.ltp_chg_pct !== undefined ? '(' + formatChange(ce.ltp_chg_pct) + '%)' : ''}` : ''}</td>
                    <td class="calls small">${ce.iv !== undefined ? ce.iv.toFixed(2) : ''} ${ce.iv_chg !== undefined ? '(' + formatChange(ce.iv_chg) + ')' : ''}</td>
                    <td class="${strikeClass}">${strike}</td>
                    <td class="puts small">${pe.iv !== undefined ? pe.iv.toFixed(2) : ''} ${pe.iv_chg !== undefined ? '(' + formatChange(pe.iv_chg) + ')' : ''}</td>
                    <td class="puts small">${pe.ltp !== undefined ? `₹${pe.ltp} ${pe.ltp_chg_pct !== undefined ? '(' + formatChange(pe.ltp_chg_pct) + '%)' : ''}` : ''}</td>
                    <td class="puts small">${pe.oi !== undefined ? (pe.oi / 100000).toFixed(2) + ' L' : ''}</td>
                    <td class="puts small">${pe.oi_lakh !== undefined ? pe.oi_lakh : ''}</td>
                    <td class="puts small">${pe.oi_chg_pct !== undefined ? formatChange(pe.oi_chg_pct) : ''}</td>
                    <td class="puts small">${pe.delta !== undefined ? pe.delta.toFixed(2) : ''}</td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        document.getElementById("option-chain-table").innerHTML = html;

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
    const options = {
        chart: {
            type: 'line',
            height: 400,
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
                    formatter: val => val.toFixed(2)
                }
            },
            {
                seriesName: 'Net P&L',
                opposite: true,
                title: { text: 'Net P&L (₹)', style: { color: '#1f8bff' } },
                labels: {
                    style: { colors: '#8fa2c1' },
                    formatter: val => val.toFixed(2)
                }
            }
        ],
        grid: {
            borderColor: '#223049',
            strokeDashArray: 3
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

    const chartContainer = document.querySelector('#pnl-chart');
    chartContainer.innerHTML = '';
    const chart = new ApexCharts(chartContainer, options);
    chart.render();
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
    const indexSelect = document.getElementById('index-select');
    if (indexSelect) {
        indexSelect.addEventListener('change', handleIndexChange);
        loadIndexOptions();
    }
});

// Update the interval calls
setInterval(fetchOptionData, POLLING_INTERVAL);
fetchOptionData();
setInterval(fetchPnl, POLLING_INTERVAL);
initializeChart();
fetchPnl();
