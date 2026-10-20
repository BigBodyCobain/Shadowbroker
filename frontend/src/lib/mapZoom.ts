/**
 * Sizing the LOCATE camera.
 *
 * Everything here produces a bounding box rather than a zoom number, so the
 * caller can hand it to map.cameraForBounds(). That matters: in Web Mercator
 * the cos(lat) shrinkage of a longitude degree is exactly cancelled by the
 * projection's horizontal stretch, so only the latitude axis needs the term.
 * Hand-rolled compensation usually corrects the wrong one. cameraForBounds
 * gets both axes and the viewport aspect ratio right for free.
 */

/** [west, south, east, north] - the order MapLibre's LngLatBoundsLike takes. */
export type Bounds = [number, number, number, number];

export const ZOOM_MIN = 2;
/** ~0.6 m/px. Deeper than this, every tile source is upscaled blur. */
export const ZOOM_MAX = 17;
/** OSM.org's own default for a bare coordinate: "somewhere around here". */
export const ZOOM_FALLBACK = 11;

const KM_PER_DEGREE = 111.32;

/**
 * A bbox axis is judged "smeared by an outlier" when the result's own
 * coordinate sits outside the middle 80% of it. Nominatim's lat/lon is the
 * representative point of the main body, so a box that genuinely describes
 * that body brackets it; a box stretched to a remote island does not.
 *
 * This catches the severe cases (Tokyo's box is 70x longer on the far side of
 * the city than the near side) and deliberately lets mild ones through.
 * Australia keeps a box widened by Heard Island, 4000km to the south-west,
 * because its centroid is still only 15% off-centre — no threshold separates
 * that from Brazil or Japan, which are similarly off-centre and honest. The
 * country still lands on screen whole, just not centred. That is also what
 * openstreetmap.org does with the same bounding box.
 */
const CENTRE_MARGIN = 0.1;

/**
 * Only axes longer than this are worth judging. Below it, a lopsided box is
 * territorial-water padding rather than an outlying territory, and the error
 * is too small to see. Monaco's country box is 26km of mostly sea with the
 * point on its northern edge; framing that is harmless.
 */
const CENTRE_TEST_MIN_KM = 100;

/**
 * No country's true north-south extent reaches this. Canada, the largest,
 * spans 41.7N to 83.3N (~4630km). A latitude span beyond the cap is therefore
 * an overseas territory dragging the box, not the country.
 */
const MAX_COUNTRY_EXTENT_KM = 5000;

export const clampZoom = (z: number): number =>
  Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));

const COORD_RE = /^([+-]?\d+(?:\.(\d*))?)[,\s]+([+-]?\d+(?:\.(\d*))?)$/;

/**
 * Parse "31.8, 34.8" / "-12.3 45.6", reporting how precisely it was typed.
 * Decimals are counted from the raw string because 78 and 78.00 parse to the
 * same float but make different claims about precision.
 */
export function parseCoordinateInput(
  raw: string,
): { lat: number; lng: number; decimals: number } | null {
  const m = raw.trim().match(COORD_RE);
  if (!m) return null;
  const lat = parseFloat(m[1]);
  const lng = parseFloat(m[3]);
  if (!(lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180)) return null;
  // The less precise axis wins: one sloppy field must not drive the framing.
  const decimals = Math.min((m[2] ?? '').length, (m[4] ?? '').length);
  return { lat, lng, decimals };
}

/** The uncertainty cell implied by `decimals` places of decimal degrees. */
export function boundsForCoordinate(
  lat: number,
  lng: number,
  decimals: number,
): Bounds {
  const half = 0.5 * Math.pow(10, -decimals);
  return [
    lng - half,
    Math.max(-90, lat - half),
    lng + half,
    Math.min(90, lat + half),
  ];
}

/**
 * Is `value` bracketed by [lo, hi] rather than sitting out at one end?
 * Short axes always pass: see CENTRE_TEST_MIN_KM.
 */
function axisBracketsPoint(lo: number, hi: number, value: number): boolean {
  const span = hi - lo;
  if (span * KM_PER_DEGREE < CENTRE_TEST_MIN_KM) return true;
  const position = (value - lo) / span;
  return position >= CENTRE_MARGIN && position <= 1 - CENTRE_MARGIN;
}

/**
 * Convert a Nominatim boundingbox to Bounds, discarding or repairing the ones
 * that would frame the wrong thing. Every rule below is a real query.
 *
 * `lat`/`lng` are the result's own coordinate. They do the heavy lifting: a
 * bounding box is trustworthy when it brackets its own representative point,
 * and suspect when that point sits at one edge. Sizing rules cannot do this
 * job — the extent Nominatim's place_rank implies is an administrative level,
 * not a size, and countries at rank 4 run from Monaco (2km) to Canada
 * (4600km). Capping on a multiple of the rank extent throws away the honest
 * boxes of every large country and state.
 */
export function sanitizeGeocodeBbox(
  bbox: unknown,
  lat: number,
  lng: number,
): Bounds | null {
  if (!Array.isArray(bbox) || bbox.length !== 4) return null;
  // Nominatim order is [min_lat, max_lat, min_lon, max_lon], as strings.
  const [south, north, west, east] = bbox.map(Number);
  if (![south, north, west, east].every(Number.isFinite)) return null;
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;

  const latSpan = north - south;
  const lonSpan = east - west;
  if (latSpan < 0 || lonSpan < 0) return null;

  // Russia, the United States, Fiji, New Zealand: a box crossing the
  // antimeridian comes back as -180..180, which MapLibre's
  // adjustAntiMeridian() reads as a legitimate whole-world box. Longitude is
  // unrecoverable, but latitude usually survives, so rebuild a square-ish box
  // from that rather than throwing the whole result away.
  if (lonSpan >= 359) return boundsFromLatitudeSpan(lat, lng, south, north);
  // France: mainland plus Kerguelen and French Polynesia, 350 deg wide but
  // never quite touching +/-180, so the dateline rule above misses it.
  // Nothing real spans more than a hemisphere of longitude.
  if (lonSpan > 180) return null;

  // Tokyo: the prefecture's box reaches 1800km south to the Ogasawara
  // Islands, leaving the city itself 1.4% from the box's northern edge. The
  // box is 15.7 x 18.4 deg — roughly square, so an aspect-ratio test misses
  // it, and it is only 5x the extent its rank claims, so a size cap loose
  // enough to admit Texas misses it too.
  if (!axisBracketsPoint(south, north, lat)) return null;
  if (!axisBracketsPoint(west, east, lng)) return null;

  // Everest: an OSM node, padded to +/-0.00005 deg. Never zero-area, so a
  // degenerate-bounds guard would not catch it - and fitBounds on a box that
  // small silently flies to the map's maxZoom.
  if (Math.max(latSpan, lonSpan) < 0.0002) return null;

  return [west, south, east, north];
}

/**
 * Rebuild bounds for a result whose longitude axis was destroyed by the
 * antimeridian, using the latitude axis it kept. There is no information left
 * about how wide the place is, so the box is made square about the result's
 * own longitude — the neutral choice, and one that lands the camera on the
 * populated middle of Russia rather than on empty Arctic.
 */
function boundsFromLatitudeSpan(
  lat: number,
  lng: number,
  south: number,
  north: number,
): Bounds | null {
  const latSpan = north - south;
  if (!(latSpan > 0)) return null;
  // Territories smear latitude too, so the point still has to be bracketed.
  if (!axisBracketsPoint(south, north, lat)) return null;

  const extentKm = latSpan * KM_PER_DEGREE;
  if (extentKm > MAX_COUNTRY_EXTENT_KM) {
    // The United States: American Samoa at 14S and Point Barrow at 71N give
    // 9600km of latitude for a 4500km country, and the midpoint of that lands
    // in the Caribbean. Neither endpoint is usable, so fall back to a capped
    // box around the result's own coordinate.
    return boundsAround(lat, lng, MAX_COUNTRY_EXTENT_KM);
  }

  // Russia: 41N to 82N is the real extent of the country and belongs on the
  // camera as-is. Deriving latitude from the result's point instead would
  // push the box past 85N, where Mercator's stretch alone forces the zoom
  // down to the floor.
  const halfLng =
    latSpan / 2 / Math.max(Math.cos(((south + north) / 2) * (Math.PI / 180)), 0.01);
  return [lng - halfLng, south, lng + halfLng, north];
}

/**
 * Nominatim's own extent estimate per search rank, in km. Ranks 13-25 are
 * documented; 4-12 are our estimates, since the docs give no figure there.
 * Keyed off place_rank rather than class/type/admin_level because Nominatim
 * has already normalized admin levels across countries (German admin_level 5
 * is rank 10, Swedish admin_level 4 is rank 12).
 */
const RANK_EXTENT_KM: ReadonlyArray<readonly [number, number]> = [
  [3, 5000],
  [4, 1000],
  [8, 250],
  [12, 60],
  [16, 15],
  [18, 4],
  [19, 2],
  [20, 1],
  [25, 0.5],
  [27, 0.3],
  [30, 0.1],
];

/** Used when Nominatim gave no rank at all, e.g. the local_only fallback. */
const UNKNOWN_RANK = 15;

function extentKmForRank(placeRank?: number): number {
  const rank = typeof placeRank === 'number' ? placeRank : UNKNOWN_RANK;
  for (const [maxRank, km] of RANK_EXTENT_KM) {
    if (rank <= maxRank) return km;
  }
  return RANK_EXTENT_KM[RANK_EXTENT_KM.length - 1][1];
}

/** A roughly square box `extentKm` across, centred on (lat, lng). */
function boundsAround(lat: number, lng: number, extentKm: number): Bounds {
  const halfLat = extentKm / 2 / KM_PER_DEGREE;
  // Synthesizing a geographic box, not a pixel measurement, so the cos term
  // genuinely applies here. Floored to keep the poles finite.
  const cos = Math.max(Math.cos((lat * Math.PI) / 180), 0.01);
  const halfLng = halfLat / cos;
  return [
    lng - halfLng,
    Math.max(-90, lat - halfLat),
    lng + halfLng,
    Math.min(90, lat + halfLat),
  ];
}

/**
 * A box of the rank's typical extent, centred on the result. The last resort,
 * for results whose bounding box was unusable and for the local_only path,
 * which carries no extent data at all.
 */
export function boundsForPlaceRank(
  lat: number,
  lng: number,
  placeRank?: number,
): Bounds {
  return boundsAround(lat, lng, extentKmForRank(placeRank));
}
