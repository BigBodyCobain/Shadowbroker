# Data Attribution & Licensing

ShadowBroker aggregates publicly available data from many third-party sources.
This file documents each source and its license so operators and users can
comply with the terms under which we access that data.

ShadowBroker itself is licensed under AGPL-3.0 (see `LICENSE`). **This file
concerns the *data* rendered by the dashboard, not the source code.**

---

## ODbL-licensed sources (Open Database License v1.0)

Data from these sources is licensed under the
[Open Database License v1.0](https://opendatacommons.org/licenses/odbl/1-0/).
If you redistribute a derivative database built from these sources, the
derivative must also be offered under ODbL and must preserve attribution.

| Source | URL | What we use it for |
|---|---|---|
| adsb.lol | https://adsb.lol | Military aircraft positions, regional commercial gap-fill, route enrichment |
| OpenStreetMap contributors | https://www.openstreetmap.org/copyright | Nominatim geocoding (LOCATE bar), CARTO basemap tiles (OSM-derived) |

**Attribution requirement:** the ShadowBroker map UI displays
"© OpenStreetMap contributors" and "adsb.lol (ODbL)" in the map attribution
control. Do not remove this attribution if you fork or redistribute the app.

---

## Other third-party data sources

These sources have their own terms; consult each link before redistributing.

| Source | URL | License / Terms | Notes |
|---|---|---|---|
| OpenSky Network | https://opensky-network.org | OpenSky API terms | Commercial and private aircraft tracking |
| CelesTrak | https://celestrak.org | Public domain / no restrictions | Satellite TLE data |
| USGS Earthquake Hazards | https://earthquake.usgs.gov | Public domain (US Federal) | Seismic events |
| NASA FIRMS | https://firms.modaps.eosdis.nasa.gov | NASA Open Data | Fire/thermal anomalies (VIIRS) |
| NASA GIBS | https://gibs.earthdata.nasa.gov | NASA Open Data | MODIS imagery tiles |
| NOAA SWPC | https://services.swpc.noaa.gov | Public domain (US Federal) | Space weather, Kp index |
| GDELT Project | https://www.gdeltproject.org | CC BY (non-commercial friendly) | Global conflict events |
| DeepState Map | https://deepstatemap.live | Per-site terms | Ukraine frontline GeoJSON |
| aisstream.io | https://aisstream.io | Free-tier API terms (attribution required) | AIS vessel positions |
| Global Fishing Watch | https://globalfishingwatch.org | CC BY 4.0 (for public data) | Fishing activity events |
| Microsoft Planetary Computer | https://planetarycomputer.microsoft.com | Sentinel-2 / ESA Copernicus terms | Sentinel-2 imagery |
| Copernicus CDSE (Sentinel Hub) | https://dataspace.copernicus.eu | ESA Copernicus open data terms | SAR + optical imagery |
| Shodan | https://www.shodan.io | Operator-supplied API key, Shodan ToS | Internet device search |
| Smithsonian GVP | https://volcano.si.edu | Attribution required | Volcanoes |
| OpenAQ | https://openaq.org | CC BY 4.0 | Air quality stations |
| NOAA NWS | https://www.weather.gov | Public domain (US Federal) | Severe weather alerts |
| WRI Global Power Plant DB | https://datasets.wri.org | CC BY 4.0 | Power plants |
| Wikidata | https://www.wikidata.org | CC0 | Head-of-state lookup |
| Wikipedia | https://en.wikipedia.org | CC BY-SA 4.0 | Region summaries |
| KiwiSDR (via dyatlov mirror) | http://rx.linkfanel.net | Per-site terms (community mirror by Pierre Ynard) | SDR receiver list — pulled from rx.linkfanel.net to keep load off jks-prv's bandwidth at kiwisdr.com |
| OpenMHZ | https://openmhz.com | Per-site terms | Police/fire scanner feeds |
| Meshtastic | https://meshtastic.org | Open Source | Mesh radio nodes (protocol) |
| Meshtastic Map (Liam Cottle) | https://meshtastic.liamcottle.net | Community project (per-site terms) | Global Meshtastic node positions — polled once per day with on-disk cache trust to minimize load on this volunteer-run HTTP API |
| APRS-IS | https://www.aprs-is.net | Open / attribution-based | Amateur radio positions |
| CARTO basemaps | https://carto.com | CARTO attribution required | Dark map tiles (OSM-derived) |
| Esri World Imagery | https://www.arcgis.com | Esri terms | High-res satellite basemap |
| IODA (Georgia Tech) | https://ioda.inetintel.cc.gatech.edu | Research/academic terms | Internet outage data |

---

## Contact

If you represent a data provider and have concerns about how ShadowBroker
uses your data, please open an issue or contact the maintainer at
`bigbodycobain@gmail.com`. We will respond promptly and, if needed, adjust
usage or remove the source.
