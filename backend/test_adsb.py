import requests
import time
import math
import random

def test_fetch_and_triangulate():
    t0 = time.time()
    url = "https://api.adsb.lol/v2/lat/39.8/lon/-98.5/dist/1000"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        print(f"Downloaded in {time.time() - t0:.2f}s")
        if "ac" in data:
            sampled = data["ac"]
            print("Flights:", len(sampled))
        else:
            print("No 'ac' in response:", data)

        
        # Load airports (mock for test)
        airports = [{"lat": random.uniform(-90, 90), "lng": random.uniform(-180, 180), "iata": f"A{i}"} for i in range(4000)]
        
        t1 = time.time()
        for f in sampled:
            lat = f.get("lat")
            lng = f.get("lon")
            heading = f.get("track", 0)
            if lat is None or lng is None: continue
            
            # Project 15 degrees (~1000 miles) backwards and forwards
            dist_deg = 15.0
            h_rad = math.radians(heading)
            dy = math.cos(h_rad) * dist_deg
            dx = math.sin(h_rad) * dist_deg
            cos_lat = max(0.2, math.cos(math.radians(lat)))
            
            origin_lat = lat - dy
            origin_lng = lng - (dx / cos_lat)
            
            dest_lat = lat + dy
            dest_lng = lng + (dx / cos_lat)
            
            # Find closest origin airport
            best_o, min_o = None, float('inf')
            for a in airports:
                d = (a['lat'] - origin_lat)**2 + (a['lng'] - origin_lng)**2
                if d < min_o: min_o = d; best_o = a
                
            # Find closest dest airport
            best_d, min_d = None, float('inf')
            for a in airports:
                d = (a['lat'] - dest_lat)**2 + (a['lng'] - dest_lng)**2
                if d < min_d: min_d = d; best_d = a
                
        print(f"Triangulated 500 flights against {len(airports)} airports in {time.time() - t1:.2f}s")
    except Exception as e:
        print("Error:", e)

test_fetch_and_triangulate()
