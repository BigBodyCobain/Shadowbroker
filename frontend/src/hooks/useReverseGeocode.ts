import { useCallback, useEffect, useState, useRef } from 'react';
import {
  GEOCODE_THROTTLE_MS,
  GEOCODE_DISTANCE_THRESHOLD,
  GEOCODE_CACHE_SIZE,
} from '@/lib/constants';
import { API_BASE } from '@/lib/api';

const REVERSE_GEOCODE_TIMEOUT_MS = 1200;
const REVERSE_GEOCODE_MIN_INTERVAL_MS = 2500;
const REVERSE_GEOCODE_GRID_DECIMALS = 1;
const MOUSE_COORDS_UI_INTERVAL_MS = 80;
const MOUSE_COORDS_DISPLAY_DECIMALS = 4;

async function fetchJsonWithTimeout(url: string, timeoutMs: number, signal?: AbortSignal) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  if (signal) signal.addEventListener('abort', onAbort, { once: true });
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    window.clearTimeout(timeout);
    if (signal) signal.removeEventListener('abort', onAbort);
  }
}

export function useReverseGeocode() {
  const [mouseCoords, setMouseCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [locationLabel, setLocationLabel] = useState('');
  const geocodeCache = useRef<Map<string, string>>(new Map());
  const geocodeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const coordsUiTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastGeocodedPos = useRef<{ lat: number; lng: number } | null>(null);
  const geocodeAbort = useRef<AbortController | null>(null);
  const lastRequestAt = useRef(0);
  const lastUiCoordsKey = useRef('');
  const pendingUiCoords = useRef<{ lat: number; lng: number } | null>(null);

  useEffect(() => {
    return () => {
      if (geocodeTimer.current) clearTimeout(geocodeTimer.current);
      if (coordsUiTimer.current) clearTimeout(coordsUiTimer.current);
      if (geocodeAbort.current) geocodeAbort.current.abort();
    };
  }, []);

  const handleMouseCoords = useCallback((coords: { lat: number; lng: number }) => {
    pendingUiCoords.current = coords;
    if (!coordsUiTimer.current) {
      coordsUiTimer.current = setTimeout(() => {
        coordsUiTimer.current = null;
        const next = pendingUiCoords.current;
        if (!next) return;
        const uiKey = `${next.lat.toFixed(MOUSE_COORDS_DISPLAY_DECIMALS)},${next.lng.toFixed(MOUSE_COORDS_DISPLAY_DECIMALS)}`;
        if (uiKey === lastUiCoordsKey.current) return;
        lastUiCoordsKey.current = uiKey;
        setMouseCoords(next);
      }, MOUSE_COORDS_UI_INTERVAL_MS);
    }

    if (geocodeTimer.current) clearTimeout(geocodeTimer.current);
    geocodeTimer.current = setTimeout(async () => {
      if (lastGeocodedPos.current) {
        const dLat = Math.abs(coords.lat - lastGeocodedPos.current.lat);
        const dLng = Math.abs(coords.lng - lastGeocodedPos.current.lng);
        if (dLat < GEOCODE_DISTANCE_THRESHOLD && dLng < GEOCODE_DISTANCE_THRESHOLD) return;
      }

      const gridKey = `${coords.lat.toFixed(REVERSE_GEOCODE_GRID_DECIMALS)},${coords.lng.toFixed(REVERSE_GEOCODE_GRID_DECIMALS)}`;
      const cached = geocodeCache.current.get(gridKey);
      if (cached) {
        setLocationLabel(cached);
        lastGeocodedPos.current = coords;
        return;
      }

      const now = Date.now();
      if (now - lastRequestAt.current < REVERSE_GEOCODE_MIN_INTERVAL_MS) return;
      lastRequestAt.current = now;

      if (geocodeAbort.current) geocodeAbort.current.abort();
      geocodeAbort.current = new AbortController();

      try {
        const data = await fetchJsonWithTimeout(
          `${API_BASE}/api/geocode/reverse?lat=${coords.lat}&lng=${coords.lng}&local_only=1`,
          REVERSE_GEOCODE_TIMEOUT_MS,
          geocodeAbort.current.signal,
        );
        const label = data?.label || 'Unknown';

        if (geocodeCache.current.size > GEOCODE_CACHE_SIZE) {
          const iter = geocodeCache.current.keys();
          for (let i = 0; i < 100; i++) {
            const key = iter.next().value;
            if (key !== undefined) geocodeCache.current.delete(key);
          }
        }
        geocodeCache.current.set(gridKey, label);
        setLocationLabel(label);
        lastGeocodedPos.current = coords;
      } catch (err) {
        const isAbort =
          typeof err === 'object' &&
          err !== null &&
          'name' in err &&
          (err as { name?: string }).name === 'AbortError';
        if (!isAbort) {
          /* Silently fail - keep last label */
        }
      }
    }, GEOCODE_THROTTLE_MS);
  }, []);

  return { mouseCoords, locationLabel, handleMouseCoords };
}
