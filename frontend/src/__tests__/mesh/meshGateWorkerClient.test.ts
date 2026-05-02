import { beforeEach, describe, expect, it, vi } from 'vitest';

const controlPlaneJson = vi.fn();
const probeInlineGateCryptoSupport = vi.fn(async () => ({ supported: true, reason: '' }));
const adoptInlineGateState = vi.fn(async (snapshot) => snapshot);
const composeInlineGateMessage = vi.fn(async () => ({
  gate_id: 'infonet',
  epoch: 7,
  ciphertext: 'inline-ciphertext',
  nonce: 'inline-nonce',
}));
const decryptInlineGateMessages = vi.fn(async () => [
  {
    ok: true,
    gate_id: 'infonet',
    epoch: 7,
    plaintext: 'sealed',
    reply_to: '',
    identity_scope: 'browser_privacy_core',
  },
]);
const forgetInlineGateState = vi.fn(async () => {});

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneJson,
}));

vi.mock('@/mesh/meshGateLocalRuntime', () => ({
  probeInlineGateCryptoSupport,
  adoptInlineGateState,
  composeInlineGateMessage,
  decryptInlineGateMessages,
  forgetInlineGateState,
}));

describe('meshGateWorkerClient inline fallback', () => {
  beforeEach(() => {
    vi.resetModules();
    controlPlaneJson.mockReset();
    probeInlineGateCryptoSupport.mockReset();
    adoptInlineGateState.mockReset();
    composeInlineGateMessage.mockReset();
    decryptInlineGateMessages.mockReset();
    forgetInlineGateState.mockReset();

    probeInlineGateCryptoSupport.mockResolvedValue({ supported: true, reason: '' });
    adoptInlineGateState.mockImplementation(async (snapshot) => snapshot);
    composeInlineGateMessage.mockResolvedValue({
      gate_id: 'infonet',
      epoch: 7,
      ciphertext: 'inline-ciphertext',
      nonce: 'inline-nonce',
    });
    decryptInlineGateMessages.mockResolvedValue([
      {
        ok: true,
        gate_id: 'infonet',
        epoch: 7,
        plaintext: 'sealed',
        reply_to: '',
        identity_scope: 'browser_privacy_core',
      },
    ]);
    forgetInlineGateState.mockResolvedValue(undefined);

    Object.defineProperty(globalThis, 'Worker', {
      value: undefined,
      configurable: true,
      writable: true,
    });
  });

  it('uses the inline runtime when the Worker transport is unavailable', async () => {
    controlPlaneJson
      .mockResolvedValueOnce({
        gate_id: 'infonet',
        epoch: 7,
        rust_state_blob_b64: 'blob',
        members: [],
        active_identity_scope: 'anonymous',
        active_persona_id: '',
        active_node_id: '!sb_local',
      })
      .mockResolvedValueOnce({
        ok: true,
        gate_id: 'infonet',
        sender_id: '!sb_gate',
        public_key: 'pub',
        public_key_algo: 'ed25519',
        protocol_version: 'sb-test',
        sequence: 3,
        signature: 'sig',
        epoch: 7,
        ciphertext: 'inline-ciphertext',
        nonce: 'inline-nonce',
        sender_ref: 'sender-ref',
        format: 'mls1',
      });

    const mod = await import('@/mesh/meshGateWorkerClient');

    await expect(mod.syncBrowserGateState('infonet', { force: true })).resolves.toBe(true);
    await expect(mod.composeBrowserGateMessage('infonet', 'hello')).resolves.toEqual(
      expect.objectContaining({
        ok: true,
        gate_id: 'infonet',
        ciphertext: 'inline-ciphertext',
      }),
    );
    await expect(
      mod.decryptBrowserGateMessages([
        {
          gate_id: 'infonet',
          epoch: 7,
          ciphertext: 'inline-ciphertext',
        },
      ]),
    ).resolves.toEqual({
      ok: true,
      results: [
        expect.objectContaining({
          ok: true,
          gate_id: 'infonet',
          plaintext: 'sealed',
        }),
      ],
    });

    expect(probeInlineGateCryptoSupport).toHaveBeenCalled();
    expect(adoptInlineGateState).toHaveBeenCalled();
    expect(composeInlineGateMessage).toHaveBeenCalledWith('infonet', 'hello', '');
    expect(decryptInlineGateMessages).toHaveBeenCalledWith([
      {
        gate_id: 'infonet',
        epoch: 7,
        ciphertext: 'inline-ciphertext',
      },
    ]);
    expect(mod.getBrowserGateLocalRuntimeStatus()).toEqual(
      expect.objectContaining({
        mode: 'inline',
        health: 'active',
        reason: 'browser_gate_worker_unavailable',
      }),
    );
    expect(mod.describeBrowserGateLocalRuntimeStatus(mod.getBrowserGateLocalRuntimeStatus())).toBe(
      'INLINE local gate runtime active (worker unavailable)',
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      1,
      '/api/wormhole/gate/state/export',
      expect.anything(),
    );
    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      2,
      '/api/wormhole/gate/message/sign-encrypted',
      expect.objectContaining({
        body: JSON.stringify({
          gate_id: 'infonet',
          epoch: 7,
          ciphertext: 'inline-ciphertext',
          nonce: 'inline-nonce',
          format: 'mls1',
          reply_to: '',
          compat_reply_to: false,
          recovery_plaintext: 'hello',
        }),
      }),
    );
  });

  it('falls back to backend sealing when browser signing cannot return a durable gate envelope', async () => {
    controlPlaneJson
      .mockResolvedValueOnce({
        gate_id: 'infonet',
        epoch: 7,
        rust_state_blob_b64: 'blob',
        members: [],
        active_identity_scope: 'anonymous',
        active_persona_id: '',
        active_node_id: '!sb_local',
      })
      .mockResolvedValueOnce({
        ok: true,
        gate_id: 'infonet',
        sender_id: '!sb_gate',
        public_key: 'pub',
        public_key_algo: 'ed25519',
        protocol_version: 'sb-test',
        sequence: 3,
        signature: 'sig',
        epoch: 7,
        ciphertext: 'inline-ciphertext',
        nonce: 'inline-nonce',
        sender_ref: 'sender-ref',
        format: 'mls1',
      })
      .mockResolvedValueOnce({
        ok: true,
        event_id: 'evt-backend-sealed',
      });

    const mod = await import('@/mesh/meshGateWorkerClient');

    await expect(mod.syncBrowserGateState('infonet', { force: true })).resolves.toBe(true);
    await expect(mod.postBrowserGateMessage('infonet', 'hello durable', 'evt-parent-1')).resolves.toEqual({
      ok: true,
      event_id: 'evt-backend-sealed',
    });

    expect(controlPlaneJson).toHaveBeenNthCalledWith(
      3,
      '/api/wormhole/gate/message/post',
      expect.objectContaining({
        body: JSON.stringify({
          gate_id: 'infonet',
          plaintext: 'hello durable',
          reply_to: 'evt-parent-1',
          compat_plaintext: true,
        }),
      }),
    );
  });

  it('marks the selected inline runtime as degraded when a later local compose fails', async () => {
    controlPlaneJson.mockResolvedValueOnce({
      gate_id: 'infonet',
      epoch: 7,
      rust_state_blob_b64: 'blob',
      members: [],
      active_identity_scope: 'anonymous',
      active_persona_id: '',
      active_node_id: '!sb_local',
    });
    composeInlineGateMessage.mockRejectedValueOnce(new Error('worker_gate_wrap_key_missing'));

    const mod = await import('@/mesh/meshGateWorkerClient');

    await expect(mod.syncBrowserGateState('infonet', { force: true })).resolves.toBe(true);
    await expect(mod.composeBrowserGateMessage('infonet', 'hello')).resolves.toBeNull();

    expect(mod.getBrowserGateCryptoFailureReason('infonet', 'compose')).toBe('worker_gate_wrap_key_missing');
    expect(mod.getBrowserGateLocalRuntimeStatus()).toEqual(
      expect.objectContaining({
        mode: 'inline',
        health: 'degraded',
        reason: 'worker_gate_wrap_key_missing',
      }),
    );
    expect(mod.describeBrowserGateLocalRuntimeStatus(mod.getBrowserGateLocalRuntimeStatus())).toBe(
      'INLINE local gate runtime degraded (secure storage unavailable)',
    );
  });

  it('reuses self-authored plaintext when local gate decrypt cannot reopen the just-posted ciphertext', async () => {
    controlPlaneJson
      .mockResolvedValueOnce({
        gate_id: 'infonet',
        epoch: 7,
        rust_state_blob_b64: 'blob',
        members: [],
        active_identity_scope: 'anonymous',
        active_persona_id: '',
        active_node_id: '!sb_local',
      })
      .mockResolvedValueOnce({
        ok: true,
        gate_id: 'infonet',
        sender_id: '!sb_gate',
        public_key: 'pub',
        public_key_algo: 'ed25519',
        protocol_version: 'sb-test',
        sequence: 3,
        signature: 'sig',
        epoch: 7,
        ciphertext: 'inline-ciphertext',
        nonce: 'inline-nonce',
        sender_ref: 'sender-ref',
        format: 'mls1',
      });
    decryptInlineGateMessages.mockResolvedValueOnce([
      {
        ok: false,
        gate_id: 'infonet',
        detail: 'gate_mls_decrypt_failed',
      },
    ]);

    const mod = await import('@/mesh/meshGateWorkerClient');

    await expect(mod.syncBrowserGateState('infonet', { force: true })).resolves.toBe(true);
    await expect(mod.composeBrowserGateMessage('infonet', 'hello self', 'evt-parent-7')).resolves.toEqual(
      expect.objectContaining({
        ok: true,
        gate_id: 'infonet',
        ciphertext: 'inline-ciphertext',
      }),
    );
    await expect(
      mod.decryptBrowserGateMessages([
        {
          gate_id: 'infonet',
          epoch: 7,
          ciphertext: 'inline-ciphertext',
        },
      ]),
    ).resolves.toEqual({
      ok: true,
      results: [
        expect.objectContaining({
          ok: true,
          gate_id: 'infonet',
          epoch: 7,
          plaintext: 'hello self',
          reply_to: 'evt-parent-7',
          identity_scope: 'browser_self_echo',
        }),
      ],
    });

    expect(mod.getBrowserGateLocalRuntimeStatus()).toEqual(
      expect.objectContaining({
        mode: 'inline',
        health: 'active',
      }),
    );
  });
});
