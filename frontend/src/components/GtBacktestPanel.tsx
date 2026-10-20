'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Minus, Plus, Radar, RefreshCw, XCircle } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { useTranslation } from '@/i18n';
import type { GtBacktestReport, GtMicroRollingReport, GtRollingReport } from '@/types/dashboard';

interface Props {
  layerEnabled?: boolean;
  embedded?: boolean;
}

type TabId = 'benchmark' | 'operational';

function pct(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(1)}%`;
}

export default function GtBacktestPanel({ layerEnabled = false, embedded = false }: Props) {
  const { t } = useTranslation();
  const [isMinimized, setIsMinimized] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>('operational');
  const [benchmark, setBenchmark] = useState<GtBacktestReport | null>(null);
  const [rolling, setRolling] = useState<GtRollingReport | null>(null);
  const [micro, setMicro] = useState<GtMicroRollingReport | null>(null);
  const [loadingBenchmark, setLoadingBenchmark] = useState(false);
  const [loadingRolling, setLoadingRolling] = useState(false);
  const [loadingMicro, setLoadingMicro] = useState(false);
  const [showFailures, setShowFailures] = useState(false);

  const refreshBenchmark = useCallback(async () => {
    if (!layerEnabled) {
      setBenchmark(null);
      return;
    }
    setLoadingBenchmark(true);
    try {
      const res = await fetch(`${API_BASE}/api/analytics/backtest?expanded=true&tune=false`);
      if (res.ok) setBenchmark(await res.json());
    } catch {
      /* non-fatal */
    } finally {
      setLoadingBenchmark(false);
    }
  }, [layerEnabled]);

  const refreshRolling = useCallback(async () => {
    if (!layerEnabled) {
      setRolling(null);
      return;
    }
    setLoadingRolling(true);
    try {
      const res = await fetch(`${API_BASE}/api/analytics/rolling?weeks=8`);
      if (res.ok) setRolling(await res.json());
    } catch {
      /* non-fatal */
    } finally {
      setLoadingRolling(false);
    }
  }, [layerEnabled]);

  const refreshMicro = useCallback(async () => {
    if (!layerEnabled) {
      setMicro(null);
      return;
    }
    setLoadingMicro(true);
    try {
      const res = await fetch(`${API_BASE}/api/analytics/rolling/micro?window_days=3&limit=6`);
      if (res.ok) setMicro(await res.json());
    } catch {
      /* non-fatal */
    } finally {
      setLoadingMicro(false);
    }
  }, [layerEnabled]);

  const refresh = useCallback(async () => {
    await Promise.all([refreshBenchmark(), refreshRolling(), refreshMicro()]);
  }, [refreshBenchmark, refreshRolling, refreshMicro]);

  useEffect(() => {
    refresh();
    if (!layerEnabled) return undefined;
    const id = setInterval(refresh, 15 * 60_000);
    return () => clearInterval(id);
  }, [refresh, layerEnabled]);

  const failures = (benchmark?.cases || []).filter((row) => !row.correct);
  const operationalScorable = Boolean(
    rolling && ((rolling.weeks_scorable ?? 0) > 0 || rolling.latest?.scorable),
  );
  const benchmarkPass = benchmark?.meets_target;
  const rollingPass = rolling?.meets_target;
  const passBadge =
    activeTab === 'benchmark'
      ? benchmarkPass
      : operationalScorable
        ? rollingPass
        : undefined;
  const showCollectingBadge =
    activeTab === 'operational' && layerEnabled && rolling?.enabled && !operationalScorable;
  const loading =
    activeTab === 'benchmark'
      ? loadingBenchmark
      : loadingRolling || loadingMicro;
  const latest = rolling?.latest;
  const microRegions = micro?.ignitions?.length
    ? micro.ignitions
    : (micro?.top_regions || []).slice(0, 4);

  const shellClass = embedded
    ? 'pointer-events-auto flex-shrink-0 border-b border-amber-800/30 bg-black/70'
    : 'pointer-events-auto flex-shrink-0 border border-amber-700/40 bg-black/75 backdrop-blur-sm shadow-[0_0_18px_rgba(245,158,11,0.10)]';

  return (
    <div className={shellClass}>
      <div
        className="flex items-center justify-between border-b border-amber-700/30 bg-amber-950/20 px-3 py-2.5 cursor-pointer hover:bg-amber-950/40 transition-colors"
        onClick={() => setIsMinimized((prev) => !prev)}
      >
        <div className="flex items-center gap-2">
          <Radar size={16} className="text-amber-400" />
          <span className="text-[12px] font-mono font-bold tracking-widest text-amber-400">
            {t('gtBacktest.title').toUpperCase()}
          </span>
          {showCollectingBadge && (
            <span className="text-[11px] font-mono px-1.5 py-0.5 tracking-wider border bg-amber-900/25 border-amber-700/40 text-amber-300">
              {t('gtBacktest.collecting')}
            </span>
          )}
          {layerEnabled && passBadge != null && (
            <span
              className={`text-[11px] font-mono px-1.5 py-0.5 tracking-wider border ${
                passBadge
                  ? 'bg-emerald-900/30 border-emerald-700/40 text-emerald-300'
                  : 'bg-red-900/30 border-red-700/40 text-red-300'
              }`}
            >
              {passBadge ? t('gtBacktest.pass') : t('gtBacktest.fail')}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              refresh();
            }}
            title={t('gtBacktest.refresh')}
            className="text-amber-600 transition-colors hover:text-amber-400 p-0.5"
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          </button>
          {isMinimized ? (
            <Plus size={16} className="text-amber-400" />
          ) : (
            <Minus size={16} className="text-amber-400" />
          )}
        </div>
      </div>

      {!isMinimized && (
        <div className="px-3 py-2 max-h-60 overflow-y-auto styled-scrollbar space-y-2">
          {!layerEnabled ? (
            <div className="text-[11px] font-mono tracking-wider text-amber-600/70 py-1">
              {t('gtBacktest.layerOff')}
            </div>
          ) : (
            <>
              <div className="flex gap-1">
                {(['operational', 'benchmark'] as TabId[]).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setActiveTab(tab)}
                    className={`text-[10px] font-mono tracking-widest px-2 py-0.5 border transition-colors ${
                      activeTab === tab
                        ? 'border-amber-500/60 bg-amber-900/30 text-amber-200'
                        : 'border-amber-800/30 text-amber-600/80 hover:text-amber-400'
                    }`}
                  >
                    {tab === 'benchmark'
                      ? t('gtBacktest.tabBenchmark')
                      : t('gtBacktest.tabOperational')}
                  </button>
                ))}
              </div>

              {activeTab === 'benchmark' ? (
                !benchmark?.enabled ? (
                  <div className="text-[11px] font-mono tracking-wider text-amber-600/70 py-1">
                    {t('gtBacktest.disabled')}
                  </div>
                ) : loadingBenchmark && !benchmark.accuracy ? (
                  <div className="text-[11px] font-mono tracking-wider text-amber-500/80 py-1">
                    {t('gtBacktest.loading')}
                  </div>
                ) : (
                  <>
                    <div className="text-[10px] font-mono tracking-wider text-amber-600/60">
                      {t('gtBacktest.benchmarkNote')}
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="border border-amber-800/30 bg-amber-950/15 px-2 py-1.5">
                        <div className="text-[10px] font-mono tracking-widest text-amber-600/80">
                          {t('gtBacktest.accuracy')}
                        </div>
                        <div className="text-[13px] font-mono font-bold text-amber-200">
                          {pct(benchmark.accuracy)}
                        </div>
                      </div>
                      <div className="border border-amber-800/30 bg-amber-950/15 px-2 py-1.5">
                        <div className="text-[10px] font-mono tracking-widest text-amber-600/80">
                          {t('gtBacktest.confidence')}
                        </div>
                        <div className="text-[13px] font-mono font-bold text-amber-200">
                          {pct(benchmark.confidence_rate)}
                        </div>
                      </div>
                    </div>

                    <div className="text-[10px] font-mono tracking-wider text-amber-600/70 leading-relaxed">
                      {t('gtBacktest.cases').replace('{count}', String(benchmark.total_cases))} ·{' '}
                      {t('gtBacktest.threshold').replace('{value}', benchmark.alert_threshold.toFixed(2))} ·{' '}
                      {t('gtBacktest.target').replace('{value}', pct(benchmark.target_confidence))}
                    </div>

                    <div className="flex flex-wrap gap-2 text-[10px] font-mono tracking-wider">
                      <span className="text-emerald-400">TP {benchmark.true_positives}</span>
                      <span className="text-emerald-400">TN {benchmark.true_negatives}</span>
                      <span className="text-red-400">FP {benchmark.false_positives}</span>
                      <span className="text-red-400">FN {benchmark.false_negatives}</span>
                    </div>

                    <div className="flex items-center gap-1.5 text-[10px] font-mono tracking-wider text-amber-500/90">
                      {benchmark.meets_target ? (
                        <CheckCircle2 size={12} className="text-emerald-400 shrink-0" />
                      ) : (
                        <XCircle size={12} className="text-red-400 shrink-0" />
                      )}
                      <span>
                        {benchmark.meets_target
                          ? t('gtBacktest.meetsTarget')
                          : t('gtBacktest.belowTarget')}
                      </span>
                    </div>

                    {failures.length > 0 && (
                      <div>
                        <button
                          type="button"
                          onClick={() => setShowFailures((prev) => !prev)}
                          className="text-[10px] font-mono tracking-widest text-red-400 hover:text-red-300"
                        >
                          {showFailures ? '−' : '+'} {t('gtBacktest.misclassified').replace('{count}', String(failures.length))}
                        </button>
                        {showFailures && (
                          <div className="mt-1 space-y-1">
                            {failures.map((row) => (
                              <div
                                key={row.case_id}
                                className="border border-red-800/30 bg-red-950/15 px-2 py-1 text-[10px] font-mono text-red-200/90"
                              >
                                {row.name} ({row.kind})
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )
              ) : !rolling?.enabled && !micro?.enabled ? (
                <div className="text-[11px] font-mono tracking-wider text-amber-600/70 py-1">
                  {t('gtBacktest.disabled')}
                </div>
              ) : (loadingRolling || loadingMicro) && !rolling?.latest && !micro?.regions_tracked ? (
                <div className="text-[11px] font-mono tracking-wider text-amber-500/80 py-1">
                  {t('gtBacktest.operationalLoading')}
                </div>
              ) : (
                <>
                  <div className="border border-amber-800/25 bg-amber-950/10 px-2 py-1.5 space-y-1">
                    <div className="text-[10px] font-mono tracking-widest text-amber-500/90">
                      {t('gtBacktest.microTitle').toUpperCase()}
                    </div>
                    {micro?.enabled ? (
                      <>
                        <div className="text-[10px] font-mono tracking-wider text-amber-600/75">
                          {t('gtBacktest.microWindow')
                            .replace('{days}', String(micro.window_days))
                            .replace('{delta}', micro.ignition_delta.toFixed(2))}
                        </div>
                        <div className="flex flex-wrap gap-2 text-[10px] font-mono tracking-wider">
                          <span className="text-orange-300">
                            {t('gtBacktest.microIgnitions').replace(
                              '{count}',
                              String(micro.ignition_count)
                            )}
                          </span>
                          <span className="text-amber-300/90">
                            {t('gtBacktest.microAlerted3d').replace(
                              '{count}',
                              String(micro.alerted_3d_count)
                            )}
                          </span>
                        </div>
                        {microRegions.length > 0 ? (
                          <div className="space-y-0.5">
                            {microRegions.map((row) => (
                              <div
                                key={row.region}
                                className="text-[10px] font-mono text-amber-200/85 flex items-center gap-1.5"
                              >
                                {row.ignition && (
                                  <span className="text-orange-400 border border-orange-700/40 px-1 text-[9px]">
                                    {t('gtBacktest.microIgnitionBadge')}
                                  </span>
                                )}
                                <span>
                                  {t('gtBacktest.microRegionLine')
                                    .replace('{region}', row.region)
                                    .replace('{spot}', pct(row.spot_risk))
                                    .replace('{avg}', pct(row.risk_3d_avg))
                                    .replace('{delta}', pct(row.risk_delta))}
                                </span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-[10px] font-mono tracking-wider text-amber-600/65">
                            {t('gtBacktest.microEmpty')}
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="text-[10px] font-mono tracking-wider text-amber-600/65">
                        {t('gtBacktest.microEmpty')}
                      </div>
                    )}
                  </div>

                  <div className="text-[10px] font-mono tracking-widest text-amber-600/80 pt-1">
                    {t('gtBacktest.tabOperational').toUpperCase()} — {t('gtBacktest.operationalTrend')}
                  </div>

                  {!rolling || rolling.weeks_stored === 0 ? (
                    <div className="text-[10px] font-mono tracking-wider text-amber-600/70 py-1">
                      {t('gtBacktest.operationalEmpty')}
                    </div>
                  ) : (
                    <>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="border border-amber-800/30 bg-amber-950/15 px-2 py-1.5">
                      <div className="text-[10px] font-mono tracking-widest text-amber-600/80">
                        {t('gtBacktest.accuracy')}
                      </div>
                      <div className="text-[13px] font-mono font-bold text-amber-200">
                        {latest?.scorable ? pct(latest.accuracy) : '—'}
                      </div>
                    </div>
                    <div className="border border-amber-800/30 bg-amber-950/15 px-2 py-1.5">
                      <div className="text-[10px] font-mono tracking-widest text-amber-600/80">
                        {t('gtBacktest.confidence')}
                      </div>
                      <div className="text-[13px] font-mono font-bold text-amber-200">
                        {latest?.scorable ? pct(latest.confidence_rate) : '—'}
                      </div>
                    </div>
                  </div>

                  <div className="text-[10px] font-mono tracking-wider text-amber-600/70 leading-relaxed">
                    {t('gtBacktest.operationalWeeks')
                      .replace('{stored}', String(rolling.weeks_stored))
                      .replace('{scorable}', String(rolling.weeks_scorable))}
                    {latest
                      ? ` · ${t('gtBacktest.operationalLabeled')
                          .replace('{labeled}', String(latest.labeled))
                          .replace('{pending}', String(latest.pending))}`
                      : ''}
                  </div>

                  {latest && !latest.scorable && (
                    <div className="text-[10px] font-mono tracking-wider text-amber-500/80">
                      {t('gtBacktest.operationalMinLabels').replace(
                        '{count}',
                        String(rolling.min_labeled_per_week)
                      )}
                    </div>
                  )}

                  {latest?.scorable && (
                    <div className="flex flex-wrap gap-2 text-[10px] font-mono tracking-wider">
                      <span className="text-emerald-400">TP {latest.true_positives}</span>
                      <span className="text-emerald-400">TN {latest.true_negatives}</span>
                      <span className="text-red-400">FP {latest.false_positives}</span>
                      <span className="text-red-400">FN {latest.false_negatives}</span>
                    </div>
                  )}

                  {(rolling.accuracy_series?.length ?? 0) > 0 && (
                    <div>
                      <div className="text-[10px] font-mono tracking-widest text-amber-600/80 mb-1">
                        {t('gtBacktest.operationalTrend')}
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {rolling.accuracy_series.map((point) => (
                          <span
                            key={point.week_id}
                            className="text-[10px] font-mono border border-amber-800/30 bg-amber-950/20 px-1.5 py-0.5 text-amber-200/90"
                            title={`${point.labeled} labeled`}
                          >
                            {point.week_id.replace('-W', 'w')}: {pct(point.accuracy)}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {latest?.scorable && (
                    <div className="flex items-center gap-1.5 text-[10px] font-mono tracking-wider text-amber-500/90">
                      {rolling.meets_target ? (
                        <CheckCircle2 size={12} className="text-emerald-400 shrink-0" />
                      ) : (
                        <XCircle size={12} className="text-red-400 shrink-0" />
                      )}
                      <span>
                        {rolling.improving_vs_prior
                          ? t('gtBacktest.operationalImproving')
                          : t('gtBacktest.operationalFlat')}
                        {' · '}
                        {rolling.meets_target
                          ? t('gtBacktest.meetsTarget')
                          : t('gtBacktest.belowTarget')}
                      </span>
                    </div>
                  )}
                    </>
                  )}
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}