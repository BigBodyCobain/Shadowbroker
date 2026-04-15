'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  Terminal,
  Radio,
  Camera,
  Search,
  TrainFront,
  Globe,
  Shield,
  Bug,
  Heart,
} from 'lucide-react';

const CURRENT_VERSION = '0.9.6';
const STORAGE_KEY = `shadowbroker_changelog_v${CURRENT_VERSION}`;
const RELEASE_TITLE = 'InfoNet Experimental Testnet — Decentralized Intelligence Experiment';

const HEADLINE_FEATURE = {
  icon: <Terminal size={20} className="text-cyan-400" />,
  title: 'InfoNet Experimental Testnet is Live',
  subtitle: 'The first decentralized intelligence mesh built directly into an OSINT platform. This is an experimental testnet — NOT a privacy tool.',
  details: [
    'A global, obfuscated message relay running inside ShadowBroker. Anyone with the dashboard can transmit and receive on the InfoNet — no accounts, no signup, no identity required.',
    'Messages pass through a Wormhole relay layer with gate personas, canonical payload signing, and message obfuscation. Transport is obfuscated to a degree, but this is NOT private communication. Do not transmit anything you would not say in public. End-to-end encryption is being developed but is not yet implemented.',
    'Dead Drop inbox for peer-to-peer message exchange. Mesh Terminal CLI for power users. Gate persona system for pseudonymous identity. Double-ratchet DM scaffolding in progress.',
    'Nothing like this has existed in an OSINT tool before. This is an open experiment — jump on the testnet, explore the protocol, and help shape what decentralized intelligence looks like.',
  ],
  callToAction: 'OPEN MESH CHAT \u2192 MESH TAB \u2192 START TRANSMITTING',
};

const NEW_FEATURES = [
  {
    icon: <Radio size={18} className="text-amber-400" />,
    title: 'Meshtastic + APRS Radio Integration',
    desc: 'Live Meshtastic mesh radio nodes plotted worldwide via MQTT. APRS amateur radio positioning via APRS-IS TCP feed. Both integrated into Mesh Chat and the SIGINT grid. Note: Mesh radio is NOT private — RF transmissions are public by nature.',
    color: 'amber',
  },
  {
    icon: <Terminal size={18} className="text-cyan-400" />,
    title: 'Mesh Terminal',
    desc: 'Built-in command-line interface. Send messages, DMs, run market commands, inspect gate state. Draggable panel, minimizes to the top bar. Type "help" to see everything.',
    color: 'cyan',
  },
  {
    icon: <Search size={18} className="text-green-400" />,
    title: 'Shodan Device Search',
    desc: 'Query Shodan directly from ShadowBroker. Search internet-connected devices by keyword, CVE, or port — results plotted as a live overlay on the map with configurable marker style.',
    color: 'green',
  },
  {
    icon: <Camera size={18} className="text-emerald-400" />,
    title: 'CCTV Mesh Expanded — 12 Sources, 11,000+ Cameras',
    desc: 'Massive expansion: added Spain (DGT national + Madrid city), California (12 Caltrans districts), Washington State, Georgia, Illinois, Michigan, and Windy Webcams. Now covers 6 countries. Enabled by default.',
    color: 'emerald',
  },
  {
    icon: <TrainFront size={18} className="text-blue-400" />,
    title: 'Train Tracking (Amtrak + European Rail)',
    desc: 'Real-time Amtrak train positions across the US and European rail via DigiTraffic. Speed, heading, route, and status for every train on the network.',
    color: 'blue',
  },
  {
    icon: <Globe size={18} className="text-purple-400" />,
    title: '8 New Intelligence Layers',
    desc: 'Volcanoes (Smithsonian), air quality PM2.5 (OpenAQ), severe weather alerts, fishing activity (Global Fishing Watch), military bases, 35K+ power plants, SatNOGS ground stations, TinyGS LoRa satellites, VIIRS nightlights.',
    color: 'purple',
  },
  {
    icon: <Shield size={18} className="text-yellow-400" />,
    title: 'Sentinel Hub Imagery + Desktop Shell Scaffold',
    desc: 'Copernicus CDSE satellite imagery via Sentinel Hub Process API with OAuth2 token flow. Desktop-native control routing scaffold (pre-Tauri) with session profiles and audit trail.',
    color: 'yellow',
  },
];

const BUG_FIXES = [
  'CCTV auto-seed fix — partial DB (4 of 12 sources) no longer silently skips the other 8 ingestors on startup',
  'SQLite threading fix — CCTV ingestors no longer share connections across threads',
  'CCTV layer now ON by default and participates in the All On/Off global toggle',
  'KiwiSDR, FIRMS fires, internet outages, data centers all switched to ON by default',
  'Terminal minimized tab repositioned to top-center with proper icon (no more phantom cursor)',
  'Mesh Chat defaults to MESH tab on startup instead of locked INFONET gate',
];

const CONTRIBUTORS = [
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
            {/* === HEADLINE: InfoNet Testnet === */}
            <div className="border border-cyan-500/30 bg-cyan-950/20 p-4 space-y-3">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 border border-cyan-500/40 bg-cyan-500/10 flex items-center justify-center flex-shrink-0">
                  {HEADLINE_FEATURE.icon}
                </div>
                <div>
                  <div className="text-sm font-mono text-cyan-300 font-bold tracking-wide">
                    {HEADLINE_FEATURE.title}
                  </div>
                  <div className="text-xs font-mono text-cyan-500/80 mt-0.5">
                    {HEADLINE_FEATURE.subtitle}
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                {HEADLINE_FEATURE.details.map((para, i) => (
                  <p
                    key={i}
                    className="text-xs font-mono text-[var(--text-secondary)] leading-relaxed"
                  >
                    {para}
                  </p>
                ))}
              </div>

              {/* Testnet disclaimer */}
              <div className="flex items-start gap-2 p-2.5 border border-red-500/30 bg-red-950/20">
                <span className="text-red-400 text-xs mt-0.5 flex-shrink-0 font-bold">!!</span>
                <div className="space-y-1.5">
                  <span className="text-[11px] font-mono text-red-400/90 leading-relaxed block font-bold">
                    EXPERIMENTAL TESTNET — NO PRIVACY GUARANTEE
                  </span>
                  <span className="text-[11px] font-mono text-amber-400/80 leading-relaxed block">
                    InfoNet messages are obfuscated but NOT encrypted end-to-end. The Mesh network
                    (Meshtastic/APRS) is NOT private &mdash; radio transmissions are inherently
                    public. Do not send anything sensitive on any channel. Privacy and E2E encryption
                    are actively being developed. Treat all channels as open and public for now.
                  </span>
                </div>
              </div>

              {/* CTA */}
              <div className="text-center pt-1">
                <span className="text-[11px] font-mono text-cyan-400 tracking-[0.25em] font-bold">
                  {HEADLINE_FEATURE.callToAction}
                </span>
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
