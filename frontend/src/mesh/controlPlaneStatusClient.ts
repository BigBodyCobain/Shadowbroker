import { controlPlaneJson } from '@/lib/controlPlane';
import { generateNodeKeys, getNodeIdentity } from '@/mesh/meshIdentity';

export interface PrivacyProfileSnapshot {
  profile?: string;
  wormhole_enabled?: boolean;
}

export interface RnsStatusSnapshot {
  enabled: boolean;
  ready: boolean;
  configured_peers: number;
  active_peers: number;
}

export interface InfonetBootstrapSnapshot {
  node_mode?: string;
  bootstrap_state?: string;
  bootstrap_detail?: string;
  manifest_loaded?: boolean;
  manifest_signer_id?: string;
  manifest_valid_until?: number;
  bootstrap_peer_count?: number;
  sync_peer_count?: number;
  push_peer_count?: number;
  operator_peer_count?: number;
  bootstrap_seed_peer_count?: number;
  default_sync_peer_count?: number;
  last_bootstrap_error?: string;
  swarm_sync_peer_count?: number;
  swarm_push_peer_count?: number;
  swarm_manifest_pull?: {
    ok?: boolean;
    skipped?: boolean;
    reason?: string;
    detail?: string;
    retrying?: boolean;
    tried_seed_count?: number;
    peer_count?: number;
    merged_peer_count?: number;
    seed_peer_url?: string;
  };
}

export interface InfonetSyncRuntimeSnapshot {
  last_sync_started_at?: number;
  last_sync_finished_at?: number;
  last_sync_ok_at?: number;
  next_sync_due_at?: number;
  last_peer_url?: string;
  last_error?: string;
  last_outcome?: string;
  current_head?: string;
  fork_detected?: boolean;
  consecutive_failures?: number;
}

export interface InfonetPushResultSnapshot {
  peer_url?: string;
  ok?: boolean;
  error?: string;
  transport?: string;
}

export interface InfonetPushRuntimeSnapshot {
  last_event_id?: string;
  last_push_ok_at?: number;
  last_push_error?: string;
  last_results?: InfonetPushResultSnapshot[];
}

export interface InfonetNodeStatusSnapshot {
  network_id?: string;
  total_events?: number;
  active_events?: number;
  known_nodes?: number;
  author_nodes?: number;
  registered_nodes?: number;
  chain_size_kb?: number;
  head_hash?: string;
  unsigned_events?: number;
  valid?: boolean;
  validation?: string;
  event_types?: Record<string, number>;
  node_mode?: string;
  node_enabled?: boolean;
  bootstrap?: InfonetBootstrapSnapshot;
  sync_runtime?: InfonetSyncRuntimeSnapshot;
  push_runtime?: InfonetPushRuntimeSnapshot;
  private_lane_tier?: string;
  private_transport_required?: boolean;
}

export interface NodeSettingsSnapshot {
  enabled?: boolean;
  timemachine_enabled?: boolean;
  updated_at?: number;
  node_mode?: string;
  node_enabled?: boolean;
}

export interface TorHiddenServiceSnapshot {
  ok?: boolean;
  running?: boolean;
  onion_address?: string;
  detail?: string;
}

const CACHE_TTL_MS = 5000;

type CacheEntry<T> = {
  value: T;
  expiresAt: number;
  inflight: Promise<T> | null;
} | null;

let privacyProfileCache: CacheEntry<PrivacyProfileSnapshot> = null;
let rnsStatusCache: CacheEntry<RnsStatusSnapshot> = null;
let infonetNodeStatusCache: CacheEntry<InfonetNodeStatusSnapshot> = null;

function loadPrivacyProfile(): Promise<PrivacyProfileSnapshot> {
  return controlPlaneJson<PrivacyProfileSnapshot>('/api/settings/privacy-profile', {
    requireAdminSession: false,
  });
}

async function loadRnsStatus(): Promise<RnsStatusSnapshot> {
  const data = await controlPlaneJson<Partial<RnsStatusSnapshot>>('/api/mesh/rns/status', {
    requireAdminSession: false,
  });
  return {
    enabled: Boolean(data?.enabled),
    ready: Boolean(data?.ready),
    configured_peers: Number(data?.configured_peers || 0),
    active_peers: Number(data?.active_peers || 0),
  };
}

function loadInfonetNodeStatus(): Promise<InfonetNodeStatusSnapshot> {
  return controlPlaneJson<InfonetNodeStatusSnapshot>('/api/mesh/infonet/status', {
    requireAdminSession: false,
  });
}

function loadNodeSettings(): Promise<NodeSettingsSnapshot> {
  return controlPlaneJson<NodeSettingsSnapshot>('/api/settings/node', {
    requireAdminSession: false,
  });
}

async function resolveCached<T>(
  cache: CacheEntry<T>,
  loader: () => Promise<T>,
  setCache: (value: CacheEntry<T>) => void,
  force: boolean,
): Promise<T> {
  const now = Date.now();
  if (!force && cache?.value && cache.expiresAt > now) {
    return cache.value;
  }
  if (!force && cache?.inflight) {
    return cache.inflight;
  }
  const inflight = loader()
    .then((value) => {
      setCache({
        value,
        expiresAt: Date.now() + CACHE_TTL_MS,
        inflight: null,
      });
      return value;
    })
    .catch((error) => {
      setCache(cache ? { ...cache, inflight: null } : null);
      throw error;
    });
  setCache({
    value: cache?.value as T,
    expiresAt: 0,
    inflight,
  });
  return inflight;
}

export function invalidatePrivacyProfileCache(): void {
  privacyProfileCache = null;
}

export function invalidateRnsStatusCache(): void {
  rnsStatusCache = null;
}

export function invalidateInfonetNodeStatusCache(): void {
  infonetNodeStatusCache = null;
}

export async function fetchPrivacyProfileSnapshot(
  force: boolean = false,
): Promise<PrivacyProfileSnapshot> {
  return resolveCached(
    privacyProfileCache,
    loadPrivacyProfile,
    (value) => {
      privacyProfileCache = value;
    },
    force,
  );
}

export async function fetchRnsStatusSnapshot(force: boolean = false): Promise<RnsStatusSnapshot> {
  return resolveCached(
    rnsStatusCache,
    loadRnsStatus,
    (value) => {
      rnsStatusCache = value;
    },
    force,
  );
}

export async function fetchInfonetNodeStatusSnapshot(
  force: boolean = false,
): Promise<InfonetNodeStatusSnapshot> {
  return resolveCached(
    infonetNodeStatusCache,
    loadInfonetNodeStatus,
    (value) => {
      infonetNodeStatusCache = value;
    },
    force,
  );
}

export async function fetchNodeSettingsSnapshot(): Promise<NodeSettingsSnapshot> {
  return loadNodeSettings();
}

export async function setInfonetNodeEnabled(enabled: boolean): Promise<NodeSettingsSnapshot> {
  const result = await controlPlaneJson<NodeSettingsSnapshot>('/api/settings/node', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
    requireAdminSession: false,
  });
  invalidateInfonetNodeStatusCache();
  return result;
}

export async function startTorHiddenService(): Promise<TorHiddenServiceSnapshot> {
  return controlPlaneJson<TorHiddenServiceSnapshot>('/api/settings/tor/start', {
    method: 'POST',
    requireAdminSession: false,
  });
}

export async function stopTorHiddenService(): Promise<TorHiddenServiceSnapshot> {
  return controlPlaneJson<TorHiddenServiceSnapshot>('/api/settings/tor/stop', {
    method: 'POST',
    requireAdminSession: false,
  });
}

export interface InfonetSwarmJoinSnapshot {
  ok?: boolean;
  detail?: string;
  announce?: {
    ok?: boolean;
    peer_url?: string;
    skipped?: boolean;
    results?: Array<{ seed_peer_url?: string; ok?: boolean; status_code?: number }>;
  };
  manifest_pull?: {
    ok?: boolean;
    peer_count?: number;
    merged_peer_count?: number;
    seed_peer_url?: string;
    detail?: string;
  };
}

/** Register with the fleet seed and pull the signed peer manifest. */
export async function joinInfonetSwarm(): Promise<InfonetSwarmJoinSnapshot> {
  const result = await controlPlaneJson<InfonetSwarmJoinSnapshot>('/api/mesh/infonet/swarm/join', {
    method: 'POST',
    requireAdminSession: false,
  });
  invalidateInfonetNodeStatusCache();
  return result;
}

/** Warm Tor/Arti, enable the node, and join the private Infonet swarm. */
export async function ensureInfonetParticipantNodeReady(): Promise<void> {
  if (!getNodeIdentity()) {
    await generateNodeKeys().catch(() => null);
  }
  await startTorHiddenService().catch(() => null);
  await setInfonetNodeEnabled(true);
  await joinInfonetSwarm().catch(() => null);
  await fetchInfonetNodeStatusSnapshot(true).catch(() => null);
}
