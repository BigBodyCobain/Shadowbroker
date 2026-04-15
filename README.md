<p align="center">
  <h1 align="center">🛰️ S H A D O W B R O K E R</h1>
  <p align="center"><strong>Global Threat Intercept — Real-Time Geospatial Intelligence Platform</strong></p>
  <p align="center">

  </p>
</p>

---




https://github.com/user-attachments/assets/248208ec-62f7-49d1-831d-4bd0a1fa6852





**ShadowBroker** is a real-time, multi-domain OSINT dashboard that fuses 60+ live intelligence feeds into a single dark-ops map interface. Aircraft, ships, satellites, conflict zones, CCTV networks, GPS jamming, internet-connected devices, police scanners, mesh radio nodes, and breaking geopolitical events — all updating in real time on one screen.

Built with **Next.js**, **MapLibre GL**, **FastAPI**, and **Python**. 35+ toggleable data layers. Right-click any point on Earth for a region/country dossier, head-of-state lookup, and the latest Sentinel-2 satellite photo. No user data is collected or transmitted — the dashboard runs entirely in your browser against a self-hosted backend.

Designed for analysts, researchers, radio operators, and anyone who wants to see what the world looks like when every public signal is on the same map.


## Why This Exists

A surprising amount of global telemetry is already public — aircraft ADS-B broadcasts, maritime AIS signals, satellite orbital data, earthquake sensors, mesh radio networks, police scanner feeds, environmental monitoring stations, internet infrastructure telemetry, and more. This data is scattered across dozens of tools and APIs. ShadowBroker combines all of it into a single interface.

The project does not introduce new surveillance capabilities — it aggregates and visualizes existing public datasets. It is fully open-source so anyone can audit exactly what data is accessed and how. No user data is collected or transmitted — everything runs locally against a self-hosted backend. No telemetry, no analytics, no accounts.

### Shodan Connector

ShadowBroker includes an optional Shodan connector for operator-supplied API access. Shodan results are fetched with your own `SHODAN_API_KEY`, rendered as a local investigative overlay (not merged into core feeds), and remain subject to Shodan’s terms of service.

---

## Interesting Use Cases

* **Transmit on the InfoNet testnet** — the first decentralized intelligence mesh built into an OSINT tool. Obfuscated messaging with gate personas, Dead Drop peer-to-peer exchange, and a built-in terminal CLI. No accounts, no signup. Privacy is not guaranteed yet — this is an experimental testnet — but the protocol is live and being hardened.
* **Track Air Force One**, the private jets of billionaires and dictators, and every military tanker, ISR, and fighter broadcasting ADS-B — with automatic holding pattern detection when aircraft start circling
* **Estimate where US aircraft carriers are** using automated GDELT news scraping — no other open tool does this
* **Search internet-connected devices worldwide** via Shodan — cameras, SCADA systems, databases — plotted as a live overlay on the map
* **Right-click anywhere on Earth** for a country dossier (head of state, population, languages), Wikipedia summary, and the latest Sentinel-2 satellite photo at 10m resolution
* **Click a KiwiSDR node** and tune into live shortwave radio directly in the dashboard. Click a police scanner feed and eavesdrop in one click.
* **Watch 11,000+ CCTV cameras** across 6 countries — London, NYC, California, Spain, Singapore, and more — streaming live on the map
* **See GPS jamming zones** in real time — derived from NAC-P degradation analysis of aircraft transponder data
* **Monitor satellites overhead** color-coded by mission type — military recon, SIGINT, SAR, early warning, space stations — with SatNOGS and TinyGS ground station networks
* **Track naval traffic** including 25,000+ AIS vessels, fishing activity via Global Fishing Watch, and billionaire superyachts
* **Follow earthquakes, volcanic eruptions, active wildfires** (NASA FIRMS), severe weather alerts, and air quality readings worldwide
* **Map military bases, 35,000+ power plants**, 2,000+ data centers, and internet outage regions — cross-referenced automatically
* **Connect to Meshtastic mesh radio nodes** and APRS amateur radio networks — visible on the map and integrated into Mesh Chat
* **Switch visual modes** — DEFAULT, SATELLITE, FLIR (thermal), NVG (night vision), CRT (retro terminal) — via the STYLE button
* **Track trains** across the US (Amtrak) and Europe (DigiTraffic) in real time

---

## ⚡ Quick Start (Docker)

```bash
git clone https://github.com/BigBodyCobain/Shadowbroker.git
cd Shadowbroker
docker compose pull
docker compose up -d
```

Open `http://localhost:3000` to view the dashboard! *(Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) or Docker Engine)*

> **Podman users:** Replace `docker compose` with `podman compose`, or use the `compose.sh` wrapper which auto-detects your engine. Force Podman with `./compose.sh --engine podman up -d`.

---

##  🔄 **How to Update**

ShadowBroker uses pre-built Docker images — no local building required. Updating takes seconds:

```bash
docker compose pull
docker compose up -d
```

That's it. `pull` grabs the latest images, `up -d` restarts the containers.

> **Coming from an older version?** Pull the latest repo code first, then pull images:
>
> ```bash
> git pull origin main
> docker compose down
> docker compose pull
> docker compose up -d
> ```

### ⚠️ **Stuck on the old version?**

**If `git pull` fails or `docker compose up` keeps building from source instead of pulling images**, your clone predates a March 2026 repository migration that rewrote commit history. A normal `git pull` cannot fix this. Run:

```bash
# Back up any local config you want to keep (.env, etc.)
cd ..
rm -rf Shadowbroker
git clone https://github.com/BigBodyCobain/Shadowbroker.git
cd Shadowbroker
docker compose pull
docker compose up -d
```

**How to tell if you're affected:** If `docker compose up` shows `RUN apt-get`, `RUN npm ci`, or `RUN pip install` — it's building from source instead of pulling pre-built images. You need a fresh clone.

**Other troubleshooting:**

* **Force re-pull:** `docker compose pull --no-cache`
* **Prune old images:** `docker image prune -f`
* **Check logs:** `docker compose logs -f backend`

---

### **☸️ Kubernetes / Helm (Advanced)**

For high-availability deployments or home-lab clusters, ShadowBroker supports deployment via **Helm**. This chart is based on the `bjw-s-labs` template and provides a robust, modular setup for both the backend and frontend.

**1. Add the Repository:**
```bash
helm repo add bjw-s-labs https://bjw-s-labs.github.io/helm-charts/
helm repo update
```

**2. Install the Chart:**
```bash
# Install from the local helm/chart directory
helm install shadowbroker ./helm/chart --create-namespace --namespace shadowbroker
```

**3. Key Features:**
*   **Modular Architecture:** Individually scale the intelligence backend and the HUD frontend.
*   **Security Context:** Runs with restricted UIDs (1001) for container hardening.
*   **Ingress Ready:** Compatible with Traefik, Cert-Manager, and Gateway API for secure, external access to your intelligence node.

*Special thanks to [@chr0n1x](https://github.com/chr0n1x) for contributing the initial Kubernetes architecture.*

---

## Experimental Testnet — No Privacy Guarantee

ShadowBroker v0.9.6 introduces **InfoNet**, a decentralized intelligence mesh with obfuscated messaging. This is an **experimental testnet** — not a private messenger.

| Channel | Privacy Status | Details |
|---|---|---|
| **Meshtastic / APRS** | **PUBLIC** | RF radio transmissions are public and interceptable by design. |
| **InfoNet Gate Chat** | **OBFUSCATED** | Messages are obfuscated with gate personas and canonical payload signing, but NOT end-to-end encrypted. Metadata is not hidden. |
| **Dead Drop DMs** | **STRONGEST CURRENT LANE** | Token-based epoch mailbox with SAS word verification. Strongest lane in this build, but not yet confidently private. |

**Do not transmit anything sensitive on any channel.** Treat all lanes as open and public for now. E2E encryption and deeper native/Tauri hardening are the next milestones. If you fork this project, keep these labels intact and do not make stronger privacy claims than the implementation supports.

---


## ✨ Features

### 🧅 InfoNet — Decentralized Intelligence Mesh (NEW in v0.9.6)

The first decentralized intelligence communication layer built directly into an OSINT platform. No accounts, no signup, no identity required. Nothing like this has existed in an OSINT tool before.

* **InfoNet Experimental Testnet** — A global, obfuscated message relay. Anyone running ShadowBroker can transmit and receive on the InfoNet. Messages pass through a Wormhole relay layer with gate personas, Ed25519 canonical payload signing, and transport obfuscation.
* **Mesh Chat Panel** — Three-tab interface:
  * **INFONET** — Gate chat with obfuscated transport (experimental — not yet E2E encrypted)
  * **MESH** — Meshtastic radio integration (default tab on startup)
  * **DEAD DROP** — Peer-to-peer message exchange with token-based epoch mailboxes (strongest current lane)
* **Gate Persona System** — Pseudonymous identities with Ed25519 signing keys, prekey bundles, SAS word contact verification, and abuse reporting
* **Mesh Terminal** — Built-in CLI: `send`, `dm`, market commands, gate state inspection. Draggable panel, minimizes to the top bar. Type `help` to see all commands.
* **Crypto Stack** — Ed25519 signing, X25519 Diffie-Hellman, AESGCM encryption with HKDF key derivation, hash chain commitment system. Double-ratchet DM scaffolding in progress.

> **Experimental Testnet — No Privacy Guarantee:** InfoNet messages are obfuscated but NOT end-to-end encrypted. The Mesh network (Meshtastic/APRS) is NOT private — radio transmissions are inherently public. Do not send anything sensitive on any channel. E2E encryption is being developed but is not yet implemented. Treat all channels as open and public for now.

### 🔍 Shodan Device Search (NEW in v0.9.6)

* **Internet Device Search** — Query Shodan directly from ShadowBroker. Search by keyword, CVE, port, or service — results plotted as a live overlay on the map
* **Configurable Markers** — Shape, color, and size customization for Shodan results
* **Operator-Supplied API** — Uses your own `SHODAN_API_KEY`; results rendered as a local investigative overlay

### 🛩️ Aviation Tracking

* **Commercial Flights** — Real-time positions via OpenSky Network (~5,000+ aircraft)
* **Private Aircraft** — Light GA, turboprops, bizjets tracked separately
* **Private Jets** — High-net-worth individual aircraft with owner identification
* **Military Flights** — Tankers, ISR, fighters, transports via adsb.lol military endpoint
* **Flight Trail Accumulation** — Persistent breadcrumb trails for all tracked aircraft
* **Holding Pattern Detection** — Automatically flags aircraft circling (>300° total turn)
* **Aircraft Classification** — Shape-accurate SVG icons: airliners, turboprops, bizjets, helicopters
* **Grounded Detection** — Aircraft below 100ft AGL rendered with grey icons

### 🚢 Maritime Tracking

* **AIS Vessel Stream** — 25,000+ vessels via aisstream.io WebSocket (real-time)
* **Ship Classification** — Cargo, tanker, passenger, yacht, military vessel types with color-coded icons
* **Carrier Strike Group Tracker** — All 11 active US Navy aircraft carriers with OSINT-estimated positions. No other open tool does this.
  * Automated GDELT news scraping parses carrier movement reporting to estimate positions
  * 50+ geographic region-to-coordinate mappings (e.g. "Eastern Mediterranean" → lat/lng)
  * Disk-cached positions, auto-refreshes at 00:00 & 12:00 UTC
* **Cruise & Passenger Ships** — Dedicated layer for cruise liners and ferries
* **Fishing Activity** — Global Fishing Watch vessel events (NEW)
* **Clustered Display** — Ships cluster at low zoom with count labels, decluster on zoom-in

### 🚆 Rail Tracking (NEW in v0.9.6)

* **Amtrak Trains** — Real-time positions of Amtrak trains across the US with speed, heading, route, and status
* **European Rail** — DigiTraffic integration for European train positions

### 🛰️ Space & Satellites

* **Orbital Tracking** — Real-time satellite positions via CelesTrak TLE data + SGP4 propagation (2,000+ active satellites, no API key required)
* **Mission-Type Classification** — Color-coded by mission: military recon (red), SAR (cyan), SIGINT (white), navigation (blue), early warning (magenta), commercial imaging (green), space station (gold)
* **SatNOGS Ground Stations** — Amateur satellite ground station network with live observation data (NEW)
* **TinyGS LoRa Satellites** — LoRa satellite constellation tracking (NEW)

### 🌍 Geopolitics & Conflict

* **Global Incidents** — GDELT-powered conflict event aggregation (last 8 hours, ~1,000 events)
* **Ukraine Frontline** — Live warfront GeoJSON from DeepState Map
* **Ukraine Air Alerts** — Real-time regional air raid alerts (NEW)
* **SIGINT/RISINT News Feed** — Real-time RSS aggregation from multiple intelligence-focused sources with user-customizable feeds (up to 20 sources, configurable priority weights 1-5)
* **Region Dossier** — Right-click anywhere on Earth for an instant intelligence briefing:
  * Country profile (population, capital, languages, currencies, area)
  * Current head of state & government type (live Wikidata SPARQL query)
  * Local Wikipedia summary with thumbnail
  * Latest Sentinel-2 satellite photo with capture date and cloud cover (10m resolution)

### 🛰️ Satellite Imagery

* **NASA GIBS (MODIS Terra)** — Daily true-color satellite imagery overlay with 30-day time slider, play/pause animation, and opacity control (~250m/pixel)
* **High-Res Satellite (Esri)** — Sub-meter resolution imagery via Esri World Imagery — zoom into buildings and terrain detail (zoom 18+)
* **Sentinel-2 Intel Card** — Right-click anywhere on the map for a floating intel card showing the latest Sentinel-2 satellite photo with capture date, cloud cover %, and clickable full-resolution image (10m resolution, updated every ~5 days)
* **Sentinel Hub Process API** — Copernicus CDSE satellite imagery with OAuth2 token flow (NEW)
* **VIIRS Nightlights** — Night-time light change detection overlay (NEW)
* **5 Visual Modes** — Toggle the entire map aesthetic via the STYLE button:
  * **DEFAULT** — Dark CARTO basemap
  * **SATELLITE** — Sub-meter Esri World Imagery
  * **FLIR** — Thermal imaging aesthetic (inverted greyscale)
  * **NVG** — Night vision green phosphor
  * **CRT** — Retro terminal scanline overlay

### 📻 Software-Defined Radio & SIGINT

* **KiwiSDR Receivers** — 500+ public SDR receivers plotted worldwide with clustered amber markers
* **Live Radio Tuner** — Click any KiwiSDR node to open an embedded SDR tuner directly in the SIGINT panel
* **Metadata Display** — Node name, location, antenna type, frequency bands, active users
* **Meshtastic Mesh Radio** — MQTT-based mesh radio integration with node map, integrated into Mesh Chat (NEW)
* **APRS Integration** — Amateur radio positioning via APRS-IS TCP feed (NEW)
* **GPS Jamming Detection** — Real-time analysis of aircraft NAC-P (Navigation Accuracy Category) values
  * Grid-based aggregation identifies interference zones
  * Red overlay squares with "GPS JAM XX%" severity labels
* **Radio Intercept Panel** — Scanner-style UI with OpenMHZ police/fire scanner feeds. Click any system to listen live. Scan mode cycles through active feeds automatically. Eavesdrop-by-click on real emergency communications.

### 📷 Surveillance

* **CCTV Mesh** — 11,000+ live traffic cameras from 13 sources across 6 countries:
  * 🇬🇧 Transport for London JamCams
  * 🇺🇸 NYC DOT, Austin TX (TxDOT)
  * 🇺🇸 California (12 Caltrans districts), Washington State (WSDOT), Georgia DOT, Illinois DOT, Michigan DOT
  * 🇪🇸 Spain DGT National (20 cities), Madrid City (357 cameras via KML)
  * 🇸🇬 Singapore LTA
  * 🌍 Windy Webcams
* **Feed Rendering** — Automatic detection & rendering of video, MJPEG, HLS, embed, satellite tile, and image feeds
* **Clustered Map Display** — Green dots cluster with count labels, decluster on zoom

### 🔥 Environmental & Hazard Monitoring

* **NASA FIRMS Fire Hotspots (24h)** — 5,000+ global thermal anomalies from NOAA-20 VIIRS satellite, updated every cycle. Flame-shaped icons color-coded by fire radiative power (FRP): yellow (low), orange, red, dark red (intense). Clustered at low zoom with fire-shaped cluster markers.
* **Volcanoes** — Smithsonian Global Volcanism Program Holocene volcanoes plotted worldwide (NEW)
* **Weather Alerts** — Severe weather polygons with urgency/severity indicators (NEW)
* **Air Quality (PM2.5)** — OpenAQ stations worldwide with real-time particulate matter readings (NEW)
* **Earthquakes (24h)** — USGS real-time earthquake feed with magnitude-scaled markers
* **Space Weather Badge** — Live NOAA geomagnetic storm indicator in the bottom status bar. Color-coded Kp index: green (quiet), yellow (active), red (storm G1–G5). Data from SWPC planetary K-index 1-minute feed.

### 🏗️ Infrastructure Monitoring

* **Internet Outage Monitoring** — Regional internet connectivity alerts from Georgia Tech IODA. Grey markers at affected regions with severity percentage. Uses only reliable datasources (BGP routing tables, active ping probing) — no telescope or interpolated data.
* **Data Center Mapping** — 2,000+ global data centers plotted from a curated dataset. Clustered purple markers with server-rack icons. Click for operator, location, and automatic internet outage cross-referencing by country.
* **Military Bases** — Global military installation and missile facility database (NEW)
* **Power Plants** — 35,000+ global power plants from the WRI database (NEW)

### 🌐 Additional Layers & Tools

* **Day/Night Cycle** — Solar terminator overlay showing global daylight/darkness
* **Global Markets Ticker** — Live financial market indices (minimizable)
* **Measurement Tool** — Point-to-point distance & bearing measurement on the map
* **LOCATE Bar** — Search by coordinates (31.8, 34.8) or place name (Tehran, Strait of Hormuz) to fly directly to any location — geocoded via OpenStreetMap Nominatim

![Gaza](https://github.com/user-attachments/assets/f2c953b2-3528-4360-af5a-7ea34ff28489)

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      FRONTEND (Next.js)                         │
│                                                                 │
│  ┌─────────────┐  ┌──────────┐  ┌───────────┐  ┌────────────┐   │
│  │ MapLibre GL │  │ NewsFeed │  │  Control  │  │    Mesh    │   │
│  │  2D WebGL   │  │  SIGINT  │  │  Panels   │  │    Chat    │   │
│  │ Map Render  │  │  Intel   │  │  Radio    │  │  Terminal  │   │
│  └──────┬──────┘  └────┬─────┘  └─────┬─────┘  └─────┬──────┘   │
│         └──────────────┼──────────────┼──────────────┘          │
│                        │ REST + WebSocket                       │
├────────────────────────┼────────────────────────────────────────┤
│                    BACKEND (FastAPI)                            │
│                        │                                        │
│  ┌─────────────────────┼─────────────────────────────────────┐  │
│  │              Data Fetcher (Scheduler)                     │  │
│  │                                                           │  │
│  │  ┌───────────┬───────────┬───────────┬───────────┐        │  │
│  │  │  OpenSky  │ adsb.lol  │ CelesTrak │   USGS    │        │  │
│  │  │  Flights  │ Military  │   Sats    │  Quakes   │        │  │
│  │  ├───────────┼───────────┼───────────┼───────────┤        │  │
│  │  │  AIS WS   │ Carrier   │  GDELT    │ CCTV (13) │        │  │
│  │  │  Ships    │ Tracker   │ Conflict  │  Cameras  │        │  │
│  │  ├───────────┼───────────┼───────────┼───────────┤        │  │
│  │  │ DeepState │   RSS     │  Region   │    GPS    │        │  │
│  │  │ Frontline │  Intel    │ Dossier   │  Jamming  │        │  │
│  │  ├───────────┼───────────┼───────────┼───────────┤        │  │
│  │  │  NASA     │  NOAA     │   IODA    │  KiwiSDR  │        │  │
│  │  │  FIRMS    │ Space Wx  │  Outages  │  Radios   │        │  │
│  │  ├───────────┼───────────┼───────────┼───────────┤        │  │
│  │  │  Shodan   │  Amtrak   │  SatNOGS  │Meshtastic │        │  │
│  │  │ Devices   │ DigiTraf  │  TinyGS   │   APRS    │        │  │
│  │  ├───────────┼───────────┼───────────┼───────────┤        │  │
│  │  │ Volcanoes │ Weather   │  Fishing  │ Mil Bases │        │  │
│  │  │ Air Qual. │ Alerts    │ Activity  │Pwr Plants │        │  │
│  │  ├───────────┼───────────┼───────────┼───────────┤        │  │
│  │  │  Sentinel │  MODIS    │  VIIRS    │  Data     │        │  │
│  │  │  Hub/STAC │  Terra    │ Nightlts  │  Centers  │        │  │
│  │  └───────────┴───────────┴───────────┴───────────┘        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Wormhole / InfoNet Relay                     │  │
│  │  Gate Personas │ Canonical Signing │ Dead Drop DMs        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                   GHCR (Pre-built Images)                 │  │
│  │  ghcr.io/bigbodycobain/shadowbroker-backend:latest        │  │
│  │  ghcr.io/bigbodycobain/shadowbroker-frontend:latest       │  │
│  │  Multi-arch: linux/amd64 + linux/arm64                    │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📊 Data Sources & APIs

| Source | Data | Update Frequency | API Key Required |
|---|---|---|---|
| [OpenSky Network](https://opensky-network.org) | Commercial & private flights | ~60s | Optional (anonymous limited) |
| [adsb.lol](https://adsb.lol) | Military aircraft | ~60s | No |
| [aisstream.io](https://aisstream.io) | AIS vessel positions | Real-time WebSocket | **Yes** |
| [CelesTrak](https://celestrak.org) | Satellite orbital positions (TLE + SGP4) | ~60s | No |
| [USGS Earthquake](https://earthquake.usgs.gov) | Global seismic events | ~60s | No |
| [GDELT Project](https://www.gdeltproject.org) | Global conflict events | ~6h | No |
| [DeepState Map](https://deepstatemap.live) | Ukraine frontline | ~30min | No |
| [Shodan](https://www.shodan.io) | Internet-connected device search | On-demand | **Yes** |
| [Amtrak](https://www.amtrak.com) | US train positions | ~60s | No |
| [DigiTraffic](https://www.digitraffic.fi) | European rail positions | ~60s | No |
| [Global Fishing Watch](https://globalfishingwatch.org) | Fishing vessel activity events | ~10min | No |
| Transport for London, NYC DOT, TxDOT | CCTV cameras (UK, US) | ~10min | No |
| Caltrans, WSDOT, GDOT, IDOT, MDOT | CCTV cameras (5 US states) | ~10min | No |
| Spain DGT, Madrid City | CCTV cameras (Spain) | ~10min | No |
| [Singapore LTA](https://datamall.lta.gov.sg) | Singapore traffic cameras | ~10min | **Yes** |
| [Windy Webcams](https://www.windy.com) | Global webcams | ~10min | No |
| [SatNOGS](https://satnogs.org) | Amateur satellite ground stations | ~30min | No |
| [TinyGS](https://tinygs.com) | LoRa satellite ground stations | ~30min | No |
| [Meshtastic MQTT](https://meshtastic.org) | Mesh radio node positions | Real-time | No |
| [APRS-IS](https://www.aprs-is.net) | Amateur radio positions | Real-time TCP | No |
| [KiwiSDR](https://kiwisdr.com) | Public SDR receiver locations | ~30min | No |
| [OpenMHZ](https://openmhz.com) | Police/fire scanner feeds | Real-time | No |
| [Smithsonian GVP](https://volcano.si.edu) | Holocene volcanoes worldwide | Static (cached) | No |
| [OpenAQ](https://openaq.org) | Air quality PM2.5 stations | ~120s | No |
| NOAA / NWS | Severe weather alerts & polygons | ~120s | No |
| [WRI Global Power Plant DB](https://datasets.wri.org) | 35,000+ power plants | Static (cached) | No |
| Military base datasets | Global military installations | Static (cached) | No |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) | NOAA-20 VIIRS fire/thermal hotspots | ~120s | No |
| [NOAA SWPC](https://services.swpc.noaa.gov) | Space weather Kp index & solar events | ~120s | No |
| [IODA (Georgia Tech)](https://ioda.inetintel.cc.gatech.edu) | Regional internet outage alerts | ~120s | No |
| [DC Map (GitHub)](https://github.com/Ringmast4r/Data-Center-Map---Global) | Global data center locations | Static (cached 7d) | No |
| [NASA GIBS](https://gibs.earthdata.nasa.gov) | MODIS Terra daily satellite imagery | Daily (24-48h delay) | No |
| [Esri World Imagery](https://www.arcgis.com) | High-res satellite basemap | Static (periodically updated) | No |
| [MS Planetary Computer](https://planetarycomputer.microsoft.com) | Sentinel-2 L2A scenes (right-click) | On-demand | No |
| [Copernicus CDSE](https://dataspace.copernicus.eu) | Sentinel Hub imagery (Process API) | On-demand | **Yes** (free) |
| [VIIRS Nightlights](https://eogdata.mines.edu) | Night-time light change detection | Static | No |
| [RestCountries](https://restcountries.com) | Country profile data | On-demand (cached 24h) | No |
| [Wikidata SPARQL](https://query.wikidata.org) | Head of state data | On-demand (cached 24h) | No |
| [Wikipedia API](https://en.wikipedia.org/api) | Location summaries & aircraft images | On-demand (cached) | No |
| [OSM Nominatim](https://nominatim.openstreetmap.org) | Place name geocoding (LOCATE bar) | On-demand | No |
| [CARTO Basemaps](https://carto.com) | Dark map tiles | Continuous | No |

---

## 🚀 Getting Started

### 🐳 Docker Setup (Recommended for Self-Hosting)

The repo includes a `docker-compose.yml` that pulls pre-built images from the GitHub Container Registry.

```bash
git clone https://github.com/BigBodyCobain/Shadowbroker.git
cd Shadowbroker
# Add your API keys in a repo-root .env file (optional — see Environment Variables below)
docker compose pull
docker compose up -d
```

Open `http://localhost:3000` to view the dashboard.

> **Deploying publicly or on a LAN?** No configuration needed for most setups.
> The frontend proxies all API calls through the Next.js server to `BACKEND_URL`,
> which defaults to `http://backend:8000` (Docker internal networking).
> Port 8000 does not need to be exposed externally.
>
> If your backend runs on a **different host or port**, set `BACKEND_URL` at runtime — no rebuild required:
>
> ```bash
> # Linux / macOS
> BACKEND_URL=http://myserver.com:9096 docker-compose up -d
>
> # Podman (via compose.sh wrapper)
> BACKEND_URL=http://192.168.1.50:9096 ./compose.sh up -d
>
> # Windows (PowerShell)
> $env:BACKEND_URL="http://myserver.com:9096"; docker-compose up -d
>
> # Or add to a .env file next to docker-compose.yml:
> # BACKEND_URL=http://myserver.com:9096
> ```

**Podman users:** Replace `docker compose` with `podman compose`, or use the `compose.sh` wrapper which auto-detects your engine.

---

### 🐋 Standalone Deploy (Portainer, Uncloud, NAS, etc.)

No need to clone the repo. Use the pre-built images published to the GitHub Container Registry.

Create a `docker-compose.yml` with the following content and deploy it directly — paste it into Portainer's stack editor, `uncloud deploy`, or any Docker host:

```yaml
services:
  backend:
    image: ghcr.io/bigbodycobain/shadowbroker-backend:latest
    container_name: shadowbroker-backend
    ports:
      - "8000:8000"
    environment:
      - AIS_API_KEY=your_aisstream_key          # Required — get one free at aisstream.io
      - OPENSKY_CLIENT_ID=                       # Optional — higher flight data rate limits
      - OPENSKY_CLIENT_SECRET=                   # Optional — paired with Client ID above
      - LTA_ACCOUNT_KEY=                         # Optional — Singapore CCTV cameras
      - SHODAN_API_KEY=                          # Optional — Shodan device search overlay
      - SH_CLIENT_ID=                            # Optional — Sentinel Hub satellite imagery
      - SH_CLIENT_SECRET=                        # Optional — paired with Sentinel Hub ID
      - CORS_ORIGINS=                            # Optional — comma-separated allowed origins
    volumes:
      - backend_data:/app/data
    restart: unless-stopped

  frontend:
    image: ghcr.io/bigbodycobain/shadowbroker-frontend:latest
    container_name: shadowbroker-frontend
    ports:
      - "3000:3000"
    environment:
      - BACKEND_URL=http://backend:8000   # Docker internal networking — no rebuild needed
    depends_on:
      - backend
    restart: unless-stopped

volumes:
  backend_data:
```

> **How it works:** The frontend container proxies all `/api/*` requests through the Next.js server to `BACKEND_URL` using Docker's internal networking. The browser only ever talks to port 3000 — port 8000 does not need to be exposed externally.
>
> `BACKEND_URL` is a plain runtime environment variable (not a build-time `NEXT_PUBLIC_*`), so you can change it in Portainer, Uncloud, or any compose editor without rebuilding the image. Set it to the address where your backend is reachable from inside the Docker network (e.g. `http://backend:8000`, `http://192.168.1.50:8000`).

---

### 📦 Quick Start (No Code Required)

If you just want to run the dashboard without dealing with terminal commands:

1. Go to the **[Releases](../../releases)** tab on the right side of this GitHub page.
2. Download the latest `.zip` file from the release.
3. Extract the folder to your computer.
4. **Windows:** Double-click `start.bat`.
   **Mac/Linux:** Open terminal, type `chmod +x start.sh` and run `./start.sh`.
5. It will automatically install everything and launch the dashboard!

Local launcher notes:

- `start.bat` / `start.sh` run the app without Docker — they install dependencies and start both servers directly.
- If Wormhole identity or DM contact endpoints fail after an upgrade, check the `docs/mesh/` folder for troubleshooting.

---

### 💻 Developer Setup

If you want to modify the code or run from source:

#### Prerequisites

* **Node.js** 18+ and **npm** — [nodejs.org](https://nodejs.org/)
* **Python** 3.10, 3.11, or 3.12 with `pip` — [python.org](https://www.python.org/downloads/) (**check "Add to PATH"** during install)
  * ⚠️ Python 3.13+ may have compatibility issues with some dependencies. **3.11 or 3.12 is recommended.**
* API keys for: `aisstream.io` (required), and optionally `opensky-network.org` (OAuth2), `lta.gov.sg`

### Installation

```bash
# Clone the repository
git clone https://github.com/BigBodyCobain/Shadowbroker.git
cd Shadowbroker

# Backend setup
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install .   # installs all dependencies from pyproject.toml

# Optional helper scripts (creates venv + installs dev deps)
# Windows PowerShell
# .\scripts\setup-venv.ps1
# macOS/Linux
# ./scripts/setup-venv.sh

# Optional env check (prints warnings for missing keys)
# Windows PowerShell
# .\scripts\check-env.ps1
# macOS/Linux
# ./scripts/check-env.sh

# Create .env with your API keys
echo "AIS_API_KEY=your_aisstream_key" >> .env
echo "OPENSKY_CLIENT_ID=your_opensky_client_id" >> .env
echo "OPENSKY_CLIENT_SECRET=your_opensky_secret" >> .env

# Frontend setup
cd ../frontend
npm install
```

### Running

```bash
# From the frontend directory — starts both frontend & backend concurrently
npm run dev
```

This starts:

* **Next.js** frontend on `http://localhost:3000`
* **FastAPI** backend on `http://localhost:8000`

### Pre-commit (Optional)

If you use pre-commit, install hooks once from repo root:

```bash
pre-commit install
```

### Local AIS Receiver (Optional)

You can feed your own AIS ship data into ShadowBroker using an RTL-SDR dongle and [AIS-catcher](https://github.com/jvde-github/AIS-catcher), an open-source AIS decoder. This gives you real-time coverage of vessels in your local area — no API key needed.

1. Plug in an RTL-SDR dongle
2. Install AIS-catcher ([releases](https://github.com/jvde-github/AIS-catcher/releases)) or use the Docker image:
   ```bash
   docker run -d --device /dev/bus/usb \
     ghcr.io/jvde-github/ais-catcher -H http://host.docker.internal:4000/api/ais/feed interval 10
   ```
3. Or run natively:
   ```bash
   AIS-catcher -H http://localhost:4000/api/ais/feed interval 10
   ```

AIS-catcher decodes VHF radio signals on 161.975 MHz and 162.025 MHz and POSTs decoded vessel data to ShadowBroker every 10 seconds. Ships detected by your SDR antenna appear alongside the global AIS stream.

**Docker (ARM/Raspberry Pi):** See [docker-shipfeeder](https://github.com/sdr-enthusiasts/docker-shipfeeder) for a production-ready Docker image optimized for ARM.

**Note:** AIS range depends on your antenna — typically 20-40 nautical miles with a basic setup, 60+ nm with a marine VHF antenna at elevation.

---

## 🎛️ Data Layers

All 37 layers are independently toggleable from the left panel:

| Layer | Default | Description |
|---|---|---|
| Commercial Flights | ✅ ON | Airlines, cargo, GA aircraft |
| Private Flights | ✅ ON | Non-commercial private aircraft |
| Private Jets | ✅ ON | High-value bizjets with owner data |
| Military Flights | ✅ ON | Military & government aircraft |
| Tracked Aircraft | ✅ ON | Special interest watch list |
| GPS Jamming | ✅ ON | NAC-P degradation zones |
| Carriers / Mil / Cargo | ✅ ON | Navy carriers, cargo ships, tankers |
| Civilian Vessels | ✅ ON | Yachts, fishing, recreational |
| Cruise / Passenger | ✅ ON | Cruise ships and ferries |
| Tracked Yachts | ✅ ON | Billionaire & oligarch superyachts |
| Fishing Activity | ✅ ON | Global Fishing Watch vessel events |
| Trains | ✅ ON | Amtrak + European rail positions |
| Satellites | ✅ ON | Orbital assets by mission type |
| SatNOGS | ✅ ON | Amateur satellite ground stations |
| TinyGS | ✅ ON | LoRa satellite ground stations |
| Earthquakes (24h) | ✅ ON | USGS seismic events |
| Fire Hotspots (24h) | ✅ ON | NASA FIRMS VIIRS thermal anomalies |
| Volcanoes | ✅ ON | Smithsonian Holocene volcanoes |
| Weather Alerts | ✅ ON | Severe weather polygons |
| Air Quality (PM2.5) | ✅ ON | OpenAQ stations worldwide |
| Ukraine Frontline | ✅ ON | Live warfront positions |
| Ukraine Air Alerts | ✅ ON | Regional air raid alerts |
| Global Incidents | ✅ ON | GDELT conflict events |
| CCTV Mesh | ✅ ON | 11,000+ cameras across 13 sources, 6 countries |
| Internet Outages | ✅ ON | IODA regional connectivity alerts |
| Data Centers | ✅ ON | Global data center locations (2,000+) |
| Military Bases | ✅ ON | Global military installations |
| KiwiSDR Receivers | ✅ ON | Public SDR radio receivers |
| Meshtastic Nodes | ✅ ON | Mesh radio node positions |
| APRS | ✅ ON | Amateur radio positioning |
| Scanners | ✅ ON | Police/fire scanner feeds |
| Day / Night Cycle | ✅ ON | Solar terminator overlay |
| MODIS Terra (Daily) | ❌ OFF | NASA GIBS daily satellite imagery |
| High-Res Satellite | ❌ OFF | Esri sub-meter satellite imagery |
| Sentinel Hub | ❌ OFF | Copernicus CDSE Process API |
| VIIRS Nightlights | ❌ OFF | Night-time light change detection |
| Power Plants | ❌ OFF | 35,000+ global power plants |
| Shodan Overlay | ❌ OFF | Internet device search results |

---

## 🔧 Performance

The platform is optimized for handling massive real-time datasets:

* **Gzip Compression** — API payloads compressed ~92% (11.6 MB → 915 KB)
* **ETag Caching** — `304 Not Modified` responses skip redundant JSON parsing
* **Viewport Culling** — Only features within the visible map bounds (+20% buffer) are rendered
* **Imperative Map Updates** — High-volume layers (flights, satellites, fires) bypass React reconciliation via direct `setData()` calls
* **Clustered Rendering** — Ships, CCTV, earthquakes, and data centers use MapLibre clustering to reduce feature count
* **Debounced Viewport Updates** — 300ms debounce prevents GeoJSON rebuild thrash during pan/zoom; 2s debounce on dense layers (satellites, fires)
* **Position Interpolation** — Smooth 10s tick animation between data refreshes
* **React.memo** — Heavy components wrapped to prevent unnecessary re-renders
* **Coordinate Precision** — Lat/lng rounded to 5 decimals (~1m) to reduce JSON size

---

## 📁 Project Structure

```
Shadowbroker/
├── backend/
│   ├── main.py                     # FastAPI app, middleware, API routes
│   ├── pyproject.toml              # Python dependencies
│   ├── services/
│   │   ├── data_fetcher.py         # Core scheduler — orchestrates all data sources
│   │   ├── ais_stream.py           # AIS WebSocket client (25K+ vessels)
│   │   ├── carrier_tracker.py      # OSINT carrier position estimator
│   │   ├── cctv_pipeline.py        # 14-source CCTV camera ingestion pipeline
│   │   ├── correlation_engine.py   # Cross-layer intelligence correlation
│   │   ├── geopolitics.py          # GDELT + Ukraine frontline + air alerts
│   │   ├── region_dossier.py       # Right-click country/city intelligence
│   │   ├── radio_intercept.py      # Police scanner feeds + OpenMHZ
│   │   ├── oracle_service.py       # Prediction market oracle resolution
│   │   ├── shodan_connector.py     # Shodan device search connector
│   │   ├── sigint_bridge.py        # APRS-IS TCP bridge
│   │   ├── config.py               # pydantic-settings configuration
│   │   ├── fetchers/
│   │   │   ├── _store.py           # Thread-safe in-memory data store
│   │   │   ├── flights.py          # OpenSky, adsb.lol, GPS jamming, holding patterns
│   │   │   ├── geo.py              # AIS vessels, carriers, GDELT, fishing activity
│   │   │   ├── satellites.py       # CelesTrak TLE + SGP4 propagation
│   │   │   ├── earth_observation.py # Quakes, fires, volcanoes, air quality, weather
│   │   │   ├── infrastructure.py   # Data centers, power plants, military bases
│   │   │   ├── prediction_markets.py # Polymarket aggregation
│   │   │   ├── trains.py           # Amtrak + DigiTraffic European rail
│   │   │   ├── sigint.py           # SatNOGS, TinyGS, APRS, Meshtastic
│   │   │   ├── plane_alert.py      # Plane-Alert DB enrichment
│   │   │   ├── news.py             # RSS intelligence feed aggregation
│   │   │   ├── financial.py        # Global markets data
│   │   │   └── ukraine_alerts.py   # Ukraine air raid alerts
│   │   └── mesh/                   # InfoNet / Wormhole protocol stack
│   │       ├── mesh_protocol.py    # Core mesh protocol + payload normalization
│   │       ├── mesh_crypto.py      # Ed25519, ECDSA, HKDF primitives
│   │       ├── mesh_hashchain.py   # Append-only hash chain
│   │       ├── mesh_router.py      # Multi-transport router (APRS, LoRa, Tor, clearnet)
│   │       ├── mesh_dm_mls.py      # MLS-like DM encryption
│   │       ├── mesh_gate_mls.py    # MLS-like gate (channel) encryption
│   │       ├── mesh_rns.py         # Reticulum Network Stack + Dandelion++ routing
│   │       ├── mesh_reputation.py  # Node reputation scoring
│   │       ├── mesh_schema.py      # Event payload validation
│   │       ├── mesh_wormhole_identity.py  # Wormhole identity management
│   │       ├── mesh_wormhole_dead_drop.py # Dead Drop token-based DM mailbox
│   │       ├── mesh_wormhole_contacts.py  # Contact exchange
│   │       ├── mesh_wormhole_seal.py      # Message sealing + unsealing
│   │       ├── mesh_oracle.py      # Oracle consensus protocol
│   │       └── mesh_secure_storage.py # Secure credential storage
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   └── page.tsx            # Main dashboard — state, polling, layout
│   │   ├── components/
│   │   │   ├── MaplibreViewer.tsx   # Core map — all GeoJSON layers
│   │   │   ├── InfonetTerminal/    # InfoNet mesh terminal UI
│   │   │   ├── MeshChat.tsx        # Mesh / Dead Drop chat panel
│   │   │   ├── MeshTerminal.tsx    # Draggable CLI terminal
│   │   │   ├── NewsFeed.tsx        # SIGINT feed + entity detail panels
│   │   │   ├── PredictionsPanel.tsx # Prediction market panel
│   │   │   ├── ShodanPanel.tsx     # Shodan search panel
│   │   │   ├── FilterPanel.tsx     # Data filter controls
│   │   │   ├── WorldviewLeftPanel.tsx   # Data layer toggles (37+ layers)
│   │   │   ├── WorldviewRightPanel.tsx  # Search + filter sidebar
│   │   │   ├── RadioInterceptPanel.tsx  # Scanner-style radio panel
│   │   │   ├── MarketsPanel.tsx    # Global financial markets ticker
│   │   │   ├── FindLocateBar.tsx   # Search/locate bar
│   │   │   └── map/               # Map sub-components, layers, icons, styles
│   │   ├── hooks/                  # useDataPolling, useDataStore, useGateSSE
│   │   ├── mesh/                   # Frontend mesh/DM/identity client code
│   │   └── lib/                    # Utilities, desktop bridge, API client
│   └── package.json
│
├── desktop-shell/                  # Tauri (Rust) desktop wrapper
├── helm/chart/                     # Kubernetes Helm chart
├── docker-compose.yml              # Main Docker Compose config
├── start.sh / start.bat            # Local launcher scripts
└── compose.sh                      # Podman/Docker auto-detect wrapper
```

---

## 🔑 Environment Variables

### Backend (`backend/.env`)

```env
# Required
AIS_API_KEY=your_aisstream_key                # Maritime vessel tracking (aisstream.io)

# Optional (enhances data quality)
OPENSKY_CLIENT_ID=your_opensky_client_id      # OAuth2 — higher rate limits for flight data
OPENSKY_CLIENT_SECRET=your_opensky_secret     # OAuth2 — paired with Client ID above
LTA_ACCOUNT_KEY=your_lta_key                  # Singapore CCTV cameras
SHODAN_API_KEY=your_shodan_key                # Shodan device search overlay
SH_CLIENT_ID=your_sentinel_hub_id             # Copernicus CDSE Sentinel Hub imagery
SH_CLIENT_SECRET=your_sentinel_hub_secret     # Paired with Sentinel Hub Client ID
```

### Frontend

| Variable | Where to set | Purpose |
|---|---|---|
| `BACKEND_URL` | `environment` in `docker-compose.yml`, or shell env | URL the Next.js server uses to proxy API calls to the backend. Defaults to `http://backend:8000`. **Runtime variable — no rebuild needed.** |

**How it works:** The frontend proxies all `/api/*` requests through the Next.js server to `BACKEND_URL` using Docker's internal networking. Browsers only talk to port 3000; port 8000 never needs to be exposed externally. For local dev without Docker, `BACKEND_URL` defaults to `http://localhost:8000`.

---

## 🤝 Contributors

ShadowBroker is built in the open. These people shipped real code:

| Who | What | PR |
|-----|------|----|
| [@wa1id](https://github.com/wa1id) | CCTV ingestion fix — threaded SQLite, persistent DB, startup hydration, cluster clickability | #92 |
| [@AlborzNazari](https://github.com/AlborzNazari) | Spain DGT + Madrid CCTV sources, STIX 2.1 threat intel export | #91 |
| [@adust09](https://github.com/adust09) | Power plants layer, East Asia intel coverage (JSDF bases, ICAO enrichment, Taiwan news, military classification) | #71, #72, #76, #77, #87 |
| [@Xpirix](https://github.com/Xpirix) | LocateBar style and interaction improvements | #78 |
| [@imqdcr](https://github.com/imqdcr) | Ship toggle split (4 categories) + stable MMSI/callsign entity IDs | — |
| [@csysp](https://github.com/csysp) | Dismissible threat alerts + stable entity IDs for GDELT & News | #48, #63 |
| [@suranyami](https://github.com/suranyami) | Parallel multi-arch Docker builds (11min → 3min) + runtime BACKEND_URL fix | #35, #44 |
| [@chr0n1x](https://github.com/chr0n1x) | Kubernetes / Helm chart architecture for HA deployments | — |

---

## ⚠️ Disclaimer

This tool is built entirely on publicly available, open-source intelligence (OSINT) data. No classified, restricted, or non-public data is used. Carrier positions are estimates based on public reporting. The military-themed UI is purely aesthetic.

---

## 📜 License

This project is for educational and personal research purposes. See individual API provider terms of service for data usage restrictions.

---

<p align="center">
  <sub>Built with ☕ and too many API calls</sub>
</p>
