import { useCallback, useEffect } from 'react';
import { API_BASE } from '@/lib/api';
import { normalizeInfoNetMessage, isEncryptedGateEnvelope, gateDecryptCacheKey } from './useMeshChatController.helpers';
import { decryptWormholeGateMessages } from '@/mesh/wormholeClient';
import { describeNativeControlError } from '@/lib/desktopBridge';
import { describeGateLocalRuntimeRequired } from './useMeshChatController.helpers';

const GATE_DECRYPT_CACHE_MAX = 200;
const ACTIVE_GATE_ROOM_MESSAGE_LIMIT = 120;

export interface MeshInfonetMessagesCtx {
  wormholeEnabled: boolean;
  wormholeReadyState: boolean;
  gateDecryptCacheRef: React.MutableRefObject<Map<string, any>>;
  infoCursorRef: React.MutableRefObject<number>;
  infoPollSignatureRef: React.MutableRefObject<string>;
  selectedGateRef: React.MutableRefObject<string>;
  repsRef: React.MutableRefObject<Record<string, number>>;
  setGateError: (v: string) => void;
  markGateResyncRequired: (err: unknown, gateIdHint?: string) => boolean;
  setInfoMessages: (v: any[]) => void;
  setReps: (v: any) => void;
  fetchGateMessageSnapshotState: (gateId: string, limit: number, opts?: any) => Promise<any>;
  selectedGate: string | null;
  [k: string]: any;
}

export function useMeshInfonetMessages(ctx: MeshInfonetMessagesCtx) {
  const {
    wormholeEnabled, wormholeReadyState, gateDecryptCacheRef, infoCursorRef, infoPollSignatureRef,
    selectedGateRef, repsRef, setGateError, markGateResyncRequired, setInfoMessages, setReps,
    fetchGateMessageSnapshotState, selectedGate,
  } = ctx;

  const hydrateInfonetMessages = useCallback(
    async (messages: InfoNetMessage[]): Promise<InfoNetMessage[]> => {
      const baseMessages = (Array.isArray(messages) ? messages : []).map(normalizeInfoNetMessage);
      if (!wormholeEnabled || !wormholeReadyState) {
        return baseMessages.map((message) => ({ ...message, decrypted_message: '' }));
      }
      const hydrated: Array<InfoNetMessage | null> = baseMessages.map((message) => {
        if (!isEncryptedGateEnvelope(message)) {
          return { ...message, decrypted_message: '' };
        }
        const cacheKey = gateDecryptCacheKey(message);
        const cached = gateDecryptCacheRef.current.get(cacheKey);
        if (!cached) {
          return null;
        }
        gateDecryptCacheRef.current.delete(cacheKey);
        gateDecryptCacheRef.current.set(cacheKey, cached);
        return {
          ...message,
          epoch: Number(cached.epoch || message.epoch || 0),
          decrypted_message: String(cached.plaintext || ''),
          reply_to: String(cached.replyTo || message.reply_to || ''),
        };
      });

      const pendingDecrypts = baseMessages
        .map((message, index) => ({ index, message }))
        .filter(({ message, index }) => isEncryptedGateEnvelope(message) && hydrated[index] === null)
        .map(({ index, message }) => ({
          index,
          message,
          cacheKey: gateDecryptCacheKey(message),
        }));

      if (pendingDecrypts.length > 0) {
        try {
          const batch = await decryptWormholeGateMessages(
            pendingDecrypts.map(({ message }) => ({
              gate_id: String(message.gate || ''),
              epoch: 0,
              ciphertext: String(message.ciphertext || ''),
              nonce: String(message.nonce || ''),
              sender_ref: String(message.sender_ref || ''),
              format: String(message.format || 'mls1'),
              gate_envelope: String(message.gate_envelope || ''),
              envelope_hash: String(message.envelope_hash || ''),
            })),
          );
          const results = Array.isArray(batch.results) ? batch.results : [];
          const compatDecryptBlocked = results.some(
            (result) => !result?.ok && String(result?.detail || '') === 'gate_backend_decrypt_recovery_only',
          );
          if (compatDecryptBlocked) {
            setGateError(
              'Service-side gate decrypt is disabled on this runtime. Use native desktop or an explicit recovery path.',
            );
          }
          pendingDecrypts.forEach(({ index, message, cacheKey }, resultIndex) => {
            const decrypted = results[resultIndex];
            if (decrypted?.ok) {
              const selfAuthored = Boolean(decrypted.self_authored);
              const entry = {
                epoch: Number(decrypted.epoch || message.epoch || 0),
                plaintext: selfAuthored && !decrypted.plaintext
                  ? (decrypted.legacy
                    ? '[legacy gate message — pre-encryption-fix]'
                    : '[your message — plaintext not cached]')
                  : String(decrypted.plaintext || ''),
                replyTo: String(decrypted.reply_to || '').trim(),
              };
              if (gateDecryptCacheRef.current.has(cacheKey)) {
                gateDecryptCacheRef.current.delete(cacheKey);
              }
              gateDecryptCacheRef.current.set(cacheKey, entry);
              if (gateDecryptCacheRef.current.size > GATE_DECRYPT_CACHE_MAX) {
                const oldestKey = gateDecryptCacheRef.current.keys().next().value;
                if (oldestKey) {
                  gateDecryptCacheRef.current.delete(oldestKey);
                }
              }
              hydrated[index] = {
                ...message,
                epoch: entry.epoch,
                decrypted_message: entry.plaintext,
                reply_to: entry.replyTo || String(message.reply_to || ''),
              };
              return;
            }
            hydrated[index] = { ...message, decrypted_message: '' };
          });
        } catch (err) {
          const gateIdHint = String(pendingDecrypts[0]?.message?.gate || '').trim().toLowerCase();
          const detail = err instanceof Error ? err.message : '';
          if (
            detail === 'gate_compat_fallback_consent_required' ||
            detail.startsWith('gate_local_runtime_required:')
          ) {
            setGateError(describeGateLocalRuntimeRequired(detail, gateIdHint));
          } else if (markGateResyncRequired(err, gateIdHint)) {
            setGateError(
              describeNativeControlError(err) || 'Gate state changed on another path. Resync before retrying.',
            );
          }
          pendingDecrypts.forEach(({ index, message }) => {
            hydrated[index] = { ...message, decrypted_message: '' };
          });
        }
      }

      return hydrated.map(
        (message, index) => message ?? { ...baseMessages[index], decrypted_message: '' },
      );
    },
    [markGateResyncRequired, wormholeEnabled, wormholeReadyState],
  );

  useEffect(() => {
    selectedGateRef.current = String(selectedGate || '').trim().toLowerCase();
    infoCursorRef.current = 0;
  }, [selectedGate]);

  const refreshInfonetMessages = useCallback(
    async ({
      gateId,
      force = false,
      snapshot,
      proofMode,
    }: {
      gateId?: string;
      force?: boolean;
      snapshot?: GateMessageSnapshotState;
      proofMode?: GateAccessHeaderMode;
    } = {}): Promise<boolean> => {
      try {
        const targetGate = String(gateId ?? selectedGateRef.current ?? '')
          .trim()
          .toLowerCase();
        let rawMessages: InfoNetMessage[] = [];
        if (targetGate) {
          const nextSnapshot =
            snapshot ??
            (await fetchGateMessageSnapshotState(targetGate, ACTIVE_GATE_ROOM_MESSAGE_LIMIT, {
              force,
              proofMode,
            }));
          if (targetGate === selectedGateRef.current) {
            infoCursorRef.current = nextSnapshot.cursor;
          }
          rawMessages = nextSnapshot.messages.map((message) =>
            normalizeInfoNetMessage(message as InfoNetMessage),
          );
        } else {
          infoCursorRef.current = 0;
          const params = new URLSearchParams({ limit: '30' });
          const res = await fetch(`${API_BASE}/api/mesh/infonet/messages?${params}`);
          if (!res.ok) {
            return false;
          }
          const data = await res.json();
          rawMessages = Array.isArray(data.messages)
            ? (data.messages as InfoNetMessage[]).map(normalizeInfoNetMessage)
            : [];
        }
        const pollSignature = [
          targetGate,
          wormholeEnabled ? '1' : '0',
          wormholeReadyState ? '1' : '0',
          rawMessages.map((message) => String(message.event_id || '')).join('|'),
        ].join('::');
        if (targetGate && targetGate !== selectedGateRef.current) {
          return true;
        }
        if (force || infoPollSignatureRef.current !== pollSignature) {
          const hydrated = await hydrateInfonetMessages(rawMessages);
          if (targetGate && targetGate !== selectedGateRef.current) {
            return true;
          }
          infoPollSignatureRef.current = pollSignature;
          setInfoMessages(hydrated.reverse());
        } else {
          infoPollSignatureRef.current = pollSignature;
        }

        const nodeIds = [
          ...new Set(
            rawMessages
              .map((message: InfoNetMessage) => String(message.node_id || '').trim())
              .filter(Boolean),
          ),
        ];
        const uncachedNodeIds = nodeIds.filter(
          (nid) => !Object.prototype.hasOwnProperty.call(repsRef.current, nid),
        );
        if (uncachedNodeIds.length > 0) {
          try {
            const repParams = new URLSearchParams();
            uncachedNodeIds.slice(0, 100).forEach((nid) => repParams.append('node_id', nid));
            const repRes = await fetch(`${API_BASE}/api/mesh/reputation/batch?${repParams.toString()}`);
            if (repRes.ok) {
              const repData = await repRes.json();
              const reputations =
                repData && typeof repData.reputations === 'object' && repData.reputations
                  ? repData.reputations
                  : {};
              setReps((prev) => {
                let changed = false;
                const next = { ...prev };
                for (const [nid, value] of Object.entries(reputations)) {
                  const overall = Number(value || 0);
                  if (next[nid] !== overall) {
                    next[nid] = overall;
                    changed = true;
                  }
                }
                return changed ? next : prev;
              });
            }
          } catch {
            /* ignore */
          }
        }
        return true;
      } catch {
        return false;
      }
    },
    [hydrateInfonetMessages, wormholeEnabled, wormholeReadyState],
  );

  return { hydrateInfonetMessages, refreshInfonetMessages };
}
