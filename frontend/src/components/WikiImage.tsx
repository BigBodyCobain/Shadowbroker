'use client';
import React, { useState, useEffect } from 'react';
import ExternalImage from '@/components/ExternalImage';

// Module-level cache: Wikipedia article title → thumbnail URL
const _cache: Record<string, { url: string | null; done: boolean }> = {};

/**
 * WikiImage — displays a Wikipedia thumbnail for a given article URL.
 * Uses the Wikipedia REST API with a module-level cache (only fetches once per article).
 *
 * Props:
 *   wikiUrl:  Full Wikipedia URL, e.g. "https://en.wikipedia.org/wiki/Boeing_787_Dreamliner"
 *   label:    Alt text / label for the image link
 *   maxH:     Max height class (default "max-h-32")
 *   accent:   Border hover color class (default "hover:border-cyan-500/50")
 */
export default function WikiImage({
  wikiUrl,
  label,
  maxH = 'max-h-52',
  accent = 'hover:border-cyan-500/50',
}: {
  wikiUrl: string;
  label?: string;
  maxH?: string;
  accent?: string;
}) {
  const [, forceUpdate] = useState(0);

  // Extract article title from URL
  const title = wikiUrl.replace(/^https?:\/\/[^/]+\/wiki\//, '');

  useEffect(() => {
    if (!title || _cache[title]?.done) return;
    if (_cache[title]) return; // In-flight
    _cache[title] = { url: null, done: false };

    fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title)}`)
      .then((r) => r.json())
      .then((d) => {
        _cache[title] = { url: d.thumbnail?.source || d.originalimage?.source || null, done: true };
        forceUpdate((n) => n + 1);
      })
      .catch(() => {
        _cache[title] = { url: null, done: true };
        forceUpdate((n) => n + 1);
      });
  }, [title]);

  const cached = _cache[title];
  const imgUrl = cached?.url;
  const loading = cached && !cached.done;

  return (
    <div className="pb-2">
      {loading && (
        <div className={`w-full h-20 rounded bg-[var(--bg-tertiary)]/60 animate-pulse`} />
      )}
      {imgUrl && (
        <a href={wikiUrl} target="_blank" rel="noopener noreferrer" className="block">
          <ExternalImage
            src={imgUrl}
            alt={label || title.replace(/_/g, ' ')}
            width={640}
            height={360}
            className={`w-full h-auto ${maxH} object-contain rounded border border-[var(--border-primary)]/50 ${accent} transition-colors`}
            style={{ width: '100%', height: 'auto' }}
          />
        </a>
      )}
      <a
        href={wikiUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="text-[10px] text-cyan-400 hover:text-cyan-300 underline mt-1 inline-block font-mono"
      >
        📖 {label || title.replace(/_/g, ' ')} — Wikipedia →
      </a>
    </div>
  );
}
