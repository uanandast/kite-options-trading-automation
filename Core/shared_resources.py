from threading import Lock
from copy import deepcopy

# Shared lock for monitoring
monitor_lock = Lock()

# Thread-safe monitoring flag
is_monitoring = False
is_processing = False
is_shutting_down = False
option_instrument_cache = {}

def set_monitoring_state(state):
    global is_monitoring
    with monitor_lock:
        is_monitoring = state
        return is_monitoring

def get_monitoring_state():
    with monitor_lock:
        return is_monitoring

def set_processing_state(state):
    global is_processing
    with monitor_lock:
        is_processing = state
        return is_processing

def get_processing_state():
    with monitor_lock:
        return is_processing

def set_shutdown_state(state):
    global is_shutting_down
    with monitor_lock:
        is_shutting_down = state
        return is_shutting_down

def get_shutdown_state():
    with monitor_lock:
        return is_shutting_down

def set_option_instrument_cache(exchange, instruments):
    exchange_norm = str(exchange or "").strip().upper()
    if not exchange_norm:
        return 0
    with monitor_lock:
        option_instrument_cache[exchange_norm] = deepcopy(list(instruments or []))
        return len(option_instrument_cache[exchange_norm])

def get_option_instrument_cache(exchange=None):
    exchange_norm = str(exchange or "").strip().upper()
    with monitor_lock:
        if exchange_norm:
            return deepcopy(option_instrument_cache.get(exchange_norm, []))
        return deepcopy(option_instrument_cache)

def clear_option_instrument_cache(exchange=None):
    exchange_norm = str(exchange or "").strip().upper()
    with monitor_lock:
        if exchange_norm:
            option_instrument_cache.pop(exchange_norm, None)
            return
        option_instrument_cache.clear()

# Other shared resources can be added here
