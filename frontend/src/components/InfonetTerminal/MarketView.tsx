'use client';

import React, { useState } from 'react';
import { ChevronLeft, Search, Activity, Shield, Crosshair, DollarSign, Newspaper } from 'lucide-react';
import { useDataKeys } from '@/hooks/useDataStore';
import type { DashboardData, StockTicker } from '@/types/dashboard';

function formatVolume(vol: number): string {
  if (!vol || vol <= 0) return '';
  if (vol >= 1_000_000) return `$${(vol / 1_000_000).toFixed(1)}M`;
  if (vol >= 1_000) return `$${(vol / 1_000).toFixed(0)}K`;
  return `$${vol.toFixed(0)}`;
}

function formatEndDate(iso: string | null | undefined): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const now = new Date();
    const days = Math.floor((d.getTime() - now.getTime()) / 86400000);
    if (days < 0) return 'EXPIRED';
    if (days === 0) return 'TODAY';
    if (days === 1) return '1d';
    if (days < 30) return `${days}d`;
    if (days < 365) return `${Math.floor(days / 30)}mo`;
    return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
  } catch { return ''; }
}

const CATEGORY_CONFIG: Record<string, { color: string; icon: typeof Shield }> = {
  POLITICS: { color: 'text-blue-400', icon: Shield },
  CONFLICT: { color: 'text-red-400', icon: Crosshair },
  FINANCE: { color: 'text-emerald-400', icon: DollarSign },
  CRYPTO: { color: 'text-amber-400', icon: DollarSign },
  NEWS: { color: 'text-cyan-400', icon: Newspaper },
};

type Category = 'ALL' | 'POLITICS' | 'CONFLICT' | 'FINANCE' | 'CRYPTO' | 'NEWS';

interface MarketViewProps {
  onBack: () => void;
}

type DataSlice = Pick<DashboardData, 'trending_markets' | 'stocks'>;
const DATA_KEYS = ['trending_markets', 'stocks'] as const;

export default function MarketView({ onBack }: MarketViewProps) {
  const [category, setCategory] = useState<Category>('ALL');
  const [searchInput, setSearchInput] = useState('');

  const data = useDataKeys(DATA_KEYS) as DataSlice;
  const markets = data?.trending_markets || [];
  const stocks = data?.stocks;

  const filteredMarkets = markets.filter(m => {
    const matchesCat = category === 'ALL' || m.category === category;
    const matchesSearch = !searchInput || m.title.toLowerCase().includes(searchInput.toLowerCase());
    return matchesCat && matchesSearch;
  });

  const CATEGORIES: Category[] = ['ALL', 'POLITICS', 'CONFLICT', 'FINANCE', 'CRYPTO', 'NEWS'];

  // Build ticker from real stocks data
  const tickerItems: string[] = [];
  if (stocks) {
    const entries = Object.entries(stocks as Record<string, StockTicker>).filter(([k]) => !['last_updated', 'source'].includes(k));
    for (const [symbol, val] of entries) {
      if (val && val.change_percent != null) {
        const up = val.change_percent >= 0;
        tickerItems.push(`${symbol.toUpperCase()} ${up ? '▲' : '▼'} ${Math.abs(val.change_percent).toFixed(1)}%`);
      }
    }
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden relative">
      {/* Header */}
      <div className="border-b border-gray-800 pb-4 mb-4 shrink-0">
        <button
          onClick={onBack}
          className="flex items-center text-cyan-500 hover:text-cyan-400 transition-all uppercase text-xs tracking-widest border border-cyan-900/50 px-3 py-1 bg-cyan-900/10 hover:bg-cyan-900/30 hover:border-cyan-500/50 mb-4"
        >
          <ChevronLeft size={14} className="mr-1" />
          RETURN TO MAIN
        </button>
        <h1 className="text-2xl font-bold text-cyan-400 uppercase tracking-widest flex items-center">
          <Activity className="mr-2 text-cyan-400 animate-pulse" />
          PREDICTION MARKETS
        </h1>
        <p className="text-gray-500 text-sm mt-1">Live Polymarket + Kalshi feeds. {markets.length} active markets tracked.</p>
      </div>

      {/* Categories */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-4 gap-4 shrink-0">
        <div className="flex gap-2 overflow-x-auto w-full md:w-auto pb-2 md:pb-0">
          {CATEGORIES.map(cat => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={`px-3 py-1 text-xs uppercase tracking-widest border whitespace-nowrap ${
                category === cat
                  ? 'bg-gray-800 text-white border-white'
                  : 'bg-gray-900/30 text-gray-500 border-gray-800 hover:border-gray-600'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
        <span className="text-sm text-gray-500 font-mono">{filteredMarkets.length} RESULTS</span>
      </div>

      {/* Search Bar */}
      <div className="mb-4 shrink-0">
        <div className="flex items-center border border-gray-800 bg-[#0a0a0a] p-2">
          <Search size={14} className="text-gray-600 mr-2" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search prediction markets..."
            className="bg-transparent border-none outline-none text-white w-full text-sm placeholder-gray-700"
            spellCheck={false}
          />
        </div>
      </div>

      {/* Markets List */}
      <div className="flex-1 overflow-y-auto pr-2 space-y-3 pb-4">
        {filteredMarkets.length > 0 ? filteredMarkets.map((market, i) => {
          const pct = market.consensus_pct ?? market.polymarket_pct ?? market.kalshi_pct ?? 0;
          const catConfig = CATEGORY_CONFIG[market.category] || { color: 'text-gray-400' };
          const vol = formatVolume(market.volume);
          const vol24 = formatVolume(market.volume_24h);
          // Runtime-optional fields the backend may send but aren't in the strict TS type
          const raw = market as Record<string, unknown>;
          const endDate = formatEndDate(typeof raw.end_date === 'string' ? raw.end_date : null);
          const outcomes = market.outcomes && market.outcomes.length > 0 ? market.outcomes : null;
          const consensus = raw.consensus as { total_picks: number; total_staked: number } | undefined;

          return (
            <div key={market.slug || i} className="border border-gray-800 bg-gray-900/10 p-4 hover:border-gray-600 transition-colors">
              {/* Title + Category */}
              <div className="flex items-start justify-between gap-4 mb-3">
                <div className="flex-1">
                  <div className="text-gray-300 font-bold text-sm md:text-base leading-snug">{market.title}</div>
                  <div className="flex items-center gap-2 mt-1.5 text-sm font-mono">
                    <span className={`${catConfig.color} uppercase tracking-widest`}>{market.category}</span>
                    {vol && <span className="text-gray-500">VOL: {vol}</span>}
                    {vol24 && <span className="text-gray-500">24H: {vol24}</span>}
                    {endDate && <span className="text-gray-500">CLOSES: {endDate}</span>}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  {outcomes && outcomes.length > 0 ? (
                    <>
                      <div className="text-2xl font-bold text-cyan-400 font-mono">{outcomes[0].pct}%</div>
                      <div className="text-[13px] text-gray-400 uppercase truncate max-w-[100px]" title={outcomes[0].name}>{outcomes[0].name}</div>
                    </>
                  ) : (
                    <>
                      <div className="text-2xl font-bold text-emerald-400 font-mono">{pct}%</div>
                      <div className="text-[13px] text-gray-500 uppercase">CONSENSUS</div>
                    </>
                  )}
                </div>
              </div>

              {/* Probability bar */}
              {outcomes && outcomes.length > 0 ? (
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-[13px] text-cyan-400 font-mono truncate max-w-[80px]" title={outcomes[0].name}>{outcomes[0].name}</span>
                  <div className="flex-1 h-2 bg-gray-900 overflow-hidden flex">
                    <div className="bg-cyan-500/60" style={{ width: `${outcomes[0].pct}%` }} />
                    <div className="bg-gray-700/30 flex-1" />
                  </div>
                  <span className="text-[13px] text-cyan-400 font-mono w-8 text-right">{outcomes[0].pct}%</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-[13px] text-green-400 font-mono w-8">YES</span>
                  <div className="flex-1 h-2 bg-gray-900 overflow-hidden flex">
                    <div className="bg-emerald-500/60" style={{ width: `${pct}%` }} />
                    <div className="bg-red-500/30 flex-1" />
                  </div>
                  <span className="text-[13px] text-red-400 font-mono w-8 text-right">NO</span>
                </div>
              )}

              {/* Source badges */}
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-1.5 flex-wrap">
                  {market.sources?.map((s, si) => (
                    <span key={si} className={`text-[13px] font-mono px-1.5 py-0.5 border ${
                      s.name === 'POLY'
                        ? 'bg-purple-500/15 text-purple-400 border-purple-500/20'
                        : 'bg-blue-500/15 text-blue-400 border-blue-500/20'
                    }`}>
                      {s.name} {s.pct}%
                    </span>
                  ))}
                  {consensus && consensus.total_picks > 0 && (
                    <span className="text-[13px] font-mono px-1.5 py-0.5 border bg-amber-500/10 text-amber-400 border-amber-500/20">
                      {consensus.total_picks} pick{consensus.total_picks !== 1 ? 's' : ''}
                      {consensus.total_staked > 0 ? ` · ${consensus.total_staked.toFixed(1)} REP` : ''}
                    </span>
                  )}
                </div>

                {/* Delta indicator */}
                {market.delta_pct != null && market.delta_pct !== 0 && (
                  <span className={`text-sm font-mono font-bold ${market.delta_pct > 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {market.delta_pct > 0 ? '▲' : '▼'} {Math.abs(market.delta_pct).toFixed(1)}%
                  </span>
                )}
              </div>

              {/* Multi-choice outcomes */}
              {outcomes && outcomes.length > 0 && (
                <div className="mt-3 pt-2 border-t border-gray-800 space-y-1">
                  {outcomes.slice(0, 5).map((outcome, oi) => (
                    <div key={oi} className="flex items-center gap-2 text-sm">
                      <span className="text-gray-400 w-24 truncate">{outcome.name}</span>
                      <div className="flex-1 h-1 bg-gray-900 overflow-hidden">
                        <div className="bg-cyan-500/50 h-full" style={{ width: `${outcome.pct}%` }} />
                      </div>
                      <span className="text-cyan-400 font-mono w-8 text-right">{outcome.pct}%</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        }) : (
          <div className="text-center text-gray-600 py-8">
            <p className="text-sm italic">No markets found{searchInput ? ` for "${searchInput}"` : ''}.</p>
          </div>
        )}
      </div>

      {/* Ticker */}
      {tickerItems.length > 0 && (
        <div className="shrink-0 border-t border-gray-800 bg-gray-900/30 overflow-hidden py-2 mt-2">
          <div className="animate-ticker text-gray-400 font-bold text-sm tracking-widest whitespace-nowrap">
            {Array(10).fill(tickerItems.join('  |  ')).join('  |  ').split('  |  ').map((item, i) => {
              const isUp = item.includes('▲');
              return (
                <span key={i} className="mx-4">
                  {item.replace(/[▲▼]/, '')}
                  <span className={isUp ? 'text-green-400 ml-1' : 'text-red-400 ml-1'}>
                    {isUp ? '▲' : '▼'}
                  </span>
                </span>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
