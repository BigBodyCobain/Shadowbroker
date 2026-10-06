/**
 * ShadowBroker's zero-config basemap uses OpenFreeMap vector styles.
 * Operators who configure CARTO_API_KEY keep the existing CARTO raster
 * basemap path. This avoids CARTO's unkeyed "API KEY REQUIRED" watermark
 * without taking the configured provider away from existing installs.
 */

export type BasemapTheme = 'dark' | 'light';

export const OPENFREEMAP_STYLE_URLS: Record<BasemapTheme, string> = {
  dark: 'https://tiles.openfreemap.org/styles/dark',
  light: 'https://tiles.openfreemap.org/styles/positron',
};

const CARTO_SUBDOMAINS = ['a', 'b', 'c', 'd'] as const;
const CARTO_RASTER_STYLE: Record<BasemapTheme, string> = {
  dark: 'dark_all',
  light: 'light_all',
};

export const OSM_ATTRIBUTION_HTML =
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>';
export const CARTO_ATTRIBUTION_HTML =
  '<a href="https://carto.com/attribution" target="_blank" rel="noopener">CARTO</a>';
export const OPENFREEMAP_ATTRIBUTION_HTML =
  '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> · <a href="https://openmaptiles.org" target="_blank" rel="noopener">OpenMapTiles</a>';

/** Tile URL templates for the optional CARTO raster style. */
export function cartoTileUrls(theme: BasemapTheme, cartoApiKey: string): string[] {
  const style = CARTO_RASTER_STYLE[theme];
  const key = cartoApiKey.trim();
  return CARTO_SUBDOMAINS.map(
    (s) =>
      `https://${s}.basemaps.cartocdn.com/rastertiles/${style}/{z}/{x}/{y}@2x.png?key=${encodeURIComponent(key)}`,
  );
}

/**
 * Use OpenFreeMap by default. CARTO is retained as an opt-in compatibility
 * path when an operator has already configured CARTO_API_KEY.
 */
export function buildBasemapStyle(theme: BasemapTheme, cartoApiKey?: string | null) {
  const key = (cartoApiKey || '').trim();
  if (!key) return OPENFREEMAP_STYLE_URLS[theme];

  const sourceId = `carto-${theme}`;
  return {
    version: 8,
    sources: {
      [sourceId]: {
        type: 'raster',
        tiles: cartoTileUrls(theme, key),
        tileSize: 256,
        attribution: `${OSM_ATTRIBUTION_HTML} ${CARTO_ATTRIBUTION_HTML}`,
      },
    },
    layers: [{ id: `${sourceId}-layer`, type: 'raster', source: sourceId, minzoom: 0, maxzoom: 22 }],
  };
}

export const darkStyle = buildBasemapStyle('dark');
export const lightStyle = buildBasemapStyle('light');
