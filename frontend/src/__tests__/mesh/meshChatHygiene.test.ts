/**
 * Phase 6A: Residual Backlog & Hygiene Closeout tests.
 *
 * Validates:
 * 1. DECOY_KEY removal from types.ts causes no import/runtime regression
 * 2. build_controller.py and build_index.py are deleted
 * 3. promotePendingAlias no longer calls updateContact from storage.ts
 * 4. Alias-promotion behavior unchanged after controller applies returned delta
 */
import { describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

const MESH_CHAT_DIR = path.resolve(__dirname, '../../components/MeshChat');

function readFile(name: string): string {
  return fs.readFileSync(path.join(MESH_CHAT_DIR, name), 'utf-8');
}

function fileExists(name: string): boolean {
  return fs.existsSync(path.join(MESH_CHAT_DIR, name));
}

// ---------------------------------------------------------------------------
// 1. DECOY_KEY removal causes no import/runtime regression
// ---------------------------------------------------------------------------

describe('DECOY_KEY deduplication', () => {
  it('types.ts does NOT export DECOY_KEY', () => {
    const types = readFile('types.ts');
    expect(types).not.toMatch(/export\s+(const|let|var)\s+DECOY_KEY/);
  });

  it('storage.ts still exports DECOY_KEY as canonical location', () => {
    const storage = readFile('storage.ts');
    expect(storage).toMatch(/export\s+const\s+DECOY_KEY/);
  });

  it('DECOY_KEY is importable from storage at runtime', async () => {
    const { DECOY_KEY } = await import('../../components/MeshChat/storage');
    expect(DECOY_KEY).toBe('sb_dm_decoy');
  });

  it('no file imports DECOY_KEY from types', () => {
    const files = fs.readdirSync(MESH_CHAT_DIR).filter((f) => f.endsWith('.ts') || f.endsWith('.tsx'));
    for (const file of files) {
      const content = readFile(file);
      const importFromTypes = content.match(/import\s*\{[^}]*DECOY_KEY[^}]*\}\s*from\s*['"]\.\/types['"]/);
      expect(importFromTypes, `${file} should not import DECOY_KEY from types`).toBeNull();
    }
  });
});

// ---------------------------------------------------------------------------
// 2. build_controller.py and build_index.py are deleted
// ---------------------------------------------------------------------------

describe('stale generator scripts removed', () => {
  it('build_controller.py does not exist', () => {
    expect(fileExists('build_controller.py')).toBe(false);
  });

  it('build_index.py does not exist', () => {
    expect(fileExists('build_index.py')).toBe(false);
  });

  it('no build/test config references build_controller.py or build_index.py', () => {
    const packageJson = fs.readFileSync(
      path.resolve(MESH_CHAT_DIR, '../../../package.json'),
      'utf-8',
    );
    expect(packageJson).not.toContain('build_controller.py');
    expect(packageJson).not.toContain('build_index.py');
  });
});

// ---------------------------------------------------------------------------
// 3. promotePendingAlias no longer calls updateContact from storage.ts
// ---------------------------------------------------------------------------

describe('promotePendingAlias decoupled from updateContact', () => {
  it('storage.ts does not import updateContact', () => {
    const storage = readFile('storage.ts');
    expect(storage).not.toMatch(/import\s*\{[^}]*updateContact[^}]*\}\s*from/);
  });

  it('storage.ts does not import getContacts', () => {
    const storage = readFile('storage.ts');
    expect(storage).not.toMatch(/import\s*\{[^}]*getContacts[^}]*\}\s*from/);
  });

  it('promotePendingAlias does not call updateContact', () => {
    const storage = readFile('storage.ts');
    // Extract the promotePendingAlias function body
    const fnStart = storage.indexOf('export function promotePendingAlias');
    expect(fnStart).toBeGreaterThan(-1);
    const fnBody = storage.slice(fnStart, storage.indexOf('\n}', fnStart) + 2);
    expect(fnBody).not.toContain('updateContact(');
  });

  it('promotePendingAlias does not call getContacts', () => {
    const storage = readFile('storage.ts');
    const fnStart = storage.indexOf('export function promotePendingAlias');
    const fnBody = storage.slice(fnStart, storage.indexOf('\n}', fnStart) + 2);
    expect(fnBody).not.toContain('getContacts(');
  });

  it('controller call sites apply updateContact after promotePendingAlias', () => {
    const controller = readFile('useMeshChatController.ts');
    // Both call sites should follow pattern: promotePendingAlias → updateContact
    const promotionCalls = controller.match(/const promotion = promotePendingAlias\(/g);
    expect(promotionCalls?.length).toBeGreaterThanOrEqual(2);
    const updateAfterPromotion = controller.match(
      /if \(promotion\) updateContact\([^,]+, promotion\.delta\.updates\)/g,
    );
    expect(updateAfterPromotion?.length).toBeGreaterThanOrEqual(2);
  });
});

// ---------------------------------------------------------------------------
// 4. Alias-promotion behavior unchanged (delta structure)
// ---------------------------------------------------------------------------

describe('alias-promotion delta correctness', () => {
  it('returns null when contact has no pendingSharedAlias', async () => {
    const { promotePendingAlias } = await import('../../components/MeshChat/storage');
    const contact = { sharedAlias: 'abc' } as any;
    const result = promotePendingAlias('test-id', contact);
    expect(result).toBeNull();
  });

  it('returns null when grace period has not expired', async () => {
    const { promotePendingAlias } = await import('../../components/MeshChat/storage');
    const contact = {
      pendingSharedAlias: 'new-alias',
      sharedAlias: 'old-alias',
      sharedAliasGraceUntil: Date.now() + 60_000,
    } as any;
    const result = promotePendingAlias('test-id', contact);
    expect(result).toBeNull();
  });

  it('returns delta with promoted contact when grace period expired', async () => {
    const { promotePendingAlias } = await import('../../components/MeshChat/storage');
    const contact = {
      pendingSharedAlias: 'new-alias',
      sharedAlias: 'old-alias',
      sharedAliasGraceUntil: Date.now() - 1000,
      previousSharedAliases: [],
    } as any;
    const result = promotePendingAlias('test-id', contact);
    expect(result).not.toBeNull();
    expect(result!.delta.updates.sharedAlias).toBe('new-alias');
    expect(result!.delta.updates.pendingSharedAlias).toBeUndefined();
    expect(result!.delta.updates.sharedAliasGraceUntil).toBeUndefined();
    expect(result!.delta.updates.sharedAliasRotatedAt).toBeGreaterThan(0);
    expect(result!.delta.updates.previousSharedAliases).toContain('old-alias');
    expect(result!.promoted.sharedAlias).toBe('new-alias');
    expect(result!.promoted.pendingSharedAlias).toBeUndefined();
  });

  it('promoted contact merges updates onto original contact', async () => {
    const { promotePendingAlias } = await import('../../components/MeshChat/storage');
    const contact = {
      dhPubKey: 'some-key',
      pendingSharedAlias: 'next',
      sharedAlias: 'current',
      sharedAliasGraceUntil: 0,
      previousSharedAliases: ['older'],
    } as any;
    const result = promotePendingAlias('test-id', contact);
    expect(result).not.toBeNull();
    // Original fields preserved
    expect(result!.promoted.dhPubKey).toBe('some-key');
    // Alias history includes both old aliases
    expect(result!.promoted.previousSharedAliases).toContain('current');
    expect(result!.promoted.previousSharedAliases).toContain('older');
  });
});
