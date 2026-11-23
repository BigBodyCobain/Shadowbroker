/**
 * Public viewer data loader. Replaces the app's backend poller.
 *
 * The full app polls its own backend (`/api/live-data/*`). The viewer has no
 * backend: it reads the static files the bridge publishes. It fetches the
 * small manifest on a timer and downloads a data file only when the manifest
 * says that file changed.
 *
 * The exports mirror the app's hook so borrowed panels keep compiling.
 */

import { useEffect } from 'react';
import { mergeData, setBackendStatus, setPollMeta } from './useDataStore';
import { VIEWER_DATA_BASE } from '@/viewer/config';
import { noteManifest, noteUnreachable } from '@/viewer/feedStatus';

export type BackendStatus = 'connecting' | 'connected' | 'disconnected';

/** Kept for borrowed code that listens for it; the viewer never dispatches it. */
export const LAYER_TOGGLE_EVENT = 'sb:layer-toggle';

type FileRef = { f: string; v: string; bytes?: number };
type Manifest = {
  schema: number;
  generated_at: string;
  seq: number;
  cadence?: { fast_s?: number; slow_s?: number };
  bundles?: Record<string, FileRef>;
  keys?: Record<string, FileRef & { tier?: string; count?: number }>;
};

const SUPPORTED_SCHEMA = 1;
const MIN_POLL_MS = 10_000;
const STARTUP_RETRY_MS = 4_000;

let paused = false;
let kick: (() => void) | null = null;

/** Pause live loading (kept for API parity with the app's poller). */
export function pausePolling() {
  paused = true;
}

export function isPollingPaused(): boolean {
  return paused;
}

export function resumePolling() {
  paused = false;
}

/** Resume and reload immediately. */
export async function forceRefreshLiveData(): Promise<void> {
  paused = false;
  kick?.();
}

async function getJson<T>(path: string, version?: string): Promise<T> {
  const url = `${VIEWER_DATA_BASE}/${path}${version ? `?v=${encodeURIComponent(version)}` : ''}`;
  const res = await fetch(url, version ? undefined : { cache: 'no-store' });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export function useDataPolling() {
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let inFlight = false;
    let pollMs = STARTUP_RETRY_MS;
    /** file path -> version already merged into the store */
    const merged = new Map<string, string>();
    /** time stamp of the newest data set already applied */
    let newestAt = 0;

    const schedule = (ms: number) => {
      if (stopped) return;
      if (timer) clearTimeout(timer);
      if (document.hidden) return; // resumed by visibilitychange
      timer = setTimeout(tick, ms);
    };

    const tick = async () => {
      if (stopped || inFlight) return;
      if (paused) {
        schedule(pollMs);
        return;
      }
      inFlight = true;
      try {
        const manifest = await getJson<Manifest>('manifest.json');
        if (manifest.schema !== SUPPORTED_SCHEMA) throw new Error(`unsupported data schema ${manifest.schema}`);
        // The data host can briefly hand back an older copy. Never step back to it.
        const at = Date.parse(manifest.generated_at);
        if (Number.isFinite(at) && at < newestAt) return;
        if (Number.isFinite(at)) newestAt = at;
        noteManifest(manifest.generated_at, manifest.seq);

        const jobs: Promise<void>[] = [];
        for (const ref of Object.values(manifest.bundles || {})) {
          if (merged.get(ref.f) === ref.v) continue;
          jobs.push(
            getJson<Record<string, unknown>>(ref.f, ref.v).then((bundle) => {
              mergeData(bundle);
              merged.set(ref.f, ref.v);
            }),
          );
        }
        for (const [key, ref] of Object.entries(manifest.keys || {})) {
          if (merged.get(ref.f) === ref.v) continue;
          jobs.push(
            getJson<unknown>(ref.f, ref.v).then((value) => {
              mergeData({ [key]: value });
              merged.set(ref.f, ref.v);
            }),
          );
        }
        const results = await Promise.allSettled(jobs);
        if (results.some((r) => r.status === 'rejected')) {
          console.warn('Some data files failed to load; they will be retried');
        }
        setPollMeta({ mode: 'snapshot' });
        setBackendStatus('connected');
        pollMs = Math.max(MIN_POLL_MS, (manifest.cadence?.fast_s || 15) * 1000);
      } catch (error) {
        console.warn('Data host not reachable; will retry', error);
        noteUnreachable();
        setBackendStatus('disconnected');
        pollMs = Math.max(pollMs, MIN_POLL_MS);
      } finally {
        inFlight = false;
        schedule(pollMs); // also after the early return above
      }
    };

    const onVisibility = () => {
      if (document.hidden) {
        if (timer) clearTimeout(timer);
        timer = null;
        return;
      }
      void tick();
    };

    kick = () => void tick();
    document.addEventListener('visibilitychange', onVisibility);
    void tick();

    return () => {
      stopped = true;
      kick = null;
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);
}
