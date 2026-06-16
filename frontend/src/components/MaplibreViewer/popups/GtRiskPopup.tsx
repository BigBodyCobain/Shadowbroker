'use client';

import React, { useEffect, useState } from 'react';
import { Popup } from 'react-map-gl/maplibre';
import { Radar } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { API_BASE } from '@/lib/api';
import { formatGtRegionLabel } from '@/lib/gtAlerts';
import type { GtDossier } from '@/types/dashboard';

export interface GtRiskPopupProps {
  region: string;
  risk: number;
  financial?: number;
  unrest?: number;
  conflict?: number;
  contagion?: number;
  interpretation?: string;
  lat: number;
  lng: number;
  onClose: () => void;
}

function riskColor(score: number): string {
  if (score >= 0.6) return '#ef4444';
  if (score >= 0.4) return '#f97316';
  if (score >= 0.25) return '#eab308';
  return '#22c55e';
}

function formatSignalName(name: string): string {
  return name.replace(/_/g, ' ');
}

async function fetchDossier(region: string, lat: number, lng: number): Promise<GtDossier | null> {
  const candidates = [
    region.trim().toLowerCase(),
    `${lat.toFixed(2)},${lng.toFixed(2)}`,
  ].filter((value, index, list) => value && list.indexOf(value) === index);

  let best: GtDossier | null = null;
  for (const key of candidates) {
    try {
      const response = await fetch(`${API_BASE}/api/analytics/dossier/${encodeURIComponent(key)}`);
      if (!response.ok) continue;
      const payload = (await response.json()) as GtDossier;
      if (!payload.enabled) continue;
      if (!best || (payload.current_risk ?? 0) >= (best.current_risk ?? 0)) {
        best = payload;
      }
    } catch {
      /* optional analytics */
    }
  }
  return best;
}

export function GtRiskPopup({
  region,
  risk,
  financial,
  unrest,
  conflict,
  contagion,
  interpretation,
  lat,
  lng,
  onClose,
}: GtRiskPopupProps) {
  const { t } = useTranslation();
  const color = riskColor(risk);
  const [dossier, setDossier] = useState<GtDossier | null>(null);
  const [loadingSignals, setLoadingSignals] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoadingSignals(true);
    void fetchDossier(region, lat, lng).then((result) => {
      if (!cancelled) {
        setDossier(result);
        setLoadingSignals(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [region, lat, lng]);

  const resolvedInterpretation = interpretation || dossier?.interpretation || '';
  const signals = dossier?.recent_signals || [];

  return (
    <Popup
      longitude={lng}
      latitude={lat}
      closeButton={false}
      closeOnClick={false}
      onClose={onClose}
      className="threat-popup"
      maxWidth="360px"
    >
      <div className="bg-black/95 border border-amber-700/50 rounded-lg overflow-hidden font-mono text-[11px]">
        <div className="px-3 py-2 border-b border-amber-800/40 bg-amber-950/40 flex items-center gap-2">
          <Radar size={14} className="text-amber-400" />
          <span className="text-amber-300 font-bold tracking-widest text-[10px]">
            {t('gtRisk.popupTitle')}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto text-[var(--text-muted)] hover:text-white"
          >
            ✕
          </button>
        </div>
        <div className="p-3 flex flex-col gap-2 max-h-72 overflow-y-auto styled-scrollbar">
          <div className="flex justify-between items-center">
            <span className="text-[var(--text-muted)]">{t('gtRisk.region')}</span>
            <span className="text-white font-bold uppercase">{formatGtRegionLabel(region)}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-[var(--text-muted)]">{t('gtRisk.composite')}</span>
            <span className="font-bold" style={{ color }}>
              {(risk * 100).toFixed(1)}%
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-[10px]">
            <div>
              <div className="text-[var(--text-muted)]">{t('gtRisk.financial')}</div>
              <div className="text-cyan-300">{((financial ?? 0) * 100).toFixed(0)}%</div>
            </div>
            <div>
              <div className="text-[var(--text-muted)]">{t('gtRisk.unrest')}</div>
              <div className="text-orange-300">{((unrest ?? 0) * 100).toFixed(0)}%</div>
            </div>
            <div>
              <div className="text-[var(--text-muted)]">{t('gtRisk.conflict')}</div>
              <div className="text-red-300">{((conflict ?? 0) * 100).toFixed(0)}%</div>
            </div>
          </div>
          {contagion != null && contagion > 0 && (
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">{t('gtRisk.contagion')}</span>
              <span className="text-purple-300">{(contagion * 100).toFixed(1)}%</span>
            </div>
          )}
          {resolvedInterpretation && (
            <p className="text-[var(--text-secondary)] leading-relaxed border-t border-amber-900/40 pt-2">
              <span className="text-amber-400 font-bold">&gt;_ </span>
              {resolvedInterpretation}
            </p>
          )}

          <div className="border-t border-amber-900/40 pt-2">
            <div className="text-[10px] tracking-widest text-amber-500/90 font-bold mb-1.5">
              {t('gtRisk.costlySignals')}
            </div>
            {loadingSignals ? (
              <div className="text-[10px] text-amber-600/80">{t('gtRisk.loadingSignals')}</div>
            ) : signals.length > 0 ? (
              <div className="space-y-1.5">
                {signals.slice(-4).reverse().map((entry, idx) => (
                  <div
                    key={`${entry.timestamp}-${idx}`}
                    className="border-l-2 border-amber-700/60 pl-2 text-[10px] text-[var(--text-secondary)]"
                  >
                    <div className="text-amber-300 uppercase">
                      {Object.keys(entry.signals || {})
                        .map(formatSignalName)
                        .join(', ') || entry.domain}
                    </div>
                    <div className="text-[var(--text-muted)] truncate" title={entry.source}>
                      {entry.source || t('gtRisk.unknownSource')}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[10px] text-amber-600/75 leading-relaxed">
                {t('gtRisk.noSignals')}
              </div>
            )}
          </div>
        </div>
      </div>
    </Popup>
  );
}