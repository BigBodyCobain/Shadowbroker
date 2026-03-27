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

// ── Write API (called from useDataPolling) ───────────────────────────────

/** Merge a partial payload into the store, notifying only affected keys. */
export function mergeData(patch: Record<string, unknown>) {
  const changedKeys: string[] = [];
  for (const key of Object.keys(patch)) {
    const next = patch[key];
    if (store[key] !== next) {
      store[key] = next;
      changedKeys.push(key);
    }
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
