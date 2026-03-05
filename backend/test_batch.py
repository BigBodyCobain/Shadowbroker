import requests
import json

# Step 1: Fetch some real flights from adsb.lol
print("Fetching real flights from adsb.lol...")
r = requests.get("https://api.adsb.lol/v2/lat/39.8/lon/-98.5/dist/250", timeout=10)
data = r.json()
ac = data.get("ac", [])
print("Got", len(ac), "aircraft")

# Step 2: Build a batch of real callsigns
planes = []
for f in ac[:20]:  # Just 20 real flights
    cs = str(f.get("flight", "")).strip()
    lat = f.get("lat")
    lon = f.get("lon")
    if cs and lat and lon:
        planes.append({"callsign": cs, "lat": lat, "lng": lon})

print("Built batch of", len(planes), "planes")
print("Sample plane:", json.dumps(planes[0]) if planes else "NONE")

# Step 3: Test routeset with real data
if planes:
    payload = {"planes": planes}
    print("Payload size:", len(json.dumps(payload)), "bytes")
    r2 = requests.post("https://api.adsb.lol/api/0/routeset", json=payload, timeout=15)
    print("Routeset HTTP:", r2.status_code)
    if r2.status_code == 200:
        result = r2.json()
        print("Response type:", type(result).__name__)
        print("Routes found:", len(result) if isinstance(result, list) else "dict")
        if isinstance(result, list) and len(result) > 0:
            print("First route:", json.dumps(result[0], indent=2))
    else:
        print("Error body:", r2.text[:500])

# Step 4: Test with bigger batch
print("\n--- Testing with 100 real flights ---")
planes100 = []
for f in ac[:120]:
    cs = str(f.get("flight", "")).strip()
    lat = f.get("lat")
    lon = f.get("lon")
    if cs and lat and lon:
        planes100.append({"callsign": cs, "lat": lat, "lng": lon})
planes100 = planes100[:100]

print("Built batch of", len(planes100), "planes")
r3 = requests.post("https://api.adsb.lol/api/0/routeset", json={"planes": planes100}, timeout=15)
print("Routeset HTTP:", r3.status_code)
if r3.status_code == 200:
    result3 = r3.json()
    print("Routes found:", len(result3) if isinstance(result3, list) else "dict")
else:
    print("Error body:", r3.text[:500])
