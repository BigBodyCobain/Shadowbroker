'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE } from '@/lib/api';
import { isPublicReadOnlyRuntime } from '@/lib/publicRuntime';

export type LiveUamapScraperStatus = {
  platform_requires_opt_in: boolean;
  ui_opted_in: boolean;
  scraper_enabled: boolean;
  env_override: 'on' | 'off' | null;
  ui_choice_recorded?: boolean;
  api_configured?: boolean;
  enrichment_enabled?: boolean;
  provider_mode?: 'api' | 'scraper' | 'gdelt-only';
};

export function useLiveUamapScraperOptIn(enabled = true) {
  const [status, setStatus] = useState<LiveUamapScraperStatus | null>(null);
  const choicePromptedRef = useRef(false);

  const refreshStatus = useCallback(async () => {
    if (isPublicReadOnlyRuntime()) {
      setStatus(null);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/liveuamap/scraper-status`);
      if (!res.ok) return;
      const body = (await res.json()) as LiveUamapScraperStatus;
      setStatus(body);
    } catch {
      // Backend may still be starting.
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void refreshStatus();
  }, [enabled, refreshStatus]);

  const setOptIn = useCallback(async (optedIn: boolean) => {
    if (isPublicReadOnlyRuntime()) {
      throw new Error('LiveUAMap controls are available only in the local operator runtime');
    }
    const res = await fetch(`${API_BASE}/api/liveuamap/scraper-opt-in`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opted_in: optedIn }),
    });
    if (!res.ok) {
      throw new Error(`LiveUAMap opt-in failed (${res.status})`);
    }
    const body = (await res.json()) as LiveUamapScraperStatus;
    setStatus(body);
    return body;
  }, []);

  const needsConsentBeforeEnable = useCallback(
    (layerId: string, turningOn: boolean) => {
      if (layerId !== 'global_incidents' || !turningOn) return false;

      const choiceRecorded = status?.ui_choice_recorded ?? status?.ui_opted_in ?? false;
      const shouldOfferBrowserEnrichment =
        Boolean(status?.platform_requires_opt_in) &&
        !choiceRecorded &&
        !status?.api_configured &&
        status?.env_override === null;

      if (
        shouldOfferBrowserEnrichment &&
        !choicePromptedRef.current &&
        typeof window !== 'undefined'
      ) {
        choicePromptedRef.current = true;
        const optedIn = window.confirm(
          "Global Incidents will turn on with GDELT either way. Add optional LiveUAMap pins too? LiveUAMap will see this server's IP. OK enables LiveUAMap; Cancel keeps GDELT-only incidents.",
        );

        // Do not make the Global Incidents toggle wait on an optional provider.
        // Give the layer-state update a moment to reach the backend before the
        // opt-in endpoint opportunistically starts an immediate refresh.
        window.setTimeout(() => {
          void setOptIn(optedIn).catch((error) => {
            console.warn('LiveUAMap preference update failed:', error);
          });
        }, 250);
      }

      // LiveUAMap is enrichment, never a prerequisite for Global Incidents.
      return false;
    },
    [setOptIn, status],
  );

  const confirmOptIn = useCallback(() => setOptIn(true), [setOptIn]);

  return {
    status,
    refreshStatus,
    needsConsentBeforeEnable,
    confirmOptIn,
  };
}
