import requests
import traceback

try:
    print("Testing adsb.lol...")
    r = requests.get("https://api.adsb.lol/v2/lat/39.8/lon/-98.5/dist/100", timeout=15)
    print(f"Status: {r.status_code}")
    d = r.json()
    print(f"Aircraft: {len(d.get('ac', []))}")
except Exception as e:
    print(f"Error type: {type(e).__name__}")
    print(f"Error: {e}")
    traceback.print_exc()
