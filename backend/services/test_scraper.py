import requests
from bs4 import BeautifulSoup
import json

def scrape_broadcastify_top():
    print("Scraping Broadcastify Top Feeds...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        # The top 50 feeds page provides a wealth of listening data
        res = requests.get("https://www.broadcastify.com/listen/top", headers=headers, timeout=10)
        if res.status_code != 200:
            print(f"Failed HTTP {res.status_code}")
            return []
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # The table of feeds is in a standard class
        table = soup.find('table', {'class': 'btable'})
        if not table:
            print("Could not find feeds table.")
            return []
            
        feeds = []
        rows = table.find_all('tr')[1:] # Skip header
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 5:
                # Top layout: [Listeners, Feed ID (hidden), Location, Feed Name, Category, Genre]
                listeners_str = cols[0].text.strip().replace(',', '')
                listeners = int(listeners_str) if listeners_str.isdigit() else 0
                
                # The link is usually in the Feed Name column
                link_tag = cols[2].find('a')
                if not link_tag:
                    continue
                    
                href = link_tag.get('href', '')
                feed_id = href.split('/')[-1] if '/listen/feed/' in href else None
                
                if not feed_id:
                    continue
                    
                location = cols[1].text.strip()
                name = cols[2].text.strip()
                
                feeds.append({
                    "id": feed_id,
                    "listeners": listeners,
                    "location": location,
                    "name": name,
                    "stream_url": f"https://broadcastify.cdnstream1.com/{feed_id}"
                })
                
        print(f"Successfully scraped {len(feeds)} top feeds.")
        return feeds
        
    except Exception as e:
        print(f"Scrape error: {e}")
        return []

if __name__ == "__main__":
    top_feeds = scrape_broadcastify_top()
    print(json.dumps(top_feeds[:3], indent=2))
