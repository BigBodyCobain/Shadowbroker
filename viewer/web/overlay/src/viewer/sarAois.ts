/**
 * Radar (SAR) watch areas for the public viewer.
 *
 * The full app asks its own server for the watch-area list. The viewer has
 * no server, so it reads the areas from the published coverage list, which
 * carries each area's name, centre and radius.
 *
 * No imports, so the rule can be tested without a browser.
 */

export type ViewerSarAoi = {
  id: string;
  name: string;
  description?: string;
  center: [number, number]; // [lat, lon]
  radius_km: number;
  polygon?: number[][] | null;
  category: string;
};

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** Turn the published coverage rows into watch areas. Rows without a usable centre are skipped. */
export function viewerSarAois(coverage: unknown): ViewerSarAoi[] {
  if (!Array.isArray(coverage)) return [];
  const areas: ViewerSarAoi[] = [];
  const seen = new Set<string>();
  for (const row of coverage) {
    if (!row || typeof row !== 'object') continue;
    const r = row as Record<string, unknown>;
    const id = typeof r.aoi_id === 'string' ? r.aoi_id : '';
    const lat = finite(r.center_lat);
    const lon = finite(r.center_lon);
    if (!id || seen.has(id) || lat === null || lon === null) continue;
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) continue;
    seen.add(id);
    const radius = finite(r.radius_km);
    areas.push({
      id,
      name: typeof r.aoi_name === 'string' && r.aoi_name ? r.aoi_name : id,
      center: [lat, lon],
      radius_km: radius !== null && radius > 0 ? Math.min(radius, 500) : 25,
      polygon: null,
      category: typeof r.category === 'string' && r.category ? r.category : 'watchlist',
    });
  }
  return areas;
}
