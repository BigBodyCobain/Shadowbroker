/**
 * §7.D / §3.7 — deterministic zero-model loop phrase coverage.
 *
 * The camera regexes (zoom/orbit), the plain-language layer-toggle and
 * Time-Machine phrases added for acceptance #38, and the §3.7 item 2
 * pending-confirmation turn for gated route_query recommendations.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { onRequest } from '@/lib/mapControlBus';
import {
  clearPendingConfirmation,
  getPendingConfirmation,
  runDeterministicTurn,
} from '@/lib/voiceDeterministic';
import { voiceController } from '@/lib/voiceController';
import type { ClientToolContext } from '@/lib/clientTools';

function baseCtx(overrides: Partial<ClientToolContext> = {}): ClientToolContext {
  return {
    flyTo: vi.fn(),
    toggleLayer: vi.fn((_layer: string, enabled: boolean) => enabled), // applied == requested
    applyMapStyle: vi.fn((s) => s),
    setFilter: vi.fn(),
    setSelectedEntity: vi.fn(),
    viewSummary: vi.fn(() => ({ activeLayers: { sar: false, ships: true }, filters: {} })),
    ...overrides,
  };
}

describe('deterministic plain-language phrases (acceptance #38)', () => {
  beforeEach(() => clearPendingConfirmation());
  afterEach(() => {
    clearPendingConfirmation();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("'toggle sar layer' enables the sar layer", async () => {
    const ctx = baseCtx();
    const outcome = await runDeterministicTurn('toggle sar layer', ctx);
    expect(ctx.toggleLayer).toHaveBeenCalledWith('sar', true);
    expect(outcome.steps[0]).toMatchObject({ tool: 'toggle_layer', ok: true });
    expect(outcome.reply).toBe('Layer sar enabled.');
  });

  it("'hide ships layer' disables the ships layer", async () => {
    const ctx = baseCtx();
    const outcome = await runDeterministicTurn('hide ships layer', ctx);
    expect(ctx.toggleLayer).toHaveBeenCalledWith('ships', false);
    expect(outcome.steps[0]).toMatchObject({ tool: 'toggle_layer', ok: true });
    expect(outcome.reply).toBe('Layer ships disabled.');
  });

  it("'play time machine' starts playback through tm_playback", async () => {
    const outcome = await runDeterministicTurn('play time machine', baseCtx());
    expect(outcome.steps[0]).toMatchObject({ tool: 'tm_playback', ok: true });
    expect(outcome.reply).toBe('Time Machine play.');
  });

  it("'zoom out' rides the map control bus, not the tool endpoint", async () => {
    let sawToolEndpoint = false;
    const seen: unknown[] = [];
    const dispose = onRequest((cmd) => {
      seen.push(cmd);
      return { ok: true, action: cmd.type };
    });
    const wrapped = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/api/voice/tool')) sawToolEndpoint = true;
      throw new Error(`unexpected fetch ${String(input)}`);
    });
    vi.stubGlobal('fetch', wrapped);
    try {
      const outcome = await runDeterministicTurn('zoom out', baseCtx());
      expect(seen).toEqual([{ type: 'zoom', direction: 'out', amount: 'medium' }]);
      expect(sawToolEndpoint).toBe(false); // camera regexes stay local (§3.7)
      expect(outcome.steps[0]).toMatchObject({ tool: 'map_zoom', ok: true });
      expect(outcome.reply).toBe('Zoomed out.');
    } finally {
      dispose();
    }
  });

  it("'stop orbit' stops the orbit through the bus", async () => {
    const seen: unknown[] = [];
    const dispose = onRequest((cmd) => {
      seen.push(cmd);
      return { ok: true, action: cmd.type, orbiting: false };
    });
    try {
      const outcome = await runDeterministicTurn('stop orbit', baseCtx());
      // radiusKm/speed stay unset for the stop verb (toEqual ignores undefined).
      expect(seen).toEqual([{ type: 'orbit', lng: 0, lat: 0, stop: true }]);
      expect(outcome.steps[0]).toMatchObject({ tool: 'map_orbit', ok: true });
      expect(outcome.reply).toBe('Orbit stopped.');
    } finally {
      dispose();
    }
  });

  it("an unknown layer phrase never guesses — it falls through to route_query", async () => {
    const wrapped = vi.fn(async () =>
      new Response(JSON.stringify({ ok: false, code: 'bad_call', detail: 'no confident mapping' }), { status: 400 }),
    );
    vi.stubGlobal('fetch', wrapped);
    const ctx = baseCtx();
    const outcome = await runDeterministicTurn('toggle wibble layer', ctx);
    expect(ctx.toggleLayer).not.toHaveBeenCalled();
    expect(outcome.steps[0]?.tool).toBe('route_query');
  });
});

describe('§3.7 item 2 — gated route_query recommendation awaits confirmation', () => {
  beforeEach(() => clearPendingConfirmation());
  afterEach(() => {
    clearPendingConfirmation();
    vi.unstubAllGlobals();
  });

  function stubRouteAndGate() {
    const calls: Array<{ body: Record<string, unknown> }> = [];
    const wrapped = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
      calls.push({ body });
      if (body.tool === 'route_query') {
        return new Response(
          JSON.stringify({
            ok: true,
            data: { intent: 'telemetry_sweep', recommended: { cmd: 'full_telemetry_sweep', args: { area: 'kyiv' } } },
          }),
          { status: 200 },
        );
      }
      // Gated execution — expensive gate blocks without confirm_expensive.
      return new Response(
        JSON.stringify({
          ok: false,
          code: 'expensive_command_blocked',
          detail: "That's a full telemetry sweep — confirm?",
        }),
        { status: 400 },
      );
    });
    vi.stubGlobal('fetch', wrapped);
    return calls;
  }

  function stubConfirmAccepted(calls: Array<{ body: Record<string, unknown> }>) {
    // Re-stub AFTER the gate-blocked turn so only the confirmed retry succeeds.
    const wrapped = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
      calls.push({ body });
      return new Response(JSON.stringify({ ok: true, action: String(body.tool), data: { count: 42 } }), { status: 200 });
    });
    vi.stubGlobal('fetch', wrapped);
    return wrapped;
  }

  it('speaks the gate message verbatim and arms a pending confirmation', async () => {
    stubRouteAndGate();
    const outcome = await runDeterministicTurn('sweep kyiv telemetry', baseCtx());
    expect(outcome.reply).toBe("That's a full telemetry sweep — confirm? Type 'confirm' to run it.");
    expect(getPendingConfirmation()).toEqual({
      tool: 'full_telemetry_sweep',
      args: { area: 'kyiv' },
      kind: 'expensive',
    });
    expect(outcome.steps.some((s) => !s.ok)).toBe(true); // gate block is honest
  });

  it("the bare unlock word retries with confirm_expensive and reports the result", async () => {
    const calls = stubRouteAndGate();
    await runDeterministicTurn('sweep kyiv telemetry', baseCtx()); // arm pending against the GATING stub
    expect(getPendingConfirmation()).not.toBeNull();

    stubConfirmAccepted(calls); // only now do confirmations succeed
    const outcome = await runDeterministicTurn('confirm', baseCtx());

    const retry = calls.findLast((c) => c.body.tool === 'full_telemetry_sweep');
    expect(retry?.body.confirm_expensive).toBe(true); // top-level flag (U3 contract)
    expect(getPendingConfirmation()).toBeNull(); // one-shot consumption
    expect(outcome.reply).toBe('full_telemetry_sweep: 42');
    expect(outcome.steps.at(-1)).toMatchObject({ tool: 'full_telemetry_sweep', ok: true });
  });

  it('any other input abandons the pending confirmation honestly', async () => {
    stubRouteAndGate();
    await runDeterministicTurn('sweep kyiv telemetry', baseCtx());
    const wrapped = vi.fn(async () =>
      new Response(JSON.stringify({ results: [{ label: 'Kyiv', lat: 50.45, lng: 30.52 }] }), { status: 200 }),
    );
    vi.stubGlobal('fetch', wrapped);
    const ctx = baseCtx();
    const outcome = await runDeterministicTurn('fly to Kyiv', ctx);

    expect(getPendingConfirmation()).toBeNull(); // abandoned by non-confirm text
    expect(outcome.steps.some((s) => s.detail === 'pending confirmation discarded')).toBe(true);
    expect(ctx.flyTo).toHaveBeenCalled(); // the new intent still ran
  });

  it('a destructive gate arms kind=destructive and confirms with confirm:true', async () => {
    const calls: Array<{ body: Record<string, unknown> }> = [];
    const routeOk = () =>
      new Response(
        JSON.stringify({
          ok: true,
          data: { intent: 'cleanup', recommended: { cmd: 'delete_analysis_zone', args: { id: 'z1' } } },
        }),
        { status: 200 },
      );
    let acceptConfirms = false;
    const wrapped = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
      calls.push({ body });
      if (body.tool === 'route_query') return routeOk();
      if (!acceptConfirms) {
        return new Response(
          JSON.stringify({ ok: false, code: 'destructive_confirm_required', detail: 'Destructive op — confirm.' }),
          { status: 400 },
        );
      }
      return new Response(JSON.stringify({ ok: true, action: body.tool, data: { deleted: true } }), { status: 200 });
    });
    vi.stubGlobal('fetch', wrapped);

    const first = await runDeterministicTurn('delete zone z1', baseCtx());
    expect(first.reply).toContain('Destructive op — confirm.');
    expect(getPendingConfirmation()?.kind).toBe('destructive');

    acceptConfirms = true;
    await runDeterministicTurn('confirm', baseCtx());
    const retry = calls.filter((c) => c.body.tool === 'delete_analysis_zone').at(-1);
    expect(retry?.body.confirm).toBe(true);
  });
});

describe('degraded-mode honesty — realtime provider armed vs nothing configured', () => {
  beforeEach(() => clearPendingConfirmation());
  afterEach(() => {
    clearPendingConfirmation();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    // Restore the unconfigured resting state for later suites.
    voiceController.resetForNewSession();
    voiceController.applyStatus(unconfiguredStatus());
  });

  function unconfiguredStatus() {
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
      reasons: [],
      mode: 'full',
      costDefaults: { warnUsd: 'off', capUsd: 'off', dailyBudgetUsd: 'off' },
      dailySpend: { date: '', usdSpent: 0, budgetUsd: 'off', remainingUsd: 'off', ledgerQuarantined: false },
      activeSessions: 0,
      maxConcurrent: 1,
    } as Parameters<typeof voiceController.applyStatus>[0];
  }

  function stubRouteQueryWithoutCommand() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true, data: { intent: 'discovery' } }), { status: 200 }),
      ),
    );
  }

  it('a gemini_live badge must not read "No model configured" — name the armed provider', async () => {
    const base = unconfiguredStatus();
    voiceController.applyStatus({
      ...base,
      effectiveEnable: true,
      opt_in_state: 'enabled',
      flags: { enableSet: true, acknowledgeSet: true },
      provider: {
        ...base.provider,
        resolved: 'gemini_live',
        geminiKeySet: true,
      },
    });
    expect(voiceController.getState().providerResolved).toBe('gemini_live');
    stubRouteQueryWithoutCommand();
    const outcome = await runDeterministicTurn('what changed', baseCtx());
    expect(outcome.reply).toBe(
      "Voice provider armed (gemini_live) — text chat unavailable right now. Try: 'fly to Kyiv', 'what changed', 'news on Ukraine'.",
    );
  });

  it('nothing configured keeps the original deterministic wording', async () => {
    stubRouteQueryWithoutCommand();
    const outcome = await runDeterministicTurn('what changed', baseCtx());
    expect(outcome.reply).toBe(
      "No model configured — running deterministic mode. Try: 'fly to Kyiv', 'what changed', 'news on Ukraine'.",
    );
  });
});
