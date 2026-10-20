'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Shield } from 'lucide-react';
import { beginInfonetTerminalSession } from '@/lib/infonetTerminalSession';
import InfonetShell from '@/components/InfonetTerminal/InfonetShell';

type Props = {
  active: boolean;
  expanded: boolean;
  wormholeBusy: boolean;
  launchGate?: string;
  onExpandedChange: (expanded: boolean) => void;
  onEnterWormhole: () => Promise<void>;
  onTeardown: () => void;
  onLaunchGateConsumed?: () => void;
  onOpenDeadDrop?: (peerId: string, options?: { showSas?: boolean }) => void;
};

function InfonetIntro({
  busy,
  status,
  error,
  onEnter,
}: {
  busy: boolean;
  status: string;
  error: string;
  onEnter: () => void;
}) {
  return (
    <div className="flex-1 min-h-0 flex flex-col items-center justify-center px-3 py-4 text-center border-l-2 border-cyan-800/20 bg-[#04070b]">
      <div className="w-full max-w-sm border border-cyan-900/40 bg-cyan-950/10 px-4 py-4">
        <div className="text-sm font-mono tracking-[0.22em] text-cyan-300 mb-2">INFONET TERMINAL</div>
        <p className="text-[12px] font-mono text-[var(--text-secondary)] leading-[1.6] text-left">
          Obfuscated Wormhole lane for the Infonet shell. Leave this tab to shut Wormhole down.
        </p>
        {status && !error && (
          <div className="mt-3 text-left text-[12px] font-mono text-cyan-300/85 leading-relaxed border border-cyan-900/30 bg-cyan-950/10 px-3 py-2">
            {status}
          </div>
        )}
        {error && (
          <div className="mt-3 text-left text-[12px] font-mono text-amber-300/90 leading-relaxed border border-amber-900/30 bg-amber-950/10 px-3 py-2">
            {error}
          </div>
        )}
        <button
          type="button"
          onClick={onEnter}
          disabled={busy}
          className="mt-3 w-full px-4 py-2 text-sm font-mono tracking-[0.18em] text-cyan-200 border border-cyan-600/50 bg-cyan-950/30 hover:bg-cyan-950/50 hover:border-cyan-400/60 disabled:opacity-60 transition-colors"
        >
          {busy ? 'OPENING…' : 'ENTER WORMHOLE'}
        </button>
      </div>
    </div>
  );
}

export default function InfonetTerminalPanel({
  active,
  expanded,
  wormholeBusy,
  launchGate,
  onExpandedChange,
  onEnterWormhole,
  onTeardown,
  onLaunchGateConsumed,
  onOpenDeadDrop,
}: Props) {
  const [sessionActive, setSessionActive] = useState(false);
  const [laneBusy, setLaneBusy] = useState(false);
  const [laneError, setLaneError] = useState('');
  const [laneStatus, setLaneStatus] = useState('');
  const prepStartedRef = useRef(false);

  const shellOpen = active && sessionActive;

  const resetSession = useCallback(() => {
    setSessionActive(false);
    setLaneBusy(false);
    setLaneError('');
    setLaneStatus('');
    prepStartedRef.current = false;
  }, []);

  useEffect(() => {
    if (active) return;
    resetSession();
    onTeardown();
  }, [active, onTeardown, resetSession]);

  useEffect(() => {
    if (!shellOpen) return;
    let cancelled = false;

    const connectParticipantNode = async () => {
      try {
        if (cancelled) return;
        await beginInfonetTerminalSession();
      } catch {
        // Remote viewers may not have local-operator rights.
      }
    };

    void connectParticipantNode();
    return () => {
      cancelled = true;
    };
  }, [shellOpen]);

  const startWormholeLane = useCallback(async () => {
    if (prepStartedRef.current) return;
    prepStartedRef.current = true;
    setLaneError('');
    setLaneStatus('Starting Wormhole obfuscated lane…');
    setLaneBusy(true);
    try {
      await onEnterWormhole();
      setLaneStatus('');
    } catch (err) {
      prepStartedRef.current = false;
      setSessionActive(false);
      const message =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : 'Could not start Wormhole.';
      setLaneError(message);
      setLaneStatus('');
    } finally {
      setLaneBusy(false);
    }
  }, [onEnterWormhole]);

  const handleEnter = useCallback(() => {
    setLaneError('');
    setLaneStatus('');
    setSessionActive(true);
    onExpandedChange(true);
    void startWormholeLane();
  }, [onExpandedChange, startWormholeLane]);

  const handleShellClose = useCallback(() => {
    resetSession();
    onTeardown();
  }, [onTeardown, resetSession]);

  if (!active) {
    return (
      <div className="flex-1 min-h-0 flex flex-col items-center justify-center px-4 py-6 text-center border-l-2 border-cyan-800/20">
        <Shield size={16} className="text-cyan-400 mb-2" />
        <div className="text-sm font-mono tracking-[0.2em] text-cyan-300">INFONET TERMINAL</div>
        <div className="mt-2 text-[13px] font-mono text-[var(--text-secondary)] leading-relaxed">
          Expand Meshtastic Chat to open the Wormhole terminal.
        </div>
      </div>
    );
  }

  if (!sessionActive) {
    return (
      <InfonetIntro
        busy={laneBusy || wormholeBusy}
        status={laneStatus}
        error={laneError}
        onEnter={handleEnter}
      />
    );
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col border-l-2 border-cyan-800/25 bg-[#04070b]">
      <div className="flex items-center justify-between gap-2 border-b border-cyan-900/40 px-2 py-1.5 shrink-0">
        <div className="min-w-0 text-[12px] font-mono tracking-[0.14em] text-cyan-300/90 truncate">
          {laneBusy ? 'wormhole · obfuscated lane starting' : 'infonet terminal'}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {!expanded ? (
            <button
              type="button"
              onClick={() => onExpandedChange(true)}
              className="px-2 py-0.5 text-[11px] font-mono tracking-[0.12em] text-cyan-300 border border-cyan-800/40 hover:bg-cyan-950/30"
            >
              EXPAND
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onExpandedChange(false)}
              className="px-2 py-0.5 text-[11px] font-mono tracking-[0.12em] text-cyan-300 border border-cyan-800/40 hover:bg-cyan-950/30"
            >
              SNAP
            </button>
          )}
          <button
            type="button"
            onClick={handleShellClose}
            className="px-2 py-0.5 text-[11px] font-mono tracking-[0.12em] text-slate-400 border border-slate-700/40 hover:bg-white/5"
          >
            LEAVE
          </button>
        </div>
      </div>

      {laneError && (
        <div className="px-2 py-1 text-[12px] font-mono text-amber-300/90 border-b border-amber-900/30 bg-amber-950/10 shrink-0">
          {laneError}
        </div>
      )}

      <div className="flex-1 min-h-0 min-w-0 overflow-hidden infonet-font">
        <InfonetShell
          isOpen={shellOpen}
          embedded
          launchGate={launchGate}
          onLaunchGateConsumed={onLaunchGateConsumed}
          onClose={handleShellClose}
          onOpenDeadDrop={onOpenDeadDrop}
        />
      </div>
    </div>
  );
}
