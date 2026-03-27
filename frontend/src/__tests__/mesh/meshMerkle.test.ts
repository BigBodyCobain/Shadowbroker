import { readFileSync } from 'fs';
import path from 'path';
import { buildMerkleRoot, verifyMerkleProof } from '@/mesh/meshMerkle';

type Fixture = {
  leaves: string[];
  root: string;
  proofs: Record<string, { hash: string; side: string }[]>;
};

describe('mesh merkle fixtures', () => {
  const cwd = process.cwd();
  const fixturePath = cwd.endsWith('frontend')
    ? path.resolve(cwd, '..', 'docs', 'mesh', 'mesh-merkle-fixtures.json')
    : path.resolve(cwd, 'docs', 'mesh', 'mesh-merkle-fixtures.json');
  const fixtures = JSON.parse(readFileSync(fixturePath, 'utf-8')) as Fixture;

  it('builds the expected root', async () => {
    const root = await buildMerkleRoot(fixtures.leaves);
    expect(root).toBe(fixtures.root);
  });

  it('verifies provided proofs', async () => {
    const root = fixtures.root;
    for (const [idxStr, proof] of Object.entries(fixtures.proofs)) {
      const idx = Number(idxStr);
      const leaf = fixtures.leaves[idx];
      const ok = await verifyMerkleProof(leaf, idx, proof, root);
      expect(ok).toBe(true);
    }
  });
});
