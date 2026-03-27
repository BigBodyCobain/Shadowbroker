// ─── Pure GeoJSON builder functions ─────────────────────────────────────────
// Extracted from MaplibreViewer to reduce component size and enable unit testing.
// Each function takes data arrays + optional helpers and returns a GeoJSON FeatureCollection or null.

import type {
  Earthquake,
  GPSJammingZone,
  FireHotspot,
  InternetOutage,
  DataCenter,
  PowerPlant,
  VIIRSChangeNode,
  MilitaryBase,
  DashboardData,
  GDELTIncident,
  LiveUAmapIncident,
  CCTVCamera,
  KiwiSDR,
  PSKSpot,
  SatNOGSStation,
  TinyGSSatellite,
  Scanner,
  FrontlineGeoJSON,
  UAV,
  Flight,
  Satellite,
  Ship,
  ActiveLayers,
  SelectedEntity,
  UkraineAlert,
  WeatherAlert,
  AirQualityStation,
  Volcano,
  FishingEvent,
  SigintSignal,
  Train,
  CorrelationAlert,
} from '@/types/dashboard';
import { classifyAircraft } from '@/utils/aircraftClassification';
import { MISSION_COLORS, MISSION_ICON_MAP } from '@/components/map/icons/SatelliteIcons';
import { weatherIconId } from '@/components/map/icons/AircraftIcons';
import { interpolatePosition, projectPoint } from '@/utils/positioning';
import type { ShodanSearchMatch } from '@/types/shodan';

type FC = GeoJSON.FeatureCollection | null;
type InViewFilter = (lat: number, lng: number) => boolean;

// ─── Shared Entity Lookup ───────────────────────────────────────────────────

/** Find the currently selected entity across all data arrays. DRYs the polymorphic lookup. */
export function findSelectedEntity(
  selectedEntity: SelectedEntity | null,
  data?: DashboardData | null,
): Flight | Ship | null {
  if (!selectedEntity || !data) return null;
  const id = selectedEntity.id;
  switch (selectedEntity.type) {
    case 'flight':
      return data.commercial_flights?.find((f) => f.icao24 === id) || null;
    case 'private_flight':
      return data.private_flights?.find((f) => f.icao24 === id) || null;
    case 'military_flight':
      return data.military_flights?.find((f) => f.icao24 === id) || null;
    case 'private_jet':
      return data.private_jets?.find((f) => f.icao24 === id) || null;
    case 'tracked_flight':
      return data.tracked_flights?.find((f) => f.icao24 === id) || null;
    case 'ship':
      return data.ships?.find((s) => s.mmsi === id) || null;
    case 'uav':
      return data.uavs?.find((u) => u.id === id) || null;
    default:
      return null;
  }
}

// ─── Predictive Vector ──────────────────────────────────────────────────────

/** Build a dotted line projecting forward ~5 minutes from the entity's current heading + speed. */
type PredictiveEntity = {
  lat: number;
  lng: number;
  true_track?: number;
  cog?: number;
  heading?: number;
  speed_knots?: number | null;
  sog?: number | null;
  alt?: number | null;
};

export function buildPredictiveGeoJSON(entity: PredictiveEntity | null): FC {
  if (!entity || entity.lat == null || entity.lng == null) return null;
  const heading = entity.true_track || entity.cog || entity.heading;
  const speed = entity.speed_knots || entity.sog;
  if (!heading && heading !== 0) return null;
  if (!speed || speed <= 0) return null;
  // Skip grounded aircraft
  if (entity.alt != null && entity.alt <= 100 && !entity.sog) return null;

  const steps = [60, 120, 180, 240, 300]; // 1–5 minutes
  const coords: [number, number][] = [[entity.lng, entity.lat]];
  for (const dt of steps) {
    const [lat, lng] = interpolatePosition(entity.lat, entity.lng, heading, speed, dt, 0, 600);
    coords.push([lng, lat]);
  }

  const endCoord = coords[coords.length - 1];
  return {
    type: 'FeatureCollection' as const,
    features: [
      {
        type: 'Feature' as const,
        properties: { type: 'predictive-line' },
        geometry: { type: 'LineString' as const, coordinates: coords },
      },
      {
        type: 'Feature' as const,
        properties: { type: 'predictive-endpoint' },
        geometry: { type: 'Point' as const, coordinates: endCoord },
      },
    ],
  };
}

// ─── Proximity Rings ────────────────────────────────────────────────────────

const NM_TO_METERS = 1852;

/** Build concentric range ring LineStrings at specified nautical-mile radii. */
export function buildProximityRingsGeoJSON(lat: number, lng: number, radiiNm: number[]): FC {
  const features = radiiNm.map((nm) => {
    const distMeters = nm * NM_TO_METERS;
    const coords: [number, number][] = [];
    const segments = 64;
    for (let i = 0; i <= segments; i++) {
      const bearing = (i / segments) * 360;
      const [pLat, pLng] = projectPoint(lat, lng, bearing, distMeters);
      coords.push([pLng, pLat]);
    }
    return {
      type: 'Feature' as const,
      properties: { radius_nm: nm, label: `${nm}nm` },
      geometry: { type: 'LineString' as const, coordinates: coords },
    };
  });
  return { type: 'FeatureCollection' as const, features: features as GeoJSON.Feature[] };
}

// ─── Earthquakes ────────────────────────────────────────────────────────────

export function buildEarthquakesGeoJSON(earthquakes?: Earthquake[]): FC {
  if (!earthquakes?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: earthquakes
      .map((eq, i) => {
        if (eq.lat == null || eq.lng == null) return null;
        return {
          type: 'Feature' as const,
          properties: {
            id: i,
            type: 'earthquake',
            name: `[M${eq.mag}]\n${eq.place || 'Unknown Location'}`,
            title: eq.title,
          },
          geometry: { type: 'Point' as const, coordinates: [eq.lng, eq.lat] },
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}

// ─── GPS Jamming Zones ──────────────────────────────────────────────────────

export function buildJammingGeoJSON(zones?: GPSJammingZone[]): FC {
  if (!zones?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: zones.map((zone, i) => {
      const halfDeg = 0.5;
      return {
        type: 'Feature' as const,
        properties: {
          id: i,
          severity: zone.severity,
          ratio: zone.ratio,
          degraded: zone.degraded,
          total: zone.total,
          opacity: zone.severity === 'high' ? 0.45 : zone.severity === 'medium' ? 0.3 : 0.18,
        },
        geometry: {
          type: 'Polygon' as const,
          coordinates: [
            [
              [zone.lng - halfDeg, zone.lat - halfDeg],
              [zone.lng + halfDeg, zone.lat - halfDeg],
              [zone.lng + halfDeg, zone.lat + halfDeg],
              [zone.lng - halfDeg, zone.lat + halfDeg],
              [zone.lng - halfDeg, zone.lat - halfDeg],
            ],
          ],
        },
      };
    }),
  };
}

// ─── Correlation Alerts (Emergent Intelligence) ────────────────────────────

export function buildCorrelationsGeoJSON(alerts?: CorrelationAlert[]): FC {
  if (!alerts?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: alerts.map((a, i) => {
      const half = (a.cell_size || 2) / 2;
      const opacityMap: Record<string, Record<string, number>> = {
        rf_anomaly: { high: 0.40, medium: 0.25, low: 0.15 },
        military_buildup: { high: 0.40, medium: 0.25, low: 0.15 },
        infra_cascade: { high: 0.45, medium: 0.30, low: 0.20 },
      };
      return {
        type: 'Feature' as const,
        properties: {
          id: i,
          corr_type: a.type,
          severity: a.severity,
          score: a.score,
          drivers: (a.drivers || []).join(' + '),
          opacity: opacityMap[a.type]?.[a.severity] ?? 0.2,
        },
        geometry: {
          type: 'Polygon' as const,
          coordinates: [
            [
              [a.lng - half, a.lat - half],
              [a.lng + half, a.lat - half],
              [a.lng + half, a.lat + half],
              [a.lng - half, a.lat + half],
              [a.lng - half, a.lat - half],
            ],
          ],
        },
      };
    }),
  };
}

// ─── CCTV Cameras ──────────────────────────────────────────────────────────

export function buildCctvGeoJSON(cameras?: CCTVCamera[], inView?: InViewFilter): FC {
  if (!cameras?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: cameras
      .filter((c) => c.lat != null && c.lon != null && (!inView || inView(c.lat, c.lon)))
      .map((c, i) => ({
        type: 'Feature' as const,
        properties: {
          id: c.id || i,
          type: 'cctv',
          name: c.direction_facing || 'Camera',
          source_agency: c.source_agency || 'Unknown',
          media_url: c.media_url || '',
          media_type: c.media_type || 'image',
        },
        geometry: { type: 'Point' as const, coordinates: [c.lon, c.lat] },
      })),
  };
}

// ─── KiwiSDR Receivers ─────────────────────────────────────────────────────

export function buildKiwisdrGeoJSON(receivers?: KiwiSDR[], inView?: InViewFilter): FC {
  if (!receivers?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: receivers
      .filter((k) => k.lat != null && k.lon != null && (!inView || inView(k.lat, k.lon)))
      .map((k, i) => ({
        type: 'Feature' as const,
        properties: {
          id: i,
          type: 'kiwisdr',
          name: k.name || 'Unknown SDR',
          url: k.url || '',
          users: k.users || 0,
          users_max: k.users_max || 0,
          bands: k.bands || '',
          antenna: k.antenna || '',
          location: k.location || '',
          lat: k.lat,
          lon: k.lon,
        },
        geometry: { type: 'Point' as const, coordinates: [k.lon, k.lat] },
      })),
  };
}

// ─── PSK Reporter Spots ─────────────────────────────────────────────────────

export function buildPskReporterGeoJSON(spots?: PSKSpot[], inView?: InViewFilter): FC {
  if (!spots?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: spots
      .filter((s) => s.lat != null && s.lon != null && (!inView || inView(s.lat, s.lon)))
      .map((s, i) => ({
        type: 'Feature' as const,
        properties: {
          id: i,
          type: 'psk_spot',
          sender: s.sender || '',
          receiver: s.receiver || '',
          frequency: s.frequency || 0,
          mode: s.mode || 'FT8',
          snr: s.snr || 0,
          time: s.time || '',
          lat: s.lat,
          lon: s.lon,
        },
        geometry: { type: 'Point' as const, coordinates: [s.lon, s.lat] },
      })),
  };
}

// ─── SatNOGS Ground Stations ────────────────────────────────────────────────

export function buildSatnogsStationsGeoJSON(
  stations?: SatNOGSStation[],
  inView?: InViewFilter,
): FC {
  if (!stations?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: stations
      .filter((s) => s.lat != null && s.lng != null && (!inView || inView(s.lat, s.lng)))
      .map((s) => ({
        type: 'Feature' as const,
        properties: {
          id: s.id,
          type: 'satnogs_station',
          name: s.name || 'Unknown Station',
          antenna: s.antenna || '',
          observations: s.observations || 0,
          last_seen: s.last_seen || '',
          lat: s.lat,
          lng: s.lng,
        },
        geometry: { type: 'Point' as const, coordinates: [s.lng, s.lat] },
      })),
  };
}

// ─── TinyGS LoRa Satellites ────────────────────────────────────────────────

export function buildTinygsGeoJSON(
  sats?: TinyGSSatellite[],
  inView?: InViewFilter,
  interpTinygs?: (s: TinyGSSatellite) => [number, number],
): FC {
  if (!sats?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: sats
      .map((s, i) => {
        if (s.lat == null || s.lng == null) return null;
        const coords = interpTinygs ? interpTinygs(s) : [s.lng, s.lat] as [number, number];
        if (inView && !inView(coords[1], coords[0])) return null;
        return {
          type: 'Feature' as const,
          properties: {
            id: i,
            type: 'tinygs_satellite',
            name: s.name || 'Unknown Satellite',
            status: s.status || '',
            modulation: s.modulation || '',
            frequency: s.frequency || '',
            alt_km: s.alt_km || 0,
            sgp4_propagated: s.sgp4_propagated || false,
            tinygs_confirmed: s.tinygs_confirmed || false,
            lat: s.lat,
            lng: s.lng,
          },
          geometry: { type: 'Point' as const, coordinates: coords },
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}

// ─── Police Scanners (OpenMHZ) ──────────────────────────────────────────────

export function buildScannerGeoJSON(scanners?: Scanner[], inView?: InViewFilter): FC {
  if (!scanners?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: scanners
      .filter((s) => s.lat != null && s.lng != null && (!inView || inView(s.lat, s.lng)))
      .map((s, i) => ({
        type: 'Feature' as const,
        properties: {
          id: s.shortName || `scanner-${i}`,
          type: 'scanner',
          name: s.name || 'Unknown Scanner',
          shortName: s.shortName || '',
          city: s.city || '',
          state: s.state || '',
          clientCount: s.clientCount || 0,
          description: s.description || '',
          lat: s.lat,
          lng: s.lng,
        },
        geometry: { type: 'Point' as const, coordinates: [s.lng, s.lat] },
      })),
  };
}

// ─── NASA FIRMS Fires ───────────────────────────────────────────────────────

export function buildFirmsGeoJSON(fires?: FireHotspot[]): FC {
  if (!fires?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: fires.map((f, i) => {
      const frp = f.frp || 0;
      const iconId =
        frp >= 100
          ? 'fire-darkred'
          : frp >= 20
            ? 'fire-red'
            : frp >= 5
              ? 'fire-orange'
              : 'fire-yellow';
      return {
        type: 'Feature' as const,
        properties: {
          id: i,
          type: 'firms_fire',
          name: `Fire ${frp.toFixed(1)} MW`,
          frp,
          iconId,
          brightness: f.brightness || 0,
          confidence: f.confidence || '',
          daynight: f.daynight === 'D' ? 'Day' : 'Night',
          acq_date: f.acq_date || '',
          acq_time: f.acq_time || '',
        },
        geometry: { type: 'Point' as const, coordinates: [f.lng, f.lat] },
      };
    }),
  };
}

// ─── Internet Outages ───────────────────────────────────────────────────────

export function buildInternetOutagesGeoJSON(outages?: InternetOutage[]): FC {
  if (!outages?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: outages
      .map((o) => {
        if (o.lat == null || o.lng == null) return null;
        const severity = o.severity || 0;
        const region = o.region_name || o.region_code || '?';
        const country = o.country_name || o.country_code || '';
        const label = `${region}, ${country}`;
        const detail = `${label}\n${severity}% drop · ${o.datasource || 'IODA'}`;
        return {
          type: 'Feature' as const,
          properties: {
            id: o.region_code || region,
            type: 'internet_outage',
            name: label,
            country,
            region,
            level: o.level,
            severity,
            datasource: o.datasource || '',
            detail,
          },
          geometry: { type: 'Point' as const, coordinates: [o.lng, o.lat] },
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}

// ─── Data Centers ───────────────────────────────────────────────────────────

export function buildDataCentersGeoJSON(datacenters?: DataCenter[]): FC {
  if (!datacenters?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: datacenters.map((dc, i) => ({
      type: 'Feature' as const,
      properties: {
        id: `dc-${i}`,
        type: 'datacenter',
        name: dc.name || 'Unknown',
        company: dc.company || '',
        street: dc.street || '',
        city: dc.city || '',
        country: dc.country || '',
        zip: dc.zip || '',
      },
      geometry: { type: 'Point' as const, coordinates: [dc.lng, dc.lat] },
    })),
  };
}

// ─── Power Plants ──────────────────────────────────────────────────────────

export function buildPowerPlantsGeoJSON(plants?: PowerPlant[]): FC {
    if (!plants?.length) return null;
    return {
        type: 'FeatureCollection',
        features: plants.map((p, i) => ({
            type: 'Feature' as const,
            properties: {
                id: `pp-${i}`,
                type: 'power_plant',
                name: p.name || 'Unknown',
                country: p.country || '',
                fuel_type: p.fuel_type || 'Unknown',
                capacity_mw: p.capacity_mw ?? 0,
                owner: p.owner || '',
            },
            geometry: { type: 'Point' as const, coordinates: [p.lng, p.lat] }
        }))
    };
}

// ─── VIIRS Change Nodes ────────────────────────────────────────────────────

const VIIRS_SEVERITY_COLORS: Record<string, string> = {
    severe: '#ef4444',
    high: '#f97316',
    moderate: '#eab308',
    growth: '#22c55e',
    rapid_growth: '#06b6d4',
};

export function buildVIIRSChangeNodesGeoJSON(nodes?: VIIRSChangeNode[]): FC {
    if (!nodes?.length) return null;
    return {
        type: 'FeatureCollection',
        features: nodes.map((n, i) => ({
            type: 'Feature' as const,
            properties: {
                id: `viirs-${i}`,
                type: 'viirs_change_node',
                severity: n.severity,
                mean_change_pct: n.mean_change_pct,
                aoi_name: n.aoi_name,
                color: VIIRS_SEVERITY_COLORS[n.severity] || '#888888',
            },
            geometry: { type: 'Point' as const, coordinates: [n.lng, n.lat] },
        })),
    };
}

// ─── Shodan Overlay ────────────────────────────────────────────────────────

export function buildShodanGeoJSON(results?: ShodanSearchMatch[]): FC {
  if (!results?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: results
      .filter((item) => item.lat != null && item.lng != null)
      .map((item) => ({
        type: 'Feature' as const,
        properties: {
          type: 'shodan_host',
          name: `${item.ip}${item.port ? `:${item.port}` : ''}`,
          ...item,
          source: 'Shodan',
        },
        geometry: { type: 'Point' as const, coordinates: [item.lng as number, item.lat as number] },
      })),
  };
}

// ─── Military Bases ─────────────────────────────────────────────────────────

// Per-country style: label color + icon ID (square-with-X)
const _COUNTRY_BASE_STYLE: Record<string, { color: string; iconId: string }> = {
    'United States': { color: '#1d4ed8', iconId: 'milbase-us'   },
    'Guam':          { color: '#1d4ed8', iconId: 'milbase-us'   },
    'Hawaii':        { color: '#1d4ed8', iconId: 'milbase-us'   },
    'BIOT':          { color: '#1d4ed8', iconId: 'milbase-us'   },
    'China':         { color: '#dc2626', iconId: 'milbase-cn'   },
    'Japan':         { color: '#e5e7eb', iconId: 'milbase-jp'   },
    'North Korea':   { color: '#dc2626', iconId: 'milbase-nk'   },
    'Russia':        { color: '#2563eb', iconId: 'milbase-ru'   },
    'Iran':          { color: '#16a34a', iconId: 'milbase-ir'   },
    'Taiwan':        { color: '#dc2626', iconId: 'milbase-tw'   },
    'Philippines':   { color: '#2563eb', iconId: 'milbase-ph'   },
    'Australia':     { color: '#1e3a8a', iconId: 'milbase-au'   },
    'South Korea':   { color: '#f3f4f6', iconId: 'milbase-sk'   },
    'United Kingdom':{ color: '#1d4ed8', iconId: 'milbase-uk'   },
    'Israel':        { color: '#2563eb', iconId: 'milbase-il'   },
    'France':        { color: '#3b82f6', iconId: 'milbase-eu-x' },
    'Germany':       { color: '#3b82f6', iconId: 'milbase-eu-x' },
    'Italy':         { color: '#3b82f6', iconId: 'milbase-eu-x' },
    'Spain':         { color: '#3b82f6', iconId: 'milbase-eu'   },
    'Poland':        { color: '#3b82f6', iconId: 'milbase-eu'   },
    'Greece':        { color: '#3b82f6', iconId: 'milbase-eu'   },
    'Netherlands':   { color: '#3b82f6', iconId: 'milbase-eu'   },
    'India':         { color: '#f97316', iconId: 'milbase-in'   },
    'Pakistan':      { color: '#16a34a', iconId: 'milbase-pk'   },
};

const _DEFAULT_STYLE = { color: '#ec4899', iconId: 'milbase-default' };

function _baseStyle(country: string) {
    return _COUNTRY_BASE_STYLE[country] || _DEFAULT_STYLE;
}

export function buildMilitaryBasesGeoJSON(bases?: MilitaryBase[]): FC {
    if (!bases?.length) return null;
    return {
        type: 'FeatureCollection' as const,
        features: bases.map((base, i) => {
            const style = _baseStyle(base.country || '');
            return {
                type: 'Feature' as const,
                properties: {
                    id: `milbase-${i}`,
                    type: 'military_base',
                    name: base.name || 'Unknown',
                    country: base.country || '',
                    operator: base.operator || '',
                    branch: base.branch || '',
                    color: style.color,
                    iconId: style.iconId,
                },
                geometry: { type: 'Point' as const, coordinates: [base.lng, base.lat] },
            };
        }),
    };
}

// ─── GDELT Incidents ────────────────────────────────────────────────────────

export function buildGdeltGeoJSON(gdelt?: GDELTIncident[], inView?: InViewFilter): FC {
  if (!gdelt?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: gdelt
      .map((g) => {
        if (!g.geometry || !g.geometry.coordinates) return null;
        const [gLng, gLat] = g.geometry.coordinates;
        if (inView && !inView(gLat, gLng)) return null;
        return {
          type: 'Feature' as const,
          properties: {
            id: g.properties?.name || String(g.geometry.coordinates),
            type: 'gdelt',
            title: g.properties?.name || '',
          },
          geometry: g.geometry,
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}

// ─── LiveUAMap Incidents ────────────────────────────────────────────────────

export function buildLiveuaGeoJSON(incidents?: LiveUAmapIncident[], inView?: InViewFilter): FC {
  if (!incidents?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: incidents
      .map((incident) => {
        if (incident.lat == null || incident.lng == null) return null;
        if (inView && !inView(incident.lat, incident.lng)) return null;
        const isViolent = /bomb|missil|strike|attack|kill|destroy|fire|shoot|expl|raid/i.test(
          incident.title || '',
        );
        return {
          type: 'Feature' as const,
          properties: {
            id: incident.id,
            type: 'liveuamap',
            title: incident.title || '',
            iconId: isViolent ? 'icon-liveua-red' : 'icon-liveua-yellow',
          },
          geometry: { type: 'Point' as const, coordinates: [incident.lng, incident.lat] },
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}

// ─── Ukraine Frontline ──────────────────────────────────────────────────────

export function buildFrontlineGeoJSON(frontlines?: FrontlineGeoJSON | null): FC {
  if (!frontlines?.features?.length) return null;
  return frontlines;
}

// ─── Parameterized Flight Layer ─────────────────────────────────────────────
// Deduplicates commercial / private / jets / military flight GeoJSON builders.

export interface FlightLayerConfig {
  colorMap: Record<string, string>;
  groundedMap: Record<string, string>;
  typeLabel: string;
  idPrefix: string;
  /** For military flights: special icon overrides by military_type */
  milSpecialMap?: Record<string, string>;
  /** If true, prefer true_track over heading for rotation (commercial flights) */
  useTrackHeading?: boolean;
}

export function buildFlightLayerGeoJSON(
  flights: Flight[] | undefined,
  config: FlightLayerConfig,
  helpers: {
    interpFlight: (f: Flight) => [number, number];
    inView: InViewFilter;
    trackedIcaoSet: Set<string>;
  },
): FC {
  if (!flights?.length) return null;
  const { colorMap, groundedMap, typeLabel, idPrefix, milSpecialMap, useTrackHeading } = config;
  const { interpFlight, inView, trackedIcaoSet } = helpers;
  return {
    type: 'FeatureCollection' as const,
    features: flights
      .map((f, i) => {
        if (f.lat == null || f.lng == null) return null;
        const [iLng, iLat] = interpFlight(f);
        if (!inView(iLat, iLng)) return null;
        if (f.icao24 && trackedIcaoSet.has(f.icao24.toLowerCase())) return null;
        const acType = classifyAircraft(f.model, f.aircraft_category);
        const grounded = f.alt != null && f.alt <= 100;

        let iconId: string;
        if (milSpecialMap) {
          const milType = ('military_type' in f ? f.military_type : undefined) || 'default';
          iconId = milSpecialMap[milType] || '';
          if (!iconId) {
            iconId = grounded ? groundedMap[acType] : colorMap[acType];
          } else if (grounded) {
            iconId = groundedMap[acType];
          }
        } else {
          iconId = grounded ? groundedMap[acType] : colorMap[acType];
        }

        const rotation = useTrackHeading ? f.true_track || f.heading || 0 : f.heading || 0;
        return {
          type: 'Feature' as const,
          properties: {
            id: f.icao24 || f.callsign || `${idPrefix}${i}`,
            type: typeLabel,
            callsign: f.callsign || f.icao24,
            rotation,
            iconId,
          },
          geometry: { type: 'Point' as const, coordinates: [iLng, iLat] },
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}

// ─── UAVs / Drones ──────────────────────────────────────────────────────────

export function buildUavGeoJSON(uavs?: UAV[], inView?: InViewFilter): FC {
  if (!uavs?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: uavs
      .map((uav, i) => {
        if (uav.lat == null || uav.lng == null) return null;
        if (inView && !inView(uav.lat, uav.lng)) return null;
        return {
          type: 'Feature' as const,
          properties: {
            id: uav.id || uav.icao24 || `uav-${i}`,
            type: 'uav',
            callsign: uav.callsign,
            rotation: uav.heading || 0,
            iconId: 'svgDrone',
            name: uav.aircraft_model || uav.callsign,
            country: uav.country || '',
            uav_type: uav.uav_type || '',
            alt: uav.alt || 0,
            wiki: uav.wiki || '',
            speed_knots: uav.speed_knots || 0,
            icao24: uav.icao24 || '',
            registration: uav.registration || '',
            squawk: uav.squawk || '',
          },
          geometry: { type: 'Point' as const, coordinates: [uav.lng, uav.lat] },
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}
// ─── Satellites ─────────────────────────────────────────────────────────────

export function buildSatellitesGeoJSON(
  satellites: Satellite[] | undefined,
  inView: InViewFilter,
  interpSat: (s: Satellite) => [number, number],
): FC {
  if (!satellites?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: satellites
      .map((s, i) => {
        if (s.lat == null || s.lng == null) return null;
        const coords = interpSat(s);
        if (!inView(coords[1], coords[0])) return null;
        return {
          type: 'Feature' as const,
          properties: {
            id: s.id || i,
            type: 'satellite',
            name: s.name,
            mission: s.mission || 'general',
            sat_type: s.sat_type || 'Satellite',
            country: s.country || '',
            alt_km: s.alt_km || 0,
            wiki: s.wiki || '',
            color: MISSION_COLORS[s.mission] || '#aaaaaa',
            iconId:
              s.mission === 'space_station' && s.name?.includes('ISS')
                ? 'sat-iss'
                : MISSION_ICON_MAP[s.mission] || 'sat-gen',
            isISS: s.mission === 'space_station' && !!s.name?.includes('ISS'),
          },
          geometry: { type: 'Point' as const, coordinates: coords },
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}

// ─── Ships (non-carrier) ────────────────────────────────────────────────────

export function buildShipsGeoJSON(
  ships: Ship[] | undefined,
  activeLayers: ActiveLayers,
  inView: InViewFilter,
  interpShip: (s: Ship) => [number, number],
): FC {
  if (
    !(
      activeLayers.ships_military ||
      activeLayers.ships_cargo ||
      activeLayers.ships_civilian ||
      activeLayers.ships_passenger ||
      activeLayers.ships_tracked_yachts
    ) ||
    !ships
  )
    return null;
  return {
    type: 'FeatureCollection' as const,
    features: ships
      .map((s, i) => {
        if (s.lat == null || s.lng == null) return null;
        const [iLng, iLat] = interpShip(s);
        if (!inView(iLat, iLng)) return null;
        const isTrackedYacht = !!s.yacht_alert;
        const isMilitary = s.type === 'carrier' || s.type === 'military_vessel';
        const isCargo = s.type === 'tanker' || s.type === 'cargo';
        const isPassenger = s.type === 'passenger';

        if (s.type === 'carrier') return null; // Handled by buildCarriersGeoJSON

        if (isTrackedYacht) {
          if (activeLayers?.ships_tracked_yachts === false) return null;
        } else if (isMilitary && activeLayers?.ships_military === false) return null;
        else if (isCargo && activeLayers?.ships_cargo === false) return null;
        else if (isPassenger && activeLayers?.ships_passenger === false) return null;
        else if (!isMilitary && !isCargo && !isPassenger && activeLayers?.ships_civilian === false)
          return null;

        let iconId = 'svgShipBlue';
        if (isTrackedYacht) iconId = 'svgShipPink';
        else if (isCargo) iconId = 'svgShipRed';
        else if (s.type === 'yacht' || isPassenger) iconId = 'svgShipWhite';
        else if (isMilitary) iconId = 'svgShipAmber';

        return {
          type: 'Feature',
          properties: {
            id: s.mmsi || s.name || `ship-${i}`,
            type: 'ship',
            name: s.name,
            rotation: s.heading || 0,
            iconId,
          },
          geometry: { type: 'Point', coordinates: [iLng, iLat] },
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}

// ─── Carriers ───────────────────────────────────────────────────────────────

// ─── SIGINT GeoJSON ──────────────────────────────────────────────────────────

function buildSigintFeature(sig: SigintSignal): GeoJSON.Feature | null {
  if (sig.lat == null || sig.lng == null) return null;
  return {
    type: 'Feature' as const,
    properties: {
      id: `${sig.source || 'unknown'}:${sig.callsign || 'unknown'}`,
      type: 'sigint',
      name: sig.callsign,
      callsign: sig.callsign,
      source: sig.source,
      confidence: sig.confidence,
      raw_message: sig.raw_message || '',
      snr: sig.snr ?? null,
      frequency: sig.frequency ?? null,
      timestamp: sig.timestamp,
      region: sig.region ?? null,
      channel: sig.channel ?? null,
      status: sig.status ?? null,
      altitude: sig.altitude ?? null,
      emergency: sig.emergency ?? false,
      emergency_keyword: sig.emergency_keyword ?? null,
      // Meshtastic map API fields
      from_api: sig.from_api ?? false,
      position_updated_at: sig.position_updated_at ?? null,
      long_name: sig.long_name ?? null,
      hardware: sig.hardware ?? null,
      role: sig.role ?? null,
      battery_level: sig.battery_level ?? null,
      voltage: sig.voltage ?? null,
    },
    geometry: { type: 'Point' as const, coordinates: [sig.lng, sig.lat] },
  };
}

export function buildSigintGeoJSON(signals: SigintSignal[] | undefined): FC {
  if (!signals?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: signals.map(buildSigintFeature).filter(Boolean) as GeoJSON.Feature[],
  };
}

export function buildMeshtasticGeoJSON(signals: SigintSignal[] | undefined): FC {
  if (!signals?.length) return null;
  const filtered = signals.filter((s) => s.source === 'meshtastic');
  if (!filtered.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: filtered.map(buildSigintFeature).filter(Boolean) as GeoJSON.Feature[],
  };
}

export function buildAprsGeoJSON(signals: SigintSignal[] | undefined): FC {
  if (!signals?.length) return null;
  const filtered = signals.filter((s) => s.source === 'aprs' || s.source === 'js8call');
  if (!filtered.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: filtered.map(buildSigintFeature).filter(Boolean) as GeoJSON.Feature[],
  };
}

export function buildCarriersGeoJSON(ships: Ship[] | undefined): FC {
  if (!ships?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: ships
      .map((s, i) => {
        if (s.type !== 'carrier' || s.lat == null || s.lng == null) return null;
        return {
          type: 'Feature',
          properties: {
            id: s.mmsi || s.name || `carrier-${i}`,
            type: 'ship',
            name: s.name,
            rotation: s.heading || 0,
            iconId: 'svgCarrier',
          },
          geometry: { type: 'Point', coordinates: [s.lng, s.lat] },
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}

// ─── Ukraine Air Raid Alerts ────────────────────────────────────────────────

const ALERT_TYPE_LABELS: Record<string, string> = {
  air_raid: 'AIR RAID',
  artillery_shelling: 'SHELLING',
  urban_fights: 'URBAN COMBAT',
  chemical: 'CHEMICAL',
  nuclear: 'NUCLEAR',
};

export function buildUkraineAlertsGeoJSON(alerts?: UkraineAlert[]): FC {
  if (!alerts?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: alerts.map((a, i) => ({
      type: 'Feature' as const,
      properties: {
        id: a.id || `ua-alert-${i}`,
        type: 'ukraine_alert',
        alert_type: a.alert_type,
        alert_label: ALERT_TYPE_LABELS[a.alert_type] || a.alert_type.toUpperCase(),
        location_title: a.location_title,
        name_en: a.name_en,
        started_at: a.started_at,
        color: a.color,
      },
      geometry: a.geometry,
    })),
  };
}

export function buildUkraineAlertLabelsGeoJSON(alerts?: UkraineAlert[]): FC {
  if (!alerts?.length) return null;
  const features: GeoJSON.Feature[] = [];
  for (let i = 0; i < alerts.length; i++) {
    const a = alerts[i];
    if (!a.geometry) continue;
    const center = polygonCentroid(a.geometry);
    if (!center) continue;
    features.push({
      type: 'Feature',
      properties: {
        id: a.id || `ua-alert-${i}`,
        type: 'ukraine_alert',
        alert_type: a.alert_type,
        alert_label: ALERT_TYPE_LABELS[a.alert_type] || a.alert_type.toUpperCase(),
        name_en: a.name_en,
        color: a.color,
      },
      geometry: { type: 'Point', coordinates: center },
    });
  }
  return features.length ? { type: 'FeatureCollection' as const, features } : null;
}

// ─── Weather Alerts ─────────────────────────────────────────────────────────

const SEVERITY_COLORS: Record<string, string> = {
  Extreme: '#ef4444',
  Severe: '#f97316',
  Moderate: '#eab308',
  Minor: '#3b82f6',
};

export function buildWeatherAlertsGeoJSON(alerts?: WeatherAlert[]): FC {
  if (!alerts?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: alerts.map((a, i) => ({
      type: 'Feature' as const,
      properties: {
        id: a.id || `alert-${i}`,
        type: 'weather_alert',
        event: a.event,
        severity: a.severity,
        headline: a.headline,
        description: a.description,
        expires: a.expires,
        color: SEVERITY_COLORS[a.severity] || '#3b82f6',
      },
      geometry: a.geometry,
    })),
  };
}

/** Compute a rough centroid from a polygon/multipolygon geometry. */
function polygonCentroid(geom: GeoJSON.Geometry): [number, number] | null {
  let coords: number[][] = [];
  if (geom.type === 'Polygon') {
    coords = geom.coordinates[0];
  } else if (geom.type === 'MultiPolygon') {
    // Use the largest ring (first polygon, outer ring)
    coords = geom.coordinates[0]?.[0] ?? [];
  }
  if (!coords.length) return null;
  let sumLng = 0, sumLat = 0;
  for (const c of coords) { sumLng += c[0]; sumLat += c[1]; }
  return [sumLng / coords.length, sumLat / coords.length];
}

/** Build point features at each weather alert polygon centroid for icon + label overlay. */
export function buildWeatherAlertLabelsGeoJSON(alerts?: WeatherAlert[]): FC {
  if (!alerts?.length) return null;
  const features: GeoJSON.Feature[] = [];
  for (let i = 0; i < alerts.length; i++) {
    const a = alerts[i];
    if (!a.geometry) continue;
    const center = polygonCentroid(a.geometry);
    if (!center) continue;
    features.push({
      type: 'Feature',
      properties: {
        id: a.id || `alert-${i}`,
        type: 'weather_alert',
        event: a.event,
        severity: a.severity,
        headline: a.headline,
        iconId: weatherIconId(a.event),
        color: SEVERITY_COLORS[a.severity] || '#3b82f6',
      },
      geometry: { type: 'Point', coordinates: center },
    });
  }
  return features.length ? { type: 'FeatureCollection' as const, features } : null;
}

// ─── Air Quality ────────────────────────────────────────────────────────────

function aqiColor(aqi: number): string {
  if (aqi <= 50) return '#22c55e';
  if (aqi <= 100) return '#eab308';
  if (aqi <= 150) return '#f97316';
  if (aqi <= 200) return '#ef4444';
  if (aqi <= 300) return '#a855f7';
  return '#7f1d1d';
}

function aqiLabel(aqi: number): string {
  if (aqi <= 50) return 'Good';
  if (aqi <= 100) return 'Moderate';
  if (aqi <= 150) return 'Unhealthy (Sensitive)';
  if (aqi <= 200) return 'Unhealthy';
  if (aqi <= 300) return 'Very Unhealthy';
  return 'Hazardous';
}

export function buildAirQualityGeoJSON(stations?: AirQualityStation[]): FC {
  if (!stations?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: stations.map((s, i) => ({
      type: 'Feature' as const,
      properties: {
        id: `aq-${s.id || i}`,
        type: 'air_quality',
        name: s.name,
        pm25: s.pm25,
        aqi: s.aqi,
        aqiLabel: aqiLabel(s.aqi),
        country: s.country,
        color: aqiColor(s.aqi),
      },
      geometry: { type: 'Point' as const, coordinates: [s.lng, s.lat] },
    })),
  };
}

// ─── Volcanoes ──────────────────────────────────────────────────────────────

export function buildVolcanoesGeoJSON(volcanoes?: Volcano[]): FC {
  if (!volcanoes?.length) return null;
  const now = new Date().getFullYear();
  return {
    type: 'FeatureCollection' as const,
    features: volcanoes.map((v, i) => {
      const yearsAgo = v.last_eruption_year ? now - v.last_eruption_year : 99999;
      const iconId =
        yearsAgo <= 50
          ? 'volcano-active'
          : yearsAgo <= 500
            ? 'volcano-historical'
            : 'volcano-dormant';
      return {
        type: 'Feature' as const,
        properties: {
          id: `volcano-${i}`,
          type: 'volcano',
          name: v.name,
          vtype: v.type,
          country: v.country,
          region: v.region,
          elevation: v.elevation,
          last_eruption_year: v.last_eruption_year,
          iconId,
        },
        geometry: { type: 'Point' as const, coordinates: [v.lng, v.lat] },
      };
    }),
  };
}

// ─── Fishing Activity ───────────────────────────────────────────────────────

export function buildFishingActivityGeoJSON(events?: FishingEvent[]): FC {
  if (!events?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: events.map((e, i) => ({
      type: 'Feature' as const,
      properties: {
        id: e.id || `fish-${i}`,
        type: 'fishing_event',
        vessel_name: e.vessel_name,
        vessel_flag: e.vessel_flag,
        event_type: e.type,
        start: e.start,
        end: e.end,
        duration_hrs: e.duration_hrs,
      },
      geometry: { type: 'Point' as const, coordinates: [e.lng, e.lat] },
    })),
  };
}

// ─── Trains ────────────────────────────────────────────────────────────────

export function buildTrainsGeoJSON(trains: Train[] | undefined, inView?: InViewFilter): FC {
  if (!trains?.length) return null;
  return {
    type: 'FeatureCollection' as const,
    features: trains
      .map((t, i) => {
        if (t.lat == null || t.lng == null) return null;
        if (inView && !inView(t.lat, t.lng)) return null;
        const iconId =
          t.source === 'amtrak'
            ? 'train-amtrak'
            : t.country === 'FI' || t.telemetry_quality === 'official'
              ? 'train-fin'
              : 'train-amtrak';
        return {
          type: 'Feature' as const,
          properties: {
            id: t.id || `train-${i}`,
            type: 'train',
            name: t.name,
            number: t.number,
            source: t.source,
            source_label: t.source_label,
            operator: t.operator,
            country: t.country,
            speed_kmh: t.speed_kmh,
            status: t.status,
            route: t.route,
            iconId,
          },
          geometry: { type: 'Point' as const, coordinates: [t.lng, t.lat] },
        };
      })
      .filter(Boolean) as GeoJSON.Feature[],
  };
}

// ─── ISS Footprint ─────────────────────────────────────────────────────────

const R_EARTH = 6371; // km

/** Generate a GeoJSON polygon circle (great-circle approximation). */
function geoCircle(centerLng: number, centerLat: number, radiusKm: number, steps = 64): GeoJSON.Feature {
  const coords: [number, number][] = [];
  const angularRadius = radiusKm / R_EARTH; // radians
  const lat1 = (centerLat * Math.PI) / 180;
  const lng1 = (centerLng * Math.PI) / 180;

  for (let i = 0; i <= steps; i++) {
    const bearing = (2 * Math.PI * i) / steps;
    const lat2 = Math.asin(
      Math.sin(lat1) * Math.cos(angularRadius) +
        Math.cos(lat1) * Math.sin(angularRadius) * Math.cos(bearing),
    );
    const lng2 =
      lng1 +
      Math.atan2(
        Math.sin(bearing) * Math.sin(angularRadius) * Math.cos(lat1),
        Math.cos(angularRadius) - Math.sin(lat1) * Math.sin(lat2),
      );
    coords.push([(lng2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }

  return {
    type: 'Feature',
    properties: { type: 'iss_footprint' },
    geometry: { type: 'Polygon', coordinates: [coords] },
  };
}

export function buildISSFootprintGeoJSON(
  satellites: Satellite[] | undefined,
  interpSat: (s: Satellite) => [number, number],
): FC {
  if (!satellites?.length) return null;
  const iss = satellites.find((s) => s.mission === 'space_station' && s.name?.includes('ISS'));
  if (!iss) return null;

  const [lng, lat] = interpSat(iss);
  const alt = iss.alt_km || 420;
  // Line-of-sight footprint radius: R * arccos(R / (R + h))
  const footprintKm = R_EARTH * Math.acos(R_EARTH / (R_EARTH + alt));

  return {
    type: 'FeatureCollection' as const,
    features: [geoCircle(lng, lat, footprintKm)],
  };
}
