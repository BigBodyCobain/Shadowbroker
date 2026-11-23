'use client';

import React from 'react';
import { Plus, RotateCcw, Rss, Save, Trash2 } from 'lucide-react';
import { MAX_FEEDS, WEIGHT_COLORS, WEIGHT_LABELS } from './SettingsPanel.shared';
import type { FeedEntry } from './SettingsPanel.shared';

type FeedMsg = { type: 'ok' | 'err'; text: string } | null;

export function SettingsPanelNewsFeeds(props: {
  feeds: FeedEntry[];
  feedMsg: FeedMsg;
  feedsDirty: boolean;
  feedSaving: boolean;
  updateFeed: (idx: number, key: keyof FeedEntry, value: FeedEntry[keyof FeedEntry]) => void;
  removeFeed: (idx: number) => void;
  addFeed: () => void;
  saveFeeds: () => void;
  resetFeeds: () => void;
}) {
  const { feeds, feedMsg, feedsDirty, feedSaving, updateFeed, removeFeed, addFeed, saveFeeds, resetFeeds } = props;

  return (
    <>
      <div className="mx-4 mt-4 p-3 border border-orange-900/30 bg-orange-950/10">
        <div className="flex items-start gap-2">
          <Rss size={12} className="text-orange-500 mt-0.5 flex-shrink-0" />
          <p className="text-sm sb-prose text-[#c3d2e6] leading-relaxed">
            Configure RSS/Atom feeds for the Threat Intel news panel. Each feed is scored
            by keyword heuristics and weighted by the priority you set. Up to{' '}
            <span className="text-orange-400">{MAX_FEEDS}</span> sources.
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto styled-scrollbar p-4 space-y-2">
        {feeds.map((feed, idx) => (
          <div
            key={idx}
            className="border border-[var(--border-primary)]/60 p-3 hover:border-[var(--border-secondary)]/60 transition-colors group"
          >
            <div className="flex items-center gap-2 mb-2">
              <input
                type="text"
                value={feed.name}
                onChange={(e) => updateFeed(idx, 'name', e.target.value)}
                className="flex-1 bg-transparent border-b border-[var(--border-primary)] text-xs font-mono text-[var(--text-primary)] outline-none focus:border-cyan-500/70 transition-colors px-1 py-0.5"
                placeholder="Source name..."
              />
              <div className="flex items-center gap-1">
                {[1, 2, 3, 4, 5].map((w) => (
                  <button
                    key={w}
                    onClick={() => updateFeed(idx, 'weight', w)}
                    className={`w-5 h-5 text-[12px] font-mono font-bold border transition-all ${feed.weight === w ? WEIGHT_COLORS[w] + ' bg-black/40' : 'border-[var(--border-primary)]/40 text-[var(--text-muted)]/50 hover:border-[var(--border-secondary)]'}`}
                    title={WEIGHT_LABELS[w]}
                  >
                    {w}
                  </button>
                ))}
                <span
                  className={`text-[12px] font-mono ml-1 w-7 ${WEIGHT_COLORS[feed.weight]?.split(' ')[0] || 'text-gray-400'}`}
                >
                  {WEIGHT_LABELS[feed.weight] || 'STD'}
                </span>
              </div>
              <button
                onClick={() => removeFeed(idx)}
                className="w-6 h-6 flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 hover:bg-red-950/20 transition-all opacity-0 group-hover:opacity-100"
                title="Remove feed"
              >
                <Trash2 size={11} />
              </button>
            </div>
            <input
              type="text"
              value={feed.url}
              onChange={(e) => updateFeed(idx, 'url', e.target.value)}
              className="w-full bg-black/30 border border-[var(--border-primary)]/40 px-2 py-1 text-sm font-mono text-[var(--text-muted)] outline-none focus:border-cyan-500/50 focus:text-cyan-300 transition-colors"
              placeholder="https://example.com/rss.xml"
            />
          </div>
        ))}

        <button
          onClick={addFeed}
          disabled={feeds.length >= MAX_FEEDS}
          className="w-full py-2.5 border border-dashed border-[var(--border-primary)]/60 text-[var(--text-muted)] hover:border-orange-500/50 hover:text-orange-400 hover:bg-orange-950/10 transition-all text-sm font-mono flex items-center justify-center gap-1.5 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <Plus size={10} />
          ADD FEED ({feeds.length}/{MAX_FEEDS})
        </button>
      </div>

      {feedMsg && (
        <div
          className={`mx-4 mb-2 px-3 py-2 text-sm font-mono ${feedMsg.type === 'ok' ? 'text-green-400 bg-green-950/20 border border-green-900/30' : 'text-red-400 bg-red-950/20 border border-red-900/30'}`}
        >
          {feedMsg.text}
        </div>
      )}

      <div className="p-4 border-t border-[var(--border-primary)]/80">
        <div className="flex items-center gap-2">
          <button
            onClick={saveFeeds}
            disabled={!feedsDirty || feedSaving}
            className="flex-1 px-4 py-2 bg-orange-500/20 border border-orange-500/40 text-orange-400 hover:bg-orange-500/30 transition-colors text-sm font-mono flex items-center justify-center gap-1.5 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Save size={10} />
            {feedSaving ? 'SAVING...' : 'SAVE FEEDS'}
          </button>
          <button
            onClick={resetFeeds}
            className="px-3 py-2 border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:border-[var(--border-secondary)] transition-all text-sm font-mono flex items-center gap-1.5"
            title="Reset to defaults"
          >
            <RotateCcw size={10} />
            RESET
          </button>
        </div>
        <div className="flex items-center justify-between text-[13px] text-[var(--text-muted)] font-mono mt-2">
          <span>{feeds.length}/{MAX_FEEDS} SOURCES</span>
          <span>WEIGHT: 1=LOW 5=CRITICAL</span>
        </div>
      </div>
    </>
  );
}
