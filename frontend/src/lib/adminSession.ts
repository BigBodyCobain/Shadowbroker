import { API_BASE } from '@/lib/api';

let hasPrimedSessionHint = false;

function takeLegacyAdminKey(): string {
  if (typeof window === 'undefined') return '';
  const sessionValue = sessionStorage.getItem('sb_admin_key') || '';
  const legacyValue = localStorage.getItem('sb_admin_key') || '';
  const candidate = sessionValue || legacyValue;
  try {
    sessionStorage.removeItem('sb_admin_key');
    localStorage.removeItem('sb_admin_key');
  } catch {
    /* ignore */
  }
  return candidate;
}

export async function hasAdminSession(): Promise<boolean> {
  try {
    const existing = await fetch(`${API_BASE}/api/admin/session`, { cache: 'no-store' });
    const existingData = await existing.json().catch(() => ({}));
    return Boolean(existing.ok && existingData?.hasSession);
  } catch {
    return false;
  }
}

export async function primeAdminSession(adminKey?: string): Promise<void> {
  if (!adminKey) {
    if (await hasAdminSession()) return;
  }
  const candidate = String(adminKey || takeLegacyAdminKey() || '').trim();
  if (!candidate) throw new Error('admin_session_required');
  if (hasPrimedSessionHint && (await hasAdminSession())) return;
  const res = await fetch(`${API_BASE}/api/admin/session`, {
    method: 'POST',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ adminKey: candidate }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data?.ok === false) {
    throw new Error(data?.detail || data?.message || 'admin_session_failed');
  }
  hasPrimedSessionHint = true;
}

export async function clearAdminSession(): Promise<void> {
  hasPrimedSessionHint = false;
  if (typeof window !== 'undefined') {
    try {
      sessionStorage.removeItem('sb_admin_key');
      localStorage.removeItem('sb_admin_key');
    } catch {
      /* ignore */
    }
  }
  await fetch(`${API_BASE}/api/admin/session`, {
    method: 'DELETE',
    cache: 'no-store',
  }).catch(() => null);
}
