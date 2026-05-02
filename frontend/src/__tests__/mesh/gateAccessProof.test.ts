import { beforeEach, describe, expect, it, vi } from 'vitest';

const controlPlaneJson = vi.fn();
const hasLocalControlBridge = vi.fn(() => false);
const getGateSessionStreamAccessHeaders = vi.fn();

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneJson,
}));

vi.mock('@/lib/localControlTransport', () => ({
  hasLocalControlBridge,
}));

vi.mock('@/mesh/gateSessionStream', () => ({
  getGateSessionStreamAccessHeaders,
}));

describe('gateAccessProof cache', () => {
  beforeEach(() => {
    vi.resetModules();
    controlPlaneJson.mockReset();
    hasLocalControlBridge.mockReset();
    hasLocalControlBridge.mockReturnValue(false);
    getGateSessionStreamAccessHeaders.mockReset();
    getGateSessionStreamAccessHeaders.mockReturnValue(undefined);
  });

  it('caches browser/web gate proofs just under the backend validity window', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T22:40:00.000Z'));
    try {
      controlPlaneJson.mockResolvedValue({
        node_id: '!sb_gate',
        ts: 1712345678,
        proof: 'proof-a',
      });

      const mod = await import('@/mesh/gateAccessProof');

      await expect(mod.buildGateAccessHeaders('finance')).resolves.toEqual({
        'X-Wormhole-Node-Id': '!sb_gate',
        'X-Wormhole-Gate-Proof': 'proof-a',
        'X-Wormhole-Gate-Ts': '1712345678',
      });
      await expect(mod.buildGateAccessHeaders('finance')).resolves.toEqual({
        'X-Wormhole-Node-Id': '!sb_gate',
        'X-Wormhole-Gate-Proof': 'proof-a',
        'X-Wormhole-Gate-Ts': '1712345678',
      });

      expect(controlPlaneJson).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(52_001);

      await mod.buildGateAccessHeaders('finance');
      expect(controlPlaneJson).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('uses a shorter proof cache window on native runtimes', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T22:40:00.000Z'));
    try {
      hasLocalControlBridge.mockReturnValue(true);
      controlPlaneJson.mockResolvedValue({
        node_id: '!sb_gate',
        ts: 1712345678,
        proof: 'proof-native',
      });

      const mod = await import('@/mesh/gateAccessProof');

      await mod.buildGateAccessHeaders('finance');
      vi.advanceTimersByTime(35_001);
      await mod.buildGateAccessHeaders('finance');

      expect(controlPlaneJson).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('coalesces concurrent proof requests for the same gate into one control-plane call', async () => {
    let release: ((value: { node_id: string; ts: number; proof: string }) => void) | null = null;
    controlPlaneJson.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve as typeof release;
        }),
    );

    const mod = await import('@/mesh/gateAccessProof');

    const first = mod.buildGateAccessHeaders('finance');
    const second = mod.buildGateAccessHeaders('finance');

    expect(controlPlaneJson).toHaveBeenCalledTimes(1);

    release?.({
      node_id: '!sb_gate',
      ts: 1712345678,
      proof: 'proof-a',
    });

    await expect(first).resolves.toEqual({
      'X-Wormhole-Node-Id': '!sb_gate',
      'X-Wormhole-Gate-Proof': 'proof-a',
      'X-Wormhole-Gate-Ts': '1712345678',
    });
    await expect(second).resolves.toEqual({
      'X-Wormhole-Node-Id': '!sb_gate',
      'X-Wormhole-Gate-Proof': 'proof-a',
      'X-Wormhole-Gate-Ts': '1712345678',
    });
  });

  it('uses stream bootstrap access headers before falling back to the gate proof endpoint', async () => {
    getGateSessionStreamAccessHeaders.mockReturnValue({
      'X-Wormhole-Node-Id': '!sb_stream',
      'X-Wormhole-Gate-Proof': 'proof-stream',
      'X-Wormhole-Gate-Ts': '1712345678',
    });

    const mod = await import('@/mesh/gateAccessProof');

    await expect(mod.buildGateAccessHeaders('finance', { mode: 'session_stream' })).resolves.toEqual({
      'X-Wormhole-Node-Id': '!sb_stream',
      'X-Wormhole-Gate-Proof': 'proof-stream',
      'X-Wormhole-Gate-Ts': '1712345678',
    });
    expect(getGateSessionStreamAccessHeaders).toHaveBeenCalledWith('finance');
    expect(controlPlaneJson).not.toHaveBeenCalled();
  });

  it('reuses a fresh-enough proof longer for held wait requests than for ordinary reads', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T22:40:00.000Z'));
    try {
      const firstTs = Math.floor(Date.now() / 1000);
      const secondTs = Math.floor((Date.now() + 55_000) / 1000);
      controlPlaneJson
        .mockResolvedValueOnce({
          node_id: '!sb_gate',
          ts: firstTs,
          proof: 'proof-a',
        })
        .mockResolvedValueOnce({
          node_id: '!sb_gate',
          ts: secondTs,
          proof: 'proof-b',
        });

      const mod = await import('@/mesh/gateAccessProof');

      await expect(mod.buildGateAccessHeaders('finance')).resolves.toEqual({
        'X-Wormhole-Node-Id': '!sb_gate',
        'X-Wormhole-Gate-Proof': 'proof-a',
        'X-Wormhole-Gate-Ts': String(firstTs),
      });

      vi.advanceTimersByTime(55_000);

      await expect(mod.buildGateAccessHeaders('finance', { mode: 'wait' })).resolves.toEqual({
        'X-Wormhole-Node-Id': '!sb_gate',
        'X-Wormhole-Gate-Proof': 'proof-a',
        'X-Wormhole-Gate-Ts': String(firstTs),
      });
      expect(controlPlaneJson).toHaveBeenCalledTimes(1);

      await expect(mod.buildGateAccessHeaders('finance')).resolves.toEqual({
        'X-Wormhole-Node-Id': '!sb_gate',
        'X-Wormhole-Gate-Proof': 'proof-b',
        'X-Wormhole-Gate-Ts': String(secondTs),
      });
      expect(controlPlaneJson).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('reuses a fresh-enough proof longer for session-stream refreshes than for ordinary reads', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T22:40:00.000Z'));
    try {
      const firstTs = Math.floor(Date.now() / 1000);
      const secondTs = Math.floor((Date.now() + 55_000) / 1000);
      controlPlaneJson
        .mockResolvedValueOnce({
          node_id: '!sb_gate',
          ts: firstTs,
          proof: 'proof-a',
        })
        .mockResolvedValueOnce({
          node_id: '!sb_gate',
          ts: secondTs,
          proof: 'proof-b',
        });

      const mod = await import('@/mesh/gateAccessProof');

      await expect(mod.buildGateAccessHeaders('finance')).resolves.toEqual({
        'X-Wormhole-Node-Id': '!sb_gate',
        'X-Wormhole-Gate-Proof': 'proof-a',
        'X-Wormhole-Gate-Ts': String(firstTs),
      });

      vi.advanceTimersByTime(55_000);

      await expect(mod.buildGateAccessHeaders('finance', { mode: 'session_stream' })).resolves.toEqual({
        'X-Wormhole-Node-Id': '!sb_gate',
        'X-Wormhole-Gate-Proof': 'proof-a',
        'X-Wormhole-Gate-Ts': String(firstTs),
      });
      expect(controlPlaneJson).toHaveBeenCalledTimes(1);

      await expect(mod.buildGateAccessHeaders('finance')).resolves.toEqual({
        'X-Wormhole-Node-Id': '!sb_gate',
        'X-Wormhole-Gate-Proof': 'proof-b',
        'X-Wormhole-Gate-Ts': String(secondTs),
      });
      expect(controlPlaneJson).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
