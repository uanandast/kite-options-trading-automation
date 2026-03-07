from flask import Flask, render_template, jsonify, session, redirect, url_for, request
from threading import Thread, Lock
from Core.shared_resources import set_monitoring_state, get_monitoring_state
import time
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import sys
import importlib
import configparser
from kiteconnect import KiteConnect

app = Flask(__name__)

# Global variable to store the latest PnL
latest_iron_condor_data = {}
manual_exit_lock = Lock()
manual_exit_in_progress = False
manual_stoploss_lock = Lock()
manual_stoploss_in_progress = False
manual_cancel_sl_lock = Lock()
manual_cancel_sl_in_progress = False

kite_monitor_final = None
get_current_iron_condor = None
get_previous_day_close = None
margin = 0
previous_day_close = 0
name = "Unknown"


def _read_kite_credentials():
    config = configparser.ConfigParser()
    config.read('Cred/Cred_kite_PREM.ini')
    return config['Kite']['api_key']


def _read_access_token():
    token_path = Path("Cred/access_token.txt")
    if not token_path.exists():
        return None
    token = token_path.read_text().strip()
    return token or None


def verify_kite_connection():
    try:
        api_key = _read_kite_credentials()
        access_token = _read_access_token()
        if not access_token:
            print("⚠️ access_token.txt missing/empty.")
            return False

        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        kite.profile()
        print("✅ Kite connection check passed.")
        return True
    except Exception as e:
        print(f"❌ Kite connection check failed: {e}")
        return False


def run_login_script():
    login_path = Path(__file__).parent/"Auth" / "login.py"
    print("🔐 Running login.py to refresh access token...")
    subprocess.run([sys.executable, str(login_path)], check=True)


def ensure_kite_connection():
    if verify_kite_connection():
        return True

    try:
        run_login_script()
    except Exception as e:
        print(f"❌ Failed to run login.py: {e}")
        return False

    return verify_kite_connection()


def initialize_runtime():
    global kite_monitor_final, get_current_iron_condor, get_previous_day_close
    global margin, previous_day_close, name

    if not ensure_kite_connection():
        raise RuntimeError("Kite session unavailable even after running login.py")

    delta_module = importlib.import_module("Core.Delta_IV")
    kite_monitor_final = importlib.import_module("Core.Monitor")

    get_current_iron_condor = delta_module.get_current_iron_condor
    get_previous_day_close = delta_module.get_previous_day_close

    margin = kite_monitor_final.get_margin()
    previous_day_close, name = get_previous_day_close()

def monitor_spreads_loop():
    if kite_monitor_final is None:
        return
    if get_monitoring_state():
        return
    try:
        set_monitoring_state(True)
        kite_monitor_final.monitor_spreads()
    except Exception as e:
        print(f"❌ Error in monitor_spreads: {str(e)}")
        time.sleep(1)
    finally:
        set_monitoring_state(False)



def update_iron_condor_data():
    global latest_iron_condor_data
    if get_current_iron_condor is None:
        return
    refresh_interval_seconds = 0.2
    while True:
        try:
            result, net_delta, options_data, strangle_credit, future_price, Skew,delta,spot_price = get_current_iron_condor()

            latest_iron_condor_data = {
                'legs': result,
                'net_delta': round(net_delta, 4) if net_delta is not None else None,
                'chain': options_data,
                'strangle_credit': strangle_credit,
                'future_price': future_price,
                'skew': Skew,
                'delta':delta,
                'spot_price': spot_price

            }
            time.sleep(refresh_interval_seconds)
        except Exception as e:  
            print(f"Error in update_iron_condor_data: {str(e)}")
            time.sleep(2)  # Sleep longer on error
        

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/option_data')
def iron_condor_data():
    data = latest_iron_condor_data.copy()
    data['previous_close'] = previous_day_close
    data['symbol'] = name
    return jsonify(data)


@app.route('/pnl')
def pnl():
    try:
        if kite_monitor_final is None:
            return jsonify({"error": "Kite runtime not initialized"}), 503
        straddle_price = latest_iron_condor_data.get('strangle_credit', 0.0)
        data = {
            "net_pnl": kite_monitor_final.pnl_total if kite_monitor_final.pnl_total is not None else 0.0,
            "straddle_price": straddle_price if straddle_price is not None else 0.0,
            "timestamp": datetime.now().isoformat(),
            "Current_pos_credit": kite_monitor_final.Current_pos_credit if kite_monitor_final.Current_pos_credit is not None else 0.0,
            "margin": margin,
            "available_margin": getattr(kite_monitor_final, "available_margin", 0.0),
            "nifty_value": latest_iron_condor_data.get('spot_price', 0.0)
        }

        return jsonify(data)
    except Exception as e:
        print(f"Error in pnl endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500


def _format_cancel_sl_message(result):
    if result.get("requested", 0) == 0:
        return "No open SL orders to cancel"
    msg = f"Cancelled {result.get('cancelled', 0)} SL orders"
    if result.get("errors", 0) > 0:
        msg += f" ({result.get('errors', 0)} errors)"
    return msg


def _format_stoploss_message(result):
    if result.get("positions", 0) == 0:
        return "No option positions found for SL"
    msg = f"Placed {result.get('placed_orders', 0)} SL orders"
    if result.get("skipped", 0) > 0:
        msg += f", skipped {result.get('skipped', 0)} existing"
    if result.get("failed_positions", 0) > 0:
        msg += f" ({result.get('failed_positions', 0)} failed)"
    return msg


def _format_exit_message(result):
    if result.get("attempted", 0) == 0:
        return "No open positions to exit"
    msg = f"Exited {result.get('succeeded', 0)} legs"
    if result.get("failed", 0) > 0:
        msg += f" ({result.get('failed', 0)} failed)"
    return msg


@app.route('/manual_exit', methods=['POST'])
def manual_exit():
    global manual_exit_in_progress
    with manual_exit_lock:
        if manual_exit_in_progress:
            return jsonify({"message": "Manual exit is already in progress"}), 409
        manual_exit_in_progress = True

    try:
        if kite_monitor_final is None:
            return jsonify({"message": "Kite runtime not initialized"}), 503
        positions = kite_monitor_final.kite.positions()["net"]
        result = kite_monitor_final.Exiting_position(positions)
        return jsonify({"message": _format_exit_message(result), "details": result}), 200
    except Exception as e:
        print(f"❌ Error in manual exit: {str(e)}")
        return jsonify({"message": f"Manual exit failed: {str(e)}"}), 500
    finally:
        with manual_exit_lock:
            manual_exit_in_progress = False


@app.route('/manual_stoploss', methods=['POST'])
def manual_stoploss():
    global manual_stoploss_in_progress
    with manual_stoploss_lock:
        if manual_stoploss_in_progress:
            return jsonify({"message": "Manual stoploss is already in progress"}), 409
        manual_stoploss_in_progress = True

    try:
        if kite_monitor_final is None:
            return jsonify({"message": "Kite runtime not initialized"}), 503
        result = kite_monitor_final.stoploss_order_button()
        return jsonify({"message": _format_stoploss_message(result), "details": result}), 200
    except Exception as e:
        print(f"❌ Error in manual stoploss: {str(e)}")
        return jsonify({"message": f"Manual stoploss failed: {str(e)}"}), 500
    finally:
        with manual_stoploss_lock:
            manual_stoploss_in_progress = False


@app.route('/manual_cancel_sl', methods=['POST'])
def manual_cancel_sl():
    global manual_cancel_sl_in_progress
    with manual_cancel_sl_lock:
        if manual_cancel_sl_in_progress:
            return jsonify({"message": "Manual SL cancel is already in progress"}), 409
        manual_cancel_sl_in_progress = True

    try:
        if kite_monitor_final is None:
            return jsonify({"message": "Kite runtime not initialized"}), 503
        result = kite_monitor_final.cancel_all_sl_orders()
        return jsonify({"message": _format_cancel_sl_message(result), "details": result}), 200
    except Exception as e:
        print(f"❌ Error in manual SL cancel: {str(e)}")
        return jsonify({"message": f"Manual SL cancel failed: {str(e)}"}), 500
    finally:
        with manual_cancel_sl_lock:
            manual_cancel_sl_in_progress = False

# Run the monitoring loop in the background
if __name__ == '__main__':
    try:
        initialize_runtime()
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        sys.exit(1)

    thread1 = Thread(target=update_iron_condor_data, daemon=True)
    thread1.start()
    thread2 = Thread(target=monitor_spreads_loop, daemon=True)
    thread2.start()
    app.run(debug=False, port=5000)
