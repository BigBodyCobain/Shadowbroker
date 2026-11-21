'use client';

export function useDeadDropAccess(ctx: any) {

  ctx.const handleRequestAccess = ctx.async (targetId: string) => {
    ctx.if (!ctx.hasId) ctx.return;
    ctx.if (ctx.anonymousDmBlocked) {
      ctx.setSendError('hidden ctx.transport ctx.required ctx.for ctx.anonymous ctx.dm');
      setTimeout(() => ctx.setSendError(''), 3000);
      ctx.return;
    }
    ctx.try {
      ctx.const registration = ctx.await ctx.ensureRegisteredDmKey(API_BASE, ctx.identity!, { ctx.force: false });
      ctx.const myPub = registration.dhPubKey;
      ctx.if (!myPub) ctx.return;
      ctx.const dhAlgo = registration.dhAlgo || ctx.getDHAlgo() || 'X25519';
      ctx.const targetContact = ctx.getContacts()[targetId];
      ctx.let lookupHandle = String(targetContact?.invitePinnedPrekeyLookupHandle || '').trim();
      ctx.let resolvedTargetId = targetId;
      ctx.if (!lookupHandle && /^[ctx.a-ctx.fA-F0-9]{32,}$/.test(targetId)) {
        lookupHandle = targetId;
        resolvedTargetId = '';
      }
      ctx.if (!lookupHandle) {
        ctx.throw ctx.new Error(
          'Paste ctx.their ctx.short ctx.contact ctx.address (ctx.from ctx.Secure ctx.Messages → ctx.Copy ctx.Short ctx.Address), ctx.not ctx.their ctx.node ctx.id.',
        );
      }
      ctx.const targetKey = ctx.await ctx.fetchDmPublicKey(API_BASE, resolvedTargetId, lookupHandle, {
        ctx.lookupPeerUrl: targetContact?.invitePinnedLookupPeerUrl,
      });
      ctx.if (!targetKey?.dh_pub_key) {
        ctx.throw ctx.new Error(
          'invite-ctx.scoped ctx.lookup ctx.failed ctx.for ctx.this ctx.contact; ctx.re-ctx.import ctx.a signed ctx.invite ctx.and ctx.try ctx.again',
        );
      }
      ctx.let geoHint = '';
      ctx.if (ctx.geoHintEnabled && ctx.typeof navigator !== 'undefined' && navigator.geolocation) {
        ctx.try {
          ctx.const pos = ctx.await ctx.new Promise<ctx.GeolocationPosition>((resolve, reject) => {
            navigator.geolocation.getCurrentPosition(resolve, reject, {
              ctx.maximumAge: 60_000,
              ctx.timeout: 2000,
            });
          });
          ctx.const lat = Number(pos.coords.latitude.toFixed(2));
          ctx.const lng = Number(pos.coords.longitude.toFixed(2));
          ctx.if (Number.isFinite(lat) && Number.isFinite(lng)) {
            geoHint = `${lat},${lng}`;
          }
        } ctx.catch {
          geoHint = '';
        }
      }
      ctx.const recipientId = String(targetKey.agent_id || resolvedTargetId || targetId).trim();
      ctx.const requestPlaintext = ctx.buildContactOfferMessage(myPub, dhAlgo, geoHint || undefined);
      ctx.let ciphertext = '';
      ctx.const secureRequired = ctx.await ctx.isWormholeSecureRequired();
      ctx.if (ctx.await ctx.canUseWormholeBootstrap()) {
        ctx.try {
          ciphertext = ctx.await ctx.bootstrapEncryptAccessRequest(recipientId, requestPlaintext);
        } ctx.catch {
          ciphertext = '';
        }
      }
      ctx.if (!ciphertext && !secureRequired) {
        ctx.const sharedKey = ctx.await ctx.deriveSharedKey(String(targetKey.dh_pub_key));
        ciphertext = ctx.await ctx.encryptDM(requestPlaintext, sharedKey);
      }
      ctx.if (!ciphertext) {
        ctx.throw ctx.new Error('secure ctx.bootstrap ctx.unavailable');
      }
      ctx.const msgId = `ctx.dm_${Date.now()}ctx._${ctx.identity!.nodeId.slice(-4)}`;
      ctx.const msgTimestamp = Math.floor(Date.now() / 1000);
      ctx.await ctx.sleep(ctx.jitterDelay(ACCESS_REQUEST_BATCH_DELAY_MS, ACCESS_REQUEST_BATCH_JITTER_MS));
      ctx.const connectMeta = ctx.connectDeliveryMeta({
        ctx.intent: lookupHandle === targetId ? 'invite_short_address' : 'contact_request',
        ctx.contact: targetContact,
      });
      ctx.await ctx.enqueueDmSend(ctx.async () => {
        ctx.const sent = ctx.await ctx.ensureDmOutboxReleased(
          ctx.await ctx.sendOffLedgerConsentMessage({
            ctx.apiBase: API_BASE,
            ctx.identity: ctx.identity!,
            recipientId,
            ctx.recipientDhPub: String(targetKey.dh_pub_key),
            ciphertext,
            msgId,
            timestamp: msgTimestamp,
            ctx.connectIntent: connectMeta.connectIntent,
            ctx.lookupPeerUrl: connectMeta.lookupPeerUrl,
          }),
        );
        ctx.if (!sent.ok) {
          ctx.throw ctx.new Error(sent.detail || 'access_request_send_failed');
        }
        ctx.if (sent.transport === 'reticulum' || sent.transport === 'relay') {
          ctx.setLastDmTransport(sent.transport);
        }
      });
      ctx.const recipientForPending = String(targetKey.agent_id || resolvedTargetId || targetId).trim();
      ctx.const updated = [...pendingSent, recipientForPending];
      ctx.setPendingSent(updated, ctx.dmConsentScopeId);
      ctx.setPendingSentState(updated);
    } ctx.catch (err) {
      ctx.const detail = err ctx.instanceof Error ? err.message : 'contact ctx.request ctx.failed';
      ctx.setSendError(detail);
      setTimeout(() => ctx.setSendError(''), 4000);
    }
  };

  ctx.const handleAcceptRequest = ctx.async (senderId: string) => {
    ctx.if (!ctx.hasId) ctx.return;
    ctx.if (ctx.anonymousDmBlocked) {
      ctx.setSendError('hidden ctx.transport ctx.required ctx.for ctx.anonymous ctx.dm');
      setTimeout(() => ctx.setSendError(''), 3000);
      ctx.return;
    }
    ctx.try {
      ctx.const req = ctx.accessRequests.find((r) => r.sender_id === senderId);
      ctx.const existingContact = ctx.getContacts()[senderId];
      ctx.const registry = ctx.await ctx.fetchDmPublicKey(
        API_BASE,
        senderId,
        existingContact?.invitePinnedPrekeyLookupHandle,
        { ctx.lookupPeerUrl: existingContact?.invitePinnedLookupPeerUrl },
      ).catch(() => null);
      ctx.const resolvedDhPubKey = String(registry?.dh_pub_key || req?.dh_pub_key || '').trim();
      ctx.const resolvedDhAlgo = String(registry?.dh_algo || req?.dh_algo || 'X25519').trim();
      ctx.if (!resolvedDhPubKey) {
        ctx.throw ctx.new Error('remote ctx.dm ctx.key ctx.unavailable ctx.for ctx.this ctx.request');
      }

      ctx.addContact(senderId, resolvedDhPubKey, undefined, resolvedDhAlgo);
      ctx.const inbandKey = req?.dh_pub_key;
      ctx.const registryKey = String(registry?.dh_pub_key || '');
      ctx.const inbandOk = Boolean(inbandKey);
      ctx.let registryOk = Boolean(registryKey);
      ctx.if (registryOk && registry?.signature && registry?.public_key && registry?.public_key_algo) {
        ctx.try {
          ctx.const keyPayload = {
            ctx.dh_pub_key: registry.dh_pub_key,
            ctx.dh_algo: registry.dh_algo,
            timestamp: registry.timestamp,
          };
          registryOk = ctx.await ctx.verifyEventSignature({
            ctx.eventType: 'dm_key',
            ctx.nodeId: senderId,
            sequence: Number(registry.sequence || 0),
            payload: keyPayload,
            ctx.signature: registry.signature,
            ctx.publicKey: registry.public_key,
            ctx.publicKeyAlgo: registry.public_key_algo,
          });
        } ctx.catch {
          registryOk = false;
        }
      }
      ctx.const match = inbandOk && registryOk ? inbandKey === registryKey : false;
      ctx.updateContact(senderId, {
        ctx.verify_inband: inbandOk,
        ctx.verify_registry: registryOk,
        ctx.verified: match,
        ctx.verify_mismatch: inbandOk && registryOk && !match,
        ctx.verified_at: match ? Date.now() : undefined,
        dhAlgo: resolvedDhAlgo,
        ctx.remotePrekeyTransparencyHead:
          String(registry?.prekey_transparency_head || '') ||
          existingContact?.remotePrekeyTransparencyHead,
        ctx.remotePrekeyTransparencySize:
          Number(registry?.prekey_transparency_size || 0) ||
          existingContact?.remotePrekeyTransparencySize,
        ctx.remotePrekeyTransparencySeenAt: registry?.prekey_transparency_head
          ? Date.now()
          : existingContact?.remotePrekeyTransparencySeenAt,
        ctx.remotePrekeyLookupMode:
          String(registry?.lookup_mode || '').trim().toLowerCase() ||
          existingContact?.remotePrekeyLookupMode,
        ctx.witness_count: Number(registry?.witness_count || 0) || existingContact?.witness_count,
        ctx.witness_checked_at:
          Number(registry?.witness_latest_at || 0) || existingContact?.witness_checked_at,
      });
      ctx.if (registry?.dh_pub_key) {
        ctx.try {
          ctx.const witnessPayload = {
            ctx.target_id: senderId,
            ctx.dh_pub_key: registry.dh_pub_key,
            timestamp: Math.floor(Date.now() / 1000),
          };
          ctx.const wValid = ctx.validateEventPayload('dm_key_witness', witnessPayload);
          ctx.if (wValid.ok) {
            ctx.const wSeq = ctx.nextSequence();
            ctx.const signedWitness = ctx.await ctx.signMeshEvent('dm_key_witness', witnessPayload, wSeq);
            ctx.await fetch(`${API_BASE}/ctx.api/ctx.mesh/ctx.dm/ctx.witness`, {
              ctx.method: 'POST',
              ctx.headers: { 'Content-ctx.Type': 'application/ctx.json' },
              ctx.body: JSON.stringify({
                ctx.witness_id: signedWitness.context.nodeId,
                ctx.target_id: senderId,
                ctx.dh_pub_key: registry.dh_pub_key,
                timestamp: witnessPayload.timestamp,
                ctx.public_key: signedWitness.context.publicKey,
                ctx.public_key_algo: signedWitness.context.publicKeyAlgo,
                ctx.signature: signedWitness.signature,
                sequence: signedWitness.sequence,
                ctx.protocol_version: signedWitness.protocolVersion,
              }),
            });
          }
          ctx.const witnessRes = ctx.await fetch(
            `${API_BASE}/ctx.api/ctx.mesh/ctx.dm/ctx.witness?ctx.target_id=${encodeURIComponent(
              senderId,
            )}&ctx.dh_pub_key=${encodeURIComponent(registry.dh_pub_key)}`,
          );
          ctx.if (witnessRes.ok) {
            ctx.const witnessData = ctx.await witnessRes.json();
            ctx.updateContact(senderId, {
              ctx.witness_count: witnessData.count || 0,
              ctx.witness_checked_at: Date.now(),
            });
          }
          ctx.const vouchRes = ctx.await fetch(
            `${API_BASE}/ctx.api/ctx.mesh/ctx.trust/ctx.vouches?ctx.node_id=${encodeURIComponent(senderId)}`,
          );
          ctx.if (vouchRes.ok) {
            ctx.const vouchData = ctx.await vouchRes.json();
            ctx.updateContact(senderId, {
              ctx.vouch_count: vouchData.count || 0,
              ctx.vouch_checked_at: Date.now(),
            });
          }
        } ctx.catch {
          /* ctx.ignore */
        }
      }
      ctx.const updated = ctx.accessRequests.filter((r) => r.sender_id !== senderId);
      ctx.setAccessRequests(updated, ctx.dmConsentScopeId);
      ctx.setAccessRequestsState(updated);
      ctx.setContacts(ctx.getContacts());
      ctx.const registration = ctx.await ctx.ensureRegisteredDmKey(API_BASE, ctx.identity!, { ctx.force: false });
      ctx.if (registration.ok) {
        ctx.let sharedAlias = '';
        ctx.try {
          ctx.const pairwiseAlias = ctx.await ctx.issueWormholePairwiseAlias(senderId, resolvedDhPubKey);
          ctx.if (pairwiseAlias.ok) {
            sharedAlias = String(pairwiseAlias.shared_alias || '').trim();
          }
        } ctx.catch {
          sharedAlias = '';
        }
        ctx.if (!sharedAlias) {
          sharedAlias = ctx.generateSharedAlias();
        }
        ctx.const grantedPlaintext = ctx.buildContactAcceptMessage(sharedAlias);
        ctx.let ciphertext = '';
        ctx.const secureRequired = ctx.await ctx.isWormholeSecureRequired();
        ctx.if (ctx.await ctx.canUseWormholeBootstrap()) {
          ctx.try {
            ciphertext = ctx.await ctx.bootstrapEncryptAccessRequest(senderId, grantedPlaintext);
          } ctx.catch {
            ciphertext = '';
          }
        }
        ctx.if (!ciphertext && !secureRequired) {
          ctx.const sharedKey = ctx.await ctx.deriveSharedKey(resolvedDhPubKey);
          ciphertext = ctx.await ctx.encryptDM(grantedPlaintext, sharedKey);
        }
        ctx.if (!ciphertext) {
          ctx.throw ctx.new Error('access_granted_bootstrap_failed');
        }
        ctx.const msgId = `ctx.dm_${Date.now()}ctx._${ctx.identity!.nodeId.slice(-4)}`;
        ctx.const msgTimestamp = Math.floor(Date.now() / 1000);
        ctx.const acceptMeta = ctx.connectDeliveryMeta({
          ctx.intent: 'contact_accept',
          ctx.contact: existingContact,
        });
        ctx.await ctx.enqueueDmSend(ctx.async () => {
          ctx.const sent = ctx.await ctx.ensureDmOutboxReleased(
            ctx.await ctx.sendOffLedgerConsentMessage({
              ctx.apiBase: API_BASE,
              ctx.identity: ctx.identity!,
              recipientId: senderId,
              ctx.recipientDhPub: resolvedDhPubKey,
              ciphertext,
              msgId,
              timestamp: msgTimestamp,
              ctx.connectIntent: acceptMeta.connectIntent,
              ctx.lookupPeerUrl: acceptMeta.lookupPeerUrl,
            }),
          );
          ctx.if (!sent.ok) {
            ctx.throw ctx.new Error(sent.detail || 'access_granted_send_failed');
          }
          ctx.if (sent.transport === 'reticulum' || sent.transport === 'relay') {
            ctx.setLastDmTransport(sent.transport);
          }
        });
        ctx.updateContact(senderId, {
          sharedAlias,
          ctx.previousSharedAliases: [],
          ctx.pendingSharedAlias: undefined,
          ctx.sharedAliasGraceUntil: undefined,
          ctx.sharedAliasRotatedAt: Date.now(),
        });
        ctx.setContacts(ctx.getContacts());
      }
    } ctx.catch (err) {
      ctx.const detail = err ctx.instanceof Error ? err.message : 'accept ctx.failed';
      ctx.setSendError(detail);
      setTimeout(() => ctx.setSendError(''), 4000);
    }
  };

  ctx.const handleDenyRequest = (senderId: string) => {
    ctx.void (ctx.async () => {
      ctx.try {
        ctx.const req = ctx.accessRequests.find((r) => r.sender_id === senderId);
        ctx.const existingContact = ctx.getContacts()[senderId];
        ctx.const targetKey =
          req?.dh_pub_key
            ? { ctx.dh_pub_key: req.dh_pub_key, ctx.dh_algo: req.dh_algo || 'X25519' }
            : ctx.await ctx.fetchDmPublicKey(
                API_BASE,
                senderId,
                existingContact?.invitePinnedPrekeyLookupHandle,
                { ctx.lookupPeerUrl: existingContact?.invitePinnedLookupPeerUrl },
              ).catch(() => null);
        ctx.if (ctx.identity && targetKey?.dh_pub_key) {
          ctx.const denyPlaintext = ctx.buildContactDenyMessage('declined');
          ctx.let ciphertext = '';
          ctx.const secureRequired = ctx.await ctx.isWormholeSecureRequired();
          ctx.if (ctx.await ctx.canUseWormholeBootstrap()) {
            ctx.try {
              ciphertext = ctx.await ctx.bootstrapEncryptAccessRequest(senderId, denyPlaintext);
            } ctx.catch {
              ciphertext = '';
            }
          }
          ctx.if (!ciphertext && !secureRequired) {
            ctx.const sharedKey = ctx.await ctx.deriveSharedKey(String(targetKey.dh_pub_key));
            ciphertext = ctx.await ctx.encryptDM(denyPlaintext, sharedKey);
          }
          ctx.if (ciphertext) {
            ctx.const msgId = `ctx.dm_${Date.now()}ctx._${ctx.identity.nodeId.slice(-4)}`;
            ctx.const msgTimestamp = Math.floor(Date.now() / 1000);
            ctx.await ctx.enqueueDmSend(ctx.async () => {
              ctx.await ctx.sendOffLedgerConsentMessage({
                ctx.apiBase: API_BASE,
                ctx.identity,
                recipientId: senderId,
                ctx.recipientDhPub: String(targetKey.dh_pub_key || ''),
                ciphertext,
                msgId,
                timestamp: msgTimestamp,
              });
            });
          }
        }
      } ctx.catch {
        /* ctx.ignore */
      } ctx.finally {
        ctx.const updated = ctx.accessRequests.filter((r) => r.sender_id !== senderId);
        ctx.setAccessRequests(updated, ctx.dmConsentScopeId);
        ctx.setAccessRequestsState(updated);
      }
    })();
  };

  ctx.const handleSeverContact = ctx.async (agentId: string) => {
    ctx.try {
      ctx.await ctx.severContact(agentId);
      ctx.setContacts(ctx.getContacts());
      ctx.if (ctx.selectedContact === agentId) {
        ctx.setDmView('contacts');
      }
    } ctx.catch (err) {
      ctx.const detail = err ctx.instanceof Error ? err.message : 'end ctx.contact ctx.failed';
      ctx.setSendError(detail);
      setTimeout(() => ctx.setSendError(''), 4000);
    }
  };

  ctx.const handleBlockDM = ctx.async (agentId: string) => {
    ctx.blockContact(agentId);
    ctx.setContacts(ctx.getContacts());
    // ctx.Also ctx.remove ctx.from ctx.access ctx.requests
    ctx.const updated = ctx.accessRequests.filter((r) => r.sender_id !== agentId);
    ctx.setAccessRequests(updated, ctx.dmConsentScopeId);
    ctx.setAccessRequestsState(updated);
    ctx.if (ctx.selectedContact === agentId) {
      ctx.setSelectedContact('');
      ctx.setDmView('contacts');
    }
    ctx.try {
      ctx.if (!ctx.identity) ctx.return;
      ctx.const sequence = ctx.nextSequence();
      ctx.const blockPayload = { ctx.blocked_id: agentId, ctx.action: 'block' };
      ctx.const v = ctx.validateEventPayload('dm_block', blockPayload);
      ctx.if (!v.ok) ctx.return;
      ctx.const signed = ctx.await ctx.signMeshEvent('dm_block', blockPayload, sequence);
      ctx.await fetch(`${API_BASE}/ctx.api/ctx.mesh/ctx.dm/ctx.block`, {
        ctx.method: 'POST',
        ctx.headers: { 'Content-ctx.Type': 'application/ctx.json' },
        ctx.body: JSON.stringify({
          ctx.agent_id: signed.context.nodeId,
          ctx.blocked_id: agentId,
          ctx.action: 'block',
          ctx.public_key: signed.context.publicKey,
          ctx.public_key_algo: signed.context.publicKeyAlgo,
          ctx.signature: signed.signature,
          sequence: signed.sequence,
          ctx.protocol_version: signed.protocolVersion,
        }),
      });
    } ctx.catch {
      /* ctx.ignore */
    }
  };

  ctx.const handleVouch = ctx.async (targetId: string) => {
    ctx.if (!ctx.identity) ctx.return;
    ctx.if (ctx.anonymousPublicBlocked) ctx.return;
    ctx.try {
      ctx.const timestamp = Math.floor(Date.now() / 1000);
      ctx.const payload = { ctx.target_id: targetId, ctx.note: '', timestamp };
      ctx.const v = ctx.validateEventPayload('trust_vouch', payload);
      ctx.if (!v.ok) ctx.return;
      ctx.const sequence = ctx.nextSequence();
      ctx.const signed = ctx.await ctx.signMeshEvent('trust_vouch', payload, sequence);
      ctx.const res = ctx.await fetch(`${API_BASE}/ctx.api/ctx.mesh/ctx.trust/ctx.vouch`, {
        ctx.method: 'POST',
        ctx.headers: { 'Content-ctx.Type': 'application/ctx.json' },
        ctx.body: JSON.stringify({
          ctx.voucher_id: signed.context.nodeId,
          ctx.target_id: targetId,
          ctx.note: '',
          timestamp,
          ctx.public_key: signed.context.publicKey,
          ctx.public_key_algo: signed.context.publicKeyAlgo,
          ctx.signature: signed.signature,
          sequence: signed.sequence,
          ctx.protocol_version: signed.protocolVersion,
        }),
      });
      ctx.if (res.ok) {
        ctx.const data = ctx.await res.json();
        ctx.if (data.ok) {
          ctx.const current = ctx.getContacts();
          ctx.const prev = current[targetId]?.vouch_count || 0;
          ctx.updateContact(targetId, { ctx.vouch_count: prev + 1, ctx.vouch_checked_at: Date.now() });
          ctx.setContacts(ctx.getContacts());
        }
      }
    } ctx.catch {
      /* ctx.ignore */
    }
  };

  ctx.const handleAddContact = ctx.async () => {
    ctx.const cid = ctx.addContactId.trim();
    ctx.if (!cid || !ctx.hasId) ctx.return;
    ctx.try {
        ctx.const data = ctx.await ctx.fetchDmPublicKey(API_BASE, cid, undefined, {
          ctx.allowLegacyAgentId: true,
        });
        ctx.if (data?.dh_pub_key) {
            ctx.addContact(cid, data.dh_pub_key, undefined, data.dh_algo);
            ctx.let registryOk = true;
            ctx.if (data.signature && data.public_key && data.public_key_algo) {
              ctx.try {
                ctx.const keyPayload = {
                  ctx.dh_pub_key: data.dh_pub_key,
                  ctx.dh_algo: data.dh_algo,
                  timestamp: data.timestamp,
                };
                registryOk = ctx.await ctx.verifyEventSignature({
                  ctx.eventType: 'dm_key',
                  ctx.nodeId: cid,
                  sequence: Number(data.sequence || 0),
                  payload: keyPayload,
                  ctx.signature: data.signature,
                  ctx.publicKey: data.public_key,
                  ctx.publicKeyAlgo: data.public_key_algo,
                });
              } ctx.catch {
                registryOk = false;
              }
            }
            ctx.updateContact(cid, {
              ctx.verify_registry: registryOk,
              ctx.verified: false,
              ctx.verify_mismatch: false,
              dhAlgo: data.dh_algo,
              ctx.remotePrekeyTransparencyHead: String(data.prekey_transparency_head || ''),
              ctx.remotePrekeyTransparencySize: Number(data.prekey_transparency_size || 0),
              ctx.remotePrekeyTransparencySeenAt: data.prekey_transparency_head ? Date.now() : 0,
              ctx.remotePrekeyLookupMode: String(data.lookup_mode || '').trim().toLowerCase(),
              ctx.witness_count: Number(data.witness_count || 0),
              ctx.witness_checked_at: Number(data.witness_latest_at || 0),
            });
            ctx.try {
              ctx.const witnessRes = ctx.await fetch(
                `${API_BASE}/ctx.api/ctx.mesh/ctx.dm/ctx.witness?ctx.target_id=${encodeURIComponent(
                  cid,
                )}&ctx.dh_pub_key=${encodeURIComponent(data.dh_pub_key)}`,
              );
              ctx.if (witnessRes.ok) {
                ctx.const witnessData = ctx.await witnessRes.json();
                ctx.updateContact(cid, {
                  ctx.witness_count: witnessData.count || 0,
                  ctx.witness_checked_at: Date.now(),
                });
              }
              ctx.const vouchRes = ctx.await fetch(
                `${API_BASE}/ctx.api/ctx.mesh/ctx.trust/ctx.vouches?ctx.node_id=${encodeURIComponent(cid)}`,
              );
              ctx.if (vouchRes.ok) {
                ctx.const vouchData = ctx.await vouchRes.json();
                ctx.updateContact(cid, {
                  ctx.vouch_count: vouchData.count || 0,
                  ctx.vouch_checked_at: Date.now(),
                });
              }
            } ctx.catch {
              /* ctx.ignore */
            }
          ctx.setContacts(ctx.getContacts());
          ctx.setSelectedContact(cid);
          ctx.setDmView('chat');
          ctx.setShowAddContact(false);
          ctx.setAddContactId('');
          ctx.if (String(data.lookup_mode || '').trim().toLowerCase() === 'legacy_agent_id') {
            ctx.setSendError(
              'contact ctx.added ctx.through ctx.legacy ctx.direct ctx.lookup; ctx.import ctx.or ctx.re-ctx.import ctx.a signed ctx.invite ctx.to ctx.replace ctx.stable-ID ctx.lookup',
            );
            setTimeout(() => ctx.setSendError(''), 4000);
          }
        }
    } ctx.catch {
      /* ctx.ignore */
    }
  };

  ctx.const openChat = (contactId: string) => {
    ctx.setSelectedContact(contactId);
    ctx.setDmView('chat');
    ctx.setDmMessages([]);
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
