/**
 * wikimediaClient — Wikipedia / Wikidata via the self-hosted backend (#360).
 *
 * The browser only calls `/api/wikipedia/summary` and `/api/wikidata/sparql`.
 * Outbound Wikimedia traffic (with per-install operator attribution from
 * Round 7a) is handled server-side in `services/region_dossier.py`.
 */
import { API_BASE } from '@/lib/api';

export interface WikipediaSummary {
  title: string;
  description: string;
  extract: string;
  thumbnail: string;
  type: string;
}

interface CacheEntry {
  summary: WikipediaSummary | null;
  inflight: Promise<WikipediaSummary | null> | null;
  loaded: boolean;
}

const _summaryCache: Map<string, CacheEntry> = new Map();
const SUMMARY_CACHE_MAX = 512;

function evictIfOverCap() {
  if (_summaryCache.size <= SUMMARY_CACHE_MAX) return;
  const oldest = _summaryCache.keys().next().value;
  if (oldest) _summaryCache.delete(oldest);
}

export async function fetchWikipediaSummary(
  title: string,
): Promise<WikipediaSummary | null> {
  const trimmed = (title || '').trim();
  if (!trimmed) return null;

  const cached = _summaryCache.get(trimmed);
  if (cached?.loaded) return cached.summary;
  if (cached?.inflight) return cached.inflight;

  const promise = (async (): Promise<WikipediaSummary | null> => {
    try {
      const url = `${API_BASE}/api/wikipedia/summary?title=${encodeURIComponent(trimmed)}`;
      const r = await fetch(url);
      if (r.status === 404) return null;
      if (!r.ok) return null;
      const d = await r.json();
      return {
        title: (d?.title as string) || trimmed,
        description: (d?.description as string) || '',
        extract: (d?.extract as string) || '',
        thumbnail: (d?.thumbnail as string) || '',
        type: (d?.type as string) || 'standard',
      };
    } catch {
      return null;
    }
  })().then((summary) => {
    _summaryCache.set(trimmed, { summary, inflight: null, loaded: true });
    evictIfOverCap();
    return summary;
  });

  _summaryCache.set(trimmed, { summary: null, inflight: promise, loaded: false });
  evictIfOverCap();
  return promise;
}

export async function fetchWikidataSparql<T = Record<string, { value: string }>>(
  sparql: string,
): Promise<T[] | null> {
  const trimmed = (sparql || '').trim();
  if (!trimmed) return null;
  try {
    const res = await fetch(`${API_BASE}/api/wikidata/sparql`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: trimmed }),
    });
    if (!res.ok) return null;
    const json = await res.json();
    const bindings = json?.bindings;
    return Array.isArray(bindings) ? (bindings as T[]) : null;
  } catch {
    return null;
  }
}

/** @deprecated Browser no longer builds Wikimedia UA; kept for tests that import it. */
export async function buildWikimediaUserAgent(purpose: string): Promise<string> {
  void purpose;
  return 'Shadowbroker/1.0 (backend-proxied; purpose: wikimedia)';
}

export function _resetWikimediaClientCacheForTests() {
  _summaryCache.clear();
}
