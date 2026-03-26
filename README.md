<p align="center">
  <h1 align="center">🛰️ S H A D O W B R O K E R</h1>
  <p align="center"><strong>Global Threat Intercept — Real-Time Geospatial Intelligence Platform</strong></p>
  <p align="center">

  </p>
</p>

---




https://github.com/user-attachments/assets/248208ec-62f7-49d1-831d-4bd0a1fa6852





**ShadowBroker** is a real-time, multi-domain OSINT dashboard that aggregates live data from dozens of open-source intelligence feeds and renders them on a unified dark-ops map interface. It tracks aircraft, ships, satellites, earthquakes, conflict zones, CCTV networks, GPS jamming, and breaking geopolitical events — all updating in real time.

Built with **Next.js**, **MapLibre GL**, **FastAPI**, and **Python**, it's designed for analysts, researchers, and enthusiasts who want a single-pane-of-glass view of global activity.

---

## Why This Exists

A surprising amount of global telemetry is already public:

- Aircraft ADS-B broadcasts
- Maritime AIS signals
- Satellite orbital data
- Earthquake sensors
- Environmental monitoring networks

This data is scattered across dozens of tools and APIs. ShadowBroker began as an experiment to see what the world looks like when these signals are combined into a single interface.

The project does not introduce new surveillance capabilities — it aggregates and visualizes existing public datasets, including public aircraft registration records. It is fully open-source so anyone can audit exactly what data is accessed and how. No user data is collected or transmitted — the dashboard runs entirely in your browser against a self-hosted backend.

---

## Interesting Use Cases

* Track everything from Air Force One to the private jets of billionaires, dictators, and corporations
* Monitor satellites passing overhead and see high-resolution satellite imagery
* Nose around local emergency scanners
* Watch naval traffic worldwide
* Detect GPS jamming zones
* Follow earthquakes and other natural disasters in real time

---

## ⚡ Quick Start (Docker or Podman)

Linux/Mac

```bash
git clone https://github.com/BigBodyCobain/Shadowbroker.git
cd Shadowbroker
./compose.sh up -d
```

Windows

```bash
git clone https://github.com/BigBodyCobain/Shadowbroker.git
cd Shadowbroker
docker-compose up -d
```

Open `http://localhost:3000` to view the dashboard! *(Requires Docker or Podman)*

`compose.sh` auto-detects `docker compose`, `docker-compose`, `podman compose`, and `podman-compose`.
If both runtimes are installed, you can force Podman with `./compose.sh --engine podman up -d`.
Do not append a trailing `.` to that command; Compose treats it as a service name.

---

##  🔄 **How to Update**

If you are coming from v0.9.5 or older, you must pull the new code and rebuild your containers to see the latest data layers and performance fixes.

### 🐧 **Linux & 🍎 macOS** (Terminal / Zsh / Bash)

Since these systems are Unix-based, you can use the helper script directly.

**Pull the latest code:**
```bash
git pull origin main
```
**Run the update script:**
```bash
./compose.sh down
./compose.sh up --build -d
```

### 🪟 **Windows** (Command Prompt or PowerShell)

Windows handles scripts differently. You have two ways to update:

**Method A: The Direct Way (Recommended)**
Use the docker compose commands directly. This works in any Windows terminal (CMD, PowerShell, or Windows Terminal).

**Pull the latest code:**
```DOS
git pull origin main
```

**Rebuild the containers:**
```DOS
docker compose down
docker compose up --build -d
```

**Method B: Using the Script (Git Bash)**

If you prefer using the ./compose.sh script on Windows, you must use Git Bash (installed with Git for Windows).

Open your project folder, Right-Click, and select "Open Git Bash here".

**Run the Linux commands:**
```bash
./compose.sh down
./compose.sh up --build -d
```

---

### ⚠️ **Stuck on the old version?**

**If the dashboard still shows old data after updating:**

**Clear Docker Cache:** docker compose build --no-cache

**Prune Images:** docker image prune -f

**Check Logs:** ./compose.sh logs -f backend (or docker compose logs -f backend)

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


## ✨ Features


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
* **Carrier Strike Group Tracker** — All 11 active US Navy aircraft carriers with OSINT-estimated positions
  * Automated GDELT news scraping for carrier movement intelligence
  * 50+ geographic region-to-coordinate mappings
  * Disk-cached positions, auto-updates at 00:00 & 12:00 UTC
* **Cruise & Passenger Ships** — Dedicated layer for cruise liners and ferries
* **Clustered Display** — Ships cluster at low zoom with count labels, decluster on zoom-in

### 🛰️ Space & Satellites

* **Orbital Tracking** — Real-time satellite positions via CelesTrak TLE data + SGP4 propagation (2,000+ active satellites, no API key required)
* **Mission-Type Classification** — Color-coded by mission: military recon (red), SAR (cyan), SIGINT (white), navigation (blue), early warning (magenta), commercial imaging (green), space station (gold)

### 🌍 Geopolitics & Conflict

* **Global Incidents** — GDELT-powered conflict event aggregation (last 8 hours, ~1,000 events)
* **Ukraine Frontline** — Live warfront GeoJSON from DeepState Map
* **SIGINT/RISINT News Feed** — Real-time RSS aggregation from multiple intelligence-focused sources with user-customizable feeds (up to 20 sources, configurable priority weights 1-5)
* **Region Dossier** — Right-click anywhere on the map for:
  * Country profile (population, capital, languages, currencies, area)
  * Head of state & government type (Wikidata SPARQL)
  * Local Wikipedia summary with thumbnail

### 🛰️ Satellite Imagery

* **NASA GIBS (MODIS Terra)** — Daily true-color satellite imagery overlay with 30-day time slider, play/pause animation, and opacity control (~250m/pixel)
* **High-Res Satellite (Esri)** — Sub-meter resolution imagery via Esri World Imagery — zoom into buildings and terrain detail (zoom 18+)
* **Sentinel-2 Intel Card** — Right-click anywhere on the map for a floating intel card showing the latest Sentinel-2 satellite photo with capture date, cloud cover %, and clickable full-resolution image (10m resolution, updated every ~5 days)
* **SATELLITE Style Preset** — Quick-toggle high-res imagery via the STYLE button (DEFAULT → SATELLITE → FLIR → NVG → CRT)

### 📻 Software-Defined Radio (SDR)

* **KiwiSDR Receivers** — 500+ public SDR receivers plotted worldwide with clustered amber markers
* **Live Radio Tuner** — Click any KiwiSDR node to open an embedded SDR tuner directly in the SIGINT panel
* **Metadata Display** — Node name, location, antenna type, frequency bands, active users

### 📷 Surveillance

* **CCTV Mesh** — 4,400+ live traffic cameras from:
  * 🇬🇧 Transport for London JamCams
  * 🇺🇸 Austin, TX TxDOT
  * 🇺🇸 NYC DOT
  * 🇸🇬 Singapore LTA
  * 🇪🇸 Spanish DGT (national roads)
  * 🇪🇸 Madrid City Hall
  * 🇪🇸 Málaga City
  * 🇪🇸 Vigo City
  * 🇪🇸 Vitoria-Gasteiz
  * Custom URL ingestion
* **Feed Rendering** — Automatic detection & rendering of video, MJPEG, HLS, embed, satellite tile, and image feeds
* **Clustered Map Display** — Green dots cluster with count labels, decluster on zoom

### 📡 Signal Intelligence

* **GPS Jamming Detection** — Real-time analysis of aircraft NAC-P (Navigation Accuracy Category) values
  * Grid-based aggregation identifies interference zones
  * Red overlay squares with "GPS JAM XX%" severity labels
* **Radio Intercept Panel** — Scanner-style UI for monitoring communications

### 🔥 Environmental & Infrastructure Monitoring

* **NASA FIRMS Fire Hotspots (24h)** — 5,000+ global thermal anomalies from NOAA-20 VIIRS satellite, updated every cycle. Flame-shaped icons color-coded by fire radiative power (FRP): yellow (low), orange, red, dark red (intense). Clustered at low zoom with fire-shaped cluster markers.
* **Space Weather Badge** — Live NOAA geomagnetic storm indicator in the bottom status bar. Color-coded Kp index: green (quiet), yellow (active), red (storm G1–G5). Data from SWPC planetary K-index 1-minute feed.
* **Internet Outage Monitoring** — Regional internet connectivity alerts from Georgia Tech IODA. Grey markers at affected regions with severity percentage. Uses only reliable datasources (BGP routing tables, active ping probing) — no telescope or interpolated data.
* **Data Center Mapping** — 2,000+ global data centers plotted from a curated dataset. Clustered purple markers with server-rack icons. Click for operator, location, and automatic internet outage cross-referencing by country.

### 🌐 Additional Layers

* **Earthquakes (24h)** — USGS real-time earthquake feed with magnitude-scaled markers
* **Day/Night Cycle** — Solar terminator overlay showing global daylight/darkness
* **Global Markets Ticker** — Live financial market indices (minimizable)
* **Measurement Tool** — Point-to-point distance & bearing measurement on the map
* **LOCATE Bar** — Search by coordinates (31.8, 34.8) or place name (Tehran, Strait of Hormuz) to fly directly to any location — geocoded via OpenStreetMap Nominatim

![Gaza](https://github.com/user-attachments/assets/f2c953b2-3528-4360-af5a-7ea34ff28489)

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────┐
│                   FRONTEND (Next.js)                   │
│                                                        │
│  ┌─────────────┐    ┌──────────┐    ┌───────────────┐  │
│  │ MapLibre GL │    │ NewsFeed │    │ Control Panels│  │
│  │  2D WebGL   │    │  SIGINT  │    │ Layers/Filters│  │
│  │ Map Render  │    │  Intel   │    │ Markets/Radio │  │
│  └──────┬──────┘    └────┬─────┘    └───────┬───────┘  │
│         └────────────────┼──────────────────┘          │
│                          │ REST API (60s / 120s)       │
├──────────────────────────┼─────────────────────────────┤
│                    BACKEND (FastAPI)                   │
│                          │                             │
│  ┌───────────────────────┼──────────────────────────┐  │
│  │               Data Fetcher (Scheduler)           │  │
│  │                                                  │  │
│  │  ┌──────────┬──────────┬──────────┬───────────┐  │  │
│  │  │ OpenSky  │ adsb.lol │CelesTrak │   USGS    │  │  │
│  │  │ Flights  │ Military │   Sats   │  Quakes   │  │  │
│  │  ├──────────┼──────────┼──────────┼───────────┤  │  │
│  │  │  AIS WS  │ Carrier  │  GDELT   │   CCTV    │  │  │
│  │  │  Ships   │ Tracker  │ Conflict │  Cameras  │  │  │
│  │  ├──────────┼──────────┼──────────┼───────────┤  │  │
│  │  │ DeepState│   RSS    │  Region  │    GPS    │  │  │
│  │  │ Frontline│  Intel   │ Dossier  │  Jamming  │  │  │
│  │  ├──────────┼──────────┼──────────┼───────────┤  │  │
│  │  │  NASA    │  NOAA    │  IODA    │  KiwiSDR  │  │  │
│  │  │  FIRMS   │  Space Wx│ Outages  │  Radios   │  │  │
│  │  └──────────┴──────────┴──────────┴───────────┘  │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
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
| [Transport for London](https://api.tfl.gov.uk) | London CCTV JamCams | ~5min | No |
| [TxDOT](https://its.txdot.gov) | Austin TX traffic cameras | ~5min | No |
| [NYC DOT](https://webcams.nyctmc.org) | NYC traffic cameras | ~5min | No |
| [Singapore LTA](https://datamall.lta.gov.sg) | Singapore traffic cameras | ~5min | **Yes** |
| [DGT Spain](https://nap.dgt.es) | Spanish national road cameras | ~10min | No |
| [Madrid Open Data](https://datos.madrid.es) | Madrid urban traffic cameras | ~10min | No |
| [Málaga Open Data](https://datosabiertos.malaga.eu) | Málaga traffic cameras | ~10min | No |
| [Vigo Open Data](https://datos.vigo.org) | Vigo traffic cameras | ~10min | No |
| [Vitoria-Gasteiz](https://www.vitoria-gasteiz.org) | Vitoria-Gasteiz traffic cameras | ~10min | No |
| [RestCountries](https://restcountries.com) | Country profile data | On-demand (cached 24h) | No |
| [Wikidata SPARQL](https://query.wikidata.org) | Head of state data | On-demand (cached 24h) | No |
| [Wikipedia API](https://en.wikipedia.org/api) | Location summaries & aircraft images | On-demand (cached) | No |
| [NASA GIBS](https://gibs.earthdata.nasa.gov) | MODIS Terra daily satellite imagery | Daily (24-48h delay) | No |
| [Esri World Imagery](https://www.arcgis.com) | High-res satellite basemap | Static (periodically updated) | No |
| [MS Planetary Computer](https://planetarycomputer.microsoft.com) | Sentinel-2 L2A scenes (right-click) | On-demand | No |
| [KiwiSDR](https://kiwisdr.com) | Public SDR receiver locations | ~30min | No |
| [OSM Nominatim](https://nominatim.openstreetmap.org) | Place name geocoding (LOCATE bar) | On-demand | No |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) | NOAA-20 VIIRS fire/thermal hotspots | ~120s | No |
| [NOAA SWPC](https://services.swpc.noaa.gov) | Space weather Kp index & solar events | ~120s | No |
| [IODA (Georgia Tech)](https://ioda.inetintel.cc.gatech.edu) | Regional internet outage alerts | ~120s | No |
| [DC Map (GitHub)](https://github.com/Ringmast4r/Data-Center-Map---Global) | Global data center locations | Static (cached 7d) | No |
| [CARTO Basemaps](https://carto.com) | Dark map tiles | Continuous | No |

---

## 🚀 Getting Started

### 🐳 Docker / Podman Setup (Recommended for Self-Hosting)

The repo includes a `docker-compose.yml` that builds both images locally.

```bash
git clone https://github.com/BigBodyCobain/Shadowbroker.git
cd Shadowbroker
# Add your API keys in a repo-root .env file (optional — see Environment Variables below)
./compose.sh up -d
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

If you prefer to call the container engine directly, Podman users can run `podman compose up -d`, or force the wrapper to use Podman with `./compose.sh --engine podman up -d`.
Depending on your local Podman configuration, `podman compose` may still delegate to an external compose provider while talking to the Podman socket.

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
   **Mac/Linux:** Open terminal, type `chmod +x start.sh`, `dos2unix start.sh`, and run `./start.sh`.
5. It will automatically install everything and launch the dashboard!

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
git clone https://github.com/your-username/shadowbroker.git
cd shadowbroker/live-risk-dashboard

# Backend setup
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt   # includes pystac-client for Sentinel-2

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

All layers are independently toggleable from the left panel:

| Layer | Default | Description |
|---|---|---|
| Commercial Flights | ✅ ON | Airlines, cargo, GA aircraft |
| Private Flights | ✅ ON | Non-commercial private aircraft |
| Private Jets | ✅ ON | High-value bizjets with owner data |
| Military Flights | ✅ ON | Military & government aircraft |
| Tracked Aircraft | ✅ ON | Special interest watch list |
| Satellites | ✅ ON | Orbital assets by mission type |
| Carriers / Mil / Cargo | ✅ ON | Navy carriers, cargo ships, tankers |
| Civilian Vessels | ❌ OFF | Yachts, fishing, recreational |
| Cruise / Passenger | ✅ ON | Cruise ships and ferries |
| Tracked Yachts | ✅ ON | Billionaire & oligarch superyachts (Yacht-Alert DB) |
| Earthquakes (24h) | ✅ ON | USGS seismic events |
| CCTV Mesh | ❌ OFF | Surveillance camera network |
| Ukraine Frontline | ✅ ON | Live warfront positions |
| Global Incidents | ✅ ON | GDELT conflict events |
| GPS Jamming | ✅ ON | NAC-P degradation zones |
| MODIS Terra (Daily) | ❌ OFF | NASA GIBS daily satellite imagery |
| High-Res Satellite | ❌ OFF | Esri sub-meter satellite imagery |
| KiwiSDR Receivers | ❌ OFF | Public SDR radio receivers |
| Fire Hotspots (24h) | ❌ OFF | NASA FIRMS VIIRS thermal anomalies |
| Internet Outages | ❌ OFF | IODA regional connectivity alerts |
| Data Centers | ❌ OFF | Global data center locations (2,000+) |
| Day / Night Cycle | ✅ ON | Solar terminator overlay |

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
live-risk-dashboard/
├── backend/
│   ├── main.py                     # FastAPI app, middleware, API routes
│   ├── carrier_cache.json          # Persisted carrier OSINT positions
│   ├── cctv.db                     # SQLite CCTV camera database
│   ├── config/
│   │   └── news_feeds.json         # User-customizable RSS feed list (persists across restarts)
│   └── services/
│       ├── data_fetcher.py         # Core scheduler — fetches all data sources
│       ├── ais_stream.py           # AIS WebSocket client (25K+ vessels)
│       ├── carrier_tracker.py      # OSINT carrier position tracker
│       ├── cctv_pipeline.py        # Multi-source CCTV camera ingestion
│       ├── geopolitics.py          # GDELT + Ukraine frontline fetcher
│       ├── region_dossier.py       # Right-click country/city intelligence
│       ├── radio_intercept.py      # Scanner radio feed integration
│       ├── kiwisdr_fetcher.py      # KiwiSDR receiver scraper
│       ├── sentinel_search.py      # Sentinel-2 STAC imagery search
│       ├── network_utils.py        # HTTP client with curl fallback
│       ├── api_settings.py         # API key management
│       └── news_feed_config.py     # RSS feed config manager (add/remove/weight feeds)
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   └── page.tsx            # Main dashboard — state, polling, layout
│   │   └── components/
│   │       ├── MaplibreViewer.tsx   # Core map — 2,000+ lines, all GeoJSON layers
│   │       ├── NewsFeed.tsx         # SIGINT feed + entity detail panels
│   │       ├── WorldviewLeftPanel.tsx   # Data layer toggles
│   │       ├── WorldviewRightPanel.tsx  # Search + filter sidebar
│   │       ├── FilterPanel.tsx     # Basic layer filters
│   │       ├── AdvancedFilterModal.tsx  # Airport/country/owner filtering
│   │       ├── MapLegend.tsx       # Dynamic legend with all icons
│   │       ├── MarketsPanel.tsx    # Global financial markets ticker
│   │       ├── RadioInterceptPanel.tsx # Scanner-style radio panel
│   │       ├── FindLocateBar.tsx   # Search/locate bar
│   │       ├── ChangelogModal.tsx  # Version changelog popup
│   │       ├── SettingsPanel.tsx   # App settings (API Keys + News Feed manager)
│   │       ├── ScaleBar.tsx        # Map scale indicator
│   │       ├── WikiImage.tsx       # Wikipedia image fetcher
│   │       └── ErrorBoundary.tsx   # Crash recovery wrapper
│   └── package.json
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
```

### Frontend

| Variable | Where to set | Purpose |
|---|---|---|
| `BACKEND_URL` | `environment` in `docker-compose.yml`, or shell env | URL the Next.js server uses to proxy API calls to the backend. Defaults to `http://backend:8000`. **Runtime variable — no rebuild needed.** |

**How it works:** The frontend proxies all `/api/*` requests through the Next.js server to `BACKEND_URL` using Docker's internal networking. Browsers only talk to port 3000; port 8000 never needs to be exposed externally. For local dev without Docker, `BACKEND_URL` defaults to `http://localhost:8000`.

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
