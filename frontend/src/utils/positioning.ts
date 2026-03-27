// --- Smooth position interpolation helpers ---
// Given heading (degrees) and speed (knots), compute new lat/lng after dt seconds
export function interpolatePosition(
  lat: number,
  lng: number,
  headingDeg: number,
  speedKnots: number,
  dtSeconds: number,
  maxDist = 0,
  maxDt = 65,
): [number, number] {
  if (!speedKnots || speedKnots <= 0 || dtSeconds <= 0) return [lat, lng];
  // Cap interpolation time to prevent runaway drift when data is stale
  const clampedDt = Math.min(dtSeconds, maxDt);
  // 1 knot = 1 nautical mile/hour = 1852 m/h
  const speedMps = speedKnots * 0.5144; // meters per second
  const dist = maxDist > 0 ? Math.min(speedMps * clampedDt, maxDist) : speedMps * clampedDt;
  const R = 6371000; // Earth radius in meters
  const headingRad = (headingDeg * Math.PI) / 180;
  const latRad = (lat * Math.PI) / 180;
  const lngRad = (lng * Math.PI) / 180;
  const newLatRad = Math.asin(
    Math.sin(latRad) * Math.cos(dist / R) +
      Math.cos(latRad) * Math.sin(dist / R) * Math.cos(headingRad),
  );
  const newLngRad =
    lngRad +
    Math.atan2(
      Math.sin(headingRad) * Math.sin(dist / R) * Math.cos(latRad),
      Math.cos(dist / R) - Math.sin(latRad) * Math.sin(newLatRad),
    );
  return [(newLatRad * 180) / Math.PI, (newLngRad * 180) / Math.PI];
}

// Project a point at a given bearing and distance (meters) using great-circle math
export function projectPoint(
  lat: number,
  lng: number,
  bearingDeg: number,
  distMeters: number,
): [number, number] {
  const R = 6371000;
  const bearingRad = (bearingDeg * Math.PI) / 180;
  const latRad = (lat * Math.PI) / 180;
  const lngRad = (lng * Math.PI) / 180;
  const newLatRad = Math.asin(
    Math.sin(latRad) * Math.cos(distMeters / R) +
      Math.cos(latRad) * Math.sin(distMeters / R) * Math.cos(bearingRad),
  );
  const newLngRad =
    lngRad +
    Math.atan2(
      Math.sin(bearingRad) * Math.sin(distMeters / R) * Math.cos(latRad),
      Math.cos(distMeters / R) - Math.sin(latRad) * Math.sin(newLatRad),
    );
  return [(newLatRad * 180) / Math.PI, (newLngRad * 180) / Math.PI];
}
