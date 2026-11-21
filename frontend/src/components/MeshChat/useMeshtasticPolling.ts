'use client';

import { useEffect } from 'react';
import { API_BASE } from '@/lib/api';
import type { MeshtasticMessage } from './types';

export function useMeshtasticPolling(args: {
  expanded: boolean;
  activeTab: string;
  canUsePublicMeshInput: boolean;
  meshView: string;
  meshRegion: string;
  meshChannel: string;
  setMeshMessages: React.Dispatch<React.SetStateAction<MeshtasticMessage[]>>;
  setMeshQuickStatus: React.Dispatch<React.SetStateAction<{ type: 'ok' | 'err'; text: string } | null>>;
}) {
  const {
    expanded,
    activeTab,
    canUsePublicMeshInput,
    meshView,
    meshRegion,
    meshChannel,
    setMeshMessages,
    setMeshQuickStatus,
  } = args;

  useEffect(() => {
    if (!expanded || activeTab !== 'meshtastic' || !canUsePublicMeshInput) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const params = new URLSearchParams({
          limit: meshView === 'inbox' ? '100' : '30',
          region: meshRegion,
          channel: meshChannel,
        });
        if (meshView === 'inbox') params.set('include_direct', '1');
        const res = await fetch(`${API_BASE}/api/mesh/messages?${params}`);
        if (res.ok && !cancelled) {
          const data = await res.json();
          setMeshMessages(Array.isArray(data) ? [...data].reverse() : []);
        }
      } catch {
        /* ignore */
      }
    };
    void poll();
    const iv = setInterval(poll, 8000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [expanded, activeTab, meshRegion, meshChannel, meshView, canUsePublicMeshInput, setMeshMessages]);

  useEffect(() => {
    if (canUsePublicMeshInput) return;
    setMeshMessages([]);
    setMeshQuickStatus(null);
  }, [canUsePublicMeshInput, setMeshMessages, setMeshQuickStatus]);
}
