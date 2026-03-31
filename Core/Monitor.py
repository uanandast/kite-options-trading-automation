#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Apr  6 13:13:02 2025

@author: utkarshanand
"""
import time
import os
from urllib import response
from concurrent.futures import ThreadPoolExecutor, as_completed
from kiteconnect import KiteConnect
import configparser
from collections import defaultdict
from Core.system_close import system_close
from kiteconnect import KiteTicker
import requests
import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path
from google.genai import Client
from google.genai.types import FunctionDeclaration, Tool, GenerateContentConfig

# === Threading lock for monitor_spreads ===
from Core.shared_resources import monitor_lock, set_processing_state, get_processing_state


try:
    client = Client(api_key=os.environ.get("OPEN_API_KEY"))
except Exception as e:
    print(f"❌ Error initializing Gemini client: {e}")


# === Your credentials ===
config = configparser.ConfigParser()
config.read('Cred/Cred_kite_PREM.ini')
api_key = config['Kite']['api_key']


with open("Cred/access_token.txt", "r") as f:
    access_token = f.read().strip()


kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)


pnl_total = 0
Current_pos_credit = 0

# Track exiting state
is_exiting = False


# Track SL order IDs and matched hedge legs
placed_sl_orders = {}

def get_margin():
    margin = kite.margins('equity').get('available')['collateral'] + kite.margins('equity').get('available')['opening_balance']  

    print(f"💰 Available margin: ₹{margin:.2f}")


    return margin


margin = get_margin()
margin_buffer =  0.003  # 0.3% of margin as buffer
threshold = -margin * margin_buffer  # 0.3% of margin as threshold for exiting positions
print(f"🚨 Threshold for exiting positions: ₹{threshold:.2f} ({round(margin_buffer * 100, 2)}% of margin)"   )

def beep():
    os.system('say "order updated"')


# Telegram alert function
def send_telegram(message):
    BOT_TOKEN = config.get('Kite', 'BOT_TOKEN')
    CHAT_ID = config.get('Kite', 'CHAT_ID')

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:
        requests.get(url, params=params, timeout=5)
        print("📩 Telegram alert sent")
    except Exception as e:
        print(f"❌ Telegram error: {e}")



def motivate_trader():
    response = client.models.generate_content(
    model="gemini-3.1-flash-lite-preview",
    contents=[
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        "A stop-loss was triggered on a Nifty credit spread. "
                        f"Risk was limited to {abs(margin_buffer * 100):.2f}% of total capital. "
                        "This is the 2nd consecutive loss. "
                        "The trader followed all predefined rules.\n\n"
                        "Generate a short motivational message reinforcing discipline, "
                        "risk management, and long-term statistical thinking."
                    )
                }
            ],
        }
    ],
    config={
        "system_instruction": (
            "You are a calm, professional trading performance coach. "
            "The trader has just exited due to a stop-loss. "
            "Reinforce discipline and emotional stability. "
            "Do NOT mention recovering losses or making money back. "
            "Do NOT encourage aggressive trading. "
            "Keep the response under 2 sentences. "
            "Tone: grounded, calm, professional."
        )
    },
)
    #os.system(f'say "{response.text}"')
    print(f"💬 Motivational message: {response.text}")
    send_telegram(f"💬 Motivational message: {response.text}")



def ask_and_sleep_mac():
    try:
        print("Locking Account...")
        system_close()
        send_telegram("🚨 Max loss threshold breached. Account locked and Mac will sleep. Review the situation calmly before resuming trading.")
        motivate_trader()
        # print("💤 Sleeping Mac...")
        # time.sleep(60)
        # os.system("pmset sleepnow")
        # exit(0)
        # else:
        #     print("🛑 Sleep cancelled by user.")
    except Exception as e:
        print(f"⚠️ Could not display popup or sleep: {e}")


# def get_last_sell_price(symbol):
#     try:
#         orders = kite.orders()
#         sells = [
#             o for o in orders
#             if o["tradingsymbol"] == symbol
#             and o["transaction_type"] == "SELL"
#             and o["status"] == "COMPLETE"
#         ]
#         if sells:
#             # Sort by order time descending, take latest
#             sells = sorted(
#                         sells,
#                         key=lambda x: x.get("order_timestamp") or x.get("exchange_timestamp") or 0,
#                         reverse=True)
#             return sells[0]["average_price"]
#     except Exception as e:
#         print(f"⚠️ Error fetching last sell price for {symbol}: {e}")
#     return None


def cancel_all_sl_orders(fast=False):
    try:
        orders = kite.orders()
        sl_orders = [
            o for o in orders
            if o["status"] in ["OPEN", "TRIGGER PENDING"] and o["order_type"] == "SL"
        ]
        cancelled = 0
        errors = 0

        def _cancel(o):
            nonlocal cancelled, errors
            try:
                kite.cancel_order(order_id=o["order_id"], variety="regular")
                cancelled += 1
                if not fast:
                    print(f"❌ Cancelled SL order {o['order_id']} for {o['tradingsymbol']}")
            except Exception as e:
                errors += 1
                print(f"⚠️ Error cancelling SL order {o['order_id']} for {o['tradingsymbol']}: {e}")

        if fast and len(sl_orders) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            max_workers = min(4, len(sl_orders))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_cancel, o) for o in sl_orders]
                for f in as_completed(futures):
                    f.result()
        else:
            for o in sl_orders:
                _cancel(o)
        return {
            "requested": len(sl_orders),
            "cancelled": cancelled,
            "errors": errors,
        }
    except Exception as e:
        print(f"⚠️ Error fetching orders for cancellation: {e}")
        return {
            "requested": 0,
            "cancelled": 0,
            "errors": 1,
            "error": str(e),
        }




def has_existing_stoploss(kite, symbol, orders_cache=None):
    """
    Checks if a SL or SL-L order already exists for this symbol.
    """
    try:
        orders = orders_cache if orders_cache is not None else kite.orders()
        for order in orders:
            if (
                order["tradingsymbol"] == symbol
                and order["status"] in ["OPEN", "TRIGGER PENDING"]
                and order["order_type"] == "SL"  # Covers both SL-M and SL-L
            ):
                return order["order_id"]
    except Exception as e:
        print(f"❌ Error checking SL for {symbol}:", e)
    return False




def place_stoploss_order(position, *, ltp=None, sl_trigger_price=None, fast=False):
    
    # last_sell_price = get_last_sell_price(position["tradingsymbol"])    
    # print(f"💰 Last sell price for {position['tradingsymbol']}: {last_sell_price}")

    stoploss_point = 9 # Adjust this value as needed

    if sl_trigger_price is None:
        if ltp is None and not fast:
            try:
                ltp_data = kite.ltp(f"{position['exchange']}:{position['tradingsymbol']}")
                ltp = ltp_data[f"{position['exchange']}:{position['tradingsymbol']}"]["last_price"]
                print(f"💰 LTP for {position['tradingsymbol']}: {ltp}")
            except Exception as e:
                print(f"❌ Failed to fetch LTP for {position['tradingsymbol']}: {e}")
                ltp = None
        if ltp is not None:
            sl_trigger_price = round(ltp + ltp / 4, 1)  # Placing SL at 25% above current LTP
        else:
            sl_trigger_price = round(position['average_price'] + stoploss_point, 1)
    # if last_sell_price is None:
    #     print(f"❌ Last sell price not found for {position['tradingsymbol']}, using average price")
    #     sl_trigger_price = round(position['average_price']+stoploss_point ,1)
    # else:    
    #     sl_trigger_price = round(last_sell_price + stoploss_point, 1)


    total_qty = abs(position["quantity"])

    freeze_limit = 1755

    try:
        order_ids = []
        chunks = []
        for i in range(0, total_qty, freeze_limit):
            chunks.append(min(freeze_limit, total_qty - i))

        def _place_chunk(chunk_qty):
            order_id = kite.place_order(
                exchange=position["exchange"],
                tradingsymbol=position["tradingsymbol"],
                transaction_type="BUY",  # Covering short
                quantity=chunk_qty,
                order_type="SL",
                price=sl_trigger_price,
                trigger_price=sl_trigger_price - 0.5,
                product=position["product"],
                variety="regular"
            )
            if not fast:
                print(f"✅ SL order placed: Qty={chunk_qty}, Trigger={sl_trigger_price}, Order ID={order_id}")
                beep()
            return order_id

        if fast and len(chunks) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            max_workers = min(3, len(chunks))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_place_chunk, qty) for qty in chunks]
                for f in as_completed(futures):
                    order_ids.append(f.result())
        else:
            for qty in chunks:
                order_ids.append(_place_chunk(qty))

        return order_ids
    except Exception as e:
        print(f"❌ Failed to place SL for {position['tradingsymbol']}: {e}")
        return None

def stoploss_order_button():
    try:
        # This function can be called from the UI when the user clicks a button to place SL orders manually
        positions = kite.positions()["net"]
        option_positions = [p for p in positions if p["quantity"] < 0 and p["tradingsymbol"].endswith(("CE", "PE")) and p['exchange'] in ('BFO','NFO')]
        total_positions = len(option_positions)
        skipped_existing = 0
        placed_orders = 0
        failed_positions = 0

        # Fetch orders once to avoid per-symbol API calls
        try:
            orders_cache = kite.orders()
        except Exception as e:
            print(f"⚠️ Error fetching orders (falling back to per-symbol checks): {e}")
            orders_cache = None

        existing_sl_symbols = set()
        if orders_cache is not None:
            for o in orders_cache:
                if (
                    o.get("status") in ["OPEN", "TRIGGER PENDING"]
                    and o.get("order_type") == "SL"
                    and o.get("tradingsymbol")
                ):
                    existing_sl_symbols.add(o["tradingsymbol"])

        # Prefetch LTPs in one call to avoid per-symbol latency
        ltp_map = {}
        try:
            ltp_symbols = [f"{p['exchange']}:{p['tradingsymbol']}" for p in option_positions]
            if ltp_symbols:
                ltp_data = kite.ltp(ltp_symbols)
                for k, v in ltp_data.items():
                    ltp_map[k] = v.get("last_price")
        except Exception as e:
            print(f"⚠️ Error prefetching LTPs (will use avg price): {e}")

        def _place_for_position(pos):
            symbol = pos["tradingsymbol"]
            if symbol in existing_sl_symbols:
                return ("skipped", symbol, None)
            if orders_cache is not None:
                existing_order_id = has_existing_stoploss(kite, symbol, orders_cache=orders_cache)
                if existing_order_id:
                    return ("skipped", symbol, None)
            print(f"📌 Placing SL for {symbol} from button click")
            ltp_key = f"{pos['exchange']}:{symbol}"
            ltp = ltp_map.get(ltp_key)
            order_ids = place_stoploss_order(pos, ltp=ltp, fast=True)
            return ("placed" if order_ids else "failed", symbol, order_ids)

        # Place SL orders with limited concurrency to reduce total latency
        max_workers = min(2, total_positions) if total_positions > 0 else 1
        if total_positions > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_place_for_position, pos) for pos in option_positions]
                for f in as_completed(futures):
                    status, symbol, order_ids = f.result()
                    if status == "skipped":
                        print(f"⏳ SL already exists for {symbol}, skipping...")
                        skipped_existing += 1
                    elif status == "placed":
                        placed_orders += len(order_ids)
                    else:
                        failed_positions += 1
        else:
            for pos in option_positions:
                status, symbol, order_ids = _place_for_position(pos)
                if status == "skipped":
                    print(f"⏳ SL already exists for {symbol}, skipping...")
                    skipped_existing += 1
                elif status == "placed":
                    placed_orders += len(order_ids)
                else:
                    failed_positions += 1
        return {
            "positions": total_positions,
            "skipped": skipped_existing,
            "placed_orders": placed_orders,
            "failed_positions": failed_positions,
        }
    except Exception as e:
        print(f"❌ Error in stoploss_order_button: {e}")
        return {
            "positions": 0,
            "skipped": 0,
            "placed_orders": 0,
            "failed_positions": 1,
            "error": str(e),
        }





def exit_position(pos, side):
    try:
        total_qty = abs(pos["quantity"])
        freeze_limit = 1755

        side = "BUY" if pos['quantity'] < 0 else "SELL"

        for i in range(0, total_qty, freeze_limit):
            chunk_qty = min(freeze_limit, total_qty - i)

            print(f"🔁 Exiting {pos['tradingsymbol']} with {side}, Qty={chunk_qty}")
            start_ts = time.time()
            order_id = kite.place_order(
                exchange=pos["exchange"],
                tradingsymbol=pos["tradingsymbol"],
                transaction_type=side,
                quantity=chunk_qty,
                order_type="MARKET",
                product=pos["product"],
                variety="regular"
            )
            elapsed = time.time() - start_ts
            print(f"✅ Exit order placed: {order_id} ({elapsed:.2f}s)")
        return True
    except Exception as e:
        print(f"❌ Error while exiting hedge {pos['tradingsymbol']}: {e}")
        return False



def calculate_pnl(positions):
    try:
        pnl = 0
        Current_pos_credit = 0

        # Filter option symbols for batch LTP fetch
        option_positions = [pos for pos in positions if pos['tradingsymbol'].strip().upper().endswith(("CE", "PE")) and pos['exchange'] in ('BFO','NFO')]
        symbols = [f"{pos['exchange']}:{pos['tradingsymbol']}" for pos in option_positions]
  
        
        # Fetch LTPs
        ltp_data = kite.ltp(symbols) if symbols else {}

        for pos in option_positions:
            try:
                symbol = f"{pos['exchange']}:{pos['tradingsymbol']}"
                ltp = ltp_data[symbol]["last_price"]

                # Total P&L (realized + unrealized)
                pnl += (pos['sell_value'] - pos['buy_value']) + (pos['quantity'] * ltp * pos['multiplier'])

                # Option credit/debit
                if pos['quantity'] < 0:
                    Current_pos_credit += ltp
                elif pos['quantity'] > 0:
                    Current_pos_credit -= ltp

            except Exception as e:
                print(f"❌ Error calculating P&L for {pos['tradingsymbol']}: {e}")

        return pnl, Current_pos_credit

    except Exception as e:
        print(f"❌ Error in calculate_pnl: {e}")
        return 0, 0

# def group_spreads(positions):
#     """
#     Groups each short option (primary) with the closest matching long (hedge)
#     based on same type (CE/PE) and expiry, using closest strike match.
#     Returns one spread per short leg.
#     """
#     primary_legs = [p for p in positions if p['quantity'] < 0 and p['tradingsymbol'].endswith(("CE", "PE")) and p['exchange'] in ('BFO','NFO')]
#     hedge_legs = [p for p in positions if p['quantity'] > 0 and p['tradingsymbol'].endswith(("CE", "PE")) and p['exchange'] in ('BFO','NFO')]
#     used_hedges = set()
#     spreads = []

#     for primary in primary_legs:
#         leg_type = "CE" if primary["tradingsymbol"].endswith("CE") else "PE"

#         # Find up to 2 unused hedges of the same type
#         candidates = [
#             h for h in hedge_legs
#             if h["tradingsymbol"].endswith(leg_type)
#             and h["tradingsymbol"] not in used_hedges
#         ] 

#         for h in candidates:
#             used_hedges.add(h["tradingsymbol"])

#         spreads.append({"primary": [primary], "hedge": candidates})
    
#     return spreads

def Exiting_position(positions):
    # global is_exiting
    # is_exiting = True
    try:
        print("Exiting all Postions...")

        short_legs = [p for p in positions if p['quantity'] < 0 and p['tradingsymbol'].endswith(("CE", "PE")) and p['exchange'] in ('BFO','NFO')]
        long_legs = [p for p in positions if p['quantity'] > 0 and p['tradingsymbol'].endswith(("CE", "PE")) and p['exchange'] in ('BFO','NFO')]

        short_legs = [p for p in short_legs if p['quantity'] != 0]
        long_legs = [p for p in long_legs if p['quantity'] != 0]

        total_short = len(short_legs)
        total_long = len(long_legs)
        succeeded = 0
        failed = 0

        if short_legs:
            max_workers = min(4, len(short_legs))
            print(f"⚡ Exiting short legs first: {len(short_legs)} legs (workers={max_workers})")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(exit_position, pos, "BUY") for pos in short_legs]
                for future in as_completed(futures):
                    if future.result():
                        succeeded += 1
                    else:
                        failed += 1

        if long_legs:
            max_workers = min(4, len(long_legs))
            print(f"⚡ Exiting long legs next: {len(long_legs)} legs (workers={max_workers})")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(exit_position, pos, "SELL") for pos in long_legs]
                for future in as_completed(futures):
                    if future.result():
                        succeeded += 1
                    else:
                        failed += 1
        return {
            "short_legs": total_short,
            "long_legs": total_long,
            "attempted": total_short + total_long,
            "succeeded": succeeded,
            "failed": failed,
        }
    except Exception as e:
        print(f"❌ Error in P&L monitoring: {e}")
        return {
            "short_legs": 0,
            "long_legs": 0,
            "attempted": 0,
            "succeeded": 0,
            "failed": 1,
            "error": str(e),
        }

def routine_close():
    #exit the program after 10 PM
    current_time = time.localtime()
    if current_time.tm_hour >= 22:
        print("Routine close: It's after 10 PM. Exiting all positions and shutting down.")
        exit(0)




def Exiting_closing_account(positions):
    # global is_exiting
    # is_exiting = True
    try:
        print("🚨 Max loss threshold breached. Exiting all positions...")
        # Cancel all open SL orders (no cooldown logic)
        # orders = kite.orders()
        # for o in orders:
        #     if o["status"] in ["OPEN", "TRIGGER PENDING"]:
        #         try:
        #             kite.cancel_order(order_id=o["order_id"], variety="regular")
        #             print(f"❌ Cancelled SL order {o['order_id']} for {o['tradingsymbol']}")
        #             beep()
        #         except Exception as e:
        #             print(f"⚠️ Error cancelling SL order {o['order_id']} for {o['tradingsymbol']}: {e}")
        short_legs = [p for p in positions if p['quantity'] < 0 and p['tradingsymbol'].endswith(("CE", "PE")) and p['exchange'] in ('BFO','NFO')]
        long_legs = [p for p in positions if p['quantity'] > 0 and p['tradingsymbol'].endswith(("CE", "PE")) and p['exchange'] in ('BFO','NFO')]

        short_legs = [p for p in short_legs if p['quantity'] != 0]
        long_legs = [p for p in long_legs if p['quantity'] != 0]

        if short_legs:
            max_workers = min(4, len(short_legs))
            print(f"⚡ Exiting short legs first: {len(short_legs)} legs (workers={max_workers})")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(exit_position, pos, "BUY") for pos in short_legs]
                for future in as_completed(futures):
                    future.result()

        if long_legs:
            max_workers = min(4, len(long_legs))
            print(f"⚡ Exiting long legs next: {len(long_legs)} legs (workers={max_workers})")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(exit_position, pos, "SELL") for pos in long_legs]
                for future in as_completed(futures):
                    future.result()
        # placed_sl_orders.clear()
        ask_and_sleep_mac()

    except Exception as e:
        print(f"❌ Error in P&L monitoring: {e}")

def monitor_spreads():
    last_margin_update = 0  # Track last margin update time
    threshold_breach_start = None  # Track when pnl_total first breached threshold
    account_close = False
    
    while True:       
        try:
            positions = kite.positions()["net"]
            # option_positions = [p for p in positions if p["quantity"] != 0 and p["tradingsymbol"].endswith(("CE", "PE")) and p['exchange'] in ('BFO','NFO')]
            # spreads = group_spreads(option_positions)
        
            # # Your existing monitoring code here
            # for spread in spreads:
            #     primary_legs = spread["primary"]
            #     hedge_legs = spread["hedge"]

            #     # Check if SL already placed for all primary legs
            #     all_primary_symbols = [leg["tradingsymbol"] for leg in primary_legs]
            #     sl_already_placed = all(symbol in placed_sl_orders for symbol in all_primary_symbols)

            #     if sl_already_placed:
            #         # Check if any quantity changed for any leg
            #         quantity_changed = False
            #         for leg in primary_legs:
            #             sl_data = placed_sl_orders.get(leg["tradingsymbol"], {})
            #             prev_qty = sl_data.get("qty")
            #             if abs(leg["quantity"]) != prev_qty:
            #                 quantity_changed = True
            #                 break

            #         if quantity_changed:
            #             print(f"🔄 Quantity changed for one or more legs in {all_primary_symbols}. Updating SL...")

            #             # Place new SL for updated quantities with updating flag and cancel logic
            #             for leg in primary_legs:
            #                 symbol = leg["tradingsymbol"]

            #                 sl_data = placed_sl_orders.get(symbol, {})
            #                 # Skip if recently updated within 2 seconds
            #                 if time.time() - sl_data.get("last_updated", 0) < 2:
            #                     continue

            #                 if sl_data.get("updating"):
            #                     continue

            #                 placed_sl_orders[symbol]["updating"] = True

            #                 try:
            #                     sl_data = placed_sl_orders[symbol]
            #                     order_ids = sl_data.get("order_id", [])
            #                     for oid in order_ids:
            #                         try:
            #                             kite.cancel_order(order_id=oid, variety="regular")
            #                             print(f"❌ Cancelled outdated SL order {oid} for {symbol}")
            #                             beep()
            #                         except Exception as e:
            #                             print(f"⚠️ Error cancelling outdated SL {oid} for {symbol}: {e}")

            #                     new_order_ids = place_stoploss_order(leg)
            #                     if new_order_ids:
            #                         placed_sl_orders[symbol]["order_id"] = new_order_ids
            #                         placed_sl_orders[symbol]["qty"] = abs(leg["quantity"])
            #                         placed_sl_orders[symbol]["last_updated"] = time.time()
            #                 finally:
            #                     placed_sl_orders[symbol]["updating"] = False
                        
            #         # Update hedge if new hedge was added
            #         for leg in primary_legs:
            #             ts = leg["tradingsymbol"]
            #             tracked_hedges = {h["tradingsymbol"] for h in placed_sl_orders.get(ts,{}).get("hedge",[])}
            #             current_hedges = {h["tradingsymbol"] for h in hedge_legs}
            #             if current_hedges != tracked_hedges:
            #                 print(f"🧩 New hedge detected for {leg['tradingsymbol']}. Updating...")
            #                 placed_sl_orders[leg["tradingsymbol"]]["hedge"] = hedge_legs

            #     else:
            #         # Place SL orders for legs not yet placed
            #         for leg in primary_legs:
            #             symbol = leg["tradingsymbol"]

            #             if symbol in placed_sl_orders:
            #                 continue  # Already tracked

            #             print(f"📌 Checking SL for {symbol}")
            #             existing_order_id = has_existing_stoploss(kite, symbol)

            #             if existing_order_id:
            #                 print(f"⏳ SL already exists for {symbol}, tracking it...")
            #                 placed_sl_orders[symbol] = {
            #                     "order_id": [existing_order_id],
            #                     "hedge": hedge_legs,
            #                     "qty": abs(leg["quantity"])
            #                 }
            #             else:
            #                 sl_data = placed_sl_orders.get(symbol, {})
            #                 # Skip if recently updated
            #                 if time.time() - sl_data.get("last_updated", 0) < 2:
            #                     continue

            #                 placed_sl_orders[symbol] = {
            #                     "order_id": [],
            #                     "hedge": hedge_legs,
            #                     "qty": abs(leg["quantity"]),
            #                     "updating": True
            #                 }

            #                 try:
            #                     sl_order_ids = place_stoploss_order(leg)
            #                     if sl_order_ids:
            #                         placed_sl_orders[symbol]["order_id"] = sl_order_ids
            #                         placed_sl_orders[symbol]["last_updated"] = time.time()
            #                         print(f"✅ Placed SL for {symbol}: {sl_order_ids}")
            #                     else:
            #                         print(f"⚠️ Failed to place SL for {symbol}. It is NOT protected right now.")
            #                         placed_sl_orders.pop(symbol)
            #                 finally:
            #                     if symbol in placed_sl_orders:
            #                         placed_sl_orders[symbol].pop("updating", None)

            # for symbol, data in list(placed_sl_orders.items()):
            #     order_ids = data["order_id"] #SL order IDs
            #     hedge_legs = data["hedge"]

            #     # Refresh position data for primary leg
            #     current_primary = next((p for p in positions if p["tradingsymbol"] == symbol), None)

            #     if current_primary and current_primary["quantity"] == 0:
            #         orders = kite.orders()
            #         print(f"🎯 Primary {symbol} closed manually. Cleaning up...")

            #         # Cancel SL order if still pending
            #         for oid in order_ids:
            #             for o in orders:
            #                 if o["order_id"] == oid and o["status"] in ["OPEN", "TRIGGER PENDING"]:
            #                     try:
            #                         kite.cancel_order(order_id=oid, variety="regular")
            #                         print(f"❌ Cancelled SL order {oid} for {symbol}")
            #                         beep()
            #                     except Exception as e:
            #                         print(f"⚠️ Error cancelling SL order {oid} for {symbol}: {e}")
            #                     break

            #         # --- Future logic: Exit only the hedge legs associated with this primary leg, matching type (CE/PE)
            #         # associated_hedges = data["hedge"]
            #         # # Determine if primary is CE or PE
            #         # primary_type = "CE" if symbol.endswith("CE") else "PE"
            #         #
            #         # for hedge_leg in associated_hedges:
            #         #     if hedge_leg["tradingsymbol"].endswith(primary_type):
            #         #         latest = next((p for p in positions if p["tradingsymbol"] == hedge_leg["tradingsymbol"]), None)
            #         #         if latest and latest["quantity"] != 0:
            #         #             exit_position(latest, "SELL")

            #         placed_sl_orders.pop(symbol)

            # t = time.time()
            # fmt = time.localtime(t)     
            # strf = time.strftime("%D %T", fmt)
            global pnl_total, Current_pos_credit, available_margin
            
            # Update margin every 2 seconds
            current_time = time.time()
            if current_time - last_margin_update >= 2:
                available_margin = kite.margins('equity')['net']
                last_margin_update = current_time
            
            pnl_total, Current_pos_credit = calculate_pnl(positions)
            
            if pnl_total <= threshold:
                if threshold_breach_start is None:
                    threshold_breach_start = current_time
                elif current_time - threshold_breach_start >= 2:
                    if account_close ==False:
                        Exiting_closing_account(positions)
                        account_close = True
            else:
                threshold_breach_start = None
            routine_close()
            time.sleep(.2)  # Standard monitoring interval
        except Exception as e:
            print(f"❌ Error in monitor_spreads loop: {e}")
            time.sleep(5)  # Longer sleep on error
        finally:
            # Always reset processing flag when done
            set_processing_state(False)

# === Run ===
if __name__ == "__main__":
   monitor_spreads()
    
