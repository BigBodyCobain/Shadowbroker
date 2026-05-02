'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Ban,
  Check,
  ChevronLeft,
  Inbox,
  Mail,
  PencilLine,
  RefreshCcw,
  Reply,
  Send,
  ShieldOff,
  Trash2,
  UserPlus,
  Users,
  X,
} from 'lucide-react';

import { API_BASE } from '@/lib/api';
import { classifyTick, MAX_CATCHUP_POLLS } from '@/lib/dmPollScheduler';
import {
  buildMailboxClaims,
  countDmMailboxes,
  ensureRegisteredDmKey,
  fetchDmPublicKey,
  pollDmMailboxes,
  sendDmMessage,
  sendOffLedgerConsentMessage,
  sharedMailboxToken,
  type DmMessageEnvelope,
} from '@/mesh/meshDmClient';
import {
  allDmPeerIds,
  buildContactAcceptMessage,
  buildContactDenyMessage,
  buildContactOfferMessage,
  generateSharedAlias,
  mergeAliasHistory,
  parseAliasRotateMessage,
  parseDmConsentMessage,
  preferredDmPeerId,
  type DmConsentMessage,
} from '@/mesh/meshDmConsent';
import {
  purgeBrowserDmState,
  ratchetDecryptDM,
  ratchetEncryptDM,
} from '@/mesh/meshDmWorkerClient';
import {
  addContact,
  blockContact,
  decryptDM,
  decryptSenderSealPayloadLocally,
  deriveSharedKey,
  encryptDM,
  getContacts,
  getDHAlgo,
  getNodeIdentity,
  hasSovereignty,
  hydrateWormholeContacts,
  purgeBrowserContactGraph,
  purgeBrowserSigningMaterial,
  removeContact,
  unblockContact,
  unwrapSenderSealPayload,
  updateContact,
  verifyNodeIdBindingFromPublicKey,
  verifyRawSignature,
  type Contact,
  type NodeIdentity,
} from '@/mesh/meshIdentity';
import {
  getSenderRecoveryState,
  recoverSenderSealWithFallback,
  requiresSenderRecovery,
  shouldKeepUnresolvedRequestVisible,
  shouldPromoteRecoveredSenderForBootstrap,
  shouldPromoteRecoveredSenderForKnownContact,
  type RecoveredSenderSeal,
} from '@/mesh/requestSenderRecovery';
import {
  bootstrapDecryptAccessRequest,
  bootstrapEncryptAccessRequest,
  canUseWormholeBootstrap,
} from '@/mesh/wormholeDmBootstrapClient';
import {
  fetchWormholeStatus,
  fetchWormholeIdentity,
  getWormholeDmInviteImportErrorResult,
  importWormholeDmInvite,
  isWormholeReady,
  isWormholeSecureRequired,
  prepareWormholeInteractiveLane,
  issueWormholePairwiseAlias,
  openWormholeSenderSeal,
} from '@/mesh/wormholeIdentityClient';
import {
  updatePrivateDeliveryAction,
  type PrivateDeliveryItem,
  type PrivateDeliverySummary,
} from '@/mesh/wormholeClient';
import {
  buildDmTrustHint,
  dmTrustPrimaryActionLabel,
  requiresVerifiedFirstContact,
} from '@/mesh/meshPrivacyHints';
import {
  getContactTrustSummary,
  rootWitnessBadgeLabel,
  rootWitnessContinuityLabel,
} from '@/mesh/contactTrustSummary';

type ViewTab = 'mailbox' | 'compose' | 'contacts' | 'restricted';
type MailFolder = 'inbox' | 'sent' | 'junk' | 'spam' | 'trash';
type MailKind = 'mail' | 'request' | 'system';

interface MessagesViewProps {
  onBack: () => void;
  onOpenDeadDrop?: (peerId: string, options?: { showSas?: boolean }) => void;
}

interface MailItem {
  id: string;
  msgId: string;
  folder: MailFolder;
  kind: MailKind;
  direction: 'inbound' | 'outbound' | 'local';
  senderId: string;
  recipientId: string;
  subject: string;
  body: string;
  timestamp: number;
  read: boolean;
  transport?: 'relay' | 'reticulum' | '';
  deliveryClass?: 'request' | 'shared' | '';
  requestStatus?: 'pending' | 'accepted' | 'denied' | 'unresolved';
  requestDhPubKey?: string;
  requestDhAlgo?: string;
  requestGeoHint?: string;
  recoveryState?: 'pending' | 'verified' | 'failed';
  locked?: boolean;
}

interface MailboxSnapshot {
  version: 1;
  items: MailItem[];
}

interface ComposeDraft {
  recipient: string;
  subject: string;
  body: string;
}

const FOLDERS: Array<{ key: MailFolder; label: string; icon: React.ReactNode }> = [
  { key: 'inbox', label: 'INBOX', icon: <Inbox size={14} className="mr-2" /> },
  { key: 'sent', label: 'SENT', icon: <Send size={14} className="mr-2" /> },
  { key: 'junk', label: 'JUNK', icon: <ShieldOff size={14} className="mr-2" /> },
  { key: 'spam', label: 'SPAM', icon: <Ban size={14} className="mr-2" /> },
  { key: 'trash', label: 'TRASH', icon: <Trash2 size={14} className="mr-2" /> },
];

const MAIL_POLL_BASE_MS = 12_000;
const STORAGE_VERSION = 1;
const SHADOWBROKER_WELCOME_ID = 'shadowbroker-welcome';
const MAIL_SUBJECT_PREFIX = 'MAIL_SUBJECT:';

function randomId(prefix: string): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function mailboxStorageKey(scopeId: string): string {
  return `sb_infonet_mailbox_v1:${scopeId}`;
}

function sortMessages(items: MailItem[]): MailItem[] {
  return [...items].sort((a, b) => {
    if (b.timestamp !== a.timestamp) {
      return b.timestamp - a.timestamp;
    }
    return a.id.localeCompare(b.id);
  });
}

function createShadowbrokerWelcomeMail(): MailItem {
  return {
    id: SHADOWBROKER_WELCOME_ID,
    msgId: SHADOWBROKER_WELCOME_ID,
    folder: 'inbox',
    kind: 'system',
    direction: 'local',
    senderId: 'shadowbroker',
    recipientId: 'local',
    subject: 'How secure mail works',
    body: [
      'Secure Messages rides the off-chain DM lane.',
      '',
      '- Add or accept a contact request before full mail can flow.',
      '- Once a contact is approved, mail moves through the shared DM mailbox.',
      '- Inbox, Junk, Spam, and Trash are local client folders for this install.',
      '- Moving mail to Trash or deleting it does not touch the public hashchain.',
      '- If the private lane is still starting, mail waits locally and resumes when it is ready.',
    ].join('\n'),
    timestamp: Math.floor(Date.now() / 1000),
    read: false,
    transport: '',
    deliveryClass: '',
  };
}

function ensureSeedMail(items: MailItem[]): MailItem[] {
  if (items.some((item) => item.id === SHADOWBROKER_WELCOME_ID)) {
    return sortMessages(items);
  }
  return sortMessages([createShadowbrokerWelcomeMail(), ...items]);
}

function loadMailbox(scopeId: string): MailItem[] {
  if (typeof window === 'undefined') {
    return ensureSeedMail([]);
  }
  try {
    const raw = localStorage.getItem(mailboxStorageKey(scopeId));
    if (!raw) {
      return ensureSeedMail([]);
    }
    const parsed = JSON.parse(raw) as MailboxSnapshot;
    if (parsed?.version !== STORAGE_VERSION || !Array.isArray(parsed.items)) {
      return ensureSeedMail([]);
    }
    return ensureSeedMail(parsed.items);
  } catch {
    return ensureSeedMail([]);
  }
}

function saveMailbox(scopeId: string, items: MailItem[]): void {
  if (typeof window === 'undefined') return;
  try {
    const payload: MailboxSnapshot = {
      version: STORAGE_VERSION,
      items,
    };
    localStorage.setItem(mailboxStorageKey(scopeId), JSON.stringify(payload));
  } catch {
    /* ignore */
  }
}

function encodeMailPayload(subject: string, body: string): string {
  const cleanSubject = subject.trim() || 'Secure Message';
  return `${MAIL_SUBJECT_PREFIX}${cleanSubject}\n\n${body.trim()}`;
}

function decodeMailPayload(plaintext: string): { subject: string; body: string } {
  const value = String(plaintext || '');
  if (value.startsWith(MAIL_SUBJECT_PREFIX)) {
    const withoutPrefix = value.slice(MAIL_SUBJECT_PREFIX.length);
    const [subjectLine, ...rest] = withoutPrefix.split(/\r?\n/);
    return {
      subject: subjectLine.trim() || 'Secure Message',
      body: rest.join('\n').replace(/^\n+/, '').trim(),
    };
  }
  const lines = value.split(/\r?\n/);
  const firstLine = lines.find((line) => line.trim()) || 'Secure Message';
  return {
    subject: firstLine.trim().slice(0, 96) || 'Secure Message',
    body: value.trim(),
  };
}

function displayNameForPeer(peerId: string, contacts: Record<string, Contact>): string {
  if (!peerId) return 'unknown';
  if (peerId === 'shadowbroker') return 'shadowbroker';
  const contact = contacts[peerId];
  if (contact?.alias) return contact.alias;
  return peerId;
}

function shortFingerprint(value: string): string {
  const fingerprint = String(value || '').trim().toLowerCase();
  if (!fingerprint) return 'unknown';
  if (fingerprint.length <= 14) return fingerprint;
  return `${fingerprint.slice(0, 8)}..${fingerprint.slice(-6)}`;
}

function rootTrustLabel(summary: ReturnType<typeof getContactTrustSummary>): string {
  return rootWitnessBadgeLabel(summary);
}

function contactTrustSummary(contact: Contact): { label: string; tone: string; detail: string } | null {
  const summary = getContactTrustSummary(contact);
  if (!summary) return null;
  if (summary.transparencyConflict) {
    return {
      label: 'HISTORY CONFLICT',
      tone: 'border-red-500/30 text-red-300 bg-red-950/20',
      detail: 'Prekey transparency history conflicted. Trust stays degraded until you acknowledge the changed fingerprint.',
    };
  }
  if (summary.state === 'invite_pinned') {
    const root = shortFingerprint(
      contact.invitePinnedRootFingerprint || contact.remotePrekeyRootFingerprint || '',
    );
    return {
      label: 'INVITE PINNED',
      tone: 'border-emerald-500/30 text-emerald-300 bg-emerald-950/20',
      detail: `${summary.rootAttested ? `${rootTrustLabel(summary)} ${root} • ` : ''}Fingerprint ${shortFingerprint(contact.invitePinnedTrustFingerprint || contact.remotePrekeyFingerprint || '')}${contact.remotePrekeyLookupMode === 'legacy_agent_id' ? ' • legacy lookup' : ''}`,
    };
  }
  if (summary.state === 'sas_verified') {
    const root = shortFingerprint(
      contact.invitePinnedRootFingerprint || contact.remotePrekeyRootFingerprint || '',
    );
    return {
      label: 'SAS VERIFIED',
      tone: 'border-cyan-500/30 text-cyan-300 bg-cyan-950/20',
      detail: `${summary.rootAttested ? `${rootTrustLabel(summary)} ${root} • ` : ''}Fingerprint ${shortFingerprint(contact.remotePrekeyFingerprint || '')}${contact.remotePrekeyLookupMode === 'legacy_agent_id' ? ' • legacy lookup' : ''}`,
    };
  }
  if (
    summary.state === 'mismatch' ||
    summary.state === 'continuity_broken' ||
    summary.registryMismatch
  ) {
    const observedRoot = shortFingerprint(contact.remotePrekeyObservedRootFingerprint || '');
    return {
      label: summary.state === 'continuity_broken' ? 'CONTINUITY BROKEN' : 'REVERIFY',
      tone: 'border-red-500/30 text-red-300 bg-red-950/20',
      detail: `${summary.rootMismatch ? `Observed root ${observedRoot} • ` : ''}Observed ${shortFingerprint(contact.remotePrekeyObservedFingerprint || '')}${contact.remotePrekeyLookupMode === 'legacy_agent_id' ? ' • legacy lookup' : ''}`,
    };
  }
  if (contact.remotePrekeyLookupMode === 'legacy_agent_id') {
    return {
      label: 'LEGACY LOOKUP',
      tone: 'border-yellow-500/30 text-yellow-300 bg-yellow-950/20',
      detail: 'This contact still bootstraps through direct agent ID lookup. Import a signed invite to tighten lookup privacy.',
    };
  }
  if (summary.state === 'tofu_pinned') {
    return {
      label: 'TOFU PINNED',
      tone: 'border-amber-500/30 text-amber-300 bg-amber-950/10',
      detail: `Fingerprint ${shortFingerprint(contact.remotePrekeyFingerprint || '')}${contact.remotePrekeyLookupMode === 'legacy_agent_id' ? ' • legacy lookup' : ''}`,
    };
  }
  return null;
}

function contactTrustNextStep(
  contact?: Contact,
): { label: string; detail: string; action: 'import_invite' | 'dead_drop' } | null {
  const summary = getContactTrustSummary(contact);
  if (!summary) return null;
  if (summary.recommendedAction === 'import_invite') {
    return {
      label: dmTrustPrimaryActionLabel(contact),
      detail:
        'Import a signed invite in this panel before treating the contact as a trusted first-contact anchor.',
      action: 'import_invite',
    };
  }
  if (summary.recommendedAction === 'verify_sas') {
    return {
      label: dmTrustPrimaryActionLabel(contact),
      detail: 'Compare the SAS phrase in Dead Drop chat before sensitive mail or contact approval.',
      action: 'dead_drop',
    };
  }
  if (summary.recommendedAction === 'reverify') {
    return {
      label: dmTrustPrimaryActionLabel(contact),
      detail: summary.rootMismatch
        ? `${rootWitnessContinuityLabel(summary)} changed. Re-verify the SAS phrase or replace the signed invite in Dead Drop chat before trusting this contact again.`
        : 'Pause private use and re-verify the SAS phrase or replace the signed invite in Dead Drop chat.',
      action: 'dead_drop',
    };
  }
  if (summary.recommendedAction === 'show_sas') {
    return {
      label: dmTrustPrimaryActionLabel(contact),
      detail: 'Optional: review the SAS phrase in Dead Drop chat for an extra continuity check.',
      action: 'dead_drop',
    };
  }
  return null;
}

function deadDropLaunchOptions(contact?: Contact): { showSas?: boolean } {
  const summary = getContactTrustSummary(contact);
  return {
    showSas: Boolean(summary && summary.recommendedAction !== 'import_invite'),
  };
}

function formatTimestamp(timestamp: number): string {
  if (!timestamp) return 'unknown';
  return new Date(timestamp * 1000).toLocaleString();
}

function messagePreview(item: MailItem): string {
  return item.body.split('\n').find((line) => line.trim())?.trim() || item.subject;
}

function normalizeMailError(message: string): string {
  const detail = String(message || '').trim();
  if (!detail) {
    return 'Secure mail is unavailable right now.';
  }
  const lowered = detail.toLowerCase();
  if (
    lowered.includes('transport tier insufficient') ||
    lowered.includes('dm send requires private transport')
  ) {
    return 'Secure mail needs the Wormhole private lane online before it can sync or send.';
  }
  return detail;
}

async function decryptSenderSeal(
  senderSeal: string,
  candidateDhPub: string,
  recipientId: string,
  expectedMsgId: string,
): Promise<RecoveredSenderSeal> {
  const openLocal = async (): Promise<RecoveredSenderSeal> => {
    try {
      const sealEnvelope = unwrapSenderSealPayload(senderSeal);
      const sealText = await decryptSenderSealPayloadLocally(
        senderSeal,
        candidateDhPub,
        recipientId,
        expectedMsgId,
      );
      if (!sealText) {
        return null;
      }
      const seal = JSON.parse(sealText || '{}');
      const senderId = String(seal.sender_id || '').trim();
      const publicKey = String(seal.public_key || '').trim();
      const publicKeyAlgo = String(seal.public_key_algo || '').trim();
      const sealMsgId = String(seal.msg_id || '').trim();
      const sealTs = Number(seal.timestamp || 0);
      const signature = String(seal.signature || '').trim();
      if (!senderId || !publicKey || !publicKeyAlgo || !sealMsgId || !signature) {
        return null;
      }
      if (sealMsgId !== expectedMsgId) {
        return null;
      }
      const isBound = await verifyNodeIdBindingFromPublicKey(publicKey, senderId);
      if (!isBound) {
        return { sender_id: senderId, seal_verified: false };
      }
      const sealMessage =
        sealEnvelope.version === 'v3'
          ? `seal|v3|${sealMsgId}|${sealTs}|${recipientId}|${String(sealEnvelope.ephemeralPub || '')}`
          : `seal|${sealMsgId}|${sealTs}|${recipientId}`;
      const verified = await verifyRawSignature({
        message: sealMessage,
        signature,
        publicKey,
        publicKeyAlgo,
      });
      return { sender_id: senderId, seal_verified: verified };
    } catch {
      return null;
    }
  };

  const openHelper = async (): Promise<RecoveredSenderSeal> => {
    const opened = await openWormholeSenderSeal(
      senderSeal,
      candidateDhPub,
      recipientId,
      expectedMsgId,
    );
    return {
      sender_id: String(opened.sender_id || '').trim(),
      seal_verified: Boolean(opened.seal_verified),
    };
  };

  return recoverSenderSealWithFallback({
    wormholeReady: await isWormholeReady(),
    openLocal,
    openHelper,
  });
}

async function decryptSenderSealForPeer(
  senderSeal: string,
  candidateDhPub: string,
  contact: Contact | undefined,
  ownNodeId: string,
  expectedMsgId: string,
): Promise<RecoveredSenderSeal> {
  for (const recipientId of allDmPeerIds(ownNodeId, { sharedAlias: contact?.sharedAlias })) {
    const opened = await decryptSenderSeal(senderSeal, candidateDhPub, recipientId, expectedMsgId);
    if (opened) {
      return opened;
    }
  }
  return null;
}

async function decryptKnownContactMessage(
  senderId: string,
  contact: Contact,
  ciphertext: string,
): Promise<string> {
  try {
    return await ratchetDecryptDM(senderId, ciphertext);
  } catch {
    const sharedKey = await deriveSharedKey(String(contact.dhPubKey || ''));
    return decryptDM(ciphertext, sharedKey);
  }
}

export default function MessagesView({ onBack, onOpenDeadDrop }: MessagesViewProps) {
  const [activeTab, setActiveTab] = useState<ViewTab>('mailbox');
  const [selectedFolder, setSelectedFolder] = useState<MailFolder>('inbox');
  const [selectedMailId, setSelectedMailId] = useState<string>('');
  const [messages, setMessages] = useState<MailItem[]>(ensureSeedMail([]));
  const [contacts, setContacts] = useState<Record<string, Contact>>({});
  const [identity, setIdentity] = useState<NodeIdentity | null>(null);
  const [secureRequired, setSecureRequired] = useState(false);
  const [wormholeReadyState, setWormholeReadyState] = useState(false);
  const [wormholeTransportTier, setWormholeTransportTier] = useState('public_degraded');
  const [pollError, setPollError] = useState('');
  const [composeError, setComposeError] = useState('');
  const [composeStatus, setComposeStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [serverPendingCount, setServerPendingCount] = useState(0);
  const [draft, setDraft] = useState<ComposeDraft>({
    recipient: '',
    subject: '',
    body: '',
  });
  const [contactRequestTarget, setContactRequestTarget] = useState('');
  const [inviteImportAlias, setInviteImportAlias] = useState('');
  const [inviteImportBlob, setInviteImportBlob] = useState('');
  const [inviteBusy, setInviteBusy] = useState(false);
  const [inviteScanOpen, setInviteScanOpen] = useState(false);
  const [inviteScanStatus, setInviteScanStatus] = useState('');
  const [dmLaneWarmStatus, setDmLaneWarmStatus] = useState('');
  const [privateDelivery, setPrivateDelivery] = useState<PrivateDeliverySummary | null>(null);
  const [privateDeliveryBusyId, setPrivateDeliveryBusyId] = useState('');
  const inviteVideoRef = useRef<HTMLVideoElement | null>(null);
  const dmLaneWarmRef = useRef<Promise<boolean> | null>(null);

  const scopeId = identity?.nodeId || 'guest';
  const qrScanAvailable =
    typeof window !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    Boolean((window as Window & { BarcodeDetector?: unknown }).BarcodeDetector) &&
    Boolean(navigator.mediaDevices?.getUserMedia);

  useEffect(() => {
    setMessages(loadMailbox(scopeId));
  }, [scopeId]);

  useEffect(() => {
    saveMailbox(scopeId, sortMessages(messages));
  }, [messages, scopeId]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const syncRuntime = async () => {
      const secure = await isWormholeSecureRequired().catch(() => false);
      const status = await fetchWormholeStatus().catch(() => null);
      if (!alive) return;
      setSecureRequired(secure);
      setWormholeReadyState(Boolean(status?.ready));
      setWormholeTransportTier(String(status?.transport_tier || 'public_degraded'));
      setPrivateDelivery((status?.private_delivery as PrivateDeliverySummary) || null);
      timer = setTimeout(syncRuntime, 5000);
    };

    void syncRuntime();
    return () => {
      alive = false;
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, []);

  useEffect(() => {
    let alive = true;

    const syncIdentity = async () => {
      const localIdentity = getNodeIdentity();
      if (localIdentity && hasSovereignty()) {
        const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
        if (!alive) return;
        setContacts(hydratedContacts);
        setIdentity(localIdentity);
        return;
      }

      if (secureRequired && wormholeReadyState) {
        try {
          const wormholeIdentity = await fetchWormholeIdentity();
          purgeBrowserSigningMaterial();
          purgeBrowserContactGraph();
          await purgeBrowserDmState();
          const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
          if (!alive) return;
          setContacts(hydratedContacts);
          setIdentity({
            publicKey: wormholeIdentity.public_key,
            privateKey: '',
            nodeId: wormholeIdentity.node_id,
          });
          return;
        } catch {
          /* ignore */
        }
      }

      if (!alive) return;
      setContacts(getContacts());
      setIdentity(null);
    };

    void syncIdentity();
    return () => {
      alive = false;
    };
  }, [secureRequired, wormholeReadyState]);

  const dmLaneReady =
    wormholeTransportTier === 'private_control_only' ||
    wormholeTransportTier === 'private_transitional' ||
    wormholeTransportTier === 'private_strong';
  const privateDeliveryRows = useMemo(
    () =>
      ((privateDelivery?.items || []) as PrivateDeliveryItem[]).filter(
        (item) => item.lane === 'dm' && item.release_state !== 'delivered',
      ),
    [privateDelivery],
  );

  const resolveMessagingIdentity = useCallback(async () => {
    const localIdentity = getNodeIdentity();
    if (localIdentity && hasSovereignty()) {
      return localIdentity;
    }
    try {
      const wormholeIdentity = await fetchWormholeIdentity();
      return {
        publicKey: wormholeIdentity.public_key,
        privateKey: '',
        nodeId: wormholeIdentity.node_id,
      };
    } catch {
      return null;
    }
  }, []);

  const syncSecureMailRuntime = useCallback(async () => {
    const [secure, status, resolvedIdentity, hydratedContacts] = await Promise.all([
      isWormholeSecureRequired().catch(() => false),
      fetchWormholeStatus().catch(() => null),
      resolveMessagingIdentity(),
      hydrateWormholeContacts(true).catch(() => getContacts()),
    ]);
    setSecureRequired(Boolean(secure));
    setWormholeReadyState(Boolean(status?.ready));
    setWormholeTransportTier(String(status?.transport_tier || 'public_degraded'));
    setPrivateDelivery((status?.private_delivery as PrivateDeliverySummary) || null);
    setContacts(hydratedContacts);
    setIdentity(resolvedIdentity);
    return resolvedIdentity;
  }, [resolveMessagingIdentity]);

  const ensureSecureMailLane = useCallback(async (statusLine: string): Promise<boolean> => {
    if (dmLaneReady && wormholeReadyState && identity) {
      return true;
    }
    if (dmLaneWarmRef.current) {
      return dmLaneWarmRef.current;
    }
    const task = (async () => {
      setDmLaneWarmStatus(statusLine);
      try {
        const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
        setSecureRequired(Boolean(prepared.settingsEnabled));
        setWormholeReadyState(Boolean(prepared.ready));
        setWormholeTransportTier(String(prepared.transportTier || 'private_transitional'));
        const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
        setContacts(hydratedContacts);
        setIdentity(
          prepared.identity
            ? {
                publicKey: prepared.identity.public_key,
                privateKey: '',
                nodeId: prepared.identity.node_id,
              }
            : null,
        );
        setDmLaneWarmStatus('');
        return true;
      } catch {
        setDmLaneWarmStatus('');
        return false;
      }
    })();
    dmLaneWarmRef.current = task.finally(() => {
      dmLaneWarmRef.current = null;
    });
    return dmLaneWarmRef.current;
  }, [dmLaneReady, identity, wormholeReadyState]);

  useEffect(() => {
    if (dmLaneReady) {
      return;
    }
    setSyncing(false);
    setServerPendingCount(0);
    setPollError('');
  }, [dmLaneReady]);

  useEffect(() => {
    if (dmLaneReady && wormholeReadyState && identity) {
      return;
    }
    void ensureSecureMailLane('Preparing secure mail in the background...');
  }, [dmLaneReady, ensureSecureMailLane, identity, wormholeReadyState]);

  const handlePrivateDeliveryAction = useCallback(
    async (itemId: string, action: 'wait' | 'relay') => {
      setPrivateDeliveryBusyId(itemId);
      setComposeError('');
      try {
        await updatePrivateDeliveryAction(itemId, action);
        await syncSecureMailRuntime();
      } catch (error) {
        const detail = error instanceof Error ? error.message : 'private delivery action failed';
        setComposeError(detail || 'private delivery action failed');
      } finally {
        setPrivateDeliveryBusyId('');
      }
    },
    [syncSecureMailRuntime],
  );

  useEffect(() => {
    if (!inviteScanOpen) {
      setInviteScanStatus('');
      return;
    }

    const DetectorCtor = (window as Window & { BarcodeDetector?: any }).BarcodeDetector;
    if (!DetectorCtor || !navigator.mediaDevices?.getUserMedia) {
      setInviteScanStatus('QR scan is unavailable in this browser. Paste the signed invite JSON instead.');
      return;
    }

    let active = true;
    let stream: MediaStream | null = null;
    let rafId = 0;
    const detector = new DetectorCtor({ formats: ['qr_code'] });

    const stop = () => {
      if (rafId) {
        window.cancelAnimationFrame(rafId);
        rafId = 0;
      }
      if (stream) {
        for (const track of stream.getTracks()) {
          track.stop();
        }
        stream = null;
      }
      if (inviteVideoRef.current) {
        inviteVideoRef.current.srcObject = null;
      }
    };

    const scanFrame = async () => {
      if (!active) return;
      const video = inviteVideoRef.current;
      if (video && video.readyState >= 2) {
        try {
          const codes = await detector.detect(video);
          const match = Array.isArray(codes)
            ? codes.find((code: { rawValue?: string }) => String(code?.rawValue || '').trim())
            : null;
          if (match?.rawValue) {
            setInviteImportBlob(String(match.rawValue || '').trim());
            setInviteScanOpen(false);
            setInviteScanStatus('QR invite scanned. Review or import it below.');
            setComposeError('');
            setComposeStatus('QR invite scanned. Import it to pin the contact.');
            return;
          }
        } catch {
          /* ignore transient detection failures */
        }
      }
      rafId = window.requestAnimationFrame(() => {
        void scanFrame();
      });
    };

    void (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment' },
          audio: false,
        });
        if (!active) {
          stop();
          return;
        }
        const video = inviteVideoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => null);
        }
        setInviteScanStatus('Scanning for a signed DM invite QR...');
        rafId = window.requestAnimationFrame(() => {
          void scanFrame();
        });
      } catch (error) {
        setInviteScanStatus(
          error instanceof Error ? error.message : 'Camera access failed. Paste the invite JSON instead.',
        );
      }
    })();

    return () => {
      active = false;
      stop();
    };
  }, [inviteScanOpen]);

  const upsertLocalMessage = useCallback((mail: MailItem) => {
    setMessages((prev) => {
      const existingIndex = prev.findIndex(
        (item) => item.id === mail.id || (mail.msgId && item.msgId === mail.msgId),
      );
      if (existingIndex === -1) {
        return sortMessages([...prev, mail]);
      }
      const next = [...prev];
      next[existingIndex] = { ...next[existingIndex], ...mail };
      return sortMessages(next);
    });
  }, []);

  const moveMessageToFolder = useCallback((id: string, folder: MailFolder) => {
    setMessages((prev) =>
      sortMessages(
        prev.map((item) =>
          item.id === id
            ? {
                ...item,
                folder,
                read: true,
              }
            : item,
        ),
      ),
    );
  }, []);

  const deleteMessageForever = useCallback((id: string) => {
    setMessages((prev) => prev.filter((item) => item.id !== id));
    setSelectedMailId((prev) => (prev === id ? '' : prev));
  }, []);

  const markMessageRead = useCallback((id: string) => {
    setMessages((prev) =>
      prev.map((item) => (item.id === id ? { ...item, read: true } : item)),
    );
  }, []);

  const folderMessages = useMemo(
    () => sortMessages(messages.filter((item) => item.folder === selectedFolder)),
    [messages, selectedFolder],
  );

  const selectedMessage = useMemo(
    () => folderMessages.find((item) => item.id === selectedMailId) || folderMessages[0] || null,
    [folderMessages, selectedMailId],
  );

  useEffect(() => {
    if (!selectedMessage && folderMessages[0]) {
      setSelectedMailId(folderMessages[0].id);
      return;
    }
    if (selectedMessage && selectedMessage.folder !== selectedFolder) {
      setSelectedMailId(folderMessages[0]?.id || '');
    }
  }, [folderMessages, selectedFolder, selectedMessage]);

  useEffect(() => {
    if (!selectedMessage?.id) return;
    markMessageRead(selectedMessage.id);
  }, [markMessageRead, selectedMessage?.id]);

  const folderCounts = useMemo(() => {
    return FOLDERS.reduce<Record<MailFolder, number>>(
      (acc, folder) => {
        acc[folder.key] = messages.filter((item) => item.folder === folder.key).length;
        return acc;
      },
      {
        inbox: 0,
        sent: 0,
        junk: 0,
        spam: 0,
        trash: 0,
      },
    );
  }, [messages]);

  const blockedContacts = useMemo(
    () =>
      Object.entries(contacts)
        .filter(([, contact]) => contact.blocked)
        .sort(([left], [right]) => left.localeCompare(right)),
    [contacts],
  );

  const activeContacts = useMemo(
    () =>
      Object.entries(contacts)
        .filter(([, contact]) => !contact.blocked)
        .sort(([left], [right]) => left.localeCompare(right)),
    [contacts],
  );
  const composeRecipient = draft.recipient.trim();
  const composeRecipientContact = composeRecipient ? contacts[composeRecipient] : undefined;
  const composeTrustHint = composeRecipientContact ? buildDmTrustHint(composeRecipientContact) : null;
  const composeTrustSummary = composeRecipientContact
    ? contactTrustSummary(composeRecipientContact)
    : null;
  const composeNeedsVerifiedFirstContact = Boolean(
    composeRecipient && requiresVerifiedFirstContact(composeRecipientContact),
  );

  const buildInboundMail = useCallback(
    async (
      envelope: DmMessageEnvelope,
      currentContacts: Record<string, Contact>,
    ): Promise<MailItem | null> => {
      let senderId = String(envelope.sender_id || '').trim();
      let contact = currentContacts[senderId];
      const senderSeal = String(envelope.sender_seal || '').trim();
      const deliveryClass = (String(envelope.delivery_class || 'shared').trim().toLowerCase() ||
        'shared') as 'request' | 'shared';
      let secureRequiredNow = secureRequired;

      if (requiresSenderRecovery(envelope) && senderSeal) {
        let resolved: RecoveredSenderSeal = null;

        for (const [contactId, knownContact] of Object.entries(currentContacts)) {
          if (!knownContact.dhPubKey || knownContact.blocked) continue;
          resolved = await decryptSenderSealForPeer(
            senderSeal,
            knownContact.dhPubKey,
            knownContact,
            identity?.nodeId || '',
            envelope.msg_id,
          );
          if (resolved && shouldPromoteRecoveredSenderForKnownContact(resolved, contactId)) {
            senderId = resolved.sender_id;
            contact = currentContacts[senderId];
            break;
          }
        }

        if (!contact && envelope.ciphertext.startsWith('x3dh1:') && (await canUseWormholeBootstrap())) {
          try {
            const requestText = await bootstrapDecryptAccessRequest('', envelope.ciphertext);
            const consent = parseDmConsentMessage(requestText);
            if (consent?.kind === 'contact_offer' && consent.dh_pub_key) {
              resolved = await decryptSenderSealForPeer(
                senderSeal,
                consent.dh_pub_key,
                undefined,
                identity?.nodeId || '',
                envelope.msg_id,
              );
              if (resolved && shouldPromoteRecoveredSenderForBootstrap(resolved)) {
                senderId = resolved.sender_id;
                contact = currentContacts[senderId];
              }
            }
          } catch {
            /* ignore */
          }
        }
      }

      if (contact?.blocked) {
        return null;
      }

      if (contact?.dhPubKey) {
        let plaintext = '';
        try {
          plaintext = await decryptKnownContactMessage(senderId, contact, envelope.ciphertext);
        } catch {
          return {
            id: `mail-${envelope.msg_id}`,
            msgId: envelope.msg_id,
            folder: 'inbox',
            kind: 'system',
            direction: 'inbound',
            senderId,
            recipientId: identity?.nodeId || '',
            subject: 'Encrypted message could not be opened',
            body: 'This message reached your inbox, but the local client could not decrypt it.',
            timestamp: Number(envelope.timestamp || Math.floor(Date.now() / 1000)),
            read: false,
            transport: envelope.transport || 'relay',
            deliveryClass,
            recoveryState: getSenderRecoveryState(envelope),
            locked: true,
          };
        }

        const aliasRotate = parseAliasRotateMessage(plaintext);
        if (aliasRotate?.shared_alias) {
          updateContact(senderId, {
            pendingSharedAlias: aliasRotate.shared_alias,
            sharedAliasGraceUntil: Date.now() + 5 * 60_000,
            sharedAliasRotatedAt: Date.now(),
            previousSharedAliases: mergeAliasHistory([
              contact.sharedAlias,
              ...(contact.previousSharedAliases || []),
            ]),
          });
          return {
            id: `mail-${envelope.msg_id}`,
            msgId: envelope.msg_id,
            folder: 'inbox',
            kind: 'system',
            direction: 'inbound',
            senderId,
            recipientId: identity?.nodeId || '',
            subject: 'Shared alias rotated',
            body: `${displayNameForPeer(senderId, getContacts())} rotated the pairwise alias for future mail.`,
            timestamp: Number(envelope.timestamp || Math.floor(Date.now() / 1000)),
            read: false,
            transport: envelope.transport || 'relay',
            deliveryClass,
            recoveryState: getSenderRecoveryState(envelope),
          };
        }

        const consent = parseDmConsentMessage(plaintext);
        if (consent?.kind === 'contact_accept') {
          updateContact(senderId, {
            sharedAlias: consent.shared_alias,
            previousSharedAliases: [],
            pendingSharedAlias: undefined,
            sharedAliasGraceUntil: undefined,
            sharedAliasRotatedAt: Date.now(),
          });
          return {
            id: `mail-${envelope.msg_id}`,
            msgId: envelope.msg_id,
            folder: 'inbox',
            kind: 'system',
            direction: 'inbound',
            senderId,
            recipientId: identity?.nodeId || '',
            subject: 'Contact request accepted',
            body: `${displayNameForPeer(senderId, getContacts())} accepted your secure mail request.`,
            timestamp: Number(envelope.timestamp || Math.floor(Date.now() / 1000)),
            read: false,
            transport: envelope.transport || 'relay',
            deliveryClass,
            requestStatus: 'accepted',
            recoveryState: getSenderRecoveryState(envelope),
          };
        }
        if (consent?.kind === 'contact_deny') {
          return {
            id: `mail-${envelope.msg_id}`,
            msgId: envelope.msg_id,
            folder: 'inbox',
            kind: 'system',
            direction: 'inbound',
            senderId,
            recipientId: identity?.nodeId || '',
            subject: 'Contact request denied',
            body: `${displayNameForPeer(senderId, getContacts())} declined your secure mail request.`,
            timestamp: Number(envelope.timestamp || Math.floor(Date.now() / 1000)),
            read: false,
            transport: envelope.transport || 'relay',
            deliveryClass,
            requestStatus: 'denied',
            recoveryState: getSenderRecoveryState(envelope),
          };
        }

        const decoded = decodeMailPayload(plaintext);
        return {
          id: `mail-${envelope.msg_id}`,
          msgId: envelope.msg_id,
          folder: 'inbox',
          kind: 'mail',
          direction: 'inbound',
          senderId,
          recipientId: identity?.nodeId || '',
          subject: decoded.subject,
          body: decoded.body,
          timestamp: Number(envelope.timestamp || Math.floor(Date.now() / 1000)),
          read: false,
          transport: envelope.transport || 'relay',
          deliveryClass,
          recoveryState: getSenderRecoveryState(envelope),
        };
      }

      let consent: DmConsentMessage | null = null;
      secureRequiredNow = await isWormholeSecureRequired().catch(() => secureRequiredNow);
      const existingContact = senderId ? getContacts()[senderId] : undefined;

      try {
        if (envelope.ciphertext.startsWith('x3dh1:') && (await canUseWormholeBootstrap())) {
          const requestText = await bootstrapDecryptAccessRequest(
            senderId.startsWith('sealed:') ? '' : senderId,
            envelope.ciphertext,
          );
          consent = parseDmConsentMessage(requestText);
        } else if (!senderId.startsWith('sealed:') && !secureRequiredNow) {
          const senderKey = await fetchDmPublicKey(
            API_BASE,
            senderId,
            existingContact?.invitePinnedPrekeyLookupHandle,
          );
          if (senderKey?.dh_pub_key) {
            const sharedKey = await deriveSharedKey(String(senderKey.dh_pub_key));
            const requestText = await decryptDM(envelope.ciphertext, sharedKey);
            consent = parseDmConsentMessage(requestText);
          }
        }
      } catch {
        consent = null;
      }

      if (consent?.kind === 'contact_accept' && senderId && !senderId.startsWith('sealed:')) {
        const senderKey = await fetchDmPublicKey(
          API_BASE,
          senderId,
          existingContact?.invitePinnedPrekeyLookupHandle,
        ).catch(() => null);
        if (senderKey?.dh_pub_key) {
          addContact(senderId, String(senderKey.dh_pub_key), undefined, senderKey.dh_algo);
          updateContact(senderId, {
            dhAlgo: senderKey.dh_algo,
            remotePrekeyLookupMode:
              String(senderKey.lookup_mode || '').trim().toLowerCase() ||
              existingContact?.remotePrekeyLookupMode,
            sharedAlias: consent.shared_alias,
            previousSharedAliases: [],
            pendingSharedAlias: undefined,
            sharedAliasGraceUntil: undefined,
            sharedAliasRotatedAt: Date.now(),
          });
        }
        return {
          id: `mail-${envelope.msg_id}`,
          msgId: envelope.msg_id,
          folder: 'inbox',
          kind: 'system',
          direction: 'inbound',
          senderId,
          recipientId: identity?.nodeId || '',
          subject: 'Contact request accepted',
          body: `${displayNameForPeer(senderId, getContacts())} accepted your secure mail request.`,
          timestamp: Number(envelope.timestamp || Math.floor(Date.now() / 1000)),
          read: false,
          transport: envelope.transport || 'relay',
          deliveryClass,
          requestStatus: 'accepted',
          recoveryState: getSenderRecoveryState(envelope),
        };
      }

      if (consent?.kind === 'contact_deny') {
        return {
          id: `mail-${envelope.msg_id}`,
          msgId: envelope.msg_id,
          folder: 'inbox',
          kind: 'system',
          direction: 'inbound',
          senderId: senderId || 'unknown',
          recipientId: identity?.nodeId || '',
          subject: 'Contact request denied',
          body: `${displayNameForPeer(senderId || 'unknown', getContacts())} declined your secure mail request.`,
          timestamp: Number(envelope.timestamp || Math.floor(Date.now() / 1000)),
          read: false,
          transport: envelope.transport || 'relay',
          deliveryClass,
          requestStatus: 'denied',
          recoveryState: getSenderRecoveryState(envelope),
        };
      }

      if (consent?.kind === 'contact_offer' || shouldKeepUnresolvedRequestVisible(envelope)) {
        return {
          id: `mail-${envelope.msg_id}`,
          msgId: envelope.msg_id,
          folder: 'inbox',
          kind: 'request',
          direction: 'inbound',
          senderId: senderId || 'sealed:unknown',
          recipientId: identity?.nodeId || '',
          subject:
            consent?.kind === 'contact_offer'
              ? `Contact request from ${displayNameForPeer(senderId || 'unknown', getContacts())}`
              : 'Unresolved secure contact request',
          body:
            consent?.kind === 'contact_offer'
              ? [
                  `${displayNameForPeer(senderId || 'unknown', getContacts())} wants to open a secure mailbox.`,
                  consent.geo_hint ? `Geo hint: ${consent.geo_hint}` : '',
                  '',
                  'Accept to add this contact and open shared DM mail.',
                ]
                  .filter(Boolean)
                  .join('\n')
              : 'This request arrived through the reduced sealed-sender path. It stays visible until the sender can be resolved.',
          timestamp: Number(envelope.timestamp || Math.floor(Date.now() / 1000)),
          read: false,
          transport: envelope.transport || 'relay',
          deliveryClass,
          requestStatus: consent?.kind === 'contact_offer' ? 'pending' : 'unresolved',
          requestDhPubKey: consent?.kind === 'contact_offer' ? consent.dh_pub_key : '',
          requestDhAlgo: consent?.kind === 'contact_offer' ? consent.dh_algo : '',
          requestGeoHint: consent?.kind === 'contact_offer' ? consent.geo_hint : '',
          recoveryState: getSenderRecoveryState(envelope),
          locked: consent?.kind !== 'contact_offer',
        };
      }

      return {
        id: `mail-${envelope.msg_id}`,
        msgId: envelope.msg_id,
        folder: 'inbox',
        kind: 'system',
        direction: 'inbound',
        senderId: senderId || 'unknown',
        recipientId: identity?.nodeId || '',
        subject: 'Encrypted item received',
        body: 'A secure payload reached your mailbox, but it did not match the current mail or contact request formats.',
        timestamp: Number(envelope.timestamp || Math.floor(Date.now() / 1000)),
        read: false,
        transport: envelope.transport || 'relay',
        deliveryClass,
        recoveryState: getSenderRecoveryState(envelope),
        locked: true,
      };
    },
    [identity?.nodeId, secureRequired],
  );

  const pollHasMoreRef = useRef(false);

  const refreshMailbox = useCallback(async (includeCount = true) => {
    pollHasMoreRef.current = false;
    if (!dmLaneReady) {
      return 'Secure mail is starting the private lane in the background.';
    }
    let activeIdentity = identity;
    if (!wormholeReadyState || !dmLaneReady || !activeIdentity) {
      const warmed = await ensureSecureMailLane('Preparing secure mail in the background...');
      if (!warmed) {
        setPollError('Secure mail is still warming up in the background.');
        return;
      }
      activeIdentity = await syncSecureMailRuntime();
    }
    if (!activeIdentity) {
      setPollError('Secure mail is still preparing your private identity.');
      return;
    }
    setSyncing(true);
    setPollError('');
    try {
      const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
      setContacts(hydratedContacts);
      const claims = await buildMailboxClaims(hydratedContacts, activeIdentity);
      const pollPromise = pollDmMailboxes(API_BASE, activeIdentity, claims);
      const countPromise = includeCount
        ? countDmMailboxes(API_BASE, activeIdentity, claims).catch(() => ({ ok: false, count: 0 }))
        : null;
      const [pollResult, countResult] = await Promise.all([pollPromise, countPromise]);
      if (!pollResult.ok) {
        throw new Error(pollResult.detail || 'mailbox poll failed');
      }
      pollHasMoreRef.current = Boolean(pollResult.has_more);
      if (countResult) {
        setServerPendingCount(Number(countResult.count || 0));
      }
      const incoming: MailItem[] = [];
      for (const envelope of pollResult.messages || []) {
        const mail = await buildInboundMail(envelope, getContacts());
        if (mail) {
          incoming.push(mail);
        }
      }
      if (incoming.length > 0) {
        setMessages((prev) => {
          const existingIds = new Set(prev.map((item) => item.msgId));
          const dedupedIncoming = incoming.filter((item) => !existingIds.has(item.msgId));
          if (dedupedIncoming.length === 0) {
            return prev;
          }
          return ensureSeedMail(sortMessages([...prev, ...dedupedIncoming]));
        });
      }
      setContacts(getContacts());
    } catch (error) {
      pollHasMoreRef.current = false;
      setPollError(
        normalizeMailError(error instanceof Error ? error.message : 'mailbox sync failed'),
      );
    } finally {
      setSyncing(false);
    }
  }, [buildInboundMail, dmLaneReady, ensureSecureMailLane, identity, syncSecureMailRuntime, wormholeReadyState]);

  useEffect(() => {
    if (!identity || !dmLaneReady) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let catchUpBudget = MAX_CATCHUP_POLLS;

    const tick = async (includeCount = true) => {
      if (cancelled) return;
      await refreshMailbox(includeCount);
      if (cancelled) return;
      const classification = classifyTick(
        pollHasMoreRef.current,
        catchUpBudget,
        MAIL_POLL_BASE_MS,
      );
      catchUpBudget = classification.newBudget;
      timer = setTimeout(
        () => void tick(classification.refreshCount),
        classification.delay,
      );
    };

    void tick(); // first tick always includes count

    return () => {
      cancelled = true;
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [dmLaneReady, identity, refreshMailbox]);

  const queueSentMail = useCallback(
    (mail: Omit<MailItem, 'id' | 'folder' | 'direction' | 'read'>) => {
      upsertLocalMessage({
        ...mail,
        id: `local-${mail.msgId || randomId('mail')}`,
        folder: 'sent',
        direction: 'outbound',
        read: true,
      });
    },
    [upsertLocalMessage],
  );

  const handleComposeSubmit = useCallback(async () => {
    const recipient = draft.recipient.trim();
    const subject = draft.subject.trim();
    const body = draft.body.trim();
    let activeIdentity = identity;
    if (!recipient) {
      setComposeError('Recipient is required.');
      return;
    }
    if (!body) {
      setComposeError('Write a message first.');
      return;
    }
    if (!wormholeReadyState || !dmLaneReady || !activeIdentity) {
      setComposeStatus('Preparing secure mail in the background...');
      const warmed = await ensureSecureMailLane('Preparing secure mail in the background...');
      if (!warmed) {
        setComposeStatus('');
        setComposeError('Secure mail is still warming up in the background.');
        return;
      }
      activeIdentity = await syncSecureMailRuntime();
    }
    if (!activeIdentity) {
      setComposeStatus('');
      setComposeError('Secure mail is still preparing your private identity.');
      return;
    }
    if (requiresVerifiedFirstContact(contacts[recipient])) {
      setComposeStatus('');
      setComposeError('Import a signed invite first. Unverified TOFU first-contact requests are disabled.');
      return;
    }

    setBusy(true);
    setComposeError('');
    setComposeStatus('');
    try {
      const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
      setContacts(hydratedContacts);
      const existingContact = hydratedContacts[recipient];

      if (existingContact?.blocked) {
        throw new Error('Recipient is restricted on this install.');
      }

      if (existingContact?.dhPubKey) {
        await ensureRegisteredDmKey(API_BASE, activeIdentity, { force: false });
        const recipientId = preferredDmPeerId(recipient, existingContact);
        const ciphertext = await ratchetEncryptDM(
          recipient,
          String(existingContact.dhPubKey || ''),
          encodeMailPayload(subject, body),
        );
        const recipientToken = await sharedMailboxToken(
          recipientId,
          String(existingContact.dhPubKey || ''),
        );
        const msgId = `dm_${Date.now()}_${activeIdentity.nodeId.slice(-4)}`;
        const timestamp = Math.floor(Date.now() / 1000);
        const sent = await sendDmMessage({
          apiBase: API_BASE,
          identity: activeIdentity,
          recipientId,
          recipientDhPub: String(existingContact.dhPubKey || ''),
          ciphertext,
          msgId,
          timestamp,
          deliveryClass: 'shared',
          recipientToken,
          useSealedSender: true,
        });
        if (!sent.ok) {
          throw new Error(sent.detail || 'secure mail send failed');
        }
        queueSentMail({
          msgId,
          kind: 'mail',
          senderId: activeIdentity.nodeId,
          recipientId: recipient,
          subject: subject || 'Secure Message',
          body,
          timestamp,
          transport: sent.transport || '',
          deliveryClass: 'shared',
        });
        setComposeStatus(`Mail delivered to ${displayNameForPeer(recipient, hydratedContacts)}.`);
        setDraft({
          recipient,
          subject: '',
          body: '',
        });
        setActiveTab('mailbox');
        setSelectedFolder('sent');
        return;
      }

      const registration = await ensureRegisteredDmKey(API_BASE, activeIdentity, { force: false });
      const myDhPub = String(registration.dhPubKey || '').trim();
      if (!myDhPub) {
        throw new Error('Local DM key is unavailable.');
      }
      const recipientContact = getContacts()[recipient];
      const lookupHandle = String(recipientContact?.invitePinnedPrekeyLookupHandle || '').trim();
      if (!lookupHandle) {
        throw new Error(
          'Import or re-import a signed invite before sending a contact request; legacy direct lookup is disabled.',
        );
      }
      const targetKey = await fetchDmPublicKey(API_BASE, recipient, lookupHandle);
      if (!targetKey?.dh_pub_key) {
        throw new Error(
          'Invite-scoped lookup failed for this contact. Re-import a signed invite and try again.',
        );
      }
      const offerPlaintext = buildContactOfferMessage(
        myDhPub,
        registration.dhAlgo || getDHAlgo() || 'X25519',
      );
      let ciphertext = '';
      if (await canUseWormholeBootstrap()) {
        try {
          ciphertext = await bootstrapEncryptAccessRequest(recipient, offerPlaintext);
        } catch {
          ciphertext = '';
        }
      }
      if (!ciphertext && !secureRequired) {
        const sharedKey = await deriveSharedKey(String(targetKey.dh_pub_key));
        ciphertext = await encryptDM(offerPlaintext, sharedKey);
      }
      if (!ciphertext) {
        throw new Error('Secure bootstrap path is unavailable for this contact request.');
      }
      const msgId = `dm_${Date.now()}_${activeIdentity.nodeId.slice(-4)}`;
      const timestamp = Math.floor(Date.now() / 1000);
      const sent = await sendOffLedgerConsentMessage({
        apiBase: API_BASE,
        identity: activeIdentity,
        recipientId: recipient,
        recipientDhPub: String(targetKey.dh_pub_key),
        ciphertext,
        msgId,
        timestamp,
      });
      if (!sent.ok) {
        throw new Error(sent.detail || 'contact request failed');
      }
      queueSentMail({
        msgId,
        kind: 'system',
        senderId: activeIdentity.nodeId,
        recipientId: recipient,
        subject: `Contact request to ${recipient}`,
        body:
          'Secure mail is not open with this peer yet. A contact request was sent first. Once they accept, full mail can flow.',
        timestamp,
        transport: sent.transport || '',
        deliveryClass: 'request',
        requestStatus: 'pending',
      });
      setComposeStatus(`Contact request sent to ${recipient}.`);
      setDraft({
        recipient,
        subject: '',
        body: '',
      });
      setActiveTab('mailbox');
      setSelectedFolder('sent');
    } catch (error) {
      setComposeError(normalizeMailError(error instanceof Error ? error.message : 'mail send failed'));
    } finally {
      setBusy(false);
    }
  }, [contacts, dmLaneReady, draft, ensureSecureMailLane, identity, queueSentMail, secureRequired, syncSecureMailRuntime, wormholeReadyState]);

  const handleSendContactRequest = useCallback(async () => {
    const recipient = contactRequestTarget.trim();
    if (!recipient) {
      setComposeError('Enter an agent ID to send a contact request.');
      return;
    }
    setDraft((prev) => ({
      ...prev,
      recipient,
    }));
    setActiveTab('compose');
    setComposeError('');
    setComposeStatus(
      requiresVerifiedFirstContact(contacts[recipient])
        ? 'Signed invite import is required before first contact. Unverified TOFU contact requests are disabled.'
        : '',
    );
  }, [contactRequestTarget, contacts]);

  const handleImportInvite = useCallback(async () => {
    const raw = inviteImportBlob.trim();
    if (!raw) {
      setComposeStatus('');
      setComposeError('Paste a signed DM invite first.');
      return;
    }

    setInviteBusy(true);
    setComposeError('');
    setComposeStatus('');
    try {
      if (!wormholeReadyState) {
        const warmed = await ensureSecureMailLane('Preparing secure mail in the background...');
        if (!warmed) {
          throw new Error('Secure mail is still warming up in the background.');
        }
      }
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      const nestedInvite = parsed?.invite;
      const invite =
        nestedInvite && typeof nestedInvite === 'object' && !Array.isArray(nestedInvite)
          ? (nestedInvite as Record<string, unknown>)
          : parsed;
      const result = await importWormholeDmInvite(invite, inviteImportAlias.trim());
      const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
      const importedContact = hydratedContacts[result.peer_id];
      const importedTrust = importedContact ? contactTrustSummary(importedContact) : null;
      const importedTrustLabel =
        importedTrust?.label ||
        (result.trust_level === 'invite_pinned'
          ? 'INVITE PINNED'
          : result.trust_level === 'tofu_pinned'
            ? 'TOFU PINNED'
            : 'INVITE IMPORTED');
      setContacts(hydratedContacts);
      setInviteImportBlob('');
      setInviteImportAlias('');
      setComposeStatus(
        `${importedTrustLabel} for ${displayNameForPeer(result.peer_id, hydratedContacts)} (${shortFingerprint(result.trust_fingerprint)}).${result.detail ? ` ${result.detail}` : ''}`,
      );
    } catch (error) {
      setComposeStatus('');
      const failure = getWormholeDmInviteImportErrorResult(error);
      if (failure?.peer_id) {
        const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
        setContacts(hydratedContacts);
        const failedContact = hydratedContacts[failure.peer_id];
        const failedTrustSummary = getContactTrustSummary(failedContact);
        if (failedTrustSummary?.state === 'continuity_broken' && failedTrustSummary.rootMismatch) {
          setComposeError(
            `CONTINUITY BROKEN for ${displayNameForPeer(failure.peer_id, hydratedContacts)}. Stable root continuity changed. Re-verify SAS in Dead Drop or replace the signed invite before trusting this contact again.${failure.detail ? ` ${failure.detail}` : ''}`,
          );
          return;
        }
      }
      setComposeError(error instanceof Error ? error.message : 'invite import failed');
    } finally {
      setInviteBusy(false);
    }
  }, [ensureSecureMailLane, inviteImportAlias, inviteImportBlob, wormholeReadyState]);

  const handleStartInviteScan = useCallback(() => {
    setComposeError('');
    setComposeStatus('');
    if (!qrScanAvailable) {
      setInviteScanStatus('QR scan is unavailable in this browser. Paste the signed invite JSON instead.');
      return;
    }
    setInviteScanOpen(true);
  }, [qrScanAvailable]);

  const handleAcceptRequest = useCallback(
    async (mail: MailItem) => {
      let activeIdentity = identity;
      if (!mail.requestDhPubKey || !mail.senderId || mail.senderId.startsWith('sealed:')) {
        setComposeError('This request cannot be accepted until the sender is resolved.');
        return;
      }
      if (!wormholeReadyState || !dmLaneReady || !activeIdentity) {
        const warmed = await ensureSecureMailLane('Preparing secure mail in the background...');
        if (!warmed) {
          setComposeError('Secure mail is still warming up in the background.');
          return;
        }
        activeIdentity = await syncSecureMailRuntime();
      }
      if (!activeIdentity) {
        setComposeError('Secure mail is still preparing your private identity.');
        return;
      }
      setBusy(true);
      setComposeError('');
      try {
        const existingContact = getContacts()[mail.senderId];
        const registry = await fetchDmPublicKey(
          API_BASE,
          mail.senderId,
          existingContact?.invitePinnedPrekeyLookupHandle,
        ).catch(() => null);
        const dhPubKey = String(registry?.dh_pub_key || mail.requestDhPubKey || '').trim();
        const dhAlgo = String(registry?.dh_algo || mail.requestDhAlgo || 'X25519').trim();
        if (!dhPubKey) {
          throw new Error('Remote DM key is unavailable.');
        }

        addContact(mail.senderId, dhPubKey, undefined, dhAlgo);

        let sharedAlias = '';
        try {
          const issued = await issueWormholePairwiseAlias(mail.senderId, dhPubKey);
          if (issued.ok) {
            sharedAlias = String(issued.shared_alias || '').trim();
          }
        } catch {
          sharedAlias = '';
        }
        if (!sharedAlias) {
          sharedAlias = generateSharedAlias();
        }

        updateContact(mail.senderId, {
          dhAlgo,
          sharedAlias,
          previousSharedAliases: [],
          pendingSharedAlias: undefined,
          sharedAliasGraceUntil: undefined,
          sharedAliasRotatedAt: Date.now(),
        });

        const acceptPlaintext = buildContactAcceptMessage(sharedAlias);
        let ciphertext = '';
        if (await canUseWormholeBootstrap()) {
          try {
            ciphertext = await bootstrapEncryptAccessRequest(mail.senderId, acceptPlaintext);
          } catch {
            ciphertext = '';
          }
        }
        if (!ciphertext && !secureRequired) {
          const sharedKey = await deriveSharedKey(dhPubKey);
          ciphertext = await encryptDM(acceptPlaintext, sharedKey);
        }
        if (!ciphertext) {
          throw new Error('Unable to build secure contact acceptance.');
        }

        const msgId = `dm_${Date.now()}_${activeIdentity.nodeId.slice(-4)}`;
        const timestamp = Math.floor(Date.now() / 1000);
        const sent = await sendOffLedgerConsentMessage({
          apiBase: API_BASE,
          identity: activeIdentity,
          recipientId: mail.senderId,
          recipientDhPub: dhPubKey,
          ciphertext,
          msgId,
          timestamp,
        });
        if (!sent.ok) {
          throw new Error(sent.detail || 'contact accept failed');
        }

        moveMessageToFolder(mail.id, 'trash');
        queueSentMail({
          msgId,
          kind: 'system',
          senderId: activeIdentity.nodeId,
          recipientId: mail.senderId,
          subject: `Accepted ${displayNameForPeer(mail.senderId, getContacts())}`,
          body: 'Secure mailbox opened. Future messages can flow through the shared DM lane.',
          timestamp,
          transport: sent.transport || '',
          deliveryClass: 'request',
          requestStatus: 'accepted',
        });
        setContacts(getContacts());
        setComposeStatus(`Contact accepted: ${displayNameForPeer(mail.senderId, getContacts())}.`);
      } catch (error) {
        setComposeError(error instanceof Error ? error.message : 'accept failed');
      } finally {
        setBusy(false);
      }
    },
    [dmLaneReady, ensureSecureMailLane, identity, moveMessageToFolder, queueSentMail, secureRequired, syncSecureMailRuntime, wormholeReadyState],
  );

  const handleDenyRequest = useCallback(
    async (mail: MailItem) => {
      let activeIdentity = identity;
      if (!mail.requestDhPubKey || !mail.senderId || mail.senderId.startsWith('sealed:')) {
        moveMessageToFolder(mail.id, 'trash');
        return;
      }
      if (!wormholeReadyState || !dmLaneReady || !activeIdentity) {
        const warmed = await ensureSecureMailLane('Preparing secure mail in the background...');
        if (!warmed) {
          setComposeError('Secure mail is still warming up in the background.');
          return;
        }
        activeIdentity = await syncSecureMailRuntime();
      }
      if (!activeIdentity) {
        setComposeError('Secure mail is still preparing your private identity.');
        return;
      }
      setBusy(true);
      setComposeError('');
      try {
        const denyPlaintext = buildContactDenyMessage('declined');
        let ciphertext = '';
        if (await canUseWormholeBootstrap()) {
          try {
            ciphertext = await bootstrapEncryptAccessRequest(mail.senderId, denyPlaintext);
          } catch {
            ciphertext = '';
          }
        }
        if (!ciphertext && !secureRequired) {
          const sharedKey = await deriveSharedKey(mail.requestDhPubKey);
          ciphertext = await encryptDM(denyPlaintext, sharedKey);
        }
        if (ciphertext) {
          const msgId = `dm_${Date.now()}_${activeIdentity.nodeId.slice(-4)}`;
          const timestamp = Math.floor(Date.now() / 1000);
          await sendOffLedgerConsentMessage({
            apiBase: API_BASE,
            identity: activeIdentity,
            recipientId: mail.senderId,
            recipientDhPub: mail.requestDhPubKey,
            ciphertext,
            msgId,
            timestamp,
          });
          queueSentMail({
            msgId,
            kind: 'system',
            senderId: activeIdentity.nodeId,
            recipientId: mail.senderId,
            subject: `Declined ${displayNameForPeer(mail.senderId, getContacts())}`,
            body: 'You declined this secure mailbox request.',
            timestamp,
            deliveryClass: 'request',
            requestStatus: 'denied',
          });
        }
        moveMessageToFolder(mail.id, 'trash');
        setComposeStatus(`Request denied: ${displayNameForPeer(mail.senderId, getContacts())}.`);
      } catch (error) {
        setComposeError(error instanceof Error ? error.message : 'deny failed');
      } finally {
        setBusy(false);
      }
    },
    [dmLaneReady, ensureSecureMailLane, identity, moveMessageToFolder, queueSentMail, secureRequired, syncSecureMailRuntime, wormholeReadyState],
  );

  const handleReply = useCallback((mail: MailItem) => {
    if (!mail.senderId || mail.senderId === 'shadowbroker' || mail.senderId === 'system') {
      return;
    }
    setDraft({
      recipient: mail.senderId,
      subject: mail.subject.startsWith('Re:') ? mail.subject : `Re: ${mail.subject}`,
      body: '',
    });
    setActiveTab('compose');
  }, []);

  const statusLine = useMemo(() => {
    if (dmLaneWarmStatus) {
      return dmLaneWarmStatus;
    }
    if (!wormholeReadyState) {
      return 'Secure mail is preparing the local obfuscated identity in the background.';
    }
    if (!dmLaneReady) {
      return 'Secure mail is starting the direct obfuscated DM transport in the background.';
    }
    if (!identity) {
      return 'Secure mail is preparing the local private identity in the background.';
    }
    if (syncing) {
      return 'SYNCING SECURE MAILBOX...';
    }
    return `SECURE MAIL READY - ${serverPendingCount} remote items still pending on the server.`;
  }, [dmLaneReady, dmLaneWarmStatus, identity, serverPendingCount, syncing, wormholeReadyState]);

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      <div className="border-b border-gray-800 pb-4 mb-4 shrink-0">
        <div className="flex items-center justify-between mb-2">
          <button
            onClick={onBack}
            className="flex items-center text-cyan-500 hover:text-cyan-400 transition-all uppercase text-xs tracking-widest border border-cyan-900/50 px-3 py-1 bg-cyan-900/10 hover:bg-cyan-900/30 hover:border-cyan-500/50"
          >
            <ChevronLeft size={14} className="mr-1" />
            RETURN TO MAIN
          </button>
          <button
            onClick={() => void refreshMailbox()}
            className="flex items-center text-cyan-400 hover:text-cyan-300 uppercase text-sm tracking-[0.2em] border border-cyan-900/50 px-3 py-1 bg-cyan-900/10 disabled:opacity-50"
            disabled={!identity || syncing || !dmLaneReady}
          >
            <RefreshCcw size={13} className={`mr-2 ${syncing ? 'animate-spin' : ''}`} />
            REFRESH
          </button>
        </div>
        <h1 className="text-2xl font-bold text-cyan-400 uppercase tracking-widest mt-4 flex items-center">
          <Mail size={24} className="mr-3" />
          SECURE MESSAGES
        </h1>
        <p className="text-gray-500 text-sm mt-1">End-to-end encrypted peer-to-peer comms.</p>
      </div>

      <div className="border border-cyan-900/30 bg-cyan-950/10 px-4 py-3 text-[11px] tracking-[0.16em] uppercase text-cyan-300 mb-4 shrink-0">
        {statusLine}
      </div>

      {(pollError || composeError || composeStatus) && (
        <div className="space-y-2 mb-4 shrink-0">
          {pollError && (
            <div className="border border-red-500/30 bg-red-950/20 px-4 py-3 text-sm text-red-300 flex items-start">
              <AlertCircle size={16} className="mr-2 mt-0.5 shrink-0" />
              <span>{pollError}</span>
            </div>
          )}
          {composeError && (
            <div className="border border-red-500/30 bg-red-950/20 px-4 py-3 text-sm text-red-300 flex items-start">
              <AlertCircle size={16} className="mr-2 mt-0.5 shrink-0" />
              <span>{composeError}</span>
            </div>
          )}
          {composeStatus && (
            <div className="border border-emerald-500/30 bg-emerald-950/20 px-4 py-3 text-sm text-emerald-300">
              {composeStatus}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center border-b border-gray-800/80 shrink-0">
        {[
          { key: 'mailbox' as const, label: 'MAILBOX', icon: <Inbox size={14} className="mr-2" /> },
          { key: 'compose' as const, label: 'COMPOSE', icon: <PencilLine size={14} className="mr-2" /> },
          { key: 'contacts' as const, label: 'CONTACTS', icon: <Users size={14} className="mr-2" /> },
          { key: 'restricted' as const, label: 'RESTRICTED', icon: <ShieldOff size={14} className="mr-2" /> },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-3 text-xs tracking-[0.2em] uppercase border-r border-gray-800 flex items-center ${
              activeTab === tab.key
                ? 'text-cyan-300 bg-cyan-950/20'
                : 'text-gray-500 hover:text-cyan-300 hover:bg-gray-900/30'
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === 'mailbox' && (
          <div className="grid grid-cols-[200px_1fr_1.2fr] gap-6 h-full pt-4">
            <div className="border border-gray-800/80 p-3 overflow-y-auto">
              {FOLDERS.map((folder) => (
                <button
                  key={folder.key}
                  onClick={() => setSelectedFolder(folder.key)}
                  className={`w-full flex items-center justify-between px-3 py-3 text-sm tracking-[0.18em] uppercase mb-2 border ${
                    selectedFolder === folder.key
                      ? 'border-cyan-500/40 bg-cyan-950/20 text-cyan-300'
                      : 'border-transparent text-gray-500 hover:text-cyan-300 hover:bg-gray-900/30'
                  }`}
                >
                  <span className="flex items-center">{folder.icon}{folder.label}</span>
                  <span className="text-xs">{folderCounts[folder.key]}</span>
                </button>
              ))}
            </div>

            <div className="border border-gray-800/80 overflow-y-auto">
              {folderMessages.length === 0 ? (
                <div className="p-6 text-sm text-gray-500">This folder is empty.</div>
              ) : (
                folderMessages.map((mail) => (
                  <button
                    key={mail.id}
                    onClick={() => setSelectedMailId(mail.id)}
                    className={`w-full border-b border-gray-800/60 px-5 py-4 text-left ${
                      selectedMessage?.id === mail.id ? 'bg-cyan-950/15' : 'hover:bg-gray-900/20'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4 mb-2">
                      <div className="text-gray-300 font-semibold">
                        {displayNameForPeer(mail.senderId, contacts)}
                      </div>
                      <div className="text-[11px] text-gray-600 whitespace-nowrap">
                        {formatTimestamp(mail.timestamp)}
                      </div>
                    </div>
                    <div className="text-cyan-300 text-sm mb-1">{mail.subject}</div>
                    <div className="text-xs text-gray-500 line-clamp-2">{messagePreview(mail)}</div>
                    {!mail.read && (
                      <div className="mt-2 text-sm tracking-[0.2em] uppercase text-cyan-400">
                        unread
                      </div>
                    )}
                  </button>
                ))
              )}
            </div>

            <div className="border border-gray-800/80 overflow-y-auto">
              {selectedMessage ? (
                <div className="p-6">
                  <div className="flex items-start justify-between gap-4 mb-4">
                    <div>
                      <div className="text-cyan-300 text-lg font-semibold mb-2">
                        {selectedMessage.subject}
                      </div>
                      <div className="text-sm text-gray-400">
                        From: {displayNameForPeer(selectedMessage.senderId, contacts)}
                      </div>
                      <div className="text-sm text-gray-500">
                        {formatTimestamp(selectedMessage.timestamp)}
                      </div>
                    </div>
                    <div className="text-sm tracking-[0.18em] uppercase text-gray-500">
                      {selectedMessage.transport || 'local'}
                    </div>
                  </div>

                  <div className="border border-gray-800/60 bg-gray-950/20 p-4 text-sm text-gray-300 whitespace-pre-wrap min-h-[220px]">
                    {selectedMessage.body}
                  </div>

                  {selectedMessage.kind === 'request' && (
                    <div className="mt-4 flex flex-wrap gap-3">
                      <button
                        onClick={() => void handleAcceptRequest(selectedMessage)}
                        disabled={busy || selectedMessage.requestStatus !== 'pending'}
                        className="px-4 py-2 border border-emerald-500/40 bg-emerald-950/20 text-emerald-300 text-xs tracking-[0.18em] uppercase disabled:opacity-50 flex items-center"
                      >
                        <Check size={14} className="mr-2" />
                        Accept
                      </button>
                      <button
                        onClick={() => void handleDenyRequest(selectedMessage)}
                        disabled={busy || selectedMessage.requestStatus === 'denied'}
                        className="px-4 py-2 border border-red-500/40 bg-red-950/20 text-red-300 text-xs tracking-[0.18em] uppercase disabled:opacity-50 flex items-center"
                      >
                        <X size={14} className="mr-2" />
                        Deny
                      </button>
                    </div>
                  )}

                  <div className="mt-6 flex flex-wrap gap-3">
                    {selectedMessage.kind === 'mail' && selectedMessage.senderId !== 'shadowbroker' && (
                      <button
                        onClick={() => handleReply(selectedMessage)}
                        className="px-4 py-2 border border-cyan-500/40 bg-cyan-950/20 text-cyan-300 text-xs tracking-[0.18em] uppercase flex items-center"
                      >
                        <Reply size={14} className="mr-2" />
                        Reply
                      </button>
                    )}
                    {selectedFolder !== 'junk' && (
                      <button
                        onClick={() => moveMessageToFolder(selectedMessage.id, 'junk')}
                        className="px-4 py-2 border border-gray-700 bg-gray-950/20 text-gray-300 text-xs tracking-[0.18em] uppercase"
                      >
                        Move to Junk
                      </button>
                    )}
                    {selectedFolder !== 'spam' && (
                      <button
                        onClick={() => moveMessageToFolder(selectedMessage.id, 'spam')}
                        className="px-4 py-2 border border-gray-700 bg-gray-950/20 text-gray-300 text-xs tracking-[0.18em] uppercase"
                      >
                        Move to Spam
                      </button>
                    )}
                    {selectedFolder !== 'trash' ? (
                      <button
                        onClick={() => moveMessageToFolder(selectedMessage.id, 'trash')}
                        className="px-4 py-2 border border-red-500/40 bg-red-950/20 text-red-300 text-xs tracking-[0.18em] uppercase"
                      >
                        Move to Trash
                      </button>
                    ) : (
                      <button
                        onClick={() => deleteMessageForever(selectedMessage.id)}
                        className="px-4 py-2 border border-red-500/40 bg-red-950/20 text-red-300 text-xs tracking-[0.18em] uppercase"
                      >
                        Delete Forever
                      </button>
                    )}
                    {selectedFolder !== 'inbox' && selectedFolder !== 'trash' && (
                      <button
                        onClick={() => moveMessageToFolder(selectedMessage.id, 'inbox')}
                        className="px-4 py-2 border border-cyan-900/50 bg-cyan-950/10 text-cyan-300 text-xs tracking-[0.18em] uppercase"
                      >
                        Move to Inbox
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="p-6 text-sm text-gray-500">Select a message to read it.</div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'compose' && (
          <div className="h-full overflow-y-auto pt-4">
            <div className="border border-gray-800/80 p-6 max-w-4xl">
              <div className="grid grid-cols-1 gap-4">
                <label className="text-xs tracking-[0.18em] uppercase text-gray-500">
                  Recipient agent ID
                  <input
                    value={draft.recipient}
                    onChange={(event) => setDraft((prev) => ({ ...prev, recipient: event.target.value }))}
                    className="mt-2 w-full bg-transparent border border-gray-800 px-4 py-3 text-sm text-white outline-none focus:border-cyan-500/40"
                    placeholder="!sb_..."
                    spellCheck={false}
                  />
                </label>
                <label className="text-xs tracking-[0.18em] uppercase text-gray-500">
                  Subject
                  <input
                    value={draft.subject}
                    onChange={(event) => setDraft((prev) => ({ ...prev, subject: event.target.value }))}
                    className="mt-2 w-full bg-transparent border border-gray-800 px-4 py-3 text-sm text-white outline-none focus:border-cyan-500/40"
                    placeholder="Secure Message"
                    spellCheck={false}
                  />
                </label>
                <label className="text-xs tracking-[0.18em] uppercase text-gray-500">
                  Message
                  <textarea
                    value={draft.body}
                    onChange={(event) => setDraft((prev) => ({ ...prev, body: event.target.value }))}
                    className="mt-2 w-full min-h-[220px] bg-transparent border border-gray-800 px-4 py-3 text-sm text-white outline-none focus:border-cyan-500/40"
                    placeholder="Write the message body here..."
                    spellCheck={false}
                  />
                </label>
              </div>

              <div className="mt-4 border border-amber-500/20 bg-amber-950/10 px-4 py-3 text-xs text-amber-300">
                {dmLaneWarmStatus
                  ? dmLaneWarmStatus
                  : !wormholeReadyState
                    ? 'Secure mail is waking up in the background. You can finish the draft now and send when the lane is ready.'
                    : !dmLaneReady
                      ? 'Secure mail is bringing the private lane online in the background.'
                      : 'If the recipient is not already in your contacts, sending from here opens with a secure contact request first. Full mail begins after they accept.'}
              </div>

              {privateDeliveryRows.length > 0 && (
                <div className="mt-4 space-y-3">
                  {privateDeliveryRows.map((item) => {
                    const approval = item.approval || {};
                    const detail =
                      approval.detail ||
                      item.status?.reason ||
                      'Trying more private routing in the background.';
                    const busy = privateDeliveryBusyId === item.id;
                    return (
                      <div
                        key={item.id}
                        className="border border-cyan-900/60 bg-slate-950/80 px-4 py-4"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div className="text-[10px] uppercase tracking-[0.18em] text-cyan-300/85">
                            {approval.status_label || item.status?.label || 'Preparing private lane'}
                          </div>
                          <div className="text-[10px] uppercase tracking-[0.18em] text-gray-500">
                            queued secure mail
                          </div>
                        </div>
                        <div className="mt-2 text-[11px] leading-[1.65] text-gray-200">
                          {detail}
                        </div>
                        {approval.required && (
                          <div className="mt-4 flex flex-wrap gap-3">
                            <button
                              type="button"
                              onClick={() => handlePrivateDeliveryAction(item.id, 'wait')}
                              disabled={busy}
                              className="border border-cyan-500/40 bg-cyan-950/20 px-4 py-2 text-[11px] uppercase tracking-[0.16em] text-cyan-200 disabled:opacity-60"
                            >
                              Keep waiting
                            </button>
                            <button
                              type="button"
                              onClick={() => handlePrivateDeliveryAction(item.id, 'relay')}
                              disabled={busy}
                              className="border border-gray-700 bg-transparent px-4 py-2 text-[11px] uppercase tracking-[0.16em] text-gray-200 disabled:opacity-60"
                            >
                              Send via relay
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {composeRecipient && composeNeedsVerifiedFirstContact && (
                <div className="mt-4 border border-red-500/30 bg-red-950/20 px-4 py-4 text-sm text-red-200">
                  <div className="text-xs tracking-[0.18em] uppercase text-red-300">
                    Verified First Contact Required
                  </div>
                  <div className="mt-2 leading-[1.65]">
                    This recipient has no imported signed invite or other verified first-contact
                    anchor yet. Secure request bootstrap is blocked until you import a signed invite
                    or otherwise verify the contact out of band first.
                  </div>
                  <div className="mt-4 flex flex-wrap gap-3">
                    <button
                      onClick={() => {
                        setInviteImportAlias((prev) => prev || composeRecipient);
                        setContactRequestTarget(composeRecipient);
                        setActiveTab('contacts');
                        setComposeStatus(
                          `Import a signed invite for ${composeRecipient} before returning to Compose.`,
                        );
                        setComposeError('');
                      }}
                      className="px-4 py-2 border border-emerald-500/40 bg-emerald-950/20 text-emerald-300 text-xs tracking-[0.18em] uppercase"
                    >
                      Import Signed Invite
                    </button>
                  </div>
                </div>
              )}

              {composeRecipient && !composeNeedsVerifiedFirstContact && composeTrustHint && (
                <div
                  className={`mt-4 border px-4 py-4 text-sm ${
                    composeTrustHint.severity === 'danger'
                      ? 'border-red-500/30 bg-red-950/20 text-red-200'
                      : 'border-amber-500/20 bg-amber-950/10 text-amber-200'
                  }`}
                >
                  <div
                    className={`text-xs tracking-[0.18em] uppercase ${
                      composeTrustHint.severity === 'danger' ? 'text-red-300' : 'text-amber-300'
                    }`}
                  >
                    {composeTrustHint.title}
                  </div>
                  <div className="mt-2 leading-[1.65]">{composeTrustHint.detail}</div>
                  {composeTrustSummary?.detail && (
                    <div className="mt-3 text-xs leading-[1.7] text-cyan-200/85">
                      {composeTrustSummary.detail}
                    </div>
                  )}
                  {composeRecipientContact && contactTrustNextStep(composeRecipientContact) && (
                    <>
                      <div className="mt-3 text-xs leading-[1.7] text-cyan-200/85">
                        Next: {contactTrustNextStep(composeRecipientContact)?.label} •{' '}
                        {contactTrustNextStep(composeRecipientContact)?.detail}
                      </div>
                      {contactTrustNextStep(composeRecipientContact)?.action === 'dead_drop' &&
                        onOpenDeadDrop && (
                          <div className="mt-3">
                            <button
                              onClick={() =>
                                onOpenDeadDrop(
                                  composeRecipient,
                                  deadDropLaunchOptions(composeRecipientContact),
                                )
                              }
                              className="px-4 py-2 border border-cyan-500/40 bg-cyan-950/20 text-cyan-300 text-xs tracking-[0.18em] uppercase"
                            >
                              {contactTrustNextStep(composeRecipientContact)?.label}
                            </button>
                          </div>
                        )}
                    </>
                  )}
                </div>
              )}

              <div className="mt-6 flex flex-wrap gap-3">
                <button
                  onClick={() => void handleComposeSubmit()}
                  disabled={busy || composeNeedsVerifiedFirstContact}
                  className="px-5 py-3 border border-cyan-500/40 bg-cyan-950/20 text-cyan-300 text-xs tracking-[0.18em] uppercase disabled:opacity-50"
                >
                  {busy ? 'Sending...' : 'Send Secure Mail'}
                </button>
                <button
                  onClick={() => {
                    setDraft({ recipient: '', subject: '', body: '' });
                  }}
                  className="px-5 py-3 border border-gray-700 bg-gray-950/20 text-gray-300 text-xs tracking-[0.18em] uppercase"
                >
                  Clear Draft
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'contacts' && (
          <div className="h-full overflow-y-auto pt-4 grid grid-cols-[1.2fr_1fr] gap-6">
            <div className="border border-gray-800/80 p-6">
              <div className="text-xs tracking-[0.2em] uppercase text-cyan-300 mb-4 flex items-center">
                <Users size={14} className="mr-2" />
                Contacts
              </div>
              <div className="space-y-3">
                {activeContacts.length === 0 ? (
                  <div className="text-sm text-gray-500">No approved secure contacts yet.</div>
                ) : (
                  activeContacts.map(([peerId, contact]) => {
                    const trust = contactTrustSummary(contact);
                    const nextStep = contactTrustNextStep(contact);
                    return (
                      <div key={peerId} className="border border-gray-800/60 p-4">
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <div className="text-cyan-300 font-semibold">
                              {displayNameForPeer(peerId, contacts)}
                            </div>
                            <div className="text-xs text-gray-500 mt-1">{peerId}</div>
                            {trust && (
                              <>
                                <div
                                  className={`inline-flex mt-2 px-2 py-1 border text-[11px] tracking-[0.16em] uppercase ${trust.tone}`}
                                >
                                  {trust.label}
                                </div>
                                <div className="text-[11px] text-gray-500 mt-2">
                                  {trust.detail}
                                </div>
                                {nextStep && (
                                  <div className="text-[11px] text-cyan-300/80 mt-2">
                                    Next: {nextStep.label} • {nextStep.detail}
                                  </div>
                                )}
                              </>
                            )}
                            {contact.sharedAlias && (
                              <div className="text-[11px] text-emerald-300 mt-2">
                                Shared alias: {contact.sharedAlias}
                              </div>
                            )}
                          </div>
                          <div className="flex flex-wrap justify-end gap-2">
                            <button
                              onClick={() => {
                                setDraft({ recipient: peerId, subject: '', body: '' });
                                setActiveTab('compose');
                              }}
                              className="px-3 py-2 border border-cyan-500/30 text-cyan-300 text-sm tracking-[0.18em] uppercase disabled:opacity-50"
                            >
                              Compose
                            </button>
                            {nextStep?.action === 'import_invite' && (
                              <button
                                onClick={() => {
                                  setInviteImportAlias((prev) => prev || peerId);
                                  setContactRequestTarget(peerId);
                                  setComposeStatus(
                                    `Import a signed invite for ${displayNameForPeer(peerId, contacts)} in the panel below.`,
                                  );
                                  setComposeError('');
                                }}
                                className="px-3 py-2 border border-emerald-500/30 text-emerald-300 text-sm tracking-[0.18em] uppercase"
                              >
                                Import Invite
                              </button>
                            )}
                            {nextStep?.action === 'dead_drop' && onOpenDeadDrop && (
                              <button
                                onClick={() =>
                                  onOpenDeadDrop(peerId, deadDropLaunchOptions(contact))
                                }
                                className="px-3 py-2 border border-cyan-500/30 text-cyan-300 text-sm tracking-[0.18em] uppercase"
                              >
                                {nextStep.label}
                              </button>
                            )}
                            <button
                              onClick={() => {
                                blockContact(peerId);
                                setContacts(getContacts());
                              }}
                              className="px-3 py-2 border border-amber-500/30 text-amber-300 text-sm tracking-[0.18em] uppercase"
                            >
                              Restrict
                            </button>
                            <button
                              onClick={() => {
                                removeContact(peerId);
                                setContacts(getContacts());
                              }}
                              className="px-3 py-2 border border-red-500/30 text-red-300 text-sm tracking-[0.18em] uppercase"
                            >
                              Remove
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            <div className="border border-gray-800/80 p-6">
              <div className="text-xs tracking-[0.2em] uppercase text-cyan-300 mb-4 flex items-center">
                <UserPlus size={14} className="mr-2" />
                Add Contact
              </div>
              <label className="text-xs tracking-[0.18em] uppercase text-gray-500">
                Agent ID
                <input
                  value={contactRequestTarget}
                  onChange={(event) => setContactRequestTarget(event.target.value)}
                  className="mt-2 w-full bg-transparent border border-gray-800 px-4 py-3 text-sm text-white outline-none focus:border-cyan-500/40"
                  placeholder="!sb_..."
                  spellCheck={false}
                />
              </label>
              <div className="mt-4 text-sm text-gray-500">
                Signed invite import is now the required first-contact path for new secure contact
                requests. Verify the invite over QR or another trusted side channel first.
              </div>
              <div className="mt-6">
                <div className="flex flex-wrap gap-3">
                  <button
                    onClick={() => void handleSendContactRequest()}
                    className="px-4 py-3 border border-cyan-500/40 bg-cyan-950/20 text-cyan-300 text-xs tracking-[0.18em] uppercase disabled:opacity-50"
                  >
                    Prepare First Contact
                  </button>
                  <button
                    onClick={() => handleStartInviteScan()}
                    className="px-4 py-3 border border-emerald-500/40 bg-emerald-950/20 text-emerald-300 text-xs tracking-[0.18em] uppercase disabled:opacity-50"
                  >
                    Scan Invite QR
                  </button>
                </div>
              </div>

              <div className="mt-8 pt-6 border-t border-gray-800/80">
                <div className="text-xs tracking-[0.2em] uppercase text-emerald-300 mb-4">
                  Import Verified Invite
                </div>
                <label className="text-xs tracking-[0.18em] uppercase text-gray-500">
                  Local Alias
                  <input
                    value={inviteImportAlias}
                    onChange={(event) => setInviteImportAlias(event.target.value)}
                    className="mt-2 w-full bg-transparent border border-gray-800 px-4 py-3 text-sm text-white outline-none focus:border-emerald-500/40"
                    placeholder="Optional display label"
                    spellCheck={false}
                  />
                </label>
                <label className="text-xs tracking-[0.18em] uppercase text-gray-500 block mt-4">
                  Signed Invite JSON
                  <textarea
                    value={inviteImportBlob}
                    onChange={(event) => setInviteImportBlob(event.target.value)}
                    className="mt-2 w-full min-h-[200px] bg-transparent border border-gray-800 px-4 py-3 text-sm text-white outline-none focus:border-emerald-500/40 font-mono"
                    placeholder='Paste the full export blob or the nested "invite" object here...'
                    spellCheck={false}
                  />
                </label>
                <div className="mt-4 text-sm text-gray-500 leading-[1.65]">
                  Importing a signed invite pins first contact to a trusted out-of-band identity
                  instead of plain first-sight TOFU. Use this when the invite came from QR,
                  in-person exchange, or another authenticated side channel.
                </div>
                {(inviteScanOpen || inviteScanStatus) && (
                  <div className="mt-4 border border-emerald-500/20 bg-black/30 p-4">
                    {inviteScanOpen && (
                      <video
                        ref={inviteVideoRef}
                        className="w-full max-w-md border border-gray-800 bg-black"
                        muted
                        playsInline
                      />
                    )}
                    {inviteScanStatus && (
                      <div className="mt-3 text-sm text-emerald-300">{inviteScanStatus}</div>
                    )}
                    {inviteScanOpen && (
                      <div className="mt-3">
                        <button
                          onClick={() => setInviteScanOpen(false)}
                          className="px-3 py-2 border border-gray-700 bg-gray-950/20 text-gray-300 text-xs tracking-[0.18em] uppercase"
                        >
                          Stop Scan
                        </button>
                      </div>
                    )}
                  </div>
                )}
                <div className="mt-6">
                  <button
                    onClick={() => void handleImportInvite()}
                    disabled={inviteBusy || !inviteImportBlob.trim()}
                    className="px-4 py-3 border border-emerald-500/40 bg-emerald-950/20 text-emerald-300 text-xs tracking-[0.18em] uppercase disabled:opacity-50"
                  >
                    {inviteBusy ? 'Importing...' : 'Import Signed Invite'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'restricted' && (
          <div className="h-full overflow-y-auto pt-4">
            <div className="border border-gray-800/80 p-6">
              <div className="text-xs tracking-[0.2em] uppercase text-cyan-300 mb-4 flex items-center">
                <ShieldOff size={14} className="mr-2" />
                Restricted Contacts
              </div>
              {blockedContacts.length === 0 ? (
                <div className="text-sm text-gray-500">No restricted contacts on this install.</div>
              ) : (
                <div className="space-y-3">
                  {blockedContacts.map(([peerId]) => (
                    <div key={peerId} className="border border-gray-800/60 p-4 flex items-center justify-between gap-4">
                      <div>
                        <div className="text-gray-300 font-semibold">{peerId}</div>
                        <div className="text-xs text-gray-500 mt-1">Mail from this peer is locally restricted.</div>
                      </div>
                      <button
                        onClick={() => {
                          unblockContact(peerId);
                          setContacts(getContacts());
                        }}
                        className="px-4 py-2 border border-cyan-500/40 bg-cyan-950/20 text-cyan-300 text-sm tracking-[0.18em] uppercase"
                      >
                        Restore
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
