import requests

try:
    print('Testing Seattle SDOT...')
    r_sea = requests.get('https://data.seattle.gov/resource/65fc-btcc.json?$limit=5', headers={'X-App-Token': 'f2jdDBw5JMXPFOQyk64SKlPkn'})
    print(r_sea.status_code)
    try:
        print(r_sea.json()[0])
    except:
        pass
except:
    pass

try:
    print('Testing NYC 511...')
    r_nyc = requests.get('https://webcams.nyctmc.org/api/cameras', timeout=5)
    print(r_nyc.status_code)
    try:
        print(len(r_nyc.json()))
        print(r_nyc.json()[0])
    except:
        pass
except:
    pass
