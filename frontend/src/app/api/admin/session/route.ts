import { NextRequest, NextResponse } from 'next/server';
import {
  clearAdminSessionToken,
  createAdminSessionToken,
  hasAdminSessionToken,
} from '@/lib/server/adminSessionStore';

const COOKIE_NAME = 'sb_admin_session';
const COOKIE_MAX_AGE = 60 * 60 * 8;
const NO_STORE_HEADERS = {
  'Cache-Control': 'no-store, max-age=0',
  Pragma: 'no-cache',
};

function cookieOptions() {
  return {
    httpOnly: true,
    sameSite: 'strict' as const,
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: COOKIE_MAX_AGE,
  };
}

/**
 * Verify an operator-supplied admin key before minting a session cookie.
 *
 * Issue #255: the previous implementation, when ADMIN_KEY was unset on
 * the server, fell through to verifying against the backend by GET-ing
 * /api/settings/privacy-profile. That endpoint is public — it returns
 * 200 for any X-Admin-Key value (or none at all) — so the fallback
 * accepted *arbitrary* keys and minted full admin sessions for them.
 *
 * Fix: require ADMIN_KEY to be configured before any session can be
 * minted, and do the validation locally instead of round-tripping to a
 * potentially-public endpoint. If ADMIN_KEY is unset, the backend
 * already auto-trusts loopback / docker-bridge callers via
 * require_local_operator + SHADOWBROKER_TRUST_DOCKER_BRIDGE_LOCAL_OPERATOR,
 * so legitimate local users keep working — they just don't get (and
 * don't need) a privileged session cookie.
 */
async function verifyAdminKey(
  adminKey: string,
): Promise<{ ok: true } | { ok: false; detail: string }> {
  const configuredAdmin = String(process.env.ADMIN_KEY || '').trim();
  if (!configuredAdmin) {
    return {
      ok: false,
      detail:
        'No admin key configured on the server. Local-host requests are '
        + 'already auto-trusted by the backend — no session is needed. '
        + 'To enable session-based admin auth, set ADMIN_KEY in the backend '
        + 'environment and restart.',
    };
  }
  if (adminKey !== configuredAdmin) {
    return { ok: false, detail: 'Invalid admin key' };
  }
  return { ok: true };
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const adminKey = String(body?.adminKey || '').trim();
  if (!adminKey) {
    return NextResponse.json(
      { ok: false, detail: 'Missing admin key' },
      { status: 400, headers: NO_STORE_HEADERS },
    );
  }
  const verification = await verifyAdminKey(adminKey);
  if (!verification.ok) {
    return NextResponse.json(
      { ok: false, detail: verification.detail },
      { status: 403, headers: NO_STORE_HEADERS },
    );
  }
  const existingToken = req.cookies.get(COOKIE_NAME)?.value || '';
  if (existingToken) {
    clearAdminSessionToken(existingToken);
  }
  const sessionToken = createAdminSessionToken(adminKey, COOKIE_MAX_AGE);
  const res = NextResponse.json({ ok: true }, { headers: NO_STORE_HEADERS });
  res.cookies.set(COOKIE_NAME, sessionToken, cookieOptions());
  return res;
}

export async function DELETE(req: NextRequest) {
  const existingToken = req.cookies.get(COOKIE_NAME)?.value || '';
  if (existingToken) {
    clearAdminSessionToken(existingToken);
  }
  const res = NextResponse.json({ ok: true }, { headers: NO_STORE_HEADERS });
  res.cookies.set(COOKIE_NAME, '', {
    ...cookieOptions(),
    maxAge: 0,
  });
  return res;
}

export async function GET(req: NextRequest) {
  const token = req.cookies.get(COOKIE_NAME)?.value || '';
  return NextResponse.json(
    { ok: true, hasSession: hasAdminSessionToken(token) },
    { headers: NO_STORE_HEADERS },
  );
}
