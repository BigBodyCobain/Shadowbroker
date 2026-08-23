/**
 * Public ShadowBroker is a read-only research surface.  Operator endpoints
 * stay behind the local control boundary, so the public browser must not poll
 * or mutate them before an authenticated local session exists.
 */
const PUBLIC_READ_ONLY_HOSTS = new Set(['shadow.qdev.run']);
const PUBLIC_READ_ONLY_ENV = process.env.NEXT_PUBLIC_PUBLIC_READ_ONLY === 'true';

export function isPublicReadOnlyHost(hostname: string): boolean {
  return PUBLIC_READ_ONLY_HOSTS.has(hostname.toLowerCase());
}

export function isPublicReadOnlyRuntime(): boolean {
  if (PUBLIC_READ_ONLY_ENV) return true;
  if (typeof window === 'undefined') return false;
  return isPublicReadOnlyHost(window.location.hostname);
}
