/**
 * useWatchlist — persistent entity watchlist with live data updates.
 *
 * Allows users to pin entities (flights, ships, news) for persistent tracking.
 * Persisted to localStorage. Max 10 items.
 */
import { useState, useEffect, useCallback } from 'react';

export interface WatchlistEntry {
  id: string;
  type: 'flight' | 'ship' | 'news' | 'satellite' | string;
  name: string;
  lat: number;
  lng: number;
  addedAt: number;
  // Live stats (updated externally)
  altitude?: number;
  speed?: number;
  heading?: number;
  risk_score?: number;
}

const STORAGE_KEY = 'sb_watchlist';
const MAX_ITEMS = 10;

function loadWatchlist(): WatchlistEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as WatchlistEntry[];
  } catch {
    return [];
  }
}

function saveWatchlist(items: WatchlistEntry[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

export function useWatchlist() {
  const [items, setItems] = useState<WatchlistEntry[]>(() => loadWatchlist());

  // Persist on change
  useEffect(() => {
    saveWatchlist(items);
  }, [items]);

  const addToWatchlist = useCallback((entry: WatchlistEntry) => {
    setItems((prev) => {
      // Don't add duplicates
      if (prev.some((e) => e.id === entry.id)) return prev;
      // FIFO overflow
      const next = [entry, ...prev];
      if (next.length > MAX_ITEMS) next.pop();
      return next;
    });
  }, []);

  const removeFromWatchlist = useCallback((id: string) => {
    setItems((prev) => prev.filter((e) => e.id !== id));
  }, []);

  const isWatched = useCallback(
    (id: string) => items.some((e) => e.id === id),
    [items],
  );

  const clearWatchlist = useCallback(() => {
    setItems([]);
  }, []);

  return { items, addToWatchlist, removeFromWatchlist, isWatched, clearWatchlist };
}
