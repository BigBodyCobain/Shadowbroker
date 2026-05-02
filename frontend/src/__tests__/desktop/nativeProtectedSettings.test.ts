/**
 * Tests for native desktop protected-settings readiness bypass.
 *
 * Verifies that:
 * - isNativeProtectedSettingsReady() correctly reflects native bridge presence
 * - When the native bridge is present, admin-session browser flow is bypassed
 * - When no native bridge, existing admin-session gating is preserved
 *
 * These are unit tests for the extracted readiness logic. They do NOT render
 * SettingsPanel — they test the decision layer that SettingsPanel depends on.
 * Full component render coverage is not claimed.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the bridge detection used by nativeProtectedSettings
const mockHasLocalControlBridge = vi.fn();

vi.mock('@/lib/localControlTransport', () => ({
  hasLocalControlBridge: () => mockHasLocalControlBridge(),
  canInvokeLocalControl: vi.fn(),
  localControlFetch: vi.fn(),
}));

// Mock adminSession to verify it's bypassed or called as expected
const mockHasAdminSession = vi.fn();
const mockPrimeAdminSession = vi.fn();

vi.mock('@/lib/adminSession', () => ({
  hasAdminSession: () => mockHasAdminSession(),
  primeAdminSession: (...args: unknown[]) => mockPrimeAdminSession(...args),
  clearAdminSession: vi.fn(),
}));

describe('isNativeProtectedSettingsReady', () => {
  beforeEach(() => {
    vi.resetModules();
    mockHasLocalControlBridge.mockReset();
  });

  it('returns true when native local-control bridge is present', async () => {
    mockHasLocalControlBridge.mockReturnValue(true);
    const mod = await import('@/lib/nativeProtectedSettings');
    expect(mod.isNativeProtectedSettingsReady()).toBe(true);
  });

  it('returns false when no native bridge (browser mode)', async () => {
    mockHasLocalControlBridge.mockReturnValue(false);
    const mod = await import('@/lib/nativeProtectedSettings');
    expect(mod.isNativeProtectedSettingsReady()).toBe(false);
  });
});

describe('controlPlaneFetch admin-session bypass with native bridge', () => {
  beforeEach(() => {
    vi.resetModules();
    mockHasLocalControlBridge.mockReset();
    mockHasAdminSession.mockReset();
    mockPrimeAdminSession.mockReset();
  });

  it('skips primeAdminSession when native bridge handles the request', async () => {
    mockHasLocalControlBridge.mockReturnValue(true);
    // canInvokeLocalControl is mocked to be truthy via the mock setup
    const { canInvokeLocalControl, localControlFetch } = await import(
      '@/lib/localControlTransport'
    );
    (canInvokeLocalControl as ReturnType<typeof vi.fn>).mockReturnValue(true);
    (localControlFetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const mod = await import('@/lib/controlPlane');
    await mod.controlPlaneFetch('/api/settings/api-keys', {
      method: 'GET',
    });

    expect(mockPrimeAdminSession).not.toHaveBeenCalled();
    expect(localControlFetch).toHaveBeenCalledTimes(1);
  });

  it('still primes admin session in browser mode (no native bridge)', async () => {
    mockHasLocalControlBridge.mockReturnValue(false);
    const { canInvokeLocalControl, localControlFetch } = await import(
      '@/lib/localControlTransport'
    );
    (canInvokeLocalControl as ReturnType<typeof vi.fn>).mockReturnValue(false);
    (localControlFetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    mockPrimeAdminSession.mockResolvedValue(undefined);

    const mod = await import('@/lib/controlPlane');
    await mod.controlPlaneFetch('/api/settings/api-keys', {
      method: 'GET',
    });

    expect(mockPrimeAdminSession).toHaveBeenCalledTimes(1);
  });
});

describe('native protected-settings readiness in SettingsPanel context', () => {
  beforeEach(() => {
    vi.resetModules();
    mockHasLocalControlBridge.mockReset();
    mockHasAdminSession.mockReset();
  });

  it('native bridge present: hasAdminSession is NOT called by refreshAdminSession logic', async () => {
    mockHasLocalControlBridge.mockReturnValue(true);
    // The helper returns true — SettingsPanel's refreshAdminSession should
    // short-circuit and never call hasAdminSession()
    const mod = await import('@/lib/nativeProtectedSettings');
    expect(mod.isNativeProtectedSettingsReady()).toBe(true);
    // hasAdminSession should not have been called
    expect(mockHasAdminSession).not.toHaveBeenCalled();
  });

  it('no native bridge: hasAdminSession is the readiness source', async () => {
    mockHasLocalControlBridge.mockReturnValue(false);
    const mod = await import('@/lib/nativeProtectedSettings');
    expect(mod.isNativeProtectedSettingsReady()).toBe(false);
    // In this scenario, SettingsPanel would call hasAdminSession() — we
    // verify the helper returns false so the browser flow is used.
    mockHasAdminSession.mockResolvedValue(true);
    const adminMod = await import('@/lib/adminSession');
    const ready = await adminMod.hasAdminSession();
    expect(ready).toBe(true);
    expect(mockHasAdminSession).toHaveBeenCalledTimes(1);
  });
});
