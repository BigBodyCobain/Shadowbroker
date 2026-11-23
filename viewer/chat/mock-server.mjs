#!/usr/bin/env node
/**
 * Local stand-in for the chat service. Development only.
 *
 * It answers the same handful of login and database calls the viewer makes
 * to a real Supabase project, with the same rules as viewer/chat/schema.sql
 * (sign in to post, username first, pace limits), so the chat panel can be
 * tried without creating any account anywhere. Everything is kept in memory
 * and lost when it stops. Never expose it to the internet.
 *
 *   node viewer/chat/mock-server.mjs [--port 54321]
 *
 * Matching viewer/web/chat.config.json:
 *   { "url": "http://127.0.0.1:54321", "anonKey": "<printed at start>", "providers": ["google"] }
 */

import crypto from 'node:crypto';
import http from 'node:http';

const args = process.argv.slice(2);
const portArg = args.indexOf('--port');
const port = Number(portArg >= 0 ? args[portArg + 1] : process.env.PORT || 54321);

const b64 = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64url');
/** Shaped like a real public key: a token whose role is "anon". Not a secret. */
export const MOCK_ANON_KEY = `${b64({ alg: 'none', typ: 'JWT' })}.${b64({ role: 'anon', iss: 'sb-chat-mock' })}.mock`;

const users = new Map(); // email -> { id, email, password }
const tokens = new Map(); // access token -> user id
const refreshTokens = new Map(); // refresh token -> user id
const profiles = new Map(); // user id -> username
const messages = []; // { id, user_id, username, body, created_at }
const reports = new Set();
let nextMessageId = 1;

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'apikey, authorization, content-type, prefer',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
};

function send(res, status, body, extra = {}) {
  const text = body === undefined ? '' : JSON.stringify(body);
  res.writeHead(status, { ...CORS, 'Content-Type': 'application/json', ...extra });
  res.end(text);
}

function readBody(req) {
  return new Promise((resolve) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 64 * 1024) req.destroy();
    });
    req.on('end', () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        resolve({});
      }
    });
  });
}

function issue(user) {
  const access = crypto.randomBytes(24).toString('base64url');
  const refresh = crypto.randomBytes(24).toString('base64url');
  tokens.set(access, user.id);
  refreshTokens.set(refresh, user.id);
  return {
    access_token: access,
    refresh_token: refresh,
    expires_in: 3600,
    token_type: 'bearer',
    user: { id: user.id, email: user.email },
  };
}

function userFromRequest(req) {
  const header = String(req.headers.authorization || '');
  const id = tokens.get(header.replace(/^Bearer\s+/i, ''));
  return id ? [...users.values()].find((u) => u.id === id) || null : null;
}

function ensureUser(email, password = null) {
  let user = users.get(email);
  if (!user) {
    user = { id: crypto.randomUUID(), email, password };
    users.set(email, user);
  }
  return user;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${port}`);
  const route = `${req.method} ${url.pathname}`;
  if (req.method === 'OPTIONS') return send(res, 204);

  // ── Login ────────────────────────────────────────────────────────────────
  if (route === 'POST /auth/v1/signup') {
    const { email, password } = await readBody(req);
    if (!email || !password || String(password).length < 6) return send(res, 422, { msg: 'Password is too short' });
    if (users.has(email)) return send(res, 422, { msg: 'User already registered' });
    return send(res, 200, issue(ensureUser(String(email), String(password))));
  }
  if (route === 'POST /auth/v1/token') {
    const body = await readBody(req);
    if (url.searchParams.get('grant_type') === 'refresh_token') {
      const id = refreshTokens.get(String(body.refresh_token || ''));
      const user = id && [...users.values()].find((u) => u.id === id);
      return user ? send(res, 200, issue(user)) : send(res, 400, { error_description: 'Invalid Refresh Token' });
    }
    const user = users.get(String(body.email || ''));
    if (!user || user.password === null || user.password !== body.password) {
      return send(res, 400, { error_description: 'Invalid login credentials' });
    }
    return send(res, 200, issue(user));
  }
  if (route === 'GET /auth/v1/authorize') {
    // A real provider shows its own sign-in page here. The stand-in signs in a fixed test person.
    const provider = url.searchParams.get('provider') || 'google';
    const back = url.searchParams.get('redirect_to') || '';
    if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//.test(back)) return send(res, 400, { msg: 'bad redirect' });
    const session = issue(ensureUser(`${provider}-tester@example.test`));
    const fragment = new URLSearchParams({
      access_token: session.access_token,
      refresh_token: session.refresh_token,
      expires_in: '3600',
      token_type: 'bearer',
    });
    res.writeHead(302, { ...CORS, Location: `${back}#${fragment}` });
    return res.end();
  }
  if (route === 'GET /auth/v1/user') {
    const user = userFromRequest(req);
    return user ? send(res, 200, { id: user.id, email: user.email }) : send(res, 401, { msg: 'Invalid token' });
  }
  if (route === 'POST /auth/v1/logout') {
    tokens.delete(String(req.headers.authorization || '').replace(/^Bearer\s+/i, ''));
    return send(res, 204);
  }

  // ── Usernames ────────────────────────────────────────────────────────────
  if (route === 'GET /rest/v1/profiles') {
    const id = (url.searchParams.get('id') || '').replace(/^eq\./, '');
    return send(res, 200, profiles.has(id) ? [{ username: profiles.get(id) }] : []);
  }
  if (route === 'POST /rest/v1/profiles') {
    const user = userFromRequest(req);
    if (!user) return send(res, 401, { message: 'Sign in to chat.' });
    const { id, username } = await readBody(req);
    const name = String(username || '');
    if (id !== user.id) return send(res, 403, { message: 'new row violates row-level security policy' });
    if (!/^[A-Za-z0-9_]{3,20}$/.test(name)) return send(res, 400, { code: '23514', message: 'Username shape' });
    if (/(admin|moderator|^mods?$|shadowbroker|shadow_broker|official|support|system|staff)/i.test(name)) {
      return send(res, 400, { code: 'P0001', message: 'That username is reserved. Pick another.' });
    }
    const taken = [...profiles.values()].some((n) => n.toLowerCase() === name.toLowerCase());
    if (taken || profiles.has(user.id)) return send(res, 409, { code: '23505', message: 'duplicate key' });
    profiles.set(user.id, name);
    return send(res, 201);
  }

  // ── Messages ─────────────────────────────────────────────────────────────
  if (route === 'GET /rest/v1/messages') {
    const after = Number((url.searchParams.get('id') || '').replace(/^gt\./, '')) || 0;
    const shape = ({ id, username, body, created_at }) => ({ id, username, body, created_at });
    if (after) return send(res, 200, messages.filter((m) => m.id > after).slice(0, 100).map(shape));
    return send(res, 200, messages.slice(-60).reverse().map(shape));
  }
  if (route === 'POST /rest/v1/messages') {
    const user = userFromRequest(req);
    if (!user) return send(res, 401, { message: 'Sign in to chat.' });
    const username = profiles.get(user.id);
    if (!username) return send(res, 400, { code: 'P0001', message: 'Pick a username first.' });
    const { body } = await readBody(req);
    // eslint-disable-next-line no-control-regex
    const text = String(body || '').replace(/[\u0000-\u001f\u007f]+/g, ' ').trim();
    if (!text || text.length > 500) return send(res, 400, { code: '23514', message: 'Message length' });
    const mine = messages.filter((m) => m.user_id === user.id);
    const now = Date.now();
    if (mine.some((m) => now - Date.parse(m.created_at) < 3000)) {
      return send(res, 400, { code: 'P0001', message: 'Slow down a little.' });
    }
    if (mine.filter((m) => now - Date.parse(m.created_at) < 60000).length >= 10) {
      return send(res, 400, { code: 'P0001', message: 'Too many messages. Try again in a minute.' });
    }
    const row = { id: nextMessageId++, user_id: user.id, username, body: text, created_at: new Date().toISOString() };
    messages.push(row);
    return send(res, 201, [{ id: row.id, username, body: text, created_at: row.created_at }]);
  }
  if (route === 'POST /rest/v1/reports') {
    const user = userFromRequest(req);
    if (!user) return send(res, 401, { message: 'Sign in to chat.' });
    const { message_id: messageId } = await readBody(req);
    const key = `${messageId}:${user.id}`;
    if (reports.has(key)) return send(res, 409, { code: '23505', message: 'duplicate key' });
    reports.add(key);
    return send(res, 201);
  }

  return send(res, 404, { message: 'not found' });
});

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, '/').split('/').pop())) {
  server.listen(port, '127.0.0.1', () => {
    console.log(`chat stand-in on http://127.0.0.1:${port}`);
    console.log(`anonKey: ${MOCK_ANON_KEY}`);
  });
}

export { server };
