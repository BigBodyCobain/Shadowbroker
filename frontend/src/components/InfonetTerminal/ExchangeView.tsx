'use client';

import React, { useState, useMemo } from 'react';
import { ChevronLeft, ArrowRightLeft, TrendingUp, TrendingDown, Activity, Wallet, ArrowDownToLine, ArrowUpFromLine, Copy, X } from 'lucide-react';
import { useDataKeys } from '@/hooks/useDataStore';
import type { DashboardData, StockTicker } from '@/types/dashboard';

interface ExchangeViewProps {
  onBack: () => void;
}

type DataSlice = Pick<DashboardData, 'stocks'>;
const DATA_KEYS = ['stocks'] as const;

// Symbols we want to show as crypto trading pairs
const CRYPTO_SYMBOLS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];
const CRYPTO_NAMES: Record<string, string> = {
  BTC: 'Bitcoin', ETH: 'Ethereum', SOL: 'Solana', XRP: 'Ripple', DOGE: 'Dogecoin',
  ZEC: 'Zcash', XMR: 'Monero', ADA: 'Cardano', DOT: 'Polkadot', AVAX: 'Avalanche',
};

const FALLBACK_PAIRS = [
  { symbol: 'BTC', name: 'Bitcoin', price: '—', change: '—', up: true },
  { symbol: 'ETH', name: 'Ethereum', price: '—', change: '—', up: true },
  { symbol: 'SOL', name: 'Solana', price: '—', change: '—', up: true },
];

const MOCK_BALANCES = [
  { symbol: 'CREDITS', name: 'Credits', balance: '12,540.00', value: '12,540.00' },
  { symbol: 'BTC', name: 'Bitcoin', balance: '0.045', value: '56,025.00' },
  { symbol: 'ETH', name: 'Ethereum', balance: '1.2', value: '101,040.60' },
  { symbol: 'SOL', name: 'Solana', balance: '45.0', value: '184,511.25' },
  { symbol: 'ZEC', name: 'Zcash', balance: '0.00', value: '0.00' },
  { symbol: 'XMR', name: 'Monero', balance: '2.5', value: '72,251.87' },
];

const ORDER_BOOK_BIDS = [
  { price: '1,244,900.00', amount: '0.05', total: '62,245.00' },
  { price: '1,244,850.00', amount: '0.12', total: '149,382.00' },
  { price: '1,244,800.00', amount: '0.80', total: '995,840.00' },
];

const ORDER_BOOK_ASKS = [
  { price: '1,245,100.00', amount: '0.02', total: '24,902.00' },
  { price: '1,245,150.00', amount: '0.15', total: '186,772.50' },
  { price: '1,245,200.00', amount: '1.50', total: '1,867,800.00' },
];

export default function ExchangeView({ onBack }: ExchangeViewProps) {
  const data = useDataKeys(DATA_KEYS) as DataSlice;
  const stocks = data?.stocks;

  // Build live trading pairs from real stock data
  const PAIRS = useMemo(() => {
    if (!stocks) return FALLBACK_PAIRS;
    const entries = Object.entries(stocks as Record<string, StockTicker>)
      .filter(([k]) => !['last_updated', 'source'].includes(k));
    // Try crypto symbols first, then fill with whatever's available
    const pairs: { symbol: string; name: string; price: string; change: string; up: boolean }[] = [];
    for (const sym of CRYPTO_SYMBOLS) {
      const match = entries.find(([k]) => k.toUpperCase() === sym);
      if (match) {
        const [, val] = match;
        if (val && val.price != null) {
          pairs.push({
            symbol: sym,
            name: CRYPTO_NAMES[sym] || sym,
            price: val.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
            change: `${val.change_percent >= 0 ? '+' : ''}${val.change_percent.toFixed(1)}%`,
            up: val.change_percent >= 0,
          });
        }
      }
    }
    // If we didn't find enough crypto, add other stock tickers
    if (pairs.length < 3) {
      for (const [k, val] of entries) {
        if (pairs.some(p => p.symbol === k.toUpperCase())) continue;
        if (val && val.price != null) {
          pairs.push({
            symbol: k.toUpperCase(),
            name: CRYPTO_NAMES[k.toUpperCase()] || k.toUpperCase(),
            price: val.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
            change: `${val.change_percent >= 0 ? '+' : ''}${val.change_percent.toFixed(1)}%`,
            up: val.change_percent >= 0,
          });
          if (pairs.length >= 8) break;
        }
      }
    }
    return pairs.length > 0 ? pairs : FALLBACK_PAIRS;
  }, [stocks]);

  const [activeTab, setActiveTab] = useState<'trade' | 'funds'>('trade');
  const [selectedPair, setSelectedPair] = useState(PAIRS[0]);
  const [orderType, setOrderType] = useState<'BUY' | 'SELL'>('BUY');
  const [amount, setAmount] = useState('');
  const [price, setPrice] = useState(selectedPair.price.replace(/,/g, ''));

  const [depositAsset, setDepositAsset] = useState<typeof MOCK_BALANCES[0] | null>(null);
  const [withdrawAsset, setWithdrawAsset] = useState<typeof MOCK_BALANCES[0] | null>(null);
  const [withdrawAmount, setWithdrawAmount] = useState('');

  const generateMockAddress = (symbol: string) => {
    const prefix = symbol === 'BTC' ? 'bc1q' : symbol === 'ETH' ? '0x' : symbol === 'SOL' ? '' : 't1';
    const randomHex = Array.from({length: 32}, () => Math.floor(Math.random()*16).toString(16)).join('');
    return `${prefix}${randomHex}`;
  };

  const getNetworkFee = (symbol: string) => {
    switch(symbol) {
      case 'BTC': return 0.00015;
      case 'ETH': return 0.004;
      case 'SOL': return 0.005;
      case 'ZEC': return 0.001;
      case 'XMR': return 0.002;
      case 'CREDITS': return 5.00;
      default: return 0.01;
    }
  };

  const handleWithdrawClick = (asset: typeof MOCK_BALANCES[0]) => {
    setWithdrawAsset(asset);
    setWithdrawAmount('');
  };

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
          <ArrowRightLeft className="mr-2 text-cyan-400" />
          DECENTRALIZED EXCHANGE
        </h1>
        <p className="text-gray-500 text-sm mt-1">Trade crypto assets against Credits. Zero KYC. Zero logs.</p>
      </div>

      {/* Navigation Tabs */}
      <div className="flex gap-2 mb-4 shrink-0 border-b border-gray-800 pb-2 overflow-x-auto">
        <button
          onClick={() => setActiveTab('trade')}
          className={`flex items-center px-4 py-2 uppercase text-xs tracking-widest transition-colors whitespace-nowrap ${activeTab === 'trade' ? 'bg-gray-800/50 text-gray-300 border-b-2 border-cyan-400' : 'text-gray-500 hover:text-gray-400'}`}
        >
          <ArrowRightLeft size={14} className="mr-2" /> TRADE
        </button>
        <button
          onClick={() => setActiveTab('funds')}
          className={`flex items-center px-4 py-2 uppercase text-xs tracking-widest transition-colors whitespace-nowrap ${activeTab === 'funds' ? 'bg-gray-800/50 text-gray-300 border-b-2 border-cyan-400' : 'text-gray-500 hover:text-gray-400'}`}
        >
          <Wallet size={14} className="mr-2" /> FUNDS
        </button>
      </div>

      <div className="flex-1 overflow-y-auto pr-2 flex flex-col md:flex-row gap-4 pb-4">

        {/* TRADE TAB */}
        {activeTab === 'trade' && (
          <>
            {/* Left Column: Pairs & Chart */}
            <div className="flex-1 flex flex-col gap-4">
              {/* Pairs List */}
              <div className="border border-gray-800 bg-gray-900/20 p-4">
                <h2 className="text-cyan-400 font-bold mb-4 border-b border-gray-800 pb-2 flex items-center">
                  <Activity size={16} className="mr-2" /> TRADING PAIRS (vs CREDITS)
                </h2>
                <div className="space-y-2">
                  {PAIRS.map(pair => (
                    <div
                      key={pair.symbol}
                      onClick={() => { setSelectedPair(pair); setPrice(pair.price.replace(/,/g, '')); }}
                      className={`flex justify-between items-center p-2 cursor-pointer transition-colors border ${selectedPair.symbol === pair.symbol ? 'border-cyan-400 bg-cyan-900/20' : 'border-gray-800 bg-[#0a0a0a] hover:border-gray-700'}`}
                    >
                      <div className="flex items-center">
                        <span className="font-bold text-gray-300 w-12">{pair.symbol}</span>
                        <span className="text-gray-500 text-xs hidden sm:inline">{pair.name}</span>
                      </div>
                      <div className="text-right flex items-center gap-4">
                        <span className="font-mono text-gray-400">{pair.price}</span>
                        <span className={`text-xs flex items-center w-16 justify-end ${pair.up ? 'text-green-400' : 'text-red-400'}`}>
                          {pair.up ? <TrendingUp size={12} className="mr-1" /> : <TrendingDown size={12} className="mr-1" />}
                          {pair.change}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Simple Chart Area */}
              <div className="border border-gray-800 bg-gray-900/20 p-4 flex-1 flex flex-col">
                <h2 className="text-cyan-400 font-bold mb-4 border-b border-gray-800 pb-2 flex justify-between items-center">
                  <span>{selectedPair.symbol}/CREDITS CHART</span>
                  <span className="text-xs text-gray-500">1H | 4H | 1D | 1W</span>
                </h2>
                <div className="flex-1 flex items-end justify-between gap-1 pt-4 h-32">
                  {Array.from({ length: 20 }).map((_, i) => {
                    const height = 20 + Math.random() * 80;
                    const isUp = Math.random() > 0.5;
                    return (
                      <div
                        key={i}
                        className={`w-full ${isUp ? 'bg-green-500/50 border-t border-green-400' : 'bg-red-500/50 border-t border-red-400'}`}
                        style={{ height: `${height}%` }}
                      ></div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Right Column: Order Book & Trade Form */}
            <div className="w-full md:w-80 flex flex-col gap-4 shrink-0">
              {/* Trade Form */}
              <div className="border border-gray-800 bg-gray-900/20 p-4">
                <div className="flex gap-2 mb-4">
                  <button
                    onClick={() => setOrderType('BUY')}
                    className={`flex-1 py-2 font-bold text-sm border transition-colors ${orderType === 'BUY' ? 'bg-green-900/50 border-green-400 text-green-400' : 'bg-black border-gray-800 text-gray-500 hover:border-gray-700'}`}
                  >
                    BUY {selectedPair.symbol}
                  </button>
                  <button
                    onClick={() => setOrderType('SELL')}
                    className={`flex-1 py-2 font-bold text-sm border transition-colors ${orderType === 'SELL' ? 'bg-red-900/50 border-red-400 text-red-400' : 'bg-black border-gray-800 text-gray-500 hover:border-gray-700'}`}
                  >
                    SELL {selectedPair.symbol}
                  </button>
                </div>

                <div className="space-y-4">
                  <div>
                    <label className="text-xs text-gray-500 uppercase tracking-widest mb-1 block">Price (Credits)</label>
                    <input
                      type="text"
                      value={price}
                      onChange={(e) => setPrice(e.target.value)}
                      className="w-full bg-black border border-gray-800 p-2 text-gray-300 font-mono outline-none focus:border-cyan-400"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 uppercase tracking-widest mb-1 block">Amount ({selectedPair.symbol})</label>
                    <input
                      type="text"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      placeholder="0.00"
                      className="w-full bg-black border border-gray-800 p-2 text-gray-300 font-mono outline-none focus:border-cyan-400"
                    />
                  </div>
                  <div className="pt-2 border-t border-gray-800 flex justify-between items-center">
                    <span className="text-xs text-gray-500 uppercase tracking-widest">Total</span>
                    <span className="font-mono text-gray-300 font-bold">
                      {amount && price && !isNaN(Number(amount)) && !isNaN(Number(price))
                        ? (Number(amount) * Number(price)).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                        : '0.00'} CREDITS
                    </span>
                  </div>
                  <button className={`w-full py-3 font-bold uppercase tracking-widest transition-colors ${orderType === 'BUY' ? 'bg-green-600 hover:bg-green-500 text-black' : 'bg-red-600 hover:bg-red-500 text-black'}`}>
                    {orderType} {selectedPair.symbol}
                  </button>
                </div>
              </div>

              {/* Order Book */}
              <div className="border border-gray-800 bg-gray-900/20 p-4 flex-1">
                <h2 className="text-cyan-400 font-bold mb-4 border-b border-gray-800 pb-2">ORDER BOOK</h2>
                <div className="flex justify-between text-xs text-gray-500 uppercase tracking-widest mb-2 px-1">
                  <span>Price(CREDITS)</span>
                  <span>Amt({selectedPair.symbol})</span>
                  <span>Total</span>
                </div>

                <div className="space-y-1 mb-4">
                  {ORDER_BOOK_ASKS.slice().reverse().map((ask, i) => (
                    <div key={i} className="flex justify-between text-xs font-mono px-1 hover:bg-gray-800/50 cursor-pointer">
                      <span className="text-red-400">{ask.price}</span>
                      <span className="text-gray-300">{ask.amount}</span>
                      <span className="text-gray-500">{ask.total}</span>
                    </div>
                  ))}
                </div>

                <div className="py-2 border-y border-gray-800 text-center font-mono font-bold text-gray-300 mb-4">
                  {selectedPair.price} <span className="text-gray-500 text-xs font-sans">Spread: 100.00</span>
                </div>

                <div className="space-y-1">
                  {ORDER_BOOK_BIDS.map((bid, i) => (
                    <div key={i} className="flex justify-between text-xs font-mono px-1 hover:bg-gray-800/50 cursor-pointer">
                      <span className="text-green-400">{bid.price}</span>
                      <span className="text-gray-300">{bid.amount}</span>
                      <span className="text-gray-500">{bid.total}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </>
        )}

        {/* FUNDS TAB */}
        {activeTab === 'funds' && (
          <div className="flex-1 flex flex-col gap-4">
            <div className="border border-gray-800 bg-gray-900/20 p-4">
              <h2 className="text-cyan-400 font-bold mb-4 border-b border-gray-800 pb-2 flex items-center">
                <Wallet size={16} className="mr-2" /> ASSET BALANCES
              </h2>
              <div className="space-y-2">
                {MOCK_BALANCES.map(asset => (
                  <div key={asset.symbol} className="flex flex-col sm:flex-row justify-between items-start sm:items-center p-3 border border-gray-800 bg-[#0a0a0a] hover:border-gray-700 transition-colors gap-4">
                    <div className="flex items-center gap-3 w-48">
                      <div className="w-8 h-8 bg-gray-800/50 rounded-full flex items-center justify-center text-gray-300 font-bold">
                        {asset.symbol.charAt(0)}
                      </div>
                      <div>
                        <div className="font-bold text-gray-300">{asset.symbol}</div>
                        <div className="text-xs text-gray-500">{asset.name}</div>
                      </div>
                    </div>
                    <div className="flex-1 text-left sm:text-right">
                      <div className="font-mono text-gray-300">{asset.balance}</div>
                      <div className="text-xs text-gray-500 font-mono">&asymp; {asset.value} CREDITS</div>
                    </div>
                    <div className="flex gap-2 w-full sm:w-auto mt-2 sm:mt-0">
                      <button onClick={() => setDepositAsset(asset)} className="flex-1 sm:flex-none flex items-center justify-center px-3 py-1.5 bg-cyan-900/20 border border-cyan-900/50 text-cyan-400 hover:bg-cyan-900/40 transition-colors text-xs uppercase tracking-widest">
                        <ArrowDownToLine size={14} className="mr-1" /> RECEIVE
                      </button>
                      <button onClick={() => handleWithdrawClick(asset)} className="flex-1 sm:flex-none flex items-center justify-center px-3 py-1.5 bg-gray-800/50 border border-gray-700 text-gray-300 hover:bg-gray-700 transition-colors text-xs uppercase tracking-widest">
                        <ArrowUpFromLine size={14} className="mr-1" /> SEND
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Deposit Modal */}
      {depositAsset && (
        <div className="absolute inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-[#0a0a0a] border border-cyan-600 p-6 max-w-md w-full shadow-[0_0_30px_rgba(6,182,212,0.15)]">
            <div className="flex justify-between items-center mb-4 border-b border-gray-800 pb-2">
              <h2 className="text-cyan-500 text-lg font-bold flex items-center">
                <ArrowDownToLine className="mr-2" /> RECEIVE {depositAsset.symbol}
              </h2>
              <button onClick={() => setDepositAsset(null)} className="text-gray-500 hover:text-white"><X size={20}/></button>
            </div>
            <div className="flex flex-col items-center justify-center py-6">
              <div className="bg-white p-2 mb-4">
                <div className="w-40 h-40 grid grid-cols-8 grid-rows-8 gap-0.5 bg-white p-1">
                  {Array.from({length: 64}).map((_, i) => (
                    <div key={i} className={Math.random() > 0.4 ? 'bg-black' : 'bg-white'}></div>
                  ))}
                </div>
              </div>
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-2 text-center">Scan QR code or copy address below</p>
              <div className="w-full flex items-center bg-black border border-gray-800 p-2">
                <span className="flex-1 font-mono text-xs text-gray-300 truncate select-all">
                  {generateMockAddress(depositAsset.symbol)}
                </span>
                <button className="ml-2 text-cyan-400 hover:text-cyan-300"><Copy size={14} /></button>
              </div>
              <p className="text-xs text-red-400 mt-4 text-center">Send ONLY {depositAsset.name} ({depositAsset.symbol}) to this address. Sending any other asset will result in permanent loss.</p>
            </div>
          </div>
        </div>
      )}

      {/* Withdraw Modal */}
      {withdrawAsset && (
        <div className="absolute inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-[#0a0a0a] border border-cyan-600 p-6 max-w-md w-full shadow-[0_0_30px_rgba(6,182,212,0.15)]">
            <div className="flex justify-between items-center mb-4 border-b border-gray-800 pb-2">
              <h2 className="text-cyan-500 text-lg font-bold flex items-center">
                <ArrowUpFromLine className="mr-2" /> SEND {withdrawAsset.symbol}
              </h2>
              <button onClick={() => setWithdrawAsset(null)} className="text-gray-500 hover:text-white"><X size={20}/></button>
            </div>
            <div className="space-y-4 py-2">
              <div>
                <div className="flex justify-between mb-1">
                  <label className="text-xs text-gray-500 uppercase tracking-widest">Available Balance</label>
                  <span className="text-xs font-mono text-cyan-400">{withdrawAsset.balance} {withdrawAsset.symbol}</span>
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500 uppercase tracking-widest mb-1 block">Destination Address</label>
                <input type="text" placeholder={`Enter ${withdrawAsset.symbol} address`} className="w-full bg-black border border-gray-800 p-2 text-gray-300 font-mono outline-none focus:border-cyan-400 text-sm" spellCheck={false} />
              </div>
              <div>
                <label className="text-xs text-gray-500 uppercase tracking-widest mb-1 block">Amount</label>
                <div className="relative">
                  <input
                    type="text"
                    value={withdrawAmount}
                    onChange={(e) => setWithdrawAmount(e.target.value)}
                    placeholder="0.00"
                    className="w-full bg-black border border-gray-800 p-2 text-gray-300 font-mono outline-none focus:border-cyan-400 text-sm pr-16"
                  />
                  <button
                    onClick={() => setWithdrawAmount(withdrawAsset.balance)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-cyan-400 hover:text-cyan-300 uppercase tracking-widest font-bold"
                  >
                    MAX
                  </button>
                </div>
              </div>

              <div className="bg-gray-900/30 border border-gray-800 p-3 mt-2">
                <div className="flex justify-between items-center mb-1">
                  <span className="text-xs text-gray-500 uppercase tracking-widest">Network Fee</span>
                  <span className="text-xs font-mono text-gray-400">{getNetworkFee(withdrawAsset.symbol)} {withdrawAsset.symbol}</span>
                </div>
                <div className="flex justify-between items-center border-t border-gray-800 pt-1 mt-1">
                  <span className="text-xs text-gray-500 uppercase tracking-widest">Total Deduction</span>
                  <span className="text-xs font-mono text-white font-bold">
                    {withdrawAmount && !isNaN(Number(withdrawAmount))
                      ? (Number(withdrawAmount) + getNetworkFee(withdrawAsset.symbol)).toFixed(withdrawAsset.symbol === 'CREDITS' ? 2 : 6)
                      : '0.00'} {withdrawAsset.symbol}
                  </span>
                </div>
              </div>

              <div className="pt-4">
                <button className="w-full py-3 bg-cyan-900/50 border border-cyan-500 text-cyan-400 hover:bg-cyan-800 transition-colors font-bold uppercase tracking-widest">
                  CONFIRM SEND
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
