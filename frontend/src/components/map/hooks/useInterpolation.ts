'use client';

import { useCallback, useRef, useEffect, useState } from 'react';
import { interpolatePosition } from '@/utils/positioning';
import { INTERP_TICK_MS } from '@/lib/constants';

const UNBOUNDED_INTERP_SECONDS = Number.POSITIVE_INFINITY;

/**
 * Custom hook that provides position interpolation for flights, ships, and satellites.
 * Tracks elapsed time since last data refresh and provides helper functions
 * to smoothly animate entity positions between API updates.
 *
 * The interp functions read dtSeconds from a ref so their references stay stable.
 * This prevents 7 GeoJSON useMemos from re-firing every tick — GeoJSON only rebuilds
 * when source data actually changes (new API fetch), not on every interpolation tick.
 */
export function useInterpolation() {
  const dataTimestamp = useRef(Date.now());
  const dtRef = useRef(0);
  const [interpTick, setInterpTick] = useState(0);

  // Update dtSeconds on each tick and bump a lightweight counter so moving
  // layers actually rebuild between backend refreshes.
  useEffect(() => {
    const iv = setInterval(() => {
      dtRef.current = (Date.now() - dataTimestamp.current) / 1000;
      setInterpTick((tick) => tick + 1);
    }, INTERP_TICK_MS);
    return () => clearInterval(iv);
  }, []);

  /** Call this when new data arrives to reset the interpolation baseline */
  const resetTimestamp = useCallback(() => {
    dataTimestamp.current = Date.now();
    dtRef.current = 0;
  }, []);

  /** Interpolate a flight's position if airborne and has speed + heading */
  const interpFlight = useCallback(
    (f: {
      lat: number;
      lng: number;
      speed_knots?: number | null;
      alt?: number | null;
      true_track?: number;
      heading?: number;
    }): [number, number] => {
      const dt = dtRef.current;
      if (!f.speed_knots || f.speed_knots <= 0 || dt <= 0) return [f.lng, f.lat];
      if (f.alt != null && f.alt <= 100) return [f.lng, f.lat];
      if (dt < 1) return [f.lng, f.lat];
      const heading = f.true_track || f.heading || 0;
      const [newLat, newLng] = interpolatePosition(
        f.lat,
        f.lng,
        heading,
        f.speed_knots,
        dt,
        0,
        UNBOUNDED_INTERP_SECONDS,
      );
      return [newLng, newLat];
    },
    [],
  );

  /** Interpolate a ship's position using SOG + COG */
  const interpShip = useCallback(
    (s: {
      lat: number;
      lng: number;
      sog?: number;
      cog?: number;
      heading?: number;
    }): [number, number] => {
      const dt = dtRef.current;
      if (typeof s.sog !== 'number' || !s.sog || s.sog <= 0 || dt <= 0)
        return [s.lng, s.lat];
      const heading = (typeof s.cog === 'number' ? s.cog : 0) || s.heading || 0;
      const [newLat, newLng] = interpolatePosition(
        s.lat,
        s.lng,
        heading,
        s.sog,
        dt,
        0,
        UNBOUNDED_INTERP_SECONDS,
      );
      return [newLng, newLat];
    },
    [],
  );

  /** Interpolate a satellite's position between API updates */
  const interpSat = useCallback(
    (s: { lat: number; lng: number; speed_knots?: number; heading?: number }): [number, number] => {
      const dt = dtRef.current;
      if (!s.speed_knots || s.speed_knots <= 0 || dt < 1) return [s.lng, s.lat];
      const [newLat, newLng] = interpolatePosition(
        s.lat,
        s.lng,
        s.heading || 0,
        s.speed_knots,
        dt,
        0,
        UNBOUNDED_INTERP_SECONDS,
      );
      return [newLng, newLat];
    },
    [],
  );

  return {
    interpFlight,
    interpShip,
    interpSat,
    interpTick,
    dtSeconds: dtRef,
    resetTimestamp,
    dataTimestamp,
  };
}
