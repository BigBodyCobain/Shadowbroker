/**
 * §7.D items 32–33 — VoiceHudPanel: tool failures render verbatim detail and
 * OK is never shown for a failed tool; composer Enter routes through the
 * controller transcript path; cost `*` renders with the note tooltip.
 * The honesty smoke drives the deterministic loop against an ok:false server
 * envelope and asserts the failure is flagged, never fabricated as success.
 */
import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import VoiceHudPanel from '@/components/VoiceHudPanel';
import { voiceController } from '@/lib/voiceController';
import { runDeterministicTurn } from '@/lib/voiceDeterministic';
import type { ClientToolContext } from '@/lib/clientTools';

function baseCtx(): ClientToolContext {
  return {
    flyTo: vi.fn(),
    toggleLayer: vi.fn(() => true),
    applyMapStyle: vi.fn((s) => s),
    setFilter: vi.fn(),
    setSelectedEntity: vi.fn(),
    viewSummary: vi.fn(() => ({ activeLayers: {}, filters: {} })),
  };
}

describe('VoiceHudPanel', () => {
  beforeEach(() => {
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus({
      ok: true,
      effectiveEnable: false,
      opt_in_state: 'not_requested',
      flags: { enableSet: false, acknowledgeSet: false },
      provider: { resolved: null, requestedMode: 'auto', openaiKeySet: false, compatKeySet: false, compatBaseUrlSet: false, chatModelConfigured: false },
      degradedReason: 'voice disabled',
      reasons: ['blocked'],
      mode: 'full',
      costDefaults: { warnUsd: 'off', capUsd: 'off', dailyBudgetUsd: 'off' },
      dailySpend: { date: '', usdSpent: 0, budgetUsd: 'off', remainingUsd: 'off', ledgerQuarantined: false },
      activeSessions: 0,
      maxConcurrent: 1,
    });
  });

  afterEach(() => cleanup());

  it('failed tool rows render verbatim detail; OK never shown for them', () => {
    voiceController.pushTurn({
      role: 'agent',
      kind: 'tool',
      text: 'news_search',
      tool: { name: 'news_search', args_summary: 'query=ukraine', ok: false, detail: 'upstream feed returned HTTP 503' },
    });
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    const row = screen.getByTestId('voice-tool-row');
    expect(row.textContent).toContain('FAILED');
    expect(row.textContent).toContain('upstream feed returned HTTP 503'); // verbatim
    expect(row.textContent).not.toContain('OK');
  });

  it('successful tool rows render OK', () => {
    voiceController.pushTurn({
      role: 'agent',
      kind: 'tool',
      text: 'map_fly_to',
      tool: { name: 'map_fly_to', args_summary: '31.5, 34.8', ok: true, detail: '' },
    });
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    const row = screen.getByTestId('voice-tool-row');
    expect(row.textContent).toContain('OK');
    expect(row.querySelector('[data-testid="voice-tool-fail"]')).toBeNull();
  });

  it('composer Enter routes through the same controller path (onSubmit)', () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<VoiceHudPanel onSubmit={onSubmit} onClose={vi.fn()} />);
    const input = screen.getByRole('textbox') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'fly to Kyiv' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith('fly to Kyiv');
  });

  it('cost chip renders the incomplete asterisk with the honest tooltip', () => {
    voiceController.applyCost({ total_usd: 0.42, display: '~$0.42', level: 'ok', note: 'estimated from audio duration — provider did not report token usage', incomplete: true });
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    const chip = screen.getByTestId('voice-cost-chip');
    expect(chip.textContent).toBe('~$0.42*');
    expect(chip.getAttribute('title')).toContain('provider did not report token usage');
  });

  it('transcript container exposes log semantics for captions', () => {
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    const log = screen.getByTestId('voice-transcript');
    expect(log.getAttribute('role')).toBe('log');
    expect(log.getAttribute('aria-live')).toBe('polite');
  });
});

describe('honesty eval smoke (#33) — deterministic loop with ok:false envelope', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it('renders the failure flagged, never as success', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/voice/tool')) {
        // First call routes, second executes and fails.
        const body = JSON.parse((fetchMock as unknown as { lastBody?: string }).lastBody ?? '{}');
        void body;
        return new Response(JSON.stringify({ ok: false, code: 'upstream_error', detail: 'feed unreachable: ECONNREFUSED' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    }) as unknown as typeof fetch & { lastBody?: string };
    const wrapped = async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body) (fetchMock as unknown as { lastBody?: string }).lastBody = String(init.body);
      return fetchMock(input, init);
    };
    vi.stubGlobal('fetch', wrapped);

    const outcome = await runDeterministicTurn('news on Ukraine', baseCtx());
    expect(outcome.steps.some((s) => !s.ok)).toBe(true);
    expect(outcome.reply).toBe('feed unreachable: ECONNREFUSED'); // verbatim

    // Rendered transcript flags the failure.
    voiceController.pushTurn({
      role: 'agent',
      kind: 'tool',
      text: outcome.steps[1]?.tool ?? 'route_query',
      tool: {
        name: outcome.steps[1]?.tool ?? 'route_query',
        args_summary: '',
        ok: false,
        detail: outcome.reply,
      },
    });
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    const row = screen.getByTestId('voice-tool-fail');
    expect(row.textContent).toContain('feed unreachable: ECONNREFUSED');
    expect(screen.getByTestId('voice-transcript').textContent).not.toMatch(/—\s*OK/);
  });

  it('camera phrases fly the map without any model or LLM path', async () => {
    let sawToolEndpoint = false;
    const wrapped = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/geocode/search')) {
        return new Response(JSON.stringify({ results: [{ label: 'Kyiv, Ukraine', lat: 50.45, lng: 30.52 }] }), { status: 200 });
      }
      if (url.includes('/api/voice/tool')) sawToolEndpoint = true;
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal('fetch', wrapped);

    const ctx = baseCtx();
    const outcome = await runDeterministicTurn('fly to Kyiv', ctx);
    expect(sawToolEndpoint).toBe(false); // camera regex path stays local
    expect(ctx.flyTo).toHaveBeenCalledWith(expect.objectContaining({ lat: 50.45, lng: 30.52 }));
    expect(outcome.reply).toBe('Flying to Kyiv, Ukraine.'); // geocoded label, verbatim
    expect(outcome.steps.every((s) => s.ok)).toBe(true);
  });
});

describe('U6 cost/quota UX surfaces', () => {
  beforeEach(() => {
    voiceController.resetForNewSession();
    voiceController.resetTranscript();
    voiceController.applyStatus({
      ok: true,
      effectiveEnable: false,
      opt_in_state: 'not_requested',
      flags: { enableSet: false, acknowledgeSet: false },
      provider: { resolved: null, requestedMode: 'auto', openaiKeySet: false, compatKeySet: false, compatBaseUrlSet: false, chatModelConfigured: false },
      degradedReason: 'voice disabled',
      reasons: ['blocked'],
      mode: 'full',
      costDefaults: { warnUsd: 'off', capUsd: 'off', dailyBudgetUsd: 'off' },
      dailySpend: { date: '', usdSpent: 0, budgetUsd: 'off', remainingUsd: 'off', ledgerQuarantined: false },
      activeSessions: 0,
      maxConcurrent: 1,
    });
  });

  afterEach(() => cleanup());

  it('estimated + worst-case-rate snapshots surface both disclosures and the asterisk', () => {
    voiceController.applyCost({
      total_usd: 0.9,
      display: '~$0.90',
      level: 'ok',
      note: null,
      estimated: true,
      ratesRecognized: false,
    });
    render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    const chip = screen.getByTestId('voice-cost-chip');
    expect(chip.textContent).toBe('~$0.90*');
    expect(chip.getAttribute('title')).toContain('estimated from audio duration');
    expect(chip.getAttribute('title')).toContain('worst-case rates');
  });

  it('daily spend chip renders against the budget only when one is configured', () => {
    voiceController.applyStatus({
      ok: true,
      effectiveEnable: false,
      opt_in_state: 'not_requested',
      flags: { enableSet: false, acknowledgeSet: false },
      provider: { resolved: null, requestedMode: 'auto', openaiKeySet: false, compatKeySet: false, compatBaseUrlSet: false, chatModelConfigured: false },
      degradedReason: null,
      reasons: [],
      mode: 'full',
      costDefaults: { warnUsd: 'off', capUsd: 'off', dailyBudgetUsd: 5 },
      dailySpend: { date: '2026-08-26', usdSpent: 1.25, budgetUsd: 5, remainingUsd: 3.75, ledgerQuarantined: false },
      activeSessions: 0,
      maxConcurrent: 1,
    });
    const { rerender } = render(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    const chip = screen.getByTestId('voice-spend-chip');
    expect(chip.textContent).toBe('$1.25/$5.00');

    // Over budget ⇒ chip goes red; budget off ⇒ no chip at all.
    voiceController.applyStatus({
      ok: true,
      effectiveEnable: false,
      opt_in_state: 'not_requested',
      flags: { enableSet: false, acknowledgeSet: false },
      provider: { resolved: null, requestedMode: 'auto', openaiKeySet: false, compatKeySet: false, compatBaseUrlSet: false, chatModelConfigured: false },
      degradedReason: null,
      reasons: [],
      mode: 'full',
      costDefaults: { warnUsd: 'off', capUsd: 'off', dailyBudgetUsd: 5 },
      dailySpend: { date: '2026-08-26', usdSpent: 5.4, budgetUsd: 5, remainingUsd: 0, ledgerQuarantined: false },
      activeSessions: 0,
      maxConcurrent: 1,
    });
    rerender(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByTestId('voice-spend-chip').className).toContain('red-500');
  });

  it('BRIEF NOW invokes the manual request; disabled while narrating or unbound', () => {
    // BRIEF NOW is reachable whenever voice is reachable — move off the
    // opt-in-required policy phase first.
    voiceController.applyStatus({
      ok: true,
      effectiveEnable: true,
      opt_in_state: 'enabled',
      flags: { enableSet: true, acknowledgeSet: true },
      provider: { resolved: 'local_text', requestedMode: 'auto', openaiKeySet: false, compatKeySet: false, compatBaseUrlSet: true, chatModelConfigured: true },
      degradedReason: null,
      reasons: [],
      mode: 'full',
      costDefaults: { warnUsd: 'off', capUsd: 'off', dailyBudgetUsd: 'off' },
      dailySpend: { date: '', usdSpent: 0, budgetUsd: 'off', remainingUsd: 'off', ledgerQuarantined: false },
      activeSessions: 0,
      maxConcurrent: 1,
    });
    const onRequestBrief = vi.fn();
    const { rerender } = render(
      <VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} onRequestBrief={onRequestBrief} />,
    );
    const button = screen.getByTestId('voice-brief-now') as HTMLButtonElement;
    expect(button.textContent.length).toBeGreaterThan(0);
    fireEvent.click(button);
    expect(onRequestBrief).toHaveBeenCalledTimes(1);

    // Narrating disables the affordance.
    voiceController.setNarrating(true);
    rerender(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} onRequestBrief={onRequestBrief} />);
    expect((screen.getByTestId('voice-brief-now') as HTMLButtonElement).disabled).toBe(true);
    voiceController.setNarrating(false);

    // Unbound handler renders the button disabled rather than dead.
    rerender(<VoiceHudPanel onSubmit={vi.fn()} onClose={vi.fn()} />);
    expect((screen.getByTestId('voice-brief-now') as HTMLButtonElement).disabled).toBe(true);
  });
});
