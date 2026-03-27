import { API_BASE } from '@/lib/api';
import type {
  ShodanCountResponse,
  ShodanHostResponse,
  ShodanSearchResponse,
  ShodanStatusResponse,
} from '@/types/shodan';

type JsonBody = Record<string, unknown>;

async function postJson<T>(path: string, body: JsonBody): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(String((data as { detail?: string }).detail || 'Request failed'));
  }
  return data as T;
}

export async function fetchShodanStatus(): Promise<ShodanStatusResponse> {
  const res = await fetch(`${API_BASE}/api/tools/shodan/status`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(String((data as { detail?: string }).detail || 'Failed to load Shodan status'));
  }
  return data as ShodanStatusResponse;
}

export function searchShodan(query: string, page = 1, facets: string[] = []) {
  return postJson<ShodanSearchResponse>('/api/tools/shodan/search', { query, page, facets });
}

export function countShodan(query: string, facets: string[] = []) {
  return postJson<ShodanCountResponse>('/api/tools/shodan/count', { query, facets });
}

export function lookupShodanHost(ip: string, history = false) {
  return postJson<ShodanHostResponse>('/api/tools/shodan/host', { ip, history });
}
