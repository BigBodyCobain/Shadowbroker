'use client';
/**
 * VoiceHudPanel — the voice console panel (voice-agent plan §5.3).
 *
 * Grows upward from the mic row using LocateBar's dropdown pattern. U4 scope:
 * header (model + cost chips), reverse-chronological transcript with verbatim
 * tool rows, and the always-present composer driving the identical
 * deterministic pipeline. The NARRATE block / freshness strip land with U5's
 * grounding composer; collapse is panel open/close only — the one-line ticker
 * mode is deferred (see the U4 milestone report).
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { voiceController } from '@/lib/voiceController';
import VoiceSetupCard from '@/components/VoiceSetupCard';
import { useTranslation } from '@/i18n';
import type { FreshnessDisposition } from '@/lib/voiceFreshness';

/** Freshness disposition → status-bar feed-dot class (§5.3 provenance strip). */
const DISPOSITION_DOT: Record<FreshnessDisposition, string> = {
  live: 'feed-dot-healthy',
  aging: 'feed-dot-stale',
  stale: 'feed-dot-stale',
  unknown: 'feed-dot-offline',
};

export default function VoiceHudPanel({
  onSubmit,
  onClose,
}: {
  onSubmit: (text: string) => Promise<void> | void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const state = useSyncExternalStore(voiceController.subscribe, voiceController.getState);
  const [value, setValue] = useState('');
  // "Change model" toggle — reopens the setup card on demand even after a
  // provider is already configured (saving a different provider/key upserts).
  const [setupOpen, setSetupOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus management: open → composer; also when the mic routes here (§3.7).
  useEffect(() => {
    if (state.composerFocusNonce > 0 || state.panelOpen) inputRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.composerFocusNonce]);

  const submit = () => {
    const text = value.trim();
    if (!text) return;
    setValue('');
    void onSubmit(text);
  };

  // Reverse-chronological transcript: newest last, container scrolls to bottom.
  const turnsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = turnsRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state.turns.length]);

  // §4.6/§5.5 honesty tooltips: estimated / worst-case-rate / incomplete each
  // get their own verbatim-honest disclosure on the spend chip.
  const cost = state.cost;
  const costParts: string[] = [];
  if (cost) {
    costParts.push(t('voice.panel.costNote'));
    if (cost.note) costParts.push(cost.note);
    if (cost.estimated) costParts.push(t('voice.panel.costEstimated'));
    if (cost.ratesRecognized === false) costParts.push(t('voice.panel.costWorstCase'));
    if (cost.incomplete) costParts.push(t('voice.panel.costIncomplete'));
  }
  const costTooltip = costParts.join(' — ');

  return (
    <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 w-[520px] max-w-[92vw] max-h-[420px] z-[200] bg-[var(--bg-secondary)] border border-violet-500/40 shadow-[0_-8px_30px_rgba(0,0,0,0.4)] flex flex-col" data-testid="voice-hud-panel">
      {/* Header row */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border-primary)]">
        <span className="text-[11px] text-violet-400 font-mono font-bold tracking-widest">{`>_ ${t('voice.panel.title')}`}</span>
        {state.modelLabel && (
          <span className="px-1 py-[1px] text-[11px] font-mono bg-violet-500/20 border border-violet-500/40 text-violet-300 tracking-wide">
            {state.modelLabel}
          </span>
        )}
        <span className="flex-1" />
        {/* Daily spend chip (§4.3 dailySpend) — only when a budget is set. */}
        {state.dailySpend && state.dailySpend.budgetUsd !== 'off' && (
          <span
            data-testid="voice-spend-chip"
            title={t('voice.panel.spendNote')}
            className={`px-1 py-[1px] text-[11px] font-mono border whitespace-nowrap ${
              state.dailySpend.remainingUsd !== 'off' && typeof state.dailySpend.remainingUsd === 'number' && state.dailySpend.remainingUsd <= 0
                ? 'bg-red-500/20 border-red-500/40 text-red-300'
                : 'bg-cyan-500/10 border-cyan-800/50 text-cyan-400'
            }`}
          >
            {`$${state.dailySpend.usdSpent.toFixed(2)}/$${typeof state.dailySpend.budgetUsd === 'number' ? state.dailySpend.budgetUsd.toFixed(2) : state.dailySpend.budgetUsd}`}
          </span>
        )}
        {cost && (
          <span
            title={costTooltip}
            data-testid="voice-cost-chip"
            className={`px-1 py-[1px] text-[11px] font-mono border ${
              cost.level === 'cap'
                ? 'bg-red-500/20 border-red-500/40 text-red-300'
                : cost.level === 'warn'
                  ? 'bg-yellow-500/20 border-yellow-500/40 text-yellow-300'
                  : 'bg-cyan-500/10 border-cyan-800/50 text-cyan-400'
            }`}
          >
            {`${cost.display}${(cost.incomplete || cost.estimated || cost.ratesRecognized === false) ? '*' : ''}`}
          </span>
        )}
        {/* Persistent model-switch affordance: visible in every non-lean
            state once the console exists (the first-run card already owns the
            opt-in-required phase, so the toggle only matters afterwards). */}
        {state.phase !== 'lean-unavailable' && state.phase !== 'opt-in-required' && (
          <button
            type="button"
            data-testid="voice-change-model"
            aria-pressed={setupOpen}
            aria-label={t('voice.panel.changeModel')}
            title={t('voice.panel.changeModel')}
            onClick={() => setSetupOpen((v) => !v)}
            className={`px-1 py-[1px] text-[11px] font-mono tracking-wide border whitespace-nowrap ${
              setupOpen
                ? 'bg-violet-500/20 border-violet-500/40 text-violet-300'
                : 'bg-transparent border-[var(--border-primary)] text-[var(--text-muted)] hover:border-violet-500/50 hover:text-[var(--text-secondary)]'
            }`}
          >
            {t('voice.panel.changeModel')}
          </button>
        )}
        <button type="button" onClick={onClose} aria-label={t('voice.panel.close')} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-sm leading-none">
          ×
        </button>
      </div>

      {/* Disabled state → plain SETUP CARD (UX pass): while voice is off,
          the setup card yields to a first-run card that turns voice on
          and saves the provider. Enabled but with no usable AI (unconnected
          or local_text/degraded) → the connect card leads and the live
          console stays below it. Any configured provider keeps the card one
          "Change model" click away. */}
      {state.phase === 'opt-in-required' ? (
        <VoiceSetupCard />
      ) : (
      <>
      {state.phase !== 'lean-unavailable' &&
        (setupOpen || state.providerResolved === null || state.providerResolved === 'local_text') && (
          <VoiceSetupCard />
        )}
      {/* Narration renders ONLY when an actual brief exists — no placeholder
          chrome. Ambient briefs stay controller-gated (default OFF) with no
          panel chrome; hold-last-good lives in the controller. */}
      {(state.narration?.summary || state.narration?.error) && (
      <div className="px-3 pt-2" data-testid="voice-narrate-block">
        <div className="p-2 bg-black/60 border border-cyan-800/50 rounded-sm text-[11px] font-mono">
          <div className="flex items-center gap-2 mb-1">
            {state.narrating && <span className="w-[2px] bg-cyan-500 animate-pulse h-3" aria-hidden="true" />}
          </div>
          <div className="text-[var(--text-primary)] break-words whitespace-pre-wrap" data-testid="voice-narrate-text">
            {state.narration?.summary || ''}
          </div>
          {state.narration?.error && (
            <div className="mt-1 text-red-400 text-xs" data-testid="voice-narrate-error">
              {t('voice.turn.faultLeadIn')} {state.narration.error}
            </div>
          )}
          {/* Freshness strip — mirrors status-bar feed dots so the narrative's
              provenance stays visible (live/aging/stale/unknown). */}
          {state.freshnessRows.length > 0 && (
            <div className="mt-2 pt-1 border-t border-cyan-900/40 flex flex-wrap gap-x-3 gap-y-[2px]" data-testid="voice-freshness-strip">
              {state.freshnessRows.map((row) => (
                <span key={row.layer} className="text-[11px] text-[var(--text-muted)]" title={`${row.layer} — ${row.disposition}${row.age_s != null ? ` (${row.age_s}s)` : ''}`}>
                  <span className={`feed-dot ${DISPOSITION_DOT[row.disposition]}`} aria-hidden="true" />
                  {row.layer} · {t(`voice.freshness.${row.disposition}`)}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      )}
      </>
      )}

      {/* Transcript */}
      <div
        ref={turnsRef}
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        className="flex-1 min-h-[80px] overflow-y-auto styled-scrollbar px-3 py-2 space-y-1"
        data-testid="voice-transcript"
      >
        {state.turns.length === 0 && (
          <div className="text-xs font-mono text-[var(--text-muted)]">{t('voice.composer.placeholder')}</div>
        )}
        {state.turns.map((turn) =>
          turn.kind === 'tool' && turn.tool ? (
            <div key={turn.id} className="font-mono text-xs" data-testid="voice-tool-row">
              <span className="text-cyan-600">▸ </span>
              <span className="text-[var(--text-secondary)]">
                {turn.tool.name}
                {turn.tool.args_summary ? `(${turn.tool.args_summary})` : ''}
              </span>
              {turn.tool.ok ? (
                <span className="text-emerald-400"> — {t('voice.turn.toolOk')}</span>
              ) : (
                <span className="text-red-400" data-testid="voice-tool-fail">
                  {' '}
                  — {t('voice.turn.toolFail')}: {turn.tool.detail}
                </span>
              )}
            </div>
          ) : (
            <div key={turn.id} className="font-mono text-xs">
              <span className={turn.role === 'operator' ? 'text-cyan-400 font-bold' : 'text-violet-400 font-bold'}>
                {turn.role === 'operator' ? t('voice.turn.you') : t('voice.turn.sys')}
              </span>{' '}
              <span className="text-[var(--text-primary)] break-words">
                {/* Human lead-in on FAULT turns; the reason itself stays verbatim. */}
                {turn.role === 'agent' && turn.kind === 'text' && state.phase === 'error' && turn.text === state.lastFaultReason
                  ? `${t('voice.turn.faultLeadIn')} `
                  : ''}
                {turn.text}
              </span>
            </div>
          ),
        )}
      </div>

      {/* Composer — always present; typed text drives the identical pipeline */}
      <div className="flex items-center gap-2 px-3 py-2 border-t border-[var(--border-primary)]">
        {state.degraded && (
          <span className="px-1 py-[1px] text-[11px] font-mono bg-cyan-500/10 border border-cyan-800/50 text-cyan-400 whitespace-nowrap" data-testid="voice-text-mode-chip">
            {t('voice.panel.textModeChip')}
          </span>
        )}
        <input
          ref={inputRef}
          data-testid="voice-composer"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              submit();
            }
            e.stopPropagation();
          }}
          placeholder={t('voice.composer.placeholder')}
          aria-label={t('voice.composer.placeholder')}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          className="flex-1 bg-transparent text-[12px] text-[var(--text-primary)] font-mono outline-none placeholder:text-[var(--text-muted)] focus-visible:outline-none"
        />
      </div>
    </div>
  );
}
