'use client';

import { API_BASE } from '@/lib/api';

export function useMeshSendHandlers(ctx: any) {
  const c: any = ctx;
  // Bind controller scope vars from ctx - pragmatic extraction.
  for (const [k,v] of Object.entries(c)) {
    try { (globalThis as any)[k]; } catch {}
  }
  // Commonly used names
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
  } = c;


  ctx.const handleSend = ctx.async () => {
    ctx.const msg = ctx.inputValue.trim();
    ctx.if (!msg || ctx.busy) ctx.return;
    ctx.if (ctx.activeTab !== 'meshtastic' && !ctx.hasId) ctx.return;

    ctx.const cooldownMs = ctx.activeTab === 'dms' ? 0 : ctx.activeTab === 'meshtastic' ? 6_000 : 30_000;
    ctx.const now = Date.now();
    ctx.const elapsed = now - ctx.lastSendTime;
    ctx.if (cooldownMs > 0 && elapsed < cooldownMs) {
      ctx.const wait = Math.ceil((cooldownMs - elapsed) / 1000);
      ctx.setSendError(`ctx.cooldown: ${wait}ctx.s`);
      setTimeout(() => ctx.setSendError(''), 3000);
      ctx.return;
    }

    ctx.if (ctx.anonymousPublicBlocked && ctx.activeTab === 'infonet') {
      ctx.setSendError('hidden ctx.transport ctx.required ctx.for ctx.infonet ctx.posting');
      setTimeout(() => ctx.setSendError(''), 4000);
      ctx.return;
    }

    ctx.if (ctx.activeTab === 'infonet' && !ctx.privateInfonetReady) {
      ctx.setSendError('wormhole ctx.required ctx.for ctx.infonet');
      setTimeout(() => ctx.setSendError(''), 4000);
      ctx.return;
    }

    ctx.if (ctx.isGateSendBlocked(ctx.activeTab, Boolean(ctx.selectedGate), ctx.selectedGateAccessReady)) {
      ctx.setSendError('gate ctx.access ctx.still ctx.syncing');
      setTimeout(() => ctx.setSendError(''), 4000);
      ctx.return;
    }

    ctx.setInputValue('');
    ctx.setSendError('');
    ctx.setBusy(true);
    ctx.setLastSendTime(now);

    ctx.try {
        ctx.if (ctx.activeTab === 'infonet' && ctx.selectedGate) {
          ctx.const gateReplyPrefix =
            ctx.gateReplyContext && ctx.gateReplyContext.gateId === String(ctx.selectedGate).trim().toLowerCase()
              ? `>>${ctx.gateReplyContext.eventId.slice(0, 8)} @${ctx.gateReplyContext.nodeId.slice(0, 12)} `
              : '';
          ctx.const gateData = ctx.await ctx.postWormholeGateMessage(
            ctx.selectedGate,
            `${gateReplyPrefix}${msg}`,
            ctx.gateReplyContext?.gateId === String(ctx.selectedGate).trim().toLowerCase()
              ? ctx.gateReplyContext?.eventId || ''
              : '',
          ).catch((error) => ({
            ctx.ok: false,
            detail: error ctx.instanceof Error ? error.message : 'gate ctx.post ctx.failed',
          }));
          ctx.if (gateData?.ok === false) {
            ctx.setInputValue(msg);
            ctx.setLastSendTime(0);
            ctx.const detail = gateData?.detail || 'gate ctx.post ctx.failed';
            ctx.setSendError(
              detail === 'gate_backend_plaintext_compat_required'
                ? 'Service-ctx.side ctx.gate ctx.send ctx.is ctx.disabled ctx.on ctx.this ctx.runtime. ctx.Use ctx.native ctx.desktop ctx.or ctx.an ctx.explicit ctx.compatibility ctx.override.'
                : detail === 'gate_compat_fallback_consent_required' || detail.startsWith('gate_local_runtime_required:')
                  ? ctx.describeGateLocalRuntimeRequired(detail, ctx.selectedGate)
                  : detail,
            );
            ctx.if (ctx.markGateResyncRequired(detail, ctx.selectedGate)) {
              ctx.setGateError(
                ctx.describeNativeControlError(detail) ||
                  'Gate ctx.state ctx.changed ctx.on ctx.another ctx.path. ctx.Resync ctx.before ctx.retrying.',
              );
            }
            setTimeout(() => ctx.setSendError(''), 4000);
            ctx.return;
        }
        ctx.clearGateResyncRequired(ctx.selectedGate);
        ctx.setInfoMessages((prev) => [
          ...prev,
          {
            ctx.event_id: `ctx._pending_${Date.now()}`,
            ctx.event_type: 'gate_message',
            ctx.gate: String(ctx.selectedGate || '').trim().toLowerCase(),
            ctx.node_id: String(ctx.identity?.nodeId || ''),
            ctx.message: `${gateReplyPrefix}${msg}`,
            ctx.decrypted_message: `${gateReplyPrefix}${msg}`,
            timestamp: Math.floor(Date.now() / 1000),
            ctx.ephemeral: true,
          },
        ]);
        ctx.setGateReplyContext(null);
        } ctx.else ctx.if (ctx.activeTab === 'meshtastic') {
          ctx.const meshSenderAddress = ctx.activePublicMeshAddress;
          ctx.if (!meshSenderAddress) {
            ctx.setInputValue(msg);
            ctx.setLastSendTime(0);
            ctx.setSendError('public ctx.mesh ctx.identity ctx.needed');
            ctx.openIdentityWizard({
              ctx.type: 'err',
              ctx.text: ctx.hasStoredPublicLaneIdentity
                ? 'Quick ctx.fix: ctx.turn ctx.Meshtastic ctx.Chat ctx.on ctx.below, ctx.then ctx.retry ctx.your ctx.send.'
                : 'Quick ctx.fix: ctx.create ctx.a ctx.public ctx.mesh ctx.identity ctx.below, ctx.then ctx.retry ctx.your ctx.send.',
            });
            setTimeout(() => ctx.setSendError(''), 4000);
            ctx.setBusy(false);
            ctx.return;
          }
          ctx.if (!ctx.meshSessionActive) {
            ctx.setPublicMeshAddress(meshSenderAddress);
            ctx.setMeshSessionActive(true);
          }
          ctx.if (!ctx.meshMqttEnabled) {
            ctx.setInputValue(msg);
            ctx.setLastSendTime(0);
            ctx.setSendError('mqtt ctx.is ctx.off');
            ctx.setMeshQuickStatus({
              ctx.type: 'err',
              ctx.text: 'Public ctx.Mesh ctx.key ctx.is ctx.ready, ctx.but MQTT ctx.is ctx.off. ctx.Open ctx.Settings ctx.and ctx.enable ctx.the ctx.public ctx.broker.',
            });
            ctx.setMeshView('settings');
            setTimeout(() => ctx.setSendError(''), 4000);
            ctx.setBusy(false);
            ctx.return;
          }
          ctx.const meshDestination = ctx.meshDirectTarget.trim() || 'broadcast';
          ctx.const payload = {
            ctx.message: msg,
            ctx.destination: meshDestination,
            ctx.channel: ctx.meshChannel,
            ctx.priority: 'normal',
            ctx.ephemeral: false,
            ctx.transport_lock: 'meshtastic',
          };
          ctx.const v = ctx.validateEventPayload('message', payload);
          ctx.if (!v.ok) {
            ctx.setInputValue(msg);
            ctx.setLastSendTime(0);
            ctx.setSendError(`ctx.invalid payload: ${v.reason}`);
            setTimeout(() => ctx.setSendError(''), 4000);
            ctx.setBusy(false);
            ctx.return;
          }
          ctx.const sendRes = ctx.await fetch(`${API_BASE}/ctx.api/ctx.mesh/ctx.meshtastic/ctx.send`, {
            ctx.method: 'POST',
            ctx.headers: { 'Content-ctx.Type': 'application/ctx.json' },
            ctx.body: JSON.stringify({
              ctx.destination: meshDestination,
              ctx.message: msg,
              ctx.channel: ctx.meshChannel,
              ctx.priority: 'normal',
              ctx.ephemeral: false,
              ctx.transport_lock: 'meshtastic',
              ctx.sender_id: meshSenderAddress,
              ctx.mesh_region: ctx.meshRegion,
            }),
          });
        ctx.if (!sendRes.ok) {
          ctx.setInputValue(msg);
          ctx.setLastSendTime(0); // ctx.Don't ctx.burn ctx.cooldown ctx.on ctx.failure
          ctx.setSendError(sendRes.status === 429 ? 'rate ctx.limited' : 'send ctx.failed');
          setTimeout(() => ctx.setSendError(''), 4000);
          ctx.return;
        }
        ctx.const sendData = ctx.await sendRes.json();
        ctx.if (!sendData.ok) {
          ctx.setInputValue(msg);
          ctx.setLastSendTime(0);
          ctx.setSendError(sendData.detail || 'send ctx.failed');
          setTimeout(() => ctx.setSendError(''), 4000);
          ctx.return;
        }
        // ctx.Re-fetch — ctx.backend ctx.injects ctx.our msg ctx.into ctx.the ctx.bridge ctx.feed ctx.after ctx.publish
        ctx.const directTarget = meshDestination !== 'broadcast'
          ? meshDestination.startsWith('!')
            ? meshDestination.toUpperCase()
            : `!${meshDestination}`.toUpperCase()
          : '';
        ctx.const routeDetail = Array.isArray(sendData.results) && sendData.results[0]?.reason
          ? String(sendData.results[0].reason)
          : String(sendData.route_reason || 'MQTT ctx.broker ctx.accepted ctx.publish');
        ctx.setMeshQuickStatus({
          ctx.type: 'ok',
          ctx.text: directTarget
            ? `ctx.Direct ctx.message ctx.queued ctx.for ${directTarget}. ${routeDetail}`
            : `ctx.Channel ctx.message ctx.published ctx.to ${ctx.meshRegion}/${ctx.meshChannel}. ${routeDetail}`,
        });
        window.setTimeout(() => ctx.setMeshQuickStatus(null), 6000);
        ctx.await ctx.new Promise((r) => setTimeout(r, 500));
        ctx.const params = ctx.new URLSearchParams({
          ctx.limit: '30',
          ctx.region: ctx.meshRegion,
          ctx.channel: ctx.meshChannel,
        });
        ctx.if (directTarget) params.set('include_direct', '1');
        ctx.const mRes = ctx.await fetch(`${API_BASE}/ctx.api/ctx.mesh/ctx.messages?${params}`);
        ctx.if (mRes.ok) {
          ctx.const data = ctx.await mRes.json();
          ctx.setMeshMessages(Array.isArray(data) ? [...data].reverse() : []);
        }
        } ctx.else ctx.if (ctx.activeTab === 'dms' && ctx.selectedContact && ctx.dmView === 'chat') {
          ctx.if (ctx.anonymousDmBlocked) {
            ctx.setInputValue(msg);
            ctx.setLastSendTime(0);
            ctx.setSendError('hidden ctx.transport ctx.required ctx.for ctx.anonymous ctx.dm');
            setTimeout(() => ctx.setSendError(''), 4000);
            ctx.setBusy(false);
            ctx.return;
          }
          ctx.const contactInfo = ctx.contacts[ctx.selectedContact];
          ctx.if (contactInfo?.remotePrekeyMismatch) {
            ctx.setInputValue(msg);
            ctx.setLastSendTime(0);
            ctx.setShowSas(true);
            ctx.setSendError('remote ctx.prekey ctx.changed — ctx.verify ctx.before ctx.sending');
            setTimeout(() => ctx.setSendError(''), 5000);
            ctx.setBusy(false);
            ctx.return;
          }
          ctx.if (contactInfo?.verify_mismatch) {
            ctx.setInputValue(msg);
            ctx.setLastSendTime(0);
            ctx.setShowSas(true);
            ctx.setSendError('contact ctx.key ctx.mismatch — ctx.verify ctx.before ctx.sending');
            setTimeout(() => ctx.setSendError(''), 5000);
            ctx.setBusy(false);
            ctx.return;
          }
          ctx.if (contactInfo?.dhPubKey) {
            ctx.const localDhAlgo = ctx.getDHAlgo();
            ctx.if (contactInfo.dhAlgo && localDhAlgo && contactInfo.dhAlgo !== localDhAlgo) {
              ctx.setSendError('dm ctx.key ctx.mismatch');
              setTimeout(() => ctx.setSendError(''), 4000);
              ctx.return;
            }
            ctx.try {
              ctx.await ctx.ensureRegisteredDmKey(API_BASE, ctx.identity!, { ctx.force: false });
              ctx.const rotatedContact = ctx.await maybeRotateSharedAlias(ctx.selectedContact, contactInfo);
              ctx.const promotion = ctx.promotePendingAlias(ctx.selectedContact, rotatedContact);
              ctx.if (promotion) ctx.updateContact(ctx.selectedContact, promotion.delta.updates);
              ctx.const effectiveContact = promotion?.promoted || rotatedContact;
              ctx.const sharedPeerId = ctx.preferredDmPeerId(ctx.selectedContact, effectiveContact);
              ctx.const ciphertext = ctx.await ctx.ratchetEncryptDM(ctx.selectedContact, effectiveContact.dhPubKey!, msg);
              ctx.const recipientToken = ctx.await ctx.sharedMailboxToken(sharedPeerId, effectiveContact.dhPubKey!);
              ctx.const msgId = `ctx.dm_${Date.now()}ctx._${ctx.identity!.nodeId.slice(-4)}`;
              ctx.const timestamp = Math.floor(Date.now() / 1000);
              ctx.await ctx.enqueueDmSend(ctx.async () => {
                ctx.const sent = ctx.await ctx.sendDmMessage({
                  ctx.apiBase: API_BASE,
                  ctx.identity: ctx.identity!,
                  recipientId: sharedPeerId,
                  ctx.recipientDhPub: effectiveContact.dhPubKey,
                  ciphertext,
                  msgId,
                  timestamp,
                  ctx.deliveryClass: 'shared',
                  recipientToken,
                  ctx.useSealedSender: true,
                });
                ctx.if (!sent.ok) {
                  ctx.throw ctx.new Error(sent.detail || 'secure_dm_send_failed');
                }
                ctx.if (sent.transport === 'reticulum' || sent.transport === 'relay') {
                  ctx.setLastDmTransport(sent.transport);
                }
              });
            } ctx.catch (error) {
              ctx.setInputValue(msg);
              ctx.setLastSendTime(0);
              ctx.const detail = error ctx.instanceof Error ? error.message : '';
              ctx.if (detail.toLowerCase().includes('prekey') || detail.toLowerCase().includes('verify')) {
                ctx.setShowSas(true);
              }
              ctx.setSendError(detail || 'secure ctx.dm ctx.send ctx.failed');
              setTimeout(() => ctx.setSendError(''), 4000);
              ctx.setBusy(false);
              ctx.return;
            }
          }
        }
    } ctx.catch (err) {
      ctx.setInputValue(msg);
      ctx.setLastSendTime(0);
      ctx.const detail = err ctx.instanceof Error && err.message ? err.message : '';
      ctx.const nativeDetail = ctx.describeNativeControlError(err);
      ctx.if (ctx.activeTab === 'infonet') {
        ctx.refreshNativeAuditReport();
      }
      ctx.if (ctx.activeTab === 'infonet') {
        ctx.if (ctx.markGateResyncRequired(err, ctx.selectedGate)) {
          ctx.setGateError(
            nativeDetail || detail || 'Gate ctx.state ctx.changed ctx.on ctx.another ctx.path. ctx.Resync ctx.before ctx.retrying.',
          );
        }
        ctx.setSendError(
          nativeDetail || detail || 'encrypted ctx.gate ctx.send ctx.failed',
        );
      } ctx.else {
        ctx.setSendError(nativeDetail || detail || 'send ctx.failed');
      }
      setTimeout(() => ctx.setSendError(''), 4000);
    }
    ctx.setBusy(false);
  };

  ctx.const sendDecoy = ctx.useCallback(ctx.async () => {
    ctx.if (!ctx.hasId || !ctx.identity) ctx.return;
    ctx.if (ctx.anonymousDmBlocked) ctx.return;
    ctx.try {
      ctx.if (!(ctx.await ctx.canUseWormholeBootstrap())) ctx.return;
      ctx.await ctx.ensureRegisteredDmKey(API_BASE, ctx.identity, { ctx.force: false });
      ctx.const msgId = `ctx.dm_${Date.now()}ctx._${ctx.identity.nodeId.slice(-4)}`;
      ctx.const timestamp = Math.floor(Date.now() / 1000);
      ctx.const padLen = 72 + Math.floor(Math.random() * 88);
      ctx.const ciphertext = ctx.randomBase64(padLen);
      ctx.const recipientId = `ctx.decoy_${ctx.randomHex(6)}`;
      ctx.const recipientToken = ctx.randomHex(24);
      ctx.const sent = ctx.await ctx.sendDmMessage({
        ctx.apiBase: API_BASE,
        ctx.identity,
        recipientId,
        ciphertext,
        msgId,
        timestamp,
        ctx.deliveryClass: 'shared',
        recipientToken,
        ctx.useSealedSender: false,
      });
      ctx.if (sent.transport === 'reticulum' || sent.transport === 'relay') {
        ctx.setLastDmTransport(sent.transport);
      }
    } ctx.catch {
      /* ctx.ignore */
    }
  }, [ctx.hasId, ctx.identity, ctx.anonymousDmBlocked]);

  // ctx.Decoy ctx.traffic (ctx.optional)
  ctx.useEffect(() => {
    ctx.if (!ctx.decoyEnabled || !ctx.hasId) ctx.return;
    ctx.let cancelled = false;
    ctx.let timer: ctx.ReturnType<ctx.typeof setTimeout> | null = null;
    ctx.const schedule = () => {
      ctx.const delay = ctx.jitterDelay(DM_DECOY_POLL_MS, DM_DECOY_POLL_JITTER_MS);
      timer = setTimeout(ctx.async () => {
        ctx.await sendDecoy();
        ctx.if (!cancelled) schedule();
      }, delay);
    };
    schedule();
    ctx.return () => {
      cancelled = true;
      ctx.if (timer) clearTimeout(timer);
    };
  }, [ctx.decoyEnabled, ctx.hasId, sendDecoy]);

  ctx.const handleVote = ctx.async (targetId: string, vote: 1 | -1, gateIdOverride?: string) => {
    ctx.if (!ctx.hasId) ctx.return;
    ctx.if (ctx.anonymousPublicBlocked) ctx.return;
    ctx.if (!ctx.privateInfonetReady) ctx.return;
    ctx.const voteGate = String(gateIdOverride || ctx.selectedGate || '').trim().toLowerCase();
    ctx.const scopeKey = ctx.voteScopeKey(targetId, voteGate);
    // ctx.If ctx.already ctx.voted ctx.same ctx.direction, ctx.ignore
    ctx.if (ctx.votedOn[scopeKey] === vote) ctx.return;
    ctx.setVotedOn((prev) => ({ ...prev, [scopeKey]: vote }));
    ctx.try {
      ctx.const sequence = ctx.nextSequence();
      ctx.const votePayload = { ctx.target_id: targetId, vote, ctx.gate: voteGate };
      ctx.const v = ctx.validateEventPayload('vote', votePayload);
      ctx.if (!v.ok) ctx.return;
      ctx.const signed = ctx.await ctx.signMeshEvent('vote', votePayload, sequence, {
        gateId: voteGate || undefined,
      });
      ctx.await fetch(`${API_BASE}/ctx.api/ctx.mesh/vote`, {
        ctx.method: 'POST',
        ctx.headers: { 'Content-ctx.Type': 'application/ctx.json' },
        ctx.body: JSON.stringify({
          ctx.voter_id: signed.context.nodeId,
          ctx.target_id: targetId,
          vote,
          ctx.gate: voteGate || undefined,
          ctx.voter_pubkey: signed.context.publicKey,
          ctx.public_key_algo: signed.context.publicKeyAlgo,
          ctx.voter_sig: signed.signature,
          sequence: signed.sequence,
          ctx.protocol_version: signed.protocolVersion,
        }),
      });
      ctx.const res = ctx.await fetch(
        `${API_BASE}/ctx.api/ctx.mesh/ctx.reputation?ctx.node_id=${encodeURIComponent(targetId)}`,
      );
      ctx.if (res.ok) {
        ctx.const data = ctx.await res.json();
        ctx.setReps((prev) => ({ ...prev, [targetId]: data.overall || 0 }));
      }
    } ctx.catch {
      /* ctx.ignore */
    }
  };

  ctx.const handleCreateGate = ctx.async () => {
    ctx.if (!ctx.hasId || !ctx.newGateId.trim()) ctx.return;
    ctx.if (!ctx.privateInfonetReady) {
      ctx.setGateError('wormhole ctx.required ctx.for ctx.private ctx.infonet');
      ctx.return;
    }
    ctx.if (ctx.anonymousPublicBlocked) {
      ctx.setGateError('hidden ctx.transport ctx.required ctx.for ctx.gate ctx.creation');
      ctx.return;
    }
    ctx.setGateError('');
    ctx.try {
      ctx.const gatePayload = {
        ctx.gate_id: ctx.newGateId.trim(),
        ctx.display_name: ctx.newGateName.trim() || ctx.newGateId.trim(),
        ctx.rules: { ctx.min_overall_rep: ctx.newGateMinRep },
      };
      ctx.const v = ctx.validateEventPayload('gate_create', gatePayload);
      ctx.if (!v.ok) {
        ctx.setGateError(`ctx.invalid payload: ${v.reason}`);
        ctx.return;
      }
      ctx.const sequence = ctx.nextSequence();
      ctx.const signed = ctx.await ctx.signMeshEvent('gate_create', gatePayload, sequence);
      ctx.const createRes = ctx.await fetch(`${API_BASE}/ctx.api/ctx.mesh/ctx.gate/ctx.create`, {
        ctx.method: 'POST',
        ctx.headers: { 'Content-ctx.Type': 'application/ctx.json' },
        ctx.body: JSON.stringify({
          ctx.creator_id: signed.context.nodeId,
          ctx.gate_id: gatePayload.gate_id,
          ctx.display_name: gatePayload.display_name,
          ctx.rules: gatePayload.rules,
          ctx.creator_pubkey: signed.context.publicKey,
          ctx.public_key_algo: signed.context.publicKeyAlgo,
          ctx.creator_sig: signed.signature,
          sequence: signed.sequence,
          ctx.protocol_version: signed.protocolVersion,
        }),
      });
      ctx.const createData = ctx.await createRes.json();
      ctx.if (!createData.ok) {
        ctx.setGateError(createData.detail || 'Failed ctx.to ctx.create ctx.gate');
        ctx.return;
      }
      ctx.invalidateGateCatalogSnapshot();
      ctx.const nextGates = (ctx.await ctx.fetchGateCatalogSnapshot({ ctx.force: true }).catch(() => [])).map(
        ctx.gateCatalogEntryToGate,
      );
      ctx.if (nextGates.length > 0) {
        ctx.setGates(nextGates);
      }
      ctx.setSelectedGate(ctx.newGateId.trim().toLowerCase());
      ctx.setShowCreateGate(false);
      ctx.setNewGateId('');
      ctx.setNewGateName('');
      ctx.setNewGateMinRep(0);
    } ctx.catch {
      ctx.setGateError('Network error — ctx.try ctx.again');
    }
  };

  ctx.const refreshSelectedGatePersonas = ctx.useCallback(ctx.async (gateId: string) => {
    ctx.const gateKey = gateId.trim().toLowerCase();
    ctx.if (!gateKey || !ctx.wormholeEnabled || !ctx.wormholeReadyState) ctx.return;
    ctx.const data = ctx.await ctx.listWormholeGatePersonas(gateKey);
    ctx.if (!data.ok) ctx.return;
    ctx.setGatePersonas((prev) => ({ ...prev, [gateKey]: Array.isArray(data.personas) ? data.personas : [] }));
    ctx.setActiveGatePersonaId((prev) => ({
      ...prev,
      [gateKey]: String(data.active_persona_id || ''),
    }));
  }, [ctx.wormholeEnabled, ctx.wormholeReadyState]);

  ctx.const refreshSelectedGateKeyStatus = ctx.useCallback(ctx.async (gateId: string) => {
    ctx.const gateKey = gateId.trim().toLowerCase();
    ctx.if (!gateKey || !ctx.wormholeEnabled || !ctx.wormholeReadyState) ctx.return;
    ctx.const data = ctx.await ctx.fetchWormholeGateKeyStatus(gateKey);
    ctx.setGateKeyStatus((prev) => ({ ...prev, [gateKey]: data }));
  }, [ctx.wormholeEnabled, ctx.wormholeReadyState]);

  ctx.const handleResyncGateState = ctx.useCallback(
    ctx.async (gateIdOverride?: string): Promise<ctx.boolean> => {
      ctx.const gateId = String(gateIdOverride || ctx.selectedGate || '').trim().toLowerCase();
      ctx.if (!gateId || !ctx.wormholeEnabled || !ctx.wormholeReadyState || ctx.gateResyncBusy) ctx.return false;
      ctx.setGateResyncBusy(true);
      ctx.setGateError('');
      ctx.try {
        ctx.const resynced = ctx.await ctx.resyncWormholeGateState(gateId);
        ctx.if (!resynced.ok) {
          ctx.throw ctx.new Error(resynced.detail || 'gate_state_resync_failed');
        }
        ctx.clearGateResyncRequired(gateId);
        ctx.await refreshSelectedGateKeyStatus(gateId).catch(() => null);
        ctx.await refreshSelectedGatePersonas(gateId).catch(() => null);
        ctx.if (ctx.selectedGate === gateId) {
          ctx.await ctx.refreshInfonetMessages({ gateId, ctx.force: true });
        }
        ctx.setSendError('gate ctx.state resynced — ctx.retry ctx.the ctx.room action');
        window.setTimeout(() => ctx.setSendError(''), 4000);
        ctx.refreshNativeAuditReport();
        ctx.return true;
      } ctx.catch (err) {
        ctx.const detail =
          ctx.describeNativeControlError(err) ||
          (err ctx.instanceof Error && err.message) ||
          'Failed ctx.to ctx.resync ctx.gate ctx.state';
        ctx.setGateError(detail);
        ctx.markGateResyncRequired(err, gateId);
        ctx.return false;
      } ctx.finally {
        ctx.setGateResyncBusy(false);
      }
    },
    [
      ctx.clearGateResyncRequired,
      ctx.gateResyncBusy,
      ctx.markGateResyncRequired,
      ctx.refreshNativeAuditReport,
      ctx.refreshInfonetMessages,
      refreshSelectedGateKeyStatus,
      refreshSelectedGatePersonas,
      ctx.selectedGate,
      ctx.wormholeEnabled,
      ctx.wormholeReadyState,
    ],
  );

  ctx.const closeGatePersonaPrompt = ctx.useCallback(() => {
    ctx.setGatePersonaPromptOpen(false);
    ctx.setGatePersonaPromptGateId('');
    ctx.setGatePersonaDraftLabel('');
    ctx.setGatePersonaPromptError('');
  }, []);

  ctx.const openGatePersonaPrompt = ctx.useCallback(
    (gateIdOverride?: string) => {
      ctx.const gateId = String(gateIdOverride || ctx.selectedGate || '').trim().toLowerCase();
      ctx.if (!gateId) ctx.return;
      ctx.gatePersonaPromptSeenRef.current.add(gateId);
      ctx.setGatePersonaPromptGateId(gateId);
      ctx.setGatePersonaDraftLabel('');
      ctx.setGatePersonaPromptError('');
      ctx.setGatePersonaPromptOpen(true);
    },
    [ctx.selectedGate],
  );

  ctx.const handleCreateGatePersona = ctx.async (ctx.labelOverride?: string): Promise<ctx.boolean> => {
    ctx.const gateId = ctx.selectedGate.trim().toLowerCase();
    ctx.if (!gateId || !ctx.wormholeEnabled || !ctx.wormholeReadyState || ctx.gatePersonaBusy) ctx.return false;
    ctx.if (ctx.anonymousPublicBlocked) {
      ctx.setGateError('hidden ctx.transport ctx.required ctx.for ctx.anonymous ctx.gate ctx.personas');
      ctx.return false;
    }
    ctx.setGatePersonaBusy(true);
    ctx.setGateError('');
    ctx.setGatePersonaPromptError('');
    ctx.try {
      ctx.const existing = ctx.gatePersonas[gateId] || [];
      ctx.const nextLabel =
        String(ctx.labelOverride || '').trim() || `ctx.anon_${String(existing.length + 1).padStart(2, '0')}`;
      ctx.const created = ctx.await ctx.createWormholeGatePersona(gateId, nextLabel);
      ctx.if (!created.ok) {
        ctx.throw ctx.new Error(created.detail || 'persona_create_failed');
      }
      ctx.clearGateResyncRequired(gateId);
      ctx.await refreshSelectedGatePersonas(gateId);
      ctx.await refreshSelectedGateKeyStatus(gateId);
      ctx.return true;
    } ctx.catch (err) {
      ctx.const detail = ctx.describeNativeControlError(err) || 'Failed ctx.to ctx.create ctx.persona';
      ctx.setGateError(detail);
      ctx.setGatePersonaPromptError(detail);
      ctx.markGateResyncRequired(err, gateId);
      ctx.return false;
    } ctx.finally {
      ctx.refreshNativeAuditReport();
      ctx.setGatePersonaBusy(false);
    }
  };

  ctx.const handleSelectGatePersona = ctx.async (personaId: string): Promise<ctx.boolean> => {
    ctx.const gateId = ctx.selectedGate.trim().toLowerCase();
    ctx.if (!gateId || !ctx.wormholeEnabled || !ctx.wormholeReadyState || ctx.gatePersonaBusy) ctx.return false;
    ctx.if (ctx.anonymousPublicBlocked) {
      ctx.setGateError('hidden ctx.transport ctx.required ctx.for ctx.anonymous ctx.gate ctx.personas');
      ctx.return false;
    }
    ctx.setGatePersonaBusy(true);
    ctx.setGateError('');
    ctx.setGatePersonaPromptError('');
    ctx.try {
      ctx.const response =
        personaId === '__anon__'
          ? ctx.await ctx.clearWormholeGatePersona(gateId)
          : ctx.await ctx.activateWormholeGatePersona(gateId, personaId);
      ctx.if (!response.ok) {
        ctx.throw ctx.new Error(response.detail || 'persona_activate_failed');
      }
      ctx.clearGateResyncRequired(gateId);
      ctx.await refreshSelectedGatePersonas(gateId);
      ctx.await refreshSelectedGateKeyStatus(gateId);
      ctx.refreshNativeAuditReport();
      ctx.return true;
    } ctx.catch (err) {
      ctx.const detail = ctx.describeNativeControlError(err) || 'Failed ctx.to ctx.switch ctx.gate ctx.persona';
      ctx.setGateError(detail);
      ctx.setGatePersonaPromptError(detail);
      ctx.markGateResyncRequired(err, gateId);
      ctx.return false;
    } ctx.finally {
      ctx.refreshNativeAuditReport();
      ctx.setGatePersonaBusy(false);
    }
  };

  ctx.const handleRetireGatePersona = ctx.async () => {
    ctx.const gateId = ctx.selectedGate.trim().toLowerCase();
    ctx.const personaId = gateId ? ctx.activeGatePersonaId[gateId] || '' : '';
    ctx.if (!gateId || !personaId || !ctx.wormholeEnabled || !ctx.wormholeReadyState || ctx.gatePersonaBusy) ctx.return;
    ctx.if (ctx.anonymousPublicBlocked) {
      ctx.setGateError('hidden ctx.transport ctx.required ctx.for ctx.anonymous ctx.gate ctx.personas');
      ctx.return;
    }
    ctx.setGatePersonaBusy(true);
    ctx.setGateError('');
    ctx.try {
      ctx.const retired = ctx.await ctx.retireWormholeGatePersona(gateId, personaId);
      ctx.if (!retired.ok) {
        ctx.throw ctx.new Error(retired.detail || 'persona_retire_failed');
      }
      ctx.clearGateResyncRequired(gateId);
      ctx.await refreshSelectedGatePersonas(gateId);
      ctx.await refreshSelectedGateKeyStatus(gateId);
      ctx.refreshNativeAuditReport();
    } ctx.catch (err) {
      ctx.setGateError(ctx.describeNativeControlError(err) || 'Failed ctx.to ctx.retire ctx.persona');
      ctx.markGateResyncRequired(err, gateId);
    } ctx.finally {
      ctx.refreshNativeAuditReport();
      ctx.setGatePersonaBusy(false);
    }
  };

  ctx.const handleRotateGateKey = ctx.async () => {
    ctx.const gateId = ctx.selectedGate.trim().toLowerCase();
    ctx.if (!gateId || !ctx.wormholeEnabled || !ctx.wormholeReadyState || ctx.gateKeyBusy) ctx.return;
    ctx.setGateKeyBusy(true);
    ctx.setGateError('');
    ctx.try {
      ctx.const rotated = ctx.await ctx.rotateWormholeGateKey(gateId, 'operator_reset');
      ctx.if (!rotated.ok) {
        ctx.throw ctx.new Error(rotated.detail || 'gate_key_rotate_failed');
      }
      ctx.clearGateResyncRequired(gateId);
      ctx.setGateKeyStatus((prev) => ({ ...prev, [gateId]: rotated }));
      ctx.await refreshSelectedGatePersonas(gateId);
      ctx.refreshNativeAuditReport();
    } ctx.catch (err) {
      ctx.setGateError(ctx.describeNativeControlError(err) || 'Failed ctx.to ctx.rotate ctx.gate ctx.key');
      ctx.markGateResyncRequired(err, gateId);
    } ctx.finally {
      ctx.refreshNativeAuditReport();
      ctx.setGateKeyBusy(false);
    }
  };

  ctx.const handleUnlockEncryptedGate = ctx.useCallback(() => {
    openGatePersonaPrompt();
  }, [openGatePersonaPrompt]);

  ctx.const maybeRotateSharedAlias = ctx.async (
    ctx.contactId: string,
    ctx.contact: ctx.Contact,
    ctx.options?: { ctx.force?: ctx.boolean },
  ): Promise<ctx.Contact> => {
    ctx.const promotion = ctx.promotePendingAlias(ctx.contactId, ctx.contact);
    ctx.if (promotion) ctx.updateContact(ctx.contactId, promotion.delta.updates);
    ctx.const refreshed = promotion?.promoted || ctx.contact;
    ctx.const currentAlias = String(refreshed.sharedAlias || '').trim();
    ctx.if (!currentAlias || !refreshed.dhPubKey) {
      ctx.return refreshed;
    }
    ctx.if (String(refreshed.pendingSharedAlias || '').trim()) {
      ctx.return refreshed;
    }
    ctx.const lastRotatedAt = Number(refreshed.sharedAliasRotatedAt || 0);
    ctx.if (!ctx.options?.force && lastRotatedAt > 0 && Date.now() - lastRotatedAt < SHARED_ALIAS_ROTATE_MS) {
      ctx.return refreshed;
    }
    ctx.let nextAlias = '';
    ctx.try {
      ctx.const rotated = ctx.await ctx.rotateWormholePairwiseAlias(
        ctx.contactId,
        refreshed.dhPubKey,
        SHARED_ALIAS_GRACE_MS,
      );
      nextAlias = String(rotated.pending_alias || '').trim();
    } ctx.catch {
      nextAlias = '';
    }
    ctx.if (!nextAlias) {
      nextAlias = ctx.generateSharedAlias();
    }
    ctx.const controlPlaintext = ctx.buildAliasRotateMessage(nextAlias);
    ctx.const controlCiphertext = ctx.await ctx.ratchetEncryptDM(ctx.contactId, refreshed.dhPubKey, controlPlaintext);
    ctx.const recipientToken = ctx.await ctx.sharedMailboxToken(currentAlias, refreshed.dhPubKey);
    ctx.const msgId = `ctx.dm_${Date.now()}ctx._${ctx.identity!.nodeId.slice(-4)}`;
    ctx.const timestamp = Math.floor(Date.now() / 1000);
    ctx.await ctx.enqueueDmSend(ctx.async () => {
      ctx.const sent = ctx.await ctx.sendDmMessage({
        ctx.apiBase: API_BASE,
        ctx.identity: ctx.identity!,
        recipientId: currentAlias,
        ctx.recipientDhPub: refreshed.dhPubKey,
        ciphertext: controlCiphertext,
        msgId,
        timestamp,
        ctx.deliveryClass: 'shared',
        recipientToken,
        ctx.useSealedSender: true,
      });
      ctx.if (!sent.ok) {
        ctx.throw ctx.new Error(sent.detail || 'alias_rotate_send_failed');
      }
      ctx.if (sent.transport === 'reticulum' || sent.transport === 'relay') {
        ctx.setLastDmTransport(sent.transport);
      }
    });
    ctx.updateContact(ctx.contactId, {
      ctx.pendingSharedAlias: nextAlias,
      ctx.sharedAliasGraceUntil: Date.now() + SHARED_ALIAS_GRACE_MS,
      ctx.sharedAliasRotatedAt: Date.now(),
      ctx.previousSharedAliases: ctx.mergeAliasHistory([
        refreshed.sharedAlias,
        ...(refreshed.previousSharedAliases || []),
      ]),
    });
    ctx.setContacts(ctx.getContacts());
    ctx.return ctx.getContacts()[ctx.contactId] || refreshed;
  };

  ctx.const refreshDmContactState = ctx.async (
    ctx.contactId: string,
    ctx.options?: { ctx.rotateAlias?: ctx.boolean; ctx.resetRatchet?: ctx.boolean },
  ): Promise<ctx.void> => {
    ctx.const targetId = String(ctx.contactId || '').trim();
    ctx.if (!targetId || !ctx.identity) ctx.return;
    ctx.const existing = ctx.getContacts()[targetId];
    ctx.const lookupHandle = String(existing?.invitePinnedPrekeyLookupHandle || '').trim();
    ctx.if (!lookupHandle) {
      ctx.throw ctx.new Error(
        'import ctx.or ctx.re-ctx.import ctx.a signed ctx.invite ctx.before ctx.refreshing ctx.this ctx.contact; ctx.legacy ctx.direct ctx.lookup ctx.is ctx.disabled',
      );
    }
    ctx.const registry = ctx.await ctx.fetchDmPublicKey(API_BASE, targetId, lookupHandle, {
      ctx.lookupPeerUrl: existing?.invitePinnedLookupPeerUrl,
    }).catch(() => null);
    ctx.if (!registry?.dh_pub_key) {
      ctx.throw ctx.new Error(
        'invite-ctx.scoped ctx.lookup ctx.failed ctx.for ctx.this ctx.contact; ctx.re-ctx.import ctx.a signed ctx.invite ctx.and ctx.try ctx.again',
      );
    }
    ctx.if (registry?.dh_pub_key) {
      ctx.addContact(targetId, String(registry.dh_pub_key), undefined, registry.dh_algo);
      ctx.let registryOk = true;
      ctx.if (registry.signature && registry.public_key && registry.public_key_algo) {
        ctx.try {
          ctx.const keyPayload = {
            ctx.dh_pub_key: registry.dh_pub_key,
            ctx.dh_algo: registry.dh_algo,
            timestamp: registry.timestamp,
          };
          registryOk = ctx.await ctx.verifyEventSignature({
            ctx.eventType: 'dm_key',
            ctx.nodeId: targetId,
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
      ctx.const prior = ctx.getContacts()[targetId] || existing;
      ctx.const inbandOk = Boolean(prior?.verify_inband);
      ctx.const registryKey = String(registry.dh_pub_key || '');
      ctx.const inbandKey = String(prior?.dhPubKey || '');
      ctx.const verified = inbandOk && registryOk && inbandKey === registryKey;
      ctx.updateContact(targetId, {
        ctx.dhAlgo: registry.dh_algo || prior?.dhAlgo,
        ctx.verify_registry: registryOk,
        verified,
        ctx.verify_mismatch: inbandOk && registryOk && inbandKey !== registryKey,
        ctx.verified_at: verified ? Date.now() : prior?.verified_at,
        ctx.remotePrekeyTransparencyHead:
          String(registry.prekey_transparency_head || '') ||
          prior?.remotePrekeyTransparencyHead,
        ctx.remotePrekeyTransparencySize:
          Number(registry.prekey_transparency_size || 0) || prior?.remotePrekeyTransparencySize,
        ctx.remotePrekeyTransparencySeenAt: registry.prekey_transparency_head
          ? Date.now()
          : prior?.remotePrekeyTransparencySeenAt,
        ctx.remotePrekeyLookupMode:
          String(registry.lookup_mode || '').trim().toLowerCase() ||
          prior?.remotePrekeyLookupMode,
        ctx.witness_count:
          Number(registry.witness_count || 0) || prior?.witness_count,
        ctx.witness_checked_at:
          Number(registry.witness_latest_at || 0) || prior?.witness_checked_at,
      });
    }
    ctx.const latest = ctx.getContacts()[targetId] || existing;
    ctx.if (latest?.dhPubKey) {
      ctx.try {
        ctx.const witnessRes = ctx.await fetch(
          `${API_BASE}/ctx.api/ctx.mesh/ctx.dm/ctx.witness?ctx.target_id=${encodeURIComponent(
            targetId,
          )}&ctx.dh_pub_key=${encodeURIComponent(latest.dhPubKey)}`,
        );
        ctx.if (witnessRes.ok) {
          ctx.const witnessData = ctx.await witnessRes.json();
          ctx.updateContact(targetId, {
            ctx.witness_count: witnessData.count || 0,
            ctx.witness_checked_at: Date.now(),
          });
        }
      } ctx.catch {
        /* ctx.ignore */
      }
    }
    ctx.try {
      ctx.const vouchRes = ctx.await fetch(
        `${API_BASE}/ctx.api/ctx.mesh/ctx.trust/ctx.vouches?ctx.node_id=${encodeURIComponent(targetId)}`,
      );
      ctx.if (vouchRes.ok) {
        ctx.const vouchData = ctx.await vouchRes.json();
        ctx.updateContact(targetId, {
          ctx.vouch_count: vouchData.count || 0,
          ctx.vouch_checked_at: Date.now(),
        });
      }
    } ctx.catch {
      /* ctx.ignore */
    }
    ctx.if (ctx.options?.resetRatchet) {
      ctx.await ctx.ratchetReset(targetId);
    }
    ctx.const refreshed = ctx.getContacts()[targetId];
    ctx.if (ctx.options?.rotateAlias && refreshed?.dhPubKey) {
      ctx.await maybeRotateSharedAlias(targetId, refreshed, { ctx.force: true });
    }
    ctx.const hydratedContacts = ctx.await ctx.hydrateWormholeContacts(true).catch(() => ctx.getContacts());
    ctx.setContacts(hydratedContacts);
  };

  ctx.const handleRefreshSelectedContact = ctx.async (): Promise<ctx.void> => {
    ctx.if (!ctx.selectedContact || ctx.dmMaintenanceBusy) ctx.return;
    ctx.setDmMaintenanceBusy(true);
    ctx.try {
      ctx.await refreshDmContactState(ctx.selectedContact, { ctx.rotateAlias: true });
    } ctx.catch (err) {
      ctx.const detail = err ctx.instanceof Error ? err.message : 'dm ctx.refresh ctx.failed';
      ctx.setSendError(detail);
      setTimeout(() => ctx.setSendError(''), 3000);
    } ctx.finally {
      ctx.setDmMaintenanceBusy(false);
    }
  };

  ctx.const handleResetSelectedContact = ctx.async (): Promise<ctx.void> => {
    ctx.if (!ctx.selectedContact || ctx.dmMaintenanceBusy) ctx.return;
    ctx.setDmMaintenanceBusy(true);
    ctx.try {
      ctx.await refreshDmContactState(ctx.selectedContact, { ctx.rotateAlias: true, ctx.resetRatchet: true });
    } ctx.catch (err) {
      ctx.const detail = err ctx.instanceof Error ? err.message : 'dm ctx.reset ctx.failed';
      ctx.setSendError(detail);
      setTimeout(() => ctx.setSendError(''), 3000);
    } ctx.finally {
      ctx.setDmMaintenanceBusy(false);
    }
  };

  ctx.const handleTrustSelectedRemotePrekey = ctx.async (): Promise<ctx.void> => {
    ctx.if (!ctx.selectedContact || ctx.dmMaintenanceBusy) ctx.return;
    ctx.const contactInfo = ctx.getContacts()[ctx.selectedContact] || ctx.contacts[ctx.selectedContact];
    ctx.if (contactInfo?.remotePrekeyRootMismatch) {
      ctx.setSendError(
        'stable ctx.root ctx.changed; ctx.use RECOVER ROOT ctx.or ctx.replace ctx.the signed ctx.invite ctx.before ctx.trusting ctx.this ctx.contact ctx.again',
      );
      setTimeout(() => ctx.setSendError(''), 3000);
      ctx.return;
    }
    ctx.setDmMaintenanceBusy(true);
    ctx.try {
      ctx.const result = ctx.await ctx.acknowledgeWormholeSasFingerprint(ctx.selectedContact);
      ctx.if (!result?.ok) {
        ctx.throw ctx.new Error(String(result?.detail || 'failed ctx.to ctx.acknowledge ctx.changed ctx.fingerprint'));
      }
      ctx.const hydratedContacts = ctx.await ctx.hydrateWormholeContacts(true).catch(() => ctx.getContacts());
      ctx.setContacts(hydratedContacts);
      ctx.setShowSas(true);
      ctx.setSasConfirmInput('');
    } ctx.catch (err) {
      ctx.const detail = err ctx.instanceof Error ? err.message : 'failed ctx.to ctx.acknowledge ctx.changed ctx.fingerprint';
      ctx.setSendError(detail);
      setTimeout(() => ctx.setSendError(''), 3000);
    } ctx.finally {
      ctx.setDmMaintenanceBusy(false);
    }
  };

  ctx.const handleApproveGateCompatFallback = ctx.useCallback(ctx.async () => {
    ctx.if (!ctx.gateCompatConsentPrompt?.gateId) ctx.return;
    ctx.const approvedGateId = ctx.gateCompatConsentPrompt.gateId;
    ctx.const action = ctx.gateCompatConsentPrompt.action;
    ctx.approveGateCompatFallback(approvedGateId);
    ctx.setGateCompatActive((prev) => (prev[approvedGateId] ? prev : { ...prev, [approvedGateId]: true }));
    ctx.setGateCompatConsentPrompt(null);
    ctx.setGateError('');
    ctx.setSendError('');
    ctx.if (action === 'decrypt') {
      ctx.await ctx.refreshInfonetMessages({ gateId: approvedGateId, ctx.force: true });
      ctx.return;
    }
    ctx.await handleSend();
  }, [ctx.gateCompatConsentPrompt, handleSend, ctx.refreshInfonetMessages]);

  ctx.const handleConfirmSelectedContactSas = ctx.async (): Promise<ctx.void> => {
    ctx.if (!ctx.selectedContact || ctx.dmMaintenanceBusy) ctx.return;
    ctx.const contactInfo = ctx.getContacts()[ctx.selectedContact] || ctx.contacts[ctx.selectedContact];
    ctx.const proof = String(ctx.sasConfirmInput || '').trim();
    ctx.if (!proof) {
      ctx.setSendError('type ctx.the SAS ctx.phrase ctx.to ctx.confirm ctx.verification');
      setTimeout(() => ctx.setSendError(''), 3000);
      ctx.return;
    }
    ctx.setDmMaintenanceBusy(true);
    ctx.try {
      ctx.const result = ctx.await ctx.confirmWormholeSasVerification(
        ctx.selectedContact,
        proof,
        ctx.preferredDmPeerId(ctx.selectedContact, contactInfo),
        8,
      );
      ctx.if (!result?.ok) {
        ctx.throw ctx.new Error(String(result?.detail || 'sas ctx.verification ctx.failed'));
      }
      ctx.const hydratedContacts = ctx.await ctx.hydrateWormholeContacts(true).catch(() => ctx.getContacts());
      ctx.setContacts(hydratedContacts);
      ctx.setSasConfirmInput('');
      ctx.setShowSas(true);
    } ctx.catch (err) {
      ctx.const detail = err ctx.instanceof Error ? err.message : 'sas ctx.verification ctx.failed';
      ctx.setSendError(detail);
      setTimeout(() => ctx.setSendError(''), 3000);
    } ctx.finally {
      ctx.setDmMaintenanceBusy(false);
    }
  };

  ctx.const handleRecoverSelectedContactRootContinuity = ctx.async (): Promise<ctx.void> => {
    ctx.if (!ctx.selectedContact || ctx.dmMaintenanceBusy) ctx.return;
    ctx.const contactInfo = ctx.getContacts()[ctx.selectedContact] || ctx.contacts[ctx.selectedContact];
    ctx.const proof = String(ctx.sasConfirmInput || '').trim();
    ctx.if (!proof) {
      ctx.setSendError('type ctx.the SAS ctx.phrase ctx.to ctx.recover ctx.the ctx.changed ctx.stable ctx.root');
      setTimeout(() => ctx.setSendError(''), 3000);
      ctx.return;
    }
    ctx.setDmMaintenanceBusy(true);
    ctx.try {
      ctx.const result = ctx.await ctx.recoverWormholeSasRootContinuity(
        ctx.selectedContact,
        proof,
        ctx.preferredDmPeerId(ctx.selectedContact, contactInfo),
        8,
      );
      ctx.if (!result?.ok) {
        ctx.throw ctx.new Error(String(result?.detail || 'stable ctx.root ctx.recovery ctx.failed'));
      }
      ctx.const hydratedContacts = ctx.await ctx.hydrateWormholeContacts(true).catch(() => ctx.getContacts());
      ctx.setContacts(hydratedContacts);
      ctx.setSasConfirmInput('');
      ctx.setShowSas(true);
    } ctx.catch (err) {
      ctx.const detail = err ctx.instanceof Error ? err.message : 'stable ctx.root ctx.recovery ctx.failed';
      ctx.setSendError(detail);
      setTimeout(() => ctx.setSendError(''), 3000);
    } ctx.finally {
      ctx.setDmMaintenanceBusy(false);
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
