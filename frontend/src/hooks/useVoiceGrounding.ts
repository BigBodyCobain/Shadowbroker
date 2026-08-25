/**
 * useVoiceGrounding — composes the §2.4 `sb.grounding.v1` GroundingSnapshot
 * from the operator's actual client store and drives ambient NARRATE
 * regeneration (voice-agent plan §2.6/§2.7, U5).
 *
 * Triggers: VIEWPORT_COMMITTED_EVENT (debounced), sb:layer-toggle,
 * sb:layer-preferences-changed, freshness diff restricted to
 * NARRATION_LAYER_KEYS. Skip-gates before any network call: env opt-in /
 * controller phase, ambient ARM (default OFF — disarmed ⇒ zero hud-summary
 * calls), Time-Machine polling pause, hidden tab, debounce + min-interval,
 * and a fingerprint-hash gate so unchanged views never POST.
 *
 * Regeneration is hold-last-good: an upstream failure keeps the previous
 * brief on screen and records the verbatim error.
 */
import { useCallback, useEffect, useRef } from 'react';
import { API_BASE } from '@/lib/api';
import {
  GROUNDING_SCHEMA_ID,
  GROUNDING_SNAPSHOT_MAX_BYTES,
  type GroundingSnapshot,
  type HudSummaryResponse,
} from '@/lib/voiceGroundingTypes';
import {
  DERIVED_LAYER_FRESHNESS_PARENT,
  LAYER_EXPECTED_CADENCE_S,
  NARRATION_LAYER_KEYS,
  ageFromStamp,
  dispositionForLayer,
  newsSentimentBucket,
  type FreshnessDisposition,
} from '@/lib/voiceFreshness';
import { voiceSpeech } from '@/lib/voiceSpeech';
import { voiceController, type FreshnessRow } from '@/lib/voiceController';
import { getLiveDataBounds } from '@/lib/liveDataViewport';
import { getPollMeta, readDataKey, useDataKey, type PollMeta } from '@/hooks/useDataStore';
import { isPollingPaused } from '@/hooks/useDataPolling';
import { VIEWPORT_COMMITTED_EVENT } from '@/components/map/hooks/useViewportBounds';
import { LAYER_TOGGLE_EVENT } from '@/hooks/useDataPolling';
import type { VoiceAgentBindings } from '@/hooks/useVoiceAgent';

const REGEN_DEBOUNCE_MS = 2500; // §3.6 debounced view-change
/** Ambient briefs stay well under the 30/min hud-summary limiter. */
export const REGEN_MIN_INTERVAL_MS = 45000;
const HEALTH_CACHE_TTL_MS = 60000; // cmd=get_fetch_health cache (§2.4)
/** Test surface for the debounce constant (#27). */
export const REGEN_DEBOUNCE_MS_FOR_TESTS = REGEN_DEBOUNCE_MS;

export const LAYER_PREFERENCES_EVENT = 'sb:layer-preferences-changed';

// ── Snapshot composition ────────────────────────────────────────────────────

function scaleClass(bounds: { south: number; west: number; north: number; east: number } | null): 'world' | 'region' | 'local' {
  if (!bounds) return 'world';
  const latSpan = Math.max(0, bounds.north - bounds.south);
  let lngSpan = bounds.east - bounds.west;
  if (lngSpan < 0) lngSpan += 360;
  if (latSpan >= 120 || lngSpan >= 300) return 'world';
  if (latSpan > 20 || lngSpan > 40) return 'region';
  return 'local';
}

function entityId(item: Record<string, unknown>): string {
  for (const key of ['icao24', 'hex', 'mmsi', 'id', 'callsign', 'name']) {
    const value = item[key];
    if (typeof value === 'string' && value.trim()) return value.slice(0, 24);
    if (typeof value === 'number') return String(value).slice(0, 24);
  }
  return '';
}

function entityName(item: Record<string, unknown>): string {
  for (const key of ['callsign', 'flight', 'name', 'title', 'icao24', 'mmsi', 'hex']) {
    const value = item[key];
    if (typeof value === 'string' && value.trim()) return value.slice(0, 40);
  }
  return '';
}

const ENTITY_LAYERS = ['tracked_flights', 'military_flights', 'private_jets', 'ships'] as const;

function composeEntities(): GroundingSnapshot['entities'] {
  const entities: GroundingSnapshot['entities'] = [];
  for (const layer of ENTITY_LAYERS) {
    const rows = readDataKey(layer);
    if (!Array.isArray(rows)) continue;
    for (const raw of rows.slice(0, 12)) {
      if (!raw || typeof raw !== 'object') continue;
      const item = raw as Record<string, unknown>;
      const id = entityId(item);
      if (!id) continue;
      entities.push({ id, name: entityName(item) || id, layer });
      if (entities.length >= 24) return entities;
    }
  }
  return entities;
}

function composeCounts(activeLayers: Record<string, boolean>): Record<string, number> {
  // Counts come from the client store mirror — non-empty ACTIVE narration
  // layers only; every listed layer says an exact count (0 included, §3.6).
  const counts: Record<string, number> = {};
  for (const layer of NARRATION_LAYER_KEYS) {
    if (activeLayers[layer] === false) continue;
    const rows = readDataKey(layer);
    if (!Array.isArray(rows)) continue;
    counts[layer] = rows.length;
  }
  return counts;
}

interface NewsItem extends Record<string, unknown> {
  title?: unknown;
  sentiment?: unknown;
  machine_assessment?: unknown;
}

function composeNewsVerdicts(): GroundingSnapshot['verdicts']['news'] {
  const rows = readDataKey('news');
  if (!Array.isArray(rows)) return [];
  const items = rows.filter(
    (raw): raw is NewsItem => !!raw && typeof raw === 'object',
  );
  const scored = items
    .map((item) => ({
      title: typeof item.title === 'string' ? item.title.slice(0, 140) : '',
      sentiment: typeof item.sentiment === 'number' && Number.isFinite(item.sentiment) ? item.sentiment : null,
      machine_assessment: typeof item.machine_assessment === 'string' ? item.machine_assessment : '',
    }))
    .sort((a, b) => Math.abs(b.sentiment ?? 0) - Math.abs(a.sentiment ?? 0))
    .slice(0, 5)
    .map((item) => ({ ...item, bucket: newsSentimentBucket(item.sentiment) }));
  return scored;
}

export interface ComposedFreshness {
  rows: FreshnessRow[];
  map: GroundingSnapshot['freshness'];
}

export function composeFreshness(stamps: Record<string, string> | null | undefined, now = Date.now()): ComposedFreshness {
  const rows: FreshnessRow[] = [];
  const map: GroundingSnapshot['freshness'] = {};
  const keys = new Set<string>(NARRATION_LAYER_KEYS);
  if (stamps) for (const key of Object.keys(stamps)) keys.add(key);
  for (const layer of keys) {
    const parent = DERIVED_LAYER_FRESHNESS_PARENT[layer];
    const stampSource = parent ? stamps?.[parent] : stamps?.[layer];
    const age_s = stampSource ? ageFromStamp(stampSource, now) : null;
    const disposition: FreshnessDisposition =
      parent && age_s == null && !stampSource ? 'unknown' : dispositionForLayer(parent ?? layer, age_s);
    const cadence = LAYER_EXPECTED_CADENCE_S[parent ?? layer] ?? null;
    rows.push({ layer, disposition, age_s });
    map[layer] = { age_s, disposition, expected_cadence_s: cadence };
  }
  rows.sort((a, b) => a.layer.localeCompare(b.layer));
  return { rows, map };
}

/** djb2-style stable hash over the regen-relevant projection (fingerprint gate). */
export function groundingFingerprint(snapshot: GroundingSnapshot): string {
  const core = JSON.stringify({
    v: snapshot.view,
    c: snapshot.counts,
    f: snapshot.freshness,
    e: snapshot.entities.map((entity) => entity.id),
    n: snapshot.verdicts.news.map((item) => item.title),
    m: snapshot.session.mode,
    l: snapshot.layers.active,
  });
  let hash = 5381;
  for (let i = 0; i < core.length; i++) hash = ((hash << 5) + hash + core.charCodeAt(i)) >>> 0;
  return hash.toString(36);
}

// ── Health bridge (60 s cached cmd=get_fetch_health) ───────────────────────

interface HealthCache {
  at: number;
  data: GroundingSnapshot['health'];
}
let _healthCache: HealthCache | null = null;

/** Reset the module-level health cache (tests / operator refresh). */
export function resetHealthCacheForTests(): void {
  _healthCache = null;
}

async function fetchHealth(): Promise<GroundingSnapshot['health']> {
  if (_healthCache && Date.now() - _healthCache.at < HEALTH_CACHE_TTL_MS) return _healthCache.data;
  try {
    const res = await fetch(`${API_BASE}/api/ai/channel/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cmd: 'get_fetch_health', args: {} }),
    });
    if (!res.ok) throw new Error(`get_fetch_health ${res.status}`);
    const body = await res.json();
    const data = body?.data;
    const health: GroundingSnapshot['health'] = {};
    if (data && typeof data === 'object') {
      for (const [task, entry] of Object.entries(data as Record<string, unknown>)) {
        if (!entry || typeof entry !== 'object') continue;
        const record = entry as Record<string, unknown>;
        const errorText = record.error ?? record.last_error ?? record.condition;
        health[task] = {
          ok: record.ok !== false,
          error: typeof errorText === 'string' ? errorText.slice(0, 200) : null,
        };
      }
    }
    _healthCache = { at: Date.now(), data: health };
    return health;
  } catch {
    // Health is context, never a blocker — narrate without it.
    return {};
  }
}

// ── Ambient regen gate decision (§2.6 — pure, unit-testable) ────────────────

export type RegenGateVerdict = { ok: true } | { ok: false; reason: string };

/** Every skip must happen BEFORE any network call — disarmed ⇒ zero
 *  hud-summary POSTs (#41/#27). Exported pure so the gate matrix is
 *  unit-testable without rendering the hook. */
export function shouldAttemptRegen(input: {
  controllerPhase: string;
  ambientArmed: boolean;
  pollingPaused: boolean;
  tabHidden: boolean;
  msSinceLastPost: number;
  lastHash: string;
  nextHash: string;
}): RegenGateVerdict {
  if (input.controllerPhase === 'opt-in-required') return { ok: false, reason: 'opt_in_required' };
  if (input.controllerPhase === 'lean-unavailable') return { ok: false, reason: 'mesh_lean' };
  if (!input.ambientArmed) return { ok: false, reason: 'disarmed' };
  if (input.pollingPaused) return { ok: false, reason: 'time_machine_paused' };
  if (input.tabHidden) return { ok: false, reason: 'tab_hidden' };
  if (input.msSinceLastPost < REGEN_MIN_INTERVAL_MS && input.lastHash !== '') {
    return { ok: false, reason: 'min_interval' };
  }
  if (input.nextHash === input.lastHash) return { ok: false, reason: 'fingerprint_unchanged' };
  return { ok: true };
}

// ── The hook ────────────────────────────────────────────────────────────────

export interface UseVoiceGroundingResult {
  /** Compose the current snapshot WITHOUT posting (used by get_grounding_snapshot verb). */
  composeSnapshot: () => Promise<GroundingSnapshot>;
  /** Force one regeneration attempt (manual BRIEF NOW path). */
  requestBrief: () => void;
}

export function useVoiceGrounding(bindings: VoiceAgentBindings): UseVoiceGroundingResult {
  // Freshness merges arrive on every changed delta poll — the exact proxy for
  // version bumps restricted to NARRATION_LAYER_KEYS (§2.6).
  const freshnessStamps = useDataKey('freshness') as unknown as Record<string, string> | undefined;

  const bindingsRef = useRef(bindings);
  bindingsRef.current = bindings;

  const stateRef = useRef({
    timer: null as ReturnType<typeof setTimeout> | null,
    lastPostAt: 0,
    lastHash: '',
    inFlight: false,
  });

  useEffect(() => {
    voiceController.loadAmbientArm();
    voiceSpeech.probe();
    const state = stateRef.current;
    return () => {
      if (state.timer) clearTimeout(state.timer);
    };
  }, []);

  const composeSnapshot = useCallback(async (): Promise<GroundingSnapshot> => {
    const meta: PollMeta = getPollMeta();
    const view = bindingsRef.current.viewSummary();
    const activeLayers = view.activeLayers;
    const bounds = getLiveDataBounds();
    const snapshot: GroundingSnapshot = {
      schema: GROUNDING_SCHEMA_ID,
      generated_at: new Date().toISOString(),
      view: {
        bounds: bounds ? { ...bounds } : null,
        zoom: null,
        scale_class: scaleClass(bounds),
      },
      session: { mode: meta.mode },
      layers: {
        active: Object.keys(activeLayers).filter((key) => activeLayers[key]),
        inactive_count: Object.keys(activeLayers).filter((key) => !activeLayers[key]).length,
      },
      counts: composeCounts(activeLayers),
      entities: composeEntities(),
      correlations: [],
      verdicts: { news: composeNewsVerdicts() },
      freshness: {},
      health: {},
    };
    const correlations = readDataKey('correlations');
    if (Array.isArray(correlations)) {
      snapshot.correlations = correlations
        .filter((c) => !!c && typeof c === 'object')
        .slice(0, 6)
        .map((c) => c as Record<string, unknown>);
    }
    snapshot.freshness = composeFreshness(freshnessStamps ?? null).map;
    snapshot.health = await fetchHealth();

    // Hard cap 6 KB serialized — truncate entities first, then news verdicts.
    let encoded = JSON.stringify(snapshot);
    while (new Blob([encoded]).size > GROUNDING_SNAPSHOT_MAX_BYTES) {
      if (snapshot.entities.length > 0) {
        snapshot.entities = snapshot.entities.slice(0, Math.max(0, snapshot.entities.length - 2));
      } else if (snapshot.verdicts.news.length > 0) {
        snapshot.verdicts.news = snapshot.verdicts.news.slice(0, Math.max(0, snapshot.verdicts.news.length - 1));
      } else {
        break;
      }
      encoded = JSON.stringify(snapshot);
    }
    return snapshot;
  }, [freshnessStamps]);

  const postSummary = useCallback(async (manual: boolean) => {
    const st = stateRef.current;
    if (st.inFlight) return;
    try {
      const snapshot = await composeSnapshot();
      const hash = groundingFingerprint(snapshot);
      const controller = voiceController.getState();
      // Ambient briefs require the session ARM; an explicit operator request
      // ("BRIEF NOW") counts as its own consent and bypasses only that switch.
      const verdict = shouldAttemptRegen({
        controllerPhase: controller.phase,
        ambientArmed: manual ? true : controller.ambientArmed,
        pollingPaused: isPollingPaused(),
        tabHidden: typeof document !== 'undefined' && document.hidden,
        msSinceLastPost: Date.now() - st.lastPostAt,
        lastHash: st.lastHash,
        nextHash: hash,
      });
      if (!verdict.ok) {
        // Gate says no — zero POSTs (the fetch below never runs).
        return;
      }
      st.inFlight = true;
      voiceController.setNarrating(true);
      const res = await fetch(`${API_BASE}/api/voice/hud-summary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snapshot }),
      });
      if (!res.ok) throw new Error(`hud-summary ${res.status}`);
      const body = (await res.json()) as HudSummaryResponse;
      if (!body.ok) throw new Error(body.summary || 'hud-summary failed');
      st.lastHash = hash;
      st.lastPostAt = Date.now();
      voiceController.setNarration({ summary: body.summary, generatedAt: Date.now(), error: null });
      voiceController.setFreshnessRows(composeFreshness(freshnessStamps ?? null).rows);
      voiceSpeech.say(body.summary);
    } catch (err) {
      // Hold-last-good: keep the previous brief, record the verbatim reason.
      const message = err instanceof Error && err.message ? err.message : 'hud-summary unreachable';
      const prev = voiceController.getState().narration;
      voiceController.setNarration({
        summary: prev?.summary ?? '',
        generatedAt: prev?.generatedAt ?? Date.now(),
        error: message,
      });
    } finally {
      st.inFlight = false;
    }
  }, [composeSnapshot, freshnessStamps]);

  /** Ambient gates (§2.6): every skip must happen BEFORE any fetch (#41/#27). */
  const scheduleRegen = useCallback(() => {
    const controller = voiceController.getState();
    if (controller.phase === 'opt-in-required' || controller.phase === 'lean-unavailable') return;
    if (!controller.ambientArmed) return; // disarmed ⇒ zero hud-summary calls
    if (isPollingPaused()) return; // Time-Machine pause
    if (typeof document !== 'undefined' && document.hidden) return; // tab hidden
    const st = stateRef.current;
    if (st.timer) clearTimeout(st.timer);
    st.timer = setTimeout(() => {
      st.timer = null;
      const now = Date.now();
      if (now - st.lastPostAt < REGEN_MIN_INTERVAL_MS) return;
      void postSummary(false); // ambient path — ARM already verified pre-schedule
    }, REGEN_DEBOUNCE_MS);
  }, [postSummary]);

  // Trigger set (§2.6). Viewport commits are event-driven; freshness diffs
  // re-arm through the `freshnessStamps` dependency below.
  useEffect(() => {
    window.addEventListener(VIEWPORT_COMMITTED_EVENT, scheduleRegen);
    window.addEventListener(LAYER_TOGGLE_EVENT, scheduleRegen);
    window.addEventListener(LAYER_PREFERENCES_EVENT, scheduleRegen);
    return () => {
      window.removeEventListener(VIEWPORT_COMMITTED_EVENT, scheduleRegen);
      window.removeEventListener(LAYER_TOGGLE_EVENT, scheduleRegen);
      window.removeEventListener(LAYER_PREFERENCES_EVENT, scheduleRegen);
    };
  }, [scheduleRegen]);

  // Freshness diff trigger — only when armed (gates run before scheduling so
  // a disarmed console performs zero work here).
  useEffect(() => {
    scheduleRegen();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [freshnessStamps]);

  const requestBrief = useCallback(() => {
    void postSummary(true); // explicit operator request bypasses only the ARM switch
  }, [postSummary]);

  return { composeSnapshot, requestBrief };
}
