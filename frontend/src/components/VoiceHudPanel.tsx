'use client';
/**
 * VoiceHudPanel — the voice console panel (voice-agent plan §5.3).
 *
 * Grows upward from the mic row using LocateBar's dropdown pattern. U4 scope:
 * header (model + cost chips), reverse-chronological transcript with verbatim
 * tool rows, and the always-present composer driving the identical
 * deterministic pipeline. The NARRATE block / freshness strip land with U5's
 * grounding composer; collapse ticker is included.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { voiceController } from '@/lib/voiceController';
import { useTranslation } from '@/i18n';

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

  return (
    <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 w-[520px] max-w-[92vw] max-h-[420px] z-[200] bg-[var(--bg-secondary)] border border-violet-500/40 shadow-[0_-8px_30px_rgba(0,0,0,0.4)] flex flex-col" data-testid="voice-hud-panel">
      {/* Header row */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border-primary)]">
        <span className="text-[11px] text-violet-400 font-mono font-bold tracking-widest">{`>_ ${t('voice.panel.title')}`}</span>
        {state.modelLabel && (
          <span className="px-1 py-[1px] text-[9px] font-mono bg-violet-500/20 border border-violet-500/40 text-violet-300 tracking-wider">
            {state.modelLabel}
          </span>
        )}
        <span className="flex-1" />
        {state.cost && (
          <span
            title={`${t('voice.panel.costNote')}${state.cost.note ? ` — ${state.cost.note}` : ''}`}
            data-testid="voice-cost-chip"
            className={`px-1 py-[1px] text-[9px] font-mono border ${
              state.cost.level === 'cap'
                ? 'bg-red-500/20 border-red-500/40 text-red-300'
                : state.cost.level === 'warn'
                  ? 'bg-yellow-500/20 border-yellow-500/40 text-yellow-300'
                  : 'bg-cyan-500/10 border-cyan-800/50 text-cyan-400'
            }`}
          >
            {`${state.cost.display}${state.cost.incomplete ? '*' : ''}`}
          </span>
        )}
        <button type="button" onClick={onClose} aria-label={t('voice.panel.close')} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-sm leading-none">
          ×
        </button>
      </div>

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
          <div className="text-[10px] font-mono text-[var(--text-muted)]">{t('voice.composer.placeholder')}</div>
        )}
        {state.turns.map((turn) =>
          turn.kind === 'tool' && turn.tool ? (
            <div key={turn.id} className="font-mono text-[10px]" data-testid="voice-tool-row">
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
            <div key={turn.id} className="font-mono text-[11px]">
              <span className={turn.role === 'operator' ? 'text-cyan-400 font-bold' : 'text-violet-400 font-bold'}>
                {turn.role === 'operator' ? t('voice.turn.you') : t('voice.turn.sys')}
              </span>{' '}
              <span className="text-[var(--text-primary)] break-words">{turn.text}</span>
            </div>
          ),
        )}
      </div>

      {/* Composer — always present; typed text drives the identical pipeline */}
      <div className="flex items-center gap-2 px-3 py-2 border-t border-[var(--border-primary)]">
        {state.degraded && (
          <span className="px-1 py-[1px] text-[8px] font-mono bg-cyan-500/10 border border-cyan-800/50 text-cyan-400 whitespace-nowrap" data-testid="voice-text-mode-chip">
            {t('voice.panel.textModeChip')}
          </span>
        )}
        <input
          ref={inputRef}
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
          className="flex-1 bg-transparent text-[12px] text-[var(--text-primary)] font-mono outline-none placeholder:text-[var(--text-muted)] focus-visible:outline-none"
        />
      </div>
    </div>
  );
}
