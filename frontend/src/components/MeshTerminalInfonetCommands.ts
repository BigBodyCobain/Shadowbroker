import { useCallback } from 'react';
import {
  hasSovereignty, createIdentityCandidate, getPublicKeyAlgo, signMessage,
  nextSequence, signEvent, persistIdentity, setSequence, generateDHKeys, verifyEventSignature,
} from '@/mesh/meshIdentity';
import { PROTOCOL_VERSION, buildSignaturePayload } from '@/mesh/meshProtocol';
import { validateEventPayload } from '@/mesh/meshSchema';
import { verifyMerkleProof } from '@/mesh/meshMerkle';
import type { InfonetMerkleProof } from './MeshTerminal.shared';

const API = '';

export interface MeshTerminalInfonetCmdsCtx {
  addError: (t: string) => void;
  addLines: (lines: any[]) => void;
  addOutput: (t: string) => void;
  addSystem: (t: string) => void;
  nodeIdentity: any;
  setNodeIdentity: (v: any) => void;
  getInfonetLocator: () => any;
  getInfonetPeers: () => string[];
  getPrivacyStrictPreference: () => boolean;
  setInfonetHead: (v: any) => void;
  [k: string]: any;
}

export function useMeshTerminalInfonetCommands(ctx: MeshTerminalInfonetCmdsCtx) {
  const {
    addError, addLines, addOutput, addSystem, nodeIdentity, setNodeIdentity,
    getInfonetLocator, getInfonetPeers, getPrivacyStrictPreference, setInfonetHead,
  } = ctx as any;

  const cmdMerkle = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/mesh/infonet/merkle`);
      const data = await res.json();
      addSystem('');
      addSystem('  INFONET MERKLE');
      addOutput(`    Merkle Root: ${data.merkle_root || 'genesis'}`);
      addOutput(`    Head Hash:   ${data.head_hash || 'genesis'}`);
      addOutput(`    Count:       ${data.count ?? 0}`);
      addSystem('');
    } catch {
      addError('Failed to fetch merkle root');
    }
  }, [addOutput, addError, addSystem]);

  const cmdSync = useCallback(
    async (limit: number = 100) => {
      try {
        const locator = getInfonetLocator();
        const peers = getInfonetPeers();
        const strictPrivacy = getPrivacyStrictPreference();
        const shuffled = [...peers].sort(() => Math.random() - 0.5);
        const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
        const requests = shuffled.map(async (peer, idx) => {
          try {
            if (strictPrivacy) {
              const jitter = 50 + Math.floor(Math.random() * 350) + idx * 25;
              await sleep(jitter);
            }
            const res = await fetch(`${peer}/api/mesh/infonet/sync`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ locator, limit, include_proofs: true }),
            });
            const data = await res.json();
            if (data.ok === false) return null;
            return { peer, data };
          } catch {
            return null;
          }
        });

        const responses = (await Promise.all(requests)).filter(
          (r): r is { peer: string; data: any } => Boolean(r),
        );
        const failures = peers.length - responses.length;
        if (responses.length === 0) {
          addError('Sync failed: no peers responded');
          return;
        }

        const forkedResponses = responses.filter((r) => r.data.forked);
        const candidates = responses.filter((r) => !r.data.forked);
        if (candidates.length === 0) {
          addError('Fork detected across all peers — no safe head to follow');
          return;
        }

        const groups = new Map<
          string,
          { count: number; samples: { peer: string; data: any }[] }
        >();
        for (const r of candidates) {
          const key = String(r.data.matched_hash || '');
          const group = groups.get(key) || { count: 0, samples: [] };
          group.count += 1;
          group.samples.push(r);
          groups.set(key, group);
        }
        const quorum = Math.floor(candidates.length / 2) + 1;
        let selectedGroup:
          | { count: number; samples: { peer: string; data: any }[] }
          | null = null;
        for (const group of groups.values()) {
          if (!selectedGroup || group.count > selectedGroup.count) selectedGroup = group;
        }
        if (!selectedGroup || selectedGroup.count < quorum) {
          addError('No majority match on locator — sync aborted');
          return;
        }

        const selected = selectedGroup.samples.reduce((best, cur) =>
          (cur.data.events?.length || 0) > (best.data.events?.length || 0) ? cur : best,
        );
        const data = selected.data;
        const events = data.events || [];
        const matched = data.matched_hash || '';
        const forked = false;
        const proofs = Array.isArray(data.merkle_proofs) ? data.merkle_proofs : [];
        const merkleRoot = data.merkle_root || '';
        const peerUsed = selected.peer;
        let verified = 0;
        let failed = 0;
        let unsigned = 0;
        let merkleVerified = 0;
        let merkleFailed = 0;

        for (const e of events) {
          if (!e.signature || !e.public_key || !e.public_key_algo) {
            unsigned += 1;
            continue;
          }
          if (String(e.event_type || '') === 'gate_message') {
            verified += 1;
            continue;
          }
          const ok = await verifyEventSignature({
            eventType: e.event_type,
            nodeId: e.node_id,
            sequence: e.sequence || 0,
            payload: e.payload || {},
            signature: e.signature,
            publicKey: e.public_key,
            publicKeyAlgo: e.public_key_algo,
          });
          if (ok) verified += 1;
          else failed += 1;
        }

        if (merkleRoot && proofs.length) {
          const proofMap = new Map<string, InfonetMerkleProof>();
          for (const p of proofs) {
            if (p?.leaf) proofMap.set(p.leaf, p);
          }
          for (const e of events) {
            const proof = proofMap.get(e.event_id);
            if (!proof) {
              merkleFailed += 1;
              continue;
            }
            const ok = await verifyMerkleProof(
              String(proof.leaf),
              Number(proof.index ?? 0),
              Array.isArray(proof.proof)
                ? proof.proof.map((h: any) => ({ hash: h, side: 'left' as const }))
                : [],
              merkleRoot,
            );
            if (ok) merkleVerified += 1;
            else merkleFailed += 1;
          }
        }

        addSystem('');
        addSystem('  INFONET SYNC');
        addOutput(`    Remote Head: ${data.head_hash || 'genesis'}`);
        addOutput(`    Locator:     ${locator[0] ? `${locator[0].slice(0, 16)}...` : 'genesis'}`);
        addOutput(`    Matched:     ${matched ? `${matched.slice(0, 16)}...` : 'none'}`);
        addOutput(`    Forked:      ${forked ? 'YES' : 'NO'}`);
        addOutput(
          `    Peers:       ${peers.length} ok / ${candidates.length} safe / ${forkedResponses.length} forked / ${failures} failed`,
        );
        addOutput(`    Quorum:      ${selectedGroup.count}/${candidates.length} (peer ${peerUsed})`);
        addOutput(`    Pulled:      ${events.length}`);
        addOutput(`    Verified:    ${verified}`);
        addOutput(`    Failed:      ${failed}`);
        addOutput(`    Unsigned:    ${unsigned}`);
        addOutput(
          `    Merkle:      ${
            merkleRoot ? `${merkleRoot.slice(0, 16)}...` : 'n/a'
          } (${merkleVerified} ok / ${merkleFailed} fail)`,
        );

        if (forked) {
          addError('Fork detected — head not advanced');
        } else if (failed === 0 && (merkleFailed === 0 || !merkleRoot) && data.head_hash) {
          setInfonetHead(data.head_hash);
          addOutput(`    Head Saved:  ${data.head_hash.slice(0, 16)}...`);
        } else if (failed > 0) {
          addError('Signature failures detected — head not advanced');
        } else if (merkleFailed > 0) {
          addError('Merkle proof failures detected — head not advanced');
        }
        addSystem('');
      } catch {
        addError('Failed to sync Infonet');
      }
    },
    [addOutput, addError, addSystem, getInfonetLocator, getInfonetPeers, setInfonetHead],
  );

  const cmdRevoke = useCallback(
    async (args: string[]) => {
      if (!nodeIdentity || !hasSovereignty()) {
        addError("Not connected. Type 'connect' to activate your Agent identity.");
        return;
      }
      const DEFAULT_GRACE_HOURS = 48;
      const MAX_GRACE_HOURS = 168;
      let graceHours = DEFAULT_GRACE_HOURS;
      let reason = args.join(' ').trim();
      if (args.length > 0) {
        const last = args[args.length - 1];
        const parsed = Number(last);
        if (Number.isFinite(parsed)) {
          graceHours = Math.max(1, Math.min(MAX_GRACE_HOURS, Math.trunc(parsed)));
          reason = args.slice(0, -1).join(' ').trim();
        }
      }
      if (!reason) reason = 'compromised';

      try {
        const revokedAt = Math.floor(Date.now() / 1000);
        const graceUntil = revokedAt + graceHours * 3600;
        const payload = {
          revoked_public_key: nodeIdentity.publicKey,
          revoked_public_key_algo: getPublicKeyAlgo(),
          revoked_at: revokedAt,
          grace_until: graceUntil,
          reason,
        };
        const v = validateEventPayload('key_revoke', payload);
        if (!v.ok) {
          addError(`Invalid payload: ${v.reason}`);
          return;
        }
        const sequence = nextSequence();
        const signature = await signEvent('key_revoke', nodeIdentity.nodeId, sequence, payload);
        const res = await fetch(`${API}/api/mesh/identity/revoke`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            node_id: nodeIdentity.nodeId,
            public_key: nodeIdentity.publicKey,
            public_key_algo: getPublicKeyAlgo(),
            signature,
            sequence,
            protocol_version: PROTOCOL_VERSION,
            revoked_at: revokedAt,
            grace_until: graceUntil,
            reason,
          }),
        });
        const data = await res.json();
        if (data.ok) {
          addSystem(`  Revocation recorded. Grace window: ${graceHours}h.`);
        } else {
          addError(data.detail || 'Revocation failed');
        }
      } catch {
        addError('Revocation failed');
      }
    },
    [addError, addSystem, nodeIdentity],
  );

  const cmdRotate = useCallback(async () => {
    if (!nodeIdentity || !hasSovereignty()) {
      addError("Not connected. Type 'connect' to activate your Agent identity.");
      return;
    }
    try {
      addSystem('  Generating new identity...');
      const { identity: newIdentity, algo: newAlgo } = await createIdentityCandidate();
      const oldAlgo = getPublicKeyAlgo();
      const timestamp = Math.floor(Date.now() / 1000);

      const claimPayload = {
        old_node_id: nodeIdentity.nodeId,
        old_public_key: nodeIdentity.publicKey,
        old_public_key_algo: oldAlgo,
        new_public_key: newIdentity.publicKey,
        new_public_key_algo: newAlgo,
        timestamp,
      };

      const oldSigPayload = buildSignaturePayload({
        eventType: 'key_rotate',
        nodeId: nodeIdentity.nodeId,
        sequence: 0,
        payload: claimPayload,
      });
      const oldSignature = await signMessage(oldSigPayload, nodeIdentity.privateKey, oldAlgo);

      const fullPayload = { ...claimPayload, old_signature: oldSignature };
      const v = validateEventPayload('key_rotate', fullPayload);
      if (!v.ok) {
        addError(`Invalid payload: ${v.reason}`);
        return;
      }
      const sequence = 1;
      const newSigPayload = buildSignaturePayload({
        eventType: 'key_rotate',
        nodeId: newIdentity.nodeId,
        sequence,
        payload: fullPayload,
      });
      const newSignature = await signMessage(newSigPayload, newIdentity.privateKey, newAlgo);

      const res = await fetch(`${API}/api/mesh/identity/rotate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          old_node_id: nodeIdentity.nodeId,
          old_public_key: nodeIdentity.publicKey,
          old_public_key_algo: oldAlgo,
          old_signature: oldSignature,
          new_node_id: newIdentity.nodeId,
          new_public_key: newIdentity.publicKey,
          new_public_key_algo: newAlgo,
          new_signature: newSignature,
          timestamp,
          sequence,
          protocol_version: PROTOCOL_VERSION,
        }),
      });
      const data = await res.json();
      if (!data.ok) {
        addError(data.detail || 'Rotation failed');
        return;
      }

      persistIdentity(newIdentity, newAlgo, sequence);
      setSequence(sequence);
      setNodeIdentity(newIdentity);
      await generateDHKeys();

      addSystem(`  Identity rotated to ${newIdentity.nodeId}`);
    } catch (err) {
      const msg =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : '';
      const dhStorageFailure =
        msg !== 'browser_identity_blocked_secure_mode' &&
        /(indexeddb|browser storage|dh key|storage unavailable)/i.test(msg);
      addError(
        msg === 'browser_identity_blocked_secure_mode'
          ? 'Browser identity rotation is disabled in Wormhole secure mode'
          : dhStorageFailure
            ? 'Identity rotation failed: browser storage unavailable for DH key generation'
            : 'Identity rotation failed',
      );
    }
  }, [addError, addSystem, nodeIdentity]);

  return { cmdMerkle, cmdSync, cmdRevoke, cmdRotate };
}
