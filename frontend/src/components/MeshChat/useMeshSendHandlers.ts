'use client';

import { API_BASE } from '@/lib/api';

export function useMeshSendHandlers(ctx: Record<string, any>) {
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
    } = ctx as any;


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
        setInfoMessages((prev) => [
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
              const rotatedContact = await maybeRotateSharedAlias(selectedContact, contactInfo);
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
    setVotedOn((prev) => ({ ...prev, [scopeKey]: vote }));
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
        setReps((prev) => ({ ...prev, [targetId]: data.overall || 0 }));
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
    setGatePersonas((prev) => ({ ...prev, [gateKey]: Array.isArray(data.personas) ? data.personas : [] }));
    setActiveGatePersonaId((prev) => ({
      ...prev,
      [gateKey]: String(data.active_persona_id || ''),
    }));
  }, [wormholeEnabled, wormholeReadyState]);

  const refreshSelectedGateKeyStatus = useCallback(async (gateId: string) => {
    const gateKey = gateId.trim().toLowerCase();
    if (!gateKey || !wormholeEnabled || !wormholeReadyState) return;
    const data = await fetchWormholeGateKeyStatus(gateKey);
    setGateKeyStatus((prev) => ({ ...prev, [gateKey]: data }));
  }, [wormholeEnabled, wormholeReadyState]);

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
      setGateKeyStatus((prev) => ({ ...prev, [gateId]: rotated }));
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
    contact: Contact,
    options?: { force?: boolean },
  ): Promise<Contact> => {
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
    setGateCompatActive((prev) => (prev[approvedGateId] ? prev : { ...prev, [approvedGateId]: true }));
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
    handleSend,
    sendDecoy,
    handleVote,
    handleCreateGate,
    refreshSelectedGatePersonas,
    refreshSelectedGateKeyStatus,
    handleResyncGateState,
    closeGatePersonaPrompt,
    openGatePersonaPrompt,
    handleCreateGatePersona,
    handleSelectGatePersona,
    handleRetireGatePersona,
    handleRotateGateKey,
    handleUnlockEncryptedGate,
    maybeRotateSharedAlias,
    refreshDmContactState,
    handleRefreshSelectedContact,
    handleResetSelectedContact,
    handleTrustSelectedRemotePrekey,
    handleApproveGateCompatFallback,
    handleConfirmSelectedContactSas,
    handleRecoverSelectedContactRootContinuity
  };
}
