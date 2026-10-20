'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, Minus, Network, Plus, X } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { isEntityGraphEligible, mapEntityToGraphType } from '@/lib/entityGraph';
import type { SelectedEntity } from '@/types/dashboard';

interface GraphNode {
  id: string;
  label: string;
  type: string;
  properties?: Record<string, unknown>;
}

interface GraphLink {
  source: string;
  target: string;
  label: string;
}

interface Props {
  entity: SelectedEntity | null;
  onClose: () => void;
}

const TYPE_COLORS: Record<string, string> = {
  aircraft: 'text-cyan-300',
  vessel: 'text-cyan-400',
  company: 'text-amber-300',
  person: 'text-violet-300',
  country: 'text-emerald-300',
  sanction: 'text-red-300',
  ip: 'text-orange-300',
  event: 'text-yellow-300',
};

export default function EntityGraphPanel({ entity, onClose }: Props) {
  const [isMinimized, setIsMinimized] = useState(false);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [links, setLinks] = useState<GraphLink[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadGraph = useCallback(async () => {
    if (!entity || !isEntityGraphEligible(entity)) return;
    const type = mapEntityToGraphType(entity.type);
    if (!type) return;
    const id = String(entity.name || entity.extra?.callsign || entity.extra?.registration || entity.id);
    const params = new URLSearchParams({ type, id });
    if (entity.extra?.registration) params.set('registration', String(entity.extra.registration));
    if (entity.extra?.icao24) params.set('icao24', String(entity.extra.icao24));
    if (entity.extra?.model) params.set('model', String(entity.extra.model));

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/entity/expand?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || 'Expand failed');
      setNodes(data.nodes || []);
      setLinks(data.links || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Graph unavailable');
      setNodes([]);
      setLinks([]);
    } finally {
      setLoading(false);
    }
  }, [entity]);

  useEffect(() => {
    if (entity) loadGraph();
    else {
      setNodes([]);
      setLinks([]);
    }
  }, [entity, loadGraph]);

  if (!entity || !isEntityGraphEligible(entity)) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[250] w-80 max-h-[50vh] pointer-events-auto flex flex-col border border-cyan-700/40 bg-black/85 backdrop-blur-sm shadow-[0_0_24px_rgba(34,211,238,0.12)]">
      <div
        className="flex items-center justify-between border-b border-cyan-700/30 bg-cyan-950/25 px-3 py-2.5 cursor-pointer hover:bg-cyan-950/40 transition-colors"
        onClick={() => setIsMinimized((prev) => !prev)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Network size={16} className="text-cyan-400 shrink-0" />
          <span className="text-[12px] font-mono font-bold tracking-widest text-cyan-400 truncate">
            ENTITY GRAPH
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onClose();
            }}
            className="text-cyan-600 hover:text-cyan-300 transition-colors"
            title="Close"
          >
            <X size={14} />
          </button>
          {isMinimized ? (
            <Plus size={16} className="text-cyan-400" />
          ) : (
            <Minus size={16} className="text-cyan-400" />
          )}
        </div>
      </div>

      {!isMinimized && (
        <div className="px-3 py-2 overflow-y-auto styled-scrollbar flex-1 space-y-2">
          <div className="text-[10px] font-mono tracking-wider text-cyan-600 truncate">
            {entity.type.toUpperCase()} · {entity.name || entity.id}
          </div>

          {loading && (
            <div className="flex items-center gap-2 text-[11px] font-mono text-cyan-500 tracking-wider">
              <Loader2 size={12} className="animate-spin" />
              RESOLVING…
            </div>
          )}

          {error && (
            <div className="border border-red-500/30 bg-red-950/20 px-2 py-1.5 text-[11px] font-mono text-red-400">
              {error}
            </div>
          )}

          {!loading && !error && (
            <>
              <div className="space-y-1">
                {nodes.map((n) => (
                  <div
                    key={n.id}
                    className="border border-cyan-900/40 bg-black/50 px-2 py-1.5"
                  >
                    <div className={`text-[9px] font-mono tracking-[0.2em] uppercase opacity-70 ${TYPE_COLORS[n.type] || 'text-cyan-500'}`}>
                      {n.type}
                    </div>
                    <div className="text-[11px] font-mono text-cyan-200 leading-snug">{n.label}</div>
                  </div>
                ))}
              </div>

              {links.length > 0 && (
                <div className="border-t border-cyan-900/40 pt-2">
                  <div className="text-[10px] font-mono tracking-[0.2em] text-cyan-600 mb-1">RELATIONSHIPS</div>
                  {links.slice(0, 24).map((l, i) => (
                    <div key={`${l.source}-${l.target}-${i}`} className="text-[10px] font-mono text-cyan-500/90 truncate leading-relaxed">
                      {l.label}: {l.source.split(':').pop()} → {l.target.split(':').pop()}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
