'use client';

import { useState, useMemo, useRef, useCallback, useEffect } from 'react';
import { useDataKey } from '@/hooks/useDataStore';
import { API_BASE } from '@/lib/api';
import { controlPlaneFetch } from '@/lib/controlPlane';
import {
  useTimeMachine,
  enterSnapshotMode,
  exitSnapshotMode,
  stepForward,
  stepBackward,
  togglePlayback,
  refreshHourlyIndex,
} from '@/hooks/useTimeMachine';
import type { NewsArticle } from '@/types/dashboard';

/**
 * TimelineScrubber — 24-hour activity timeline with Time Machine playback.
 *
 * LIVE MODE: Shows news density histogram. Bins with snapshots are highlighted.
 * SNAPSHOT MODE: Shows playback controls (rewind, step, play/pause, live).
 * Clicking a bin with snapshot data enters snapshot mode for that hour.
 */

const HOURS = 24;
const BAR_W = 350;
const BAR_H = 32;

function getRiskColor(score: number): string {
  if (score >= 9) return '#ef4444';
  if (score >= 7) return '#f97316';
  if (score >= 4) return '#eab308';
  return '#22d3ee';
}

interface HourBin {
  hour: number;
  count: number;
  maxRisk: number;
  label: string;
  hasSnapshot: boolean;
  snapshotId: string | null;
}

export default function TimelineScrubber() {
  const news = useDataKey('news') as NewsArticle[] | undefined;
  const tm = useTimeMachine();
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [tmEnabled, setTmEnabled] = useState(false);
  const [tmTooltipDismissed, setTmTooltipDismissed] = useState(false);

  // Hydration-safe: read localStorage only after mount
  useEffect(() => {
    if (localStorage.getItem('sb_tm_tooltip_dismissed') === '1') {
      setTmTooltipDismissed(true);
    }
  }, []);

  // Check if Time Machine is enabled + refresh hourly index
  useEffect(() => {
    refreshHourlyIndex();
    fetch(`${API_BASE}/api/settings/timemachine`)
      .then((r) => r.json())
      .then((d) => setTmEnabled(!!d.enabled))
      .catch(() => {});
    // Re-check every 60s in case user toggles it in settings
    const interval = setInterval(() => {
      fetch(`${API_BASE}/api/settings/timemachine`)
        .then((r) => r.json())
        .then((d) => setTmEnabled(!!d.enabled))
        .catch(() => {});
    }, 60_000);
    return () => clearInterval(interval);
  }, []);

  const toggleTm = useCallback(async () => {
    const turningOn = !tmEnabled;
    try {
      const res = await controlPlaneFetch('/api/settings/timemachine', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: turningOn }),
        requireAdminSession: false,
      });
      if (res.ok) {
        const data = await res.json();
        setTmEnabled(!!data.enabled);
        // Take an immediate snapshot when enabling
        if (data.enabled) {
          fetch(`${API_BASE}/api/ai/timemachine/snapshot`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ compress: true, profile: 'manual' }),
          }).then(() => refreshHourlyIndex()).catch(() => {});
        }
      }
    } catch {}
    // Dismiss the storage tooltip after first interaction
    if (!tmTooltipDismissed) {
      localStorage.setItem('sb_tm_tooltip_dismissed', '1');
      setTmTooltipDismissed(true);
    }
  }, [tmEnabled, tmTooltipDismissed]);

  const bins = useMemo<HourBin[]>(() => {
    const buckets = Array.from({ length: HOURS }, (_, i) => {
      const hourEntry = tm.hourlyIndex[i];
      return {
        hour: i,
        count: 0,
        maxRisk: 0,
        label: `${String(i).padStart(2, '0')}:00`,
        hasSnapshot: !!hourEntry && hourEntry.count > 0,
        snapshotId: hourEntry?.latest_id ?? null,
      };
    });

    if (!news || !Array.isArray(news)) return buckets;

    const now = new Date();
    const cutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000);

    for (const article of news) {
      if (!article.pub_date) continue;
      const d = new Date(article.pub_date);
      if (d < cutoff) continue;
      const h = d.getHours();
      buckets[h].count++;
      buckets[h].maxRisk = Math.max(buckets[h].maxRisk, article.risk_score || 0);
    }

    return buckets;
  }, [news, tm.hourlyIndex]);

  const maxCount = useMemo(() => Math.max(1, ...bins.map((b) => b.count)), [bins]);

  // Get the hour of the currently loaded snapshot (for highlight)
  const snapshotHour = useMemo(() => {
    if (tm.mode !== 'snapshot' || !tm.snapshotTimestamp) return null;
    try {
      return new Date(tm.snapshotTimestamp).getHours();
    } catch { return null; }
  }, [tm.mode, tm.snapshotTimestamp]);

  // Draw the timeline
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = BAR_W * dpr;
    canvas.height = BAR_H * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, BAR_W, BAR_H);

    // Background
    ctx.fillStyle = 'rgba(5, 10, 20, 0.85)';
    ctx.fillRect(0, 0, BAR_W, BAR_H);

    const binW = BAR_W / HOURS;
    const nowHour = new Date().getHours();
    const isSnapshot = tm.mode === 'snapshot';

    for (let i = 0; i < HOURS; i++) {
      const bin = bins[i];
      const fillPct = bin.count / maxCount;
      const barH = Math.max(2, fillPct * (BAR_H - 8));
      const x = i * binW;
      const color = getRiskColor(bin.maxRisk);

      // Bar fill
      ctx.fillStyle = hoverIdx === i ? color : color + '80';
      ctx.fillRect(x + 1, BAR_H - barH - 2, binW - 2, barH);

      // Snapshot available indicator (small dot at top)
      if (bin.hasSnapshot) {
        ctx.fillStyle = isSnapshot ? '#f59e0b' : '#22d3ee';
        ctx.beginPath();
        ctx.arc(x + binW / 2, 4, 2, 0, Math.PI * 2);
        ctx.fill();
      }

      // Current hour marker (live mode) or snapshot hour marker
      if (isSnapshot && snapshotHour === i) {
        ctx.fillStyle = '#f59e0b40';
        ctx.fillRect(x, 0, binW, BAR_H);
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x + 0.5, 0.5, binW - 1, BAR_H - 1);
      } else if (!isSnapshot && i === nowHour) {
        ctx.fillStyle = '#22d3ee60';
        ctx.fillRect(x, 0, binW, BAR_H);
      }

      // Hover highlight
      if (hoverIdx === i) {
        ctx.strokeStyle = bin.hasSnapshot ? '#f59e0b' : '#22d3ee';
        ctx.lineWidth = 1;
        ctx.strokeRect(x + 0.5, 0.5, binW - 1, BAR_H - 1);
      }
    }

    // 6h tick marks
    ctx.fillStyle = 'rgba(6, 182, 212, 0.3)';
    ctx.font = '7px monospace';
    ctx.textAlign = 'center';
    for (let h = 0; h < HOURS; h += 6) {
      const x = h * binW;
      ctx.fillRect(x, 0, 0.5, BAR_H);
      ctx.fillText(`${String(h).padStart(2, '0')}`, x + binW / 2 + 2, 8);
    }

    // Border
    ctx.strokeStyle = isSnapshot ? 'rgba(245, 158, 11, 0.25)' : 'rgba(6, 182, 212, 0.15)';
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, BAR_W - 1, BAR_H - 1);
  }, [bins, maxCount, hoverIdx, tm.mode, snapshotHour]);

  useEffect(() => { draw(); }, [draw]);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const binW = BAR_W / HOURS;
    const idx = Math.floor(x / binW);
    if (idx >= 0 && idx < HOURS) setHoverIdx(idx);
    else setHoverIdx(null);
  }, []);

  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!tmEnabled) return; // Time Machine is off
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const binW = BAR_W / HOURS;
    const idx = Math.floor(x / binW);
    if (idx >= 0 && idx < HOURS) {
      const bin = bins[idx];
      if (bin.hasSnapshot && bin.snapshotId) {
        enterSnapshotMode(bin.snapshotId);
      }
    }
  }, [bins, tmEnabled]);

  const isSnapshot = tm.mode === 'snapshot';

  // Format snapshot timestamp for display
  const snapshotLabel = useMemo(() => {
    if (!tm.snapshotTimestamp) return '';
    try {
      const d = new Date(tm.snapshotTimestamp);
      return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')} LOCAL`;
    } catch { return ''; }
  }, [tm.snapshotTimestamp]);

  return (
    <div className="absolute top-[2.5rem] right-6 z-[201] pointer-events-auto w-[400px]">
      <div className="relative flex flex-col items-center">
        {/* Title — changes based on mode */}
        {isSnapshot ? (
          <div className="flex items-center gap-2 mb-1">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
            </span>
            <span className="text-xs font-mono tracking-[0.3em] text-amber-500 uppercase">
              SNAPSHOT · {snapshotLabel}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-mono tracking-[0.3em] text-cyan-600 uppercase">
              24H EVENT TIMELINE
            </span>
            <button
              type="button"
              onClick={toggleTm}
              className={`text-[11px] font-mono tracking-[0.2em] uppercase cursor-pointer hover:brightness-125 transition-colors ${
                tmEnabled ? 'text-amber-400/80' : 'text-amber-600/60'
              }`}
              title={tmTooltipDismissed ? undefined : (tmEnabled ? 'Click to disable snapshots (~68 MB/day)' : 'Click to enable snapshots (~68 MB/day)')}
            >
              {tmEnabled ? 'SNAPSHOTS ON' : 'SNAPSHOTS OFF'}
            </button>
          </div>
        )}

        {/* Tooltip */}
        {hoverIdx !== null && (
          <div
            className="absolute -top-6 left-1/2 -translate-x-1/2 bg-[rgba(5,5,5,0.95)] border border-[var(--border-primary)] rounded-sm px-2 py-0.5 text-[11px] font-mono text-cyan-400 tracking-wider whitespace-nowrap"
            style={{ boxShadow: '0 0 8px rgba(6,182,212,0.1)' }}
          >
            {bins[hoverIdx].label} · {bins[hoverIdx].count} events
            {bins[hoverIdx].maxRisk > 0 && ` · MAX LVL ${bins[hoverIdx].maxRisk}`}
            {tmEnabled && bins[hoverIdx].hasSnapshot && ' · ◆ SNAPSHOT'}
          </div>
        )}

        <div className="flex items-center gap-2 w-full">
          {/* Label */}
          <span className="text-[11px] font-mono tracking-[0.2em] text-[var(--text-muted)] uppercase">
            24H
          </span>

          <canvas
            ref={canvasRef}
            style={{ width: BAR_W, height: BAR_H, cursor: 'crosshair', borderRadius: '2px' }}
            onMouseMove={handleMouseMove}
            onMouseLeave={() => setHoverIdx(null)}
            onClick={handleClick}
          />

          {/* Now marker label */}
          <span className="text-[11px] font-mono tracking-[0.2em] text-cyan-600 uppercase">
            NOW
          </span>
        </div>

        {/* Playback controls — visible in snapshot mode */}
        {isSnapshot && (
          <div
            className="flex items-center justify-center gap-1 mt-1.5 w-full"
            style={{ maxWidth: BAR_W }}
          >
            {/* Rewind (step back) */}
            <button
              type="button"
              onClick={stepBackward}
              className="px-2 py-0.5 text-[11px] font-mono tracking-wider text-amber-400 hover:text-amber-300 bg-[rgba(245,158,11,0.08)] hover:bg-[rgba(245,158,11,0.15)] border border-amber-900/30 rounded-sm transition-colors"
              title="Previous snapshot"
            >
              ◄◄
            </button>

            {/* Play / Pause */}
            <button
              type="button"
              onClick={togglePlayback}
              className={`px-3 py-0.5 text-[11px] font-mono tracking-wider border rounded-sm transition-colors ${
                tm.playing
                  ? 'text-amber-300 bg-[rgba(245,158,11,0.2)] border-amber-700/50'
                  : 'text-amber-400 hover:text-amber-300 bg-[rgba(245,158,11,0.08)] hover:bg-[rgba(245,158,11,0.15)] border-amber-900/30'
              }`}
              title={tm.playing ? 'Pause playback' : 'Auto-play snapshots'}
            >
              {tm.playing ? '❚❚ PAUSE' : '► PLAY'}
            </button>

            {/* Step forward */}
            <button
              type="button"
              onClick={stepForward}
              className="px-2 py-0.5 text-[11px] font-mono tracking-wider text-amber-400 hover:text-amber-300 bg-[rgba(245,158,11,0.08)] hover:bg-[rgba(245,158,11,0.15)] border border-amber-900/30 rounded-sm transition-colors"
              title="Next snapshot"
            >
              ►►
            </button>

            {/* Divider */}
            <span className="text-amber-900/40 mx-0.5">│</span>

            {/* Return to LIVE */}
            <button
              type="button"
              onClick={exitSnapshotMode}
              className="px-3 py-0.5 text-[11px] font-mono tracking-[0.15em] text-cyan-400 hover:text-cyan-300 bg-[rgba(6,182,212,0.08)] hover:bg-[rgba(6,182,212,0.15)] border border-cyan-900/30 rounded-sm transition-colors"
              title="Return to live feed"
            >
              ● LIVE
            </button>
          </div>
        )}

        {/* Loading indicator */}
        {tm.loading && (
          <div className="text-[11px] font-mono text-amber-500/70 tracking-wider mt-1 animate-pulse">
            LOADING SNAPSHOT...
          </div>
        )}
      </div>
    </div>
  );
}
