'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Camera,
  ChevronDown,
  ChevronUp,
  Clock,
  Coffee,
  Gauge,
  Minus,
  Moon,
  Pause,
  Play,
  Plus,
  Radio,
  RotateCcw,
  Settings2,
  Shield,
  SkipBack,
  SkipForward,
  Zap,
} from 'lucide-react';
import { useDataKey } from '@/hooks/useDataStore';
import { API_BASE } from '@/lib/api';
import { controlPlaneFetch } from '@/lib/controlPlane';
import {
  enterSnapshotMode,
  exitSnapshotMode,
  refreshHourlyIndex,
  seekToTime,
  setPlaybackSpeed,
  stepBackward,
  stepForward,
  togglePlayback,
  useTimeMachine,
} from '@/hooks/useTimeMachine';
import type { DashboardData } from '@/types/dashboard';

const SPEED_OPTIONS = [
  { label: 'FAST', value: 3, desc: '3 seconds between snapshots' },
  { label: 'NORMAL', value: 6, desc: '6 seconds between snapshots' },
  { label: 'SLOW', value: 12, desc: '12 seconds between snapshots' },
  { label: 'VERY SLOW', value: 20, desc: '20 seconds between snapshots' },
];

const PRESET_META: Record<string, { label: string; desc: string; icon: typeof Zap }> = {
  paranoid: { label: 'PARANOID', desc: 'Every 5 min high-freq / 30 min standard', icon: Shield },
  active: { label: 'ACTIVE', desc: 'Every 15 min high-freq / 2 hr standard', icon: Zap },
  casual: { label: 'CASUAL', desc: 'Every 60 min high-freq / 6 hr standard', icon: Coffee },
  minimal: { label: 'MINIMAL', desc: 'Every 6 hr high-freq / standard off', icon: Moon },
};

function formatClock(unixTs: number | null): string {
  if (!unixTs) return '--:--';
  const d = new Date(unixTs * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatFullTime(unixTs: number | null): string {
  if (!unixTs) return 'No snapshot selected';
  const d = new Date(unixTs * 1000);
  return d.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function pct(value: number, min: number, max: number): number {
  if (max <= min) return 0;
  return Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
}

export default function TimelinePanel() {
  const tm = useTimeMachine();
  const [isMinimized, setIsMinimized] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [tmEnabled, setTmEnabled] = useState(false);
  const [tmSaving, setTmSaving] = useState(false);
  const [activePreset, setActivePreset] = useState('active');
  const [snapshotBusy, setSnapshotBusy] = useState(false);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const [scrubOffsetMs, setScrubOffsetMs] = useState<number | null>(null);

  useEffect(() => {
    const fetchStatus = () => {
      fetch(`${API_BASE}/api/settings/timemachine`)
        .then((r) => r.json())
        .then((d) => setTmEnabled(!!d.enabled))
        .catch(() => {});
      fetch(`${API_BASE}/api/ai/timemachine/config`)
        .then((r) => r.json())
        .then((d) => {
          if (d.config?.preset) setActivePreset(d.config.preset);
        })
        .catch(() => {});
    };
    fetchStatus();
    refreshHourlyIndex();
    const iv = setInterval(fetchStatus, 60_000);
    return () => clearInterval(iv);
  }, []);

  const toggleTm = useCallback(async () => {
    setTmSaving(true);
    try {
      const res = await controlPlaneFetch('/api/settings/timemachine', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !tmEnabled }),
        requireAdminSession: false,
      });
      if (res.ok) {
        const data = await res.json();
        setTmEnabled(!!data.enabled);
        if (data.enabled) {
          await fetch(`${API_BASE}/api/ai/timemachine/snapshot`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ compress: true, profile: 'manual' }),
          });
          await refreshHourlyIndex();
        }
      }
    } catch {}
    setTmSaving(false);
  }, [tmEnabled]);

  const applyPreset = useCallback(async (preset: string) => {
    try {
      const res = await controlPlaneFetch('/api/ai/timemachine/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preset }),
        requireAdminSession: false,
      });
      if (res.ok) setActivePreset(preset);
    } catch {}
  }, []);

  const takeSnapshot = useCallback(async () => {
    setSnapshotBusy(true);
    try {
      const res = await fetch(`${API_BASE}/api/ai/timemachine/snapshot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ compress: true, profile: 'manual' }),
      });
      if (res.ok) {
        const json = await res.json();
        await refreshHourlyIndex();
        const snapshotId = json.snapshot_id || json.id;
        if (snapshotId) await enterSnapshotMode(snapshotId);
      }
    } catch {}
    setSnapshotBusy(false);
  }, []);

  const isSnapshot = tm.mode === 'snapshot';
  const totalSnapshots = tm.snapshots.length;
  const timelineStart = tm.timelineStart ?? 0;
  const timelineEnd = tm.timelineEnd ?? timelineStart;
  const currentUnixTs = tm.currentUnixTs ?? timelineEnd;
  const hasPlayableRange = tmEnabled && totalSnapshots > 0 && timelineEnd > timelineStart;
  const timelineSpanMs = Math.max(1, Math.round((timelineEnd - timelineStart) * 1000));
  const liveOffsetMs = Math.max(0, Math.min(timelineSpanMs, Math.round((currentUnixTs - timelineStart) * 1000)));
  const effectiveOffsetMs = isScrubbing && scrubOffsetMs !== null ? scrubOffsetMs : liveOffsetMs;
  const effectiveUnixTs = timelineStart + effectiveOffsetMs / 1000;

  const progressPct = pct(effectiveOffsetMs, 0, timelineSpanMs);

  const snapshotMarks = useMemo(() => {
    if (!hasPlayableRange) return [];
    return tm.snapshots.map((snap) => ({
      id: snap.id,
      left: pct(snap.unix_ts, timelineStart, timelineEnd),
    }));
  }, [hasPlayableRange, timelineEnd, timelineStart, tm.snapshots]);

  const startPlaybackFromPanel = useCallback(() => {
    if (!isSnapshot && tm.snapshots[0]) {
      enterSnapshotMode(tm.snapshots[0].id).then(() => togglePlayback());
      return;
    }
    togglePlayback();
  }, [isSnapshot, tm.snapshots]);

  const commitScrub = useCallback((offsetMs: number | null) => {
    if (!hasPlayableRange || offsetMs === null) return;
    const clamped = Math.max(0, Math.min(timelineSpanMs, offsetMs));
    setIsScrubbing(false);
    setScrubOffsetMs(null);
    void seekToTime(timelineStart + clamped / 1000);
  }, [hasPlayableRange, timelineSpanMs, timelineStart]);

  const handleScrubStart = useCallback(() => {
    if (!hasPlayableRange) return;
    if (tm.playing) togglePlayback();
    setIsScrubbing(true);
    setScrubOffsetMs(liveOffsetMs);
  }, [hasPlayableRange, liveOffsetMs, tm.playing]);

  const handleScrubChange = useCallback((value: string) => {
    const nextOffsetMs = Number(value);
    if (!Number.isFinite(nextOffsetMs)) return;
    setScrubOffsetMs(nextOffsetMs);
    if (!isScrubbing) {
      commitScrub(nextOffsetMs);
    }
  }, [commitScrub, isScrubbing]);

  useEffect(() => {
    if (!isScrubbing) return;
    const finish = () => commitScrub(scrubOffsetMs);
    window.addEventListener('pointerup', finish);
    return () => {
      window.removeEventListener('pointerup', finish);
    };
  }, [commitScrub, isScrubbing, scrubOffsetMs]);

  return (
    <div className="bg-[rgba(5,10,18,0.92)] border border-cyan-900/40 backdrop-blur-sm">
      <div
        className="flex items-center justify-between px-3 py-2.5 cursor-pointer hover:bg-cyan-950/30 transition-colors border-b border-cyan-900/40"
        onClick={() => setIsMinimized(!isMinimized)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Clock size={16} className={isSnapshot ? 'text-amber-400' : 'text-cyan-400'} />
          <span
            className={`text-[12px] font-mono tracking-widest font-bold ${
              isSnapshot ? 'text-amber-400' : 'text-cyan-400'
            }`}
          >
            TIME MACHINE
          </span>
          <span
            className={`text-[10px] font-mono tracking-wider px-1.5 py-0.5 border ${
              isSnapshot
                ? 'text-amber-300 border-amber-600/50 bg-amber-950/30'
                : 'text-emerald-300 border-emerald-600/40 bg-emerald-950/20'
            }`}
          >
            {isSnapshot ? 'SNAPSHOT' : 'LIVE'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${isSnapshot ? 'bg-amber-400' : 'bg-emerald-500'}`} />
          {isMinimized ? <Plus size={16} className="text-cyan-400" /> : <Minus size={16} className="text-cyan-400" />}
        </div>
      </div>

      {!isMinimized && (
        <div className="px-3 py-3 flex flex-col gap-3">
          {isSnapshot && (
            <div className="flex items-center justify-between gap-3 px-3 py-2 bg-amber-950/35 border border-amber-500/45 rounded-sm">
              <div className="min-w-0">
                <div className="text-[12px] font-mono tracking-wider font-bold text-amber-300">
                  VIEWING RECORDED SNAPSHOT
                </div>
                <div className="text-[11px] font-mono text-amber-200/70 truncate">
                  {formatFullTime(tm.currentUnixTs)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => exitSnapshotMode()}
                className="flex shrink-0 items-center gap-1.5 px-3 py-1.5 text-[12px] font-mono tracking-wider font-bold text-emerald-300 bg-emerald-950/40 hover:bg-emerald-900/50 border border-emerald-500/50 rounded-sm transition-colors"
              >
                <RotateCcw size={13} />
                LIVE
              </button>
            </div>
          )}

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Radio size={12} className={tmEnabled ? 'text-emerald-400' : 'text-red-500/60'} />
              <span className={`text-[11px] font-mono tracking-wider ${tmEnabled ? 'text-emerald-400' : 'text-red-400/60'}`}>
                {tmEnabled ? 'LIVE CAPTURE ON' : 'SNAPSHOTS OFF'}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={takeSnapshot}
                disabled={!tmEnabled || snapshotBusy}
                className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-mono tracking-wider text-cyan-400 hover:text-cyan-300 bg-cyan-950/30 hover:bg-cyan-950/50 border border-cyan-900/30 rounded-sm transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                title="Capture current map state"
              >
                <Camera size={10} />
                {snapshotBusy ? 'SAVING...' : 'SNAP'}
              </button>
              <button
                type="button"
                onClick={() => setConfigOpen(!configOpen)}
                className={`flex items-center gap-1 px-2 py-0.5 text-[10px] font-mono tracking-wider border rounded-sm transition-colors ${
                  configOpen
                    ? 'text-amber-300 bg-amber-950/30 border-amber-700/40'
                    : 'text-cyan-400 hover:text-cyan-300 bg-cyan-950/30 hover:bg-cyan-950/50 border-cyan-900/30'
                }`}
              >
                <Settings2 size={10} />
                CONFIGURE
                {configOpen ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
              </button>
            </div>
          </div>

          {configOpen && (
            <div className="border border-cyan-900/30 bg-[rgba(5,5,10,0.95)] p-3 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-mono tracking-wider text-[var(--text-secondary)]">SNAPSHOTS</span>
                <button
                  type="button"
                  onClick={toggleTm}
                  disabled={tmSaving}
                  className={`px-3 py-1 text-[11px] font-mono tracking-wider border rounded-sm transition-colors ${
                    tmEnabled
                      ? 'text-emerald-300 border-emerald-600/40 bg-emerald-950/30 hover:bg-emerald-950/50'
                      : 'text-red-400 border-red-800/40 bg-red-950/20 hover:bg-red-950/40'
                  } disabled:opacity-40`}
                >
                  {tmSaving ? '...' : tmEnabled ? 'ON' : 'OFF'}
                </button>
              </div>

              <div>
                <span className="text-[10px] font-mono tracking-wider text-[var(--text-muted)] block mb-2">
                  CAPTURE FREQUENCY
                </span>
                <div className="grid grid-cols-2 gap-1.5">
                  {Object.entries(PRESET_META).map(([key, meta]) => {
                    const Icon = meta.icon;
                    const active = activePreset === key;
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => applyPreset(key)}
                        className={`flex items-center gap-1.5 px-2 py-1.5 text-left border rounded-sm transition-colors ${
                          active
                            ? 'text-amber-300 border-amber-600/50 bg-amber-950/30'
                            : 'text-[var(--text-secondary)] border-cyan-900/20 hover:bg-cyan-950/20 hover:border-cyan-800/30'
                        }`}
                      >
                        <Icon size={12} className={active ? 'text-amber-400' : 'text-cyan-600'} />
                        <div>
                          <div className="text-[10px] font-mono tracking-wider font-bold">{meta.label}</div>
                          <div className="text-[11px] font-mono text-[var(--text-muted)] leading-tight">{meta.desc}</div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {tmEnabled && totalSnapshots > 0 ? (
            <div className={`border rounded-sm px-3 py-3 ${isSnapshot ? 'border-amber-800/40 bg-amber-950/15' : 'border-cyan-900/30 bg-cyan-950/10'}`}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-mono tracking-wider text-[var(--text-muted)]">
                  {formatClock(timelineStart)}
                </span>
                <span className={`text-[12px] font-mono tracking-wider font-bold ${isSnapshot ? 'text-amber-300' : 'text-cyan-300'}`}>
                  {isSnapshot || isScrubbing ? formatFullTime(effectiveUnixTs) : `${totalSnapshots} snapshots ready`}
                </span>
                <span className="text-[11px] font-mono tracking-wider text-[var(--text-muted)]">
                  {formatClock(timelineEnd)}
                </span>
              </div>

              <div className="px-1 pt-2 pb-1">
                <div className="relative h-8">
                  <div className="absolute left-1 right-1 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-cyan-950/80 border border-cyan-900/40" />
                  <div
                    className={`absolute left-1 top-1/2 h-[3px] -translate-y-1/2 rounded-full ${isSnapshot ? 'bg-amber-400/70' : 'bg-cyan-400/60'}`}
                    style={{ width: `${progressPct}%` }}
                  />
                  <input
                    type="range"
                    min={0}
                    max={timelineSpanMs}
                    step={1000}
                    value={effectiveOffsetMs}
                    disabled={!hasPlayableRange}
                    onPointerDown={handleScrubStart}
                    onChange={(e) => handleScrubChange(e.currentTarget.value)}
                    className="relative z-10 h-8 w-full bg-transparent cursor-pointer disabled:cursor-default"
                    style={{ accentColor: isSnapshot ? '#f59e0b' : '#22d3ee' }}
                    aria-label="Snapshot playback position"
                  />
                </div>
                <div className="mt-1.5 flex items-center gap-2">
                  <span className="shrink-0 text-[9px] font-mono tracking-[0.24em] text-[var(--text-muted)] opacity-70">
                    SNAPS
                  </span>
                  <div className="relative h-2 flex-1 rounded-full bg-cyan-950/25">
                    {snapshotMarks.map((mark) => (
                      <span
                        key={mark.id}
                        className={`absolute top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full ${
                          isSnapshot ? 'bg-amber-300/75' : 'bg-cyan-300/65'
                        }`}
                        style={{ left: `${mark.left}%` }}
                      />
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between gap-2 mt-2">
                <button
                  type="button"
                  onClick={stepBackward}
                  className="p-2 rounded-sm transition-colors text-cyan-300 hover:text-cyan-100 hover:bg-cyan-950/40 disabled:opacity-30"
                  disabled={!hasPlayableRange}
                  title="Previous snapshot"
                >
                  <SkipBack size={18} />
                </button>
                <button
                  type="button"
                  onClick={startPlaybackFromPanel}
                  className={`flex items-center justify-center gap-2 px-5 py-1.5 rounded-sm text-[12px] font-mono tracking-wider font-bold transition-colors min-w-[110px] ${
                    tm.playing
                      ? 'text-amber-300 bg-amber-600/20 hover:bg-amber-600/30 border border-amber-600/40'
                      : 'text-cyan-300 bg-cyan-950/30 hover:bg-cyan-950/50 border border-cyan-900/40'
                  }`}
                  disabled={!hasPlayableRange}
                >
                  {tm.playing ? (
                    <>
                      <Pause size={16} /> PAUSE
                    </>
                  ) : (
                    <>
                      <Play size={16} /> PLAY
                    </>
                  )}
                </button>
                <button
                  type="button"
                  onClick={stepForward}
                  className="p-2 rounded-sm transition-colors text-cyan-300 hover:text-cyan-100 hover:bg-cyan-950/40 disabled:opacity-30"
                  disabled={!hasPlayableRange}
                  title="Next snapshot"
                >
                  <SkipForward size={18} />
                </button>
                <button
                  type="button"
                  onClick={() => exitSnapshotMode()}
                  disabled={!isSnapshot}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-mono tracking-wider font-bold text-emerald-300 bg-emerald-950/30 hover:bg-emerald-900/40 border border-emerald-500/40 rounded-sm transition-colors disabled:opacity-40 disabled:hover:bg-emerald-950/30"
                  title="Return to live feed"
                >
                  <RotateCcw size={13} />
                  LIVE
                </button>
              </div>

              <div className="flex items-center justify-between gap-2 mt-3">
                <div className="flex items-center gap-1.5 text-[11px] font-mono tracking-wider text-[var(--text-muted)]">
                  <Gauge size={12} />
                  PLAYBACK
                </div>
                <div className="flex gap-1">
                  {SPEED_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setPlaybackSpeed(opt.value)}
                      className={`px-2 py-1 text-[10px] font-mono tracking-wider border rounded-sm transition-colors ${
                        tm.playbackSpeed === opt.value
                          ? 'text-amber-300 border-amber-600/50 bg-amber-950/30'
                          : 'text-[var(--text-secondary)] border-cyan-900/20 hover:bg-cyan-950/20'
                      }`}
                      title={opt.desc}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : tmEnabled ? (
            <div className="w-full border border-cyan-900/30 rounded-sm py-3 px-3 bg-cyan-950/10 text-center">
              <div className="text-[12px] font-mono text-cyan-500 tracking-wider mb-1">
                WAITING FOR FIRST SNAPSHOT
              </div>
              <div className="text-[11px] font-mono text-[var(--text-muted)] leading-relaxed">
                Recording is on. Playback controls will appear after the first capture.
              </div>
              <button
                type="button"
                onClick={takeSnapshot}
                disabled={snapshotBusy}
                className="mt-2 flex items-center gap-1.5 mx-auto px-4 py-1.5 text-[11px] font-mono tracking-wider text-cyan-400 hover:text-cyan-300 border border-cyan-800/40 hover:border-cyan-600/50 bg-cyan-950/20 hover:bg-cyan-950/40 rounded-sm transition-colors"
              >
                <Camera size={12} />
                {snapshotBusy ? 'SAVING...' : 'TAKE FIRST SNAPSHOT NOW'}
              </button>
            </div>
          ) : (
            <div className="w-full border border-cyan-900/30 rounded-sm py-4 px-3 bg-cyan-950/10 text-center">
              <div className="text-[12px] font-mono text-[var(--text-muted)] tracking-wider leading-relaxed mb-3">
                Enable snapshots to record map state and play it back later.
              </div>
              <button
                type="button"
                onClick={toggleTm}
                className="px-5 py-2 text-[12px] font-mono tracking-wider font-bold text-cyan-400 hover:text-cyan-300 border border-cyan-700/50 hover:border-cyan-500/60 bg-cyan-950/30 hover:bg-cyan-950/50 rounded-sm transition-colors"
              >
                ENABLE SNAPSHOTS
              </button>
            </div>
          )}

          {tm.loading && (
            <div className="text-[11px] font-mono text-amber-500/70 tracking-wider text-center animate-pulse">
              LOADING RECORDED FRAME...
            </div>
          )}
          {tm.error && (
            <div className="text-[11px] font-mono text-red-400/80 tracking-wider text-center">
              {tm.error}
            </div>
          )}

          {isSnapshot && (
            <div className="border border-amber-900/20 bg-amber-950/10 px-3 py-2">
              <div className="text-[11px] font-mono tracking-wider text-amber-400/70 mb-1.5">
                RECORDED LAYERS
              </div>
              <div className="grid grid-cols-3 gap-x-2 gap-y-1">
                <TelemetryDot label="FLIGHTS" dataKey="commercial_flights" />
                <TelemetryDot label="MILITARY" dataKey="military_flights" />
                <TelemetryDot label="SHIPS" dataKey="ships" />
                <TelemetryDot label="SATS" dataKey="satellites" />
                <TelemetryDot label="NEWS" dataKey="news" />
                <TelemetryDot label="QUAKES" dataKey="earthquakes" />
                <TelemetryDot label="GDELT" dataKey="gdelt" />
                <TelemetryDot label="SIGINT" dataKey="sigint" />
                <TelemetryDot label="FIRES" dataKey="firms_fires" />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TelemetryDot({ label, dataKey }: { label: string; dataKey: keyof DashboardData }) {
  const data = useDataKey(dataKey);
  const count = Array.isArray(data) ? data.length : 0;
  const active = count > 0;
  return (
    <div className="flex items-center gap-1.5">
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${active ? 'bg-emerald-400' : 'bg-red-900/50'}`} />
      <span className="text-[11px] font-mono tracking-wider text-[var(--text-muted)]">{label}</span>
      {active && <span className="text-[11px] font-mono text-emerald-500/70">{count}</span>}
    </div>
  );
}
