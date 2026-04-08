#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Apr  6 13:13:02 2025

@author: utkarshanand
"""
import time
import os
import re
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
_instrument_cache = {}

INDEX_STRIKE_STEP = {
    "BANKNIFTY": 100,
    "NIFTY": 50,
    "SENSEX": 100,
}

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



def _load_instruments(exchange):
    now = time.time()
    cached = _instrument_cache.get(exchange)
    if cached and (now - cached["ts"] < 120):
        return cached["data"]
    data = kite.instruments(exchange)
    _instrument_cache[exchange] = {"ts": now, "data": data}
    return data


def _position_index_key(position):
    return f"{position.get('exchange')}::{position.get('tradingsymbol')}"


def _extract_opt_type(position):
    symbol = str(position.get("tradingsymbol", "")).upper()
    if symbol.endswith("CE"):
        return "CE"
    if symbol.endswith("PE"):
        return "PE"
    return None


def _parse_strike_from_symbol(symbol):
    match = re.search(r"(\d+)(CE|PE)$", str(symbol).upper())
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _extract_instrument_details(position, instruments):
    token = position.get("instrument_token")
    if token is not None:
        try:
            token_int = int(token)
            by_token = next((inst for inst in instruments if int(inst.get("instrument_token", -1)) == token_int), None)
            if by_token:
                return by_token
        except Exception:
            pass
    symbol = position.get("tradingsymbol")
    return next((inst for inst in instruments if inst.get("tradingsymbol") == symbol), None)


def _determine_strike_step(name, same_family):
    normalized = str(name or "").upper()
    if "BANKNIFTY" in normalized:
        return INDEX_STRIKE_STEP["BANKNIFTY"]
    if "SENSEX" in normalized:
        return INDEX_STRIKE_STEP["SENSEX"]
    if "NIFTY" in normalized:
        return INDEX_STRIKE_STEP["NIFTY"]

    unique_strikes = sorted({float(inst.get("strike", 0)) for inst in same_family if float(inst.get("strike", 0)) > 0})
    diffs = []
    for i in range(1, len(unique_strikes)):
        diff = unique_strikes[i] - unique_strikes[i - 1]
        if diff > 0:
            diffs.append(diff)
    if diffs:
        return int(round(min(diffs)))
    return 50


def _compute_target_strike(current_strike, opt_type, shift_steps, strike_step):
    if opt_type == "CE":
        return float(current_strike) + (shift_steps * strike_step)
    if opt_type == "PE":
        return float(current_strike) - (shift_steps * strike_step)
    raise ValueError(f"Unsupported option type for shift: {opt_type}")


def exit_position(pos, side=None, quantity=None):
    try:
        total_qty = abs(int(pos.get("quantity", 0)))
        if total_qty <= 0:
            return []

        requested_qty = total_qty
        if quantity is not None:
            try:
                requested_qty = int(quantity)
            except (TypeError, ValueError):
                print(f"❌ Invalid exit quantity for {pos.get('tradingsymbol')}: {quantity}")
                return []
            if requested_qty <= 0:
                print(f"❌ Exit quantity must be positive for {pos.get('tradingsymbol')}: {requested_qty}")
                return []
            if requested_qty > total_qty:
                print(f"❌ Exit quantity {requested_qty} exceeds open {total_qty} for {pos.get('tradingsymbol')}")
                return []

        freeze_limit = 1755

        # Side is derived from current position direction to avoid accidental reversal.
        side = "BUY" if int(pos.get("quantity", 0)) < 0 else "SELL"
        order_ids = []

        for i in range(0, requested_qty, freeze_limit):
            chunk_qty = min(freeze_limit, requested_qty - i)

            print(f"🔁 Exiting {pos['tradingsymbol']} with {side}, Qty={chunk_qty}")
            start_ts = time.time()
            order_id = kite.place_order(
                exchange=pos["exchange"],
                tradingsymbol=pos["tradingsymbol"],
                transaction_type=side,
                quantity=chunk_qty,
                order_type="MARKET",
                product=pos["product"],
                variety="regular",
                market_protection=-1
            )
            elapsed = time.time() - start_ts
            print(f"✅ Exit order placed: {order_id} ({elapsed:.2f}s)")
            order_ids.append(order_id)
        return order_ids
    except Exception as e:
        print(f"❌ Error while exiting hedge {pos['tradingsymbol']}: {e}")
        return []


def _place_market_entry(order_template, quantity):
    freeze_limit = 1755
    order_ids = []
    for i in range(0, quantity, freeze_limit):
        chunk_qty = min(freeze_limit, quantity - i)
        order_id = kite.place_order(
            exchange=order_template["exchange"],
            tradingsymbol=order_template["tradingsymbol"],
            transaction_type=order_template["transaction_type"],
            quantity=chunk_qty,
            order_type="MARKET",
            product=order_template["product"],
            variety="regular",
            market_protection=-1
        )
        order_ids.append(order_id)
    return order_ids


def _open_option_positions_snapshot():
    positions = kite.positions()["net"]
    return [
        p for p in positions
        if p.get("quantity", 0) != 0
        and str(p.get("tradingsymbol", "")).upper().endswith(("CE", "PE"))
        and p.get("exchange") in ("NFO", "BFO")
    ]


def _resolve_open_position(open_positions, symbol, exchange=""):
    exchange_norm = str(exchange or "").strip().upper()
    if exchange_norm:
        matched = next(
            (
                p for p in open_positions
                if p.get("tradingsymbol") == symbol and p.get("exchange") == exchange_norm
            ),
            None
        )
        if matched:
            return matched
    candidates = [p for p in open_positions if p.get("tradingsymbol") == symbol]
    return candidates[0] if len(candidates) == 1 else None


def get_open_option_positions():
    option_positions = _open_option_positions_snapshot()

    result = []
    for p in option_positions:
        quantity = int(p.get("quantity", 0))
        result.append({
            "tradingsymbol": p.get("tradingsymbol"),
            "exchange": p.get("exchange"),
            "product": p.get("product"),
            "quantity": quantity,
            "side": "SHORT" if quantity < 0 else "LONG",
            "avg_price": p.get("average_price"),
        })
    result.sort(key=lambda item: (item["exchange"], item["tradingsymbol"]))
    return result


def shift_selected_legs(selected_legs, shift_steps):
    if not isinstance(shift_steps, int):
        raise ValueError("Shift must be an integer")
    if shift_steps == 0:
        raise ValueError("Shift cannot be 0")

    open_positions = _open_option_positions_snapshot()
    results = []

    def _shift_single_leg(leg):
        symbol = str(leg.get("tradingsymbol", "")).strip()
        exchange = str(leg.get("exchange", "")).strip().upper()
        if not symbol:
            return {
                "status": "failed",
                "old_symbol": "",
                "new_symbol": None,
                "error": "Missing tradingsymbol",
            }

        pos = _resolve_open_position(open_positions, symbol, exchange=exchange)
        if pos is None:
            return {
                "status": "failed",
                "old_symbol": symbol,
                "new_symbol": None,
                "error": "Position not found or already closed",
            }

        pos_exchange = pos.get("exchange")
        pos_symbol = pos.get("tradingsymbol")
        pos_qty = int(pos.get("quantity", 0))
        opt_type = _extract_opt_type(pos)
        if opt_type is None:
            return {
                "status": "failed",
                "old_symbol": pos_symbol,
                "new_symbol": None,
                "error": "Not an option leg",
            }

        try:
            instruments = _load_instruments(pos_exchange)
            current_inst = _extract_instrument_details(pos, instruments)
            if not current_inst:
                raise RuntimeError("Unable to resolve instrument metadata")

            current_strike = float(current_inst.get("strike", 0) or 0)
            if current_strike <= 0:
                parsed = _parse_strike_from_symbol(pos_symbol)
                if parsed is None:
                    raise RuntimeError("Unable to resolve current strike")
                current_strike = parsed

            same_family = [
                inst for inst in instruments
                if inst.get("exchange") == current_inst.get("exchange")
                and inst.get("expiry") == current_inst.get("expiry")
                and inst.get("name") == current_inst.get("name")
                and inst.get("instrument_type") == current_inst.get("instrument_type")
            ]
            strike_step = _determine_strike_step(current_inst.get("name"), same_family)
            target_strike = _compute_target_strike(current_strike, opt_type, shift_steps, strike_step)

            target_inst = next(
                (
                    inst for inst in same_family
                    if float(inst.get("strike", -1)) == float(target_strike)
                ),
                None
            )
            if not target_inst:
                raise RuntimeError(f"No target symbol for strike {int(target_strike)} {opt_type} same expiry")

            is_short = pos_qty < 0

            exit_order_ids = exit_position(pos, quantity=abs(pos_qty))
            if not exit_order_ids:
                raise RuntimeError("Square off failed")

            entry_qty = abs(pos_qty)
            requested_new_qty = leg.get("new_qty")
            if requested_new_qty is not None:
                try:
                    parsed_new_qty = int(requested_new_qty)
                except (TypeError, ValueError):
                    raise RuntimeError("Invalid new_qty for leg")
                if parsed_new_qty <= 0:
                    raise RuntimeError("new_qty must be positive")
                entry_qty = parsed_new_qty

            entry_side = "SELL" if is_short else "BUY"
            entry_order_ids = _place_market_entry({
                "exchange": pos_exchange,
                "tradingsymbol": target_inst["tradingsymbol"],
                "transaction_type": entry_side,
                "product": pos.get("product"),
            }, entry_qty)

            sl_place_result = {"placed": 0, "error": None}

            return {
                "status": "success",
                "old_symbol": pos_symbol,
                "new_symbol": target_inst["tradingsymbol"],
                "exchange": pos_exchange,
                "quantity": abs(pos_qty),
                "entry_quantity": entry_qty,
                "entry_side": entry_side,
                "target_strike": target_strike,
                "sl_placed": sl_place_result["placed"],
                "sl_error": sl_place_result["error"],
                "entry_order_ids": entry_order_ids,
            }
        except Exception as e:
            return {
                "status": "failed",
                "old_symbol": pos_symbol,
                "new_symbol": None,
                "exchange": pos_exchange,
                "error": str(e),
            }

    if len(selected_legs) > 1:
        max_workers = min(4, len(selected_legs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_shift_single_leg, leg) for leg in selected_legs]
            for future in as_completed(futures):
                results.append(future.result())
    else:
        for leg in selected_legs:
            results.append(_shift_single_leg(leg))

    succeeded = sum(1 for r in results if r.get("status") == "success")
    failed = sum(1 for r in results if r.get("status") == "failed")
    return {
        "requested": len(selected_legs),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def exit_selected_legs(selected_legs):
    open_positions = _open_option_positions_snapshot()
    results = []

    for leg in selected_legs:
        symbol = str(leg.get("tradingsymbol", "")).strip()
        exchange = str(leg.get("exchange", "")).strip().upper()
        if not symbol:
            results.append({
                "status": "failed",
                "tradingsymbol": "",
                "exchange": exchange,
                "error": "Missing tradingsymbol",
            })
            continue

        pos = _resolve_open_position(open_positions, symbol, exchange=exchange)
        if pos is None:
            results.append({
                "status": "failed",
                "tradingsymbol": symbol,
                "exchange": exchange,
                "error": "Position not found or already closed",
            })
            continue

        try:
            position_qty = abs(int(pos.get("quantity", 0)))
            order_ids = exit_position(pos, quantity=position_qty)
            results.append({
                "status": "success",
                "tradingsymbol": pos.get("tradingsymbol"),
                "exchange": pos.get("exchange"),
                "quantity": position_qty,
                "order_ids": order_ids,
            })
        except Exception as e:
            results.append({
                "status": "failed",
                "tradingsymbol": pos.get("tradingsymbol"),
                "exchange": pos.get("exchange"),
                "quantity": abs(int(pos.get("quantity", 0))),
                "error": str(e),
            })

    succeeded = sum(1 for item in results if item.get("status") == "success")
    failed = sum(1 for item in results if item.get("status") == "failed")
    return {
        "requested": len(selected_legs),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
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


def Exiting_position(positions):
    # This Function is called when Button is pressed to exit all positions at once, it will first exit all short legs and then long legs with concurrency to speed up the process.
    # global is_exiting
    # is_exiting = True
    try:
        print("Exiting all Postions...")

        short_legs = [p for p in positions if p['quantity'] < 0 and p['tradingsymbol'].endswith(("CE", "PE")) and p['exchange'] in ('BFO','NFO','MCX')]
        long_legs = [p for p in positions if p['quantity'] > 0 and p['tradingsymbol'].endswith(("CE", "PE")) and p['exchange'] in ('BFO','NFO','MCX')]

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
        send_telegram("Routine close: It's after 10 PM. Exiting all positions and shutting down.")
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
    
