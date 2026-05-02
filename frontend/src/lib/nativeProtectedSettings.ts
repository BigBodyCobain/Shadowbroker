/**
 * Native desktop protected-settings readiness detection.
 *
 * In the native Tauri desktop window, protected settings requests (api-keys,
 * news-feeds, wormhole, privacy) are handled through the Rust IPC control
 * boundary, which owns the admin key natively. The browser admin-session
 * cookie flow (`/api/admin/session`) is unnecessary and unavailable in
 * packaged mode — the loopback server intentionally does not implement it.
 *
 * This helper detects when the native bridge can handle protected settings
 * so the UI can bypass browser admin-session gating and treat those surfaces
 * as immediately available.
 *
 * Returns false in browser mode and browser companion mode, preserving the
 * existing admin-session gating for those environments.
 */

import { hasLocalControlBridge } from '@/lib/localControlTransport';

/**
 * Returns `true` when the native desktop control bridge is present and can
 * handle protected settings requests through Rust IPC with native admin-key
 * ownership.
 *
 * When this returns `true`, browser admin-session gating (`/api/admin/session`)
 * should be bypassed for settings surfaces that are already mapped to native
 * IPC commands (api-keys, news-feeds, wormhole, privacy, system update).
 */
export function isNativeProtectedSettingsReady(): boolean {
  return hasLocalControlBridge();
}
