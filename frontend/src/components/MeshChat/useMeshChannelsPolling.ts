'use client';

import { useEffect } from 'react';
import { API_BASE } from '@/lib/api';
import { DEFAULT_MESH_ROOTS, sortMeshRoots } from './useMeshChatController.helpers';

export function useMeshChannelsPolling({ expanded, activeTab, canUsePublicMeshInput, meshRegion, setMeshRoots, setMeshRegion }: any) {
  useEffect(() => {
    if (!expanded || activeTab !== 'meshtastic' || !canUsePublicMeshInput) return;
    let cancelled = false;
    const fetchChannels = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/mesh/channels`);
        if (res.ok && !cancelled) {
          const stats = await res.json();
          const rootCounts: Record<string, number> = {};
          const knownRoots = Array.isArray(stats.known_roots) ? stats.known_roots : [];
          Object.entries((stats.roots || {}) as Record<string, { nodes?: number }>).forEach(
            ([root, data]) => {
              rootCounts[root] = Number(data?.nodes || 0);
            },
          );
          const roots = sortMeshRoots(
            [...DEFAULT_MESH_ROOTS, ...knownRoots, ...Object.keys(rootCounts), meshRegion],
            rootCounts,
            meshRegion,
          );
          setMeshRoots(roots);

          // Collect channels from selected root/region + global message log
          const chSet = new Set<string>(['LongFast']);
          const active = new Set<string>();
          const meshData = stats.roots?.[meshRegion] || stats.regions?.[meshRegion];
          if (meshData?.channels) {
            Object.entries(meshData.channels).forEach(([ch, count]) => {
              chSet.add(ch);
              if ((count as number) > 0) active.add(ch);
            });
          }
          if (stats.channel_messages) {
            Object.entries(stats.channel_messages).forEach(([ch, count]) => {
              chSet.add(ch);
              if ((count as number) > 0) active.add(ch);
            });
          }
          // Sort: LongFast first, then active channels, then alphabetical
          const sorted = Array.from(chSet).sort((a, b) => {
            if (a === 'LongFast') return -1;
            if (b === 'LongFast') return 1;
            const aActive = active.has(a) ? 0 : 1;
            const bActive = active.has(b) ? 0 : 1;
            if (aActive !== bActive) return aActive - bActive;
            return a.localeCompare(b);
          });
          setMeshChannels(sorted);
          setActiveChannels(active);
        }
      } catch {
        /* ignore */
      }
    };
    fetchChannels();
    const iv = setInterval(fetchChannels, 30000); // Refresh channel list every 30s
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [expanded, activeTab, meshRegion, canUsePublicMeshInput]);
}
