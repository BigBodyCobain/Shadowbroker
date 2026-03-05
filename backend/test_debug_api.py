import json
import urllib.request

try:
    data = json.loads(urllib.request.urlopen('http://localhost:8000/api/live-data').read())
    
    # Tracked flights
    tracked = data.get('tracked_flights', [])
    print(f"=== TRACKED FLIGHTS: {len(tracked)} ===")
    if tracked:
        colors = {}
        for t in tracked:
            c = t.get('alert_color', 'NONE')
            colors[c] = colors.get(c, 0) + 1
        print(f"  Colors: {colors}")
        print(f"  Sample: {json.dumps(tracked[0], indent=2)[:500]}")
    
    # Ships
    ships = data.get('ships', [])
    print(f"\n=== SHIPS: {len(ships)} ===")
    types = {}
    for s in ships:
        t = s.get('type', 'unknown')
        types[t] = types.get(t, 0) + 1
    print(f"  Types: {types}")
    if ships:
        print(f"  Sample: {json.dumps(ships[0], indent=2)[:300]}")
    
    # News
    news = data.get('news', [])
    print(f"\n=== NEWS: {len(news)} ===")
    
    # Earthquakes
    quakes = data.get('earthquakes', [])
    print(f"=== EARTHQUAKES: {len(quakes)} ===")
    
except Exception as e:
    print(f"Error: {e}")
