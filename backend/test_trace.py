"""Test trace endpoints with explicit output."""
import json, subprocess

hex_code = "a34bac"  # DOJ166

from datetime import datetime, timezone
now = datetime.now(timezone.utc)
date_str = now.strftime("%Y/%m/%d")
hex_prefix = hex_code[-2:]

# Test 1: adsb.fi trace_full
url1 = f"https://globe.adsb.fi/data/traces/{date_str}/{hex_prefix}/trace_full_{hex_code}.json"
print(f"URL1: {url1}")
r = subprocess.run(["curl.exe", "-s", "--max-time", "10", url1], capture_output=True, text=True, timeout=15)
if r.stdout.strip().startswith("{"):
    data = json.loads(r.stdout)
    print(f"SUCCESS! Keys: {list(data.keys())}")
    if 'trace' in data:
        pts = data['trace']
        print(f"Trace points: {len(pts)}")
        if pts:
            print(f"FIRST (takeoff): {pts[0]}")
            print(f"LAST (now): {pts[-1]}")
else:
    print(f"Not JSON (first 100 chars): {r.stdout[:100]}")
    # That response was behind cloudflare, try adsb.lol instead
    
# Test 2: adsb.lol hex lookup
url2 = f"https://api.adsb.lol/v2/hex/{hex_code}"
print(f"\nURL2: {url2}")
r2 = subprocess.run(["curl.exe", "-s", "--max-time", "10", url2], capture_output=True, text=True, timeout=15)
if r2.stdout.strip().startswith("{"):
    data = json.loads(r2.stdout)
    if 'ac' in data and data['ac']:
        ac = data['ac'][0]
        keys = sorted(ac.keys())
        print(f"All keys ({len(keys)}): {keys}")
else:
    print(f"Not JSON: {r2.stdout[:100]}")

# Test 3: Try adsb.lol trace 
url3 = f"https://api.adsb.lol/trace/{hex_code}"
print(f"\nURL3: {url3}")
r3 = subprocess.run(["curl.exe", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10", url3], capture_output=True, text=True, timeout=15)
print(f"HTTP status: {r3.stdout}")

# Test 4: Try globe.adsb.lol format
url4 = f"https://globe.adsb.lol/data/traces/{date_str}/{hex_prefix}/trace_full_{hex_code}.json"
print(f"\nURL4: {url4}")
r4 = subprocess.run(["curl.exe", "-s", "--max-time", "10", url4], capture_output=True, text=True, timeout=15)
if r4.stdout.strip().startswith("{"):
    data = json.loads(r4.stdout)
    print(f"SUCCESS! Keys: {list(data.keys())}")
    if 'trace' in data:
        pts = data['trace']
        print(f"Trace points: {len(pts)}")
        if pts:
            print(f"FIRST (takeoff): {pts[0]}")
            print(f"LAST (now): {pts[-1]}")
else:
    print(f"Response: {r4.stdout[:150]}")
