'use client';

import React, { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/api';
import { fetchInfonetNodeStatusSnapshot } from '@/mesh/controlPlaneStatusClient';

interface Stats {
  meshtastic: number;
  aprs: number;
  ledgerNodes: number;
  infonetEvents: number;
  syncPeers: number;
  seedPeers: number;
  nodeEnabled: boolean;
  syncOutcome: string;
  syncError: string;
  bootstrapState: string;
  bootstrapDetail: string;
  artiReady: boolean | null;
}

const EMPTY: Stats = {
  meshtastic: 0, aprs: 0, ledgerNodes: 0, infonetEvents: 0,
  syncPeers: 0, seedPeers: 0, nodeEnabled: false, syncOutcome: 'offline', syncError: '',
  bootstrapState: 'offline', bootstrapDetail: '',
  artiReady: null,
};

function isArtiTransportBlocked(syncError: string, artiReady: boolean | null): boolean {
  if (artiReady === true) return false;
  if (artiReady === false) return true;
  const lower = syncError.toLowerCase();
  return (
    lower.includes('ready arti transport')
    || lower.includes('require arti to be enabled')
    || lower.includes('onion peer requests require a ready arti')
  );
}

export default function NetworkStats() {
  const [stats, setStats] = useState<Stats>(EMPTY);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const [meshRes, channelsRes, infonet, wormholeRes] = await Promise.all([
          fetch(`${API_BASE}/api/mesh/status`).then(r => r.ok ? r.json() : null).catch(() => null),
          fetch(`${API_BASE}/api/mesh/channels`).then(r => r.ok ? r.json() : null).catch(() => null),
          fetchInfonetNodeStatusSnapshot(true).catch(() => null),
          fetch(`${API_BASE}/api/wormhole/status`).then(r => r.ok ? r.json() : null).catch(() => null),
        ]);
        if (!alive) return;
        const authorNodes = Number(infonet?.author_nodes ?? infonet?.known_nodes ?? 0);
        const registeredNodes = Number(infonet?.registered_nodes || 0);
        const syncPeerCount = Number(infonet?.bootstrap?.sync_peer_count || 0);
        const seedPeerCount = Number(
          infonet?.bootstrap?.bootstrap_seed_peer_count
          ?? infonet?.bootstrap?.default_sync_peer_count
          ?? 0,
        );
        const syncOutcome = String(infonet?.sync_runtime?.last_outcome || 'offline').toLowerCase();
        const bootstrapState = String(infonet?.bootstrap?.bootstrap_state || '').toLowerCase();
        const artiReady = typeof wormholeRes?.arti_ready === 'boolean' ? wormholeRes.arti_ready : null;
        setStats({
          meshtastic: Number(channelsRes?.total_live || channelsRes?.total_nodes || meshRes?.signal_counts?.meshtastic || 0),
          aprs: Number(meshRes?.signal_counts?.aprs || 0),
          ledgerNodes: Math.max(authorNodes, registeredNodes),
          infonetEvents: Number(infonet?.total_events || 0),
          syncPeers: syncPeerCount,
          seedPeers: seedPeerCount,
          nodeEnabled: Boolean(infonet?.node_enabled),
          syncOutcome,
          syncError: String(infonet?.sync_runtime?.last_error || '').trim(),
          bootstrapState,
          bootstrapDetail: String(infonet?.bootstrap?.bootstrap_detail || '').trim(),
          artiReady,
        });
      } catch { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 8000);
    return () => { alive = false; clearInterval(interval); };
  }, []);

  const artiBlocked = isArtiTransportBlocked(stats.syncError, stats.artiReady);
  const connecting = stats.bootstrapState === 'connecting';
  const localActive = stats.syncOutcome === 'solo' || (stats.nodeEnabled && connecting);
  const nodeColor = stats.syncOutcome === 'ok' || stats.syncOutcome === 'solo' ? 'text-green-400'
    : stats.syncOutcome === 'running' ? 'text-amber-400'
    : stats.nodeEnabled ? 'text-amber-400' : 'text-gray-600';
  const nodeLabel = stats.syncOutcome === 'ok' ? 'SEED SYNCED'
    : localActive ? 'LOCAL ACTIVE'
    : stats.syncOutcome === 'running' ? 'SYNCING'
    : stats.syncOutcome === 'error' || stats.syncOutcome === 'fork'
      ? (artiBlocked ? 'ARTI WARMING' : 'CONNECTING')
    : stats.nodeEnabled ? 'WAITING' : 'OFFLINE';
  const nodeTitle = stats.bootstrapDetail
    ? stats.bootstrapDetail
    : stats.syncError
      ? `Infonet seed sync is retrying in the background: ${stats.syncError}`
    : stats.nodeEnabled
      ? 'Participant node enabled; waiting for seed ledger sync.'
      : 'Participant node offline.';

  return (
    <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1 mt-5 text-sm font-mono text-gray-500">
      <span title={nodeTitle}>NODE <span className={nodeColor}>{nodeLabel}</span></span>
      <span className="text-gray-700">|</span>
      <span>MESH <span className={stats.meshtastic > 0 ? 'text-green-400' : 'text-gray-600'}>{stats.meshtastic.toLocaleString()}</span></span>
      <span className="text-gray-700">|</span>
      <span>APRS <span className={stats.aprs > 0 ? 'text-green-400' : 'text-gray-600'}>{stats.aprs.toLocaleString()}</span></span>
      <span className="text-gray-700">|</span>
      <span title="Distinct identities this node has seen on the accepted Infonet ledger. This is not a live user count.">
        LEDGER NODES <span className="text-white">{stats.ledgerNodes}</span>
      </span>
      <span className="text-gray-700">|</span>
      <span>EVENTS <span className="text-white">{stats.infonetEvents}</span></span>
      <span className="text-gray-700">|</span>
      <span title="Peers this node syncs from (seed + swarm-discovered participants).">
        SYNC PEERS <span className="text-white">{stats.syncPeers}</span>
      </span>
      {stats.seedPeers > stats.syncPeers ? (
        <>
          <span className="text-gray-700">|</span>
          <span title="Bootstrap seed peers available from config or manifest.">SEEDS <span className="text-white">{stats.seedPeers}</span></span>
        </>
      ) : null}
    </div>
  );
}
