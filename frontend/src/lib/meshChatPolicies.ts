/**
 * Pure policy predicates extracted from MeshChat controller logic.
 * Used by useMeshChatController and tested independently.
 */

/** Returns true when DM sends should be queued (delayed) rather than fired immediately. */
export function shouldQueueDmSend(privacyProfile: 'default' | 'high'): boolean {
  return privacyProfile === 'high';
}

/** Returns true when gate send should be blocked because access is still syncing. */
export function isGateSendBlocked(
  activeTab: string,
  hasSelectedGate: boolean,
  selectedGateAccessReady: boolean,
): boolean {
  return activeTab === 'infonet' && hasSelectedGate && !selectedGateAccessReady;
}

/** Returns true when DM polling should skip real fetches (wormhole not ready or anonymous blocked). */
export function isDmPollBlocked(
  wormholeEnabled: boolean,
  wormholeReadyState: boolean,
  anonymousDmBlocked: boolean,
): boolean {
  return (wormholeEnabled && !wormholeReadyState) || anonymousDmBlocked;
}
