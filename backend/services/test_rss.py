import feedparser
import requests
import re

feeds = {
    "NPR": "https://feeds.npr.org/1004/rss.xml",
    "BBC": "http://feeds.bbci.co.uk/news/world/rss.xml"
}

keyword_coords = {
    "venezuela": (7.119, -66.589), "brazil": (-14.235, -51.925), "argentina": (-38.416, -63.616),
    "colombia": (4.570, -74.297), "mexico": (23.634, -102.552), "united states": (38.907, -77.036),
    " usa ": (38.907, -77.036), " us ": (38.907, -77.036), "washington": (38.907, -77.036),
    "canada": (56.130, -106.346), "ukraine": (49.487, 31.272), "kyiv": (50.450, 30.523),
    "russia": (61.524, 105.318), "moscow": (55.755, 37.617), "israel": (31.046, 34.851),
    "gaza": (31.416, 34.333), "iran": (32.427, 53.688), "lebanon": (33.854, 35.862),
    "syria": (34.802, 38.996), "yemen": (15.552, 48.516), "china": (35.861, 104.195),
    "beijing": (39.904, 116.407), "taiwan": (23.697, 120.960), "north korea": (40.339, 127.510),
    "south korea": (35.907, 127.766), "pyongyang": (39.039, 125.762), "seoul": (37.566, 126.978),
    "japan": (36.204, 138.252), "afghanistan": (33.939, 67.709), "pakistan": (30.375, 69.345),
    "india": (20.593, 78.962), " uk ": (55.378, -3.435), "london": (51.507, -0.127),
    "france": (46.227, 2.213), "paris": (48.856, 2.352), "germany": (51.165, 10.451),
    "berlin": (52.520, 13.405), "sudan": (12.862, 30.217), "congo": (-4.038, 21.758),
    "south africa": (-30.559, 22.937), "nigeria": (9.082, 8.675), "egypt": (26.820, 30.802),
    "zimbabwe": (-19.015, 29.154), "australia": (-25.274, 133.775), "middle east": (31.500, 34.800),
    "europe": (48.800, 2.300), "africa": (0.000, 25.000), "america": (38.900, -77.000),
    "south america": (-14.200, -51.900), "asia": (34.000, 100.000),
    "california": (36.778, -119.417), "texas": (31.968, -99.901), "florida": (27.994, -81.760),
    "new york": (40.712, -74.006), "virginia": (37.431, -78.656),
    "british columbia": (53.726, -127.647), "ontario": (51.253, -85.323), "quebec": (52.939, -73.549),
    "delhi": (28.704, 77.102), "new delhi": (28.613, 77.209), "mumbai": (19.076, 72.877),
    "shanghai": (31.230, 121.473), "hong kong": (22.319, 114.169), "istanbul": (41.008, 28.978),
    "dubai": (25.204, 55.270), "singapore": (1.352, 103.819)
}

for name, url in feeds.items():
    r = requests.get(url)
    feed = feedparser.parse(r.text)
    for entry in feed.entries[:10]: 
        title = entry.get('title', '')
        summary = entry.get('summary', '')
        text = (title + " " + summary).lower()
        padded_text = f" {text} "
        
        matched_kw = None
        for kw, coords in keyword_coords.items():
            if kw.startswith(" ") or kw.endswith(" "):
                if kw in padded_text:
                    matched_kw = kw
                    break
            else:
                if re.search(r'\b' + re.escape(kw) + r'\b', text):
                    matched_kw = kw
                    break
        print(f"[{name}] {title}\n  Matched: {matched_kw}\n  Text: {text}\n")
