'use client';
/**
 * VoiceSetupCard — plain-language first-run setup for the voice console.
 *
 * Rendered by VoiceHudPanel whenever the console rests in the
 * `opt-in-required` phase: one primary button enables voice
 * (POST /api/voice/opt-in), then a compact provider step saves the chosen
 * provider/key (POST /api/voice/provider). The long verbatim policy reasons
 * that used to live in the mic tooltip render here, honestly and in full.
 * Endpoint errors stay verbatim behind a short human lead-in (§5.5 honesty).
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { API_BASE } from '@/lib/api';
import { voiceController } from '@/lib/voiceController';
import { useTranslation } from '@/i18n';

type SetupStep = 'idle' | 'pending' | 'done';
type ProviderChoice = 'openai' | 'gemini' | 'compat';

const PROVIDER_CHOICES: Array<{ id: ProviderChoice; labelKey: string }> = [
  { id: 'openai', labelKey: 'voice.setup.providerOpenai' },
  { id: 'gemini', labelKey: 'voice.setup.providerGemini' },
  { id: 'compat', labelKey: 'voice.setup.providerCompat' },
];

/** How long the "Voice is on" confirmation stays readable before the card
 *  yields to the live console (status refresh flips the phase). */
const DONE_LINGER_MS = 2500;

export default function VoiceSetupCard() {
  const { t } = useTranslation();
  const state = useSyncExternalStore(voiceController.subscribe, voiceController.getState);

  const [optIn, setOptIn] = useState<SetupStep>('idle');
  const [envNote, setEnvNote] = useState<string | null>(null);
  const [optInError, setOptInError] = useState<string | null>(null);

  const [provider, setProvider] = useState<ProviderChoice>('openai');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [provSave, setProvSave] = useState<SetupStep>('idle');
  const [provMessage, setProvMessage] = useState<string | null>(null);

  // After both steps succeed, let the operator actually read the "Voice is
  // on" line before the delayed status refresh swaps in the live console.
  const lingerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (lingerTimer.current) clearTimeout(lingerTimer.current);
    },
    [],
  );

  const turnOn = async () => {
    setOptIn('pending');
    setOptInError(null);
    try {
      const res = await fetch(`${API_BASE}/api/voice/opt-in`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable: true }),
      });
      const json = (await res.json()) as {
        ok?: boolean;
        effectiveEnable?: boolean;
        managedByEnvironment?: boolean;
        note?: string;
        error?: string;
        detail?: string;
      };
      if (!res.ok || !json?.ok) {
        setOptInError(json?.detail || json?.error || `HTTP ${res.status}`);
        setOptIn('idle');
        return;
      }
      if (json.managedByEnvironment && json.note) setEnvNote(String(json.note));
      if (json.effectiveEnable) {
        setOptIn('done');
      } else {
        // Honest: the server says voice is still off (e.g. env-managed).
        setEnvNote((prev) => prev ?? json.note ?? json.detail ?? null);
        setOptIn('idle');
      }
    } catch (err) {
      setOptInError(err instanceof Error && err.message ? err.message : `HTTP error`);
      setOptIn('idle');
    }
  };

  const saveProvider = async () => {
    setProvSave('pending');
    setProvMessage(null);
    try {
      const body: Record<string, unknown> = { provider };
      const key = apiKey.trim();
      const url = baseUrl.trim();
      if (key) body.apiKey = key;
      if (url) body.baseUrl = url;
      const res = await fetch(`${API_BASE}/api/voice/provider`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const json = (await res.json()) as {
        ok?: boolean;
        resolved?: string | null;
        degradedReason?: string | null;
        error?: string;
        detail?: string;
      };
      if (!res.ok || !json?.ok) {
        setProvMessage(json?.detail || json?.error || `HTTP ${res.status}`);
        setProvSave('idle');
        return;
      }
      // Show what resolved — or verbatim why it degraded — never a fake OK.
      setProvMessage(json.resolved ? String(json.resolved) : json.degradedReason || '');
      setProvSave('done');
      lingerTimer.current = setTimeout(() => void refreshStatus(), DONE_LINGER_MS);
    } catch (err) {
      setProvMessage(err instanceof Error && err.message ? err.message : `HTTP error`);
      setProvSave('idle');
    }
  };

  /** Re-poll /api/voice/status so the console leaves opt-in-required as soon
   *  as setup completes instead of waiting for the 60s hook poll. */
  const refreshStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/voice/status`);
      if (!res.ok) return;
      const json = await res.json();
      if (json?.ok) voiceController.applyStatus(json);
    } catch {
      // The 60s poll remains the fallback — never wedge the console here.
    }
  };

  const bothDone = optIn === 'done' && provSave === 'done';

  return (
    <div className="mx-3 mt-2 p-3 bg-black/60 border border-violet-500/40 rounded-sm" data-testid="voice-setup-card">
      <div className="text-violet-300 font-bold text-sm font-mono mb-1">{t('voice.setup.title')}</div>
      <p className="text-xs font-mono text-[var(--text-secondary)] mb-2">{t('voice.setup.explainer')}</p>

      {/* Step 1 — enable */}
      {optIn !== 'done' ? (
        <button
          type="button"
          data-testid="voice-setup-turn-on"
          disabled={optIn === 'pending'}
          onClick={() => void turnOn()}
          className={`w-full px-3 py-2 text-sm font-mono border transition-colors ${
            optIn === 'pending'
              ? 'bg-transparent border-[var(--border-primary)] text-[var(--text-muted)] cursor-wait'
              : 'bg-violet-500/20 border-violet-400/60 text-violet-200 hover:border-violet-300 hover:bg-violet-500/30 focus-visible:outline focus-visible:outline-violet-400'
          }`}
        >
          {t('voice.setup.turnOn')}
        </button>
      ) : (
        <div className="text-xs font-mono text-emerald-400" data-testid="voice-setup-optin-done">
          ✓ {t('voice.setup.turnOn')}
        </div>
      )}
      {optInError && (
        <div className="mt-1 text-xs font-mono text-red-400 break-words" data-testid="voice-setup-optin-error">
          {t('voice.turn.faultLeadIn')} {optInError}
        </div>
      )}
      {envNote && (
        <div className="mt-1 text-xs font-mono text-cyan-300 break-words" data-testid="voice-setup-env-note">
          {envNote}
        </div>
      )}

      {/* Step 2 — provider choice (revealed once voice is on) */}
      {optIn === 'done' && (
        <div className="mt-2 pt-2 border-t border-[var(--border-primary)]">
          <div className="text-xs font-mono text-[var(--text-secondary)] mb-1">{t('voice.setup.providerLabel')}</div>
          <div className="flex gap-1 flex-wrap" role="group" aria-label={t('voice.setup.providerLabel')}>
            {PROVIDER_CHOICES.map((choice) => {
              const selected = provider === choice.id;
              return (
                <button
                  key={choice.id}
                  type="button"
                  aria-pressed={selected}
                  data-testid={`voice-setup-provider-${choice.id}`}
                  onClick={() => {
                    setProvider(choice.id);
                    setProvSave('idle');
                    setProvMessage(null);
                  }}
                  className={`px-2 py-1 text-xs font-mono border transition-colors ${
                    selected
                      ? 'bg-violet-500/20 border-violet-400/60 text-violet-200'
                      : 'bg-transparent border-[var(--border-primary)] text-[var(--text-muted)] hover:border-violet-500/40'
                  }`}
                >
                  {t(choice.labelKey)}
                </button>
              );
            })}
          </div>

          <div className="mt-2 flex flex-col gap-1">
            <input
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={t('voice.setup.apiKeyPlaceholder')}
              aria-label={t('voice.setup.apiKeyPlaceholder')}
              type="password"
              autoComplete="off"
              className="w-full bg-black/50 border border-[var(--border-primary)] px-2 py-1.5 text-xs font-mono text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus-visible:border-violet-500/60"
              data-testid="voice-setup-api-key"
            />
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={t('voice.setup.baseUrlPlaceholder')}
              aria-label={t('voice.setup.baseUrlPlaceholder')}
              type="text"
              autoComplete="off"
              className={`w-full bg-black/50 border px-2 py-1.5 text-xs font-mono text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus-visible:border-violet-500/60 ${
                provider === 'compat' ? 'border-[var(--border-primary)]' : 'border-[var(--border-primary)] opacity-70'
              }`}
              data-testid="voice-setup-base-url"
            />
          </div>

          <button
            type="button"
            data-testid="voice-setup-save-provider"
            disabled={provSave === 'pending'}
            onClick={() => void saveProvider()}
            className={`mt-2 w-full px-3 py-2 text-sm font-mono border transition-colors ${
              provSave === 'pending'
                ? 'bg-transparent border-[var(--border-primary)] text-[var(--text-muted)] cursor-wait'
                : 'bg-cyan-500/10 border-cyan-700/60 text-cyan-300 hover:border-cyan-500/60 focus-visible:outline focus-visible:outline-cyan-400'
            }`}
          >
            {t('voice.setup.saveCheck')}
          </button>
          {provMessage && (
            <div className="mt-1 text-xs font-mono break-words text-[var(--text-secondary)]" data-testid="voice-setup-provider-result">
              {provSave === 'done' ? `${provider}: ` : `${t('voice.turn.faultLeadIn')} `}
              {provMessage}
            </div>
          )}
        </div>
      )}

      {/* Both steps done — read this before the console goes live. */}
      {bothDone && (
        <div className="mt-2 text-sm font-mono text-emerald-400" data-testid="voice-setup-done">
          {t('voice.setup.done')}
        </div>
      )}

      {/* Long verbatim policy reasons moved here out of the mic tooltip. */}
      {state.reasons.length > 0 && (
        <div className="mt-2 pt-2 border-t border-[var(--border-primary)] space-y-[2px]" data-testid="voice-setup-reasons">
          {state.reasons.map((reason, i) => (
            <div key={`${i}-${reason.slice(0, 24)}`} className="text-[11px] font-mono text-[var(--text-muted)] break-words">
              {reason}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
