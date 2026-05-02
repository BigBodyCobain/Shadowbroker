import '@testing-library/jest-dom/vitest';

import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  controlPlaneJson: vi.fn(),
  approveGateCompatFallback: vi.fn(),
  decryptWormholeGateMessages: vi.fn(),
  fetchWormholeGateKeyStatus: vi.fn(),
  hasGateCompatFallbackApproval: vi.fn(() => false),
  postWormholeGateMessage: vi.fn(),
  prepareWormholeInteractiveLane: vi.fn(async () => ({
    ready: true,
    settingsEnabled: true,
    transportTier: 'private_transitional',
    identity: null,
  })),
  revokeGateCompatFallback: vi.fn(),
  syncBrowserWormholeGateState: vi.fn(async () => true),
  getGateSessionStreamStatus: vi.fn(() => ({
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
  })),
  retainGateSessionStreamGate: vi.fn(() => vi.fn()),
  subscribeGateSessionStreamEvents: vi.fn(() => vi.fn()),
  subscribeGateSessionStreamStatus: vi.fn((listener: (status: unknown) => void) => {
    listener(mocks.getGateSessionStreamStatus());
    return vi.fn();
  }),
  getGateSessionStreamAccessHeaders: vi.fn(() => undefined),
  getGateSessionStreamKeyStatus: vi.fn(() => null),
  invalidateGateSessionStreamGateContext: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  API_BASE: 'http://test.local',
}));

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneJson: mocks.controlPlaneJson,
}));

vi.mock('@/mesh/meshIdentity', () => ({
  nextSequence: vi.fn(() => 1),
}));

vi.mock('@/mesh/wormholeIdentityClient', () => ({
  approveGateCompatFallback: mocks.approveGateCompatFallback,
  decryptWormholeGateMessages: mocks.decryptWormholeGateMessages,
  fetchWormholeGateKeyStatus: mocks.fetchWormholeGateKeyStatus,
  hasGateCompatFallbackApproval: mocks.hasGateCompatFallbackApproval,
  postWormholeGateMessage: mocks.postWormholeGateMessage,
  prepareWormholeInteractiveLane: mocks.prepareWormholeInteractiveLane,
  revokeGateCompatFallback: mocks.revokeGateCompatFallback,
  signMeshEvent: vi.fn(),
  syncBrowserWormholeGateState: mocks.syncBrowserWormholeGateState,
}));

vi.mock('@/mesh/gateEnvelope', () => ({
  gateEnvelopeDisplayText: vi.fn(() => 'sealed'),
  gateEnvelopeState: vi.fn(() => 'sealed'),
  isEncryptedGateEnvelope: vi.fn((message: { ciphertext?: string }) => Boolean(message?.ciphertext)),
}));

vi.mock('@/mesh/meshSchema', () => ({
  validateEventPayload: vi.fn(() => ({ ok: true })),
}));

vi.mock('@/hooks/useGateSSE', () => ({
  useGateSSE: vi.fn(),
}));

vi.mock('@/mesh/gateSessionStream', () => ({
  getGateSessionStreamAccessHeaders: mocks.getGateSessionStreamAccessHeaders,
  getGateSessionStreamKeyStatus: mocks.getGateSessionStreamKeyStatus,
  getGateSessionStreamStatus: mocks.getGateSessionStreamStatus,
  invalidateGateSessionStreamGateContext: mocks.invalidateGateSessionStreamGateContext,
  retainGateSessionStreamGate: mocks.retainGateSessionStreamGate,
  subscribeGateSessionStreamEvents: mocks.subscribeGateSessionStreamEvents,
  subscribeGateSessionStreamStatus: mocks.subscribeGateSessionStreamStatus,
}));

describe('GateView compat-decrypt UX', () => {
  let streamStatusListeners: Array<(status: unknown) => void> = [];

  beforeEach(() => {
    streamStatusListeners = [];
    mocks.controlPlaneJson.mockReset();
    mocks.approveGateCompatFallback.mockReset();
    mocks.decryptWormholeGateMessages.mockReset();
    mocks.fetchWormholeGateKeyStatus.mockReset();
    mocks.hasGateCompatFallbackApproval.mockReset();
    mocks.hasGateCompatFallbackApproval.mockReturnValue(false);
    mocks.postWormholeGateMessage.mockReset();
    mocks.prepareWormholeInteractiveLane.mockReset();
    mocks.prepareWormholeInteractiveLane.mockResolvedValue({
      ready: true,
      settingsEnabled: true,
      transportTier: 'private_transitional',
      identity: null,
    });
    mocks.revokeGateCompatFallback.mockReset();
    mocks.syncBrowserWormholeGateState.mockReset();
    mocks.getGateSessionStreamStatus.mockReset();
    mocks.retainGateSessionStreamGate.mockReset();
    mocks.subscribeGateSessionStreamEvents.mockReset();
    mocks.subscribeGateSessionStreamStatus.mockReset();
    mocks.getGateSessionStreamAccessHeaders.mockReset();
    mocks.getGateSessionStreamAccessHeaders.mockReturnValue(undefined);
    mocks.getGateSessionStreamKeyStatus.mockReset();
    mocks.getGateSessionStreamKeyStatus.mockReturnValue(null);
    mocks.invalidateGateSessionStreamGateContext.mockReset();
    mocks.syncBrowserWormholeGateState.mockResolvedValue(true);
    mocks.getGateSessionStreamStatus.mockReturnValue({
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
    mocks.retainGateSessionStreamGate.mockReturnValue(vi.fn());
    mocks.subscribeGateSessionStreamEvents.mockReturnValue(vi.fn());
    mocks.subscribeGateSessionStreamStatus.mockImplementation((listener: (status: unknown) => void) => {
      streamStatusListeners.push(listener);
      listener(mocks.getGateSessionStreamStatus());
      return vi.fn();
    });

    mocks.fetchWormholeGateKeyStatus.mockResolvedValue({
      ok: true,
      has_local_access: true,
      identity_scope: 'gate',
    });
    mocks.controlPlaneJson.mockResolvedValue({
      node_id: '!sb_local',
      proof: 'proof-token',
      ts: 1712345678,
    });
    mocks.decryptWormholeGateMessages.mockResolvedValue({
      ok: true,
      results: [
        {
          ok: true,
          gate_id: 'infonet',
          epoch: 7,
          plaintext: 'sealed',
          identity_scope: 'browser_privacy_core',
        },
      ],
    });

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url.includes('/api/mesh/infonet/messages')) {
          return {
            ok: true,
            json: async () => ({
              messages: [
                {
                  event_id: 'evt-1',
                  timestamp: 1712345678,
                  payload: {
                    gate: 'infonet',
                    ciphertext: 'ciphertext-1',
                    nonce: 'nonce-1',
                    sender_ref: 'sender-ref-1',
                    format: 'mls1',
                    gate_envelope: 'gate-envelope-1',
                    envelope_hash: 'hash-1',
                  },
                },
              ],
            }),
          };
        }
        if (url.includes('/api/mesh/reputation/batch')) {
          return {
            ok: true,
            json: async () => ({ reputations: {} }),
          };
        }
        throw new Error(`unexpected fetch url: ${url}`);
      }),
    );

    Object.defineProperty(Element.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  const emitStreamStatus = (status: {
    enabled: boolean;
    phase: 'idle' | 'connecting' | 'open' | 'closed' | 'disabled' | 'error';
    transport: 'sse';
    sessionId: string;
    subscriptions: string[];
    heartbeatS: number;
    batchMs: number;
    lastEventType: string;
    lastEventAt: number;
    detail: string;
  }) => {
    mocks.getGateSessionStreamStatus.mockReturnValue(status);
    streamStatusListeners.forEach((listener) => listener(status));
  };

  it('shows a clear room error when browser-local gate runtime is required', async () => {
    mocks.decryptWormholeGateMessages.mockRejectedValue(
      new Error('gate_local_runtime_required:browser_gate_state_resync_required:infonet'),
    );

    const { default: GateView } = await import('@/components/InfonetTerminal/GateView');

    render(
      <GateView
        gateName="infonet"
        persona="!sb_local"
        onBack={() => {}}
        onNavigateGate={() => {}}
        availableGates={['infonet']}
      />,
    );

    expect(
      await screen.findByText(
        'Local infonet state needs a resync on this device. Use native desktop or resync local gate state.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'ENABLE FOR ROOM' })).not.toBeInTheDocument();
    expect(mocks.syncBrowserWormholeGateState).toHaveBeenCalledWith('infonet');
    expect(mocks.decryptWormholeGateMessages).toHaveBeenCalledWith([
      expect.objectContaining({
        gate_id: 'infonet',
        ciphertext: 'ciphertext-1',
        envelope_hash: 'hash-1',
      }),
    ]);
  });

  it('keeps recovery-only decrypt failures out of the red room-error path', async () => {
    mocks.decryptWormholeGateMessages.mockResolvedValue({
      ok: true,
      results: [
        {
          ok: false,
          detail: 'gate_backend_decrypt_recovery_only',
          gate_id: 'infonet',
          compat_requested: true,
          compat_effective: false,
        },
      ],
    });

    const { default: GateView } = await import('@/components/InfonetTerminal/GateView');

    render(
      <GateView
        gateName="infonet"
        persona="!sb_local"
        onBack={() => {}}
        onNavigateGate={() => {}}
        availableGates={['infonet']}
      />,
    );

    await waitFor(() => expect(mocks.decryptWormholeGateMessages).toHaveBeenCalled());
    expect(screen.queryByText('COMPAT MODE')).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        'Service-side gate decrypt is disabled on this runtime. Use native desktop or an explicit recovery path.',
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByText('sealed')).toBeInTheDocument();
  });

  it('shows a friendly room message instead of a raw transport-tier gate post failure', async () => {
    mocks.postWormholeGateMessage.mockRejectedValue(new Error('transport tier insufficient'));

    const { default: GateView } = await import('@/components/InfonetTerminal/GateView');

    render(
      <GateView
        gateName="infonet"
        persona="!sb_local"
        onBack={() => {}}
        onNavigateGate={() => {}}
        availableGates={['infonet']}
      />,
    );

    expect(await screen.findByText('sealed')).toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.prepareWormholeInteractiveLane).toHaveBeenCalledWith({
        minimumTransportTier: 'private_control_only',
      });
    });

    fireEvent.change(screen.getByPlaceholderText('Post into this gate...'), {
      target: { value: 'hello' },
    });
    fireEvent.click(screen.getByRole('button', { name: /post/i }));

    expect(
      await screen.findByText(
        'The obfuscated lane is still warming up in the background. Stay in the room and posting should unlock shortly.',
      ),
    ).toBeInTheDocument();
  });

  it('shows a friendly room message instead of a raw gate-envelope post failure', async () => {
    mocks.postWormholeGateMessage.mockRejectedValue(new Error('gate_envelope_required'));

    const { default: GateView } = await import('@/components/InfonetTerminal/GateView');

    render(
      <GateView
        gateName="infonet"
        persona="!sb_local"
        onBack={() => {}}
        onNavigateGate={() => {}}
        availableGates={['infonet']}
      />,
    );

    expect(await screen.findByText('sealed')).toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.prepareWormholeInteractiveLane).toHaveBeenCalledWith({
        minimumTransportTier: 'private_control_only',
      });
    });

    fireEvent.change(screen.getByPlaceholderText('Post into this gate...'), {
      target: { value: 'hello' },
    });
    fireEvent.click(screen.getByRole('button', { name: /post/i }));

    expect(
      await screen.findByText('Local gate sealing is warming up. Your draft is still here.'),
    ).toBeInTheDocument();
  });

  it('does one initial gate fetch and then switches to wait-for-change reads', async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes('/api/mesh/infonet/messages/wait?')) {
        return {
          ok: true,
          json: async () => ({
            gate: 'infonet',
            changed: false,
            cursor: 1,
            messages: [
              {
                event_id: 'evt-1',
                timestamp: 1712345678,
                payload: {
                  gate: 'infonet',
                  ciphertext: 'ciphertext-1',
                  nonce: 'nonce-1',
                  sender_ref: 'sender-ref-1',
                  format: 'mls1',
                  gate_envelope: 'gate-envelope-1',
                  envelope_hash: 'hash-1',
                },
              },
            ],
          }),
        };
      }
      if (url.includes('/api/mesh/infonet/messages?gate=')) {
        return {
          ok: true,
          json: async () => ({
            cursor: 1,
            messages: [
              {
                event_id: 'evt-1',
                timestamp: 1712345678,
                payload: {
                  gate: 'infonet',
                  ciphertext: 'ciphertext-1',
                  nonce: 'nonce-1',
                  sender_ref: 'sender-ref-1',
                  format: 'mls1',
                  gate_envelope: 'gate-envelope-1',
                  envelope_hash: 'hash-1',
                },
              },
            ],
          }),
        };
      }
      if (url.includes('/api/mesh/reputation/batch')) {
        return {
          ok: true,
          json: async () => ({ reputations: {} }),
        };
      }
      throw new Error(`unexpected fetch url: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    const gateSnapshotModule = await import('@/mesh/gateMessageSnapshot');
    const fetchSnapshotSpy = vi.spyOn(gateSnapshotModule, 'fetchGateMessageSnapshotState');
    const waitSnapshotSpy = vi.spyOn(gateSnapshotModule, 'waitForGateMessageSnapshot');
    gateSnapshotModule.invalidateGateMessageSnapshot('infonet');
    const { default: GateView } = await import('@/components/InfonetTerminal/GateView');

    render(
      <GateView
        gateName="infonet"
        persona="!sb_local"
        onBack={() => {}}
        onNavigateGate={() => {}}
        availableGates={['infonet']}
      />,
    );

    expect(await screen.findByText('sealed')).toBeInTheDocument();

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes('/api/mesh/infonet/messages/wait?gate=infonet&after=1'),
        ),
      ).toBe(true),
    );
    expect(fetchSnapshotSpy).toHaveBeenCalledWith('infonet', 40, expect.any(Object));
    expect(waitSnapshotSpy).toHaveBeenCalledWith(
      'infonet',
      1,
      40,
      expect.objectContaining({ timeoutMs: expect.any(Number), signal: expect.any(Object) }),
    );
  });

  it('uses stream-driven room updates as the steady-state path when the gate session stream is open', async () => {
    const streamEventListeners: Array<(event: { event: string; data: unknown }) => void> = [];
    mocks.getGateSessionStreamAccessHeaders.mockReturnValue({
      'X-Wormhole-Node-Id': '!sb_stream',
      'X-Wormhole-Gate-Proof': 'proof-stream',
      'X-Wormhole-Gate-Ts': '1712360000',
    });
    emitStreamStatus({
      enabled: true,
      phase: 'open',
      transport: 'sse',
      sessionId: 'sess-1',
      subscriptions: ['infonet'],
      heartbeatS: 20,
      batchMs: 1500,
      lastEventType: 'hello',
      lastEventAt: 1712360000,
      detail: '',
    });
    mocks.subscribeGateSessionStreamStatus.mockImplementation((listener: (status: unknown) => void) => {
      streamStatusListeners.push(listener);
      listener(mocks.getGateSessionStreamStatus());
      return vi.fn();
    });
    mocks.subscribeGateSessionStreamEvents.mockImplementation((listener: (event: { event: string; data: unknown }) => void) => {
      streamEventListeners.push(listener);
      return vi.fn();
    });

    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes('/api/mesh/infonet/messages?gate=')) {
        return {
          ok: true,
          json: async () => ({
            cursor: url.includes('force') ? 2 : 1,
            messages: [
              {
                event_id: url.includes('force') ? 'evt-2' : 'evt-1',
                timestamp: 1712345678,
                payload: {
                  gate: 'infonet',
                  ciphertext: 'ciphertext-1',
                  nonce: 'nonce-1',
                  sender_ref: 'sender-ref-1',
                  format: 'mls1',
                  gate_envelope: 'gate-envelope-1',
                  envelope_hash: 'hash-1',
                },
              },
            ],
          }),
        };
      }
      if (url.includes('/api/mesh/reputation/batch')) {
        return {
          ok: true,
          json: async () => ({ reputations: {} }),
        };
      }
      throw new Error(`unexpected fetch url: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    const gateSnapshotModule = await import('@/mesh/gateMessageSnapshot');
    const fetchSnapshotSpy = vi.spyOn(gateSnapshotModule, 'fetchGateMessageSnapshotState');
    const waitSnapshotSpy = vi.spyOn(gateSnapshotModule, 'waitForGateMessageSnapshot');
    gateSnapshotModule.invalidateGateMessageSnapshot('infonet');

    const { default: GateView } = await import('@/components/InfonetTerminal/GateView');

    render(
      <GateView
        gateName="infonet"
        persona="!sb_local"
        onBack={() => {}}
        onNavigateGate={() => {}}
        availableGates={['infonet']}
      />,
    );

    expect(await screen.findByText('sealed')).toBeInTheDocument();
    expect(mocks.subscribeGateSessionStreamEvents).toHaveBeenCalled();
    expect(mocks.fetchWormholeGateKeyStatus).toHaveBeenCalledWith(
      'infonet',
      expect.objectContaining({ mode: 'session_stream' }),
    );
    expect(mocks.controlPlaneJson).not.toHaveBeenCalled();
    waitSnapshotSpy.mockClear();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(waitSnapshotSpy).not.toHaveBeenCalled();

    streamEventListeners.forEach((listener) =>
      listener({
        event: 'gate_update',
        data: {
          session_id: 'sess-1',
          updates: [{ gate_id: 'infonet', cursor: 2 }],
          ts: 1712360001,
        },
      }),
    );

    await waitFor(() =>
      expect(fetchSnapshotSpy).toHaveBeenCalledWith(
        'infonet',
        40,
        expect.objectContaining({ force: true, proofMode: 'session_stream' }),
      ),
    );
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes('/api/mesh/infonet/messages/wait?'),
      ),
    ).toBe(false);
    expect(mocks.controlPlaneJson).not.toHaveBeenCalled();
  });

  it('falls back to wait-for-change on stream loss and hands control back after reconnect', async () => {
    const streamEventListeners: Array<(event: { event: string; data: unknown }) => void> = [];
    emitStreamStatus({
      enabled: true,
      phase: 'open',
      transport: 'sse',
      sessionId: 'sess-2',
      subscriptions: ['infonet'],
      heartbeatS: 20,
      batchMs: 1500,
      lastEventType: 'hello',
      lastEventAt: 1712360100,
      detail: '',
    });
    mocks.subscribeGateSessionStreamEvents.mockImplementation((listener: (event: { event: string; data: unknown }) => void) => {
      streamEventListeners.push(listener);
      return vi.fn();
    });

    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes('/api/mesh/infonet/messages/wait?')) {
        return {
          ok: true,
          json: async () => ({
            gate: 'infonet',
            changed: false,
            cursor: 1,
            messages: [
              {
                event_id: 'evt-1',
                timestamp: 1712345678,
                payload: {
                  gate: 'infonet',
                  ciphertext: 'ciphertext-1',
                  nonce: 'nonce-1',
                  sender_ref: 'sender-ref-1',
                  format: 'mls1',
                  gate_envelope: 'gate-envelope-1',
                  envelope_hash: 'hash-1',
                },
              },
            ],
          }),
        };
      }
      if (url.includes('/api/mesh/infonet/messages?gate=')) {
        return {
          ok: true,
          json: async () => ({
            cursor: 1,
            messages: [
              {
                event_id: 'evt-1',
                timestamp: 1712345678,
                payload: {
                  gate: 'infonet',
                  ciphertext: 'ciphertext-1',
                  nonce: 'nonce-1',
                  sender_ref: 'sender-ref-1',
                  format: 'mls1',
                  gate_envelope: 'gate-envelope-1',
                  envelope_hash: 'hash-1',
                },
              },
            ],
          }),
        };
      }
      if (url.includes('/api/mesh/reputation/batch')) {
        return {
          ok: true,
          json: async () => ({ reputations: {} }),
        };
      }
      throw new Error(`unexpected fetch url: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    const gateSnapshotModule = await import('@/mesh/gateMessageSnapshot');
    const fetchSnapshotSpy = vi.spyOn(gateSnapshotModule, 'fetchGateMessageSnapshotState');
    const waitSnapshotSpy = vi.spyOn(gateSnapshotModule, 'waitForGateMessageSnapshot');
    gateSnapshotModule.invalidateGateMessageSnapshot('infonet');

    const { default: GateView } = await import('@/components/InfonetTerminal/GateView');

    render(
      <GateView
        gateName="infonet"
        persona="!sb_local"
        onBack={() => {}}
        onNavigateGate={() => {}}
        availableGates={['infonet']}
      />,
    );

    expect(await screen.findByText('sealed')).toBeInTheDocument();
    waitSnapshotSpy.mockClear();

    emitStreamStatus({
      enabled: false,
      phase: 'closed',
      transport: 'sse',
      sessionId: 'sess-2',
      subscriptions: ['infonet'],
      heartbeatS: 20,
      batchMs: 1500,
      lastEventType: 'heartbeat',
      lastEventAt: 1712360200,
      detail: 'gate_session_stream_closed',
    });

    await waitFor(() =>
      expect(waitSnapshotSpy).toHaveBeenCalledWith(
        'infonet',
        1,
        40,
        expect.objectContaining({ timeoutMs: expect.any(Number), signal: expect.any(Object) }),
      ),
    );

    waitSnapshotSpy.mockClear();
    fetchSnapshotSpy.mockClear();

    emitStreamStatus({
      enabled: true,
      phase: 'open',
      transport: 'sse',
      sessionId: 'sess-3',
      subscriptions: ['infonet'],
      heartbeatS: 20,
      batchMs: 1500,
      lastEventType: 'hello',
      lastEventAt: 1712360300,
      detail: '',
    });

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(waitSnapshotSpy).not.toHaveBeenCalled();

    streamEventListeners.forEach((listener) =>
      listener({
        event: 'gate_update',
        data: {
          session_id: 'sess-3',
          updates: [{ gate_id: 'infonet', cursor: 2 }],
          ts: 1712360301,
        },
      }),
    );

    await waitFor(() =>
      expect(fetchSnapshotSpy).toHaveBeenCalledWith(
        'infonet',
        40,
        expect.objectContaining({ force: true }),
      ),
    );
  });
});
