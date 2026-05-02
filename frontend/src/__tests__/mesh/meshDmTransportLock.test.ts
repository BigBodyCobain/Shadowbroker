import { beforeEach, describe, expect, it, vi } from 'vitest';

const signMeshEvent = vi.fn();
const issueWormholeDmSenderToken = vi.fn();
const issueWormholeDmSenderTokens = vi.fn();
const registerWormholeDmKey = vi.fn();
const validateEventPayload = vi.fn(() => ({ ok: true, reason: 'ok' }));
const nextSequence = vi.fn(() => 42);

vi.mock('@/mesh/meshDeadDrop', () => ({
  deadDropToken: vi.fn(async () => 'shared-token'),
  deadDropTokensForContacts: vi.fn(async () => []),
}));

vi.mock('@/mesh/meshMailbox', () => ({
  mailboxClaimToken: vi.fn(async (type: string) => `${type}-token`),
  mailboxDecoySharedToken: vi.fn(async (index: number) => `decoy-${index}`),
}));

vi.mock('@/mesh/meshIdentity', () => ({
  deriveSenderSealKey: vi.fn(),
  ensureDhKeysFresh: vi.fn(),
  deriveSharedKey: vi.fn(),
  encryptDM: vi.fn(),
  getDHAlgo: vi.fn(() => 'X25519'),
  getNodeIdentity: vi.fn(() => ({ nodeId: '!sb_self', publicKey: 'pub' })),
  getPublicKeyAlgo: vi.fn(() => 'Ed25519'),
  nextSequence,
  verifyNodeIdBindingFromPublicKey: vi.fn(async () => true),
}));

vi.mock('@/mesh/wormholeIdentityClient', () => ({
  buildWormholeSenderSeal: vi.fn(),
  getActiveSigningContext: vi.fn(async () => null),
  isWormholeSecureRequired: vi.fn(async () => false),
  issueWormholeDmSenderToken,
  issueWormholeDmSenderTokens,
  registerWormholeDmKey,
  signRawMeshMessage: vi.fn(),
  signMeshEvent,
}));

vi.mock('@/mesh/meshSchema', () => ({
  validateEventPayload,
}));

describe('DM transport lock signing', () => {
  const fetchMock = vi.fn();
  const identity = {
    nodeId: '!sb_self',
    publicKey: 'pub',
    privateKey: 'priv',
  };

  beforeEach(() => {
    vi.resetModules();
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    validateEventPayload.mockClear();
    nextSequence.mockClear();
    signMeshEvent.mockReset();
    issueWormholeDmSenderToken.mockReset();
    issueWormholeDmSenderTokens.mockReset();
    registerWormholeDmKey.mockReset();
    signMeshEvent.mockResolvedValue({
      context: {
        nodeId: '!sb_self',
        publicKey: 'pub',
        publicKeyAlgo: 'Ed25519',
      },
      signature: 'sig',
      sequence: 42,
      protocolVersion: 'infonet/2',
    });
    issueWormholeDmSenderTokens.mockResolvedValue({ tokens: [] });
    issueWormholeDmSenderToken.mockResolvedValue({ sender_token: 'sender-token' });
    registerWormholeDmKey.mockResolvedValue({ ok: true });
    fetchMock.mockResolvedValue({ json: async () => ({ ok: true }) });
  });

  it('signs and sends private_strong on DM sends', async () => {
    const mod = await import('@/mesh/meshDmClient');

    await mod.sendDmMessage({
      apiBase: 'http://localhost:8000',
      identity,
      recipientId: '!sb_peer',
      ciphertext: 'sealed',
      msgId: 'dm-test-1',
      timestamp: 123,
      deliveryClass: 'request',
    });

    expect(signMeshEvent).toHaveBeenCalledWith(
      'dm_message',
      expect.objectContaining({ transport_lock: 'private_strong' }),
      42,
    );
    const body = JSON.parse(fetchMock.mock.calls.at(-1)?.[1]?.body as string);
    expect(body.transport_lock).toBe('private_strong');
  });

  it('signs and sends private_strong on DM poll/count', async () => {
    const mod = await import('@/mesh/meshDmClient');
    const claims = [{ type: 'requests' as const, token: 'request-token' }];

    await mod.pollDmMailboxes('http://localhost:8000', identity, claims);
    await mod.countDmMailboxes('http://localhost:8000', identity, claims);

    expect(signMeshEvent).toHaveBeenCalledWith(
      'dm_poll',
      expect.objectContaining({ transport_lock: 'private_strong' }),
      42,
    );
    expect(signMeshEvent).toHaveBeenCalledWith(
      'dm_count',
      expect.objectContaining({ transport_lock: 'private_strong' }),
      42,
    );
    const pollBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    const countBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(pollBody.transport_lock).toBe('private_strong');
    expect(countBody.transport_lock).toBe('private_strong');
  });
});
