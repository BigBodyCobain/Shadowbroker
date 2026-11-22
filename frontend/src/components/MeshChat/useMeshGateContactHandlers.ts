import { useCallback } from 'react';
import { API_BASE } from '@/lib/api';
import { describeNativeControlError } from '@/lib/desktopControlContract';
import { verifyEventSignature } from '@/mesh/meshIdentity';
import { ratchetEncryptDM } from '@/mesh/meshDmWorkerClient';
import { ratchetReset } from '@/mesh/meshDmWorkerClient';
import { fetchDmPublicKey, sendDmMessage, sharedMailboxToken } from '@/mesh/meshDmClient';
import { generateSharedAlias, buildAliasRotateMessage, mergeAliasHistory, preferredDmPeerId } from '@/mesh/meshDmConsent';
import {
  activateWormholeGatePersona, clearWormholeGatePersona, createWormholeGatePersona,
  resyncWormholeGateState, retireWormholeGatePersona, rotateWormholeGateKey,
  rotateWormholePairwiseAlias, acknowledgeWormholeSasFingerprint, confirmWormholeSasVerification,
  recoverWormholeSasRootContinuity,
} from '@/mesh/wormholeIdentityClient';
import { SHARED_ALIAS_GRACE_MS, SHARED_ALIAS_ROTATE_MS } from './types';


export interface MeshGateContactHandlersCtx { [k: string]: any }

export function useMeshGateContactHandlers(ctx: any) {
  const {
    activeTab, hasId, busy, inputValue, selectedGate, selectedGateAccessReady, anonymousPublicBlocked, privateInfonetReady,
    wormholeEnabled, wormholeReadyState, anonymousDmBlocked, privacyProfile, expanded, identity, contacts, selectedContact,
    dmView, accessRequests, pendingSent, dmConsentScopeId, lastSendTime, meshRegion, meshChannel, meshDirectTarget,
    meshDestination, meshSenderAddress, meshMqttEnabled, meshSessionActive, meshQuickStatus, gateCompatConsentPrompt,
    gatePersonaBusy, gateKeyBusy, gateResyncBusy, sasPhrase, sasConfirmInput, dmMaintenanceBusy,
    setInputValue, setSendError, setBusy, setLastSendTime, setContacts, setDmMessages, setDmUnread, setAccessRequestsState,
    setPendingSentState, setLastDmTransport, setMeshMessages, setMeshQuickStatus, setMeshSessionActive, setMeshView,
    setGateError, setGateKeyBusy, setGateKeyStatus, setGatePersonaBusy, setGatePersonaDraftLabel, setGatePersonaPromptError,
    setGatePersonaPromptGateId, setGatePersonaPromptOpen, setGatePersonas, setActiveGatePersonaId, setGateReplyContext,
    setGateCompatConsentPrompt, setGateResyncBusy, setInfoMessages, setInfoVerification, setShowSas, setSasConfirmInput,
    setSasPhrase, setDmMaintenanceBusy, setGates, setSelectedGate, setGateCompatActive, setNewGateId,
    isWormholeSecureRequired, isGateSendBlocked, getContacts, updateContact, addContact, getAccessRequests, setAccessRequests,
    setPendingSent, getPendingSent, gateReplyContext, meshView,
    activeGatePersonaId, approveGateCompatFallback, clearGateResyncRequired, gatePersonaPromptSeenRef, gatePersonas,
    handleSend, hydrateWormholeContacts, markGateResyncRequired, promotePendingAlias, refreshInfonetMessages,
    refreshNativeAuditReport, refreshSelectedGateKeyStatus, refreshSelectedGatePersonas, enqueueDmSend,
  } = ctx as any;
  const handleResyncGateState = useCallback(
    async (gateIdOverride?: string): Promise<boolean> => {
      const gateId = String(gateIdOverride || selectedGate || '').trim().toLowerCase();
      if (!gateId || !wormholeEnabled || !wormholeReadyState || gateResyncBusy) return false;
      setGateResyncBusy(true);
      setGateError('');
      try {
        const resynced = await resyncWormholeGateState(gateId);
        if (!resynced.ok) {
          throw new Error(resynced.detail || 'gate_state_resync_failed');
        }
        clearGateResyncRequired(gateId);
        await refreshSelectedGateKeyStatus(gateId).catch(() => null);
        await refreshSelectedGatePersonas(gateId).catch(() => null);
        if (selectedGate === gateId) {
          await refreshInfonetMessages({ gateId, force: true });
        }
        setSendError('gate state resynced — retry the room action');
        window.setTimeout(() => setSendError(''), 4000);
        refreshNativeAuditReport();
        return true;
      } catch (err) {
        const detail =
          describeNativeControlError(err) ||
          (err instanceof Error && err.message) ||
          'Failed to resync gate state';
        setGateError(detail);
        markGateResyncRequired(err, gateId);
        return false;
      } finally {
        setGateResyncBusy(false);
      }
    },
    [
      clearGateResyncRequired,
      gateResyncBusy,
      markGateResyncRequired,
      refreshNativeAuditReport,
      refreshInfonetMessages,
      refreshSelectedGateKeyStatus,
      refreshSelectedGatePersonas,
      selectedGate,
      wormholeEnabled,
      wormholeReadyState,
    ],
  );

  const closeGatePersonaPrompt = useCallback(() => {
    setGatePersonaPromptOpen(false);
    setGatePersonaPromptGateId('');
    setGatePersonaDraftLabel('');
    setGatePersonaPromptError('');
  }, []);

  const openGatePersonaPrompt = useCallback(
    (gateIdOverride?: string) => {
      const gateId = String(gateIdOverride || selectedGate || '').trim().toLowerCase();
      if (!gateId) return;
      gatePersonaPromptSeenRef.current.add(gateId);
      setGatePersonaPromptGateId(gateId);
      setGatePersonaDraftLabel('');
      setGatePersonaPromptError('');
      setGatePersonaPromptOpen(true);
    },
    [selectedGate],
  );

  const handleCreateGatePersona = async (labelOverride?: string): Promise<boolean> => {
    const gateId = selectedGate.trim().toLowerCase();
    if (!gateId || !wormholeEnabled || !wormholeReadyState || gatePersonaBusy) return false;
    if (anonymousPublicBlocked) {
      setGateError('hidden transport required for anonymous gate personas');
      return false;
    }
    setGatePersonaBusy(true);
    setGateError('');
    setGatePersonaPromptError('');
    try {
      const existing = gatePersonas[gateId] || [];
      const nextLabel =
        String(labelOverride || '').trim() || `anon_${String(existing.length + 1).padStart(2, '0')}`;
      const created = await createWormholeGatePersona(gateId, nextLabel);
      if (!created.ok) {
        throw new Error(created.detail || 'persona_create_failed');
      }
      clearGateResyncRequired(gateId);
      await refreshSelectedGatePersonas(gateId);
      await refreshSelectedGateKeyStatus(gateId);
      return true;
    } catch (err) {
      const detail = describeNativeControlError(err) || 'Failed to create persona';
      setGateError(detail);
      setGatePersonaPromptError(detail);
      markGateResyncRequired(err, gateId);
      return false;
    } finally {
      refreshNativeAuditReport();
      setGatePersonaBusy(false);
    }
  };

  const handleSelectGatePersona = async (personaId: string): Promise<boolean> => {
    const gateId = selectedGate.trim().toLowerCase();
    if (!gateId || !wormholeEnabled || !wormholeReadyState || gatePersonaBusy) return false;
    if (anonymousPublicBlocked) {
      setGateError('hidden transport required for anonymous gate personas');
      return false;
    }
    setGatePersonaBusy(true);
    setGateError('');
    setGatePersonaPromptError('');
    try {
      const response =
        personaId === '__anon__'
          ? await clearWormholeGatePersona(gateId)
          : await activateWormholeGatePersona(gateId, personaId);
      if (!response.ok) {
        throw new Error(response.detail || 'persona_activate_failed');
      }
      clearGateResyncRequired(gateId);
      await refreshSelectedGatePersonas(gateId);
      await refreshSelectedGateKeyStatus(gateId);
      refreshNativeAuditReport();
      return true;
    } catch (err) {
      const detail = describeNativeControlError(err) || 'Failed to switch gate persona';
      setGateError(detail);
      setGatePersonaPromptError(detail);
      markGateResyncRequired(err, gateId);
      return false;
    } finally {
      refreshNativeAuditReport();
      setGatePersonaBusy(false);
    }
  };

  const handleRetireGatePersona = async () => {
    const gateId = selectedGate.trim().toLowerCase();
    const personaId = gateId ? activeGatePersonaId[gateId] || '' : '';
    if (!gateId || !personaId || !wormholeEnabled || !wormholeReadyState || gatePersonaBusy) return;
    if (anonymousPublicBlocked) {
      setGateError('hidden transport required for anonymous gate personas');
      return;
    }
    setGatePersonaBusy(true);
    setGateError('');
    try {
      const retired = await retireWormholeGatePersona(gateId, personaId);
      if (!retired.ok) {
        throw new Error(retired.detail || 'persona_retire_failed');
      }
      clearGateResyncRequired(gateId);
      await refreshSelectedGatePersonas(gateId);
      await refreshSelectedGateKeyStatus(gateId);
      refreshNativeAuditReport();
    } catch (err) {
      setGateError(describeNativeControlError(err) || 'Failed to retire persona');
      markGateResyncRequired(err, gateId);
    } finally {
      refreshNativeAuditReport();
      setGatePersonaBusy(false);
    }
  };

  const handleRotateGateKey = async () => {
    const gateId = selectedGate.trim().toLowerCase();
    if (!gateId || !wormholeEnabled || !wormholeReadyState || gateKeyBusy) return;
    setGateKeyBusy(true);
    setGateError('');
    try {
      const rotated = await rotateWormholeGateKey(gateId, 'operator_reset');
      if (!rotated.ok) {
        throw new Error(rotated.detail || 'gate_key_rotate_failed');
      }
      clearGateResyncRequired(gateId);
      setGateKeyStatus((prev: any) => ({ ...prev, [gateId]: rotated }));
      await refreshSelectedGatePersonas(gateId);
      refreshNativeAuditReport();
    } catch (err) {
      setGateError(describeNativeControlError(err) || 'Failed to rotate gate key');
      markGateResyncRequired(err, gateId);
    } finally {
      refreshNativeAuditReport();
      setGateKeyBusy(false);
    }
  };

  const handleUnlockEncryptedGate = useCallback(() => {
    openGatePersonaPrompt();
  }, [openGatePersonaPrompt]);

  const maybeRotateSharedAlias = async (
    contactId: string,
    contact: any,
    options?: { force?: boolean },
  ): Promise<any> => {
    const promotion = promotePendingAlias(contactId, contact);
    if (promotion) updateContact(contactId, promotion.delta.updates);
    const refreshed = promotion?.promoted || contact;
    const currentAlias = String(refreshed.sharedAlias || '').trim();
    if (!currentAlias || !refreshed.dhPubKey) {
      return refreshed;
    }
    if (String(refreshed.pendingSharedAlias || '').trim()) {
      return refreshed;
    }
    const lastRotatedAt = Number(refreshed.sharedAliasRotatedAt || 0);
    if (!options?.force && lastRotatedAt > 0 && Date.now() - lastRotatedAt < SHARED_ALIAS_ROTATE_MS) {
      return refreshed;
    }
    let nextAlias = '';
    try {
      const rotated = await rotateWormholePairwiseAlias(
        contactId,
        refreshed.dhPubKey,
        SHARED_ALIAS_GRACE_MS,
      );
      nextAlias = String(rotated.pending_alias || '').trim();
    } catch {
      nextAlias = '';
    }
    if (!nextAlias) {
      nextAlias = generateSharedAlias();
    }
    const controlPlaintext = buildAliasRotateMessage(nextAlias);
    const controlCiphertext = await ratchetEncryptDM(contactId, refreshed.dhPubKey, controlPlaintext);
    const recipientToken = await sharedMailboxToken(currentAlias, refreshed.dhPubKey);
    const msgId = `dm_${Date.now()}_${identity!.nodeId.slice(-4)}`;
    const timestamp = Math.floor(Date.now() / 1000);
    await enqueueDmSend(async () => {
      const sent = await sendDmMessage({
        apiBase: API_BASE,
        identity: identity!,
        recipientId: currentAlias,
        recipientDhPub: refreshed.dhPubKey,
        ciphertext: controlCiphertext,
        msgId,
        timestamp,
        deliveryClass: 'shared',
        recipientToken,
        useSealedSender: true,
      });
      if (!sent.ok) {
        throw new Error(sent.detail || 'alias_rotate_send_failed');
      }
      if (sent.transport === 'reticulum' || sent.transport === 'relay') {
        setLastDmTransport(sent.transport);
      }
    });
    updateContact(contactId, {
      pendingSharedAlias: nextAlias,
      sharedAliasGraceUntil: Date.now() + SHARED_ALIAS_GRACE_MS,
      sharedAliasRotatedAt: Date.now(),
      previousSharedAliases: mergeAliasHistory([
        refreshed.sharedAlias,
        ...(refreshed.previousSharedAliases || []),
      ]),
    });
    setContacts(getContacts());
    return getContacts()[contactId] || refreshed;
  };

  const refreshDmContactState = async (
    contactId: string,
    options?: { rotateAlias?: boolean; resetRatchet?: boolean },
  ): Promise<void> => {
    const targetId = String(contactId || '').trim();
    if (!targetId || !identity) return;
    const existing = getContacts()[targetId];
    const lookupHandle = String(existing?.invitePinnedPrekeyLookupHandle || '').trim();
    if (!lookupHandle) {
      throw new Error(
        'import or re-import a signed invite before refreshing this contact; legacy direct lookup is disabled',
      );
    }
    const registry = await fetchDmPublicKey(API_BASE, targetId, lookupHandle, {
      lookupPeerUrl: existing?.invitePinnedLookupPeerUrl,
    }).catch(() => null);
    if (!registry?.dh_pub_key) {
      throw new Error(
        'invite-scoped lookup failed for this contact; re-import a signed invite and try again',
      );
    }
    if (registry?.dh_pub_key) {
      addContact(targetId, String(registry.dh_pub_key), undefined, registry.dh_algo);
      let registryOk = true;
      if (registry.signature && registry.public_key && registry.public_key_algo) {
        try {
          const keyPayload = {
            dh_pub_key: registry.dh_pub_key,
            dh_algo: registry.dh_algo,
            timestamp: registry.timestamp,
          };
          registryOk = await verifyEventSignature({
            eventType: 'dm_key',
            nodeId: targetId,
            sequence: Number(registry.sequence || 0),
            payload: keyPayload,
            signature: registry.signature,
            publicKey: registry.public_key,
            publicKeyAlgo: registry.public_key_algo,
          });
        } catch {
          registryOk = false;
        }
      }
      const prior = getContacts()[targetId] || existing;
      const inbandOk = Boolean(prior?.verify_inband);
      const registryKey = String(registry.dh_pub_key || '');
      const inbandKey = String(prior?.dhPubKey || '');
      const verified = inbandOk && registryOk && inbandKey === registryKey;
      updateContact(targetId, {
        dhAlgo: registry.dh_algo || prior?.dhAlgo,
        verify_registry: registryOk,
        verified,
        verify_mismatch: inbandOk && registryOk && inbandKey !== registryKey,
        verified_at: verified ? Date.now() : prior?.verified_at,
        remotePrekeyTransparencyHead:
          String(registry.prekey_transparency_head || '') ||
          prior?.remotePrekeyTransparencyHead,
        remotePrekeyTransparencySize:
          Number(registry.prekey_transparency_size || 0) || prior?.remotePrekeyTransparencySize,
        remotePrekeyTransparencySeenAt: registry.prekey_transparency_head
          ? Date.now()
          : prior?.remotePrekeyTransparencySeenAt,
        remotePrekeyLookupMode:
          String(registry.lookup_mode || '').trim().toLowerCase() ||
          prior?.remotePrekeyLookupMode,
        witness_count:
          Number(registry.witness_count || 0) || prior?.witness_count,
        witness_checked_at:
          Number(registry.witness_latest_at || 0) || prior?.witness_checked_at,
      });
    }
    const latest = getContacts()[targetId] || existing;
    if (latest?.dhPubKey) {
      try {
        const witnessRes = await fetch(
          `${API_BASE}/api/mesh/dm/witness?target_id=${encodeURIComponent(
            targetId,
          )}&dh_pub_key=${encodeURIComponent(latest.dhPubKey)}`,
        );
        if (witnessRes.ok) {
          const witnessData = await witnessRes.json();
          updateContact(targetId, {
            witness_count: witnessData.count || 0,
            witness_checked_at: Date.now(),
          });
        }
      } catch {
        /* ignore */
      }
    }
    try {
      const vouchRes = await fetch(
        `${API_BASE}/api/mesh/trust/vouches?node_id=${encodeURIComponent(targetId)}`,
      );
      if (vouchRes.ok) {
        const vouchData = await vouchRes.json();
        updateContact(targetId, {
          vouch_count: vouchData.count || 0,
          vouch_checked_at: Date.now(),
        });
      }
    } catch {
      /* ignore */
    }
    if (options?.resetRatchet) {
      await ratchetReset(targetId);
    }
    const refreshed = getContacts()[targetId];
    if (options?.rotateAlias && refreshed?.dhPubKey) {
      await maybeRotateSharedAlias(targetId, refreshed, { force: true });
    }
    const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
    setContacts(hydratedContacts);
  };

  const handleRefreshSelectedContact = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    setDmMaintenanceBusy(true);
    try {
      await refreshDmContactState(selectedContact, { rotateAlias: true });
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'dm refresh failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };

  const handleResetSelectedContact = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    setDmMaintenanceBusy(true);
    try {
      await refreshDmContactState(selectedContact, { rotateAlias: true, resetRatchet: true });
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'dm reset failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };

  const handleTrustSelectedRemotePrekey = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    const contactInfo = getContacts()[selectedContact] || contacts[selectedContact];
    if (contactInfo?.remotePrekeyRootMismatch) {
      setSendError(
        'stable root changed; use RECOVER ROOT or replace the signed invite before trusting this contact again',
      );
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    setDmMaintenanceBusy(true);
    try {
      const result = await acknowledgeWormholeSasFingerprint(selectedContact);
      if (!result?.ok) {
        throw new Error(String(result?.detail || 'failed to acknowledge changed fingerprint'));
      }
      const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
      setContacts(hydratedContacts);
      setShowSas(true);
      setSasConfirmInput('');
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'failed to acknowledge changed fingerprint';
      setSendError(detail);
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };

  const handleApproveGateCompatFallback = useCallback(async () => {
    if (!gateCompatConsentPrompt?.gateId) return;
    const approvedGateId = gateCompatConsentPrompt.gateId;
    const action = gateCompatConsentPrompt.action;
    approveGateCompatFallback(approvedGateId);
    setGateCompatActive((prev: any) => (prev[approvedGateId] ? prev : { ...prev, [approvedGateId]: true }));
    setGateCompatConsentPrompt(null);
    setGateError('');
    setSendError('');
    if (action === 'decrypt') {
      await refreshInfonetMessages({ gateId: approvedGateId, force: true });
      return;
    }
    await handleSend();
  }, [gateCompatConsentPrompt, handleSend, refreshInfonetMessages]);

  const handleConfirmSelectedContactSas = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    const contactInfo = getContacts()[selectedContact] || contacts[selectedContact];
    const proof = String(sasConfirmInput || '').trim();
    if (!proof) {
      setSendError('type the SAS phrase to confirm verification');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    setDmMaintenanceBusy(true);
    try {
      const result = await confirmWormholeSasVerification(
        selectedContact,
        proof,
        preferredDmPeerId(selectedContact, contactInfo),
        8,
      );
      if (!result?.ok) {
        throw new Error(String(result?.detail || 'sas verification failed'));
      }
      const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
      setContacts(hydratedContacts);
      setSasConfirmInput('');
      setShowSas(true);
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'sas verification failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };

  const handleRecoverSelectedContactRootContinuity = async (): Promise<void> => {
    if (!selectedContact || dmMaintenanceBusy) return;
    const contactInfo = getContacts()[selectedContact] || contacts[selectedContact];
    const proof = String(sasConfirmInput || '').trim();
    if (!proof) {
      setSendError('type the SAS phrase to recover the changed stable root');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    setDmMaintenanceBusy(true);
    try {
      const result = await recoverWormholeSasRootContinuity(
        selectedContact,
        proof,
        preferredDmPeerId(selectedContact, contactInfo),
        8,
      );
      if (!result?.ok) {
        throw new Error(String(result?.detail || 'stable root recovery failed'));
      }
      const hydratedContacts = await hydrateWormholeContacts(true).catch(() => getContacts());
      setContacts(hydratedContacts);
      setSasConfirmInput('');
      setShowSas(true);
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'stable root recovery failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 3000);
    } finally {
      setDmMaintenanceBusy(false);
    }
  };


  return {
    handleResyncGateState, handleCreateGatePersona, handleSelectGatePersona, handleRetireGatePersona, handleRotateGateKey,
    handleUnlockEncryptedGate, handleRefreshSelectedContact, handleResetSelectedContact, handleTrustSelectedRemotePrekey,
    handleApproveGateCompatFallback, handleConfirmSelectedContactSas, handleRecoverSelectedContactRootContinuity,
  };
}
