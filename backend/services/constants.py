# ─── ShadowBroker Backend Constants ──────────────────────────────────────────
# Centralized magic numbers. Import from here instead of hardcoding.

# ─── Flight Trails ──────────────────────────────────────────────────────────
FLIGHT_TRAIL_MAX_TRACKED = 2000  # Max concurrent tracked trails before LRU eviction
FLIGHT_TRAIL_POINTS_PER_FLIGHT = 200  # Max trail points kept per aircraft
TRACKED_TRAIL_TTL_S = 1800  # 30 min - trail TTL for tracked flights
DEFAULT_TRAIL_TTL_S = 300  # 5 min - trail TTL for non-tracked flights

# ─── Detection Thresholds ──────────────────────────────────────────────────
HOLD_PATTERN_DEGREES = 300  # Total heading change to flag holding pattern
GPS_JAMMING_NACP_THRESHOLD = 8  # NACp below this = degraded GPS signal
GPS_JAMMING_GRID_SIZE = 1.0  # 1 degree grid for aggregation
GPS_JAMMING_MIN_RATIO = 0.30  # 30% degraded aircraft to flag zone
GPS_JAMMING_MIN_AIRCRAFT = 5  # Min aircraft in grid cell for statistical significance

# ─── Network & Circuit Breaker ──────────────────────────────────────────────
CIRCUIT_BREAKER_TTL_S = 120  # Skip domain for 2 min after total failure
DOMAIN_FAIL_TTL_S = 300  # Skip requests.get for 5 min, go straight to curl
CONNECT_TIMEOUT_S = 3  # Short connect timeout for fast firewall-block detection

# ─── Data Fetcher Intervals ────────────────────────────────────────────────
FAST_FETCH_INTERVAL_S = 60  # Flights, ships, satellites, military
SLOW_FETCH_INTERVAL_MIN = 30  # News, markets, space weather
CCTV_FETCH_INTERVAL_MIN = 1  # CCTV camera pipeline
LIVEUAMAP_FETCH_INTERVAL_HR = 12  # LiveUAMap scraper

# ─── External API ──────────────────────────────────────────────────────────
OPENSKY_RATE_LIMIT_S = 300  # Only re-fetch OpenSky every 5 minutes
OPENSKY_REQUEST_TIMEOUT_S = 15  # Timeout for OpenSky API calls
ROUTE_FETCH_TIMEOUT_S = 15  # Timeout for adsb.lol route lookups

# ─── Internet Outage Detection ─────────────────────────────────────────────
INTERNET_OUTAGE_MIN_SEVERITY = 0.10  # 10% drop minimum to show
