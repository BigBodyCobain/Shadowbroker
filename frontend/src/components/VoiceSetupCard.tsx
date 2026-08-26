'use client';
/**
 * VoiceSetupCard — plain-language first-run setup for the voice console.
 *
 * Rendered by VoiceHudPanel whenever the console has no usable AI: the
 * `opt-in-required` phase, or enabled-but-unconnected (providerResolved null
 * or local_text) where it leads the panel as a "Connect a model" section.
 * One primary button enables voice (POST /api/voice/opt-in), then a compact
 * provider step saves the chosen provider/key/model (POST /api/voice/provider).
 * Provider presets: OpenAI, Gemini, Anthropic, OpenRouter, Local/Ollama and
 * Custom endpoint (the latter three are presets of the `compat` provider;
 * Anthropic is TEXT-ONLY — Claude has no realtime speech API, so it feeds the
 * typed console + briefs leg and never opens the mic path). Compat presets
 * get a live model dropdown fed by GET /api/voice/models plus an
 * always-usable free-text fallback; endpoint errors stay verbatim behind a
 * short human lead-in (§5.5 honesty). All inputs opt out of browser autofill
 * — a stray saved credential must never land in a console field.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { API_BASE } from '@/lib/api';
import { voiceController } from '@/lib/voiceController';
import { useTranslation } from '@/i18n';

type SetupStep = 'idle' | 'pending' | 'done';
/** UI preset — openrouter/local/custom all POST as the `compat` provider. */
type ProviderPreset = 'openai' | 'gemini' | 'openrouter' | 'local' | 'anthropic' | 'custom';
type WireProvider = 'openai' | 'gemini' | 'compat' | 'anthropic';

const OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1';
const LOCAL_BASE_PLACEHOLDER = 'http://127.0.0.1:11434/v1';
const CUSTOM_BASE_PLACEHOLDER = 'https://your-gateway.example/v1';
const GEMINI_DEFAULT_MODEL = 'gemini-2.0-flash-live-001';
const MODELS_FETCH_DEBOUNCE_MS = 300;

const PROVIDER_PRESETS: Array<{ id: ProviderPreset; labelKey: string }> = [
  { id: 'openai', labelKey: 'voice.setup.providerOpenai' },
  { id: 'gemini', labelKey: 'voice.setup.providerGemini' },
  { id: 'anthropic', labelKey: 'voice.setup.providerAnthropic' },
  { id: 'openrouter', labelKey: 'voice.setup.providerOpenrouter' },
  { id: 'local', labelKey: 'voice.setup.providerCompat' },
  { id: 'custom', labelKey: 'voice.setup.providerCustom' },
];

function wireProviderFor(preset: ProviderPreset): WireProvider {
  return preset === 'openrouter' || preset === 'local' || preset === 'custom' ? 'compat' : preset;
}

/** Shared autofill-hygiene attrs (C3): no saved tokens in console fields. */
const NO_AUTOFILL = {
  autoComplete: 'off',
  autoCorrect: 'off',
  autoCapitalize: 'off',
  spellCheck: false,
} as const;

/** How long the "Voice is on" confirmation stays readable before the card
 *  yields to the live console (status refresh flips the phase). */
const DONE_LINGER_MS = 2500;

export default function VoiceSetupCard() {
  const { t } = useTranslation();
  const state = useSyncExternalStore(voiceController.subscribe, voiceController.getState);

  // Mounted while voice is already enabled but unconnected? Then opt-in
  // succeeded earlier — land directly on the provider step instead of asking
  // the operator to turn voice on twice.
  const [optIn, setOptIn] = useState<SetupStep>(() =>
    voiceController.getState().phase === 'opt-in-required' ? 'idle' : 'done',
  );
  const [envNote, setEnvNote] = useState<string | null>(null);
  const [optInError, setOptInError] = useState<string | null>(null);

  const [preset, setPreset] = useState<ProviderPreset>('openai');
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [provSave, setProvSave] = useState<SetupStep>('idle');
  const [provMessage, setProvMessage] = useState<string | null>(null);

  const wireProvider = wireProviderFor(preset);
  const needsBaseUrl = wireProvider === 'compat';
  const needsModel = preset !== 'openai';

  // After both steps succeed, let the operator actually read the "Voice is
  // on" line before the delayed status refresh swaps in the live console.
  const lingerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (lingerTimer.current) clearTimeout(lingerTimer.current);
    },
    [],
  );

  const pickPreset = (next: ProviderPreset) => {
    setPreset(next);
    setProvSave('idle');
    setProvMessage(null);
    setModels([]);
    setModelsError(null);
    if (next === 'openrouter') setBaseUrl(OPENROUTER_BASE_URL);
    else if (next === 'local') setBaseUrl('');
    else setBaseUrl('');
    if (next === 'gemini') setModel((prev) => prev || GEMINI_DEFAULT_MODEL);
    else if (next === 'openai') setModel('');
  };

  // Live model list: Anthropic gets its curated list from
  // /api/voice/models?provider=anthropic; compat gateways (OpenRouter,
  // Ollama, custom endpoints) are queried per base URL. Free text stays
  // authoritative — the dropdown is only a convenience, and failures never
  // block typing.
  useEffect(() => {
    let query: string | null = null;
    if (preset === 'anthropic') {
      query = `${API_BASE}/api/voice/models?provider=anthropic`;
    } else if (needsBaseUrl && baseUrl.trim()) {
      query = `${API_BASE}/api/voice/models?provider=compat&baseUrl=${encodeURIComponent(baseUrl.trim())}`;
    }
    if (!query) {
      setModels([]);
      setModelsError(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(query);
        const json = (await res.json()) as {
          ok?: boolean;
          models?: Array<{ id?: unknown }>;
          note?: string;
          error?: string;
          detail?: string;
        };
        if (cancelled) return;
        if (res.ok && json?.ok && Array.isArray(json.models)) {
          setModels(json.models.map((m) => String(m.id ?? '')).filter(Boolean));
          setModelsError(null);
        } else {
          // Verbatim detail behind the human lead-in (§5.5); free text stays.
          setModels([]);
          setModelsError(json?.detail || json?.error || `HTTP ${res.status}`);
        }
      } catch (err) {
        if (cancelled) return;
        setModels([]);
        setModelsError(err instanceof Error && err.message ? err.message : 'HTTP error');
      }
    }, MODELS_FETCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [preset, needsBaseUrl, baseUrl]);

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
      const body: Record<string, unknown> = { provider: wireProvider };
      const key = apiKey.trim();
      const url = baseUrl.trim();
      const modelId = model.trim();
      if (key) body.apiKey = key;
      if (url) body.baseUrl = url;
      if (modelId && needsModel) body.model = modelId;
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

  /** Re-poll /api/voice/status so the console leaves the unconfigured state
   *  as soon as setup completes instead of waiting for the 60s hook poll. */
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
  // Enabled-but-unconnected mounts lead with the connect headline instead of
  // the first-run title.
  const titleKey =
    voiceController.getState().phase === 'opt-in-required' ? 'voice.setup.title' : 'voice.setup.connectTitle';

  return (
    <div className="mx-3 mt-2 p-3 bg-black/60 border border-violet-500/40 rounded-sm" data-testid="voice-setup-card">
      <div className="text-violet-300 font-bold text-sm font-mono mb-1">{t(titleKey)}</div>
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
            {PROVIDER_PRESETS.map((choice) => {
              const selected = preset === choice.id;
              return (
                <button
                  key={choice.id}
                  type="button"
                  aria-pressed={selected}
                  data-testid={`voice-setup-provider-${choice.id}`}
                  onClick={() => pickPreset(choice.id)}
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
            {/* Anthropic honesty label: Claude is text-in/text-out — no voice. */}
            {preset === 'anthropic' && (
              <div
                className="text-[11px] font-mono text-cyan-300 break-words"
                data-testid="voice-setup-anthropic-note"
              >
                {t('voice.setup.anthropicTextOnly')}
              </div>
            )}
            {/* Gemini free tier: the fastest no-card path — link straight to it. */}
            {preset === 'gemini' && (
              <a
                href="https://aistudio.google.com/apikey"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[11px] font-mono text-cyan-300 underline decoration-cyan-700 hover:text-cyan-200 break-words"
                data-testid="voice-setup-gemini-free-key"
              >
                {t('voice.setup.geminiFreeKey')}
              </a>
            )}
            <div className="relative">
              <input
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={t('voice.setup.apiKeyPlaceholder')}
                aria-label={t('voice.setup.apiKeyPlaceholder')}
                type={showKey ? 'text' : 'password'}
                name="voice-provider-key"
                {...NO_AUTOFILL}
                autoComplete="new-password"
                className="w-full bg-black/50 border border-[var(--border-primary)] px-2 py-1.5 pr-12 text-xs font-mono text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus-visible:border-violet-500/60"
                data-testid="voice-setup-api-key"
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                aria-label={showKey ? t('voice.setup.hideKey') : t('voice.setup.showKey')}
                title={showKey ? t('voice.setup.hideKey') : t('voice.setup.showKey')}
                className="absolute right-1 top-1/2 -translate-y-1/2 px-1 py-[1px] text-[10px] font-mono tracking-wide border border-[var(--border-primary)] bg-transparent text-[var(--text-muted)] hover:border-violet-500/50 hover:text-[var(--text-secondary)] focus-visible:outline focus-visible:outline-violet-400"
                data-testid="voice-setup-key-toggle"
              >
                {showKey ? t('voice.setup.hideKey') : t('voice.setup.showKey')}
              </button>
            </div>
            {needsBaseUrl && (
              <input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={
                  preset === 'local'
                    ? LOCAL_BASE_PLACEHOLDER
                    : preset === 'custom'
                      ? CUSTOM_BASE_PLACEHOLDER
                      : t('voice.setup.baseUrlPlaceholder')
                }
                aria-label={t('voice.setup.baseUrlPlaceholder')}
                type="text"
                name="voice-provider-base-url"
                {...NO_AUTOFILL}
                className="w-full bg-black/50 border border-[var(--border-primary)] px-2 py-1.5 text-xs font-mono text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus-visible:border-violet-500/60"
                data-testid="voice-setup-base-url"
              />
            )}
            {needsModel && (
              <>
                <input
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder={t('voice.setup.modelPlaceholder')}
                  aria-label={t('voice.setup.modelLabel')}
                  type="text"
                  name="voice-provider-model"
                  {...NO_AUTOFILL}
                  className="w-full bg-black/50 border border-[var(--border-primary)] px-2 py-1.5 text-xs font-mono text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus-visible:border-violet-500/60"
                  data-testid="voice-setup-model"
                />
                {models.length > 0 && (
                  <select
                    value=""
                    onChange={(e) => {
                      if (e.target.value) setModel(e.target.value);
                    }}
                    aria-label={t('voice.setup.modelDropdownAria')}
                    className="w-full bg-black/50 border border-[var(--border-primary)] px-2 py-1.5 text-xs font-mono text-[var(--text-secondary)] outline-none focus-visible:border-violet-500/60"
                    data-testid="voice-setup-model-select"
                  >
                    <option value="">{t('voice.setup.modelDropdownPrompt')}</option>
                    {models.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </select>
                )}
                {modelsError && (
                  <div className="text-[11px] font-mono text-red-400 break-words" data-testid="voice-setup-models-error">
                    {t('voice.turn.faultLeadIn')} {modelsError}
                  </div>
                )}
              </>
            )}
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
              {provSave === 'done' ? `${wireProvider}: ` : `${t('voice.turn.faultLeadIn')} `}
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
