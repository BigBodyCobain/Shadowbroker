'use client';
/**
 * VoiceSetupCard — plain-language first-run setup for the voice console.
 *
 * Rendered by VoiceHudPanel whenever the console has no usable AI: the
 * `opt-in-required` phase, or enabled-but-unconnected (providerResolved null
 * or local_text) where it leads the panel as a "Connect a model" section.
 * Also mounted on demand from the panel's persistent "Change model"
 * affordance — it then shows the currently active provider and lands
 * directly on the provider step; saving another provider/key upserts.
 * One primary button enables voice (POST /api/voice/opt-in), then a compact
 * provider step saves the chosen provider/key/model (POST /api/voice/provider).
 * Hosted and local presets discover model IDs from the saved backend connection.
 * Free-text model IDs remain available when discovery is unavailable. Credentials
 * stay on the backend; inputs disable autofill to prevent accidental reuse.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { API_BASE } from '@/lib/api';
import { voiceController } from '@/lib/voiceController';
import { useTranslation } from '@/i18n';

type SetupStep = 'idle' | 'pending' | 'done';
/** UI presets map to backend provider profiles. */
type ProviderPreset = 'openai' | 'gemini' | 'openrouter' | 'local' | 'anthropic' | 'xai' | 'meta' | 'lmstudio' | 'custom';
type WireProvider = 'openai' | 'gemini' | 'compat' | 'anthropic' | 'xai' | 'openrouter' | 'meta' | 'ollama' | 'lmstudio';

const LOCAL_BASE_PLACEHOLDER = 'http://127.0.0.1:11434/v1';
const CUSTOM_BASE_PLACEHOLDER = 'https://your-gateway.example/v1';
const MODELS_FETCH_DEBOUNCE_MS = 300;

const PROVIDER_PRESETS: Array<{ id: ProviderPreset; labelKey: string }> = [
  { id: 'openai', labelKey: 'voice.setup.providerOpenai' },
  { id: 'gemini', labelKey: 'voice.setup.providerGemini' },
  { id: 'anthropic', labelKey: 'voice.setup.providerAnthropic' },
  { id: 'xai', labelKey: 'voice.setup.providerXai' },
  { id: 'openrouter', labelKey: 'voice.setup.providerOpenrouter' },
  { id: 'meta', labelKey: 'voice.setup.providerMeta' },
  { id: 'lmstudio', labelKey: 'voice.setup.providerLmstudio' },
  { id: 'local', labelKey: 'voice.setup.providerCompat' },
  { id: 'custom', labelKey: 'voice.setup.providerCustom' },
];

function wireProviderFor(preset: ProviderPreset): WireProvider {
  return preset === 'local' ? 'ollama' : preset === 'custom' ? 'compat' : preset;
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

/** Per-provider keySet flags from GET /api/voice/status — drives the
 *  "Replace key / clear" affordances for an already-configured provider. */
interface ProviderFlags {
  openaiKeySet: boolean;
  compatKeySet: boolean;
  compatBaseUrlSet: boolean;
  geminiKeySet: boolean;
  anthropicKeySet: boolean;
  keysSet: Record<string, boolean>;
}

function readProviderFlags(status: unknown): ProviderFlags | null {
  const provider = (status as { provider?: Record<string, unknown> } | null)?.provider;
  if (!provider || typeof provider !== 'object') return null;
  const bool = (v: unknown) => v === true;
  return {
    openaiKeySet: bool(provider.openaiKeySet),
    compatKeySet: bool(provider.compatKeySet),
    compatBaseUrlSet: bool(provider.compatBaseUrlSet),
    geminiKeySet: bool(provider.geminiKeySet),
    anthropicKeySet: bool(provider.anthropicKeySet),
    keysSet: (provider.keysSet || {}) as Record<string, boolean>,
  };
}

function isProviderConfigured(wire: WireProvider, flags: ProviderFlags | null): boolean {
  if (!flags) return false;
  if (flags.keysSet[wire]) return true;
  if (wire === 'xai' || wire === 'openrouter' || wire === 'meta') return false;
  if (wire === 'openai') return flags.openaiKeySet;
  if (wire === 'gemini') return flags.geminiKeySet;
  if (wire === 'anthropic') return flags.anthropicKeySet;
  return flags.compatBaseUrlSet || flags.compatKeySet;
}

export default function VoiceSetupCard() {
  const { t } = useTranslation();
  const state = useSyncExternalStore(voiceController.subscribe, voiceController.getState, voiceController.getState);

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
  const [mode, setMode] = useState<'text' | 'realtime'>('text');
  const [apiStyle, setApiStyle] = useState<'chat' | 'responses'>('responses');
  const [chatModel, setChatModel] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [provSave, setProvSave] = useState<SetupStep>('idle');
  const [providerReady, setProviderReady] = useState(false);
  const [provMessage, setProvMessage] = useState<string | null>(null);
  const [providerFlags, setProviderFlags] = useState<ProviderFlags | null>(null);
  const [clearing, setClearing] = useState(false);

  const wireProvider = wireProviderFor(preset);
  const needsBaseUrl = wireProvider === 'compat' || wireProvider === 'ollama' || wireProvider === 'lmstudio';
  const needsModel = true;
  const supportsRealtime = preset === 'openai' || preset === 'gemini' || preset === 'custom';

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
    setProviderReady(false);
    setProvMessage(null);
    setModels([]);
    setModelsError(null);
    setApiKey('');
    setModel('');
    setChatModel('');
    setMode('text');
    setApiStyle(next === 'openai' || next === 'xai' ? 'responses' : 'chat');
    setBaseUrl(next === 'local' ? LOCAL_BASE_PLACEHOLDER : next === 'lmstudio' ? 'http://127.0.0.1:1234/v1' : '');
  };

  // Discover from the saved provider connection; free-text IDs remain usable.
  useEffect(() => {
    const query = `${API_BASE}/api/voice/models?provider=${wireProvider}&mode=${mode}${needsBaseUrl && baseUrl.trim() ? `&baseUrl=${encodeURIComponent(baseUrl.trim())}` : ''}`;
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
  }, [wireProvider, mode, needsBaseUrl, baseUrl, provSave]);

  // Key-management affordances need the current keySet flags — poll status
  // once when the provider step is visible (and again after any save/clear).
  useEffect(() => {
    if (optIn !== 'done') return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/voice/status`);
        if (!res.ok) return;
        const json = await res.json();
        if (!cancelled) setProviderFlags(readProviderFlags(json));
      } catch {
        // Flags stay null → no clear button; saving still works.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [optIn, provSave]);

  /** POST the documented clear variant — removes this provider's persisted
   *  key (+ its model row) server-side; a fresh status poll updates flags. */
  const clearProvider = async () => {
    setClearing(true);
    setProviderReady(false);
    setProvMessage(null);
    try {
      const res = await fetch(`${API_BASE}/api/voice/provider`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: wireProvider, clear: true }),
      });
      const json = (await res.json()) as {
        ok?: boolean;
        note?: string;
        error?: string;
        detail?: string;
        provider?: { resolved?: string | null };
      };
      if (!res.ok || !json?.ok) {
        setProvMessage(json?.detail || json?.error || `HTTP ${res.status}`);
      } else {
        setProvMessage(json.note ? String(json.note) : t('voice.setup.cleared'));
        void refreshStatus();
      }
    } catch (err) {
      setProvMessage(err instanceof Error && err.message ? err.message : `HTTP error`);
    } finally {
      setClearing(false);
      try {
        const res = await fetch(`${API_BASE}/api/voice/status`);
        if (res.ok) setProviderFlags(readProviderFlags(await res.json()));
      } catch {
        // keep last-known flags
      }
    }
  };

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
    setProviderReady(false);
    setProvMessage(null);
    try {
      const body: Record<string, unknown> = { provider: wireProvider, mode, apiStyle };
      if (mode === 'realtime') body.chatModel = chatModel.trim();
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
        provider?: { resolved?: string | null };
        note?: string;
      };
      if (!res.ok || !json?.ok) {
        setProvMessage(json?.detail || json?.error || `HTTP ${res.status}`);
        setProvSave('idle');
        return;
      }
      // Show what resolved — or verbatim why it degraded — never a fake OK.
      setProvMessage(json.note || (json.provider?.resolved || json.resolved) || json.degradedReason || t('voice.setup.chooseModelAfterSave'));
      setProviderReady(Boolean(modelId && (json.provider?.resolved || json.resolved)));
      setProvSave('done');
      setApiKey('');
      if (modelId) lingerTimer.current = setTimeout(() => void refreshStatus(), DONE_LINGER_MS);
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

  const bothDone = optIn === 'done' && provSave === 'done' && providerReady;
  // Enabled-but-unconnected mounts lead with the connect headline instead of
  // the first-run title.
  const titleKey =
    voiceController.getState().phase === 'opt-in-required' ? 'voice.setup.title' : 'voice.setup.connectTitle';

  return (
    <div className="mx-3 mt-2 p-3 max-h-[45vh] overflow-y-auto styled-scrollbar bg-black/60 border border-violet-500/40 rounded-sm" data-testid="voice-setup-card">
      <div className="text-violet-300 font-bold text-sm font-mono mb-1">{t(titleKey)}</div>
      <p className="text-xs font-mono text-[var(--text-secondary)] mb-2">{t('voice.setup.explainer')}</p>

      {/* Currently active provider (Change-model path): honest armed state —
          resolved provider id + its model label — before any replacement. */}
      {(state.providerResolved || state.modelLabel) && (
        <div
          className="mb-2 text-xs font-mono text-cyan-300 break-words"
          data-testid="voice-setup-current-provider"
        >
          {t('voice.setup.currentProvider')}{' '}
          {state.providerResolved || '—'}
          {state.modelLabel ? ` · ${state.modelLabel}` : ''}
        </div>
      )}

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
            {mode === 'text' && (
              <div
                className="text-[11px] font-mono text-cyan-300 break-words"
                data-testid="voice-setup-anthropic-note"
              >
                {t('voice.setup.textModeNote')}
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
            {preset === 'meta' && <p className="text-xs text-cyan-300">{t('voice.setup.metaNote')}</p>}
            {needsBaseUrl && <p className="text-xs text-[var(--text-muted)]">{t('voice.setup.localNote')}</p>}
            <label className="text-xs font-mono text-[var(--text-secondary)]">
              {t('voice.setup.interactionMode')}
              <select data-testid="voice-setup-mode" value={mode} onChange={(e) => { setMode(e.target.value as 'text' | 'realtime'); setModel(''); }} className="ml-2 bg-black/60 border border-[var(--border-primary)] p-1">
                <option value="text">{t('voice.setup.textCommands')}</option>
                {supportsRealtime && <option value="realtime">{t('voice.setup.realtimeAudio')}</option>}
              </select>
            </label>
            {needsBaseUrl && <label className="text-xs font-mono text-[var(--text-secondary)]">
              {t('voice.setup.apiStyleLabel')}
              <select data-testid="voice-setup-api-style" value={apiStyle} onChange={(e) => setApiStyle(e.target.value as 'chat' | 'responses')} className="ml-2 bg-black/60 border border-[var(--border-primary)] p-1">
                <option value="chat">Chat Completions</option><option value="responses">Responses</option>
              </select>
            </label>}
            {mode === 'realtime' && <input data-testid="voice-setup-chat-model" aria-label={t('voice.setup.chatModelLabel')} placeholder={t('voice.setup.chatModelLabel')} value={chatModel} onChange={(e) => setChatModel(e.target.value)} {...NO_AUTOFILL} className="bg-black/50 border border-[var(--border-primary)] px-2 py-1.5 text-xs" />}
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

          {/* Already-configured provider: replace/clear affordances. Saving
              again simply overwrites (upsert); Clear removes the rows. */}
          {isProviderConfigured(wireProvider, providerFlags) && (
            <div className="mt-2 flex items-center justify-between gap-2">
              <div
                className="text-[11px] font-mono text-cyan-300 break-words"
                data-testid="voice-setup-key-configured-note"
              >
                {t('voice.setup.keyConfiguredNote')}
              </div>
              <button
                type="button"
                data-testid="voice-setup-clear-provider"
                disabled={clearing}
                onClick={() => void clearProvider()}
                className={`shrink-0 px-2 py-1 text-xs font-mono border transition-colors ${
                  clearing
                    ? 'bg-transparent border-[var(--border-primary)] text-[var(--text-muted)] cursor-wait'
                    : 'bg-transparent border-red-700/60 text-red-300 hover:border-red-500/60 focus-visible:outline focus-visible:outline-red-400'
                }`}
              >
                {t('voice.setup.clearKey')}
              </button>
            </div>
          )}

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
            {model.trim() ? t('voice.setup.saveCheck') : t('voice.setup.connectModels')}
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
          {t('voice.setup.connected')}
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
