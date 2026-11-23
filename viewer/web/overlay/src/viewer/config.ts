/**
 * Public viewer settings. Everything here is public by nature: there is no
 * key, token or private address in the viewer build.
 */

/**
 * The folder the viewer itself is published in ("" at the top of a site,
 * "/map" under another site). Set at build time.
 */
export const VIEWER_BASE_PATH = (process.env.NEXT_PUBLIC_SB_BASE_PATH || '').replace(/\/+$/, '');

/** Address of one of the viewer's own static files, e.g. asset('/skill/manifest.json'). */
export function asset(path: string): string {
  return `${VIEWER_BASE_PATH}${path}`;
}

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
  'planetarycomputer.microsoft.com', // right-click: open Sentinel-2 satellite scenes, no key
  'api.geckoterminal.com', // token card: public price figures, no key
] as const;

/** Layer switches that never appear in the viewer. */
export const VIEWER_HIDDEN_LAYERS: ReadonlySet<string> = new Set([
  'shodan_overlay', // spends the owner's Shodan credits
  'sentinel_hub', // spends the owner's Copernicus quota
  'ai_intel', // the owner's private pins
  'sar', // the owner's watch areas
  'road_corridor_trends', // starts jobs on the owner's server
  'telegram_osint', // media is relayed through the owner's server
  'crowdthreat', // not published
  'gt_risk', // not published
]);

/** Data older than this is shown as stale instead of live. */
export const VIEWER_STALE_AFTER_MS =
  (Number(process.env.NEXT_PUBLIC_SB_STALE_AFTER_S) > 0 ? Number(process.env.NEXT_PUBLIC_SB_STALE_AFTER_S) : 240) * 1000;

export const VIEWER_REPO_URL = 'https://github.com/BigBodyCobain/Shadowbroker';

/** Top-right links. Each opens the project's own page on that site in a new tab. */
export type ViewerLinkId = 'discord' | 'github' | 'discussions';
export const VIEWER_LINKS: readonly { id: ViewerLinkId; label: string; title: string; href: string }[] = [
  { id: 'discord', label: 'Discord', title: 'Join the community on Discord', href: 'https://discord.gg/hTWprYS6gC' },
  { id: 'github', label: 'GitHub', title: 'Source code, and the full app to run yourself', href: VIEWER_REPO_URL },
  { id: 'discussions', label: 'Forum', title: 'Project discussion board on GitHub', href: `${VIEWER_REPO_URL}/discussions` },
];

/** The project token, shown in its own card above the Public Viewer card. */
const TOKEN_ADDRESS = '8Uk9f5WfJndkC9VkFRLDwEpHgD2KD8BcFbqh5zuBpump';
export const VIEWER_TOKEN = {
  symbol: '$SB',
  href: `https://pump.fun/coin/${TOKEN_ADDRESS}`,
  /** GeckoTerminal's public, keyless token endpoint. */
  quoteUrl: `https://api.geckoterminal.com/api/v2/networks/solana/tokens/${TOKEN_ADDRESS}`,
} as const;

/**
 * Optional chat room, on a separate hosted login + database service. Both
 * values are public by design (the "anon" key is what browsers are meant to
 * hold); the database rules decide what a visitor may do. Empty = no chat.
 */
export const VIEWER_CHAT: {
  url: string;
  anonKey: string;
  providers: ('google' | 'facebook')[];
} = {
  url: (process.env.NEXT_PUBLIC_SB_CHAT_URL || '').replace(/\/+$/, ''),
  anonKey: process.env.NEXT_PUBLIC_SB_CHAT_KEY || '',
  providers: (process.env.NEXT_PUBLIC_SB_CHAT_PROVIDERS || '')
    .split(',')
    .map((p) => p.trim().toLowerCase())
    .filter((p): p is 'google' | 'facebook' => p === 'google' || p === 'facebook'),
};
