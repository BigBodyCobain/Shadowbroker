import { beforeEach, describe, expect, it, vi } from 'vitest';

const primeAdminSession = vi.fn();
const localControlFetch = vi.fn();
const hasLocalControlBridge = vi.fn();
const canInvokeLocalControl = vi.fn();

vi.mock('@/lib/adminSession', () => ({
  primeAdminSession,
}));

vi.mock('@/lib/localControlTransport', () => ({
  localControlFetch,
  hasLocalControlBridge,
  canInvokeLocalControl,
}));

describe('controlPlane native boundary', () => {
  beforeEach(() => {
    vi.resetModules();
    primeAdminSession.mockReset();
    localControlFetch.mockReset();
    hasLocalControlBridge.mockReset();
    canInvokeLocalControl.mockReset();
    localControlFetch.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  });

  it('skips browser admin-session priming when a native bridge can invoke the request', async () => {
    hasLocalControlBridge.mockReturnValue(true);
    canInvokeLocalControl.mockReturnValue(true);

    const mod = await import('@/lib/controlPlane');
    await mod.controlPlaneFetch('/api/wormhole/gate/message/compose', {
      method: 'POST',
      body: JSON.stringify({ gate_id: 'infonet', plaintext: 'hello' }),
    });

    expect(primeAdminSession).not.toHaveBeenCalled();
    expect(localControlFetch).toHaveBeenCalledTimes(1);
  });

  it('still primes browser admin-session when no native invoke path exists', async () => {
    hasLocalControlBridge.mockReturnValue(false);
    canInvokeLocalControl.mockReturnValue(false);

    const mod = await import('@/lib/controlPlane');
    await mod.controlPlaneFetch('/api/wormhole/identity');

    expect(primeAdminSession).toHaveBeenCalledTimes(1);
    expect(localControlFetch).toHaveBeenCalledTimes(1);
  });
});
