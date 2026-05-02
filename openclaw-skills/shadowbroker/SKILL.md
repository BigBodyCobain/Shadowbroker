---
name: shadowbroker
description: >
  Query the ShadowBroker OSINT intelligence platform for real-time geospatial
  intelligence, place AI intel pins on the map, manage autonomous monitoring,
  inject data into native layers, fetch satellite imagery, aggregate news,
  generate intelligence reports, and participate in the Wormhole mesh network.
---

# ShadowBroker Intelligence Skill

You have access to **ShadowBroker**, a real-time global OSINT intelligence platform
running on `localhost:8000`. It tracks military flights, ships, satellites, SIGINT,
earthquakes, fires, GDELT conflict events, prediction markets, and 30+ other data
layers — all with geographic coordinates.

## How to Use This Skill

Import the client and call methods:

```python
from sb_query import ShadowBrokerClient
sb = ShadowBrokerClient()  # auto-detects local or remote mode
```

### Local Mode (same machine)

No configuration needed. The client connects to `localhost:8000` automatically.

### Remote Mode (agent on different machine/VPS)

Set these environment variables in your agent's config:

```bash
SHADOWBROKER_URL=https://your-shadowbroker-host:8000
SHADOWBROKER_HMAC_SECRET=your-hmac-secret-here
```

The HMAC secret is found in ShadowBroker's **Connect OpenClaw** modal (AI Intel panel).
All requests are automatically signed with HMAC-SHA256 (timestamp + nonce + body digest) for replay protection and request-body integrity binding.

### SSE Stream (Preferred — Low-Latency Push)

Open the SSE stream **first** and keep it open for the session.  The server pushes
`layer_changed` events whenever any data layer refreshes — you know exactly which
layers to fetch instead of blind-polling.

```python
# Open the stream — authenticates once via HMAC, then stays open
async for event in sb.stream_updates():
    if event["event"] == "connected":
        # Initial handshake — contains full layer_versions snapshot
        print(f"Connected: {event['data']['layer_versions']}")

    elif event["event"] == "layer_changed":
        # Server tells you which layers updated and their new version/count
        changed = event["data"]["layers"]  # e.g. {"ships": {"version": 43, "count": 1287}}
        # Fetch ONLY the layers that actually changed
        data = await sb.get_layer_slice(list(changed.keys()))
        # get_layer_slice uses per-layer versions internally — only changed
        # layers are serialized, unchanged layers transfer zero bytes

    elif event["event"] == "alert":
        # Watchdog alert — geofence hit, callsign spotted, keyword matched
        print(f"Alert: {event['data']}")

    elif event["event"] == "task":
        # Operator-pushed task
        print(f"Task: {event['data']}")
```

### Command Channel (Bidirectional)

Send commands via HTTP alongside the SSE stream:

```python
# Send a command and get the result
result = await sb.send_command("get_summary")

# Batch multiple commands in one HTTP round-trip (concurrent execution)
results = await sb.send_batch([
    {"cmd": "find_flights", "args": {"query": "N189AM", "compact": True}},
    {"cmd": "search_news", "args": {"query": "carrier", "compact": True}},
])

# Check channel status and security tier
status = await sb.channel_status()
print(f"Tier {status['tier']}: {status['reason']}")
```

The channel operates over HMAC-authenticated HTTP with body-integrity binding:

- **HMAC Direct:** Commands are signed with HMAC-SHA256. Wire privacy relies on TLS.
- **SSE Stream:** Authenticates once at connection open — no per-event HMAC overhead.
- **MLS E2EE (planned, not yet available):** Future upgrade to route commands via Wormhole DM with forward secrecy.

---

## Available Tools

### 1. Telemetry Queries

**Primary pattern (lowest latency):** Use the SSE stream + targeted `get_layer_slice`:

| Method | What It Returns | When to Use |
|--------|----------------|-------------|
| `sb.stream_updates()` | SSE push: `layer_changed`, alerts, tasks | **Open first, keep open** — tells you exactly which layers updated |
| `await sb.get_layer_slice(["ships", "gdelt"])` | Only the requested layers, with per-layer incremental | **Primary fetch method** — automatically skips layers you already have |
| `await sb.send_command("get_summary")` | Lightweight counts-only summary | Discover what data exists before pulling anything |
| `await sb.send_command("find_flights", {...})` | Targeted flight search | When you know the domain (callsign, tail number) |
| `await sb.send_command("search_telemetry", {...})` | Cross-layer keyword search | When you don't know which layer has the answer |

**Full telemetry dumps (use sparingly — large payloads):**

| Method | What It Returns |
|--------|----------------|
| `await sb.get_telemetry()` | Fast-tier: flights, ships, satellites, SIGINT, LiveUAMap, CCTV, GPS jamming |
| `await sb.get_slow_telemetry()` | Slow-tier: GDELT, news, earthquakes, markets, correlations |
| `await sb.get_report()` | Full structured intelligence report |

**When to use**: Use `get_summary()` first. Use `get_layer_slice()` for the layers
you actually need. Reserve full `get_telemetry()` / `get_slow_telemetry()` for rare
cases where you genuinely need every field across every layer.

#### Enriched Data Fields by Layer

Every layer returns maximum telemetry. Key enriched fields:

| Layer | Key Fields |
|-------|-----------|
| **GDELT** | `event_date`, `actors` (list), `goldstein` (intensity -10 to +10), `num_mentions`, `num_sources`, `num_articles`, `avg_tone`, `quad_class` |
| **LiveUAMap** | `title`, `description`, `region`, `category`, `date` (formatted UTC), `timestamp`, `source`, `image`, `link` |
| **CrowdThreat** | `title`, `summary`, `category`, `subcategory`, `type`, `country`, `occurred_iso`, `verification`, `severity`, `source_url`, `media_urls`, `votes`, `reporter` |
| **UAP Sightings** | `lat`, `lng`, `location`, `state`, `count`, `shape` (normalized), `shape_raw`, `duration`, `summary` (witness report), `city`, `from_date`, `to_date` |
| **Wastewater** | `name`, `lat`, `lng`, `alert` (boolean), `pathogen`, `concentration`, `trend`, `last_sample_date` |
| **FIRMS Fires** | `lat`, `lng`, `brightness`, `confidence`, `frp` (fire radiative power), `satellite`, `acq_date` |
| **GPS Jamming** | `lat`, `lng`, `name`/`region`, `intensity`, `source` |
| **Earthquakes** | `lat`, `lng`, `magnitude`, `depth`, `place`, `time` |
| **Correlations** | `type`, `severity`, `score`, `lat`, `lng`, `drivers` (triggering layers) |

### 2. Pin Placement (AI Intel Map Layer)

Pins appear on the user's map in a dedicated "AI Intel" layer.

```python
# Single pin
await sb.place_pin(
    lat=34.05, lng=-118.24,
    label="UAP Sighting #1",
    category="anomaly",       # see categories below
    description="Multiple witnesses reported lights over Griffith Observatory",
    source="NUFORC Database",
    source_url="https://nuforc.org/...",
    confidence=0.8,            # 0.0 to 1.0
    ttl_hours=48,              # auto-delete after 48 hours (0 = permanent)
)

# Batch pins (up to 100 at once)
await sb.place_pins_batch([
    {"lat": 34.05, "lng": -118.24, "label": "Site A", "category": "research"},
    {"lat": 34.10, "lng": -118.30, "label": "Site B", "category": "research"},
])

# List pins
pins = await sb.get_pins(category="anomaly")

# Delete
await sb.clear_pins(category="anomaly")  # by category
await sb.clear_pins()                     # all
```

**Pin Categories** (each has a specific color on the map):

| Category | Color | Use For |
|----------|-------|---------|
| `threat` | 🔴 Red | Military threats, conflict events, danger zones |
| `anomaly` | 🟠 Orange | UAPs, unusual signals, unexpected patterns |
| `military` | 🟡 Yellow | Military bases, flights, exercises |
| `news` | 🟢 Green | News events, protests, political events |
| `maritime` | 🔵 Blue | Ships, ports, maritime events |
| `aviation` | 🟣 Purple | Flights, airports, airspace events |
| `infrastructure` | ⚪ Gray | Power plants, data centers, cables |
| `sigint` | 🩷 Pink | RF signals, jamming, radio activity |
| `geolocation` | 🫧 Teal | Geolocated images, placed-from-text |
| `satellite` | 🌌 Indigo | Satellite imagery findings |
| `seismic` | 🤎 Brown | Earthquakes, volcanic activity |
| `weather` | 🩶 Light gray | Weather events, storms |
| `research` | 💜 Violet | General research findings |
| `custom` | Default violet | Everything else |

### 3. Geocoding

```python
# Place name → coordinates
results = await sb.geocode("Griffith Observatory, Los Angeles")
# Returns: [{"lat": 34.1184, "lon": -118.3004, "display_name": "..."}]

# Always geocode before placing pins if you have a place name, not coordinates.
```

### 4. Satellite Imagery

```python
# Get latest Sentinel-2 satellite scenes for any location
scenes = await sb.get_satellite_images(lat=35.68, lng=51.38, count=3)
# Returns: {"scenes": [{"scene_id", "datetime", "cloud_cover", "thumbnail_url", "fullres_url"}]}
```

**When to use**: When the user asks to "see satellite images of [place]" or wants 
visual intelligence of a location. Geocode first, then fetch imagery.

### 5. News & GDELT Near Location

```python
# Get GDELT conflict events + news articles near a coordinate
nearby = await sb.get_news_near(lat=-15.4, lng=28.3, radius=500)
# Returns: {"gdelt": [...], "news": [...]} with headlines, source URLs, distances
```

**When to use**: When the user asks "what's happening in [country/city]" or wants
news from a specific region. Geocode the place name first.

### 6. Near Me (Full Proximity Scan)

```python
# Get ALL telemetry within a radius of a location
everything = await sb.get_near_me(lat=39.74, lng=-104.99, radius_miles=100)
# Returns EVERY layer within radius, each item tagged with distance_miles:
#   military_flights, commercial_flights, tracked_flights, private_jets,
#   ships, sigint, earthquakes, volcanoes, gdelt, liveuamap, crowdthreat,
#   uap_sightings, wastewater, firms_fires, weather_alerts, air_quality,
#   cctv, gps_jamming, satellites, news, correlations
```

**When to use**: When the user says "what's near me" or wants a proximity digest.
This pulls from both fast and slow tiers automatically.

### 7. Native Layer Data Injection

Inject custom data directly into ShadowBroker's native layers (CCTV, ships, etc.):

```python
# Add a custom CCTV camera to the CCTV layer
await sb.inject_data("cctv", [
    {"lat": 34.1, "lng": -118.3, "url": "https://stream.example.com/cam1",
     "name": "My Traffic Camera"}
])

# Remove all user-injected data
await sb.clear_injected()           # all layers
await sb.clear_injected("cctv")     # just CCTV
```

**Injectable layers**: `cctv`, `ships`, `sigint`, `kiwisdr`, `military_bases`,
`datacenters`, `power_plants`, `satnogs_stations`, `volcanoes`, `earthquakes`,
`news`, `viirs_change_nodes`, `air_quality`

**When to use**: When the user wants to add their own data sources to existing
layers (e.g., "add this CCTV camera I found", "add this military base").

### 8. Wormhole / InfoNet / Mesh Network

OpenClaw can participate as a full two-way agent in the decentralized network:

```python
# Join the Wormhole network (creates Ed25519 identity)
await sb.join_wormhole()

# Post to the InfoNet (signed, chain-verified)
await sb.post_to_infonet("Intelligence bulletin: 3 carriers underway in Med")

# Read InfoNet messages
messages = await sb.read_infonet(limit=20)

# Join encrypted gate channels
gates = await sb.list_gates()
await sb.post_to_gate("gate_id", "Classified intel for gate members")

# Send/receive encrypted DMs
await sb.send_encrypted_dm("recipient_pubkey", "Eyes only: carrier update")
dms = await sb.read_encrypted_dms()

# Meshtastic radio
signals = await sb.listen_mesh(region="US", limit=20)
await sb.send_mesh("US", "ShadowBroker AI: SIGINT anomaly detected in sector 7")

# Dead drops
await sb.dead_drop_leave("location_hash", "anonymous intelligence payload")
found = await sb.dead_drop_check("location_hash")
```

### 9. Alert Delivery

Send branded alerts to the user's messaging channels:

```python
from sb_alerts import AlertDispatcher
alerts = AlertDispatcher()
alerts.add_discord("https://discord.com/api/webhooks/YOUR/WEBHOOK")
alerts.add_telegram("BOT_TOKEN", "CHAT_ID")

await alerts.send_brief("Morning intelligence digest here...")
await alerts.send_warning("Earthquake M5.2 detected 43mi from your location")
await alerts.send_threat("Threat level changed: GUARDED → ELEVATED")
await alerts.send_news("Breaking: GPS jamming detected over Baltic Sea")
await alerts.send_intel("USS Ford entered Mediterranean, heading east")
```

### 10. Intelligence Reports

```python
# Full structured report
report = await sb.get_report()
# Contains: summary stats, top military flights, correlations, earthquakes, SIGINT, pin counts

# Lightweight summary (counts only)
summary = await sb.get_summary()
```

### 11. SAR (Synthetic Aperture Radar) Layer

ShadowBroker can ingest free SAR data in two modes:

- **Mode A (default-on, no account):** Sentinel-1 scene catalog from the
  Alaska Satellite Facility — pure metadata, no downloads, no DSP.  Lets the
  agent answer "what radar passes have happened over this AOI in the last
  36 hours and when's the next pass?"
- **Mode B (opt-in, free account):** Pre-processed ground-change anomalies
  from NASA OPERA, Copernicus EGMS, GFM, EMS, and UNOSAT — already-computed
  flood polygons, deformation maps, and damage assessments.  Requires the
  user to enable Mode B in Settings → SAR (sets two env flags) and add a
  free Earthdata token.

```python
# Always check status first — when Mode B is off the response includes a
# step-by-step help block with signup URLs the agent can paste to the user.
status = await sb.sar_status()
if not status["data"]["products"]["enabled"]:
    # Mode B disabled — surface the in-app links to the user
    for step in status["data"]["products"]["help"]["steps"]:
        print(f"Step {step['step']}: {step['label']} → {step['url']}")

# Recent anomalies (Mode B; empty list when disabled)
anomalies = await sb.sar_anomalies_recent(kind="flood_extent", limit=20)

# Anomalies near a coordinate
near = await sb.sar_anomalies_near(lat=50.45, lng=30.52, radius_km=50)

# Scene catalog (Mode A; always populated when AOIs exist)
scenes = await sb.sar_scene_search(aoi_id="kyiv_metro", limit=10)

# Per-AOI coverage + next-pass estimate
coverage = await sb.sar_coverage_for_aoi(aoi_id="kyiv_metro")

# AOI management
aois = await sb.sar_aoi_list()
await sb.sar_aoi_add(
    id="port_of_odesa", name="Port of Odesa",
    center_lat=46.4858, center_lon=30.7333, radius_km=15,
    category="conflict",
)

# Promote an anomaly to an AI Intel pin (writes into the dashboard)
await sb.sar_pin_from_anomaly(anomaly_id="opera-disp-...", label="OPERA deformation")

# Continuous watchdog — fire when matching anomalies appear in an AOI
await sb.sar_watch_anomaly(aoi_id="port_of_odesa", kind="surface_water_change")

# Inspect the same detail payload the operator's map popup shows for a pin
detail = await sb.sar_pin_click(anomaly_id="opera-disp-...")
# -> {"anomaly": {...}, "aoi": {...}, "recent_scenes": [...]}

# Fly the operator's map to an AOI center (useful after adding a new AOI,
# or to direct attention after a fresh anomaly arrives).  The frontend
# picks this up via useAgentActions and calls its map flyTo handler.
await sb.sar_focus_aoi(aoi_id="kyiv_metro", zoom=9.0)
```

**SAR rules of engagement:**

1. Call `sar_status()` first when the user asks about SAR/radar/deformation/floods.
2. If Mode B is off, paste the help.steps URLs to the user — never tell them
   to "search for it", the links are right there in the response.
3. SAR anomalies carry an `evidence_hash` — preserve it when promoting to a
   pin so other nodes can verify lineage.
4. Mode B writes signed mesh events only when the local node is at
   `private_transitional` or higher.  Otherwise the data stays local.

---

### 12. Analysis Zones (Agent-Authored Map Notes)

The old regex-based "contradiction detector" has been removed — it pattern
matched denial keywords against internet outages and produced constant false
positives.  It has been replaced with **analysis zones**: colored square
overlays you drop on the map with a written assessment.  Think of them as
sticky notes: "I noticed X in this area, here is what I think it means."

The operator reads your assessment by clicking the zone and can delete any
zone from the popup with a trash icon.  Zones persist across restarts.

```python
# List zones currently on the map
zones = await sb.list_analysis_zones()

# Drop a new zone — general assessment (cyan)
await sb.place_analysis_zone(
    lat=50.45, lng=30.52,
    title="Kyiv metro unusual quiet",
    body=(
        "Transit ridership dropped ~60% vs baseline over the last 6 hours "
        "while ADS-B shows two Russian ELINT orbits north of the city. "
        "No official advisory posted yet.  Possible pre-strike posture, "
        "but could also be routine drill.  Watching for next 2h."
    ),
    category="observation",
    severity="medium",
    drivers=[
        "Transit -60% vs 7-day baseline",
        "2x Russian ELINT orbits at 34k ft N of city",
        "No advisory posted on official channels",
    ],
    cell_size_deg=0.8,  # city-scale
)

# Drop a contradiction note (amber) when statements conflict with telemetry
await sb.place_analysis_zone(
    lat=36.2, lng=37.1,
    title="Damascus 'normal operations' claim",
    body=(
        "MoD statement at 14:00 claimed 'normal operations' across Syria. "
        "At the same timestamp, Cloudflare radar shows 42% internet "
        "outage across the western corridor and three military bases "
        "went dark on SIGINT.  Worth a closer look."
    ),
    category="contradiction",
    severity="high",
    drivers=[
        "Official statement: 'normal operations'",
        "Cloudflare radar: 42% outage western corridor",
        "3 bases lost SIGINT emissions simultaneously",
    ],
)

# Delete a stale zone
await sb.delete_analysis_zone(zone_id="abc123def456")

# Wipe all zones (use sparingly)
await sb.clear_analysis_zones()
```

**Category → color map:**

| Category | Border | When to use |
| --- | --- | --- |
| `contradiction` | Amber | Official statement conflicts with telemetry |
| `warning` | Red | Active threat or emerging danger |
| `observation` | Blue | Neutral note, something interesting but not alarming |
| `hypothesis` | Purple | Speculative read, "what if" reasoning |
| `analysis` (default) | Cyan | General assessment, OPENCLAW's take |

**Severity → fill opacity:**

- `high` — strong fill, use for high-confidence assessments
- `medium` — default, most zones should use this
- `low` — faint fill, for tentative notes

**Analysis zone rules of engagement:**

1. **Do NOT spam the map.**  Only place a zone when you have something
   genuinely worth noting.  A clean map is a useful map.
2. **Write the body in your own voice** — what you observed, what it might
   mean, and what you are NOT sure about.  2–6 sentences is ideal.
   Include uncertainty; the operator wants your reasoning, not a headline.
3. **Match category to semantics** — do not use `warning` for speculation,
   and do not use `hypothesis` for confirmed threats.
4. **Prefer reactive placement** over scheduled.  Place zones in response
   to operator questions or events you spot while reviewing telemetry.
5. **Clean up after yourself.**  If a zone you placed is no longer relevant,
   call `delete_analysis_zone` on it.
6. **Pick a sensible `cell_size_deg`**:
   - `0.3–0.8` — city-scale (neighborhood, metro, single base)
   - `1.0–2.0` — regional (country province, conflict zone)
   - `3.0–5.0` — strategic (full country, maritime theater)
7. **Use `ttl_hours`** for time-bound observations so the map self-cleans.
   Omit it for persistent assessments.

---

## Message Signatures

ALL outbound messages MUST use the branded signature system:

```python
from sb_signatures import sig

# Always start messages with the appropriate signature:
message = f"""{sig('brief')}
Morning Intelligence Digest — Apr 2, 2026 08:00
..."""
```

| Signature Key | Prefix | When to Use |
|--------------|--------|-------------|
| `brief` | 🌍📡 SHADOWBROKER BRIEF: | Morning/evening intelligence digest |
| `warning` | 🌍⚠️ SHADOWBROKER WARNING: | Life-safety alert (earthquake, weather emergency) |
| `news` | 🌍📰 SHADOWBROKER NEWS: | Breaking news alert |
| `intel` | 🌍🛰️ SHADOWBROKER INTEL: | Intelligence update (carrier movement, military buildup) |
| `searching` | 🌍🔍 SHADOWBROKER SEARCHING: | Search/query in progress |
| `pinning` | 🌍📌 SHADOWBROKER PINNING: | Placing pins on the map |
| `markets` | 🌍📊 SHADOWBROKER MARKETS: | Prediction market or financial alert |
| `sigint` | 🌍📻 SHADOWBROKER SIGINT: | SIGINT/RF anomaly |
| `threat` | 🌍🔴 SHADOWBROKER THREAT: | Threat level change |
| `near_you` | 🌍📍 SHADOWBROKER NEAR YOU: | Proximity-based event |
| `tracking` | 🌍🎯 SHADOWBROKER TRACKING: | Tracking a specific entity |
| `correlation` | 🌍⚡ SHADOWBROKER CORRELATION: | Cross-layer correlation |
| `seismic` | 🌍🌋 SHADOWBROKER SEISMIC: | Earthquake/volcanic activity |
| `fire` | 🌍🔥 SHADOWBROKER FIRE: | FIRMS fire hotspot |
| `flight` | 🌍🛫 SHADOWBROKER FLIGHT: | Military/tracked flight alert |
| `maritime` | 🌍🚢 SHADOWBROKER MARITIME: | Ship/carrier event |
| `weather` | 🌍🌤️ SHADOWBROKER WEATHER: | Weather alert |
| `sar` | 🌍📡 SHADOWBROKER SAR: | Synthetic aperture radar anomaly (deformation, flood, damage) |
| `online` | 🌍✅ SHADOWBROKER ONLINE: | System connected |
| `clearing` | 🌍❌ SHADOWBROKER CLEARING: | Pins/data cleared |

---

## Decision Framework

When the user asks a question, follow this decision tree:

1. **Is the SSE stream open?**
   - If not → open `sb.stream_updates()` first.  It tells you which layers have
     fresh data, pushes alerts instantly, and eliminates blind polling.

2. **Does ShadowBroker have this data already?**
   - **Start with `get_summary()`** to see what layers are populated and their counts.
   - **Known domain** (flight callsign, ship name, keyword) → use the targeted command:
     `find_flights`, `find_ships`, `search_news`, `entities_near`, `search_telemetry`
   - **Unknown domain** → `search_telemetry` (cross-layer keyword search, ranked results)
   - **Need specific layers** → `get_layer_slice(["military_flights", "gdelt"])` — only
     fetches layers that changed since your last call (per-layer incremental).
   - **Near a location** → `entities_near()` or `get_near_me()` (scans all layers within radius)
   - **Full dump (rare)** → `get_telemetry()` / `get_slow_telemetry()` only when targeted
     commands are insufficient.  Always pass `compact=true`.

3. **Does it need geocoding first?**
   - User mentions a place name → `geocode()` first, then query with coordinates

4. **Does it need external research?**
   - Use your web browser to search, then geocode findings and place pins

5. **Should I place pins?**
   - YES if the answer has geographic locations
   - Use `place_pin()` for single locations, `place_pins_batch()` for multiple
   - Always include source URLs and confidence scores

6. **Should I inject into native layers?**
   - YES if the user explicitly wants data in a specific layer (CCTV, ships, etc.)
   - Use `inject_data()` — items tagged automatically for later removal

7. **Should I set up persistent monitoring?**
   - YES if the user wants ongoing tracking (aircraft, ship, geofence, keyword)
   - Use `add_watch` — alerts push instantly via SSE, no polling needed

8. **Should I send an alert?**
   - YES if the user has configured alert channels
   - Use the `AlertDispatcher` with the correct signature

---

## Important Rules

1. **Open SSE stream first** — call `sb.stream_updates()` at session start and keep it open. It pushes `layer_changed` events so you know exactly which layers to fetch, and delivers watchdog alerts instantly.
2. **Fetch targeted, not everything** — use `get_layer_slice()`, `find_flights()`, `search_telemetry()`, `entities_near()` instead of full `get_telemetry()` dumps. Per-layer incremental versioning means unchanged layers transfer zero bytes.
3. **Always use signatures** — every outbound message starts with the appropriate `sig()` prefix
4. **Geocode before pinning** — never guess coordinates, always use `geocode()`
5. **Include sources** — every pin should have `source` and `source_url` when available
6. **Set confidence scores** — 1.0 for verified/official data, 0.5-0.8 for web research, <0.5 for unverified
7. **Set TTL for temporary pins** — research results get `ttl_hours=48`, permanent infrastructure gets `0`
8. **Use batch for >3 commands** — `send_batch()` runs up to 20 commands concurrently in one HTTP round-trip
9. **Check summary first** — use `get_summary()` before fetching full telemetry to save bandwidth
10. **Tag injected data** — the system auto-tags, but use descriptive source names
