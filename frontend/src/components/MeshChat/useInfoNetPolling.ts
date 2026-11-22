// @ts-nocheck
'use client';

import { useEffect } from 'react';
import { API_BASE } from '@/lib/api';
import { isGateSendBlocked } from '@/lib/meshChatPolicies';
import {
  fetchGateCatalogSnapshot,
  invalidateGateCatalogSnapshot,
} from '@/mesh/gateCatalogSnapshot';
import {
  ACTIVE_GATE_ROOM_MESSAGE_LIMIT,
  fetchGateMessageSnapshotState,
  waitForGateMessageSnapshot,
} from '@/mesh/gateMessageSnapshot';
import {
  fetchWormholeGateKeyStatus,
  hasGateCompatFallbackApproval,
  isWormholeSecureRequired,
  listWormholeGatePersonas,
  postWormholeGateMessage,
  prepareWormholeInteractiveLane,
  resyncWormholeGateState,
  syncBrowserWormholeGateState,
} from '@/mesh/wormholeIdentityClient';
import { nextGateMessagesPollDelayMs, nextGateMessagesWaitRearmDelayMs, nextGateMessagesWaitTimeoutMs } from '@/mesh/gateMetadataTiming';
import { gateCatalogEntryToGate } from './useMeshChatController.helpers';
import type { Gate, InfoNetMessage, WormholeGateKeyStatus } from './types';

export function useInfoNetPolling(ctx: Record<string, any>) {
  const {
    expanded, wormholeEnabled, wormholeReadyState, selectedGate, anonymousDmBlocked, privacyProfile,
    setGates, setSelectedGate, setInfoMessages, setGatePersonas, setActiveGatePersonaId,
    setGateKeyStatus, setGateError, setGateCompatActive, setGateCompatConsentPrompt,
    setGatePersonaDraftLabel, setGatePersonaPromptError, setGatePersonaPromptGateId, setGatePersonaPromptOpen,
    setGateReplyContext, setInfoVerification,
    activeGateSessionRef, infoPollSignatureRef, infoMessageIdsRef, infoGateHeadRef, infoGateKeyEpochRef,
    gateCompatApprovalAttemptRef, infoPullInFlightRef, gateCompatConsentPromptGateRef,
    identity, contacts, hasId, wormholeState, activeTab,
  } = ctx;


  useEffect(() => {
    if (!expanded) return;
    const fetchGates = async () => {
      try {
        const nextGates = (await fetchGateCatalogSnapshot()).map(gateCatalogEntryToGate);
        setGates(nextGates);
        if (nextGates.length > 0) {
          setSelectedGate((prev) => prev || String(nextGates[0].gate_id || '').trim().toLowerCase());
        }
      } catch {
        /* ignore */
      }
    };
    void fetchGates();
  }, [expanded]);

  useEffect(() => {
    if (!wormholeEnabled || !wormholeReadyState) return;
    let cancelled = false;
    const nextGate = selectedGate.trim().toLowerCase();

    const ensureGateAccess = async () => {
      try {
        if (activeGateSessionRef.current !== nextGate) {
          activeGateSessionRef.current = '';
          infoPollSignatureRef.current = '';
          if (!cancelled) {
            setInfoMessages([]);
          }
        }
        if (!nextGate) return;
        if (activeGateSessionRef.current === nextGate) return;

        const personasData = await listWormholeGatePersonas(nextGate).catch(() => null);
        if (cancelled) return;
        const personas =
          personasData?.ok && Array.isArray(personasData.personas) ? personasData.personas : [];
        const activePersonaId =
          personasData?.ok ? String(personasData.active_persona_id || '').trim() : '';
        if (personasData?.ok) {
          setGatePersonas((prev) => ({ ...prev, [nextGate]: personas }));
          setActiveGatePersonaId((prev) => ({
            ...prev,
            [nextGate]: activePersonaId,
          }));
        }

        let status = await fetchWormholeGateKeyStatus(nextGate, { mode: 'active_room' }).catch(() => null);
        if (cancelled) return;
        if (status) {
          const nextStatus = status as WormholeGateKeyStatus;
          setGateKeyStatus((prev) => ({ ...prev, [nextGate]: nextStatus }));
        }
        if (status?.ok && status.has_local_access) {
          await syncBrowserWormholeGateState(nextGate).catch(() => false);
          activeGateSessionRef.current = nextGate;
          setGateError('');
          return;
        }
        if (!activePersonaId) {
          const entered = await enterWormholeGate(nextGate, false).catch(() => null);
          if (cancelled || !entered?.ok) {
            if (!cancelled) {
              setGateError(String(entered?.detail || 'Failed to enter anonymous gate session'));
            }
            return;
          }
          status = await fetchWormholeGateKeyStatus(nextGate, { mode: 'active_room' }).catch(() => null);
          if (cancelled) return;
          if (status) {
            const nextStatus = status as WormholeGateKeyStatus;
            setGateKeyStatus((prev) => ({ ...prev, [nextGate]: nextStatus }));
          }
          if (!cancelled && status?.ok && status.has_local_access) {
            await syncBrowserWormholeGateState(nextGate).catch(() => false);
            setGateError('');
            activeGateSessionRef.current = nextGate;
            return;
          }
        } else {
          const ensured = await activateWormholeGatePersona(nextGate, activePersonaId).catch(() => null);
          if (cancelled || !ensured?.ok) {
            if (!cancelled) {
              setGateError(String(ensured?.detail || 'Failed to activate gate face'));
            }
            return;
          }
          status = await fetchWormholeGateKeyStatus(nextGate, { mode: 'active_room' }).catch(() => null);
          if (cancelled) return;
          if (status) {
            const nextStatus = status as WormholeGateKeyStatus;
            setGateKeyStatus((prev) => ({ ...prev, [nextGate]: nextStatus }));
          }
          if (!cancelled && status?.ok && status.has_local_access) {
            await syncBrowserWormholeGateState(nextGate).catch(() => false);
            setGateError('');
            activeGateSessionRef.current = nextGate;
            return;
          }
        }

        if (!cancelled) {
          setGateError(String(status?.detail || 'Failed to prepare private gate access'));
        }
      } catch {
        if (!cancelled) {
          setGateError('Failed to prepare private gate access');
        }
      }
    };

    void ensureGateAccess();
    return () => {
      cancelled = true;
    };
  }, [selectedGate, wormholeEnabled, wormholeReadyState]);

  useEffect(() => {
    return () => {
      activeGateSessionRef.current = '';
    };
  }, []);

  useEffect(() => {
    if (!wormholeEnabled || !wormholeReadyState || !selectedGate) return;
    let cancelled = false;
    const gateId = selectedGate.trim().toLowerCase();
    const loadGatePersonas = async () => {
      try {
        const data = await listWormholeGatePersonas(gateId).catch(() => null);
        if (!data?.ok || cancelled) return;
        setGatePersonas((prev) => ({ ...prev, [gateId]: Array.isArray(data.personas) ? data.personas : [] }));
        setActiveGatePersonaId((prev) => ({
          ...prev,
          [gateId]: String(data.active_persona_id || ''),
        }));
      } catch {
        /* ignore */
      }
    };
    loadGatePersonas();
    return () => {
      cancelled = true;
    };
  }, [selectedGate, wormholeEnabled, wormholeReadyState]);

  useEffect(() => {
    if (!gateReplyContext) return;
    if (!selectedGate || gateReplyContext.gateId !== String(selectedGate || '').trim().toLowerCase()) {
      setGateReplyContext(null);
    }
  }, [gateReplyContext, selectedGate]);

  const streamEnabledForSelectedGate =
    Boolean(selectedGate) &&
    gateSessionStreamStatus.phase === 'open' &&
    gateSessionStreamStatus.subscriptions.includes(String(selectedGate || '').trim().toLowerCase());
  const streamPreferredForSelectedGate =
    Boolean(selectedGate) &&
    (gateSessionStreamStatus.phase === 'connecting' || gateSessionStreamStatus.phase === 'open') &&
    gateSessionStreamStatus.subscriptions.includes(String(selectedGate || '').trim().toLowerCase());

  useEffect(() => {
    if (!wormholeEnabled || !wormholeReadyState || !selectedGate) return;
    let cancelled = false;
    const gateId = selectedGate.trim().toLowerCase();
    const loadGateKeyStatus = async () => {
      try {
        const data = await fetchWormholeGateKeyStatus(gateId, {
          mode: streamPreferredForSelectedGate ? 'session_stream' : 'active_room',
        }).catch(() => null);
        if (!data || cancelled) return;
        if (data.ok && data.has_local_access && !streamPreferredForSelectedGate) {
          void syncBrowserWormholeGateState(gateId).catch(() => false);
        }
        setGateKeyStatus((prev) => ({ ...prev, [gateId]: data }));
      } catch {
        /* ignore */
      }
    };
    void loadGateKeyStatus();
    return () => {
      cancelled = true;
    };
  }, [selectedGate, wormholeEnabled, wormholeReadyState, gatePersonaBusy, streamPreferredForSelectedGate]);

  useEffect(() => {
    if (
      !expanded ||
      activeTab !== 'infonet' ||
      !wormholeEnabled ||
      !wormholeReadyState ||
      !selectedGate
    ) {
      return;
    }
    const gateId = selectedGate.trim().toLowerCase();
    const gateStatus = gateId ? gateKeyStatus[gateId] || null : null;
    if (!gateId || !gateStatus?.has_local_access || gatePersonaBusy || gatePersonaPromptOpen) {
      return;
    }
    return retainGateSessionStreamGate(gateId);
  }, [
    expanded,
    activeTab,
    selectedGate,
    gateKeyStatus,
    gatePersonaBusy,
    gatePersonaPromptOpen,
    wormholeEnabled,
    wormholeReadyState,
  ]);

  useEffect(() => {
    streamEnabledForSelectedGateRef.current = streamPreferredForSelectedGate;
  }, [streamPreferredForSelectedGate]);

  useEffect(() => {
    if (
      !expanded ||
      activeTab !== 'infonet' ||
      !wormholeEnabled ||
      !wormholeReadyState ||
      !streamEnabledForSelectedGate
    ) {
      return;
    }
    return subscribeGateSessionStreamEvents((event) => {
      if (event.event !== 'gate_update' || !event.data || typeof event.data !== 'object') {
        return;
      }
      const activeGateId = String(selectedGateRef.current || '').trim().toLowerCase();
      if (!activeGateId) {
        return;
      }
      const updates = Array.isArray((event.data as { updates?: unknown }).updates)
        ? ((event.data as { updates?: Array<{ gate_id?: string; cursor?: number }> }).updates || [])
        : [];
      const matching = updates.find(
        (update) => String(update?.gate_id || '').trim().toLowerCase() === activeGateId,
      );
      if (!matching) {
        return;
      }
      void refreshInfonetMessages({
        gateId: activeGateId,
        force: true,
        proofMode: 'session_stream',
      });
    });
  }, [
    activeTab,
    expanded,
    refreshInfonetMessages,
    streamEnabledForSelectedGate,
    wormholeEnabled,
    wormholeReadyState,
  ]);

  useEffect(() => {
    setGateCompatConsentPrompt(null);
    const gateId = String(selectedGate || '').trim().toLowerCase();
    if (!gateId) return;
    setGateCompatActive((prev) => {
      if (hasGateCompatFallbackApproval(gateId)) {
        return prev[gateId] ? prev : { ...prev, [gateId]: true };
      }
      if (!prev[gateId]) return prev;
      const next = { ...prev };
      delete next[gateId];
      return next;
    });
  }, [selectedGate]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleCompatFallback = (event: Event) => {
      const detail =
        event instanceof CustomEvent && event.detail && typeof event.detail === 'object'
          ? (event.detail as { gateId?: string })
          : null;
      const eventGateId = String(detail?.gateId || '').trim().toLowerCase();
      if (!eventGateId) return;
      setGateCompatActive((prev) => (prev[eventGateId] ? prev : { ...prev, [eventGateId]: true }));
    };
    window.addEventListener('sb:gate-compat-fallback', handleCompatFallback as EventListener);
    return () => {
      window.removeEventListener('sb:gate-compat-fallback', handleCompatFallback as EventListener);
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleCompatConsentRequired = (event: Event) => {
      const detail =
        event instanceof CustomEvent && event.detail && typeof event.detail === 'object'
          ? (event.detail as GateCompatConsentPromptState)
          : null;
      const eventGateId = String(detail?.gateId || '').trim().toLowerCase();
      if (!eventGateId || eventGateId !== selectedGateRef.current || !detail) {
        return;
      }
      setGateCompatConsentPrompt({
        gateId: eventGateId,
        action: detail.action,
        reason: String(detail.reason || ''),
      });
      setGateError('Local gate crypto is unavailable for this room.');
    };
    window.addEventListener(
      'sb:gate-compat-consent-required',
      handleCompatConsentRequired as EventListener,
    );
    return () => {
      window.removeEventListener(
        'sb:gate-compat-consent-required',
        handleCompatConsentRequired as EventListener,
      );
    };
  }, []);

  useEffect(() => {
    if (
      activeTab !== 'infonet' ||
      !wormholeEnabled ||
      !wormholeReadyState ||
      !selectedGate ||
      gatePersonaBusy ||
      gatePersonaPromptOpen
    ) {
      return;
    }
    const gateId = selectedGate.trim().toLowerCase();
    if (!gateId || gatePersonaPromptSeenRef.current.has(gateId)) return;
    const status = gateKeyStatus[gateId];
    const knownPersonas = gatePersonas[gateId] || [];
    if (!status || status.identity_scope !== 'anonymous' || status.has_local_access) return;
    if (knownPersonas.length === 0) return;
    gatePersonaPromptSeenRef.current.add(gateId);
    setGatePersonaPromptGateId(gateId);
    setGatePersonaDraftLabel('');
    setGatePersonaPromptError('');
    setGatePersonaPromptOpen(true);
  }, [
    activeTab,
    gateKeyStatus,
    gatePersonas,
    gatePersonaBusy,
    gatePersonaPromptOpen,
    selectedGate,
    wormholeEnabled,
    wormholeReadyState,
  ]);

  useEffect(() => {
    if (!gatePersonaPromptOpen) return;
    const gateId = selectedGate.trim().toLowerCase();
    if (!gateId || (gatePersonaPromptGateId && gatePersonaPromptGateId !== gateId)) {
      setGatePersonaPromptOpen(false);
      setGatePersonaPromptGateId('');
      setGatePersonaDraftLabel('');
      setGatePersonaPromptError('');
    }
  }, [gatePersonaPromptGateId, gatePersonaPromptOpen, selectedGate]);

  useEffect(() => {
    if (!gateSessionStreamHydrated) return;
    const isLiveStreamPreferredForSelectedGate = () => {
      const liveStreamStatus = getGateSessionStreamStatus();
      return (
        Boolean(selectedGate) &&
        (liveStreamStatus.phase === 'connecting' || liveStreamStatus.phase === 'open') &&
        liveStreamStatus.subscriptions.includes(String(selectedGate || '').trim().toLowerCase())
      );
    };
    const liveStreamPreferredForSelectedGateNow =
      streamPreferredForSelectedGate || isLiveStreamPreferredForSelectedGate();
    streamEnabledForSelectedGateRef.current = liveStreamPreferredForSelectedGateNow;
    if (!expanded || activeTab !== 'infonet') return;
    const gateId = selectedGate.trim().toLowerCase();
    const gateStatus = gateId ? gateKeyStatus[gateId] || null : null;
    const gateAccessReady = !gateId || Boolean(gateStatus?.has_local_access);
    if (gateId && (!gateAccessReady || gatePersonaBusy || gatePersonaPromptOpen)) {
      return;
    }
    let cancelled = false;
    const clearRetry = () => {
      if (infoPollTimerRef.current) {
        clearTimeout(infoPollTimerRef.current);
        infoPollTimerRef.current = null;
      }
    };

    const scheduleRetry = () => {
      if (cancelled || streamEnabledForSelectedGateRef.current) return;
      clearRetry();
      infoPollTimerRef.current = setTimeout(() => {
        infoPollTimerRef.current = null;
        void runNext();
      }, nextGateMessagesPollDelayMs());
    };

    const startWaitIfNeeded = () => {
      queueMicrotask(() => {
        streamEnabledForSelectedGateRef.current =
          streamPreferredForSelectedGate || isLiveStreamPreferredForSelectedGate();
        if (!cancelled && !streamEnabledForSelectedGateRef.current) {
          void runNext();
        }
      });
    };

    const runNext = async () => {
      streamEnabledForSelectedGateRef.current =
        streamPreferredForSelectedGate || isLiveStreamPreferredForSelectedGate();
      if (cancelled || streamEnabledForSelectedGateRef.current) return;
      if (!gateId) {
        const ok = await refreshInfonetMessages({ gateId: '' });
        if (cancelled) return;
        if (!ok) {
          scheduleRetry();
          return;
        }
        scheduleRetry();
        return;
      }
      const controller = new AbortController();
      infoWaitAbortRef.current = controller;
      try {
        const snapshot = await waitForGateMessageSnapshot(
          gateId,
          infoCursorRef.current,
          ACTIVE_GATE_ROOM_MESSAGE_LIMIT,
          {
          timeoutMs: nextGateMessagesWaitTimeoutMs(),
          signal: controller.signal,
          },
        );
        infoWaitAbortRef.current = null;
        if (cancelled) return;
        infoCursorRef.current = snapshot.cursor;
        if (snapshot.changed) {
          await refreshInfonetMessages({ gateId, snapshot });
          void runNext();
          return;
        }
        clearRetry();
        infoPollTimerRef.current = setTimeout(() => {
          infoPollTimerRef.current = null;
          void runNext();
        }, nextGateMessagesWaitRearmDelayMs());
      } catch {
        infoWaitAbortRef.current = null;
        if (cancelled || controller.signal.aborted) {
          return;
        }
        const ok = await refreshInfonetMessages({ gateId, force: true });
        if (cancelled) return;
        if (!ok) {
          scheduleRetry();
          return;
        }
        startWaitIfNeeded();
      }
    };

    if (gateId && liveStreamPreferredForSelectedGateNow) {
      void refreshInfonetMessages({ gateId, proofMode: 'session_stream' });
      return () => {
        cancelled = true;
        clearRetry();
        if (infoWaitAbortRef.current) {
          infoWaitAbortRef.current.abort();
          infoWaitAbortRef.current = null;
        }
      };
    }

    void refreshInfonetMessages({ gateId: selectedGate }).then((ok) => {
      streamEnabledForSelectedGateRef.current =
        streamPreferredForSelectedGate || isLiveStreamPreferredForSelectedGate();
      if (cancelled) return;
      if (!ok) {
        scheduleRetry();
        return;
      }
      if (!streamEnabledForSelectedGateRef.current) {
        startWaitIfNeeded();
      }
    });

    return () => {
      cancelled = true;
      clearRetry();
      if (infoWaitAbortRef.current) {
        infoWaitAbortRef.current.abort();
        infoWaitAbortRef.current = null;
      }
    };
  }, [
    expanded,
    activeTab,
    selectedGate,
    gateKeyStatus,
    gatePersonaBusy,
    gatePersonaPromptOpen,
    gateSessionStreamHydrated,
    refreshInfonetMessages,
    streamPreferredForSelectedGate,
  ]);

  useEffect(() => {
    return () => {
      if (infoPollTimerRef.current) {
        clearTimeout(infoPollTimerRef.current);
        infoPollTimerRef.current = null;
      }
      if (infoWaitAbortRef.current) {
        infoWaitAbortRef.current.abort();
        infoWaitAbortRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (!infoMessages.length) {
        setInfoVerification({});
        return;
      }
      const results: Record<string, 'verified' | 'failed' | 'unsigned'> = {};
      const toVerify = infoMessages.filter((message) => {
        const eventType = message.event_type || (message.gate ? 'gate_message' : 'message');
        if (eventType === 'gate_message') {
          return false;
        }
        const cacheKey = String(message.event_id || '').trim();
        if (cacheKey && infoVerificationCacheRef.current.has(cacheKey)) {
          results[cacheKey] = infoVerificationCacheRef.current.get(cacheKey)!;
          return false;
        }
        return true;
      });
      const verified = await Promise.all(
        toVerify.map(async (m) => {
          if (!m.signature || !m.public_key || !m.public_key_algo || !m.sequence) {
            return [String(m.event_id || ''), 'unsigned'] as const;
          }
          const eventType = m.event_type || (m.gate ? 'gate_message' : 'message');
          const payload = {
            message: m.message,
            destination: m.destination ?? 'broadcast',
            channel: m.channel ?? 'LongFast',
            priority: m.priority ?? 'normal',
            ephemeral: Boolean(m.ephemeral),
          };
          const ok = await verifyEventSignature({
            eventType,
            nodeId: String(m.node_id || ''),
            sequence: m.sequence || 0,
            payload,
            signature: m.signature,
            publicKey: m.public_key,
            publicKeyAlgo: m.public_key_algo,
          });
          return [String(m.event_id || ''), ok ? 'verified' : 'failed'] as const;
        }),
      );
      for (const [eventId, status] of verified) {
        if (!eventId) continue;
        results[eventId] = status;
        infoVerificationCacheRef.current.set(eventId, status);
        if (infoVerificationCacheRef.current.size > INFO_VERIFICATION_CACHE_MAX) {
          const oldestKey = infoVerificationCacheRef.current.keys().next().value;
          if (oldestKey) {
            infoVerificationCacheRef.current.delete(oldestKey);
          }
        }
      }
      if (!cancelled) setInfoVerification(results);
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [infoMessages]);

}
