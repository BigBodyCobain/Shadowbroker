from pydantic import BaseModel
from typing import Optional, Dict, List, Any, Literal


class HealthResponse(BaseModel):
    status: str
    version: str = ""
    last_updated: Optional[str] = None
    sources: Dict[str, int]
    freshness: Dict[str, str]
    uptime_seconds: int


class RefreshResponse(BaseModel):
    status: str


class AisFeedResponse(BaseModel):
    status: str
    ingested: int = 0


class RouteResponse(BaseModel):
    orig_loc: Optional[list] = None
    dest_loc: Optional[list] = None
    origin_name: Optional[str] = None
    dest_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Data Center — canonical record schema (all pipeline layers)
# Fields are nullable when not yet populated by a pipeline stage.
# Pipeline stages write to datacenters_geocoded.json; the fetcher passes
# every field through unchanged.
# ---------------------------------------------------------------------------

class DataCenterRecord(BaseModel):
    # ── Identity ──────────────────────────────────────────────────────────
    name: str
    company: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    zip: str = ""
    lat: float
    lng: float

    # ── Layer 1: Physical asset ───────────────────────────────────────────
    # Populated by: scripts/enrich_l1_physical.py (OSM + bgeesaman dataset)
    operator_type: Optional[Literal["hyperscaler", "colocation", "enterprise"]] = None
    tier_rating: Optional[Literal[1, 2, 3, 4]] = None  # Uptime Institute Tier I–IV
    mw_capacity: Optional[float] = None                 # IT load in MW
    year_built: Optional[int] = None
    cooling_type: Optional[Literal["air", "liquid", "hybrid"]] = None
    floor_level: Optional[Literal["above", "basement", "mixed"]] = None

    # ── Layer 2: Hazard exposure (point-extracted, facility-level) ────────
    # Populated by: scripts/enrich_l2_hazard.py
    jrc_flood_100yr_m: Optional[float] = None      # JRC flood depth at 100yr RP (metres)
    usgs_pga_10pct_50yr: Optional[float] = None    # USGS PGA g-value (2%/10% in 50yr)
    ibtracs_track_density: Optional[float] = None  # Tropical cyclone tracks/decade within 200 km
    wildfire_days_50km: Optional[float] = None     # NASA FIRMS: active fire days/yr within 50 km
    heat_extreme_days: Optional[float] = None      # ERA5: days/yr above 35°C WBGT
    # Normalised 0–100 hazard scores (legacy INFORM + updated from raw values)
    hazard_eq: int = 0
    hazard_flood: int = 0
    hazard_cyclone: int = 0
    hazard_fire: int = 0

    # ── Layer 2 (legacy): power proximity ────────────────────────────────
    nearest_plant_km: Optional[float] = None
    nearest_plant_fuel: str = ""
    grid_score: int = 0
    dc_density_50km: int = 0
    concentration_score: int = 0
    nat_cat_score: int = 0

    # ── Layer 3: Dependency graph ─────────────────────────────────────────
    # Populated by: scripts/enrich_l3_dependencies.py (OSM power + PeeringDB)
    substation_osm_id: Optional[str] = None        # Nearest HV substation OSM node ID
    substation_dist_km: Optional[float] = None
    substation_cluster_id: Optional[str] = None    # Shared-substation cluster key
    substation_shared_count: Optional[int] = None  # Facilities on the same substation
    ixp_ids: Optional[List[str]] = None            # PeeringDB IXP IDs within 100 km
    nearest_ixp_km: Optional[float] = None
    ixp_count_50km: Optional[int] = None
    fibre_path_count: Optional[int] = None         # Independent physical fibre paths
    water_stress_idx: Optional[float] = None       # FAO AQUASTAT 0–5
    asn: Optional[str] = None                      # Primary BGP ASN

    # ── Layer 4: Network topology ─────────────────────────────────────────
    # Populated by: scripts/enrich_l4_topology.py (graph analysis)
    betweenness_centrality: Optional[float] = None  # 0–1 normalised
    systemic_importance_score: Optional[float] = None  # 0–100 composite
    accumulation_flag: Optional[bool] = None        # True if cluster size ≥ 3

    # ── Layer 5: Composite risk index ────────────────────────────────────
    risk_score: float = 0.0
