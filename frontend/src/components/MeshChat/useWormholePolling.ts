'use client';

import { useEffect } from 'react';
import { fetchWormholeSettings } from '@/mesh/wormholeClient';
import { fetchWormholeStatus } from '@/mesh/wormholeIdentityClient';

export function useWormholePolling(ctx: any) {
  const {
    setSecureModeCached, setWormholeEnabled, setMeshSessionActive, setMeshMessages,
    purgeBrowserContactGraph, hydrateWormholeContacts,
    setWormholeReadyState, setAnonymousModeEnabled, setAnonymousModeReady,
    setWormholeRnsReady, setWormholeRnsPeers, setWormholeRnsDirectReady,
    setRecentPrivateFallback, setRecentPrivateFallbackReason,
  } = ctx;
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const [settingsRes, statusRes] = await Promise.allSettled([
          fetchWormholeSettings(),
          fetchWormholeStatus(),
        ]);
        if (!alive) return;
        if (settingsRes.status === 'fulfilled') {
          const data = settingsRes.value;
          const enabled = Boolean(data?.enabled);
          setSecureModeCached(enabled);
          setWormholeEnabled(enabled);
          if (enabled) {
            setMeshSessionActive(false);
            setMeshMessages([]);
            purgeBrowserContactGraph();
            void hydrateWormholeContacts();
          }
        }
        if (statusRes.status === 'fulfilled') {
          const data = statusRes.value;
          setWormholeReadyState(Boolean(data?.ready));
          setAnonymousModeEnabled(Boolean(data?.anonymous_mode));
          setAnonymousModeReady(Boolean(data?.anonymous_mode_ready));
          setWormholeRnsReady(Boolean(data?.rns_ready));
          setWormholeRnsPeers({
            active: Number(data?.rns_active_peers || 0),
            configured: Number(data?.rns_configured_peers || 0),
          });
          setWormholeRnsDirectReady(Boolean(data?.rns_private_dm_direct_ready));
          setRecentPrivateFallback(Boolean(data?.recent_private_clearnet_fallback));
          setRecentPrivateFallbackReason(
            String(data?.recent_private_clearnet_fallback_reason || '').trim(),
          );
        } else {
          setWormholeReadyState(false);
          setAnonymousModeReady(false);
          setWormholeRnsReady(false);
          setWormholeRnsPeers({ active: 0, configured: 0 });
          setWormholeRnsDirectReady(false);
          setRecentPrivateFallback(false);
          setRecentPrivateFallbackReason('');
        }
      } catch {
        if (!alive) return;
        setWormholeReadyState(false);
        setAnonymousModeReady(false);
        setWormholeRnsReady(false);
        setWormholeRnsPeers({ active: 0, configured: 0 });
        setWormholeRnsDirectReady(false);
        setRecentPrivateFallback(false);
        setRecentPrivateFallbackReason('');
      } finally {
        if (alive) timer = setTimeout(poll, 5000);
      }
    };
    void poll();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, []);
}
