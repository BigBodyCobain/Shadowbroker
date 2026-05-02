import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { isDmPollBlocked, isGateSendBlocked, shouldQueueDmSend } from '@/lib/meshChatPolicies';

function readSource(relativePath: string): string {
  const here = path.dirname(fileURLToPath(import.meta.url));
  return fs.readFileSync(path.resolve(here, relativePath), 'utf-8');
}

describe('MeshChat behavior - shouldQueueDmSend', () => {
  it('returns false for default privacy profile', () => {
    expect(shouldQueueDmSend('default')).toBe(false);
  });

  it('returns true for high privacy profile', () => {
    expect(shouldQueueDmSend('high')).toBe(true);
  });
});

describe('MeshChat behavior - isGateSendBlocked', () => {
  it('blocks when on infonet tab with gate selected but access not ready', () => {
    expect(isGateSendBlocked('infonet', true, false)).toBe(true);
  });

  it('does not block when gate access is ready', () => {
    expect(isGateSendBlocked('infonet', true, true)).toBe(false);
  });

  it('does not block when no gate is selected', () => {
    expect(isGateSendBlocked('infonet', false, false)).toBe(false);
  });

  it('does not block on non-infonet tabs', () => {
    expect(isGateSendBlocked('dms', true, false)).toBe(false);
    expect(isGateSendBlocked('meshtastic', true, false)).toBe(false);
    expect(isGateSendBlocked('mesh', true, false)).toBe(false);
  });

  it('does not block when all conditions are false', () => {
    expect(isGateSendBlocked('dms', false, true)).toBe(false);
  });
});

describe('MeshChat behavior - isDmPollBlocked', () => {
  it('blocks when wormhole is enabled but not ready', () => {
    expect(isDmPollBlocked(true, false, false)).toBe(true);
  });

  it('blocks when anonymous DM is blocked', () => {
    expect(isDmPollBlocked(false, false, true)).toBe(true);
  });

  it('blocks when both wormhole not ready and anonymous blocked', () => {
    expect(isDmPollBlocked(true, false, true)).toBe(true);
  });

  it('does not block when wormhole is ready and anonymous is not blocked', () => {
    expect(isDmPollBlocked(true, true, false)).toBe(false);
  });

  it('does not block when wormhole is disabled and anonymous is not blocked', () => {
    expect(isDmPollBlocked(false, false, false)).toBe(false);
  });

  it('does not block when wormhole is disabled and ready', () => {
    expect(isDmPollBlocked(false, true, false)).toBe(false);
  });
});

describe('MeshChat behavior - policy wiring', () => {
  it('controller imports all three policy functions from meshChatPolicies', () => {
    const controller = readSource('../../components/MeshChat/useMeshChatController.ts');
    expect(controller).toMatch(
      /import\s*\{[^}]*shouldQueueDmSend[^}]*\}\s*from\s+['"]@\/lib\/meshChatPolicies['"]/,
    );
    expect(controller).toMatch(
      /import\s*\{[^}]*isGateSendBlocked[^}]*\}\s*from\s+['"]@\/lib\/meshChatPolicies['"]/,
    );
    expect(controller).toMatch(
      /import\s*\{[^}]*isDmPollBlocked[^}]*\}\s*from\s+['"]@\/lib\/meshChatPolicies['"]/,
    );
  });

  it('controller calls shouldQueueDmSend in enqueueDmSend', () => {
    const controller = readSource('../../components/MeshChat/useMeshChatController.ts');
    expect(controller).toContain('shouldQueueDmSend(privacyProfile)');
  });

  it('controller calls isGateSendBlocked in handleSend', () => {
    const controller = readSource('../../components/MeshChat/useMeshChatController.ts');
    expect(controller).toContain('isGateSendBlocked(');
  });

  it('controller calls isDmPollBlocked in DM poll effects', () => {
    const controller = readSource('../../components/MeshChat/useMeshChatController.ts');
    expect(controller).toContain(
      'isDmPollBlocked(wormholeEnabled, wormholeReadyState, anonymousDmBlocked)',
    );
  });

  it('controller suppresses unread-count polling while the DMS tab owns mailbox refresh', () => {
    const controller = readSource('../../components/MeshChat/useMeshChatController.ts');
    expect(controller).toContain("if (!hasId || !getDMNotify() || (expanded && activeTab === 'dms')) return;");
    expect(controller).toContain("jitteredPollDelay(baseDelay, { profile: privacyProfile })");
  });

  it('controller uses the shared DM poll scheduler for live mailbox refresh cadence', () => {
    const controller = readSource('../../components/MeshChat/useMeshChatController.ts');
    expect(controller).toContain('classifyTick(hasMore, catchUpBudget, DM_MESSAGES_POLL_MS');
    expect(controller).toContain('timer = setTimeout(() => void poll(classification.refreshCount), classification.delay);');
  });

  it('dead-drop UI distinguishes invite-pinned trust from TOFU-only', () => {
    const index = readSource('../../components/MeshChat/index.tsx');
    expect(index).toContain('getContactTrustSummary');
    expect(index).toContain('INVITE PINNED');
    expect(index).toContain('TOFU ONLY');
    expect(index).toContain('anchored by an imported signed invite');
    expect(index).toContain('rootWitnessContinuityLabel');
    expect(index).toContain('RECOVER ROOT');
    expect(index).toContain('!selectedContactTrustSummary?.rootMismatch');
  });

  it('request UI does not route ordinary request flow through legacy add-contact lookup', () => {
    const index = readSource('../../components/MeshChat/index.tsx');
    expect(index).toContain('handleRequestComposerAction');
    expect(index).not.toContain('handleAddContact().catch(() =>');
    expect(index).toContain('dm add');
    expect(index).toContain('legacy migration');
  });

  it('controller blocks trust-new-key when the stable root changed', () => {
    const controller = readSource('../../components/MeshChat/useMeshChatController.ts');
    expect(controller).toContain('contactInfo?.remotePrekeyRootMismatch');
    expect(controller).toContain('stable root changed; use RECOVER ROOT or replace the signed invite');
  });
});
