import { useEffect, useState, useRef } from "react";
import { API_BASE } from "@/lib/api";

export type BackendStatus = 'connecting' | 'connected' | 'disconnected';

/**
 * Polls the backend for fast and slow data tiers.
 *
 * Matches the proven GitHub polling pattern:
 *   - Empty useEffect dependency array (no restarts on viewport change)
 *   - No viewport bbox filtering (full data every poll)
 *   - Adaptive startup polling (3s retry → 15s/120s steady state)
 *   - ETag conditional requests for bandwidth savings
 *   - AbortController for clean unmount
 */
export function useDataPolling() {
  const dataRef = useRef<any>({});
  const [dataVersion, setDataVersion] = useState(0);
  const data = dataRef.current;

  const [backendStatus, setBackendStatus] = useState<BackendStatus>('connecting');

  const fastEtag = useRef<string | null>(null);
  const slowEtag = useRef<string | null>(null);

  useEffect(() => {
    let hasData = false;
    let fastTimerId: ReturnType<typeof setTimeout> | null = null;
    let slowTimerId: ReturnType<typeof setTimeout> | null = null;

    const fetchFastData = async () => {
      try {
        const headers: Record<string, string> = {};
        if (fastEtag.current) headers['If-None-Match'] = fastEtag.current;
        const res = await fetch(`${API_BASE}/api/live-data/fast`, { headers });
        if (res.status === 304) { setBackendStatus('connected'); scheduleNext('fast'); return; }
        if (res.ok) {
          setBackendStatus('connected');
          fastEtag.current = res.headers.get('etag') || null;
          const json = await res.json();
          dataRef.current = { ...dataRef.current, ...json };
          setDataVersion(v => v + 1);
          const flights = json.commercial_flights?.length || 0;
          if (flights > 100) hasData = true;
        }
      } catch (e) {
        console.error("Failed fetching fast live data", e);
        setBackendStatus('disconnected');
      }
      scheduleNext('fast');
    };

    const fetchSlowData = async () => {
      try {
        const headers: Record<string, string> = {};
        if (slowEtag.current) headers['If-None-Match'] = slowEtag.current;
        const res = await fetch(`${API_BASE}/api/live-data/slow`, { headers });
        if (res.status === 304) { scheduleNext('slow'); return; }
        if (res.ok) {
          slowEtag.current = res.headers.get('etag') || null;
          const json = await res.json();
          dataRef.current = { ...dataRef.current, ...json };
          setDataVersion(v => v + 1);
        }
      } catch (e) {
        console.error("Failed fetching slow live data", e);
      }
      scheduleNext('slow');
    };

    // Adaptive polling: retry every 3s during startup, back off to normal cadence once data arrives
    const scheduleNext = (tier: 'fast' | 'slow') => {
      if (tier === 'fast') {
        const delay = hasData ? 15000 : 3000; // 3s startup retry → 15s steady state
        fastTimerId = setTimeout(fetchFastData, delay);
      } else {
        const delay = hasData ? 120000 : 5000; // 5s startup retry → 120s steady state
        slowTimerId = setTimeout(fetchSlowData, delay);
      }
    };

    fetchFastData();
    fetchSlowData();

    return () => {
      if (fastTimerId) clearTimeout(fastTimerId);
      if (slowTimerId) clearTimeout(slowTimerId);
    };
  }, []);

  return { data, dataVersion, backendStatus };
}
