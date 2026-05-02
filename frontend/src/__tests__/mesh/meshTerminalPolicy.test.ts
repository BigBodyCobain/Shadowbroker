import * as fs from 'node:fs';
import * as path from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  getMeshTerminalWriteLockReason,
  isMeshTerminalWriteCommand,
} from '@/lib/meshTerminalPolicy';

describe('mesh terminal policy', () => {
  it('blocks sensitive terminal writes while anonymous mode is active', () => {
    const reason = getMeshTerminalWriteLockReason({
      wormholeRequired: true,
      wormholeReady: true,
      anonymousMode: true,
      anonymousModeReady: true,
    });

    expect(reason).toContain('Anonymous Infonet mode');
    expect(isMeshTerminalWriteCommand('dm', ['add', '!sb_test'])).toBe(true);
    expect(isMeshTerminalWriteCommand('mesh', ['send', 'hello'])).toBe(true);
  });

  it('blocks sensitive terminal writes until Wormhole secure mode is ready', () => {
    const reason = getMeshTerminalWriteLockReason({
      wormholeRequired: true,
      wormholeReady: false,
      anonymousMode: false,
      anonymousModeReady: false,
    });

    expect(reason).toContain('until Wormhole secure mode is ready');
    expect(isMeshTerminalWriteCommand('gate', ['create', 'newsroom'])).toBe(true);
    expect(isMeshTerminalWriteCommand('send', ['broadcast', 'hello'])).toBe(true);
  });

  it('wormhole active lock reason distinguishes gate and DM posture', () => {
    const reason = getMeshTerminalWriteLockReason({
      wormholeRequired: true,
      wormholeReady: true,
      anonymousMode: false,
      anonymousModeReady: false,
    });

    // Must mention gate as transitional lane
    expect(reason).toContain('gate chat (transitional lane)');
    // Must mention Dead Drop as the stronger lane
    expect(reason).toContain('Dead Drop (stronger private lane)');
    // Must NOT use "hardened private actions" which flattens both
    expect(reason).not.toContain('hardened private actions');
  });

  it('anonymous mode lock reason distinguishes gate and DM posture', () => {
    const reason = getMeshTerminalWriteLockReason({
      wormholeRequired: true,
      wormholeReady: true,
      anonymousMode: true,
      anonymousModeReady: true,
    });

    expect(reason).toContain('gate chat (transitional lane)');
    expect(reason).toContain('Dead Drop (stronger private lane)');
    expect(reason).not.toContain('hardened');
  });

  it('keeps read-only terminal commands available', () => {
    expect(isMeshTerminalWriteCommand('status', [])).toBe(false);
    expect(isMeshTerminalWriteCommand('signals', ['10'])).toBe(false);
    expect(isMeshTerminalWriteCommand('mesh', ['listen', '20'])).toBe(false);
    expect(isMeshTerminalWriteCommand('messages', [])).toBe(false);
  });

  it('MeshTerminal does not use raw agent-id fetch as the ordinary DM send path', () => {
    const terminal = fs.readFileSync(
      path.resolve(__dirname, '../../components/MeshTerminal.tsx'),
      'utf-8',
    );
    expect(terminal).toContain('fetchDmPublicKey');
    expect(terminal).toContain("only for legacy migration");
    expect(terminal).not.toContain('/api/mesh/dm/pubkey?agent_id=');
  });

  it('MeshTerminal inbox surface owns mailbox refresh instead of racing the unread poll loop', () => {
    const terminal = fs.readFileSync(
      path.resolve(__dirname, '../../components/MeshTerminal.tsx'),
      'utf-8',
    );
    expect(terminal).toContain("if (!isOpen || !nodeIdentity || !hasSovereignty() || !getDMNotify() || surfacePanel === 'inbox') return;");
    expect(terminal).toContain('classifyTick(hasMore, catchUpBudget, 15_000)');
    expect(terminal).toContain('() => void loadInboxSurface(classification.refreshCount)');
  });
});
