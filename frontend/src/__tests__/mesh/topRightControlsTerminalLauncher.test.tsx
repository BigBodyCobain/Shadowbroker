import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const deferred = <T,>() => {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

const fetchWormholeStatus = vi.fn(async () => ({
  ready: false,
  running: false,
  transport_tier: 'public_degraded',
  transport_active: 'public_degraded',
}));
const prepareWormholeInteractiveLane = vi.fn();
const fetchWormholeSettings = vi.fn(async () => ({
  enabled: false,
  anonymous_mode: false,
}));
const purgeBrowserContactGraph = vi.fn();
const purgeBrowserSigningMaterial = vi.fn();
const setSecureModeCached = vi.fn();
const getNodeIdentity = vi.fn(() => null);
const generateNodeKeys = vi.fn(async () => ({}));
const purgeBrowserDmState = vi.fn(async () => {});
const fetchInfonetNodeStatusSnapshot = vi.fn(async () => ({
  enabled: false,
  peers_ready: false,
  identity_ready: false,
}));
const requestMeshTerminalOpen = vi.fn();
const subscribeSecureMeshTerminalLauncherOpen = vi.fn(() => () => {});
const classifyUpdateRuntime = vi.fn(() => ({
  action: 'auto_apply',
  detail: 'test',
}));
const getDesktopUpdateContext = vi.fn(() => ({
  packaged: false,
  ownsLocalBackend: false,
}));
const getPreferredManualUpdateUrl = vi.fn(() => 'https://example.test/releases/latest');
const getUpdateAction = vi.fn(() => 'auto_apply');
const controlPlaneFetch = vi.fn();

vi.mock('@/mesh/wormholeIdentityClient', () => ({
  fetchWormholeStatus,
  prepareWormholeInteractiveLane,
}));

vi.mock('@/mesh/wormholeClient', () => ({
  fetchWormholeSettings,
}));

vi.mock('@/mesh/meshIdentity', () => ({
  purgeBrowserContactGraph,
  purgeBrowserSigningMaterial,
  setSecureModeCached,
  getNodeIdentity,
  generateNodeKeys,
}));

vi.mock('@/mesh/meshDmWorkerClient', () => ({
  purgeBrowserDmState,
}));

vi.mock('@/mesh/controlPlaneStatusClient', () => ({
  fetchInfonetNodeStatusSnapshot,
}));

vi.mock('@/lib/meshTerminalLauncher', () => ({
  requestMeshTerminalOpen,
  subscribeSecureMeshTerminalLauncherOpen,
}));

vi.mock('@/lib/updateRuntime', () => ({
  classifyUpdateRuntime,
  getDesktopUpdateContext,
  getPreferredManualUpdateUrl,
  getUpdateAction,
}));

vi.mock('@/lib/controlPlane', () => ({
  controlPlaneFetch,
}));

describe('TopRightControls terminal launcher', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchWormholeStatus.mockResolvedValue({
      ready: false,
      running: false,
      transport_tier: 'public_degraded',
      transport_active: 'public_degraded',
    });
    fetchWormholeSettings.mockResolvedValue({
      enabled: false,
      anonymous_mode: false,
    });
    fetchInfonetNodeStatusSnapshot.mockResolvedValue({
      enabled: false,
      peers_ready: false,
      identity_ready: false,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('opens the terminal immediately while Wormhole prep continues in the background', async () => {
    const prep = deferred<{
      ready: boolean;
      settingsEnabled: boolean;
      transportTier: string;
      identity: null;
    }>();
    prepareWormholeInteractiveLane.mockReturnValue(prep.promise);

    const { default: TopRightControls } = await import('@/components/TopRightControls');
    const onTerminalToggle = vi.fn();

    render(<TopRightControls onTerminalToggle={onTerminalToggle} />);

    fireEvent.click(await screen.findByRole('button', { name: /terminal/i }));
    expect(await screen.findByRole('button', { name: /activate wormhole/i })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /activate wormhole/i }));

    await waitFor(() => expect(onTerminalToggle).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /activate wormhole/i })).toBeNull(),
    );
    expect(prepareWormholeInteractiveLane).toHaveBeenCalledWith({ bootstrapIdentity: true });

    prep.resolve({
      ready: true,
      settingsEnabled: true,
      transportTier: 'private_control_only',
      identity: null,
    });
  });
});
