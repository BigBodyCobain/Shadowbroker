'use client';

import React, { useState, useMemo, useCallback, useRef } from 'react';
import { Ruler, Trash2 } from 'lucide-react';

/**
 * Dynamic Scale Bar with:
 *   1. Auto-scaling distance display based on zoom level
 *   2. Draggable right edge to manually resize the ruler
 *   3. Measurement mode toggle — lets the user place up to 3 waypoints on the map
 */

const MILES_PER_METER = 0.000621371;
const KM_PER_METER = 0.001;

/** Metres per pixel at a given zoom & latitude (Web Mercator). */
function metersPerPixel(zoom: number, latitude: number) {
  return (156543.03392 * Math.cos((latitude * Math.PI) / 180)) / Math.pow(2, zoom);
}

/** Format a metric distance nicely. */
function fmtMetric(km: number) {
  return km >= 1 ? `${km.toFixed(km < 10 ? 1 : 0)} km` : `${Math.round(km * 1000)} m`;
}
/** Format an imperial distance nicely. */
function fmtImperial(mi: number) {
  return mi >= 1 ? `${mi.toFixed(mi < 10 ? 1 : 0)} mi` : `${Math.round(mi * 5280)} ft`;
}

interface MeasurePoint {
  lat: number;
  lng: number;
}

interface ScaleBarProps {
  zoom: number;
  latitude: number;
  measureMode?: boolean;
  measurePoints?: MeasurePoint[];
  onToggleMeasure?: () => void;
  onClearMeasure?: () => void;
}

function ScaleBar({
  zoom,
  latitude,
  measureMode,
  measurePoints,
  onToggleMeasure,
  onClearMeasure,
}: ScaleBarProps) {
  const [unit, setUnit] = useState<'mi' | 'km'>('mi');
  const [barWidth, setBarWidth] = useState(120); // current bar width in px
  const dragging = useRef(false);
  const startX = useRef(0);
  const startW = useRef(0);

  const MIN_BAR = 60;
  const MAX_BAR = 280;

  // ── Draggable right edge ──
  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragging.current = true;
      startX.current = e.clientX;
      startW.current = barWidth;
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [barWidth],
  );

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return;
    const dx = e.clientX - startX.current;
    setBarWidth(Math.max(MIN_BAR, Math.min(MAX_BAR, startW.current + dx)));
  }, []);

  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  // ── Distance label for the current bar width ──
  const scaleLabel = useMemo(() => {
    const mpp = metersPerPixel(zoom, latitude);
    const totalMeters = mpp * barWidth;
    if (unit === 'km') {
      return fmtMetric(totalMeters * KM_PER_METER);
    } else {
      return fmtImperial(totalMeters * MILES_PER_METER);
    }
  }, [zoom, latitude, barWidth, unit]);

  // ── Measurement distances ──
  const segmentDistances = useMemo(() => {
    if (!measurePoints || measurePoints.length < 2) return [];
    const dists: string[] = [];
    let total = 0;
    for (let i = 1; i < measurePoints.length; i++) {
      const d = haversine(measurePoints[i - 1], measurePoints[i]);
      total += d;
      if (unit === 'km') dists.push(fmtMetric(d / 1000));
      else dists.push(fmtImperial(d * MILES_PER_METER));
    }
    if (measurePoints.length > 2) {
      if (unit === 'km') dists.push(`Σ ${fmtMetric(total / 1000)}`);
      else dists.push(`Σ ${fmtImperial(total * MILES_PER_METER)}`);
    }
    return dists;
  }, [measurePoints, unit]);

  return (
    <div className="flex items-end gap-3 select-none">
      {/* Scale ruler */}
      <div className="flex flex-col items-start">
        <div
          className="flex items-end relative"
          style={{ width: barWidth }}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        >
          {/* Left tick */}
          <div className="w-px h-2.5 bg-cyan-400 flex-shrink-0" />
          {/* Bar */}
          <div
            className="flex-1 h-px bg-cyan-400 relative"
            style={{ boxShadow: '0 0 6px rgba(0,255,255,0.3)' }}
          >
            {/* Graduation marks */}
            <div className="absolute left-1/4 top-0 w-px h-1.5 bg-cyan-400/50" />
            <div className="absolute left-1/2 top-0 w-px h-2 bg-cyan-400/70" />
            <div className="absolute left-3/4 top-0 w-px h-1.5 bg-cyan-400/50" />
          </div>
          {/* Draggable right tick */}
          <div
            className="w-2 h-3 bg-cyan-400/80 rounded-r cursor-ew-resize flex-shrink-0 hover:bg-cyan-300 transition-colors"
            onPointerDown={onPointerDown}
            title="Drag to resize scale"
            style={{ touchAction: 'none' }}
          />
        </div>
        <span className="text-[9px] font-mono text-cyan-300 tracking-widest mt-0.5">
          {scaleLabel}
        </span>
      </div>

      {/* Unit toggle */}
      <button
        onClick={() => setUnit((u) => (u === 'mi' ? 'km' : 'mi'))}
        className="text-[8px] font-mono tracking-widest px-1.5 py-0.5 rounded border border-[var(--border-primary)] hover:border-cyan-500/50 text-[var(--text-muted)] hover:text-cyan-400 transition-all hover:bg-cyan-950/20 uppercase"
        title={`Switch to ${unit === 'mi' ? 'Metric (km)' : 'Imperial (mi)'}`}
      >
        {unit === 'mi' ? 'MI' : 'KM'}
      </button>

      {/* Measure mode toggle */}
      <button
        onClick={onToggleMeasure}
        className={`flex items-center gap-1 text-[8px] font-mono tracking-widest px-2 py-0.5 rounded border transition-all ${
          measureMode
            ? 'border-cyan-500/60 text-cyan-400 bg-cyan-950/30 shadow-[0_0_8px_rgba(0,255,255,0.2)]'
            : 'border-[var(--border-primary)] text-[var(--text-muted)] hover:text-cyan-400 hover:border-cyan-500/50 hover:bg-cyan-950/20'
        }`}
        title={measureMode ? 'Exit measurement mode' : 'Measure distance (click up to 3 points)'}
      >
        <Ruler size={10} />
        {measureMode ? 'MEASURING' : 'MEASURE'}
      </button>

      {/* Clear measurements */}
      {measureMode && measurePoints && measurePoints.length > 0 && (
        <button
          onClick={onClearMeasure}
          className="flex items-center gap-1 text-[8px] font-mono tracking-widest px-1.5 py-0.5 rounded border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-red-400 hover:border-red-500/50 hover:bg-red-950/20 transition-all"
          title="Clear all waypoints"
        >
          <Trash2 size={10} />
        </button>
      )}

      {/* Segment distances readout */}
      {segmentDistances.length > 0 && (
        <div className="flex items-center gap-2 ml-1">
          {segmentDistances.map((d, i) => (
            <span
              key={i}
              className={`text-[9px] font-mono tracking-wider px-1.5 py-0.5 rounded border ${
                d.startsWith('Σ')
                  ? 'border-cyan-500/50 text-cyan-300 bg-cyan-950/30'
                  : 'border-[var(--border-primary)] text-[var(--text-secondary)]'
              }`}
            >
              {d}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Haversine distance in meters between two lat/lng points. */
function haversine(a: MeasurePoint, b: MeasurePoint): number {
  const R = 6371000;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const sa = Math.sin(dLat / 2);
  const sb = Math.sin(dLng / 2);
  const h =
    sa * sa + Math.cos((a.lat * Math.PI) / 180) * Math.cos((b.lat * Math.PI) / 180) * sb * sb;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export default React.memo(ScaleBar);
