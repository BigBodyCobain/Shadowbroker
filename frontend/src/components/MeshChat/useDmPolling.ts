// @ts-nocheck
'use client';

import { isWormholeSecureRequired } from '@/mesh/wormholeIdentityClient';
import { useEffect } from 'react';
import { API_BASE } from '@/lib/api';
import { classifyTick, jitteredPollDelay, MAX_CATCHUP_POLLS } from '@/lib/dmPollScheduler';
import { isDmPollBlocked } from '@/lib/meshChatPolicies';
import {
  buildMailboxClaims,
  countDmMailboxes,
  fetchDmPublicKey,
  pollDmMailboxes,
} from '@/mesh/meshDmClient';
import {
  bootstrapDecryptAccessRequest,
  canUseWormholeBootstrap,
} from '@/mesh/wormholeDmBootstrapClient';
import { decryptDM, deriveSharedKey } from '@/mesh/meshIdentity';
import { ratchetDecryptDM } from '@/mesh/meshDmWorkerClient';
import { deriveSasPhrase } from '@/mesh/meshSas';
import type { AccessRequest, Contact, DMMessage, NodeIdentity } from './types';
import {
  addContact,
  getContacts,
  getDMNotify,
  updateContact,
} from '@/mesh/meshIdentity';
import {
  decryptSenderSealForContact,
  getAccessRequests,
  getPendingSent,
  getSenderRecoveryState,
  mergeAliasHistory,
  parseAliasRotateMessage,
  parseDmConsentMessage,
  preferredDmPeerId,
  requiresSenderRecovery,
  setAccessRequests,
  setPendingSent,
  shouldAutoRevealSasForTrust,
  shouldKeepUnresolvedRequestVisible,
  shouldPromoteRecoveredSenderForBootstrap,
  shouldPromoteRecoveredSenderForKnownContact,
} from './storage';

type DmView = 'contacts' | 'chat' | 'requests' | 'new';
type PrivacyProfile = 'normal' | 'private' | 'hardened';

export function useDmPolling(args: {
  hasId: boolean;
  identity: NodeIdentity | null;
  expanded: boolean;
  activeTab: string;
  wormholeEnabled: boolean;
  wormholeReadyState: boolean;
  anonymousDmBlocked: boolean;
  privacyProfile: PrivacyProfile;
  selectedContact: string | null;
  dmView: DmView;
  contacts: Record<string, Contact>;
  accessRequests: AccessRequest[];
  pendingSent: string[];
  dmConsentScopeId: string;
  setContacts: React.Dispatch<React.SetStateAction<Record<string, Contact>>>;
  setDmUnread: React.Dispatch<React.SetStateAction<number>>;
  setUnresolvedSenderSealCount: React.Dispatch<React.SetStateAction<number>>;
  setDmMessages: React.Dispatch<React.SetStateAction<DMMessage[]>>;
  setAccessRequestsState: React.Dispatch<React.SetStateAction<AccessRequest[]>>;
  setPendingSentState: React.Dispatch<React.SetStateAction<string[]>>;
  setLastDmTransport: React.Dispatch<React.SetStateAction<'relay' | 'reticulum'>>;
  setShowSas: React.Dispatch<React.SetStateAction<boolean>>;
  setSasPhrase: React.Dispatch<React.SetStateAction<string>>;
  setSasConfirmInput: React.Dispatch<React.SetStateAction<string>>;
}) {
  const {
    hasId, identity, expanded, activeTab, wormholeEnabled, wormholeReadyState,
    anonymousDmBlocked, privacyProfile, selectedContact, dmView, contacts,
    accessRequests, pendingSent, dmConsentScopeId,
    setContacts, setDmUnread, setUnresolvedSenderSealCount, setDmMessages,
    setAccessRequestsState, setPendingSentState, setLastDmTransport,
    setShowSas, setSasPhrase, setSasConfirmInput,
  } = args;


  useEffect(() => {
    setContacts(getContacts());
  }, [expanded, activeTab]);

  // Poll unread count — slower when collapsed to reduce network/CPU usage
  useEffect(() => {
    if (!hasId || !getDMNotify() || (expanded && activeTab === 'dms')) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      const baseDelay = expanded ? DM_UNREAD_POLL_EXPANDED_MS : DM_UNREAD_POLL_COLLAPSED_MS;
      timer = setTimeout(
        poll,
        jitteredPollDelay(baseDelay, { profile: privacyProfile }),
      );
    };
    const poll = async () => {
      if (isDmPollBlocked(wormholeEnabled, wormholeReadyState, anonymousDmBlocked)) {
        if (!cancelled) setDmUnread(0);
        if (!cancelled) schedule();
        return;
      }
      try {
        const claims = await buildMailboxClaims(getContacts());
        const data = await countDmMailboxes(API_BASE, identity!, claims);
        if (data.ok && !cancelled) {
          setDmUnread(data.count || 0);
        } else if (!cancelled) {
          setUnresolvedSenderSealCount(0);
        }
      } catch {
        if (!cancelled) setUnresolvedSenderSealCount(0);
      } finally {
        if (!cancelled) schedule();
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [
    hasId,
    identity,
    expanded,
    activeTab,
    wormholeEnabled,
    wormholeReadyState,
    anonymousDmBlocked,
    privacyProfile,
  ]);

  // Poll DM messages — also detect access requests (messages from unknown senders)
  useEffect(() => {
    if (!expanded || activeTab !== 'dms' || !hasId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let catchUpBudget = MAX_CATCHUP_POLLS;
    const poll = async (includeCount = true) => {
      let hasMore = false;
      if (isDmPollBlocked(wormholeEnabled, wormholeReadyState, anonymousDmBlocked)) {
        if (!cancelled) {
          setDmMessages([]);
          setDmUnread(0);
        }
        return;
      }
      try {
        const claims = await buildMailboxClaims(getContacts());
        const pollPromise = pollDmMailboxes(API_BASE, identity!, claims);
        const countPromise = includeCount
          ? countDmMailboxes(API_BASE, identity!, claims).catch(() => ({ ok: false, count: 0 }))
          : null;
        const [data, countResult] = await Promise.all([pollPromise, countPromise]);
        if (data.ok && !cancelled) {
          hasMore = Boolean(data.has_more);
          if (countResult) {
            setDmUnread(Number(countResult.count || 0));
          }
          const msgs: DMMessage[] = (data.messages || []).map((message) => ({
            ...message,
            transport: message.transport || 'relay',
            sender_recovery_state: getSenderRecoveryState(message),
            seal_resolution_failed: getSenderRecoveryState(message) === 'failed',
          }));
          const currentContacts = getContacts();
          const newRequests: AccessRequest[] = [];
          const knownMsgs: DMMessage[] = [];
          let unresolvedSeals = 0;
          const secureRequired = await isWormholeSecureRequired();

          for (const rawMessage of msgs) {
            let m = { ...rawMessage };
            let parsedFromSeal: ReturnType<typeof parseDmConsentMessage> | null = null;
            const senderSeal = String(m.sender_seal || '');
            const recoveryRequired = requiresSenderRecovery(m);
            const allowOpaqueRequestInbox = shouldKeepUnresolvedRequestVisible(m);

            if (recoveryRequired && senderSeal) {
              for (const [contactId, contact] of Object.entries(currentContacts)) {
                if (!contact.dhPubKey || contact.blocked) continue;
                const resolved = await decryptSenderSealForContact(
                  senderSeal,
                  contact.dhPubKey,
                  contact,
                  identity!.nodeId,
                  m.msg_id,
                );
                if (resolved && shouldPromoteRecoveredSenderForKnownContact(resolved, contactId)) {
                  m = {
                    ...m,
                    sender_id: resolved.sender_id,
                    seal_verified: resolved.seal_verified,
                    sender_recovery_state: 'verified',
                  };
                  break;
                }
              }

              if (
                m.sender_id.startsWith('sealed:') &&
                m.ciphertext.startsWith('x3dh1:') &&
                (await canUseWormholeBootstrap())
              ) {
                try {
                  const requestText = await bootstrapDecryptAccessRequest('', m.ciphertext);
                  parsedFromSeal = parseDmConsentMessage(requestText);
                  if (parsedFromSeal?.kind === 'contact_offer' && parsedFromSeal.dh_pub_key) {
                    const resolved = await decryptSenderSealForContact(
                      senderSeal,
                      parsedFromSeal.dh_pub_key,
                      undefined,
                      identity!.nodeId,
                      m.msg_id,
                    );
                    if (resolved && shouldPromoteRecoveredSenderForBootstrap(resolved)) {
                      m = {
                        ...m,
                        sender_id: resolved.sender_id,
                        seal_verified: resolved.seal_verified,
                        sender_recovery_state: 'verified',
                      };
                    }
                  }
                } catch {
                  parsedFromSeal = null;
                }
              }

              if (m.sender_id.startsWith('sealed:')) {
                unresolvedSeals += 1;
                m = {
                  ...m,
                  seal_resolution_failed: true,
                  seal_verified: false,
                  sender_recovery_state: 'failed',
                };
              }
            }

            if (
              currentContacts[m.sender_id] &&
              currentContacts[m.sender_id].dhPubKey &&
              !currentContacts[m.sender_id].blocked
            ) {
              knownMsgs.push(m);
            } else if (
              !currentContacts[m.sender_id]?.blocked &&
              (!m.sender_id.startsWith('sealed:') || allowOpaqueRequestInbox)
            ) {
              // Unknown sender = access request
              const senderContact = currentContacts[m.sender_id];
              const existing = accessRequests;
              let consent = parsedFromSeal;
              try {
                if (!consent && m.ciphertext.startsWith('x3dh1:') && (await canUseWormholeBootstrap())) {
                  const requestText = await bootstrapDecryptAccessRequest(
                    allowOpaqueRequestInbox ? '' : m.sender_id,
                    m.ciphertext,
                  );
                  consent = parseDmConsentMessage(requestText);
                } else if (!consent && !secureRequired) {
                  const senderKey = await fetchDmPublicKey(
                    API_BASE,
                    m.sender_id,
                    senderContact?.invitePinnedPrekeyLookupHandle,
                    { lookupPeerUrl: senderContact?.invitePinnedLookupPeerUrl },
                  );
                  if (senderKey?.dh_pub_key) {
                    const sharedKey = await deriveSharedKey(String(senderKey.dh_pub_key));
                    const requestText = await decryptDM(m.ciphertext, sharedKey);
                    consent = parseDmConsentMessage(requestText);
                  }
                }
              } catch {
                consent = null;
              }
              if (consent?.kind === 'contact_accept' && consent.shared_alias) {
                const senderKey = await fetchDmPublicKey(
                  API_BASE,
                  m.sender_id,
                  senderContact?.invitePinnedPrekeyLookupHandle,
                  { lookupPeerUrl: senderContact?.invitePinnedLookupPeerUrl },
                ).catch(() => null);
                if (senderKey?.dh_pub_key) {
                  addContact(m.sender_id, String(senderKey.dh_pub_key), undefined, senderKey.dh_algo);
                  updateContact(m.sender_id, {
                    dhAlgo: senderKey.dh_algo,
                    remotePrekeyLookupMode:
                      String(senderKey.lookup_mode || '').trim().toLowerCase() ||
                      senderContact?.remotePrekeyLookupMode,
                    sharedAlias: consent.shared_alias,
                    previousSharedAliases: [],
                    pendingSharedAlias: undefined,
                    sharedAliasGraceUntil: undefined,
                    sharedAliasRotatedAt: Date.now(),
                  });
                  const remainingPending = pendingSent.filter((id) => id !== m.sender_id);
                  setPendingSent(remainingPending, dmConsentScopeId);
                  setPendingSentState(remainingPending);
                  setContacts(getContacts());
                }
                } else if (consent?.kind === 'contact_deny') {
                  const remainingPending = pendingSent.filter((id) => id !== m.sender_id);
                  setPendingSent(remainingPending, dmConsentScopeId);
                  setPendingSentState(remainingPending);
                } else {
                  const existingReq = existing.find((r) => r.sender_id === m.sender_id);
                  const shouldCreateUnresolvedRequest = shouldKeepUnresolvedRequestVisible(m);
                  if (!existingReq && (consent?.kind === 'contact_offer' || shouldCreateUnresolvedRequest)) {
                    newRequests.push({
                      sender_id: m.sender_id,
                      timestamp: m.timestamp,
                      dh_pub_key: consent?.kind === 'contact_offer' ? consent.dh_pub_key : undefined,
                      dh_algo: consent?.kind === 'contact_offer' ? consent.dh_algo : undefined,
                      geo_hint: consent?.kind === 'contact_offer' ? consent.geo_hint : undefined,
                      request_contract_version: m.request_contract_version,
                      sender_recovery_required: m.sender_recovery_required,
                      sender_recovery_state: m.sender_recovery_state,
                    });
                  } else if (
                    existingReq &&
                    consent?.kind === 'contact_offer' &&
                    !existingReq.dh_pub_key &&
                    consent.dh_pub_key
                  ) {
                    const updated = existing.map((r) =>
                      r.sender_id === m.sender_id
                        ? {
                          ...r,
                          dh_pub_key: consent.dh_pub_key,
                          dh_algo: consent.dh_algo || r.dh_algo,
                          geo_hint: consent.geo_hint || r.geo_hint,
                          request_contract_version: m.request_contract_version || r.request_contract_version,
                          sender_recovery_required:
                            m.sender_recovery_required ?? r.sender_recovery_required,
                          sender_recovery_state: m.sender_recovery_state || r.sender_recovery_state,
                        }
                        : r,
                    );
                  setAccessRequests(updated, dmConsentScopeId);
                  setAccessRequestsState(updated);
                }
              }
            }
          }

          // Save new access requests
          if (newRequests.length > 0) {
            const all = [...accessRequests, ...newRequests];
            setAccessRequests(all, dmConsentScopeId);
            setAccessRequestsState(all);
          }
          setUnresolvedSenderSealCount(unresolvedSeals);

          // Decrypt messages from selected contact
          if (selectedContact && dmView === 'chat') {
            const contactInfo = currentContacts[selectedContact];
            if (contactInfo?.dhPubKey) {
              const decrypted: DMMessage[] = [];
              const secureRequired = await isWormholeSecureRequired();
              for (const m of knownMsgs.filter((m) => m.sender_id === selectedContact)) {
                try {
                  let plaintext = '';
                  try {
                    plaintext = await ratchetDecryptDM(selectedContact, m.ciphertext);
                  } catch (err) {
                    const message =
                      typeof err === 'object' && err !== null && 'message' in err
                        ? String((err as { message?: string }).message)
                        : '';
                    if (message === 'legacy') {
                      if (secureRequired) {
                        throw new Error('legacy_dm_blocked_in_secure_mode');
                      }
                      const sharedKey = await deriveSharedKey(contactInfo.dhPubKey!);
                      plaintext = await decryptDM(m.ciphertext, sharedKey);
                    } else {
                      throw err;
                    }
                  }
                  let sealVerified: boolean | undefined;
                  let sealResolutionFailed = Boolean(m.seal_resolution_failed);
                  if (m.sender_seal) {
                    try {
                      const opened = await decryptSenderSealForContact(
                        m.sender_seal,
                        contactInfo.dhPubKey!,
                        contactInfo,
                        identity!.nodeId,
                        m.msg_id,
                      );
                      if (opened?.sender_id === m.sender_id) {
                        sealVerified = opened.seal_verified;
                      } else {
                        sealVerified = false;
                        sealResolutionFailed = true;
                      }
                    } catch {
                      sealVerified = false;
                      sealResolutionFailed = true;
                    }
                  }
                  const aliasRotate = parseAliasRotateMessage(plaintext);
                  if (aliasRotate?.shared_alias) {
                    updateContact(selectedContact, {
                      sharedAlias: aliasRotate.shared_alias,
                      pendingSharedAlias: undefined,
                      sharedAliasGraceUntil: undefined,
                      sharedAliasRotatedAt: Date.now(),
                      previousSharedAliases: mergeAliasHistory([
                        currentContacts[selectedContact]?.sharedAlias,
                        ...(currentContacts[selectedContact]?.previousSharedAliases || []),
                      ]),
                    });
                    setContacts(getContacts());
                    continue;
                  }
                  decrypted.push({
                    ...m,
                    plaintext,
                    seal_verified: sealVerified,
                    seal_resolution_failed: sealResolutionFailed,
                  });
                } catch {
                  decrypted.push({ ...m, plaintext: '[decryption failed]' });
                }
              }
              setDmMessages(decrypted);
              const latestTransport = [...decrypted]
                .sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0))
                .find((item) => item.transport)?.transport;
              if (latestTransport === 'reticulum' || latestTransport === 'relay') {
                setLastDmTransport(latestTransport);
              }
              if (decrypted.length > 0) setDmUnread(0);
            }
          }
        }
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) {
          const classification = classifyTick(hasMore, catchUpBudget, DM_MESSAGES_POLL_MS, {
            profile: privacyProfile,
          });
          catchUpBudget = classification.newBudget;
          timer = setTimeout(() => void poll(classification.refreshCount), classification.delay);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [
    expanded,
    activeTab,
    selectedContact,
    hasId,
    identity,
    dmView,
    wormholeEnabled,
    wormholeReadyState,
    anonymousDmBlocked,
    privacyProfile,
  ]);

  // SAS phrase for active DM contact
  useEffect(() => {
    let cancelled = false;
    setShowSas(false);
    setSasPhrase('');
    setSasConfirmInput('');
    const run = async () => {
      if (!selectedContact) return;
      const contactInfo = contacts[selectedContact];
      if (!contactInfo?.dhPubKey) return;
      try {
        const phrase = await deriveSasPhrase(
          selectedContact,
          contactInfo.dhPubKey,
          8,
          preferredDmPeerId(selectedContact, contactInfo),
        );
        if (!cancelled) setSasPhrase(phrase);
      } catch {
        if (!cancelled) setSasPhrase('');
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [selectedContact, contacts[selectedContact]?.dhPubKey]);

  useEffect(() => {
    if (!selectedContact) return;
    const contactInfo = contacts[selectedContact];
    if (shouldAutoRevealSasForTrust(contactInfo)) {
      setShowSas(true);
    }
  }, [
    selectedContact,
    contacts[selectedContact]?.remotePrekeyMismatch,
    contacts[selectedContact]?.verify_mismatch,
    contacts[selectedContact]?.remotePrekeyFingerprint,
    contacts[selectedContact]?.remotePrekeyPinnedAt,
    contacts[selectedContact]?.verify_registry,
    contacts[selectedContact]?.verify_inband,
    contacts[selectedContact]?.verified,
  ]);

  // Refresh witness/vouch counts when opening a chat
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (!selectedContact) return;
      const contactInfo = getContacts()[selectedContact];
      if (!contactInfo?.dhPubKey) return;
      try {
        const witnessRes = await fetch(
          `${API_BASE}/api/mesh/dm/witness?target_id=${encodeURIComponent(
            selectedContact,
          )}&dh_pub_key=${encodeURIComponent(contactInfo.dhPubKey)}`,
        );
        if (witnessRes.ok && !cancelled) {
          const witnessData = await witnessRes.json();
          updateContact(selectedContact, {
            witness_count: witnessData.count || 0,
            witness_checked_at: Date.now(),
          });
          setContacts(getContacts());
        }
        const vouchRes = await fetch(
          `${API_BASE}/api/mesh/trust/vouches?node_id=${encodeURIComponent(selectedContact)}`,
        );
        if (vouchRes.ok && !cancelled) {
          const vouchData = await vouchRes.json();
          updateContact(selectedContact, {
            vouch_count: vouchData.count || 0,
            vouch_checked_at: Date.now(),
          });
          setContacts(getContacts());
        }
      } catch {
        /* ignore */
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [selectedContact]);

}
