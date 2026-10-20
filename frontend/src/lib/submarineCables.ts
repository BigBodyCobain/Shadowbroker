/** Synthetic TeleGeography corridor overlays — not real cable routes. */
const SYNTHETIC_CABLE_NAMES = new Set([
  'SEA-ME-WE Corridor',
  'Trans-Atlantic North',
  'Trans-Atlantic South',
  'WACS / SAT-3 Corridor',
  'EASSy / SEACOM',
  'East Asia Corridor',
  'Asia-Australia',
  'Trans-Pacific',
  'South Atlantic',
]);

type LngLat = [number, number];

function lonJumpDegrees(a: LngLat, b: LngLat): number {
  const d = Math.abs(b[0] - a[0]);
  return Math.min(d, 360 - d);
}

function iterParts(geometry: GeoJSON.Geometry): LngLat[][] {
  if (geometry.type === 'LineString') {
    return [geometry.coordinates as LngLat[]];
  }
  if (geometry.type === 'MultiLineString') {
    return geometry.coordinates as LngLat[][];
  }
  return [];
}

/** Split a path when consecutive vertices jump across continents / dateline. */
function splitAtJumps(coords: LngLat[], maxJumpDeg = 90): LngLat[][] {
  if (coords.length < 2) return coords.length ? [coords] : [];

  const segments: LngLat[][] = [[coords[0]]];
  for (let i = 1; i < coords.length; i += 1) {
    const prev = segments[segments.length - 1][segments[segments.length - 1].length - 1];
    const next = coords[i];
    if (lonJumpDegrees(prev, next) > maxJumpDeg) {
      segments.push([next]);
    } else {
      segments[segments.length - 1].push(next);
    }
  }
  return segments.filter((seg) => seg.length >= 2);
}

function partsToGeometry(parts: LngLat[][]): GeoJSON.LineString | GeoJSON.MultiLineString | null {
  if (!parts.length) return null;
  if (parts.length === 1) {
    return { type: 'LineString', coordinates: parts[0] };
  }
  return { type: 'MultiLineString', coordinates: parts };
}

/**
 * Drop synthetic corridor junk and split lines that cut across the dateline.
 * Land-crossing segments are stripped at build time (see scripts/sanitize_submarine_cables.py).
 */
export function sanitizeSubmarineCables(
  collection: GeoJSON.FeatureCollection,
): GeoJSON.FeatureCollection {
  const byName = new Map<string, GeoJSON.Feature>();

  for (const feature of collection.features) {
    const name = String(feature.properties?.name || '').trim();
    if (!name || SYNTHETIC_CABLE_NAMES.has(name)) continue;
    if (!feature.geometry || feature.geometry.type === 'GeometryCollection') continue;

    const splitParts: LngLat[][] = [];
    for (const part of iterParts(feature.geometry)) {
      splitParts.push(...splitAtJumps(part));
    }
    const geometry = partsToGeometry(splitParts);
    if (!geometry) continue;

    const cleaned: GeoJSON.Feature = {
      type: 'Feature',
      properties: feature.properties ?? {},
      geometry,
    };

    const existing = byName.get(name);
    if (!existing) {
      byName.set(name, cleaned);
      continue;
    }
    const existingPts = iterParts(existing.geometry!).flat().length;
    const newPts = splitParts.flat().length;
    if (newPts > existingPts) byName.set(name, cleaned);
  }

  return {
    type: 'FeatureCollection',
    features: Array.from(byName.values()),
  };
}
