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
    expect(provCalls[0].body).toEqual({ provider: 'gemini', apiKey: 'gm-key-1' });

    // Resolved provider echoed back honestly.
    expect(screen.getByTestId('voice-setup-provider-result').textContent).toContain('gemini_live');
  });

  it('shows the Voice-is-on confirmation once both steps succeed', async () => {
    stubFetch();
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('voice-setup-turn-on'));
    await screen.findByTestId('voice-setup-optin-done');
    fireEvent.click(screen.getByTestId('voice-setup-save-provider'));
    expect(await screen.findByTestId('voice-setup-done')).not.toBeNull();
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
