import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv
import os


# Load base .env first (if exists)
load_dotenv()

# Detect environment
env = os.getenv("ENV")

if not env:
    print("❌ Environment variable 'ENV' not set (e.g., 'local' or 'prod'). Script closing.")
    sys.exit(1)

# Load environment-specific file
env_file = f".env.{env}"
if not os.path.exists(env_file):
    print(f"❌ Environment file '{env_file}' not found. Script closing.")
    sys.exit(1)

load_dotenv(env_file, override=True)

# Re-verify ENV from the specific file
env = os.getenv("ENV")



def system_close():
    print("System close command executed successfully.")
    try:
        # system_close.py is in <project>/Core/, so parent[1] is the project root.
        if env == "local":
            script_path = Path(__file__).parent / "Kill_Time.py"
        else:
            script_path = Path(__file__).parent / "Kill_Time_prod.py"
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




