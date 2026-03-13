import os
import subprocess
import sys

"""Run app.py in background using nohup.

This script runs the same Python interpreter being used to run this script.
Output is written to nohup.out (or appended if it already exists).
"""

# Run under sudo/root to make stopping the process require sudo authentication.
# Note: this will prompt for your password when you run this script unless you already have
# a cached sudo credential.

cmd = ["nohup", sys.executable, "app.py"]

with open("nohup.out", "ab") as f:
    subprocess.Popen(
        cmd,
        stdout=f,
        stderr=f,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )

print("Started app.py in background via nohup (output -> nohup.out)")

