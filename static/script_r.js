// Constants
const POLLING_INTERVAL = 1000; // 1 second
const CHART_UPDATE_INTERVAL = 1000; // 1 second
const MAX_DATA_POINTS = 3600; // 60 hours at 1 minute interval
const ANIMATION_DURATION = 350; // milliseconds

let straddlePriceFromSocket = 0;
let lastKnownStraddlePrice = 0;
let currentStraddlePrice = null;
let lastRenderedStraddlePrice = null;
let pendingChartUpdate = false;
let lastChartUpdate = Date.now();
let currentSelectedIndex = 'nifty';
let openOptionPositions = [];
let future_price = null;
let skew = null;
let delta = null;
let currentPosCredit = null;
let recommendationNetDelta = null;
const SPLITTER_STORAGE_KEY = 'dashboardSplitterWidth_v1';
let observedStraddleLow = null;
let observedStraddleHigh = null;
const STRIKE_STEP_BY_INDEX = {
    nifty: 50,
    sensex: 100,
    banknifty: 100
};
const INDEX_LOT_QTY = {
    nifty: 65,
    sensex: 20,
    banknifty: 30
};

function isValidNumber(value) {
    return typeof value === 'number' && Number.isFinite(value);
}

function formatRupeeCompact(value) {
    return Number.isFinite(value) ? `₹${formatIndianNumber(value).replace(/\.00$/, '')}` : '--';
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
    return html;
}


function updateSpotDisplay(spotPrice, previousClose) {
    const spotValueEl = document.getElementById('spot-value');
    const spotChangeEl = document.getElementById('spot-change');
    const container = document.getElementById('spot-price');
    if (!spotValueEl || !spotChangeEl || !container) return;

    // Calculate point and percent change
    const validSpot = isValidNumber(Number(spotPrice)) ? Number(spotPrice) : null;
    const validPrevClose = isValidNumber(Number(previousClose)) ? Number(previousClose) : null;

    if (validSpot === null || validPrevClose === null || validPrevClose === 0) {
        spotValueEl.textContent = validSpot !== null ? validSpot.toFixed(2) : '--';
        spotChangeEl.textContent = '(--%)';
        spotChangeEl.className = 'text-slate-400';
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
    spotChangeEl.className = isPositive ? 'text-emerald-400' : 'text-rose-500';
}

function normalizeLegRows(legs) {
    if (!legs || typeof legs !== 'object') return [];
    if (Array.isArray(legs)) return legs;

    const legMap = {
        hedge_pe: 'HEDGE PE',
        short_pe: 'SHORT PE',
        short_ce: 'SHORT CE',
        hedge_ce: 'HEDGE CE'
    };
    const orderedKeys = Object.keys(legMap);
    const mappedRows = orderedKeys
        .filter((key) => legs[key])
        .map((key) => {
            const value = legs[key];
            return {
                leg: legMap[key],
                strike: Number(value?.strike),
                type: value?.type || '-',
                ltp: Number(value?.ltp),
                delta: Number(value?.delta)
            };
        });

    // Include any extra leg keys from backend after known legMap rows.
    const extraRows = Object.entries(legs)
        .filter(([key]) => !orderedKeys.includes(key))
        .map(([key, value]) => ({
            leg: String(key).replace(/_/g, ' ').toUpperCase(),
            strike: Number(value?.strike),
            type: value?.type || '-',
            ltp: Number(value?.ltp),
            delta: Number(value?.delta)
        }));

    return [...mappedRows, ...extraRows];
}

function renderCompactLegsTable(legs) {
    const container = document.getElementById('legs-table');
    if (!container) return;

    const rows = normalizeLegRows(legs);
    if (rows.length === 0) {
        container.innerHTML = `<div class="border-b border-slate-900 py-1 text-xs text-slate-500">No legs data available</div>`;
        return;
    }

    container.innerHTML = rows.map((row) => {
        const strike = Number.isFinite(row.strike) ? row.strike.toLocaleString('en-IN') : '-';
        const ltp = Number.isFinite(row.ltp) ? row.ltp.toFixed(2) : '-';
        const deltaVal = Number.isFinite(row.delta) ? row.delta : null;
        const deltaClass = deltaVal !== null ? (deltaVal >= 0 ? 'text-emerald-400' : 'text-rose-500') : 'text-slate-400';
        const deltaText = deltaVal !== null ? `${deltaVal >= 0 ? '+' : ''}${deltaVal.toFixed(2)}` : '-';

        return `
            <div class="flex items-center border-b border-slate-900 py-0.5 text-xs">
                <span class="flex-1 text-slate-300">${escapeHtml(row.leg)}</span>
                <span class="w-16 text-right font-mono text-slate-200">${escapeHtml(strike)}</span>
                <span class="w-10 text-right font-mono text-slate-300">${escapeHtml(row.type)}</span>
                <span class="w-20 text-right font-mono text-slate-200">${escapeHtml(ltp)}</span>
                <span class="w-16 text-right font-mono ${deltaClass}">${escapeHtml(deltaText)}</span>
            </div>
        `;
    }).join('');
}

function syncShiftInputs() {
    const qtyVisible = document.getElementById('qty-input');
    const strikesVisible = document.getElementById('strikes-input');
    const qtyHidden = document.getElementById('shift-qty-input');
    const strikesHidden = document.getElementById('shift-count-input');
    if (!qtyVisible || !strikesVisible || !qtyHidden || !strikesHidden) return;

    qtyVisible.addEventListener('input', () => {
        qtyHidden.value = qtyVisible.value || '1';
    });
    strikesVisible.addEventListener('input', () => {
        strikesHidden.value = strikesVisible.value || '1';
    });
}

function getLotQtyForIndex(indexName = currentSelectedIndex) {
    const key = String(indexName || '').toLowerCase();
    if (key.includes('bank')) return INDEX_LOT_QTY.banknifty;
    if (key.includes('sensex')) return INDEX_LOT_QTY.sensex;
    if (key.includes('nifty')) return INDEX_LOT_QTY.nifty;
    return INDEX_LOT_QTY.nifty;
}

function normalizeQtyToLot(rawValue, lotSize) {
    const parsed = Number.parseInt(String(rawValue ?? '').trim(), 10);
    if (!Number.isInteger(parsed) || parsed <= 0) return lotSize;
    const rounded = Math.max(lotSize, Math.round(parsed / lotSize) * lotSize);
    return rounded;
}

function applyIndexQtyRules(indexName = currentSelectedIndex, forceReset = false) {
    const lotSize = getLotQtyForIndex(indexName);
    const qtyVisible = document.getElementById('qty-input');
    const qtyHidden = document.getElementById('shift-qty-input');
    if (!qtyVisible || !qtyHidden) return;

    qtyVisible.step = String(lotSize);
    qtyVisible.min = String(lotSize);

    const nextValue = forceReset
        ? lotSize
        : normalizeQtyToLot(qtyVisible.value || qtyHidden.value, lotSize);

    qtyVisible.value = String(nextValue);
    qtyHidden.value = String(nextValue);
}

function syncTopBarFromStraddle(priceNum) {
    if (!Number.isFinite(priceNum)) return;
    if (Number.isFinite(lastRenderedStraddlePrice) && Math.abs(lastRenderedStraddlePrice - priceNum) < 0.01) {
        return;
    }
    lastRenderedStraddlePrice = priceNum;
    currentStraddlePrice = priceNum;
    observedStraddleLow = observedStraddleLow === null ? priceNum : Math.min(observedStraddleLow, priceNum);
    observedStraddleHigh = observedStraddleHigh === null ? priceNum : Math.max(observedStraddleHigh, priceNum);

    const strangleEl = document.getElementById('status-strangle-price');
    const lowInlineEl = document.getElementById('top-straddle-low-inline');
    const highInlineEl = document.getElementById('top-straddle-high-inline');
    if (strangleEl) strangleEl.textContent = `₹${formatIndianNumber(priceNum).replace(/\.00$/, '')}`;
    if (lowInlineEl) lowInlineEl.textContent = `₹${formatIndianNumber(observedStraddleLow).replace(/\.00$/, '')}`;
    if (highInlineEl) highInlineEl.textContent = `₹${formatIndianNumber(observedStraddleHigh).replace(/\.00$/, '')}`;
}

function resetIndexScopedStraddleStats() {
    observedStraddleLow = null;
    observedStraddleHigh = null;
    currentStraddlePrice = null;
    lastRenderedStraddlePrice = null;
    lastKnownStraddlePrice = 0;

    const lowInlineEl = document.getElementById('top-straddle-low-inline');
    const highInlineEl = document.getElementById('top-straddle-high-inline');
    const strangleEl = document.getElementById('status-strangle-price');
    const statusStrangleEl = document.getElementById('status-left-strangle');

    if (lowInlineEl) lowInlineEl.textContent = '--';
    if (highInlineEl) highInlineEl.textContent = '--';
    if (strangleEl) strangleEl.textContent = '--';
    if (statusStrangleEl) statusStrangleEl.textContent = '--';
}

function updateTopTimestamp() {
    const updatedEl = document.getElementById('top-updated-time');
    if (!updatedEl) return;
    updatedEl.textContent = new Date().toLocaleTimeString('en-IN', { hour12: false });
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
    const priceNum = Number.isFinite(currentStraddlePrice) ? currentStraddlePrice : null;
    const lowNum = observedStraddleLow;
    const highNum = observedStraddleHigh;
    const updated = new Date().toLocaleString('en-IN', { hour12: false });

    setVitalValue('vital-card-symbol', 'vital-symbol', symbol, true);
    setVitalValue('vital-card-spot', 'vital-spot', spot, spot !== '--');
    setVitalValue('vital-card-synth', 'vital-synth', synthFutNum !== null ? `₹${formatIndianNumber(synthFutNum)}` : '--', synthFutNum !== null);
    setVitalValue('vital-card-atm', 'vital-atm', atmStrike !== null ? String(atmStrike) : '--', atmStrike !== null);
    setVitalValue('vital-card-price', 'vital-price', priceNum !== null ? `₹${formatIndianNumber(priceNum)}` : '--', priceNum !== null);
    setVitalValue('vital-card-low', 'vital-low', lowNum !== null ? `₹${formatIndianNumber(lowNum)}` : '--', lowNum !== null);
    setVitalValue('vital-card-high', 'vital-high', highNum !== null ? `₹${formatIndianNumber(highNum)}` : '--', highNum !== null);
    setVitalValue('vital-card-updated', 'vital-updated', updated, true);

    const statusNetDeltaEl = document.getElementById('status-left-net-delta');
    const statusStrangleEl = document.getElementById('status-left-strangle');
    const statusCspEl = document.getElementById('status-left-csp');
    const statusDeltaEl = document.getElementById('status-left-delta');
    const statusSynthEl = document.getElementById('status-left-synth');
    const statusSynthBottomEl = document.getElementById('status-left-synth-bottom');
    const statusSkewEl = document.getElementById('status-left-skew');

    if (statusNetDeltaEl) {
        const visibleDelta = Number.isFinite(Number(recommendationNetDelta)) ? Number(recommendationNetDelta) : Number(json.net_delta);
        statusNetDeltaEl.textContent = Number.isFinite(visibleDelta) ? visibleDelta.toFixed(3) : '--';
        statusNetDeltaEl.classList.remove('text-emerald-400', 'text-rose-500', 'text-slate-300');
        if (!Number.isFinite(visibleDelta)) {
            statusNetDeltaEl.classList.add('text-slate-300');
        } else if (visibleDelta >= 0) {
            statusNetDeltaEl.classList.add('text-emerald-400');
        } else {
            statusNetDeltaEl.classList.add('text-rose-500');
        }
    }
    if (statusStrangleEl) {
        statusStrangleEl.textContent = formatRupeeCompact(priceNum);
    }
    if (statusCspEl) {
        statusCspEl.textContent = formatRupeeCompact(currentPosCredit);
    }
    if (statusDeltaEl) {
        const liveDelta = Number.isFinite(Number(delta)) ? Number(delta) : null;
        statusDeltaEl.textContent = liveDelta !== null ? liveDelta.toFixed(3) : '--';
        statusDeltaEl.classList.remove('text-emerald-400', 'text-rose-500', 'text-slate-300');
        if (liveDelta === null) {
            statusDeltaEl.classList.add('text-slate-300');
        } else if (liveDelta >= 0) {
            statusDeltaEl.classList.add('text-emerald-400');
        } else {
            statusDeltaEl.classList.add('text-rose-500');
        }
    }
    if (statusSynthEl) {
        statusSynthEl.textContent = synthFutNum !== null ? `₹${formatIndianNumber(synthFutNum).replace(/\.00$/, '')}` : '--';
    }
    if (statusSynthBottomEl) {
        statusSynthBottomEl.textContent = synthFutNum !== null ? `₹${formatIndianNumber(synthFutNum).replace(/\.00$/, '')}` : '--';
    }
    if (statusSkewEl) {
        const skewNum = Number(json.skew);
        statusSkewEl.textContent = Number.isFinite(skewNum) ? skewNum.toFixed(2) : '--';
    }
    const topDeltaEl = document.getElementById('top-position-delta');
    if (topDeltaEl) {
        const visibleDelta = Number.isFinite(Number(delta)) ? Number(delta) : null;
        topDeltaEl.textContent = Number.isFinite(visibleDelta) ? visibleDelta.toFixed(3) : '--';
        topDeltaEl.classList.remove('text-emerald-400', 'text-rose-500', 'text-slate-300');
        if (!Number.isFinite(visibleDelta)) {
            topDeltaEl.classList.add('text-slate-300');
        } else if (visibleDelta >= 0) {
            topDeltaEl.classList.add('text-emerald-400');
        } else {
            topDeltaEl.classList.add('text-rose-500');
        }
    }
    if (Number.isFinite(lowNum) || Number.isFinite(highNum)) {
        const lowInlineEl = document.getElementById('top-straddle-low-inline');
        const highInlineEl = document.getElementById('top-straddle-high-inline');
        if (lowInlineEl && Number.isFinite(lowNum)) lowInlineEl.textContent = formatRupeeCompact(lowNum);
        if (highInlineEl && Number.isFinite(highNum)) highInlineEl.textContent = formatRupeeCompact(highNum);
    }
    updateTopTimestamp();
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
    const liveCard = document.getElementById('live-pnl-card');
    const strategyCard = document.getElementById('strategy-card');
    if (!mainContent || !splitter) return;

    const savedWidth = Number(localStorage.getItem(SPLITTER_STORAGE_KEY));
    const applyPaneWidth = (percent) => {
        if (!liveCard || !strategyCard) return;
        liveCard.style.width = `${percent}%`;
        strategyCard.style.width = `${100 - percent}%`;
    };
    if (isValidNumber(savedWidth) && savedWidth >= 50 && savedWidth <= 80) {
        applyPaneWidth(savedWidth);
    }

    let dragging = false;

    const onMove = (clientX) => {
        const rect = mainContent.getBoundingClientRect();
        const rawPercent = ((clientX - rect.left) / rect.width) * 100;
        const clampedPercent = Math.min(80, Math.max(50, rawPercent));
        applyPaneWidth(clampedPercent);
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
        // app.py mapping:
        // - net_delta: from recommendation position
        // - delta/Delta: from current position
        const currentPosDelta = Number(json.Delta ?? json.delta);
        if (Number.isFinite(currentPosDelta)) {
            delta = currentPosDelta;
        }
        const netDeltaFromRecommendation = Number(json.net_delta);
        if (Number.isFinite(netDeltaFromRecommendation)) {
            recommendationNetDelta = netDeltaFromRecommendation;
        }


        const spotPrice = Number(json.spot_price);
        const previousClose = Number(json.previous_close);
        if (json.selected_index) {
            const incomingIndex = String(json.selected_index).toLowerCase();
            if (incomingIndex !== currentSelectedIndex) {
                currentSelectedIndex = incomingIndex;
                resetIndexScopedStraddleStats();
            } else {
                currentSelectedIndex = incomingIndex;
            }
        }
        updateSpotDisplay(json.spot_price, json.previous_close);
        const symbolEl = document.getElementById('symbol');
        if (symbolEl) symbolEl.textContent = json.symbol || "Index";
        renderCompactLegsTable(json.legs);
        const recommendationEl = document.getElementById("recommendation");
        if (recommendationEl) {
            recommendationEl.innerHTML = renderRecommendation(
            json.legs,
            json.net_delta,
            json.strangle_credit,
            json.future_price,
            json.skew
        );
        }

        const strikeStep = STRIKE_STEP_BY_INDEX[currentSelectedIndex] || null;
        const atmStrike = (strikeStep && Number.isFinite(spotPrice))
            ? Math.round(spotPrice / strikeStep) * strikeStep
            : null;
        updateTopCockpit(json, atmStrike);
        updateSpotDisplay(spotPrice, previousClose);
        // Keep top-bar price stable from position PnL feed to avoid flicker.

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
        const chartApiStraddle = Number(json.straddle_price);
        // app.py /pnl mapping:
        // - Current_pos_credit: current position credit (CSP)
        const cspValue = Number(json.Current_pos_credit);
        if (Number.isFinite(cspValue)) {
            currentPosCredit = cspValue;
        }
        const positionDelta = Number(json.Delta ?? json.delta ?? json.Current_pos_delta ?? json.current_pos_delta ?? json.position_delta);
        const socketStraddle = Number(straddlePriceFromSocket);

        // Chart should reflect live strangle/straddle ticks.
        let chartStraddlePrice = Number.isFinite(chartApiStraddle) ? chartApiStraddle : null;
        if (!Number.isFinite(chartStraddlePrice)) {
            chartStraddlePrice = Number.isFinite(socketStraddle) ? socketStraddle : null;
        }
        if (Number.isFinite(chartStraddlePrice)) {
            lastKnownStraddlePrice = chartStraddlePrice;
        } else {
            chartStraddlePrice = lastKnownStraddlePrice;
        }

        // Use the same value used by chart for top/status Straddle display.
        const displayStraddlePrice = chartStraddlePrice;
        if (Number.isFinite(positionDelta)) {
            delta = positionDelta;
        }

        if (!Number.isFinite(netPnl) || !Number.isFinite(chartStraddlePrice)) {
            return;
        }

        syncTopBarFromStraddle(displayStraddlePrice);
        updateTopTimestamp();

        // Group points by minute for 1-minute historical data gap
        const tsMinute = Math.floor(ts / 60000) * 60000;

        if (pnlData.pnlSeries.length > 0 && pnlData.pnlSeries[pnlData.pnlSeries.length - 1][0] === tsMinute) {
            // Update current minute's point
            pnlData.pnlSeries[pnlData.pnlSeries.length - 1][1] = netPnl;
            pnlData.straddleSeries[pnlData.straddleSeries.length - 1][1] = chartStraddlePrice;
        } else {
            // New minute, add new point
            pnlData.pnlSeries.push([tsMinute, netPnl]);
            pnlData.straddleSeries.push([tsMinute, chartStraddlePrice]);
        }

        if (pnlData.pnlSeries.length > MAX_DATA_POINTS) {
            pnlData.pnlSeries = pnlData.pnlSeries.slice(-MAX_DATA_POINTS);
            pnlData.straddleSeries = pnlData.straddleSeries.slice(-MAX_DATA_POINTS);
        }

        saveToLocalStorage();
        updatePnLDisplay(json, netPnl, displayStraddlePrice);

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

function buildSparklinePath(values, width = 54, height = 20) {
    if (!Array.isArray(values) || values.length === 0) {
        return 'M1 15 L9 14 L17 10 L25 11 L33 7 L41 8 L53 3';
    }
    if (values.length === 1) {
        return `M1 ${height / 2} L${width - 1} ${height / 2}`;
    }

    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const stepX = (width - 2) / (values.length - 1);
    const points = values.map((value, index) => {
        const x = 1 + (index * stepX);
        const y = 2 + ((max - value) / range) * (height - 4);
        return `${x.toFixed(2)} ${y.toFixed(2)}`;
    });
    return `M${points.join(' L')}`;
}

function getDeltaTone(deltaValue) {
    if (!Number.isFinite(deltaValue)) return 'neutral';
    if (deltaValue > 0.05) return 'positive';
    if (deltaValue < -0.05) return 'negative';
    return 'neutral';
}

function updatePnLDisplay(json, netPnl, straddlePrice) {
    const availableMargin = json.available_margin ?? 0;
    const availableMarginEl = document.getElementById("available-margin");
    if (availableMarginEl) {
        availableMarginEl.textContent = `Margin: ₹${formatIndianNumber(availableMargin)}`;
    }

    const margin = json.margin;
    const marginRatio = margin !== 0 ? netPnl / margin : 0;
    const pnlPercent = margin !== 0 ? (marginRatio * 100) : 0;
    const pnlSign = netPnl >= 0 ? '+' : '-';
    const absPnl = Math.abs(netPnl);
    const netPnlFormatted = `${pnlSign}₹${formatIndianNumber(absPnl).replace(/\.00$/, '')}`;
    const pnlPercentFormatted = `${pnlSign}${Math.abs(pnlPercent).toFixed(1)}%`;
    const netPnlDisplay = `${netPnlFormatted} (${pnlPercentFormatted})`;
    const strangleDisplay = formatRupeeCompact(straddlePrice);
    const deltaValue = Number.isFinite(Number(delta)) ? Number(delta) : null;
    const deltaFormatted = deltaValue !== null ? deltaValue.toFixed(2) : '--';
    const deltaTone = getDeltaTone(deltaValue);
    const deltaOutlook = deltaTone === 'positive' ? 'Mild Bullish' : (deltaTone === 'negative' ? 'Mild Bearish' : 'Neutral');

    const pnlValueEl = document.getElementById('status-net-pnl-value');
    const pnlArrowEl = document.getElementById('status-pnl-arrow');
    const pnlTooltipEl = document.getElementById('status-pnl-tooltip');
    const strangleValueEl = document.getElementById('status-strangle-price');
    const strangleTooltipEl = document.getElementById('status-strangle-tooltip');
    const statusStrangleEl = document.getElementById('status-left-strangle');
    const statusCspEl = document.getElementById('status-left-csp');
    const statusDeltaEl = document.getElementById('status-left-delta');
    const deltaValueEl = document.getElementById('status-delta-value');
    const deltaTooltipEl = document.getElementById('status-delta-tooltip');
    const sparklineEl = document.getElementById('status-sparkline');
    const sparklinePathEl = document.getElementById('status-sparkline-path');

    if (pnlValueEl) {
        pnlValueEl.textContent = netPnlDisplay;
        pnlValueEl.classList.remove('positive', 'negative', 'text-emerald-400', 'text-rose-500');
        pnlValueEl.classList.add(netPnl >= 0 ? 'text-emerald-400' : 'text-rose-500');
    }
    if (pnlArrowEl) {
        pnlArrowEl.classList.remove('positive', 'negative');
        pnlArrowEl.classList.add(netPnl >= 0 ? 'positive' : 'negative');
    }
    if (pnlTooltipEl) {
        pnlTooltipEl.setAttribute('data-tooltip', `Net Profit/Loss: ${netPnlFormatted} (${pnlPercentFormatted})`);
    }
    if (strangleValueEl) {
        strangleValueEl.textContent = strangleDisplay;
    }
    if (statusStrangleEl) {
        statusStrangleEl.textContent = strangleDisplay;
    }
    if (statusCspEl) {
        statusCspEl.textContent = formatRupeeCompact(currentPosCredit);
    }
    if (statusDeltaEl) {
        statusDeltaEl.textContent = deltaFormatted === '--' ? '--' : Number(deltaValue).toFixed(3);
        statusDeltaEl.classList.remove('text-emerald-400', 'text-rose-500', 'text-slate-300');
        if (deltaValue === null) {
            statusDeltaEl.classList.add('text-slate-300');
        } else if (deltaValue >= 0) {
            statusDeltaEl.classList.add('text-emerald-400');
        } else {
            statusDeltaEl.classList.add('text-rose-500');
        }
    }
    if (strangleTooltipEl) {
        const tooltipPrice = Number.isFinite(straddlePrice) ? Math.round(straddlePrice) : 0;
        strangleTooltipEl.setAttribute('data-tooltip', `Current Strangle Price: ${tooltipPrice}`);
    }
    if (deltaValueEl) {
        deltaValueEl.textContent = deltaFormatted;
    }
    if (deltaTooltipEl) {
        deltaTooltipEl.setAttribute('data-tooltip', `Delta: ${deltaFormatted} (${deltaOutlook})`);
    }
    const statusNetDeltaEl = document.getElementById('status-left-net-delta');
    if (statusNetDeltaEl) {
        const netDeltaVal = Number.isFinite(Number(recommendationNetDelta)) ? Number(recommendationNetDelta) : null;
        statusNetDeltaEl.textContent = netDeltaVal === null ? '--' : netDeltaVal.toFixed(3);
        statusNetDeltaEl.classList.remove('text-emerald-400', 'text-rose-500', 'text-slate-300');
        if (netDeltaVal === null) {
            statusNetDeltaEl.classList.add('text-slate-300');
        } else if (netDeltaVal >= 0) {
            statusNetDeltaEl.classList.add('text-emerald-400');
        } else {
            statusNetDeltaEl.classList.add('text-rose-500');
        }
    }
    const topDeltaEl = document.getElementById('top-position-delta');
    if (topDeltaEl) {
        topDeltaEl.textContent = deltaFormatted === '--' ? '--' : Number(deltaValue).toFixed(3);
        topDeltaEl.classList.remove('text-emerald-400', 'text-rose-500', 'text-slate-300');
        if (deltaValue === null) {
            topDeltaEl.classList.add('text-slate-300');
        } else if (deltaValue >= 0) {
            topDeltaEl.classList.add('text-emerald-400');
        } else {
            topDeltaEl.classList.add('text-rose-500');
        }
    }
    if (sparklineEl && sparklinePathEl) {
        const recentPnl = pnlData.pnlSeries.slice(-7).map((point) => Number(point[1])).filter(Number.isFinite);
        const minPointsForSparkline = 4;
        const variationThreshold = 5;
        const hasEnoughPoints = recentPnl.length >= minPointsForSparkline;
        const hasVariation = hasEnoughPoints && (Math.max(...recentPnl) - Math.min(...recentPnl)) >= variationThreshold;

        if (hasVariation) {
            sparklinePathEl.setAttribute('d', buildSparklinePath(recentPnl));
            sparklineEl.classList.remove('positive', 'negative');
            sparklineEl.classList.add(netPnl >= 0 ? 'positive' : 'negative');
            sparklineEl.style.display = 'block';
        } else {
            sparklineEl.style.display = 'none';
        }
    }
}

// Update the chart options for better real-time visualization
function renderPnlChart() {
    const chartContainer = document.querySelector('#pnl-chart');
    if (!chartContainer || typeof ApexCharts === 'undefined') return;

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
            background: '#000000',
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
                top: 24,
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
    toast.className = `rounded-md border px-3 py-2 text-xs shadow-lg backdrop-blur ${
        type === 'error'
            ? 'border-rose-700 bg-rose-900/80 text-rose-100'
            : 'border-emerald-700 bg-emerald-900/80 text-emerald-100'
    }`;
    toast.innerHTML = `
        <div class="flex items-start justify-between gap-3">
            <div>
                <div class="font-semibold">${escapeHtml(title)}</div>
                <div>${escapeHtml(message)}</div>
            </div>
            <button class="toast-close text-slate-200/90 hover:text-white" aria-label="Dismiss">×</button>
        </div>
    `;

    container.appendChild(toast);
    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => toast.remove());

    setTimeout(() => {
        toast.remove();
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
        container.innerHTML = `<div class="rounded border border-slate-800 bg-slate-900 px-2 py-2 text-xs text-slate-400">No open option legs found.</div>`;
        return;
    }

    const parseLegDisplayParts = (tradingsymbol = '', exchange = '') => {
        const raw = String(tradingsymbol || '').toUpperCase();
        const knownPrefixes = ['BANKNIFTY', 'SENSEX', 'NIFTY'];
        const indexName = knownPrefixes.find((prefix) => raw.startsWith(prefix)) || String(exchange || '').toUpperCase() || 'INDEX';
        const typeMatch = raw.match(/(CE|PE)$/);
        const optionType = typeMatch ? typeMatch[1] : '--';
        const numericTail = raw
            .replace(indexName, '')
            .replace(/(CE|PE)$/, '')
            .replace(/\D/g, '');

        const strikeStep = STRIKE_STEP_BY_INDEX[String(indexName || '').toLowerCase()] || 100;
        const minStrikeByIndex = {
            NIFTY: 10000,
            BANKNIFTY: 20000,
            SENSEX: 30000
        };
        const maxStrikeByIndex = {
            NIFTY: 50000,
            BANKNIFTY: 90000,
            SENSEX: 120000
        };
        const minStrike = minStrikeByIndex[indexName] || 1000;
        const maxStrike = maxStrikeByIndex[indexName] || 200000;

        let strikeValue = null;
        for (let len = 4; len <= Math.min(7, numericTail.length); len += 1) {
            const suffix = numericTail.slice(-len);
            const candidate = Number.parseInt(suffix, 10);
            if (!Number.isFinite(candidate)) continue;
            if (candidate < minStrike || candidate > maxStrike) continue;
            if (candidate % strikeStep !== 0) continue;
            strikeValue = candidate;
            break;
        }
        if (!Number.isFinite(strikeValue) && numericTail.length > 0) {
            strikeValue = Number.parseInt(numericTail.slice(-5), 10);
        }

        return {
            indexName,
            strikeLabel: Number.isFinite(strikeValue) ? String(strikeValue) : '--',
            optionType
        };
    };

    const rows = openOptionPositions.map((leg) => {
        const key = `${leg.exchange}::${leg.tradingsymbol}`;
        const prev = prevState[key] || {};
        const checked = prev.checked ? 'checked' : '';
        const currentQty = Math.abs(Number(leg.quantity || 0));
        const isShort = String(leg.side || '').toUpperCase() === 'SHORT';
        const sideLabel = isShort ? 'SHORT' : 'LONG';
        const display = parseLegDisplayParts(leg.tradingsymbol, leg.exchange);

        return `
            <div class="shift-leg-item flex items-center gap-2 rounded border border-slate-800 bg-slate-900 px-2 py-1.5 text-xs">
                <input
                    type="checkbox"
                    class="h-3.5 w-3.5 accent-emerald-500"
                    value="${escapeHtml(key)}"
                    data-symbol="${escapeHtml(leg.tradingsymbol)}"
                    data-exchange="${escapeHtml(leg.exchange)}"
                    data-product="${escapeHtml(leg.product || '')}"
                    data-current-qty="${currentQty}"
                    ${checked}
                />
                <span class="shift-leg-symbol flex-1 truncate font-mono text-slate-200" title="${escapeHtml(leg.tradingsymbol)}">
                    ${escapeHtml(display.indexName)} | ${escapeHtml(display.strikeLabel)} | ${escapeHtml(display.optionType)}
                </span>
                <span class="shift-leg-side rounded px-1.5 py-0.5 text-[10px] font-semibold ${isShort ? 'bg-rose-900/80 text-rose-200' : 'bg-emerald-900/70 text-emerald-200'}">${sideLabel}</span>
                <span class="shift-leg-qty-label font-mono text-slate-400">x${currentQty}</span>
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
            container.innerHTML = `<div class="rounded border border-rose-800 bg-rose-900/40 px-2 py-2 text-xs text-rose-200">${escapeHtml(error.message || 'Error loading open positions')}</div>`;
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
    const qtyInput = document.getElementById('qty-input');
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
        resetIndexScopedStraddleStats();
        applyIndexQtyRules(currentSelectedIndex, true);
    } catch (error) {
        console.error('Error loading index options:', error);
        showToast('Error', error.message || 'Could not load index options', 'error', 3000);
        applyIndexQtyRules(currentSelectedIndex, true);
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
        resetIndexScopedStraddleStats();
        applyIndexQtyRules(currentSelectedIndex, true);
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
    const qtyInput = document.getElementById('qty-input');
    const strikesInput = document.getElementById('strikes-input');
    if (useQtyCheckbox && qtyInput) {
        const syncQtyEnabledState = () => {
            qtyInput.disabled = !useQtyCheckbox.checked;
        };
        useQtyCheckbox.addEventListener('change', syncQtyEnabledState);
        syncQtyEnabledState();
    }
    if (qtyInput) {
        qtyInput.addEventListener('change', () => applyIndexQtyRules(currentSelectedIndex, false));
    }
    if (strikesInput) {
        strikesInput.value = strikesInput.value && Number(strikesInput.value) > 0 ? strikesInput.value : '1';
        strikesInput.addEventListener('change', () => {
            const parsed = Number.parseInt(strikesInput.value, 10);
            strikesInput.value = Number.isInteger(parsed) && parsed > 0 ? String(parsed) : '1';
            const hidden = document.getElementById('shift-count-input');
            if (hidden) hidden.value = strikesInput.value;
        });
    }
    const indexSelect = document.getElementById('index-select');
    if (indexSelect) {
        indexSelect.addEventListener('change', handleIndexChange);
        loadIndexOptions();
    }
    syncShiftInputs();
    applyIndexQtyRules(currentSelectedIndex, true);
    updateTopTimestamp();
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
