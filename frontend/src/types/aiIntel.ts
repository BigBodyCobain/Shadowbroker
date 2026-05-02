/**
 * AI Intel types — shared TypeScript interfaces for the AI Intel subsystem.
 */

// ---------------------------------------------------------------------------
// Entity Attachment (pin tracks a moving object)
// ---------------------------------------------------------------------------

export interface EntityAttachment {
  entity_type: string;  // "ship", "flight", "satellite", etc.
  entity_id: string;
  entity_label: string;
}

// ---------------------------------------------------------------------------
// Pin Layers
// ---------------------------------------------------------------------------

export interface AIIntelLayer {
  id: string;
  name: string;
  description: string;
  source: string;         // "user" | "openclaw" | "system" | "external"
  visible: boolean;
  color: string;
  created_at: number;
  created_at_iso: string;
  feed_url: string;
  feed_interval: number;
  feed_last_fetched?: number;
  pin_count: number;
}

// ---------------------------------------------------------------------------
// Pins
// ---------------------------------------------------------------------------

export interface AIIntelPinComment {
  id: string;
  text: string;
  author: string;         // "user" | "agent" | "openclaw"
  author_label: string;
  reply_to: string;       // parent comment id, if any
  created_at: number;
  created_at_iso: string;
}

export interface AIIntelPin {
  id: string;
  layer_id: string;
  lat: number;
  lng: number;
  label: string;
  category: PinCategory;
  color: string;
  description: string;
  source: string;
  source_url: string;
  confidence: number;
  created_at: string;
  expires_at?: number | null;
  metadata: Record<string, unknown>;
  entity_attachment?: EntityAttachment | null;
  comments?: AIIntelPinComment[];
}

export type PinCategory =
  | 'threat'
  | 'news'
  | 'geolocation'
  | 'custom'
  | 'anomaly'
  | 'military'
  | 'maritime'
  | 'flight'
  | 'infrastructure'
  | 'weather'
  | 'sigint'
  | 'prediction'
  | 'research';

export const PIN_CATEGORY_COLORS: Record<PinCategory, string> = {
  threat: '#ef4444',
  news: '#f59e0b',
  geolocation: '#8b5cf6',
  custom: '#3b82f6',
  anomaly: '#f97316',
  military: '#dc2626',
  maritime: '#0ea5e9',
  flight: '#6366f1',
  infrastructure: '#64748b',
  weather: '#22d3ee',
  sigint: '#a855f7',
  prediction: '#eab308',
  research: '#10b981',
};

export const PIN_CATEGORY_LABELS: Record<PinCategory, string> = {
  threat: 'Threat',
  news: 'News',
  geolocation: 'Geolocation',
  custom: 'Custom',
  anomaly: 'Anomaly',
  military: 'Military',
  maritime: 'Maritime',
  flight: 'Flight',
  infrastructure: 'Infrastructure',
  weather: 'Weather',
  sigint: 'SIGINT',
  prediction: 'Prediction',
  research: 'Research',
};

// ---------------------------------------------------------------------------
// Status / GeoJSON / Other
// ---------------------------------------------------------------------------

export interface AIIntelStatus {
  ok: boolean;
  service: string;
  version: string;
  pin_count: number;
  pin_categories: Record<string, number>;
  capabilities: string[];
  timestamp: number;
}

export interface AIIntelGeoJSON {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    geometry: {
      type: 'Point';
      coordinates: [number, number];
    };
    properties: {
      id: string;
      layer_id: string;
      label: string;
      category: PinCategory;
      color: string;
      description: string;
      source: string;
      source_url: string;
      confidence: number;
      created_at: string;
      entity_attachment?: EntityAttachment;
    };
  }>;
}

export interface SatelliteScene {
  scene_id: string;
  datetime: string;
  cloud_cover: number;
  platform: string;
  thumbnail_url: string;
  fullres_url: string;
  bbox: number[];
}

export interface NewsNearResult {
  ok: boolean;
  center: { lat: number; lng: number };
  radius_miles: number;
  gdelt: Array<{
    name: string;
    count: number;
    urls: string[];
    headlines: string[];
    lat: number;
    lng: number;
    distance_miles: number;
  }>;
  gdelt_count: number;
  news: Array<{
    title: string;
    summary: string;
    source: string;
    link: string;
    risk_score: number;
    lat: number;
    lng: number;
    distance_miles: number;
  }>;
  news_count: number;
}
