import json
import urllib.request
import time

time.sleep(5)
try:
    data = urllib.request.urlopen('http://localhost:8000/api/live-data').read()
    d = json.loads(data)
    ships = d.get('ships', [])
    print(f"Ships: {len(ships)}")
except Exception as e:
    print(f"Error fetching API: {e}")
