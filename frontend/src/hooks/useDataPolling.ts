import { useEffect, useRef } from "react";
import { API_BASE } from "@/lib/api";
import {
  applyLayerDeltas,
  mergeData,
  setBackendStatus as setStoreBackendStatus,
} from "./useDataStore";
import { appendLiveDataBoundsParams, liveDataBoundsKey } from "@/lib/liveDataViewport";
import { VIEWPORT_COMMITTED_EVENT } from "@/components/map/hooks/useViewportBounds";

export type BackendStatus = 'connecting' | 'connected' | 'disconnected';

const DELTA_LAYER_KEYS = [
  "ships",
  "commercial_flights",
  "military_flights",
  "tracked_flights",
  "private_flights",
  "private_jets",
  "cctv",
  "uavs",
  "liveuamap",
  "gps_jamming",
  "satellites",
  "sigint",
  "trains",
] as const;

function formatLayerVersions(lv: Record<string, number> | null): string | null {
  if (!lv) return null;
  const parts: string[] = [];
  for (const key of DELTA_LAYER_KEYS) {
    const ver = lv[key];
    if (typeof ver === "number" && Number.isFinite(ver)) {
      parts.push(`${key}:${ver}`);
    }
  }
  // Need at least the primary delta layers before requesting deltas.
  if (!parts.some((p) => p.startsWith("ships:") || p.startsWith("commercial_flights:"))) {
    return null;
  }
  return parts.join(",");
}

function ingestFastPayload(
  json: Record<string, unknown>,
  layerVersionsRef: { current: Record<string, number> | null },
): boolean {
  const mode = String(json.mode || "snapshot");
  if (json.layer_versions && typeof json.layer_versions === "object") {
    layerVersionsRef.current = {
      ...(layerVersionsRef.current || {}),
      ...(json.layer_versions as Record<string, number>),
    };
  }

  if (mode === "delta") {
    const deltas = (json.deltas || {}) as Record<
      string,
      { upsert?: unknown[]; delete?: string[]; version?: number }
    >;
    const ok = applyLayerDeltas(deltas);
    if (!ok) return false;
    const layers = (json.layers || {}) as Record<string, unknown>;
    if (layers && Object.keys(layers).length > 0) {
      mergeData(layers);
    }
    if (json.freshness) mergeData({ freshness: json.freshness });
    if (json.cctv_total != null) mergeData({ cctv_total: json.cctv_total });
    if (json.sigint_totals) mergeData({ sigint_totals: json.sigint_totals });
    return true;
  }

  mergeData(json);
  return true;
}

// ---------------------------------------------------------------------------
// Polling pause/resume — used by Time Machine snapshot playback
// ---------------------------------------------------------------------------
let _pollingPaused = false;
/** True while the browser tab is hidden — timers are cleared; refresh on focus. */
let _tabHidden = false;
let _fastEtagRef: { current: string | null } | null = null;
let _slowEtagRef: { current: string | null } | null = null;

/** Pause live data polling (snapshot mode). */
export function pausePolling() {
  _pollingPaused = true;
}

/** Resume live data polling and invalidate ETags for a full refresh. */
export function resumePolling() {
  _pollingPaused = false;
  // Invalidate ETags so the next poll gets fresh data (not 304)
  if (_fastEtagRef) _fastEtagRef.current = null;
  if (_slowEtagRef) _slowEtagRef.current = null;
}

/** Resume live mode and fetch both live tiers immediately instead of waiting for the next poll tick. */
export async function forceRefreshLiveData(): Promise<void> {
  _pollingPaused = false;
  if (_fastEtagRef) _fastEtagRef.current = null;
  if (_slowEtagRef) _slowEtagRef.current = null;

  try {
    const [fastRes, slowRes] = await Promise.all([
      fetch(appendLiveDataBoundsParams(`${API_BASE}/api/live-data/fast`)),
      fetch(appendLiveDataBoundsParams(`${API_BASE}/api/live-data/slow`)),
    ]);

    if (fastRes.ok) {
      if (_fastEtagRef) _fastEtagRef.current = fastRes.headers.get('etag') || null;
      mergeData(await fastRes.json());
    }
    if (slowRes.ok) {
      if (_slowEtagRef) _slowEtagRef.current = slowRes.headers.get('etag') || null;
      mergeData(await slowRes.json());
    }
    if (fastRes.ok || slowRes.ok) {
      setStoreBackendStatus('connected');
    }
  } catch (e) {
    console.error("Failed forcing live data refresh", e);
    setStoreBackendStatus('disconnected');
  }
}
type FastDataProbe = {
  commercial_flights?: unknown[];
  military_flights?: unknown[];
  tracked_flights?: unknown[];
  ships?: unknown[];
  sigint?: unknown[];
  cctv?: unknown[];
  news?: unknown[];
  threat_level?: unknown;
};

function hasMeaningfulFastData(json: FastDataProbe): boolean {
  return (
    (json.commercial_flights?.length || 0) > 100 ||
    (json.military_flights?.length || 0) > 25 ||
    (json.tracked_flights?.length || 0) > 10 ||
    (json.ships?.length || 0) > 100 ||
    (json.sigint?.length || 0) > 100 ||
    (json.cctv?.length || 0) > 100
  );
}

/**
 * Event name dispatched by page.tsx when a layer toggle changes.
 * useDataPolling listens for this to immediately refetch slow-tier data
 * so toggled layers (power plants, GDELT, etc.) appear without the usual
 * 120-second wait.
 */
export const LAYER_TOGGLE_EVENT = 'sb:layer-toggle';

/** Debounce rapid pans; min gap keeps viewport refetches under the 120/min rate limit. */
const VIEWPORT_FAST_REFETCH_DEBOUNCE_MS = 400;
const VIEWPORT_FAST_REFETCH_MIN_INTERVAL_MS = 2500;

/**
 * Polls the backend for fast and slow data tiers.
 *
 * Issue #288: heavy, density-driven layers (vessels, aircraft, gdelt
 * events, fires, sigint, …) are bbox-scoped to the visible map area via
 * `appendLiveDataBoundsParams`. Static reference layers (datacenters,
 * military bases, power plants, satellites, weather, news, …) are NOT
 * filtered backend-side, so panning never reveals an "empty world" of
 * infrastructure. World-zoomed views skip bbox params entirely and hit
 * the shared ETag cache exactly like the pre-#288 behaviour.
 *
 * Viewport commits trigger a debounced fast-tier refetch so regional pans
 * refill aircraft/ships without waiting for the 15s poll cadence. That refetch
 * clears layer-version delta state — row deltas are not bbox-aware for the
 * client's existing arrays, so an empty delta after a pan would leave the
 * previous region's aircraft on screen (or none, after inView culls them).
 *
 * The AIS stream viewport POST (/api/viewport) is still handled separately
 * by useViewportBounds to limit upstream AIS ingestion.
 */
export function useDataPolling() {
  const fastEtag = useRef<string | null>(null);
  const slowEtag = useRef<string | null>(null);

  useEffect(() => {
    // Expose refs so pausePolling/resumePolling can invalidate ETags
    _fastEtagRef = fastEtag;
    _slowEtagRef = slowEtag;
    _tabHidden = typeof document !== 'undefined' && document.hidden;

    let hasData = false;
    let fetchedStartupFastPayload = false;
    let fastTimerId: ReturnType<typeof setTimeout> | null = null;
    let slowTimerId: ReturnType<typeof setTimeout> | null = null;
    let viewportDebounceTimer: ReturnType<typeof setTimeout> | null = null;
    let layerToggleRetryTimer: ReturnType<typeof setTimeout> | null = null;
    const fastAbortRef = { current: null as AbortController | null };
    const slowAbortRef = { current: null as AbortController | null };
    const fastFetchGenRef = { current: 0 };
    const layerVersionsRef = { current: null as Record<string, number> | null };
    let lastViewportFetchKey: string | null = null;
    let lastViewportFetchAt = 0;

    const fetchCriticalBootstrap = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/bootstrap/critical`, {
          headers: { Accept: 'application/json' },
        });
        if (res.ok) {
          setStoreBackendStatus('connected');
          const json = await res.json();
          mergeData(json);
          if (hasMeaningfulFastData(json) || (json.news?.length || 0) > 0 || json.threat_level) {
            hasData = true;
          }
        }
      } catch (e) {
        const aborted =
          typeof e === 'object' &&
          e !== null &&
          'name' in e &&
          (e as { name?: string }).name === 'AbortError';
        if (!aborted) {
          console.warn("Critical bootstrap fetch will retry via live polling", e);
        }
      }
    };

    const abortInFlightFastFetch = () => {
      if (fastAbortRef.current) {
        fastAbortRef.current.abort();
        fastAbortRef.current = null;
      }
    };

    const fetchFastData = async () => {
      if (fastTimerId) {
        clearTimeout(fastTimerId);
        fastTimerId = null;
      }
      // Skip fetch when Time Machine snapshot mode is active
      if (_pollingPaused) { scheduleNext('fast'); return; }

      abortInFlightFastFetch();
      const controller = new AbortController();
      fastAbortRef.current = controller;
      const fetchGen = ++fastFetchGenRef.current;

      try {
        const useStartupPayload = !fetchedStartupFastPayload && !fastEtag.current;
        const headers: Record<string, string> = {};
        if (!useStartupPayload && fastEtag.current) headers['If-None-Match'] = fastEtag.current;
        let url = appendLiveDataBoundsParams(
          `${API_BASE}/api/live-data/fast${useStartupPayload ? '?initial=1' : ''}`,
        );
        const lvParam = !useStartupPayload ? formatLayerVersions(layerVersionsRef.current) : null;
        if (lvParam) {
          url += (url.includes('?') ? '&' : '?') + `lv=${encodeURIComponent(lvParam)}`;
        }
        const res = await fetch(url, {
          headers,
          signal: controller.signal,
        });
        if (fetchGen !== fastFetchGenRef.current) return;
        if (res.status === 304) {
          setStoreBackendStatus('connected');
          scheduleNext('fast', fetchGen);
          return;
        }
        if (res.ok) {
          setStoreBackendStatus('connected');
          // Do not keep the capped startup ETag. The next steady poll should
          // request the full fast dataset and replace the representative first paint.
          fastEtag.current = useStartupPayload ? null : res.headers.get('etag') || null;
          if (useStartupPayload) fetchedStartupFastPayload = true;
          const json = await res.json();
          if (fetchGen !== fastFetchGenRef.current) return;
          const applied = ingestFastPayload(json, layerVersionsRef);
          if (!applied) {
            // Delta apply failed — force a full snapshot next tick.
            layerVersionsRef.current = null;
            fastEtag.current = null;
          } else if (hasMeaningfulFastData(json) || json.mode === 'delta') {
            hasData = true;
          }
        }
      } catch (e) {
        const aborted =
          typeof e === 'object' &&
          e !== null &&
          'name' in e &&
          (e as { name?: string }).name === 'AbortError';
        if (!aborted) {
          console.warn("Fast live data fetch will retry after runtime is reachable", e);
          setStoreBackendStatus('disconnected');
        }
      } finally {
        if (fastAbortRef.current === controller) {
          fastAbortRef.current = null;
        }
      }
      scheduleNext('fast', fetchGen);
    };

    const fetchSlowData = async () => {
      if (_pollingPaused) { scheduleNext('slow'); return; }
      if (slowAbortRef.current) return;
      const controller = new AbortController();
      slowAbortRef.current = controller;
      try {
        const headers: Record<string, string> = {};
        if (slowEtag.current) headers['If-None-Match'] = slowEtag.current;
        const res = await fetch(
          appendLiveDataBoundsParams(`${API_BASE}/api/live-data/slow`),
          {
            headers,
            signal: controller.signal,
          },
        );
        if (res.status === 304) { scheduleNext('slow'); return; }
        if (res.ok) {
          slowEtag.current = res.headers.get('etag') || null;
          const json = await res.json();
          mergeData(json);
        }
      } catch (e) {
        const aborted =
          typeof e === 'object' &&
          e !== null &&
          'name' in e &&
          (e as { name?: string }).name === 'AbortError';
        if (!aborted) {
          console.warn("Slow live data fetch will retry after runtime is reachable", e);
        }
      } finally {
        if (slowAbortRef.current === controller) {
          slowAbortRef.current = null;
        }
      }
      scheduleNext('slow');
    };

    // Adaptive polling: retry every 3s during startup, back off to normal cadence once data arrives
    const scheduleNext = (tier: 'fast' | 'slow', fetchGen?: number) => {
      // Pause scheduling while the tab is backgrounded; visibilitychange resumes with a refresh.
      if (_tabHidden || document.hidden) return;
      if (tier === 'fast') {
        if (fetchGen !== undefined && fetchGen !== fastFetchGenRef.current) return;
        const delay = hasData ? 15000 : 3000; // 3s startup retry → 15s steady state
        const needsFullFastPayload = fetchedStartupFastPayload && !fastEtag.current;
        fastTimerId = setTimeout(fetchFastData, needsFullFastPayload ? 750 : delay);
      } else {
        const delay = hasData ? 120000 : 5000; // 5s startup retry → 120s steady state
        slowTimerId = setTimeout(fetchSlowData, delay);
      }
    };

    const clearPollTimers = () => {
      if (fastTimerId) {
        clearTimeout(fastTimerId);
        fastTimerId = null;
      }
      if (slowTimerId) {
        clearTimeout(slowTimerId);
        slowTimerId = null;
      }
    };

    const onVisibilityChange = () => {
      if (document.hidden) {
        _tabHidden = true;
        clearPollTimers();
        return;
      }
      _tabHidden = false;
      // Resume with one refresh on focus so the UI doesn't feel stuck.
      // Keep ETags — 304 is fine when nothing changed. Still respect Time Machine pause.
      if (_pollingPaused) return;
      void fetchFastData();
      void fetchSlowData();
    };

    const fireViewportFastRefetch = () => {
      if (_pollingPaused || _tabHidden || document.hidden) return;

      // null bounds → world-scale fetch; still refetch when leaving a region
      // so the store is not stuck with the previous bbox-filtered arrays.
      const currentFetchKey = liveDataBoundsKey() ?? '__world__';
      if (currentFetchKey === lastViewportFetchKey) return;

      const now = Date.now();
      const waitMs = VIEWPORT_FAST_REFETCH_MIN_INTERVAL_MS - (now - lastViewportFetchAt);
      if (waitMs > 0) {
        // Do not drop the pan — retry when the rate window opens.
        if (viewportDebounceTimer) clearTimeout(viewportDebounceTimer);
        viewportDebounceTimer = setTimeout(() => {
          viewportDebounceTimer = null;
          fireViewportFastRefetch();
        }, waitMs);
        return;
      }

      lastViewportFetchKey = currentFetchKey;
      lastViewportFetchAt = now;
      fastEtag.current = null;
      // Force a bbox-scoped snapshot. Delta mode only patches rows that changed
      // in the store; it cannot replace "Europe flights" with "America flights".
      layerVersionsRef.current = null;
      void fetchFastData();
    };

    const queueViewportFastRefetch = () => {
      if (_pollingPaused || _tabHidden || document.hidden) return;

      const fetchKey = liveDataBoundsKey() ?? '__world__';
      if (fetchKey === lastViewportFetchKey) return;

      if (viewportDebounceTimer) clearTimeout(viewportDebounceTimer);
      viewportDebounceTimer = setTimeout(() => {
        viewportDebounceTimer = null;
        fireViewportFastRefetch();
      }, VIEWPORT_FAST_REFETCH_DEBOUNCE_MS);
    };

    // When a layer toggle fires, refetch live tiers immediately and one follow-up
    // retry so network-heavy on-enable fetches (FIRMS, PSK, …) can land without
    // a multi-retry storm (was 1s/2.5s/5s → up to 8 requests).
    const onLayerToggle = () => {
      slowEtag.current = null;
      fastEtag.current = null;
      // Force full snapshot after toggle — deltas may miss cold-layer fills.
      layerVersionsRef.current = null;
      if (slowTimerId) clearTimeout(slowTimerId);
      slowTimerId = null;
      if (layerToggleRetryTimer) {
        clearTimeout(layerToggleRetryTimer);
        layerToggleRetryTimer = null;
      }
      void fetchFastData();
      void fetchSlowData();
      layerToggleRetryTimer = setTimeout(() => {
        layerToggleRetryTimer = null;
        if (_pollingPaused || _tabHidden || document.hidden) return;
        slowEtag.current = null;
        fastEtag.current = null;
        void fetchSlowData();
        void fetchFastData();
      }, 2500);
    };
    window.addEventListener(LAYER_TOGGLE_EVENT, onLayerToggle);
    window.addEventListener(VIEWPORT_COMMITTED_EVENT, queueViewportFastRefetch);
    document.addEventListener('visibilitychange', onVisibilityChange);

    void (async () => {
      await fetchCriticalBootstrap();
      fetchFastData();
      // Let the bootstrap/fast payload paint before competing with the slow tier.
      slowTimerId = setTimeout(fetchSlowData, 5000);
    })();

    return () => {
      window.removeEventListener(LAYER_TOGGLE_EVENT, onLayerToggle);
      window.removeEventListener(VIEWPORT_COMMITTED_EVENT, queueViewportFastRefetch);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      clearPollTimers();
      if (viewportDebounceTimer) clearTimeout(viewportDebounceTimer);
      if (layerToggleRetryTimer) clearTimeout(layerToggleRetryTimer);
      abortInFlightFastFetch();
      if (slowAbortRef.current) slowAbortRef.current.abort();
    };
  }, []);

  // Data and backend status are now accessed via useDataStore hooks
  // (useDataKey, useDataKeys, useDataSnapshot, useBackendStatus).
  // This hook is a pure side-effect — it starts polling and writes to the store.
}
