import {
  CommercialFlight,
  MilitaryFlight,
  PrivateFlight,
  PrivateJet,
  TrackedFlight,
  Ship,
  CCTVCamera,
  LiveUAmapIncident,
  GPSJammingZone,
  Satellite,
  FreshnessMap,
  NewsArticle,
  StocksData,
  OilData,
  Weather,
  Earthquake,
  FrontlineGeoJSON,
  GDELTIncident,
  Airport,
  KiwiSDR,
  SpaceWeather,
  InternetOutage,
  FireHotspot,
  DataCenter,
  Scanner,
  UAV,
  SigintSignal,
} from './dashboard';

export interface LiveDataFastResponse {
  commercial_flights: CommercialFlight[];
  military_flights: MilitaryFlight[];
  private_flights: PrivateFlight[];
  private_jets: PrivateJet[];
  tracked_flights: TrackedFlight[];
  ships: Ship[];
  cctv: CCTVCamera[];
  uavs: UAV[];
  liveuamap: LiveUAmapIncident[];
  gps_jamming: GPSJammingZone[];
  satellites: Satellite[];
  satellite_source: string;
  sigint: SigintSignal[];
  sigint_totals?: {
    total?: number;
    meshtastic?: number;
    meshtastic_live?: number;
    meshtastic_map?: number;
    aprs?: number;
    js8call?: number;
  };
  cctv_total?: number;
  freshness: FreshnessMap;
}

export interface LiveDataSlowResponse {
  last_updated?: string | null;
  news: NewsArticle[];
  stocks: StocksData;
  oil: OilData;
  weather: Weather | null;
  traffic: unknown[];
  earthquakes: Earthquake[];
  frontlines: FrontlineGeoJSON | null;
  gdelt: GDELTIncident[];
  airports: Airport[];
  kiwisdr: KiwiSDR[];
  satnogs_stations: import('./dashboard').SatNOGSStation[];
  satnogs_total?: number;
  satnogs_observations: import('./dashboard').SatNOGSObservation[];
  tinygs_satellites: import('./dashboard').TinyGSSatellite[];
  tinygs_total?: number;
  space_weather: SpaceWeather | null;
  internet_outages: InternetOutage[];
  firms_fires: FireHotspot[];
  datacenters: DataCenter[];
  scanners: Scanner[];
  freshness: FreshnessMap;
}

export interface HealthResponse {
  status: 'ok';
  last_updated?: string | null;
  sources: Record<string, number>;
  freshness: FreshnessMap;
  uptime_seconds: number;
}

export interface RefreshResponse {
  status: string;
}
