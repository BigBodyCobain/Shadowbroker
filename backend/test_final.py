import json
import urllib.request

try:
    data = json.loads(urllib.request.urlopen('http://localhost:8000/api/live-data').read())
    
    tracked = data.get('tracked_flights', [])
    colors = {}
    for t in tracked:
        c = t.get('alert_color', 'NONE')
        colors[c] = colors.get(c, 0) + 1
    print(f"TRACKED FLIGHTS: {len(tracked)} | Colors: {colors}")
    
    ships = data.get('ships', [])
    types = {}
    for s in ships:
        t = s.get('type', 'unknown')
        types[t] = types.get(t, 0) + 1
    print(f"SHIPS: {len(ships)} | Types: {types}")
    
    print(f"NEWS: {len(data.get('news', []))} | EARTHQUAKES: {len(data.get('earthquakes', []))} | CCTV: {len(data.get('cctv', []))}")
except Exception as e:
    print(f"Error: {e}")
