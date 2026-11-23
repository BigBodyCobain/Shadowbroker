/**
 * Chat client for the public viewer.
 *
 * Talks to a Supabase project (hosted login + database) with plain `fetch`,
 * so the viewer needs no extra packages. The chat service is separate from
 * the ShadowBroker engine: it never sees map data or the engine machine.
 *
 * Only two public values are compiled in: the project address and its
 * "anon" key. Both are meant to be seen by browsers; what a visitor may do
 * with them is decided by the database rules in viewer/chat/schema.sql.
 * Passwords are sent to the login service over https and never stored here.
 */

import { VIEWER_CHAT } from '../config';

export type ChatUser = { id: string; email: string | null };
export type ChatSession = {
  accessToken: string;
  refreshToken: string;
  /** Epoch ms when the access token stops working. */
  expiresAt: number;
  user: ChatUser;
};
export type ChatMessage = { id: number; username: string; body: string; created_at: string };

export class ChatError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}

const SESSION_KEY = 'sb_viewer_chat_session';
export const MESSAGE_MAX = 500;
export const USERNAME_RULE = /^[A-Za-z0-9_]{3,20}$/;

export function chatConfigured(): boolean {
  return Boolean(VIEWER_CHAT.url && VIEWER_CHAT.anonKey);
}

function endpoint(path: string): string {
  return `${VIEWER_CHAT.url}${path}`;
}

function friendly(body: unknown, status: number): string {
  const b = (body || {}) as Record<string, unknown>;
  const text = String(b.msg || b.message || b.error_description || b.error || '').trim();
  if (b.code === '23505') return 'That username is taken.';
  if (/invalid login credentials/i.test(text)) return 'Wrong email or password.';
  if (/already registered/i.test(text)) return 'That email already has an account. Sign in instead.';
  if (status === 429) return 'Too many tries. Wait a minute.';
  if (status === 401 || status === 403) return text || 'Please sign in again.';
  return text || `Chat service error (${status}).`;
}

async function call<T>(
  path: string,
  options: { method?: string; body?: unknown; token?: string; prefer?: string } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    apikey: VIEWER_CHAT.anonKey,
    Authorization: `Bearer ${options.token || VIEWER_CHAT.anonKey}`,
  };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.prefer) headers.Prefer = options.prefer;
  let res: Response;
  try {
    res = await fetch(endpoint(path), {
      method: options.method || 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new ChatError('Chat service is unreachable.');
  }
  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  if (!res.ok) throw new ChatError(friendly(parsed, res.status), res.status);
  return parsed as T;
}

// ── Session ────────────────────────────────────────────────────────────────

type TokenResponse = {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  user?: { id?: string; email?: string | null };
};

function toSession(t: TokenResponse): ChatSession | null {
  if (!t.access_token || !t.refresh_token || !t.user?.id) return null;
  return {
    accessToken: t.access_token,
    refreshToken: t.refresh_token,
    expiresAt: Date.now() + Math.max(60, Number(t.expires_in) || 3600) * 1000,
    user: { id: t.user.id, email: t.user.email ?? null },
  };
}

export function loadSession(): ChatSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as ChatSession;
    return s && s.accessToken && s.refreshToken && s.user?.id ? s : null;
  } catch {
    return null;
  }
}

export function saveSession(session: ChatSession | null): void {
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable: the session lasts for this page only */
  }
}

/** Return a session whose token is good for at least another minute, or null. */
export async function freshSession(session: ChatSession | null): Promise<ChatSession | null> {
  if (!session) return null;
  if (session.expiresAt - Date.now() > 60_000) return session;
  try {
    const next = toSession(
      await call<TokenResponse>('/auth/v1/token?grant_type=refresh_token', {
        method: 'POST',
        body: { refresh_token: session.refreshToken },
      }),
    );
    saveSession(next);
    return next;
  } catch {
    saveSession(null);
    return null;
  }
}

// ── Sign in / up / out ─────────────────────────────────────────────────────

export async function signInWithPassword(email: string, password: string): Promise<ChatSession> {
  const session = toSession(
    await call<TokenResponse>('/auth/v1/token?grant_type=password', {
      method: 'POST',
      body: { email, password },
    }),
  );
  if (!session) throw new ChatError('Sign-in failed.');
  saveSession(session);
  return session;
}

/** Create an account. Returns a session, or null when the service emailed a confirmation link. */
export async function signUpWithPassword(email: string, password: string): Promise<ChatSession | null> {
  const session = toSession(
    await call<TokenResponse>('/auth/v1/signup', { method: 'POST', body: { email, password } }),
  );
  if (session) saveSession(session);
  return session;
}

export type OAuthProvider = 'google' | 'facebook';

/** Send the browser to the provider's own sign-in page. It returns here afterwards. */
export function startOAuth(provider: OAuthProvider): void {
  const back = `${window.location.origin}${window.location.pathname}`;
  window.location.assign(
    endpoint(`/auth/v1/authorize?provider=${provider}&redirect_to=${encodeURIComponent(back)}`),
  );
}

/**
 * After a provider sign-in the browser comes back with the session in the
 * address fragment. Read it, confirm it with the login service, and clean
 * the address bar. Returns null when this page load is not such a return.
 */
export async function completeOAuthReturn(): Promise<ChatSession | null> {
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : '';
  if (!hash.includes('access_token=') && !hash.includes('error_description=')) return null;
  const params = new URLSearchParams(hash);
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
  const problem = params.get('error_description');
  if (problem) throw new ChatError(problem.replace(/\+/g, ' '));
  const accessToken = params.get('access_token') || '';
  const refreshToken = params.get('refresh_token') || '';
  if (!accessToken || !refreshToken) return null;
  // Never trust the fragment by itself: ask the service who this token belongs to.
  const user = await call<{ id?: string; email?: string | null }>('/auth/v1/user', { token: accessToken });
  const session = toSession({
    access_token: accessToken,
    refresh_token: refreshToken,
    expires_in: Number(params.get('expires_in')) || 3600,
    user,
  });
  if (!session) throw new ChatError('Sign-in failed.');
  saveSession(session);
  return session;
}

export async function signOut(session: ChatSession | null): Promise<void> {
  saveSession(null);
  if (!session) return;
  try {
    await call('/auth/v1/logout', { method: 'POST', token: session.accessToken });
  } catch {
    /* already signed out locally */
  }
}

// ── Username ───────────────────────────────────────────────────────────────

export async function fetchUsername(session: ChatSession): Promise<string | null> {
  const rows = await call<{ username: string }[]>(
    `/rest/v1/profiles?select=username&id=eq.${encodeURIComponent(session.user.id)}`,
    { token: session.accessToken },
  );
  return rows?.[0]?.username ?? null;
}

export async function claimUsername(session: ChatSession, username: string): Promise<string> {
  const name = username.trim();
  if (!USERNAME_RULE.test(name)) {
    throw new ChatError('Use 3 to 20 letters, numbers or underscores.');
  }
  await call('/rest/v1/profiles', {
    method: 'POST',
    token: session.accessToken,
    body: { id: session.user.id, username: name },
  });
  return name;
}

// ── Messages ───────────────────────────────────────────────────────────────

const MESSAGE_COLUMNS = 'id,username,body,created_at';

/** Newest messages, oldest first. With `afterId`, only messages newer than it. */
export async function fetchMessages(afterId: number | null, token?: string): Promise<ChatMessage[]> {
  if (afterId) {
    return call<ChatMessage[]>(
      `/rest/v1/messages?select=${MESSAGE_COLUMNS}&id=gt.${Math.floor(afterId)}&order=id.asc&limit=100`,
      { token },
    );
  }
  const rows = await call<ChatMessage[]>(`/rest/v1/messages?select=${MESSAGE_COLUMNS}&order=id.desc&limit=60`, {
    token,
  });
  return rows.reverse();
}

export async function postMessage(session: ChatSession, body: string): Promise<ChatMessage> {
  const text = body.trim();
  if (!text) throw new ChatError('Message is empty.');
  if (text.length > MESSAGE_MAX) throw new ChatError(`Keep it under ${MESSAGE_MAX} characters.`);
  const rows = await call<ChatMessage[]>(`/rest/v1/messages?select=${MESSAGE_COLUMNS}`, {
    method: 'POST',
    token: session.accessToken,
    prefer: 'return=representation',
    body: { body: text },
  });
  if (!rows?.[0]) throw new ChatError('Message was not saved.');
  return rows[0];
}

export async function reportMessage(session: ChatSession, messageId: number): Promise<void> {
  try {
    await call('/rest/v1/reports', {
      method: 'POST',
      token: session.accessToken,
      body: { message_id: messageId },
    });
  } catch (error) {
    // Reporting the same message twice is fine.
    if (!(error instanceof ChatError) || error.status !== 409) throw error;
  }
}
