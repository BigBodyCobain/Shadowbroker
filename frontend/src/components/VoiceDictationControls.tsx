'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { API_BASE } from '@/lib/api';
import { voiceController } from '@/lib/voiceController';
import { audioBase64, startDictation } from '@/lib/voiceDictation';
import { voiceSpeech } from '@/lib/voiceSpeech';
import { useTranslation } from '@/i18n';

interface SpeechConfiguration {
  provider: 'off' | 'openai' | 'gemini' | 'compat';
  model: string;
  baseUrl: string;
  ready: boolean;
  keySet: boolean;
}
const OFF: SpeechConfiguration = {
  provider: 'off',
  model: '',
  baseUrl: '',
  ready: false,
  keySet: false,
};

export default function VoiceDictationControls({
  onSubmit,
}: {
  onSubmit: (text: string) => Promise<void> | void;
}) {
  const { t } = useTranslation();
  const state = useSyncExternalStore(
    voiceController.subscribe,
    voiceController.getState,
    voiceController.getState,
  );
  const speech = useSyncExternalStore(
    voiceSpeech.subscribe,
    voiceSpeech.getState,
    voiceSpeech.getState,
  );
  const [configuration, setConfiguration] = useState<SpeechConfiguration>(OFF);
  const [provider, setProvider] = useState<SpeechConfiguration['provider']>('off');
  const [model, setModel] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [setup, setSetup] = useState(false);
  const [recording, setRecording] = useState(false);
  const [pending, setPending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const session = useRef<Awaited<ReturnType<typeof startDictation>> | null>(null);
  const capture = useRef<AbortController | null>(null);
  const disabled = state.phase === 'quota-capped' || state.phase === 'thinking';
  const cancel = () => {
    capture.current?.abort();
    session.current?.abort();
    session.current = null;
    capture.current = null;
    setRecording(false);
    setPending(false);
  };

  useEffect(() => {
    let active = true;
    void fetch(`${API_BASE}/api/voice/speech-settings`)
      .then(async (response) => {
        const json = await response.json();
        if (active && response.ok && json.ok) {
          setConfiguration(json);
          setProvider(json.provider);
          setModel(json.model || '');
          setBaseUrl(json.baseUrl || '');
        }
      })
      .catch(() => {});
    const blur = () => cancel();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') cancel();
    };
    window.addEventListener('blur', blur);
    window.addEventListener('keydown', key);
    return () => {
      active = false;
      capture.current?.abort();
      session.current?.abort();
      window.removeEventListener('blur', blur);
      window.removeEventListener('keydown', key);
    };
  }, []);
  useEffect(() => {
    if (disabled) cancel();
  }, [disabled]);

  const save = async () => {
    setError('');
    setSaving(true);
    try {
      const response = await fetch(`${API_BASE}/api/voice/speech-settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider,
          model,
          ...(provider === 'compat' ? { baseUrl } : {}),
          ...(apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
        }),
      });
      const json = await response.json();
      if (!response.ok || !json.ok)
        throw new Error(String(json.detail || json.error || `HTTP ${response.status}`));
      setConfiguration(json);
      setProvider(json.provider);
      setModel(json.model || '');
      setBaseUrl(json.baseUrl || '');
      setApiKey('');
      if (json.managedByEnvironment) setError(t('voice.dictation.managed'));
      const list = await fetch(`${API_BASE}/api/voice/speech-models`);
      const catalog = await list.json();
      if (list.ok && catalog.ok)
        setModels((catalog.models || []).map((row: { id: string }) => row.id));
      if (json.ready) setSetup(false);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : 'failed');
    } finally {
      setSaving(false);
    }
  };

  const start = async () => {
    if (pending) { cancel(); return; }
    if (session.current) {
      setRecording(false);
      setPending(true);
      session.current.stop();
      return;
    }
    setError('');
    setPending(true);
    voiceSpeech.cancel();
    const controller = new AbortController();
    capture.current = controller;
    try {
      const handle = await startDictation({
        signal: controller.signal,
        onAudio: async (audio) => {
          if (capture.current !== controller || controller.signal.aborted) return;
          setRecording(false);
          setPending(true);
          const response = await fetch(`${API_BASE}/api/voice/transcribe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ audio: audioBase64(audio) }),
            signal: controller.signal,
          });
          const json = await response.json();
          if (!response.ok || !json.ok)
            throw new Error(String(json.detail || json.error || `HTTP ${response.status}`));
          if (!json.text?.trim()) throw new Error('no-speech');
          if (!controller.signal.aborted) void onSubmit(json.text);
        },
        onError: (code) => { if (capture.current === controller && !controller.signal.aborted) setError(code); },
        onEnd: () => {
          if (capture.current !== controller) return;
          session.current = null;
          capture.current = null;
          setRecording(false);
          setPending(false);
        },
      });
      if (controller.signal.aborted || capture.current !== controller) handle.abort();
      else {
        session.current = handle;
        setRecording(true);
        setPending(false);
      }
    } catch (exception) {
      if (capture.current !== controller) return;
      if (!controller.signal.aborted)
        setError(exception instanceof Error ? exception.message : 'failed');
      setPending(false);
    }
  };

  const knownError = ['unsupported', 'insecure', 'invalid-audio', 'no-speech', 'failed'].includes(
    error,
  );
  return (
    <div
      className="px-3 py-2 border-t border-[var(--border-primary)] text-xs font-mono space-y-2"
      data-testid="voice-dictation-controls"
    >
      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          data-testid="voice-dictate"
          disabled={disabled || saving || !configuration.ready}
          aria-pressed={recording}
          onClick={() => void start()}
          className="px-2 py-1 border border-cyan-700 text-cyan-300 disabled:opacity-50"
        >
          {t(
            recording
              ? 'voice.dictation.stop'
              : pending
                ? 'voice.dictation.cancel'
                : 'voice.dictation.start',
          )}
        </button>
        <button
          type="button"
          data-testid="voice-speech-settings"
          aria-expanded={setup}
          disabled={recording || pending || saving}
          onClick={() => setSetup(!setup)}
          className="underline text-cyan-300"
        >
          {t('voice.dictation.settings')}
        </button>
        <label className="flex items-center gap-1 text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={state.readReplies}
            onChange={(event) => {
              voiceController.setReadReplies(event.target.checked);
              if (event.target.checked) voiceSpeech.probe();
              else voiceSpeech.cancel();
            }}
          />
          {t('voice.dictation.readReplies')}
        </label>
      </div>
      {!configuration.ready && (
        <p className="text-[var(--text-muted)]">{t('voice.dictation.configureFirst')}</p>
      )}
      {configuration.ready && !setup && (
        <p className="text-[var(--text-muted)]">
          {configuration.provider} · {configuration.model}
        </p>
      )}
      {setup && (
        <div className="space-y-2">
          <p className="text-[var(--text-muted)]">{t('voice.dictation.disclosure')}</p>
          <label>
            {t('voice.dictation.provider')}
            <select
              aria-label={t('voice.dictation.provider')}
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value as SpeechConfiguration['provider']);
                setApiKey('');
                setModels([]);
                setModel('');
                setBaseUrl('');
              }}
              className="ml-2 bg-black/60 border border-[var(--border-primary)] p-1"
            >
              <option value="off">{t('voice.dictation.off')}</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Google Gemini</option>
              <option value="compat">{t('voice.dictation.custom')}</option>
            </select>
          </label>
          {provider !== 'off' && (
            <>
              <input
                aria-label={t('voice.setup.apiKeyPlaceholder')}
                type="password"
                autoComplete="new-password"
                placeholder={
                  configuration.keySet && configuration.provider === provider
                    ? t('voice.setup.keyConfiguredNote')
                    : t('voice.setup.apiKeyPlaceholder')
                }
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                className="w-full bg-black/50 border border-[var(--border-primary)] p-1"
              />
              {provider === 'compat' && (
                <input
                  aria-label={t('voice.setup.baseUrlPlaceholder')}
                  placeholder="http://127.0.0.1:8080/v1"
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                  className="w-full bg-black/50 border border-[var(--border-primary)] p-1"
                />
              )}
              <input
                aria-label={t('voice.dictation.model')}
                placeholder={t('voice.dictation.model')}
                value={model}
                onChange={(event) => setModel(event.target.value)}
                className="w-full bg-black/50 border border-[var(--border-primary)] p-1"
              />
              {models.length > 0 && (
                <select
                  aria-label={t('voice.setup.modelDropdownAria')}
                  value=""
                  onChange={(event) => {
                    if (event.target.value) setModel(event.target.value);
                  }}
                  className="w-full bg-black/60 border border-[var(--border-primary)] p-1"
                >
                  <option value="">{t('voice.setup.modelDropdownPrompt')}</option>
                  {models.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
                </select>
              )}
            </>
          )}
          <button
            type="button"
            disabled={pending || saving}
            onClick={() => void save()}
            className="px-2 py-1 border border-cyan-700 text-cyan-300"
          >
            {model.trim() || provider === 'off'
              ? t('voice.setup.saveCheck')
              : t('voice.setup.connectModels')}
          </button>
        </div>
      )}
      {recording && (
        <div role="status" className="text-cyan-300">
          {t('voice.dictation.listening')}
        </div>
      )}
      {pending && (
        <div role="status" className="text-cyan-300">
          {t('voice.dictation.processing')}
        </div>
      )}
      {state.readReplies && speech.mode === 'TEXT' && (
        <div role="status" className="text-amber-300">
          {speech.reason}
        </div>
      )}
      {error && (
        <div role="alert" className="text-amber-300">
          {knownError ? t(`voice.dictation.errors.${error}`) : error}
        </div>
      )}
    </div>
  );
}
