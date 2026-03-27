import { beforeEach, describe, expect, it, vi } from 'vitest';

const deadDropTokensForContacts = vi.fn();
const mailboxClaimToken = vi.fn();
const mailboxDecoySharedToken = vi.fn();

vi.mock('@/mesh/meshDeadDrop', () => ({
  deadDropToken: vi.fn(),
  deadDropTokensForContacts,
}));

vi.mock('@/mesh/meshMailbox', () => ({
  mailboxClaimToken,
  mailboxDecoySharedToken,
}));

vi.mock('@/mesh/meshIdentity', () => ({
  deriveSenderSealKey: vi.fn(),
  ensureDhKeysFresh: vi.fn(),
  deriveSharedKey: vi.fn(),
  encryptDM: vi.fn(),
  getDHAlgo: vi.fn(() => 'X25519'),
  getNodeIdentity: vi.fn(() => ({ nodeId: '!self', publicKey: 'pub' })),
  getPublicKeyAlgo: vi.fn(() => 'Ed25519'),
  nextSequence: vi.fn(() => 1),
  verifyNodeIdBindingFromPublicKey: vi.fn(async () => true),
}));

vi.mock('@/mesh/wormholeIdentityClient', () => ({
  buildWormholeSenderSeal: vi.fn(),
  getActiveSigningContext: vi.fn(async () => null),
  isWormholeSecureRequired: vi.fn(async () => false),
  issueWormholeDmSenderToken: vi.fn(),
  issueWormholeDmSenderTokens: vi.fn(),
  registerWormholeDmKey: vi.fn(),
  signRawMeshMessage: vi.fn(),
  signMeshEvent: vi.fn(),
}));

vi.mock('@/mesh/meshSchema', () => ({
  validateEventPayload: vi.fn(() => ({ ok: true, reason: 'ok' })),
}));

describe('mailbox claim privacy padding', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.stubEnv('NEXT_PUBLIC_ENABLE_RFC2A_CLAIM_SHAPE', '1');
    deadDropTokensForContacts.mockReset();
    mailboxClaimToken.mockReset();
    mailboxDecoySharedToken.mockReset();
    mailboxClaimToken.mockImplementation(async (type: string) => `${type}-token`);
    mailboxDecoySharedToken.mockImplementation(async (index: number) => `decoy-${index}`);
  });

  function buildSharedTokens(count: number): string[] {
    return Array.from({ length: count }, (_, index) => `shared-${index + 1}`);
  }

  it('uses bucketed shared-claim envelopes across multiple contact counts', async () => {
    const mod = await import('@/mesh/meshDmClient');

    for (const testCase of [
      { realSharedClaims: 0, expectedSharedClaims: 3, expectedTotalClaims: 5 },
      { realSharedClaims: 1, expectedSharedClaims: 3, expectedTotalClaims: 5 },
      { realSharedClaims: 3, expectedSharedClaims: 3, expectedTotalClaims: 5 },
      { realSharedClaims: 4, expectedSharedClaims: 6, expectedTotalClaims: 8 },
      { realSharedClaims: 7, expectedSharedClaims: 12, expectedTotalClaims: 14 },
      { realSharedClaims: 25, expectedSharedClaims: 30, expectedTotalClaims: 32 },
      { realSharedClaims: 30, expectedSharedClaims: 30, expectedTotalClaims: 32 },
    ]) {
      deadDropTokensForContacts.mockResolvedValue(buildSharedTokens(testCase.realSharedClaims));

      const claims = await mod.buildMailboxClaims({});
      expect(claims.slice(0, 2)).toEqual([
        { type: 'self', token: 'self-token' },
        { type: 'requests', token: 'requests-token' },
      ]);
      expect(claims.filter((claim) => claim.type === 'shared')).toHaveLength(
        testCase.expectedSharedClaims,
      );
      expect(claims).toHaveLength(testCase.expectedTotalClaims);
    }
  });

  it('falls back to the legacy shared-claim floor when the experiment is disabled', async () => {
    vi.resetModules();
    vi.stubEnv('NEXT_PUBLIC_ENABLE_RFC2A_CLAIM_SHAPE', '0');
    deadDropTokensForContacts.mockResolvedValue(['shared-1', 'shared-2', 'shared-3', 'shared-4']);

    const mod = await import('@/mesh/meshDmClient');
    const claims = await mod.buildMailboxClaims({});
    const sharedClaims = claims.filter((claim) => claim.type === 'shared');

    expect(mod.MAILBOX_SHARED_CLAIM_SHAPE_VERSION).toBe('legacy-floor-v1');
    expect(sharedClaims).toEqual([
      { type: 'shared', token: 'shared-1' },
      { type: 'shared', token: 'shared-2' },
      { type: 'shared', token: 'shared-3' },
      { type: 'shared', token: 'shared-4' },
    ]);
    expect(claims).toHaveLength(6);
  });

  it('deduplicates real shared tokens before filling the bucketed envelope', async () => {
    deadDropTokensForContacts.mockResolvedValue(['shared-real', 'shared-real']);

    const mod = await import('@/mesh/meshDmClient');
    const claims = await mod.buildMailboxClaims({
      alice: { blocked: false, dhPubKey: 'dh-a' },
    });

    const sharedClaims = claims.filter((claim) => claim.type === 'shared');
    expect(sharedClaims).toEqual([
      { type: 'shared', token: 'decoy-0' },
      { type: 'shared', token: 'shared-real' },
      { type: 'shared', token: 'decoy-1' },
    ]);
  });

  it('preserves every real shared token within the supported 30-claim shared range', async () => {
    const realSharedTokens = buildSharedTokens(30);
    deadDropTokensForContacts.mockResolvedValue(realSharedTokens);

    const mod = await import('@/mesh/meshDmClient');
    const claims = await mod.buildMailboxClaims({});

    const sharedTokens = claims
      .filter((claim) => claim.type === 'shared')
      .map((claim) => claim.token);
    expect(sharedTokens).toHaveLength(30);
    expect(new Set(sharedTokens)).toEqual(new Set(realSharedTokens));
  });

  it('keeps decoy shared tokens distinct from real shared tokens', async () => {
    const realSharedTokens = ['shared-1', 'shared-2', 'shared-3', 'shared-4'];
    deadDropTokensForContacts.mockResolvedValue(realSharedTokens);

    const mod = await import('@/mesh/meshDmClient');
    const claims = await mod.buildMailboxClaims({});

    const sharedTokens = claims
      .filter((claim) => claim.type === 'shared')
      .map((claim) => String(claim.token || ''));
    const decoyTokens = sharedTokens.filter((token) => !realSharedTokens.includes(token));

    expect(sharedTokens).toEqual([
      'shared-1',
      'decoy-0',
      'shared-2',
      'shared-3',
      'decoy-1',
      'shared-4',
    ]);
    expect(decoyTokens).toEqual(['decoy-0', 'decoy-1']);
    expect(decoyTokens.every((token) => !realSharedTokens.includes(token))).toBe(true);
  });
});
