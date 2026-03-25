import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv
import os



# Detect environment FIRST (must come from system or default file name)
env = os.getenv("ENV")

# If ENV is not set, try to infer from existing env files
if not env:
    if os.path.exists(".env.local"):
        env = "local"
    elif os.path.exists(".env.lightsail"):
        env = "lightsail"
    else:
        print("❌ ENV not set and no .env.local or .env.lightsail found. Script closing.")
        sys.exit(1)

# Now load the correct env file
env_file = f".env.{env}"
if not os.path.exists(env_file):
    print(f"❌ Environment file '{env_file}' not found. Script closing.")
    sys.exit(1)

load_dotenv(env_file, override=True)

# Confirm ENV after loading
env = os.getenv("ENV")

def system_close():
    print("System close command executed successfully.")
    try:
        # system_close.py is in <project>/Core/, so parent[1] is the project root.
        if env == "local":
            script_path = Path(__file__).parent / "Kill_Time.py"
        else:
            script_path = Path(__file__).parent / "Kill_Time_Prod.py"
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




