export interface ShodanFacetBucket {
  value: string;
  count: number;
}

export interface ShodanSearchMatch {
  id: string;
  ip: string;
  port: number | null;
  transport?: string | null;
  timestamp?: string | null;
  lat: number | null;
  lng: number | null;
  city?: string | null;
  region_code?: string | null;
  country_code?: string | null;
  country_name?: string | null;
  location_label?: string | null;
  asn?: string | null;
  org?: string | null;
  isp?: string | null;
  product?: string | null;
  os?: string | null;
  hostnames: string[];
  domains: string[];
  tags: string[];
  vulns: string[];
  data_snippet?: string | null;
  attribution: string;
}

export interface ShodanHostService {
  port: number | null;
  transport?: string | null;
  product?: string | null;
  timestamp?: string | null;
  tags: string[];
  banner_excerpt?: string | null;
}

export interface ShodanHost {
  id: string;
  ip: string;
  lat: number | null;
  lng: number | null;
  city?: string | null;
  region_code?: string | null;
  country_code?: string | null;
  country_name?: string | null;
  location_label?: string | null;
  asn?: string | null;
  org?: string | null;
  isp?: string | null;
  os?: string | null;
  hostnames: string[];
  domains: string[];
  tags: string[];
  ports: number[];
  services: ShodanHostService[];
  vulns: string[];
  attribution: string;
}

export interface ShodanStatusResponse {
  ok: boolean;
  configured: boolean;
  source: string;
  mode: string;
  paid_api: boolean;
  manual_only: boolean;
  background_polling: boolean;
  local_only: boolean;
  attribution: string;
  warning: string;
  limits: {
    default_pages_per_search: number;
    max_pages_per_search: number;
    cooldown_seconds: number;
  };
}

export interface ShodanSearchResponse {
  ok: boolean;
  source: string;
  attribution: string;
  query: string;
  page: number;
  total: number;
  matches: ShodanSearchMatch[];
  facets: Record<string, ShodanFacetBucket[]>;
  note: string;
}

export interface ShodanCountResponse {
  ok: boolean;
  source: string;
  attribution: string;
  query: string;
  total: number;
  facets: Record<string, ShodanFacetBucket[]>;
  note: string;
}

export interface ShodanHostResponse {
  ok: boolean;
  source: string;
  attribution: string;
  host: ShodanHost;
  history: boolean;
  note: string;
}

export type ShodanMarkerShape = 'circle' | 'triangle' | 'diamond' | 'square';
export type ShodanMarkerSize = 'sm' | 'md' | 'lg';

export interface ShodanStyleConfig {
  shape: ShodanMarkerShape;
  color: string;
  size: ShodanMarkerSize;
}
