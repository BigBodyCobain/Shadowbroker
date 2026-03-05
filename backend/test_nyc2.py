import requests, json

url = "https://api.us.socrata.com/api/catalog/v1?domains=data.cityofnewyork.us&q=camera"
try:
    r = requests.get(url)
    res = r.json().get('results', [])
    for d in res:
        print(f"{d['resource']['id']} - {d['resource']['name']}")
except Exception as e:
    print(e)
