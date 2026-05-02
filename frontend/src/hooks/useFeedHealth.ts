/**
 * useFeedHealth — derives live feed health from the data store.
 *
 * Tracks how many entities are in each data category and how fresh the data is.
 * Returns compact stats for the bottom status bar.
 */
import { useRef, useMemo } from 'react';
import { useDataKeys } from './useDataStore';
import type { DashboardData, NewsArticle } from '@/types/dashboard';

type FeedStatus = 'healthy' | 'stale' | 'offline';

interface FeedInfo {
  label: string;
  count: string; // formatted count e.g. "12.4K"
  status: FeedStatus;
}

function formatCount(n: number): string {
  if (n >= 10000) return `${(n / 1000).toFixed(1)}K`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

function arrayLen(v: unknown): number {
  return Array.isArray(v) ? v.length : 0;
}

export function useFeedHealth(): FeedInfo[] {
  const data = useDataKeys([
    'commercial_flights',
    'private_flights',
    'military_flights',
    'private_jets',
    'tracked_flights',
    'ships',
    'news',
    'satellites',
  ] as const satisfies readonly (keyof DashboardData)[]);

  // Track last-seen timestamps per feed
  const timestamps = useRef<Record<string, number>>({});
  const now = Date.now();

  // Update timestamps when data changes
  const feeds = useMemo(() => {
    const adsb =
      arrayLen(data.commercial_flights) +
      arrayLen(data.private_flights) +
      arrayLen(data.military_flights) +
      arrayLen(data.private_jets) +
      arrayLen(data.tracked_flights);

    const ais = arrayLen(data.ships);

    // Count unique news sources
    const newsArr = Array.isArray(data.news) ? data.news : [];
    const newsSources = new Set(newsArr.map((n: NewsArticle) => n.source).filter(Boolean));

    const sats = arrayLen(data.satellites);

    // Update timestamps
    if (adsb > 0) timestamps.current.adsb = now;
    if (ais > 0) timestamps.current.ais = now;
    if (newsArr.length > 0) timestamps.current.news = now;
    if (sats > 0) timestamps.current.sats = now;

    function getStatus(key: string, count: number): FeedStatus {
      if (count === 0) return 'offline';
      const lastSeen = timestamps.current[key] || 0;
      const age = now - lastSeen;
      if (age > 120_000) return 'offline';
      if (age > 30_000) return 'stale';
      return 'healthy';
    }

    return [
      { label: 'ADS-B', count: formatCount(adsb), status: getStatus('adsb', adsb) },
      { label: 'AIS', count: formatCount(ais), status: getStatus('ais', ais) },
      { label: 'NEWS', count: String(newsSources.size), status: getStatus('news', newsArr.length) },
      { label: 'SAT', count: formatCount(sats), status: getStatus('sats', sats) },
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  return feeds;
}
