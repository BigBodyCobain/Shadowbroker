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
  Lock,
  Users,
  Radio,
} from 'lucide-react';

const CURRENT_VERSION = '0.9.83';
const STORAGE_KEY = `shadowbroker_changelog_v${CURRENT_VERSION}`;
const RELEASE_TITLE = 'Infonet Gate Messaging + DM Protocols Live';

const HEADLINE_FEATURES = [
  {
    icon: <Lock size={20} className="text-purple-400" />,
    accent: 'purple' as const,
    title: 'Gate Messaging — End-to-End on the Hashchain',
    subtitle:
      'Encrypted MLS gate rooms now carry live chat over your private Infonet hashchain. Messages replicate across participant nodes via swarm push/pull — only gate members can decrypt.',
    details: [
      'Gate messages append as signed `gate_message` events on each participant\'s private chain; peers sync ciphertext through the mesh without exposing room keys to outsiders.',
      'Swarm replication keeps late joiners and offline nodes convergent — pull missing blocks, push new envelopes to known gate peers.',
      'MLS group crypto (privacy-core) handles forward secrecy and membership changes; the UI surfaces delivery, key rotation, and compat approval when room epochs advance.',
    ],
    callToAction: 'MESH CHAT → GATES → CREATE OR JOIN A ROOM',
  },
  {
    icon: <MessageSquare size={20} className="text-cyan-400" />,
    accent: 'cyan' as const,
    title: 'Direct Messages — Short Address, Request, Encrypt',
    subtitle:
      'DMs are fully operational over the wormhole/Tor lane: share your short wormhole address out-of-band, accept a contact request, then exchange ratchet-encrypted messages.',
    details: [
      'Contact flow: outbound request → peer approve/deny → mutual DM session with double-ratchet bundles and mailbox claim keys.',
      'No public phonebook — addresses are intentionally short and meant to be exchanged like a phone number or email, not discovered from a directory.',
      'Fleet-tested across multiple onion participants: request, accept, decrypt, and reply paths verified on live Tor hidden services.',
    ],
    callToAction: 'MESH CHAT → DIRECT → SHARE SHORT ADDRESS',
  },
  {
    icon: <Network size={20} className="text-amber-400" />,
    accent: 'cyan' as const,
    title: 'Infonet Transport Hardening',
    subtitle:
      'Tor/Arti warmup, SOCKS readiness, and terminal session lifecycle fixes so sovereign nodes actually join the mesh instead of sitting on NODE ARTI WARMING.',
    details: [
      'Tor hidden service config always exposes SOCKS; readiness probes cache and recover wedged transports instead of blocking wormhole sync indefinitely.',
      'Leaving the Infonet terminal now tears down wormhole prep, leaves the session, and stops Tor when the UI enabled it — no ghost connections after close.',
      'Network stats distinguish real transport warmup from stale sync backoff so operators see actionable status instead of a permanent warming spinner.',
    ],
    callToAction: 'TOP RIGHT → ENTER INFONET → CHECK NODE STATUS',
  },
];

const NEW_FEATURES = [
  {
    icon: <Users size={18} className="text-purple-400" />,
    title: 'Gate Swarm Replication',
    desc: 'Participant nodes push and pull gate hashchain segments so encrypted room history converges across the fleet without a central relay.',
  },
  {
    icon: <KeyRound size={18} className="text-cyan-400" />,
    title: 'DM Contact Requests',
    desc: 'Pending inbound/outbound access requests with approve, deny, and scoped per-node DM state — no cross-identity leakage in local storage.',
  },
  {
    icon: <Radio size={18} className="text-green-400" />,
    title: 'Wormhole Session Teardown',
    desc: 'Closing the Infonet terminal aborts in-flight wormhole prep, leaves the lane, and resets launcher busy state for clean re-entry.',
  },
  {
    icon: <Shield size={18} className="text-amber-400" />,
    title: 'Fail-Closed Tor Proof',
    desc: 'Onion sync waits for a working SOCKS handshake before declaring transport ready — prevents silent half-open mesh joins.',
  },
];

const BUG_FIXES = [
  'Arti/Tor transport no longer omits SocksPort when MESH_ARTI_ENABLED — SOCKS probes succeed and wormhole sync can start.',
  'Concurrent Arti readiness checks no longer wedge Tor under load; single-flight probes with auto-recycle when SOCKS stalls.',
  'Infonet terminal exit no longer leaves background wormhole prep or terminalLaunchBusy stuck after close.',
  'Stale onion sync backoff clears when transport recovers so NODE ARTI WARMING does not persist after Tor is healthy.',
  'DM decrypt timeouts on multi-participant fleets addressed via improved peer push timing and mailbox claim sequencing.',
];

type ChangelogContributor = {
  name: string;
  desc: string;
  pr?: string;
};

const CONTRIBUTORS: ChangelogContributor[] = [
  {
    name: 'privacy-core (MLS)',
    desc: 'Rust MLS gate crypto — WASM/FFI path for browser and Tauri sovereign shells',
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

            {/* Auto-update note for v0.9.82+ installs */}
            <div className="border border-green-500/30 bg-green-950/15 p-3 flex items-start gap-3">
              <KeyRound size={18} className="text-green-400 mt-0.5 flex-shrink-0" />
              <div className="space-y-1">
                <div className="text-xs font-mono text-green-300 font-bold tracking-wide uppercase">
                  One-click update from v0.9.82
                </div>
                <div className="text-xs font-mono text-green-200/80 leading-relaxed">
                  If you installed v0.9.82, the in-app Update button verifies this release via the
                  signed Tauri updater (`latest.json` + minisign). Desktop installs on v0.9.82 or
                  later should auto-apply v0.9.83 without a manual MSI hop once the release is
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
