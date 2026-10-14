import type { Ship } from '@/types/dashboard';

/**
 * Feature ids shared by the worker that builds map icons and the main-thread
 * code that picks label subjects, so both sides agree on which record a
 * feature represents. Records with no identifier get the worker's positional
 * fallback, which cannot be matched from outside and so draw no label.
 */
export function trackedFlightFeatureId(
  f: { icao24?: string; callsign?: string },
  fallback = '',
): string {
  return f.icao24 || f.callsign || fallback;
}

export function shipFeatureId(s: Pick<Ship, 'mmsi' | 'name'>, fallback = ''): string {
  return String(s.mmsi || s.name || fallback);
}
