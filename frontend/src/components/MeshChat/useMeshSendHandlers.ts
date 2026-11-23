'use client';

import { useCallback, useEffect } from 'react';

import { nextSequence } from '@/mesh/meshIdentity';
import { getDHAlgo } from '@/mesh/meshIdentity';
import { validateEventPayload } from '@/mesh/meshSchema';
import { signMeshEvent } from '@/mesh/wormholeIdentityClient';
import { invalidateGateCatalogSnapshot, fetchGateCatalogSnapshot } from '@/mesh/gateCatalogSnapshot';
import { gateCatalogEntryToGate } from './useMeshChatController.helpers';
import { listWormholeGatePersonas, fetchWormholeGateKeyStatus, postWormholeGateMessage } from '@/mesh/wormholeIdentityClient';
import { canUseWormholeBootstrap } from '@/mesh/wormholeDmBootstrapClient';
import { ensureRegisteredDmKey, sendDmMessage, sharedMailboxToken } from '@/mesh/meshDmClient';
import { ratchetEncryptDM } from '@/mesh/meshDmWorkerClient';
import { preferredDmPeerId } from '@/mesh/meshDmConsent';
import { describeNativeControlError } from '@/lib/desktopControlContract';
import { useMeshGateContactHandlers } from './useMeshGateContactHandlers';
import { API_BASE } from '@/lib/api';

export interface MeshSendHandlersCtx { [k: string]: any; activeTab?: any; hasId?: any; busy?: any; inputValue?: any; selectedGate?: any; selectedGateAccessReady?: any; anonymousPublicBlocked?: any; privateInfonetReady?: any; wormholeEnabled?: any; wormholeReadyState?: any; anonymousDmBlocked?: any; privacyProfile?: any; expanded?: any; identity?: any; contacts?: any; selectedContact?: any; dmView?: any; accessRequests?: any; pendingSent?: any; dmConsentScopeId?: any; lastSendTime?: any; meshRegion?: any; meshChannel?: any; meshDirectTarget?: any; meshDestination?: any; meshSenderAddress?: any; meshMqttEnabled?: any; meshSessionActive?: any; meshQuickStatus?: any; gateCompatConsentPrompt?: any; gatePersonaBusy?: any; gateKeyBusy?: any; gateResyncBusy?: any; sasPhrase?: any; sasConfirmInput?: any; dmMaintenanceBusy?: any; setInputValue?: any; setSendError?: any; setBusy?: any; setLastSendTime?: any; setContacts?: any; setDmMessages?: any; setDmUnread?: any; setAccessRequestsState?: any; setPendingSentState?: any; setLastDmTransport?: any; setMeshMessages?: any; setMeshQuickStatus?: any; setMeshSessionActive?: any; setMeshView?: any; setGateError?: any; setGateKeyBusy?: any; setGateKeyStatus?: any; setGatePersonaBusy?: any; setGatePersonaDraftLabel?: any; setGatePersonaPromptError?: any; setGatePersonaPromptGateId?: any; setGatePersonaPromptOpen?: any; setGatePersonas?: any; setActiveGatePersonaId?: any; setGateReplyContext?: any; setGateCompatConsentPrompt?: any; setGateResyncBusy?: any; setInfoMessages?: any; setInfoVerification?: any; setShowSas?: any; setSasConfirmInput?: any; setSasPhrase?: any; setDmMaintenanceBusy?: any; setGates?: any; setSelectedGate?: any; setGateCompatActive?: any; setNewGateId?: any; isWormholeSecureRequired?: any; isGateSendBlocked?: any; getContacts?: any; updateContact?: any; addContact?: any; getAccessRequests?: any; setAccessRequests?: any; setPendingSent?: any; getPendingSent?: any; gateReplyContext?: any; meshView?: any; }

export function useMeshSendHandlers(ctx: MeshSendHandlersCtx) {
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
    activePublicMeshAddress, clearGateResyncRequired, decoyEnabled, describeGateLocalRuntimeRequired,
    DM_DECOY_POLL_JITTER_MS, DM_DECOY_POLL_MS, enqueueDmSend, hasStoredPublicLaneIdentity,
    jitterDelay, markGateResyncRequired, newGateId, newGateMinRep, newGateName,
    openIdentityWizard, promotePendingAlias, randomBase64, randomHex, refreshNativeAuditReport,
    setNewGateMinRep, setNewGateName, setPublicMeshAddress, setReps, setShowCreateGate, setVotedOn,
    votedOn, voteScopeKey, gateIdentity, setGateIdentity, activeGateIdentity,
    hasPublicLaneIdentity, hasPrivateLaneIdentity, dashboardRestrictedTab, isGateSignedReplyAllowed,
    publicMeshAddress, setPublicMeshBlockedByWormhole, isWormholeSecureReady, dmDecryptionError,
    senders, setSenders, meshInbox, setMeshInbox, sasState, sasVerified, sasConfirmPending,
    setSasVerified, setSasConfirmPending, setSasState, dmPollStatus, setDmPollStatus,
    gatePollStatus, setGatePollStatus, infonetPollStatus, setInfonetPollStatus, hasSovereignty
    } = ctx as any;

  const gateContactHandlers = useMeshGateContactHandlers(ctx);

  const handleSend = async () => {
    const msg = inputValue.trim();
    if (!msg || busy) return;
    if (activeTab !== 'meshtastic' && !hasId) return;

    const cooldownMs = activeTab === 'dms' ? 0 : activeTab === 'meshtastic' ? 6_000 : 30_000;
    const now = Date.now();
    const elapsed = now - lastSendTime;
    if (cooldownMs > 0 && elapsed < cooldownMs) {
      const wait = Math.ceil((cooldownMs - elapsed) / 1000);
      setSendError(`cooldown: ${wait}s`);
      setTimeout(() => setSendError(''), 3000);
      return;
    }

    if (anonymousPublicBlocked && activeTab === 'infonet') {
      setSendError('hidden transport required for infonet posting');
      setTimeout(() => setSendError(''), 4000);
      return;
    }

    if (activeTab === 'infonet' && !privateInfonetReady) {
      setSendError('wormhole required for infonet');
      setTimeout(() => setSendError(''), 4000);
      return;
    }

    if (isGateSendBlocked(activeTab, Boolean(selectedGate), selectedGateAccessReady)) {
      setSendError('gate access still syncing');
      setTimeout(() => setSendError(''), 4000);
      return;
    }

    setInputValue('');
    setSendError('');
    setBusy(true);
    setLastSendTime(now);

    try {
        if (activeTab === 'infonet' && selectedGate) {
          const gateReplyPrefix =
            gateReplyContext && gateReplyContext.gateId === String(selectedGate).trim().toLowerCase()
              ? `>>${gateReplyContext.eventId.slice(0, 8)} @${gateReplyContext.nodeId.slice(0, 12)} `
              : '';
          const gateData = await postWormholeGateMessage(
            selectedGate,
            `${gateReplyPrefix}${msg}`,
            gateReplyContext?.gateId === String(selectedGate).trim().toLowerCase()
              ? gateReplyContext?.eventId || ''
              : '',
          ).catch((error) => ({
            ok: false,
            detail: error instanceof Error ? error.message : 'gate post failed',
          }));
          if (gateData?.ok === false) {
            setInputValue(msg);
            setLastSendTime(0);
            const detail = gateData?.detail || 'gate post failed';
            setSendError(
              detail === 'gate_backend_plaintext_compat_required'
                ? 'Service-side gate send is disabled on this runtime. Use native desktop or an explicit compatibility override.'
                : detail === 'gate_compat_fallback_consent_required' || detail.startsWith('gate_local_runtime_required:')
                  ? describeGateLocalRuntimeRequired(detail, selectedGate)
                  : detail,
            );
            if (markGateResyncRequired(detail, selectedGate)) {
              setGateError(
                describeNativeControlError(detail) ||
                  'Gate state changed on another path. Resync before retrying.',
              );
            }
            setTimeout(() => setSendError(''), 4000);
            return;
        }
        clearGateResyncRequired(selectedGate);
        setInfoMessages((prev: any) => [
          ...prev,
          {
            event_id: `_pending_${Date.now()}`,
            event_type: 'gate_message',
            gate: String(selectedGate || '').trim().toLowerCase(),
            node_id: String(identity?.nodeId || ''),
            message: `${gateReplyPrefix}${msg}`,
            decrypted_message: `${gateReplyPrefix}${msg}`,
            timestamp: Math.floor(Date.now() / 1000),
            ephemeral: true,
          },
        ]);
        setGateReplyContext(null);
        } else if (activeTab === 'meshtastic') {
          const meshSenderAddress = activePublicMeshAddress;
          if (!meshSenderAddress) {
            setInputValue(msg);
            setLastSendTime(0);
            setSendError('public mesh identity needed');
            openIdentityWizard({
              type: 'err',
              text: hasStoredPublicLaneIdentity
                ? 'Quick fix: turn Meshtastic Chat on below, then retry your send.'
                : 'Quick fix: create a public mesh identity below, then retry your send.',
            });
            setTimeout(() => setSendError(''), 4000);
            setBusy(false);
            return;
          }
          if (!meshSessionActive) {
            setPublicMeshAddress(meshSenderAddress);
            setMeshSessionActive(true);
          }
          if (!meshMqttEnabled) {
            setInputValue(msg);
            setLastSendTime(0);
            setSendError('mqtt is off');
            setMeshQuickStatus({
              type: 'err',
              text: 'Public Mesh key is ready, but MQTT is off. Open Settings and enable the public broker.',
            });
            setMeshView('settings');
            setTimeout(() => setSendError(''), 4000);
            setBusy(false);
            return;
          }
          const meshDestination = meshDirectTarget.trim() || 'broadcast';
          const payload = {
            message: msg,
            destination: meshDestination,
            channel: meshChannel,
            priority: 'normal',
            ephemeral: false,
            transport_lock: 'meshtastic',
          };
          const v = validateEventPayload('message', payload);
          if (!v.ok) {
            setInputValue(msg);
            setLastSendTime(0);
            setSendError(`invalid payload: ${v.reason}`);
            setTimeout(() => setSendError(''), 4000);
            setBusy(false);
            return;
          }
          const sendRes = await fetch(`${API_BASE}/api/mesh/meshtastic/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              destination: meshDestination,
              message: msg,
              channel: meshChannel,
              priority: 'normal',
              ephemeral: false,
              transport_lock: 'meshtastic',
              sender_id: meshSenderAddress,
              mesh_region: meshRegion,
            }),
          });
        if (!sendRes.ok) {
          setInputValue(msg);
          setLastSendTime(0); // Don't burn cooldown on failure
          setSendError(sendRes.status === 429 ? 'rate limited' : 'send failed');
          setTimeout(() => setSendError(''), 4000);
          return;
        }
        const sendData = await sendRes.json();
        if (!sendData.ok) {
          setInputValue(msg);
          setLastSendTime(0);
          setSendError(sendData.detail || 'send failed');
          setTimeout(() => setSendError(''), 4000);
          return;
        }
        // Re-fetch — backend injects our msg into the bridge feed after publish
        const directTarget = meshDestination !== 'broadcast'
          ? meshDestination.startsWith('!')
            ? meshDestination.toUpperCase()
            : `!${meshDestination}`.toUpperCase()
          : '';
        const routeDetail = Array.isArray(sendData.results) && sendData.results[0]?.reason
          ? String(sendData.results[0].reason)
          : String(sendData.route_reason || 'MQTT broker accepted publish');
        setMeshQuickStatus({
          type: 'ok',
          text: directTarget
            ? `Direct message queued for ${directTarget}. ${routeDetail}`
            : `Channel message published to ${meshRegion}/${meshChannel}. ${routeDetail}`,
        });
        window.setTimeout(() => setMeshQuickStatus(null), 6000);
        await new Promise((r) => setTimeout(r, 500));
        const params = new URLSearchParams({
          limit: '30',
          region: meshRegion,
          channel: meshChannel,
        });
        if (directTarget) params.set('include_direct', '1');
        const mRes = await fetch(`${API_BASE}/api/mesh/messages?${params}`);
        if (mRes.ok) {
          const data = await mRes.json();
          setMeshMessages(Array.isArray(data) ? [...data].reverse() : []);
        }
        } else if (activeTab === 'dms' && selectedContact && dmView === 'chat') {
          if (anonymousDmBlocked) {
            setInputValue(msg);
            setLastSendTime(0);
            setSendError('hidden transport required for anonymous dm');
            setTimeout(() => setSendError(''), 4000);
            setBusy(false);
            return;
          }
          const contactInfo = contacts[selectedContact];
          if (contactInfo?.remotePrekeyMismatch) {
            setInputValue(msg);
            setLastSendTime(0);
            setShowSas(true);
            setSendError('remote prekey changed — verify before sending');
            setTimeout(() => setSendError(''), 5000);
            setBusy(false);
            return;
          }
          if (contactInfo?.verify_mismatch) {
            setInputValue(msg);
            setLastSendTime(0);
            setShowSas(true);
            setSendError('contact key mismatch — verify before sending');
            setTimeout(() => setSendError(''), 5000);
            setBusy(false);
            return;
          }
          if (contactInfo?.dhPubKey) {
            const localDhAlgo = getDHAlgo();
            if (contactInfo.dhAlgo && localDhAlgo && contactInfo.dhAlgo !== localDhAlgo) {
              setSendError('dm key mismatch');
              setTimeout(() => setSendError(''), 4000);
              return;
            }
            try {
              await ensureRegisteredDmKey(API_BASE, identity!, { force: false });
              const rotatedContact = await gateContactHandlers.maybeRotateSharedAlias(selectedContact, contactInfo);
              const promotion = promotePendingAlias(selectedContact, rotatedContact);
              if (promotion) updateContact(selectedContact, promotion.delta.updates);
              const effectiveContact = promotion?.promoted || rotatedContact;
              const sharedPeerId = preferredDmPeerId(selectedContact, effectiveContact);
              const ciphertext = await ratchetEncryptDM(selectedContact, effectiveContact.dhPubKey!, msg);
              const recipientToken = await sharedMailboxToken(sharedPeerId, effectiveContact.dhPubKey!);
              const msgId = `dm_${Date.now()}_${identity!.nodeId.slice(-4)}`;
              const timestamp = Math.floor(Date.now() / 1000);
              await enqueueDmSend(async () => {
                const sent = await sendDmMessage({
                  apiBase: API_BASE,
                  identity: identity!,
                  recipientId: sharedPeerId,
                  recipientDhPub: effectiveContact.dhPubKey,
                  ciphertext,
                  msgId,
                  timestamp,
                  deliveryClass: 'shared',
                  recipientToken,
                  useSealedSender: true,
                });
                if (!sent.ok) {
                  throw new Error(sent.detail || 'secure_dm_send_failed');
                }
                if (sent.transport === 'reticulum' || sent.transport === 'relay') {
                  setLastDmTransport(sent.transport);
                }
              });
            } catch (error) {
              setInputValue(msg);
              setLastSendTime(0);
              const detail = error instanceof Error ? error.message : '';
              if (detail.toLowerCase().includes('prekey') || detail.toLowerCase().includes('verify')) {
                setShowSas(true);
              }
              setSendError(detail || 'secure dm send failed');
              setTimeout(() => setSendError(''), 4000);
              setBusy(false);
              return;
            }
          }
        }
    } catch (err) {
      setInputValue(msg);
      setLastSendTime(0);
      const detail = err instanceof Error && err.message ? err.message : '';
      const nativeDetail = describeNativeControlError(err);
      if (activeTab === 'infonet') {
        refreshNativeAuditReport();
      }
      if (activeTab === 'infonet') {
        if (markGateResyncRequired(err, selectedGate)) {
          setGateError(
            nativeDetail || detail || 'Gate state changed on another path. Resync before retrying.',
          );
        }
        setSendError(
          nativeDetail || detail || 'encrypted gate send failed',
        );
      } else {
        setSendError(nativeDetail || detail || 'send failed');
      }
      setTimeout(() => setSendError(''), 4000);
    }
    setBusy(false);
  };

  const sendDecoy = useCallback(async () => {
    if (!hasId || !identity) return;
    if (anonymousDmBlocked) return;
    try {
      if (!(await canUseWormholeBootstrap())) return;
      await ensureRegisteredDmKey(API_BASE, identity, { force: false });
      const msgId = `dm_${Date.now()}_${identity.nodeId.slice(-4)}`;
      const timestamp = Math.floor(Date.now() / 1000);
      const padLen = 72 + Math.floor(Math.random() * 88);
      const ciphertext = randomBase64(padLen);
      const recipientId = `decoy_${randomHex(6)}`;
      const recipientToken = randomHex(24);
      const sent = await sendDmMessage({
        apiBase: API_BASE,
        identity,
        recipientId,
        ciphertext,
        msgId,
        timestamp,
        deliveryClass: 'shared',
        recipientToken,
        useSealedSender: false,
      });
      if (sent.transport === 'reticulum' || sent.transport === 'relay') {
        setLastDmTransport(sent.transport);
      }
    } catch {
      /* ignore */
    }
  }, [hasId, identity, anonymousDmBlocked]);

  // Decoy traffic (optional)
  useEffect(() => {
    if (!decoyEnabled || !hasId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      const delay = jitterDelay(DM_DECOY_POLL_MS, DM_DECOY_POLL_JITTER_MS);
      timer = setTimeout(async () => {
        await sendDecoy();
        if (!cancelled) schedule();
      }, delay);
    };
    schedule();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [decoyEnabled, hasId, sendDecoy]);

  const handleVote = async (targetId: string, vote: 1 | -1, gateIdOverride?: string) => {
    if (!hasId) return;
    if (anonymousPublicBlocked) return;
    if (!privateInfonetReady) return;
    const voteGate = String(gateIdOverride || selectedGate || '').trim().toLowerCase();
    const scopeKey = voteScopeKey(targetId, voteGate);
    // If already voted same direction, ignore
    if (votedOn[scopeKey] === vote) return;
    setVotedOn((prev: any) => ({ ...prev, [scopeKey]: vote }));
    try {
      const sequence = nextSequence();
      const votePayload = { target_id: targetId, vote, gate: voteGate };
      const v = validateEventPayload('vote', votePayload);
      if (!v.ok) return;
      const signed = await signMeshEvent('vote', votePayload, sequence, {
        gateId: voteGate || undefined,
      });
      await fetch(`${API_BASE}/api/mesh/vote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          voter_id: signed.context.nodeId,
          target_id: targetId,
          vote,
          gate: voteGate || undefined,
          voter_pubkey: signed.context.publicKey,
          public_key_algo: signed.context.publicKeyAlgo,
          voter_sig: signed.signature,
          sequence: signed.sequence,
          protocol_version: signed.protocolVersion,
        }),
      });
      const res = await fetch(
        `${API_BASE}/api/mesh/reputation?node_id=${encodeURIComponent(targetId)}`,
      );
      if (res.ok) {
        const data = await res.json();
        setReps((prev: any) => ({ ...prev, [targetId]: data.overall || 0 }));
      }
    } catch {
      /* ignore */
    }
  };

  const handleCreateGate = async () => {
    if (!hasId || !newGateId.trim()) return;
    if (!privateInfonetReady) {
      setGateError('wormhole required for private infonet');
      return;
    }
    if (anonymousPublicBlocked) {
      setGateError('hidden transport required for gate creation');
      return;
    }
    setGateError('');
    try {
      const gatePayload = {
        gate_id: newGateId.trim(),
        display_name: newGateName.trim() || newGateId.trim(),
        rules: { min_overall_rep: newGateMinRep },
      };
      const v = validateEventPayload('gate_create', gatePayload);
      if (!v.ok) {
        setGateError(`invalid payload: ${v.reason}`);
        return;
      }
      const sequence = nextSequence();
      const signed = await signMeshEvent('gate_create', gatePayload, sequence);
      const createRes = await fetch(`${API_BASE}/api/mesh/gate/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          creator_id: signed.context.nodeId,
          gate_id: gatePayload.gate_id,
          display_name: gatePayload.display_name,
          rules: gatePayload.rules,
          creator_pubkey: signed.context.publicKey,
          public_key_algo: signed.context.publicKeyAlgo,
          creator_sig: signed.signature,
          sequence: signed.sequence,
          protocol_version: signed.protocolVersion,
        }),
      });
      const createData = await createRes.json();
      if (!createData.ok) {
        setGateError(createData.detail || 'Failed to create gate');
        return;
      }
      invalidateGateCatalogSnapshot();
      const nextGates = (await fetchGateCatalogSnapshot({ force: true }).catch(() => [])).map(
        gateCatalogEntryToGate,
      );
      if (nextGates.length > 0) {
        setGates(nextGates);
      }
      setSelectedGate(newGateId.trim().toLowerCase());
      setShowCreateGate(false);
      setNewGateId('');
      setNewGateName('');
      setNewGateMinRep(0);
    } catch {
      setGateError('Network error — try again');
    }
  };

  const refreshSelectedGatePersonas = useCallback(async (gateId: string) => {
    const gateKey = gateId.trim().toLowerCase();
    if (!gateKey || !wormholeEnabled || !wormholeReadyState) return;
    const data = await listWormholeGatePersonas(gateKey);
    if (!data.ok) return;
    setGatePersonas((prev: any) => ({ ...prev, [gateKey]: Array.isArray(data.personas) ? data.personas : [] }));
    setActiveGatePersonaId((prev: any) => ({
      ...prev,
      [gateKey]: String(data.active_persona_id || ''),
    }));
  }, [wormholeEnabled, wormholeReadyState]);

  const refreshSelectedGateKeyStatus = useCallback(async (gateId: string) => {
    const gateKey = gateId.trim().toLowerCase();
    if (!gateKey || !wormholeEnabled || !wormholeReadyState) return;
    const data = await fetchWormholeGateKeyStatus(gateKey);
    setGateKeyStatus((prev: any) => ({ ...prev, [gateKey]: data }));
  }, [wormholeEnabled, wormholeReadyState]);

  return {
    ...gateContactHandlers,
    handleSend,
    sendDecoy,
    handleVote,
    handleCreateGate,
    refreshSelectedGatePersonas,
    refreshSelectedGateKeyStatus} as any;
}