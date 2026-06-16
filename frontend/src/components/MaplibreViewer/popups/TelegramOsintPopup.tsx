'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Popup } from 'react-map-gl/maplibre';
import { Radio } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { TELEGRAM_MARKER_OFFSET } from '@/components/map/geoJSONBuilders';
import { buildTelegramMediaProxyUrl } from '@/lib/telegramProxy';
import type { TelegramOsintPost } from '@/types/dashboard';

export interface TelegramOsintPopupProps {
  posts: TelegramOsintPost[];
  lat: number;
  lng: number;
  onClose: () => void;
}

function formatTime(pubDate?: string) {
  if (!pubDate) return '';
  try {
    return new Date(pubDate).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function riskTheme(rs: number) {
  if (rs >= 9) {
    return {
      hex: '#ef4444',
      threatColor: 'text-red-400',
      borderColor: 'border-red-700',
      bgHeaderColor: 'bg-red-950/50',
      bgClass: 'bg-red-950/20 border-red-500/30',
      titleClass: 'text-cyan-300 font-bold',
      badgeClass: 'bg-red-500/10 text-red-400 border-red-500/30',
    };
  }
  if (rs >= 7) {
    return {
      hex: '#f97316',
      threatColor: 'text-orange-400',
      borderColor: 'border-orange-700',
      bgHeaderColor: 'bg-orange-950/50',
      bgClass: 'bg-orange-950/20 border-orange-500/30',
      titleClass: 'text-cyan-300 font-bold',
      badgeClass: 'bg-orange-500/10 text-orange-400 border-orange-500/30',
    };
  }
  if (rs >= 4) {
    return {
      hex: '#eab308',
      threatColor: 'text-yellow-400',
      borderColor: 'border-yellow-800',
      bgHeaderColor: 'bg-yellow-950/50',
      bgClass: 'bg-yellow-950/20 border-yellow-500/30',
      titleClass: 'text-cyan-300 font-bold',
      badgeClass: 'bg-yellow-500/10 text-yellow-500 border-yellow-500/30',
    };
  }
  return {
    hex: '#22c55e',
    threatColor: 'text-green-400',
    borderColor: 'border-green-800',
    bgHeaderColor: 'bg-green-950/50',
    bgClass: 'bg-green-950/20 border-green-500/30',
    titleClass: 'text-cyan-300 font-medium',
    badgeClass: 'bg-green-500/10 text-green-400 border-green-500/30',
  };
}

const CYRILLIC_RE = /[\u0400-\u04FF]/;

function containsCyrillic(text: string): boolean {
  return CYRILLIC_RE.test(text);
}

function sourceLangLabel(post: TelegramOsintPost): string {
  if (post.source_lang_label) return post.source_lang_label;
  const code = String(post.source_lang || '').trim().toLowerCase();
  const labels: Record<string, string> = {
    uk: 'Ukrainian',
    ru: 'Russian',
    en: 'English',
    ar: 'Arabic',
    he: 'Hebrew',
    'zh-cn': 'Chinese',
    fr: 'French',
    de: 'German',
    pl: 'Polish',
  };
  return labels[code] || code.toUpperCase();
}

function hasTranslation(post: TelegramOsintPost): boolean {
  const translated = String(post.title_translated || post.description_translated || '').trim();
  const original = String(post.title || post.description || '').trim();
  return Boolean(translated && translated !== original);
}

function postHeadline(post: TelegramOsintPost, showOriginal: boolean): string {
  const original = String(post.title || post.description || 'Telegram intercept').trim();
  const translated = String(post.title_translated || post.description_translated || '').trim();
  if (!showOriginal && translated) {
    return translated.split('\n', 1)[0].trim();
  }
  if (!showOriginal && containsCyrillic(original) && translated) {
    return translated.split('\n', 1)[0].trim();
  }
  return original;
}

function postDetail(post: TelegramOsintPost, showOriginal: boolean): string | null {
  if (!showOriginal && post.description_translated) {
    const translatedTitle = String(post.title_translated || '').trim();
    const translatedBody = String(post.description_translated || '').trim();
    if (!translatedBody || translatedBody === translatedTitle) return null;
    const extra = translatedBody.startsWith(translatedTitle)
      ? translatedBody.slice(translatedTitle.length).trim()
      : translatedBody;
    return extra || null;
  }

  const title = String(post.title || '').trim();
  const description = String(post.description || '').trim();
  if (!description || description === title || description.startsWith(title)) return null;
  const extra = description.startsWith(title) ? description.slice(title.length).trim() : description;
  return extra || null;
}

function TelegramPostMedia({ post }: { post: TelegramOsintPost }) {
  const { t } = useTranslation();
  const proxyUrl = post.media_url ? buildTelegramMediaProxyUrl(post.media_url) : null;

  let media: React.ReactNode = null;
  if (post.media_type === 'video' && proxyUrl) {
    media = (
      <video
        src={proxyUrl}
        controls
        playsInline
        preload="metadata"
        className="w-full max-h-52 bg-black"
      />
    );
  } else if (post.media_type === 'photo' && proxyUrl) {
    media = (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={proxyUrl} alt="" className="w-full max-h-52 object-contain bg-black" />
    );
  } else if (post.embed_url) {
    media = (
      <iframe
        src={post.embed_url}
        title={t('telegram.embedTitle')}
        className="w-full"
        height={240}
        style={{ border: 'none' }}
        loading="lazy"
        referrerPolicy="no-referrer"
      />
    );
  }

  if (!media) return null;

  return (
    <div className="mt-2 rounded-sm border border-cyan-900/40 overflow-hidden bg-black/70">
      {media}
    </div>
  );
}

function TelegramPostCard({ post }: { post: TelegramOsintPost }) {
  const { t } = useTranslation();
  const [showOriginal, setShowOriginal] = useState(false);
  const rs = post.risk_score ?? 1;
  const theme = riskTheme(rs);
  const translated = hasTranslation(post);
  const headline = postHeadline(post, showOriginal);
  const detail = postDetail(post, showOriginal);
  const isHigh = rs >= 8;

  return (
    <article
      className={`p-2 rounded-sm border-l-[2px] border-r border-t border-b ${theme.bgClass} flex flex-col gap-1`}
    >
      <div className="flex items-center justify-between text-[12px] text-[var(--text-secondary)] uppercase tracking-widest">
        <span className="font-bold flex items-center gap-1 text-white">
          {isHigh && <span className="text-red-400 mr-1">BREAKING</span>}
          &gt;_ {post.source || 'TELEGRAM'}
        </span>
        <span>[{formatTime(post.published)}]</span>
      </div>

      <h3 className={`text-[12px] leading-tight ${theme.titleClass}`}>{headline}</h3>

      {detail ? (
        <p className="text-[11px] text-[var(--text-muted)] leading-relaxed whitespace-pre-wrap">{detail}</p>
      ) : null}

      {translated && !showOriginal && post.source_lang ? (
        <p className="text-[10px] text-cyan-700/80 uppercase tracking-wider">
          {t('telegram.translatedFrom').replace('{lang}', sourceLangLabel(post))}
        </p>
      ) : null}

      <TelegramPostMedia post={post} />

      <div className="flex items-center gap-1.5 mt-1 flex-wrap">
        <span className={`text-[11px] font-bold font-mono px-1.5 py-0.5 rounded-sm border ${theme.badgeClass}`}>
          {isHigh ? 'BREAKING' : `LVL: ${rs}/10`}
        </span>
        {translated ? (
          <button
            type="button"
            onClick={() => setShowOriginal((prev) => !prev)}
            className="text-[11px] font-mono text-cyan-600 hover:text-cyan-300 transition-colors"
          >
            {showOriginal
              ? t('telegram.showTranslation')
              : t('telegram.showOriginal').replace('{lang}', sourceLangLabel(post))}
          </button>
        ) : null}
        {post.link ? (
          <a
            href={post.link}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px] font-mono text-cyan-500 hover:text-cyan-300 transition-colors"
          >
            {t('telegram.openOriginal')}
          </a>
        ) : null}
      </div>
    </article>
  );
}

export function TelegramOsintPopup({ posts, lat, lng, onClose }: TelegramOsintPopupProps) {
  const { t, locale } = useTranslation();
  const [localizedPosts, setLocalizedPosts] = useState(posts);

  useEffect(() => {
    setLocalizedPosts(posts);
  }, [posts]);

  useEffect(() => {
    const needsLocalizedFeed = posts.some((post) => !hasTranslation(post));
    if (!needsLocalizedFeed) {
      return;
    }

    let cancelled = false;
    const controller = new AbortController();

    fetch(`/api/telegram-feed?lang=${encodeURIComponent(locale)}`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (cancelled || !payload?.posts) return;
        const byId = new Map(
          (payload.posts as TelegramOsintPost[]).map((post) => [post.id, post]),
        );
        setLocalizedPosts(posts.map((post) => byId.get(post.id) || post));
      })
      .catch(() => {
        /* keep feed posts when locale translation fetch fails */
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [locale, posts]);

  const sortedPosts = useMemo(
    () =>
      [...localizedPosts].sort(
        (a, b) =>
          (b.risk_score ?? 0) - (a.risk_score ?? 0) ||
          String(b.published || '').localeCompare(String(a.published || '')),
      ),
    [localizedPosts],
  );

  const maxRisk = sortedPosts[0]?.risk_score ?? 1;
  const header = riskTheme(maxRisk);

  return (
    <Popup
      longitude={lng}
      latitude={lat}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      anchor="bottom"
      offset={TELEGRAM_MARKER_OFFSET}
      className="threat-popup"
      maxWidth="560px"
    >
      <div
        className={`bg-[#080c12] border ${header.borderColor} rounded-lg flex flex-col font-mono overflow-hidden w-[min(520px,92vw)]`}
        style={{
          boxShadow: `0 0 60px ${header.hex}33, 0 0 160px ${header.hex}11, inset 0 1px 0 rgba(255,255,255,0.05)`,
        }}
      >
        <div
          className={`px-4 py-3 border-b ${header.borderColor}/60 ${header.bgHeaderColor} flex justify-between items-center shrink-0`}
        >
          <div className="flex items-center gap-2">
            <Radio size={16} className={header.threatColor} />
            <span className={`text-[13px] tracking-[0.25em] font-bold ${header.threatColor}`}>
              TELEGRAM INTERCEPT
            </span>
            {maxRisk >= 8 && (
              <span className="text-[9px] bg-red-500 text-white px-2 py-0.5 rounded-sm font-bold animate-pulse">
                LIVE
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className={`text-[12px] ${header.threatColor} font-bold`}>
              ALERT LVL: {maxRisk}/10
            </span>
            <button
              type="button"
              onClick={onClose}
              className="text-[var(--text-secondary)] hover:text-white text-lg leading-none px-1 hover:bg-white/10 rounded transition-colors"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="px-3 py-2 border-b border-cyan-900/40 bg-black/40 shrink-0">
          <div className="text-[11px] text-[var(--text-muted)] uppercase tracking-widest mb-1">
            {t('telegram.postsAtLocation').replace('{count}', String(sortedPosts.length))}
          </div>
          <div className="p-2 bg-black/60 border border-amber-700/40 rounded-sm text-[11px] text-amber-100/90 leading-relaxed relative overflow-hidden">
            <div className="absolute top-0 left-0 w-[2px] h-full bg-amber-500/80" />
            <span className="font-bold text-amber-300">&gt;_ SYS.NOTICE: </span>
            {t('telegram.disclaimer')}
          </div>
        </div>

        <div className="overflow-y-auto styled-scrollbar flex flex-col gap-2 p-3 max-h-[min(420px,55vh)]">
          {sortedPosts.map((post) => (
            <TelegramPostCard key={post.id} post={post} />
          ))}
        </div>
      </div>
    </Popup>
  );
}