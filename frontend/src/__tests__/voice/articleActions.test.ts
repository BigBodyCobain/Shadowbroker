import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mergeData, readDataKey } from '@/hooks/useDataStore';
import { articleSourceUrl, findNewsArticle } from '@/lib/newsArticles';
import { executeClientVerb, type ClientToolContext } from '@/lib/clientTools';
import { runDeterministicTurn } from '@/lib/voiceDeterministic';

const rows = [
  { title: 'Port traffic update', summary: 'Container arrivals', link: 'https://news.example/port', coords: [0, 0] },
  { title: 'Storm warning', link: 'https://news.example/storm', alertKey: 'storm-id' },
  { title: 'Local report without coordinates' },
];
let previous: unknown;
beforeEach(() => { previous = readDataKey('news'); mergeData({ news: rows }); });
afterEach(() => { mergeData({ news: previous }); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const context = (): ClientToolContext => ({
  flyTo: vi.fn(), toggleLayer: vi.fn(), applyMapStyle: vi.fn(), setFilter: vi.fn(),
  setSelectedEntity: vi.fn(), viewSummary: () => ({ activeLayers: {}, filters: {} }),
});

describe('article preview actions', () => {
  it('selects the existing news dossier with a stable key and no network request', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    const ctx = context();
    const result = await executeClientVerb('open_article', { query: 'port' }, ctx);
    expect(result.ok).toBe(true);
    expect(ctx.setSelectedEntity).toHaveBeenCalledWith({ id: 'Port traffic update|0,0', type: 'news', name: 'Port traffic update' });
    expect(fetch).not.toHaveBeenCalled();
  });
  it('resolves exact URLs without falling back to a different story', () => {
    expect(findNewsArticle({ url: rows[1].link, query: 'port' })?.id).toBe('storm-id');
    expect(findNewsArticle({ url: 'https://unrelated.example/', query: 'port' })).toBeNull();
  });
  it('opens stories without coordinates and respects explicit feed IDs', async () => {
    const ctx = context();
    expect((await executeClientVerb('open_article', { id: 'storm-id' }, ctx)).ok).toBe(true);
    expect((await executeClientVerb('open_article', { query: 'without coordinates' }, ctx)).ok).toBe(true);
    expect(ctx.setSelectedEntity).toHaveBeenLastCalledWith({ id: 'Local report without coordinates|undefined,undefined', type: 'news', name: 'Local report without coordinates' });
  });
  it('reports a missing article without opening a different item', async () => {
    const ctx = context();
    expect(await executeClientVerb('open_article', { query: 'missing story' }, ctx)).toMatchObject({ ok: false, error: 'article not found in loaded news' });
    expect(ctx.setSelectedEntity).not.toHaveBeenCalled();
  });
  it('recognizes plain article requests before the generic map-place matcher', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    const ctx = context();
    const outcome = await runDeterministicTurn('Show me the article about port', ctx);
    expect(outcome.reply).toBe('Opened article: Port traffic update');
    expect(ctx.setSelectedEntity).toHaveBeenCalledOnce();
    expect(fetch).not.toHaveBeenCalled();
  });
  it.each(['javascript:alert(1)', 'data:text/html,hello', '//other.example/', 'https://user:password@example.com/', 'https://example.com/\\bad'])('rejects unsafe publisher links: %s', (url) => {
    expect(articleSourceUrl(url)).toBeNull();
  });
  it('allows absolute publisher HTTP(S) links', () => {
    expect(articleSourceUrl('https://news.example/story')).toBe('https://news.example/story');
  });
});
