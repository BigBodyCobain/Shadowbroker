import { afterEach, describe, expect, it, vi } from 'vitest';

import { createRuntimeBridge } from '../../../../desktop-shell/src/runtimeBridge';

describe('runtimeBridge session profile routing', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uses the invocation session profile hint when the runtime context is unscoped', async () => {
    const auditControlUse = vi.fn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    const runtime = createRuntimeBridge({
      backendBaseUrl: 'http://127.0.0.1:8000',
      wormholeBaseUrl: 'http://127.0.0.1:8787',
      auditControlUse,
    });

    await runtime.invokeLocalControl(
      'wormhole.gate.key.rotate',
      { gate_id: 'infonet', reason: 'operator_reset' },
      {
        capability: 'wormhole_gate_key',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
      },
    );

    expect(auditControlUse).toHaveBeenCalledWith(
      expect.objectContaining({
        command: 'wormhole.gate.key.rotate',
        targetRef: 'infonet',
        sessionProfile: 'gate_operator',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
        profileAllows: true,
        outcome: 'allowed',
      }),
    );

    const report = runtime.getNativeControlAuditReport?.(5);
    expect(report).toEqual(
      expect.objectContaining({
        totalEvents: 1,
        totalRecorded: 1,
        byOutcome: expect.objectContaining({ allowed: 1 }),
      }),
    );
    expect(report?.recent[0]).toEqual(
      expect.objectContaining({
        command: 'wormhole.gate.key.rotate',
        targetRef: 'infonet',
        sessionProfile: 'gate_operator',
        outcome: 'allowed',
      }),
    );
  });

  it('preserves an explicitly scoped runtime session profile over the invocation hint', async () => {
    const auditControlUse = vi.fn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    const runtime = createRuntimeBridge({
      backendBaseUrl: 'http://127.0.0.1:8000',
      wormholeBaseUrl: 'http://127.0.0.1:8787',
      sessionProfile: 'settings_only',
      auditControlUse,
    });

    await runtime.invokeLocalControl(
      'wormhole.gate.key.rotate',
      { gate_id: 'infonet', reason: 'operator_reset' },
      {
        capability: 'wormhole_gate_key',
        sessionProfileHint: 'gate_operator',
      },
    );

    expect(auditControlUse).toHaveBeenCalledWith(
      expect.objectContaining({
        command: 'wormhole.gate.key.rotate',
        sessionProfile: 'settings_only',
        sessionProfileHint: 'gate_operator',
        profileAllows: false,
        outcome: 'profile_warn',
      }),
    );

    const report = runtime.getNativeControlAuditReport?.(5);
    expect(report).toEqual(
      expect.objectContaining({
        totalEvents: 1,
        totalRecorded: 1,
        byOutcome: expect.objectContaining({ profile_warn: 1 }),
        lastProfileMismatch: expect.objectContaining({
          command: 'wormhole.gate.key.rotate',
          sessionProfile: 'settings_only',
          outcome: 'profile_warn',
        }),
      }),
    );
  });

  it('denies a strictly hinted gate-key command when the runtime is pinned to another profile', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    const runtime = createRuntimeBridge({
      backendBaseUrl: 'http://127.0.0.1:8000',
      wormholeBaseUrl: 'http://127.0.0.1:8787',
      sessionProfile: 'settings_only',
    });

    await expect(
      runtime.invokeLocalControl(
        'wormhole.gate.key.rotate',
        { gate_id: 'infonet', reason: 'operator_reset' },
        {
          capability: 'wormhole_gate_key',
          sessionProfileHint: 'gate_operator',
          enforceProfileHint: true,
        },
      ),
    ).rejects.toThrow('native_control_profile_mismatch');

    const report = runtime.getNativeControlAuditReport?.(5);
    expect(report).toEqual(
      expect.objectContaining({
        totalEvents: 1,
        totalRecorded: 1,
        byOutcome: expect.objectContaining({ profile_denied: 1 }),
        lastDenied: expect.objectContaining({
          command: 'wormhole.gate.key.rotate',
          outcome: 'profile_denied',
        }),
      }),
    );
  });
});
