<p align="center">
  <h1 align="center">🛰️ S H A D O W B R O K E R</h1>
  <p align="center"><strong>Global Threat Intercept — Real-Time Geospatial Intelligence Platform</strong></p>
  <p align="center">
    
  </p>
</p>

---
![Shadowbroker1](https://github.com/user-attachments/assets/000b94eb-bf33-4e8b-8c60-15ca4a723c68)
**ShadowBroker** is a real-time, full-spectrum geospatial intelligence dashboard that aggregates live data from dozens of open-source intelligence (OSINT) feeds and renders them on a unified dark-ops map interface. It tracks aircraft, ships, satellites, earthquakes, conflict zones, CCTV networks, GPS jamming, and breaking geopolitical events — all updating in real time.

Built with **Next.js**, **MapLibre GL**, **FastAPI**, and **Python**, it's designed for analysts, researchers, and enthusiasts who want a single-pane-of-glass view of global activity.

---

## ✨ Features

### 🛩️ Aviation Tracking

- **Commercial Flights** — Real-time positions via OpenSky Network (~5,000+ aircraft)
- **Private Aircraft** — Light GA, turboprops, bizjets tracked separately
- **Private Jets** — High-net-worth individual aircraft with owner identification
- **Military Flights** — Tankers, ISR, fighters, transports via adsb.lol military endpoint
- **Flight Trail Accumulation** — Persistent breadcrumb trails for all tracked aircraft
- **Holding Pattern Detection** — Automatically flags aircraft circling (>300° total turn)
- **Aircraft Classification** — Shape-accurate SVG icons: airliners, turboprops, bizjets, helicopters
- **Grounded Detection** — Aircraft below 100ft AGL rendered with grey icons

### 🚢 Maritime Tracking

- **AIS Vessel Stream** — 25,000+ vessels via aisstream.io WebSocket (real-time)
- **Ship Classification** — Cargo, tanker, passenger, yacht, military vessel types with color-coded icons
- **Carrier Strike Group Tracker** — All 11 active US Navy aircraft carriers with OSINT-estimated positions
  - Automated GDELT news scraping for carrier movement intelligence
  - 50+ geographic region-to-coordinate mappings
  - Disk-cached positions, auto-updates at 00:00 & 12:00 UTC
- **Cruise & Passenger Ships** — Dedicated layer for cruise liners and ferries
- **Clustered Display** — Ships cluster at low zoom with count labels, decluster on zoom-in

### 🛰️ Space & Satellites

- **Orbital Tracking** — Real-time satellite positions from N2YO API
- **Mission-Type Classification** — Color-coded by mission: military recon (red), SAR (cyan), SIGINT (white), navigation (blue), early warning (magenta), commercial imaging (green), space station (gold)

### 🌍 Geopolitics & Conflict

- **Global Incidents** — GDELT-powered conflict event aggregation (last 8 hours, ~1,000 events)
- **Ukraine Frontline** — Live warfront GeoJSON from DeepState Map
- **SIGINT/RISINT News Feed** — Real-time RSS aggregation from multiple intelligence-focused sources
- **Region Dossier** — Right-click anywhere on the map for:
  - Country profile (population, capital, languages, currencies, area)
  - Head of state & government type (Wikidata SPARQL)
  - Local Wikipedia summary with thumbnail

### 📷 Surveillance

- **CCTV Mesh** — 2,000+ live traffic cameras from:
  - 🇬🇧 Transport for London JamCams
  - 🇺🇸 Austin, TX TxDOT
  - 🇺🇸 NYC DOT
  - 🇸🇬 Singapore LTA
  - Custom URL ingestion
- **Feed Rendering** — Automatic detection & rendering of video, MJPEG, HLS, embed, satellite tile, and image feeds
- **Clustered Map Display** — Green dots cluster with count labels, decluster on zoom

### 📡 Signal Intelligence

- **GPS Jamming Detection** — Real-time analysis of aircraft NAC-P (Navigation Accuracy Category) values
  - Grid-based aggregation identifies interference zones
  - Red overlay squares with "GPS JAM XX%" severity labels
- **Radio Intercept Panel** — Scanner-style UI for monitoring communications

### 🌐 Additional Layers

- **Earthquakes (24h)** — USGS real-time earthquake feed with magnitude-scaled markers
- **Day/Night Cycle** — Solar terminator overlay showing global daylight/darkness
- **Global Markets Ticker** — Live financial market indices (minimizable)
- **Measurement Tool** — Point-to-point distance & bearing measurement on the map

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js)                 │
│                                                      │
│  ┌─────────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │ MapLibre GL │  │ NewsFeed │  │  Control Panels  │ │
│  │  2D WebGL   │  │  SIGINT  │  │ Layers/Filters   │ │
│  │  Map Render │  │  Intel   │  │ Markets/Radio    │ │
│  └──────┬──────┘  └────┬─────┘  └────────┬────────┘ │
│         └──────────────┼─────────────────┘           │
│                        │ REST API (15s fast / 60s slow│
├────────────────────────┼─────────────────────────────┤
│                    BACKEND (FastAPI)                   │
│                        │                              │
│  ┌─────────────────────┼─────────────────────────┐   │
│  │              Data Fetcher (Scheduler)          │   │
│  │  ┌──────────┬──────────┬──────────┬─────────┐ │   │
│  │  │ OpenSky  │ adsb.lol │  N2YO    │  USGS   │ │   │
│  │  │ Flights  │ Military │ Sats     │ Quakes  │ │   │
│  │  ├──────────┼──────────┼──────────┼─────────┤ │   │
│  │  │ AIS WS   │ Carrier  │  GDELT   │  CCTV   │ │   │
│  │  │ Ships    │ Tracker  │ Conflict │ Cameras │ │   │
│  │  ├──────────┼──────────┼──────────┼─────────┤ │   │
│  │  │ DeepState│ RSS      │ Region   │  GPS    │ │   │
│  │  │ Frontline│ Intel    │ Dossier  │ Jamming │ │   │
│  │  └──────────┴──────────┴──────────┴─────────┘ │   │
│  └───────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```

---

## 📊 Data Sources & APIs

| Source | Data | Update Frequency | API Key Required |
|---|---|---|---|
| [OpenSky Network](https://opensky-network.org) | Commercial & private flights | ~60s | Optional (anonymous limited) |
| [adsb.lol](https://adsb.lol) | Military aircraft | ~60s | No |
| [aisstream.io](https://aisstream.io) | AIS vessel positions | Real-time WebSocket | **Yes** |
| [N2YO](https://www.n2yo.com) | Satellite orbital positions | ~60s | **Yes** |
| [USGS Earthquake](https://earthquake.usgs.gov) | Global seismic events | ~60s | No |
| [GDELT Project](https://www.gdeltproject.org) | Global conflict events | ~6h | No |
| [DeepState Map](https://deepstatemap.live) | Ukraine frontline | ~30min | No |
| [Transport for London](https://api.tfl.gov.uk) | London CCTV JamCams | ~5min | No |
| [TxDOT](https://its.txdot.gov) | Austin TX traffic cameras | ~5min | No |
| [NYC DOT](https://webcams.nyctmc.org) | NYC traffic cameras | ~5min | No |
| [Singapore LTA](https://datamall.lta.gov.sg) | Singapore traffic cameras | ~5min | **Yes** |
| [RestCountries](https://restcountries.com) | Country profile data | On-demand (cached 24h) | No |
| [Wikidata SPARQL](https://query.wikidata.org) | Head of state data | On-demand (cached 24h) | No |
| [Wikipedia API](https://en.wikipedia.org/api) | Location summaries & aircraft images | On-demand (cached) | No |
| [CARTO Basemaps](https://carto.com) | Dark map tiles | Continuous | No |

---

## 🚀 Getting Started

### 📦 Quick Start (No Code Required)

If you just want to run the dashboard without dealing with terminal commands:

1. Go to the **[Releases](../../releases)** tab on the right side of this GitHub page.
2. Download the `ShadowBroker_v0.1.zip` file.
3. Extract the folder to your computer.
4. **Windows:** Double-click `start.bat`.
   **Mac/Linux:** Open terminal, type `chmod +x start.sh`, and run `./start.sh`.
5. It will automatically install everything and launch the dashboard!

---

### 💻 Developer Setup

If you want to modify the code or run from source:

#### Prerequisites

- **Node.js** 18+ and **npm**
- **Python** 3.10+ with `pip`
- API keys for: `aisstream.io`, `n2yo.com` (and optionally `opensky-network.org`, `lta.gov.sg`)

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
pip install -r requirements.txt

# Create .env with your API keys
echo "AISSTREAM_API_KEY=your_key_here" >> .env
echo "N2YO_API_KEY=your_key_here" >> .env
echo "OPENSKY_USERNAME=your_user" >> .env
echo "OPENSKY_PASSWORD=your_pass" >> .env

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

- **Next.js** frontend on `http://localhost:3000`
- **FastAPI** backend on `http://localhost:8000`

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
| Earthquakes (24h) | ✅ ON | USGS seismic events |
| CCTV Mesh | ❌ OFF | Surveillance camera network |
| Ukraine Frontline | ✅ ON | Live warfront positions |
| Global Incidents | ✅ ON | GDELT conflict events |
| GPS Jamming | ✅ ON | NAC-P degradation zones |
| Day / Night Cycle | ✅ ON | Solar terminator overlay |

---

## 🔧 Performance

The platform is optimized for handling massive real-time datasets:

- **Gzip Compression** — API payloads compressed ~92% (11.6 MB → 915 KB)
- **ETag Caching** — `304 Not Modified` responses skip redundant JSON parsing
- **Viewport Culling** — Only features within the visible map bounds (+20% buffer) are rendered
- **Clustered Rendering** — Ships, CCTV, and earthquakes use MapLibre clustering to reduce feature count
- **Debounced Viewport Updates** — 300ms debounce prevents GeoJSON rebuild thrash during pan/zoom
- **Position Interpolation** — Smooth 10s tick animation between data refreshes
- **React.memo** — Heavy components wrapped to prevent unnecessary re-renders
- **Coordinate Precision** — Lat/lng rounded to 5 decimals (~1m) to reduce JSON size

---

## 📁 Project Structure

```
live-risk-dashboard/
├── backend/
│   ├── main.py                     # FastAPI app, middleware, API routes
│   ├── carrier_cache.json          # Persisted carrier OSINT positions
│   ├── cctv.db                     # SQLite CCTV camera database
│   └── services/
│       ├── data_fetcher.py         # Core scheduler — fetches all data sources
│       ├── ais_stream.py           # AIS WebSocket client (25K+ vessels)
│       ├── carrier_tracker.py      # OSINT carrier position tracker
│       ├── cctv_pipeline.py        # Multi-source CCTV camera ingestion
│       ├── geopolitics.py          # GDELT + Ukraine frontline fetcher
│       ├── region_dossier.py       # Right-click country/city intelligence
│       ├── radio_intercept.py      # Scanner radio feed integration
│       ├── network_utils.py        # HTTP client with curl fallback
│       └── api_settings.py         # API key management
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
│   │       ├── SettingsPanel.tsx   # App settings
│   │       ├── ScaleBar.tsx        # Map scale indicator
│   │       ├── WikiImage.tsx       # Wikipedia image fetcher
│   │       └── ErrorBoundary.tsx   # Crash recovery wrapper
│   └── package.json
```

---

## 🔑 Environment Variables

Create a `.env` file in the `backend/` directory:

```env
# Required
AISSTREAM_API_KEY=your_aisstream_key      # Maritime vessel tracking
N2YO_API_KEY=your_n2yo_key               # Satellite position data

# Optional (enhances data quality)
OPENSKY_CLIENT_ID=your_opensky_client_id  # Higher rate limits for flight data
OPENSKY_CLIENT_SECRET=your_opensky_secret
LTA_ACCOUNT_KEY=your_lta_key             # Singapore CCTV cameras
```

---

## ⚠️ Disclaimer

This is an **educational and research tool** built entirely on publicly available, open-source intelligence (OSINT) data. No classified, restricted, or non-public data sources are used. Carrier positions are estimates based on public reporting. The military-themed UI is purely aesthetic.

**Do not use this tool for any operational, military, or intelligence purpose.**

---

## 📜 License

This project is for educational and personal research purposes. See individual API provider terms of service for data usage restrictions.

---

<p align="center">
  <sub>Built with ☕ and too many API calls</sub>
</p>
