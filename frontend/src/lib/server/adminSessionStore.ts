import { randomUUID } from 'crypto';

type AdminSessionRecord = {
  adminKey: string;
  expiresAt: number;
};

const sessions = new Map<string, AdminSessionRecord>();

function purgeExpiredSessions() {
  const now = Date.now();
  for (const [token, session] of sessions.entries()) {
    if (session.expiresAt <= now) {
      sessions.delete(token);
    }
  }
}

export function createAdminSessionToken(adminKey: string, maxAgeSeconds: number): string {
  purgeExpiredSessions();
  const token = randomUUID();
  sessions.set(token, {
    adminKey,
    expiresAt: Date.now() + maxAgeSeconds * 1000,
  });
  return token;
}

export function resolveAdminSessionToken(token: string): string {
  purgeExpiredSessions();
  const session = sessions.get(token);
  if (!session) return '';
  return session.adminKey;
}

export function hasAdminSessionToken(token: string): boolean {
  return Boolean(resolveAdminSessionToken(token));
}

export function clearAdminSessionToken(token: string): void {
  if (!token) return;
  sessions.delete(token);
}
