'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, GitBranch, Server, AlertCircle, CheckCircle2, Loader } from 'lucide-react';
import {
  buildUpgradeProposePayload,
  buildUpgradeSignPayload,
  buildUpgradeSignalReadyPayload,
  buildUpgradeVotePayload,
  fetchUpgrades,
  freshLocalId,
  type UpgradeProposalSummary,
} from '@/mesh/infonetEconomyClient';
import { useSignAndAppend } from '@/hooks/useSignAndAppend';

interface UpgradeViewProps {
  onBack: () => void;
}

const STATUS_STYLE: Record<string, { color: string; label: string }> = {
  signatures:        { color: 'text-cyan-400',  label: 'COLLECTING SIGNATURES' },
  voting:            { color: 'text-blue-400',  label: 'VOTING' },
  challenge:         { color: 'text-amber-400', label: 'CHALLENGE WINDOW' },
  activation:        { color: 'text-purple-400', label: 'AWAITING HEAVY-NODE READINESS' },
  activated:         { color: 'text-green-500', label: 'ACTIVATED' },
  failed_signatures: { color: 'text-red-400',   label: 'FAILED — SIGNATURES' },
  failed_vote:       { color: 'text-red-400',   label: 'FAILED — VOTE' },
  voided_challenge:  { color: 'text-red-500',   label: 'VOIDED BY CHALLENGE' },
  failed_activation: { color: 'text-red-400',   label: 'FAILED — ACTIVATION' },
  not_found:         { color: 'text-gray-500',  label: 'NOT FOUND' },
};

function UpgradeRow({
  proposal,
  onAction,
}: {
  proposal: UpgradeProposalSummary;
  onAction: () => void;
}) {
  const style = STATUS_STYLE[proposal.status] ?? STATUS_STYLE.not_found;
  const totalVotes = proposal.votes_for_weight + proposal.votes_against_weight;
  const yesPct = totalVotes > 0 ? (proposal.votes_for_weight / totalVotes) * 100 : 0;
  const readinessPct = (proposal.readiness_fraction || 0) * 100;
  const { state, result, submit } = useSignAndAppend();
  const busy = state === 'submitting';

  const sign = useCallback(async () => {
    const built = buildUpgradeSignPayload(proposal.proposal_id);
    const res = await submit(built.event_type, built.payload);
    if (res.ok) onAction();
  }, [proposal.proposal_id, submit, onAction]);

  const voteFor = useCallback(async () => {
    const built = buildUpgradeVotePayload(proposal.proposal_id, 'for');
    const res = await submit(built.event_type, built.payload);
    if (res.ok) onAction();
  }, [proposal.proposal_id, submit, onAction]);

  const voteAgainst = useCallback(async () => {
    const built = buildUpgradeVotePayload(proposal.proposal_id, 'against');
    const res = await submit(built.event_type, built.payload);
    if (res.ok) onAction();
  }, [proposal.proposal_id, submit, onAction]);

  const signalReady = useCallback(async () => {
    const built = buildUpgradeSignalReadyPayload(
      proposal.proposal_id,
      proposal.release_hash,
    );
    const res = await submit(built.event_type, built.payload);
    if (res.ok) onAction();
  }, [proposal.proposal_id, proposal.release_hash, submit, onAction]);

  return (
    <div className="border border-gray-800 bg-black/40 p-3">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-2">
          <GitBranch size={14} className={style.color} />
          <span className={`text-xs font-bold uppercase tracking-wider ${style.color}`}>
            {style.label}
          </span>
        </div>
        <span className="text-xs text-gray-500 font-mono">
          → v{proposal.target_protocol_version}
        </span>
      </div>

      <div className="text-xs text-gray-400 mb-2 font-mono break-all">
        release_hash: {proposal.release_hash.slice(0, 32)}…
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs mb-2">
        <div>
          <div className="text-gray-500">Proposer</div>
          <div className="text-gray-300 font-mono truncate">
            {proposal.proposer_id.slice(0, 16)}…
          </div>
        </div>
        <div>
          <div className="text-gray-500">Filed</div>
          <div className="text-gray-300">
            {proposal.filed_at ? new Date(proposal.filed_at * 1000).toLocaleDateString() : '—'}
          </div>
        </div>
      </div>

      {(proposal.status === 'voting' || proposal.status === 'challenge'
        || proposal.status === 'activation' || proposal.status === 'activated') && (
        <>
          <div className="text-xs text-gray-500 mb-1">
            Vote: {proposal.votes_for_weight.toFixed(1)} for / {proposal.votes_against_weight.toFixed(1)} against
            <span className="text-gray-600 ml-2">(80% supermajority required)</span>
          </div>
          <div className="h-1 bg-gray-800 mb-2 overflow-hidden flex">
            <div className="h-full bg-green-500" style={{ width: `${yesPct}%` }} />
            <div className="h-full bg-red-500" style={{ width: `${100 - yesPct}%` }} />
          </div>
        </>
      )}

      {(proposal.status === 'activation' || proposal.status === 'activated') && (
        <>
          <div className="text-xs text-purple-400 mb-1 flex items-center gap-1">
            <Server size={11} />
            Heavy-Node readiness: {readinessPct.toFixed(1)}%
            <span className="text-gray-500 ml-2">(67% required for activation)</span>
            {proposal.readiness_threshold_met && (
              <span className="text-green-400 ml-2">✓ THRESHOLD MET</span>
            )}
          </div>
          <div className="h-1 bg-gray-800 overflow-hidden">
            <div
              className="h-full bg-purple-500 transition-all"
              style={{ width: `${Math.min(100, readinessPct)}%` }}
            />
          </div>
        </>
      )}

      <div className="flex flex-wrap gap-2 mt-3">
        {proposal.status === 'signatures' && (
          <button
            type="button"
            onClick={sign}
            disabled={busy}
            className="px-2 py-0.5 text-xs uppercase tracking-wider border border-purple-700/50 bg-purple-900/20 text-purple-400 hover:bg-purple-900/40 disabled:opacity-30"
          >
            {busy ? 'Signing…' : 'Sign'}
          </button>
        )}
        {proposal.status === 'voting' && (
          <>
            <button
              type="button"
              onClick={voteFor}
              disabled={busy}
              className="px-2 py-0.5 text-xs uppercase tracking-wider border border-green-700/50 bg-green-900/20 text-green-400 hover:bg-green-900/40 disabled:opacity-30"
            >
              {busy ? '…' : 'Vote FOR'}
            </button>
            <button
              type="button"
              onClick={voteAgainst}
              disabled={busy}
              className="px-2 py-0.5 text-xs uppercase tracking-wider border border-red-700/50 bg-red-900/20 text-red-400 hover:bg-red-900/40 disabled:opacity-30"
            >
              {busy ? '…' : 'Vote AGAINST'}
            </button>
          </>
        )}
        {proposal.status === 'activation' && (
          <button
            type="button"
            onClick={signalReady}
            disabled={busy}
            title="Signal that this Heavy Node has installed and verified the new release"
            className="px-2 py-0.5 text-xs uppercase tracking-wider border border-purple-700/50 bg-purple-900/20 text-purple-400 hover:bg-purple-900/40 disabled:opacity-30"
          >
            {busy ? '…' : 'Signal Ready'}
          </button>
        )}
      </div>

      {result && !result.ok && (
        <div className="text-xs text-red-400 font-mono mt-2 break-all">
          <AlertCircle size={10} className="inline mr-1" />
          {result.reason}
        </div>
      )}
    </div>
  );
}

function ProposeUpgradePanel({ onAction }: { onAction: () => void }) {
  const [releaseHash, setReleaseHash] = useState('');
  const [releaseDescription, setReleaseDescription] = useState('');
  const [targetProtocolVersion, setTargetProtocolVersion] = useState('');
  const { state, result, submit } = useSignAndAppend();
  const busy = state === 'submitting';

  const propose = useCallback(async () => {
    const trimmedHash = releaseHash.trim().toLowerCase();
    const trimmedDesc = releaseDescription.trim();
    const trimmedVersion = targetProtocolVersion.trim();
    if (trimmedHash.length !== 64 || !/^[0-9a-f]{64}$/.test(trimmedHash)) return;
    if (!trimmedDesc) return;
    if (!trimmedVersion) return;
    const built = buildUpgradeProposePayload({
      proposalId: freshLocalId('upg'),
      releaseHash: trimmedHash,
      releaseDescription: trimmedDesc,
      targetProtocolVersion: trimmedVersion,
    });
    const res = await submit(built.event_type, built.payload);
    if (res.ok) {
      setReleaseHash('');
      setReleaseDescription('');
      setTargetProtocolVersion('');
      onAction();
    }
  }, [releaseHash, releaseDescription, targetProtocolVersion, submit, onAction]);

  return (
    <div className="border border-purple-900/50 bg-purple-900/5 p-3">
      <div className="text-xs uppercase tracking-wider text-purple-400 font-bold mb-2">
        File Upgrade Proposal
      </div>
      <div className="text-xs text-gray-500 mb-3 leading-relaxed">
        Filing requires <span className="text-purple-400">upgrade_filing_cost</span> common rep and a
        SHA-256 hash of the verified release artifact. After filing, the proposal collects
        signatures, then enters voting (80% supermajority / 40% quorum), then the challenge window,
        then awaits 67% Heavy-Node readiness signal before activation.
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-2">
        <input
          type="text"
          value={releaseHash}
          onChange={(e) => setReleaseHash(e.target.value)}
          placeholder="release_hash (64 hex chars)"
          className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono text-xs col-span-1 md:col-span-2"
        />
        <input
          type="number"
          min="1"
          step="1"
          value={targetProtocolVersion}
          onChange={(e) => setTargetProtocolVersion(e.target.value)}
          placeholder="target protocol_version"
          className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono text-xs"
        />
      </div>
      <textarea
        value={releaseDescription}
        onChange={(e) => setReleaseDescription(e.target.value)}
        placeholder="release_description — what changes / event types / formulas does this introduce?"
        rows={2}
        className="bg-black/60 border border-gray-700 px-2 py-1 text-white text-xs w-full mb-2"
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={propose}
          disabled={busy}
          className="px-3 py-1 text-xs uppercase tracking-wider border border-purple-700/50 bg-purple-900/20 text-purple-400 hover:bg-purple-900/40 disabled:opacity-30"
        >
          {busy ? 'Filing…' : 'Propose Upgrade'}
        </button>
        {result && result.ok && (
          <span className="text-xs text-green-400 flex items-center gap-1">
            <CheckCircle2 size={11} /> Filed
          </span>
        )}
      </div>
      {result && !result.ok && (
        <div className="text-xs text-red-400 font-mono mt-2 break-all">
          <AlertCircle size={10} className="inline mr-1" />
          {result.reason}
        </div>
      )}
    </div>
  );
}

export default function UpgradeView({ onBack }: UpgradeViewProps) {
  const [upgrades, setUpgrades] = useState<UpgradeProposalSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchUpgrades();
      setUpgrades(data.upgrades);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'network error');
    } finally {
      setLoading(false);
    }
  }, []);

  const hasActivePhase = (upgrades || []).some((u) =>
    u.status === 'signatures' || u.status === 'voting' ||
    u.status === 'challenge' || u.status === 'activation',
  );

  useEffect(() => {
    void reload();
    const interval = setInterval(() => void reload(), hasActivePhase ? 8_000 : 60_000);
    return () => clearInterval(interval);
  }, [reload, hasActivePhase]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-gray-800/50 pb-3 mb-4 shrink-0">
        <button
          onClick={onBack}
          className="flex items-center text-cyan-400 hover:text-cyan-300 transition-colors text-sm"
        >
          <ChevronLeft size={14} className="mr-1" />
          BACK
        </button>
        <div className="text-sm text-purple-400 font-bold uppercase tracking-widest flex items-center gap-2">
          <GitBranch size={16} />
          UPGRADE-HASH GOVERNANCE
        </div>
        <button
          onClick={() => void reload()}
          disabled={loading}
          className="text-xs text-gray-500 hover:text-purple-400 disabled:opacity-30"
        >
          {loading ? <Loader size={12} className="animate-spin" /> : 'REFRESH'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto pr-3 space-y-4">
        <div className="text-xs text-gray-500 leading-relaxed">
          Protocol upgrades that need new logic / new event types / new formulas
          can&apos;t be expressed as parameter changes — they use upgrade-hash
          governance. The network votes on a software release&apos;s SHA-256 hash;
          Heavy Nodes that have downloaded and verified the release emit
          <span className="text-purple-400"> upgrade_signal_ready</span>. Once 67%
          of Heavy Nodes have signaled, the upgrade activates and protocol_version
          increments. Higher thresholds than param petitions: <span className="text-green-400">80% supermajority</span>,
          <span className="text-blue-400"> 40% quorum</span>,
          <span className="text-purple-400"> 67% Heavy-Node activation</span>.
        </div>

        <ProposeUpgradePanel onAction={() => void reload()} />

        {error && (
          <div className="border border-red-900/50 bg-red-900/10 p-3 text-xs text-red-400">
            <AlertCircle size={12} className="inline mr-1" />
            <span className="font-bold">Failed to load:</span>
            <span className="text-gray-400 ml-2 font-mono">{error}</span>
          </div>
        )}

        {upgrades && upgrades.length === 0 && !loading && (
          <div className="border border-gray-800 bg-black/40 p-6 text-center">
            <div className="text-gray-500 text-sm">No upgrade proposals on chain.</div>
            <div className="text-gray-600 text-xs mt-1">
              Filing requires <span className="text-purple-400">upgrade_filing_cost</span> common rep
              and a SHA-256 release hash.
            </div>
          </div>
        )}

        {upgrades?.map((u) => (
          <UpgradeRow key={u.proposal_id} proposal={u} onAction={() => void reload()} />
        ))}
      </div>
    </div>
  );
}
