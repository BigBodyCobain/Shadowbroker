'use client';

import { useSyncExternalStore } from 'react';
import { VIEWER_STALE_AFTER_MS } from './config';

/** What the viewer knows about the published data's age. */
export type FeedStatus = {
  /** Have we ever read a manifest? */
  loaded: boolean;
  /** The bridge's own timestamp on the latest manifest (ISO). */
  generatedAt: string | null;
  /** Bridge sequence number of the latest manifest. */
  seq: number;
  /** Local clock time when `seq` last changed. */
  seqChangedAt: number;
  /** Times this page has seen the manifest advance since it loaded. */
  advances: number;
  /** Local clock time of the last successful manifest read. */
  lastOkAt: number;
  /** Can we currently reach the data host? */
  reachable: boolean;
};

let status: FeedStatus = {
  loaded: false,
  generatedAt: null,
  seq: 0,
  seqChangedAt: 0,
  advances: 0,
  lastOkAt: 0,
  reachable: true,
};
const listeners = new Set<() => void>();

function emit() {
  for (const fn of listeners) fn();
}

export function noteManifest(generatedAt: string, seq: number): void {
  const now = Date.now();
  const changed = !status.loaded || seq !== status.seq || generatedAt !== status.generatedAt;
  status = {
    loaded: true,
    generatedAt,
    seq,
    seqChangedAt: changed ? now : status.seqChangedAt,
    advances: status.loaded && changed ? status.advances + 1 : status.advances,
    lastOkAt: now,
    reachable: true,
  };
  emit();
}

export function noteUnreachable(): void {
  if (!status.reachable) return;
  status = { ...status, reachable: false };
  emit();
}

export function getFeedStatus(): FeedStatus {
  return status;
}

export function useFeedStatus(): FeedStatus {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => status,
    () => status,
  );
}

/**
 * Age of the data in ms, or null before the first load.
 *
 * Two signals, whichever is worse: the bridge's timestamp against this
 * device's clock, and how long the manifest has gone without changing while
 * this page watched. The second one still works when the visitor's clock is
 * wrong.
 */
export function feedAgeMs(s: FeedStatus, now: number): number | null {
  if (!s.loaded) return null;
  const sinceChange = Math.max(0, now - s.seqChangedAt);
  // Once this page has watched the manifest advance, the feed is provably
  // live and only "time since it last advanced" matters.
  if (s.advances > 0) return sinceChange;
  const stamped = s.generatedAt ? now - Date.parse(s.generatedAt) : NaN;
  return Number.isFinite(stamped) ? Math.max(sinceChange, stamped) : sinceChange;
}

export function feedIsStale(s: FeedStatus, now: number): boolean {
  const age = feedAgeMs(s, now);
  return age !== null && age > VIEWER_STALE_AFTER_MS;
}
