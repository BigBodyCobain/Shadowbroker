'use client';

import React, { useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown,
  ChevronUp,
  TrendingUp,
  Landmark,
  UserCheck,
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  Settings,
  ExternalLink,
} from 'lucide-react';
import type { DashboardData, StockTicker } from '@/types/dashboard';
import type { CongressTrade, InsiderTransaction } from '@/types/unusualWhales';
import { fetchUWStatus, fetchCongressTrades, fetchInsiderTransactions } from '@/lib/uwClient';

type Tab = 'tickers' | 'congress' | 'insider';

const TAB_CONFIG: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: 'tickers', label: 'TICKERS', icon: <TrendingUp size={10} /> },
  { key: 'congress', label: 'CONGRESS', icon: <Landmark size={10} /> },
  { key: 'insider', label: 'INSIDER', icon: <UserCheck size={10} /> },
];

// ── Helpers ─────────────────────────────────────────────────────────────────

function chamberBadge(chamber: string) {
  const c = chamber?.toLowerCase();
  if (c === 'senator' || c === 'senate') return 'S';
  if (c === 'representative' || c === 'house') return 'H';
  return c?.charAt(0)?.toUpperCase() || '?';
}

function txColor(tx: string) {
  const t = tx?.toLowerCase() || '';
  if (t.includes('purchase') || t.includes('buy')) return 'text-green-400';
  if (t.includes('sale') || t.includes('sell')) return 'text-red-400';
  return 'text-yellow-400';
}

function insiderCodeLabel(code: string) {
  const map: Record<string, string> = {
    P: 'Purchase', S: 'Sale', A: 'Grant', M: 'Exercise',
    F: 'Tax', G: 'Gift', C: 'Conversion', X: 'Expiration',
  };
  return map[code?.toUpperCase()] || code || '—';
}

// ── Tab: Tickers ────────────────────────────────────────────────────────────

const CRYPTO_LABELS = new Set(['BTC', 'ETH']);

function TickerRow({ ticker, info }: { ticker: string; info: StockTicker }) {
  return (
    <div className="flex items-center justify-between border border-cyan-500/10 bg-cyan-950/10 p-1.5 rounded-sm">
      <span className="font-bold text-cyan-300 text-[10px]">[{ticker}]</span>
      <div className="flex items-center gap-3 text-right">
        <span className="text-[var(--text-primary)] font-bold text-xs">
          ${(info.price ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
        <span className={`flex items-center gap-0.5 w-12 justify-end text-[9px] ${info.up ? 'text-cyan-400' : 'text-red-400'}`}>
          {info.up ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
          {Math.abs(info.change_percent ?? 0).toFixed(2)}%
        </span>
      </div>
    </div>
  );
}

function TickersTab({ stocks, oil }: { stocks: Record<string, StockTicker>; oil: Record<string, StockTicker> }) {
  const defenseEntries = Object.entries(stocks).filter(([k]) => !CRYPTO_LABELS.has(k));
  const cryptoEntries = Object.entries(stocks).filter(([k]) => CRYPTO_LABELS.has(k));
  const hasDefense = defenseEntries.length > 0;
  const hasCrypto = cryptoEntries.length > 0;
  const hasOil = Object.keys(oil).length > 0;
  if (!hasDefense && !hasCrypto && !hasOil)
    return <div className="text-[var(--text-muted)] text-[10px] py-4 text-center">Waiting for market data...</div>;
  return (
    <div className="flex flex-col gap-3">
      {hasCrypto && (
        <div>
          <h3 className="text-[9px] font-bold tracking-widest text-orange-400 mb-1.5">CRYPTO</h3>
          <div className="flex flex-col gap-1">
            {cryptoEntries.map(([ticker, info]) => (
              <TickerRow key={ticker} ticker={ticker} info={info} />
            ))}
          </div>
        </div>
      )}
      {hasDefense && (
        <div>
          <h3 className="text-[9px] font-bold tracking-widest text-cyan-400 mb-1.5">DEFENSE SECTOR</h3>
          <div className="flex flex-col gap-1">
            {defenseEntries.map(([ticker, info]) => (
              <TickerRow key={ticker} ticker={ticker} info={info} />
            ))}
          </div>
        </div>
      )}
      {hasOil && (
        <div>
          <h3 className="text-[9px] font-bold tracking-widest text-cyan-400 mb-1.5">COMMODITIES</h3>
          <div className="flex flex-col gap-1">
            {Object.entries(oil).map(([name, info]) => (
              <div key={name} className="flex flex-col border border-cyan-500/10 bg-cyan-950/10 p-1.5 rounded-sm">
                <span className="font-bold text-cyan-500 text-[9px] uppercase mb-0.5">{name}</span>
                <div className="flex items-center justify-between">
                  <span className="text-[var(--text-primary)] font-bold text-[11px]">${(info.price ?? 0).toFixed(2)}</span>
                  <span className={`flex items-center gap-0.5 text-[9px] ${info.up ? 'text-cyan-400' : 'text-red-400'}`}>
                    {info.up ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                    {Math.abs(info.change_percent ?? 0).toFixed(2)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tab: Congress ───────────────────────────────────────────────────────────

function CongressTab({ trades }: { trades: CongressTrade[] }) {
  if (!trades.length)
    return <div className="text-[var(--text-muted)] text-[10px] py-4 text-center">No recent congress trades</div>;
  return (
    <div className="flex flex-col gap-1.5">
      {trades.slice(0, 20).map((t, i) => (
        <div key={i} className="border border-cyan-500/10 bg-cyan-950/10 p-1.5 rounded-sm">
          <div className="flex items-center justify-between gap-1">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="text-[9px] font-bold text-cyan-300 bg-cyan-900/40 px-1 rounded flex-shrink-0">
                {chamberBadge(t.chamber)}
              </span>
              <span className="text-[10px] text-[var(--text-primary)] truncate font-medium">
                {t.politician_name}
              </span>
            </div>
            {t.ticker && (
              <span className="text-[10px] font-bold text-cyan-400 flex-shrink-0">{t.ticker}</span>
            )}
          </div>
          <div className="flex items-center justify-between mt-0.5">
            <span className={`text-[9px] ${txColor(t.transaction_type || '')}`}>
              {t.transaction_type || '—'}
            </span>
            <div className="flex items-center gap-2">
              {t.amount_range && (
                <span className="text-[9px] text-[var(--text-muted)]">{t.amount_range}</span>
              )}
              {t.filing_date && (
                <span className="text-[9px] text-[var(--text-muted)]">{t.filing_date}</span>
              )}
            </div>
          </div>
          {t.asset_name && t.asset_name !== t.ticker && (
            <div className="text-[11px] text-[var(--text-muted)]/70 truncate mt-0.5">{t.asset_name}</div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Tab: Insider ────────────────────────────────────────────────────────────

function InsiderTab({ transactions }: { transactions: InsiderTransaction[] }) {
  if (!transactions.length)
    return <div className="text-[var(--text-muted)] text-[10px] py-4 text-center">No recent insider transactions</div>;
  return (
    <div className="flex flex-col gap-1.5">
      {transactions.slice(0, 20).map((t, i) => {
        const isBuy = t.transaction_code === 'P';
        const isSell = t.transaction_code === 'S';
        return (
          <div key={i} className="border border-cyan-500/10 bg-cyan-950/10 p-1.5 rounded-sm">
            <div className="flex items-center justify-between gap-1">
              <span className="text-[10px] text-[var(--text-primary)] truncate font-medium">{t.name}</span>
              <span className="text-[10px] font-bold text-cyan-400 flex-shrink-0">{t.ticker}</span>
            </div>
            <div className="flex items-center justify-between mt-0.5">
              <span className={`text-[9px] font-bold ${isBuy ? 'text-green-400' : isSell ? 'text-red-400' : 'text-yellow-400'}`}>
                {insiderCodeLabel(t.transaction_code || '')}
              </span>
              <div className="flex items-center gap-2">
                {t.change !== 0 && (
                  <span className={`text-[9px] ${t.change > 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {t.change > 0 ? '+' : ''}{t.change.toLocaleString()} shares
                  </span>
                )}
                {t.transaction_price > 0 && (
                  <span className="text-[9px] text-[var(--text-muted)]">${t.transaction_price.toFixed(2)}</span>
                )}
              </div>
            </div>
            {t.filing_date && (
              <div className="text-[11px] text-[var(--text-muted)]/70 mt-0.5">{t.filing_date}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main Panel ──────────────────────────────────────────────────────────────

interface MarketsPanelProps {
  data: DashboardData;
  focused?: boolean;
  onFocusChange?: (focused: boolean) => void;
}

const MarketsPanel = React.memo(function MarketsPanel({ data, focused, onFocusChange }: MarketsPanelProps) {
  const [isMinimized, setIsMinimized] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>('tickers');
  const [finnhubConfigured, setFinnhubConfigured] = useState<boolean | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Local overlay for on-demand fetches
  const [localCongress, setLocalCongress] = useState<CongressTrade[] | null>(null);
  const [localInsider, setLocalInsider] = useState<InsiderTransaction[] | null>(null);

  // Check Finnhub status
  useEffect(() => {
    fetchUWStatus()
      .then((s) => setFinnhubConfigured(s.configured))
      .catch(() => setFinnhubConfigured(false));
  }, []);

  // Data sources: background-polled + local overlay
  const stocks = data?.stocks || {};
  const oil = data?.oil || {};
  const uw = data?.unusual_whales;
  const congressTrades = localCongress ?? uw?.congress_trades ?? [];
  const insiderTxns = localInsider ?? uw?.insider_transactions ?? [];

  const handleRefresh = useCallback(async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const [c, ins] = await Promise.all([
        fetchCongressTrades().catch(() => null),
        fetchInsiderTransactions().catch(() => null),
      ]);
      if (c?.trades) setLocalCongress(c.trades);
      if (ins?.transactions) setLocalInsider(ins.transactions);
    } finally {
      setRefreshing(false);
    }
  }, [refreshing]);

  // Determine if Finnhub tabs should show
  const hasFinnhub = finnhubConfigured === true;

  return (
    <motion.div
      initial={{ y: -50, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.8, delay: 0.2 }}
      className="w-full bg-[#0a0a0a]/90 backdrop-blur-sm border border-cyan-900/40 z-10 flex flex-col font-mono text-sm pointer-events-auto flex-shrink-0"
    >
      {/* Header */}
      <div
        className="flex justify-between items-center p-4 cursor-pointer hover:bg-[var(--bg-secondary)]/50 transition-colors border-b border-[var(--border-primary)]/50"
        onClick={() => {
          const next = !isMinimized;
          setIsMinimized(next);
          onFocusChange?.(!next);
        }}
      >
        <div className="flex items-center gap-2">
          <TrendingUp size={12} className="text-cyan-500" />
          <span className="text-[12px] text-[var(--text-muted)] font-mono tracking-widest">
            GLOBAL MARKETS
          </span>
          {hasFinnhub && (
            <span className="text-[11px] text-green-500 bg-green-900/30 px-1 rounded">FINNHUB</span>
          )}
        </div>
        <button className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
          {isMinimized ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
      </div>

      <AnimatePresence>
        {!isMinimized && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className={`overflow-y-auto styled-scrollbar flex flex-col ${focused ? 'max-h-[calc(100vh-180px)]' : 'max-h-[450px]'}`}
          >
            {hasFinnhub ? (
              <>
                {/* Tab bar */}
                <div className="flex border-b border-[var(--border-primary)]/50">
                  {TAB_CONFIG.map((tab) => (
                    <button
                      key={tab.key}
                      onClick={() => setActiveTab(tab.key)}
                      className={`flex-1 flex items-center justify-center gap-1 py-2 text-[9px] tracking-wider transition-colors ${
                        activeTab === tab.key
                          ? 'text-cyan-400 border-b border-cyan-400 bg-cyan-950/20'
                          : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                      }`}
                    >
                      {tab.icon}
                      {tab.label}
                    </button>
                  ))}
                </div>

                {/* Refresh bar (congress/insider tabs only) */}
                {activeTab !== 'tickers' && (
                  <div className="flex justify-end px-3 pt-2 pb-1">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleRefresh(); }}
                      disabled={refreshing}
                      className="flex items-center gap-1 text-[9px] text-[var(--text-muted)] hover:text-cyan-400 transition-colors disabled:opacity-40"
                    >
                      <RefreshCw size={10} className={refreshing ? 'animate-spin' : ''} />
                      {refreshing ? 'FETCHING...' : 'REFRESH'}
                    </button>
                  </div>
                )}

                {/* Tab content */}
                <div className="p-3 pt-1">
                  {activeTab === 'tickers' && <TickersTab stocks={stocks} oil={oil} />}
                  {activeTab === 'congress' && <CongressTab trades={congressTrades} />}
                  {activeTab === 'insider' && <InsiderTab transactions={insiderTxns} />}
                </div>

                {/* Attribution */}
                <div className="px-3 pb-2">
                  <p className="text-[11px] text-[var(--text-muted)]/60 text-center">
                    Data from Finnhub
                  </p>
                </div>
              </>
            ) : (
              /* No Finnhub key — show stocks/oil only (yfinance fallback) + setup hint */
              <div className="flex flex-col">
                <div className="p-3">
                  <TickersTab stocks={stocks} oil={oil} />
                </div>
                {finnhubConfigured === false && (
                  <div className="flex flex-col items-center gap-2 px-3 pb-3 border-t border-[var(--border-primary)]/30 pt-2">
                    <div className="flex items-center gap-1.5">
                      <Settings size={10} className="text-[var(--text-muted)]" />
                      <p className="text-[9px] text-[var(--text-muted)]">
                        Add <span className="text-cyan-400">FINNHUB_API_KEY</span> for congress trades &amp; insider data
                      </p>
                    </div>
                    <a
                      href="https://finnhub.io/register"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-[11px] text-cyan-400 hover:text-cyan-300 transition-colors"
                    >
                      Free API Key <ExternalLink size={8} />
                    </a>
                  </div>
                )}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
});

export default MarketsPanel;
