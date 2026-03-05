import requests

def test_openmhz():
    print("Testing OpenMHZ...")
    res = requests.get("https://api.openmhz.com/systems")
    if res.status_code == 200:
        data = res.json()
        print(f"OpenMHZ returned {len(data)} systems.")
        print(f"Example: {data[0]['name']} ({data[0]['shortName']})")
    else:
        print(f"OpenMHZ Failed: {res.status_code}")

def test_scanner_radio():
    print("Testing Scanner Radio...")
    # Gordon Edwards app often uses something like this
    # We will just try broadcastify public page scrape as a secondary fallback
    pass

test_openmhz()
