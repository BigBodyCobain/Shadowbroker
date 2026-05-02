/**
 * useTimeMachine - snapshot playback state for the map.
 *
 * The UI uses this as a media-style transport: a straight timeline, explicit
 * snapshot mode, immediate live restore, and interpolated frames between
 * recorded snapshots for moving entities.
 */

import { useSyncExternalStore } from 'react';
import { API_BASE } from '@/lib/api';
import { mergeData } from './useDataStore';
import { forceRefreshLiveData, pausePolling, resumePolling } from './useDataPolling';

export interface HourlyIndexEntry {
  count: number;
  latest_id: string;
  latest_ts: string;
  snapshot_ids: string[];
}

export interface SnapshotMeta {
  id: string;
  timestamp: string;
  unix_ts: number;
  format?: string;
  layers: string[];
  layer_counts: Record<string, number>;
  profile?: string | null;
}

interface PlaybackSnapshot extends SnapshotMeta {
  snapshot_id: string;
  data: SnapshotData;
}

type SnapshotData = Record<string, unknown>;
type Entity = Record<string, unknown>;
type Listener = () => void;

export interface TimeMachineState {
  mode: 'live' | 'snapshot';
  snapshotId: string | null;
  snapshotTimestamp: string | null;
  currentUnixTs: number | null;
  timelineStart: number | null;
  timelineEnd: number | null;
  snapshots: SnapshotMeta[];
  playing: boolean;
  playbackSpeed: number;
  hourlyIndex: Record<number, HourlyIndexEntry>;
  loading: boolean;
  error: string | null;
}

const MOVING_LAYER_KEYS = new Set([
  'commercial_flights',
  'private_flights',
  'private_jets',
  'military_flights',
  'tracked_flights',
  'uavs',
  'ships',
  'satellites',
  'tinygs_satellites',
  'sigint',
]);

const listeners = new Set<Listener>();
const playbackCache = new Map<string, PlaybackSnapshot>();
const playbackFetches = new Map<string, Promise<PlaybackSnapshot | null>>();

let state: TimeMachineState = {
  mode: 'live',
  snapshotId: null,
  snapshotTimestamp: null,
  currentUnixTs: null,
  timelineStart: null,
  timelineEnd: null,
  snapshots: [],
  playing: false,
  playbackSpeed: 6,
  hourlyIndex: {},
  loading: false,
  error: null,
};

let _playbackTimer: ReturnType<typeof setInterval> | null = null;
let _playbackLastTick = 0;
let _seekSerial = 0;
let _playbackSeeking = false;

function setState(patch: Partial<TimeMachineState>) {
  state = { ...state, ...patch };
  for (const fn of listeners) fn();
}

function getSnapshot() {
  return state;
}

function subscribe(onStoreChange: Listener) {
  listeners.add(onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
  };
}

function numericTs(meta: { unix_ts?: number | null; timestamp?: string | null }): number {
  if (typeof meta.unix_ts === 'number' && Number.isFinite(meta.unix_ts)) return meta.unix_ts;
  if (meta.timestamp) {
    const ms = Date.parse(meta.timestamp);
    if (Number.isFinite(ms)) return ms / 1000;
  }
  return 0;
}

function sortSnapshots(snapshots: SnapshotMeta[]): SnapshotMeta[] {
  return [...snapshots]
    .map((snap) => ({ ...snap, unix_ts: numericTs(snap) }))
    .filter((snap) => snap.id && snap.unix_ts > 0)
    .sort((a, b) => a.unix_ts - b.unix_ts);
}

function updateTimelineFromSnapshots(snapshots: SnapshotMeta[]) {
  setState({
    snapshots,
    timelineStart: snapshots[0]?.unix_ts ?? null,
    timelineEnd: snapshots[snapshots.length - 1]?.unix_ts ?? null,
  });
}

function snapshotIndex(snapshotId: string): number {
  return state.snapshots.findIndex((snap) => snap.id === snapshotId);
}

function prefetchPlaybackSnapshots(snapshotIds: Array<string | null | undefined>) {
  for (const snapshotId of snapshotIds) {
    if (!snapshotId || playbackCache.has(snapshotId) || playbackFetches.has(snapshotId)) continue;
    void fetchPlaybackSnapshot(snapshotId);
  }
}

function snapshotPatch(data: SnapshotData): SnapshotData {
  return { ...data };
}

function stopPlaybackWithError(message: string) {
  setState({ loading: false, error: message, playing: false });
  _stopPlaybackTimer();
}

function asEntityArray(value: unknown): Entity[] | null {
  if (!Array.isArray(value)) return null;
  return value.filter((item): item is Entity => typeof item === 'object' && item !== null);
}

function stringField(entity: Entity, key: string): string {
  const value = entity[key];
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return '';
}

function numberField(entity: Entity, key: string): number | null {
  const value = entity[key];
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function entityKey(layer: string, entity: Entity): string {
  const candidates =
    layer === 'ships'
      ? ['mmsi', 'imo', 'callsign', 'name']
      : layer.includes('satellite')
        ? ['norad_id', 'norad', 'id', 'name']
        : layer === 'sigint'
          ? ['id', 'callsign', 'long_name']
          : ['icao24', 'registration', 'callsign', 'id', 'name'];

  for (const candidate of candidates) {
    const value = stringField(entity, candidate).toLowerCase();
    if (value) return `${layer}:${candidate}:${value}`;
  }
  return '';
}

function interpolateScalar(a: unknown, b: unknown, ratio: number): unknown {
  if (typeof a !== 'number' || typeof b !== 'number') return a;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return a;
  return a + (b - a) * ratio;
}

function interpolateAngle(a: unknown, b: unknown, ratio: number): unknown {
  if (typeof a !== 'number' || typeof b !== 'number') return a;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return a;
  const delta = ((((b - a) % 360) + 540) % 360) - 180;
  return (a + delta * ratio + 360) % 360;
}

function interpolateEntity(layer: string, prev: Entity, next: Entity, ratio: number): Entity | null {
  const prevLat = numberField(prev, 'lat');
  const prevLng = numberField(prev, 'lng');
  const nextLat = numberField(next, 'lat');
  const nextLng = numberField(next, 'lng');
  if (prevLat == null || prevLng == null || nextLat == null || nextLng == null) return null;

  const frame: Entity = { ...prev };
  frame.lat = prevLat + (nextLat - prevLat) * ratio;
  frame.lng = prevLng + (nextLng - prevLng) * ratio;
  frame.alt = interpolateScalar(prev.alt, next.alt, ratio);
  frame.altitude = interpolateScalar(prev.altitude, next.altitude, ratio);
  frame.heading = interpolateAngle(prev.heading, next.heading, ratio);
  frame.true_track = interpolateAngle(prev.true_track, next.true_track, ratio);
  frame.cog = interpolateAngle(prev.cog, next.cog, ratio);
  frame.sog = interpolateScalar(prev.sog, next.sog, ratio);
  frame.speed_knots = interpolateScalar(prev.speed_knots, next.speed_knots, ratio);
  frame._snapshot_interpolated = true;
  frame._snapshot_interpolation_layer = layer;
  return frame;
}

function interpolateSnapshotData(prev: SnapshotData, next: SnapshotData, ratio: number): SnapshotData {
  if (ratio <= 0) return snapshotPatch(prev);
  if (ratio >= 1) return snapshotPatch(next);

  const out = snapshotPatch(prev);

  for (const layer of MOVING_LAYER_KEYS) {
    const prevItems = asEntityArray(prev[layer]);
    const nextItems = asEntityArray(next[layer]);
    if (!prevItems?.length) continue;
    if (!nextItems?.length) {
      out[layer] = [];
      continue;
    }

    const nextByKey = new Map<string, Entity>();
    for (const item of nextItems) {
      const key = entityKey(layer, item);
      if (key) nextByKey.set(key, item);
    }

    const interpolated: Entity[] = [];
    for (const item of prevItems) {
      const key = entityKey(layer, item);
      if (!key) continue;
      const nextItem = nextByKey.get(key);
      if (!nextItem) continue;
      const frame = interpolateEntity(layer, item, nextItem, ratio);
      if (frame) interpolated.push(frame);
    }
    out[layer] = interpolated;
  }

  return out;
}

function findFramePair(unixTs: number): { prev: SnapshotMeta; next: SnapshotMeta | null } | null {
  const snapshots = state.snapshots;
  if (snapshots.length === 0) return null;
  if (unixTs <= snapshots[0].unix_ts) return { prev: snapshots[0], next: null };
  const last = snapshots[snapshots.length - 1];
  if (unixTs >= last.unix_ts) return { prev: last, next: null };

  for (let i = 0; i < snapshots.length - 1; i += 1) {
    const prev = snapshots[i];
    const next = snapshots[i + 1];
    if (unixTs >= prev.unix_ts && unixTs <= next.unix_ts) {
      return { prev, next };
    }
  }
  return { prev: last, next: null };
}

async function fetchPlaybackSnapshot(snapshotId: string): Promise<PlaybackSnapshot | null> {
  const cached = playbackCache.get(snapshotId);
  if (cached) return cached;
  const inflight = playbackFetches.get(snapshotId);
  if (inflight) return inflight;

  const request = (async () => {
    try {
      const res = await fetch(`${API_BASE}/api/ai/timemachine/playback/${snapshotId}`);
      if (!res.ok) return null;
      const json = (await res.json()) as PlaybackSnapshot;
      const snap: PlaybackSnapshot = {
        ...json,
        id: json.snapshot_id || json.id,
        unix_ts: numericTs(json),
        layer_counts: json.layer_counts || {},
        layers: json.layers || Object.keys(json.data || {}),
        data: json.data || {},
      };
      playbackCache.set(snapshotId, snap);
      return snap;
    } finally {
      playbackFetches.delete(snapshotId);
    }
  })();

  playbackFetches.set(snapshotId, request);
  return request;
}

async function loadExactSnapshot(snapshotId: string, pausePlayback: boolean): Promise<void> {
  setState({ loading: true, error: null });
  const serial = ++_seekSerial;
  try {
    const snap = await fetchPlaybackSnapshot(snapshotId);
    if (serial !== _seekSerial) return;
    if (!snap) {
      stopPlaybackWithError('Failed to load snapshot frame.');
      return;
    }
    pausePolling();
    mergeData(snapshotPatch(snap.data));
    setState({
      mode: 'snapshot',
      snapshotId: snap.snapshot_id || snap.id,
      snapshotTimestamp: snap.timestamp,
      currentUnixTs: snap.unix_ts,
      loading: false,
      error: null,
      playing: pausePlayback ? false : state.playing,
    });
    const idx = snapshotIndex(snap.id);
    prefetchPlaybackSnapshots([
      state.snapshots[idx + 1]?.id,
      state.snapshots[idx + 2]?.id,
    ]);
    if (pausePlayback) _stopPlaybackTimer();
  } catch (e) {
    stopPlaybackWithError(`Network error: ${e}`);
  }
}

function _stopPlaybackTimer() {
  if (_playbackTimer) {
    clearInterval(_playbackTimer);
    _playbackTimer = null;
  }
  _playbackSeeking = false;
}

function _startPlaybackTimer() {
  _stopPlaybackTimer();
  _playbackLastTick = performance.now();
  _playbackTimer = setInterval(() => {
    if (state.mode !== 'snapshot' || !state.playing || state.snapshots.length === 0) {
      _stopPlaybackTimer();
      return;
    }
    if (_playbackSeeking) return;

    const now = performance.now();
    const elapsedMs = Math.max(1, now - _playbackLastTick);
    _playbackLastTick = now;

    const currentTs = state.currentUnixTs ?? state.snapshots[0].unix_ts;
    const pair = findFramePair(currentTs + 0.001);
    if (!pair?.next) {
      setState({ playing: false });
      _stopPlaybackTimer();
      return;
    }

    const segmentSeconds = Math.max(1, state.playbackSpeed);
    const segmentGap = Math.max(1, pair.next.unix_ts - pair.prev.unix_ts);
    const advance = segmentGap * (elapsedMs / (segmentSeconds * 1000));
    const nextTs = Math.min(pair.next.unix_ts, currentTs + advance);

    _playbackSeeking = true;
    void seekToTime(nextTs, { keepPlaying: true }).finally(() => {
      _playbackSeeking = false;
    });
  }, 250);
}

export async function refreshSnapshotList(): Promise<void> {
  try {
    const res = await fetch(`${API_BASE}/api/ai/timemachine/snapshots?limit=100`);
    if (!res.ok) return;
    const json = await res.json();
    updateTimelineFromSnapshots(sortSnapshots(json.snapshots || []));
  } catch (e) {
    console.error('Time Machine: failed to fetch snapshots', e);
  }
}

export async function refreshHourlyIndex(): Promise<void> {
  try {
    const [indexRes] = await Promise.all([
      fetch(`${API_BASE}/api/ai/timemachine/hourly-index`),
      refreshSnapshotList(),
    ]);
    if (indexRes.ok) {
      const json = await indexRes.json();
      setState({ hourlyIndex: json.hours || {} });
    }
  } catch (e) {
    console.error('Time Machine: failed to fetch hourly index', e);
  }
}

export async function enterSnapshotMode(snapshotId: string): Promise<void> {
  await loadExactSnapshot(snapshotId, true);
}

export function exitSnapshotMode(): void {
  _stopPlaybackTimer();
  resumePolling();
  setState({
    mode: 'live',
    snapshotId: null,
    snapshotTimestamp: null,
    currentUnixTs: null,
    playing: false,
    loading: false,
    error: null,
  });
  void forceRefreshLiveData();
}

export async function seekToTime(
  unixTs: number,
  options: { keepPlaying?: boolean } = {},
): Promise<void> {
  if (state.snapshots.length === 0) return;
  const pair = findFramePair(unixTs);
  if (!pair) return;

  const serial = ++_seekSerial;
  const waitingOnUncachedFrame =
    !playbackCache.has(pair.prev.id) || Boolean(pair.next && !playbackCache.has(pair.next.id));
  setState({ loading: !options.keepPlaying || waitingOnUncachedFrame, error: null });

  try {
    const prev = await fetchPlaybackSnapshot(pair.prev.id);
    const next = pair.next ? await fetchPlaybackSnapshot(pair.next.id) : null;
    if (serial !== _seekSerial) return;
    if (!prev) {
      stopPlaybackWithError('Failed to fetch playback frame.');
      return;
    }

    const hasNext = Boolean(next && pair.next && pair.next.unix_ts > pair.prev.unix_ts);
    const ratio =
      hasNext && pair.next
        ? Math.max(0, Math.min(1, (unixTs - pair.prev.unix_ts) / (pair.next.unix_ts - pair.prev.unix_ts)))
        : 0;
    const data = hasNext && next ? interpolateSnapshotData(prev.data, next.data, ratio) : snapshotPatch(prev.data);
    const timestamp = new Date(unixTs * 1000).toISOString();

    pausePolling();
    mergeData(data);
    setState({
      mode: 'snapshot',
      snapshotId: prev.snapshot_id || prev.id,
      snapshotTimestamp: timestamp,
      currentUnixTs: unixTs,
      loading: false,
      error: null,
      playing: options.keepPlaying ? state.playing : false,
    });
    const prevIdx = snapshotIndex(prev.id);
    prefetchPlaybackSnapshots([
      pair.next?.id,
      state.snapshots[prevIdx + 2]?.id,
      state.snapshots[prevIdx + 3]?.id,
    ]);
    if (!options.keepPlaying) _stopPlaybackTimer();
  } catch (e) {
    stopPlaybackWithError(`Network error: ${e}`);
  }
}

export async function stepForward(): Promise<void> {
  const snapshots = state.snapshots;
  if (snapshots.length === 0) return;
  const currentTs = state.currentUnixTs ?? snapshots[0].unix_ts;
  const next = snapshots.find((snap) => snap.unix_ts > currentTs + 0.001);
  if (!next) {
    setState({ playing: false });
    _stopPlaybackTimer();
    return;
  }
  await loadExactSnapshot(next.id, true);
}

export async function stepBackward(): Promise<void> {
  const snapshots = state.snapshots;
  if (snapshots.length === 0) return;
  const currentTs = state.currentUnixTs ?? snapshots[snapshots.length - 1].unix_ts;
  const previous = [...snapshots].reverse().find((snap) => snap.unix_ts < currentTs - 0.001);
  if (!previous) return;
  await loadExactSnapshot(previous.id, true);
}

export async function startPlayback(): Promise<void> {
  if (state.snapshots.length === 0) return;
  if (state.mode !== 'snapshot') {
    await seekToTime(state.currentUnixTs ?? state.snapshots[0].unix_ts, { keepPlaying: true });
  }
  setState({ playing: true });
  _startPlaybackTimer();
}

export function togglePlayback(): void {
  if (state.playing) {
    setState({ playing: false });
    _stopPlaybackTimer();
    return;
  }
  void startPlayback();
}

export function setPlaybackSpeed(secondsPerSegment: number): void {
  setState({ playbackSpeed: Math.max(1, secondsPerSegment) });
  if (state.playing) _startPlaybackTimer();
}

export function useTimeMachine(): TimeMachineState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

let _indexRefreshTimer: ReturnType<typeof setInterval> | null = null;
if (typeof window !== 'undefined' && !_indexRefreshTimer) {
  setTimeout(refreshHourlyIndex, 1500);
  _indexRefreshTimer = setInterval(refreshHourlyIndex, 5 * 60 * 1000);
}
