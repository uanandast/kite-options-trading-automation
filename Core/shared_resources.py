from threading import Lock

# Shared lock for monitoring
monitor_lock = Lock()

# Thread-safe monitoring flag
is_monitoring = False
is_processing = False
is_shutting_down = False

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

# Other shared resources can be added here 