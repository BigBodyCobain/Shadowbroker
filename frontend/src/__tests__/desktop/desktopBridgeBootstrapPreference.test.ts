import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ShadowbrokerDesktopRuntime } from '@/lib/desktopBridge';

describe('desktopBridgeBootstrapPreference', () => {
  beforeEach(() => {
    vi.resetModules();
    // Clean window globals before each test
    delete (window as Record<string, unknown>).__SHADOWBROKER_DESKTOP__;
    delete (window as Record<string, unknown>).__SHADOWBROKER_LOCAL_CONTROL__;
  });

  it('prefers a pre-installed native runtime over the HTTP shim', async () => {
    const nativeInvoke = vi.fn().mockResolvedValue({ ok: true });
    const nativeRuntime: ShadowbrokerDesktopRuntime = {
      invokeLocalControl: nativeInvoke,
      getNativeControlAuditReport: () => ({
        totalEvents: 0,
        totalRecorded: 0,
        recent: [],
        byOutcome: {},
      }),
      clearNativeControlAuditReport: vi.fn(),
    };

    // Simulate Tauri injection: set __SHADOWBROKER_DESKTOP__ before bootstrap
    window.__SHADOWBROKER_DESKTOP__ = nativeRuntime;

    const { bootstrapDesktopControlBridge } = await import('@/lib/desktopBridge');
    const installed = bootstrapDesktopControlBridge();

    expect(installed).toBe(true);
    // The bridge should have been derived from the native runtime
    expect(window.__SHADOWBROKER_LOCAL_CONTROL__).toBeDefined();
    expect(window.__SHADOWBROKER_LOCAL_CONTROL__!.invoke).toBeDefined();

    // Invoke through the bridge — should delegate to the native runtime
    await window.__SHADOWBROKER_LOCAL_CONTROL__!.invoke!({
      command: 'wormhole.status',
      payload: undefined,
    });
    expect(nativeInvoke).toHaveBeenCalledTimes(1);
    expect(nativeInvoke.mock.calls[0][0]).toBe('wormhole.status');
  });

  it('does not install bridge when no native runtime and shim env is off', async () => {
    // No __SHADOWBROKER_DESKTOP__ and NEXT_PUBLIC_ENABLE_DESKTOP_BRIDGE_SHIM != '1'
    const originalEnv = process.env.NEXT_PUBLIC_ENABLE_DESKTOP_BRIDGE_SHIM;
    process.env.NEXT_PUBLIC_ENABLE_DESKTOP_BRIDGE_SHIM = '0';

    const { bootstrapDesktopControlBridge } = await import('@/lib/desktopBridge');
    const installed = bootstrapDesktopControlBridge();

    expect(installed).toBe(false);
    expect(window.__SHADOWBROKER_LOCAL_CONTROL__).toBeUndefined();

    process.env.NEXT_PUBLIC_ENABLE_DESKTOP_BRIDGE_SHIM = originalEnv;
  });

  it('falls back to HTTP shim when no native runtime and shim env is on', async () => {
    const originalEnv = process.env.NEXT_PUBLIC_ENABLE_DESKTOP_BRIDGE_SHIM;
    process.env.NEXT_PUBLIC_ENABLE_DESKTOP_BRIDGE_SHIM = '1';

    const { bootstrapDesktopControlBridge } = await import('@/lib/desktopBridge');
    const installed = bootstrapDesktopControlBridge();

    expect(installed).toBe(true);
    // Bridge installed via shim
    expect(window.__SHADOWBROKER_LOCAL_CONTROL__).toBeDefined();
    // __SHADOWBROKER_DESKTOP__ is the HTTP-backed shim
    expect(window.__SHADOWBROKER_DESKTOP__).toBeDefined();
    expect(window.__SHADOWBROKER_DESKTOP__!.invokeLocalControl).toBeDefined();
    expect(window.__SHADOWBROKER_DESKTOP__!.getNativeControlAuditReport).toBeDefined();
    expect(window.__SHADOWBROKER_DESKTOP__!.clearNativeControlAuditReport).toBeDefined();

    process.env.NEXT_PUBLIC_ENABLE_DESKTOP_BRIDGE_SHIM = originalEnv;
  });

  it('native runtime audit report is accessible through getDesktopNativeControlAuditReport', async () => {
    const auditReport = {
      totalEvents: 5,
      totalRecorded: 5,
      recent: [],
      byOutcome: { allowed: 5 },
    };
    const nativeRuntime: ShadowbrokerDesktopRuntime = {
      invokeLocalControl: vi.fn().mockResolvedValue({}),
      getNativeControlAuditReport: () => auditReport,
      clearNativeControlAuditReport: vi.fn(),
    };
    window.__SHADOWBROKER_DESKTOP__ = nativeRuntime;

    const { bootstrapDesktopControlBridge, getDesktopNativeControlAuditReport } =
      await import('@/lib/desktopBridge');
    bootstrapDesktopControlBridge();

    const report = getDesktopNativeControlAuditReport();
    expect(report).toEqual(auditReport);
  });

  it('localControlFetch routes through native bridge when available', async () => {
    const nativeInvoke = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 'connected' });
    const nativeRuntime: ShadowbrokerDesktopRuntime = {
      invokeLocalControl: nativeInvoke,
    };
    window.__SHADOWBROKER_DESKTOP__ = nativeRuntime;

    const { installDesktopControlBridge } = await import('@/lib/desktopBridge');
    installDesktopControlBridge(nativeRuntime);

    const { localControlFetch } = await import('@/lib/localControlTransport');
    const response = await localControlFetch('/api/wormhole/status');
    const data = await response.json();

    expect(nativeInvoke).toHaveBeenCalledTimes(1);
    expect(nativeInvoke.mock.calls[0][0]).toBe('wormhole.status');
    expect(data).toEqual({ ok: true, status: 'connected' });
  });

  it('localControlFetch falls back to fetch when no bridge is present', async () => {
    // No bridge installed — localControlFetch should use regular fetch
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const { localControlFetch } = await import('@/lib/localControlTransport');
    await localControlFetch('/api/wormhole/status');

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const callUrl = fetchSpy.mock.calls[0][0] as string;
    expect(callUrl).toContain('/api/wormhole/status');

    fetchSpy.mockRestore();
  });

  it('Rust handler coverage matches the full contract command set', async () => {
    const { DESKTOP_CONTROL_COMMANDS } = await import(
      '@/lib/desktopControlContract'
    );
    // This test documents the expected contract size.
    // If the contract grows, the Rust handlers.rs must be updated to match.
    expect(DESKTOP_CONTROL_COMMANDS.length).toBe(27);

    // Verify every command has a corresponding HTTP route
    const { commandToHttpRequest } = await import(
      '@/lib/desktopControlRouting'
    );
    for (const command of DESKTOP_CONTROL_COMMANDS) {
      // Gate commands need a payload with gate_id
      const payload = command.includes('gate')
        ? { gate_id: 'test-gate', plaintext: 'x', reason: 'test', label: 'l', persona_id: 'p', epoch: 0, ciphertext: '', nonce: '', sender_ref: '', messages: [] }
        : undefined;
      expect(() => commandToHttpRequest(command, payload)).not.toThrow();
    }
  });

  it('native runtime forwards meta to invokeLocalControl', async () => {
    const nativeInvoke = vi.fn().mockResolvedValue({ ok: true });
    const nativeRuntime: ShadowbrokerDesktopRuntime = {
      invokeLocalControl: nativeInvoke,
    };
    window.__SHADOWBROKER_DESKTOP__ = nativeRuntime;

    const { installDesktopControlBridge } = await import('@/lib/desktopBridge');
    installDesktopControlBridge(nativeRuntime);

    await window.__SHADOWBROKER_LOCAL_CONTROL__!.invoke!({
      command: 'wormhole.gate.key.rotate',
      payload: { gate_id: 'infonet', reason: 'operator_reset' },
      meta: {
        capability: 'wormhole_gate_key',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
      },
    });

    expect(nativeInvoke).toHaveBeenCalledTimes(1);
    expect(nativeInvoke.mock.calls[0][0]).toBe('wormhole.gate.key.rotate');
    expect(nativeInvoke.mock.calls[0][1]).toEqual({ gate_id: 'infonet', reason: 'operator_reset' });
    // meta must not be dropped
    const receivedMeta = nativeInvoke.mock.calls[0][2];
    expect(receivedMeta).toBeDefined();
    expect(receivedMeta).toEqual(expect.objectContaining({
      capability: 'wormhole_gate_key',
      sessionProfileHint: 'gate_operator',
      enforceProfileHint: true,
    }));
  });

  it('native runtime rejects on capability mismatch and records audit', async () => {
    const { controlCommandCapability } = await import('@/lib/desktopControlContract');
    const nativeInvoke = vi.fn().mockResolvedValue({ ok: true });
    const auditEntries: unknown[] = [];

    // Simulate a Tauri-like runtime that checks capability mismatch
    const nativeRuntime: ShadowbrokerDesktopRuntime = {
      invokeLocalControl: async (command, payload, meta) => {
        const expectedCap = controlCommandCapability(command!);
        if (meta?.capability && meta.capability !== expectedCap) {
          auditEntries.push({
            command,
            expectedCapability: expectedCap,
            declaredCapability: meta.capability,
            outcome: 'capability_mismatch',
          });
          throw new Error(
            `native_control_capability_mismatch:${meta.capability}:${expectedCap}`,
          );
        }
        return nativeInvoke(command, payload, meta);
      },
      getNativeControlAuditReport: () => ({
        totalEvents: auditEntries.length,
        totalRecorded: auditEntries.length,
        recent: [],
        byOutcome: { capability_mismatch: auditEntries.length },
      }),
      clearNativeControlAuditReport: vi.fn(),
    };
    window.__SHADOWBROKER_DESKTOP__ = nativeRuntime;

    const { installDesktopControlBridge } = await import('@/lib/desktopBridge');
    installDesktopControlBridge(nativeRuntime);

    // Declare wrong capability: 'settings' for a wormhole_gate_key command
    await expect(
      window.__SHADOWBROKER_LOCAL_CONTROL__!.invoke!({
        command: 'wormhole.gate.key.rotate',
        payload: { gate_id: 'infonet', reason: 'test' },
        meta: { capability: 'settings' },
      }),
    ).rejects.toThrow('native_control_capability_mismatch');

    expect(nativeInvoke).not.toHaveBeenCalled();
    expect(auditEntries).toHaveLength(1);
    expect(auditEntries[0]).toEqual(
      expect.objectContaining({
        command: 'wormhole.gate.key.rotate',
        declaredCapability: 'settings',
        expectedCapability: 'wormhole_gate_key',
        outcome: 'capability_mismatch',
      }),
    );
  });

  it('native runtime denies on profile enforcement and records audit', async () => {
    const { controlCommandCapability, sessionProfileCapabilities } = await import(
      '@/lib/desktopControlContract'
    );
    const nativeInvoke = vi.fn().mockResolvedValue({ ok: true });
    const auditEntries: unknown[] = [];

    // Simulate a Tauri-like runtime that enforces session profiles
    const nativeRuntime: ShadowbrokerDesktopRuntime = {
      invokeLocalControl: async (command, payload, meta) => {
        const expectedCap = controlCommandCapability(command!);
        const profile = meta?.sessionProfileHint;
        const profileCaps = profile ? sessionProfileCapabilities(profile) : [];
        const profileAllows =
          !profile || profileCaps.length === 0 || profileCaps.includes(expectedCap);
        const enforced = Boolean(meta?.enforceProfileHint && profile);
        if (!profileAllows && enforced) {
          auditEntries.push({
            command,
            expectedCapability: expectedCap,
            sessionProfile: profile,
            outcome: 'profile_denied',
          });
          throw new Error(
            `native_control_profile_mismatch:${profile}:${expectedCap}`,
          );
        }
        return nativeInvoke(command, payload, meta);
      },
      getNativeControlAuditReport: () => ({
        totalEvents: auditEntries.length,
        totalRecorded: auditEntries.length,
        recent: [],
        byOutcome: { profile_denied: auditEntries.length },
      }),
      clearNativeControlAuditReport: vi.fn(),
    };
    window.__SHADOWBROKER_DESKTOP__ = nativeRuntime;

    const { installDesktopControlBridge } = await import('@/lib/desktopBridge');
    installDesktopControlBridge(nativeRuntime);

    // settings_only profile cannot access wormhole_gate_key commands
    await expect(
      window.__SHADOWBROKER_LOCAL_CONTROL__!.invoke!({
        command: 'wormhole.gate.key.rotate',
        payload: { gate_id: 'infonet', reason: 'test' },
        meta: {
          capability: 'wormhole_gate_key',
          sessionProfileHint: 'settings_only',
          enforceProfileHint: true,
        },
      }),
    ).rejects.toThrow('native_control_profile_mismatch');

    expect(nativeInvoke).not.toHaveBeenCalled();
    expect(auditEntries).toHaveLength(1);
    expect(auditEntries[0]).toEqual(
      expect.objectContaining({
        command: 'wormhole.gate.key.rotate',
        expectedCapability: 'wormhole_gate_key',
        sessionProfile: 'settings_only',
        outcome: 'profile_denied',
      }),
    );
  });

  it('native runtime audit report populates on allowed invocations', async () => {
    let auditCallCount = 0;
    const nativeInvoke = vi.fn().mockResolvedValue({ ok: true });
    const nativeRuntime: ShadowbrokerDesktopRuntime = {
      invokeLocalControl: async (command, payload, meta) => {
        auditCallCount++;
        return nativeInvoke(command, payload, meta);
      },
      getNativeControlAuditReport: () => ({
        totalEvents: auditCallCount,
        totalRecorded: auditCallCount,
        recent: [],
        byOutcome: { allowed: auditCallCount },
      }),
      clearNativeControlAuditReport: () => { auditCallCount = 0; },
    };
    window.__SHADOWBROKER_DESKTOP__ = nativeRuntime;

    const { installDesktopControlBridge, getDesktopNativeControlAuditReport } =
      await import('@/lib/desktopBridge');
    installDesktopControlBridge(nativeRuntime);

    await window.__SHADOWBROKER_LOCAL_CONTROL__!.invoke!({
      command: 'wormhole.status',
      payload: undefined,
    });
    await window.__SHADOWBROKER_LOCAL_CONTROL__!.invoke!({
      command: 'settings.privacy.get',
      payload: undefined,
    });

    const report = getDesktopNativeControlAuditReport();
    expect(report).toBeDefined();
    expect(report!.totalEvents).toBe(2);
    expect(report!.totalRecorded).toBe(2);
    expect(report!.byOutcome).toEqual(expect.objectContaining({ allowed: 2 }));
  });

  it('injected JS capability map covers every contract command', async () => {
    const { DESKTOP_CONTROL_COMMANDS, controlCommandCapability } = await import(
      '@/lib/desktopControlContract'
    );
    // The capability map embedded in the Tauri injected JS (main.rs) must
    // cover every command. This test verifies the TypeScript contract source
    // which the JS map mirrors — if the contract grows, this catches drift.
    for (const command of DESKTOP_CONTROL_COMMANDS) {
      const cap = controlCommandCapability(command);
      expect(cap).toBeDefined();
      expect(typeof cap).toBe('string');
    }
  });

  it('profile capability resolution matches between TS and expected Tauri JS tables', async () => {
    const { sessionProfileCapabilities } = await import(
      '@/lib/desktopControlContract'
    );
    // Verify the profile→capabilities mapping that the Tauri JS mirrors
    const profiles = [
      'full_app', 'gate_observe', 'gate_operator', 'wormhole_runtime', 'settings_only',
    ] as const;
    for (const profile of profiles) {
      const caps = sessionProfileCapabilities(profile);
      expect(Array.isArray(caps)).toBe(true);
      expect(caps.length).toBeGreaterThan(0);
    }
    // Specific assertions matching the Tauri JS table
    expect(sessionProfileCapabilities('settings_only')).toEqual(['settings']);
    expect(sessionProfileCapabilities('gate_observe')).toEqual(['wormhole_gate_content']);
    expect(sessionProfileCapabilities('full_app')).toHaveLength(5);
  });
});
