'use client';

import React, { useState } from 'react';
import { Popup } from 'react-map-gl/maplibre';
import { Activity, ShieldCheck } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { API_BASE } from '@/lib/api';
import { SNAPMAP_LEVEL_COLORS } from '@/components/map/geoJSONBuilders';
import type { SnapmapReliability, SnapmapZone } from '@/types/dashboard';

const RELIABILITY_STYLE: Record<SnapmapReliability, string> = {
  A: 'bg-emerald-600 text-white',
  B: 'bg-sky-600 text-white',
  C: 'bg-zinc-600 text-white',
};

function mediaSrc(url: string | null): string | null {
  if (!url) return null;
  return `${API_BASE}/api/snapmap/media?url=${encodeURIComponent(url)}`;
}

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—';
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 60) return `${minutes} min`;
  return `${Math.round(minutes / 60)} h`;
}

export interface SnapmapOsintPopupProps {
  zone: SnapmapZone;
  onClose: () => void;
}

export function SnapmapOsintPopup({ zone, onClose }: SnapmapOsintPopupProps) {
  const { t } = useTranslation();
  const [note, setNote] = useState('');
  const [rating, setRating] = useState<SnapmapReliability>(zone.reliability);
  const [confirmState, setConfirmState] = useState<'idle' | 'sending' | 'error'>('idle');
  const color = SNAPMAP_LEVEL_COLORS[zone.level] || SNAPMAP_LEVEL_COLORS.unknown;
  const canConfirm = Boolean(zone.alert_id) && rating !== 'A';

  async function confirm() {
    if (!zone.alert_id || !note.trim()) return;
    setConfirmState('sending');
    try {
      const res = await fetch(`${API_BASE}/api/snapmap/alerts/${zone.alert_id}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: note.trim() }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setRating('A');
      setConfirmState('idle');
    } catch {
      setConfirmState('error');
    }
  }

  return (
    <Popup
      longitude={zone.lng}
      latitude={zone.lat}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      className="threat-popup"
      maxWidth="380px"
    >
      <div className="bg-black/95 border border-yellow-700/50 rounded-lg overflow-hidden font-mono text-[11px]">
        <div className="px-3 py-2 border-b border-yellow-800/40 bg-yellow-950/40 flex items-center gap-2">
          <Activity size={14} className="text-yellow-400" />
          <span className="text-yellow-300 font-bold tracking-widest text-[10px] uppercase truncate">
            {zone.label}
          </span>
          <span
            className={`ml-auto px-1.5 py-0.5 rounded text-[10px] font-bold ${RELIABILITY_STYLE[rating]}`}
            title={t('snapmap.reliabilityHint')}
          >
            {rating}
          </span>
          <button type="button" onClick={onClose} className="text-[var(--text-muted)] hover:text-white">
            ✕
          </button>
        </div>

        <div className="p-3 flex flex-col gap-2 max-h-80 overflow-y-auto styled-scrollbar">
          <div className="flex justify-between items-center">
            <span className="text-[var(--text-muted)]">{t('snapmap.level')}</span>
            <span className="font-bold uppercase" style={{ color }}>
              {zone.level}
              {zone.level !== 'warmup' && zone.level !== 'unknown' ? ` · z ${zone.z.toFixed(1)}` : ''}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-[10px]">
            <div>
              <div className="text-[var(--text-muted)]">{t('snapmap.lastHour')}</div>
              <div className="text-white font-bold">{zone.count_1h}</div>
            </div>
            <div>
              <div className="text-[var(--text-muted)]">{t('snapmap.baseline')}</div>
              <div className="text-white">{zone.baseline_mean ?? '—'}</div>
            </div>
            <div>
              <div className="text-[var(--text-muted)]">24 h</div>
              <div className="text-white">{zone.count_24h}</div>
            </div>
          </div>

          {zone.level === 'warmup' && (
            <div className="text-[10px] text-[var(--text-muted)]">{t('snapmap.warmup')}</div>
          )}

          {zone.corroboration.length > 0 && (
            <div className="flex flex-col gap-1">
              <div className="text-[var(--text-muted)] text-[10px]">{t('snapmap.corroboration')}</div>
              {zone.corroboration.map((c) => (
                <div key={`${c.layer}-${c.title}`} className="text-[10px] text-sky-300 truncate" title={c.title}>
                  [{c.layer}] {c.title || '—'} · {c.distance_km} km
                </div>
              ))}
            </div>
          )}

          {zone.keyword_hits.length > 0 && (
            <div className="text-[10px] text-orange-300">
              {t('snapmap.keywords')}: {zone.keyword_hits.join(', ')}
            </div>
          )}

          {zone.media.length > 0 && (
            <div className="grid grid-cols-3 gap-1">
              {zone.media.slice(0, 9).map((m) => {
                const src = mediaSrc(m.url);
                if (!src) return null;
                return m.type === 'video' ? (
                  <video
                    key={m.id}
                    src={src}
                    className="w-full aspect-[9/16] object-cover rounded bg-zinc-900"
                    muted
                    controls
                    preload="none"
                    title={`${m.locality || ''} · ${timeAgo(m.time)}`}
                  />
                ) : (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    key={m.id}
                    src={src}
                    alt={m.locality || 'snap'}
                    loading="lazy"
                    className="w-full aspect-[9/16] object-cover rounded bg-zinc-900"
                    title={`${m.locality || ''} · ${timeAgo(m.time)}`}
                  />
                );
              })}
            </div>
          )}

          {canConfirm && (
            <div className="flex flex-col gap-1 border-t border-zinc-800 pt-2">
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t('snapmap.confirmPlaceholder')}
                className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-[10px] text-white"
              />
              <button
                type="button"
                disabled={!note.trim() || confirmState === 'sending'}
                onClick={() => void confirm()}
                className="flex items-center justify-center gap-1 rounded bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 px-2 py-1 text-[10px] text-white"
              >
                <ShieldCheck size={12} /> {t('snapmap.confirm')}
              </button>
              {confirmState === 'error' && <div className="text-[10px] text-red-400">{t('snapmap.confirmError')}</div>}
            </div>
          )}

          <div className="text-[9px] text-[var(--text-muted)] border-t border-zinc-800 pt-2">
            {t('snapmap.scanned')} {timeAgo(zone.last_scan)} · {t('snapmap.disclaimer')}
          </div>
        </div>
      </div>
    </Popup>
  );
}
