/**
 * Public viewer stand-in. The full app's version of this file talks to the
 * owner's server; the viewer has no server, so this one does nothing and
 * the original code is not part of the public build.
 */

type LoadingListener = (inflight: number, loaded: number) => void;

export async function checkBackendSentinelStatus(): Promise<boolean> {
  return false;
}

export function hasSentinelCredentials(): boolean {
  return false;
}

export function getSentinelToken(): Promise<string | null> {
  return Promise.resolve(null);
}

export function registerSentinelProtocol(_maplibregl: unknown): void {}

export function buildSentinelTileUrl(_preset: string, _date: string): string {
  return '';
}

export function onTileLoadingChange(_cb: LoadingListener): () => void {
  return () => {};
}

export function resetTileLoading(): void {}

export function hasSentinelInfoBeenSeen(): boolean {
  return true;
}

export function markSentinelInfoSeen(): void {}
