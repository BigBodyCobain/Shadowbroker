export type ViewBounds = {
  south: number;
  west: number;
  north: number;
  east: number;
};

const EARTH_RADIUS_MILES = 3958.7613;
const RAD_TO_DEG = 180 / Math.PI;
const DEG_TO_RAD = Math.PI / 180;
export const DEFAULT_PRELOAD_RADIUS_MILES = 3000;

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function normalizeLongitude(value: number): number {
  if (!Number.isFinite(value)) return 0;
  let normalized = ((value + 180) % 360 + 360) % 360 - 180;
  if (normalized === -180 && value > 0) normalized = 180;
  return normalized;
}

export function normalizeViewBounds(bounds: ViewBounds): ViewBounds {
  const south = clamp(bounds.south, -90, 90);
  const north = clamp(bounds.north, -90, 90);
  const rawWidth = Math.abs(bounds.east - bounds.west);
  if (!Number.isFinite(rawWidth) || rawWidth >= 360) {
    return { south, west: -180, north, east: 180 };
  }
  const west = normalizeLongitude(bounds.west);
  const east = normalizeLongitude(bounds.east);
  if (east < west) {
    return { south, west: -180, north, east: 180 };
  }
  return { south, west, north, east };
}

export function expandBoundsToRadius(
  bounds: ViewBounds,
  radiusMiles: number = DEFAULT_PRELOAD_RADIUS_MILES,
): ViewBounds {
  const normalized = normalizeViewBounds(bounds);
  if (!Number.isFinite(radiusMiles) || radiusMiles <= 0) return normalized;
  if (normalized.west === -180 && normalized.east === 180) return normalized;

  const centerLat = (normalized.south + normalized.north) / 2;
  const centerLng = (normalized.west + normalized.east) / 2;
  const angularDistance = radiusMiles / EARTH_RADIUS_MILES;
  const latDelta = angularDistance * RAD_TO_DEG;
  const centerLatRad = centerLat * DEG_TO_RAD;
  const cosLat = Math.cos(centerLatRad);

  let lngDelta = 180;
  if (cosLat > 1e-6) {
    const ratio = Math.sin(angularDistance) / cosLat;
    lngDelta = Math.min(180, Math.asin(Math.min(1, Math.max(-1, ratio))) * RAD_TO_DEG);
  }

  const south = clamp(Math.min(normalized.south, centerLat - latDelta), -90, 90);
  const north = clamp(Math.max(normalized.north, centerLat + latDelta), -90, 90);

  const radiusWest = centerLng - lngDelta;
  const radiusEast = centerLng + lngDelta;
  if (radiusWest < -180 || radiusEast > 180) {
    return { south, west: -180, north, east: 180 };
  }

  return normalizeViewBounds({
    south,
    west: Math.min(normalized.west, radiusWest),
    north,
    east: Math.max(normalized.east, radiusEast),
  });
}

function quantizationStep(bounds: ViewBounds): number {
  const latSpan = Math.abs(bounds.north - bounds.south);
  const lngSpan = Math.abs(bounds.east - bounds.west);
  const span = Math.max(latSpan, lngSpan);
  if (!Number.isFinite(span) || span >= 180) return 5;
  if (span >= 80) return 2;
  if (span >= 20) return 1;
  if (span >= 8) return 0.25;
  if (span >= 3) return 0.1;
  return 0.05;
}

function decimalsForStep(step: number): number {
  if (step >= 1) return 0;
  if (step >= 0.25) return 2;
  return 2;
}

function floorToStep(value: number, step: number): number {
  return Math.floor(value / step) * step;
}

function ceilToStep(value: number, step: number): number {
  return Math.ceil(value / step) * step;
}

function outwardRound(bounds: ViewBounds, step: number): ViewBounds {
  const digits = decimalsForStep(step);
  const south = Number(clamp(floorToStep(bounds.south, step), -90, 90).toFixed(digits));
  const west = Number(clamp(floorToStep(bounds.west, step), -180, 180).toFixed(digits));
  const north = Number(clamp(ceilToStep(bounds.north, step), -90, 90).toFixed(digits));
  const east = Number(clamp(ceilToStep(bounds.east, step), -180, 180).toFixed(digits));
  if (east - west >= 360) {
    return { south, west: -180, north, east: 180 };
  }
  return { south, west, north, east };
}

export function coarsenViewBounds(bounds: ViewBounds): ViewBounds {
  const normalized = normalizeViewBounds(bounds);
  if (normalized.west === -180 && normalized.east === 180) {
    return normalized;
  }
  return outwardRound(normalized, quantizationStep(normalized));
}

export function buildBoundsQuery(bounds: ViewBounds | null | undefined): string {
  if (!bounds) return '';
  const coarse = coarsenViewBounds(bounds);
  const step = quantizationStep(coarse);
  const digits = decimalsForStep(step);
  return `?s=${coarse.south.toFixed(digits)}&w=${coarse.west.toFixed(digits)}&n=${coarse.north.toFixed(digits)}&e=${coarse.east.toFixed(digits)}`;
}
