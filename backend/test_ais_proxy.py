import json
import subprocess
import os
import time

proxy_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ais_proxy.js")
API_KEY = "75cc39af03c9cc23c90e8a7b3c3bc2b2a507c5fb"

print(f"Proxy script: {proxy_script}")
print(f"Exists: {os.path.exists(proxy_script)}")

process = subprocess.Popen(
    ['node', proxy_script, API_KEY],
    stdout=subprocess.PIPE, 
    stderr=subprocess.PIPE,  # Separate stderr!
    text=True, 
    bufsize=1
)

print("Process started, reading stdout...")
count = 0
start = time.time()
for line in iter(process.stdout.readline, ''):
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
        if count == 20:
            elapsed = time.time() - start
            print(f"\nReceived {count} messages in {elapsed:.1f}s — proxy is working!")
            process.terminate()
            break
    except json.JSONDecodeError as e:
        print(f"  BAD JSON: {line[:100]}... err={e}")

if count == 0:
    # Check stderr
    stderr_out = process.stderr.read()
    print(f"Zero messages received. stderr: {stderr_out[:500]}")
