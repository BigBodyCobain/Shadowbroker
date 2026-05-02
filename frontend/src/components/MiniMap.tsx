'use client';

import { useState, useEffect, useRef, useMemo } from 'react';
import { Minimize2 } from 'lucide-react';
import { useDataKey } from '@/hooks/useDataStore';
import type { NewsArticle } from '@/types/dashboard';

/**
 * MiniMap — lightweight world-overview inset showing current viewport position
 * and high-severity news dots. Uses canvas for performance.
 */

// Simple Plate Carrée projection
const MAP_W = 200;
const MAP_H = 100;

function latLngToXY(lat: number, lng: number): [number, number] {
  const x = ((lng + 180) / 360) * MAP_W;
  const y = ((90 - lat) / 180) * MAP_H;
  return [x, y];
}

// Simplified world coastline outline (major continental boundaries)
// Approximate hull points for each continent
const CONTINENTS: Array<[number, number][]> = [
  // North America
  [[72, -170], [72, -55], [48, -52], [25, -80], [15, -85], [15, -105], [30, -118], [48, -125], [60, -140], [72, -170]],
  // South America
  [[12, -70], [12, -35], [-5, -35], [-23, -42], [-55, -67], [-55, -75], [-15, -77], [0, -80], [12, -70]],
  // Europe
  [[72, -10], [72, 40], [55, 40], [47, 40], [38, 28], [36, -6], [43, -10], [48, -6], [55, -5], [72, -10]],
  // Africa
  [[37, -17], [37, 35], [30, 32], [12, 42], [-12, 44], [-34, 27], [-34, 18], [-5, 8], [5, -5], [15, -17], [37, -17]],
  // Asia
  [[72, 40], [72, 180], [55, 165], [30, 130], [22, 120], [8, 105], [1, 103], [22, 87], [25, 65], [30, 48], [42, 44], [47, 40], [55, 40], [72, 40]],
  // Australia
  [[-12, 130], [-12, 154], [-28, 154], [-38, 146], [-35, 117], [-20, 114], [-12, 130]],
];

function getRiskColor(score: number): string {
  if (score >= 9) return '#ef4444';
  if (score >= 7) return '#f97316';
  if (score >= 4) return '#eab308';
  return '#22d3ee';
}

export default function MiniMap() {
  const [collapsed, setCollapsed] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const news = useDataKey('news') as NewsArticle[] | undefined;

  const highSeverityDots = useMemo(() => {
    if (!news || !Array.isArray(news)) return [];
    return news
      .filter((n) => (n.risk_score || 0) >= 5 && (n.coords || (n.lat && n.lng)))
      .slice(0, 20)
      .map((n) => ({
        lat: n.coords?.[0] ?? n.lat,
        lng: n.coords?.[1] ?? n.lng,
        score: n.risk_score,
      }));
  }, [news]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = MAP_W * dpr;
    canvas.height = MAP_H * dpr;
    ctx.scale(dpr, dpr);

    // Clear
    ctx.clearRect(0, 0, MAP_W, MAP_H);

    // Background
    ctx.fillStyle = 'rgba(5, 10, 20, 0.9)';
    ctx.fillRect(0, 0, MAP_W, MAP_H);

    // Draw grid lines
    ctx.strokeStyle = 'rgba(6, 182, 212, 0.08)';
    ctx.lineWidth = 0.5;
    for (let lng = -180; lng <= 180; lng += 30) {
      const [x] = latLngToXY(0, lng);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, MAP_H);
      ctx.stroke();
    }
    for (let lat = -90; lat <= 90; lat += 30) {
      const [, y] = latLngToXY(lat, 0);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(MAP_W, y);
      ctx.stroke();
    }

    // Draw continents
    ctx.strokeStyle = 'rgba(6, 182, 212, 0.25)';
    ctx.fillStyle = 'rgba(6, 182, 212, 0.04)';
    ctx.lineWidth = 0.8;
    for (const continent of CONTINENTS) {
      ctx.beginPath();
      for (let i = 0; i < continent.length; i++) {
        const [x, y] = latLngToXY(continent[i][0], continent[i][1]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }

    // Draw news threat dots
    for (const dot of highSeverityDots) {
      const [x, y] = latLngToXY(dot.lat, dot.lng);
      const color = getRiskColor(dot.score);

      // Outer glow
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fillStyle = color + '40';
      ctx.fill();

      // Inner dot
      ctx.beginPath();
      ctx.arc(x, y, 1.5, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    }

    // Border
    ctx.strokeStyle = 'rgba(6, 182, 212, 0.2)';
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, MAP_W - 1, MAP_H - 1);
  }, [highSeverityDots, collapsed]);

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="absolute bottom-[6.5rem] right-[28rem] z-[200] pointer-events-auto px-2 py-1 bg-[var(--bg-panel)] border border-[var(--border-primary)] rounded-sm text-[9px] font-mono tracking-[0.15em] text-cyan-400 hover:border-cyan-600/40 transition-colors"
      >
        MAP
      </button>
    );
  }

  return (
    <div
      className="absolute bottom-[6.5rem] right-[28rem] z-[200] pointer-events-auto"
      style={{
        width: MAP_W,
        height: MAP_H,
        boxShadow: '0 0 16px rgba(6, 182, 212, 0.08)',
      }}
    >
      <canvas
        ref={canvasRef}
        style={{ width: MAP_W, height: MAP_H, borderRadius: '2px' }}
      />

      {/* Collapse button */}
      <button
        onClick={() => setCollapsed(true)}
        className="absolute top-1 right-1 p-0.5 text-[var(--text-muted)] hover:text-cyan-400 transition-colors"
        title="Collapse mini-map"
      >
        <Minimize2 size={10} />
      </button>

      {/* Label */}
      <div className="absolute bottom-0.5 left-1 text-[10px] font-mono tracking-[0.2em] text-cyan-700/60 uppercase">
        OVERVIEW
      </div>
    </div>
  );
}
