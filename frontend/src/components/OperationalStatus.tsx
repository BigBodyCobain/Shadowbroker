'use client';

import { useEffect, useState } from 'react';
import { Activity, CircleAlert, LoaderCircle } from 'lucide-react';
import { API_BASE } from '@/lib/api';

type HealthSnapshot = {
  status?: 'ok' | 'degraded' | 'error';
  last_updated?: string | null;
  sources?: Record<string, unknown>;
};

type StatusState =
  | { kind: 'loading' }
  | { kind: 'ready'; health: HealthSnapshot }
  | { kind: 'unavailable' };

function sourceCount(sources: Record<string, unknown> | undefined): number {
  if (!sources) return 0;
  return Object.values(sources).reduce<number>(
    (total, value) => total + (typeof value === 'number' ? value : 0),
    0,
  );
}

/**
 * A public-safe summary of the backend's own health contract. It deliberately
 * reports an unavailable service instead of presenting decorative activity
 * metrics when the data plane has not answered.
 */
export default function OperationalStatus() {
  const [state, setState] = useState<StatusState>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8_000);

    void fetch(`${API_BASE}/api/health`, { signal: controller.signal, cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) throw new Error(`health ${response.status}`);
        return response.json() as Promise<HealthSnapshot>;
      })
      .then((health) => setState({ kind: 'ready', health }))
      .catch(() => setState({ kind: 'unavailable' }))
      .finally(() => window.clearTimeout(timeout));

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  if (state.kind === 'loading') {
    return (
      <div className="avds-operational-status" role="status" aria-live="polite" data-ui="service-status">
        <LoaderCircle size={15} className="animate-spin" aria-hidden="true" />
        <span>Checking data service</span>
      </div>
    );
  }

  if (state.kind === 'unavailable') {
    return (
      <div className="avds-operational-status avds-operational-status--unavailable" role="status" data-ui="service-status">
        <CircleAlert size={15} aria-hidden="true" />
        <span>Data service is unavailable. Map controls remain available.</span>
      </div>
    );
  }

  const degraded = state.health.status && state.health.status !== 'ok';
  const updated = state.health.last_updated
    ? new Date(state.health.last_updated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : 'not reported';

  return (
    <div
      className={`avds-operational-status${degraded ? ' avds-operational-status--degraded' : ''}`}
      role="status"
      data-ui="service-status"
    >
      <Activity size={15} aria-hidden="true" />
      <span>
        {degraded ? 'Data service degraded' : 'Data service available'} · {sourceCount(state.health.sources)} records · updated {updated}
      </span>
    </div>
  );
}
