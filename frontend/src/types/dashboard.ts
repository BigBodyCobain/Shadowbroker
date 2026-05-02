// ─── ShadowBroker Dashboard Data Types ─────────────────────────────────────
// Canonical type definitions for all data flowing from backend → frontend.
// Every `any` in the codebase should eventually be replaced with these types.

// ─── FLIGHTS ────────────────────────────────────────────────────────────────

export interface FlightBase {
  callsign: string;
  country: string;
  lat: number;
  lng: number;
  alt: number;
  heading: number;
  true_track?: number;
  speed_knots: number | null;
  registration: string;
  model: string;
  icao24: string;
  squawk?: string;
  aircraft_category?: string;
  nac_p?: number;
  _seen_at?: number;
  origin_loc?: [number, number] | null;
  dest_loc?: [number, number] | null;
  origin_name?: string;
  dest_name?: string;
  trail?: Array<{ lat: number; lng: number; alt?: number; ts?: number }>;
  holding?: boolean;
  emissions?: { fuel_gph: number; co2_kg_per_hour: number };
}

export interface CommercialFlight extends FlightBase {
  type: 'commercial_flight';
  airline_code?: string;
  supplemental_source?: string;
}

export interface PrivateFlight extends FlightBase {
  type: 'private_ga' | 'private_flight';
}

export interface PrivateJet extends FlightBase {
  type: 'private_jet';
}

export interface MilitaryFlight extends FlightBase {
  type: 'military_flight';
  military_type?: 'heli' | 'fighter' | 'bomber' | 'tanker' | 'cargo' | 'recon' | 'default';
  force?: string;
}

export interface TrackedFlight extends FlightBase {
  type: 'tracked_flight';
  alert_category?: string;
  alert_operator?: string;
  alert_special?: string;
  alert_flag?: string;
  alert_color?: string;
  alert_wiki?: string;
  alert_type?: string;
  alert_tags?: string[];
  alert_link?: string;
  alert_socials?: { twitter?: string; instagram?: string };
  tracked_name?: string;
  operator?: string;
  owner?: string;
  name?: string;
}

export interface UAV extends FlightBase {
  type: 'uav';
  uav_type?: string;
  aircraft_model?: string;
  wiki?: string;
  force?: string;
  id?: string | number;
}

export type Flight =
  | CommercialFlight
  | PrivateFlight
  | PrivateJet
  | MilitaryFlight
  | TrackedFlight
  | UAV;

// ─── SHIPS / MARITIME ───────────────────────────────────────────────────────

export interface Ship {
  mmsi: number;
  name: string;
  type:
    | 'carrier'
    | 'military_vessel'
    | 'tanker'
    | 'cargo'
    | 'passenger'
    | 'yacht'
    | 'other'
    | 'unknown';
  lat: number;
  lng: number;
  heading: number;
  sog: number;
  cog: number;
  callsign?: string;
  destination?: string;
  imo?: number;
  country: string;
  ais_type_code?: number;
  _updated?: number;
  estimated?: boolean;
  source?: string;
  source_url?: string;
  last_osint_update?: string;
  desc?: string;
  // Tracked yacht enrichment
  yacht_alert?: boolean;
  yacht_owner?: string;
  yacht_name?: string;
  yacht_category?: string;
  yacht_color?: string;
  yacht_builder?: string;
  yacht_length?: number;
  yacht_year?: number;
  yacht_link?: string;
  // PLAN/CCG vessel enrichment
  plan_name?: string;
  plan_class?: string;
  plan_force?: string;
  plan_hull?: string;
  plan_wiki?: string;
  // Carrier enrichment
  wiki?: string;
  homeport?: string;
  homeport_lat?: number;
  homeport_lng?: number;
  fallback_lat?: number;
  fallback_lng?: number;
  fallback_heading?: number;
  fallback_desc?: string;
}

// ─── SATELLITES ─────────────────────────────────────────────────────────────

export type SatelliteMission =
  | 'military_recon'
  | 'military_sar'
  | 'military_ew'
  | 'military_comms'
  | 'sar'
  | 'commercial_imaging'
  | 'navigation'
  | 'early_warning'
  | 'space_station'
  | 'sigint'
  | 'starlink'
  | 'constellation'
  | 'general';

export interface Satellite {
  id: number;
  name: string;
  mission: SatelliteMission;
  sat_type: string;
  country: string;
  wiki?: string;
  lat: number;
  lng: number;
  alt_km: number;
  speed_knots: number;
  heading: number;
}

export interface SatManeuverAlert {
  norad_id: number;
  name: string;
  type: 'maneuver';
  reasons: string[];
  epoch: string;
  delta_period_min: number;
  delta_inclination_deg: number;
  delta_eccentricity: number;
}

export interface SatDecayAlert {
  norad_id: number;
  name: string;
  type: 'decay_anomaly';
  mm_rate: number;
  current_mm: number;
  approx_alt_km: number;
  epoch: string;
  dt_days: number;
}

export interface StarlinkSummary {
  total: number;
  shells: Record<string, number>;
}

export interface SatelliteAnalysis {
  maneuvers: SatManeuverAlert[];
  decay_anomalies: SatDecayAlert[];
  starlink: StarlinkSummary;
  catalog_size: number;
  classified_count: number;
}

// ─── EARTHQUAKES ────────────────────────────────────────────────────────────

export interface Earthquake {
  id: string;
  mag: number;
  lat: number;
  lng: number;
  place: string;
  title?: string;
}

// ─── GPS JAMMING ────────────────────────────────────────────────────────────

export interface GPSJammingZone {
  lat: number;
  lng: number;
  severity: 'high' | 'medium' | 'low';
  ratio: number;
  degraded: number;
  total: number;
}

// ─── FIRE HOTSPOTS (NASA FIRMS) ─────────────────────────────────────────────

export interface FireHotspot {
  lat: number;
  lng: number;
  frp: number;
  brightness: number;
  confidence: string;
  daynight: string;
  acq_date: string;
  acq_time: string;
}

// ─── TRAINS ────────────────────────────────────────────────────────────

export interface Train {
  id: string;
  name: string;
  number: string;
  source: 'amtrak' | 'digitraffic' | string;
  source_label?: string;
  operator?: string;
  country?: string;
  telemetry_quality?: string;
  lat: number;
  lng: number;
  speed_kmh: number | null;
  heading: number | null;
  status: string;
  route: string;
}

// ─── CCTV CAMERAS ───────────────────────────────────────────────────────────

export interface CCTVCamera {
  id: string | number;
  lat: number;
  lon: number;
  direction_facing?: string;
  source_agency?: string;
  media_url?: string;
  media_type?: 'image' | 'hls' | 'mjpeg';
}

// ─── KIWISDR RECEIVERS ─────────────────────────────────────────────────────

export interface KiwiSDR {
  lat: number;
  lon: number;
  name: string;
  url?: string;
  users?: number;
  users_max?: number;
  bands?: string;
  antenna?: string;
  location?: string;
}

// ─── PSK REPORTER SPOTS ─────────────────────────────────────────────────────

export interface PSKSpot {
  lat: number;
  lon: number;
  sender: string;
  receiver: string;
  frequency: number;
  mode: string;
  snr: number;
  time: string;
}

// ─── SATNOGS GROUND STATIONS ────────────────────────────────────────────────

export interface SatNOGSStation {
  id: number;
  name: string;
  lat: number;
  lng: number;
  altitude?: number;
  antenna?: string;
  observations?: number;
  status?: number;
  last_seen?: string;
}

export interface SatNOGSObservation {
  id: number;
  satellite_name: string;
  norad_id?: number;
  station_name: string;
  lat: number;
  lng: number;
  start?: string;
  end?: string;
  frequency?: number;
  mode?: string;
  waterfall?: string;
  audio?: string;
  status?: string;
}

// ─── TINYGS LORA SATELLITES ─────────────────────────────────────────────────

export interface TinyGSSatellite {
  name: string;
  lat: number;
  lng: number;
  heading?: number;
  speed_knots?: number;
  alt_km?: number;
  status?: string;
  modulation?: string;
  frequency?: string;
  sgp4_propagated?: boolean;
  tinygs_confirmed?: boolean;
}

// ─── POLICE SCANNERS (OpenMHZ) ──────────────────────────────────────────────

export interface Scanner {
  shortName: string;
  name: string;
  lat: number;
  lng: number;
  city: string;
  state: string;
  clientCount: number;
  description: string;
}

// ─── SIGINT (APRS / Meshtastic / JS8Call) ───────────────────────────────────

export interface SigintSignal {
  callsign?: string;
  lat?: number;
  lng?: number;
  source?: 'aprs' | 'meshtastic' | 'js8call' | string;
  region?: string;
  root?: string;
  channel?: string;
  confidence?: number;
  timestamp?: string;
  position_updated_at?: string;
  raw_message?: string;
  status?: string;
  comment?: string;
  station_type?: string;
  emergency?: boolean;
  emergency_keyword?: string;
  long_name?: string;
  short_name?: string;
  hardware?: string;
  role?: string;
  battery_level?: number;
  voltage?: number | string | null;
  altitude?: number | null;
  from_api?: boolean;
  snr?: number;
  frequency?: string | number;
  grid?: string;
  symbol?: string;
  altitude_ft?: number;
  speed_knots?: number;
  course?: number;
  battery_v?: number;
  power_watts?: number;
  geometry?: { coordinates?: [number, number] };
}

// ─── INTERNET OUTAGES (IODA) ────────────────────────────────────────────────

export interface InternetOutage {
  region_code: string;
  region_name: string;
  country_code: string;
  country_name: string;
  level: string;
  datasource: string;
  severity: number;
  lat: number;
  lng: number;
}

// ─── DATA CENTERS ───────────────────────────────────────────────────────────

export interface DataCenter {
  name: string;
  company: string;
  street?: string;
  city?: string;
  country?: string;
  zip?: string;
  lat: number;
  lng: number;
}

export interface PowerPlant {
  name: string;
  country: string;
  fuel_type: string;
  capacity_mw: number | null;
  owner: string;
  lat: number;
  lng: number;
}

export interface VIIRSChangeNode {
  lat: number;
  lng: number;
  mean_change_pct: number;
  severity: 'severe' | 'high' | 'moderate' | 'growth' | 'rapid_growth';
  aoi_name: string;
}

export interface MilitaryBase {
  name: string;
  country: string;
  operator: string;
  branch: string;
  lat: number;
  lng: number;
}

export interface UkraineAlert {
  id: number;
  alert_type: string;
  location_title: string;
  location_uid: string;
  name_en: string;
  started_at: string;
  color: string;
  geometry: GeoJSON.Geometry;
}

export interface WeatherAlert {
  id: string;
  event: string;
  severity: string;
  certainty: string;
  urgency: string;
  headline: string;
  description: string;
  expires: string;
  geometry: GeoJSON.Geometry;
}

export interface AirQualityStation {
  id: number;
  name: string;
  lat: number;
  lng: number;
  pm25: number;
  aqi: number;
  country: string;
}

export interface Volcano {
  name: string;
  type: string;
  country: string;
  region: string;
  elevation: number;
  last_eruption_year: number | null;
  lat: number;
  lng: number;
}

// ─── UAP SIGHTINGS ─────────────────────────────────────────────────────

export interface UAPSighting {
  id: string;
  date_time: string;
  city: string;
  state: string;
  country: string;
  shape: string;
  shape_raw: string;
  duration: string;
  summary: string;
  posted: string;
  lat: number;
  lng: number;
  source: string;
}

// ─── WASTEWATER SCAN ────────────────────────────────��─────────────────

export interface WastewaterPathogen {
  name: string;
  target_key: string;
  concentration: number;
  normalized: number;
  activity: string;
  alert: boolean;
}

export interface WastewaterPlant {
  id: string;
  name: string;
  site_name: string;
  city: string;
  state: string;
  country: string;
  population: number | null;
  lat: number;
  lng: number;
  pathogens: WastewaterPathogen[];
  alert_count: number;
  collection_date: string;
  source: string;
}

export interface FishingEvent {
  id: string;
  type: string;
  lat: number;
  lng: number;
  start: string;
  end: string;
  vessel_id?: string;
  vessel_ssvid?: string;
  vessel_name: string;
  vessel_flag: string;
  duration_hrs: number;
  event_count?: number;
}

// ─── CORRELATION ALERTS ────────────────────────────────────────────────────

// ─── CROWDTHREAT ───────────────────────────────────────────────────────────

export interface CrowdThreatItem {
  id: number;
  title: string;
  summary?: string;
  lat: number;
  lng: number;
  address: string;
  city: string;
  country?: string;
  category: string;
  category_id: number;
  category_colour: string;
  subcategory: string;
  threat_type: string;
  icon_id: string;
  occurred: string;
  occurred_iso?: string;
  timeago: string;
  reported?: string;
  verification?: string;
  severity?: string;
  source_url?: string;
  media_urls?: string[];
  votes?: number;
  reporter?: string;
  source: string;
}

export interface CorrelationAlert {
  lat: number;
  lng: number;
  type: 'rf_anomaly' | 'military_buildup' | 'infra_cascade' | 'contradiction' | 'analysis_zone';
  severity: 'high' | 'medium' | 'low';
  score: number;
  drivers: string[];
  cell_size: number;
  // Contradiction-specific fields
  context?: 'STRONG' | 'MODERATE' | 'WEAK' | 'DETECTION_GAP';
  alternatives?: string[];
  location_name?: string;
  headlines?: string[];
  related_markets?: { title: string; probability: number }[];
  nearby_outages?: { region: string; severity: number; distance_km: number }[];
  // Analysis zone fields (OpenClaw-placed overlays)
  id?: string;
  title?: string;
  body?: string;
  category?: string;
  source?: string;
}

// ─── NEWS / GLOBAL INCIDENTS ────────────────────────────────────────────────

export interface NewsArticle {
  id: number | string;
  title: string;
  summary: string;
  source: string;
  link: string;
  pub_date: string;
  risk_score: number;
  lat: number;
  lng: number;
  region?: string;
  coords?: [number, number];
  machine_assessment?: string;
  oracle_score?: number;
  sentiment?: number;
  breaking?: boolean;
  prediction_odds?: {
    title: string;
    polymarket_pct: number | null;
    kalshi_pct: number | null;
    consensus_pct: number | null;
    match_score: number;
  } | null;
}

export interface ThreatLevel {
  score: number;
  level: 'GREEN' | 'GUARDED' | 'ELEVATED' | 'HIGH' | 'SEVERE';
  color: string;
  drivers: string[];
}

// ─── UKRAINE FRONTLINE ──────────────────────────────────────────────────────

export interface FrontlineGeoJSON {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    geometry: {
      type: 'Polygon';
      coordinates: [number, number][][];
    };
    properties: {
      name: string;
      zone_id: number;
    };
  }>;
}

// ─── GDELT INCIDENTS ────────────────────────────────────────────────────────

export interface GDELTIncident {
  type: 'Feature';
  geometry: {
    type: 'Point';
    coordinates: [number, number];
  };
  properties: {
    name: string;
    count: number;
    event_date?: string;
    event_code?: string;
    quad_class?: number;
    goldstein?: number;
    num_mentions?: number;
    num_sources?: number;
    num_articles?: number;
    avg_tone?: number;
    actor1?: string;
    actor2?: string;
    actors?: string[];
    _urls_list: string[];
    _headlines_list: string[];
    _snippets_list?: string[];
  };
}

// ─── LIVEUAMAP ──────────────────────────────────────────────────────────────

export interface LiveUAmapIncident {
  id: string | number;
  lat: number;
  lng: number;
  title: string;
  description?: string;
  date?: string;
  timestamp?: number | string;
  link?: string;
  category?: string;
  region?: string;
  image?: string;
  source?: string;
}

// ─── STOCKS & COMMODITIES ───────────────────────────────────────────────────

export interface StockTicker {
  price: number;
  change_percent: number;
  up: boolean;
}

export type StocksData = Record<string, StockTicker>;
export type OilData = Record<string, StockTicker>;

// ─── SPACE WEATHER ──────────────────────────────────────────────────────────

export interface SpaceWeatherEvent {
  type: string;
  begin: string;
  end: string;
  classtype: string;
}

export interface SpaceWeather {
  kp_index: number | null;
  kp_text: string;
  events: SpaceWeatherEvent[];
}

// ─── WEATHER (RAINVIEWER) ───────────────────────────────────────────────────

export interface Weather {
  time: number;
  host: string;
}

// ─── AIRPORTS ───────────────────────────────────────────────────────────────

export interface Airport {
  id: string;
  name: string;
  iata: string;
  lat: number;
  lng: number;
  type: 'airport';
}

// ─── RADIO FEEDS ────────────────────────────────────────────────────────────

export interface RadioFeed {
  id: string;
  name: string;
  location: string;
  category: string;
  listeners: number;
  stream_url?: string;
}

// ─── ROUTE ──────────────────────────────────────────────────────────────────

export interface FlightRoute {
  orig_loc: [number, number];
  dest_loc: [number, number];
  origin_name: string;
  dest_name: string;
}

// ─── REGION DOSSIER ─────────────────────────────────────────────────────────

export interface RegionDossier {
  lat: number;
  lng: number;
  admin_regions?: string[];
  populated_places?: string[];
  // Dynamic properties from backend (sentinel2, weather, etc.)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}

// ─── FRESHNESS METADATA ─────────────────────────────────────────────────────

export type FreshnessMap = Record<string, string>;

// ─── FIMI DISINFORMATION ────────────────────────────────────────────────────

export interface FimiNarrative {
  title: string;
  link: string;
  published: string;
  snippet: string;
  claims: Array<{ url: string; title: string }>;
  actors: string[];
  targets: string[];
  disinfo_keywords: string[];
}

export interface FimiData {
  narratives: FimiNarrative[];
  claims: Array<{ url: string; title: string }>;
  threat_actors: Record<string, number>;
  targets: Record<string, number>;
  disinfo_keywords: string[];
  major_wave: boolean;
  major_wave_target: string | null;
  last_fetched: string;
  source: string;
  source_url: string;
}

// ─── ROOT DATA OBJECT ───────────────────────────────────────────────────────

export interface DashboardData {
  // Metadata
  last_updated?: string | null;
  freshness?: FreshnessMap;
  satellite_source?: string;
  financial_source?: string;
  cctv_total?: number;
  satnogs_total?: number;
  tinygs_total?: number;
  sigint_totals?: {
    total?: number;
    meshtastic?: number;
    meshtastic_live?: number;
    meshtastic_map?: number;
    aprs?: number;
    js8call?: number;
  };

  // Fast tier
  commercial_flights?: CommercialFlight[];
  private_flights?: PrivateFlight[];
  private_jets?: PrivateJet[];
  military_flights?: MilitaryFlight[];
  tracked_flights?: TrackedFlight[];
  uavs?: UAV[];
  ships?: Ship[];
  cctv?: CCTVCamera[];
  liveuamap?: LiveUAmapIncident[];
  gps_jamming?: GPSJammingZone[];
  satellites?: Satellite[];
  satellite_analysis?: SatelliteAnalysis;
  sigint?: SigintSignal[];
  trains?: Train[];

  // Slow tier
  threat_level?: ThreatLevel;
  trending_markets?: Array<{
    title: string;
    consensus_pct: number | null;
    polymarket_pct: number | null;
    kalshi_pct: number | null;
    delta_pct: number | null;
    volume: number;
    volume_24h: number;
    category: string;
    sources: Array<{ name: string; pct: number }>;
    slug: string;
    outcomes?: Array<{ name: string; pct: number }>;
  }>;
  news?: NewsArticle[];
  stocks?: StocksData;
  oil?: OilData;
  unusual_whales?: {
    congress_trades?: import('@/types/unusualWhales').CongressTrade[];
    insider_transactions?: import('@/types/unusualWhales').InsiderTransaction[];
    quotes?: Record<string, { price: number; change_percent: number; up: boolean }>;
  };
  weather?: Weather | null;
  earthquakes?: Earthquake[];
  frontlines?: FrontlineGeoJSON | null;
  gdelt?: GDELTIncident[];
  airports?: Airport[];
  kiwisdr?: KiwiSDR[];
  psk_reporter?: PSKSpot[];
  satnogs_stations?: SatNOGSStation[];
  satnogs_observations?: SatNOGSObservation[];
  tinygs_satellites?: TinyGSSatellite[];
  scanners?: Scanner[];
  space_weather?: SpaceWeather | null;
  internet_outages?: InternetOutage[];
  firms_fires?: FireHotspot[];
  datacenters?: DataCenter[];
  military_bases?: MilitaryBase[];
  power_plants?: PowerPlant[];
  viirs_change_nodes?: VIIRSChangeNode[];
  ukraine_alerts?: UkraineAlert[];
  weather_alerts?: WeatherAlert[];
  air_quality?: AirQualityStation[];
  volcanoes?: Volcano[];
  fishing_activity?: FishingEvent[];

  // Cross-layer correlations
  correlations?: CorrelationAlert[];

  // UAP sightings
  uap_sightings?: UAPSighting[];

  // WastewaterSCAN pathogen surveillance
  wastewater?: WastewaterPlant[];

  // CrowdThreat — crowdsourced threat intelligence
  crowdthreat?: CrowdThreatItem[];

  // FIMI disinformation
  fimi?: FimiData;

  // SAR (Synthetic Aperture Radar) layer
  sar_scenes?: SarScene[];
  sar_anomalies?: SarAnomaly[];
  sar_aoi_coverage?: SarAoiCoverage[];
  sar_aois?: SarAoi[];
}

// ─── SAR ─────────────────────────────────────────────────────────────────────

export interface SarScene {
  scene_id: string;
  platform: string;
  mode: string;
  level: string;
  time: string;
  aoi_id: string;
  relative_orbit: number;
  flight_direction: string;
  bbox: number[];
  download_url: string;
  provider: string;
  raw_provider_id?: string;
}

export interface SarAnomaly {
  anomaly_id: string;
  kind: string;
  lat: number;
  lon: number;
  magnitude: number;
  magnitude_unit: string;
  confidence: number;
  first_seen: number;
  last_seen: number;
  aoi_id: string;
  scene_count: number;
  solver: string;
  source_constellation: string;
  provenance_url: string;
  category: string;
  title: string;
  summary: string;
  evidence_hash?: string;
  extras?: Record<string, unknown>;
}

export interface SarAoi {
  id: string;
  name: string;
  description?: string;
  center: [number, number]; // [lat, lon]
  radius_km: number;
  polygon?: number[][] | null;
  category: string;
}

export interface SarAoiCoverage {
  aoi_id: string;
  scene_count?: number;
  last_pass?: string;
  next_pass?: string;
  [key: string]: unknown;
}

// ─── COMPONENT PROPS ────────────────────────────────────────────────────────

export interface ActiveLayers {
  flights: boolean;
  private: boolean;
  jets: boolean;
  military: boolean;
  tracked: boolean;
  satellites: boolean;
  ships_military: boolean;
  ships_cargo: boolean;
  ships_civilian: boolean;
  ships_passenger: boolean;
  ships_tracked_yachts: boolean;
  earthquakes: boolean;
  cctv: boolean;
  ukraine_frontline: boolean;
  global_incidents: boolean;
  day_night: boolean;
  gps_jamming: boolean;
  gibs_imagery: boolean;
  highres_satellite: boolean;
  kiwisdr: boolean;
  psk_reporter: boolean;
  satnogs: boolean;
  tinygs: boolean;
  scanners: boolean;
  firms: boolean;
  internet_outages: boolean;
  datacenters: boolean;
  military_bases: boolean;
  power_plants: boolean;
  sigint_meshtastic: boolean;
  sigint_aprs: boolean;
  ukraine_alerts: boolean;
  weather_alerts: boolean;
  air_quality: boolean;
  volcanoes: boolean;
  fishing_activity: boolean;
  sentinel_hub: boolean;
  trains: boolean;
  shodan_overlay: boolean;
  viirs_nightlights: boolean;
  correlations: boolean;
  contradictions: boolean;
  uap_sightings: boolean;
  wastewater: boolean;
  ai_intel: boolean;
  crowdthreat: boolean;
  sar: boolean;
}

export interface SelectedEntity {
  id: string | number;
  type: string;
  name?: string;
  media_url?: string;
  // Dynamic bag — varies by entity type (flight, ship, cctv, region_dossier, etc.)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  extra?: Record<string, any>;
}

export interface MeasurePoint {
  lat: number;
  lng: number;
}

export interface MapEffects {
  bloom: boolean;
  style?: string;
}

export interface MaplibreViewerProps {
  data: DashboardData;
  activeLayers: ActiveLayers;
  activeFilters?: Record<string, string[]>;
  effects?: MapEffects;
  onEntityClick: (entity: SelectedEntity | null) => void;
  flyToLocation: { lat: number; lng: number; zoom?: number; ts?: number } | null;
  selectedEntity: SelectedEntity | null;
  onMouseCoords: (coords: { lat: number; lng: number }) => void;
  onRightClick: (coords: { lat: number; lng: number }) => void;
  regionDossier: RegionDossier | null;
  regionDossierLoading: boolean;
  onViewStateChange?: (vs: { zoom: number; latitude: number }) => void;
  measureMode: boolean;
  onMeasureClick: (coords: { lat: number; lng: number }) => void;
  measurePoints: MeasurePoint[];
  gibsDate: string;
  gibsOpacity: number;
  sentinelDate?: string;
  sentinelOpacity?: number;
  sentinelPreset?: string;
  isEavesdropping?: boolean;
  onEavesdropClick?: (coords: { lat: number; lng: number }) => void;
  onCameraMove?: (coords: { lat: number; lng: number }) => void;
  viewBoundsRef?: React.RefObject<{
    south: number;
    west: number;
    north: number;
    east: number;
  } | null>;
  trackedSdr?: KiwiSDR | null;
  setTrackedSdr?: (sdr: KiwiSDR | null) => void;
  trackedScanner?: Scanner | null;
  setTrackedScanner?: (scanner: Scanner | null) => void;
  shodanResults?: import('@/types/shodan').ShodanSearchMatch[];
  shodanStyle?: import('@/types/shodan').ShodanStyleConfig;
  pinPlacementMode?: boolean;
  onPinPlaced?: () => void;
  sarAoiDropMode?: boolean;
  onSarAoiDropped?: (coords: { lat: number; lng: number }) => void;
  /** Incremented when the AOI list is modified — triggers immediate re-fetch. */
  sarAoiListVersion?: number;
}
