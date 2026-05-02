/// <reference lib="webworker" />

import initPrivacyCore, {
  wasm_gate_decrypt,
  wasm_gate_encrypt,
  wasm_gate_export_state,
  wasm_gate_import_state,
  wasm_release_group,
  wasm_release_identity,
  wasm_reset_all_state,
} from './privacyCoreWasm/privacy_core';
import {
  clearWorkerGateStates,
  deleteWorkerGateState,
  readWorkerGateState,
  writeWorkerGateState,
  type WorkerGateStateMember,
  type WorkerGateStateSnapshot,
} from './meshGateWorkerVault';

type WorkerRequest =
  | { id: string; action: 'supported' }
  | { id: string; action: 'adopt'; snapshot: WorkerGateStateSnapshot }
  | { id: string; action: 'compose'; gateId: string; plaintext: string; replyTo?: string }
  | {
      id: string;
      action: 'decryptBatch';
      messages: Array<{ gate_id: string; epoch?: number; ciphertext: string }>;
    }
  | { id: string; action: 'forget'; gateId?: string };

type WorkerResponse = { id: string; ok: boolean; result?: unknown; error?: string };

type GateStateImportMapping = {
  identities: Record<string, number>;
  groups: Record<string, number>;
};

type ImportedGateState = {
  snapshot: WorkerGateStateSnapshot;
  identityHandles: number[];
  groupHandles: number[];
  activeGroupHandle: number;
  members: WorkerGateStateMember[];
};

const GATE_BUCKETS = [192, 384, 768, 1536, 3072, 6144];

let wasmReady: Promise<void> | null = null;
const gateStateCache = new Map<string, ImportedGateState>();

function normalizeGateId(gateId: string): string {
  return String(gateId || '').trim().toLowerCase();
}

function bytesToBase64(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes));
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(String(value || '').trim());
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    out[i] = binary.charCodeAt(i);
  }
  return out;
}

function padGateCiphertext(raw: Uint8Array): Uint8Array {
  const prefixed = new Uint8Array(raw.length + 2);
  const len = Math.min(raw.length, 0xffff);
  prefixed[0] = (len >> 8) & 0xff;
  prefixed[1] = len & 0xff;
  prefixed.set(raw, 2);
  for (const bucket of GATE_BUCKETS) {
    if (prefixed.length <= bucket) {
      const out = new Uint8Array(bucket);
      out.set(prefixed);
      return out;
    }
  }
  const lastBucket = GATE_BUCKETS[GATE_BUCKETS.length - 1] || 6144;
  const target = Math.ceil(prefixed.length / lastBucket) * lastBucket;
  const out = new Uint8Array(target);
  out.set(prefixed);
  return out;
}

function unpadGateCiphertext(padded: Uint8Array): Uint8Array {
  if (padded.length < 2) return padded;
  const originalLen = ((padded[0] << 8) | padded[1]) >>> 0;
  if (originalLen <= 0 || originalLen + 2 > padded.length) {
    return padded;
  }
  return padded.slice(2, 2 + originalLen);
}

function encodeGateCiphertext(raw: Uint8Array): string {
  return bytesToBase64(padGateCiphertext(raw));
}

function decodeGateCiphertext(ciphertextB64: string): Uint8Array {
  return unpadGateCiphertext(base64ToBytes(ciphertextB64));
}

function encodeGatePlaintext(plaintext: string, epoch: number, replyTo: string = ''): Uint8Array {
  const normalizedReplyTo = String(replyTo || '').trim();
  return new TextEncoder().encode(
    JSON.stringify({
      m: plaintext,
      e: epoch,
      ...(normalizedReplyTo ? { r: normalizedReplyTo } : {}),
    }),
  );
}

function decodeGatePlaintext(ciphertextOpen: Uint8Array, fallbackEpoch: number): {
  plaintext: string;
  epoch: number;
  reply_to: string;
} {
  const raw = new TextDecoder().decode(ciphertextOpen);
  try {
    const parsed = JSON.parse(raw) as { m?: string; e?: number; r?: string };
    return {
      plaintext: typeof parsed?.m === 'string' ? parsed.m : raw,
      epoch: Number.isFinite(parsed?.e) ? Number(parsed.e) : fallbackEpoch,
      reply_to: typeof parsed?.r === 'string' ? parsed.r : '',
    };
  } catch {
    return { plaintext: raw, epoch: fallbackEpoch, reply_to: '' };
  }
}

function generateGateNonce(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return bytesToBase64(bytes);
}

function gateMemberMatchesActive(
  snapshot: WorkerGateStateSnapshot,
  member: WorkerGateStateMember,
): boolean {
  const activeScope = String(snapshot.active_identity_scope || '').trim().toLowerCase();
  if (activeScope === 'persona') {
    const activePersonaId = String(snapshot.active_persona_id || '').trim();
    return Boolean(activePersonaId) && String(member.persona_id || '').trim() === activePersonaId;
  }
  const activeNodeId = String(snapshot.active_node_id || '').trim();
  return (
    Boolean(activeNodeId) &&
    String(member.node_id || '').trim() === activeNodeId &&
    String(member.identity_scope || '').trim().toLowerCase() === 'anonymous'
  );
}

async function ensureWasm(): Promise<void> {
  if (!wasmReady) {
    wasmReady = initPrivacyCore().then(() => undefined);
  }
  await wasmReady;
}

function releaseImportedState(imported: ImportedGateState): void {
  for (const groupHandle of imported.groupHandles) {
    try {
      wasm_release_group(BigInt(groupHandle));
    } catch {
      /* ignore */
    }
  }
  for (const identityHandle of imported.identityHandles) {
    try {
      wasm_release_identity(BigInt(identityHandle));
    } catch {
      /* ignore */
    }
  }
}

function cacheImportedState(imported: ImportedGateState): void {
  const gateId = normalizeGateId(imported.snapshot.gate_id);
  const previous = gateStateCache.get(gateId);
  if (previous) {
    releaseImportedState(previous);
  }
  gateStateCache.set(gateId, imported);
}

function parseImportMapping(json: string): GateStateImportMapping {
  const parsed = JSON.parse(json) as Partial<GateStateImportMapping>;
  return {
    identities: parsed.identities || {},
    groups: parsed.groups || {},
  };
}

async function importSnapshot(snapshot: WorkerGateStateSnapshot): Promise<ImportedGateState> {
  await ensureWasm();
  const blob = base64ToBytes(snapshot.rust_state_blob_b64);
  const mapping = parseImportMapping(wasm_gate_import_state(blob));
  const remappedMembers = (snapshot.members || []).map((member) => {
    const key = String(member.group_handle);
    const mapped = Number(mapping.groups[key] || 0);
    if (!mapped) {
      throw new Error(`browser_gate_state_mapping_missing_group:${key}`);
    }
    return {
      ...member,
      group_handle: mapped,
    };
  });
  const activeMember = remappedMembers.find((member) => gateMemberMatchesActive(snapshot, member));
  if (!activeMember?.group_handle) {
    throw new Error('browser_gate_state_active_member_missing');
  }
  return {
    snapshot: {
      ...snapshot,
      gate_id: normalizeGateId(snapshot.gate_id),
      members: remappedMembers,
    },
    identityHandles: Object.values(mapping.identities || {}).map((value) => Number(value)),
    groupHandles: Array.from(
      new Set(remappedMembers.map((member) => Number(member.group_handle)).filter(Boolean)),
    ),
    activeGroupHandle: Number(activeMember.group_handle),
    members: remappedMembers,
  };
}

async function persistImportedState(imported: ImportedGateState): Promise<void> {
  await ensureWasm();
  const blob = wasm_gate_export_state(
    JSON.stringify(imported.identityHandles),
    JSON.stringify(imported.groupHandles),
  );
  const snapshot: WorkerGateStateSnapshot = {
    ...imported.snapshot,
    gate_id: normalizeGateId(imported.snapshot.gate_id),
    rust_state_blob_b64: bytesToBase64(blob),
    members: imported.members,
  };
  imported.snapshot = snapshot;
  await writeWorkerGateState(snapshot);
}

async function ensureImportedGateState(gateId: string): Promise<ImportedGateState> {
  const normalized = normalizeGateId(gateId);
  const cached = gateStateCache.get(normalized);
  if (cached) return cached;
  const snapshot = await readWorkerGateState(normalized);
  if (!snapshot) {
    throw new Error(`browser_gate_state_resync_required:${normalized}`);
  }
  const imported = await importSnapshot(snapshot);
  cacheImportedState(imported);
  return imported;
}

async function adoptGateState(snapshot: WorkerGateStateSnapshot): Promise<WorkerGateStateSnapshot> {
  const imported = await importSnapshot(snapshot);
  cacheImportedState(imported);
  await persistImportedState(imported);
  return imported.snapshot;
}

async function forgetGateState(gateId?: string): Promise<void> {
  const normalized = normalizeGateId(gateId || '');
  if (!normalized) {
    for (const imported of gateStateCache.values()) {
      releaseImportedState(imported);
    }
    gateStateCache.clear();
    try {
      wasm_reset_all_state();
    } catch {
      /* ignore */
    }
    await clearWorkerGateStates();
    return;
  }
  const existing = gateStateCache.get(normalized);
  if (existing) {
    releaseImportedState(existing);
    gateStateCache.delete(normalized);
  }
  await deleteWorkerGateState(normalized);
}

async function composeGateCiphertext(gateId: string, plaintext: string, replyTo: string = ''): Promise<{
  gate_id: string;
  epoch: number;
  ciphertext: string;
  nonce: string;
}> {
  const imported = await ensureImportedGateState(gateId);
  const encodedPlaintext = encodeGatePlaintext(
    plaintext,
    Number(imported.snapshot.epoch || 0),
    replyTo,
  );
  const rawCiphertext = wasm_gate_encrypt(BigInt(imported.activeGroupHandle), encodedPlaintext);
  await persistImportedState(imported);
  return {
    gate_id: normalizeGateId(gateId),
    epoch: Number(imported.snapshot.epoch || 0),
    ciphertext: encodeGateCiphertext(rawCiphertext),
    nonce: generateGateNonce(),
  };
}

async function decryptGateBatch(
  messages: Array<{ gate_id: string; epoch?: number; ciphertext: string }>,
): Promise<Array<Record<string, unknown>>> {
  const results: Array<Record<string, unknown>> = [];
  for (const message of messages) {
    const gateId = normalizeGateId(message.gate_id);
    try {
      const imported = await ensureImportedGateState(gateId);
      const requestedEpoch = Number(message.epoch || 0);
      if (requestedEpoch > 0 && requestedEpoch > Number(imported.snapshot.epoch || 0)) {
        results.push({
          ok: false,
          detail: `browser_gate_state_resync_required:${gateId}`,
          gate_id: gateId,
        });
        continue;
      }
      const ciphertext = decodeGateCiphertext(message.ciphertext);
      let opened: Uint8Array | null = null;
      for (const groupHandle of imported.groupHandles) {
        try {
          opened = wasm_gate_decrypt(BigInt(groupHandle), ciphertext);
          break;
        } catch {
          /* keep trying remapped members */
        }
      }
      if (!opened) {
        results.push({
          ok: false,
          detail: 'gate_mls_decrypt_failed',
          gate_id: gateId,
        });
        continue;
      }
      const decoded = decodeGatePlaintext(opened, requestedEpoch || Number(imported.snapshot.epoch || 0));
      await persistImportedState(imported);
      results.push({
        ok: true,
        gate_id: gateId,
        epoch: decoded.epoch,
        plaintext: decoded.plaintext,
        reply_to: decoded.reply_to,
        identity_scope: 'browser_privacy_core',
      });
    } catch (error) {
      results.push({
        ok: false,
        detail: error instanceof Error ? error.message : 'browser_gate_crypto_error',
        gate_id: gateId,
      });
    }
  }
  return results;
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const msg = event.data;
  const respond = (payload: WorkerResponse) => postMessage(payload);
  try {
    switch (msg.action) {
      case 'supported':
        await ensureWasm();
        respond({ id: msg.id, ok: true, result: true });
        return;
      case 'adopt': {
        const snapshot = await adoptGateState(msg.snapshot);
        respond({ id: msg.id, ok: true, result: snapshot });
        return;
      }
      case 'compose': {
        const result = await composeGateCiphertext(msg.gateId, msg.plaintext, msg.replyTo || '');
        respond({ id: msg.id, ok: true, result });
        return;
      }
      case 'decryptBatch': {
        const results = await decryptGateBatch(msg.messages);
        respond({ id: msg.id, ok: true, result: results });
        return;
      }
      case 'forget':
        await forgetGateState(msg.gateId);
        respond({ id: msg.id, ok: true, result: true });
        return;
      default: {
        const unsupported = msg as { id?: string };
        respond({ id: unsupported.id || '', ok: false, error: 'unsupported_gate_worker_action' });
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'worker_error';
    respond({ id: msg.id, ok: false, error: message || 'worker_error' });
  }
};
