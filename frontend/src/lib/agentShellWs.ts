export async function mintAgentShellWsToken(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  try {
    const res = await fetch('/api/agent-shell/ws-token', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { token?: string };
    const token = String(body?.token || '').trim();
    return token || null;
  } catch {
    return null;
  }
}

export function resolveAgentShellWsUrl(cwd?: string, wsToken?: string): string {
  if (typeof window === 'undefined') return '';
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = window.location.hostname || '127.0.0.1';
  const fePort = window.location.port;
  // NEXT_PUBLIC_BACKEND_PORT wins; otherwise keep the side-by-side dev offset
  // (frontend 3000-3999 → backend 8000+N), and dial the default 8000 when the
  // frontend is on :3000 itself or behind a proxy with no port exposed.
  const port =
    process.env.NEXT_PUBLIC_BACKEND_PORT ||
    (fePort && Number(fePort) >= 3001 && Number(fePort) <= 3999
      ? String(Number(fePort) - 3000 + 8000)
      : '8000');
  const params = new URLSearchParams();
  const trimmed = String(cwd || '').trim();
  if (trimmed) params.set('cwd', trimmed);
  const token = String(wsToken || '').trim();
  if (token) params.set('ws_token', token);
  const query = params.toString();
  return `${protocol}://${host}:${port}/api/agent-shell/ws${query ? `?${query}` : ''}`;
}
