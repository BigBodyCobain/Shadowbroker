/**
 * Network guard for the public viewer.
 *
 * The viewer borrows panels from the full app, and those panels were written
 * to talk to an owner's backend. This guard makes that impossible by
 * construction: every request from page code is checked first (the rule is
 * in guardRules.ts), and only three kinds get through, all read-only:
 *
 *   1. the viewer's own static files;
 *   2. the bridge's data files;
 *   3. a short list of map-tile and reference hosts (see config.ts).
 *
 * Calls to the app's /api/* routes never touch the network. A few read
 * routes are answered from data already loaded; everything else gets a local
 * "not available" reply. WebSocket, EventSource and sendBeacon are disabled.
 *
 * The page's Content-Security-Policy repeats the same host list, so the
 * browser enforces it independently of this file.
 */

import { readDataKey } from '@/hooks/useDataStore';
import { VIEWER_CHAT, VIEWER_CONNECT_HOSTS, VIEWER_DATA_BASE } from './config';
import { classifyRequest, type GuardContext, type LocalRoute } from './guardRules';

export type GuardEvent = { method: string; url: string; at: number };

type GuardState = {
  installed: true;
  /** Requests that were refused locally. Read by the launch checks. */
  blocked: GuardEvent[];
  /** Requests that were allowed onto the network. */
  allowed: GuardEvent[];
};

declare global {
  interface Window {
    __sbViewerGuard?: GuardState;
  }
}

const MAX_LOG = 500;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-SB-Viewer': 'local' },
  });
}

function refused(): Response {
  // An empty object: borrowed code that reads the body without checking the
  // status then sees "no data" rather than something it might display.
  return new Response('{}', {
    status: 403,
    headers: { 'Content-Type': 'application/json', 'X-SB-Viewer': 'refused' },
  });
}

/** Answer one of the app's read routes without a server. */
async function answerLocally(route: LocalRoute, url: URL, nativeFetch: typeof fetch): Promise<Response> {
  if (route === '/api/cyber-threats') {
    return jsonResponse(readDataKey('cyber_threats') ?? { threats: [], stats: {} });
  }
  if (route === '/api/scm-suppliers') {
    return jsonResponse(readDataKey('scm_suppliers') ?? { suppliers: [], total: 0, critical_count: 0 });
  }
  // '/api/wikipedia/summary': same shape the app's backend returns, fetched
  // by the visitor's own browser so no server of the owner's is involved.
  const title = (url.searchParams.get('title') || '').trim();
  if (!title) return jsonResponse({ detail: 'missing title' }, 400);
  try {
    const res = await nativeFetch(
      `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title.replace(/ /g, '_'))}`,
      { headers: { Accept: 'application/json' }, credentials: 'omit' },
    );
    if (!res.ok) return jsonResponse({ detail: 'not found' }, 404);
    const d = (await res.json()) as {
      title?: string;
      description?: string;
      extract?: string;
      type?: string;
      thumbnail?: { source?: string };
    };
    return jsonResponse({
      title: d.title || title,
      description: d.description || '',
      extract: d.extract || '',
      thumbnail: d.thumbnail?.source || '',
      type: d.type || 'standard',
    });
  } catch {
    return jsonResponse({ detail: 'unavailable' }, 502);
  }
}

function record(list: GuardEvent[], method: string, url: string) {
  list.push({ method, url, at: Date.now() });
  if (list.length > MAX_LOG) list.splice(0, list.length - MAX_LOG);
}

export function installNetGuard(): void {
  if (typeof window === 'undefined' || window.__sbViewerGuard) return;

  const state: GuardState = { installed: true, blocked: [], allowed: [] };
  window.__sbViewerGuard = state;

  const nativeFetch = window.fetch.bind(window);
  const ctx: GuardContext = {
    pageOrigin: window.location.origin,
    dataBase: new URL(VIEWER_DATA_BASE, window.location.href),
    allowedHosts: VIEWER_CONNECT_HOSTS,
    chatBase: VIEWER_CHAT.url ? new URL(VIEWER_CHAT.url) : null,
  };

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const method = String(init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    let url: URL;
    try {
      url = new URL(raw, window.location.href);
    } catch {
      record(state.blocked, method, String(raw));
      return refused();
    }
    const verdict = classifyRequest(url, method, ctx);
    if (verdict.kind === 'network') {
      record(state.allowed, method, url.href);
      // Never send cookies or other credentials anywhere.
      return nativeFetch(input, { ...init, credentials: 'omit' });
    }
    if (verdict.kind === 'local') return answerLocally(verdict.route, url, nativeFetch);
    record(state.blocked, method, url.href);
    return refused();
  };

  // XMLHttpRequest: same rule. A refused request fails like a network error.
  const nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function open(
    this: XMLHttpRequest,
    method: string,
    target: string | URL,
    ...rest: unknown[]
  ) {
    const upper = String(method || 'GET').toUpperCase();
    let allowed = false;
    try {
      const url = new URL(String(target), window.location.href);
      allowed = classifyRequest(url, upper, ctx).kind === 'network';
      record(allowed ? state.allowed : state.blocked, upper, url.href);
    } catch {
      record(state.blocked, upper, String(target));
    }
    if (!allowed) throw new DOMException('Not available in the public viewer', 'NetworkError');
    return (nativeOpen as (...args: unknown[]) => void).call(this, method, target, ...rest);
  } as typeof XMLHttpRequest.prototype.open;

  // The viewer has no live socket to anything.
  class DisabledSocket {
    constructor(url: string | URL) {
      record(state.blocked, 'SOCKET', String(url));
      throw new DOMException('Not available in the public viewer', 'SecurityError');
    }
  }
  window.WebSocket = DisabledSocket as unknown as typeof WebSocket;
  window.EventSource = DisabledSocket as unknown as typeof EventSource;

  if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
    navigator.sendBeacon = (url: string | URL) => {
      record(state.blocked, 'BEACON', String(url));
      return false;
    };
  }
}

installNetGuard();
