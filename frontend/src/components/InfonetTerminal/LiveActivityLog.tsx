'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Activity } from 'lucide-react';
import { useDataKeys } from '@/hooks/useDataStore';
import type { DashboardData } from '@/types/dashboard';

interface ActivityLog {
  id: string;
  timestamp: string;
  gate: string;
  user: string;
  content: string;
  color: string;
}

const COLORS = [
  'text-cyan-400',
  'text-fuchsia-400',
  'text-emerald-400',
  'text-violet-400',
  'text-rose-400',
  'text-blue-400',
  'text-lime-400',
  'text-amber-400',
];

function pickColor(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  return COLORS[Math.abs(hash) % COLORS.length];
}

function timeStr(): string {
  return new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

type DataSlice = Pick<DashboardData, 'news' | 'trending_markets' | 'commercial_flights' | 'military_flights' | 'ships' | 'correlations' | 'threat_level' | 'liveuamap'>;
const DATA_KEYS = ['news', 'trending_markets', 'commercial_flights', 'military_flights', 'ships', 'correlations', 'threat_level', 'liveuamap'] as const;

export default function LiveActivityLog() {
  const [logs, setLogs] = useState<ActivityLog[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevDataRef = useRef<DataSlice | null>(null);

  const data = useDataKeys(DATA_KEYS) as DataSlice;

  // Generate event logs from real data changes
  useEffect(() => {
    const prev = prevDataRef.current;
    if (!prev) {
      // First load — generate initial summary logs
      prevDataRef.current = data;
      const initial: ActivityLog[] = [];
      const now = timeStr();

      if (data?.news?.length) {
        initial.push({ id: crypto.randomUUID(), timestamp: now, gate: 'SYS', user: 'SYSTEM', content: `Wire feed loaded: ${data.news.length} articles indexed`, color: 'text-gray-500' });
      }
      if (data?.trending_markets?.length) {
        initial.push({ id: crypto.randomUUID(), timestamp: now, gate: 'SYS', user: 'SYSTEM', content: `${data.trending_markets.length} prediction markets synced from Polymarket/Kalshi`, color: 'text-gray-500' });
      }
      if (data?.commercial_flights?.length || data?.military_flights?.length) {
        const total = (data.commercial_flights?.length || 0) + (data.military_flights?.length || 0);
        initial.push({ id: crypto.randomUUID(), timestamp: now, gate: 'tracked-planes', user: 'SYSTEM', content: `ADS-B: ${total} flights tracked`, color: 'text-gray-500' });
      }
      if (data?.ships?.length) {
        initial.push({ id: crypto.randomUUID(), timestamp: now, gate: 'SYS', user: 'SYSTEM', content: `AIS: ${data.ships.length} vessels tracked`, color: 'text-gray-500' });
      }
      if (data?.threat_level) {
        initial.push({ id: crypto.randomUUID(), timestamp: now, gate: 'SYS', user: 'SYSTEM', content: `Threat level: ${data.threat_level.level} (${data.threat_level.score}/100)`, color: pickColor('threat') });
      }

      if (initial.length > 0) setLogs(initial);
      return;
    }

    // Diff to generate new events
    const newLogs: ActivityLog[] = [];
    const now = timeStr();

    // New articles
    if (data?.news && prev.news) {
      const prevIds = new Set(prev.news.map(n => n.id));
      const newArticles = data.news.filter(n => !prevIds.has(n.id));
      for (const article of newArticles.slice(0, 3)) {
        newLogs.push({
          id: crypto.randomUUID(), timestamp: now,
          gate: 'world-news', user: article.source || 'WIRE',
          content: article.title,
          color: article.breaking ? 'text-red-400' : pickColor(article.source || 'news'),
        });
      }
    }

    // New markets
    if (data?.trending_markets && prev.trending_markets) {
      const prevSlugs = new Set(prev.trending_markets.map(m => m.slug));
      const newMarkets = data.trending_markets.filter(m => !prevSlugs.has(m.slug));
      for (const market of newMarkets.slice(0, 2)) {
        const pct = market.consensus_pct ?? market.polymarket_pct ?? 0;
        newLogs.push({
          id: crypto.randomUUID(), timestamp: now,
          gate: 'prediction-markets', user: 'ORACLE',
          content: `New market: "${market.title}" (${pct}% YES)`,
          color: 'text-amber-400',
        });
      }
    }

    // Flight count changes
    const curFlights = (data?.commercial_flights?.length || 0) + (data?.military_flights?.length || 0);
    const prevFlights = (prev.commercial_flights?.length || 0) + (prev.military_flights?.length || 0);
    if (Math.abs(curFlights - prevFlights) > 5) {
      newLogs.push({
        id: crypto.randomUUID(), timestamp: now,
        gate: 'tracked-planes', user: 'ADS-B',
        content: `Flight count ${curFlights > prevFlights ? 'increased' : 'decreased'}: ${prevFlights} → ${curFlights}`,
        color: 'text-cyan-400',
      });
    }

    // Ship count changes
    const curShips = data?.ships?.length || 0;
    const prevShips = prev.ships?.length || 0;
    if (Math.abs(curShips - prevShips) > 3) {
      newLogs.push({
        id: crypto.randomUUID(), timestamp: now,
        gate: 'SYS', user: 'AIS',
        content: `Vessel count updated: ${prevShips} → ${curShips}`,
        color: 'text-blue-400',
      });
    }

    // Correlation alerts
    if (data?.correlations && prev.correlations) {
      const prevCount = prev.correlations.length;
      const curCount = data.correlations.length;
      if (curCount > prevCount) {
        const newCorrels = data.correlations.slice(prevCount);
        for (const corr of newCorrels.slice(0, 2)) {
          newLogs.push({
            id: crypto.randomUUID(), timestamp: now,
            gate: 'gathered-intel', user: 'CORRELATION-ENGINE',
            content: `${corr.type.replace(/_/g, ' ').toUpperCase()} [${corr.severity}] — ${corr.drivers.slice(0, 2).join(', ')}`,
            color: 'text-fuchsia-400',
          });
        }
      }
    }

    // Threat level changes
    if (data?.threat_level && prev.threat_level && data.threat_level.level !== prev.threat_level.level) {
      newLogs.push({
        id: crypto.randomUUID(), timestamp: now,
        gate: 'SYS', user: 'SYSTEM',
        content: `THREAT LEVEL CHANGE: ${prev.threat_level.level} → ${data.threat_level.level}`,
        color: data.threat_level.level === 'SEVERE' ? 'text-red-400' : 'text-yellow-400',
      });
    }

    // LiveUAMap events
    if (data?.liveuamap && prev.liveuamap) {
      const prevLiveIds = new Set(prev.liveuamap.map(e => e.id));
      const newEvents = data.liveuamap.filter(e => !prevLiveIds.has(e.id));
      for (const evt of newEvents.slice(0, 2)) {
        newLogs.push({
          id: crypto.randomUUID(), timestamp: now,
          gate: 'ukraine-front', user: 'LIVEUAMAP',
          content: evt.title || evt.description || 'New conflict event',
          color: 'text-rose-400',
        });
      }
    }

    if (newLogs.length > 0) {
      setLogs(prev => {
        const updated = [...prev, ...newLogs];
        if (updated.length > 50) return updated.slice(-50);
        return updated;
      });
    }

    prevDataRef.current = data;
  }, [data]);

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [logs]);

  return (
    <div className="mt-6 border border-gray-800 bg-[#0a0a0a] p-3 shrink-0 flex flex-col h-48">
      <div className="flex items-center justify-between mb-2 border-b border-gray-800 pb-2 shrink-0">
        <h3 className="text-cyan-400 font-bold flex items-center text-xs tracking-widest uppercase">
          <Activity size={14} className="mr-2 animate-pulse text-green-400" />
          Live Network Telemetry
        </h3>
        <span className="text-sm text-gray-500 font-mono">
          FEEDS: {logs.length} EVENTS
        </span>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto font-mono text-sm sm:text-xs space-y-1.5 pr-2 [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:bg-gray-800"
      >
        {logs.length === 0 && (
          <div className="text-gray-600 italic text-center py-4">Waiting for data stream...</div>
        )}
        {logs.map(log => (
          <div key={log.id} className={`flex items-start gap-2 hover:bg-white/5 px-1 py-0.5 transition-colors ${log.color}`}>
            <span className="opacity-50 shrink-0">[{log.timestamp}]</span>
            <span className="opacity-75 shrink-0">[{log.gate}]</span>
            <span className="opacity-90 shrink-0">@{log.user}:</span>
            <span className="flex-1 break-words brightness-110">{log.content}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
