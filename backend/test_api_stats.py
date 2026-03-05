import json
import urllib.request
import time

time.sleep(5)
try:
    data = urllib.request.urlopen('http://localhost:8000/api/live-data').read()
    d = json.loads(data)
    print(f"News: {len(d.get('news', []))} | Earthquakes: {len(d.get('earthquakes', []))} | Satellites: {len(d.get('satellites', []))} | CCTV: {len(d.get('cctv', []))}")
except Exception as e:
    print(f"Error fetching API: {e}")
