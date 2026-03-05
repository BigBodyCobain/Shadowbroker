import requests

regions = [
    {"lat": 39.8, "lon": -98.5, "dist": 2000},  # USA
    {"lat": 50.0, "lon": 15.0, "dist": 2000},   # Europe
    {"lat": 35.0, "lon": 105.0, "dist": 2000}   # Asia / China
]

for r in regions:
    url = f"https://api.adsb.lol/v2/lat/{r['lat']}/lon/{r['lon']}/dist/{r['dist']}"
    res = requests.get(url, timeout=10)
    if res.status_code == 200:
        data = res.json()
        acs = data.get("ac", [])
        print(f"Region lat:{r['lat']} lon:{r['lon']} dist:{r['dist']} -> Flights: {len(acs)}")
    else:
        print(f"Error for Region lat:{r['lat']} lon:{r['lon']}: HTTP {res.status_code}")
