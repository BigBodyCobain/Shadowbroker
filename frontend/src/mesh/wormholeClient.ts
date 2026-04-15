import { API_BASE } from '@/lib/api';
import { controlPlaneFetch } from '@/lib/controlPlane';

export interface WormholeState {
  installed: boolean;
  configured: boolean;
  running: boolean;
  ready: boolean;
  transport_tier?: string;
  transport_configured: string;
  transport_active: string;
  arti_ready?: boolean;
  proxy_active: string;
  last_error: string;
  started_at: number;
  pid: number;
  privacy_level_effective: string;
  reason: string;
  last_restart: number;
  last_start: number;
  transport: string;
  proxy: string;
  anonymous_mode?: boolean;
  anonymous_mode_ready?: boolean;
  rns_enabled?: boolean;
  rns_ready?: boolean;
  rns_configured_peers?: number;
  rns_active_peers?: number;
  rns_private_dm_direct_ready?: boolean;
  recent_private_clearnet_fallback?: boolean;
  recent_private_clearnet_fallback_at?: number;
  recent_private_clearnet_fallback_reason?: string;
}

export interface WormholeSettingsSnapshot {
  enabled?: boolean;
  transport?: string;
  socks_proxy?: string;
  socks_dns?: boolean;
  anonymous_mode?: boolean;
  privacy_profile?: string;
}

export interface WormholeJoinResponse {
  ok: boolean;
  identity?: {
    node_id: string;
    public_key: string;
    public_key_algo: string;
  };
  runtime?: WormholeState;
  settings?: WormholeSettingsSnapshot;
}

const CACHE_TTL_MS = 15000;

let wormholeStateCache:
  | {
      value: WormholeState;
      expiresAt: number;
      inflight: Promise<WormholeState> | null;
    }
  | null = null;
let wormholeSettingsCache:
  | {
      value: WormholeSettingsSnapshot;
      expiresAt: number;
      inflight: Promise<WormholeSettingsSnapshot> | null;
    }
  | null = null;

async function parseState(res: Response): Promise<WormholeState> {
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data?.detail || data?.message || 'Wormhole request failed');
  }
  return (await res.json()) as WormholeState;
}

function resetWormholeCaches(): void {
  wormholeStateCache = null;
  wormholeSettingsCache = null;
}

async function loadWormholeState(): Promise<WormholeState> {
  const res = await fetch(`${API_BASE}/api/wormhole/status`, { cache: 'no-store' });
  return parseState(res);
}

async function loadWormholeSettings(): Promise<WormholeSettingsSnapshot> {
  const res = await fetch(`${API_BASE}/api/settings/wormhole`, { cache: 'no-store' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data?.detail || data?.message || 'Wormhole settings request failed');
  }
  return (await res.json()) as WormholeSettingsSnapshot;
}

export function invalidateWormholeRuntimeCache(): void {
  resetWormholeCaches();
}

export async function fetchWormholeState(force: boolean = false): Promise<WormholeState> {
  const now = Date.now();
  if (!force && wormholeStateCache?.value && wormholeStateCache.expiresAt > now) {
    return wormholeStateCache.value;
  }
  if (!force && wormholeStateCache?.inflight) {
    return wormholeStateCache.inflight;
  }
  const inflight = loadWormholeState()
    .then((value) => {
      wormholeStateCache = {
        value,
        expiresAt: Date.now() + CACHE_TTL_MS,
        inflight: null,
      };
      return value;
    })
    .catch((error) => {
      if (wormholeStateCache) wormholeStateCache.inflight = null;
      throw error;
    });
  wormholeStateCache = {
    value: wormholeStateCache?.value || ({} as WormholeState),
    expiresAt: 0,
    inflight,
  };
  return inflight;
}

export async function fetchWormholeSettings(
  force: boolean = false,
): Promise<WormholeSettingsSnapshot> {
  const now = Date.now();
  if (!force && wormholeSettingsCache?.value && wormholeSettingsCache.expiresAt > now) {
    return wormholeSettingsCache.value;
  }
  if (!force && wormholeSettingsCache?.inflight) {
    return wormholeSettingsCache.inflight;
  }
  const inflight = loadWormholeSettings()
    .then((value) => {
      wormholeSettingsCache = {
        value,
        expiresAt: Date.now() + CACHE_TTL_MS,
        inflight: null,
      };
      return value;
    })
    .catch((error) => {
      if (wormholeSettingsCache) wormholeSettingsCache.inflight = null;
      throw error;
    });
  wormholeSettingsCache = {
    value: wormholeSettingsCache?.value || {},
    expiresAt: 0,
    inflight,
  };
  return inflight;
}

export async function connectWormhole(): Promise<WormholeState> {
  resetWormholeCaches();
  const res = await controlPlaneFetch('/api/wormhole/connect', {
    method: 'POST',
  });
  const state = await parseState(res);
  wormholeStateCache = {
    value: state,
    expiresAt: Date.now() + CACHE_TTL_MS,
    inflight: null,
  };
  return state;
}

export async function disconnectWormhole(): Promise<WormholeState> {
  resetWormholeCaches();
  const res = await controlPlaneFetch('/api/wormhole/disconnect', {
    method: 'POST',
  });
  const state = await parseState(res);
  wormholeStateCache = {
    value: state,
    expiresAt: Date.now() + CACHE_TTL_MS,
    inflight: null,
  };
  return state;
}

export async function restartWormhole(): Promise<WormholeState> {
  resetWormholeCaches();
  const res = await controlPlaneFetch('/api/wormhole/restart', {
    method: 'POST',
  });
  const state = await parseState(res);
  wormholeStateCache = {
    value: state,
    expiresAt: Date.now() + CACHE_TTL_MS,
    inflight: null,
  };
  return state;
}

export async function joinWormhole(): Promise<WormholeJoinResponse> {
  resetWormholeCaches();
  const res = await controlPlaneFetch('/api/wormhole/join', {
    method: 'POST',
    requireAdminSession: false,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data?.detail || data?.message || 'Wormhole join failed');
  }
  const data = (await res.json()) as WormholeJoinResponse;
  if (data?.runtime) {
    wormholeStateCache = {
      value: data.runtime,
      expiresAt: Date.now() + CACHE_TTL_MS,
      inflight: null,
    };
  }
  if (data?.settings) {
    wormholeSettingsCache = {
      value: data.settings,
      expiresAt: Date.now() + CACHE_TTL_MS,
      inflight: null,
    };
  }
  return data;
}

export async function leaveWormhole(): Promise<WormholeJoinResponse> {
  resetWormholeCaches();
  const res = await controlPlaneFetch('/api/wormhole/leave', {
    method: 'POST',
    requireAdminSession: false,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data?.detail || data?.message || 'Wormhole leave failed');
  }
  const data = (await res.json()) as WormholeJoinResponse;
  if (data?.runtime) {
    wormholeStateCache = {
      value: data.runtime,
      expiresAt: Date.now() + CACHE_TTL_MS,
      inflight: null,
    };
  }
  if (data?.settings) {
    wormholeSettingsCache = {
      value: data.settings,
      expiresAt: Date.now() + CACHE_TTL_MS,
      inflight: null,
    };
  }
  return data;
}
