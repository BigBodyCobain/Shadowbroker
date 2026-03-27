'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronUp,
  ChevronDown,
  TrendingUp,
  Trophy,
  User,
  AlertTriangle,
  Search,
  X,
  Shield,
  Crosshair,
  DollarSign,
  Bitcoin,
  Newspaper,
  ExternalLink,
  Lock,
  Zap,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { getNodeIdentity, nextSequence } from '@/mesh/meshIdentity';
import { validateEventPayload } from '@/mesh/meshSchema';
import { getActiveSigningContext, signMeshEvent } from '@/mesh/wormholeIdentityClient';
import { useDataKeys } from '@/hooks/useDataStore';

// ─── Types ───────────────────────────────────────────────────────────────────

type MarketCategory = 'POLITICS' | 'CONFLICT' | 'NEWS' | 'FINANCE' | 'CRYPTO';

interface SourceBadge {
  name: string;
  pct: number;
}

interface Outcome {
  name: string;
  pct: number;
}

interface ConsensusSide {
  picks: number;
  staked: number;
}

interface MarketConsensus {
  total_picks: number;
  total_staked: number;
  sides: Record<string, ConsensusSide>;
}

interface Market {
  title: string;
  consensus_pct: number | null;
  polymarket_pct: number | null;
  kalshi_pct: number | null;
  volume: number;
  volume_24h: number;
  end_date: string | null;
  description: string;
  category: MarketCategory;
  sources: SourceBadge[];
  slug: string;
  kalshi_ticker?: string;
  outcomes?: Outcome[];
  consensus?: MarketConsensus;
}

interface CategorizedMarkets {
  POLITICS: Market[];
  CONFLICT: Market[];
  NEWS: Market[];
  FINANCE: Market[];
  CRYPTO: Market[];
}

interface Prediction {
  prediction_id: string;
  market_title: string;
  side: string;
  probability_at_bet: number;
  potential_rep: number;
  staked: number;
  mode: 'free' | 'staked';
  placed: string;
}

interface OracleProfile {
  node_id: string;
  oracle_rep: number;
  oracle_rep_total: number;
  oracle_rep_locked: number;
  predictions_won: number;
  predictions_lost: number;
  win_rate: number;
  farming_pct: number;
}

type Tab = 'markets' | 'trending' | 'active' | 'profile';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatVolume(vol: number): string {
  if (!vol || vol <= 0) return '';
  if (vol >= 1_000_000) return `$${(vol / 1_000_000).toFixed(1)}M`;
  if (vol >= 1_000) return `$${(vol / 1_000).toFixed(0)}K`;
  return `$${vol.toFixed(0)}`;
}

function formatEndDate(iso: string | null): string {
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
  } catch {
    return '';
  }
}

const CATEGORY_CONFIG: {
  id: MarketCategory;
  label: string;
  color: string;
  icon: typeof TrendingUp;
}[] = [
  { id: 'POLITICS', label: 'POLITICS', color: 'text-blue-400', icon: Shield },
  { id: 'CONFLICT', label: 'CONFLICT', color: 'text-red-400', icon: Crosshair },
  { id: 'FINANCE', label: 'FINANCE', color: 'text-emerald-400', icon: DollarSign },
  { id: 'CRYPTO', label: 'CRYPTO', color: 'text-amber-400', icon: Bitcoin },
  { id: 'NEWS', label: 'NEWS', color: 'text-cyan-400', icon: Newspaper },
];

// ─── MarketCard (compact — click opens modal) ────────────────────────────────

function MarketCard({ market, onOpenModal }: { market: Market; onOpenModal: (m: Market) => void }) {
  const pct = market.consensus_pct ?? 50;
  const vol = formatVolume(market.volume);
  const endDate = formatEndDate(market.end_date);
  const c = market.consensus;
  const hasPicks = c && c.total_picks > 0;

  return (
    <div
      className="border border-[var(--border-primary)]/40 bg-[var(--bg-secondary)]/20 hover:bg-[var(--bg-secondary)]/40 transition-colors cursor-pointer"
      onClick={() => onOpenModal(market)}
    >
      <div className="p-2.5">
        <div className="text-[10px] text-[var(--text-secondary)] font-mono leading-snug mb-1.5">
          {market.title}
        </div>
        {/* Probability — leader name for multi-choice, bar for binary */}
        {market.outcomes && market.outcomes.length > 0 ? (() => {
          const leader = [...market.outcomes].filter(o => o.pct > 0).sort((a, b) => b.pct - a.pct)[0];
          return leader ? (
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[9px] font-mono text-emerald-400 truncate mr-2">{leader.name}</span>
              <span className="text-[10px] font-mono text-emerald-400 font-bold flex-shrink-0">{leader.pct}%</span>
            </div>
          ) : null;
        })() : (
          <div className="flex items-center gap-2 mb-1.5">
            <div className="flex-1 h-1.5 rounded-full bg-[var(--bg-primary)]/60 overflow-hidden flex">
              <div className="bg-emerald-500/50 transition-all" style={{ width: `${pct}%` }} />
              <div className="bg-red-500/30 flex-1" />
            </div>
            <span className="text-[9px] font-mono text-emerald-400 w-10 text-right">{pct}%</span>
          </div>
        )}
        {/* Bottom row: source badges + network activity + volume + end date */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            {market.sources?.map((s, i) => (
              <span
                key={i}
                className={`text-[7px] font-mono px-1 py-0.5 border ${
                  s.name === 'POLY'
                    ? 'bg-purple-500/15 text-purple-400 border-purple-500/20'
                    : 'bg-blue-500/15 text-blue-400 border-blue-500/20'
                }`}
              >
                {s.name} {s.pct}%
              </span>
            ))}
            {hasPicks && (
              <span className="text-[7px] font-mono px-1 py-0.5 border bg-amber-500/10 text-amber-400 border-amber-500/20">
                {c.total_picks} picks
                {c.total_staked > 0 ? ` · ${c.total_staked.toFixed(1)} REP` : ''}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-[7px] font-mono text-[var(--text-muted)]">
            {vol && <span>{vol}</span>}
            {endDate && <span>{endDate}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── MarketModal (full dossier + staking UI) ─────────────────────────────────

function MarketModal({
  market,
  onClose,
  onPredict,
  loading,
  availableRep,
}: {
  market: Market;
  onClose: () => void;
  onPredict: (title: string, side: string, stakeAmount: number) => void;
  loading: boolean;
  availableRep: number;
}) {
  const [mode, setMode] = useState<'free' | 'stake'>('free');
  const [stakeInput, setStakeInput] = useState('');
  const [confirmSide, setConfirmSide] = useState<string | null>(null);
  const pct = market.consensus_pct ?? 50;
  const c = market.consensus;

  const handlePick = (side: string) => {
    setConfirmSide(side);
  };

  const handleConfirm = () => {
    if (!confirmSide) return;
    const amount = mode === 'stake' ? parseFloat(stakeInput) || 0 : 0;
    onPredict(market.title, confirmSide, amount);
    setConfirmSide(null);
  };

  // Build consensus bars for display
  const sides = c?.sides || {};
  const sideEntries = Object.entries(sides).sort(
    (a, b) => b[1].picks + b[1].staked - (a[1].picks + a[1].staked),
  );
  const maxPicks = Math.max(1, ...Object.values(sides).map((s) => s.picks));

  const isMulti = market.outcomes && market.outcomes.length > 0;
  const sortedOutcomes = isMulti
    ? [...market.outcomes!].filter(o => o.pct > 0).sort((a, b) => b.pct - a.pct)
    : [];
  const leader = sortedOutcomes[0];

  return (
    <div
      style={{
        position: 'fixed',
        top: 0, left: 0, right: 0, bottom: 0,
        zIndex: 9999,
        background: 'rgba(0,0,0,0.88)',
        backdropFilter: 'blur(12px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '40px 20px',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => { if (e.key === 'Escape') onClose(); }}
      tabIndex={-1}
      ref={(el) => el?.focus()}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        className="relative w-full max-w-[600px] max-h-[calc(100vh-80px)] overflow-y-auto styled-scrollbar bg-[#080c12] border border-cyan-800/50 rounded-lg shadow-2xl font-mono"
        style={{ boxShadow: '0 0 80px rgba(0,255,255,0.08), inset 0 1px 0 rgba(255,255,255,0.05)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-[#080c12] border-b border-cyan-800/40 px-5 py-3 flex justify-between items-start z-10">
          <div className="flex-1 pr-4">
            <div className="text-[14px] text-[var(--text-primary)] font-mono leading-snug font-bold">
              {market.title}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-white transition-colors flex-shrink-0 mt-0.5 px-1 hover:bg-white/10 rounded"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 flex flex-col gap-4">
          {/* ── LEADER / CONSENSUS ── */}
          {isMulti && leader ? (
            <div className="bg-emerald-950/20 border border-emerald-500/30 rounded p-4 text-center">
              <div className="text-[9px] text-[var(--text-muted)] tracking-[0.2em] mb-1.5">CURRENT LEADER</div>
              <div className="text-[22px] font-bold text-emerald-400">{leader.name}</div>
              <div className="text-[28px] font-bold text-white mt-1">{leader.pct}%</div>
            </div>
          ) : (
            <div>
              <div className="flex items-center gap-3 mb-2">
                <div className="flex-1 h-3 rounded-full bg-[var(--bg-secondary)] overflow-hidden flex">
                  <div className="bg-emerald-500/60 transition-all" style={{ width: `${pct}%` }} />
                  <div className="bg-red-500/30 flex-1" />
                </div>
                <span className="text-[14px] font-mono text-emerald-400 font-bold">{pct}%</span>
              </div>
            </div>
          )}

          {/* Source badges row */}
          <div className="flex items-center gap-2 flex-wrap">
            {market.sources?.map((s, i) => (
              <span
                key={i}
                className={`text-[9px] font-mono px-2 py-0.5 border ${
                  s.name === 'POLY'
                    ? 'bg-purple-500/15 text-purple-400 border-purple-500/20'
                    : 'bg-blue-500/15 text-blue-400 border-blue-500/20'
                }`}
              >
                {s.name} {s.pct}%
              </span>
            ))}
            {market.volume > 0 && (
              <span className="text-[9px] font-mono text-[var(--text-muted)]">
                {formatVolume(market.volume)} vol
              </span>
            )}
            {market.volume_24h > 0 && (
              <span className="text-[9px] font-mono text-cyan-400">
                {formatVolume(market.volume_24h)} 24h
              </span>
            )}
            {market.end_date && (
              <span className="text-[9px] font-mono text-[var(--text-muted)]">
                ends{' '}
                {new Date(market.end_date).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                })}
              </span>
            )}
          </div>

          {/* Resolution stipulation / Description */}
          {market.description && (
            <div className="border border-[var(--border-primary)]/40 bg-[var(--bg-secondary)]/20 p-3 rounded">
              <div className="text-[9px] font-mono tracking-widest text-[var(--text-muted)] mb-1.5">
                RESOLUTION STIPULATION
              </div>
              <div className="text-[10px] text-[var(--text-secondary)] font-mono leading-relaxed max-h-[150px] overflow-y-auto styled-scrollbar whitespace-pre-wrap">
                {market.description}
              </div>
            </div>
          )}

          {/* ── OUTCOMES LIST ── */}
          {isMulti && sortedOutcomes.length > 0 && (
            <div>
              <div className="text-[9px] font-mono tracking-widest text-[var(--text-muted)] mb-2">
                ALL OUTCOMES ({sortedOutcomes.length})
              </div>
              <div className="flex flex-col gap-1 max-h-[300px] overflow-y-auto styled-scrollbar">
                {sortedOutcomes.map((o, i) => (
                  <div
                    key={i}
                    className={`flex items-center justify-between py-2 px-3 text-[10px] font-mono border rounded-sm flex-shrink-0 ${
                      i === 0
                        ? 'border-emerald-500/40 bg-emerald-950/20'
                        : 'border-[var(--border-primary)]/30 bg-black/20'
                    }`}
                  >
                    <span className={`truncate mr-3 ${i === 0 ? 'text-emerald-400 font-bold' : 'text-[var(--text-secondary)]'}`}>
                      {o.name}
                    </span>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <div className="w-20 h-2 rounded-full bg-[var(--bg-primary)]/60 overflow-hidden">
                        <div
                          className={`h-full ${i === 0 ? 'bg-emerald-500/60' : 'bg-emerald-500/30'}`}
                          style={{ width: `${o.pct}%` }}
                        />
                      </div>
                      <span className={`w-14 text-right font-bold ${i === 0 ? 'text-emerald-400' : 'text-[var(--text-secondary)]'}`}>
                        {o.pct}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Binary consensus display */}
          {!isMulti && (
            <div className="flex gap-3">
              <div className="flex-1 py-3 text-center text-[13px] font-mono font-bold border border-emerald-500/40 bg-emerald-950/20 text-emerald-400 rounded-sm">
                YES {pct}%
              </div>
              <div className="flex-1 py-3 text-center text-[13px] font-mono font-bold border border-red-500/40 bg-red-950/20 text-red-400 rounded-sm">
                NO {(100 - pct).toFixed(0)}%
              </div>
            </div>
          )}

          {/* Network Activity */}
          {sideEntries.length > 0 && (
            <div className="border border-[var(--border-primary)]/40 bg-[var(--bg-secondary)]/20 p-3 rounded">
              <div className="text-[9px] font-mono tracking-widest text-[var(--text-muted)] mb-2">
                NETWORK ACTIVITY
              </div>
              <div className="flex flex-col gap-1.5">
                {sideEntries.map(([side, data]) => (
                  <div key={side} className="flex items-center gap-2">
                    <span className="text-[9px] font-mono text-[var(--text-secondary)] w-20 truncate uppercase">
                      {side}
                    </span>
                    <div className="flex-1 h-1.5 rounded-full bg-[var(--bg-primary)]/60 overflow-hidden">
                      <div
                        className="h-full bg-amber-500/50 transition-all"
                        style={{ width: `${(data.picks / maxPicks) * 100}%` }}
                      />
                    </div>
                    <span className="text-[8px] font-mono text-[var(--text-muted)] w-24 text-right">
                      {data.picks} pick{data.picks !== 1 ? 's' : ''}
                      {data.staked > 0 ? ` · ${data.staked.toFixed(1)} REP` : ''}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* External links */}
          <div className="flex flex-wrap gap-2 pt-1 border-t border-[var(--border-primary)]/30">
            {market.slug && (
              <button
                onClick={() => window.open(`https://polymarket.com/event/${market.slug}`, '_blank', 'noopener,noreferrer')}
                className="flex items-center gap-1 px-3 py-1.5 text-[9px] font-mono border border-purple-500/30 bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 hover:border-purple-400 transition-colors cursor-pointer rounded-sm"
              >
                <ExternalLink size={10} /> POLYMARKET
              </button>
            )}
            {market.kalshi_ticker && (
              <button
                onClick={() => window.open(`https://kalshi.com/markets/${market.kalshi_ticker}`, '_blank', 'noopener,noreferrer')}
                className="flex items-center gap-1 px-3 py-1.5 text-[9px] font-mono border border-blue-500/30 bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 hover:border-blue-400 transition-colors cursor-pointer rounded-sm"
              >
                <ExternalLink size={10} /> KALSHI
              </button>
            )}
            <button
              onClick={onClose}
              className="ml-auto text-[10px] text-[var(--text-muted)] hover:text-white border border-[var(--border-primary)] hover:border-white/30 px-3 py-1.5 rounded-sm transition-colors"
            >
              CLOSE
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

const PredictionsPanel = React.memo(function PredictionsPanel() {
  const { trending_markets, news: _newsData } = useDataKeys(['trending_markets', 'news'] as const);
  const [isMinimized, setIsMinimized] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>('markets');

  // Markets state
  const [categories, setCategories] = useState<CategorizedMarkets>({
    POLITICS: [],
    CONFLICT: [],
    NEWS: [],
    FINANCE: [],
    CRYPTO: [],
  });
  const [totalCount, setTotalCount] = useState(0);
  const [catTotals, setCatTotals] = useState<Record<MarketCategory, number>>({
    POLITICS: 0,
    CONFLICT: 0,
    NEWS: 0,
    FINANCE: 0,
    CRYPTO: 0,
  });
  const [expandedCategories, setExpandedCategories] = useState<Set<MarketCategory>>(
    new Set(['POLITICS']),
  );
  const [loadingMore, setLoadingMore] = useState<Set<MarketCategory>>(new Set());

  // Modal state
  const [modalMarket, setModalMarket] = useState<Market | null>(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Market[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Existing state
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [profile, setProfile] = useState<OracleProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [betStatus, setBetStatus] = useState('');
  const [activeNodeId, setActiveNodeId] = useState('');

  const identity = typeof window !== 'undefined' ? getNodeIdentity() : null;
  const nodeId = activeNodeId || identity?.nodeId || '';

  // ── Fetchers ──

  const fetchMarkets = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/mesh/oracle/markets`);
      if (res.ok) {
        const d = await res.json();
        setCategories(
          d.categories || { POLITICS: [], CONFLICT: [], NEWS: [], FINANCE: [], CRYPTO: [] },
        );
        setTotalCount(d.total_count || 0);
        if (d.cat_totals) setCatTotals(d.cat_totals);
      }
    } catch {
      /* silent */
    }
  }, []);

  const loadMoreMarkets = useCallback(
    async (cat: MarketCategory) => {
      const current = categories[cat]?.length || 0;
      setLoadingMore((prev) => new Set(prev).add(cat));
      try {
        const res = await fetch(
          `${API_BASE}/api/mesh/oracle/markets/more?category=${cat}&offset=${current}&limit=10`,
        );
        if (res.ok) {
          const d = await res.json();
          if (d.markets?.length) {
            setCategories((prev) => ({
              ...prev,
              [cat]: [...prev[cat], ...d.markets],
            }));
          }
          if (d.total != null) setCatTotals((prev) => ({ ...prev, [cat]: d.total }));
        }
      } catch {
        /* silent */
      }
      setLoadingMore((prev) => {
        const n = new Set(prev);
        n.delete(cat);
        return n;
      });
    },
    [categories],
  );

  const searchMarkets = useCallback(async (query: string) => {
    if (query.length < 2) {
      setSearchResults([]);
      setIsSearching(false);
      return;
    }
    setIsSearching(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/mesh/oracle/search?q=${encodeURIComponent(query)}&limit=20`,
      );
      if (res.ok) {
        const d = await res.json();
        setSearchResults(d.results || []);
      }
    } catch {
      /* silent */
    }
    setIsSearching(false);
  }, []);

  const handleSearchInput = useCallback(
    (value: string) => {
      setSearchQuery(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => searchMarkets(value), 300);
    },
    [searchMarkets],
  );

  const fetchPredictions = useCallback(async () => {
    if (!nodeId) return;
    try {
      const res = await fetch(
        `${API_BASE}/api/mesh/oracle/predictions?node_id=${encodeURIComponent(nodeId)}`,
      );
      if (res.ok) {
        const d = await res.json();
        setPredictions(d.predictions || []);
      }
    } catch {
      /* silent */
    }
  }, [nodeId]);

  const fetchProfile = useCallback(async () => {
    if (!nodeId) return;
    try {
      const res = await fetch(
        `${API_BASE}/api/mesh/oracle/profile?node_id=${encodeURIComponent(nodeId)}`,
      );
      if (res.ok) {
        const d = await res.json();
        setProfile(d);
      }
    } catch {
      /* silent */
    }
  }, [nodeId]);

  useEffect(() => {
    let mounted = true;
    const syncIdentity = async () => {
      try {
        const context = await getActiveSigningContext();
        if (mounted) {
          setActiveNodeId(context?.nodeId || identity?.nodeId || '');
        }
      } catch {
        if (mounted) {
          setActiveNodeId(identity?.nodeId || '');
        }
      }
    };
    void syncIdentity();
    const iv = setInterval(() => {
      void syncIdentity();
    }, 5000);
    return () => {
      mounted = false;
      clearInterval(iv);
    };
  }, [identity?.nodeId]);

  // Poll based on active tab
  useEffect(() => {
    if (isMinimized) return;
    if (activeTab === 'markets') {
      fetchMarkets();
      const iv = setInterval(fetchMarkets, 60000);
      return () => clearInterval(iv);
    } else if (activeTab === 'active') {
      fetchPredictions();
      const iv = setInterval(fetchPredictions, 30000);
      return () => clearInterval(iv);
    } else if (activeTab === 'profile') {
      fetchProfile();
      const iv = setInterval(fetchProfile, 60000);
      return () => clearInterval(iv);
    }
  }, [isMinimized, activeTab, fetchMarkets, fetchPredictions, fetchProfile]);

  // ── Place prediction (supports free + staked) ──

  const placePrediction = async (marketTitle: string, side: string, stakeAmount: number = 0) => {
    if (!nodeId) {
      setBetStatus('GENERATE IDENTITY FIRST');
      setTimeout(() => setBetStatus(''), 3000);
      return;
    }
    setLoading(true);
    try {
      const signingContext = await getActiveSigningContext();
      if (!signingContext) {
        setBetStatus('identity required');
        setLoading(false);
        return;
      }
      const sequence = nextSequence();
      const predictionPayload = {
        market_title: marketTitle,
        side,
        stake_amount: stakeAmount,
      };
      const v = validateEventPayload('prediction', predictionPayload);
      if (!v.ok) {
        setBetStatus(`invalid payload: ${v.reason}`);
        setLoading(false);
        setTimeout(() => setBetStatus(''), 4000);
        return;
      }
      const signed = await signMeshEvent('prediction', predictionPayload, sequence);
      const res = await fetch(`${API_BASE}/api/mesh/oracle/predict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          node_id: signed.context.nodeId,
          market_title: marketTitle,
          side,
          stake_amount: stakeAmount,
          public_key: signed.context.publicKey,
          public_key_algo: signed.context.publicKeyAlgo,
          signature: signed.signature,
          sequence: signed.sequence,
          protocol_version: signed.protocolVersion,
        }),
      });
      const d = await res.json();
      if (d.ok) {
        const modeLabel = stakeAmount > 0 ? `STAKED ${stakeAmount.toFixed(1)} REP` : 'FREE PICK';
        setBetStatus(`${side.toUpperCase()} ${modeLabel} — FINAL`);
        setModalMarket(null);
        setActiveNodeId(signed.context.nodeId);
        fetchPredictions();
        fetchProfile();
      } else {
        setBetStatus(d.detail || 'FAILED');
      }
    } catch {
      setBetStatus('NETWORK ERROR');
    }
    setLoading(false);
    setTimeout(() => setBetStatus(''), 4000);
  };

  // ── Toggle category ──

  const toggleCategory = (cat: MarketCategory) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  // ── Header market count ──
  const headerCount = totalCount || Object.values(categories).reduce((a, c) => a + c.length, 0);
  const availableRep = profile?.oracle_rep ?? 0;

  const tabs: { id: Tab; label: string; icon: typeof TrendingUp }[] = [
    { id: 'markets', label: 'MARKETS', icon: TrendingUp },
    { id: 'trending', label: 'TRENDING', icon: Zap },
    { id: 'active', label: 'ACTIVE', icon: AlertTriangle },
    { id: 'profile', label: 'PROFILE', icon: User },
  ];

  return (
    <>
      {/* Market Modal */}
      <AnimatePresence>
        {modalMarket && (
          <MarketModal
            market={modalMarket}
            onClose={() => setModalMarket(null)}
            onPredict={placePrediction}
            loading={loading}
            availableRep={availableRep}
          />
        )}
      </AnimatePresence>

      <motion.div
        initial={{ opacity: 0, x: 50 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.8, delay: 0.2 }}
        className="w-full bg-[#0a0a0a]/90 backdrop-blur-sm border border-cyan-900/40 z-10 flex flex-col font-mono text-sm pointer-events-auto flex-shrink-0"
      >
        {/* Header */}
        <div
          className="flex justify-between items-center p-4 cursor-pointer hover:bg-[var(--bg-secondary)]/50 transition-colors border-b border-[var(--border-primary)]/50"
          onClick={() => setIsMinimized(!isMinimized)}
        >
          <div className="flex items-center gap-2">
            <Trophy size={12} className="text-[var(--text-muted)]" />
            <span className="text-[12px] text-[var(--text-muted)] font-mono tracking-widest">
              ORACLE PREDICTIONS
            </span>
            {headerCount > 0 && (
              <span className="text-[8px] bg-emerald-500/15 text-emerald-400 px-1.5 py-0.5 rounded-sm font-mono">
                {headerCount}
              </span>
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
              className="overflow-hidden flex flex-col"
            >
              {/* Tab bar */}
              <div className="flex border-b border-[var(--border-primary)]/50">
                {tabs.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setActiveTab(t.id)}
                    className={`flex-1 py-2 text-[10px] font-mono tracking-widest transition-colors flex items-center justify-center gap-1 ${
                      activeTab === t.id
                        ? 'text-emerald-400 border-b border-emerald-400/60 bg-emerald-500/5'
                        : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                    }`}
                  >
                    <t.icon size={10} /> {t.label}
                  </button>
                ))}
              </div>

              {/* Status bar */}
              {betStatus && (
                <div className="px-3 py-1 text-[8px] font-mono text-center bg-emerald-500/10 text-emerald-400 border-b border-[var(--border-primary)]/30">
                  {betStatus}
                </div>
              )}

              {/* Content */}
              <div className="overflow-y-auto styled-scrollbar max-h-[280px]">
                {/* ─── MARKETS TAB ─── */}
                {activeTab === 'markets' && (
                  <div className="flex flex-col">
                    {/* Search bar */}
                    <div className="px-3 pt-3 pb-2">
                      <div className="relative">
                        <Search
                          size={10}
                          className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
                        />
                        <input
                          type="text"
                          value={searchQuery}
                          onChange={(e) => handleSearchInput(e.target.value)}
                          placeholder="SEARCH MARKETS..."
                          className="w-full pl-6 pr-6 py-1.5 text-[9px] font-mono tracking-wider bg-[var(--bg-primary)]/60 border border-[var(--border-primary)]/50 text-[var(--text-secondary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-emerald-500/50"
                        />
                        {searchQuery && (
                          <button
                            onClick={() => {
                              setSearchQuery('');
                              setSearchResults([]);
                            }}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                          >
                            <X size={10} />
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Search results overlay */}
                    {searchQuery.length >= 2 && (
                      <div className="px-3 pb-2 flex flex-col gap-1">
                        <div className="text-[7px] font-mono tracking-widest text-[var(--text-muted)] mb-1">
                          {isSearching
                            ? 'SEARCHING ALL MARKETS...'
                            : `${searchResults.length} RESULTS FROM POLYMARKET + KALSHI`}
                        </div>
                        {!isSearching && searchResults.length === 0 && (
                          <div className="text-[8px] text-[var(--text-muted)] font-mono text-center py-3">
                            NO RESULTS FOR &quot;{searchQuery.toUpperCase()}&quot;
                          </div>
                        )}
                        {searchResults.map((m, i) => (
                          <MarketCard key={`s-${i}`} market={m} onOpenModal={setModalMarket} />
                        ))}
                      </div>
                    )}

                    {/* Category accordions (hidden during search) */}
                    {searchQuery.length < 2 && (
                      <div className="flex flex-col">
                        {CATEGORY_CONFIG.map((cat) => {
                          const catMarkets = categories[cat.id] || [];
                          const isExpanded = expandedCategories.has(cat.id);
                          return (
                            <div
                              key={cat.id}
                              className="border-b border-[var(--border-primary)]/30 last:border-b-0"
                            >
                              {/* Category header */}
                              <button
                                onClick={() => toggleCategory(cat.id)}
                                className="w-full flex items-center justify-between px-3 py-2 text-[9px] font-mono tracking-widest hover:bg-[var(--bg-secondary)]/30 transition-colors"
                              >
                                <div className="flex items-center gap-1.5">
                                  <cat.icon size={10} className={cat.color} />
                                  <span className={cat.color}>{cat.label}</span>
                                  <span className="text-[7px] text-[var(--text-muted)]">
                                    ({catMarkets.length})
                                  </span>
                                </div>
                                {isExpanded ? (
                                  <ChevronUp size={10} className="text-[var(--text-muted)]" />
                                ) : (
                                  <ChevronDown size={10} className="text-[var(--text-muted)]" />
                                )}
                              </button>
                              {/* Category markets */}
                              <AnimatePresence>
                                {isExpanded && (
                                  <motion.div
                                    initial={{ height: 0, opacity: 0 }}
                                    animate={{ height: 'auto', opacity: 1 }}
                                    exit={{ height: 0, opacity: 0 }}
                                    className="overflow-hidden"
                                  >
                                    <div className="flex flex-col gap-1 px-3 pb-2">
                                      {catMarkets.length === 0 && (
                                        <div className="text-[8px] text-[var(--text-muted)] text-center py-2 font-mono">
                                          NO MARKETS
                                        </div>
                                      )}
                                      {catMarkets.map((m, i) => (
                                        <MarketCard
                                          key={`${cat.id}-${i}`}
                                          market={m}
                                          onOpenModal={setModalMarket}
                                        />
                                      ))}
                                      {/* MORE button */}
                                      {catMarkets.length > 0 &&
                                        catMarkets.length < (catTotals[cat.id] || 0) && (
                                          <button
                                            onClick={() => loadMoreMarkets(cat.id)}
                                            disabled={loadingMore.has(cat.id)}
                                            className="w-full py-1.5 text-[8px] font-mono tracking-widest text-[var(--text-muted)] hover:text-emerald-400 border border-[var(--border-primary)]/30 hover:border-emerald-500/30 transition-colors disabled:opacity-50"
                                          >
                                            {loadingMore.has(cat.id)
                                              ? 'LOADING...'
                                              : `MORE (${catMarkets.length}/${catTotals[cat.id]})`}
                                          </button>
                                        )}
                                    </div>
                                  </motion.div>
                                )}
                              </AnimatePresence>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* ─── TRENDING TAB ─── */}
                {activeTab === 'trending' && (
                  <div className="flex flex-col gap-1 p-3">
                    {/* News-Linked Markets */}
                    {(() => {
                      const newsLinked = (_newsData || [])
                        .filter((n: any) => n.prediction_odds?.consensus_pct != null)
                        .map((n: any) => n.prediction_odds)
                        .filter((v: any, i: number, a: any[]) => a.findIndex((x: any) => x.title === v.title) === i)
                        .slice(0, 5);
                      if (newsLinked.length === 0) return null;
                      return (
                        <>
                          <div className="text-[7px] font-mono tracking-widest text-amber-400 mb-1">
                            LINKED TO CURRENT HEADLINES
                          </div>
                          {newsLinked.map((m: any, i: number) => (
                            <div key={`nl-${i}`} className="border border-amber-500/30 bg-amber-950/20 p-2">
                              <div className="text-[9px] text-[var(--text-secondary)] font-mono leading-snug mb-1">
                                {m.title}
                              </div>
                              <div className="flex items-center gap-2">
                                <div className="flex-1 h-1 rounded-full bg-[var(--bg-primary)]/60 overflow-hidden flex">
                                  <div className="bg-amber-500/50 transition-all" style={{ width: `${m.consensus_pct}%` }} />
                                  <div className="bg-red-500/20 flex-1" />
                                </div>
                                <span className="text-[8px] font-mono text-amber-400 font-bold">{m.consensus_pct}%</span>
                              </div>
                              <div className="flex gap-1 mt-1">
                                {m.polymarket_pct != null && (
                                  <span className="text-[7px] font-mono px-1 py-0.5 bg-purple-500/15 text-purple-400 border border-purple-500/20">
                                    POLY {m.polymarket_pct}%
                                  </span>
                                )}
                                {m.kalshi_pct != null && (
                                  <span className="text-[7px] font-mono px-1 py-0.5 bg-blue-500/15 text-blue-400 border border-blue-500/20">
                                    KALSHI {m.kalshi_pct}%
                                  </span>
                                )}
                              </div>
                            </div>
                          ))}
                          <div className="border-b border-[var(--border-primary)]/30 my-2" />
                        </>
                      );
                    })()}

                    {/* Trending by Delta */}
                    <div className="text-[7px] font-mono tracking-widest text-[var(--text-muted)] mb-1">
                      BIGGEST PROBABILITY SWINGS
                    </div>
                    {(!trending_markets || trending_markets.length === 0) ? (
                      <div className="text-[8px] text-[var(--text-muted)] font-mono text-center py-4">
                        NO SWINGS DETECTED YET — DELTAS APPEAR AFTER 2+ FETCH CYCLES
                      </div>
                    ) : (
                      trending_markets.map((m: any, i: number) => {
                        const delta = m.delta_pct || 0;
                        const isUp = delta > 0;
                        return (
                          <div
                            key={`t-${i}`}
                            className="border border-[var(--border-primary)]/40 bg-[var(--bg-secondary)]/20 p-2 cursor-pointer hover:bg-[var(--bg-secondary)]/40 transition-colors"
                            onClick={() => {
                              const fakeMarket: Market = {
                                title: m.title,
                                consensus_pct: m.consensus_pct,
                                polymarket_pct: m.polymarket_pct,
                                kalshi_pct: m.kalshi_pct,
                                volume: m.volume || 0,
                                volume_24h: m.volume_24h || 0,
                                end_date: null,
                                description: '',
                                category: m.category || 'NEWS',
                                sources: m.sources || [],
                                slug: m.slug || '',
                              };
                              setModalMarket(fakeMarket);
                            }}
                          >
                            <div className="text-[9px] text-[var(--text-secondary)] font-mono leading-snug mb-1">
                              {m.title}
                            </div>
                            <div className="flex items-center gap-2">
                              <div className="flex-1 h-1 rounded-full bg-[var(--bg-primary)]/60 overflow-hidden flex">
                                <div className="bg-emerald-500/50 transition-all" style={{ width: `${m.consensus_pct ?? 50}%` }} />
                                <div className="bg-red-500/30 flex-1" />
                              </div>
                              <span className="text-[8px] font-mono text-emerald-400">{m.consensus_pct ?? '?'}%</span>
                              <span className={`text-[8px] font-mono font-bold ${isUp ? 'text-green-400' : 'text-red-400'}`}>
                                {isUp ? '\u25B2' : '\u25BC'}{Math.abs(delta).toFixed(1)}%
                              </span>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                )}

                {/* ─── ACTIVE TAB ─── */}
                {activeTab === 'active' && (
                  <div className="flex flex-col gap-1 p-3">
                    {!nodeId && (
                      <div className="text-[9px] text-[var(--text-muted)] font-mono text-center py-6">
                        CONNECT WORMHOLE OR GENERATE IDENTITY IN MESH CHAT FIRST
                      </div>
                    )}
                    {nodeId && predictions.length === 0 && (
                      <div className="text-[9px] text-[var(--text-muted)] font-mono text-center py-6">
                        NO ACTIVE PREDICTIONS
                      </div>
                    )}
                    {predictions.map((p, i) => (
                      <div
                        key={i}
                        className="p-2 border border-[var(--border-primary)]/40 bg-[var(--bg-secondary)]/20"
                      >
                        <div className="text-[9px] text-[var(--text-secondary)] font-mono leading-snug mb-1.5">
                          {p.market_title}
                        </div>
                        <div className="flex items-center gap-2 text-[8px] font-mono flex-wrap">
                          <span
                            className={`px-1.5 py-0.5 rounded-sm border ${
                              p.side.toLowerCase() === 'no'
                                ? 'bg-red-500/15 text-red-400 border-red-500/30'
                                : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                            }`}
                          >
                            {p.side.toUpperCase()}
                          </span>
                          <span className="text-[var(--text-muted)]">
                            @ {p.probability_at_bet}%
                          </span>
                          <span
                            className={`px-1 py-0.5 rounded-sm ${
                              p.mode === 'staked'
                                ? 'bg-amber-500/15 text-amber-400 border border-amber-500/20'
                                : 'bg-[var(--bg-secondary)] text-[var(--text-muted)]'
                            }`}
                          >
                            {p.mode === 'staked' ? `STAKED ${p.staked.toFixed(1)}` : 'FREE'}
                          </span>
                          <span className="text-[var(--text-muted)]">{p.placed}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* ─── PROFILE TAB ─── */}
                {activeTab === 'profile' && (
                  <div className="p-3">
                    {!nodeId && (
                      <div className="text-[9px] text-[var(--text-muted)] font-mono text-center py-6">
                        CONNECT WORMHOLE OR GENERATE IDENTITY IN MESH CHAT FIRST
                      </div>
                    )}
                    {nodeId && !profile && (
                      <div className="text-[9px] text-[var(--text-muted)] font-mono text-center py-6">
                        PLACE YOUR FIRST PREDICTION
                      </div>
                    )}
                    {profile && (
                      <div className="flex flex-col gap-3">
                        <div className="grid grid-cols-3 gap-2">
                          <div className="p-2 border border-[var(--border-primary)]/40 bg-[var(--bg-secondary)]/20 text-center">
                            <div className="text-[14px] font-bold text-emerald-400 font-mono">
                              {profile.oracle_rep.toFixed(1)}
                            </div>
                            <div className="text-[7px] text-[var(--text-muted)] font-mono tracking-widest mt-0.5">
                              ORACLE REP
                            </div>
                          </div>
                          <div className="p-2 border border-[var(--border-primary)]/40 bg-[var(--bg-secondary)]/20 text-center">
                            <div className="text-[14px] font-bold text-cyan-400 font-mono">
                              {profile.win_rate}%
                            </div>
                            <div className="text-[7px] text-[var(--text-muted)] font-mono tracking-widest mt-0.5">
                              WIN RATE
                            </div>
                          </div>
                          <div className="p-2 border border-[var(--border-primary)]/40 bg-[var(--bg-secondary)]/20 text-center">
                            <div className="text-[14px] font-bold text-amber-400 font-mono">
                              {profile.predictions_won + profile.predictions_lost}
                            </div>
                            <div className="text-[7px] text-[var(--text-muted)] font-mono tracking-widest mt-0.5">
                              TOTAL BETS
                            </div>
                          </div>
                        </div>
                        <div className="flex flex-col gap-1 text-[9px] font-mono">
                          <div className="flex justify-between px-1">
                            <span className="text-[var(--text-muted)]">Available Rep</span>
                            <span className="text-emerald-400">
                              {profile.oracle_rep.toFixed(2)}
                            </span>
                          </div>
                          <div className="flex justify-between px-1">
                            <span className="text-[var(--text-muted)]">Locked Rep</span>
                            <span className="text-amber-400">
                              {profile.oracle_rep_locked.toFixed(2)}
                            </span>
                          </div>
                          <div className="flex justify-between px-1">
                            <span className="text-[var(--text-muted)]">W / L</span>
                            <span className="text-[var(--text-secondary)]">
                              {profile.predictions_won} / {profile.predictions_lost}
                            </span>
                          </div>
                          <div className="flex justify-between px-1">
                            <span className="text-[var(--text-muted)]">Farming Score</span>
                            <span
                              className={
                                profile.farming_pct > 70
                                  ? 'text-red-400'
                                  : 'text-[var(--text-secondary)]'
                              }
                            >
                              {profile.farming_pct}%
                            </span>
                          </div>
                        </div>
                        <div className="text-[7px] text-[var(--text-muted)] font-mono text-center mt-1 opacity-60 truncate">
                          {nodeId}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </>
  );
});

export default PredictionsPanel;
