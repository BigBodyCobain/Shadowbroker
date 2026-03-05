import requests, json

print("Searching Socrata NYC/Seattle Cameras...")
try:
    url = "https://api.us.socrata.com/api/catalog/v1?q=traffic cameras&limit=100"
    r = requests.get(url)
    res = r.json().get('results', [])
    for d in res:
        domain = d['metadata']['domain'].lower()
        if 'seattle' in domain or 'newyork' in domain or 'nyc' in domain:
            print(f"{d['resource']['id']} - {d['resource']['name']} ({domain})")
except Exception as e:
    print(e)
