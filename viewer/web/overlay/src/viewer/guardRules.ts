/**
 * The public viewer's network rule, as a pure function so it can be tested
 * on its own (viewer/web/tests). netGuard.ts applies it to every request.
 *
 * A request is one of:
 *   - "network": allowed to leave the browser. Read-only, and only to the
 *     viewer's own static files, the bridge's data files, or a listed host;
 *   - "local":   an app route the viewer can answer without any server;
 *   - "refuse":  everything else. It never touches the network.
 */

export type GuardVerdict = { kind: 'network' } | { kind: 'local'; route: LocalRoute } | { kind: 'refuse' };

/** App read routes the viewer answers by itself. */
export const LOCAL_ROUTES = ['/api/cyber-threats', '/api/scm-suppliers', '/api/wikipedia/summary'] as const;
export type LocalRoute = (typeof LOCAL_ROUTES)[number];

export type GuardContext = {
  /** Origin the viewer page is served from. */
  pageOrigin: string;
  /** Absolute URL of the data folder. */
  dataBase: URL;
  /** Exact outside hostnames that may be read over https. */
  allowedHosts: readonly string[];
};

function readOnly(method: string): boolean {
  return method === 'GET' || method === 'HEAD';
}

function isApiPath(pathname: string): boolean {
  // Case-insensitive, and tolerant of doubled slashes, so no spelling of an
  // app route is ever mistaken for a static file.
  const normalized = pathname.replace(/\/{2,}/g, '/').toLowerCase();
  return normalized === '/api' || normalized.startsWith('/api/');
}

function underDataBase(url: URL, dataBase: URL): boolean {
  if (url.origin !== dataBase.origin) return false;
  const base = dataBase.pathname.replace(/\/+$/, '');
  // URL parsing has already resolved "." and ".." segments, so a prefix test
  // on the parsed path cannot be escaped with "../".
  return url.pathname === base || url.pathname.startsWith(`${base}/`);
}

export function classifyRequest(url: URL, method: string, ctx: GuardContext): GuardVerdict {
  const verb = String(method || 'GET').toUpperCase();
  if (url.protocol === 'data:' || url.protocol === 'blob:') return { kind: 'network' };
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return { kind: 'refuse' };
  // Credentials in a URL are never legitimate here.
  if (url.username || url.password) return { kind: 'refuse' };

  if (url.origin === ctx.pageOrigin && isApiPath(url.pathname)) {
    if (!readOnly(verb)) return { kind: 'refuse' };
    const path = url.pathname.replace(/\/{2,}/g, '/').replace(/\/+$/, '');
    const route = LOCAL_ROUTES.find((candidate) => candidate === path);
    return route ? { kind: 'local', route } : { kind: 'refuse' };
  }

  if (underDataBase(url, ctx.dataBase)) return readOnly(verb) ? { kind: 'network' } : { kind: 'refuse' };

  if (url.origin === ctx.pageOrigin) return readOnly(verb) ? { kind: 'network' } : { kind: 'refuse' };

  if (url.protocol === 'https:' && readOnly(verb) && ctx.allowedHosts.includes(url.hostname.toLowerCase())) {
    return { kind: 'network' };
  }
  return { kind: 'refuse' };
}
