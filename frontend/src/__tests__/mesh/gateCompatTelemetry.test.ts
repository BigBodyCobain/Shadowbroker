import { beforeEach, describe, expect, it, vi } from 'vitest';

const getNodeIdentity = vi.fn(() => null);
const getWormholeIdentityDescriptor = vi.fn(() => ({ nodeId: '!sb_scope_a' }));

vi.mock('@/mesh/meshIdentity', () => ({
  getNodeIdentity,
  getWormholeIdentityDescriptor,
}));

describe('gateCompatTelemetry', () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    window.sessionStorage.clear();
    getNodeIdentity.mockReset();
    getNodeIdentity.mockReturnValue(null);
    getWormholeIdentityDescriptor.mockReset();
    getWormholeIdentityDescriptor.mockReturnValue({ nodeId: '!sb_scope_a' });
  });

  it('records required and used compat events with reason summaries', async () => {
    const mod = await import('@/mesh/gateCompatTelemetry');

    mod.recordGateCompatTelemetry({
      gateId: 'infonet',
      action: 'decrypt',
      reason: 'browser_gate_state_resync_required:infonet',
      kind: 'required',
      at: 1712500000000,
    });
    mod.recordGateCompatTelemetry({
      gateId: 'infonet',
      action: 'decrypt',
      reason: 'browser_gate_state_resync_required:infonet',
      kind: 'used',
      at: 1712500005000,
    });

    const snapshot = mod.getGateCompatTelemetrySnapshot();

    expect(snapshot.totalRequired).toBe(1);
    expect(snapshot.totalUsed).toBe(1);
    expect(snapshot.reasons[0]).toEqual(
      expect.objectContaining({
        reason: 'browser_gate_state_resync_required:infonet',
        requiredCount: 1,
        usedCount: 1,
        recentGates: ['infonet'],
      }),
    );
  });

  it('keeps telemetry scoped to the current browser profile across reloads', async () => {
    const mod = await import('@/mesh/gateCompatTelemetry');

    mod.recordGateCompatTelemetry({
      gateId: 'infonet',
      action: 'compose',
      reason: 'browser_gate_worker_unavailable',
      kind: 'required',
      at: 1712501000000,
    });

    vi.resetModules();
    getWormholeIdentityDescriptor.mockReturnValue({ nodeId: '!sb_scope_a' });

    const reloaded = await import('@/mesh/gateCompatTelemetry');
    expect(reloaded.getGateCompatTelemetrySnapshot().totalRequired).toBe(1);

    vi.resetModules();
    getWormholeIdentityDescriptor.mockReturnValue({ nodeId: '!sb_scope_b' });

    const otherScope = await import('@/mesh/gateCompatTelemetry');
    expect(otherScope.getGateCompatTelemetrySnapshot().totalRequired).toBe(0);
  });
});
