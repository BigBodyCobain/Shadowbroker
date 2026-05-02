'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, AlertTriangle, Lock, Clock, ShieldOff, Loader, CheckCircle2 } from 'lucide-react';
import {
  buildGateShutdownAppealFilePayload,
  buildGateShutdownFilePayload,
  buildGateSuspendFilePayload,
  fetchGateState,
  freshLocalId,
  type GateState,
} from '@/mesh/infonetEconomyClient';
import { useSignAndAppend } from '@/hooks/useSignAndAppend';

interface GateShutdownViewProps {
  gateId: string;
  onBack: () => void;
}

const STATUS_STYLE: Record<string, { color: string; label: string; icon: typeof Lock }> = {
  active:    { color: 'text-green-400', label: 'ACTIVE',    icon: CheckCircle2 },
  suspended: { color: 'text-amber-400', label: 'SUSPENDED', icon: Clock },
  shutdown:  { color: 'text-red-500',   label: 'SHUTDOWN',  icon: ShieldOff },
};

function formatTs(ts: number | null): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString();
}

function formatRelative(ts: number | null, now: number): string {
  if (!ts) return '—';
  const delta = ts - now;
  const abs = Math.abs(delta);
  const days = Math.floor(abs / 86400);
  const hours = Math.floor((abs % 86400) / 3600);
  if (delta > 0) {
    if (days > 0) return `in ${days}d ${hours}h`;
    return `in ${hours}h`;
  }
  if (days > 0) return `${days}d ago`;
  return `${hours}h ago`;
}

export default function GateShutdownView({ gateId, onBack }: GateShutdownViewProps) {
  const [data, setData] = useState<GateState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filing forms — reused for suspend / shutdown / appeal.
  const [reason, setReason] = useState('');
  const [evidenceHash, setEvidenceHash] = useState('');
  const suspendAction = useSignAndAppend();
  const shutdownAction = useSignAndAppend();
  const appealAction = useSignAndAppend();

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchGateState(gateId);
      if (res.ok) {
        setData(res);
      } else {
        setError(res.reason);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'network error');
    } finally {
      setLoading(false);
    }
  }, [gateId]);

  const hasActivePhase = data?.suspension.status === 'suspended';

  useEffect(() => {
    void reload();
    const interval = setInterval(() => void reload(), hasActivePhase ? 8_000 : 30_000);
    return () => clearInterval(interval);
  }, [reload, hasActivePhase]);

  const status = data ? STATUS_STYLE[data.suspension.status] ?? STATUS_STYLE.active : null;

  const fileSuspend = useCallback(async () => {
    if (!reason.trim() || !evidenceHash.trim()) return;
    const built = buildGateSuspendFilePayload(
      freshLocalId('sus'), gateId, reason.trim(), [evidenceHash.trim()],
    );
    const res = await suspendAction.submit(built.event_type, built.payload);
    if (res.ok) {
      setReason(''); setEvidenceHash('');
      void reload();
    }
  }, [reason, evidenceHash, gateId, suspendAction, reload]);

  const fileShutdown = useCallback(async () => {
    if (!reason.trim() || !evidenceHash.trim()) return;
    const built = buildGateShutdownFilePayload(
      freshLocalId('shd'), gateId, reason.trim(), [evidenceHash.trim()],
    );
    const res = await shutdownAction.submit(built.event_type, built.payload);
    if (res.ok) {
      setReason(''); setEvidenceHash('');
      void reload();
    }
  }, [reason, evidenceHash, gateId, shutdownAction, reload]);

  const fileAppeal = useCallback(async () => {
    if (!reason.trim() || !evidenceHash.trim()) return;
    if (!data?.shutdown.pending_petition_id) return;
    const built = buildGateShutdownAppealFilePayload(
      freshLocalId('app'),
      gateId,
      data.shutdown.pending_petition_id,
      reason.trim(),
      [evidenceHash.trim()],
    );
    const res = await appealAction.submit(built.event_type, built.payload);
    if (res.ok) {
      setReason(''); setEvidenceHash('');
      void reload();
    }
  }, [reason, evidenceHash, gateId, data, appealAction, reload]);

  const canFileSuspend = data?.suspension.status === 'active';
  const canFileShutdown = data?.suspension.status === 'suspended' && !data?.shutdown.has_pending;
  const canFileAppeal = data?.shutdown.pending_status === 'executing';

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-gray-800/50 pb-3 mb-4 shrink-0">
        <button onClick={onBack} className="flex items-center text-cyan-400 hover:text-cyan-300 text-sm">
          <ChevronLeft size={14} className="mr-1" /> BACK
        </button>
        <div className="text-sm text-amber-400 font-bold uppercase tracking-widest flex items-center gap-2">
          <ShieldOff size={16} /> GATE SHUTDOWN — {gateId}
        </div>
        <button
          onClick={() => void reload()}
          disabled={loading}
          className="text-xs text-gray-500 hover:text-amber-400 disabled:opacity-30"
        >
          {loading ? <Loader size={12} className="animate-spin" /> : 'REFRESH'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto pr-3 space-y-4">
        <div className="text-xs text-gray-500 leading-relaxed">
          Gate shutdown is two-tier: <span className="text-amber-400">SUSPEND</span> (30-day reversible freeze)
          → <span className="text-red-400">SHUTDOWN</span> (irreversible archive, 7-day execution delay
          with one typed appeal allowed). Voting uses oracle_rep_active weight; thresholds are higher for
          locked gates (<span className="text-cyan-400">75% suspend / 80% shutdown</span> instead of 67% / 75%).
          Anti-stall: one appeal per shutdown, 48h filing window after vote passes.
        </div>

        {error && (
          <div className="border border-red-900/50 bg-red-900/10 p-3 text-xs text-red-400">
            <AlertTriangle size={12} className="inline mr-1" /> {error}
          </div>
        )}

        {data && status && (
          <>
            <div className="border border-gray-800 bg-black/40 p-3">
              <div className="flex items-center gap-2 mb-2">
                <status.icon size={14} className={status.color} />
                <span className={`text-xs font-bold uppercase tracking-wider ${status.color}`}>
                  {status.label}
                </span>
                {data.locked.is_locked && (
                  <span className="ml-2 text-cyan-400 text-xs flex items-center gap-1">
                    <Lock size={12} /> LOCKED
                  </span>
                )}
                {data.ratified && (
                  <span className="ml-2 text-green-400 text-xs">✓ RATIFIED</span>
                )}
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
                <div>
                  <div className="text-gray-500">Members</div>
                  <div className="text-white">{data.members.length}</div>
                </div>
                <div>
                  <div className="text-gray-500">Cumulative Oracle Rep</div>
                  <div className="text-white">{data.cumulative_member_oracle_rep.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-gray-500">Entry Sacrifice</div>
                  <div className="text-white">{data.meta.entry_sacrifice} common rep</div>
                </div>
                <div>
                  <div className="text-gray-500">Min Overall Rep</div>
                  <div className="text-white">{data.meta.min_overall_rep}</div>
                </div>
                <div>
                  <div className="text-gray-500">Created</div>
                  <div className="text-white text-xs">{formatTs(data.meta.created_at)}</div>
                </div>
                <div>
                  <div className="text-gray-500">Locked At</div>
                  <div className="text-white text-xs">
                    {data.locked.locked_at ? formatTs(data.locked.locked_at) : '—'}
                  </div>
                </div>
              </div>
            </div>

            {data.suspension.status === 'suspended' && (
              <div className="border border-amber-900/50 bg-amber-900/10 p-3">
                <div className="text-xs uppercase tracking-wider text-amber-400 mb-2 flex items-center gap-1">
                  <Clock size={12} /> Suspension State
                </div>
                <div className="text-xs text-gray-300 space-y-1">
                  <div>Suspended at: <span className="text-white">{formatTs(data.suspension.suspended_at)}</span></div>
                  <div>
                    Auto-unsuspends:{' '}
                    <span className="text-amber-400">
                      {formatRelative(data.suspension.suspended_until, data.now)} ({formatTs(data.suspension.suspended_until)})
                    </span>
                  </div>
                  <div className="text-gray-500 mt-2">
                    During suspension: no gate_message, gate_enter, gate_exit. Members retain
                    membership; content preserved (append-only).
                  </div>
                </div>
              </div>
            )}

            {data.shutdown.has_pending && (
              <div className="border border-red-900/50 bg-red-900/10 p-3">
                <div className="text-xs uppercase tracking-wider text-red-400 mb-2 flex items-center gap-1">
                  <ShieldOff size={12} /> Pending Shutdown Petition
                </div>
                <div className="text-xs space-y-1">
                  <div className="text-gray-300">
                    ID: <span className="font-mono text-white">{data.shutdown.pending_petition_id}</span>
                  </div>
                  <div className="text-gray-300">
                    Status:{' '}
                    <span className={
                      data.shutdown.pending_status === 'executing' ? 'text-red-400' :
                      data.shutdown.pending_status === 'appealed'  ? 'text-amber-400' :
                      data.shutdown.pending_status === 'voided_appeal' ? 'text-green-400' :
                      'text-gray-300'
                    }>
                      {data.shutdown.pending_status?.toUpperCase()}
                    </span>
                  </div>
                  {data.shutdown.execution_at && (
                    <div className="text-red-400">
                      Executes {formatRelative(data.shutdown.execution_at, data.now)} (
                      {formatTs(data.shutdown.execution_at)})
                    </div>
                  )}
                  {data.shutdown.pending_status === 'appealed' && (
                    <div className="text-amber-400">
                      ⚠ Execution timer is PAUSED while appeal is voted on. If the appeal
                      passes, the shutdown is voided. If it fails, the timer resumes.
                    </div>
                  )}
                </div>
              </div>
            )}

            {data.shutdown.executed && (
              <div className="border border-red-900/50 bg-red-900/20 p-3 text-xs">
                <div className="text-red-400 font-bold uppercase tracking-wider mb-1">
                  GATE SHUT DOWN — IRREVERSIBLE
                </div>
                <div className="text-gray-400">
                  Members released. Content archived. gate_id retired. No petition can reopen.
                </div>
              </div>
            )}

            {!data.shutdown.executed && (canFileSuspend || canFileShutdown || canFileAppeal) && (
              <div className="border border-gray-800 bg-black/40 p-3">
                <div className="text-xs uppercase tracking-wider text-gray-300 mb-2">
                  File a Petition
                </div>
                <div className="text-xs text-gray-500 mb-2">
                  Reason and at least one evidence hash are required. Filing
                  costs common rep (suspend: 15, shutdown: 25, appeal: 20)
                  and triggers a 7-day vote window.
                  {canFileSuspend && ' Suspend → 30-day reversible freeze.'}
                  {canFileShutdown && ' Shutdown requires active suspension.'}
                  {canFileAppeal && ' Appeal pauses the 7-day execution timer.'}
                </div>
                <div className="space-y-2 text-xs">
                  <input
                    type="text"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="reason (max 2000 chars)"
                    maxLength={2000}
                    className="w-full bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono"
                  />
                  <input
                    type="text"
                    value={evidenceHash}
                    onChange={(e) => setEvidenceHash(e.target.value)}
                    placeholder="evidence hash (e.g. ipfs://… or sha256:…)"
                    className="w-full bg-black/60 border border-gray-700 px-2 py-1 text-white font-mono"
                  />
                  <div className="flex flex-wrap gap-2">
                    {canFileSuspend && (
                      <button
                        type="button"
                        onClick={fileSuspend}
                        disabled={
                          suspendAction.state === 'submitting' ||
                          !reason.trim() || !evidenceHash.trim()
                        }
                        className="px-3 py-1 uppercase tracking-wider border border-amber-700/50 bg-amber-900/20 text-amber-400 hover:bg-amber-900/40 disabled:opacity-30"
                      >
                        {suspendAction.state === 'submitting' ? 'Filing…' : 'File Suspend'}
                      </button>
                    )}
                    {canFileShutdown && (
                      <button
                        type="button"
                        onClick={fileShutdown}
                        disabled={
                          shutdownAction.state === 'submitting' ||
                          !reason.trim() || !evidenceHash.trim()
                        }
                        className="px-3 py-1 uppercase tracking-wider border border-red-700/50 bg-red-900/20 text-red-400 hover:bg-red-900/40 disabled:opacity-30"
                      >
                        {shutdownAction.state === 'submitting' ? 'Filing…' : 'File Shutdown'}
                      </button>
                    )}
                    {canFileAppeal && (
                      <button
                        type="button"
                        onClick={fileAppeal}
                        disabled={
                          appealAction.state === 'submitting' ||
                          !reason.trim() || !evidenceHash.trim()
                        }
                        className="px-3 py-1 uppercase tracking-wider border border-cyan-700/50 bg-cyan-900/20 text-cyan-400 hover:bg-cyan-900/40 disabled:opacity-30"
                      >
                        {appealAction.state === 'submitting' ? 'Filing…' : 'File Appeal'}
                      </button>
                    )}
                  </div>
                </div>
                {(suspendAction.result && !suspendAction.result.ok) && (
                  <div className="text-red-400 font-mono text-xs mt-2 break-all">
                    <AlertTriangle size={10} className="inline mr-1" />
                    {suspendAction.result.reason}
                  </div>
                )}
                {(shutdownAction.result && !shutdownAction.result.ok) && (
                  <div className="text-red-400 font-mono text-xs mt-2 break-all">
                    <AlertTriangle size={10} className="inline mr-1" />
                    {shutdownAction.result.reason}
                  </div>
                )}
                {(appealAction.result && !appealAction.result.ok) && (
                  <div className="text-red-400 font-mono text-xs mt-2 break-all">
                    <AlertTriangle size={10} className="inline mr-1" />
                    {appealAction.result.reason}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
