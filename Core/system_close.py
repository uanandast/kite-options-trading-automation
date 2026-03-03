import subprocess
import sys
from pathlib import Path

def system_close():
    print("System close command executed successfully.")
    try:
        # system_close.py is in <project>/Core/, so parent[1] is the project root.
        script_path = Path(__file__).parent / "Kill_Time.py"
        if not script_path.exists():
            print(f"Target script not found: {script_path}")
            return
        subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True  # Detaches process from parent
        )
    except Exception as e:
        print(f"Error starting background process: {e}")

if __name__ == "__main__":
    try:
        system_close()
    except Exception as e:
        print(f"Error executing system close command: {e}")




