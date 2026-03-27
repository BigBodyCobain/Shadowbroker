import { useEffect, useRef } from "react";
import { API_BASE } from "@/lib/api";
import { mergeData, setBackendStatus as setStoreBackendStatus } from "./useDataStore";

export type BackendStatus = 'connecting' | 'connected' | 'disconnected';
type FastDataProbe = {
  commercial_flights?: unknown[];
  military_flights?: unknown[];
  tracked_flights?: unknown[];
  ships?: unknown[];
  sigint?: unknown[];
  cctv?: unknown[];
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

/**
 * Polls the backend for fast and slow data tiers.
 *
 * All data is fetched globally (no bbox filtering) — the backend returns its
 * full in-memory cache and MapLibre culls off-screen entities on the GPU.
 * This eliminates the "empty map when zooming out" lag.
 *
 * The AIS stream viewport POST (/api/viewport) is still handled separately
 * by useViewportBounds to limit upstream AIS ingestion.
 */
export function useDataPolling() {
  const fastEtag = useRef<string | null>(null);
  const slowEtag = useRef<string | null>(null);

  useEffect(() => {
    let hasData = false;
    let fastTimerId: ReturnType<typeof setTimeout> | null = null;
    let slowTimerId: ReturnType<typeof setTimeout> | null = null;
    const fastAbortRef = { current: null as AbortController | null };
    const slowAbortRef = { current: null as AbortController | null };

    const fetchFastData = async () => {
      if (fastTimerId) {
        clearTimeout(fastTimerId);
        fastTimerId = null;
      }
      if (fastAbortRef.current) return;
      const controller = new AbortController();
      fastAbortRef.current = controller;
      try {
        const headers: Record<string, string> = {};
        if (fastEtag.current) headers['If-None-Match'] = fastEtag.current;
        const res = await fetch(`${API_BASE}/api/live-data/fast`, {
          headers,
          signal: controller.signal,
        });
        if (res.status === 304) {
          setStoreBackendStatus('connected');
          scheduleNext('fast');
          return;
        }
        if (res.ok) {
          setStoreBackendStatus('connected');
          fastEtag.current = res.headers.get('etag') || null;
          const json = await res.json();
          mergeData(json);
          if (hasMeaningfulFastData(json)) hasData = true;
        }
      } catch (e) {
        const aborted =
          typeof e === 'object' &&
          e !== null &&
          'name' in e &&
          (e as { name?: string }).name === 'AbortError';
        if (!aborted) {
          console.error("Failed fetching fast live data", e);
          setStoreBackendStatus('disconnected');
        }
      } finally {
        if (fastAbortRef.current === controller) {
          fastAbortRef.current = null;
        }
      }
      scheduleNext('fast');
    };

    const fetchSlowData = async () => {
      if (slowAbortRef.current) return;
      const controller = new AbortController();
      slowAbortRef.current = controller;
      try {
        const headers: Record<string, string> = {};
        if (slowEtag.current) headers['If-None-Match'] = slowEtag.current;
        const res = await fetch(`${API_BASE}/api/live-data/slow`, {
          headers,
          signal: controller.signal,
        });
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
          console.error("Failed fetching slow live data", e);
        }
      } finally {
        if (slowAbortRef.current === controller) {
          slowAbortRef.current = null;
        }
      }
      scheduleNext('slow');
    };

    // Adaptive polling: retry every 3s during startup, back off to normal cadence once data arrives
    const scheduleNext = (tier: 'fast' | 'slow') => {
      if (tier === 'fast') {
        const delay = hasData ? 15000 : 3000; // 3s startup retry → 15s steady state
        fastTimerId = setTimeout(fetchFastData, delay);
      } else {
        const delay = hasData ? 120000 : 5000; // 5s startup retry → 120s steady state
        slowTimerId = setTimeout(fetchSlowData, delay);
      }
    };

    // When a layer toggle fires, immediately refetch slow data so the user
    // doesn't wait up to 120s for power plants / GDELT / etc. to appear.
    const onLayerToggle = () => {
      slowEtag.current = null;           // invalidate ETag → guarantees fresh payload
      if (slowTimerId) clearTimeout(slowTimerId);
      slowTimerId = null;
      fetchSlowData();
    };
    window.addEventListener(LAYER_TOGGLE_EVENT, onLayerToggle);

    fetchFastData();
    fetchSlowData();

    return () => {
      window.removeEventListener(LAYER_TOGGLE_EVENT, onLayerToggle);
      if (fastTimerId) clearTimeout(fastTimerId);
      if (slowTimerId) clearTimeout(slowTimerId);
      if (fastAbortRef.current) fastAbortRef.current.abort();
      if (slowAbortRef.current) slowAbortRef.current.abort();
    };
  }, []);

  // Data and backend status are now accessed via useDataStore hooks
  // (useDataKey, useDataKeys, useDataSnapshot, useBackendStatus).
  // This hook is a pure side-effect — it starts polling and writes to the store.
}
