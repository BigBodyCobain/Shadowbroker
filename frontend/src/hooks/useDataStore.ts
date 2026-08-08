/**
 * Granular reactive data store — replaces the monolithic `data` prop cascade.
 *
 * Components subscribe to individual keys via useDataKey("ships") or
 * useDataKeys(["ships", "sigint"]) and ONLY re-render when those specific
 * keys change.  This eliminates the re-render cascade where every 15-second
 * fast poll forced all 8+ dashboard components to reconcile.
 *
 * Built on React 18 useSyncExternalStore — zero dependencies, tear-free reads.
 */
import { useSyncExternalStore, useRef, useMemo } from "react";
import type { DashboardData } from "@/types/dashboard";
import type { BackendStatus } from "./useDataPolling";

// ── Store singleton ──────────────────────────────────────────────────────
type Listener = () => void;

/** Per-key listener sets — only listeners subscribed to changed keys fire. */
const keyListeners = new Map<string, Set<Listener>>();
/** Global listeners — fire on ANY key change (used by useDataSnapshot). */
const globalListeners = new Set<Listener>();

const store: Record<string, unknown> = {};

let backendStatus: BackendStatus = "connecting";
const statusListeners = new Set<Listener>();

// ── Content-aware equality (stable merge) ────────────────────────────────

/** Cheap O(n) fingerprint for dashboard arrays — id + rounded lat/lng. */
export function arrayFingerprint(arr: unknown[]): string {
  let h = String(arr.length);
  for (let i = 0; i < arr.length; i++) {
    const item = arr[i] as Record<string, unknown> | null | undefined;
    if (item == null || typeof item !== "object") {
      h += `|${item}`;
      continue;
    }
    const id =
      item.icao ?? item.id ?? item.mmsi ?? item.hex ?? item.callsign ?? item.name ?? i;
    const lat = item.lat != null ? Math.round(Number(item.lat) * 100) : "";
    const lng = item.lng != null ? Math.round(Number(item.lng) * 100) : "";
    h += `|${id}:${lat}:${lng}`;
  }
  return h;
}

/**
 * Content-aware equality for mergeData: keep the previous reference when
 * values are equivalent enough that subscribers need not re-render.
 */
export function valuesEquivalent(prev: unknown, next: unknown): boolean {
  if (prev === next) return true;
  if (prev == null || next == null) return prev === next;
  if (typeof prev !== typeof next) return false;
  if (Array.isArray(prev) && Array.isArray(next)) {
    if (prev.length !== next.length) return false;
    if (prev.length === 0) return true;
    // Geo / track layers: cheap id+position fingerprint. Other arrays
    // (news, etc.) fall through as not-equivalent so new refs still notify.
    const sample = prev[0];
    const isGeoish =
      sample != null &&
      typeof sample === "object" &&
      ("lat" in (sample as object) ||
        "lng" in (sample as object) ||
        "icao" in (sample as object) ||
        "icao24" in (sample as object) ||
        "mmsi" in (sample as object));
    if (!isGeoish) return false;
    return arrayFingerprint(prev) === arrayFingerprint(next);
  }
  if (typeof prev === "object" && typeof next === "object") {
    // Shallow: same keys and === values
    const pk = Object.keys(prev as object);
    const nk = Object.keys(next as object);
    if (pk.length !== nk.length) return false;
    for (const k of pk) {
      if ((prev as Record<string, unknown>)[k] !== (next as Record<string, unknown>)[k]) {
        return false;
      }
    }
    return true;
  }
  return prev === next;
}

// ── Write API (called from useDataPolling) ───────────────────────────────

/** Merge a partial payload into the store, notifying only affected keys. */
export function mergeData(patch: Record<string, unknown>) {
  const changedKeys: string[] = [];
  for (const key of Object.keys(patch)) {
    // Protocol / meta fields from live-data — never materialize as layers.
    if (
      key === "mode" ||
      key === "deltas" ||
      key === "layers" ||
      key === "store_version" ||
      key === "layer_versions" ||
      key === "payload_scale" ||
      key === "payload_sampled" ||
      key === "layer_totals" ||
      key === "startup_payload" ||
      key === "bootstrap_payload" ||
      key === "bootstrap_ready"
    ) {
      continue;
    }
    const next = patch[key];
    const prev = store[key];
    if (valuesEquivalent(prev, next)) {
      // Keep previous reference so subscribers do not fire
      store[key] = prev;
      continue;
    }
    store[key] = next;
    changedKeys.push(key);
  }
  // Notify per-key subscribers
  for (const key of changedKeys) {
    const set = keyListeners.get(key);
    if (set) for (const fn of set) fn();
  }
  // Notify global subscribers only if something actually changed
  if (changedKeys.length > 0) {
    for (const fn of globalListeners) fn();
  }
}

function entityIdForLayer(layer: string, item: Record<string, unknown>): string {
  if (layer === "ships") {
    return String(item.mmsi ?? item.id ?? "").trim();
  }
  return String(item.icao24 ?? item.icao ?? item.id ?? item.hex ?? "")
    .trim()
    .toLowerCase();
}

/**
 * Apply row-level upsert/delete patches from `/api/live-data/fast` delta mode.
 * Returns false if a layer patch cannot be applied safely (caller should full-resync).
 */
export function applyLayerDeltas(
  deltas: Record<string, { upsert?: unknown[]; delete?: string[]; version?: number }>,
): boolean {
  const changedKeys: string[] = [];
  for (const [key, patch] of Object.entries(deltas || {})) {
    if (!patch || typeof patch !== "object") return false;
    const prev = store[key];
    const base = Array.isArray(prev) ? (prev as Record<string, unknown>[]) : [];
    const byId = new Map<string, Record<string, unknown>>();
    for (const item of base) {
      if (!item || typeof item !== "object") continue;
      const id = entityIdForLayer(key, item);
      if (id) byId.set(id, item);
    }
    for (const id of patch.delete || []) {
      byId.delete(String(id));
    }
    for (const raw of patch.upsert || []) {
      if (!raw || typeof raw !== "object") continue;
      const item = raw as Record<string, unknown>;
      const id = entityIdForLayer(key, item);
      if (!id) continue;
      byId.set(id, item);
    }
    store[key] = Array.from(byId.values());
    changedKeys.push(key);
  }
  for (const key of changedKeys) {
    const set = keyListeners.get(key);
    if (set) for (const fn of set) fn();
  }
  if (changedKeys.length > 0) {
    for (const fn of globalListeners) fn();
  }
  return true;
}

export function setBackendStatus(next: BackendStatus) {
  if (backendStatus === next) return;
  backendStatus = next;
  for (const fn of statusListeners) fn();
}

// ── Read API (hooks) ─────────────────────────────────────────────────────

/** Subscribe to a single data key.  Component only re-renders when that key's
 *  reference identity changes. */
export function useDataKey<K extends keyof DashboardData>(key: K): DashboardData[K] {
  const subscribe = useMemo(() => {
    return (onStoreChange: Listener) => {
      let set = keyListeners.get(key as string);
      if (!set) {
        set = new Set();
        keyListeners.set(key as string, set);
      }
      set.add(onStoreChange);
      return () => {
        set!.delete(onStoreChange);
        if (set!.size === 0) keyListeners.delete(key as string);
      };
    };
  }, [key]);

  const getSnapshot = useMemo(() => {
    return () => store[key as string] as DashboardData[K];
  }, [key]);

  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Subscribe to multiple keys.  Returns a stable object whose identity only
 *  changes when any of the subscribed keys change. */
export function useDataKeys<K extends keyof DashboardData>(
  keys: readonly K[],
): Pick<DashboardData, K> {
  // Stable key list — avoid re-subscribing on every render
  const keysRef = useRef(keys);
  const keysStr = keys.join(",");
  const stableKeys = useMemo(() => {
    keysRef.current = keys;
    return keys;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keysStr]);

  const subscribe = useMemo(() => {
    return (onStoreChange: Listener) => {
      const unsubs: (() => void)[] = [];
      for (const key of stableKeys) {
        let set = keyListeners.get(key as string);
        if (!set) {
          set = new Set();
          keyListeners.set(key as string, set);
        }
        set.add(onStoreChange);
        unsubs.push(() => {
          set!.delete(onStoreChange);
          if (set!.size === 0) keyListeners.delete(key as string);
        });
      }
      return () => { for (const u of unsubs) u(); };
    };
  }, [stableKeys]);

  // Build a snapshot object whose identity is stable across renders when the
  // underlying values haven't changed.
  const prevRef = useRef<Pick<DashboardData, K> | null>(null);
  const getSnapshot = useMemo(() => {
    return () => {
      const prev = prevRef.current;
      let same = prev !== null;
      const obj = {} as Record<string, unknown>;
      for (const key of stableKeys) {
        const val = store[key as string];
        obj[key as string] = val;
        if (same && prev![key as string as K] !== val) same = false;
      }
      if (same) return prev!;
      const next = obj as Pick<DashboardData, K>;
      prevRef.current = next;
      return next;
    };
  }, [stableKeys]);

  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Subscribe to backend connection status. */
export function useBackendStatus(): BackendStatus {
  const subscribe = useMemo(() => {
    return (onStoreChange: Listener) => {
      statusListeners.add(onStoreChange);
      return () => { statusListeners.delete(onStoreChange); };
    };
  }, []);
  const getSnapshot = useMemo(() => () => backendStatus, []);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Full snapshot — used only by components that genuinely need everything
 *  (e.g. MaplibreViewer).  Re-renders on ANY key change, same as before. */
export function useDataSnapshot(): Record<string, unknown> {
  const prevRef = useRef<Record<string, unknown>>(store);
  const subscribe = useMemo(() => {
    return (onStoreChange: Listener) => {
      globalListeners.add(onStoreChange);
      return () => { globalListeners.delete(onStoreChange); };
    };
  }, []);
  const getSnapshot = useMemo(() => {
    return () => {
      // Return the same store reference — identity changes via globalListeners
      // already guarantee a re-render when mergeData is called.
      prevRef.current = store;
      return store;
    };
  }, []);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
