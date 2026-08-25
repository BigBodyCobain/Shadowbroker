/**
 * clientTools — the browser-side half of the unified voice tool registry
 * (voice-agent plan U4, §3.4). Each executor binds to a verified page anchor
 * via the `ClientToolContext` passed once from page.tsx and returns the
 * envelope `{ok, action, error?, cancelled?, ...evidence}`.
 *
 * Executor discipline (ported from gevActions): clamp everything (strings
 * ≤200 chars, arrays ≤24 items, numeric ranges) before React state; never
 * claim unverified state (`toggle_layer` re-reads applied state; actual ≠
 * requested ⇒ ok:false); supersession via monotonically increasing turnId
 * (late finishers return cancelled:true); static error text only — free-text
 * parameters never flow into `error` (injection defense).
 *
 * The marker-delimited descriptor block below is the single source of truth
 * for backend/fixtures/voice_client_tools.json — update both together.
 * backend/tests/test_voice_tool_registry.py fails on drift.
 */
import { send } from '@/lib/mapControlBus';
import { getPollMeta, readDataKey } from '@/hooks/useDataStore';
import {
  enterSnapshotMode,
  exitSnapshotMode,
  seekToTime,
  startPlayback,
  stepBackward,
  stepForward,
  togglePlayback,
} from '@/hooks/useTimeMachine';

// ── Descriptor types ───────────────────────────────────────────────────────

export interface ClientToolParamSpec {
  type: 'string' | 'integer' | 'float' | 'boolean' | 'array' | 'object';
  required?: boolean;
  enum?: string[];
  min?: number;
  max?: number;
}

export interface ClientToolDescriptor {
  name: string;
  type: string;
  surface: 'client';
  description: string;
  parameters: Record<string, ClientToolParamSpec>;
  returns: string;
  latency_tier_ms: number;
  requires_confirm: boolean;
}

export interface ToolResult {
  ok: boolean;
  action: string;
  error?: string;
  cancelled?: boolean;
  [key: string]: unknown;
}

/** Page-provided bindings — one wiring site in page.tsx (§3.5). */
export interface ClientToolContext {
  flyTo(target: {
    lat: number;
    lng: number;
    zoom?: number;
    bounds?: [number, number, number, number];
  }): void;
  /** Apply the layer toggle; returns the ACTUAL applied state, or null when refused. */
  toggleLayer(layer: string, enabled: boolean): boolean | null;
  /** Apply basemap style; returns the ACTUAL applied style. */
  applyMapStyle(style: 'DEFAULT' | 'SATELLITE'): 'DEFAULT' | 'SATELLITE';
  setFilter(filterKey: string, values: string[]): void;
  setSelectedEntity(entity: { id: string; type: string; name?: string; extra?: Record<string, unknown> } | null): void;
  viewSummary(): { activeLayers: Record<string, boolean>; filters: Record<string, string[]> };
}

export const CLIENT_TOOL_DESCRIPTORS: readonly ClientToolDescriptor[] = /* voice-client-tools:begin */ [
  {
    "name": "map_fly_to",
    "type": "camera",
    "surface": "client",
    "description": "Fly the operator's 2D map to a location. Optionally set zoom or fit to bounds.",
    "parameters": {
      "lat": { "type": "float", "required": true, "min": -90, "max": 90 },
      "lng": { "type": "float", "required": true, "min": -180, "max": 180 },
      "zoom": { "type": "float", "required": false, "min": 0, "max": 20 },
      "label": { "type": "string", "required": false }
    },
    "returns": "{ok, action, center:{lat,lng}, zoom, arrived}",
    "latency_tier_ms": 900,
    "requires_confirm": false
  },
  {
    "name": "map_ease_to",
    "type": "camera",
    "surface": "client",
    "description": "Ease the operator's map camera to a location over a duration instead of flying.",
    "parameters": {
      "lat": { "type": "float", "required": true, "min": -90, "max": 90 },
      "lng": { "type": "float", "required": true, "min": -180, "max": 180 },
      "zoom": { "type": "float", "required": false, "min": 0, "max": 20 },
      "duration_ms": { "type": "integer", "required": false, "min": 0, "max": 10000 }
    },
    "returns": "{ok, action, center:{lat,lng}, zoom}",
    "latency_tier_ms": 900,
    "requires_confirm": false
  },
  {
    "name": "map_fit_bounds",
    "type": "camera",
    "surface": "client",
    "description": "Fit the operator's map viewport to a geographic bounding box.",
    "parameters": {
      "west": { "type": "float", "required": true, "min": -180, "max": 180 },
      "south": { "type": "float", "required": true, "min": -90, "max": 90 },
      "east": { "type": "float", "required": true, "min": -180, "max": 180 },
      "north": { "type": "float", "required": true, "min": -90, "max": 90 },
      "padding": { "type": "integer", "required": false, "min": 0, "max": 400 }
    },
    "returns": "{ok, action, bounds:{west,south,east,north}}",
    "latency_tier_ms": 900,
    "requires_confirm": false
  },
  {
    "name": "map_orbit",
    "type": "camera",
    "surface": "client",
    "description": "Start or stop an orbiting camera animation around a point on the operator's map.",
    "parameters": {
      "lng": { "type": "float", "required": true, "min": -180, "max": 180 },
      "lat": { "type": "float", "required": true, "min": -90, "max": 90 },
      "radius_km": { "type": "float", "required": false, "min": 0, "max": 2000 },
      "speed": { "type": "float", "required": false, "min": 0, "max": 10 },
      "stop": { "type": "boolean", "required": false }
    },
    "returns": "{ok, action, orbiting:boolean}",
    "latency_tier_ms": 900,
    "requires_confirm": false
  },
  {
    "name": "map_zoom",
    "type": "camera",
    "surface": "client",
    "description": "Zoom the operator's map in or out by a small, medium, or large amount.",
    "parameters": {
      "direction": { "type": "string", "required": true, "enum": ["in", "out"] },
      "amount": { "type": "string", "required": false, "enum": ["little", "medium", "lot"] }
    },
    "returns": "{ok, action, zoom}",
    "latency_tier_ms": 500,
    "requires_confirm": false
  },
  {
    "name": "toggle_layer",
    "type": "ui",
    "surface": "client",
    "description": "Enable or disable one of the operator's map data layers by id.",
    "parameters": {
      "layer": { "type": "string", "required": true },
      "enabled": { "type": "boolean", "required": true }
    },
    "returns": "{ok, action, layer, enabled, actual_enabled}",
    "latency_tier_ms": 300,
    "requires_confirm": false
  },
  {
    "name": "set_map_style",
    "type": "ui",
    "surface": "client",
    "description": "Switch the operator's map basemap style between DEFAULT and SATELLITE.",
    "parameters": {
      "style": { "type": "string", "required": true, "enum": ["DEFAULT", "SATELLITE"] }
    },
    "returns": "{ok, action, style}",
    "latency_tier_ms": 300,
    "requires_confirm": false
  },
  {
    "name": "set_filter",
    "type": "ui",
    "surface": "client",
    "description": "Replace one filter key's value list in the operator's active filters.",
    "parameters": {
      "filter_key": { "type": "string", "required": true },
      "values": { "type": "array", "required": true }
    },
    "returns": "{ok, action, filter_key, values}",
    "latency_tier_ms": 300,
    "requires_confirm": false
  },
  {
    "name": "select_entity",
    "type": "ui",
    "surface": "client",
    "description": "Select an entity on the operator's map by id or free-text query (visual-follow only; does not persist a watch).",
    "parameters": {
      "id": { "type": "string", "required": false },
      "query": { "type": "string", "required": false },
      "layer": { "type": "string", "required": false }
    },
    "returns": "{ok, action, entity:{id,layer,label} | selected:false}",
    "latency_tier_ms": 300,
    "requires_confirm": false
  },
  {
    "name": "clear_selection",
    "type": "ui",
    "surface": "client",
    "parameters": {},
    "description": "Clear the operator's current entity selection.",
    "returns": "{ok, action}",
    "latency_tier_ms": 200,
    "requires_confirm": false
  },
  {
    "name": "tm_enter_snapshot",
    "type": "ui",
    "surface": "client",
    "description": "Enter Time Machine snapshot mode for a stored snapshot id.",
    "parameters": {
      "snapshot_id": { "type": "string", "required": true }
    },
    "returns": "{ok, action, snapshot_id}",
    "latency_tier_ms": 600,
    "requires_confirm": false
  },
  {
    "name": "tm_playback",
    "type": "ui",
    "surface": "client",
    "description": "Control Time Machine playback: play, pause, stop, step forward, or step backward.",
    "parameters": {
      "action": { "type": "string", "required": true, "enum": ["play", "pause", "stop", "fwd", "back"] },
      "speed": { "type": "float", "required": false, "min": 0, "max": 64 }
    },
    "returns": "{ok, action, playing, speed}",
    "latency_tier_ms": 300,
    "requires_confirm": false
  },
  {
    "name": "tm_seek",
    "type": "ui",
    "surface": "client",
    "description": "Seek the Time Machine timeline to an ISO timestamp.",
    "parameters": {
      "timestamp": { "type": "string", "required": true }
    },
    "returns": "{ok, action, timestamp}",
    "latency_tier_ms": 300,
    "requires_confirm": false
  },
  {
    "name": "tm_exit",
    "type": "ui",
    "surface": "client",
    "parameters": {},
    "description": "Exit Time Machine snapshot mode and return to live data.",
    "returns": "{ok, action}",
    "latency_tier_ms": 300,
    "requires_confirm": false
  },
  {
    "name": "get_view_state",
    "type": "read",
    "surface": "client",
    "parameters": {},
    "description": "Read the operator's current camera position, active layers, and filter summary.",
    "returns": "{ok, action, view:{center,zoom}, active_layers:[...], filters:{...}}",
    "latency_tier_ms": 100,
    "requires_confirm": false
  },
  {
    "name": "get_grounding_snapshot",
    "type": "read",
    "surface": "client",
    "parameters": {},
    "description": "Read the sb.grounding.v1 snapshot of what the operator is currently looking at.",
    "returns": "{ok, action, snapshot:<sb.grounding.v1>}",
    "latency_tier_ms": 100,
    "requires_confirm": false
  }
] /* voice-client-tools:end */;

export const CLIENT_TOOL_NAMES: ReadonlySet<string> = new Set(
  CLIENT_TOOL_DESCRIPTORS.map((d) => d.name),
);

// ── Clamp discipline (gevActions port) ─────────────────────────────────────

const STRING_MAX = 200;
const ARRAY_MAX = 24;

function clampString(v: unknown, max: number = STRING_MAX): string {
  return String(v ?? '').slice(0, max);
}

function clampNumber(v: unknown, min: number, max: number, fallback: number): number {
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function clampStringArray(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.slice(0, ARRAY_MAX).map((item) => clampString(item));
}

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

// ── Supersession ────────────────────────────────────────────────────────────

let turnCounter = 1;
const latestTurnByVerb = new Map<string, number>();

function nextTurnId(): number {
  return ++turnCounter;
}

function isSuperseded(verb: string, turnId: number): boolean {
  return (latestTurnByVerb.get(verb) ?? 0) > turnId;
}

function cancelledResult(action: string): ToolResult {
  return { ok: false, action, cancelled: true };
}

// ── Layer-id validation & entity resolution ────────────────────────────────

const ENTITY_SEARCH_LAYERS = [
  'commercial_flights',
  'military_flights',
  'tracked_flights',
  'private_flights',
  'private_jets',
  'ships',
  'satellites',
] as const;

const MAX_ENTITY_SCAN = 500;

function entityIdForLayer(layer: string, item: Record<string, unknown>): string {
  if (layer === 'ships') return String(item.mmsi ?? item.id ?? '').trim();
  return String(item.icao24 ?? item.icao ?? item.id ?? item.hex ?? '').trim().toLowerCase();
}

function entityLabelForLayer(layer: string, item: Record<string, unknown>): string {
  return String(
    item.callsign ?? item.name ?? item.reg ?? item.flight ?? item.mmsi ?? item.icao24 ?? item.id ?? '',
  ).slice(0, STRING_MAX);
}

function findEntity(
  wantedLayer: string | null,
  predicate: (item: Record<string, unknown>) => boolean,
): { id: string; layer: string; label: string; item: Record<string, unknown> } | null {
  for (const layer of ENTITY_SEARCH_LAYERS) {
    if (wantedLayer && layer !== wantedLayer) continue;
    const arr = readDataKey(layer);
    if (!Array.isArray(arr)) continue;
    for (const raw of arr.slice(0, MAX_ENTITY_SCAN)) {
      const item = asRecord(raw);
      if (predicate(item)) {
        return { id: entityIdForLayer(layer, item), layer, label: entityLabelForLayer(layer, item), item };
      }
    }
  }
  return null;
}

function normalizeLayerId(v: unknown): string {
  // Accept either store keys (commercial_flights) or UI toggles (flights).
  return clampString(v).trim().toLowerCase();
}

// ── Executors ───────────────────────────────────────────────────────────────

async function execMapFlyTo(args: Record<string, unknown>, ctx: ClientToolContext, _turnId: number): Promise<ToolResult> {
  const lat = clampNumber(args.lat, -90, 90, 0);
  const lng = clampNumber(args.lng, -180, 180, 0);
  const zoom = args.zoom == null ? undefined : clampNumber(args.zoom, 0, 20, 8);
  ctx.flyTo({ lat, lng, zoom });
  return { ok: true, action: 'map_fly_to', center: { lat, lng }, zoom: zoom ?? null, arrived: true };
}

async function execMapEaseTo(args: Record<string, unknown>, ctx: ClientToolContext, turnId: number): Promise<ToolResult> {
  const lat = clampNumber(args.lat, -90, 90, 0);
  const lng = clampNumber(args.lng, -180, 180, 0);
  const zoom = args.zoom == null ? undefined : clampNumber(args.zoom, 0, 20, 8);
  const durationMs = args.duration_ms == null ? undefined : clampNumber(args.duration_ms, 0, 10000, 800);
  const result = await send({ type: 'easeTo', lat, lng, zoom, durationMs });
  if (isSuperseded('map_ease_to', turnId)) return cancelledResult('map_ease_to');
  return { ...result, action: 'map_ease_to' };
}

async function execMapFitBounds(args: Record<string, unknown>, ctx: ClientToolContext, _turnId: number): Promise<ToolResult> {
  const west = clampNumber(args.west, -180, 180, -10);
  const south = clampNumber(args.south, -90, 90, -10);
  const east = clampNumber(args.east, -180, 180, 10);
  const north = clampNumber(args.north, -90, 90, 10);
  ctx.flyTo({ lat: (south + north) / 2, lng: (west + east) / 2, bounds: [west, south, east, north] });
  return { ok: true, action: 'map_fit_bounds', bounds: { west, south, east, north } };
}

async function execMapOrbit(args: Record<string, unknown>, _ctx: ClientToolContext, turnId: number): Promise<ToolResult> {
  const lng = clampNumber(args.lng, -180, 180, 0);
  const lat = clampNumber(args.lat, -90, 90, 0);
  const radiusKm = args.radius_km == null ? undefined : clampNumber(args.radius_km, 0, 2000, 50);
  const speed = args.speed == null ? undefined : clampNumber(args.speed, 0, 10, 1);
  const stop = args.stop === true;
  const result = await send({ type: 'orbit', lng, lat, radiusKm, speed, stop });
  if (isSuperseded('map_orbit', turnId)) return cancelledResult('map_orbit');
  return { ...result, action: 'map_orbit' };
}

async function execMapZoom(args: Record<string, unknown>, _ctx: ClientToolContext, turnId: number): Promise<ToolResult> {
  const direction = args.direction === 'out' ? 'out' : 'in';
  const amountRaw = clampString(args.amount, 16);
  const amount = amountRaw === 'little' || amountRaw === 'lot' ? amountRaw : 'medium';
  const result = await send({ type: 'zoom', direction, amount });
  if (isSuperseded('map_zoom', turnId)) return cancelledResult('map_zoom');
  return { ...result, action: 'map_zoom' };
}

async function execToggleLayer(args: Record<string, unknown>, ctx: ClientToolContext, _turnId: number): Promise<ToolResult> {
  const layer = normalizeLayerId(args.layer);
  const enabled = args.enabled === true;
  const known = Object.keys(ctx.viewSummary().activeLayers);
  if (!layer || !known.includes(layer)) {
    return { ok: false, action: 'toggle_layer', layer, enabled, error: 'unknown layer id' };
  }
  const actual = ctx.toggleLayer(layer, enabled);
  if (actual === null) {
    return { ok: false, action: 'toggle_layer', layer, enabled, error: 'layer toggle was not applied' };
  }
  if (actual !== enabled) {
    // Honesty rule: report actual-not-requested state.
    return {
      ok: false,
      action: 'toggle_layer',
      layer,
      enabled,
      actual_enabled: actual,
      error: 'requested layer state was not applied',
    };
  }
  return { ok: true, action: 'toggle_layer', layer, enabled, actual_enabled: actual };
}

async function execSetMapStyle(args: Record<string, unknown>, ctx: ClientToolContext, _turnId: number): Promise<ToolResult> {
  const requested = args.style === 'SATELLITE' ? 'SATELLITE' : 'DEFAULT';
  const actual = ctx.applyMapStyle(requested);
  if (actual !== requested) {
    return { ok: false, action: 'set_map_style', style: requested, actual_style: actual, error: 'requested style was not applied' };
  }
  return { ok: true, action: 'set_map_style', style: actual };
}

async function execSetFilter(args: Record<string, unknown>, ctx: ClientToolContext, _turnId: number): Promise<ToolResult> {
  const filterKey = clampString(args.filter_key, 64);
  const values = clampStringArray(args.values);
  if (!filterKey) {
    return { ok: false, action: 'set_filter', error: 'filter key required' };
  }
  ctx.setFilter(filterKey, values);
  return { ok: true, action: 'set_filter', filter_key: filterKey, values };
}

async function execSelectEntity(args: Record<string, unknown>, ctx: ClientToolContext, _turnId: number): Promise<ToolResult> {
  const id = clampString(args.id, 64).trim().toLowerCase();
  const query = clampString(args.query, 200).trim();
  const layerArg = args.layer == null ? null : normalizeLayerId(args.layer);
  if (!id && !query) {
    return { ok: false, action: 'select_entity', error: 'id or query required' };
  }
  let hit: ReturnType<typeof findEntity> = null;
  if (id) hit = findEntity(layerArg, (item) => entityIdForLayer(layerArg ?? '', item) === id);
  if (!hit && query) {
    const lowered = query.toLowerCase();
    hit = findEntity(layerArg, (item) => entityLabelForLayer('', item).toLowerCase().includes(lowered));
  }
  if (!hit) {
    return { ok: true, action: 'select_entity', selected: false };
  }
  const extra: Record<string, unknown> = {};
  if (typeof hit.item.lat === 'number') extra.lat = hit.item.lat;
  if (typeof hit.item.lng === 'number') extra.lng = hit.item.lng;
  ctx.setSelectedEntity({ id: hit.id, type: hit.layer, name: hit.label, extra });
  return { ok: true, action: 'select_entity', entity: { id: hit.id, layer: hit.layer, label: hit.label } };
}

async function execClearSelection(args: Record<string, unknown>, ctx: ClientToolContext, _turnId: number): Promise<ToolResult> {
  ctx.setSelectedEntity(null);
  return { ok: true, action: 'clear_selection' };
}

async function execTmEnterSnapshot(args: Record<string, unknown>, _ctx: ClientToolContext, turnId: number): Promise<ToolResult> {
  const snapshotId = clampString(args.snapshot_id, 120);
  if (!snapshotId) return { ok: false, action: 'tm_enter_snapshot', error: 'snapshot id required' };
  try {
    await enterSnapshotMode(snapshotId);
  } catch {
    return { ok: false, action: 'tm_enter_snapshot', snapshot_id: snapshotId, error: 'snapshot could not be opened' };
  }
  if (isSuperseded('tm_enter_snapshot', turnId)) return cancelledResult('tm_enter_snapshot');
  return { ok: true, action: 'tm_enter_snapshot', snapshot_id: snapshotId };
}

async function execTmPlayback(args: Record<string, unknown>, _ctx: ClientToolContext, turnId: number): Promise<ToolResult> {
  const verb = clampString(args.action, 8);
  const speed = args.speed == null ? undefined : clampNumber(args.speed, 0, 64, 1);
  try {
    switch (verb) {
      case 'play':
        await startPlayback();
        break;
      case 'pause':
        togglePlayback();
        break;
      case 'stop':
        togglePlayback();
        break;
      case 'fwd':
        await stepForward();
        break;
      case 'back':
        await stepBackward();
        break;
      default:
        return { ok: false, action: 'tm_playback', error: 'unknown playback action' };
    }
    if (speed != null && (verb === 'play' || verb === 'pause')) setSpeedSafe(speed);
  } catch {
    return { ok: false, action: 'tm_playback', error: 'playback control failed' };
  }
  if (isSuperseded('tm_playback', turnId)) return cancelledResult('tm_playback');
  return { ok: true, action: 'tm_playback', playing: verb === 'play', speed: speed ?? null };
}

function setSpeedSafe(speed: number): void {
  // Imported lazily to keep this module side-effect free at import time.
  import('@/hooks/useTimeMachine').then((tm) => tm.setPlaybackSpeed(speed)).catch(() => {});
}

async function execTmSeek(args: Record<string, unknown>, _ctx: ClientToolContext, turnId: number): Promise<ToolResult> {
  const timestamp = clampString(args.timestamp, 40).trim();
  const ts = Date.parse(timestamp);
  if (!timestamp || Number.isNaN(ts)) {
    return { ok: false, action: 'tm_seek', error: 'invalid timestamp' };
  }
  try {
    await seekToTime(Math.floor(ts / 1000));
  } catch {
    return { ok: false, action: 'tm_seek', timestamp, error: 'seek failed' };
  }
  if (isSuperseded('tm_seek', turnId)) return cancelledResult('tm_seek');
  return { ok: true, action: 'tm_seek', timestamp };
}

async function execTmExit(_args: Record<string, unknown>, _ctx: ClientToolContext, _turnId: number): Promise<ToolResult> {
  try {
    exitSnapshotMode();
  } catch {
    return { ok: false, action: 'tm_exit', error: 'exit failed' };
  }
  return { ok: true, action: 'tm_exit' };
}

async function execGetViewState(_args: Record<string, unknown>, ctx: ClientToolContext, turnId: number): Promise<ToolResult> {
  const result = await send({ type: 'getViewState' });
  if (isSuperseded('get_view_state', turnId)) return cancelledResult('get_view_state');
  if (!result.ok) return { ...result, action: 'get_view_state' };
  const summary = ctx.viewSummary();
  const activeLayers = Object.keys(summary.activeLayers).filter((k) => summary.activeLayers[k]).sort();
  return {
    ok: true,
    action: 'get_view_state',
    view: result.view ?? null,
    active_layers: activeLayers,
    filters: summary.filters,
  };
}

/**
 * Minimal sb.grounding.v1 projection for U4 — honest view/layers/counts/mode
 * only. The full composer (freshness dispositions, correlations, news
 * verdicts, health bridge) lands with U5's useVoiceGrounding.
 */
async function execGetGroundingSnapshot(_args: Record<string, unknown>, ctx: ClientToolContext, _turnId: number): Promise<ToolResult> {
  const summary = ctx.viewSummary();
  const activeLayers = Object.keys(summary.activeLayers).filter((k) => summary.activeLayers[k]).sort();
  const counts: Record<string, number> = {};
  for (const layer of activeLayers) {
    const arr = readDataKey(layer);
    counts[layer] = Array.isArray(arr) ? arr.length : 0;
  }
  const meta = getPollMeta();
  const snapshot = {
    schema: 'sb.grounding.v1',
    generated_at: new Date().toISOString(),
    session: { mode: meta.mode },
    layers: { active: activeLayers, inactive_count: Object.keys(summary.activeLayers).length - activeLayers.length },
    counts,
    filters: summary.filters,
    poll_meta: { mode: meta.mode, layer_versions: meta.layerVersions, updated_at: meta.updatedAt || null },
  };
  return { ok: true, action: 'get_grounding_snapshot', snapshot };
}

const EXECUTORS: Record<
  string,
  (args: Record<string, unknown>, ctx: ClientToolContext, turnId: number) => Promise<ToolResult>
> = {
  map_fly_to: execMapFlyTo,
  map_ease_to: execMapEaseTo,
  map_fit_bounds: execMapFitBounds,
  map_orbit: execMapOrbit,
  map_zoom: execMapZoom,
  toggle_layer: execToggleLayer,
  set_map_style: execSetMapStyle,
  set_filter: execSetFilter,
  select_entity: execSelectEntity,
  clear_selection: execClearSelection,
  tm_enter_snapshot: execTmEnterSnapshot,
  tm_playback: execTmPlayback,
  tm_seek: execTmSeek,
  tm_exit: execTmExit,
  get_view_state: execGetViewState,
  get_grounding_snapshot: execGetGroundingSnapshot,
};

/**
 * Execute one client-surface verb. `turnId` defaults to a fresh monotonic id;
 * pass an explicit id to participate in supersession across a conversation
 * turn (late finishers resolve `cancelled:true`).
 */
export async function executeClientVerb(
  name: string,
  args: unknown,
  ctx: ClientToolContext,
  turnId: number = nextTurnId(),
): Promise<ToolResult> {
  const executor = EXECUTORS[name];
  const cleanArgs = asRecord(args);
  if (!executor) {
    return { ok: false, action: String(name), error: 'unknown client verb' };
  }
  latestTurnByVerb.set(name, Math.max(latestTurnByVerb.get(name) ?? 0, turnId));
  try {
    return await executor(cleanArgs, ctx, turnId);
  } catch {
    return { ok: false, action: String(name), error: 'client verb execution failed' };
  }
}
