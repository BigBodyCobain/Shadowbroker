import { useCallback } from 'react';
import {
  hasSovereignty, createIdentityCandidate, getPublicKeyAlgo, signMessage, signEvent,
  nextSequence, getContacts, addContact, getDHAlgo,
} from '@/mesh/meshIdentity';
import { PROTOCOL_VERSION, buildSignaturePayload } from '@/mesh/meshProtocol';
import { validateEventPayload } from '@/mesh/meshSchema';
import { ratchetEncryptDM } from '@/mesh/meshDmWorkerClient';
import {
  ensureRegisteredDmKey, fetchDmPublicKey, sendDmMessage, sharedMailboxToken,
} from '@/mesh/meshDmClient';

const API = '';

export interface MeshTerminalSendFlowCtx {
  addError: (t: string) => void;
  addLines: (lines: any[]) => void;
  addSystem: (t: string) => void;
  nodeIdentity: any;
  setSendStep: (v: any) => void;
  [k: string]: any;
}

export function useMeshTerminalSendFlow(ctx: MeshTerminalSendFlowCtx) {
  const { addError, addLines, addSystem, nodeIdentity, setSendStep } = ctx as any;

  const doSend = useCallback(
    async (dest: string, message: string) => {
      // Must be connected to send
      if (!nodeIdentity || !hasSovereignty()) {
        addError("Not connected. Type 'connect' to activate your Agent identity.");
        return;
      }

      addSystem(`  Signing as ${nodeIdentity.nodeId}...`);
      try {
        const sequence = nextSequence();
        const payload = {
          message,
          destination: dest,
          channel: 'LongFast',
          priority: 'normal',
          ephemeral: false,
        };
        const v = validateEventPayload('message', payload);
        if (!v.ok) {
          addError(`Invalid payload: ${v.reason}`);
          return;
        }
        const signature = await signEvent('message', nodeIdentity.nodeId, sequence, payload);

        addSystem(`  Routing to ${dest}...`);
        const res = await fetch(`${API}/api/mesh/send`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sender_id: nodeIdentity.nodeId,
            node_id: nodeIdentity.nodeId,
            public_key: nodeIdentity.publicKey,
            public_key_algo: getPublicKeyAlgo(),
            signature: signature,
            destination: dest,
            message: message,
            priority: 'normal',
            ephemeral: false,
            sequence,
            protocol_version: PROTOCOL_VERSION,
          }),
        });
        const data = await res.json();
        if (data.results) {
          for (const r of data.results) {
            addLines([
              {
                text: `    [${r.ok ? 'OK' : 'FAIL'}] ${r.transport}: ${r.detail}`,
                type: r.ok ? 'output' : 'error',
              },
            ]);
          }
        }
        if (data.route_reason) addSystem(`    ${data.route_reason}`);
        addSystem('');
      } catch {
        addError('Mesh router unreachable');
      }
    },
    [addLines, addError, addSystem, nodeIdentity],
  );

  // ─── Meshtastic regional send ─────────────────────────────
  const doMeshSend = useCallback(
    async (message: string, region: string) => {
      if (!nodeIdentity || !hasSovereignty()) {
        addError("Public mesh needs a public Agent identity. Type 'connect' first.");
        return;
      }
      addSystem(`  Signing as ${nodeIdentity.nodeId}...`);
      try {
        const sequence = nextSequence();
        const payload = {
          message,
          destination: 'broadcast',
          channel: 'LongFast',
          priority: 'normal',
          ephemeral: false,
          transport_lock: 'meshtastic',
        };
        const v = validateEventPayload('message', payload);
        if (!v.ok) {
          addError(`Invalid payload: ${v.reason}`);
          return;
        }
        const signature = await signEvent('message', nodeIdentity.nodeId, sequence, payload);
        addSystem(`  Publishing to ${region}/LongFast...`);
        const res = await fetch(`${API}/api/mesh/send`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sender_id: nodeIdentity.nodeId,
            node_id: nodeIdentity.nodeId,
            public_key: nodeIdentity.publicKey,
            public_key_algo: getPublicKeyAlgo(),
            signature,
            destination: 'broadcast',
            message,
            priority: 'normal',
            channel: 'LongFast',
            ephemeral: false,
            transport_lock: 'meshtastic',
            sequence,
            protocol_version: PROTOCOL_VERSION,
            credentials: { mesh_region: region },
          }),
        });
        const data = await res.json();
        if (data.results) {
          for (const r of data.results) {
            addLines([
              {
                text: `    [${r.ok ? 'OK' : 'FAIL'}] ${r.transport}: ${r.detail}`,
                type: r.ok ? 'output' : 'error',
              },
            ]);
          }
        }
        addSystem('');
      } catch {
        addError('Mesh router unreachable');
      }
    },
    [addLines, addError, addSystem, nodeIdentity],
  );

  const startInteractiveSend = useCallback(() => {
    addSystem('');
    addSystem('  SEND MESSAGE');
    addLines([{ text: '  Who do you want to reach?', type: 'dim' }]);
    addLines([{ text: "  Enter a callsign (e.g. KE4EVL-Y) or 'broadcast':", type: 'dim' }]);
    addSystem('');
    setSendStep('dest');
  }, [addSystem, addLines]);

  // ─── Encrypted DM send ──────────────────────────────────
  const doDMSend = useCallback(
    async (recipientId: string, plaintext: string) => {
      if (!nodeIdentity || !hasSovereignty()) {
        addError("Not connected. Type 'connect' to activate your Agent identity.");
        return;
      }

      addSystem(`  Encrypting for ${recipientId}...`);
        try {
          // 1. Get recipient's DH public key from an existing invite-backed contact
          const contacts = getContacts();
          const recipientContact = contacts[recipientId];
          let theirDHPub = recipientContact?.dhPubKey;
          const contactAlgo = recipientContact?.dhAlgo;
          const localAlgo = getDHAlgo();
          if (contactAlgo && localAlgo && contactAlgo !== localAlgo) {
            addError('DM key algorithm mismatch. Regenerate keys to match recipient.');
            return;
          }

          if (!theirDHPub) {
            const lookupHandle = String(recipientContact?.invitePinnedPrekeyLookupHandle || '').trim();
            if (!lookupHandle) {
              addError(
                "No invite-backed DM key for this contact. Import or re-import a signed invite, or use 'dm add <agent_id>' only for legacy migration.",
              );
              return;
            }
            const keyData = await fetchDmPublicKey(API, recipientId, lookupHandle);
            if (!keyData?.dh_pub_key) {
              addError('Invite-scoped lookup failed. Re-import a signed invite and try again.');
              return;
            }
            theirDHPub = keyData.dh_pub_key as string;
            addContact(recipientId, theirDHPub, undefined, keyData.dh_algo);
            const localAlgo = getDHAlgo();
            if (keyData.dh_algo && localAlgo && keyData.dh_algo !== localAlgo) {
              addError('DM key algorithm mismatch. Regenerate keys to match recipient.');
              return;
            }
          }

          await ensureRegisteredDmKey(API, nodeIdentity, { force: false });
        // 2. Encrypt via the shared worker ratchet path
        const ciphertext = await ratchetEncryptDM(recipientId, theirDHPub!, plaintext);

        // 3. Send encrypted blob to server
        const msgId = `dm_${Date.now()}_${nodeIdentity.nodeId.slice(-4)}`;
        const timestamp = Math.floor(Date.now() / 1000);
        const recipientToken = await sharedMailboxToken(recipientId, theirDHPub!);
        const data = await sendDmMessage({
          apiBase: API,
          identity: nodeIdentity,
          recipientId,
          ciphertext,
          msgId,
          timestamp,
          deliveryClass: 'shared',
          recipientToken,
        });
        if (data.ok) {
          if (data.queued) {
            addSystem(`  Message sealed and queued for private delivery. ID: ${data.msg_id || msgId}`);
          } else {
            addSystem(`  Message delivered to dead drop. ID: ${data.msg_id || msgId}`);
          }
          addLines([{ text: '  Encrypted end-to-end. Server cannot read this.', type: 'dim' }]);
          if (data.private_transport_pending) {
            addLines([{ text: '  Private transport is warming up in the background.', type: 'dim' }]);
          }
        } else {
          addError(data.detail || 'DM delivery failed');
        }
      } catch (err) {
        const msg =
          typeof err === 'object' && err !== null && 'message' in err
            ? String((err as { message?: string }).message)
            : 'encryption error';
        addError(`DM failed: ${msg}`);
      }
      addSystem('');
    },
    [addLines, addError, addSystem, nodeIdentity],
  );

  return { doSend, doMeshSend, startInteractiveSend, doDMSend };
}
