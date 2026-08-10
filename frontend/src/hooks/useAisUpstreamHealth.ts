/**
 * useAisUpstreamHealth — polls /api/health and exposes AIS proxy connectivity.
 *
 * Background: AISStream's WebSocket server went fully offline 2026-05-23 (TCP
 * timeouts at stream.aisstream.io). The backend kept reconnecting in a tight
 * loop and the ships layer silently went empty. Users had no signal that the
 * problem was upstream, not their config. This hook surfaces the state so a
 * banner can explain "AIS upstream is offline" instead of letting users
 * wonder.
 *
 * When AISStream is silent, the backend can still fill ships via AISHub REST
 * (`AISHUB_USERNAME`) on a slow cadence. ``aishubConfigured`` tells the banner
 * whether to nudge the operator to add that backup or confirm it is active.
 *
 * The poll interval is intentionally relaxed (30s) — this is a low-urgency UX
 * signal, not a real-time data feed. Backend already escalates top_status to
 * "degraded" when AIS is configured-but-disconnected.
 */
import { useEffect, useRef, useState } from 'react';
import { API_BASE } from '@/lib/api';

export interface AisUpstreamHealth {
  /** True when we've received a vessel message in the last ~60s. */
  connected: boolean;
  /** Seconds since the last vessel message; null when we've never seen one. */
  lastMsgAgeSeconds: number | null;
  /**
   * True when the SPKI-pinned fallback is in effect (issue #258).
   * Data still flows in this mode — it's a separate, less urgent signal
   * than ``connected``.
   */
  degradedTls: boolean;
  /** How many times the proxy has been spawned (sustained growth without
   *  ``connected`` means upstream is dead and we're respawning in a loop). */
  proxySpawnCount: number;
  /** Whether the operator has configured an API key. When false, the banner
   *  shouldn't fire because "AIS is off" is the intended state. The backend
   *  signals this via the ``connected`` flag being false AND no msg ever
   *  seen — we approximate it by requiring at least one spawn before
   *  declaring an outage. */
  aisEnabled: boolean;
  /** True when ``AISHUB_USERNAME`` is set so the REST backup can run. */
  aishubConfigured: boolean;
}

const POLL_INTERVAL_MS = 30_000;

export function useAisUpstreamHealth(): AisUpstreamHealth | null {
  const [health, setHealth] = useState<AisUpstreamHealth | null>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;

    const fetchHealth = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/health`, { cache: 'no-store' });
        if (!res.ok) return;
        const body = await res.json();
        if (cancelledRef.current) return;
        const proxy = body?.ais_proxy ?? {};
        // ``proxy_spawn_count > 0`` is the cheapest "AIS is enabled" check:
        // if the backend never spawned the proxy (no API key, opt-out env)
        // we shouldn't ever show the outage banner. Once the proxy has
        // spawned at least once we know the operator wants AIS data.
        const spawns = Number(proxy.proxy_spawn_count ?? 0);
        setHealth({
          connected: Boolean(proxy.connected),
          lastMsgAgeSeconds:
            proxy.last_msg_age_seconds == null
              ? null
              : Number(proxy.last_msg_age_seconds),
          degradedTls: Boolean(proxy.degraded_tls),
          proxySpawnCount: spawns,
          aisEnabled: spawns > 0,
          aishubConfigured: Boolean(proxy.aishub_configured),
        });
      } catch {
        // Backend unreachable — separate problem. Banner not relevant.
      }
    };

    void fetchHealth();
    const interval = setInterval(() => void fetchHealth(), POLL_INTERVAL_MS);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
    };
  }, []);

  return health;
}
