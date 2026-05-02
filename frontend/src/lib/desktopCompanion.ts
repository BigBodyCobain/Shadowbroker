/**
 * Desktop companion mode helpers.
 *
 * Wraps the Tauri companion commands behind a clean async API.
 * Returns `null` from all functions when the native Tauri runtime is not
 * available (i.e. running in a normal browser), so callers can gate UI
 * visibility without try/catch.
 */

export interface CompanionStatus {
  enabled: boolean;
  url: string | null;
  warning: string;
}

// ---------------------------------------------------------------------------
// Runtime detection
// ---------------------------------------------------------------------------

function getTauriInvoke(): ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>) | null {
  if (typeof window === 'undefined') return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tauri = (window as any).__TAURI__;
  return tauri?.core?.invoke ?? null;
}

/** Returns `true` when running inside the Tauri native desktop shell. */
export function isNativeDesktop(): boolean {
  return getTauriInvoke() !== null;
}

// ---------------------------------------------------------------------------
// Companion commands
// ---------------------------------------------------------------------------

/** Query current companion status. Returns `null` if not in desktop mode. */
export async function companionStatus(): Promise<CompanionStatus | null> {
  const invoke = getTauriInvoke();
  if (!invoke) return null;
  return (await invoke('companion_status')) as CompanionStatus;
}

/** Enable companion mode. Returns updated status, or `null` if not in desktop mode. */
export async function companionEnable(): Promise<CompanionStatus | null> {
  const invoke = getTauriInvoke();
  if (!invoke) return null;
  return (await invoke('companion_enable')) as CompanionStatus;
}

/** Disable companion mode. Returns updated status, or `null` if not in desktop mode. */
export async function companionDisable(): Promise<CompanionStatus | null> {
  const invoke = getTauriInvoke();
  if (!invoke) return null;
  return (await invoke('companion_disable')) as CompanionStatus;
}

/** Open the companion URL in the system browser. Only works when enabled. */
export async function companionOpenBrowser(): Promise<CompanionStatus | null> {
  const invoke = getTauriInvoke();
  if (!invoke) return null;
  return (await invoke('companion_open_browser')) as CompanionStatus;
}
