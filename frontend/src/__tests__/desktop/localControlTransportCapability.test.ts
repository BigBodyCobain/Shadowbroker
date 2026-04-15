import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('localControlTransport capability metadata', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('attaches capability intent metadata when invoking the native bridge', async () => {
    const invoke = vi.fn(async () => ({ ok: true }));
    Object.defineProperty(globalThis, 'window', {
      value: {
        __SHADOWBROKER_LOCAL_CONTROL__: {
          invoke,
        },
      },
      configurable: true,
      writable: true,
    });

    const mod = await import('@/lib/localControlTransport');
    await mod.localControlFetch('/api/wormhole/gate/key/rotate', {
      method: 'POST',
      capabilityIntent: 'wormhole_gate_key',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      body: JSON.stringify({ gate_id: 'infonet', reason: 'operator_reset' }),
    });

    expect(invoke).toHaveBeenCalledWith({
      command: 'wormhole.gate.key.rotate',
      payload: { gate_id: 'infonet', reason: 'operator_reset' },
      meta: {
        capability: 'wormhole_gate_key',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
      },
    });
  });

  it('falls back to plain fetch when the HTTP-backed shim refuses strict enforcement', async () => {
    const invoke = vi.fn(async () => {
      throw new Error('desktop_runtime_shim_enforcement_inactive');
    });
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, gate_id: 'infonet' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    Object.defineProperty(globalThis, 'window', {
      value: {
        __SHADOWBROKER_LOCAL_CONTROL__: {
          invoke,
        },
      },
      configurable: true,
      writable: true,
    });

    const mod = await import('@/lib/localControlTransport');
    const res = await mod.localControlFetch('/api/wormhole/gate/proof', {
      method: 'POST',
      capabilityIntent: 'wormhole_gate_content',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gate_id: 'infonet' }),
    });
    const data = await res.json();

    expect(invoke).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/wormhole/gate/proof',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ gate_id: 'infonet' }),
      }),
    );
    expect(data).toEqual({ ok: true, gate_id: 'infonet' });
  });
});
