'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  Terminal,
  Bot,
  Network,
  Scale,
  KeyRound,
  Cpu,
  Layers,
  GitBranch,
  Shield,
  Plane,
  Clock,
  Satellite,
  Bug,
  Heart,
} from 'lucide-react';

const CURRENT_VERSION = '0.9.7';
const STORAGE_KEY = `shadowbroker_changelog_v${CURRENT_VERSION}`;
const RELEASE_TITLE = 'Agentic AI Channel + InfoNet Decentralized Intelligence';

const HEADLINE_FEATURES = [
  {
    icon: <Bot size={20} className="text-purple-400" />,
    accent: 'purple' as const,
    title: 'Agentic AI Channel — supports OpenClaw and any HMAC-signing agent',
    subtitle: 'ShadowBroker now exposes a signed agent command channel. Bring your own agent (OpenClaw, Claude Code, GPT, LangChain, or a custom client) and drive the dashboard from any LLM that speaks the protocol.',
    details: [
      'A signed command channel (POST /api/ai/channel/command) plus a batched concurrent-execution endpoint (up to 20 tool calls per round-trip via /api/ai/channel/batch). Agents query flights, ships, SIGINT, news, and intel layers; reason over the live mesh; and run market or threat analyses without a human in the loop.',
      'HMAC-SHA256 request signing with timestamp + nonce replay protection. Tier-gated access (restricted vs full) governs which read and write commands the agent can invoke. Every call is auditable through the channel log.',
      'ShadowBroker does not bundle an LLM, an agent runtime, or model weights — it ships the protocol. Any agent that signs requests with the documented HMAC contract can connect. OpenClaw is the reference implementation.',
    ],
    callToAction: 'CONNECT YOUR AGENT \u2192 /API/AI/CHANNEL/COMMAND',
  },
  {
    icon: <Network size={20} className="text-cyan-400" />,
    accent: 'cyan' as const,
    title: 'InfoNet Testnet \u2014 Framework, Privacy, and a Path to Decentralized Intelligence',
    subtitle: 'The testnet now ships its full governance economy and the runway for a privacy-preserving decentralized intelligence platform.',
    details: [
      'Sovereign Shell views: petitions (governance DSL covers parameter updates and feature toggles), upgrade-hash voting (80% supermajority, 67% Heavy-Node activation), evidence submission, dispute markets, gate suspension and shutdown, and bootstrap eligible-node-one-vote. Every write action is a clickable form with verbatim diagnostics on rejection.',
      'Privacy primitive runway: locked Protocol contracts for ring signatures, stealth addresses, shielded balances, and DEX matching. The privacy-core Rust crate is the integration target. Function Keys (anonymous citizenship proof) ship 5 of 6 pieces; only blind-signature issuance waits on a primitive decision.',
      'Backbone: two-tier event state with epoch finality, identity rotation, progressive penalties, ramp milestones, and constitutional invariants enforced via MappingProxyType. Sprint 11+ wires the cryptographic primitives into the locked Protocols.',
      'Still an experimental testnet \u2014 no privacy guarantee yet. Treat all channels as public until E2E and the privacy primitives ship.',
    ],
    callToAction: 'OPEN SOVEREIGN SHELL \u2192 PETITIONS \u2022 UPGRADES \u2022 GATES',
  },
];

const NEW_FEATURES = [
  {
    icon: <Cpu size={18} className="text-purple-400" />,
    title: 'AI Batch Command Channel',
    desc: 'POST up to 20 tool calls in a single HTTP round-trip; the backend executes them concurrently and returns a fan-out result map. Cuts agent latency by an order of magnitude over sequential calls.',
  },
  {
    icon: <Scale size={18} className="text-amber-400" />,
    title: 'Governance DSL — Petition-Driven Parameter Changes',
    desc: 'Type-safe payload executor for UPDATE_PARAM, BATCH_UPDATE_PARAMS, ENABLE_FEATURE, and DISABLE_FEATURE petitions. Tunable knobs change on-chain via a vote — no code deploys required.',
  },
  {
    icon: <GitBranch size={18} className="text-purple-400" />,
    title: 'Upgrade-Hash Governance',
    desc: 'Protocol upgrades that need new logic (not just parameter changes) vote on a SHA-256 hash of the verified release. 80% supermajority, 40% quorum, 67% Heavy-Node activation. Lifecycle: signatures, voting, challenge window, awaiting readiness, activated.',
  },
  {
    icon: <KeyRound size={18} className="text-purple-400" />,
    title: 'Function Keys — Anonymous Citizenship Proof',
    desc: 'A citizen proves "I am an Infonet citizen" without revealing their Infonet identity. 5 of 6 pieces shipped: nullifiers, challenge-response, two-phase commit receipts, enumerated denial codes, batched settlement. Issuance via blind signatures waits on a primitive decision.',
  },
  {
    icon: <Shield size={18} className="text-cyan-400" />,
    title: 'Privacy Primitive Runway',
    desc: 'Locked Protocol contracts in services/infonet/privacy/contracts.py for ring signatures, stealth addresses, Pedersen commitments, range proofs, and DEX matching. The privacy-core Rust crate is the integration target — no caller of the privacy module needs to know which scheme is active.',
  },
  {
    icon: <Layers size={18} className="text-blue-400" />,
    title: 'Two-Tier State + Epoch Finality',
    desc: 'Tier 1 events propagate CRDT-style for low latency; Tier 2 events require epoch finality before they can be acted on. Identity rotation, progressive penalties, ramp milestones, and constitutional invariants are enforced via MappingProxyType.',
  },
  {
    icon: <Terminal size={18} className="text-cyan-400" />,
    title: 'Sovereign Shell Write Surface',
    desc: 'PetitionsView, UpgradeView, ResolutionView, GateShutdownView, BootstrapView, and FunctionKeyView each expose every Sprint 4-8 + 10 write action as a clickable form. Adaptive polling tightens to 8 seconds during active voting/challenge phases.',
  },
  {
    icon: <Clock size={18} className="text-pink-400" />,
    title: 'Time Machine — Snapshot Playback',
    desc: 'Scrub backward through saved telemetry. Live polling pauses on entry to snapshot mode, the map redraws from the recorded snapshot, and moving entities interpolate between recorded frames. Hourly index lets you jump to any captured timestamp; pressing Live restores the current feed instantly.',
  },
  {
    icon: <Satellite size={18} className="text-orange-400" />,
    title: 'SAR Satellite Telemetry — ASF, OPERA, Copernicus',
    desc: 'New SAR (Synthetic Aperture Radar) layer. Mode A (default-on) pulls free catalog metadata from the Alaska Satellite Facility — no account required. Mode B (two-step opt-in) ingests pre-processed ground-change anomalies from NASA OPERA, Copernicus EGMS, GFM, EMS, and UNOSAT — deformation, flood, and damage assessments. Integrates with OpenClaw so agents can read and act on SAR anomalies; broadcasts default to private-tier transport (Tor / RNS).',
  },
];

const BUG_FIXES = [
  'Sovereign Shell adaptive polling — voting and challenge windows refresh every 8 seconds while active, every 30 to 60 seconds when idle. Voting feels live without a websocket layer.',
  'Per-row write actions (petitions, upgrades, disputes) hold isolated submission state so concurrent forms no longer share a single in-flight slot.',
  'Verbatim diagnostic surfacing on every write button. The backend reason text is always shown on rejection — no opaque "denied" toasts.',
  'Evidence submission canonicalization matches Python repr() exactly, so client-side SHA-256 hashes round-trip cleanly through the chain.',
  'Function Keys copy is context-agnostic — citizenship proof is described abstractly, not tied to a specific use case.',
  'Post-cutover legacy mesh files (mesh_schema.py, mesh_signed_events.py, mesh_hashchain.py) hash-verified against the recorded baseline; the chain extension hook stays surgical.',
];

const CONTRIBUTORS = [
  {
    name: '@Alienmajik',
    desc: 'Raspberry Pi 5 support — ARM64 packaging, headless deployment notes, and runtime tuning for Pi-class hardware',
  },
  {
    name: '@wa1id',
    desc: 'CCTV ingestion fix — fresh SQLite connections per ingest, persistent DB path, startup hydration, cluster clickability',
    pr: '#92',
  },
  {
    name: '@AlborzNazari',
    desc: 'Spain DGT + Madrid CCTV sources and STIX 2.1 threat intelligence export endpoint',
    pr: '#91',
  },
  {
    name: '@adust09',
    desc: 'Power plants layer, East Asia intel coverage (JSDF bases, ICAO enrichment, Taiwan news sources, military classification)',
    pr: '#71, #72, #76, #77, #87',
  },
  {
    name: '@Xpirix',
    desc: 'LocateBar style and interaction improvements',
    pr: '#78',
  },
  {
    name: '@imqdcr',
    desc: 'Ship toggle split into 4 categories + stable MMSI/callsign entity IDs for map markers',
    pr: '#52',
  },
  {
    name: '@csysp',
    desc: 'Dismissible threat alerts + stable entity IDs for GDELT & News popups + UI declutter',
    pr: '#48, #61, #63',
  },
  {
    name: '@suranyami',
    desc: 'Parallel multi-arch Docker builds (11min \u2192 3min) + runtime BACKEND_URL fix',
    pr: '#35, #44',
  },
  {
    name: '@chr0n1x',
    desc: 'Kubernetes / Helm chart architecture for high-availability deployments',
  },
  {
    name: '@johan-martensson',
    desc: 'COSMO-SkyMed satellite classification fix + yfinance batch download optimization',
    pr: '#96, #98',
  },
  {
    name: '@singularfailure',
    desc: 'Spanish CCTV feeds + image loading fix',
    pr: '#93',
  },
  {
    name: '@smithbh',
    desc: 'Makefile-based taskrunner with LAN/local access options',
    pr: '#103',
  },
  {
    name: '@OrfeoTerkuci',
    desc: 'UV project management setup',
    pr: '#102',
  },
  {
    name: '@deuza',
    desc: 'dos2unix fix for Mac/Linux quick start',
    pr: '#101',
  },
  {
    name: '@tm-const',
    desc: 'CI/CD workflow updates',
    pr: '#108, #109',
  },
  {
    name: '@Elhard1',
    desc: 'start.sh shell script fix',
    pr: '#111',
  },
  {
    name: '@ttulttul',
    desc: 'Podman compose support + frontend production CSS fix',
    pr: '#23',
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
            {/* === HEADLINE PAIR: OpenClaw API + InfoNet === */}
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

                  {!isPurple && (
                    <div className="flex items-start gap-2 p-2.5 border border-red-500/30 bg-red-950/20">
                      <span className="text-red-400 text-xs mt-0.5 flex-shrink-0 font-bold">!!</span>
                      <div className="space-y-1.5">
                        <span className="text-[11px] font-mono text-red-400/90 leading-relaxed block font-bold">
                          EXPERIMENTAL TESTNET &mdash; NO PRIVACY GUARANTEE
                        </span>
                        <span className="text-[11px] font-mono text-amber-400/80 leading-relaxed block">
                          InfoNet messages are obfuscated but NOT encrypted end-to-end. The Mesh
                          network (Meshtastic/APRS) is NOT private &mdash; radio transmissions are
                          inherently public. The privacy primitive contracts are scaffolded but not
                          yet wired. Treat all channels as open and public for now.
                        </span>
                      </div>
                    </div>
                  )}

                  <div className="text-center pt-1">
                    <span className={ctaClass}>{h.callToAction}</span>
                  </div>
                </div>
              );
            })}

            {/* === Required-config callout: OpenSky API === */}
            <div className="border border-amber-500/40 bg-amber-950/20 p-3 flex items-start gap-3">
              <Plane size={18} className="text-amber-400 mt-0.5 flex-shrink-0" />
              <div className="space-y-1">
                <div className="text-xs font-mono text-amber-300 font-bold tracking-wide uppercase">
                  Required: OpenSky API credentials for airplane telemetry
                </div>
                <div className="text-xs font-mono text-amber-200/80 leading-relaxed">
                  Airplane telemetry now requires an OpenSky Network OAuth2 client. Set{' '}
                  <span className="text-amber-100 font-bold">OPENSKY_CLIENT_ID</span> and{' '}
                  <span className="text-amber-100 font-bold">OPENSKY_CLIENT_SECRET</span> in your{' '}
                  <span className="text-amber-100 font-bold">.env</span>. Free registration:{' '}
                  <a
                    href="https://opensky-network.org/index.php?option=com_users&view=registration"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-amber-100 font-bold underline underline-offset-2 hover:text-amber-50"
                  >
                    opensky-network.org/register
                  </a>
                  . Without these the flights layer falls back to ADS-B-only coverage with
                  significant gaps in Africa, Asia, and Latin America, and the startup environment
                  check will surface a critical warning.
                </div>
              </div>
            </div>

            {/* === Other New Features === */}
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
                COMMUNITY CONTRIBUTORS
              </div>
              <div className="space-y-1.5">
                {CONTRIBUTORS.map((c, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 px-3 py-2 border border-pink-500/20 bg-pink-500/5"
                  >
                    <span className="text-pink-400 text-xs mt-0.5 flex-shrink-0">
                      &hearts;
                    </span>
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
