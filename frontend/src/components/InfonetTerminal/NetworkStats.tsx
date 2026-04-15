'use client';

import React, { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/api';
import { fetchInfonetNodeStatusSnapshot } from '@/mesh/controlPlaneStatusClient';

interface Stats {
  meshtastic: number;
  aprs: number;
  infonetNodes: number;
  infonetEvents: number;
  syncPeers: number;
  nodeEnabled: boolean;
  syncOutcome: string;
}

const EMPTY: Stats = {
  meshtastic: 0, aprs: 0, infonetNodes: 0, infonetEvents: 0,
  syncPeers: 0, nodeEnabled: false, syncOutcome: 'offline',
};

export default function NetworkStats() {
  const [stats, setStats] = useState<Stats>(EMPTY);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const [meshRes, channelsRes, infonet] = await Promise.all([
          fetch(`${API_BASE}/api/mesh/status`).then(r => r.ok ? r.json() : null).catch(() => null),
          fetch(`${API_BASE}/api/mesh/channels`).then(r => r.ok ? r.json() : null).catch(() => null),
          fetchInfonetNodeStatusSnapshot(true).catch(() => null),
        ]);
        if (!alive) return;
        setStats({
          meshtastic: Number(channelsRes?.total_live || channelsRes?.total_nodes || meshRes?.signal_counts?.meshtastic || 0),
          aprs: Number(meshRes?.signal_counts?.aprs || 0),
          infonetNodes: Number(infonet?.known_nodes || 0),
          infonetEvents: Number(infonet?.total_events || 0),
          syncPeers: Number(infonet?.bootstrap?.sync_peer_count || 0),
          nodeEnabled: Boolean(infonet?.node_enabled),
          syncOutcome: String(infonet?.sync_runtime?.last_outcome || 'offline').toLowerCase(),
        });
      } catch { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 15000);
    return () => { alive = false; clearInterval(interval); };
  }, []);

  const nodeColor = stats.syncOutcome === 'ok' ? 'text-green-400'
    : stats.syncOutcome === 'running' ? 'text-amber-400'
    : stats.nodeEnabled ? 'text-amber-400' : 'text-gray-600';
  const nodeLabel = stats.syncOutcome === 'ok' ? 'CONNECTED'
    : stats.syncOutcome === 'running' ? 'SYNCING'
    : stats.syncOutcome === 'error' || stats.syncOutcome === 'fork' ? 'RETRYING'
    : stats.nodeEnabled ? 'WAITING' : 'OFFLINE';

  return (
    <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1 mt-5 text-sm font-mono text-gray-500">
      <span>NODE <span className={nodeColor}>{nodeLabel}</span></span>
      <span className="text-gray-700">|</span>
      <span>MESH <span className={stats.meshtastic > 0 ? 'text-green-400' : 'text-gray-600'}>{stats.meshtastic.toLocaleString()}</span></span>
      <span className="text-gray-700">|</span>
      <span>APRS <span className={stats.aprs > 0 ? 'text-green-400' : 'text-gray-600'}>{stats.aprs.toLocaleString()}</span></span>
      <span className="text-gray-700">|</span>
      <span>INFONET NODES <span className="text-white">{stats.infonetNodes}</span></span>
      <span className="text-gray-700">|</span>
      <span>EVENTS <span className="text-white">{stats.infonetEvents}</span></span>
      <span className="text-gray-700">|</span>
      <span>PEERS <span className="text-white">{stats.syncPeers}</span></span>
    </div>
  );
}
