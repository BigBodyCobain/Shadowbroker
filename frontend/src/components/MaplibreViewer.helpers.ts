// @ts-nocheck
import type { KiwiSDR, Scanner, SigintSignal } from '@/types/dashboard';
import type { findSelectedEntity } from '@/components/map/geoJSONBuilders';


export type ViewBounds = { south: number; west: number; north: number; east: number };

export type DynamicRoute = {
  orig_loc?: [number, number];
  dest_loc?: [number, number];
  origin_name?: string;
  dest_name?: string;
};

export type GeoExtras = {
  lat?: number;
  lng?: number;
  lon?: number;
  geometry?: { coordinates?: [number, number] };
};

export type KiwiProps = Partial<KiwiSDR> & GeoExtras;
export type ScannerProps = Partial<Scanner> & GeoExtras;
export type SigintProps = Partial<SigintSignal> & GeoExtras;
export type TrailPoint = { lng: number; lat: number; alt?: number; sog?: number; ts?: number };
export type TrailKind = 'flight' | 'ship';

export const FLIGHT_SELECTION_TYPES = new Set([
  'flight',
  'private_flight',
  'military_flight',
  'private_jet',
  'tracked_flight',
]);

export function parseTrailPoints(raw: unknown, kind: TrailKind): TrailPoint[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((p): TrailPoint | null => {
      if (Array.isArray(p)) {
        const lat = Number(p[0]);
        const lng = Number(p[1]);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
        if (kind === 'ship') {
          return { lat, lng, sog: Number(p[2]) || 0, ts: Number(p[3]) || 0 };
        }
        return { lat, lng, alt: Number(p[2]) || 0, ts: Number(p[3]) || 0 };
      }
      if (p && typeof p === 'object') {
        const point = p as { lat?: number; lng?: number; alt?: number; sog?: number; ts?: number };
        const lat = Number(point.lat);
        const lng = Number(point.lng);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
        return {
          lat,
          lng,
          alt: Number(point.alt) || 0,
          sog: Number(point.sog) || 0,
          ts: Number(point.ts) || 0,
        };
      }
      return null;
    })
    .filter((p): p is TrailPoint => Boolean(p && (p.lat !== 0 || p.lng !== 0)));
}

export function hasKnownRouteName(value?: string | null): boolean {
  const normalized = String(value || '').trim().toUpperCase();
  return Boolean(normalized && normalized !== 'UNKNOWN');
}

export function flightHasKnownRoute(entity: ReturnType<typeof findSelectedEntity>, dynamicRoute: DynamicRoute | null): boolean {
  if (!entity) return false;
  if (dynamicRoute?.orig_loc && dynamicRoute?.dest_loc) return true;
  return flightPayloadHasKnownRoute(entity);
}

export function flightPayloadHasKnownRoute(entity: ReturnType<typeof findSelectedEntity>): boolean {
  if (!entity) return false;
  if (!('origin_loc' in entity) && !('origin_name' in entity)) return false;
  const flight = entity as Flight;
  return Boolean(
    (flight.origin_loc && flight.dest_loc)
      || (hasKnownRouteName(flight.origin_name) && hasKnownRouteName(flight.dest_name)),
  );
}

export const MAP_EXTRA_DATA_KEYS = [
  'air_quality',
  'cctv',
  'correlations',
  'crowdthreat',
  'malware_threats',
  'telegram_osint',
  'gt_risk',
  'datacenters',
  'firms_fires',
  'fishing_activity',
  'frontlines',
  'gps_jamming',
  'internet_outages',
  'kiwisdr',
  'military_bases',
  'power_plants',
  'psk_reporter',
  'sar_anomalies',
  'satellite_analysis',
  'satellites',
  'satnogs_stations',
  'scanners',
  'sigint',
  'tinygs_satellites',
  'trains',
  'uap_sightings',
  'ukraine_alerts',
  'viirs_change_nodes',
  'volcanoes',
  'wastewater',
  'weather_alerts',
] as const satisfies readonly (keyof DashboardData)[];

export const VIIRS_TILE_TEMPLATES = [
  // The older daily Day/Night Band path now 404s in GIBS. Black Marble is the
  // current stable night-lights product and has a best-available endpoint.
  'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png',
  'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/default/2016-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png',
];

export function buildProbeRasterUrl(tileTemplate: string): string {
  return tileTemplate
    .replace('{z}', '0')
    .replace('{y}', '0')
    .replace('{x}', '0');
}

export function probeRasterTile(url: string): Promise<boolean> {
  return new Promise((resolve) => {
    const img = new Image();
    let settled = false;
    const finish = (ok: boolean) => {
      if (settled) return;
      settled = true;
      img.onload = null;
      img.onerror = null;
      resolve(ok);
    };
    img.onload = () => finish(true);
    img.onerror = () => finish(false);
    img.referrerPolicy = 'no-referrer';
    img.src = url;
  });
}

export function buildPolymarketUrl(prediction: { slug?: string; title?: string } | null | undefined): string {
  const slug = String(prediction?.slug || '').trim();
  if (slug) return `https://polymarket.com/event/${encodeURIComponent(slug)}`;
  const title = String(prediction?.title || '').trim();
  return title
    ? `https://polymarket.com/search?query=${encodeURIComponent(title)}`
    : 'https://polymarket.com/markets';
}

