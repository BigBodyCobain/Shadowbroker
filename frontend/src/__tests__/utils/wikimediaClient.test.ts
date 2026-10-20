/**
 * #360: Wikipedia / Wikidata traffic is proxied via the self-hosted backend.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fetchWikipediaSummary,
  fetchWikidataSparql,
  _resetWikimediaClientCacheForTests,
} from '@/lib/wikimediaClient';

const originalFetch = globalThis.fetch;

describe('lib/wikimediaClient', () => {
  beforeEach(() => {
    _resetWikimediaClientCacheForTests();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('fetches Wikipedia summary through backend proxy', async () => {
    const calls: string[] = [];
    globalThis.fetch = vi.fn(async (input: any) => {
      calls.push(String(input));
      return new Response(
        JSON.stringify({
          title: 'Boeing 747',
          description: 'aircraft',
          extract: 'long extract',
          thumbnail: 'https://example.org/thumb.jpg',
          type: 'standard',
        }),
        { status: 200 },
      );
    }) as any;

    const summary = await fetchWikipediaSummary('Boeing 747');
    expect(summary?.thumbnail).toBe('https://example.org/thumb.jpg');
    expect(calls).toHaveLength(1);
    expect(calls[0]).toContain('/api/wikipedia/summary');
    expect(calls[0]).not.toContain('wikipedia.org');
  });

  it('fetches Wikidata SPARQL through backend proxy', async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = vi.fn(async (url: any, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      return new Response(
        JSON.stringify({
          bindings: [{ leaderLabel: { value: 'Test Leader' } }],
        }),
        { status: 200 },
      );
    }) as any;

    const bindings = await fetchWikidataSparql('SELECT * WHERE { ?s ?p ?o }');
    expect(bindings).toHaveLength(1);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain('/api/wikidata/sparql');
    expect(calls[0].init?.method).toBe('POST');
    expect(calls[0].url).not.toContain('wikidata.org');
  });

  it('deduplicates concurrent Wikipedia summary requests', async () => {
    let hits = 0;
    globalThis.fetch = vi.fn(async () => {
      hits += 1;
      return new Response(
        JSON.stringify({
          title: 'Mount Fuji',
          description: 'mountain',
          extract: 'extract',
          thumbnail: '',
          type: 'standard',
        }),
        { status: 200 },
      );
    }) as any;

    const [a, b, c] = await Promise.all([
      fetchWikipediaSummary('Mount Fuji'),
      fetchWikipediaSummary('Mount Fuji'),
      fetchWikipediaSummary('Mount Fuji'),
    ]);
    expect(a?.title).toBe('Mount Fuji');
    expect(b).toEqual(a);
    expect(c).toEqual(a);
    expect(hits).toBe(1);
  });

  it('returns null on Wikipedia 404', async () => {
    globalThis.fetch = vi.fn(async () => new Response('{}', { status: 404 })) as any;
    expect(await fetchWikipediaSummary('Nonexistent Article 12345')).toBeNull();
  });
});
