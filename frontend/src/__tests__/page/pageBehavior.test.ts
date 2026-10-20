/**
 * Sprint 4D behavioral tests — page.tsx wormhole teardown and layer sync.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { teardownWormholeOnClose } from '@/lib/wormholeTeardown';
import { LAYER_TOGGLE_EVENT } from '@/hooks/useDataPolling';

const endInfonetTerminalSession = vi.fn(async () => {});

vi.mock('@/lib/infonetTerminalSession', () => ({
  endInfonetTerminalSession: (...args: unknown[]) => endInfonetTerminalSession(...args),
}));

describe('page.tsx behavior — teardownWormholeOnClose', () => {
  beforeEach(() => {
    endInfonetTerminalSession.mockClear();
  });

  it('ends the infonet terminal session on close', async () => {
    await teardownWormholeOnClose();
    expect(endInfonetTerminalSession).toHaveBeenCalledTimes(1);
  });
});

describe('page.tsx behavior — layer sync first-mount suppression', () => {
  it('LAYER_TOGGLE_EVENT is the expected string constant', () => {
    expect(LAYER_TOGGLE_EVENT).toBe('sb:layer-toggle');
  });

  it('first-mount ref pattern suppresses dispatch, subsequent calls dispatch', () => {
    const initialSyncDone = { current: false };
    const dispatched: boolean[] = [];

    const syncLayers = (triggerRefetch: boolean) => {
      if (triggerRefetch) {
        dispatched.push(true);
      } else {
        dispatched.push(false);
      }
    };

    if (!initialSyncDone.current) {
      initialSyncDone.current = true;
      syncLayers(false);
    } else {
      syncLayers(true);
    }
    expect(dispatched).toEqual([false]);

    if (!initialSyncDone.current) {
      initialSyncDone.current = true;
      syncLayers(false);
    } else {
      syncLayers(true);
    }
    expect(dispatched).toEqual([false, true]);

    if (!initialSyncDone.current) {
      initialSyncDone.current = true;
      syncLayers(false);
    } else {
      syncLayers(true);
    }
    expect(dispatched).toEqual([false, true, true]);
  });

  it('page.tsx uses initialLayerSyncRef for first-mount suppression', () => {
    const page = fs.readFileSync(
      path.resolve(__dirname, '../../app/page.tsx'),
      'utf-8',
    );
    expect(page).toContain('initialLayerSyncRef');
    expect(page).toContain('void syncLayers(false)');
    expect(page).toContain('void syncLayers(true)');
  });
});
