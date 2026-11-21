import { useEffect } from 'react';
import { hasSovereignty, getContacts, addContact, updateContact, deriveSharedKey, decryptDM } from '@/mesh/meshIdentity';
import { ratchetDecryptDM } from '@/mesh/meshDmWorkerClient';
import { buildMailboxClaims, countDmMailboxes, fetchDmPublicKey, pollDmMailboxes } from '@/mesh/meshDmClient';
import { classifyTick, MAX_CATCHUP_POLLS } from '@/lib/dmPollScheduler';
import type { InboxPreviewRecord } from './MeshTerminal.shared';

const API = '';

export interface MeshTerminalInboxPollingCtx {
  isOpen: boolean;
  surfacePanel: string;
  nodeIdentity: any;
  onDmCount?: (n: number) => void;
  setSurfaceInbox: (v: any[]) => void;
  setSurfaceInboxLoading: (v: boolean) => void;
}
export function useMeshTerminalInboxPolling(ctx: MeshTerminalInboxPollingCtx) {
  const { isOpen, surfacePanel, nodeIdentity, onDmCount, setSurfaceInbox, setSurfaceInboxLoading } = ctx;

  useEffect(() => {
    if (!isOpen || surfacePanel !== 'inbox') return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let catchUpBudget = MAX_CATCHUP_POLLS;

    const loadInboxSurface = async (includeCount = true) => {
      let hasMore = false;
      if (!nodeIdentity || !hasSovereignty()) {
        setSurfaceInbox([]);
        return;
      }
      setSurfaceInboxLoading(true);
      try {
        const claims = await buildMailboxClaims(getContacts());
        const pollPromise = pollDmMailboxes(API, nodeIdentity, claims);
        const countPromise = includeCount
          ? countDmMailboxes(API, nodeIdentity, claims).catch(() => ({ ok: false, count: 0 }))
          : null;
        const [data, countResult] = await Promise.all([pollPromise, countPromise]);
        if (cancelled) return;
        const msgs = Array.isArray(data.messages) ? data.messages : [];
        hasMore = Boolean(data.has_more);
        if (countResult && onDmCount) onDmCount(Number(countResult.count || 0));
        const previews: InboxPreviewRecord[] = [];
        for (const message of msgs.slice(0, 6)) {
          const ageMin = Math.floor((Date.now() / 1000 - message.timestamp) / 60);
          const age =
            ageMin < 60 ? `${ageMin}m ago` : `${Math.floor(ageMin / 60)}h ago`;
          try {
            const contacts = getContacts();
            let senderDH = contacts[message.sender_id]?.dhPubKey;
            if (!senderDH) {
              const contact = contacts[message.sender_id];
              const keyData = await fetchDmPublicKey(
                API,
                message.sender_id,
                contact?.invitePinnedPrekeyLookupHandle,
              );
              if (keyData?.dh_pub_key) {
                senderDH = keyData.dh_pub_key as string;
                addContact(message.sender_id, senderDH, undefined, keyData.dh_algo);
                updateContact(message.sender_id, {
                  dhAlgo: keyData.dh_algo || contact?.dhAlgo,
                  remotePrekeyLookupMode:
                    String(keyData.lookup_mode || '').trim().toLowerCase() ||
                    contact?.remotePrekeyLookupMode,
                });
              }
            }
            if (!senderDH) {
              previews.push({
                sender: message.sender_id,
                age,
                text: 'Key unavailable for preview',
                locked: true,
              });
              continue;
            }
            let plaintext = '';
            try {
              plaintext = await ratchetDecryptDM(message.sender_id, message.ciphertext);
            } catch {
              const sharedKey = await deriveSharedKey(senderDH);
              plaintext = await decryptDM(message.ciphertext, sharedKey);
            }
            previews.push({
              sender: message.sender_id,
              age,
              text: plaintext.slice(0, 140),
            });
          } catch {
            previews.push({
              sender: message.sender_id,
              age,
              text: 'Preview unavailable',
              locked: true,
            });
          }
        }
        setSurfaceInbox(previews);
      } catch {
        if (!cancelled) setSurfaceInbox([]);
      } finally {
        if (!cancelled) {
          setSurfaceInboxLoading(false);
          const classification = classifyTick(hasMore, catchUpBudget, 15_000);
          catchUpBudget = classification.newBudget;
          timer = setTimeout(
            () => void loadInboxSurface(classification.refreshCount),
            classification.delay,
          );
        }
      }
    };

    void loadInboxSurface();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [isOpen, surfacePanel, nodeIdentity, onDmCount]);
}
