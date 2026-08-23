/**
 * Sentinel Hub (Copernicus CDSE) — client-side token + Process API tile fetcher.
 *
 * Issue #298 (tg12): Credentials are now stored server-side in the backend
 * ``.env`` (managed through the existing ``/api/settings/api-keys`` flow,
 * same as every other third-party API key). The browser no longer holds
 * ``client_id`` / ``client_secret`` in localStorage or sessionStorage and
 * no longer forwards them in proxy requests.
 *
 * Old browser-storage keys (``sb_sentinel_client_id`` / ``sb_sentinel_client_secret``
 * / ``sb_sentinel_instance_id``) are migrated out by ``SettingsPanel`` on
 * first mount after the upgrade — see ``migrateLegacySentinelBrowserKeys()``
 * exported below.
 */

import { API_BASE } from '@/lib/api';
import { isPublicReadOnlyRuntime } from '@/lib/publicRuntime';

// Token exchange proxied through our backend (Copernicus blocks browser CORS).
const TOKEN_PROXY_URL = `${API_BASE}/api/sentinel/token`;

// In-memory token cache (never persisted)
let cachedToken: string | null = null;
let tokenExpiry = 0;
// Dedup: only one in-flight token request at a time
let _tokenPromise: Promise<string | null> | null = null;

// In-memory cache of "does the backend have Sentinel credentials configured?"
// so the rest of the UI can short-circuit tile load attempts without a server
// round-trip per tile. Refreshed by callers via `refreshSentinelStatus()`.
let _backendCredentialsConfigured: boolean | null = null;
let _backendStatusPromise: Promise<boolean> | null = null;

// ─── Credential status (server-side) ───────────────────────────────────────

/**
 * Ask the backend whether Sentinel credentials are configured in ``.env``.
 * Caches the result in memory; call ``refreshSentinelStatus()`` after the
 * operator saves new API keys in the settings panel.
 *
 * Returns ``false`` on network errors so the UI fails safely (no broken
 * tile requests). Never returns the secret itself — that stays server-side.
 */
export async function checkBackendSentinelStatus(): Promise<boolean> {
  if (isPublicReadOnlyRuntime()) {
    _backendCredentialsConfigured = false;
    return false;
  }
  if (_backendCredentialsConfigured !== null) return _backendCredentialsConfigured;
  if (_backendStatusPromise) return _backendStatusPromise;

  _backendStatusPromise = (async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/settings/api-keys`, {
        headers: { Accept: 'application/json' },
      });
      if (!resp.ok) return false;
      const list = await resp.json();
      // /api/settings/api-keys returns an array of { id, env_key, is_set, ... }
      const ids = new Set(['sentinel_client_id', 'sentinel_client_secret']);
      const configured = Array.isArray(list)
        && list.filter((row: { id?: string; is_set?: boolean }) =>
              row && row.id && ids.has(row.id) && row.is_set === true,
           ).length === 2;
      _backendCredentialsConfigured = configured;
      return configured;
    } catch {
      _backendCredentialsConfigured = false;
      return false;
    } finally {
      _backendStatusPromise = null;
    }
  })();

  return _backendStatusPromise;
}

/** Invalidate the cached status — call this after the API Keys panel saves. */
export function refreshSentinelStatus(): void {
  _backendCredentialsConfigured = null;
  // Drop any cached token too — credentials may have changed.
  cachedToken = null;
  tokenExpiry = 0;
}

/**
 * Synchronous getter — returns the last known status without a network call.
 * Returns ``null`` until ``checkBackendSentinelStatus()`` has run at least once.
 */
export function getCachedSentinelStatus(): boolean | null {
  return _backendCredentialsConfigured;
}

/**
 * Back-compat shim. Pre-#298 callers asked ``hasSentinelCredentials()`` to
 * decide whether to render the Sentinel layer / open the API key prompt.
 * The credential now lives server-side, so this is just the cached
 * server-status check. Returns ``false`` until the first
 * ``checkBackendSentinelStatus()`` resolves (callers should kick that off
 * once at app startup — see ``page.tsx`` mount effect).
 */
export function hasSentinelCredentials(): boolean {
  return _backendCredentialsConfigured === true;
}

/**
 * One-time migration helper: clear the legacy browser-storage keys that
 * pre-#298 versions used to persist Sentinel credentials. Idempotent and
 * safe to call on every page load — does nothing if no keys are present.
 *
 * Called by ``SettingsPanel`` on mount. We do NOT auto-POST the legacy
 * browser values to the backend, because doing so would silently migrate
 * a secret across a trust boundary without operator consent. Operators
 * who relied on browser-stored credentials will re-enter them once in
 * the API Keys panel, and the legacy keys get wiped here.
 */
export function migrateLegacySentinelBrowserKeys(): { cleared: string[] } {
  if (typeof window === 'undefined') return { cleared: [] };
  const legacy = [
    'sb_sentinel_client_id',
    'sb_sentinel_client_secret',
    'sb_sentinel_instance_id',
  ];
  const cleared: string[] = [];
  for (const key of legacy) {
    try {
      if (window.localStorage?.getItem(key) !== null) {
        window.localStorage.removeItem(key);
        cleared.push(key);
      }
    } catch { /* ignore quota / privacy mode errors */ }
    try {
      if (window.sessionStorage?.getItem(key) !== null) {
        window.sessionStorage.removeItem(key);
        if (!cleared.includes(key)) cleared.push(key);
      }
    } catch { /* ignore */ }
  }
  return { cleared };
}

// ─── OAuth2 token ──────────────────────────────────────────────────────────

/**
 * Fetch an OAuth2 access token using the client_credentials grant.
 * Caches in memory; auto-refreshes 30 s before expiry.
 *
 * The request body NO LONGER carries client_id/secret — the backend
 * resolves credentials from its ``.env`` via the API Keys flow. The
 * server-side proxy still accepts body credentials for legacy callers,
 * but the dashboard does not supply them.
 */
export function getSentinelToken(): Promise<string | null> {
  // Return cached token if still valid (with 30 s margin)
  if (cachedToken && Date.now() < tokenExpiry - 30_000) return Promise.resolve(cachedToken);

  // Dedup: reuse in-flight request so 20 tiles don't each trigger a token fetch
  if (_tokenPromise) return _tokenPromise;

  _tokenPromise = (async () => {
    try {
      const resp = await fetch(TOKEN_PROXY_URL, {
        method: 'POST',
        // Backend resolves credentials from env. Empty body = "use server-side".
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({}),
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
 *
 * Body no longer carries client_id/secret — the backend uses .env values.
 */
export async function fetchSentinelTile(
  z: number,
  x: number,
  y: number,
  preset: string,
  date: string,
): Promise<ArrayBuffer | null> {
  const resp = await fetch(TILE_PROXY_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preset, date, z, x, y }),
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
