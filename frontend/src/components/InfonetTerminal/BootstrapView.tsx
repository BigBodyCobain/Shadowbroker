'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, Cpu, Loader, AlertCircle, CheckCircle2, XCircle, Server } from 'lucide-react';
import {
  buildBootstrapResolutionVotePayload,
  fetchBootstrapMarketState,
  fetchInfonetStatus,
  type BootstrapMarketState,
  type InfonetStatus,
} from '@/mesh/infonetEconomyClient';
import { generateNodeKeys, getNodeIdentity } from '@/mesh/meshIdentity';
import {
  DEFAULT_INFONET_SEED_URL,
  fetchInfonetNodeStatusSnapshot,
  setInfonetNodeEnabled,
  type InfonetNodeStatusSnapshot,
} from '@/mesh/controlPlaneStatusClient';
import { useSignAndAppend } from '@/hooks/useSignAndAppend';

interface BootstrapViewProps {
  marketId?: string;
  onBack: () => void;
}

export default function BootstrapView({ marketId, onBack }: BootstrapViewProps) {
  const [status, setStatus] = useState<InfonetStatus | null>(null);
  const [market, setMarket] = useState<BootstrapMarketState | null>(null);
  const [nodeStatus, setNodeStatus] = useState<InfonetNodeStatusSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodeToggleBusy, setNodeToggleBusy] = useState(false);
  const [nodeToggleError, setNodeToggleError] = useState<string | null>(null);
  const [voteSide, setVoteSide] = useState<'yes' | 'no'>('yes');
  const [powNonce, setPowNonce] = useState('0');
  const voteAction = useSignAndAppend();

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, m, n] = await Promise.all([
        fetchInfonetStatus(),
        marketId ? fetchBootstrapMarketState(marketId).catch(() => null) : Promise.resolve(null),
        fetchInfonetNodeStatusSnapshot(true).catch(() => null),
      ]);
      setStatus(s);
      setMarket(m);
      setNodeStatus(n);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'network error');
    } finally {
      setLoading(false);
    }
  }, [marketId]);

  const nodeEnabled = Boolean(nodeStatus?.node_enabled);
  const nodeMode = String(nodeStatus?.node_mode || 'participant').toUpperCase();
  const syncOutcome = String(nodeStatus?.sync_runtime?.last_outcome || 'idle').toLowerCase();
  const seedPeerCount = Number(nodeStatus?.bootstrap?.default_sync_peer_count || 0);
  const syncPeerCount = Number(nodeStatus?.bootstrap?.sync_peer_count || 0);
  const lastPeerUrl = String(nodeStatus?.sync_runtime?.last_peer_url || '').trim();

  const toggleNode = useCallback(async (enabled: boolean) => {
    setNodeToggleBusy(true);
    setNodeToggleError(null);
    try {
      if (enabled && !getNodeIdentity()) {
        await generateNodeKeys();
      }
      await setInfonetNodeEnabled(enabled);
      const next = await fetchInfonetNodeStatusSnapshot(true);
      setNodeStatus(next);
    } catch (err) {
      setNodeToggleError(err instanceof Error ? err.message : 'node settings update failed');
    } finally {
      setNodeToggleBusy(false);
    }
  }, []);

  const hasActivePhase = !!market && market.tally.total_eligible >= 0
    && market.tally.yes + market.tally.no < market.tally.total_eligible;

  useEffect(() => {
    void reload();
    const interval = setInterval(() => void reload(), hasActivePhase ? 8_000 : 30_000);
    return () => clearInterval(interval);
  }, [reload, hasActivePhase]);

  const submitVote = useCallback(async () => {
    if (!marketId) return;
    const nonce = Number(powNonce);
    if (!Number.isFinite(nonce) || nonce < 0) return;
    const built = buildBootstrapResolutionVotePayload(marketId, voteSide, Math.floor(nonce));
    const res = await voteAction.submit(built.event_type, built.payload);
    if (res.ok) {
      void reload();
    }
  }, [marketId, voteSide, powNonce, voteAction, reload]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-gray-800/50 pb-3 mb-4 shrink-0">
        <button onClick={onBack} className="flex items-center text-cyan-400 hover:text-cyan-300 text-sm">
          <ChevronLeft size={14} className="mr-1" /> BACK
        </button>
        <div className="text-sm text-cyan-400 font-bold uppercase tracking-widest flex items-center gap-2">
          <Cpu size={16} /> BOOTSTRAP MODE
        </div>
        <button onClick={() => void reload()} disabled={loading} className="text-xs text-gray-500 hover:text-cyan-400 disabled:opacity-30">
          {loading ? <Loader size={12} className="animate-spin" /> : 'REFRESH'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto pr-3 space-y-4">
        <div className="text-xs text-gray-500 leading-relaxed">
          The first <span className="text-cyan-400">bootstrap_market_count</span> (default 100) markets
          resolve via <span className="text-cyan-400">eligible-node-one-vote</span> instead of oracle-rep-weighted
          staking. Eligibility: identity age ≥ 3 days vs market.snapshot.frozen_at,
          NOT in the predictor exclusion set, and a valid Argon2id PoW
          (Heavy-Node-only — requires ≥64MB RAM per computation).
          Once node count crosses <span className="text-cyan-400">bootstrap_threshold</span> (default 1000),
          new markets default to staked resolution. Existing bootstrap-indexed markets continue under
          bootstrap rules until they resolve.
        </div>

        {error && (
          <div className="border border-red-900/50 bg-red-900/10 p-3 text-xs text-red-400">
            <AlertCircle size={12} className="inline mr-1" />{error}
          </div>
        )}

        <div className="border border-cyan-900/50 bg-cyan-950/10 p-3">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div className="text-xs uppercase tracking-wider text-cyan-400 flex items-center gap-2">
              <Server size={14} /> Network Seed
            </div>
            <button
              type="button"
              onClick={() => void reload()}
              disabled={loading}
              className="text-[10px] text-gray-500 hover:text-cyan-400 disabled:opacity-30 uppercase tracking-widest"
            >
              Refresh
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
            <div>
              <div className="text-gray-500">Default Seed</div>
              <div className="text-cyan-300 font-mono break-all">{DEFAULT_INFONET_SEED_URL}</div>
            </div>
            <div>
              <div className="text-gray-500">Local Node</div>
              <div className={nodeEnabled ? 'text-green-400' : 'text-gray-500'}>
                {nodeEnabled ? `${nodeMode} ONLINE` : `${nodeMode} OFF`}
              </div>
            </div>
            <div>
              <div className="text-gray-500">Sync Path</div>
              <div className="text-white font-mono">
                {syncPeerCount} peers / {seedPeerCount} default
              </div>
            </div>
          </div>
          <div className="mt-3 flex flex-col md:flex-row md:items-center gap-3">
            <div className="flex-1 text-[11px] text-gray-500 leading-relaxed">
              {nodeEnabled
                ? `Public chain sync is ${syncOutcome || 'active'}${lastPeerUrl ? ` via ${lastPeerUrl}` : ''}.`
                : 'Start a local participant node to pull from the default seed and help carry the public Infonet chain while this backend is running.'}
            </div>
            <button
              type="button"
              onClick={() => void toggleNode(!nodeEnabled)}
              disabled={nodeToggleBusy}
              className={
                nodeEnabled
                  ? 'px-3 py-2 border border-rose-700/50 bg-rose-950/20 text-rose-300 hover:bg-rose-950/35 disabled:opacity-40 text-[10px] uppercase tracking-wider'
                  : 'px-3 py-2 border border-cyan-700/50 bg-cyan-900/20 text-cyan-300 hover:bg-cyan-900/40 disabled:opacity-40 text-[10px] uppercase tracking-wider'
              }
            >
              {nodeToggleBusy ? 'Updating...' : nodeEnabled ? 'Turn Off Node' : 'Start Node'}
            </button>
          </div>
          {nodeToggleError && (
            <div className="mt-3 border border-amber-900/50 bg-amber-950/20 p-2 text-[11px] text-amber-300">
              <AlertCircle size={11} className="inline mr-1" />{nodeToggleError}
            </div>
          )}
        </div>

        {status && (
          <div className="border border-gray-800 bg-black/40 p-3">
            <div className="text-xs uppercase tracking-wider text-cyan-400 mb-2">Network Ramp</div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
              <div>
                <div className="text-gray-500">Distinct Nodes</div>
                <div className="text-white font-mono text-lg">{status.ramp.node_count}</div>
              </div>
              <div>
                <div className="text-gray-500">Bootstrap Resolution</div>
                <div className={status.ramp.bootstrap_resolution_active ? 'text-green-400' : 'text-gray-500'}>
                  {status.ramp.bootstrap_resolution_active ? 'ACTIVE' : 'TRANSITIONED'}
                </div>
              </div>
              <div>
                <div className="text-gray-500">Staked Resolution</div>
                <div className={status.ramp.staked_resolution_active ? 'text-green-400' : 'text-gray-500'}>
                  {status.ramp.staked_resolution_active ? 'ACTIVE' : 'LOCKED'}
                </div>
              </div>
              <div>
                <div className="text-gray-500">Petitions</div>
                <div className={status.ramp.governance_petitions_active ? 'text-green-400' : 'text-gray-500'}>
                  {status.ramp.governance_petitions_active ? 'ACTIVE' : 'LOCKED'}
                </div>
              </div>
              <div>
                <div className="text-gray-500">Upgrade Governance</div>
                <div className={status.ramp.upgrade_governance_active ? 'text-green-400' : 'text-gray-500'}>
                  {status.ramp.upgrade_governance_active ? 'ACTIVE' : 'LOCKED'}
                </div>
              </div>
              <div>
                <div className="text-gray-500">CommonCoin</div>
                <div className={status.ramp.commoncoin_active ? 'text-green-400' : 'text-gray-500'}>
                  {status.ramp.commoncoin_active ? 'ACTIVE' : 'LOCKED'}
                </div>
              </div>
            </div>
          </div>
        )}

        {market && (
          <div className="border border-gray-800 bg-black/40 p-3">
            <div className="text-xs uppercase tracking-wider text-cyan-400 mb-2">
              Market: <span className="font-mono text-white">{market.market_id}</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs mb-3">
              <div>
                <div className="text-gray-500">YES votes</div>
                <div className="text-green-400 font-mono text-lg">{market.tally.yes}</div>
              </div>
              <div>
                <div className="text-gray-500">NO votes</div>
                <div className="text-red-400 font-mono text-lg">{market.tally.no}</div>
              </div>
              <div>
                <div className="text-gray-500">Total Eligible</div>
                <div className="text-white font-mono text-lg">{market.tally.total_eligible}</div>
              </div>
              <div>
                <div className="text-gray-500">Min Required</div>
                <div className="text-gray-300 font-mono text-lg">{market.tally.min_market_participants}</div>
              </div>
            </div>

            <div className="border border-cyan-900/50 bg-cyan-900/10 p-2 mb-3 text-xs">
              <div className="text-cyan-400 font-bold uppercase tracking-wider mb-2">
                Cast Bootstrap Vote
              </div>
              <div className="text-gray-500 mb-2">
                Eligibility: identity age ≥{' '}
                {status ? '3 days' : 'configured threshold'}{' '}
                vs market.snapshot.frozen_at, NOT in predictor exclusion set,
                and a valid Argon2id PoW (Heavy-Node-only). The PoW nonce
                input is for testnet — production wires the Argon2id solver
                via privacy-core when the Rust binding lands.
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={voteSide}
                  onChange={(e) => setVoteSide(e.target.value as 'yes' | 'no')}
                  title="Bootstrap vote side"
                  aria-label="Bootstrap vote side"
                  className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono"
                >
                  <option value="yes">YES</option>
                  <option value="no">NO</option>
                </select>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={powNonce}
                  onChange={(e) => setPowNonce(e.target.value)}
                  placeholder="pow_nonce"
                  className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono w-32"
                />
                <button
                  type="button"
                  onClick={submitVote}
                  disabled={voteAction.state === 'submitting' || !marketId}
                  className="px-3 py-1 uppercase tracking-wider border border-cyan-700/50 bg-cyan-900/20 text-cyan-400 hover:bg-cyan-900/40 disabled:opacity-30"
                >
                  {voteAction.state === 'submitting' ? 'Submitting…' : 'Cast Vote'}
                </button>
              </div>
              {voteAction.result && !voteAction.result.ok && (
                <div className="text-red-400 font-mono mt-2 break-all">
                  <AlertCircle size={10} className="inline mr-1" />
                  {voteAction.result.reason}
                </div>
              )}
            </div>

            <div className="text-xs uppercase tracking-wider text-gray-500 mb-2">All Submitted Votes</div>
            <div className="space-y-1 max-h-64 overflow-y-auto">
              {market.votes.map((v) => (
                <div key={v.node_id} className="flex items-center justify-between gap-2 text-xs border-b border-gray-800/30 py-1">
                  <span className="font-mono text-gray-400 truncate flex-1">{v.node_id.slice(0, 16)}…</span>
                  <span className={v.side === 'yes' ? 'text-green-400' : 'text-red-400'}>{v.side?.toUpperCase()}</span>
                  <span className="w-20 text-right">
                    {v.eligible ? (
                      <CheckCircle2 size={12} className="text-green-400 inline" />
                    ) : (
                      <span className="text-amber-400 flex items-center justify-end gap-1">
                        <XCircle size={12} />
                        <span className="text-xs">{v.ineligible_reason}</span>
                      </span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {!marketId && (
          <div className="border border-gray-800 bg-black/40 p-6 text-center text-xs text-gray-500">
            Open a bootstrap-indexed market from the Markets view to see its
            eligible-node-one-vote tally here.
          </div>
        )}
      </div>
    </div>
  );
}
