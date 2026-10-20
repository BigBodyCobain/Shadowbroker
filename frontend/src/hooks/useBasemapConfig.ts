'use client';

import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/api';

export type BasemapConfig = {
  /** CARTO basemap API key, or null when none is configured / not yet loaded. */
  cartoApiKey: string | null;
  /** True once the map may render: config arrived, failed, or timed out. */
  loaded: boolean;
};

type BasemapConfigResponse = { carto?: { configured?: boolean; key?: string } };

/** Render the unkeyed map if the config has not arrived by then. */
export const BASEMAP_CONFIG_SOFT_TIMEOUT_MS = 3000;
/** Abort the config request outright after this long. */
export const BASEMAP_CONFIG_HARD_TIMEOUT_MS = 15000;

const PENDING: BasemapConfig = { cartoApiKey: null, loaded: false };
const UNCONFIGURED: BasemapConfig = { cartoApiKey: null, loaded: true };

// Successful responses are cached for the page lifetime and shared by every
// map instance. Failures are not cached so a later mount retries (the backend
// may still have been starting).
let cached: BasemapConfig | null = null;
let inflight: Promise<BasemapConfig> | null = null;

async function requestBasemapConfig(): Promise<BasemapConfig> {
  const controller = new AbortController();
  const hardTimer = setTimeout(() => controller.abort(), BASEMAP_CONFIG_HARD_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}/api/basemap-config`, {
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!res.ok) return UNCONFIGURED;
    const body = (await res.json()) as BasemapConfigResponse;
    const key = String(body?.carto?.key || '').trim();
    cached = { cartoApiKey: key || null, loaded: true };
    return cached;
  } catch {
    return UNCONFIGURED;
  } finally {
    clearTimeout(hardTimer);
    inflight = null;
  }
}

/** Reset module state (tests only). */
export function __resetBasemapConfigCache(): void {
  cached = null;
  inflight = null;
}

export function useBasemapConfig(): BasemapConfig {
  const [config, setConfig] = useState<BasemapConfig>(() => cached ?? PENDING);

  useEffect(() => {
    if (cached) {
      setConfig(cached);
      return;
    }
    let cancelled = false;
    if (!inflight) inflight = requestBasemapConfig();
    // Fail open: a slow or hung config request must not hold the whole map.
    // If the key arrives later the style is rebuilt with it, same as a theme switch.
    const softTimer = setTimeout(() => {
      if (!cancelled) setConfig((current) => (current.loaded ? current : UNCONFIGURED));
    }, BASEMAP_CONFIG_SOFT_TIMEOUT_MS);
    void inflight.then((resolved) => {
      if (!cancelled) setConfig(resolved);
    });
    return () => {
      cancelled = true;
      clearTimeout(softTimer);
    };
  }, []);

  return config;
}
