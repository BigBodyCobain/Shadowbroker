import { NextRequest, NextResponse } from 'next/server';
import { timingSafeEqual } from 'crypto';
import { isAllowedBrowserRequest } from '@/lib/requestOrigin';
import { readRequestBody, RequestBodyTooLarge } from '@/lib/server/requestBody';
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

async function verifyAdminKey(
  adminKey: string,
): Promise<{ ok: true } | { ok: false; detail: string }> {
  const configuredAdmin = String(process.env.ADMIN_KEY || '').trim();
  if (!configuredAdmin) {
    return {
      ok: false,
      detail: 'No admin key configured. Set ADMIN_KEY on the frontend and backend, then restart to enable operator login.',
    };
  }
  const presented = Buffer.from(String(adminKey || ''));
  const expected = Buffer.from(configuredAdmin);
  if (presented.length !== expected.length || !timingSafeEqual(presented, expected)) {
    return { ok: false, detail: 'Invalid admin key' };
  }
  return { ok: true };
}

export async function POST(req: NextRequest) {
  if (!isAllowedBrowserRequest(req)) return NextResponse.json({ detail: 'Cross-origin request denied' }, { status: 403, headers: NO_STORE_HEADERS });
  let body;
  try {
    body = JSON.parse(await readRequestBody(req, 64 * 1024) || '{}');
  } catch (error) {
    return NextResponse.json({ detail: 'Invalid session request' }, { status: error instanceof RequestBodyTooLarge ? 413 : 400, headers: NO_STORE_HEADERS });
  }
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
  if (!isAllowedBrowserRequest(req)) return NextResponse.json({ detail: 'Cross-origin request denied' }, { status: 403, headers: NO_STORE_HEADERS });
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
