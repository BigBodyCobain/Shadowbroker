<p align="center">
  <h1 align="center">🛰️ S H A D O W B R O K E R</h1>
  <p align="center"><strong>Global Threat Intercept — Real-Time Geospatial Intelligence Platform</strong></p>
  <p align="center">

  </p>
</p>

---




![ShadowBroker](/uploads/46f99d19fa141a2efba37feee9de8aab/Title.jpg)





**ShadowBroker** is a decentralized real-time, multi-domain OSINT dashboard that fuses 60+ live intelligence feeds into a single dark-ops map interface. Aircraft, ships, satellites, conflict zones, CCTV networks, GPS jamming, internet-connected devices, police scanners, mesh radio nodes, and breaking geopolitical events — all updating in real time on one screen as well as a obfuscated communications protocol and information exchange infrastructure.

Built with **Next.js**, **MapLibre GL**, **FastAPI**, and **Python**. 35+ toggleable data layers including SAR ground-change detection. Multiple visual modes (DEFAULT / SATELLITE / FLIR / NVG / CRT). Right-click any point on Earth for a country dossier, head-of-state lookup, and the latest Sentinel-2 satellite photo. No user data is collected or transmitted — the dashboard runs entirely in your browser against a self-hosted backend.

Designed for analysts, researchers, radio operators, and anyone who wants to see what the world looks like when every public signal is on the same map.


## Why This Exists

A surprising amount of global telemetry is already public — aircraft ADS-B broadcasts, maritime AIS signals, satellite orbital data, earthquake sensors, mesh radio networks, police scanner feeds, environmental monitoring stations, internet infrastructure telemetry, and more. This data is scattered across dozens of tools and APIs. ShadowBroker combines all of it into a single interface.

The project does not introduce new surveillance capabilities — it aggregates and visualizes existing public datasets. It is fully open-source so anyone can audit exactly what data is accessed and how. No user data is collected or transmitted — everything runs locally against a self-hosted backend. No telemetry, no analytics, no accounts.

### Shodan Connector

ShadowBroker includes an optional Shodan connector for operator-supplied API access. Shodan results are fetched with your own `SHODAN_API_KEY`, rendered as a local investigative overlay (not merged into core feeds), and remain subject to Shodan’s terms of service.

---

## Interesting Use Cases

* **Communicate on the InfoNet testnet** — The first decentralized intelligence mesh built into an OSINT tool. Obfuscated messaging with gate personas, Dead Drop peer-to-peer exchange, and a built-in terminal CLI. No accounts, no signup. Privacy is not guaranteed yet — this is an experimental testnet — but the protocol is live and being hardened.
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
* **Connect an AI agent as a co-analyst** through ShadowBroker's HMAC-signed agentic command channel — supports OpenClaw and any other agent that speaks the protocol (Claude, GPT, LangChain, custom). The agent gets full read/write access to all 35+ data layers, pin placement, map control, SAR ground-change, mesh networking, and alert delivery. It sees everything the operator sees and can take actions on the map in real time.
* **Detect ground changes through cloud cover** with SAR (Synthetic Aperture Radar) — mm-scale ground deformation, flood extent, vegetation disturbance, and damage assessments from NASA OPERA and Copernicus EGMS. Define your own watch areas and get anomaly alerts. Free with a NASA Earthdata account.
* **Switch visual modes** — DEFAULT, SATELLITE, FLIR (thermal), NVG (night vision), CRT (retro terminal) — via the STYLE button
* **Track trains** across the US (Amtrak) and Europe (DigiTraffic) in real time

---

## ⚡ Quick Start (Docker)

```bash
git clone https://github.com/bigbodycobain/Shadowbroker.git
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
git clone https://github.com/bigbodycobain/Shadowbroker.git
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

ShadowBroker v0.9.7 ships **InfoNet** (decentralized intelligence mesh + Sovereign Shell governance economy), an **agentic AI command channel** (supports OpenClaw and any HMAC-signing agent), **Time Machine snapshot playback**, and **SAR satellite ground-change detection**. This is an **experimental testnet** — not a private messenger and not a production governance system.

| Channel | Privacy Status | Details |
|---|---|---|
| **Meshtastic / APRS** | **PUBLIC** | RF radio transmissions are public and interceptable by design. |
| **InfoNet Gate Chat** | **OBFUSCATED** | Messages are obfuscated with gate personas and canonical payload signing, but NOT end-to-end encrypted. Metadata is not hidden. |
| **Dead Drop DMs** | **STRONGEST CURRENT LANE** | Token-based epoch mailbox with SAS word verification. Strongest lane in this build, but not yet confidently private. |
| **Sovereign Shell governance** | **PUBLIC LEDGER** | Petitions, votes, upgrade hashes, and dispute stakes are signed events on a public hashchain. Pseudonymous via gate persona, but governance actions are intentionally observable. |
| **Privacy primitives (RingCT / stealth / DEX)** | **NOT YET WIRED** | Locked Protocol contracts are in place, but the cryptographic scheme has not been chosen. The privacy-core Rust crate is the integration target for a future sprint. |

**Do not transmit anything sensitive on any channel.** Treat all lanes as open and public for now. E2E encryption and deeper native/Tauri hardening are the next milestones. If you fork this project, keep these labels intact and do not make stronger privacy claims than the implementation supports.

> **For a full picture of what the mesh actually defends against and
> what it doesn't, read the
> [threat model](docs/mesh/threat-model.md) and the
> [claims reconciliation](docs/mesh/claims-reconciliation.md). Every
> sentence above is mapped there to the code path that enforces it (or
> doesn't).**

---


## ✨ Features

### 🧅 InfoNet — Decentralized Intelligence Mesh + Sovereign Shell (expanded in v0.9.7)

The first decentralized intelligence communication and governance layer built directly into an OSINT platform. No accounts, no signup, no identity required. v0.9.7 promotes InfoNet from a chat layer into a full governance economy with a clear path to a privacy-preserving decentralized intelligence platform.

**Communication layer (since v0.9.6):**

* **InfoNet Experimental Testnet** — A global, obfuscated message relay. Anyone running ShadowBroker can transmit and receive on the InfoNet. Messages pass through a Wormhole relay layer with gate personas, Ed25519 canonical payload signing, and transport obfuscation.
* **Mesh Chat Panel** — Three-tab interface: **INFONET** (gate chat with obfuscated transport), **MESH** (Meshtastic radio integration), **DEAD DROP** (peer-to-peer message exchange with token-based epoch mailboxes — strongest current lane).
* **Gate Persona System** — Pseudonymous identities with Ed25519 signing keys, prekey bundles, SAS word contact verification, and abuse reporting.
* **Mesh Terminal** — Built-in CLI: `send`, `dm`, market commands, gate state inspection. Draggable panel, minimizes to the top bar. Type `help` to see all commands.
* **Crypto Stack** — Ed25519 signing, X25519 Diffie-Hellman, AESGCM encryption with HKDF key derivation, hash chain commitment system. Double-ratchet DM scaffolding in progress.

**Sovereign Shell — governance economy (NEW in v0.9.7):**

* **Petitions + Governance DSL** — On-chain parameter changes via signed petitions. Type-safe payload executor for `UPDATE_PARAM`, `BATCH_UPDATE_PARAMS`, `ENABLE_FEATURE`, and `DISABLE_FEATURE`. Tunable knobs change by vote — no code deploys required.
* **Upgrade-Hash Governance** — Protocol upgrades that need new logic (not just parameter changes) vote on a SHA-256 hash of the verified release. 80% supermajority, 40% quorum, 67% Heavy-Node activation. Lifecycle: signatures → voting → challenge window → awaiting readiness → activated.
* **Resolution & Dispute Markets** — Stake on market resolution outcomes (yes / no / data_unavailable), open disputes with bonded evidence, and stake on dispute confirm-or-reverse. Per-row submission state stays isolated so concurrent actions don't share an in-flight slot.
* **Evidence Submission** — Bonded evidence bundles with client-side SHA-256 canonicalization that matches Python `repr()` exactly, so hashes round-trip cleanly through the chain.
* **Gate Suspension / Shutdown / Appeals** — Filing forms for suspending or shutting down a gate, with a reusable appeal flow auto-targeting the pending petition.
* **Bootstrap Eligible-Node-One-Vote** — The first 100 markets resolve via one-vote-per-eligible-node instead of stake-weighted resolution. Eligibility: identity age ≥ 3 days, not in predictor exclusion set, valid Argon2id PoW (Heavy-Node-only). Transitions to staked resolution at 1000 nodes.
* **Two-Tier State + Epoch Finality** — Tier 1 events propagate CRDT-style for low latency; Tier 2 events require epoch finality before they can be acted on. Identity rotation, progressive penalties, ramp milestones, and constitutional invariants enforced via `MappingProxyType`.
* **Adaptive Polling** — Sovereign Shell views poll every 8 seconds during active voting / challenge / activation phases, every 30–60 seconds when idle. Voting feels live without a websocket layer.
* **Verbatim Diagnostics** — Every write button surfaces the backend's verbatim rejection reason. No opaque "denied" toasts.

**Privacy primitive runway (NEW in v0.9.7):**

* **Function Keys — Anonymous Citizenship Proof** — A citizen proves "I am an Infonet citizen" without revealing their Infonet identity. 5 of 6 pieces shipped: nullifiers, challenge-response, two-phase commit receipts, enumerated denial codes, batched settlement. Issuance via blind signatures waits on a primitive decision (RSA blind sigs vs BBS+ vs U-Prove vs Idemix).
* **Locked Protocol Contracts** — Stable interfaces in `services/infonet/privacy/contracts.py` for ring signatures, stealth addresses, Pedersen commitments, range proofs, and DEX matching. The `privacy-core` Rust crate is the integration target — no caller of the privacy module needs to know which scheme is active.
* **Sprint 11+ Path** — When the cryptographic scheme is chosen, primitives wire into the locked Protocols without API churn.

> **Experimental Testnet — No Privacy Guarantee:** InfoNet messages are obfuscated but NOT end-to-end encrypted. The Mesh network (Meshtastic/APRS) is NOT private — radio transmissions are inherently public. The privacy primitive contracts are scaffolded but not yet wired. Do not send anything sensitive on any channel. Treat all channels as open and public for now.

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

### 🛰️ SAR Ground-Change Detection (NEW)

* **Synthetic Aperture Radar Layer** — Detects ground changes through cloud cover, at night, anywhere on Earth. Two modes, both free:
  * **Mode A (Catalog)** — Free Sentinel-1 scene metadata from Alaska Satellite Facility. No account required. Shows when radar passes happened over your AOIs and when the next pass is coming.
  * **Mode B (Full Anomalies)** — Real-time ground-change alerts from NASA OPERA (DISP, DSWx, DIST-ALERT) and Copernicus EGMS. Requires a free NASA Earthdata account — the in-app wizard walks you through setup in under a minute.
* **Anomaly Types** — Ground deformation (mm-scale subsidence, landslides), surface water change (flood extent), vegetation disturbance (deforestation, burn scars, blast craters), damage assessments (UNOSAT/Copernicus EMS verified), and coherence change detection
* **Map Visualization** — Color-coded anomaly pins by kind (orange for deformation, cyan for water, green for vegetation, red for damage, purple for coherence). AOI boundaries drawn as dashed polygons with category-based coloring. Click any pin for a detail popup with magnitude, confidence, solver, scene count, and provenance link.
* **AOI Editor** — Define areas of interest directly from the map. Click the "EDIT AOIs" button when the SAR layer is active, then use the crosshair tool to click-to-drop an AOI center on the map. Set name, radius (1–500 km), and category. AOIs appear on the map immediately.
* **OpenClaw Integration** — The AI agent can inspect SAR anomaly details (`sar_pin_click`) and fly the operator's map to any AOI center (`sar_focus_aoi`) — enabling collaborative analyst workflows.
* **Settings Panel** — Dedicated SAR tab in Settings shows Mode A/B status, OpenClaw integration state, and lets you revoke Earthdata credentials with one click.

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

![Gaza](https://gitlab.com/bigbodycobain/Shadowbroker/uploads/c55a0c8d49e5e05c6cd094279e6e089b/gaza-screenshot.jpg)

### 🤖 Agentic AI Command Channel — OpenClaw + Compatible Agents (expanded in v0.9.7)

ShadowBroker exposes a **bidirectional agentic AI command channel** — a signed, tier-gated bridge that gives any compatible AI agent full read/write access to the intelligence platform. **OpenClaw is the reference agent**, but the channel is an open protocol: any LLM-driven agent that signs requests with HMAC-SHA256 (Claude Code, GPT, LangChain, custom Python/TypeScript clients, or your own integration) can connect as an analyst that sees the same data as the operator and can take actions on the map. ShadowBroker does *not* bundle an LLM, an agent runtime, or model weights — it provides the surface; you bring the agent.

v0.9.7 turns ShadowBroker from a dashboard a human watches into an intelligence surface any agent can act on.

**Channel transport (NEW in v0.9.7):**

* **Single Command Channel** — `POST /api/ai/channel/command` accepts `{cmd, args}` and dispatches to any registered tool.
* **Batched Concurrent Execution** — `POST /api/ai/channel/batch` accepts up to 20 commands in one request. The backend runs them concurrently and returns a fan-out result map. Cuts agent latency by an order of magnitude over sequential calls.
* **Tier-Gated Access** — `OPENCLAW_ACCESS_TIER` controls which commands the agent can call: `restricted` exposes the read-only set, `full` adds writes and injection. Discovery endpoint returns `available_commands` so the agent can introspect its own capabilities.
* **HMAC-SHA256 Signing** — Every command is signed `HMAC-SHA256(secret, METHOD|path|timestamp|nonce|sha256(body))` with timestamp + nonce replay protection and request integrity. Supports local mode (no config) and remote mode (agent on a different machine / VPS).

**Capabilities:**

* **Full Telemetry Access** — The agent queries all 35+ data layers: flights, ships, satellites, SIGINT, conflict events, earthquakes, fires, wastewater, prediction markets, and more. Fast and slow tier endpoints return enriched data with geographic coordinates, timestamps, and source attribution.
* **AI Intel Pins** — Place color-coded investigation markers directly on the operator's map. 14 pin categories (threat, anomaly, military, maritime, aviation, SIGINT, infrastructure, etc.) with confidence scores, TTL expiry, source URLs, and batch placement up to 100 pins at once.
* **Map Control** — Fly the operator's map view to any coordinate, trigger satellite imagery lookups, and open region dossiers. The agent can direct the operator's attention to specific locations in real time.
* **SAR Ground-Change** — Query SAR anomaly feeds, inspect pin details, manage AOIs, and fly the map to watch areas. The agent can monitor for ground deformation, flood extent, or damage and promote anomalies to pins.
* **Native Layer Injection** — Push custom data directly into ShadowBroker's native layers (CCTV cameras, ships, SIGINT nodes, military bases, etc.) so agent-discovered sources render alongside real feeds.
* **Wormhole Mesh Participation** — The agent can join the decentralized InfoNet, post signed messages, join encrypted gate channels, send/receive encrypted DMs, and interact with Meshtastic radio and Dead Drops — operating as a full mesh peer.
* **Sovereign Shell Participation (v0.9.7)** — File petitions, sign and vote on governance changes, stake on resolutions and disputes, signal Heavy-Node readiness for upgrades — all programmatically, all gated by tier and HMAC. Agents become first-class participants in the decentralized intelligence economy.
* **Geocoding & Proximity Scans** — Resolve place names to coordinates, then scan all layers within a radius for a complete proximity digest.
* **News & GDELT Near Location** — Pull GDELT conflict events and aggregated news articles near any coordinate for regional situational awareness.
* **Alert Delivery** — Send branded intelligence briefs, warnings, and threat notifications to Discord webhooks and Telegram channels.
* **Intelligence Reports** — Generate structured reports with summary stats, top military flights, correlations, earthquake activity, SIGINT counts, and pin inventories.
* **Auditable** — Every channel call is logged; the operator can introspect what the agent has done.

**Connect an agent:** Open the AI Intel panel in the left sidebar, click **Connect Agent**, and copy the HMAC secret. From there, point any compatible agent at the channel — for OpenClaw, import `ShadowBrokerClient` from the OpenClaw skill package; for any other agent, use the same HMAC contract documented above (timestamp + nonce + body digest, tier-gated). The channel is the protocol, not the agent.

### ⏱️ Time Machine — Snapshot Playback (NEW in v0.9.7)

A media-style transport for the entire telemetry feed. Treat the live map as a recording that can be scrubbed, paused, and replayed.

* **Live ↔ Snapshot Toggle** — Switching to snapshot mode pauses the global polling loop instantly; switching back to Live invalidates ETags and force-refreshes both fast and slow tiers so the dashboard catches up without a stale-frame flicker.
* **Hourly Index** — Every captured snapshot is indexed by its hour bucket with `count`, `latest_id`, `latest_ts`, and the full `snapshot_ids` list. Jump to any captured timestamp directly from the timeline scrubber.
* **Frame Interpolation** — Moving entities (aircraft, ships, satellites, military flights) interpolate smoothly between recorded frames during playback so motion stays continuous even when snapshots are sparse.
* **Variable Playback Speed** — Step, play, fast-forward, and rewind through saved telemetry at adjustable speed.
* **Profile-Aware** — Each snapshot records the privacy profile that was active when it was captured, so playback is faithful to what an operator on that profile would have seen.
* **Operator-Side, Not Server-Side** — Snapshots are stored locally in the backend; no third party ever sees the playback timeline.

### 📦 API Keys Panel — Path-First, Read-Only (NEW in v0.9.7)

Settings → API Keys is now a read-only registry. Key values never reach the browser process — not even an obfuscated prefix. The panel surfaces:

* The absolute path to the backend `.env` file as resolved by `Path(__file__).resolve()` — works on every OS, every drive, every install location (Linux `/home/...`, macOS `/Users/...`, Windows on any drive, Docker containers, cloud VMs).
* `[exists]` / `[will be created on first save]` / `[NOT WRITABLE — edit by hand]` indicators on the path itself.
* The path to the `.env.example` template so users can copy it and fill in their keys.
* A binary `CONFIGURED` / `NOT CONFIGURED` badge per key, plus a copy-pastable env line (e.g. `OPENSKY_CLIENT_ID=YOUR_VALUE`) the user can drop into the file by hand.

OpenSky API credentials are now a **critical-warn** environment requirement: the startup environment check flags missing OpenSky OAuth2 credentials with a strong warning, and the changelog modal links directly to the free registration page. Without them, the flights layer falls back to ADS-B-only coverage with significant gaps in Africa, Asia, and Latin America.

---

## 🏗️ Architecture

ShadowBroker v0.9.7 is composed of three vertically-stacked planes — the **Operator UI**, the **Backend Service Plane**, and the **Decentralized Layer (InfoNet)** — plus two cross-cutting bridges (the **Time Machine** and the **Agentic AI Channel**, which is the protocol that OpenClaw and any other compatible agent connects through) and a **Privacy Core** Rust crate that backstops both the legacy mesh and the future shielded coin / DEX work.

```
╔═════════════════════════════════════════════════════════════════════════════╗
║                       OPERATOR UI  (Next.js + MapLibre)                     ║
║                                                                             ║
║  ┌────────────────┐  ┌──────────┐  ┌────────────────┐  ┌────────────────┐   ║
║  │ MapLibre GL    │  │ NewsFeed │  │ Sovereign Shell│  │   Mesh Chat    │   ║
║  │  WebGL render  │  │  SIGINT  │  │  Petitions /   │  │  + Mesh Term.  │   ║
║  │  + clusters    │  │  GDELT   │  │  Upgrades /    │  │  (Infonet /    │   ║
║  │                │  │  Threat  │  │  Disputes /    │  │   Mesh /       │   ║
║  │                │  │          │  │  Gates /       │  │   Dead Drop)   │   ║
║  │                │  │          │  │  Bootstrap /   │  │                │   ║
║  │                │  │          │  │  Function Keys │  │                │   ║
║  └──────┬─────────┘  └────┬─────┘  └────────┬───────┘  └────────┬───────┘   ║
║         │                 │                 │                   │           ║
║  ┌──────┴─────────────────┴─────────────────┴───────────────────┴───────┐   ║
║  │  Time Machine ◀── snapshot playback ── snapshotMode toggle ──▶ Live │   ║
║  │  hourly index │ frame interpolation │ profile-aware │ per-tier ETag  │   ║
║  └──────────────────────────────────┬───────────────────────────────────┘   ║
║                                     │ REST  +  /api/[...path] proxy         ║
╠═════════════════════════════════════╪═══════════════════════════════════════╣
║                       BACKEND SERVICE PLANE  (FastAPI)                      ║
║                                     │                                       ║
║  ┌──────────────────────────────────┴────────────────────────────────────┐  ║
║  │              Data Fetcher  (APScheduler — fast / slow tiers)          │  ║
║  │                                                                       │  ║
║  │  ┌───────────┬───────────┬───────────┬───────────┬───────────┐        │  ║
║  │  │  OpenSky* │ adsb.lol  │ CelesTrak │   USGS    │   AIS WS  │        │  ║
║  │  │  Flights  │ Military  │   Sats    │  Quakes   │   Ships   │        │  ║
║  │  ├───────────┼───────────┼───────────┼───────────┼───────────┤        │  ║
║  │  │  Carrier  │   GDELT   │ CCTV (12) │ DeepState │   NASA    │        │  ║
║  │  │  Tracker  │ Conflict  │  Cameras  │ Frontline │   FIRMS   │        │  ║
║  │  ├───────────┼───────────┼───────────┼───────────┼───────────┤        │  ║
║  │  │   GPS     │  KiwiSDR  │  Shodan   │  Amtrak   │  SatNOGS  │        │  ║
║  │  │  Jamming  │   Radios  │  Devices  │ DigiTraf  │  TinyGS   │        │  ║
║  │  ├───────────┼───────────┼───────────┼───────────┼───────────┤        │  ║
║  │  │ Volcanoes │  Weather  │  Fishing  │ Mil Bases │   IODA    │        │  ║
║  │  │  Air Qual │  Alerts   │  Activity │ PwrPlants │  Outages  │        │  ║
║  │  ├───────────┼───────────┼───────────┼───────────┼───────────┤        │  ║
║  │  │ Sentinel  │   MODIS   │   VIIRS   │   Data    │ Meshtastic│        │  ║
║  │  │  Hub/STAC │   Terra   │ Nightlts  │  Centers  │   APRS    │        │  ║
║  │  ├───────────┴───────────┴───────────┴───────────┴───────────┤        │  ║
║  │  │  SAR (NEW v0.9.7)                                         │        │  ║
║  │  │   Mode A: ASF Search catalog (free, no account)           │        │  ║
║  │  │   Mode B: NASA OPERA / Copernicus EGMS / GFM / EMS /      │        │  ║
║  │  │           UNOSAT  ground-change anomalies (opt-in)        │        │  ║
║  │  └───────────────────────────────────────────────────────────┘        │  ║
║  │   * OpenSky: REQUIRED for global flight coverage                      │  ║
║  └───────────────────────────────────────────────────────────────────────┘  ║
║                                     │                                       ║
║  ┌──────────────────────────────────┴────────────────────────────────────┐  ║
║  │                   Snapshot Store  (Time Machine source)               │  ║
║  │   Hourly index  │  per-snapshot layer manifest  │  profile metadata   │  ║
║  └───────────────────────────────────────────────────────────────────────┘  ║
║                                                                             ║
║  ┌───────────────────────────────────────────────────────────────────────┐  ║
║  │   Agentic AI Channel  (HMAC-SHA256, tier-gated  —  OpenClaw + others) │  ║
║  │                                                                       │  ║
║  │   POST /api/ai/channel/command   →  one tool call                     │  ║
║  │   POST /api/ai/channel/batch     →  up to 20 concurrent tool calls    │  ║
║  │                                                                       │  ║
║  │   Tier:   restricted (read-only)   │   full (read + write + inject)   │  ║
║  │   Auth:   X-SB-Timestamp + X-SB-Nonce + X-SB-Signature                │  ║
║  │   Sig  =  HMAC-SHA256(secret, METHOD|path|ts|nonce|sha256(body))      │  ║
║  └───────────────────────────────────────────────────────────────────────┘  ║
╠═════════════════════════════════════════════════════════════════════════════╣
║                  DECENTRALIZED LAYER  (InfoNet Testnet — signed events)     ║
║                                                                             ║
║  ┌────────────────────────────┐    ┌──────────────────────────────────┐     ║
║  │    Mesh Hashchain          │    │   Sovereign Shell Governance     │     ║
║  │                            │    │                                  │     ║
║  │  Ed25519 signed events     │    │  Petitions  (DSL: UPDATE_PARAM,  │     ║
║  │  Public-key binding        │    │              ENABLE_FEATURE …)   │     ║
║  │  Replay / sequence guard   │    │  Upgrade-Hash voting (80% / 40%  │     ║
║  │  Two-tier finality         │    │             quorum / 67% Heavy)  │     ║
║  │   ├ Tier 1 (CRDT, fast)    │    │  Resolution & Dispute markets    │     ║
║  │   └ Tier 2 (epoch finality)│    │  Gate suspend / shutdown / appeal│     ║
║  │  Identity rotation         │    │  Bootstrap eligible-node-1-vote  │     ║
║  │  Constitutional invariants │    │   (Argon2id PoW, Heavy-Node only)│     ║
║  │  (MappingProxyType)        │    │  Function Keys (5 of 6 pieces)   │     ║
║  └─────────────┬──────────────┘    └─────────────┬────────────────────┘     ║
║                │                                 │                          ║
║                └──────────────┬──────────────────┘                          ║
║                               │                                             ║
║  ┌────────────────────────────┴──────────────────────────────────────┐      ║
║  │            Wormhole / InfoNet Relay  (transport layer)            │      ║
║  │   Gate personas │ canonical signing │ Dead Drop epoch mailboxes   │      ║
║  └───────────────────────────────────────────────────────────────────┘      ║
╠═════════════════════════════════════════════════════════════════════════════╣
║              PRIVACY CORE  (Rust crate — locked Protocol contracts)         ║
║                                                                             ║
║   privacy-core/  ─►  Argon2id │ Ed25519/X25519 │ AESGCM │ HKDF              ║
║                      Ring sigs* │ Stealth addrs* │ Pedersen* │ Bulletproofs*║
║                      Blind-sig issuance* (RSA / BBS+ / U-Prove / Idemix)    ║
║                                                                             ║
║   * = locked Protocol contract; cryptographic primitive lands Sprint 11+    ║
╚═════════════════════════════════════════════════════════════════════════════╝

   Distribution
   ────────────
     GitHub (primary):  ghcr.io/bigbodycobain/shadowbroker-{backend,frontend}
     GitLab (mirror):   registry.gitlab.com/bigbodycobain/shadowbroker/{backend,frontend}
     Multi-arch:        linux/amd64  +  linux/arm64  (Raspberry Pi 5 supported)
     Desktop:           Tauri shell  →  packaged backend-runtime  +  Next.js frontend
```

---

## 📊 Data Sources & APIs

| Source | Data | Update Frequency | API Key Required |
|---|---|---|---|
| [OpenSky Network](https://opensky-network.org) | Commercial & private flights | ~60s | **Yes** |
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

The repo includes a `docker-compose.yml` that pulls pre-built images from GitHub Container Registry.

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

No need to clone the repo. Use the pre-built images from GitHub Container Registry. GitLab registry images may be used as a mirror if you publish them there.

Create a `docker-compose.yml` with the following content and deploy it directly — paste it into Portainer's stack editor, `uncloud deploy`, or any Docker host:

```yaml
## Image registry — uncomment ONE line per service:
##   GitHub  (primary): ghcr.io/bigbodycobain/shadowbroker-backend:latest
##   GitLab  (mirror):  registry.gitlab.com/bigbodycobain/shadowbroker/backend:latest


services:
  backend:
    image: ghcr.io/bigbodycobain/shadowbroker-backend:latest
    # image: registry.gitlab.com/bigbodycobain/shadowbroker/backend:latest
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
    # image: registry.gitlab.com/bigbodycobain/shadowbroker/frontend:latest
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

1. Go to the **[Releases](../../releases)** tab on the right side of this repo page.
2. Download the latest `.zip` file from the release.
3. Extract the folder to your computer.
4. **Windows:** Double-click `start.bat`.
   **Mac/Linux:** Open terminal, type `chmod +x start.sh`, `dos2unix start.sh`, and run `./start.sh`.
5. It will automatically install everything and launch the dashboard!

Local launcher notes:

- `start.bat` / `start.sh` run the app without Docker — they install dependencies and start both servers directly.
- If Wormhole identity or DM contact endpoints fail after an upgrade, check the `docs/mesh/` folder for troubleshooting.
- For DM root witness, transparency, and operator monitoring rollout, start with `docs/mesh/wormhole-dm-root-operations-runbook.md`.
- For sample DM root ops bridge assets, also see `scripts/mesh/poll-dm-root-health-alerts.mjs`, `scripts/mesh/export-dm-root-health-prometheus.mjs`, `scripts/mesh/publish-external-root-witness-package.mjs`, `scripts/mesh/smoke-external-root-witness-flow.mjs`, `scripts/mesh/smoke-root-transparency-publication-flow.mjs`, `scripts/mesh/smoke-dm-root-deployment-flow.mjs`, `scripts/mesh/sync-dm-root-external-assurance.mjs`, and `docs/mesh/examples/`.

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
pip install .

# Optional helper scripts (creates venv + installs dev deps)
# Windows PowerShell
# .\backend\scripts\setup-venv.ps1
# macOS/Linux
# ./backend/scripts/setup-venv.sh

# Optional env check (prints warnings for missing keys)
# Windows PowerShell
# .\backend\scripts\check-env.ps1
# macOS/Linux
# ./backend/scripts/check-env.sh

# Create .env with your API keys
echo "AIS_API_KEY=your_aisstream_key" >> .env
echo "OPENSKY_CLIENT_ID=your_opensky_client_id" >> .env
echo "OPENSKY_CLIENT_SECRET=your_opensky_secret" >> .env

# Frontend setup
cd ../frontend
npm ci
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
│   ├── main.py                     # FastAPI app, middleware, API routes (~4,000 lines)
│   ├── cctv.db                     # SQLite CCTV camera database (auto-generated)
│   ├── config/
│   │   └── news_feeds.json         # User-customizable RSS feed list
│   ├── services/
│   │   ├── data_fetcher.py         # Core scheduler — orchestrates all data sources
│   │   ├── ais_stream.py           # AIS WebSocket client (25K+ vessels)
│   │   ├── carrier_tracker.py      # OSINT carrier position estimator (GDELT news scraping)
│   │   ├── cctv_pipeline.py        # 13-source CCTV camera ingestion pipeline
│   │   ├── geopolitics.py          # GDELT + Ukraine frontline + air alerts
│   │   ├── region_dossier.py       # Right-click country/city intelligence
│   │   ├── radio_intercept.py      # Police scanner feeds + OpenMHZ
│   │   ├── kiwisdr_fetcher.py      # KiwiSDR receiver scraper
│   │   ├── sentinel_search.py      # Sentinel-2 STAC imagery search
│   │   ├── shodan_connector.py     # Shodan device search connector
│   │   ├── sigint_bridge.py        # APRS-IS TCP bridge
│   │   ├── network_utils.py        # HTTP client with curl fallback
│   │   ├── api_settings.py         # API key management
│   │   ├── news_feed_config.py     # RSS feed config manager
│   │   ├── fetchers/
│   │   │   ├── flights.py          # OpenSky, adsb.lol, GPS jamming, holding patterns
│   │   │   ├── geo.py              # AIS vessels, carriers, GDELT, fishing activity
│   │   │   ├── satellites.py       # CelesTrak TLE + SGP4 propagation
│   │   │   ├── earth_observation.py # Quakes, fires, volcanoes, air quality, weather
│   │   │   ├── infrastructure.py   # Data centers, power plants, military bases
│   │   │   ├── trains.py           # Amtrak + DigiTraffic European rail
│   │   │   ├── sigint.py           # SatNOGS, TinyGS, APRS, Meshtastic
│   │   │   ├── meshtastic_map.py   # Meshtastic MQTT + map node aggregation
│   │   │   ├── military.py         # Military aircraft classification
│   │   │   ├── news.py             # RSS intelligence feed aggregation
│   │   │   ├── financial.py        # Global markets data
│   │   │   └── ukraine_alerts.py   # Ukraine air raid alerts
│   │   └── mesh/                   # InfoNet / Wormhole protocol stack
│   │       ├── mesh_protocol.py    # Core mesh protocol + routing
│   │       ├── mesh_crypto.py      # Ed25519, X25519, AESGCM primitives
│   │       ├── mesh_hashchain.py   # Hash chain commitment system (~1,400 lines)
│   │       ├── mesh_router.py      # Multi-transport router (APRS, Meshtastic, WS)
│   │       ├── mesh_wormhole_persona.py  # Gate persona identity management
│   │       ├── mesh_wormhole_dead_drop.py # Dead Drop token-based DM mailbox
│   │       ├── mesh_wormhole_ratchet.py   # Double-ratchet DM scaffolding
│   │       ├── mesh_wormhole_gate_keys.py # Gate key management + rotation
│   │       ├── mesh_wormhole_seal.py      # Message sealing + unsealing
│   │       ├── mesh_merkle.py      # Merkle tree proofs for data commitment
│   │       ├── mesh_reputation.py  # Node reputation scoring
│   │       ├── mesh_oracle.py      # Oracle consensus protocol
│   │       └── mesh_secure_storage.py # Secure credential storage
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   └── page.tsx            # Main dashboard — state, polling, layout
│   │   └── components/
│   │       ├── MaplibreViewer.tsx   # Core map — all GeoJSON layers
│   │       ├── MeshChat.tsx        # InfoNet / Mesh / Dead Drop chat panel
│   │       ├── MeshTerminal.tsx    # Draggable CLI terminal
│   │       ├── NewsFeed.tsx        # SIGINT feed + entity detail panels
│   │       ├── WorldviewLeftPanel.tsx   # Data layer toggles (35+ layers)
│   │       ├── WorldviewRightPanel.tsx  # Search + filter sidebar
│   │       ├── AdvancedFilterModal.tsx  # Airport/country/owner filtering
│   │       ├── MapLegend.tsx       # Dynamic legend with all icons
│   │       ├── MarketsPanel.tsx    # Global financial markets ticker
│   │       ├── RadioInterceptPanel.tsx # Scanner-style radio panel
│   │       ├── FindLocateBar.tsx   # Search/locate bar
│   │       ├── ChangelogModal.tsx  # Version changelog popup (auto-shows on upgrade)
│   │       ├── SettingsPanel.tsx   # API Keys + News Feed + Shodan config
│   │       ├── ScaleBar.tsx        # Map scale indicator
│   │       └── ErrorBoundary.tsx   # Crash recovery wrapper
│   └── package.json
```

---

## 🔑 Environment Variables

### Backend (`backend/.env`)

```env
# Required for airplane telemetry (NEW in v0.9.7 — startup env check flags these as critical)
# Free registration: https://opensky-network.org/index.php?option=com_users&view=registration
OPENSKY_CLIENT_ID=your_opensky_client_id      # OAuth2 — global flight state vectors
OPENSKY_CLIENT_SECRET=your_opensky_secret     # OAuth2 — paired with Client ID above

# Optional (enhances data quality)
AIS_API_KEY=your_aisstream_key                # Maritime vessel tracking (aisstream.io) — ships layer empty without it
LTA_ACCOUNT_KEY=your_lta_key                  # Singapore CCTV cameras
SHODAN_API_KEY=your_shodan_key                # Shodan device search overlay
SH_CLIENT_ID=your_sentinel_hub_id             # Copernicus CDSE Sentinel Hub imagery
SH_CLIENT_SECRET=your_sentinel_hub_secret     # Paired with Sentinel Hub Client ID
MESH_SAR_EARTHDATA_USER=                      # NASA Earthdata user (SAR Mode B — OPERA products)
MESH_SAR_EARTHDATA_TOKEN=                     # NASA Earthdata token (paired with user above)
MESH_SAR_COPERNICUS_USER=                     # Copernicus Data Space user (SAR Mode B — EGMS / EMS)
MESH_SAR_COPERNICUS_TOKEN=                    # Copernicus token (paired with user above)
OPENCLAW_ACCESS_TIER=restricted               # OpenClaw agent tier: "restricted" (read-only) or "full"

# Private-lane privacy-core pinning (required when Arti or RNS is enabled)
PRIVACY_CORE_MIN_VERSION=0.1.0
PRIVACY_CORE_ALLOWED_SHA256=your_privacy_core_sha256
# Optional override if you load a non-default shared library path
PRIVACY_CORE_LIB=
```

When `MESH_ARTI_ENABLED=true` or `MESH_RNS_ENABLED=true`, backend startup now fails closed unless the loaded `privacy-core` artifact reports a parseable version at or above `PRIVACY_CORE_MIN_VERSION` and matches one of the hashes in `PRIVACY_CORE_ALLOWED_SHA256`.

Generate the hash from the artifact you intend to ship:

```powershell
Get-FileHash .\privacy-core\target\release\privacy_core.dll -Algorithm SHA256
```

```bash
sha256sum ./privacy-core/target/release/libprivacy_core.so
```

Then confirm authenticated `GET /api/wormhole/status` or `GET /api/settings/wormhole-status` shows the same `privacy_core.version`, `privacy_core.library_path`, and `privacy_core.library_sha256`.

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
| [@Alienmajik](https://github.com/Alienmajik) | Raspberry Pi 5 support — ARM64 packaging, headless deployment notes, runtime tuning for Pi-class hardware | — |
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
