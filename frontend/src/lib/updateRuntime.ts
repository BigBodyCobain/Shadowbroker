export type NativeDesktopUpdateMode = 'dev' | 'packaged';
export type DesktopPlatform = 'windows' | 'macos' | 'linux' | 'unknown';
export type UpdateRuntimeKind = 'browser' | 'desktop_dev' | 'desktop_packaged';
export type UpdateActionKind = 'auto_apply' | 'manual_download' | 'desktop_updater';

export interface DesktopUpdateContext {
  mode: NativeDesktopUpdateMode;
  platform: DesktopPlatform;
  is_packaged_build: boolean;
  backend_mode?: 'managed' | 'external';
  owns_local_backend?: boolean;
}

export interface GitHubReleaseAsset {
  name?: string;
  browser_download_url?: string;
  content_type?: string;
}

export interface GitHubLatestRelease {
  tag_name?: string;
  name?: string;
  html_url?: string;
  assets?: GitHubReleaseAsset[];
}

export interface DesktopUpdaterUpdateInfo {
  version: string;
  currentVersion: string;
  notes: string;
  date: string;
}

type TauriUpdate = {
  version?: string;
  currentVersion?: string;
  body?: string;
  date?: string;
  downloadAndInstall?: () => Promise<void>;
};

let pendingDesktopUpdate: TauriUpdate | null = null;

function getTauriInvoke(): ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>) | null {
  if (typeof window === 'undefined') return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tauri = (window as any).__TAURI__;
  return tauri?.core?.invoke ?? null;
}

export async function getDesktopUpdateContext(): Promise<DesktopUpdateContext | null> {
  const invoke = getTauriInvoke();
  if (!invoke) return null;
  try {
    return (await invoke('desktop_update_context')) as DesktopUpdateContext;
  } catch {
    return null;
  }
}

export function classifyUpdateRuntime(
  context: DesktopUpdateContext | null,
): UpdateRuntimeKind {
  if (!context) return 'browser';
  return context.mode === 'packaged' ? 'desktop_packaged' : 'desktop_dev';
}

export function getUpdateAction(runtime: UpdateRuntimeKind): UpdateActionKind {
  return runtime === 'desktop_packaged' ? 'manual_download' : 'auto_apply';
}

async function loadTauriUpdater(): Promise<{
  check?: () => Promise<TauriUpdate | null>;
} | null> {
  if (typeof window === 'undefined') return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if (!(window as any).__TAURI__) return null;
  try {
    return (await import('@tauri-apps/plugin-updater')) as {
      check?: () => Promise<TauriUpdate | null>;
    };
  } catch {
    return null;
  }
}

export async function checkDesktopUpdaterUpdate(): Promise<DesktopUpdaterUpdateInfo | null> {
  const updater = await loadTauriUpdater();
  if (!updater?.check) return null;
  const update = await updater.check();
  if (!update) {
    pendingDesktopUpdate = null;
    return null;
  }
  pendingDesktopUpdate = update;
  return {
    version: String(update.version || ''),
    currentVersion: String(update.currentVersion || ''),
    notes: String(update.body || ''),
    date: String(update.date || ''),
  };
}

export async function installDesktopUpdaterUpdate(): Promise<void> {
  let update = pendingDesktopUpdate;
  if (!update) {
    const updater = await loadTauriUpdater();
    update = updater?.check ? await updater.check() : null;
    pendingDesktopUpdate = update;
  }
  if (!update?.downloadAndInstall) {
    throw new Error('desktop_updater_no_update_available');
  }

  await update.downloadAndInstall();
  try {
    const process = (await import('@tauri-apps/plugin-process')) as {
      relaunch?: () => Promise<void>;
    };
    await process.relaunch?.();
  } catch {
    throw new Error('desktop_update_installed_restart_required');
  }
}

function normalizeAssetUrl(asset: GitHubReleaseAsset): string {
  return String(asset.browser_download_url || '').trim();
}

function findAssetUrl(release: GitHubLatestRelease, matchers: RegExp[]): string | null {
  const assets = Array.isArray(release.assets) ? release.assets : [];
  for (const matcher of matchers) {
    const asset = assets.find((entry) => matcher.test(String(entry.name || '')));
    const url = asset ? normalizeAssetUrl(asset) : '';
    if (url) return url;
  }
  return null;
}

export function pickDesktopInstallerUrl(
  release: GitHubLatestRelease,
  platform: DesktopPlatform,
): string | null {
  if (platform === 'windows') {
    return findAssetUrl(release, [/\.msi$/i, /setup\.exe$/i, /\.exe$/i]);
  }
  if (platform === 'macos') {
    return findAssetUrl(release, [/\.dmg$/i, /\.app\.tar\.gz$/i, /\.pkg$/i]);
  }
  if (platform === 'linux') {
    return findAssetUrl(release, [/\.AppImage$/i, /\.deb$/i, /\.rpm$/i]);
  }
  return null;
}

export function getPreferredManualUpdateUrl(
  release: GitHubLatestRelease,
  runtime: UpdateRuntimeKind,
  platform: DesktopPlatform,
): string {
  const releaseUrl =
    typeof release.html_url === 'string' && release.html_url.trim().length > 0
      ? release.html_url
      : 'https://github.com/BigBodyCobain/Shadowbroker/releases/latest';
  if (runtime !== 'desktop_packaged') return releaseUrl;
  return pickDesktopInstallerUrl(release, platform) || releaseUrl;
}
