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

async function verifyAdminKey(adminKey: string): Promise<{ ok: true } | { ok: false; detail: string }> {
  const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000';
  const verifyAgainstBackend = async (): Promise<
    { ok: true } | { ok: false; detail: string }
  > => {
    try {
      const res = await fetch(`${backendUrl}/api/settings/privacy-profile`, {
        method: 'GET',
        headers: { 'X-Admin-Key': adminKey },
        cache: 'no-store',
      });
      if (res.ok) return { ok: true };
      const data = await res.json().catch(() => ({}));
      return {
        ok: false,
        detail: String(data?.detail || data?.message || 'Unable to verify admin key'),
      };
    } catch {
      return {
        ok: false,
        detail: 'Unable to verify admin key against backend',
      };
    }
  };

  const configuredAdmin = String(process.env.ADMIN_KEY || '').trim();
  if (configuredAdmin) {
    if (adminKey !== configuredAdmin) {
      return { ok: false, detail: 'Invalid admin key' };
    }
    return verifyAgainstBackend();
  }

  return verifyAgainstBackend();
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
