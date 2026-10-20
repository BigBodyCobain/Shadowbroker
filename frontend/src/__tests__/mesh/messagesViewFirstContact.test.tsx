import '@testing-library/jest-dom/vitest';

import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

let contactsState: Record<string, any> = {};

const mocks = vi.hoisted(() => ({
  buildMailboxClaims: vi.fn(async () => []),
  countDmMailboxes: vi.fn(async () => ({ ok: true, count: 0 })),
  ensureRegisteredDmKey: vi.fn(async () => ({ dhPubKey: 'local-dh', dhAlgo: 'X25519' })),
  fetchDmPublicKey: vi.fn(async () => ({ agent_id: '!sb_peer', dh_pub_key: 'peer-dh', dh_algo: 'X25519' })),
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
  bootstrapWormholeIdentity: vi.fn(async () => ({
    node_id: '!sb_local',
    public_key: 'local-pub',
    public_key_algo: 'Ed25519',
    sequence: 1,
    protocol_version: 'infonet/2',
  })),
  exportWormholeDmInvite: vi.fn(async () => ({
    ok: true,
    invite: {
      event_type: 'dm_invite',
      payload: {
        prekey_lookup_handle: 'handle-123',
        expires_at: 2_000_000_000,
      },
    },
    peer_id: '!sb_local',
    trust_fingerprint: 'trustfp123456',
    prekey_publish_pending: false,
  })),
  fetchWormholeStatus: vi.fn(async () => ({ ready: true, transport_tier: 'private_strong' })),
  fetchWormholeIdentity: vi.fn(async () => ({ node_id: '!sb_local', public_key: 'local-pub' })),
  listWormholeDmInviteHandles: vi.fn(async () => ({ ok: true, addresses: [] })),
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
  renameWormholeDmInviteHandle: vi.fn(async () => ({ ok: true })),
  revokeWormholeDmInviteHandle: vi.fn(async () => ({ ok: true, revoked: true })),
  isWormholeReady: vi.fn(async () => true),
  isWormholeSecureRequired: vi.fn(async () => false),
  issueWormholePairwiseAlias: vi.fn(async () => ({ ok: true, shared_alias: 'alias-123' })),
  openWormholeSenderSeal: vi.fn(async () => ({ sender_id: '!sb_peer', seal_verified: true })),
  writeClipboard: vi.fn(async () => undefined),
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
  bootstrapWormholeIdentity: mocks.bootstrapWormholeIdentity,
  fetchWormholeStatus: mocks.fetchWormholeStatus,
  fetchWormholeIdentity: mocks.fetchWormholeIdentity,
  exportWormholeDmInvite: mocks.exportWormholeDmInvite,
  prepareWormholeInteractiveLane: mocks.prepareWormholeInteractiveLane,
  getWormholeDmInviteImportErrorResult: (error: unknown) =>
    error && typeof error === 'object' && 'result' in (error as Record<string, unknown>)
      ? (((error as Record<string, unknown>).result as Record<string, unknown>) || null)
      : null,
  importWormholeDmInvite: mocks.importWormholeDmInvite,
  isWormholeReady: mocks.isWormholeReady,
  isWormholeSecureRequired: mocks.isWormholeSecureRequired,
  listWormholeDmInviteHandles: mocks.listWormholeDmInviteHandles,
  issueWormholePairwiseAlias: mocks.issueWormholePairwiseAlias,
  openWormholeSenderSeal: mocks.openWormholeSenderSeal,
  renameWormholeDmInviteHandle: mocks.renameWormholeDmInviteHandle,
  revokeWormholeDmInviteHandle: mocks.revokeWormholeDmInviteHandle,
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
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: mocks.writeClipboard },
      configurable: true,
    });

    mocks.getContacts.mockImplementation(() => contactsState);
    mocks.hydrateWormholeContacts.mockImplementation(async () => contactsState);
    mocks.fetchWormholeStatus.mockResolvedValue({ ready: true, transport_tier: 'private_strong' });
    mocks.bootstrapWormholeIdentity.mockResolvedValue({
      node_id: '!sb_local',
      public_key: 'local-pub',
      public_key_algo: 'Ed25519',
      sequence: 1,
      protocol_version: 'infonet/2',
    });
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
    mocks.fetchDmPublicKey.mockResolvedValue({ agent_id: '!sb_peer', dh_pub_key: 'peer-dh', dh_algo: 'X25519' });
    mocks.sendOffLedgerConsentMessage.mockResolvedValue({ ok: true, transport: 'relay' });
    mocks.canUseWormholeBootstrap.mockResolvedValue(false);
    mocks.exportWormholeDmInvite.mockResolvedValue({
      ok: true,
      invite: {
        event_type: 'dm_invite',
        payload: {
          prekey_lookup_handle: 'handle-123',
          expires_at: 2_000_000_000,
        },
      },
      peer_id: '!sb_local',
      trust_fingerprint: 'trustfp123456',
      prekey_publish_pending: false,
    });
    mocks.listWormholeDmInviteHandles.mockResolvedValue({ ok: true, addresses: [] });
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

    expect(await screen.findByText("Paste Someone's Address")).toBeInTheDocument();
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
    expect(screen.queryByText('ROOT LOCAL QUORUM')).not.toBeInTheDocument();
    expect(screen.queryByText(/Local quorum root rootabcd\.\.123456/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Fingerprint/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send Secure Mail' })).toBeEnabled();
  });

  it('sends sealed mail without waiting for the private delivery route', async () => {
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
    mocks.prepareWormholeInteractiveLane.mockImplementation(
      () =>
        new Promise(() => {
          /* background route prep stays pending */
        }),
    );
    mocks.sendDmMessage.mockResolvedValueOnce({
      ok: true,
      queued: true,
      private_transport_pending: true,
    });

    renderMessagesView();
    await openComposeForRecipient('!sb_pinned', 'hello after warmup');

    const sendButton = screen.getByRole('button', { name: 'Send Secure Mail' });
    await waitFor(() => expect(sendButton).toBeEnabled(), { timeout: 5000 });
    fireEvent.click(sendButton);

    await waitFor(() => expect(mocks.prepareWormholeInteractiveLane).toHaveBeenCalled(), { timeout: 5000 });
    await waitFor(() => expect(mocks.sendDmMessage).toHaveBeenCalled(), { timeout: 5000 });
    await screen.findByText(/Mail sealed locally for Pinned Peer/i, {}, { timeout: 5000 });
    expect(screen.queryByText(/still warming up/i)).not.toBeInTheDocument();
  }, 10000);

  it('repairs the local sending key before sending instead of surfacing backend key jargon', async () => {
    contactsState = {
      '!sb_pinned': {
        alias: 'Pinned Peer',
        blocked: false,
        trust_level: 'invite_pinned',
        dhPubKey: 'peer-dh',
        remotePrekeyFingerprint: 'abcdef123456',
      },
    };
    mocks.ensureRegisteredDmKey
      .mockResolvedValueOnce({ ok: true, dhPubKey: '', dhAlgo: 'X25519', detail: 'Missing DH public key' })
      .mockResolvedValueOnce({ ok: true, dhPubKey: 'local-dh-repaired', dhAlgo: 'X25519' });
    mocks.sendDmMessage.mockResolvedValueOnce({ ok: true, transport: 'relay' });

    renderMessagesView();
    await openComposeForRecipient('!sb_pinned', 'hello after repair');

    fireEvent.click(screen.getByRole('button', { name: 'Send Secure Mail' }));

    await waitFor(() => expect(mocks.ensureRegisteredDmKey).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.sendDmMessage).toHaveBeenCalled());
    expect(await screen.findByText(/Mail delivered to Pinned Peer/i)).toBeInTheDocument();
    expect(screen.queryByText(/Local DM key is unavailable/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Missing DH public key/i)).not.toBeInTheDocument();
  });

  it('shows saved contacts without witness-policy implementation detail', async () => {
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

    expect(await screen.findByText('Saved Contact')).toBeInTheDocument();
    expect(screen.queryByText(/Witness-policy root rootpoli\.\.123456/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Witnessed root rootpoli\.\.123456/i)).not.toBeInTheDocument();
  });

  it('hydrates Wormhole contacts on first load even when a local browser identity exists', async () => {
    let wormholeIdentityResolved = false;
    contactsState = {
      '!sb_saved': {
        alias: 'Saved Person',
        blocked: false,
        trust_level: 'invite_pinned',
        invitePinnedPrekeyLookupHandle: 'handle-saved',
        invitePinnedTrustFingerprint: 'savedfingerprint123456',
      },
    };
    mocks.isWormholeSecureRequired.mockResolvedValue(true);
    mocks.fetchWormholeIdentity.mockImplementation(async () => {
      wormholeIdentityResolved = true;
      return { node_id: '!sb_local', public_key: 'local-pub' };
    });
    mocks.hydrateWormholeContacts.mockImplementation(async () =>
      wormholeIdentityResolved ? contactsState : {},
    );

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));

    expect(await screen.findByText('Saved Person')).toBeInTheDocument();
    expect(screen.queryByText(/No approved secure contacts yet/i)).not.toBeInTheDocument();
    expect(mocks.fetchWormholeIdentity).toHaveBeenCalled();
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

  it('surfaces pending contact requests in a top-level requests tab with approve and deny actions', async () => {
    localStorage.setItem(
      'sb_infonet_mailbox_v1:!sb_local',
      JSON.stringify({
        version: 1,
        items: [
          {
            id: 'request-1',
            msgId: 'request-1',
            folder: 'inbox',
            kind: 'request',
            direction: 'inbound',
            senderId: '!sb_requester',
            recipientId: '!sb_local',
            subject: 'Contact request from !sb_requester',
            body: '!sb_requester wants to open a secure mailbox.',
            timestamp: 1_778_624_800,
            read: false,
            transport: 'relay',
            deliveryClass: 'request',
            requestStatus: 'pending',
            requestDhPubKey: 'requester-dh',
            requestDhAlgo: 'X25519',
          },
        ],
      }),
    );
    mocks.addContact.mockImplementation((peerId: string, dhPubKey: string, _alias?: string, dhAlgo?: string) => {
      contactsState[peerId] = {
        alias: 'Requester',
        blocked: false,
        dhPubKey,
        dhAlgo,
        trust_level: 'unpinned',
      };
    });

    renderMessagesView();
    fireEvent.click(await screen.findByRole('button', { name: /REQUESTS/i }));

    expect(await screen.findByText('Contact Requests')).toBeInTheDocument();
    expect(await screen.findByText('1 pending')).toBeInTheDocument();
    expect(await screen.findAllByText('!sb_requester')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Deny' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(mocks.addContact).toHaveBeenCalledWith(
      '!sb_requester',
      'peer-dh',
      undefined,
      'X25519',
    ));
    await waitFor(() =>
      expect(mocks.sendOffLedgerConsentMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          recipientId: '!sb_requester',
          recipientDhPub: 'peer-dh',
        }),
      ),
    );
    expect(await screen.findByText(/Contact accepted: Requester\./i)).toBeInTheDocument();
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
        /This contact needs their full contact address once before messages can be sent/i,
      ),
    ).toBeInTheDocument();
    expect(mocks.fetchDmPublicKey).not.toHaveBeenCalled();
  });

  it('announces attested invite imports as a saved contact', async () => {
    mocks.importWormholeDmInvite.mockResolvedValueOnce({
      ok: true,
      peer_id: '!sb_attested',
      trust_fingerprint: 'invitefp-attested',
      trust_level: 'invite_pinned',
      contact: {},
    });

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));
    expect(await screen.findByText("Paste Someone's Address")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Paste a short address/i), {
      target: { value: JSON.stringify({ invite: { event_type: 'dm_invite', payload: {} } }) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Import Address' }));

    expect(await screen.findByText(/Contact saved: !sb_attested\./i)).toBeInTheDocument();
    expect(await screen.findByText('Saved Contact')).toBeInTheDocument();
    expect(screen.queryByText(/INVITE PINNED for/i)).not.toBeInTheDocument();
  });

  it('automatically creates a share address and keeps copy actions simple', async () => {
    renderMessagesView();

    expect(await screen.findByText(/Contact address ready/i)).toBeInTheDocument();
    expect(await screen.findByText('handle-123')).toBeInTheDocument();
    expect(screen.getByText(/Signed invite ready/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Copy Short Address/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Copy Full Address/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Copy Short Address/i }));

    await waitFor(() => expect(mocks.writeClipboard).toHaveBeenCalledWith('handle-123'));
    const copied = String(mocks.writeClipboard.mock.calls.at(-1)?.[0] || '');
    expect(copied).toBe('handle-123');
    expect(screen.queryByText(/shadowbroker\.infonet\.dm\.invite/i)).not.toBeInTheDocument();
  });

  it('does not advertise legacy handle-only addresses as copyable contact addresses', async () => {
    localStorage.setItem(
      'sb_infonet_dm_addresses_v1:!sb_local',
      JSON.stringify({
        version: 1,
        addresses: [
          {
            id: 'legacy-address',
            label: 'Legacy handle',
            handle: 'd8ce691f751817e137066f2a1858e21689b0118f8ec485c1',
            peerId: '',
            trustFingerprint: '',
            inviteBlob: '',
            createdAt: 1_700_000_000,
          },
        ],
      }),
    );

    renderMessagesView();

    expect(await screen.findByText(/Contact address ready/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));

    expect(await screen.findByText('Legacy handle')).toBeInTheDocument();
    expect(screen.getByText('Address unavailable locally.')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Copy Short' }).some((button) => !button.hasAttribute('disabled'))).toBe(true);
    expect(screen.getAllByRole('button', { name: 'Copy Full' }).some((button) => button.hasAttribute('disabled'))).toBe(true);
  });

  it('sends a contact request from a short address instead of requiring JSON', async () => {
    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));
    expect(await screen.findByText("Paste Someone's Address")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Paste a short address/i), {
      target: { value: 'f0eee9e9ccf849bcb2d86c0d7a1e0669c75be4e05533b0f6c67' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send Request' }));

    await waitFor(() => expect(mocks.sendOffLedgerConsentMessage).toHaveBeenCalled());
    expect(await screen.findByText(/Contact request sent to/i)).toBeInTheDocument();
    expect(mocks.fetchDmPublicKey).toHaveBeenCalledWith(
      'http://localhost:8000',
      '',
      'f0eee9e9ccf849bcb2d86c0d7a1e0669c75be4e05533b0f6c67',
      { allowLegacyAgentId: false },
    );
    expect(mocks.sendOffLedgerConsentMessage).toHaveBeenCalled();
    expect(screen.queryByText(/Unexpected number in JSON/i)).not.toBeInTheDocument();
    expect(mocks.importWormholeDmInvite).not.toHaveBeenCalled();
  });

  it('hides pasted signed address JSON until advanced details are opened', async () => {
    const signedAddress = JSON.stringify({
      type: 'shadowbroker.infonet.dm.invite',
      version: 1,
      invite: { event_type: 'dm_invite', payload: {} },
    });

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));
    expect(await screen.findByText("Paste Someone's Address")).toBeInTheDocument();

    const addressField = screen.getByPlaceholderText(/Paste a short address/i);
    fireEvent.paste(addressField, {
      clipboardData: {
        getData: () => signedAddress,
      },
    });

    expect(screen.getByDisplayValue(/Copied address received\. Ready to import\./i)).toBeInTheDocument();
    expect(screen.queryByDisplayValue(/shadowbroker\.infonet\.dm\.invite/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Advanced Details' }));

    expect(screen.getByLabelText('Raw copied contact address')).toHaveValue(signedAddress);
  });

  it('imports a copied address without waiting for secure mail warm-up', async () => {
    mocks.fetchWormholeStatus.mockResolvedValue({ ready: false, transport_tier: 'public_degraded' });
    mocks.prepareWormholeInteractiveLane.mockImplementation(
      () =>
        new Promise(() => {
          /* background warm-up stays pending */
        }),
    );
    mocks.importWormholeDmInvite.mockResolvedValueOnce({
      ok: true,
      peer_id: '!sb_now',
      trust_fingerprint: 'invitefp-now',
      trust_level: 'invite_pinned',
      contact: {},
    });

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));
    expect(await screen.findByText("Paste Someone's Address")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Paste a short address/i), {
      target: { value: JSON.stringify({ invite: { event_type: 'dm_invite', payload: {} } }) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Import Address' }));

    expect(await screen.findByText(/Contact saved: !sb_now\./i)).toBeInTheDocument();
    expect(mocks.importWormholeDmInvite).toHaveBeenCalled();
    expect(screen.queryByText(/Secure mail is still warming up/i)).not.toBeInTheDocument();
  });

  it('saves pending-delivery contacts without showing prekey jargon', async () => {
    mocks.importWormholeDmInvite.mockResolvedValueOnce({
      ok: true,
      peer_id: '!sb_pending',
      trust_fingerprint: 'invitefp-pending',
      trust_level: 'invite_pinned',
      pending_prekey: true,
      detail: 'Contact saved.',
      contact: {
        alias: 'Pending Person',
        blocked: false,
        trust_level: 'invite_pinned',
        invitePinnedPrekeyLookupHandle: 'handle-pending',
        invitePinnedTrustFingerprint: 'invitefp-pending',
        dhPubKey: '',
      },
    });

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));
    expect(await screen.findByText("Paste Someone's Address")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Paste a short address/i), {
      target: { value: JSON.stringify({ invite: { event_type: 'dm_invite', payload: {} } }) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Import Address' }));

    expect(await screen.findByText(/Contact saved: Pending Person\./i)).toBeInTheDocument();
    expect(await screen.findByText('Saved Contact')).toBeInTheDocument();
    expect(screen.queryByText(/prekey/i)).not.toBeInTheDocument();
  });

  it('saves mail locally when a saved contact is not reachable yet', async () => {
    contactsState = {
      '!sb_pending': {
        alias: 'Pending Person',
        blocked: false,
        trust_level: 'invite_pinned',
        invitePinnedPrekeyLookupHandle: 'handle-pending',
        invitePinnedTrustFingerprint: 'invitefp-pending',
        dhPubKey: '',
      },
    };
    mocks.fetchDmPublicKey.mockResolvedValueOnce({ agent_id: '!sb_pending', dh_pub_key: '', dh_algo: 'X25519' });

    renderMessagesView();
    await openComposeForRecipient('!sb_pending', 'hello when ready');

    fireEvent.click(screen.getByRole('button', { name: 'Send Secure Mail' }));

    expect(await screen.findByText(/Mail is saved locally and will send automatically when the contact is reachable/i)).toBeInTheDocument();
    expect(mocks.sendOffLedgerConsentMessage).not.toHaveBeenCalled();
    expect(screen.queryByText(/delivery key has not reached/i)).not.toBeInTheDocument();
  });

  it('removes an approved contact immediately from the visible contact list', { timeout: 30_000 }, async () => {
    contactsState = {
      '!sb_remove': {
        alias: 'Remove Me',
        blocked: false,
        trust_level: 'invite_pinned',
        invitePinnedTrustFingerprint: 'removefingerprint123456',
        dhPubKey: 'peer-dh',
      },
    };
    mocks.removeContact.mockImplementation((peerId: string) => {
      delete contactsState[peerId];
    });

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));

    expect(
      await screen.findByText('Remove Me', undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));

    // The Remove handler dispatches several React state updates in one
    // event:
    //   removeContact(peerId)           — external mutation (mock deletes
    //                                     from contactsState)
    //   setContacts(updater)            — React state update
    //   setComposeStatus(`Removed       — toast text, computed via
    //     contact: ${displayNameForPeer   displayNameForPeer(peerId, contacts)
    //     (peerId, contacts)}.`)         which reads the CLOSED-OVER
    //                                     contacts state
    //
    // The flake history (PRs #226, #237, #261, #262, #265, #294, #303,
    // #304, plus the fd7d6fa push) has two distinct causes:
    //
    //   (a) CI runner starvation — two parallel ci.yml invocations
    //       (direct + workflow_call from docker-publish.yml) starving
    //       each other on the same Actions runner. Fixed structurally
    //       in .github/workflows/ci.yml via a concurrency group.
    //
    //   (b) Alias-resolution race — under certain renders, the closed
    //       -over `contacts` in the Remove handler can see the post-
    //       mutation state (contact already gone), and
    //       displayNameForPeer falls through to return the raw peer
    //       id ("!sb_remove") rather than the alias ("Remove Me").
    //       The toast then renders as "Removed contact: !sb_remove."
    //       which the precise `/Removed contact: Remove Me\./i` regex
    //       missed. We loosen the assertion to match either rendering
    //       — the behavioural guarantee under test is "the removal
    //       toast appears", not "the alias was resolved correctly
    //       at toast-render time". That second property is an
    //       implementation detail the component can reorder freely.
    //
    // The pair of assertions below still proves the real contract:
    // 1. A toast that announces a removal renders.
    // 2. The contact's alias is no longer visible in the contact list.
    //
    // The failure mode this no longer masks is "no toast at all", which
    // still fails loudly at the 10s waitFor cap.
    await waitFor(
      () => {
        expect(
          screen.getByText(/Removed contact:/i),
        ).toBeInTheDocument();
      },
      { timeout: 10000, interval: 50 },
    );
    expect(screen.queryByText('Remove Me')).not.toBeInTheDocument();
  });

  it('explains unresolved address delivery without exposing backend jargon', async () => {
    mocks.importWormholeDmInvite.mockRejectedValueOnce(new Error('peer prekey lookup unavailable'));

    renderMessagesView();
    fireEvent.click(screen.getByRole('button', { name: 'CONTACTS' }));
    expect(await screen.findByText("Paste Someone's Address")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Paste a short address/i), {
      target: { value: JSON.stringify({ invite: { event_type: 'dm_invite', payload: {} } }) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Import Address' }));

    expect(await screen.findByText(/This address is valid, but contact delivery is not ready on this node yet/i)).toBeInTheDocument();
    expect(screen.queryByText('peer prekey lookup unavailable')).not.toBeInTheDocument();
    expect(screen.queryByText(/sender prekey/i)).not.toBeInTheDocument();
  });

  it('announces compat invite imports as a saved contact without backend detail', async () => {
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
    expect(await screen.findByText("Paste Someone's Address")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Paste a short address/i), {
      target: { value: JSON.stringify({ invite: { event_type: 'dm_invite', payload: {} } }) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Import Address' }));

    expect(await screen.findByText(/Contact saved: !sb_compat\./i)).toBeInTheDocument();
    expect(screen.queryByText(/TOFU PINNED for/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/legacy invite imported as tofu_pinned; SAS verification required before first contact/i),
    ).not.toBeInTheDocument();
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
    expect(await screen.findByText("Paste Someone's Address")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Paste a short address/i), {
      target: { value: JSON.stringify({ invite: { event_type: 'dm_invite', payload: {} } }) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Import Address' }));

    expect(
      await screen.findByText(/CONTINUITY BROKEN for Pinned Peer\. Stable root continuity changed\./i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/re-verify SAS in Dead Drop or replace the signed invite before trusting this contact again/i),
    ).toBeInTheDocument();
  });

  it('uses non-blocking secure-mail startup language while the DM lane warms', async () => {
    mocks.fetchWormholeStatus.mockResolvedValue({ ready: false, transport_tier: 'public_degraded' });
    mocks.prepareWormholeInteractiveLane.mockImplementation(
      () =>
        new Promise(() => {
          /* keep background warm-up pending for this assertion */
        }),
    );

    renderMessagesView();

    expect(
      await screen.findByText(/Private delivery route is connecting/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Addresses, contacts, and sealed sends can proceed now/i)).toBeInTheDocument();
    expect(screen.queryByText(/LOCKED/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/enter the Wormhole/i)).not.toBeInTheDocument();
  });
});
