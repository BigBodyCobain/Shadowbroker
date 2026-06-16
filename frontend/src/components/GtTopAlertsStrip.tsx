'use client';

import React, { useMemo } from 'react';
import { ChevronRight, Radar } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { useDataKey } from '@/hooks/useDataStore';
import { extractGtAlerts } from '@/lib/gtAlerts';
import type { SelectedEntity } from '@/types/dashboard';

interface Props {
  layerEnabled?: boolean;
  onFlyTo?: (lat: number, lng: number) => void;
  onSelectEntity?: (entity: SelectedEntity | null) => void;
  embedded?: boolean;
}

function pct(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

export default function GtTopAlertsStrip({
  layerEnabled = false,
  onFlyTo,
  onSelectEntity,
  embedded = false,
}: Props) {
  const { t } = useTranslation();
  const gtRisk = useDataKey('gt_risk');

  const { alerts, trackedRegions, plottedRegions, maxRegions } = useMemo(
    () => extractGtAlerts(gtRisk, 8),
    [gtRisk],
  );

  if (!layerEnabled || !gtRisk?.enabled) return null;

  const handleSelect = (alert: (typeof alerts)[number]) => {
    onFlyTo?.(alert.lat, alert.lng);
    onSelectEntity?.({
      id: alert.region,
      type: 'gt_risk',
      name: alert.regionLabel,
      extra: {
        region: alert.region,
        risk: alert.risk,
        financial: alert.financial,
        unrest: alert.unrest,
        conflict: alert.conflict,
        contagion: alert.contagion,
        lat: alert.lat,
        lng: alert.lng,
        risk_spot: alert.risk,
        risk_3d_avg: alert.risk3d,
        risk_delta: alert.riskDelta,
        micro_ignition: alert.ignition,
      },
    });
  };

  const shellClass = embedded
    ? 'pointer-events-auto border-t border-amber-800/30 bg-black/70'
    : 'pointer-events-auto max-w-[min(92vw,52rem)] border border-amber-700/45 bg-black/80 backdrop-blur-sm shadow-[0_0_16px_rgba(245,158,11,0.12)]';

  return (
    <div className={shellClass}>
      <div className="flex items-center gap-2 border-b border-amber-800/35 bg-amber-950/25 px-2.5 py-1.5">
        <Radar size={12} className="text-amber-400 shrink-0" />
        <span className="text-[10px] font-mono font-bold tracking-widest text-amber-300">
          {t('gtAlerts.title')}
        </span>
        <span className="text-[9px] font-mono tracking-wider text-amber-600/80">
          {t('gtAlerts.counts')
            .replace('{plotted}', String(plottedRegions))
            .replace('{tracked}', String(trackedRegions))
            .replace('{max}', String(maxRegions))}
        </span>
      </div>

      {alerts.length === 0 ? (
        <div className="px-2.5 py-2 text-[10px] font-mono tracking-wider text-amber-600/70">
          {t('gtAlerts.empty')}
        </div>
      ) : (
        <div className="flex items-stretch gap-1 overflow-x-auto styled-scrollbar px-2 py-1.5">
          {alerts.map((alert) => (
            <button
              key={alert.region}
              type="button"
              onClick={() => handleSelect(alert)}
              className="group flex min-w-[9.5rem] shrink-0 flex-col gap-0.5 border border-amber-800/35 bg-amber-950/20 px-2 py-1 text-left transition-colors hover:border-amber-600/50 hover:bg-amber-900/25"
            >
              <div className="flex items-center gap-1">
                <span className="truncate text-[10px] font-mono font-bold uppercase text-amber-100">
                  {alert.regionLabel}
                </span>
                {alert.ignition && (
                  <span className="shrink-0 border border-orange-700/50 px-1 text-[8px] font-mono text-orange-300">
                    {t('gtAlerts.ignition')}
                  </span>
                )}
                <ChevronRight
                  size={10}
                  className="ml-auto shrink-0 text-amber-600/60 group-hover:text-amber-400"
                />
              </div>
              <div className="text-[9px] font-mono tracking-wider text-amber-500/90">
                {t('gtAlerts.line')
                  .replace('{risk}', pct(alert.risk))
                  .replace('{conflict}', pct(alert.conflict))}
              </div>
            </button>
          ))}
        </div>
      )}

      <div className="border-t border-amber-900/30 px-2.5 py-1 text-[9px] font-mono leading-relaxed text-amber-600/65">
        {t('gtAlerts.hint')}
      </div>
    </div>
  );
}