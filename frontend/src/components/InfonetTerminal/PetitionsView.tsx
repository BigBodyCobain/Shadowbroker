'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronLeft, FileText, Vote, Shield, AlertCircle, CheckCircle2, Loader } from 'lucide-react';
import {
  buildChallengeFilePayload,
  buildPetitionFilePayload,
  buildPetitionSignPayload,
  buildPetitionVotePayload,
  fetchPetitions,
  freshLocalId,
  previewPetitionPayload,
  signAndAppend,
  type PetitionPayload,
  type PetitionState,
} from '@/mesh/infonetEconomyClient';
import { useSignAndAppend } from '@/hooks/useSignAndAppend';

interface PetitionsViewProps {
  onBack: () => void;
}

const STATUS_STYLE: Record<string, { color: string; label: string; icon: typeof Vote }> = {
  signatures:        { color: 'text-cyan-400',   label: 'COLLECTING SIGNATURES', icon: FileText },
  voting:            { color: 'text-blue-400',   label: 'VOTING',                icon: Vote },
  challenge:         { color: 'text-amber-400',  label: 'CHALLENGE WINDOW',      icon: Shield },
  passed:            { color: 'text-green-400',  label: 'PASSED',                icon: CheckCircle2 },
  executed:          { color: 'text-green-500',  label: 'EXECUTED',              icon: CheckCircle2 },
  failed_signatures: { color: 'text-red-400',    label: 'FAILED — SIGNATURES',   icon: AlertCircle },
  failed_vote:       { color: 'text-red-400',    label: 'FAILED — VOTE',         icon: AlertCircle },
  voided_challenge:  { color: 'text-red-500',    label: 'VOIDED BY CHALLENGE',   icon: AlertCircle },
  not_found:         { color: 'text-gray-500',   label: 'NOT FOUND',             icon: AlertCircle },
};

function formatRelative(ts: number, now: number): string {
  if (!ts) return '—';
  const delta = ts - now;
  const abs = Math.abs(delta);
  const days = Math.floor(abs / 86400);
  const hours = Math.floor((abs % 86400) / 3600);
  if (delta > 0) {
    if (days > 0) return `in ${days}d ${hours}h`;
    if (hours > 0) return `in ${hours}h`;
    return `in ${Math.floor(abs / 60)}m`;
  } else {
    if (days > 0) return `${days}d ago`;
    if (hours > 0) return `${hours}h ago`;
    return `${Math.floor(abs / 60)}m ago`;
  }
}

function PayloadSummary({ payload }: { payload: PetitionPayload | Record<string, unknown> }) {
  const t = (payload as { type?: string }).type;
  if (t === 'UPDATE_PARAM') {
    const p = payload as Extract<PetitionPayload, { type: 'UPDATE_PARAM' }>;
    return (
      <span className="text-gray-300">
        Set <span className="text-cyan-400 font-bold">{p.key}</span> = {' '}
        <span className="text-white font-bold">{String(p.value)}</span>
      </span>
    );
  }
  if (t === 'BATCH_UPDATE_PARAMS') {
    const p = payload as Extract<PetitionPayload, { type: 'BATCH_UPDATE_PARAMS' }>;
    return (
      <span className="text-gray-300">
        Update {p.updates?.length ?? 0} parameters atomically
      </span>
    );
  }
  if (t === 'ENABLE_FEATURE') {
    const p = payload as Extract<PetitionPayload, { type: 'ENABLE_FEATURE' }>;
    return <span className="text-gray-300">Enable feature <span className="text-green-400">{p.feature}</span></span>;
  }
  if (t === 'DISABLE_FEATURE') {
    const p = payload as Extract<PetitionPayload, { type: 'DISABLE_FEATURE' }>;
    return <span className="text-gray-300">Disable feature <span className="text-red-400">{p.feature}</span></span>;
  }
  return <span className="text-gray-500">Unknown payload type</span>;
}

function PetitionRow({
  petition,
  now,
  onAction,
}: {
  petition: PetitionState;
  now: number;
  onAction: () => void;
}) {
  const style = STATUS_STYLE[petition.status] ?? STATUS_STYLE.not_found;
  const Icon = style.icon;
  const sigPct = petition.signature_threshold_at_filing > 0
    ? (petition.signature_governance_weight / petition.signature_threshold_at_filing) * 100
    : 0;
  const totalVotes = petition.votes_for_weight + petition.votes_against_weight;
  const yesPct = totalVotes > 0
    ? (petition.votes_for_weight / totalVotes) * 100
    : 0;
  const { state, result, submit } = useSignAndAppend();
  const busy = state === 'submitting';

  const sign = useCallback(async () => {
    const built = buildPetitionSignPayload(petition.petition_id);
    const res = await submit(built.event_type, built.payload);
    if (res.ok) onAction();
  }, [petition.petition_id, submit, onAction]);

  const voteFor = useCallback(async () => {
    const built = buildPetitionVotePayload(petition.petition_id, 'for');
    const res = await submit(built.event_type, built.payload);
    if (res.ok) onAction();
  }, [petition.petition_id, submit, onAction]);

  const voteAgainst = useCallback(async () => {
    const built = buildPetitionVotePayload(petition.petition_id, 'against');
    const res = await submit(built.event_type, built.payload);
    if (res.ok) onAction();
  }, [petition.petition_id, submit, onAction]);

  const challenge = useCallback(async () => {
    const reason = window.prompt(
      'Constitutional challenge — describe why this petition violates the constitution:',
    );
    if (!reason || !reason.trim()) return;
    const built = buildChallengeFilePayload(petition.petition_id, reason.trim());
    const res = await submit(built.event_type, built.payload);
    if (res.ok) onAction();
  }, [petition.petition_id, submit, onAction]);

  return (
    <div className="border border-gray-800 bg-black/40 p-3 hover:bg-black/60 transition-colors">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon size={14} className={style.color} />
          <span className={`text-xs font-bold uppercase tracking-wider ${style.color}`}>
            {style.label}
          </span>
        </div>
        <span className="text-xs text-gray-500 font-mono truncate">
          {petition.petition_id.slice(0, 16)}…
        </span>
      </div>

      <div className="text-sm mb-2">
        <PayloadSummary payload={petition.petition_payload} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <div>
          <div className="text-gray-500">Filer</div>
          <div className="text-gray-300 font-mono truncate" title={petition.filer_id}>
            {petition.filer_id.slice(0, 12)}…
          </div>
        </div>
        <div>
          <div className="text-gray-500">Filed</div>
          <div className="text-gray-300">{formatRelative(petition.filed_at, now)}</div>
        </div>
        {petition.status === 'signatures' && (
          <div className="col-span-2">
            <div className="text-gray-500">
              Signatures: {petition.signature_governance_weight.toFixed(1)} / {petition.signature_threshold_at_filing.toFixed(1)}
            </div>
            <div className="h-1 bg-gray-800 mt-1 overflow-hidden">
              <div
                className="h-full bg-cyan-500 transition-all"
                style={{ width: `${Math.min(100, sigPct)}%` }}
              />
            </div>
          </div>
        )}
        {(petition.status === 'voting' || petition.status === 'challenge'
          || petition.status === 'passed' || petition.status === 'executed') && (
          <div className="col-span-2">
            <div className="text-gray-500">
              Vote: {petition.votes_for_weight.toFixed(1)} for / {petition.votes_against_weight.toFixed(1)} against
            </div>
            <div className="h-1 bg-gray-800 mt-1 overflow-hidden flex">
              <div
                className="h-full bg-green-500 transition-all"
                style={{ width: `${yesPct}%` }}
              />
              <div
                className="h-full bg-red-500 transition-all"
                style={{ width: `${100 - yesPct}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {petition.voting_deadline && petition.status === 'voting' && (
        <div className="text-xs text-gray-500 mt-2">
          Voting closes {formatRelative(petition.voting_deadline, now)}
        </div>
      )}
      {petition.challenge_window_until && petition.status === 'challenge' && (
        <div className="text-xs text-amber-400 mt-2">
          Challenge window closes {formatRelative(petition.challenge_window_until, now)}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mt-3">
        {petition.status === 'signatures' && (
          <button
            type="button"
            onClick={sign}
            disabled={busy}
            className="px-2 py-0.5 text-xs uppercase tracking-wider border border-cyan-700/50 bg-cyan-900/20 text-cyan-400 hover:bg-cyan-900/40 disabled:opacity-30"
          >
            {busy ? 'Signing…' : 'Sign'}
          </button>
        )}
        {petition.status === 'voting' && (
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
        {petition.status === 'challenge' && (
          <button
            type="button"
            onClick={challenge}
            disabled={busy}
            className="px-2 py-0.5 text-xs uppercase tracking-wider border border-amber-700/50 bg-amber-900/20 text-amber-400 hover:bg-amber-900/40 disabled:opacity-30"
            title="File a constitutional challenge against this passed petition"
          >
            {busy ? '…' : 'Challenge'}
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

function FilePetitionForm({ onFiled }: { onFiled?: () => void }) {
  const [paramKey, setParamKey] = useState('');
  const [paramValue, setParamValue] = useState('');
  const [previewing, setPreviewing] = useState(false);
  const [filing, setFiling] = useState(false);
  const [previewResult, setPreviewResult] = useState<
    { ok: true; changedKeys: string[]; newValues: Record<string, unknown> } |
    { ok: false; reason: string } | null
  >(null);
  const [fileResult, setFileResult] = useState<
    { ok: true; eventId: string } |
    { ok: false; reason: string } | null
  >(null);

  const handlePreview = useCallback(async () => {
    if (!paramKey.trim()) return;
    setPreviewing(true);
    setPreviewResult(null);
    try {
      // Try numeric coercion; fall back to string. Backend validator
      // rejects type mismatches with a diagnostic — surfaces directly.
      let value: unknown = paramValue;
      const numeric = Number(paramValue);
      if (paramValue.trim() !== '' && !Number.isNaN(numeric)) {
        value = numeric;
      } else if (paramValue.trim().toLowerCase() === 'true') {
        value = true;
      } else if (paramValue.trim().toLowerCase() === 'false') {
        value = false;
      }
      const payload: PetitionPayload = {
        type: 'UPDATE_PARAM',
        key: paramKey.trim(),
        value,
      };
      const res = await previewPetitionPayload(payload);
      if (res.ok) {
        setPreviewResult({
          ok: true,
          changedKeys: res.changed_keys ?? [],
          newValues: res.new_values ?? {},
        });
      } else {
        setPreviewResult({ ok: false, reason: res.reason ?? 'unknown_error' });
      }
    } catch (err) {
      setPreviewResult({
        ok: false,
        reason: err instanceof Error ? err.message : 'network_error',
      });
    } finally {
      setPreviewing(false);
    }
  }, [paramKey, paramValue]);

  const buildPayload = useCallback((): PetitionPayload | null => {
    if (!paramKey.trim()) return null;
    let value: unknown = paramValue;
    const numeric = Number(paramValue);
    if (paramValue.trim() !== '' && !Number.isNaN(numeric)) {
      value = numeric;
    } else if (paramValue.trim().toLowerCase() === 'true') {
      value = true;
    } else if (paramValue.trim().toLowerCase() === 'false') {
      value = false;
    }
    return { type: 'UPDATE_PARAM', key: paramKey.trim(), value };
  }, [paramKey, paramValue]);

  const handleFile = useCallback(async () => {
    const inner = buildPayload();
    if (!inner) return;
    setFiling(true);
    setFileResult(null);
    try {
      // Generate a fresh petition_id deterministically from the payload
      // + timestamp so refile attempts produce distinct IDs.
      const petitionId = `pet-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
      const built = buildPetitionFilePayload(petitionId, inner);
      const res = await signAndAppend({
        event_type: built.event_type,
        payload: built.payload,
      });
      if (res.ok) {
        setFileResult({ ok: true, eventId: res.event.event_id });
        onFiled?.();
      } else {
        setFileResult({ ok: false, reason: res.reason });
      }
    } catch (err) {
      setFileResult({
        ok: false,
        reason: err instanceof Error ? err.message : 'unknown_error',
      });
    } finally {
      setFiling(false);
    }
  }, [buildPayload, onFiled]);

  return (
    <div className="border border-cyan-900/50 bg-cyan-900/5 p-3">
      <div className="flex items-center gap-2 mb-3">
        <FileText size={14} className="text-cyan-400" />
        <span className="text-xs font-bold uppercase tracking-wider text-cyan-400">
          File or Preview a Petition
        </span>
      </div>
      <div className="text-xs text-gray-500 mb-3">
        <span className="text-cyan-400 font-bold">Preview</span> runs the
        governance DSL executor without touching the chain — the diagnostic
        on failure is shown verbatim.
        {' '}<span className="text-amber-400 font-bold">File</span> signs the
        same payload with your local node key and posts it to{' '}
        <span className="font-mono">/api/infonet/append</span>; the secure
        entry point ({' '}<span className="font-mono">Infonet.append</span>)
        verifies signature, replay, sequence, and binding before the event
        lands.
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-2">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">CONFIG key</label>
          <input
            type="text"
            value={paramKey}
            onChange={(e) => setParamKey(e.target.value)}
            placeholder="e.g. vote_decay_days"
            className="w-full bg-black/60 border border-gray-700 px-2 py-1 text-sm text-white font-mono focus:border-cyan-500 focus:outline-none"
            spellCheck={false}
          />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">New value</label>
          <input
            type="text"
            value={paramValue}
            onChange={(e) => setParamValue(e.target.value)}
            placeholder="e.g. 30 / true / argon2id"
            className="w-full bg-black/60 border border-gray-700 px-2 py-1 text-sm text-white font-mono focus:border-cyan-500 focus:outline-none"
            spellCheck={false}
          />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handlePreview}
          disabled={previewing || !paramKey.trim()}
          className="px-3 py-1 bg-cyan-900/30 border border-cyan-700/50 text-cyan-400 hover:bg-cyan-900/50 hover:text-cyan-300 transition-colors text-xs uppercase tracking-wider disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {previewing ? 'Validating…' : 'Preview'}
        </button>
        <button
          type="button"
          onClick={handleFile}
          disabled={filing || !paramKey.trim()}
          className="px-3 py-1 bg-amber-900/30 border border-amber-700/50 text-amber-400 hover:bg-amber-900/50 hover:text-amber-300 transition-colors text-xs uppercase tracking-wider disabled:opacity-30 disabled:cursor-not-allowed"
          title="Sign with the local node key + post to /api/infonet/append"
        >
          {filing ? 'Filing…' : 'File Petition'}
        </button>
      </div>

      {fileResult && fileResult.ok && (
        <div className="mt-3 border border-green-900/50 bg-green-900/10 p-2 text-xs">
          <div className="text-green-400 font-bold uppercase tracking-wider mb-1 flex items-center gap-1">
            <CheckCircle2 size={12} /> PETITION FILED
          </div>
          <div className="text-gray-300 font-mono break-all">
            event_id: {fileResult.eventId}
          </div>
          <div className="text-gray-500 mt-1">
            The petition is now in the SIGNATURES phase. Other nodes can
            sign with <span className="font-mono">petition_sign</span>;
            voting opens once 25% oracle_rep_active worth of signatures land.
          </div>
        </div>
      )}
      {fileResult && !fileResult.ok && (
        <div className="mt-3 border border-red-900/50 bg-red-900/10 p-2 text-xs">
          <div className="text-red-400 font-bold uppercase tracking-wider mb-1 flex items-center gap-1">
            <AlertCircle size={12} /> FILING REJECTED
          </div>
          <div className="text-gray-300 font-mono break-all">{fileResult.reason}</div>
          <div className="text-gray-500 mt-1">
            Common causes: local identity not initialized
            (open the InfonetTerminal first), filer rep below
            petition_filing_cost, or the chain rejected the signed event.
            Use Preview first to confirm the payload validates.
          </div>
        </div>
      )}

      {previewResult && previewResult.ok && (
        <div className="mt-3 border border-green-900/50 bg-green-900/10 p-2 text-xs">
          <div className="text-green-400 font-bold uppercase tracking-wider mb-1">
            VALIDATION PASSED
          </div>
          <div className="text-gray-300">
            Would change keys: {previewResult.changedKeys.map((k) => (
              <span key={k} className="text-cyan-400 font-mono mr-2">{k}</span>
            ))}
          </div>
          <div className="text-gray-500 mt-1">
            Filing this petition costs the configured petition_filing_cost in common rep.
            Production filing requires a signed event — this is the validation preview only.
          </div>
        </div>
      )}
      {previewResult && !previewResult.ok && (
        <div className="mt-3 border border-red-900/50 bg-red-900/10 p-2 text-xs">
          <div className="text-red-400 font-bold uppercase tracking-wider mb-1 flex items-center gap-1">
            <AlertCircle size={12} /> VALIDATION REJECTED
          </div>
          <div className="text-gray-300 font-mono">{previewResult.reason}</div>
        </div>
      )}
    </div>
  );
}

export default function PetitionsView({ onBack }: PetitionsViewProps) {
  const [petitions, setPetitions] = useState<PetitionState[] | null>(null);
  const [now, setNow] = useState(Date.now() / 1000);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPetitions();
      setPetitions(data.petitions);
      setNow(data.now);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'network error');
    } finally {
      setLoading(false);
    }
  }, []);

  const hasActivePhase = (petitions || []).some((p) =>
    p.status === 'signatures' || p.status === 'voting' || p.status === 'challenge',
  );

  useEffect(() => {
    void reload();
    const interval = setInterval(() => void reload(), hasActivePhase ? 8_000 : 30_000);
    return () => clearInterval(interval);
  }, [reload, hasActivePhase]);

  const grouped = useMemo(() => {
    if (!petitions) return null;
    const active = petitions.filter((p) =>
      ['signatures', 'voting', 'challenge'].includes(p.status),
    );
    const passed = petitions.filter((p) =>
      ['passed', 'executed'].includes(p.status),
    );
    const closed = petitions.filter((p) =>
      ['failed_signatures', 'failed_vote', 'voided_challenge'].includes(p.status),
    );
    return { active, passed, closed };
  }, [petitions]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-gray-800/50 pb-3 mb-4 shrink-0">
        <button
          onClick={onBack}
          className="flex items-center text-cyan-400 hover:text-cyan-300 transition-colors text-sm"
        >
          <ChevronLeft size={14} className="mr-1" />
          BACK TO TERMINAL
        </button>
        <div className="text-sm text-cyan-400 font-bold uppercase tracking-widest flex items-center gap-2">
          <Vote size={16} />
          BALLOT — Governance Petitions
        </div>
        <button
          onClick={() => void reload()}
          disabled={loading}
          className="text-xs text-gray-500 hover:text-cyan-400 disabled:opacity-30"
        >
          {loading ? <Loader size={12} className="animate-spin" /> : 'REFRESH'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto pr-3 space-y-6">
        <div className="text-xs text-gray-500 leading-relaxed">
          Petitions amend protocol parameters via the type-safe governance DSL.
          Lifecycle: <span className="text-cyan-400">SIGNATURES</span> (14d, 25% oracle_rep_active threshold)
          → <span className="text-blue-400">VOTING</span> (7d, 67% supermajority + 30% quorum)
          → <span className="text-amber-400">CHALLENGE</span> (48h constitutional challenge window)
          → <span className="text-green-400">EXECUTED</span>.
          The DSL executor rejects unknown CONFIG keys, type mismatches, out-of-bounds
          values, and IMMUTABLE_PRINCIPLES writes — see the validation preview below.
        </div>

        <FilePetitionForm onFiled={() => void reload()} />

        {error && (
          <div className="border border-red-900/50 bg-red-900/10 p-3 text-xs text-red-400">
            <div className="flex items-center gap-2">
              <AlertCircle size={12} />
              <span className="font-bold">Failed to load petitions</span>
            </div>
            <div className="text-gray-400 mt-1 font-mono">{error}</div>
          </div>
        )}

        {grouped && grouped.active.length > 0 && (
          <div>
            <div className="text-xs uppercase tracking-wider text-cyan-400 mb-2">
              Active Petitions ({grouped.active.length})
            </div>
            <div className="space-y-2">
              {grouped.active.map((p) => (
                <PetitionRow key={p.petition_id} petition={p} now={now} onAction={() => void reload()} />
              ))}
            </div>
          </div>
        )}

        {grouped && grouped.passed.length > 0 && (
          <div>
            <div className="text-xs uppercase tracking-wider text-green-400 mb-2">
              Passed Petitions ({grouped.passed.length})
            </div>
            <div className="space-y-2">
              {grouped.passed.map((p) => (
                <PetitionRow key={p.petition_id} petition={p} now={now} onAction={() => void reload()} />
              ))}
            </div>
          </div>
        )}

        {grouped && grouped.closed.length > 0 && (
          <div>
            <div className="text-xs uppercase tracking-wider text-gray-500 mb-2">
              Closed (Failed / Voided) ({grouped.closed.length})
            </div>
            <div className="space-y-2">
              {grouped.closed.map((p) => (
                <PetitionRow key={p.petition_id} petition={p} now={now} onAction={() => void reload()} />
              ))}
            </div>
          </div>
        )}

        {grouped && petitions && petitions.length === 0 && !loading && (
          <div className="border border-gray-800 bg-black/40 p-6 text-center">
            <div className="text-gray-500 text-sm mb-1">No petitions on the chain yet.</div>
            <div className="text-gray-600 text-xs">
              File one with the Preview tool above to see the lifecycle in action.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
