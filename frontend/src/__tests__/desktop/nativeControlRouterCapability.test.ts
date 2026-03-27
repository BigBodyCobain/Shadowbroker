import { describe, expect, it, vi } from 'vitest';

import { createNativeControlRouter } from '../../../../desktop-shell/src/nativeControlRouter';

describe('nativeControlRouter capability scaffolding', () => {
  it('rejects mismatched capability intent', async () => {
    const exec = async <T = unknown>(): Promise<T> => ({ ok: true } as T);
    const router = createNativeControlRouter(
      {
        backendBaseUrl: 'http://127.0.0.1:8000',
        wormholeBaseUrl: 'http://127.0.0.1:8787',
      },
      exec,
    );

    await expect(
      router.invoke(
        'wormhole.gate.key.rotate',
        { gate_id: 'infonet', reason: 'operator_reset' },
        { capability: 'wormhole_gate_content' },
      ),
    ).rejects.toThrow('native_control_capability_mismatch');
  });

  it('rejects commands outside the allowed native capability set', async () => {
    const exec = async <T = unknown>(): Promise<T> => ({ ok: true } as T);
    const router = createNativeControlRouter(
      {
        backendBaseUrl: 'http://127.0.0.1:8000',
        wormholeBaseUrl: 'http://127.0.0.1:8787',
        allowedCapabilities: ['wormhole_gate_content'],
      },
      exec,
    );

    await expect(
      router.invoke(
        'wormhole.gate.key.rotate',
        { gate_id: 'infonet', reason: 'operator_reset' },
        { capability: 'wormhole_gate_key' },
      ),
    ).rejects.toThrow('native_control_capability_denied');
  });

  it('audits session-profile mismatch without denying by default', async () => {
    const auditControlUse = vi.fn();
    const exec = async <T = unknown>(): Promise<T> => ({ ok: true } as T);
    const router = createNativeControlRouter(
      {
        backendBaseUrl: 'http://127.0.0.1:8000',
        wormholeBaseUrl: 'http://127.0.0.1:8787',
        sessionProfile: 'settings_only',
        auditControlUse,
      },
      exec,
    );

    const result = await router.invoke(
      'wormhole.gate.key.rotate',
      { gate_id: 'infonet', reason: 'operator_reset' },
      { capability: 'wormhole_gate_key', sessionProfileHint: 'gate_operator' },
    );

    expect(result).toEqual({ ok: true });
    expect(auditControlUse).toHaveBeenCalledWith(
      expect.objectContaining({
        command: 'wormhole.gate.key.rotate',
        expectedCapability: 'wormhole_gate_key',
        targetRef: 'infonet',
        sessionProfile: 'settings_only',
        sessionProfileHint: 'gate_operator',
        profileAllows: false,
        enforced: false,
        outcome: 'profile_warn',
      }),
    );
  });

  it('includes targetRef in audit events for gate commands', async () => {
    const auditControlUse = vi.fn();
    const exec = async <T = unknown>(): Promise<T> => ({ ok: true } as T);
    const router = createNativeControlRouter(
      {
        backendBaseUrl: 'http://127.0.0.1:8000',
        wormholeBaseUrl: 'http://127.0.0.1:8787',
        auditControlUse,
      },
      exec,
    );

    await router.invoke(
      'wormhole.gate.message.compose',
      { gate_id: 'ops-room', plaintext: 'hello' },
      { capability: 'wormhole_gate_content' },
    );

    expect(auditControlUse).toHaveBeenCalledWith(
      expect.objectContaining({
        command: 'wormhole.gate.message.compose',
        targetRef: 'ops-room',
        outcome: 'allowed',
      }),
    );
  });

  it('omits targetRef for non-gate commands', async () => {
    const auditControlUse = vi.fn();
    const exec = async <T = unknown>(): Promise<T> => ({ ok: true } as T);
    const router = createNativeControlRouter(
      {
        backendBaseUrl: 'http://127.0.0.1:8000',
        wormholeBaseUrl: 'http://127.0.0.1:8787',
        auditControlUse,
      },
      exec,
    );

    await router.invoke('wormhole.status', undefined);

    const event = auditControlUse.mock.calls[0][0];
    expect(event.command).toBe('wormhole.status');
    expect(event.targetRef).toBeUndefined();
  });

  it('can enforce session-profile mismatch when explicitly enabled', async () => {
    const exec = async <T = unknown>(): Promise<T> => ({ ok: true } as T);
    const router = createNativeControlRouter(
      {
        backendBaseUrl: 'http://127.0.0.1:8000',
        wormholeBaseUrl: 'http://127.0.0.1:8787',
        sessionProfile: 'settings_only',
        enforceSessionProfile: true,
      },
      exec,
    );

    await expect(
      router.invoke(
        'wormhole.gate.key.rotate',
        { gate_id: 'infonet', reason: 'operator_reset' },
        { capability: 'wormhole_gate_key', sessionProfileHint: 'gate_operator' },
      ),
    ).rejects.toThrow('native_control_profile_mismatch');
  });

  it('can enforce a hinted session profile for a narrow gate-key command', async () => {
    const exec = async <T = unknown>(): Promise<T> => ({ ok: true } as T);
    const router = createNativeControlRouter(
      {
        backendBaseUrl: 'http://127.0.0.1:8000',
        wormholeBaseUrl: 'http://127.0.0.1:8787',
        sessionProfile: 'settings_only',
      },
      exec,
    );

    await expect(
      router.invoke(
        'wormhole.gate.key.rotate',
        { gate_id: 'infonet', reason: 'operator_reset' },
        {
          capability: 'wormhole_gate_key',
          sessionProfileHint: 'gate_operator',
          enforceProfileHint: true,
        },
      ),
    ).rejects.toThrow('native_control_profile_mismatch');
  });
});
