'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from '@/lib/motion';
import {
  X,
  Network,
  KeyRound,
  Shield,
  Bug,
  Heart,
  MessageSquare,
  Radio,
  Radar,
  Plane,
  Languages,
  Layers,
  Bot,
} from 'lucide-react';

const CURRENT_VERSION = '0.9.84';
const STORAGE_KEY = `shadowbroker_changelog_v${CURRENT_VERSION}`;
const RELEASE_TITLE = 'GT Analytics + Telegram Translate + Full Telemetry + Saved Layout';

const HEADLINE_FEATURES = [
  {
    icon: <Radar size={20} className="text-purple-400" />,
    accent: 'purple' as const,
    title: 'GT Analytics & Strategic Risk Layer',
    subtitle:
      'OpenClaw-driven geopolitical analytics now power a Strategic Risk map layer — risk scoring, signal triage, and overlays wired into the dashboard (#392).',
    details: [
      'GT analytics pipeline feeds live risk indicators onto the worldview map so operators can correlate OSINT feeds with strategic posture.',
      'OpenClaw integration exposes entity profile and trail views for agent-assisted analysis without leaving the command surface.',
      'Layer toggles, scoring thresholds, and panel state persist across refreshes via the new dashboard preferences store.',
    ],
    callToAction: 'LEFT PANEL → LAYERS → STRATEGIC RISK',
  },
  {
    icon: <MessageSquare size={20} className="text-cyan-400" />,
    accent: 'cyan' as const,
    title: 'Telegram OSINT Auto-Translate',
    subtitle:
      'Telegram posts in map popups now auto-translate with source-language labels — Persian (fa) joins English, French, and Chinese.',
    details: [
      'Backend translate service detects source language and returns localized text for popup rendering without manual copy-paste.',
      'Persian locale pack (#472) ships full RTL layout support across the dashboard, not just Telegram labels.',
      'Source badges in popups show the detected language so analysts know when a machine translation is in play.',
    ],
    callToAction: 'MAP → TELEGRAM MARKER → VIEW TRANSLATED POST',
  },
  {
    icon: <Plane size={20} className="text-amber-400" />,
    accent: 'cyan' as const,
    title: 'ACARS Datalink + Full-World Telemetry',
    subtitle:
      'Plane dossiers now surface Airframes ACARS datalink with summarizer support, and world telemetry caps are removed so dense regions render completely.',
    details: [
      'ACARS messages attach to aircraft profiles with optional LLM summarization for long datalink bursts.',
      'Telemetry truncation limits lifted — high-density air and surface tracks no longer silently drop contacts at the map edge.',
      'Incremental live-data deltas and map render tuning reduce flicker when feeds update at high frequency.',
    ],
    callToAction: 'MAP → AIRCRAFT → OPEN DOSSIER → ACARS TAB',
  },
];

const NEW_FEATURES = [
  {
    icon: <Languages size={18} className="text-purple-400" />,
    title: 'Persian (fa) Locale + RTL',
    desc: 'Full Persian translation pack with right-to-left layout across the dashboard (#472).',
  },
  {
    icon: <Layers size={18} className="text-cyan-400" />,
    title: 'Saved Dashboard Layout',
    desc: 'Layer toggles, filter panel, map style, and section expand/collapse persist in localStorage across refreshes.',
  },
  {
    icon: <Bot size={18} className="text-green-400" />,
    title: 'OpenClaw Agent Hardening',
    desc: 'Fetch-health endpoint (#470), Docker HMAC bootstrap, entity profile/trail, and agent-shell WebSocket token auth (#409).',
  },
  {
    icon: <Radio size={18} className="text-amber-400" />,
    title: 'SAR UI + Mesh Bootstrap',
    desc: 'SAR layer polish, mesh private outbox bootstrap, and live-data delta streaming for smoother map updates.',
  },
  {
    icon: <Network size={18} className="text-cyan-400" />,
    title: 'Infonet Tab Fix',
    desc: 'Infonet routing regression resolved (#404); README collapsible sections (#393) and contributor map docs (#435).',
  },
  {
    icon: <Shield size={18} className="text-green-400" />,
    title: 'Security & Stability',
    desc: 'Agent-shell WS tokens, GDELT thread safety (#388), and store/SIGINT snapshot hardening (#389).',
  },
];

const BUG_FIXES = [
  'GDELT mutation race under concurrent fetches (#388).',
  'Store/SIGINT snapshot consistency under load (#389).',
  'Spain DGT CCTV endpoint routing (#413).',
  'Python 3.13 feedparser compatibility for RSS ingestion.',
  'Layer preference hydration overwriting saved state on page load.',
  'Infonet tab routing regression (#404).',
];

type ChangelogContributor = {
  name: string;
  desc: string;
  pr?: string;
};

const CONTRIBUTORS: ChangelogContributor[] = [
  {
    name: 'esmaeelE',
    desc: 'Persian (fa) locale + RTL, README collapsible sections',
    pr: '#472, #393',
  },
  {
    name: 'nzinci',
    desc: 'Agent fetch health endpoint for OpenClaw monitoring',
    pr: '#470',
  },
  {
    name: 'Javier Andreo Zapata',
    desc: 'Spain DGT CCTV endpoint fix',
    pr: '#413',
  },
  {
    name: 'TheYellowBeanieGuy',
    desc: 'GDELT thread safety and store/SIGINT snapshot hardening',
    pr: '#388, #389',
  },
  {
    name: 'anntr1k3',
    desc: 'Contributor map and frontend README documentation',
    pr: '#435',
  },
];

export function useChangelog() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const seen = localStorage.getItem(STORAGE_KEY);
    if (!seen) setShow(true);
  }, []);
  return { showChangelog: show, setShowChangelog: setShow };
}

interface ChangelogModalProps {
  onClose: () => void;
}

const ChangelogModal = React.memo(function ChangelogModal({ onClose }: ChangelogModalProps) {
  const handleDismiss = () => {
    localStorage.setItem(STORAGE_KEY, 'true');
    onClose();
  };

  return (
    <AnimatePresence>
      <motion.div
        key="changelog-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[10000]"
        onClick={handleDismiss}
      />
      <motion.div
        key="changelog-modal"
        initial={{ opacity: 0, scale: 0.9, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.9, y: 20 }}
        transition={{ type: 'spring', damping: 25, stiffness: 300 }}
        className="fixed inset-0 z-[10001] flex items-center justify-center pointer-events-none"
      >
        <div
          className="w-[700px] max-h-[90vh] bg-[var(--bg-secondary)]/98 border border-cyan-900/50 pointer-events-auto flex flex-col overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="p-5 pb-3 border-b border-[var(--border-primary)]/80">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <div className="px-2.5 py-1 bg-cyan-500/15 border border-cyan-500/30 text-xs font-mono font-bold text-cyan-400 tracking-widest">
                    v{CURRENT_VERSION}
                  </div>
                  <h2 className="text-base font-bold tracking-[0.15em] text-[var(--text-primary)] font-mono">
                    WHAT&apos;S NEW
                  </h2>
                </div>
                <p className="text-[11px] text-cyan-500/70 font-mono tracking-widest mt-1">
                  {RELEASE_TITLE.toUpperCase()}
                </p>
              </div>
              <button
                type="button"
                aria-label="Close release notes"
                onClick={handleDismiss}
                className="w-8 h-8 border border-[var(--border-primary)] hover:border-red-500/50 flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 transition-all hover:bg-red-950/20"
              >
                <X size={14} />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto styled-scrollbar p-5 space-y-5">
            {HEADLINE_FEATURES.map((h, idx) => {
              const isPurple = h.accent === 'purple';
              const cardClass = isPurple
                ? 'border border-purple-500/30 bg-purple-950/20 p-4 space-y-3'
                : 'border border-cyan-500/30 bg-cyan-950/20 p-4 space-y-3';
              const iconWrapClass = isPurple
                ? 'w-9 h-9 border border-purple-500/40 bg-purple-500/10 flex items-center justify-center flex-shrink-0'
                : 'w-9 h-9 border border-cyan-500/40 bg-cyan-500/10 flex items-center justify-center flex-shrink-0';
              const titleClass = isPurple
                ? 'text-sm font-mono text-purple-300 font-bold tracking-wide'
                : 'text-sm font-mono text-cyan-300 font-bold tracking-wide';
              const subtitleClass = isPurple
                ? 'text-xs font-mono text-purple-500/80 mt-0.5'
                : 'text-xs font-mono text-cyan-500/80 mt-0.5';
              const ctaClass = isPurple
                ? 'text-[11px] font-mono text-purple-400 tracking-[0.25em] font-bold'
                : 'text-[11px] font-mono text-cyan-400 tracking-[0.25em] font-bold';

              return (
                <div key={idx} className={cardClass}>
                  <div className="flex items-center gap-3">
                    <div className={iconWrapClass}>{h.icon}</div>
                    <div>
                      <div className={titleClass}>{h.title}</div>
                      <div className={subtitleClass}>{h.subtitle}</div>
                    </div>
                  </div>

                  <div className="space-y-2">
                    {h.details.map((para, i) => (
                      <p
                        key={i}
                        className="text-xs font-mono text-[var(--text-secondary)] leading-relaxed"
                      >
                        {para}
                      </p>
                    ))}
                  </div>

                  <div className="text-center pt-1">
                    <span className={ctaClass}>{h.callToAction}</span>
                  </div>
                </div>
              );
            })}

            {/* Auto-update note for v0.9.83+ installs */}
            <div className="border border-green-500/30 bg-green-950/15 p-3 flex items-start gap-3">
              <KeyRound size={18} className="text-green-400 mt-0.5 flex-shrink-0" />
              <div className="space-y-1">
                <div className="text-xs font-mono text-green-300 font-bold tracking-wide uppercase">
                  One-click update from v0.9.83
                </div>
                <div className="text-xs font-mono text-green-200/80 leading-relaxed">
                  If you installed v0.9.83, the in-app Update button verifies this release via the
                  signed Tauri updater (`latest.json` + minisign). Desktop installs on v0.9.83 or
                  later should auto-apply v0.9.84 without a manual MSI hop once the release is
                  published.
                </div>
              </div>
            </div>

            {/* Other New Features */}
            <div>
              <div className="text-xs font-mono tracking-[0.2em] text-cyan-400 font-bold mb-3 flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
                NEW CAPABILITIES
              </div>
              <div className="space-y-2">
                {NEW_FEATURES.map((f) => (
                  <div
                    key={f.title}
                    className="flex items-start gap-3 p-3 border border-[var(--border-primary)]/50 bg-[var(--bg-primary)]/30 hover:border-[var(--border-secondary)] transition-colors"
                  >
                    <div className="mt-0.5 flex-shrink-0">{f.icon}</div>
                    <div>
                      <div className="text-[13px] font-mono text-[var(--text-primary)] font-bold">
                        {f.title}
                      </div>
                      <div className="text-xs font-mono text-[var(--text-muted)] leading-relaxed mt-0.5">
                        {f.desc}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Bug Fixes */}
            <div>
              <div className="text-xs font-mono tracking-[0.2em] text-green-400 font-bold mb-3 flex items-center gap-2">
                <Bug size={14} className="text-green-400" />
                FIXES &amp; IMPROVEMENTS
              </div>
              <div className="space-y-1.5">
                {BUG_FIXES.map((fix, i) => (
                  <div key={i} className="flex items-start gap-2 px-3 py-1.5">
                    <span className="text-green-500 text-xs mt-0.5 flex-shrink-0">+</span>
                    <span className="text-xs font-mono text-[var(--text-secondary)] leading-relaxed">
                      {fix}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Contributors */}
            <div>
              <div className="text-xs font-mono tracking-[0.2em] text-pink-400 font-bold mb-3 flex items-center gap-2">
                <Heart size={14} className="text-pink-400" />
                CREDITS &amp; CONTRIBUTORS
              </div>
              <div className="space-y-1.5">
                {CONTRIBUTORS.map((c, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 px-3 py-2 border border-pink-500/20 bg-pink-500/5"
                  >
                    <span className="text-pink-400 text-xs mt-0.5 flex-shrink-0">&hearts;</span>
                    <div>
                      <span className="text-[13px] font-mono text-pink-300 font-bold">
                        {c.name}
                      </span>
                      <span className="text-xs font-mono text-[var(--text-muted)]">
                        {' '}
                        &mdash; {c.desc}
                      </span>
                      {c.pr && (
                        <span className="text-[11px] font-mono text-[var(--text-muted)]">
                          {' '}
                          (PR {c.pr})
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="p-4 border-t border-[var(--border-primary)]/80 flex items-center justify-center">
            <button
              onClick={handleDismiss}
              className="px-8 py-2.5 bg-cyan-500/15 border border-cyan-500/40 text-cyan-400 hover:bg-cyan-500/25 text-xs font-mono tracking-[0.2em] transition-all"
            >
              ACKNOWLEDGED
            </button>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
});

export default ChangelogModal;
