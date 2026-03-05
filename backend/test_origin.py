import json, urllib.request

data = json.loads(urllib.request.urlopen('http://localhost:8000/api/live-data').read())

# Check trail data
comm = data.get('commercial_flights', [])
mil = data.get('military_flights', [])
tracked = data.get('tracked_flights', [])
pvt = data.get('private_flights', [])

# Count flights with trails
comm_trails = [f for f in comm if f.get('trail') and len(f['trail']) > 0]
mil_trails = [f for f in mil if f.get('trail') and len(f['trail']) > 0]
tracked_trails = [f for f in tracked if f.get('trail') and len(f['trail']) > 0]
pvt_trails = [f for f in pvt if f.get('trail') and len(f['trail']) > 0]

print(f"Commercial: {len(comm)} total, {len(comm_trails)} with trails")
print(f"Military: {len(mil)} total, {len(mil_trails)} with trails")
print(f"Tracked: {len(tracked)} total, {len(tracked_trails)} with trails")
print(f"Private: {len(pvt)} total, {len(pvt_trails)} with trails")

# Show a sample trail
if mil_trails:
    f = mil_trails[0]
    print(f"\nSample trail ({f['callsign']}):")
    print(f"  Points: {len(f['trail'])}")
    if f['trail']:
        print(f"  First: {f['trail'][0]}")
        print(f"  Last: {f['trail'][-1]}")

# Check for grounded planes
grounded = [f for f in comm if f.get('alt', 999) <= 500 and f.get('speed_knots', 999) < 30]
print(f"\nGrounded commercial: {len(grounded)}")
if grounded:
    g = grounded[0]
    print(f"  Example: {g['callsign']} alt={g.get('alt')} speed={g.get('speed_knots')}")
