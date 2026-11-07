/**
 * UX overhaul — VoiceSetupCard first-run flow: renders whenever the console
 * rests in the opt-in-required phase; "Turn on voice" POSTs
 * /api/voice/opt-in {enable:true}; "Save & check" POSTs /api/voice/provider;
 * both success shows the "Voice is on" confirmation and a server-provided
 * environment note renders verbatim.
 */
import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import VoiceHudPanel from '@/components/VoiceHudPanel';
import { voiceController } from '@/lib/voiceController';
import type { VoiceStatusResponse } from '@/lib/voiceTypes';

function disabledStatus(): VoiceStatusResponse {
  return {
    ok: true,
    effectiveEnable: false,
    opt_in_state: 'not_requested',
    flags: { enableSet: false, acknowledgeSet: false },
    provider: {
      resolved: null,
      requestedMode: 'auto',
      openaiKeySet: false,
      compatKeySet: false,
      compatBaseUrlSet: false,
      geminiKeySet: false,
      chatModelConfigured: false,
    },
    degradedReason: 'voice disabled',
    reasons: ['Voice agent outbound is blocked by configuration'],
    mode: 'full',
    costDefaults: { warnUsd: 'off', capUsd: 'off', dailyBudgetUsd: 'off' },
    dailySpend: { date: '', usdSpent: 0, budgetUsd: 'off', remainingUsd: 'off', ledgerQuarantined: false },
    activeSessions: 0,
    maxConcurrent: 1,
  };
}

interface CapturedCall {
  url: string;
  body: Record<string, unknown> | null;
}

/** Fetch stub covering the two setup endpoints (+ status fallback). */
function stubFetch(overrides: { optIn?: Record<string, unknown>; provider?: Record<string, unknown> } = {}): CapturedCall[] {
  const calls: CapturedCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ url, body });
    if (url.includes('/api/voice/opt-in')) {
      return new Response(
        JSON.stringify(overrides.optIn ?? { ok: true, effectiveEnable: true, managedByEnvironment: false }),
        { status: 200 },
      );
    }
    if (url.includes('/api/voice/provider')) {
      const resolved =
        overrides.provider
          ? undefined
          : body?.provider === 'gemini'
            ? 'gemini_live'
            : body?.provider === 'compat'
              ? 'compatible_ws'
              : 'openai_realtime';
      return new Response(
        JSON.stringify(overrides.provider ?? { ok: true, resolved, degradedReason: null }),
        { status: 200 },
      );
    }
    if (url.includes('/api/voice/models')) {
      // Curated Anthropic list shape from GET /api/voice/models?provider=anthropic.
      return new Response(
        JSON.stringify({
          ok: true,
          models: [{ id: 'claude-sonnet-4-5' }, { id: 'claude-opus-4-1' }, { id: 'claude-3-5-haiku-latest' }],
        }),
        { status: 200 },
      );
    }
    if (url.includes('/api/voice/status')) {
      return new Response(JSON.stringify(disabledStatus()), { status: 200 });
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

describe('VoiceSetupCard (panel disabled state)', () => {
  beforeEach(() => {
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus(disabledStatus());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    voiceController.resetForNewSession();
    voiceController.setPanelOpen(false);
  });

  it('renders the setup card when the phase is opt-in-required', () => {
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByTestId('voice-setup-card')).not.toBeNull();
    // Long verbatim reasons moved here out of the mic tooltip.
    expect(screen.getByTestId('voice-setup-reasons').textContent).toContain(
      'Voice agent outbound is blocked by configuration',
    );
  });

  it('Turn on voice POSTs /api/voice/opt-in with enable:true', async () => {
    const calls = stubFetch();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');
    const optInCalls = calls.filter((c) => c.url.includes('/api/voice/opt-in'));
    expect(optInCalls).toHaveLength(1);
    expect(optInCalls[0].body).toEqual({ enable: true });
  });

  it('Save & check POSTs the chosen provider with the entered key', async () => {
    const calls = stubFetch();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');

    // Pick Gemini and enter a key.
    fireEvent.click(screen.getByTestId('voice-setup-provider-gemini'));
    fireEvent.change(screen.getByTestId('voice-setup-api-key'), { target: { value: 'gm-key-1' } });
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    await screen.findByTestId('voice-setup-provider-result');

    const provCalls = calls.filter((c) => c.url.includes('/api/voice/provider'));
    expect(provCalls).toHaveLength(1);
    // Text is the default; model IDs come from live discovery or free text.
    expect(provCalls[0].body).toEqual({ provider: 'gemini', mode: 'text', apiStyle: 'chat', apiKey: 'gm-key-1' });

    // Resolved provider echoed back honestly.
    expect(screen.getByTestId('voice-setup-provider-result').textContent).toContain('gemini_live');
  });

  it('shows the connected confirmation after saving a model', async () => {
    stubFetch();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.change(screen.getByTestId('voice-setup-model'), { target: { value: 'test-model' } });
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    expect(await screen.findByTestId('voice-setup-done')).not.toBeNull();
  });

  it('does not claim a connection after saving credentials without a model', async () => {
    stubFetch();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    await screen.findByTestId('voice-setup-provider-result');
    expect(screen.queryByTestId('voice-setup-done')).toBeNull();
  });

  it('renders a managedByEnvironment note verbatim', async () => {
    stubFetch({
      optIn: { ok: true, effectiveEnable: true, managedByEnvironment: true, note: 'Managed by VOICE_AGENT_OUTBOUND_ENABLE in your .env' },
    });
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    const note = await screen.findByTestId('voice-setup-env-note');
    expect(note.textContent).toBe('Managed by VOICE_AGENT_OUTBOUND_ENABLE in your .env');
  });

  it('endpoint errors stay verbatim behind a human lead-in', async () => {
    stubFetch({
      optIn: { error: 'forbidden', detail: 'local operator token required' },
    });
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    const err = await screen.findByTestId('voice-setup-optin-error');
    expect(err.textContent).toContain('local operator token required'); // verbatim detail
  });
});

/** Enabled but nothing usable connected — local_text/degraded resting state. */
function localTextStatus(): VoiceStatusResponse {
  return {
    ok: true,
    effectiveEnable: true,
    opt_in_state: 'enabled',
    flags: { enableSet: true, acknowledgeSet: true },
    provider: {
      resolved: 'local_text',
      requestedMode: 'auto',
      openaiKeySet: false,
      compatKeySet: false,
      compatBaseUrlSet: true,
      geminiKeySet: false,
      chatModelConfigured: true,
    },
    degradedReason: null,
    reasons: [],
    mode: 'full',
    costDefaults: { warnUsd: 'off', capUsd: 'off', dailyBudgetUsd: 'off' },
    dailySpend: { date: '', usdSpent: 0, budgetUsd: 'off', remainingUsd: 'off', ledgerQuarantined: false },
    activeSessions: 0,
    maxConcurrent: 1,
  };
}

describe('connect section in enabled-but-unconfigured states (no stranded limbo)', () => {
  beforeEach(() => {
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus(localTextStatus());
  });

  afterEach(() => {
    cleanup();
    voiceController.resetForNewSession();
    voiceController.setPanelOpen(false);
  });

  it('panel renders the connect section first when providerResolved is local_text', () => {
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    const card = screen.getByTestId('voice-setup-card');
    const transcript = screen.getByTestId('voice-transcript');
    // The connect card is the first thing the eye lands on…
    expect(card.compareDocumentPosition(transcript) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText('Connect a model')).not.toBeNull();
    // …and the deterministic console still works below it.
    expect(screen.getByTestId('voice-composer')).not.toBeNull();
  });

  it('lands directly on the provider step (opt-in already done)', () => {
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByTestId('voice-setup-optin-done')).not.toBeNull();
    expect(screen.queryByTestId('voice-setup-turn-on')).toBeNull();
    expect(screen.getByTestId('voice-setup-save-provider')).not.toBeNull();
  });
});

/** Fetch stub covering setup + status + the models-list endpoint. */
function stubSetupFetch(modelsResponse?: Record<string, unknown>): CapturedCall[] {
  const calls: CapturedCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ url, body });
    if (url.includes('/api/voice/opt-in')) {
      return new Response(JSON.stringify({ ok: true, effectiveEnable: true, managedByEnvironment: false }), { status: 200 });
    }
    if (url.includes('/api/voice/provider')) {
      return new Response(JSON.stringify({ ok: true, resolved: 'compatible_ws', degradedReason: null }), { status: 200 });
    }
    if (url.includes('/api/voice/models')) {
      return new Response(
        JSON.stringify(
          modelsResponse ?? { ok: true, models: [{ id: 'qwen/qwen3-235b' }, { id: 'meta-llama/llama-3.3-70b' }] },
        ),
        { status: 200 },
      );
    }
    if (url.includes('/api/voice/status')) {
      return new Response(JSON.stringify(disabledStatus()), { status: 200 });
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

describe('OpenRouter preset + live model dropdown (GET /api/voice/models)', () => {
  beforeEach(() => {
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus(disabledStatus());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    voiceController.resetForNewSession();
    voiceController.setPanelOpen(false);
  });

  it('prefills the OpenRouter baseUrl and feeds the dropdown from /api/voice/models', async () => {
    const calls = stubSetupFetch();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');

    fireEvent.click(screen.getByTestId('voice-setup-provider-openrouter'));
    // Hosted presets own their server-side destination.
    expect(screen.queryByTestId('voice-setup-base-url')).toBeNull();

    // Debounced models fetch resolves into a dropdown of gateway model ids.
    const select = (await screen.findByTestId('voice-setup-model-select', {}, { timeout: 3000 })) as HTMLSelectElement;
    expect(calls.some((c) => c.url.includes('/api/voice/models'))).toBe(true);
    expect(select.textContent).toContain('qwen/qwen3-235b');

    // Picking from the dropdown fills the always-present free-text field.
    fireEvent.change(select, { target: { value: 'qwen/qwen3-235b' } });
    expect((screen.getByTestId('voice-setup-model') as HTMLInputElement).value).toBe('qwen/qwen3-235b');

    // Save posts the compat wire shape incl. the model row.
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    await screen.findByTestId('voice-setup-provider-result');
    const provCalls = calls.filter((c) => c.url.includes('/api/voice/provider'));
    expect(provCalls[0].body).toEqual({
      provider: 'openrouter',
      mode: 'text',
      apiStyle: 'chat',
      model: 'qwen/qwen3-235b',
    });
  });

  it('reloads the model list after saving a previously unconfigured gateway', async () => {
    stubSetupFetch();
    const originalFetch = fetch;
    let saved = false;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/api/voice/provider')) saved = true;
      if (String(input).includes('/api/voice/models') && !saved) {
        return new Response(JSON.stringify({ detail: 'Save this gateway before fetching its model list.' }), { status: 400 });
      }
      return originalFetch(input, init);
    }));
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.click(screen.getByTestId('voice-setup-provider-openrouter'));
    await screen.findByTestId('voice-setup-models-error');
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    await screen.findByTestId('voice-setup-model-select', {}, { timeout: 3000 });
    expect(saved).toBe(true);
  });

  it('models fetch failure shows the verbatim detail; free text stays usable', async () => {
    stubSetupFetch({ ok: false, error: 'models_unavailable', detail: 'HTTP 401 from https://openrouter.ai/api/v1/models' });
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.click(screen.getByTestId('voice-setup-provider-openrouter'));

    const err = await screen.findByTestId('voice-setup-models-error', {}, { timeout: 3000 });
    expect(err.textContent).toContain('HTTP 401 from https://openrouter.ai/api/v1/models'); // verbatim
    expect(screen.queryByTestId('voice-setup-model-select')).toBeNull();

    // Custom model ids are always allowed.
    const modelInput = screen.getByTestId('voice-setup-model') as HTMLInputElement;
    fireEvent.change(modelInput, { target: { value: 'my-custom-model-id' } });
    expect(modelInput.value).toBe('my-custom-model-id');
  });
});

describe('Anthropic + Custom endpoint presets', () => {
  beforeEach(() => {
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus(disabledStatus());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    voiceController.resetForNewSession();
    voiceController.setPanelOpen(false);
  });

  it('renders both new presets alongside the existing ones', async () => {
    stubFetch();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    // The provider step is revealed once voice is on.
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');
    expect(screen.getByTestId('voice-setup-provider-anthropic')).not.toBeNull();
    expect(screen.getByTestId('voice-setup-provider-custom')).not.toBeNull();
    expect(screen.getByTestId('voice-setup-provider-openai')).not.toBeNull();
  });

  it('Anthropic preset shows the text-only label and saves the anthropic wire shape', async () => {
    const calls = stubFetch({ provider: { ok: true, resolved: 'anthropic_text', degradedReason: null } });
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');

    fireEvent.click(screen.getByTestId('voice-setup-provider-anthropic'));
    // Honesty label: Claude is TEXT-ONLY — typed console + briefs, no voice.
    expect(screen.getByTestId('voice-setup-anthropic-note').textContent).toContain('dictate');

    // Model dropdown fed by GET /api/voice/models?provider=anthropic.
    const select = (await screen.findByTestId('voice-setup-model-select', {}, { timeout: 3000 })) as HTMLSelectElement;
    const modelsCall = calls.find((c) => c.url.includes('/api/voice/models?provider=anthropic'));
    expect(modelsCall).toBeTruthy();

    fireEvent.change(select, { target: { value: 'claude-sonnet-4-5' } });
    fireEvent.change(screen.getByTestId('voice-setup-api-key'), { target: { value: 'sk-ant-1' } });
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    await screen.findByTestId('voice-setup-provider-result');

    const provCalls = calls.filter((c) => c.url.includes('/api/voice/provider'));
    expect(provCalls[0].body).toEqual({ provider: 'anthropic', mode: 'text', apiStyle: 'chat', apiKey: 'sk-ant-1', model: 'claude-sonnet-4-5' });
    expect(screen.getByTestId('voice-setup-provider-result').textContent).toContain('anthropic_text');
  });

  it('Custom endpoint is a compat alias with an example placeholder', async () => {
    const calls = stubFetch();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');

    fireEvent.click(screen.getByTestId('voice-setup-provider-custom'));
    const baseUrlInput = screen.getByTestId('voice-setup-base-url') as HTMLInputElement;
    expect(baseUrlInput.placeholder).toBe('https://your-gateway.example/v1');

    fireEvent.change(baseUrlInput, { target: { value: 'https://gw.corp.example/v1' } });
    fireEvent.change(screen.getByTestId('voice-setup-api-key'), { target: { value: 'gw-key-9' } });
    fireEvent.change(screen.getByTestId('voice-setup-model'), { target: { value: 'my-model' } });
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    await screen.findByTestId('voice-setup-provider-result');

    const provCalls = calls.filter((c) => c.url.includes('/api/voice/provider'));
    expect(provCalls[0].body).toEqual({
      provider: 'compat',
      baseUrl: 'https://gw.corp.example/v1',
      mode: 'text',
      apiStyle: 'chat',
      apiKey: 'gw-key-9',
      model: 'my-model',
    });
  });
});

describe('key management — Replace key / clear affordances for a configured provider', () => {
  /** Resting state that mounts the connect card (enabled, text mode)… */
  function textModeStatus(): VoiceStatusResponse {
    return {
      ...disabledStatus(),
      effectiveEnable: true,
      opt_in_state: 'enabled',
      flags: { enableSet: true, acknowledgeSet: true },
      provider: {
        resolved: 'local_text',
        requestedMode: 'auto',
        openaiKeySet: false,
        compatKeySet: false,
        compatBaseUrlSet: true,
        geminiKeySet: false,
        chatModelConfigured: true,
      },
      degradedReason: null,
      reasons: [],
    };
  }

  /** …while the card's own status poll reports the Gemini key already saved. */
  function geminiKeySavedStatus(): VoiceStatusResponse {
    return {
      ...textModeStatus(),
      provider: {
        ...textModeStatus().provider,
        compatBaseUrlSet: false,
        compatKeySet: false,
        chatModelConfigured: false,
        geminiKeySet: true,
      },
    };
  }

  function stubWithGeminiConfigured(): CapturedCall[] {
    const calls: CapturedCall[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
      calls.push({ url, body });
      if (url.includes('/api/voice/opt-in')) {
        return new Response(JSON.stringify({ ok: true, effectiveEnable: true, managedByEnvironment: false }), { status: 200 });
      }
      if (url.includes('/api/voice/provider')) {
        if (body?.clear === true) {
          return new Response(
            JSON.stringify({
              ok: true,
              cleared: true,
              provider: { resolved: null, geminiKeySet: false },
              degradedReason: 'No usable voice provider configured',
              managedByEnvironment: false,
            }),
            { status: 200 },
          );
        }
        return new Response(JSON.stringify({ ok: true, resolved: 'gemini_live', degradedReason: null }), { status: 200 });
      }
      if (url.includes('/api/voice/status')) {
        // First poll: configured; after the clear POST: nothing saved (still
        // enabled/text-mode so the connect card stays mounted).
        const cleared = calls.some((c) => c.url.includes('/api/voice/provider') && c.body?.clear === true);
        return new Response(JSON.stringify(cleared ? textModeStatus() : geminiKeySavedStatus()), { status: 200 });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    return calls;
  }

  beforeEach(() => {
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus(textModeStatus());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    voiceController.resetForNewSession();
    voiceController.setPanelOpen(false);
  });

  it('a configured provider shows the replace note + Clear button', async () => {
    stubWithGeminiConfigured();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    // Enabled-but-text-mode mounts the connect card directly on the provider step.
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.click(screen.getByTestId('voice-setup-provider-gemini'));

    expect(await screen.findByTestId('voice-setup-key-configured-note')).not.toBeNull();
    expect(screen.getByTestId('voice-setup-clear-provider').textContent).toContain('Clear saved key');
  });

  it('an unconfigured provider shows no Clear button', async () => {
    stubFetch(); // status → disabledStatus(): nothing configured
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.click(screen.getByTestId('voice-setup-provider-gemini'));
    await new Promise((r) => setTimeout(r, 20));

    expect(screen.queryByTestId('voice-setup-clear-provider')).toBeNull();
    expect(screen.queryByTestId('voice-setup-key-configured-note')).toBeNull();
  });

  it('Clear POSTs the clear variant and refreshes status afterwards', async () => {
    const calls = stubWithGeminiConfigured();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.click(screen.getByTestId('voice-setup-provider-gemini'));

    fireEvent.click(await screen.findByTestId('voice-setup-clear-provider'));
    await screen.findByTestId('voice-setup-provider-result');

    const clearCalls = calls.filter((c) => c.url.includes('/api/voice/provider'));
    expect(clearCalls[0].body).toEqual({ provider: 'gemini', clear: true });
    // The clear response's honest confirmation is surfaced.
    expect(screen.getByTestId('voice-setup-provider-result').textContent).toContain('cleared');
    // A fresh /api/voice/status poll followed the clear.
    expect(calls.some((c) => c.url.includes('/api/voice/status'))).toBe(true);
  });

  it('saving again simply overwrites (no clear flag on the save body)', async () => {
    const calls = stubWithGeminiConfigured();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.click(screen.getByTestId('voice-setup-provider-gemini'));
    await screen.findByTestId('voice-setup-clear-provider');

    fireEvent.change(screen.getByTestId('voice-setup-api-key'), { target: { value: 'gm-replacement' } });
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    await screen.findByTestId('voice-setup-provider-result');

    const saveCall = calls.find(
      (c) => c.url.includes('/api/voice/provider') && c.body && c.body.clear === undefined,
    );
    expect(saveCall?.body).toEqual({
      provider: 'gemini',
      apiKey: 'gm-replacement',
      mode: 'text',
      apiStyle: 'chat',
    });
  });
});

describe('multi-provider and local model setup', () => {
  beforeEach(() => {
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus(disabledStatus());
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it.each([
    ['xai', 'xai'], ['meta', 'meta'], ['lmstudio', 'lmstudio'], ['local', 'ollama'],
    ['openrouter', 'openrouter'], ['anthropic', 'anthropic'], ['gemini', 'gemini'], ['custom', 'compat'],
  ])('saves %s as an explicit text provider with the selected model', async (preset, provider) => {
    const calls = stubSetupFetch();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.click(screen.getByTestId(`voice-setup-provider-${preset}`));
    expect((screen.getByTestId('voice-setup-mode') as HTMLSelectElement).value).toBe('text');
    if (preset === 'custom') fireEvent.change(screen.getByTestId('voice-setup-base-url'), { target: { value: 'http://localhost:4141/v1' } });
    fireEvent.change(screen.getByTestId('voice-setup-model'), { target: { value: 'current-served-model' } });
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    await screen.findByTestId('voice-setup-provider-result');
    expect(calls.find((call) => call.url.endsWith('/api/voice/provider'))?.body).toMatchObject({ provider, mode: 'text', model: 'current-served-model' });
  });

  it('supports Responses on a custom server and clears a typed credential when changing provider', async () => {
    const calls = stubSetupFetch();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.change(screen.getByTestId('voice-setup-api-key'), { target: { value: 'previous-secret' } });
    fireEvent.click(screen.getByTestId('voice-setup-provider-custom'));
    expect((screen.getByTestId('voice-setup-api-key') as HTMLInputElement).value).toBe('');
    fireEvent.change(screen.getByTestId('voice-setup-api-style'), { target: { value: 'responses' } });
    fireEvent.change(screen.getByTestId('voice-setup-base-url'), { target: { value: 'http://localhost:4141/v1' } });
    fireEvent.change(screen.getByTestId('voice-setup-model'), { target: { value: 'current-gpt-model' } });
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    await screen.findByTestId('voice-setup-provider-result');
    expect(calls.find((call) => call.url.endsWith('/api/voice/provider'))?.body).toEqual({ provider: 'compat', mode: 'text', apiStyle: 'responses', baseUrl: 'http://localhost:4141/v1', model: 'current-gpt-model' });
  });
});
