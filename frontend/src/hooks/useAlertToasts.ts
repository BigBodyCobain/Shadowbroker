/**
 * useAlertToasts — watches for new high-severity news items and surfaces toast notifications.
 *
 * Monitors the `news` data key for articles with risk_score >= 8.
 * Maintains a seen-set to avoid duplicate toasts.
 *
 * NOTE: auto-dismissal is owned by the `AlertToast` component (per-card
 * timer with pause-on-hover) — this hook used to schedule its own
 * dismiss timer, but that prevented the UI from pausing it. The hook
 * now only manages the toast queue + dedup; the component decides when
 * a toast goes away.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useDataKey } from './useDataStore';
import type { NewsArticle } from '@/types/dashboard';

export interface ToastItem {
  id: string;
  title: string;
  source: string;
  risk_score: number;
  lat: number;
  lng: number;
  timestamp: number; // when the toast was created
}

const TOAST_THRESHOLD = 8; // minimum risk_score to trigger a toast
const MAX_VISIBLE = 3;

export function useAlertToasts() {
  const news = useDataKey('news') as NewsArticle[] | undefined;
  const seenKeys = useRef(new Set<string>());
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Watch for new high-severity articles
  useEffect(() => {
    if (!news || !Array.isArray(news)) return;

    const newToasts: ToastItem[] = [];

    for (const article of news) {
      if ((article.risk_score || 0) < TOAST_THRESHOLD) continue;

      const key = `${article.title}|${article.source}`;
      if (seenKeys.current.has(key)) continue;
      seenKeys.current.add(key);

      newToasts.push({
        id: key,
        title: article.title,
        source: article.source,
        risk_score: article.risk_score,
        lat: article.lat || article.coords?.[0] || 0,
        lng: article.lng || article.coords?.[1] || 0,
        timestamp: Date.now(),
      });
    }

    if (newToasts.length > 0) {
      setToasts((prev) => {
        // Merge new toasts, keep only MAX_VISIBLE most recent
        const merged = [...newToasts, ...prev].slice(0, MAX_VISIBLE);
        return merged;
      });
    }
  }, [news]);

  return { toasts, dismiss };
}
