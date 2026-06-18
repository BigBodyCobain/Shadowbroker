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
  const port =
    process.env.NEXT_PUBLIC_BACKEND_PORT ||
    (fePort && fePort !== '3000'
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
