import requests
import json
import time
import cloudscraper

def scrape_openmhz_systems():
    print("Testing OpenMHZ undocumented API with Cloudscraper...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    
    try:
        # Step 1: Hit the public systems list that the front-end map uses
        res = scraper.get("https://api.openmhz.com/systems", headers=headers, timeout=15)
        json_data = res.json()
        systems = json_data.get('systems', []) if isinstance(json_data, dict) else []
        print(f"Successfully spoofed OpenMHZ frontend. Found {len(systems)} active police/fire systems.")
        
        if not systems:
            return
            
        # Inspect the first system (usually a major city)
        city = systems[0]
        sys_name = city.get('shortName')
        print(f"Targeting System: {city.get('name')} ({sys_name})")
        
        if not sys_name:
            return
            
        time.sleep(2) # Ethical delay
        
        # Step 2: Query the recent calls for this specific system
        # The frontend queries: https://api.openmhz.com/<system_name>/calls
        calls_url = f"https://api.openmhz.com/{sys_name}/calls"
        print(f"Fetching recent bursts: {calls_url}")
        
        call_res = scraper.get(calls_url, headers=headers, timeout=15)
        
        if call_res.status_code == 200:
            call_json = call_res.json()
            calls = call_json.get('calls', []) if isinstance(call_json, dict) else []
            if calls and len(calls) > 0:
                print(f"Intercepted {len(calls)} audio bursts.")
                latest = calls[0]
                print("LATEST INTERCEPT:")
                print(f"Talkgroup: {latest.get('talkgroupNum')}")
                print(f"Audio URL: {latest.get('url')}")
            else:
                 print("No recent calls found for this system.")
        else:
             print(f"Failed to fetch calls. HTTP {call_res.status_code}")
             
    except Exception as e:
        print(f"Scrape Exception: {e}")

if __name__ == "__main__":
    scrape_openmhz_systems()
