import { useEffect, useMemo, useState } from 'react';
import { API_BASE } from '@/lib/api';
import { buildSarAnomaliesGeoJSON, buildSarAoisGeoJSON } from '@/components/map/geojsonBuilders';

export function useMapSarData(ctx: any) {
  const { activeLayers, data, sarAoiListVersion } = ctx;
  const [sarAoisList, setSarAoisList] = useState<any[]>([]);
  useEffect(() => {
    if (!activeLayers.sar) return;
    let cancelled = false;
    const run = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/sar/aois`, { credentials: 'include' });
        if (!res.ok || cancelled) return;
        const body = await res.json();
        if (!cancelled && Array.isArray(body?.aois)) setSarAoisList(body.aois);
      } catch {}
    };
    run();
    const iv = setInterval(run, 120_000);
    return () => { cancelled = true; clearInterval(iv); };
  }, [activeLayers.sar, sarAoiListVersion]);
  const sarAnomaliesGeoJSON = useMemo(
    () => (activeLayers.sar ? buildSarAnomaliesGeoJSON(data?.sar_anomalies) : null),
    [activeLayers.sar, data?.sar_anomalies],
  );
  const sarAoisGeoJSON = useMemo(
    () => (activeLayers.sar ? buildSarAoisGeoJSON(sarAoisList) : null),
    [activeLayers.sar, sarAoisList],
  );
  return { sarAoisList, sarAnomaliesGeoJSON, sarAoisGeoJSON };
}
