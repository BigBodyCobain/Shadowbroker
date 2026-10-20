/**
 * Infonet terminal session lifecycle.
 * Wormhole, Tor, and participant-node sync should only run while the terminal is open.
 */
import {
  fetchNodeSettingsSnapshot,
  setInfonetNodeEnabled,
  startTorHiddenService,
  stopTorHiddenService,
  joinInfonetSwarm,
  fetchInfonetNodeStatusSnapshot,
} from '@/mesh/controlPlaneStatusClient';
import { generateNodeKeys, getNodeIdentity, setSecureModeCached } from '@/mesh/meshIdentity';
import { fetchWormholeSettings, leaveWormhole, fetchWormholeState } from '@/mesh/wormholeClient';
import {
  abortWormholeInteractivePrep,
  isWormholePrepAbortedError,
} from '@/mesh/wormholeIdentityClient';
import { notifyInfonetSessionEnd } from '@/lib/meshTerminalLauncher';

let nodeWasEnabledBeforeSession = false;
let sessionEndInFlight: Promise<void> | null = null;

export async function beginInfonetTerminalSession(): Promise<void> {
  try {
    const before = await fetchNodeSettingsSnapshot().catch(() => null);
    nodeWasEnabledBeforeSession = Boolean(before?.enabled);
    if (!getNodeIdentity()) {
      await generateNodeKeys().catch(() => null);
    }
    await startTorHiddenService().catch(() => null);
    if (!nodeWasEnabledBeforeSession) {
      await setInfonetNodeEnabled(true);
    }
    await joinInfonetSwarm().catch(() => null);
    await fetchInfonetNodeStatusSnapshot(true).catch(() => null);
  } catch {
    // Remote viewers may not have local-operator rights.
  }
}

export async function endInfonetTerminalSession(): Promise<void> {
  if (sessionEndInFlight) {
    return sessionEndInFlight;
  }
  sessionEndInFlight = (async () => {
    abortWormholeInteractivePrep();
    try {
      const [settings, state] = await Promise.all([
        fetchWormholeSettings(false).catch(() => null),
        fetchWormholeState(false).catch(() => null),
      ]);
      const wormholeActive = Boolean(
        settings?.enabled
        || state?.configured
        || state?.running
        || state?.ready,
      );
      if (wormholeActive) {
        await leaveWormhole().catch(() => null);
      }
      if (!nodeWasEnabledBeforeSession) {
        await setInfonetNodeEnabled(false).catch(() => null);
      }
      await stopTorHiddenService().catch(() => null);
      setSecureModeCached(false);
      nodeWasEnabledBeforeSession = false;
    } catch {
      /* best-effort teardown */
    } finally {
      notifyInfonetSessionEnd();
    }
  })();
  try {
    await sessionEndInFlight;
  } finally {
    sessionEndInFlight = null;
  }
}

export { isWormholePrepAbortedError };
