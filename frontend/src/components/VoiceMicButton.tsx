'use client';
/**
 * VoiceMicButton — PTT owner + phase matrix (voice-agent plan §5.2/§5.4).
 *
 * Closed-state chrome clones LOCATE with the violet agent accent; every
 * color-coded phase also carries a text chip (color independence). Hold V is
 * wired in useKeyboardShortcuts; pointer press-and-hold mirrors it here.
 * In degraded/deterministic mode the button renders its dimmed TXT state and
 * routes activation to the composer instead of mic capture (§3.7 — there is
 * no brokered STT path without a model).
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { voiceController } from '@/lib/voiceController';
import type { VoicePhase } from '@/lib/voiceTypes';
import { useTranslation } from '@/i18n';

interface PhaseVisual {
  buttonClass: string;
  chip: string | null;
  interactive: boolean;
}

/** Per-phase visual matrix: border / text / chip. */
const PHASE_MATRIX: Record<VoicePhase, PhaseVisual> = {
  'opt-in-required': {
    buttonClass: 'border-[var(--border-primary)] text-[var(--text-muted)] opacity-50 cursor-pointer hover:border-violet-800',
    chip: 'states.optInRequired',
    interactive: false,
  },
  'lean-unavailable': {
    buttonClass: 'border-[var(--border-primary)] text-[var(--text-muted)] opacity-50 cursor-not-allowed',
    chip: 'states.leanMode',
    interactive: false,
  },
  idle: {
    // Teal-dominant idle state — filled cyan, black label, matches LOCATE's
    // family but inverted so the AI console reads as the primary control.
    buttonClass: 'border-cyan-500 bg-cyan-400 text-black hover:bg-cyan-300 font-bold',
    chip: null,
    interactive: true,
  },
  connecting: {
    buttonClass: 'border-violet-400/70 text-violet-300 bg-violet-500/20',
    chip: 'LINK…',
    interactive: true,
  },
  listening: {
    buttonClass: 'border-violet-300 text-violet-200 bg-violet-500/30 shadow-[0_0_18px_rgba(139,92,246,0.45)]',
    chip: null,
    interactive: true,
  },
  thinking: {
    buttonClass: 'border-cyan-700 text-cyan-400 bg-cyan-950/40',
    chip: '…',
    interactive: true,
  },
  speaking: {
    buttonClass: 'border-cyan-500/60 text-cyan-300 bg-cyan-950/40',
    chip: 'TX',
    interactive: true,
  },
  error: {
    buttonClass: 'border-red-800/70 text-red-400 bg-red-950/30',
    chip: 'FAULT',
    interactive: true,
  },
  'quota-capped': {
    buttonClass: 'border-amber-700/70 text-amber-400 bg-amber-950/20 opacity-60 cursor-not-allowed',
    chip: '$ CAP',
    interactive: false,
  },
};

const PTT_HOLD_MS = 250;

export default function VoiceMicButton() {
  const { t } = useTranslation();
  const state = useSyncExternalStore(voiceController.subscribe, voiceController.getState);
  const visual = PHASE_MATRIX[state.phase];
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // True only once a press crossed the hold threshold. Consumed (reset) by
  // handleClick so the synthetic click that follows pointerup — which fires
  // AFTER endHold() ran — can never double-fire as a panel toggle.
  const wasHoldRef = useRef(false);
  const [showHint, setShowHint] = useState(false);

  // One-time 6-second discoverability hint (dismissal persisted once). §5.4
  // gates it on voice being enabled: phase `idle` is the only fully-enabled,
  // non-degraded resting phase, so a dimmed/degraded button never nags.
  useEffect(() => {
    if (state.phase !== 'idle' || typeof window === 'undefined' || window.localStorage.getItem('sb_voice_hint_seen_v1')) {
      setShowHint(false);
      return;
    }
    setShowHint(true);
    const id = setTimeout(() => {
      setShowHint(false);
      window.localStorage.setItem('sb_voice_hint_seen_v1', '1');
    }, 6000);
    return () => clearTimeout(id);
  }, [state.phase]);

  useEffect(
    () => () => {
      if (holdTimer.current) clearTimeout(holdTimer.current);
    },
    [],
  );

  const tooltip =
    state.phase === 'opt-in-required'
      ? // Plain one-liner — the long verbatim reasons live in the panel's
        // setup card instead of a hover tooltip nobody can read.
        t('voice.tooltip.optInRequired')
      : state.phase === 'lean-unavailable'
        ? state.reasons[0] || t('voice.states.leanMode')
        : state.phase === 'error'
          ? // Verbatim-honesty FAULT: quote the real close/error reason as-is.
            state.lastFaultReason || t('voice.micAria.error')
          : undefined;

  const startHold = () => {
    if (!visual.interactive) return;
    wasHoldRef.current = false;
    holdTimer.current = setTimeout(() => {
      wasHoldRef.current = true;
      if (state.degraded) {
        // §3.7 zero-model rule: no brokered STT path → route to composer.
        voiceController.requestComposerFocus();
        voiceController.setPanelOpen(true);
      } else {
        voiceController.beginPtt();
      }
    }, PTT_HOLD_MS);
  };

  const endHold = () => {
    if (holdTimer.current) {
      clearTimeout(holdTimer.current);
      holdTimer.current = null;
    }
    if (wasHoldRef.current) voiceController.endPtt();
  };

  const handleClick = () => {
    // A hold-release arrives here as a synthetic click after endHold(); the
    // flag is consumed exactly once so the release never toggles the panel.
    // startHold() resets it, so a stale flag cannot swallow the next tap.
    if (wasHoldRef.current) {
      wasHoldRef.current = false;
      return;
    }
    if (visual.interactive) voiceController.setPanelOpen(!state.panelOpen);
    else voiceController.setPanelOpen(true);
    if (state.degraded) voiceController.requestComposerFocus();
  };

  const waveform = state.pttHeld || state.phase === 'listening';

  return (
    <div className="relative" data-testid="voice-mic-button">
      {showHint && (
        <div data-testid="voice-hint-chip" className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 whitespace-nowrap bg-[var(--bg-primary)]/90 border border-violet-500/40 px-2 py-1 text-[11px] font-mono tracking-wide text-violet-300">
          {t('voice.hint.ptt')}
        </div>
      )}
      <button
        type="button"
        onPointerDown={startHold}
        onPointerUp={endHold}
        onPointerCancel={endHold}
        onPointerLeave={endHold}
        onClick={handleClick}
        title={tooltip}
        aria-label={t(`voice.micAria.${state.phase}`)}
        aria-disabled={!visual.interactive}
        className={`flex items-center gap-2 border px-5 py-2.5 min-h-[40px] text-[11px] font-mono tracking-[0.15em] transition-colors focus-visible:outline focus-visible:outline-violet-400 ${visual.buttonClass}`}
      >
        {/* Slash icon for opt-in-required */}
        {state.phase === 'opt-in-required' && (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M12 3a3 3 0 0 0-3 3v5m0 3a3 3 0 0 0 5.6 1.5M17 11v-1M5 11v1a7 7 0 0 0 10.6 6M3 3l18 18" />
          </svg>
        )}

        {/* 4-bar waveform while listening */}
        {waveform && (
          <span className="flex items-end gap-[2px] h-3 motion-reduce:hidden" data-testid="voice-waveform">
            {[0, 1, 2, 3].map((i) => (
              <span
                key={i}
                className="w-[3px] bg-violet-300 animate-pulse motion-reduce:animate-none"
                style={{ height: `${5 + ((i * 3) % 7)}px` }}
              />
            ))}
          </span>
        )}

        {/* Spinner while thinking — LocateBar clone */}
        {state.phase === 'thinking' && (
          <span className="w-3 h-3 border border-cyan-500 border-t-transparent rounded-full animate-spin motion-reduce:animate-none" />
        )}

        {/* Cyan equalizer while speaking */}
        {state.phase === 'speaking' && (
          <span className="flex items-center gap-[2px] h-3 motion-reduce:hidden">
            {[0, 1, 2].map((i) => (
              <span key={i} className="w-[3px] bg-cyan-400 animate-pulse motion-reduce:animate-none" style={{ height: `${4 + i * 3}px` }} />
            ))}
          </span>
        )}

        {/* Mic glyph — the AI console's identity mark */}
        {state.phase === 'idle' && (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
            <path d="M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z" />
            <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
          </svg>
        )}

        <span>{t('voice.label')}</span>

        {/* Phase text chip — every color-coded phase carries one */}
        {visual.chip && (
          <span
            data-testid="voice-phase-chip"
            className={`px-1 py-[1px] text-[11px] font-bold tracking-wide rounded-sm ${
              state.phase === 'error'
                ? 'bg-red-500/20 border border-red-500/40 text-red-300'
                : state.phase === 'quota-capped'
                  ? 'bg-amber-500/20 border border-amber-500/40 text-amber-300'
                  : 'bg-violet-500/20 border border-violet-500/40 text-violet-300'
            }`}
          >
            {visual.chip.startsWith('states.') ? t(`voice.${visual.chip}`) : visual.chip}
          </span>
        )}

        {/* Degraded corner badge — "NO AI" when nothing usable is connected;
            "TXT" only for a text-only provider (local chat model, or Anthropic's
            Claude — text-in/text-out, no realtime speech API). */}
        {state.degraded && (
          <span
            data-testid="voice-txt-badge"
            title={
              state.providerResolved === 'anthropic_text'
                ? t('voice.badge.anthropicTxtTitle')
                : state.providerResolved === 'local_text'
                  ? t('voice.badge.txtTitle')
                  : t('voice.badge.noAiTitle')
            }
            className="absolute -top-1.5 -right-1.5 px-1 text-[11px] font-mono font-bold bg-[var(--bg-primary)] border border-cyan-800/60 text-cyan-400"
          >
            {state.providerResolved === 'local_text' || state.providerResolved === 'anthropic_text'
              ? 'TXT'
              : 'NO AI'}
          </span>
        )}
      </button>
    </div>
  );
}
