import { beforeEach, describe, expect, it, vi } from 'vitest';

const hasLocalControlBridge = vi.fn(() => false);

vi.mock('@/lib/localControlTransport', () => ({
  hasLocalControlBridge,
}));

describe('gate metadata timing policy', () => {
  beforeEach(() => {
    vi.resetModules();
    hasLocalControlBridge.mockReset();
  });

  it('jittered browser/web polling avoids an exact cadence', async () => {
    hasLocalControlBridge.mockReturnValue(false);
    const mod = await import('@/mesh/gateMetadataTiming');
    const pollDelays = Array.from({ length: 12 }, () => mod.nextGateMessagesPollDelayMs());
    expect(pollDelays.every((delay) => delay >= 24_000 && delay <= 36_000)).toBe(true);
    expect(new Set(pollDelays).size).toBeGreaterThan(1);
    const waitTimeouts = Array.from({ length: 12 }, () => mod.nextGateMessagesWaitTimeoutMs());
    expect(waitTimeouts.every((delay) => delay >= 26_000 && delay <= 38_000)).toBe(true);
    expect(new Set(waitTimeouts).size).toBeGreaterThan(1);
    const rearmDelays = Array.from({ length: 12 }, () => mod.nextGateMessagesWaitRearmDelayMs());
    expect(rearmDelays.every((delay) => delay >= 3_000 && delay <= 4_200)).toBe(true);
    expect(new Set(rearmDelays).size).toBeGreaterThan(1);
    const refreshDelays = Array.from({ length: 12 }, () => mod.nextGateActivityRefreshDelayMs());
    expect(refreshDelays.every((delay) => delay >= 4_500 && delay <= 9_500)).toBe(true);
    expect(new Set(refreshDelays).size).toBeGreaterThan(1);
  });

  it('native desktop keeps the tighter poll/send timing path', async () => {
    hasLocalControlBridge.mockReturnValue(true);
    const mod = await import('@/mesh/gateMetadataTiming');
    expect(mod.shouldJitterGateMetadataTiming()).toBe(false);
    expect(mod.nextGateMessagesPollDelayMs()).toBe(30_000);
    expect(mod.nextGateMessagesWaitTimeoutMs()).toBe(20_000);
    expect(mod.nextGateMessagesWaitRearmDelayMs()).toBe(750);
    expect(mod.nextGateActivityRefreshDelayMs()).toBe(0);
  });

  it('coarsens hidden browser tab gate polling further', async () => {
    hasLocalControlBridge.mockReturnValue(false);
    const originalVisibility = Object.getOwnPropertyDescriptor(document, 'visibilityState');
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'hidden',
    });
    try {
      const mod = await import('@/mesh/gateMetadataTiming');
      const pollDelays = Array.from({ length: 12 }, () => mod.nextGateMessagesPollDelayMs());
      expect(pollDelays.every((delay) => delay >= 48_000 && delay <= 72_000)).toBe(true);
      const waitTimeouts = Array.from({ length: 12 }, () => mod.nextGateMessagesWaitTimeoutMs());
      expect(waitTimeouts.every((delay) => delay >= 60_000 && delay <= 84_000)).toBe(true);
      const rearmDelays = Array.from({ length: 12 }, () => mod.nextGateMessagesWaitRearmDelayMs());
      expect(rearmDelays.every((delay) => delay >= 6_000 && delay <= 12_000)).toBe(true);
      const refreshDelays = Array.from({ length: 12 }, () => mod.nextGateActivityRefreshDelayMs());
      expect(refreshDelays.every((delay) => delay >= 14_000 && delay <= 22_000)).toBe(true);
    } finally {
      if (originalVisibility) {
        Object.defineProperty(document, 'visibilityState', originalVisibility);
      } else {
        delete (document as Document & { visibilityState?: string }).visibilityState;
      }
    }
  });
});
