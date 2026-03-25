import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv
import os


# Load base .env first (if exists)
load_dotenv()

# Detect environment (default = local)
env = os.getenv("ENV", "local")

# Load environment-specific file
env_file = f".env.{env}"
if os.path.exists(env_file):
    load_dotenv(env_file, override=True)

# Re-read ENV after loading correct file
env = os.getenv("ENV", "local")


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




