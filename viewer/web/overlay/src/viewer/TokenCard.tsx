'use client';

/**
 * The project token, above the Public Viewer card: current price, 24-hour
 * change and market value, and a link to its pump.fun page.
 *
 * The figures come from GeckoTerminal's public API, asked for by the
 * visitor's own browser (no key). They are shown as that service reports
 * them and are information only. If the service does not answer, the card
 * is still a plain link to the token page.
 */

import React, { useEffect, useState } from 'react';
import { ArrowUpRight, Coins } from 'lucide-react';
import { VIEWER_TOKEN } from './config';

type Quote = { price: number | null; change24h: number | null; marketValue: number | null };

const REFRESH_MS = 60_000;

function num(value: unknown): number | null {
  const n = typeof value === 'string' || typeof value === 'number' ? Number(value) : NaN;
  return Number.isFinite(n) ? n : null;
}

async function fetchQuote(signal: AbortSignal): Promise<Quote | null> {
  const res = await fetch(`${VIEWER_TOKEN.quoteUrl}?include=top_pools`, { signal, headers: { accept: 'application/json' } });
  if (!res.ok) return null;
  const body = (await res.json()) as {
    data?: { attributes?: Record<string, unknown> };
    included?: { type?: string; attributes?: Record<string, unknown> }[];
  };
  const token = body.data?.attributes || {};
  // The deepest pool is the one whose price people actually trade at.
  const pool = (body.included || [])
    .filter((item) => item.type === 'pool')
    .sort((a, b) => (num(b.attributes?.reserve_in_usd) || 0) - (num(a.attributes?.reserve_in_usd) || 0))[0]?.attributes;
  const change = (pool?.price_change_percentage || {}) as Record<string, unknown>;
  const quote: Quote = {
    price: num(pool?.base_token_price_usd) ?? num(token.price_usd),
    change24h: num(change.h24),
    marketValue: num(pool?.market_cap_usd) ?? num(token.market_cap_usd) ?? num(pool?.fdv_usd) ?? num(token.fdv_usd),
  };
  return quote.price === null && quote.marketValue === null ? null : quote;
}

function formatPrice(value: number): string {
  if (value >= 1) return `$${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  // Small prices: three meaningful digits, written out in full (no exponent).
  return `$${value.toLocaleString('en-US', { maximumSignificantDigits: 3, maximumFractionDigits: 12 })}`;
}

function formatCompact(value: number): string {
  return `$${new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 }).format(value)}`;
}

export default function TokenCard() {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let timer = 0;
    let controller: AbortController | null = null;
    let stopped = false;

    const load = async () => {
      if (document.visibilityState === 'hidden') return;
      controller?.abort();
      controller = new AbortController();
      try {
        const next = await fetchQuote(controller.signal);
        if (stopped) return;
        if (next) {
          setQuote(next);
          setFailed(false);
        } else {
          setFailed(true);
        }
      } catch {
        if (!stopped) setFailed(true);
      }
    };

    void load();
    timer = window.setInterval(load, REFRESH_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      stopped = true;
      controller?.abort();
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  const change = quote?.change24h ?? null;
  const up = change !== null && change >= 0;

  return (
    <a
      href={VIEWER_TOKEN.href}
      target="_blank"
      rel="noopener noreferrer"
      title={`${VIEWER_TOKEN.symbol} on pump.fun (opens in a new tab)`}
      className="sb-token-card sb-panel group flex-shrink-0 pointer-events-auto flex items-center gap-3 px-3.5 py-2.5 no-underline"
    >
      <span className="sb-token-mark grid place-items-center w-9 h-9 rounded-full shrink-0" aria-hidden="true">
        <Coins size={17} />
      </span>

      <span className="min-w-0 flex flex-col">
        <span className="flex items-center gap-1.5">
          <span className="text-[13px] font-mono font-bold tracking-[0.08em] text-[var(--text-primary)]">{VIEWER_TOKEN.symbol}</span>
          <span className="text-[9.5px] font-mono tracking-[0.14em] uppercase text-[var(--text-muted)]">pump.fun</span>
          <ArrowUpRight size={12} className="text-[#2cf5a0] opacity-70 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" aria-hidden="true" />
        </span>
        <span className="text-[10px] font-mono tracking-wider text-[var(--text-muted)]">
          {quote?.marketValue != null ? `Market value ${formatCompact(quote.marketValue)}` : failed ? 'Price unavailable right now' : 'Loading price…'}
        </span>
      </span>

      <span className="ml-auto flex flex-col items-end shrink-0" aria-live="polite">
        <span className="text-[14px] font-mono font-bold tabular-nums text-[var(--text-primary)]">
          {quote?.price != null ? formatPrice(quote.price) : '—'}
        </span>
        {change !== null && (
          <span className={`text-[10.5px] font-mono font-bold tabular-nums ${up ? 'text-[#2cf5a0]' : 'text-[#ff6b6b]'}`}>
            {up ? '▲' : '▼'} {Math.abs(change).toFixed(2)}% <span className="font-normal text-[var(--text-muted)]">24h</span>
          </span>
        )}
      </span>

      <style>{`
        .sb-token-card {
          border-color: color-mix(in srgb, #2cf5a0 30%, transparent);
          background: linear-gradient(100deg, color-mix(in srgb, #2cf5a0 11%, transparent), color-mix(in srgb, #2cf5a0 2%, transparent) 60%);
          transition: border-color .2s, box-shadow .2s, transform .2s;
        }
        .sb-token-card:hover, .sb-token-card:focus-visible {
          border-color: color-mix(in srgb, #2cf5a0 70%, transparent);
          box-shadow: 0 0 0 1px color-mix(in srgb, #2cf5a0 22%, transparent), 0 8px 22px -10px #2cf5a0;
          outline: none;
        }
        .sb-token-mark { color: #2cf5a0; background: color-mix(in srgb, #2cf5a0 16%, transparent); }
      `}</style>
    </a>
  );
}
