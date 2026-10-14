import type { NextRequest } from 'next/server';

export function isAllowedBrowserRequest(request: NextRequest): boolean {
  const site = (request.headers.get('sec-fetch-site') || '').toLowerCase();
  const origin = request.headers.get('origin');
  if (!origin) return !site || site === 'same-origin';
  try {
    const source = new URL(origin);
    if (!['http:', 'https:'].includes(source.protocol) || source.username || source.password) {
      return false;
    }
    if (source.href !== source.origin + '/' && source.href !== source.origin) return false;
    const ownOrigin = request.nextUrl.origin ||
      new URL('http://' + request.headers.get('host')).origin;
    const allowed = (process.env.SHADOWBROKER_ALLOWED_ORIGINS || '').split(',')
      .map((value) => value.trim()).filter(Boolean);
    // Public reverse-proxy origins must be configured; forwarding headers are untrusted.
    return source.origin === ownOrigin || allowed.includes(source.origin);
  } catch {
    return false;
  }
}
