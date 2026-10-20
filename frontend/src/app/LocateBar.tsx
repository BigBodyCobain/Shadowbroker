'use client';

import { useState, useEffect, useRef } from 'react';
import { API_BASE } from '@/lib/api';
import { NOMINATIM_DEBOUNCE_MS } from '@/lib/constants';
import {
  parseCoordinateInput,
  boundsForCoordinate,
  sanitizeGeocodeBbox,
  boundsForPlaceRank,
  type Bounds,
} from '@/lib/mapZoom';

type LocateResult = {
  label: string;
  lat: number;
  lng: number;
  bounds?: Bounds;
};

/* ── LOCATE BAR ── coordinate / place-name search above bottom status bar ── */
export function LocateBar({ onLocate, onOpenChange }: { onLocate: (lat: number, lng: number, bounds?: Bounds) => void; onOpenChange?: (open: boolean) => void }) {
  const [open, setOpen] = useState(false);

  useEffect(() => { onOpenChange?.(open); }, [open]);
  const [value, setValue] = useState('');
  const [results, setResults] = useState<LocateResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchAbortRef = useRef<AbortController | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Close when clicking outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setValue('');
        setResults([]);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleSearch = async (q: string) => {
    setValue(q);
    // Check for raw coordinates first
    const coords = parseCoordinateInput(q);
    if (coords) {
      setResults([{
        label: `${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)}`,
        lat: coords.lat,
        lng: coords.lng,
        bounds: boundsForCoordinate(coords.lat, coords.lng, coords.decimals),
      }]);
      return;
    }
    // Geocode with Nominatim (debounced)
    if (timerRef.current) clearTimeout(timerRef.current);
    if (searchAbortRef.current) searchAbortRef.current.abort();
    if (q.trim().length < 2) {
      setResults([]);
      setSearchError(null);
      return;
    }
    timerRef.current = setTimeout(async () => {
      setLoading(true);
      setSearchError(null);
      searchAbortRef.current = new AbortController();
      const signal = searchAbortRef.current.signal;
      try {
        const res = await fetch(
          `${API_BASE}/api/geocode/search?q=${encodeURIComponent(q)}&limit=5`,
          { signal },
        );
        if (res.ok) {
          const data = await res.json();
          const mapped: LocateResult[] = (data?.results || []).map(
            (r: {
              label: string; lat: number; lng: number;
              bbox?: string[]; place_rank?: number;
            }) => ({
              label: r.label,
              lat: r.lat,
              lng: r.lng,
              // A usable bbox frames the real thing; otherwise fall back to
              // the rank's typical extent, which is the only honest answer
              // for Tokyo prefecture, France and bare OSM nodes.
              bounds:
                sanitizeGeocodeBbox(r.bbox, r.lat, r.lng) ??
                boundsForPlaceRank(r.lat, r.lng, r.place_rank),
            }),
          );
          setResults(mapped);
          if (mapped.length === 0) {
            setSearchError('No places found');
          }
        } else {
          console.warn(`[Locate] Geocode proxy HTTP ${res.status}`);
          setResults([]);
          setSearchError('Place search unavailable — check backend connection');
        }
      } catch (err) {
        if ((err as Error)?.name !== 'AbortError') {
          console.warn('[Locate] Geocode proxy failed:', err);
          setResults([]);
          setSearchError('Place search unavailable — check backend connection');
        }
      } finally {
        setLoading(false);
      }
    }, NOMINATIM_DEBOUNCE_MS);
  };

  const handleSelect = (r: LocateResult) => {
    onLocate(r.lat, r.lng, r.bounds);
    setOpen(false);
    setValue('');
    setResults([]);
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 bg-[var(--bg-primary)]/80 border border-[var(--border-primary)] px-5 py-2 text-[11px] font-mono tracking-[0.15em] text-[var(--text-muted)] hover:text-cyan-400 hover:border-cyan-800 transition-colors"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="13"
          height="13"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        LOCATE
      </button>
    );
  }

  return (
    <div ref={containerRef} className="relative w-[520px]">
      <div className="flex items-center gap-2 bg-[var(--bg-primary)] border border-cyan-800/60 px-4 py-2.5 shadow-[0_0_20px_rgba(0,255,255,0.1)]">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-cyan-500 flex-shrink-0"
        >
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => handleSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setOpen(false);
              setValue('');
              setResults([]);
            }
            if (e.key === 'Enter' && results.length > 0) handleSelect(results[0]);
          }}
          placeholder="Enter coordinates (31.8, 34.8) or place name..."
          className="flex-1 bg-transparent text-[12px] text-[var(--text-primary)] font-mono tracking-wider outline-none placeholder:text-[var(--text-muted)]"
        />
        {loading && (
          <div className="w-3 h-3 border border-cyan-500 border-t-transparent rounded-full animate-spin" />
        )}
        <button
          onClick={() => {
            setOpen(false);
            setValue('');
            setResults([]);
          }}
          className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="10"
            height="10"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M18 6 6 18" />
            <path d="m6 6 12 12" />
          </svg>
        </button>
      </div>
      {searchError && results.length === 0 && !loading && value.trim().length >= 2 && (
        <div className="absolute bottom-full left-0 right-0 mb-1 bg-[var(--bg-secondary)] border border-amber-800/50 px-3 py-2 text-[10px] font-mono text-amber-200/90">
          {searchError}
        </div>
      )}
      {results.length > 0 && (
        <div className="absolute bottom-full left-0 right-0 mb-1 bg-[var(--bg-secondary)] border border-[var(--border-primary)] overflow-hidden shadow-[0_-8px_30px_rgba(0,0,0,0.4)] max-h-[200px] overflow-y-auto styled-scrollbar">
          {results.map((r, i) => (
            <button
              key={`${r.label}-${r.lat}-${r.lng}`}
              onClick={() => handleSelect(r)}
              className="w-full text-left px-3 py-2 hover:bg-cyan-950/40 transition-colors border-b border-[var(--border-primary)]/50 last:border-0 flex items-center gap-2"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="10"
                height="10"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-cyan-500 flex-shrink-0"
              >
                <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
                <circle cx="12" cy="10" r="3" />
              </svg>
              <span className="text-[11px] text-[var(--text-secondary)] font-mono truncate">
                {r.label}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
