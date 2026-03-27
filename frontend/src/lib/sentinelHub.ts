/**
 * Sentinel Hub (Copernicus CDSE) — client-side token management & Process API tile fetcher.
 *
 * Credentials are stored in browser-controlled storage only. In privacy/session
 * mode they stay session-scoped; otherwise they persist in local storage. Token
 * exchange is proxied through the ShadowBroker backend (/api/sentinel/token) to
 * avoid CORS blocks from the Copernicus identity provider. Credentials are
 * forwarded, never stored server-side.
 *
 * Uses the Process API with inline evalscripts — no Instance ID / Configuration needed.
 */

import { API_BASE } from '@/lib/api';
import {
  getSensitiveBrowserItem,
  getSensitiveBrowserStorageMode,
  removeSensitiveBrowserItem,
  setSensitiveBrowserItem,
} from '@/lib/privacyBrowserStorage';

// Token exchange proxied through our backend (Copernicus blocks browser CORS)
const TOKEN_PROXY_URL = `${API_BASE}/api/sentinel/token`;

// browser-storage keys
const LS_CLIENT_ID = 'sb_sentinel_client_id';
const LS_CLIENT_SECRET = 'sb_sentinel_client_secret';

// In-memory token cache (never persisted)
let cachedToken: string | null = null;
let tokenExpiry = 0;
// Dedup: only one in-flight token request at a time
let _tokenPromise: Promise<string | null> | null = null;

// ─── Credential helpers ────────────────────────────────────────────────────

export function getSentinelCredentials(): {
  clientId: string;
  clientSecret: string;
} {
  if (typeof window === 'undefined') return { clientId: '', clientSecret: '' };
  return {
    clientId: getSensitiveBrowserItem(LS_CLIENT_ID) || '',
    clientSecret: getSensitiveBrowserItem(LS_CLIENT_SECRET) || '',
  };
}

export function setSentinelCredentials(clientId: string, clientSecret: string): void {
  setSensitiveBrowserItem(LS_CLIENT_ID, clientId);
  setSensitiveBrowserItem(LS_CLIENT_SECRET, clientSecret);
  // Invalidate cached token when credentials change
  cachedToken = null;
  tokenExpiry = 0;
}

export function clearSentinelCredentials(): void {
  removeSensitiveBrowserItem(LS_CLIENT_ID);
  removeSensitiveBrowserItem(LS_CLIENT_SECRET);
  // Also remove legacy instance ID if present
  removeSensitiveBrowserItem('sb_sentinel_instance_id');
  if (typeof window !== 'undefined') {
    localStorage.removeItem('sb_sentinel_instance_id');
    sessionStorage.removeItem('sb_sentinel_instance_id');
  }
  cachedToken = null;
  tokenExpiry = 0;
}

export function getSentinelCredentialStorageMode(): 'local' | 'session' {
  return getSensitiveBrowserStorageMode();
}

export function hasSentinelCredentials(): boolean {
  const { clientId, clientSecret } = getSentinelCredentials();
  return Boolean(clientId && clientSecret);
}

// ─── OAuth2 token ──────────────────────────────────────────────────────────

/**
 * Fetch an OAuth2 access token using the client_credentials grant.
 * Caches in memory; auto-refreshes 30 s before expiry.
 */
export function getSentinelToken(): Promise<string | null> {
  // Return cached token if still valid (with 30 s margin)
  if (cachedToken && Date.now() < tokenExpiry - 30_000) return Promise.resolve(cachedToken);

  const { clientId, clientSecret } = getSentinelCredentials();
  if (!clientId || !clientSecret) return Promise.resolve(null);

  // Dedup: reuse in-flight request so 20 tiles don't each trigger a token fetch
  if (_tokenPromise) return _tokenPromise;

  _tokenPromise = (async () => {
    try {
      const resp = await fetch(TOKEN_PROXY_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          client_id: clientId,
          client_secret: clientSecret,
        }),
      });

      if (!resp.ok) {
        const text = await resp.text().catch(() => '');
        throw new Error(`Sentinel Hub token request failed (${resp.status}): ${text}`);
      }

      const data = await resp.json();
      cachedToken = data.access_token;
      tokenExpiry = Date.now() + (data.expires_in ?? 300) * 1000;
      return cachedToken;
    } finally {
      _tokenPromise = null;
    }
  })();

  return _tokenPromise;
}

/** Synchronous getter — returns the current cached token or null. */
export function getCachedSentinelToken(): string | null {
  if (cachedToken && Date.now() < tokenExpiry - 5_000) return cachedToken;
  return null;
}

// ─── Tile fetcher (proxied through backend) ───────────────────────────────

const TILE_PROXY_URL = `${API_BASE}/api/sentinel/tile`;

/**
 * Fetch a single 256×256 tile via backend proxy to Sentinel Hub Process API.
 * Returns a PNG ArrayBuffer or null on failure.
 */
export async function fetchSentinelTile(
  z: number,
  x: number,
  y: number,
  preset: string,
  date: string,
): Promise<ArrayBuffer | null> {
  const { clientId, clientSecret } = getSentinelCredentials();
  if (!clientId || !clientSecret) return null;

  const resp = await fetch(TILE_PROXY_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_id: clientId,
      client_secret: clientSecret,
      preset,
      date,
      z,
      x,
      y,
    }),
  });

  if (!resp.ok) return null;
  return resp.arrayBuffer();
}

// ─── MapLibre protocol registration ───────────────────────────────────────

let _protocolRegistered = false;

/**
 * Register the `sentinel://` custom protocol with MapLibre.
 * Tile URLs look like: sentinel://z/x/y?preset=TRUE-COLOR&date=2024-06-01
 *
 * Call once at app startup or before adding the Sentinel source.
 */
export function registerSentinelProtocol(maplibregl: {
  addProtocol: (
    name: string,
    handler: (
      params: { url: string },
      abortController: AbortController,
    ) => Promise<{ data: ArrayBuffer }>,
  ) => void;
}): void {
  if (_protocolRegistered) return;
  _protocolRegistered = true;

  maplibregl.addProtocol('sentinel', async (params: { url: string }) => {
    // Parse: sentinel://14/8529/5765?preset=TRUE-COLOR&date=2024-06-01
    const url = new URL(params.url.replace('sentinel://', 'http://dummy/'));
    const parts = url.pathname.split('/').filter(Boolean);
    const z = parseInt(parts[0], 10);
    const x = parseInt(parts[1], 10);
    const y = parseInt(parts[2], 10);
    const preset = url.searchParams.get('preset') || 'TRUE-COLOR';
    const date = url.searchParams.get('date') || new Date().toISOString().slice(0, 10);

    tileLoadStart();
    try {
      const data = await fetchSentinelTile(z, x, y, preset, date);
      if (!data) {
        return { data: TRANSPARENT_1X1_PNG };
      }
      recordTileFetch();
      return { data };
    } finally {
      tileLoadEnd();
    }
  });
}

// 1×1 transparent PNG (68 bytes)
const TRANSPARENT_1X1_PNG = new Uint8Array([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44,
  0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1f,
  0x15, 0xc4, 0x89, 0x00, 0x00, 0x00, 0x0a, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x62, 0x00,
  0x00, 0x00, 0x02, 0x00, 0x01, 0xe2, 0x21, 0xbc, 0x33, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,
  0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
]).buffer;

/**
 * Build a sentinel:// tile URL template for MapLibre.
 * MapLibre will substitute {z}, {x}, {y} at render time.
 */
export function buildSentinelTileUrl(preset: string, date: string): string {
  return `sentinel://{z}/{x}/{y}?preset=${encodeURIComponent(preset)}&date=${encodeURIComponent(date)}`;
}

// ─── Layer presets ─────────────────────────────────────────────────────────

export const SENTINEL_PRESETS = [
  { id: 'TRUE-COLOR', name: 'True Color (S2)', description: 'Natural color RGB' },
  { id: 'FALSE-COLOR', name: 'False Color IR', description: 'Vegetation analysis' },
  { id: 'NDVI', name: 'NDVI', description: 'Vegetation index' },
  { id: 'MOISTURE-INDEX', name: 'Moisture Index', description: 'Soil/vegetation moisture' },
] as const;

export type SentinelPresetId = (typeof SENTINEL_PRESETS)[number]['id'];

// ─── Usage tracking ───────────────────────────────────────────────────────

const LS_USAGE_KEY = 'sb_sentinel_usage';

interface SentinelUsage {
  month: string; // "2026-03"
  tiles: number;
  pu: number; // tiles * 0.25
}

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

export function getSentinelUsage(): SentinelUsage {
  if (typeof window === 'undefined') return { month: currentMonth(), tiles: 0, pu: 0 };
  try {
    const raw = localStorage.getItem(LS_USAGE_KEY);
    if (raw) {
      const data = JSON.parse(raw) as SentinelUsage;
      // Reset if month changed
      if (data.month === currentMonth()) return data;
    }
  } catch { /* ignore */ }
  return { month: currentMonth(), tiles: 0, pu: 0 };
}

export function recordTileFetch(count = 1): void {
  const usage = getSentinelUsage();
  usage.tiles += count;
  usage.pu = Math.round(usage.tiles * 0.25 * 100) / 100;
  usage.month = currentMonth();
  localStorage.setItem(LS_USAGE_KEY, JSON.stringify(usage));
}

// ─── First-time flag ──────────────────────────────────────────────────────

const LS_SENTINEL_SEEN = 'sb_sentinel_info_seen';

export function hasSentinelInfoBeenSeen(): boolean {
  if (typeof window === 'undefined') return true;
  return localStorage.getItem(LS_SENTINEL_SEEN) === 'true';
}

export function markSentinelInfoSeen(): void {
  localStorage.setItem(LS_SENTINEL_SEEN, 'true');
}

// ─── Tile loading tracker ────────────────────────────────────────────────

type LoadingListener = (inflight: number, loaded: number) => void;

let _inflight = 0;
let _loaded = 0;
let _listeners: LoadingListener[] = [];

/** Subscribe to tile loading state changes. Returns unsubscribe function. */
export function onTileLoadingChange(cb: LoadingListener): () => void {
  _listeners.push(cb);
  return () => { _listeners = _listeners.filter(l => l !== cb); };
}

function _notifyListeners() {
  for (const cb of _listeners) cb(_inflight, _loaded);
}

export function tileLoadStart(): void {
  _inflight++;
  _notifyListeners();
}

export function tileLoadEnd(): void {
  _inflight = Math.max(0, _inflight - 1);
  _loaded++;
  _notifyListeners();
}

export function resetTileLoading(): void {
  _inflight = 0;
  _loaded = 0;
  _notifyListeners();
}

export function getTileLoadingState(): { inflight: number; loaded: number } {
  return { inflight: _inflight, loaded: _loaded };
}
