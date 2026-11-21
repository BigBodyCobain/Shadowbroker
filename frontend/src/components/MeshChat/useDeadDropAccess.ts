'use client';

export function useDeadDropAccess(ctx: any) {
  const {
    expanded, activeTab, hasId, identity, contacts, accessRequests, pendingSent, dmConsentScopeId, selectedContact, dmView,
    setContacts, setDmMessages, setAccessRequestsState, setPendingSentState, setDmView, setSendError, setDmUnread, privacyProfile,
    wormholeEnabled, wormholeReadyState, anonymousDmBlocked, dmRequestTarget, setDmRequestTarget, dmRequestStatus, setDmRequestStatus,
    setSelectedContact, setShowSas, setSasPhrase, setSasConfirmInput, sendDecoy, isWormholeSecureRequired, getContacts, addContact, updateContact, blockContact, severContact, setAccessRequests, setPendingSent, getPendingSent, getAccessRequests
  } = ctx as any;


  const handleRequestAccess = async (targetId: string) => {
    if (!hasId) return;
    if (anonymousDmBlocked) {
      setSendError('hidden transport required for anonymous dm');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    try {
      const registration = await ensureRegisteredDmKey(API_BASE, identity!, { force: false });
      const myPub = registration.dhPubKey;
      if (!myPub) return;
      const dhAlgo = registration.dhAlgo || getDHAlgo() || 'X25519';
      const targetContact = getContacts()[targetId];
      let lookupHandle = String(targetContact?.invitePinnedPrekeyLookupHandle || '').trim();
      let resolvedTargetId = targetId;
      if (!lookupHandle && /^[a-fA-F0-9]{32,}$/.test(targetId)) {
        lookupHandle = targetId;
        resolvedTargetId = '';
      }
      if (!lookupHandle) {
        throw new Error(
          'Paste their short contact address (from Secure Messages → Copy Short Address), not their node id.',
        );
      }
      const targetKey = await fetchDmPublicKey(API_BASE, resolvedTargetId, lookupHandle, {
        lookupPeerUrl: targetContact?.invitePinnedLookupPeerUrl,
      });
      if (!targetKey?.dh_pub_key) {
        throw new Error(
          'invite-scoped lookup failed for this contact; re-import a signed invite and try again',
        );
      }
      let geoHint = '';
      if (geoHintEnabled && typeof navigator !== 'undefined' && navigator.geolocation) {
        try {
          const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
            navigator.geolocation.getCurrentPosition(resolve, reject, {
              maximumAge: 60_000,
              timeout: 2000,
            });
          });
          const lat = Number(pos.coords.latitude.toFixed(2));
          const lng = Number(pos.coords.longitude.toFixed(2));
          if (Number.isFinite(lat) && Number.isFinite(lng)) {
            geoHint = `${lat},${lng}`;
          }
        } catch {
          geoHint = '';
        }
      }
      const recipientId = String(targetKey.agent_id || resolvedTargetId || targetId).trim();
      const requestPlaintext = buildContactOfferMessage(myPub, dhAlgo, geoHint || undefined);
      let ciphertext = '';
      const secureRequired = await isWormholeSecureRequired();
      if (await canUseWormholeBootstrap()) {
        try {
          ciphertext = await bootstrapEncryptAccessRequest(recipientId, requestPlaintext);
        } catch {
          ciphertext = '';
        }
      }
      if (!ciphertext && !secureRequired) {
        const sharedKey = await deriveSharedKey(String(targetKey.dh_pub_key));
        ciphertext = await encryptDM(requestPlaintext, sharedKey);
      }
      if (!ciphertext) {
        throw new Error('secure bootstrap unavailable');
      }
      const msgId = `dm_${Date.now()}_${identity!.nodeId.slice(-4)}`;
      const msgTimestamp = Math.floor(Date.now() / 1000);
      await sleep(jitterDelay(ACCESS_REQUEST_BATCH_DELAY_MS, ACCESS_REQUEST_BATCH_JITTER_MS));
      const connectMeta = connectDeliveryMeta({
        intent: lookupHandle === targetId ? 'invite_short_address' : 'contact_request',
        contact: targetContact,
      });
      await enqueueDmSend(async () => {
        const sent = await ensureDmOutboxReleased(
          await sendOffLedgerConsentMessage({
            apiBase: API_BASE,
            identity: identity!,
            recipientId,
            recipientDhPub: String(targetKey.dh_pub_key),
            ciphertext,
            msgId,
            timestamp: msgTimestamp,
            connectIntent: connectMeta.connectIntent,
            lookupPeerUrl: connectMeta.lookupPeerUrl,
          }),
        );
        if (!sent.ok) {
          throw new Error(sent.detail || 'access_request_send_failed');
        }
        if (sent.transport === 'reticulum' || sent.transport === 'relay') {
          setLastDmTransport(sent.transport);
        }
      });
      const recipientForPending = String(targetKey.agent_id || resolvedTargetId || targetId).trim();
      const updated = [...pendingSent, recipientForPending];
      setPendingSent(updated, dmConsentScopeId);
      setPendingSentState(updated);
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'contact request failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 4000);
    }
  };

  const handleAcceptRequest = async (senderId: string) => {
    if (!hasId) return;
    if (anonymousDmBlocked) {
      setSendError('hidden transport required for anonymous dm');
      setTimeout(() => setSendError(''), 3000);
      return;
    }
    try {
      const req = accessRequests.find((r) => r.sender_id === senderId);
      const existingContact = getContacts()[senderId];
      const registry = await fetchDmPublicKey(
        API_BASE,
        senderId,
        existingContact?.invitePinnedPrekeyLookupHandle,
        { lookupPeerUrl: existingContact?.invitePinnedLookupPeerUrl },
      ).catch(() => null);
      const resolvedDhPubKey = String(registry?.dh_pub_key || req?.dh_pub_key || '').trim();
      const resolvedDhAlgo = String(registry?.dh_algo || req?.dh_algo || 'X25519').trim();
      if (!resolvedDhPubKey) {
        throw new Error('remote dm key unavailable for this request');
      }

      addContact(senderId, resolvedDhPubKey, undefined, resolvedDhAlgo);
      const inbandKey = req?.dh_pub_key;
      const registryKey = String(registry?.dh_pub_key || '');
      const inbandOk = Boolean(inbandKey);
      let registryOk = Boolean(registryKey);
      if (registryOk && registry?.signature && registry?.public_key && registry?.public_key_algo) {
        try {
          const keyPayload = {
            dh_pub_key: registry.dh_pub_key,
            dh_algo: registry.dh_algo,
            timestamp: registry.timestamp,
          };
          registryOk = await verifyEventSignature({
            eventType: 'dm_key',
            nodeId: senderId,
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
      const match = inbandOk && registryOk ? inbandKey === registryKey : false;
      updateContact(senderId, {
        verify_inband: inbandOk,
        verify_registry: registryOk,
        verified: match,
        verify_mismatch: inbandOk && registryOk && !match,
        verified_at: match ? Date.now() : undefined,
        dhAlgo: resolvedDhAlgo,
        remotePrekeyTransparencyHead:
          String(registry?.prekey_transparency_head || '') ||
          existingContact?.remotePrekeyTransparencyHead,
        remotePrekeyTransparencySize:
          Number(registry?.prekey_transparency_size || 0) ||
          existingContact?.remotePrekeyTransparencySize,
        remotePrekeyTransparencySeenAt: registry?.prekey_transparency_head
          ? Date.now()
          : existingContact?.remotePrekeyTransparencySeenAt,
        remotePrekeyLookupMode:
          String(registry?.lookup_mode || '').trim().toLowerCase() ||
          existingContact?.remotePrekeyLookupMode,
        witness_count: Number(registry?.witness_count || 0) || existingContact?.witness_count,
        witness_checked_at:
          Number(registry?.witness_latest_at || 0) || existingContact?.witness_checked_at,
      });
      if (registry?.dh_pub_key) {
        try {
          const witnessPayload = {
            target_id: senderId,
            dh_pub_key: registry.dh_pub_key,
            timestamp: Math.floor(Date.now() / 1000),
          };
          const wValid = validateEventPayload('dm_key_witness', witnessPayload);
          if (wValid.ok) {
            const wSeq = nextSequence();
            const signedWitness = await signMeshEvent('dm_key_witness', witnessPayload, wSeq);
            await fetch(`${API_BASE}/api/mesh/dm/witness`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                witness_id: signedWitness.context.nodeId,
                target_id: senderId,
                dh_pub_key: registry.dh_pub_key,
                timestamp: witnessPayload.timestamp,
                public_key: signedWitness.context.publicKey,
                public_key_algo: signedWitness.context.publicKeyAlgo,
                signature: signedWitness.signature,
                sequence: signedWitness.sequence,
                protocol_version: signedWitness.protocolVersion,
              }),
            });
          }
          const witnessRes = await fetch(
            `${API_BASE}/api/mesh/dm/witness?target_id=${encodeURIComponent(
              senderId,
            )}&dh_pub_key=${encodeURIComponent(registry.dh_pub_key)}`,
          );
          if (witnessRes.ok) {
            const witnessData = await witnessRes.json();
            updateContact(senderId, {
              witness_count: witnessData.count || 0,
              witness_checked_at: Date.now(),
            });
          }
          const vouchRes = await fetch(
            `${API_BASE}/api/mesh/trust/vouches?node_id=${encodeURIComponent(senderId)}`,
          );
          if (vouchRes.ok) {
            const vouchData = await vouchRes.json();
            updateContact(senderId, {
              vouch_count: vouchData.count || 0,
              vouch_checked_at: Date.now(),
            });
          }
        } catch {
          /* ignore */
        }
      }
      const updated = accessRequests.filter((r) => r.sender_id !== senderId);
      setAccessRequests(updated, dmConsentScopeId);
      setAccessRequestsState(updated);
      setContacts(getContacts());
      const registration = await ensureRegisteredDmKey(API_BASE, identity!, { force: false });
      if (registration.ok) {
        let sharedAlias = '';
        try {
          const pairwiseAlias = await issueWormholePairwiseAlias(senderId, resolvedDhPubKey);
          if (pairwiseAlias.ok) {
            sharedAlias = String(pairwiseAlias.shared_alias || '').trim();
          }
        } catch {
          sharedAlias = '';
        }
        if (!sharedAlias) {
          sharedAlias = generateSharedAlias();
        }
        const grantedPlaintext = buildContactAcceptMessage(sharedAlias);
        let ciphertext = '';
        const secureRequired = await isWormholeSecureRequired();
        if (await canUseWormholeBootstrap()) {
          try {
            ciphertext = await bootstrapEncryptAccessRequest(senderId, grantedPlaintext);
          } catch {
            ciphertext = '';
          }
        }
        if (!ciphertext && !secureRequired) {
          const sharedKey = await deriveSharedKey(resolvedDhPubKey);
          ciphertext = await encryptDM(grantedPlaintext, sharedKey);
        }
        if (!ciphertext) {
          throw new Error('access_granted_bootstrap_failed');
        }
        const msgId = `dm_${Date.now()}_${identity!.nodeId.slice(-4)}`;
        const msgTimestamp = Math.floor(Date.now() / 1000);
        const acceptMeta = connectDeliveryMeta({
          intent: 'contact_accept',
          contact: existingContact,
        });
        await enqueueDmSend(async () => {
          const sent = await ensureDmOutboxReleased(
            await sendOffLedgerConsentMessage({
              apiBase: API_BASE,
              identity: identity!,
              recipientId: senderId,
              recipientDhPub: resolvedDhPubKey,
              ciphertext,
              msgId,
              timestamp: msgTimestamp,
              connectIntent: acceptMeta.connectIntent,
              lookupPeerUrl: acceptMeta.lookupPeerUrl,
            }),
          );
          if (!sent.ok) {
            throw new Error(sent.detail || 'access_granted_send_failed');
          }
          if (sent.transport === 'reticulum' || sent.transport === 'relay') {
            setLastDmTransport(sent.transport);
          }
        });
        updateContact(senderId, {
          sharedAlias,
          previousSharedAliases: [],
          pendingSharedAlias: undefined,
          sharedAliasGraceUntil: undefined,
          sharedAliasRotatedAt: Date.now(),
        });
        setContacts(getContacts());
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'accept failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 4000);
    }
  };

  const handleDenyRequest = (senderId: string) => {
    void (async () => {
      try {
        const req = accessRequests.find((r) => r.sender_id === senderId);
        const existingContact = getContacts()[senderId];
        const targetKey =
          req?.dh_pub_key
            ? { dh_pub_key: req.dh_pub_key, dh_algo: req.dh_algo || 'X25519' }
            : await fetchDmPublicKey(
                API_BASE,
                senderId,
                existingContact?.invitePinnedPrekeyLookupHandle,
                { lookupPeerUrl: existingContact?.invitePinnedLookupPeerUrl },
              ).catch(() => null);
        if (identity && targetKey?.dh_pub_key) {
          const denyPlaintext = buildContactDenyMessage('declined');
          let ciphertext = '';
          const secureRequired = await isWormholeSecureRequired();
          if (await canUseWormholeBootstrap()) {
            try {
              ciphertext = await bootstrapEncryptAccessRequest(senderId, denyPlaintext);
            } catch {
              ciphertext = '';
            }
          }
          if (!ciphertext && !secureRequired) {
            const sharedKey = await deriveSharedKey(String(targetKey.dh_pub_key));
            ciphertext = await encryptDM(denyPlaintext, sharedKey);
          }
          if (ciphertext) {
            const msgId = `dm_${Date.now()}_${identity.nodeId.slice(-4)}`;
            const msgTimestamp = Math.floor(Date.now() / 1000);
            await enqueueDmSend(async () => {
              await sendOffLedgerConsentMessage({
                apiBase: API_BASE,
                identity,
                recipientId: senderId,
                recipientDhPub: String(targetKey.dh_pub_key || ''),
                ciphertext,
                msgId,
                timestamp: msgTimestamp,
              });
            });
          }
        }
      } catch {
        /* ignore */
      } finally {
        const updated = accessRequests.filter((r) => r.sender_id !== senderId);
        setAccessRequests(updated, dmConsentScopeId);
        setAccessRequestsState(updated);
      }
    })();
  };

  const handleSeverContact = async (agentId: string) => {
    try {
      await severContact(agentId);
      setContacts(getContacts());
      if (selectedContact === agentId) {
        setDmView('contacts');
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'end contact failed';
      setSendError(detail);
      setTimeout(() => setSendError(''), 4000);
    }
  };

  const handleBlockDM = async (agentId: string) => {
    blockContact(agentId);
    setContacts(getContacts());
    // Also remove from access requests
    const updated = accessRequests.filter((r) => r.sender_id !== agentId);
    setAccessRequests(updated, dmConsentScopeId);
    setAccessRequestsState(updated);
    if (selectedContact === agentId) {
      setSelectedContact('');
      setDmView('contacts');
    }
    try {
      if (!identity) return;
      const sequence = nextSequence();
      const blockPayload = { blocked_id: agentId, action: 'block' };
      const v = validateEventPayload('dm_block', blockPayload);
      if (!v.ok) return;
      const signed = await signMeshEvent('dm_block', blockPayload, sequence);
      await fetch(`${API_BASE}/api/mesh/dm/block`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: signed.context.nodeId,
          blocked_id: agentId,
          action: 'block',
          public_key: signed.context.publicKey,
          public_key_algo: signed.context.publicKeyAlgo,
          signature: signed.signature,
          sequence: signed.sequence,
          protocol_version: signed.protocolVersion,
        }),
      });
    } catch {
      /* ignore */
    }
  };

  const handleVouch = async (targetId: string) => {
    if (!identity) return;
    if (anonymousPublicBlocked) return;
    try {
      const timestamp = Math.floor(Date.now() / 1000);
      const payload = { target_id: targetId, note: '', timestamp };
      const v = validateEventPayload('trust_vouch', payload);
      if (!v.ok) return;
      const sequence = nextSequence();
      const signed = await signMeshEvent('trust_vouch', payload, sequence);
      const res = await fetch(`${API_BASE}/api/mesh/trust/vouch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          voucher_id: signed.context.nodeId,
          target_id: targetId,
          note: '',
          timestamp,
          public_key: signed.context.publicKey,
          public_key_algo: signed.context.publicKeyAlgo,
          signature: signed.signature,
          sequence: signed.sequence,
          protocol_version: signed.protocolVersion,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.ok) {
          const current = getContacts();
          const prev = current[targetId]?.vouch_count || 0;
          updateContact(targetId, { vouch_count: prev + 1, vouch_checked_at: Date.now() });
          setContacts(getContacts());
        }
      }
    } catch {
      /* ignore */
    }
  };

  const handleAddContact = async () => {
    const cid = addContactId.trim();
    if (!cid || !hasId) return;
    try {
        const data = await fetchDmPublicKey(API_BASE, cid, undefined, {
          allowLegacyAgentId: true,
        });
        if (data?.dh_pub_key) {
            addContact(cid, data.dh_pub_key, undefined, data.dh_algo);
            let registryOk = true;
            if (data.signature && data.public_key && data.public_key_algo) {
              try {
                const keyPayload = {
                  dh_pub_key: data.dh_pub_key,
                  dh_algo: data.dh_algo,
                  timestamp: data.timestamp,
                };
                registryOk = await verifyEventSignature({
                  eventType: 'dm_key',
                  nodeId: cid,
                  sequence: Number(data.sequence || 0),
                  payload: keyPayload,
                  signature: data.signature,
                  publicKey: data.public_key,
                  publicKeyAlgo: data.public_key_algo,
                });
              } catch {
                registryOk = false;
              }
            }
            updateContact(cid, {
              verify_registry: registryOk,
              verified: false,
              verify_mismatch: false,
              dhAlgo: data.dh_algo,
              remotePrekeyTransparencyHead: String(data.prekey_transparency_head || ''),
              remotePrekeyTransparencySize: Number(data.prekey_transparency_size || 0),
              remotePrekeyTransparencySeenAt: data.prekey_transparency_head ? Date.now() : 0,
              remotePrekeyLookupMode: String(data.lookup_mode || '').trim().toLowerCase(),
              witness_count: Number(data.witness_count || 0),
              witness_checked_at: Number(data.witness_latest_at || 0),
            });
            try {
              const witnessRes = await fetch(
                `${API_BASE}/api/mesh/dm/witness?target_id=${encodeURIComponent(
                  cid,
                )}&dh_pub_key=${encodeURIComponent(data.dh_pub_key)}`,
              );
              if (witnessRes.ok) {
                const witnessData = await witnessRes.json();
                updateContact(cid, {
                  witness_count: witnessData.count || 0,
                  witness_checked_at: Date.now(),
                });
              }
              const vouchRes = await fetch(
                `${API_BASE}/api/mesh/trust/vouches?node_id=${encodeURIComponent(cid)}`,
              );
              if (vouchRes.ok) {
                const vouchData = await vouchRes.json();
                updateContact(cid, {
                  vouch_count: vouchData.count || 0,
                  vouch_checked_at: Date.now(),
                });
              }
            } catch {
              /* ignore */
            }
          setContacts(getContacts());
          setSelectedContact(cid);
          setDmView('chat');
          setShowAddContact(false);
          setAddContactId('');
          if (String(data.lookup_mode || '').trim().toLowerCase() === 'legacy_agent_id') {
            setSendError(
              'contact added through legacy direct lookup; import or re-import a signed invite to replace stable-ID lookup',
            );
            setTimeout(() => setSendError(''), 4000);
          }
        }
    } catch {
      /* ignore */
    }
  };

  const openChat = (contactId: string) => {
    setSelectedContact(contactId);
    setDmView('chat');
    setDmMessages([]);
  };

  return {
    handleRequestAccess,
    handleAcceptRequest,
    handleDenyRequest,
    handleSeverContact,
    handleBlockDM,
    handleVouch,
    handleAddContact
  };
}
