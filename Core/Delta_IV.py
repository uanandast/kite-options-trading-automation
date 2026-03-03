import numpy as np
from kiteconnect import KiteConnect, KiteTicker
from datetime import datetime
from scipy.stats import norm
from scipy.optimize import minimize_scalar
import configparser
import time
import datetime as dt
from pathlib import Path


# === Your credentials ===
config = configparser.ConfigParser()
config.read('Cred/Cred_kite_PREM.ini')
api_key = config['Kite']['api_key']


with open("Cred/access_token.txt", "r") as f:
    access_token = f.read().strip()


kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

#spot for nifty - 256265 and sensex - 265 and banknifty - 260105
# === Spot and option instrument tokens ===
spot_token = 265

# Fetch all NFO instruments
if spot_token == 256265 or spot_token == 260105:
    nfo_instruments = kite.instruments('NFO')
elif spot_token == 265:
    nfo_instruments = kite.instruments('BFO')   
    print("Sensex")
else:
    raise ValueError("Invalid spot token. Use 256265 for Nifty or 256262 for Sensex.")

# Filter for NIFTY options (CE/PE)
if spot_token == 256265:
    nifty_options = [
        inst for inst in nfo_instruments
        if 'NIFTY' in inst['tradingsymbol'] and inst['instrument_type'] in ('CE', 'PE')
    ]
elif spot_token == 265:
    nifty_options = [
        inst for inst in nfo_instruments
        if 'SENSEX' in inst['tradingsymbol'] and inst['instrument_type'] in ('CE', 'PE')
    ]
elif spot_token == 260105:
    nifty_options = [
        inst for inst in nfo_instruments
        if 'BANKNIFTY' in inst['tradingsymbol'] and inst['instrument_type'] in ('CE', 'PE')
    ]
else:
    raise ValueError("Invalid spot token. Use 256265 for Nifty or 256262 for Sensex.")



# Get all unique expiry dates and select the nearest one
expiry_dates = {inst['expiry'] for inst in nifty_options}
nearest_expiry = min(expiry_dates)

# Filter options for the nearest expiry only
nearest_expiry_options = [
    inst for inst in nifty_options
    if inst['expiry'] == nearest_expiry
]

# Extract strike prices
strike_prices = sorted({inst['strike'] for inst in nearest_expiry_options})

# If you want to see tradingsymbol, strike, and option type:
option_chain = {
    inst['instrument_token'] : {
        'tradingsymbol': inst['tradingsymbol'],
        'strike': inst['strike'],
        'type': inst['instrument_type'],
        'expiry':inst['expiry']
    }
    for inst in nearest_expiry_options}

option_tokens = option_chain

stradle_price =0

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
            opt_details = option_tokens.get(pos['instrument_token'])
            if not opt_details or pos['instrument_token'] not in live_data:
                print(f"⚠️ Can't compute delta for {pos['tradingsymbol']}, missing data.")
                continue

            ltp = live_data[pos['instrument_token']]
            strike = opt_details['strike']
            opt_type = opt_details['type']
            expiry_datetime = datetime.combine(opt_details["expiry"], dt.time(15, 30))
            T = (expiry_datetime - datetime.now()).total_seconds() / (365 * 24 * 60 * 60)
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
    
    nifty_diff = 50
    bank_nifty_diff = 100
    sensex_diff = 100
    if spot_token == 256265:
        near_strikes = round(spot / nifty_diff) * nifty_diff
    elif spot_token == 260105:
        near_strikes = round(spot / bank_nifty_diff) * bank_nifty_diff
    elif spot_token == 265:
        near_strikes = round(spot / sensex_diff) * sensex_diff
    else:
        near_strikes = round(spot / nifty_diff) * nifty_diff
    return near_strikes




def on_ticks(ws, ticks):

    for tick in ticks:
        token = tick['instrument_token']
        ltp = tick['last_price']
        live_data[token] = ltp
        

def get_current_iron_condor():
    if spot_token not in live_data:
        return {}, None, [], None, None, None, None, None

    now = datetime.now()
    r = 0.08  # risk-free rate
    spot_price = live_data[spot_token]
    atm_strike = min_strike_selection(spot_price)
    

    atm_index = strike_prices.index(atm_strike)

    # positions = kite.positions()['net']
    # option_positions = [pos for pos in positions if pos['tradingsymbol'].strip().upper().endswith(("CE", "PE")) and pos['exchange'] in ('BFO','NFO')]
    strike_selected = strike_prices[max(0, atm_index - 20):atm_index + 21]
    ce_atm_ltp = next((k for k, v in option_tokens.items() if v['type'] == 'CE' and v['strike'] == atm_strike), None)
    pe_atm_ltp = next((k for k, v in option_tokens.items() if v['type'] == 'PE' and v['strike'] == atm_strike), None)
    ce_atm_ltp = live_data.get(ce_atm_ltp)
    pe_atm_ltp = live_data.get(pe_atm_ltp)
    if ce_atm_ltp is None or pe_atm_ltp is None:
        return {}, None, [], None, None, None, None, spot_price

    future_price = atm_strike+(ce_atm_ltp-pe_atm_ltp) if ce_atm_ltp and pe_atm_ltp else None

    future_atm_strike = min_strike_selection(future_price) if future_price else atm_strike
    #print(f"Future ATM Strike: {future_atm_strike}, Future Price: {future_price}, Spot Price: {spot_price}")
 

    
    
    ce_fut_atm_ltp = next((k for k, v in option_tokens.items() if v['type'] == 'CE' and v['strike'] == future_atm_strike), None)
    pe_fut_atm_ltp = next((k for k, v in option_tokens.items() if v['type'] == 'PE' and v['strike'] == future_atm_strike), None)
    ce_fut_atm_ltp = live_data.get(ce_fut_atm_ltp)
    pe_fut_atm_ltp = live_data.get(pe_fut_atm_ltp)
    if ce_fut_atm_ltp is None or pe_fut_atm_ltp is None:
        return {}, None, [], None, future_price, Skew, None, spot_price


    Skew = pe_fut_atm_ltp - ce_fut_atm_ltp if ce_fut_atm_ltp and pe_fut_atm_ltp else None
    strangle_credit = ce_fut_atm_ltp + pe_fut_atm_ltp 
    
    
    option_chain_selected = {k: v for k, v in option_tokens.items() if v['strike'] in strike_selected}
    # --- Fetch OI data in bulk and update live_data with OI values ---
    try:
        quote_response = kite.quote(list(option_chain_selected.keys()))
        for token in option_chain_selected:
            token_data = quote_response.get(str(token), {})
            if 'oi' in token_data:
                live_data[f"{token}_oi"] = token_data['oi']
    except Exception as e:
        print(f"⚠️ Failed to fetch OI data: {e}")
    options_data = []

    for strike in strike_selected:
        for opt_type in ['CE', 'PE']:
            token = next((k for k, v in option_chain_selected.items()
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
            OI = live_data.get(f"{token}_oi")
            if OI is None:
                continue

            options_data.append({
                'instrument_token': option_chain_selected[token]['tradingsymbol'],
                'strike': strike,
                'type': opt_type,
                'ltp': float(opt_price),
                'iv': float(iv),
                'delta': float(delta),
                'oi':float(OI)
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

    return result, net_delta, options_data,strangle_credit, future_price, Skew,delta,spot_price


def on_connect(ws, response):
    tokens = [spot_token] + list(option_tokens.keys())
    ws.subscribe(tokens)
    ws.set_mode(ws.MODE_LTP, tokens)

def on_close(ws, code, reason):
    print("WebSocket closed:", code, reason)

def on_error(ws, code, reason):
    print(f"Error: {code} - {reason}")




kws.on_ticks = on_ticks
kws.on_connect = on_connect
kws.on_close = on_close
kws.on_error = on_error

print("Connecting to WebSocket...")
kws.connect(threaded=True)

#   # Just to keep main thread alive if needed
# if __name__ == "__main__":
#     while True:
#         #get_current_iron_condor()
#         time.sleep(1)
