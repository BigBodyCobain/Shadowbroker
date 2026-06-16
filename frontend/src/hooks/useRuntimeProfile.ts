'use client';

import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/api';

export interface RuntimeGtAnalytics {
  enabled?: boolean;
  operational?: boolean;
  profile?: string;
  lean_node?: boolean;
  recommended?: boolean;
  warning?: string | null;
  experimental?: boolean;
}

export interface RuntimeProfile {
  profile?: string;
  cpu_limit?: number | null;
  memory_limit_mb?: number | null;
  gt_analytics?: RuntimeGtAnalytics;
}

export function useRuntimeProfile(): RuntimeProfile | null {
  const [runtime, setRuntime] = useState<RuntimeProfile | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/health`, { cache: 'no-store' });
        if (!res.ok || cancelled) return;
        const body = await res.json();
        if (!cancelled && body?.runtime) {
          setRuntime(body.runtime as RuntimeProfile);
        }
      } catch {
        /* health unavailable during boot */
      }
    };

    void load();
    const timer = window.setInterval(load, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return runtime;
}

export function gtLeanLayerWarning(runtime: RuntimeProfile | null): string | null {
  const gt = runtime?.gt_analytics;
  if (!gt?.lean_node) return null;
  return (
    gt.warning ||
    'This node is capped at 1 vCPU. Enabling Strategic Risk (Derived OSINT) may slow OSINT fetches.'
  );
}
