import { beforeEach, describe, expect, it, vi } from 'vitest';

const controlPlaneJson = vi.fn();
const controlPlaneFetch = vi.fn();
const getNodeIdentity = vi.fn<
  () => { nodeId: string; publicKey: string; privateKey: string } | null
>(() => null);
const signEvent = vi.fn();
const signMessage = vi.fn();
const signWithStoredKey = vi.fn();
const isSecureModeCached = vi.fn(() => true);
const fetchWormholeSettings = vi.fn(async () => ({ enabled: true }));
const fetchWormholeState = vi.fn(async () => ({ ready: true }));
const connectWormhole = vi.fn(async () => ({ ready: true }));
const joinWormhole = vi.fn(async () => ({ ok: true, runtime: { ready: true } }));
const hasLocalControlBridge = vi.fn(() => false);
const composeBrowserGateMessage = vi.fn(async () => null);
const postBrowserGateMessage = vi.fn(async () => null);
const decryptBrowserGateMessages = vi.fn(async () => null);
const forgetBrowserGateState = vi.fn(async () => {});
const syncBrowserGateState = vi.fn(async () => true);
const getBrowserGateCryptoFailureReason = vi.fn(() => 'browser_gate_worker_unavailable');
const getWormholeIdentityDescriptor = vi.fn(() => null);
const getGateSessionStreamStatus = vi.fn(() => ({
  enabled: false,
  phase: 'idle',
  transport: 'sse',
  sessionId: '',
  subscriptions: [],
  heartbeatS: 0,
  batchMs: 0,
  lastEventType: '',
  lastEventAt: 0,
  detail: '',
}));
const getGateSessionStreamAccessHeaders = vi.fn(() => undefined);
const getGateSessionStreamKeyStatus = vi.fn(() => null);
const invalidateGateSessionStreamGateContext = vi.fn();
const setGateSessionStreamGateContext = vi.fn();

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneFetch,
  controlPlaneJson,
}));

vi.mock('@/lib/localControlTransport', () => ({
  hasLocalControlBridge,
}));

vi.mock('@/mesh/meshGateWorkerClient', () => ({
  composeBrowserGateMessage,
  postBrowserGateMessage,
  decryptBrowserGateMessages,
  forgetBrowserGateState,
  syncBrowserGateState,
  getBrowserGateCryptoFailureReason,
}));

vi.mock('@/mesh/gateSessionStream', () => ({
  getGateSessionStreamAccessHeaders,
  getGateSessionStreamStatus,
  getGateSessionStreamKeyStatus,
  invalidateGateSessionStreamGateContext,
  setGateSessionStreamGateContext,
}));

vi.mock('@/mesh/meshIdentity', () => ({
  cacheWormholeIdentityDescriptor: vi.fn(),
  getNodeIdentity,
  getPublicKeyAlgo: vi.fn(() => 'ed25519'),
  getWormholeIdentityDescriptor,
  isSecureModeCached,
  purgeBrowserSigningMaterial: vi.fn(async () => {}),
  setSecureModeCached: vi.fn(),
  signEvent,
  signMessage,
  signWithStoredKey,
}));

vi.mock('@/mesh/meshProtocol', () => ({
  PROTOCOL_VERSION: 'sb-test',
}));

vi.mock('@/mesh/wormholeClient', () => ({
  connectWormhole,
  fetchWormholeSettings,
  fetchWormholeState,
  joinWormhole,
}));

describe('wormholeIdentityClient strict profile hints', () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    window.sessionStorage.clear();
    controlPlaneJson.mockReset();
    controlPlaneJson.mockResolvedValue({ ok: true });
    controlPlaneFetch.mockReset();
    controlPlaneFetch.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ ok: true }),
    });
    getNodeIdentity.mockReset();
    getNodeIdentity.mockReturnValue(null);
    signEvent.mockReset();
    signMessage.mockReset();
    signWithStoredKey.mockReset();
    isSecureModeCached.mockReset();
    isSecureModeCached.mockReturnValue(true);
    fetchWormholeSettings.mockReset();
    fetchWormholeSettings.mockResolvedValue({ enabled: true });
    fetchWormholeState.mockReset();
    fetchWormholeState.mockResolvedValue({ ready: true });
    connectWormhole.mockReset();
    connectWormhole.mockResolvedValue({ ready: true });
    joinWormhole.mockReset();
    joinWormhole.mockResolvedValue({ ok: true, runtime: { ready: true } });
    hasLocalControlBridge.mockReset();
    hasLocalControlBridge.mockReturnValue(false);
    composeBrowserGateMessage.mockReset();
    composeBrowserGateMessage.mockResolvedValue(null);
    postBrowserGateMessage.mockReset();
    postBrowserGateMessage.mockResolvedValue(null);
    decryptBrowserGateMessages.mockReset();
    decryptBrowserGateMessages.mockResolvedValue(null);
    forgetBrowserGateState.mockReset();
    forgetBrowserGateState.mockResolvedValue(undefined);
    syncBrowserGateState.mockReset();
    syncBrowserGateState.mockResolvedValue(true);
    getBrowserGateCryptoFailureReason.mockReset();
    getBrowserGateCryptoFailureReason.mockReturnValue('browser_gate_worker_unavailable');
    getWormholeIdentityDescriptor.mockReset();
    getWormholeIdentityDescriptor.mockReturnValue(null);
    getGateSessionStreamStatus.mockReset();
    getGateSessionStreamStatus.mockReturnValue({
      enabled: false,
      phase: 'idle',
      transport: 'sse',
      sessionId: '',
      subscriptions: [],
      heartbeatS: 0,
      batchMs: 0,
      lastEventType: '',
      lastEventAt: 0,
      detail: '',
    });
    getGateSessionStreamAccessHeaders.mockReset();
    getGateSessionStreamAccessHeaders.mockReturnValue(undefined);
    getGateSessionStreamKeyStatus.mockReset();
    getGateSessionStreamKeyStatus.mockReturnValue(null);
    invalidateGateSessionStreamGateContext.mockReset();
    setGateSessionStreamGateContext.mockReset();
  });

  it('applies strict gate_operator enforcement to gate persona and compose operations', async () => {
    hasLocalControlBridge.mockReturnValue(true);
    fetchWormholeState.mockResolvedValue({
      ready: true,
      transport_tier: 'private_transitional',
      transport_active: 'private_transitional',
    });
    const mod = await import('@/mesh/wormholeIdentityClient');

    await mod.listWormholeGatePersonas('infonet');
    await mod.createWormholeGatePersona('infonet', 'persona-1');
    await mod.activateWormholeGatePersona('infonet', 'persona-1');
    await mod.clearWormholeGatePersona('infonet');
    await mod.retireWormholeGatePersona('infonet', 'persona-1');
    await mod.composeWormholeGateMessage('infonet', 'hello');
    await mod.postWormholeGateMessage('infonet', 'hello', 'evt-parent-1');

    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/infonet/personas',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_persona',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
      }),
    );
    for (let i = 2; i <= 5; i += 1) {
      expect(controlPlaneJson).toHaveBeenNthCalledWith(
        i,
        expect.any(String),
        expect.objectContaining({
          capabilityIntent: 'wormhole_gate_persona',
          sessionProfileHint: 'gate_operator',
          enforceProfileHint: true,
        }),
      );
    }
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      6,
      '/api/wormhole/gate/message/compose',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_content',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello',
          reply_to: '',
          compat_plaintext: false,
        }),
      }),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      7,
      '/api/wormhole/gate/message/post',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_content',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
        method: 'POST',
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello',
          reply_to: 'evt-parent-1',
          compat_plaintext: false,
        }),
      }),
    );
  });

  it('switches gate compose/post out of plaintext compat when the native bridge is available', async () => {
    hasLocalControlBridge.mockReturnValue(true);
    fetchWormholeState.mockResolvedValue({
      ready: true,
      transport_tier: 'private_transitional',
      transport_active: 'private_transitional',
    });
    const mod = await import('@/mesh/wormholeIdentityClient');

    await mod.composeWormholeGateMessage('infonet', 'hello');
    await mod.postWormholeGateMessage('infonet', 'hello', 'evt-parent-1');

    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/message/compose',
      expect.objectContaining({
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello',
          reply_to: '',
          compat_plaintext: false,
        }),
      }),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      2,
      '/api/wormhole/gate/message/post',
      expect.objectContaining({
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello',
          reply_to: 'evt-parent-1',
          compat_plaintext: false,
        }),
      }),
    );
  });

  it('uses browser-local gate compose but commits posts through the local backend gate sealer', async () => {
    composeBrowserGateMessage.mockResolvedValue({
      ok: true,
      gate_id: 'infonet',
      sender_id: '!sb_gate',
      public_key: 'pub',
      public_key_algo: 'ed25519',
      protocol_version: 'sb-test',
      sequence: 3,
      signature: 'sig',
      epoch: 7,
      ciphertext: 'ct',
      nonce: 'nonce',
      sender_ref: 'sender-ref',
      format: 'mls1',
    });
    postBrowserGateMessage.mockResolvedValue({ ok: true });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.composeWormholeGateMessage('infonet', 'hello')).resolves.toEqual(
      expect.objectContaining({
        ok: true,
        gate_id: 'infonet',
        format: 'mls1',
      }),
    );
    await expect(mod.postWormholeGateMessage('infonet', 'hello', 'evt-parent-1')).resolves.toEqual({
      ok: true,
    });

    expect(composeBrowserGateMessage).toHaveBeenCalledWith('infonet', 'hello', '');
    expect(postBrowserGateMessage).not.toHaveBeenCalled();
    expect(controlPlaneJson).not.toHaveBeenCalledWith(
      '/api/wormhole/gate/message/compose',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenCalledWith(
      '/api/wormhole/gate/message/post',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_content',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
        method: 'POST',
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello',
          reply_to: 'evt-parent-1',
          compat_plaintext: true,
        }),
      }),
    );
  });

  it('falls back to backend gate compose/post when browser signing cannot carry a durable envelope', async () => {
    composeBrowserGateMessage.mockResolvedValue({
      ok: false,
      detail: 'gate_envelope_required',
    });
    postBrowserGateMessage.mockResolvedValue({
      ok: false,
      detail: 'gate_envelope_required',
    });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.composeWormholeGateMessage('infonet', 'hello', 'evt-parent-1')).resolves.toEqual({
      ok: true,
    });
    await expect(mod.postWormholeGateMessage('infonet', 'hello', 'evt-parent-1')).resolves.toEqual({
      ok: true,
    });

    expect(composeBrowserGateMessage).toHaveBeenCalledWith('infonet', 'hello', 'evt-parent-1');
    expect(postBrowserGateMessage).not.toHaveBeenCalled();
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/message/compose',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_content',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
        method: 'POST',
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello',
          reply_to: 'evt-parent-1',
          compat_plaintext: true,
        }),
      }),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      2,
      '/api/wormhole/gate/message/post',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_content',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
        method: 'POST',
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello',
          reply_to: 'evt-parent-1',
          compat_plaintext: true,
        }),
      }),
    );
  });

  it('prefers browser-local gate decrypt over backend compat decrypt when the worker path is available', async () => {
    decryptBrowserGateMessages.mockResolvedValue({
      ok: true,
      results: [
        {
          ok: true,
          gate_id: 'infonet',
          epoch: 7,
          plaintext: 'sealed',
          reply_to: 'evt-parent-1',
          identity_scope: 'browser_privacy_core',
        },
      ],
    });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(
      mod.decryptWormholeGateMessages([
        {
          gate_id: 'infonet',
          epoch: 7,
          ciphertext: 'ct',
          nonce: 'nonce',
          sender_ref: 'sender-ref',
          format: 'mls1',
        },
      ]),
    ).resolves.toEqual({
      ok: true,
      results: [
        {
          ok: true,
          gate_id: 'infonet',
          epoch: 7,
          plaintext: 'sealed',
          reply_to: 'evt-parent-1',
          identity_scope: 'browser_privacy_core',
        },
      ],
    });

    expect(decryptBrowserGateMessages).toHaveBeenCalledWith([
      {
        gate_id: 'infonet',
        epoch: 7,
        ciphertext: 'ct',
      },
    ]);
    expect(controlPlaneJson).not.toHaveBeenCalledWith(
      '/api/wormhole/gate/messages/decrypt',
      expect.anything(),
    );
  });

  it('recovers historical gate messages through recovery envelopes after browser-local decrypt fails', async () => {
    decryptBrowserGateMessages.mockResolvedValue({
      ok: true,
      results: [
        {
          ok: false,
          gate_id: 'infonet',
          epoch: 7,
          detail: 'gate_mls_decrypt_failed',
        },
      ],
    });
    controlPlaneJson.mockResolvedValueOnce({
      ok: true,
      results: [
        {
          ok: true,
          gate_id: 'infonet',
          epoch: 7,
          plaintext: 'history survives re-entry',
          identity_scope: 'gate_envelope',
        },
      ],
    });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(
      mod.decryptWormholeGateMessages([
        {
          gate_id: 'infonet',
          epoch: 7,
          ciphertext: 'ct',
          nonce: 'nonce',
          sender_ref: 'sender-ref',
          format: 'mls1',
          gate_envelope: 'envelope-token',
          envelope_hash: 'hash-1',
        },
      ]),
    ).resolves.toEqual({
      ok: true,
      results: [
        expect.objectContaining({
          ok: true,
          gate_id: 'infonet',
          plaintext: 'history survives re-entry',
          identity_scope: 'gate_envelope',
        }),
      ],
    });

    expect(controlPlaneJson).toHaveBeenCalledWith(
      '/api/wormhole/gate/messages/decrypt',
      expect.objectContaining({
        body: JSON.stringify({
          messages: [
            {
              gate_id: 'infonet',
              epoch: 7,
              ciphertext: 'ct',
              nonce: 'nonce',
              sender_ref: 'sender-ref',
              format: 'mls1',
              gate_envelope: 'envelope-token',
              envelope_hash: 'hash-1',
              recovery_envelope: true,
              compat_decrypt: false,
            },
          ],
        }),
      }),
    );
  });

  it('fails closed when browser-local gate runtime is unavailable', async () => {
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent');

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.composeWormholeGateMessage('infonet', 'hello')).rejects.toThrow(
      'gate_local_runtime_required:browser_gate_worker_unavailable',
    );
    await expect(mod.postWormholeGateMessage('infonet', 'hello', 'evt-parent-1')).resolves.toEqual({
      ok: true,
    });
    await expect(
      mod.decryptWormholeGateMessages([
        {
          gate_id: 'infonet',
          epoch: 7,
          ciphertext: 'ct',
          nonce: 'nonce',
          sender_ref: 'sender-ref',
          format: 'mls1',
        },
      ]),
    ).rejects.toThrow('gate_local_runtime_required:browser_gate_worker_unavailable');
    const gateFallbackEvents = dispatchSpy.mock.calls
      .map(([event]) => event)
      .filter(
        (event): event is CustomEvent =>
          event instanceof CustomEvent &&
          (event.type === 'sb:gate-compat-consent-required' || event.type === 'sb:gate-compat-fallback'),
      );
    expect(gateFallbackEvents).toEqual([]);
    expect(controlPlaneJson).not.toHaveBeenCalledWith(
      '/api/wormhole/gate/message/compose',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenCalledWith(
      '/api/wormhole/gate/message/post',
      expect.objectContaining({
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello',
          reply_to: 'evt-parent-1',
          compat_plaintext: true,
        }),
      }),
    );
    expect(controlPlaneJson).not.toHaveBeenCalledWith(
      '/api/wormhole/gate/messages/decrypt',
      expect.anything(),
    );
  });

  it('does not let stale compat approval unlock ordinary backend gate compose or decrypt', async () => {
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent');

    const mod = await import('@/mesh/wormholeIdentityClient');
    mod.approveGateCompatFallback('infonet');

    await expect(mod.composeWormholeGateMessage('infonet', 'hello')).rejects.toThrow(
      'gate_local_runtime_required:browser_gate_worker_unavailable',
    );
    await expect(mod.postWormholeGateMessage('infonet', 'hello', 'evt-parent-1')).resolves.toEqual({
      ok: true,
    });
    await expect(
      mod.decryptWormholeGateMessages([
        {
          gate_id: 'infonet',
          epoch: 7,
          ciphertext: 'ct',
          nonce: 'nonce',
          sender_ref: 'sender-ref',
          format: 'mls1',
        },
      ]),
    ).rejects.toThrow('gate_local_runtime_required:browser_gate_worker_unavailable');
    const gateFallbackEvents = dispatchSpy.mock.calls
      .map(([event]) => event)
      .filter(
        (event): event is CustomEvent =>
          event instanceof CustomEvent &&
          (event.type === 'sb:gate-compat-consent-required' || event.type === 'sb:gate-compat-fallback'),
      );
    expect(gateFallbackEvents).toEqual([]);
    expect(controlPlaneJson).not.toHaveBeenCalledWith(
      '/api/wormhole/gate/message/compose',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenCalledWith(
      '/api/wormhole/gate/message/post',
      expect.objectContaining({
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello',
          reply_to: 'evt-parent-1',
          compat_plaintext: true,
        }),
      }),
    );
    expect(controlPlaneJson).not.toHaveBeenCalledWith(
      '/api/wormhole/gate/messages/decrypt',
      expect.anything(),
    );
  });

  it('persists gate compat approval across reloads for the current browser profile', async () => {
    const mod = await import('@/mesh/wormholeIdentityClient');
    mod.approveGateCompatFallback('infonet');

    expect(mod.hasGateCompatFallbackApproval('infonet')).toBe(true);

    vi.resetModules();

    const reloaded = await import('@/mesh/wormholeIdentityClient');
    expect(reloaded.hasGateCompatFallbackApproval('infonet')).toBe(true);
  });

  it('keeps explicit recovery decrypt available when browser-local gate runtime is unavailable', async () => {
    controlPlaneJson.mockResolvedValue({
      ok: true,
      gate_id: 'infonet',
      epoch: 7,
      plaintext: 'recovered',
    });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(
      mod.decryptWormholeGateMessage(
        'infonet',
        7,
        'ct',
        'nonce',
        'sender-ref',
        'envelope-token',
        'hash-1',
        true,
      ),
    ).resolves.toEqual(
      expect.objectContaining({
        ok: true,
        plaintext: 'recovered',
      }),
    );

    expect(controlPlaneJson).toHaveBeenCalledWith(
      '/api/wormhole/gate/message/decrypt',
      expect.objectContaining({
        body: JSON.stringify({
          gate_id: 'infonet',
          epoch: 7,
          ciphertext: 'ct',
          nonce: 'nonce',
          sender_ref: 'sender-ref',
          gate_envelope: 'envelope-token',
          envelope_hash: 'hash-1',
          recovery_envelope: true,
          compat_decrypt: false,
        }),
      }),
    );
  });

  it('refreshes browser gate state after gate persona mutations and forgets it on leave', async () => {
    const mod = await import('@/mesh/wormholeIdentityClient');

    controlPlaneJson.mockResolvedValue({ ok: true, identity: { node_id: '!sb_gate' } });

    await mod.enterWormholeGate('infonet');
    await mod.activateWormholeGatePersona('infonet', 'persona-1');
    await mod.rotateWormholeGateKey('infonet');
    await mod.leaveWormholeGate('infonet');

    expect(forgetBrowserGateState).toHaveBeenNthCalledWith(1, 'infonet');
    expect(forgetBrowserGateState).toHaveBeenNthCalledWith(2, 'infonet');
    expect(forgetBrowserGateState).toHaveBeenNthCalledWith(3, 'infonet');
    expect(forgetBrowserGateState).toHaveBeenNthCalledWith(4, 'infonet');
    expect(syncBrowserGateState).toHaveBeenNthCalledWith(1, 'infonet', { force: true });
    expect(syncBrowserGateState).toHaveBeenNthCalledWith(2, 'infonet', { force: true });
    expect(syncBrowserGateState).toHaveBeenNthCalledWith(3, 'infonet', { force: true });
    expect(syncBrowserGateState).toHaveBeenCalledTimes(3);
    expect(invalidateGateSessionStreamGateContext).toHaveBeenCalledWith('infonet');
  });

  it('re-primes session-stream gate bootstrap context after streamed gate mutations', async () => {
    getGateSessionStreamStatus.mockReturnValue({
      enabled: true,
      phase: 'open',
      transport: 'sse',
      sessionId: 'sess-1',
      subscriptions: ['infonet'],
      heartbeatS: 20,
      batchMs: 1500,
      lastEventType: 'hello',
      lastEventAt: 1712345678000,
      detail: '',
    });
    controlPlaneJson
      .mockResolvedValueOnce({
        ok: true,
        identity: { node_id: '!sb_gate' },
      })
      .mockResolvedValueOnce({
        node_id: '!sb_stream',
        ts: 1712345678,
        proof: 'proof-a',
      })
      .mockResolvedValueOnce({
        ok: true,
        gate_id: 'infonet',
        current_epoch: 4,
        has_local_access: true,
        identity_scope: 'anonymous',
      });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.enterWormholeGate('infonet')).resolves.toEqual(
      expect.objectContaining({ ok: true }),
    );

    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/enter',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      2,
      '/api/wormhole/gate/proof',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      3,
      '/api/wormhole/gate/infonet/key',
      expect.anything(),
    );
    expect(setGateSessionStreamGateContext).toHaveBeenCalledWith('infonet', {
      accessHeaders: {
        'X-Wormhole-Node-Id': '!sb_stream',
        'X-Wormhole-Gate-Proof': 'proof-a',
        'X-Wormhole-Gate-Ts': '1712345678',
      },
      keyStatus: expect.objectContaining({
        gate_id: 'infonet',
        current_epoch: 4,
        has_local_access: true,
      }),
    });
  });

  it('reuses returned key status when re-priming session-stream gate context after rekey', async () => {
    getGateSessionStreamStatus.mockReturnValue({
      enabled: true,
      phase: 'open',
      transport: 'sse',
      sessionId: 'sess-1',
      subscriptions: ['infonet'],
      heartbeatS: 20,
      batchMs: 1500,
      lastEventType: 'hello',
      lastEventAt: 1712345678000,
      detail: '',
    });
    controlPlaneJson
      .mockResolvedValueOnce({
        ok: true,
        gate_id: 'infonet',
        current_epoch: 8,
        has_local_access: true,
        rotation_reason: 'manual_rotate',
      })
      .mockResolvedValueOnce({
        node_id: '!sb_stream',
        ts: 1712345688,
        proof: 'proof-b',
      });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.rotateWormholeGateKey('infonet')).resolves.toEqual(
      expect.objectContaining({ ok: true, current_epoch: 8 }),
    );

    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/key/rotate',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      2,
      '/api/wormhole/gate/proof',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenCalledTimes(2);
    expect(setGateSessionStreamGateContext).toHaveBeenCalledWith('infonet', {
      accessHeaders: {
        'X-Wormhole-Node-Id': '!sb_stream',
        'X-Wormhole-Gate-Proof': 'proof-b',
        'X-Wormhole-Gate-Ts': '1712345688',
      },
      keyStatus: expect.objectContaining({
        gate_id: 'infonet',
        current_epoch: 8,
        has_local_access: true,
      }),
    });
  });

  it('keeps the next session-stream proof and key refresh off the control plane after mutation re-prime', async () => {
    getGateSessionStreamStatus.mockReturnValue({
      enabled: true,
      phase: 'open',
      transport: 'sse',
      sessionId: 'sess-1',
      subscriptions: ['infonet'],
      heartbeatS: 20,
      batchMs: 1500,
      lastEventType: 'hello',
      lastEventAt: 1712345678000,
      detail: '',
    });
    controlPlaneJson
      .mockResolvedValueOnce({
        ok: true,
        identity: { node_id: '!sb_gate' },
      })
      .mockResolvedValueOnce({
        node_id: '!sb_stream',
        ts: 1712345678,
        proof: 'proof-a',
      })
      .mockResolvedValueOnce({
        ok: true,
        gate_id: 'infonet',
        current_epoch: 4,
        has_local_access: true,
        identity_scope: 'anonymous',
      });

    const mod = await import('@/mesh/wormholeIdentityClient');
    const accessMod = await import('@/mesh/gateAccessProof');

    await expect(mod.enterWormholeGate('infonet')).resolves.toEqual(
      expect.objectContaining({ ok: true }),
    );

    const latestStreamContext = setGateSessionStreamGateContext.mock.calls.at(-1)?.[1] as
      | {
          accessHeaders?: Record<string, string>;
          keyStatus?: Record<string, unknown>;
        }
      | undefined;
    getGateSessionStreamAccessHeaders.mockReturnValue(latestStreamContext?.accessHeaders);
    getGateSessionStreamKeyStatus.mockReturnValue(latestStreamContext?.keyStatus ?? null);

    accessMod.invalidateGateAccessHeaders('infonet');
    mod.invalidateWormholeGateKeyStatus('infonet');
    controlPlaneJson.mockClear();

    await expect(
      accessMod.buildGateAccessHeaders('infonet', { mode: 'session_stream' }),
    ).resolves.toEqual({
      'X-Wormhole-Node-Id': '!sb_stream',
      'X-Wormhole-Gate-Proof': 'proof-a',
      'X-Wormhole-Gate-Ts': '1712345678',
    });
    await expect(
      mod.fetchWormholeGateKeyStatus('infonet', { mode: 'session_stream' }),
    ).resolves.toEqual(
      expect.objectContaining({
        gate_id: 'infonet',
        current_epoch: 4,
        has_local_access: true,
      }),
    );

    expect(controlPlaneJson).not.toHaveBeenCalled();
  });

  it('auto-connects Wormhole before entering a gate when the lane is configured but not ready yet', async () => {
    fetchWormholeState
      .mockResolvedValueOnce({ ready: false })
      .mockResolvedValueOnce({ ready: true });
    fetchWormholeSettings.mockResolvedValueOnce({ enabled: true });
    connectWormhole.mockResolvedValueOnce({ ready: false });
    controlPlaneJson
      .mockResolvedValueOnce({
        ok: true,
        identity: { node_id: '!sb_gate' },
      })
      .mockResolvedValueOnce({
        ok: true,
        gate_id: 'infonet',
        current_epoch: 4,
        has_local_access: true,
      });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.enterWormholeGate('infonet')).resolves.toEqual(
      expect.objectContaining({ ok: true }),
    );

    expect(fetchWormholeState).toHaveBeenCalledWith(true);
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/enter',
      expect.anything(),
    );
  });

  it('joins Wormhole before entering a gate when the obfuscated lane is not configured yet', async () => {
    fetchWormholeState.mockResolvedValueOnce({ ready: false, configured: false });
    fetchWormholeSettings.mockResolvedValueOnce({ enabled: false });
    joinWormhole.mockResolvedValueOnce({
      ok: true,
      runtime: { ready: true },
    });
    controlPlaneJson
      .mockResolvedValueOnce({
        ok: true,
        identity: { node_id: '!sb_gate' },
      })
      .mockResolvedValueOnce({
        ok: true,
        gate_id: 'infonet',
        current_epoch: 4,
        has_local_access: true,
      });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.enterWormholeGate('infonet')).resolves.toEqual(
      expect.objectContaining({ ok: true }),
    );
  });

  it('coarsens browser gate key status fetches through a short cache window', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T22:00:00.000Z'));
    try {
      controlPlaneJson.mockResolvedValue({
        ok: true,
        gate_id: 'infonet',
        current_epoch: 7,
        has_local_access: true,
      });

      const mod = await import('@/mesh/wormholeIdentityClient');

      await expect(mod.fetchWormholeGateKeyStatus('infonet')).resolves.toEqual(
        expect.objectContaining({
          gate_id: 'infonet',
          current_epoch: 7,
        }),
      );
      await expect(mod.fetchWormholeGateKeyStatus('infonet')).resolves.toEqual(
        expect.objectContaining({
          gate_id: 'infonet',
          current_epoch: 7,
        }),
      );

      expect(controlPlaneJson).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(12_001);

      await expect(mod.fetchWormholeGateKeyStatus('infonet')).resolves.toEqual(
        expect.objectContaining({
          gate_id: 'infonet',
          current_epoch: 7,
        }),
      );

      expect(controlPlaneJson).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('coalesces concurrent gate key status reads for the same gate', async () => {
    let release:
      | ((value: {
          ok: true;
          gate_id: string;
          current_epoch: number;
          has_local_access: boolean;
        }) => void)
      | null = null;
    controlPlaneJson.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve as typeof release;
        }),
    );

    const mod = await import('@/mesh/wormholeIdentityClient');

    const first = mod.fetchWormholeGateKeyStatus('infonet');
    const second = mod.fetchWormholeGateKeyStatus('infonet', { mode: 'active_room' });

    expect(controlPlaneJson).toHaveBeenCalledTimes(1);

    release?.({
      ok: true,
      gate_id: 'infonet',
      current_epoch: 7,
      has_local_access: true,
    });

    await expect(first).resolves.toEqual(
      expect.objectContaining({
        gate_id: 'infonet',
        current_epoch: 7,
      }),
    );
    await expect(second).resolves.toEqual(
      expect.objectContaining({
        gate_id: 'infonet',
        current_epoch: 7,
      }),
    );
  });

  it('reuses active-room gate key status slightly longer than ordinary reads when local access is ready', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T22:00:00.000Z'));
    try {
      controlPlaneJson
        .mockResolvedValueOnce({
          ok: true,
          gate_id: 'infonet',
          current_epoch: 7,
          has_local_access: true,
        })
        .mockResolvedValueOnce({
          ok: true,
          gate_id: 'infonet',
          current_epoch: 8,
          has_local_access: true,
        });

      const mod = await import('@/mesh/wormholeIdentityClient');

      await expect(mod.fetchWormholeGateKeyStatus('infonet')).resolves.toEqual(
        expect.objectContaining({
          current_epoch: 7,
          has_local_access: true,
        }),
      );

      vi.advanceTimersByTime(18_000);

      await expect(mod.fetchWormholeGateKeyStatus('infonet', { mode: 'active_room' })).resolves.toEqual(
        expect.objectContaining({
          current_epoch: 7,
          has_local_access: true,
        }),
      );
      expect(controlPlaneJson).toHaveBeenCalledTimes(1);

      await expect(mod.fetchWormholeGateKeyStatus('infonet')).resolves.toEqual(
        expect.objectContaining({
          current_epoch: 8,
          has_local_access: true,
        }),
      );
      expect(controlPlaneJson).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('reuses session-stream gate key status longer than active-room reads when local access is ready', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-05T22:00:00.000Z'));
    try {
      controlPlaneJson
        .mockResolvedValueOnce({
          ok: true,
          gate_id: 'infonet',
          current_epoch: 7,
          has_local_access: true,
        })
        .mockResolvedValueOnce({
          ok: true,
          gate_id: 'infonet',
          current_epoch: 8,
          has_local_access: true,
        });

      const mod = await import('@/mesh/wormholeIdentityClient');

      await expect(mod.fetchWormholeGateKeyStatus('infonet')).resolves.toEqual(
        expect.objectContaining({
          current_epoch: 7,
          has_local_access: true,
        }),
      );

      vi.advanceTimersByTime(30_000);

      await expect(mod.fetchWormholeGateKeyStatus('infonet', { mode: 'session_stream' })).resolves.toEqual(
        expect.objectContaining({
          current_epoch: 7,
          has_local_access: true,
        }),
      );
      expect(controlPlaneJson).toHaveBeenCalledTimes(1);

      await expect(mod.fetchWormholeGateKeyStatus('infonet', { mode: 'active_room' })).resolves.toEqual(
        expect.objectContaining({
          current_epoch: 8,
          has_local_access: true,
        }),
      );
      expect(controlPlaneJson).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('uses session-stream bootstrap key status before falling back to the control plane', async () => {
    getGateSessionStreamKeyStatus.mockReturnValue({
      ok: true,
      gate_id: 'infonet',
      current_epoch: 9,
      has_local_access: true,
      identity_scope: 'anonymous',
    });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.fetchWormholeGateKeyStatus('infonet', { mode: 'session_stream' })).resolves.toEqual(
      expect.objectContaining({
        gate_id: 'infonet',
        current_epoch: 9,
        has_local_access: true,
      }),
    );

    expect(getGateSessionStreamKeyStatus).toHaveBeenCalledWith('infonet');
    expect(controlPlaneJson).not.toHaveBeenCalled();
  });

  it('invalidates cached gate key status after gate mutations', async () => {
    controlPlaneJson
      .mockResolvedValueOnce({
        ok: true,
        gate_id: 'infonet',
        current_epoch: 1,
        has_local_access: false,
      })
      .mockResolvedValueOnce({
        ok: true,
        identity: { node_id: '!sb_gate' },
      })
      .mockResolvedValueOnce({
        ok: true,
        gate_id: 'infonet',
        current_epoch: 2,
        has_local_access: true,
      });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.fetchWormholeGateKeyStatus('infonet')).resolves.toEqual(
      expect.objectContaining({
        current_epoch: 1,
        has_local_access: false,
      }),
    );
    await expect(mod.enterWormholeGate('infonet')).resolves.toEqual(
      expect.objectContaining({ ok: true }),
    );
    await expect(mod.fetchWormholeGateKeyStatus('infonet')).resolves.toEqual(
      expect.objectContaining({
        current_epoch: 2,
        has_local_access: true,
      }),
    );

    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/infonet/key',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_key',
      }),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      2,
      '/api/wormhole/gate/enter',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      3,
      '/api/wormhole/gate/infonet/key',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_key',
      }),
    );
  });

  it('invalidates cached gate access proof after gate mutations', async () => {
    controlPlaneJson
      .mockResolvedValueOnce({
        node_id: '!sb_gate',
        ts: 1712345678,
        proof: 'proof-a',
      })
      .mockResolvedValueOnce({
        ok: true,
        identity: { node_id: '!sb_gate' },
      })
      .mockResolvedValueOnce({
        node_id: '!sb_gate',
        ts: 1712345688,
        proof: 'proof-b',
      });

    const mod = await import('@/mesh/wormholeIdentityClient');
    const accessMod = await import('@/mesh/gateAccessProof');

    await expect(accessMod.buildGateAccessHeaders('infonet')).resolves.toEqual({
      'X-Wormhole-Node-Id': '!sb_gate',
      'X-Wormhole-Gate-Proof': 'proof-a',
      'X-Wormhole-Gate-Ts': '1712345678',
    });
    await expect(mod.enterWormholeGate('infonet')).resolves.toEqual(
      expect.objectContaining({ ok: true }),
    );
    await expect(accessMod.buildGateAccessHeaders('infonet')).resolves.toEqual({
      'X-Wormhole-Node-Id': '!sb_gate',
      'X-Wormhole-Gate-Proof': 'proof-b',
      'X-Wormhole-Gate-Ts': '1712345688',
    });

    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/proof',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      2,
      '/api/wormhole/gate/enter',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      3,
      '/api/wormhole/gate/proof',
      expect.anything(),
    );
  });

  it('browser raw signing fails closed instead of falling back to legacy jwk signing', async () => {
    fetchWormholeSettings.mockResolvedValue({ enabled: false });
    fetchWormholeState.mockResolvedValue({ ready: false });
    getNodeIdentity.mockReturnValue({
      nodeId: '!sb_browser',
      publicKey: 'browser-pub',
      privateKey: '',
    });
    signWithStoredKey.mockRejectedValue(new Error('no key'));

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.signRawMeshMessage('payload')).rejects.toThrow(
      'browser_signing_key_unavailable',
    );
    expect(signWithStoredKey).toHaveBeenCalledWith('payload');
    expect(signMessage).not.toHaveBeenCalled();
  });

  it('keeps the cached secure boundary when wormhole settings fetch fails', async () => {
    fetchWormholeSettings.mockRejectedValue(new Error('network down'));
    isSecureModeCached.mockReturnValue(true);

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.isWormholeSecureRequired()).resolves.toBe(true);
  });

  it('exports and imports DM invites through the wormhole control plane endpoints', async () => {
    const mod = await import('@/mesh/wormholeIdentityClient');

    controlPlaneJson.mockResolvedValueOnce({
      ok: true,
      peer_id: '!sb_invite_a',
      trust_fingerprint: 'abc123',
      invite: { event_type: 'dm_invite' },
    });
    controlPlaneFetch.mockResolvedValueOnce({
      ok: true,
      json: vi.fn().mockResolvedValue({
        ok: true,
        peer_id: '!sb_invite_b',
        trust_fingerprint: 'def456',
        trust_level: 'invite_pinned',
        contact: {},
      }),
    });

    await expect(mod.exportWormholeDmInvite()).resolves.toEqual(
      expect.objectContaining({
        peer_id: '!sb_invite_a',
        trust_fingerprint: 'abc123',
      }),
    );
    await expect(mod.importWormholeDmInvite({ event_type: 'dm_invite' }, 'field contact')).resolves.toEqual(
      expect.objectContaining({
        peer_id: '!sb_invite_b',
        trust_level: 'invite_pinned',
      }),
    );

    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/dm/invite',
      expect.objectContaining({
        requireAdminSession: false,
      }),
    );
    expect(controlPlaneFetch).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/dm/invite/import',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          invite: { event_type: 'dm_invite' },
          alias: 'field contact',
        }),
      }),
    );
  });

  it('fetches DM root health through the wormhole control plane endpoint', async () => {
    const mod = await import('@/mesh/wormholeIdentityClient');

    controlPlaneJson.mockResolvedValueOnce({
      ok: true,
      state: 'current_external',
      health_state: 'ok',
      monitoring: { state: 'ok' },
      runbook: { urgency: 'none', next_action: '', actions: [] },
      alerts: [],
      witness: { state: 'current', health_state: 'ok' },
      transparency: { state: 'current', health_state: 'ok' },
    });

    await expect(mod.fetchWormholeDmRootHealth()).resolves.toEqual(
      expect.objectContaining({
        state: 'current_external',
        monitoring: expect.objectContaining({ state: 'ok' }),
      }),
    );

    expect(controlPlaneJson).toHaveBeenCalledWith('/api/wormhole/dm/root-health');
  });

  it('prepares the interactive lane through the configured wormhole runtime and bootstraps identity state', async () => {
    fetchWormholeState.mockResolvedValueOnce({ ready: false, configured: true });
    fetchWormholeSettings.mockResolvedValueOnce({ enabled: true });
    connectWormhole.mockResolvedValueOnce({
      ready: true,
      configured: true,
      transport_tier: 'private_transitional',
      transport_active: 'private_transitional',
    });
    controlPlaneJson.mockResolvedValueOnce({
      node_id: '!sb_wormhole',
      public_key: 'wormhole-pub',
      public_key_algo: 'ed25519',
    });

    const mod = await import('@/mesh/wormholeIdentityClient');
    const prepared = await mod.prepareWormholeInteractiveLane({ bootstrapIdentity: true });

    expect(connectWormhole).toHaveBeenCalledTimes(1);
    expect(joinWormhole).not.toHaveBeenCalled();
    expect(prepared).toEqual(
      expect.objectContaining({
        ready: true,
        settingsEnabled: true,
        transportTier: 'private_transitional',
        identity: expect.objectContaining({
          node_id: '!sb_wormhole',
          public_key: 'wormhole-pub',
        }),
      }),
    );
  });

  it('warms the obfuscated lane to the posting tier and retries gate post once on a transport race', async () => {
    hasLocalControlBridge.mockReturnValue(true);
    fetchWormholeState
      .mockResolvedValueOnce({ ready: false, configured: true })
      .mockResolvedValueOnce({
        ready: true,
        configured: true,
        transport_tier: 'private_transitional',
        transport_active: 'private_transitional',
      });
    fetchWormholeSettings.mockResolvedValueOnce({ enabled: true });
    connectWormhole.mockResolvedValueOnce({
      ready: true,
      configured: true,
      transport_tier: 'private_transitional',
      transport_active: 'private_transitional',
    });
    controlPlaneJson
      .mockRejectedValueOnce(new Error('transport tier insufficient'))
      .mockResolvedValueOnce({ ok: true });

    const mod = await import('@/mesh/wormholeIdentityClient');

    await expect(mod.postWormholeGateMessage('infonet', 'hello', 'evt-parent-1')).resolves.toEqual({
      ok: true,
    });

    expect(connectWormhole).toHaveBeenCalledTimes(1);
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/message/post',
      expect.objectContaining({
        capabilityIntent: 'wormhole_gate_content',
        sessionProfileHint: 'gate_operator',
        enforceProfileHint: true,
      }),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      2,
      '/api/wormhole/gate/message/post',
      expect.objectContaining({
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello',
          reply_to: 'evt-parent-1',
          compat_plaintext: false,
        }),
      }),
    );
  });
});
