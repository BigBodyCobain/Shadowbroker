import json, urllib.request

data = json.loads(urllib.request.urlopen('http://localhost:8000/api/live-data').read())
print(f"Commercial flights: {len(data.get('commercial_flights', []))}")
print(f"Private flights: {len(data.get('private_flights', []))}")
print(f"Private jets: {len(data.get('private_jets', []))}")
print(f"Military flights: {len(data.get('military_flights', []))}")
print(f"Tracked flights: {len(data.get('tracked_flights', []))}")
print(f"Ships: {len(data.get('ships', []))}")
print(f"CCTV: {len(data.get('cctv', []))}")
