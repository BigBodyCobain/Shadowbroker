import type { Map as MaplibreMap, StyleSpecification } from 'maplibre-gl';

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
export function buildBasemapStyle(
  theme: BasemapTheme,
  cartoApiKey?: string | null,
): string | StyleSpecification {
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

/**
 * Basemap palette matching the ShadowBroker website (navy land, near-black sea, faint cyan
 * borders). Sensor modes are applied on top as canvas filters in globals.css.
 * Only touches layers that exist, so CARTO raster styles are left alone.
 */
export type BasemapPalette = 'navy';

type PaletteSpec = {
  land: string;
  water: string;
  waterway: string;
  cover: string;
  residential: string;
  building: string;
  buildingLine: string;
  roadMinor: string;
  roadMajor: string;
  roadCasing: string;
  rail: string;
  borderState: string;
  borderCountry: string;
  waterText: string;
  placeText: string;
  halo: string;
};

const PALETTES: Record<BasemapPalette, PaletteSpec> = {
  navy: {
    land: '#0a1524', water: '#02060d', waterway: '#040a14', cover: '#0d1a2d', residential: '#0c182a',
    building: '#0a1424', buildingLine: '#14243a', roadMinor: '#112036', roadMajor: '#16283f',
    roadCasing: 'rgba(40,80,130,0.55)', rail: '#18294a', borderState: 'rgba(64,160,255,0.16)',
    borderCountry: 'rgba(69,190,255,0.32)', waterText: 'rgba(90,130,175,0.75)', placeText: '#6a83a3',
    halo: 'rgba(2,5,11,0.85)',
  },
};

function paintTable(c: PaletteSpec): Record<string, Record<string, unknown>> {
  return {
    background: { 'background-color': c.land },
    water: { 'fill-color': c.water },
    waterway: { 'line-color': c.waterway },
    landcover_ice_shelf: { 'fill-color': c.cover },
    landcover_glacier: { 'fill-color': c.cover },
    landuse_residential: { 'fill-color': c.residential },
    landcover_wood: { 'fill-color': c.cover },
    landuse_park: { 'fill-color': c.cover },
    building: { 'fill-color': c.building, 'fill-outline-color': c.buildingLine },
    highway_path: { 'line-color': c.roadMinor },
    highway_minor: { 'line-color': c.roadMinor },
    highway_major_casing: { 'line-color': c.roadCasing },
    highway_major_inner: { 'line-color': c.land },
    highway_major_subtle: { 'line-color': c.roadMajor },
    highway_motorway_casing: { 'line-color': c.roadCasing },
    highway_motorway_subtle: { 'line-color': c.roadMajor },
    railway: { 'line-color': c.rail },
    railway_minor: { 'line-color': c.rail },
    railway_transit: { 'line-color': c.rail },
    boundary_state: { 'line-color': c.borderState },
    'boundary_country_z0-4': { 'line-color': c.borderCountry },
    'boundary_country_z5-': { 'line-color': c.borderCountry },
    water_name: { 'text-color': c.waterText, 'text-halo-color': c.water },
  };
}

type LoosePaintMap = {
  getLayer: (id: string) => unknown;
  getPaintProperty: (id: string, prop: string) => unknown;
  setPaintProperty: (id: string, prop: string, value: unknown) => void;
  getStyle: () => { layers?: { id: string }[] } | undefined;
};

/** Apply a basemap palette. Idempotent: returns early when the background already matches. */
export function applyBasemapPalette(maplibreMap: MaplibreMap, palette: BasemapPalette = 'navy'): void {
  // Paint property names here are plain strings from the table above.
  const map = maplibreMap as unknown as LoosePaintMap;
  const c = PALETTES[palette] ?? PALETTES.navy;
  try {
    if (!map.getLayer('background') || !map.getLayer('water')) return;
    if (map.getPaintProperty('background', 'background-color') === c.land) return;
    for (const [id, paint] of Object.entries(paintTable(c))) {
      if (!map.getLayer(id)) continue;
      for (const [prop, value] of Object.entries(paint)) map.setPaintProperty(id, prop, value);
    }
    for (const layer of map.getStyle()?.layers ?? []) {
      if (!layer.id.startsWith('place_') && !layer.id.startsWith('highway_name')) continue;
      map.setPaintProperty(layer.id, 'text-color', c.placeText);
      map.setPaintProperty(layer.id, 'text-halo-color', c.halo);
    }
  } catch {
    // Style still loading or a custom style without these layers — keep the stock colours.
  }
}

/** Back-compat name used by the viewer for the default look. */
export function applyNavyBasemap(maplibreMap: MaplibreMap): void {
  applyBasemapPalette(maplibreMap, 'navy');
}
