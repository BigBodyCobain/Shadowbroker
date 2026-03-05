import json
import subprocess
import os
import time
import sys

proxy_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ais_proxy.js")
API_KEY = "75cc39af03c9cc23c90e8a7b3c3bc2b2a507c5fb"

print(f"Proxy script: {proxy_script}")

process = subprocess.Popen(
    ['node', proxy_script, API_KEY],
    stdout=subprocess.PIPE, 
    stderr=subprocess.PIPE,
    text=True, 
    bufsize=1
)

import threading

def read_stderr():
    for line in iter(process.stderr.readline, ''):
        print(f"[STDERR] {line.strip()}", file=sys.stderr)

t = threading.Thread(target=read_stderr, daemon=True)
t.start()

print("Process started, reading stdout for 15 seconds...")
count = 0
start = time.time()
while time.time() - start < 15:
    line = process.stdout.readline()
    if not line:
        if process.poll() is not None:
            print(f"Process exited with code {process.returncode}")
            break
        continue
    line = line.strip()
    if not line:
        continue
    try:
        data = json.loads(line)
        msg_type = data.get("MessageType", "?")
        mmsi = data.get("MetaData", {}).get("MMSI", 0)
        count += 1
        if count <= 5:
            print(f"  MSG {count}: type={msg_type} mmsi={mmsi}")
    except json.JSONDecodeError as e:
        print(f"  BAD LINE: {line[:80]}...")

elapsed = time.time() - start
print(f"\nTotal {count} messages in {elapsed:.1f}s")
process.terminate()
