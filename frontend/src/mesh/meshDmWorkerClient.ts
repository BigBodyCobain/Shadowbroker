import { controlPlaneJson } from '@/lib/controlPlane';
import { getDHAlgo } from '@/mesh/meshIdentity';
import { deleteWorkerRatchetDatabase } from '@/mesh/meshDmWorkerVault';
import { ensureWormholeReadyForSecureAction, isWormholeReady } from '@/mesh/wormholeIdentityClient';

type WorkerRequest =
  | {
      id: string;
      action: 'encrypt';
      peerId: string;
      peerDhPub: string;
      plaintext: string;
      dhAlgo: string;
    }
  | {
      id: string;
      action: 'decrypt';
      peerId: string;
      ciphertext: string;
      dhAlgo: string;
    }
  | {
      id: string;
      action: 'reset';
      peerId?: string;
    };

type WorkerResponse = { id: string; ok: boolean; result?: string; error?: string };

let worker: Worker | null = null;
let reqCounter = 0;
const pending = new Map<string, { resolve: (v: string) => void; reject: (err: Error) => void }>();
let browserRatchetClearedForWormhole = false;

function ensureWorker(): Worker {
  if (worker) return worker;
  worker = new Worker(new URL('./meshDm.worker.ts', import.meta.url), { type: 'module' });
  worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
    const msg = event.data;
    const handler = pending.get(msg.id);
    if (!handler) return;
    pending.delete(msg.id);
    if (msg.ok) {
      handler.resolve(String(msg.result || ''));
    } else {
      handler.reject(new Error(msg.error || 'worker_error'));
    }
  };
  return worker;
}

function callWorker(payload: Omit<WorkerRequest, 'id'> & Record<string, unknown>): Promise<string> {
  const id = `dmw_${Date.now()}_${reqCounter++}`;
  const req = { ...payload, id } as WorkerRequest;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    try {
      ensureWorker().postMessage(req);
    } catch (err) {
      pending.delete(id);
      reject(err as Error);
    }
  });
}

async function callWormhole(path: string, body: Record<string, unknown>): Promise<string> {
  const data = await controlPlaneJson<{ result?: string }>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return String(data?.result || '');
}

async function clearBrowserRatchetForWormhole(): Promise<void> {
  if (browserRatchetClearedForWormhole) return;
  try {
    await callWorker({ action: 'reset' });
  } catch {
    /* ignore */
  }
  browserRatchetClearedForWormhole = true;
}

export async function ratchetEncryptDM(
  peerId: string,
  theirDhPub: string,
  plaintext: string,
): Promise<string> {
  await ensureWormholeReadyForSecureAction('dm_encrypt');
  if (await isWormholeReady()) {
    await clearBrowserRatchetForWormhole();
    return callWormhole('/api/wormhole/dm/encrypt', {
      peer_id: peerId,
      peer_dh_pub: theirDhPub,
      plaintext,
    });
  }
  return callWorker({
    action: 'encrypt',
    peerId,
    peerDhPub: theirDhPub,
    plaintext,
    dhAlgo: getDHAlgo() || 'X25519',
  });
}

export async function ratchetDecryptDM(peerId: string, ciphertext: string): Promise<string> {
  await ensureWormholeReadyForSecureAction('dm_decrypt');
  if (await isWormholeReady()) {
    await clearBrowserRatchetForWormhole();
    return callWormhole('/api/wormhole/dm/decrypt', {
      peer_id: peerId,
      ciphertext,
    });
  }
  return callWorker({
    action: 'decrypt',
    peerId,
    ciphertext,
    dhAlgo: getDHAlgo() || 'X25519',
  });
}

export async function ratchetReset(peerId?: string): Promise<void> {
  await ensureWormholeReadyForSecureAction('dm_reset');
  if (await isWormholeReady()) {
    await callWormhole('/api/wormhole/dm/reset', {
      peer_id: peerId || '',
    });
    if (!peerId) browserRatchetClearedForWormhole = true;
    return;
  }
  await callWorker({ action: 'reset', peerId });
}

export async function purgeBrowserDmState(): Promise<void> {
  try {
    await callWorker({ action: 'reset' });
  } catch {
    /* ignore */
  }
  if (worker) {
    try {
      worker.terminate();
    } catch {
      /* ignore */
    }
    worker = null;
  }
  pending.clear();
  browserRatchetClearedForWormhole = true;
  await deleteWorkerRatchetDatabase();
  if (typeof window !== 'undefined') {
    try {
      localStorage.removeItem('sb_mesh_dm_ratchet');
      sessionStorage.removeItem('sb_mesh_dm_ratchet');
      localStorage.removeItem('sb_mesh_ratchet_telemetry');
      sessionStorage.removeItem('sb_mesh_ratchet_telemetry');
    } catch {
      /* ignore */
    }
  }
}
