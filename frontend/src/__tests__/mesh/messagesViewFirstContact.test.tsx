import '@testing-library/jest-dom/vitest';

import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

let contactsState: Record<string, any> = {};

const mocks = vi.hoisted(() => ({
  buildMailboxClaims: vi.fn(async () => []),
  countDmMailboxes: vi.fn(async () => ({ ok: true, count: 0 })),
  ensureRegisteredDmKey: vi.fn(async () => ({ dhPubKey: 'local-dh', dhAlgo: 'X25519' })),
  fetchDmPublicKey: vi.fn(async () => ({ dh_pub_key: 'peer-dh', dh_algo: 'X25519' })),
  pollDmMailboxes: vi.fn(async () => ({ ok: true, messages: [] })),
  sendDmMessage: vi.fn(async () => ({ ok: true, transport: 'relay' })),
  sendOffLedgerConsentMessage: vi.fn(async () => ({ ok: true, transport: 'relay' })),
  sharedMailboxToken: vi.fn(async () => 'shared-token'),
  buildContactAcceptMessage: vi.fn(() => 'accept'),
  buildContactDenyMessage: vi.fn(() => 'deny'),
  buildContactOfferMessage: vi.fn(() => 'offer'),
  generateSharedAlias: vi.fn(() => 'alias-123'),
  mergeAliasHistory: vi.fn((history?: string[]) => history || []),
  parseAliasRotateMessage: vi.fn(() => null),
  parseDmConsentMessage: vi.fn(() => null),
  preferredDmPeerId: vi.fn((peerId: string) => peerId),
  allDmPeerIds: vi.fn(() => []),
  purgeBrowserDmState: vi.fn(async () => {}),
  ratchetDecryptDM: vi.fn(async () => {
    throw new Error('no_ratchet_state');
  }),
  ratchetEncryptDM: vi.fn(async () => 'ratchet-ciphertext'),
  addContact: vi.fn(),
  blockContact: vi.fn(),
  decryptDM: vi.fn(async () => 'plaintext'),
  decryptSenderSealPayloadLocally: vi.fn(async () => ''),
  deriveSharedKey: vi.fn(async () => ({})),
  encryptDM: vi.fn(async () => 'ciphertext'),
  getContacts: vi.fn(() => contactsState),
  getDHAlgo: vi.fn(() => 'X25519'),
  getNodeIdentity: vi.fn(() => ({
    nodeId: '!sb_local',
    publicKey: 'local-pub',
    privateKey: 'local-priv',
  })),
  hasSovereignty: vi.fn(() => true),
  hydrateWormholeContacts: vi.fn(async () => contactsState),
  purgeBrowserContactGraph: vi.fn(),
  purgeBrowserSigningMaterial: vi.fn(),
  removeContact: vi.fn(),
  unblockContact: vi.fn(),
  unwrapSenderSealPayload: vi.fn(() => ({ version: 'v2', ephemeralPub: '' })),
  updateContact: vi.fn(),
  verifyNodeIdBindingFromPublicKey: vi.fn(async () => true),
  verifyRawSignature: vi.fn(async () => true),
  getSenderRecoveryState: vi.fn(() => 'verified'),
  recoverSenderSealWithFallback: vi.fn(async () => null),
  requiresSenderRecovery: vi.fn(() => false),
  shouldKeepUnresolvedRequestVisible: vi.fn(() => false),
  shouldPromoteRecoveredSenderForBootstrap: vi.fn(() => false),
  shouldPromoteRecoveredSenderForKnownContact: vi.fn(() => false),
  bootstrapDecryptAccessRequest: vi.fn(async () => 'offer'),
  bootstrapEncryptAccessRequest: vi.fn(async () => 'x3dh1:bootstrap'),
  canUseWormholeBootstrap: vi.fn(async () => false),
  fetchWormholeStatus: vi.fn(async () => ({ ready: true, transport_tier: 'private_strong' })),
  fetchWormholeIdentity: vi.fn(async () => ({ node_id: '!sb_local', public_key: 'local-pub' })),
  prepareWormholeInteractiveLane: vi.fn(async () => ({
    ready: true,
    settingsEnabled: true,
    transportTier: 'private_transitional',
    identity: { node_id: '!sb_local', public_key: 'local-pub' },
  })),
  importWormholeDmInvite: vi.fn(async () => ({
    ok: true,
    peer_id: '!sb_imported',
    trust_fingerprint: 'invitefp',
    trust_level: 'invite_pinned',
  })),
  isWormholeReady: vi.fn(async () => true),
  isWormholeSecureRequired: vi.fn(async () => false),
  issueWormholePairwiseAlias: vi.fn(async () => ({ ok: true, shared_alias: 'alias-123' })),
  openWormholeSenderSeal: vi.fn(async () => ({ sender_id: '!sb_peer', seal_verified: true })),
}));

vi.mock('@/lib/api', () => ({
  API_BASE: 'http://localhost:8000',
}));

vi.mock('@/mesh/meshDmClient', () => ({
  buildMailboxClaims: mocks.buildMailboxClaims,
  countDmMailboxes: mocks.countDmMailboxes,
  ensureRegisteredDmKey: mocks.ensureRegisteredDmKey,
  fetchDmPublicKey: mocks.fetchDmPublicKey,
  pollDmMailboxes: mocks.pollDmMailboxes,
  sendDmMessage: mocks.sendDmMessage,
  sendOffLedgerConsentMessage: mocks.sendOffLedgerConsentMessage,
  sharedMailboxToken: mocks.sharedMailboxToken,
}));

vi.mock('@/mesh/meshDmConsent', () => ({
  allDmPeerIds: mocks.allDmPeerIds,
  buildContactAcceptMessage: mocks.buildContactAcceptMessage,
  buildContactDenyMessage: mocks.buildContactDenyMessage,
  buildContactOfferMessage: mocks.buildContactOfferMessage,
  generateSharedAlias: mocks.generateSharedAlias,
  mergeAliasHistory: mocks.mergeAliasHistory,
  parseAliasRotateMessage: mocks.parseAliasRotateMessage,
  parseDmConsentMessage: mocks.parseDmConsentMessage,
  preferredDmPeerId: mocks.preferredDmPeerId,
}));

vi.mock('@/mesh/meshDmWorkerClient', () => ({
  purgeBrowserDmState: mocks.purgeBrowserDmState,
  ratchetDecryptDM: mocks.ratchetDecryptDM,
  ratchetEncryptDM: mocks.ratchetEncryptDM,
}));

vi.mock('@/mesh/meshIdentity', () => ({
  addContact: mocks.addContact,
  blockContact: mocks.blockContact,
  decryptDM: mocks.decryptDM,
  decryptSenderSealPayloadLocally: mocks.decryptSenderSealPayloadLocally,
  deriveSharedKey: mocks.deriveSharedKey,
  encryptDM: mocks.encryptDM,
  getContacts: mocks.getContacts,
  getDHAlgo: mocks.getDHAlgo,
  getNodeIdentity: mocks.getNodeIdentity,
  hasSovereignty: mocks.hasSovereignty,
  hydrateWormholeContacts: mocks.hydrateWormholeContacts,
  purgeBrowserContactGraph: mocks.purgeBrowserContactGraph,
  purgeBrowserSigningMaterial: mocks.purgeBrowserSigningMaterial,
  removeContact: mocks.removeContact,
  unblockContact: mocks.unblockContact,
  unwrapSenderSealPayload: mocks.unwrapSenderSealPayload,
  updateContact: mocks.updateContact,
  verifyNodeIdBindingFromPublicKey: mocks.verifyNodeIdBindingFromPublicKey,
  verifyRawSignature: mocks.verifyRawSignature,
}));

vi.mock('@/mesh/requestSenderRecovery', () => ({
  getSenderRecoveryState: mocks.getSenderRecoveryState,
  recoverSenderSealWithFallback: mocks.recoverSenderSealWithFallback,
  requiresSenderRecovery: mocks.requiresSenderRecovery,
  shouldKeepUnresolvedRequestVisible: mocks.shouldKeepUnresolvedRequestVisible,
  shouldPromoteRecoveredSenderForBootstrap: mocks.shouldPromoteRecoveredSenderForBootstrap,
  shouldPromoteRecoveredSenderForKnownContact: mocks.shouldPromoteRecoveredSenderForKnownContact,
}));

vi.mock('@/mesh/wormholeDmBootstrapClient', () => ({
  bootstrapDecryptAccessRequest: mocks.bootstrapDecryptAccessRequest,
  bootstrapEncryptAccessRequest: mocks.bootstrapEncryptAccessRequest,
  canUseWormholeBootstrap: mocks.canUseWormholeBootstrap,
}));

vi.mock('@/mesh/wormholeIdentityClient', () => ({
  fetchWormholeStatus: mocks.fetchWormholeStatus,
  fetchWormholeIdentity: mocks.fetchWormholeIdentity,
  prepareWormholeInteractiveLane: mocks.prepareWormholeInteractiveLane,
  getWormholeDmInviteImportErrorResult: (error: unknown) =>
    error && typeof error === 'object' && 'result' in (error as Record<string, unknown>)
      ? (((error as Record<string, unknown>).result as Record<string, unknown>) || null)
      : null,
  importWormholeDmInvite: mocks.importWormholeDmInvite,
  isWormholeReady: mocks.isWormholeReady,
  isWormholeSecureRequired: mocks.isWormholeSecureRequired,
  issueWormholePairwiseAlias: mocks.issueWormholePairwiseAlias,
  openWormholeSenderSeal: mocks.openWormholeSenderSeal,
}));

import MessagesView from '@/components/InfonetTerminal/MessagesView';

function renderMessagesView(options?: {
  onOpenDeadDrop?: (peerId: string, opts?: { showSas?: boolean }) => void;
}) {
  return render(<MessagesView onBack={() => {}} onOpenDeadDrop={options?.onOpenDeadDrop} />);
}

async function openComposeForRecipient(recipient: string, body: string) {
  fireEvent.click(screen.getByRole('button', { name: 'COMPOSE' }));
  fireEvent.change(screen.getByLabelText(/Recipient agent ID/i), {
    target: { value: recipient },
  });
  fireEvent.change(screen.getByLabelText(/Message/i), {
    target: { value: body },
  });
  await screen.findByLabelText(/Recipient agent ID/i);
}

describe('MessagesView first-contact trust UX', () => {
  beforeEach(() => {
    cleanup();
    localStorage.clear();
    contactsState = {};
    vi.clearAllMocks();

    mocks.getContacts.mockImplementation(() => contactsState);
    mocks.hydrateWormholeContacts.mockImplementation(async () => contactsState);
    mocks.fetchWormholeStatus.mockResolvedValue({ ready: true, transport_tier: 'private_strong' });
    mocks.prepareWormholeInteractiveLane.mockResolvedValue({
      ready: true,
      settingsEnabled: true,
      transportTier: 'private_transitional',
      identity: { node_id: '!sb_local', public_key: 'local-pub' },
    });
    mocks.isWormholeSecureRequired.mockResolvedValue(false);
    mocks.getNodeIdentity.mockReturnValue({
      nodeId: '!sb_local',
      publicKey: 'local-pub',
      privateKey: 'local-priv',
    });
    mocks.hasSovereignty.mockReturnValue(true);
    mocks.buildMailboxClaims.mockResolvedValue([]);
    mocks.pollDmMailboxes.mockResolvedValue({ ok: true, messages: [] });
    mocks.countDmMailboxes.mockResolvedValue({ ok: true, count: 0 });
    mocks.ensureRegisteredDmKey.mockResolvedValue({ dhPubKey: 'local-dh', dhAlgo: 'X25519' });
    mocks.fetchDmPublicKey.mockResolvedValue({ dh_pub_key: 'peer-dh', dh_algo: 'X25519' });
    mocks.sendOffLedgerConsentMessage.mockResolvedValue({ ok: true, transport: 'relay' });
    mocks.canUseWormholeBootstrap.mockResolvedValue(false);
  });

  afterEach(() => {
    cleanup();
  });

  it('blocks unknown first contact until a signed invite is imported', async () => {
    renderMessagesView();
    await openComposeForRecipient('!sb_unknown', 'hello from first contact');

    expect(await screen.findByText('Verified First Contact Required')).toBeInTheDocument();
    expect(
      screen.getByText(/Secure request bootstrap is blocked until you import a signed invite/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send Secure Mail' })).toBeDisabled();
  });

  it('can jump directly from the downgrade warning into invite import flow', async () => {
    renderMessagesView();
    await openComposeForRecipient('!sb_unknown', 'hello from first contact');

    fireEvent.click(screen.getByRole('button', { name: 'Import Signed Invite' }));

    expect(await screen.findByText('Import Verified Invite')).toBeInTheDocument();
    expect(screen.getByLabelText(/Local Alias/i)).toHaveValue('!sb_unknown');
  });

  it('does not expose a TOFU downgrade button for first contact anymore', async () => {
    renderMessagesView();
    await openComposeForRecipient('!sb_unknown', 'hello from first contact');

    expect(screen.queryByRole('button', { name: /Explicitly Allow TOFU/i })).not.toBeInTheDocument();
    expect(mocks.sendOffLedgerConsentMessage).not.toHaveBeenCalled();
  });

  it('does not require the TOFU override when the contact is invite-pinned already', async () => {
    contactsState = {
      '!sb_invited': {
        alias: 'Pinned Peer',
        blocked: false,
        trust_level: 'invite_pinned',
        invitePinnedTrustFingerprint: 'abcdef123456',
        invitePinnedRootFingerprint: 'rootabcdef123456',
        invitePinnedRootManifestFingerprint: 'manifestabcdef123456',
        invitePinnedRootWitnessPolicyFingerprint: 'policyabcdef123456',
        invitePinnedRootWitnessThreshold: 2,
        invitePinnedRootWitnessCount: 3,
        invitePinnedRootManifestGeneration: 1,
        invitePinnedRootRotationProven: true,
        invitePinnedAt: 123,
        remotePrekeyFingerprint: 'abcdef123456',
        remotePrekeyRootFingerprint: 'rootabcdef123456',
        remotePrekeyRootManifestFingerprint: 'manifestabcdef123456',
        remotePrekeyRootWitnessPolicyFingerprint: 'policyabcdef123456',
        remotePrekeyRootWitnessThreshold: 2,
        remotePrekeyRootWitnessCount: 3,
        remotePrekeyRootManifestGeneration: 1,
        remotePrekeyRootRotationProven: true,
      },
    };

    renderMessagesView();
    await openComposeForRecipient('!sb_invited', 'hello to pinned peer');

    expect(screen.queryByText('Unverified First Contact')).not.toBeInTheDocument();
    expect(await screen.findByText('ROOT LOCAL QUORUM')).toBeInTheDocument();
    expect(await screen.findByText(/Local quorum root rootabcd\.\.123456/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send Secure Mail' })).toBeEnabled();
  });

  it('warms the private lane in the background before sending secure mail', async () => {
    contactsState = {
      '!sb_pinned': {
        alias: 'Pinned Peer',
        blocked: false,
        trust_level: 'invite_pinned',
        dhPubKey: 'peer-dh',
        remotePrekeyFingerprint: 'abcdef123456',
      },
    };
    mocks.fetchWormholeStatus.mockResolvedValue({ ready: false, transport_tier: 'public_degraded' });

    renderMessagesView();
    await openComposeForRecipient('!sb_pinned', 'hello after warmup');

    fireEvent.click(screen.getByRole('button', { name: 'Send Secure Mail' }));

    await screen.findByText(/Mail delivered to Pinned Peer/i);
    expect(mocks.prepareWormholeInteractiveLane).toHaveBeenCalled();
    expect(mocks.sendDmMessage).toHaveBeenCalled();
  });

  it('does not flatten witness policy not met into a generic witnessed root label', async () => {
    contactsState = {
      '!sb_policy': {
        alias: 'Policy Peer',
        blocked: false,
        trust_level: 'invite_pinned',
        invitePinnedTrustFingerprint: 'policyfingerprint123456',
        invitePinnedRootFingerprint: 'rootpolicyabcdef123456',
        invitePinnedRootManifestFingerprint: 'manifestpolicyabcdef123456',
        invitePinnedRootWitnessPolicyFingerprint: 'policyabcdef123456',
        invitePinnedRootWitnessThreshold: 2,
        invitePinnedRootWitnessCount: 1,
        invitePinnedRootManifestGeneration: 1,
        invitePinnedRootRotationProven: true,
        invitePinnedAt: 123,
        remotePrekeyFingerprint: 'policyfingerprint123456',
        remotePrekeyRootFingerprint: 'rootpolicyabcdef123456',
        remotePrekeyRootManifestFingerprint: 'manifestpolicyabcdef123456',
        remotePrekeyRootWitnessPolicyFingerprint: 'policyabcdef123456',
        remotePrekeyRootWitnessThreshold: 2,
        remotePrekeyRootWitnessCount: 1,
        remotePrekeyRootManifestGeneration: 1,
        remotePrekeyRootRotationProven: true,
      },
    };

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));

    expect(await screen.findByText(/Witness-policy root rootpoli\.\.123456/i)).toBeInTheDocument();
    expect(screen.queryByText(/Witnessed root rootpoli\.\.123456/i)).not.toBeInTheDocument();
  });

  it('shows an import-invite shortcut for unpinned contacts in the contact list', async () => {
    contactsState = {
      '!sb_unpinned': {
        alias: 'Weak Peer',
        blocked: false,
        dhPubKey: 'peer-dh',
        trust_level: 'unpinned',
      },
    };

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));

    const importButton = await screen.findByRole('button', { name: 'Import Invite' });
    fireEvent.click(importButton);
    expect(screen.getByLabelText(/Local Alias/i)).toHaveValue('!sb_unpinned');
  });

  it('routes continuity reverify from Secure Messages into Dead Drop with SAS visible', async () => {
    contactsState = {
      '!sb_reverify': {
        alias: 'Broken Root Peer',
        blocked: false,
        trust_level: 'continuity_broken',
        remotePrekeyObservedFingerprint: 'observed123456',
        remotePrekeyObservedRootFingerprint: 'rootobserved123456',
        remotePrekeyRootMismatch: true,
      },
    };
    const onOpenDeadDrop = vi.fn();

    renderMessagesView({ onOpenDeadDrop });
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));

    const reverifyButton = await screen.findByRole('button', { name: 'REVERIFY NOW' });
    fireEvent.click(reverifyButton);

    expect(onOpenDeadDrop).toHaveBeenCalledWith('!sb_reverify', { showSas: true });
  });

  it('still blocks first contact when legacy verified flags and a dh key are seeded on an unpinned contact', async () => {
    contactsState = {
      '!sb_seeded': {
        alias: 'Seeded Peer',
        blocked: false,
        dhPubKey: 'forged-dh',
        verify_inband: true,
        verify_registry: true,
        verified: true,
        trust_level: 'unpinned',
        trustSummary: {
          state: 'unpinned',
          label: 'UNVERIFIED',
          severity: 'warn',
          detail: 'invite required',
          verifiedFirstContact: false,
          recommendedAction: 'import_invite',
          legacyLookup: false,
          inviteAttested: false,
          registryMismatch: false,
          transparencyConflict: false,
        },
      },
    };

    renderMessagesView();
    await openComposeForRecipient('!sb_seeded', 'hello from forged first contact');

    expect(await screen.findByText('Verified First Contact Required')).toBeInTheDocument();
    expect(
      screen.getByText(/Secure request bootstrap is blocked until you import a signed invite/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send Secure Mail' })).toBeDisabled();
  });

  it('blocks ambient legacy lookup for verified contacts that still lack an invite handle', async () => {
    contactsState = {
      '!sb_legacy': {
        alias: 'Legacy Peer',
        blocked: false,
        trust_level: 'sas_verified',
        remotePrekeyLookupMode: 'legacy_agent_id',
        trustSummary: {
          state: 'sas_verified',
          label: 'SAS VERIFIED',
          severity: 'good',
          detail: 'legacy lookup still active',
          verifiedFirstContact: true,
          recommendedAction: 'import_invite',
          legacyLookup: true,
          inviteAttested: false,
          registryMismatch: false,
          transparencyConflict: false,
        },
      },
    };

    renderMessagesView();
    await openComposeForRecipient('!sb_legacy', 'hello from a legacy lookup contact');

    fireEvent.click(screen.getByRole('button', { name: 'Send Secure Mail' }));

    expect(
      await screen.findByText(
        /Import or re-import a signed invite before sending a contact request; legacy direct lookup is disabled\./i,
      ),
    ).toBeInTheDocument();
    expect(mocks.fetchDmPublicKey).not.toHaveBeenCalled();
  });

  it('announces attested invite imports as INVITE PINNED', async () => {
    mocks.importWormholeDmInvite.mockResolvedValueOnce({
      ok: true,
      peer_id: '!sb_attested',
      trust_fingerprint: 'invitefp-attested',
      trust_level: 'invite_pinned',
      contact: {},
    });

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));
    expect(await screen.findByText('Import Verified Invite')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Signed Invite JSON/i), {
      target: { value: JSON.stringify({ invite: { event_type: 'dm_invite', payload: {} } }) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Import Signed Invite' }));

    expect(
      await screen.findByText(/INVITE PINNED for !sb_attested \(invitefp\.\.tested\)\./i),
    ).toBeInTheDocument();
  });

  it('announces compat invite imports as TOFU PINNED with backend detail', async () => {
    mocks.importWormholeDmInvite.mockResolvedValueOnce({
      ok: true,
      peer_id: '!sb_compat',
      trust_fingerprint: 'invitefp-compat',
      trust_level: 'tofu_pinned',
      detail: 'legacy invite imported as tofu_pinned; SAS verification required before first contact',
      contact: {},
    });

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));
    expect(await screen.findByText('Import Verified Invite')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Signed Invite JSON/i), {
      target: { value: JSON.stringify({ invite: { event_type: 'dm_invite', payload: {} } }) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Import Signed Invite' }));

    expect(
      await screen.findByText(/TOFU PINNED for !sb_compat \(invitefp\.\.compat\)\./i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/legacy invite imported as tofu_pinned; SAS verification required before first contact/i),
    ).toBeInTheDocument();
  });

  it('surfaces stable root continuity breaks on invite re-import', async () => {
    contactsState = {
      '!sb_attested': {
        alias: 'Pinned Peer',
        blocked: false,
        trust_level: 'continuity_broken',
        invitePinnedTrustFingerprint: 'oldfingerprint123456',
        invitePinnedRootFingerprint: 'rootold123456',
        remotePrekeyFingerprint: 'newfingerprint654321',
        remotePrekeyObservedFingerprint: 'newfingerprint654321',
        remotePrekeyRootFingerprint: 'rootold123456',
        remotePrekeyObservedRootFingerprint: 'rootnew654321',
        remotePrekeyRootMismatch: true,
      },
    };
    const error = Object.assign(
      new Error(
        'signed invite root continuity mismatch; re-verify SAS or replace the signed invite before trusting this root change',
      ),
      {
        result: {
          ok: false,
          peer_id: '!sb_attested',
          trust_level: 'continuity_broken',
          detail:
            'signed invite root continuity mismatch; re-verify SAS or replace the signed invite before trusting this root change',
          contact: {},
        },
      },
    );
    mocks.importWormholeDmInvite.mockRejectedValueOnce(error);

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));
    expect(await screen.findByText('Import Verified Invite')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Signed Invite JSON/i), {
      target: { value: JSON.stringify({ invite: { event_type: 'dm_invite', payload: {} } }) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Import Signed Invite' }));

    expect(
      await screen.findByText(/CONTINUITY BROKEN for Pinned Peer\. Stable root continuity changed\./i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/re-verify SAS in Dead Drop or replace the signed invite before trusting this contact again/i),
    ).toBeInTheDocument();
  });

  it('uses non-blocking secure-mail startup language while the DM lane warms', async () => {
    mocks.fetchWormholeStatus.mockResolvedValueOnce({ ready: false, transport_tier: 'public_degraded' });
    mocks.prepareWormholeInteractiveLane.mockImplementation(
      () =>
        new Promise(() => {
          /* keep background warm-up pending for this assertion */
        }),
    );

    renderMessagesView();

    expect(
      await screen.findByText(/Preparing secure mail in the background/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/LOCKED/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/enter the Wormhole/i)).not.toBeInTheDocument();
  });
});
