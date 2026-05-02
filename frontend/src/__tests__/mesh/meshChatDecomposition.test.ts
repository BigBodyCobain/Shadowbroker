/**
 * Sprint 4A regression tests — MeshChat decomposition boundary checks.
 *
 * These tests validate the frozen contract:
 *  1. High-privacy DM queueing lives in the controller
 *  2. selectedGateAccessReady gating lives in the controller
 *  3. DM polling trust-mutation code lives in the controller
 *  4. Gate refresh is controller-owned via authenticated poll (SSE removed in S3A)
 *  5. Identity persistence stays in meshIdentity.ts (not in presentational code)
 *  6. No direct trust-mutating imports in presentational components
 */
import { describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

const MESH_CHAT_DIR = path.resolve(__dirname, '../../components/MeshChat');

function readFile(name: string): string {
  return fs.readFileSync(path.join(MESH_CHAT_DIR, name), 'utf-8');
}

// ─── Trust-mutation isolation ───────────────────────────────────────────────

const TRUST_MUTATING_IMPORTS = [
  'addContact',
  'updateContact',
  'blockContact',
  'purgeBrowserSigningMaterial',
  'purgeBrowserContactGraph',
  'purgeBrowserDmState',
];

describe('MeshChat decomposition — trust mutation isolation', () => {
  it('controller imports all trust-mutating functions', () => {
    const controller = readFile('useMeshChatController.ts');
    for (const fn of TRUST_MUTATING_IMPORTS) {
      expect(controller).toContain(fn);
    }
  });

  it('presentational index.tsx does NOT import trust-mutating functions directly', () => {
    const index = readFile('index.tsx');
    for (const fn of TRUST_MUTATING_IMPORTS) {
      // Check that none of these appear in import statements
      const importPattern = new RegExp(
        `import\\s*\\{[^}]*\\b${fn}\\b[^}]*\\}\\s*from`,
      );
      expect(index).not.toMatch(importPattern);
    }
  });

  it('presentational index.tsx does not import from meshIdentity', () => {
    const index = readFile('index.tsx');
    expect(index).not.toMatch(/from\s+['"]@\/mesh\/meshIdentity['"]/);
  });

  it('presentational index.tsx does not import from meshDmWorkerClient', () => {
    const index = readFile('index.tsx');
    expect(index).not.toMatch(/from\s+['"]@\/mesh\/meshDmWorkerClient['"]/);
  });
});

// ─── Controller owns required-cohesion items ────────────────────────────────

describe('MeshChat decomposition — controller required-cohesion', () => {
  const controller = readFile('useMeshChatController.ts');

  it('controller exports enqueueDmSend (high-privacy DM queueing)', () => {
    expect(controller).toMatch(/enqueueDmSend/);
    // Also in the return block
    expect(controller).toMatch(/return\s*\{[\s\S]*enqueueDmSend[\s\S]*\}/);
  });

  it('controller exports flushDmQueue (high-privacy DM queueing)', () => {
    expect(controller).toMatch(/flushDmQueue/);
    expect(controller).toMatch(/return\s*\{[\s\S]*flushDmQueue[\s\S]*\}/);
  });

  it('controller exports selectedGateAccessReady', () => {
    expect(controller).toMatch(/selectedGateAccessReady/);
    expect(controller).toMatch(/return\s*\{[\s\S]*selectedGateAccessReady[\s\S]*\}/);
  });

  it('controller exports selectedGateKeyStatus', () => {
    expect(controller).toMatch(/selectedGateKeyStatus/);
    expect(controller).toMatch(/return\s*\{[\s\S]*selectedGateKeyStatus[\s\S]*\}/);
  });

  it('controller exports native gate resync state and handler', () => {
    expect(controller).toMatch(/gateResyncTarget/);
    expect(controller).toMatch(/gateResyncBusy/);
    expect(controller).toMatch(/handleResyncGateState/);
    expect(controller).toMatch(/return\s*\{[\s\S]*gateResyncTarget[\s\S]*\}/);
    expect(controller).toMatch(/return\s*\{[\s\S]*gateResyncBusy[\s\S]*\}/);
    expect(controller).toMatch(/return\s*\{[\s\S]*handleResyncGateState[\s\S]*\}/);
  });

  it('controller exports secureDmBlocked', () => {
    expect(controller).toMatch(/secureDmBlocked/);
    expect(controller).toMatch(/return\s*\{[\s\S]*secureDmBlocked[\s\S]*\}/);
  });

  it('controller exports privacyProfile', () => {
    expect(controller).toMatch(/privacyProfile/);
    expect(controller).toMatch(/return\s*\{[\s\S]*privacyProfile[\s\S]*\}/);
  });

  it('controller exports hasId and hasPublicLaneIdentity', () => {
    expect(controller).toMatch(/return\s*\{[\s\S]*hasId[\s\S]*\}/);
    expect(controller).toMatch(/return\s*\{[\s\S]*hasPublicLaneIdentity[\s\S]*\}/);
  });

  it('controller exports publicMeshBlockedByWormhole', () => {
    expect(controller).toMatch(/return\s*\{[\s\S]*publicMeshBlockedByWormhole[\s\S]*\}/);
  });

  it('controller exports anonymousPublicBlocked and anonymousDmBlocked', () => {
    expect(controller).toMatch(/return\s*\{[\s\S]*anonymousPublicBlocked[\s\S]*\}/);
    expect(controller).toMatch(/return\s*\{[\s\S]*anonymousDmBlocked[\s\S]*\}/);
  });
});

// ─── Gate refresh is controller-owned (SSE removed in S3A) ────────────────

describe('MeshChat decomposition — gate refresh ownership', () => {
  it('controller does NOT import useGateSSE (removed in S3A)', () => {
    const controller = readFile('useMeshChatController.ts');
    expect(controller).not.toMatch(/import.*useGateSSE.*from/);
    expect(controller).not.toMatch(/useGateSSE\(/);
  });

  it('controller owns gate message polling via authenticated fetch', () => {
    const controller = readFile('useMeshChatController.ts');
    // The controller polls /api/mesh/infonet/messages for gate refresh
    expect(controller).toMatch(/\/api\/mesh\/infonet\/messages/);
    expect(controller).toMatch(/setInterval\(poll/);
  });

  it('useGateSSE is NOT imported in the presentational shell', () => {
    const index = readFile('index.tsx');
    expect(index).not.toMatch(/useGateSSE/);
  });
});

// ─── DM polling trust unit controller-owned ─────────────────────────────────

describe('MeshChat decomposition — DM poll sequence in controller', () => {
  const controller = readFile('useMeshChatController.ts');

  it('DM polling (pollDmMailboxes) is in the controller', () => {
    expect(controller).toMatch(/pollDmMailboxes/);
  });

  it('decryptDM is called in the controller (DM decrypt)', () => {
    expect(controller).toMatch(/decryptDM/);
  });

  it('ratchetDecryptDM is in the controller', () => {
    expect(controller).toMatch(/ratchetDecryptDM/);
  });

  it('sender seal decryption is in the controller via storage import', () => {
    expect(controller).toMatch(/decryptSenderSealForContact/);
  });

  it('contact mutation (addContact/updateContact) happens only in controller', () => {
    const index = readFile('index.tsx');
    // These should not appear as direct function calls in the view
    expect(index).not.toMatch(/\baddContact\s*\(/);
    expect(index).not.toMatch(/\bupdateContact\s*\(/);
    expect(index).not.toMatch(/\bblockContact\s*\(/);
  });
});

// ─── Identity persistence through meshIdentity.ts ───────────────────────────

describe('MeshChat decomposition — identity persistence', () => {
  it('controller imports identity functions from meshIdentity', () => {
    const controller = readFile('useMeshChatController.ts');
    expect(controller).toMatch(/from\s+['"]@\/mesh\/meshIdentity['"]/);
    expect(controller).toMatch(/getNodeIdentity/);
    expect(controller).toMatch(/generateNodeKeys/);
    expect(controller).toMatch(/signEvent/);
  });

  it('storage module imports from meshIdentity for seal operations', () => {
    const storage = readFile('storage.ts');
    expect(storage).toMatch(/from\s+['"]@\/mesh\/meshIdentity['"]/);
  });

  it('types module re-exports Contact and NodeIdentity from meshIdentity', () => {
    const types = readFile('types.ts');
    expect(types).toMatch(/Contact/);
    expect(types).toMatch(/NodeIdentity/);
  });
});

// ─── Re-export stability ────────────────────────────────────────────────────

describe('MeshChat decomposition — export stability', () => {
  it('MeshChat.tsx re-exports default from MeshChat/index', () => {
    const reExport = fs.readFileSync(
      path.resolve(MESH_CHAT_DIR, '../MeshChat.tsx'),
      'utf-8',
    );
    expect(reExport).toMatch(/export\s*\{\s*default\s*\}\s*from\s+['"]\.\/MeshChat\/index['"]/);
  });

  it('MeshChat.tsx re-exports MeshChatProps type', () => {
    const reExport = fs.readFileSync(
      path.resolve(MESH_CHAT_DIR, '../MeshChat.tsx'),
      'utf-8',
    );
    expect(reExport).toMatch(/export\s+type\s*\{\s*MeshChatProps\s*\}/);
  });

  it('index.tsx exports default MeshChat component', () => {
    const index = readFile('index.tsx');
    expect(index).toMatch(/export\s+default\s+MeshChat/);
  });

  it('presentational shell exposes the gate resync affordance', () => {
    const index = readFile('index.tsx');
    expect(index).toContain('RESYNC GATE STATE');
    expect(index).toContain('handleResyncGateState(selectedGate)');
  });
});
