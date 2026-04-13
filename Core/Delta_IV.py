import numpy as np
from kiteconnect import KiteConnect, KiteTicker
from datetime import datetime
from scipy.stats import norm
from scipy.optimize import minimize_scalar
import configparser
import time
import datetime as dt
from pathlib import Path
from Core.shared_resources import (
    clear_option_instrument_cache,
    get_option_instrument_cache,
    set_option_instrument_cache,
)


# === Your credentials ===
config = configparser.ConfigParser()
config.read('Cred/Cred_kite_PREM.ini')
api_key = config['Kite']['api_key']


with open("Cred/access_token.txt", "r") as f:
    access_token = f.read().strip()


kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

# spot for nifty - 256265 and sensex - 265 and banknifty - 260105
INDEX_CONFIG = {
    "nifty": {
        "label": "NIFTY",
        "spot_token": 256265,
        "exchange": "NFO",
        "option_symbol": "NIFTY",
        "strike_step": 50,
    },
    "sensex": {
        "label": "SENSEX",
        "spot_token": 265,
        "exchange": "BFO",
        "option_symbol": "SENSEX",
        "strike_step": 100,
    },
    "banknifty": {
        "label": "BANKNIFTY",
        "spot_token": 260105,
        "exchange": "NFO",
        "option_symbol": "BANKNIFTY",
        "strike_step": 100,
    },
}

selected_index_key = "nifty"
spot_token = INDEX_CONFIG[selected_index_key]["spot_token"]
strike_step = INDEX_CONFIG[selected_index_key]["strike_step"]
strike_prices = []
option_tokens = {}
option_meta_by_symbol = {}
instrument_lookup_by_exchange = {}
subscribed_tokens = []

stradle_price =0


def _normalize_option_instrument(meta):
    row = dict(meta or {})
    if "instrument_type" not in row and "type" in row:
        row["instrument_type"] = row.get("type")
    if "type" not in row and "instrument_type" in row:
        row["type"] = row.get("instrument_type")

    if not row.get("name"):
        symbol = str(row.get("tradingsymbol", "")).upper()
        if "BANKNIFTY" in symbol:
            row["name"] = "BANKNIFTY"
        elif "SENSEX" in symbol:
            row["name"] = "SENSEX"
        elif "NIFTY" in symbol:
            row["name"] = "NIFTY"
        else:
            row["name"] = ""
    return row


def _publish_option_instrument_cache():
    # Republish the entire cache snapshot after each reconfiguration.
    clear_option_instrument_cache()
    by_exchange = {}
    for meta in option_meta_by_symbol.values():
        normalized = _normalize_option_instrument(meta)
        exchange = str(normalized.get("exchange", "")).strip().upper()
        if not exchange:
            continue
        by_exchange.setdefault(exchange, []).append(normalized)
    for exchange, instruments in by_exchange.items():
        set_option_instrument_cache(exchange, instruments)


def _configure_index_data(index_key):
    global selected_index_key, spot_token, strike_step, option_tokens, strike_prices, live_data, option_meta_by_symbol, instrument_lookup_by_exchange

    normalized_index_key = (index_key or "").strip().lower()
    if normalized_index_key not in INDEX_CONFIG:
        raise ValueError("Invalid index. Supported values: nifty, sensex, banknifty")

    cfg = INDEX_CONFIG[normalized_index_key]
    instruments = kite.instruments(cfg["exchange"])
    filtered_options = [
        inst for inst in instruments
        if cfg["option_symbol"] in inst["tradingsymbol"] and inst["instrument_type"] in ("CE", "PE")
    ]
    if not filtered_options:
        raise RuntimeError(f"No options found for {cfg['label']}")

    expiry_dates = {inst["expiry"] for inst in filtered_options}
    nearest_expiry = min(expiry_dates)
    nearest_expiry_options = [
        inst for inst in filtered_options
        if inst["expiry"] == nearest_expiry
    ]

    strike_prices = sorted({inst["strike"] for inst in nearest_expiry_options})
    option_tokens = {
        inst["instrument_token"]: {
            "tradingsymbol": inst["tradingsymbol"],
            "strike": inst["strike"],
            "type": inst["instrument_type"],
            "expiry": inst["expiry"],
            "exchange": inst["exchange"],
            "instrument_token": inst["instrument_token"],
        }
        for inst in nearest_expiry_options
    }
    # Keep metadata for all expiries so current open positions can still compute delta.
    option_meta_by_symbol = {
        inst["tradingsymbol"]: {
            "tradingsymbol": inst["tradingsymbol"],
            "strike": inst["strike"],
            "type": inst["instrument_type"],
            "expiry": inst["expiry"],
            "exchange": inst["exchange"],
            "instrument_token": inst["instrument_token"],
        }
        for inst in filtered_options
    }

    selected_index_key = normalized_index_key
    spot_token = cfg["spot_token"]
    strike_step = cfg["strike_step"]
    live_data = {}
    instrument_lookup_by_exchange = {}
    _publish_option_instrument_cache()


def _build_exchange_option_lookup(exchange):
    exchange_norm = str(exchange or "").strip().upper()
    if not exchange_norm:
        return {}

    if exchange_norm in instrument_lookup_by_exchange:
        return instrument_lookup_by_exchange[exchange_norm]

    lookup = {}
    try:
        instruments = kite.instruments(exchange_norm)
        for inst in instruments:
            inst_type = str(inst.get("instrument_type", "")).upper()
            symbol = inst.get("tradingsymbol")
            if inst_type not in ("CE", "PE") or not symbol:
                continue
            lookup[symbol] = {
                "tradingsymbol": symbol,
                "strike": inst.get("strike"),
                "type": inst_type,
                "expiry": inst.get("expiry"),
                "exchange": inst.get("exchange"),
                "instrument_token": inst.get("instrument_token"),
            }
    except Exception as e:
        print(f"⚠️ Unable to build option lookup for {exchange_norm}: {e}")
        lookup = {}

    instrument_lookup_by_exchange[exchange_norm] = lookup
    return lookup


def _resolve_option_details_for_position(pos, token_int):
    symbol = pos.get('tradingsymbol')
    exchange = pos.get('exchange')

    if token_int is not None:
        details = option_tokens.get(token_int)
        if details:
            return details

    details = option_meta_by_symbol.get(symbol)
    if details:
        return details

    exchange_lookup = _build_exchange_option_lookup(exchange)
    details = exchange_lookup.get(symbol)
    if details:
        # Seed global map so future loops are faster.
        option_meta_by_symbol[symbol] = details
    return details


def _resubscribe_for_current_index():
    global subscribed_tokens
    new_tokens = [spot_token] + list(option_tokens.keys())
    try:
        if subscribed_tokens:
            kws.unsubscribe(subscribed_tokens)
        kws.subscribe(new_tokens)
        kws.set_mode(kws.MODE_LTP, new_tokens)
        subscribed_tokens = new_tokens
    except Exception as e:
        print(f"⚠️ Unable to resubscribe websocket tokens: {e}")


def set_selected_index(index_key):
    _configure_index_data(index_key)
    _resubscribe_for_current_index()
    return get_selected_index()


def get_selected_index():
    return selected_index_key


def get_available_indices():
    return list(INDEX_CONFIG.keys())

def get_cached_option_instruments(exchange=None):
    """
    Compatibility helper backed by shared global cache.
    """
    cached = get_option_instrument_cache(exchange=exchange)
    if isinstance(cached, dict):
        merged = []
        for rows in cached.values():
            merged.extend(rows)
        return merged
    return cached


def get_previous_day_close():
    prev = kite.quote(spot_token)
    previous_day_close = prev[str(spot_token)]['ohlc']['close'] 
    name = prev[str(spot_token)]['tradingsymbol']
    print(f"Previous Day Close: {previous_day_close}, Name: {name}")
    return previous_day_close,name

# === Black-Scholes Functions ===

N = norm.cdf

def BS_CALL(S, K, T, r, sigma):
    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * N(d1) - K * np.exp(-r * T) * N(d2)

def BS_PUT(S, K, T, r, sigma):
    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * N(-d2) - S * N(-d1)

def implied_vol(opt_value, S, K, T, r, type_='call'):
    try:
        def call_obj(sigma):
            return abs(BS_CALL(S, K, T, r, sigma) - opt_value)
        def put_obj(sigma):
            return abs(BS_PUT(S, K, T, r, sigma) - opt_value)

        if type_ == 'call':
            res = minimize_scalar(call_obj, bounds=(0.01, 3), method='bounded')
            return res.x
        elif type_ == 'put':
            res = minimize_scalar(put_obj, bounds=(0.01, 3), method='bounded')
            return res.x
        else:
            raise ValueError("type_ must be 'put' or 'call'")
    except:
        return np.nan

def bs_delta(S, K, T, r, sigma, option_type='call'):
    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    if option_type == 'call':
        return N(d1)
    else:
        return -N(-d1)
    


# === WebSocket Setup ===
kws = KiteTicker(api_key, access_token)
live_data = {}

def get_delta_from_position(options_data, future_price):
    """
    Calculate the total delta of all option positions.
    
    Args:
        options_data (list): List of dictionaries containing option data with pre-calculated deltas
        future_price (float): Current future price for delta calculations
        
    Returns:
        float: Total delta of all positions
    """
    total_delta = 0.0
    try:
        positions = kite.positions()['net']
        ltp_fallback_cache = {}
        for pos in positions:
            # Skip if not an option position or zero quantity
            if not pos['tradingsymbol'].endswith(('CE', 'PE')) or pos['quantity'] == 0 or pos['exchange'] not in ('BFO','NFO'):
                continue
                
            # Try to get pre-calculated delta first
            # option = options_lookup.get(pos['tradingsymbol'])
            # if option:
            #     total_delta += float(option['delta']) * pos['quantity']
            #     continue
                
            # ... existing fallback calculation code ...
            symbol = pos.get('tradingsymbol')
            token = pos.get('instrument_token')
            token_int = None
            try:
                token_int = int(token) if token is not None else None
            except (TypeError, ValueError):
                token_int = None

            opt_details = _resolve_option_details_for_position(pos, token_int)
            if not opt_details:
                print(f"⚠️ Can't compute delta for {symbol}, metadata not found.")
                continue

            # Prefer websocket tick, then fallback to quote pull.
            ltp = None
            token_from_meta = opt_details.get("instrument_token")
            if token_int is not None and token_int in live_data:
                ltp = live_data[token_int]
            elif token_from_meta in live_data:
                ltp = live_data[token_from_meta]
            else:
                ltp_key = f"{pos.get('exchange')}:{symbol}"
                if ltp_key not in ltp_fallback_cache:
                    try:
                        ltp_payload = kite.ltp(ltp_key)
                        ltp_fallback_cache[ltp_key] = ltp_payload.get(ltp_key, {}).get("last_price")
                    except Exception:
                        ltp_fallback_cache[ltp_key] = None
                ltp = ltp_fallback_cache.get(ltp_key)

            if ltp is None or ltp <= 0:
                print(f"⚠️ Can't compute delta for {symbol}, LTP unavailable.")
                continue

            strike = opt_details['strike']
            opt_type = opt_details['type']
            expiry_datetime = datetime.combine(opt_details["expiry"], dt.time(15, 30))
            T = (expiry_datetime - datetime.now()).total_seconds() / (365 * 24 * 60 * 60)
            if T <= 0:
                continue
            option_type = 'call' if opt_type == 'CE' else 'put'
            if future_price is None or future_price <= 0:
                continue
            iv = implied_vol(ltp, future_price, strike, T, 0.08, option_type)

            if np.isnan(iv) or iv > 3:
                print(f"⚠️ Invalid IV for {pos['tradingsymbol']}")
                continue

            delta = bs_delta(future_price, strike, T, 0.08, iv, option_type)
            total_delta += delta * pos['quantity']
                
    except Exception as e:
        print(f"❌ Error calculating position delta: {e}")
        return 0.0
            
    return total_delta
            
            
def select_iron_condor_from_data(
    options_data,strangle_credit,atm_strike,
    target_delta=0.3,
    hedge_delta=0.15
):
    if not options_data:
        print("⚠️ No options data available")
        return {}, 0.0
    
    distance_from_sell = 8

    straddle_credit = strangle_credit
    difference_in_strikes = abs(options_data[0]['strike'] - options_data[2]['strike'])

    # Calculate target short strikes
    target_ce_strike = atm_strike + straddle_credit + difference_in_strikes
    target_pe_strike = atm_strike - straddle_credit - difference_in_strikes
    
    # Round to nearest valid strike
    short_ce_strike = round(target_ce_strike / difference_in_strikes) * difference_in_strikes
    short_pe_strike = round(target_pe_strike / difference_in_strikes) * difference_in_strikes
    
    # Calculate target hedge strikes
    target_hedge_ce_strike = short_ce_strike + (distance_from_sell * difference_in_strikes)
    target_hedge_pe_strike = short_pe_strike - (distance_from_sell * difference_in_strikes)
    
    # Calculate exact hedge strikes
    hedge_ce_strike = round(target_hedge_ce_strike / difference_in_strikes) * difference_in_strikes
    hedge_pe_strike = round(target_hedge_pe_strike / difference_in_strikes) * difference_in_strikes
    
    # Get the exact option tokens for all strikes
    short_ce_token = next((k for k, v in option_tokens.items() 
                          if v['strike'] == short_ce_strike and v['type'] == 'CE'), None)
    short_pe_token = next((k for k, v in option_tokens.items() 
                          if v['strike'] == short_pe_strike and v['type'] == 'PE'), None)
    hedge_ce_token = next((k for k, v in option_tokens.items() 
                          if v['strike'] == hedge_ce_strike and v['type'] == 'CE'), None)
    hedge_pe_token = next((k for k, v in option_tokens.items() 
                          if v['strike'] == hedge_pe_strike and v['type'] == 'PE'), None)
    
    if not all([short_ce_token, short_pe_token, hedge_ce_token, hedge_pe_token]):
        print("❌ Could not find exact strikes for all positions")
        return {}, 0.0
        
    # Get the option data for all positions
    def get_option_data(token, strike, opt_type):
        return {
            'instrument_token': option_tokens[token]['tradingsymbol'],
            'strike': strike,
            'type': opt_type,
            'ltp': live_data.get(token, 0),
            'delta': bs_delta(
                live_data[spot_token],
                strike,
                (datetime.combine(option_tokens[token]["expiry"], dt.time(15, 30)) - datetime.now()).total_seconds() / (365 * 24 * 60 * 60),
                0.08,
                implied_vol(live_data.get(token, 0), live_data[spot_token], strike,
                           (datetime.combine(option_tokens[token]["expiry"], dt.time(15, 30)) - datetime.now()).total_seconds() / (365 * 24 * 60 * 60),
                           0.08, 'call' if opt_type == 'CE' else 'put'),
                'call' if opt_type == 'CE' else 'put'
            )
        }
    
    short_ce_data = get_option_data(short_ce_token, short_ce_strike, 'CE')
    short_pe_data = get_option_data(short_pe_token, short_pe_strike, 'PE')
    hedge_ce_data = get_option_data(hedge_ce_token, hedge_ce_strike, 'CE')
    hedge_pe_data = get_option_data(hedge_pe_token, hedge_pe_strike, 'PE')
    
    # Calculate final deltas
    net_ce_delta = float(short_ce_data['delta']) - float(hedge_ce_data['delta'])
    net_pe_delta = float(short_pe_data['delta']) - float(hedge_pe_data['delta'])
    net_delta = net_ce_delta + net_pe_delta
    
    # # Calculate margin and quantity using kite.order_margin
    # try:
    #     # Prepare orders for margin calculation
    #     orders = [
    #         {
    #             "exchange": "NFO",
    #             "tradingsymbol": short_ce_data['instrument_token'],
    #             "transaction_type": "SELL",
    #             "quantity": 1,
    #             "product": "NRML",
    #             "order_type": "MARKET"
    #         },
    #         {
    #             "exchange": "NFO",
    #             "tradingsymbol": short_pe_data['instrument_token'],
    #             "transaction_type": "SELL",
    #             "quantity": 1,
    #             "product": "NRML",
    #             "order_type": "MARKET"
    #         },
    #         {
    #             "exchange": "NFO",
    #             "tradingsymbol": hedge_ce_data['instrument_token'],
    #             "transaction_type": "BUY",
    #             "quantity": 1,
    #             "product": "NRML",
    #             "order_type": "MARKET"
    #         },
    #         {
    #             "exchange": "NFO",
    #             "tradingsymbol": hedge_pe_data['instrument_token'],
    #             "transaction_type": "BUY",
    #             "quantity": 1,
    #             "product": "NRML",
    #             "order_type": "MARKET"
    #         }
    #     ]
        
    #     # Get margin required
    #     margin_info = kite.order_margin(orders)
    #     margin_required = margin_info['total']['total']
        
    #     # Get available margin
    #     available_margin = kite.margins()['equity']['available']['cash']
        
    #     # Calculate maximum lots possible
    #     max_lots = int(available_margin / margin_required)
        
    #     # Calculate credit per lot
    #     credit_per_lot = (short_ce_data['ltp'] + short_pe_data['ltp']) - (hedge_ce_data['ltp'] + hedge_pe_data['ltp'])
        
    #     best_condor = {
    #         'hedge_ce': hedge_ce_data,
    #         'hedge_pe': hedge_pe_data,
    #         'short_ce': short_ce_data,
    #         'short_pe': short_pe_data,
    #         'max_lots': max_lots,
    #         'margin_per_lot': margin_required,
    #         'credit_per_lot': credit_per_lot,
    #         'total_credit': credit_per_lot * max_lots
    #     }
        
    # except Exception as e:
    #     print(f"❌ Error calculating margin: {e}")
    best_condor = {
        'hedge_pe': hedge_pe_data,
        'hedge_ce': hedge_ce_data,
        'short_pe': short_pe_data,
        'short_ce': short_ce_data
        
    }


    return best_condor, net_delta

def min_strike_selection(spot):
    return round(spot / strike_step) * strike_step




def on_ticks(ws, ticks):

    for tick in ticks:
        token = tick['instrument_token']
        ltp = tick['last_price']
        live_data[token] = ltp
        

def get_current_iron_condor():
    if spot_token not in live_data:
        return {}, None, [], None, None, None, None, None, None

    now = datetime.now()
    r = 0.08  # risk-free rate
    spot_price = live_data[spot_token]
    atm_strike = min_strike_selection(spot_price)
    

    if not strike_prices:
        return {}, None, [], None, None, None, None, spot_price, None
    try:
        atm_index = strike_prices.index(atm_strike)
    except ValueError:
        atm_index = min(range(len(strike_prices)), key=lambda i: abs(strike_prices[i] - atm_strike))

    # positions = kite.positions()['net']
    # option_positions = [pos for pos in positions if pos['tradingsymbol'].strip().upper().endswith(("CE", "PE")) and pos['exchange'] in ('BFO','NFO')]
    strike_selected = strike_prices[max(0, atm_index - 20):atm_index + 21]
    ce_atm_ltp = next((k for k, v in option_tokens.items() if v['type'] == 'CE' and v['strike'] == atm_strike), None)
    pe_atm_ltp = next((k for k, v in option_tokens.items() if v['type'] == 'PE' and v['strike'] == atm_strike), None)
    ce_atm_ltp = live_data.get(ce_atm_ltp)
    pe_atm_ltp = live_data.get(pe_atm_ltp)
    if ce_atm_ltp is None or pe_atm_ltp is None:
        return {}, None, [], None, None, None, None, spot_price, atm_strike

    future_price = atm_strike+(ce_atm_ltp-pe_atm_ltp) if ce_atm_ltp and pe_atm_ltp else None

    future_atm_strike = min_strike_selection(future_price) if future_price else atm_strike
    #print(f"Future ATM Strike: {future_atm_strike}, Future Price: {future_price}, Spot Price: {spot_price}")
 

    
    
    ce_fut_atm_ltp = next((k for k, v in option_tokens.items() if v['type'] == 'CE' and v['strike'] == future_atm_strike), None)
    pe_fut_atm_ltp = next((k for k, v in option_tokens.items() if v['type'] == 'PE' and v['strike'] == future_atm_strike), None)
    ce_fut_atm_ltp = live_data.get(ce_fut_atm_ltp)
    pe_fut_atm_ltp = live_data.get(pe_fut_atm_ltp)
    if ce_fut_atm_ltp is None or pe_fut_atm_ltp is None:
        return {}, None, [], None, future_price, None, None, spot_price, future_atm_strike


    Skew = pe_fut_atm_ltp - ce_fut_atm_ltp if ce_fut_atm_ltp and pe_fut_atm_ltp else None
    strangle_credit = ce_fut_atm_ltp + pe_fut_atm_ltp 
    
    
    selected_option_tokens = {k: v for k, v in option_tokens.items() if v['strike'] in strike_selected}
    options_data = []

    for strike in strike_selected:
        for opt_type in ['CE', 'PE']:
            token = next((k for k, v in selected_option_tokens.items()
                          if v['strike'] == strike and v['type'] == opt_type), None)
            if not token or token not in live_data:
                continue

            opt_price = live_data[token]
            expiry_datetime = datetime.combine(option_tokens[token]["expiry"], dt.time(15, 30))
            T = (expiry_datetime - now).total_seconds() / (365 * 24 * 60 * 60)
            option_type = 'call' if opt_type == 'CE' else 'put'
            iv = implied_vol(opt_price, spot_price, strike, T, r, option_type)
            if np.isnan(iv) or iv > 3:
                continue
            delta = bs_delta(future_price, strike, T, r, iv, option_type)

            options_data.append({
                'instrument_token': selected_option_tokens[token]['tradingsymbol'],
                'strike': strike,
                'type': opt_type,
                'ltp': float(opt_price),
                'iv': float(iv),
                'delta': float(delta)
            })
    
    # stradle = strike_prices[atm_index]
    # strangle_credit = sum(ltp['ltp'] for ltp in options_data if ltp['strike'] == stradle)
    result, net_delta = select_iron_condor_from_data(options_data,strangle_credit,future_atm_strike)
    delta = get_delta_from_position(options_data,future_price)
    # #print("Selected Iron Condor:", net_delta)
    
    # ce_atm_ltp = next((ltp for ltp in options_data if ltp['type'] == 'CE' and ltp['strike'] == stradle), None)
    # pe_atm_ltp = next((ltp for ltp in options_data if ltp['type'] == 'PE' and ltp['strike'] == stradle), None)
    # future_price = spot_price+(ce_atm_ltp['ltp']-pe_atm_ltp['ltp']) if ce_atm_ltp and pe_atm_ltp else None
    # Skew = pe_atm_ltp['ltp'] - ce_atm_ltp['ltp'] if ce_atm_ltp and pe_atm_ltp else None

    return result, net_delta, options_data, strangle_credit, future_price, Skew, delta, spot_price, future_atm_strike


def on_connect(ws, response):
    global subscribed_tokens
    tokens = [spot_token] + list(option_tokens.keys())
    ws.subscribe(tokens)
    ws.set_mode(ws.MODE_LTP, tokens)
    subscribed_tokens = tokens

def on_close(ws, code, reason):
    print("WebSocket closed:", code, reason)

def on_error(ws, code, reason):
    print(f"Error: {code} - {reason}")




kws.on_ticks = on_ticks
kws.on_connect = on_connect
kws.on_close = on_close
kws.on_error = on_error

_configure_index_data(selected_index_key)

print("Connecting to WebSocket...")
kws.connect(threaded=True)

#   # Just to keep main thread alive if needed
# if __name__ == "__main__":
#     while True:
#         #get_current_iron_condor()
#         time.sleep(1)
