/**
 * Solar Terminator — computes the day/night boundary polygon for real-time rendering.
 *
 * Uses simplified astronomical formulas to compute the subsolar point,
 * then generates a GeoJSON polygon covering the nighttime hemisphere.
 *
 * Performance: pure math, no API calls, ~0.1ms per computation.
 * The polygon has 360 vertices (one per degree of longitude) — trivial for MapLibre.
 */

const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

/**
 * Compute the Sun's declination and equation of time for a given JS Date.
 * Returns: { declination (radians), eqTime (minutes) }
 */
function solarPosition(date: Date) {
  const start = new Date(date.getFullYear(), 0, 0);
  const diff = date.getTime() - start.getTime();
  const oneDay = 1000 * 60 * 60 * 24;
  const dayOfYear = Math.floor(diff / oneDay);
  const hour = date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600;

  // Fractional year in radians
  const gamma = ((2 * Math.PI) / 365) * (dayOfYear - 1 + (hour - 12) / 24);

  // Equation of time (minutes)
  const eqTime =
    229.18 *
    (0.000075 +
      0.001868 * Math.cos(gamma) -
      0.032077 * Math.sin(gamma) -
      0.014615 * Math.cos(2 * gamma) -
      0.040849 * Math.sin(2 * gamma));

  // Solar declination (radians)
  const declination =
    0.006918 -
    0.399912 * Math.cos(gamma) +
    0.070257 * Math.sin(gamma) -
    0.006758 * Math.cos(2 * gamma) +
    0.000907 * Math.sin(2 * gamma) -
    0.002697 * Math.cos(3 * gamma) +
    0.00148 * Math.sin(3 * gamma);

  return { declination, eqTime };
}

/**
 * For a given longitude, compute the latitude of the terminator line.
 * Returns the latitude (in degrees) where the sun angle = 0.
 */
function terminatorLatitude(lng: number, declination: number, subsolarLng: number): number {
  // Hour angle at this longitude
  const ha = (lng - subsolarLng) * DEG;
  // Terminator: cos(zenith) = 0 => sin(lat)*sin(dec) + cos(lat)*cos(dec)*cos(ha) = 0
  // => tan(lat) = -cos(ha) * cos(dec) / sin(dec)
  // => lat = atan(-cos(ha) / tan(dec))

  const tanDec = Math.tan(declination);
  if (Math.abs(tanDec) < 1e-10) {
    // Near equinox, terminator is roughly at ±90° adjusted
    return -Math.acos(0) * RAD; // fallback
  }
  const lat = Math.atan(-Math.cos(ha) / tanDec) * RAD;
  return lat;
}

/**
 * Generate a GeoJSON FeatureCollection containing the nighttime polygon.
 * Updated every call with the current date.
 */
export function computeNightPolygon(date: Date = new Date()): GeoJSON.FeatureCollection {
  const { declination, eqTime } = solarPosition(date);

  // Subsolar longitude: where the sun is directly overhead
  const hour = date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600;
  const subsolarLng = -(hour - 12) * 15 - eqTime / 4; // degrees

  // Generate terminator line points (one per degree of longitude)
  const terminatorPoints: [number, number][] = [];
  for (let lng = -180; lng <= 180; lng += 1) {
    const lat = terminatorLatitude(lng, declination, subsolarLng);
    // Clamp latitude to valid range
    terminatorPoints.push([lng, Math.max(-85, Math.min(85, lat))]);
  }

  // Determine which side is night: if declination > 0 (northern summer),
  // the night polygon is on the south side of the terminator, and vice versa.
  // More precisely: at lng=subsolarLng, the sun is overhead, so the opposite side is night.
  // We check: is the subsolar point on the +lat or -lat side of the terminator at that lng?

  // The subsolar latitude
  const subsolarLat = declination * RAD;
  // The terminator latitude at the subsolar longitude
  const termLatAtSubsolar = terminatorLatitude(subsolarLng, declination, subsolarLng);

  // If subsolar lat > terminator lat at that point, night is on the south (below terminator)
  const nightIsSouth = subsolarLat > termLatAtSubsolar;

  // Build the night polygon
  // South side: terminator -> bottom edge (-85) -> close
  // North side: terminator -> top edge (85) -> close
  const nightCoords: [number, number][] = [];

  if (nightIsSouth) {
    // Night is below the terminator line
    // Go left-to-right along the terminator, then close along the bottom
    for (const pt of terminatorPoints) nightCoords.push(pt);
    nightCoords.push([180, -85]);
    nightCoords.push([-180, -85]);
  } else {
    // Night is above the terminator line
    for (const pt of terminatorPoints) nightCoords.push(pt);
    nightCoords.push([180, 85]);
    nightCoords.push([-180, 85]);
  }

  // Close the ring
  nightCoords.push(nightCoords[0]);

  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Polygon',
          coordinates: [nightCoords],
        },
      },
    ],
  };
}
