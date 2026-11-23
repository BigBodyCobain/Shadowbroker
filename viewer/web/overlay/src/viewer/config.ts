/**
 * Public viewer settings. Everything here is public by nature: there is no
 * key, token or private address in the viewer build.
 */

/** Where the bridge's files are served from. Set at build time. */
export const VIEWER_DATA_BASE = (process.env.NEXT_PUBLIC_SB_DATA_BASE || '/live-data').replace(/\/+$/, '');

/**
 * The only outside hosts the viewer may contact (besides its own files and
 * the data host). The Content-Security-Policy in layout.tsx is built from the
 * same list, so the browser enforces it even for code the guard cannot see
 * (map workers, images).
 */
export const VIEWER_CONNECT_HOSTS = [
  'tiles.openfreemap.org', // basemap style, tiles, fonts
  'gibs.earthdata.nasa.gov', // NASA imagery overlays
  'server.arcgisonline.com', // satellite basemap
  'en.wikipedia.org', // summaries, straight from the visitor's browser
] as const;

/** Layer switches that never appear in the viewer. */
export const VIEWER_HIDDEN_LAYERS: ReadonlySet<string> = new Set([
  'shodan_overlay', // spends the owner's Shodan credits
  'sentinel_hub', // spends the owner's Copernicus quota
  'ai_intel', // the owner's private pins
  'sar', // the owner's watch areas
  'road_corridor_trends', // starts jobs on the owner's server
  'cctv', // streams through the owner's proxy
  'kiwisdr', // receiver tracker removed
  'scanners', // audio streams through the owner's server
  'sigint_aprs', // not published
  'telegram_osint', // media is relayed through the owner's server
  'crowdthreat', // not published
  'gt_risk', // not published
]);

/** Data older than this is shown as stale instead of live. */
export const VIEWER_STALE_AFTER_MS = 4 * 60 * 1000;

export const VIEWER_REPO_URL = 'https://github.com/BigBodyCobain/Shadowbroker';
