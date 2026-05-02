'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, FileText, Scale, Loader, AlertCircle, CheckCircle2, ShieldOff } from 'lucide-react';
import {
  buildDisputeOpenPayload,
  buildDisputeStakePayload,
  buildEvidenceSubmitPayload,
  buildResolutionStakePayload,
  fetchMarketState,
  previewMarketResolution,
  signAndAppend,
  type AppendResult,
  type DisputeSummary,
  type MarketState,
  type ResolutionPreview,
} from '@/mesh/infonetEconomyClient';
import { useSignAndAppend } from '@/hooks/useSignAndAppend';

interface ResolutionViewProps {
  marketId: string;
  onBack: () => void;
}

const PHASE_STYLE: Record<string, { color: string; label: string }> = {
  predicting: { color: 'text-cyan-400',  label: 'PREDICTING' },
  evidence:   { color: 'text-amber-400', label: 'EVIDENCE WINDOW' },
  resolving:  { color: 'text-blue-400',  label: 'RESOLVING' },
  final:      { color: 'text-green-400', label: 'FINAL' },
  invalid:    { color: 'text-red-400',   label: 'INVALID' },
};

function DisputeRow({
  dispute,
  onAction,
}: {
  dispute: DisputeSummary;
  onAction: () => void;
}) {
  const [side, setSide] = useState<'confirm' | 'reverse'>('reverse');
  const [amount, setAmount] = useState('');
  const [repType, setRepType] = useState<'oracle' | 'common'>('oracle');
  const action = useSignAndAppend();
  const busy = action.state === 'submitting';

  const submit = useCallback(async () => {
    const amt = Number(amount);
    if (!Number.isFinite(amt) || amt <= 0) return;
    const built = buildDisputeStakePayload(dispute.dispute_id, side, amt, repType);
    const res = await action.submit(built.event_type, built.payload);
    if (res.ok) {
      setAmount('');
      onAction();
    }
  }, [amount, side, repType, dispute.dispute_id, action, onAction]);

  return (
    <div className="border border-red-900/50 bg-red-900/10 p-2 text-xs">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-red-400 font-bold">DISPUTE</span>
        {dispute.is_resolved ? (
          <span
            className={
              dispute.resolved_outcome === 'reversed' ? 'text-red-400' : 'text-green-400'
            }
          >
            {dispute.resolved_outcome?.toUpperCase()}
          </span>
        ) : (
          <span className="text-amber-400">PENDING</span>
        )}
        <span className="text-gray-500 font-mono truncate">
          {dispute.dispute_id.slice(0, 12)}…
        </span>
      </div>
      <div className="text-gray-300">
        Challenger: <span className="font-mono">{dispute.challenger_id.slice(0, 12)}…</span>
        {' — stake '}{dispute.challenger_stake.toFixed(2)}
      </div>
      <div className="text-gray-500 mt-1">
        confirm: {dispute.confirm_stakes.length} stakes •
        reverse: {dispute.reverse_stakes.length} stakes
      </div>

      {!dispute.is_resolved && (
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <select
            value={side}
            onChange={(e) => setSide(e.target.value as 'confirm' | 'reverse')}
            title="Dispute stake side"
            aria-label="Dispute stake side"
            className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono"
          >
            <option value="confirm">CONFIRM</option>
            <option value="reverse">REVERSE</option>
          </select>
          <input
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="amount"
            className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono w-24"
          />
          <select
            value={repType}
            onChange={(e) => setRepType(e.target.value as 'oracle' | 'common')}
            title="Reputation type to stake"
            aria-label="Reputation type to stake"
            className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono"
          >
            <option value="oracle">oracle</option>
            <option value="common">common</option>
          </select>
          <button
            type="button"
            onClick={submit}
            disabled={busy || !amount}
            className="px-2 py-1 uppercase tracking-wider border border-red-700/50 bg-red-900/20 text-red-400 hover:bg-red-900/40 disabled:opacity-30"
          >
            {busy ? 'Staking…' : 'Stake'}
          </button>
        </div>
      )}

      {action.result && !action.result.ok && (
        <div className="text-red-400 font-mono mt-2 break-all">
          <AlertCircle size={10} className="inline mr-1" />
          {action.result.reason}
        </div>
      )}
    </div>
  );
}

export default function ResolutionView({ marketId, onBack }: ResolutionViewProps) {
  const [state, setState] = useState<MarketState | null>(null);
  const [preview, setPreview] = useState<ResolutionPreview['preview'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Resolution-stake form state.
  const [stakeSide, setStakeSide] = useState<'yes' | 'no' | 'data_unavailable'>('yes');
  const [stakeAmount, setStakeAmount] = useState('');
  const [stakeRepType, setStakeRepType] = useState<'oracle' | 'common'>('oracle');

  // Dispute-open form state.
  const [disputeStake, setDisputeStake] = useState('');
  const [disputeReason, setDisputeReason] = useState('');

  // Evidence-submit form state (active during EVIDENCE phase).
  const [evidenceOutcome, setEvidenceOutcome] = useState<'yes' | 'no'>('yes');
  const [evidenceSourceDesc, setEvidenceSourceDesc] = useState('');
  const [evidenceHashesInput, setEvidenceHashesInput] = useState('');
  const [evidenceBond, setEvidenceBond] = useState('2');
  const [evidenceSubmitting, setEvidenceSubmitting] = useState(false);
  const [evidenceResult, setEvidenceResult] = useState<AppendResult | null>(null);

  const stakeAction = useSignAndAppend();
  const disputeAction = useSignAndAppend();

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, p] = await Promise.all([
        fetchMarketState(marketId),
        previewMarketResolution(marketId).catch(() => null),
      ]);
      setState(s);
      setPreview(p?.preview ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'network error');
    } finally {
      setLoading(false);
    }
  }, [marketId]);

  const submitStake = useCallback(async () => {
    const amt = Number(stakeAmount);
    if (!Number.isFinite(amt) || amt <= 0) return;
    const built = buildResolutionStakePayload(marketId, stakeSide, amt, stakeRepType);
    const res = await stakeAction.submit(built.event_type, built.payload);
    if (res.ok) {
      setStakeAmount('');
      void reload();
    }
  }, [stakeAmount, stakeSide, stakeRepType, marketId, stakeAction, reload]);

  const submitDispute = useCallback(async () => {
    const stake = Number(disputeStake);
    if (!Number.isFinite(stake) || stake <= 0) return;
    if (!disputeReason.trim()) return;
    const built = buildDisputeOpenPayload(marketId, stake, disputeReason.trim());
    const res = await disputeAction.submit(built.event_type, built.payload);
    if (res.ok) {
      setDisputeStake('');
      setDisputeReason('');
      void reload();
    }
  }, [disputeStake, disputeReason, marketId, disputeAction, reload]);

  const submitEvidence = useCallback(async () => {
    if (!evidenceSourceDesc.trim()) return;
    const hashes = evidenceHashesInput
      .split(/[,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (hashes.length === 0) return;
    const bond = Number(evidenceBond);
    if (!Number.isFinite(bond) || bond < 0) return;
    setEvidenceSubmitting(true);
    setEvidenceResult(null);
    try {
      const built = await buildEvidenceSubmitPayload({
        marketId,
        claimedOutcome: evidenceOutcome,
        evidenceHashes: hashes,
        sourceDescription: evidenceSourceDesc.trim(),
        bond,
      });
      const res = await signAndAppend({
        event_type: built.event_type,
        payload: built.payload,
      });
      setEvidenceResult(res);
      if (res.ok) {
        setEvidenceSourceDesc('');
        setEvidenceHashesInput('');
        void reload();
      }
    } catch (err) {
      setEvidenceResult({
        ok: false,
        reason: err instanceof Error ? err.message : 'unknown_error',
      });
    } finally {
      setEvidenceSubmitting(false);
    }
  }, [
    evidenceOutcome, evidenceSourceDesc, evidenceHashesInput, evidenceBond,
    marketId, reload,
  ]);

  const phase = state ? PHASE_STYLE[state.status] : null;
  const inEvidence = state?.status === 'evidence';
  const inResolving = state?.status === 'resolving';
  const isFinal = state?.status === 'final';
  const hasActivePhase = inEvidence || inResolving || isFinal;

  useEffect(() => {
    void reload();
    const interval = setInterval(() => void reload(), hasActivePhase ? 8_000 : 30_000);
    return () => clearInterval(interval);
  }, [reload, hasActivePhase]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-gray-800/50 pb-3 mb-4 shrink-0">
        <button onClick={onBack} className="flex items-center text-cyan-400 hover:text-cyan-300 text-sm">
          <ChevronLeft size={14} className="mr-1" /> BACK
        </button>
        <div className="text-sm text-cyan-400 font-bold uppercase tracking-widest flex items-center gap-2">
          <Scale size={16} /> RESOLUTION — {marketId}
        </div>
        <button onClick={() => void reload()} disabled={loading} className="text-xs text-gray-500 hover:text-cyan-400 disabled:opacity-30">
          {loading ? <Loader size={12} className="animate-spin" /> : 'REFRESH'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto pr-3 space-y-4">
        {error && (
          <div className="border border-red-900/50 bg-red-900/10 p-3 text-xs text-red-400">
            <AlertCircle size={12} className="inline mr-1" />{error}
          </div>
        )}

        {state && phase && (
          <div className="border border-gray-800 bg-black/40 p-3">
            <div className={`text-xs font-bold uppercase tracking-wider ${phase.color} mb-2`}>
              PHASE: {phase.label}
              {state.was_reversed && (
                <span className="ml-2 text-red-400">⚠ REVERSED BY DISPUTE</span>
              )}
            </div>
            {state.snapshot && (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
                <div>
                  <div className="text-gray-500">Frozen Predictors</div>
                  <div className="text-white">{(state.snapshot.frozen_participant_count as number) ?? 0}</div>
                </div>
                <div>
                  <div className="text-gray-500">Frozen Total Stake</div>
                  <div className="text-white">{(state.snapshot.frozen_total_stake as number)?.toFixed?.(2) ?? '0.00'}</div>
                </div>
                <div>
                  <div className="text-gray-500">Excluded Predictors</div>
                  <div className="text-white">{state.excluded_predictor_ids.length}</div>
                </div>
              </div>
            )}
          </div>
        )}

        {state && state.evidence_bundles.length > 0 && (
          <div>
            <div className="text-xs uppercase tracking-wider text-amber-400 mb-2 flex items-center gap-1">
              <FileText size={12} /> Evidence Bundles ({state.evidence_bundles.length})
            </div>
            <div className="space-y-2">
              {state.evidence_bundles.map((b) => (
                <div key={b.submission_hash} className="border border-gray-800 bg-black/40 p-2 text-xs">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className={`font-bold ${b.claimed_outcome === 'yes' ? 'text-green-400' : 'text-red-400'}`}>
                      {b.claimed_outcome.toUpperCase()}
                    </span>
                    {b.is_first_for_side && (
                      <span className="text-amber-400 text-xs">★ FIRST-FOR-SIDE BONUS</span>
                    )}
                    <span className="text-gray-500 font-mono truncate">
                      {b.node_id.slice(0, 12)}…
                    </span>
                  </div>
                  <div className="text-gray-300 mb-1">{b.source_description || '(no description)'}</div>
                  <div className="text-gray-500 font-mono">
                    bond: {b.bond} • {b.evidence_hashes.length} hash{b.evidence_hashes.length === 1 ? '' : 'es'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {state && state.disputes.length > 0 && (
          <div>
            <div className="text-xs uppercase tracking-wider text-red-400 mb-2 flex items-center gap-1">
              <ShieldOff size={12} /> Disputes ({state.disputes.length})
            </div>
            <div className="space-y-2">
              {state.disputes.map((d) => (
                <DisputeRow
                  key={d.dispute_id}
                  dispute={d}
                  onAction={() => void reload()}
                />
              ))}
            </div>
          </div>
        )}

        {inEvidence && (
          <div className="border border-amber-900/50 bg-amber-900/5 p-3">
            <div className="text-xs uppercase tracking-wider text-amber-400 mb-2 flex items-center gap-1">
              <FileText size={12} /> Submit Evidence
            </div>
            <div className="text-xs text-gray-500 mb-2">
              Pay an evidence bond (≥
              <span className="font-mono"> evidence_bond_cost</span>{' '}
              oracle rep). The bond is returned if your claimed side wins;
              forfeited otherwise. The first submitter per side gets a small
              bonus from the losing pool when the market resolves on their
              side. Hashes use the canonical content + submission scheme;
              both are computed locally before signing.
            </div>
            <div className="space-y-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={evidenceOutcome}
                  onChange={(e) => setEvidenceOutcome(e.target.value as 'yes' | 'no')}
                  title="Claimed outcome"
                  aria-label="Claimed outcome"
                  className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono"
                >
                  <option value="yes">YES</option>
                  <option value="no">NO</option>
                </select>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={evidenceBond}
                  onChange={(e) => setEvidenceBond(e.target.value)}
                  placeholder="bond"
                  title="Bond amount in oracle rep"
                  aria-label="Bond amount"
                  className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono w-24"
                />
                <button
                  type="button"
                  onClick={submitEvidence}
                  disabled={
                    evidenceSubmitting ||
                    !evidenceSourceDesc.trim() ||
                    !evidenceHashesInput.trim()
                  }
                  className="px-3 py-1 uppercase tracking-wider border border-amber-700/50 bg-amber-900/20 text-amber-400 hover:bg-amber-900/40 disabled:opacity-30"
                >
                  {evidenceSubmitting ? 'Submitting…' : 'Submit Evidence'}
                </button>
              </div>
              <input
                type="text"
                value={evidenceSourceDesc}
                onChange={(e) => setEvidenceSourceDesc(e.target.value)}
                placeholder="source description (what + where)"
                className="w-full bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono"
              />
              <input
                type="text"
                value={evidenceHashesInput}
                onChange={(e) => setEvidenceHashesInput(e.target.value)}
                placeholder="evidence hashes (comma- or space-separated; ipfs://… or sha256:…)"
                className="w-full bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono"
              />
            </div>
            {evidenceResult && !evidenceResult.ok && (
              <div className="text-xs text-red-400 font-mono mt-2 break-all">
                <AlertCircle size={10} className="inline mr-1" />
                {evidenceResult.reason}
              </div>
            )}
            {evidenceResult && evidenceResult.ok && (
              <div className="text-xs text-green-400 font-mono mt-2 break-all">
                <CheckCircle2 size={10} className="inline mr-1" />
                evidence submitted — event_id {String(evidenceResult.event.event_id).slice(0, 16)}…
              </div>
            )}
          </div>
        )}

        {inResolving && (
          <div className="border border-blue-900/50 bg-blue-900/5 p-3">
            <div className="text-xs uppercase tracking-wider text-blue-400 mb-2 flex items-center gap-1">
              <Scale size={12} /> Stake on Resolution
            </div>
            <div className="text-xs text-gray-500 mb-2">
              Pick a side and stake oracle (or common) rep. ≥75% of oracle stake on
              one side reaches supermajority. <span className="text-amber-400">data_unavailable</span>{' '}
              triggers phantom-evidence slashing if it crosses 33%.
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <select
                value={stakeSide}
                onChange={(e) => setStakeSide(e.target.value as 'yes' | 'no' | 'data_unavailable')}
                title="Resolution stake side"
                aria-label="Resolution stake side"
                className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono"
              >
                <option value="yes">YES</option>
                <option value="no">NO</option>
                <option value="data_unavailable">DATA_UNAVAILABLE</option>
              </select>
              <input
                type="number"
                min="0"
                step="0.01"
                value={stakeAmount}
                onChange={(e) => setStakeAmount(e.target.value)}
                placeholder="amount"
                className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono w-32"
              />
              <select
                value={stakeRepType}
                onChange={(e) => setStakeRepType(e.target.value as 'oracle' | 'common')}
                title="Reputation type to stake"
                aria-label="Reputation type to stake"
                className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono"
              >
                <option value="oracle">oracle rep</option>
                <option value="common">common rep</option>
              </select>
              <button
                type="button"
                onClick={submitStake}
                disabled={stakeAction.state === 'submitting' || !stakeAmount}
                className="px-3 py-1 uppercase tracking-wider border border-blue-700/50 bg-blue-900/20 text-blue-400 hover:bg-blue-900/40 disabled:opacity-30"
              >
                {stakeAction.state === 'submitting' ? 'Staking…' : 'Stake'}
              </button>
            </div>
            {stakeAction.result && !stakeAction.result.ok && (
              <div className="text-xs text-red-400 font-mono mt-2 break-all">
                <AlertCircle size={10} className="inline mr-1" />
                {stakeAction.result.reason}
              </div>
            )}
          </div>
        )}

        {isFinal && (
          <div className="border border-red-900/50 bg-red-900/5 p-3">
            <div className="text-xs uppercase tracking-wider text-red-400 mb-2 flex items-center gap-1">
              <ShieldOff size={12} /> Open a Dispute
            </div>
            <div className="text-xs text-gray-500 mb-2">
              Bounded reversal: a successful dispute flips the effective outcome of
              THIS market only — never cascades to other markets. Oracle-rep simple
              majority decides; common rep can also be staked but doesn&apos;t decide
              the outcome.
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <input
                type="number"
                min="0"
                step="0.01"
                value={disputeStake}
                onChange={(e) => setDisputeStake(e.target.value)}
                placeholder="challenger stake"
                className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono w-32"
              />
              <input
                type="text"
                value={disputeReason}
                onChange={(e) => setDisputeReason(e.target.value)}
                placeholder="reason (max 2000 chars)"
                className="bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono flex-1 min-w-[200px]"
                maxLength={2000}
              />
              <button
                type="button"
                onClick={submitDispute}
                disabled={
                  disputeAction.state === 'submitting' ||
                  !disputeStake || !disputeReason.trim()
                }
                className="px-3 py-1 uppercase tracking-wider border border-red-700/50 bg-red-900/20 text-red-400 hover:bg-red-900/40 disabled:opacity-30"
              >
                {disputeAction.state === 'submitting' ? 'Opening…' : 'Open Dispute'}
              </button>
            </div>
            {disputeAction.result && !disputeAction.result.ok && (
              <div className="text-xs text-red-400 font-mono mt-2 break-all">
                <AlertCircle size={10} className="inline mr-1" />
                {disputeAction.result.reason}
              </div>
            )}
          </div>
        )}

        {preview && (
          <div className="border border-cyan-900/50 bg-cyan-900/5 p-3">
            <div className="text-xs uppercase tracking-wider text-cyan-400 mb-2 flex items-center gap-1">
              <CheckCircle2 size={12} /> Resolution Preview (if closed now)
            </div>
            <div className="text-sm mb-2">
              Outcome: <span className={
                preview.outcome === 'yes' ? 'text-green-400 font-bold' :
                preview.outcome === 'no'  ? 'text-red-400 font-bold' :
                'text-gray-400 font-bold'
              }>{preview.outcome.toUpperCase()}</span>
              <span className="text-gray-500 ml-2 font-mono">({preview.reason})</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs text-gray-400">
              <div>
                Winners: {preview.stake_winnings.length} stake winnings,
                {' '}{preview.bond_returns.length} bond returns
              </div>
              <div>
                Forfeited: {preview.bond_forfeits.length} bonds •
                {' '}Burned: {preview.burned_amount.toFixed(2)}
              </div>
            </div>
            {preview.first_submitter_bonuses.length > 0 && (
              <div className="text-xs text-amber-400 mt-1">
                ★ First-submitter bonuses: {preview.first_submitter_bonuses.map(b => `${b.node_id.slice(0,8)}…(${b.amount.toFixed(2)})`).join(', ')}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
