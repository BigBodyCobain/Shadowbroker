import { useEffect, useState } from 'react';
import type { GtDossier } from '@/types/dashboard';
import { API_BASE } from '@/lib/api';

export function useGtDossier(
  lat: number | undefined,
  lng: number | undefined,
  countryName?: string,
  enabled = true,
) {
  const [gtDossier, setGtDossier] = useState<GtDossier | null>(null);
  const [gtDossierLoading, setGtDossierLoading] = useState(false);

  useEffect(() => {
    if (!enabled || lat == null || lng == null) {
      setGtDossier(null);
      setGtDossierLoading(false);
      return;
    }

    let cancelled = false;
    const regions = [
      `${lat.toFixed(2)},${lng.toFixed(2)}`,
      countryName?.trim().toLowerCase(),
    ].filter((value): value is string => Boolean(value));

    const load = async () => {
      setGtDossierLoading(true);
      let best: GtDossier | null = null;
      for (const region of regions) {
        try {
          const response = await fetch(
            `${API_BASE}/api/analytics/dossier/${encodeURIComponent(region)}`,
          );
          if (!response.ok) continue;
          const payload = (await response.json()) as GtDossier;
          if (!payload.enabled) continue;
          if (!best || (payload.current_risk ?? 0) > (best.current_risk ?? 0)) {
            best = { ...payload, region };
          }
        } catch {
          // GT analytics optional — ignore fetch errors
        }
      }
      if (!cancelled) {
        setGtDossier(best);
        setGtDossierLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [lat, lng, countryName, enabled]);

  return { gtDossier, gtDossierLoading };
}