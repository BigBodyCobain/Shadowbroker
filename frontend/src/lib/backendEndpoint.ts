/**
 * Runtime-resolved backend API endpoint for display and external-tool
 * configuration (e.g. "Connect OpenClaw" modals).
 *
 * All frontend modes (dev browser, packaged desktop, browser companion)
 * proxy `/api/*` through the current origin. External tools should connect
 * to `getBackendEndpoint()` + `/api/...` paths — the same origin the user
 * is viewing the app from.
 *
 * This replaces the previous hardcoded `${window.location.hostname}:8000`
 * pattern, which assumed the raw backend was always on port 8000 on the
 * same host. That assumption breaks in packaged desktop mode where the
 * page is served from a random loopback port.
 */

/**
 * Returns the user-visible API base URL for external tools.
 *
 * - Browser dev mode: `http://localhost:3000`
 * - Packaged desktop: `http://127.0.0.1:<loopback-port>`
 * - Browser companion: `http://127.0.0.1:<loopback-port>`
 *
 * All of these proxy `/api/*` to the backend.
 */
export function getBackendEndpoint(): string {
  if (typeof window === 'undefined') return 'http://localhost:8000';
  return window.location.origin;
}
