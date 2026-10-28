'use client';
import React, { useState, useEffect } from 'react';
import ExternalImage from '@/components/ExternalImage';
import { fetchWikipediaSummary } from '@/lib/wikimediaClient';

/**
 * WikiImage — displays a Wikipedia thumbnail for a given article URL.
 *
 * Issue #220 (tg12): this component previously had its own
 * module-local Wikipedia fetch + cache. It now delegates to
 * `lib/wikimediaClient`, which sends the policy-compliant
 * `Api-User-Agent` header and shares one cache across every UI
 * component that asks Wikipedia for an article summary (WikiImage,
 * NewsFeed, useRegionDossier).
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
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Extract article title from URL
  const rawTitle = wikiUrl.replace(/^https?:\/\/[^/]+\/wiki\//, '');
  let title = rawTitle;
  try {
    title = decodeURIComponent(rawTitle);
  } catch {
    // Keep malformed legacy references usable as plain article titles.
  }

  useEffect(() => {
    let cancelled = false;
    if (!title) {
      setImgUrl(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchWikipediaSummary(title).then((summary) => {
      if (cancelled) return;
      setImgUrl(summary?.thumbnail || null);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [title]);

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
