import os
import subprocess
import sys

"""Run app.py in background using nohup.

This script runs the same Python interpreter being used to run this script.
Output is written to nohup.out (or appended if it already exists).
"""

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

