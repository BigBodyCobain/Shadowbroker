import type { ActiveLayers } from '@/types/dashboard';
import { API_BASE } from '@/lib/api';

export const LAYER_PREFERENCES_STORAGE_KEY = 'sb_active_layers_v1';
export const DASHBOARD_PREFS_STORAGE_KEY = 'sb_dashboard_prefs_v1';
export const DASHBOARD_PREFS_VERSION = 1;
export const LAYER_PREFERENCES_CHANGED_EVENT = 'sb:layer-preferences-changed';

export const MAP_STYLES = ['DEFAULT', 'SATELLITE'] as const;
export type MapStyle = (typeof MAP_STYLES)[number];

export const LAYER_SECTION_IDS = [
  'aircraft',
  'maritime',
  'space',
  'hazards',
  'uap',
  'biosurveillance',
  'infrastructure',
  'shodan',
  'sigint',
  'overlays',
] as const;

export type LayerSectionId = (typeof LAYER_SECTION_IDS)[number];

type DashboardPrefsV1 = {
  version: typeof DASHBOARD_PREFS_VERSION;
  layers?: Partial<ActiveLayers>;
  mapStyle?: string;
  filters?: Record<string, string[]>;
  layerSectionsExpanded?: Record<string, boolean>;
};

/** Ship defaults for layer visibility — single source of truth for page + reset. */
export function getDefaultActiveLayers(): ActiveLayers {
  return {
    flights: true,
    private: true,
    jets: true,
    military: true,
    tracked: true,
    gps_jamming: true,
    ships_military: true,
    ships_cargo: true,
    ships_civilian: true,
    ships_passenger: true,
    ships_tracked_yachts: true,
    fishing_activity: true,
    satellites: true,
    gibs_imagery: false,
    highres_satellite: false,
    sentinel_hub: false,
    viirs_nightlights: false,
    road_corridor_trends: false,
    malware_c2: false,
    submarine_cables: false,
    scm_suppliers: false,
    cyber_threats: false,
    telegram_osint: true,
    earthquakes: true,
    firms: false,
    ukraine_alerts: true,
    weather_alerts: true,
    volcanoes: true,
    air_quality: true,
    cctv: false,
    datacenters: false,
    internet_outages: true,
    power_plants: false,
    military_bases: true,
    trains: false,
    kiwisdr: true,
    psk_reporter: false,
    satnogs: true,
    tinygs: true,
    scanners: true,
    sigint_meshtastic: true,
    sigint_aprs: true,
    ukraine_frontline: true,
    global_incidents: true,
    day_night: true,
    correlations: true,
    contradictions: true,
    uap_sightings: true,
    wastewater: true,
    crowdthreat: false,
    gt_risk: false,
    shodan_overlay: false,
    ai_intel: true,
    sar: true,
  };
}

const ACTIVE_LAYER_KEYS = Object.keys(getDefaultActiveLayers()) as (keyof ActiveLayers)[];
const LAYER_BACKEND_SYNC_INTERVAL_MS = 5000;
let layerBackendSyncTimer: ReturnType<typeof setInterval> | null = null;
let layerBackendSyncInFlight = false;
let layerBackendSeenSuccess = false;
let layerBackendSawFailure = false;
let repairedDefaultBackendState = false;

function isBooleanRecord(value: unknown): value is Record<string, boolean> {
  if (!value || typeof value !== 'object') return false;
  return Object.values(value).every((entry) => typeof entry === 'boolean');
}

function isStringArrayRecord(value: unknown): value is Record<string, string[]> {
  if (!value || typeof value !== 'object') return false;
  return Object.values(value).every(
    (entry) => Array.isArray(entry) && entry.every((item) => typeof item === 'string'),
  );
}

function readDashboardPrefs(): DashboardPrefsV1 {
  if (typeof window === 'undefined') {
    return { version: DASHBOARD_PREFS_VERSION };
  }
  try {
    const raw = localStorage.getItem(DASHBOARD_PREFS_STORAGE_KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') {
        return {
          version: DASHBOARD_PREFS_VERSION,
          ...(parsed as Omit<DashboardPrefsV1, 'version'>),
        };
      }
    }
    const legacyRaw = localStorage.getItem(LAYER_PREFERENCES_STORAGE_KEY);
    if (legacyRaw) {
      const parsed: unknown = JSON.parse(legacyRaw);
      if (parsed && typeof parsed === 'object') {
        const layers = (parsed as { layers?: unknown }).layers;
        if (isBooleanRecord(layers)) {
          return { version: DASHBOARD_PREFS_VERSION, layers: layers as Partial<ActiveLayers> };
        }
      }
    }
  } catch {
    /* ignore */
  }
  return { version: DASHBOARD_PREFS_VERSION };
}

function writeDashboardPrefs(patch: Omit<DashboardPrefsV1, 'version'>): void {
  if (typeof window === 'undefined') return;
  try {
    const { version: _version, ...current } = readDashboardPrefs();
    localStorage.setItem(
      DASHBOARD_PREFS_STORAGE_KEY,
      JSON.stringify({
        version: DASHBOARD_PREFS_VERSION,
        ...current,
        ...patch,
      }),
    );
    localStorage.removeItem(LAYER_PREFERENCES_STORAGE_KEY);
  } catch {
    /* quota / private mode */
  }
}

/** Apply saved toggles onto current defaults so new layers keep ship defaults. */
export function mergeActiveLayers(
  defaults: ActiveLayers,
  saved: Partial<ActiveLayers> | Record<string, boolean> | null | undefined,
): ActiveLayers {
  if (!saved) return { ...defaults };
  const merged = { ...defaults };
  for (const key of ACTIVE_LAYER_KEYS) {
    const value = saved[key];
    if (typeof value === 'boolean') {
      merged[key] = value;
    }
  }
  return merged;
}

export function loadActiveLayers(): ActiveLayers {
  const defaults = getDefaultActiveLayers();
  return mergeActiveLayers(defaults, readDashboardPrefs().layers);
}

function layerMapsEqual(left: ActiveLayers, right: ActiveLayers): boolean {
  return ACTIVE_LAYER_KEYS.every((key) => left[key] === right[key]);
}

function emitLayerPreferencesChanged(layers: ActiveLayers): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(
    new CustomEvent<ActiveLayers>(LAYER_PREFERENCES_CHANGED_EVENT, { detail: layers }),
  );
}

/**
 * Quietly repair the backend's process-local layer gate after a runtime restart.
 *
 * The dashboard already saves the operator's layer choices locally. The backend,
 * however, resets its fetcher gates on process restart. This reconciliation loop
 * observes the existing GET /api/layers endpoint and replays the saved operator
 * state only when a connection is first established, after an observed outage,
 * or when the backend has unmistakably fallen back to its shipped defaults.
 * It does not continuously overwrite arbitrary non-default server state, so two
 * independent clients do not get into a five-second preference tug-of-war.
 */
export async function reconcileActiveLayersWithBackend(): Promise<'synced' | 'noop' | 'offline'> {
  if (typeof window === 'undefined' || typeof fetch !== 'function') return 'offline';
  if (layerBackendSyncInFlight) return 'noop';
  layerBackendSyncInFlight = true;

  try {
    const response = await fetch(`${API_BASE}/api/layers`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`layer state probe failed (${response.status})`);

    const payload: unknown = await response.json();
    const rawLayers =
      payload && typeof payload === 'object' ? (payload as { layers?: unknown }).layers : null;
    if (!isBooleanRecord(rawLayers)) {
      throw new Error('layer state probe returned an invalid payload');
    }

    const defaults = getDefaultActiveLayers();
    const desired = loadActiveLayers();
    const backend = mergeActiveLayers(defaults, rawLayers);
    const mismatch = !layerMapsEqual(desired, backend);
    const backendAtDefaults = layerMapsEqual(backend, defaults);
    const shouldRepair =
      mismatch &&
      (!layerBackendSeenSuccess ||
        layerBackendSawFailure ||
        (backendAtDefaults && !repairedDefaultBackendState));

    if (shouldRepair) {
      const syncResponse = await fetch(`${API_BASE}/api/layers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layers: desired }),
      });
      if (!syncResponse.ok) {
        throw new Error(`layer state sync failed (${syncResponse.status})`);
      }
      // useDataPolling already listens for this event and refreshes gated data immediately.
      window.dispatchEvent(new Event('sb:layer-toggle'));
      repairedDefaultBackendState = backendAtDefaults;
      layerBackendSeenSuccess = true;
      layerBackendSawFailure = false;
      return 'synced';
    }

    if (!backendAtDefaults) repairedDefaultBackendState = false;
    layerBackendSeenSuccess = true;
    layerBackendSawFailure = false;
    return 'noop';
  } catch {
    layerBackendSawFailure = true;
    return 'offline';
  } finally {
    layerBackendSyncInFlight = false;
  }
}

function ensureLayerBackendSync(): void {
  if (
    typeof window === 'undefined' ||
    typeof fetch !== 'function' ||
    process.env.NODE_ENV === 'test'
  ) {
    return;
  }
  if (layerBackendSyncTimer !== null) return;

  void reconcileActiveLayersWithBackend();
  layerBackendSyncTimer = window.setInterval(() => {
    void reconcileActiveLayersWithBackend();
  }, LAYER_BACKEND_SYNC_INTERVAL_MS);
}

export function saveActiveLayers(layers: ActiveLayers): void {
  writeDashboardPrefs({ layers });
  emitLayerPreferencesChanged(layers);
  ensureLayerBackendSync();
}

export function clearActiveLayersPreference(): void {
  if (typeof window === 'undefined') return;
  try {
    const { version: _version, layers: _layers, ...rest } = readDashboardPrefs();
    localStorage.setItem(
      DASHBOARD_PREFS_STORAGE_KEY,
      JSON.stringify({ version: DASHBOARD_PREFS_VERSION, ...rest }),
    );
    localStorage.removeItem(LAYER_PREFERENCES_STORAGE_KEY);
  } catch {
    /* ignore */
  }
  const defaults = getDefaultActiveLayers();
  emitLayerPreferencesChanged(defaults);
  ensureLayerBackendSync();
}

export function getDefaultMapStyle(): MapStyle {
  return 'DEFAULT';
}

export function loadMapStyle(): MapStyle {
  const saved = readDashboardPrefs().mapStyle;
  return MAP_STYLES.includes(saved as MapStyle) ? (saved as MapStyle) : getDefaultMapStyle();
}

export function saveMapStyle(style: string): void {
  if (!MAP_STYLES.includes(style as MapStyle)) return;
  writeDashboardPrefs({ mapStyle: style });
}

export function loadActiveFilters(): Record<string, string[]> {
  const saved = readDashboardPrefs().filters;
  return isStringArrayRecord(saved) ? saved : {};
}

export function saveActiveFilters(filters: Record<string, string[]>): void {
  writeDashboardPrefs({ filters });
}

export function getDefaultLayerSectionExpanded(): Record<string, boolean> {
  return Object.fromEntries(LAYER_SECTION_IDS.map((id) => [id, id === 'overlays']));
}

export function mergeLayerSectionExpanded(
  defaults: Record<string, boolean>,
  saved: Record<string, boolean> | null | undefined,
): Record<string, boolean> {
  if (!saved) return { ...defaults };
  const merged = { ...defaults };
  for (const key of Object.keys(defaults)) {
    if (typeof saved[key] === 'boolean') {
      merged[key] = saved[key];
    }
  }
  return merged;
}

export function loadLayerSectionExpanded(): Record<string, boolean> {
  const defaults = getDefaultLayerSectionExpanded();
  const saved = readDashboardPrefs().layerSectionsExpanded;
  return mergeLayerSectionExpanded(defaults, isBooleanRecord(saved) ? saved : null);
}

export function saveLayerSectionExpanded(expanded: Record<string, boolean>): void {
  writeDashboardPrefs({ layerSectionsExpanded: expanded });
}
