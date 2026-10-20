'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, MapPin, Truck } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { LAYER_TOGGLE_EVENT } from '@/hooks/useDataPolling';
import { VIEWPORT_COMMITTED_EVENT } from '@/components/map/hooks/useViewportBounds';
import { useTranslation } from '@/i18n';

type ViewBounds = { south: number; west: number; north: number; east: number };

type RoadCorridorStatus = {
  deps_installed: boolean;
  credentials_configured: boolean;
  active_job?: AnalyzeJob | null;
};

type AnalyzeJob = {
  job_id: string;
  status: string;
  message: string;
  progress: number;
  error?: string | null;
  result?: {
    total_detections?: number;
    daily_counts?: Array<{ date: string; count: number }>;
    status?: string;
    error?: string | null;
  } | null;
};

function viewCenter(bounds: ViewBounds | null | undefined): { lat: number; lon: number } | null {
  if (!bounds) return null;
  const { south, west, north, east } = bounds;
  if (![south, west, north, east].every((v) => Number.isFinite(v))) return null;
  return { lat: (south + north) / 2, lon: (west + east) / 2 };
}

export default function RoadCorridorLayerControls({
  viewBoundsRef,
}: {
  viewBoundsRef?: React.RefObject<ViewBounds | null>;
}) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<RoadCorridorStatus | null>(null);
  const [job, setJob] = useState<AnalyzeJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [mapCenter, setMapCenter] = useState<{ lat: number; lon: number } | null>(() =>
    viewCenter(viewBoundsRef?.current ?? null),
  );
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const syncCenter = () => setMapCenter(viewCenter(viewBoundsRef?.current ?? null));
    syncCenter();
    window.addEventListener(VIEWPORT_COMMITTED_EVENT, syncCenter);
    return () => window.removeEventListener(VIEWPORT_COMMITTED_EVENT, syncCenter);
  }, [viewBoundsRef]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const pollJob = useCallback(
    async (jobId?: string) => {
      try {
        const qs = jobId ? `?job_id=${encodeURIComponent(jobId)}` : '';
        const res = await fetch(`${API_BASE}/api/road-corridors/analyze/status${qs}`);
        if (!res.ok) return;
        const body = await res.json();
        const next = body.job as AnalyzeJob | null;
        if (!next) return;
        setJob(next);
        if (next.status === 'ok' || next.status === 'error') {
          stopPolling();
          setSubmitting(false);
          if (next.status === 'ok') {
            window.dispatchEvent(new Event(LAYER_TOGGLE_EVENT));
          }
        }
      } catch {
        // ignore transient poll errors
      }
    },
    [stopPolling],
  );

  const startPolling = useCallback(
    (jobId: string) => {
      stopPolling();
      void pollJob(jobId);
      pollRef.current = setInterval(() => void pollJob(jobId), 2500);
    },
    [pollJob, stopPolling],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/road-corridors/status`);
        if (!res.ok || cancelled) return;
        const body = await res.json();
        setStatus(body);
        if (body.active_job?.status === 'queued' || body.active_job?.status === 'running') {
          setJob(body.active_job);
          setSubmitting(true);
          startPolling(body.active_job.job_id);
        }
      } catch {
        // backend may be offline during boot
      }
    })();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [startPolling, stopPolling]);

  const ready = Boolean(status?.deps_installed && status?.credentials_configured);
  const running = submitting || job?.status === 'queued' || job?.status === 'running';

  const handleAnalyze = async () => {
    const c = mapCenter ?? viewCenter(viewBoundsRef?.current ?? null);
    if (!c || running) return;
    setSubmitting(true);
    setJob(null);
    try {
      const res = await fetch(`${API_BASE}/api/road-corridors/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat: c.lat, lon: c.lon }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 409 && body.detail) {
        const statusRes = await fetch(`${API_BASE}/api/road-corridors/analyze/status`);
        const statusBody = await statusRes.json();
        if (statusBody.job) {
          setJob(statusBody.job);
          startPolling(statusBody.job.job_id);
        }
        return;
      }
      if (!res.ok) {
        setSubmitting(false);
        setJob({
          job_id: '',
          status: 'error',
          message: typeof body.detail === 'string' ? body.detail : t('roadCorridor.analyzeFailed'),
          progress: 100,
          error: typeof body.detail === 'string' ? body.detail : undefined,
        });
        return;
      }
      setJob(body as AnalyzeJob);
      startPolling((body as AnalyzeJob).job_id);
    } catch {
      setSubmitting(false);
      setJob({
        job_id: '',
        status: 'error',
        message: t('roadCorridor.analyzeFailed'),
        progress: 100,
      });
    }
  };

  let statusLine = t('roadCorridor.hintTrends');
  if (!ready) {
    statusLine = !status?.deps_installed
      ? t('roadCorridor.missingDeps')
      : t('roadCorridor.missingCreds');
  } else if (!mapCenter) {
    statusLine = t('roadCorridor.panMapFirst');
  } else if (running && job) {
    statusLine = job.message || t('roadCorridor.analyzing');
  } else if (job?.status === 'ok' && job.result) {
    const days = job.result.daily_counts?.length ?? 0;
    const total = job.result.total_detections ?? 0;
    statusLine = `${total} truck signatures · ${days} day${days === 1 ? '' : 's'}`;
  } else if (job?.status === 'error') {
    statusLine = job.error || job.message || t('roadCorridor.analyzeFailed');
  }

  return (
    <div className="ml-7 mt-2 flex flex-col gap-1.5" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={() => void handleAnalyze()}
        disabled={!ready || !mapCenter || running}
        className="flex items-center gap-1.5 text-[9px] font-mono tracking-wide text-amber-400 hover:text-amber-200 border border-amber-500/30 hover:border-amber-500/50 bg-amber-500/5 hover:bg-amber-500/10 disabled:opacity-40 disabled:hover:text-amber-400 disabled:hover:border-amber-500/30 disabled:hover:bg-amber-500/5 px-2.5 py-1 rounded transition w-fit"
      >
        {running ? <Loader2 size={10} className="animate-spin" /> : <MapPin size={10} />}
        {running ? t('roadCorridor.analyzing') : t('roadCorridor.analyzeHere')}
      </button>
      <div className="flex items-start gap-1.5 text-[10px] font-mono text-[var(--text-muted)] leading-snug max-w-[220px]">
        <Truck size={10} className="mt-0.5 shrink-0 text-amber-500/70" />
        <span>{statusLine}</span>
      </div>
      {running && job && job.progress > 0 ? (
        <div className="h-1 w-full max-w-[180px] bg-amber-950/40 rounded overflow-hidden">
          <div
            className="h-full bg-amber-500/70 transition-all duration-500"
            style={{ width: `${Math.min(100, job.progress)}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}
