'use client';

import React, { useState } from 'react';
import { Activity, Newspaper, TrendingUp, Vote, ChevronRight } from 'lucide-react';
import { useDataKeys } from '@/hooks/useDataStore';
import type { DashboardData } from '@/types/dashboard';
import LiveActivityLog from './LiveActivityLog';

function formatTime(pubDate: string): string {
  try {
    const now = Date.now();
    const pub = new Date(pubDate).getTime();
    const diff = Math.floor((now - pub) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  } catch { return ''; }
}

const THREAT_COLORS: Record<string, { text: string; bg: string; border: string }> = {
  GREEN: { text: 'text-green-400', bg: 'bg-green-900/30', border: 'border-green-900/50' },
  GUARDED: { text: 'text-blue-400', bg: 'bg-blue-900/30', border: 'border-blue-900/50' },
  ELEVATED: { text: 'text-yellow-400', bg: 'bg-yellow-900/30', border: 'border-yellow-900/50' },
  HIGH: { text: 'text-orange-400', bg: 'bg-orange-900/30', border: 'border-orange-900/50' },
  SEVERE: { text: 'text-red-400', bg: 'bg-red-900/30', border: 'border-red-900/50' },
};

interface TerminalDashboardProps {
  onNavigate: (view: 'market') => void;
  onComingSoon?: (module: string) => void;
}

type DataSlice = Pick<DashboardData, 'news' | 'trending_markets' | 'threat_level' | 'commercial_flights' | 'military_flights' | 'ships' | 'satellites' | 'correlations'>;
const DATA_KEYS = ['news', 'trending_markets', 'threat_level', 'commercial_flights', 'military_flights', 'ships', 'satellites', 'correlations'] as const;

export default function TerminalDashboard({ onNavigate, onComingSoon }: TerminalDashboardProps) {
  const [category, setCategory] = useState('ALL');
  const data = useDataKeys(DATA_KEYS) as DataSlice;

  const news = data?.news || [];
  const markets = data?.trending_markets || [];
  const threat = data?.threat_level;
  const threatStyle = THREAT_COLORS[threat?.level || 'ELEVATED'] || THREAT_COLORS.ELEVATED;

  // Count active data layers
  const flightCount = (data?.commercial_flights?.length || 0) + (data?.military_flights?.length || 0);
  const shipCount = data?.ships?.length || 0;
  const satCount = data?.satellites?.length || 0;
  const correlationCount = data?.correlations?.length || 0;

  // Filter news by category
  const filteredNews = news.filter(article => {
    if (category === 'ALL') return true;
    const title = article.title?.toLowerCase() || '';
    if (category === 'CONFLICT') return article.risk_score >= 7 || title.includes('military') || title.includes('war') || title.includes('attack') || title.includes('strike');
    if (category === 'POLITICS') return title.includes('politic') || title.includes('election') || title.includes('government') || title.includes('president') || title.includes('senate');
    if (category === 'FINANCE') return title.includes('market') || title.includes('stock') || title.includes('economy') || title.includes('bank') || title.includes('trade');
    if (category === 'TECH') return title.includes('tech') || title.includes('cyber') || title.includes('ai') || title.includes('quantum') || title.includes('hack');
    return true;
  }).slice(0, 6);

  // Top 3 markets for dashboard preview
  const topMarkets = markets.slice(0, 3);

  return (
    <div className="border border-gray-800 bg-gray-900/10 p-4 mb-6 shrink-0">
      {/* Dashboard Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 border-b border-gray-800 pb-3 gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-cyan-400 uppercase tracking-widest font-bold">GLOBAL THREAT INTERCEPT</span>
          {threat && (
            <span className={`text-sm px-2 py-0.5 ${threatStyle.bg} ${threatStyle.text} ${threatStyle.border} border animate-pulse font-bold`}>
              {threat.level}
            </span>
          )}
        </div>

        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="bg-[#0a0a0a] border border-gray-800 text-gray-300 text-xs p-1.5 outline-none uppercase tracking-widest cursor-pointer hover:border-gray-600 transition-colors"
        >
          <option value="ALL">ALL TOPICS</option>
          <option value="CONFLICT">CONFLICT</option>
          <option value="POLITICS">POLITICS</option>
          <option value="FINANCE">FINANCE</option>
          <option value="TECH">TECH</option>
        </select>
      </div>

      {/* Dashboard Content — 2x2 grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Top Stories (real RSS data) */}
        <div>
          <h3 className="text-cyan-400 font-bold mb-3 flex items-center text-xs tracking-widest uppercase">
            <Newspaper size={14} className="mr-2" /> TOP STORIES
          </h3>
          <div className="space-y-3">
            {filteredNews.length > 0 ? filteredNews.map((article, i) => (
              <div key={article.id || i} className="group cursor-pointer">
                <div className="flex items-baseline gap-2 mb-0.5">
                  <span className={`text-sm uppercase tracking-widest border border-gray-800 px-1 ${
                    article.risk_score >= 7 ? 'text-red-400' :
                    article.risk_score >= 4 ? 'text-yellow-400' : 'text-green-400'
                  }`}>
                    {article.risk_score >= 7 ? 'HIGH' : article.risk_score >= 4 ? 'MED' : 'LOW'}
                  </span>
                  <span className="text-sm text-gray-600 font-mono uppercase">{article.source}</span>
                  <span className="text-sm text-gray-500 font-mono">{formatTime(article.pub_date)}</span>
                  {article.breaking && (
                    <span className="text-sm text-red-500 font-bold animate-pulse">BREAKING</span>
                  )}
                </div>
                <p className="text-sm text-gray-300 group-hover:text-white transition-colors leading-snug">{article.title}</p>
              </div>
            )) : (
              <p className="text-sm text-gray-600 italic">No stories in wire feed.</p>
            )}
          </div>
        </div>

        {/* Popular Markets (real Polymarket/Kalshi data) */}
        <div>
          <h3 className="text-cyan-400 font-bold mb-3 flex items-center text-xs tracking-widest uppercase">
            <TrendingUp size={14} className="mr-2" /> POPULAR MARKETS
          </h3>
          <div className="space-y-3">
            {topMarkets.length > 0 ? topMarkets.map((market, i) => {
              const outcomes = market.outcomes || [];
              const isMulti = outcomes.length > 2;
              const pct = market.consensus_pct ?? market.polymarket_pct ?? market.kalshi_pct ?? 0;
              return (
                <div key={market.slug || i} className="group flex flex-col sm:flex-row sm:items-center justify-between gap-2 border border-gray-800 bg-gray-900/20 p-2 hover:border-gray-600 transition-colors cursor-pointer" onClick={() => onNavigate('market')}>
                  <span className="text-sm text-gray-300 group-hover:text-white transition-colors truncate pr-2">{market.title}</span>
                  <div className="flex gap-1 shrink-0">
                    {isMulti ? (
                      <>
                        <span className="text-xs px-2 py-1 bg-cyan-900/20 text-cyan-400 border border-cyan-900/50 truncate max-w-[140px]" title={outcomes[0].name}>
                          {outcomes[0].name} {outcomes[0].pct}%
                        </span>
                        {outcomes[1] && (
                          <span className="text-xs px-2 py-1 bg-gray-800/40 text-gray-400 border border-gray-700/50 truncate max-w-[100px]" title={outcomes[1].name}>
                            {outcomes[1].name} {outcomes[1].pct}%
                          </span>
                        )}
                      </>
                    ) : (
                      <>
                        <span className="text-xs px-2 py-1 bg-green-900/20 text-green-400 border border-green-900/50">Y {pct}%</span>
                        <span className="text-xs px-2 py-1 bg-red-900/20 text-red-400 border border-red-900/50">N {100 - pct}%</span>
                      </>
                    )}
                  </div>
                </div>
              );
            }) : (
              <p className="text-sm text-gray-600 italic">No market data available.</p>
            )}
          </div>
          <button
            onClick={() => onNavigate('market')}
            className="mt-3 text-xs text-cyan-400 hover:text-cyan-300 uppercase tracking-widest flex items-center transition-colors"
          >
            View All Markets <ChevronRight size={12} className="ml-1" />
          </button>
        </div>

        {/* Open ballot placeholder */}
        <div>
          <h3 className="text-cyan-400 font-bold mb-3 flex items-center text-xs tracking-widest uppercase">
            <Vote size={14} className="mr-2" /> OPEN BALLOT
          </h3>
          <div
            className="border border-gray-800 bg-gray-900/20 p-5 cursor-pointer hover:border-gray-600 transition-colors"
            onClick={() => onComingSoon?.('BALLOT')}
          >
            <div className="text-center border border-cyan-900/40 bg-cyan-950/10 px-4 py-8">
              <div className="text-2xl md:text-3xl font-bold tracking-[0.32em] text-cyan-300">
                DEMOCRACY FOR ALL SOON
              </div>
              <div className="mt-4 text-xs text-gray-400 uppercase tracking-[0.22em]">
                No live ballot counts or policy promises are being advertised in this shell yet.
              </div>
            </div>
            <div className="mt-3 text-[11px] text-gray-500 leading-relaxed">
              When governance arrives, it should be real, verifiable, and community-shaped instead of placeholder politics.
            </div>
          </div>
          <button
            onClick={() => onComingSoon?.('BALLOT')}
            className="mt-3 text-xs text-cyan-400 hover:text-cyan-300 uppercase tracking-widest flex items-center transition-colors"
          >
            View Governance Note <ChevronRight size={12} className="ml-1" />
          </button>
        </div>

        {/* Network Telemetry (real data) */}
        <div className="flex flex-col">
          <h3 className="text-cyan-400 font-bold mb-3 flex items-center text-xs tracking-widest uppercase">
            <Activity size={14} className="mr-2" /> D.I.N. TELEMETRY
          </h3>
          <div className="flex-1 border border-gray-800 bg-gray-900/20 p-3 flex flex-col justify-between">
            <div className="space-y-2">
              <div className="flex justify-between items-center border-b border-gray-800/50 pb-1">
                <span className="text-sm text-gray-500 uppercase tracking-widest">Tracked Flights</span>
                <span className="text-xs text-green-400 font-mono">{flightCount.toLocaleString()}</span>
              </div>
              <div className="flex justify-between items-center border-b border-gray-800/50 pb-1">
                <span className="text-sm text-gray-500 uppercase tracking-widest">Tracked Vessels</span>
                <span className="text-xs text-cyan-400 font-mono">{shipCount.toLocaleString()}</span>
              </div>
              <div className="flex justify-between items-center border-b border-gray-800/50 pb-1">
                <span className="text-sm text-gray-500 uppercase tracking-widest">Satellites</span>
                <span className="text-xs text-gray-300 font-mono">{satCount.toLocaleString()}</span>
              </div>
              <div className="flex justify-between items-center border-b border-gray-800/50 pb-1">
                <span className="text-sm text-gray-500 uppercase tracking-widest">Active Markets</span>
                <span className="text-xs text-gray-300 font-mono">{markets.length}</span>
              </div>
              <div className="flex justify-between items-center border-b border-gray-800/50 pb-1">
                <span className="text-sm text-gray-500 uppercase tracking-widest">Correlations</span>
                <span className="text-xs text-amber-400 font-mono">{correlationCount}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-500 uppercase tracking-widest">Threat Level</span>
                <span className={`text-sm px-2 py-0.5 ${threatStyle.bg} ${threatStyle.text} ${threatStyle.border} border ${threat?.level === 'SEVERE' || threat?.level === 'HIGH' ? 'animate-pulse' : ''}`}>
                  {threat?.level || 'UNKNOWN'} {threat?.score != null ? `(${threat.score})` : ''}
                </span>
              </div>
            </div>

            {/* Threat drivers */}
            {threat?.drivers && threat.drivers.length > 0 && (
              <div className="mt-3 pt-2 border-t border-gray-800">
                <span className="text-[12px] text-gray-500 uppercase tracking-widest block mb-1">THREAT DRIVERS</span>
                {threat.drivers.slice(0, 3).map((driver, i) => (
                  <p key={i} className="text-[13px] text-gray-400 leading-tight">• {driver}</p>
                ))}
              </div>
            )}

            <div className="mt-3 pt-3 border-t border-gray-800">
              <div className="w-full bg-gray-900 h-1.5 rounded-full overflow-hidden flex">
                <div className="bg-cyan-500" style={{ width: `${Math.min((threat?.score || 50), 100)}%` }}></div>
                <div className="bg-green-500 flex-1"></div>
              </div>
              <div className="flex justify-between mt-1">
                <span className="text-[12px] text-gray-500 uppercase">Threat Score</span>
                <span className="text-[12px] text-gray-500 uppercase">{threat?.score ?? '—'}/100</span>
              </div>
            </div>
          </div>
        </div>

      </div>

      {/* Live Network Telemetry Log */}
      <LiveActivityLog />
    </div>
  );
}
