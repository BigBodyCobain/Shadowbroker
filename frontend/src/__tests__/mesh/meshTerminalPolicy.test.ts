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

  it('keeps read-only terminal commands available', () => {
    expect(isMeshTerminalWriteCommand('status', [])).toBe(false);
    expect(isMeshTerminalWriteCommand('signals', ['10'])).toBe(false);
    expect(isMeshTerminalWriteCommand('mesh', ['listen', '20'])).toBe(false);
    expect(isMeshTerminalWriteCommand('messages', [])).toBe(false);
  });
});
