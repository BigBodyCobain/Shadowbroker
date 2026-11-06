import { readDataKey } from '@/hooks/useDataStore';

export interface ArticleReference {
  id?: string;
  query?: string;
  url?: string;
}

/** Resolve only articles already loaded by the dashboard; never navigate an AI-authored URL. */
export function findNewsArticle(reference: ArticleReference): { id: string; title: string; url: string } | null {
  const rows = readDataKey('news');
  if (!Array.isArray(rows)) return null;
  const id = String(reference.id || '').trim().slice(0, 512);
  const url = String(reference.url || '').trim().slice(0, 2048);
  const query = String(reference.query || '').trim().slice(0, 200).toLowerCase();
  if (!id && !url && !query) return null;
  const articles = rows.filter((row): row is Record<string, unknown> => !!row && typeof row === 'object');
  const key = (row: Record<string, unknown>) => {
    const coords = Array.isArray(row.coords) ? row.coords : [];
    return String(row.alertKey || `${row.title}|${coords[0]},${coords[1]}`);
  };
  const title = (row: Record<string, unknown>) => String(row.title || '').trim().toLowerCase();
  const link = (row: Record<string, unknown>) => String(row.link || row.url || '').trim();
  const hit = id ? articles.find((row) => key(row) === id)
    : url ? articles.find((row) => link(row) === url)
      : articles.find((row) => title(row) === query)
        || articles.find((row) => query.split(/\s+/).every((word) => `${title(row)} ${String(row.summary || '').toLowerCase()}`.includes(word)));
  return hit ? { id: key(hit), title: String(hit.title || ''), url: link(hit) } : null;
}

/** Publisher links are explicit user clicks; permit only absolute HTTP(S) destinations. */
export function articleSourceUrl(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 2048 || /[\x00-\x1f\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
