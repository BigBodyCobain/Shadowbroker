'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Minus, Plus, RefreshCw, Target } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { useTranslation } from '@/i18n';

interface Supplier {
  id: string;
  name: string;
  city: string;
  country: string;
  category: string;
  risk_level: string;
  active_threats: string[];
}

interface ScmPayload {
  suppliers: Supplier[];
  critical_count: number;
  total: number;
  timestamp?: string;
}

interface Props {
  /** Only evaluate threats when the map layer is enabled. */
  layerEnabled?: boolean;
}

export default function ScmPanel({ layerEnabled = false }: Props) {
  const { t } = useTranslation();
  const [isMinimized, setIsMinimized] = useState(true);
  const [data, setData] = useState<ScmPayload | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!layerEnabled) {
      setData(null);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/scm-suppliers`);
      if (res.ok) setData(await res.json());
    } catch {
      /* non-fatal */
    } finally {
      setLoading(false);
    }
  }, [layerEnabled]);

  useEffect(() => {
    refresh();
    if (!layerEnabled) return undefined;
    const id = setInterval(refresh, 5 * 60_000);
    return () => clearInterval(id);
  }, [refresh, layerEnabled]);

  const critical = (data?.suppliers || []).filter(
    (s) => s.risk_level === 'CRITICAL' || s.risk_level === 'HIGH',
  );

  return (
    <div className="pointer-events-auto flex-shrink-0 border border-cyan-700/40 bg-black/75 backdrop-blur-sm shadow-[0_0_18px_rgba(34,211,238,0.10)]">
      <div
        className="flex items-center justify-between border-b border-cyan-700/30 bg-cyan-950/20 px-3 py-2.5 cursor-pointer hover:bg-cyan-950/40 transition-colors"
        onClick={() => setIsMinimized((prev) => !prev)}
      >
        <div className="flex items-center gap-2">
          <Target size={16} className="text-cyan-400" />
          <span className="text-[12px] font-mono font-bold tracking-widest text-cyan-400">
            {t('scm.title').toUpperCase()}
          </span>
          {layerEnabled && critical.length > 0 && (
            <span className="text-[11px] font-mono px-1.5 py-0.5 bg-red-900/30 border border-red-700/40 text-red-300 tracking-wider">
              {critical.length} ALERT{critical.length === 1 ? '' : 'S'}
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
            title="Refresh SCM overlay"
            className="text-cyan-600 transition-colors hover:text-cyan-400 p-0.5"
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          </button>
          {isMinimized ? (
            <Plus size={16} className="text-cyan-400" />
          ) : (
            <Minus size={16} className="text-cyan-400" />
          )}
        </div>
      </div>

      {!isMinimized && (
        <div className="px-3 py-2 max-h-44 overflow-y-auto styled-scrollbar space-y-1.5">
          {!layerEnabled ? (
            <div className="text-[11px] font-mono tracking-wider text-cyan-600/70 py-1">
              {t('scm.layerOff')}
            </div>
          ) : critical.length === 0 ? (
            <div className="text-[11px] font-mono tracking-wider text-cyan-500/80 py-1">
              {t('scm.allClear')}
            </div>
          ) : (
            critical.map((s) => (
              <div key={s.id} className="border border-red-700/30 bg-red-950/15 px-2 py-1.5">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[11px] font-mono font-bold tracking-wide text-red-300 leading-tight">
                    {s.name}
                  </span>
                  <span className="text-[10px] font-mono tracking-widest text-red-400 shrink-0">
                    {s.risk_level}
                  </span>
                </div>
                <div className="text-[10px] font-mono text-cyan-600/80 mt-0.5">
                  {s.city}, {s.country}
                </div>
                {s.active_threats.map((threat) => (
                  <div key={threat} className="flex items-center gap-1.5 text-[10px] font-mono text-amber-400/90 mt-1 tracking-wide">
                    <AlertTriangle size={10} className="shrink-0" />
                    {threat}
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
