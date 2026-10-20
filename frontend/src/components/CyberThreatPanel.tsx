'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Minus, Plus, RefreshCw } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { useTranslation } from '@/i18n';

interface CyberThreat {
  id: string;
  name: string;
  vendor?: string;
  product?: string;
  severity?: string;
  date?: string;
  due?: string;
  source?: string;
}

interface CyberPayload {
  threats: CyberThreat[];
  stats?: {
    active_cves?: number;
    threat_level?: string;
    cisa_total?: number;
  };
}

interface Props {
  layerEnabled?: boolean;
}

export default function CyberThreatPanel({ layerEnabled = false }: Props) {
  const { t } = useTranslation();
  const [isMinimized, setIsMinimized] = useState(true);
  const [data, setData] = useState<CyberPayload | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!layerEnabled) {
      setData(null);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/cyber-threats`, { cache: 'no-store' });
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

  const threats = data?.threats || [];
  const threatLevel = data?.stats?.threat_level || '—';

  return (
    <div className="pointer-events-auto flex-shrink-0 border border-amber-700/40 bg-black/75 backdrop-blur-sm shadow-[0_0_18px_rgba(245,158,11,0.10)]">
      <div
        className="flex items-center justify-between border-b border-amber-700/30 bg-amber-950/20 px-3 py-2.5 cursor-pointer hover:bg-amber-950/40 transition-colors"
        onClick={() => setIsMinimized((prev) => !prev)}
      >
        <div className="flex items-center gap-2">
          <AlertTriangle size={16} className="text-amber-400" />
          <span className="text-[12px] font-mono font-bold tracking-widest text-amber-400">
            {t('layers.cyberThreats').toUpperCase()}
          </span>
          {layerEnabled && threats.length > 0 && (
            <span className="text-[11px] font-mono px-1.5 py-0.5 bg-red-900/30 border border-red-700/40 text-red-300 tracking-wider">
              {threats.length} ACTIVE
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
            title="Refresh CISA KEV overlay"
            className="text-amber-600 transition-colors hover:text-amber-400 p-0.5"
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          </button>
          {isMinimized ? <Plus size={16} className="text-amber-400" /> : <Minus size={16} className="text-amber-400" />}
        </div>
      </div>

      {!isMinimized && (
        <div className="px-3 py-2 max-h-52 overflow-y-auto styled-scrollbar space-y-1.5">
          {!layerEnabled ? (
            <div className="text-[11px] font-mono tracking-wider text-amber-600/70 py-1">
              Enable the Cyber Threats layer to load CISA KEV.
            </div>
          ) : threats.length === 0 ? (
            <div className="text-[11px] font-mono tracking-wider text-amber-500/80 py-1">
              No CISA KEV additions in the last 30 days.
            </div>
          ) : (
            <>
              <div className="text-[10px] font-mono tracking-widest text-amber-500/80 pb-1">
                THREAT LEVEL: {threatLevel}
              </div>
              {threats.map((threat) => (
                <div key={threat.id} className="border border-amber-700/30 bg-amber-950/15 px-2 py-1.5">
                  <div className="text-[11px] font-mono font-bold tracking-wide text-amber-200 leading-tight">
                    {threat.id}
                  </div>
                  <div className="text-[10px] font-mono text-amber-500/90 mt-0.5 leading-tight">
                    {threat.name}
                  </div>
                  {(threat.vendor || threat.product) && (
                    <div className="text-[10px] font-mono text-amber-600/80 mt-0.5">
                      {[threat.vendor, threat.product].filter(Boolean).join(' · ')}
                    </div>
                  )}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
