type MerkleStep = { hash: string; side: 'left' | 'right' | string };

function bufToHex(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let out = '';
  for (let i = 0; i < bytes.length; i += 1) {
    out += bytes[i].toString(16).padStart(2, '0');
  }
  return out;
}

async function sha256Hex(data: string): Promise<string> {
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(data));
    return bufToHex(buf);
  }
  const mod = await import('crypto');
  return mod.createHash('sha256').update(data).digest('hex');
}

async function hashLeaf(value: string): Promise<string> {
  return sha256Hex(value);
}

async function hashPair(left: string, right: string): Promise<string> {
  return sha256Hex(`${left}${right}`);
}

export async function buildMerkleRoot(leaves: string[]): Promise<string> {
  if (!leaves.length) return '';
  let level = await Promise.all(leaves.map((leaf) => hashLeaf(leaf)));
  while (level.length > 1) {
    const next: string[] = [];
    for (let i = 0; i < level.length; i += 2) {
      const left = level[i];
      const right = level[i + 1] ?? left;
      next.push(await hashPair(left, right));
    }
    level = next;
  }
  return level[0];
}

export async function verifyMerkleProof(
  leafValue: string,
  index: number,
  proof: MerkleStep[],
  root: string,
): Promise<boolean> {
  let current = await hashLeaf(leafValue);
  let idx = index;
  for (const step of proof) {
    const sibling = step.hash ?? '';
    const side = String(step.side || 'right').toLowerCase();
    if (side === 'left') {
      current = await hashPair(sibling, current);
    } else {
      current = await hashPair(current, sibling);
    }
    idx = Math.floor(idx / 2);
  }
  return current === root;
}

export type { MerkleStep };
