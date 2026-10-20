'use client';

import { useCallback, useEffect, useState } from 'react';
import { API_BASE } from '@/lib/api';

export type PredictionMarketsStatus = {
  enabled: boolean;
  ui_opted_in: boolean;
  env_override: 'on' | 'off' | null;
  jitter?: {
    scheduler_interval_minutes: number;
    scheduler_jitter_seconds: number;
    pre_fetch_jitter_seconds: number;
  };
};

export function usePredictionMarketsOptIn(enabled = true) {
  const [status, setStatus] = useState<PredictionMarketsStatus | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/prediction-markets/status`);
      if (!res.ok) return;
      const body = (await res.json()) as PredictionMarketsStatus;
      setStatus(body);
    } catch {
      // Backend may still be starting.
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void refreshStatus();
  }, [enabled, refreshStatus]);

  const setOptIn = useCallback(
    async (optedIn: boolean) => {
      const res = await fetch(`${API_BASE}/api/prediction-markets/opt-in`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ opted_in: optedIn }),
      });
      if (!res.ok) {
        throw new Error(`Prediction markets opt-in failed (${res.status})`);
      }
      const body = (await res.json()) as PredictionMarketsStatus;
      setStatus(body);
      return body;
    },
    [],
  );

  return { status, refreshStatus, setOptIn };
}
