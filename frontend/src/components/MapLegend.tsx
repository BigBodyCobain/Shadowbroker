'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ChevronDown, ChevronUp } from 'lucide-react';
import ExternalImage from '@/components/ExternalImage';

// ─── Inline SVG legend icons (small, crisp, no external deps) ───
const plane = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`;

const airliner = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="black"><path d="M12 2C11.2 2 10.5 2.8 10.5 3.5V8.5L3 13V15L10.5 12.5V18L8 19.5V21L12 19.5L16 21V19.5L13.5 18V12.5L21 15V13L13.5 8.5V3.5C13.5 2.8 12.8 2 12 2Z M5.5 13.5L3.5 14.5 M18.5 13.5L20.5 14.5"/><circle cx="7" cy="12.5" r="1.2" fill="${fill}" stroke="black" stroke-width="0.5"/><circle cx="17" cy="12.5" r="1.2" fill="${fill}" stroke="black" stroke-width="0.5"/></svg>`;

const turboprop = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="black"><path d="M12 3C11.3 3 10.8 3.5 10.8 4V9L3 12V13.5L10.8 11.5V18.5L9 19.5V21L12 20L15 21V19.5L13.2 18.5V11.5L21 13.5V12L13.2 9V4C13.2 3.5 12.7 3 12 3Z"/></svg>`;

const bizjet = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="black"><path d="M12 1.5C11.4 1.5 11 2 11 2.8V9L5 12.5V14L11 12V18.5L8.5 20V21.5L12 20.5L15.5 21.5V20L13 18.5V12L19 14V12.5L13 9V2.8C13 2 12.6 1.5 12 1.5Z"/></svg>`;

const heli = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="${fill}" stroke-dasharray="2 2" stroke-width="1"/></svg>`;

const ship = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none"><path d="M6 22 L6 6 L12 2 L18 6 L18 22 Z" fill="${fill}" stroke="#000" stroke-width="1"/></svg>`;

const triangle = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="#000" stroke-width="1"><path d="M1 21h22L12 2 1 21z"/></svg>`;

const circle = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="${fill}" stroke="#000" stroke-width="1"/></svg>`;

const dot = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5" fill="${fill}" stroke="#000" stroke-width="1"/></svg>`;

function IconImg({ svg }: { svg: string }) {
  return (
    <ExternalImage
      src={`data:image/svg+xml;utf8,${encodeURIComponent(svg)}`}
      alt=""
      width={16}
      height={16}
      className="w-4 h-4 flex-shrink-0"
      draggable={false}
    />
  );
}

// ─── Legend data ───

interface LegendItem {
  svg: string;
  label: string;
}

interface LegendCategory {
  name: string;
  color: string;
  items: LegendItem[];
}

const sat = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${fill}" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M4.93 4.93l2.83 2.83"/><path d="M16.24 16.24l2.83 2.83"/><path d="M4.93 19.07l2.83-2.83"/><path d="M16.24 7.76l2.83-2.83"/><circle cx="12" cy="12" r="8" fill="none" stroke="${fill}" stroke-dasharray="3 3" stroke-width="0.8"/></svg>`;

const square = (fill: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" fill="${fill}" stroke="#000" stroke-width="1" opacity="0.6" rx="2"/></svg>`;

const clusterCircle = (fill: string, stroke: string, size = 16) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="${fill}" stroke="${stroke}" stroke-width="2" opacity="0.8"/><text x="12" y="15" text-anchor="middle" fill="white" font-size="8" font-family="monospace" font-weight="bold">5</text></svg>`;

const LEGEND: LegendCategory[] = [
  {
    name: 'COMMERCIAL AVIATION',
    color: 'text-cyan-600 border-cyan-700/30',
    items: [
      { svg: airliner('#0891b2'), label: 'Airliner (dim cyan — baseline)' },
      { svg: turboprop('#0891b2'), label: 'Turboprop (dim cyan)' },
      { svg: heli('#0891b2'), label: 'Helicopter (dim cyan)' },
      { svg: airliner('#555'), label: 'Grounded / Parked (grey)' },
    ],
  },
  {
    name: 'PRIVATE / UNKNOWN AVIATION',
    color: 'text-purple-400 border-purple-500/30',
    items: [
      { svg: airliner('#9B59B6'), label: 'Private Flight — Airliner (purple)' },
      { svg: turboprop('#9B59B6'), label: 'Private Flight — Turboprop' },
      { svg: bizjet('#9B59B6'), label: 'Private Jet — Bizjet' },
      { svg: heli('#9B59B6'), label: 'Private / Unknown — Helicopter' },
    ],
  },
  {
    name: 'MILITARY AVIATION',
    color: 'text-amber-400 border-amber-500/30',
    items: [
      { svg: airliner('#f59e0b'), label: 'Military — Standard (amber)' },
      { svg: plane('#f59e0b'), label: 'Fighter / Interceptor (amber)' },
      { svg: heli('#f59e0b'), label: 'Military — Helicopter (amber)' },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="orange" stroke="black"><path d="M12 2L15 8H9L12 2Z" /><rect x="8" y="8" width="8" height="2" /><path d="M4 10L10 14H14L20 10V12L14 16H10L4 12V10Z" /><circle cx="12" cy="14" r="2" fill="red"/></svg>`,
        label: 'UAV / Drone (live ADS-B)',
      },
    ],
  },
  {
    name: 'TRACKED AIRCRAFT (ALERT)',
    color: 'text-pink-400 border-pink-500/30',
    items: [
      { svg: airliner('#FF1493'), label: 'VIP / Celebrity / Bizjet (hot pink)' },
      { svg: airliner('#FF2020'), label: 'Dictator / Oligarch (red)' },
      { svg: airliner('#3b82f6'), label: 'Government / Police / Customs (blue)' },
      { svg: heli('#32CD32'), label: 'Medical / Fire / Rescue (lime)' },
      { svg: airliner('yellow'), label: 'Military / Intelligence (yellow)' },
      { svg: airliner('#222'), label: 'PIA — Privacy / Stealth (black)' },
      { svg: airliner('#FF8C00'), label: 'Private Flights / Joe Cool (orange)' },
      { svg: airliner('white'), label: 'Climate Crisis (white)' },
      { svg: airliner('#9B59B6'), label: 'Private Jets / Historic / Other (purple)' },
    ],
  },
  {
    name: 'POTUS FLEET',
    color: 'text-yellow-400 border-yellow-500/30',
    items: [
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="none" stroke="gold" stroke-width="2" stroke-dasharray="4 2"/><g transform="translate(6,6)"><path d="M12 2C11.2 2 10.5 2.8 10.5 3.5V8.5L3 13V15L10.5 12.5V18L8 19.5V21L12 19.5L16 21V19.5L13.5 18V12.5L21 15V13L13.5 8.5V3.5C13.5 2.8 12.8 2 12 2Z" fill="#FF1493" stroke="black" stroke-width="0.5"/></g></svg>`,
        label: 'Air Force One / Two (gold ring)',
      },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="none" stroke="gold" stroke-width="2" stroke-dasharray="4 2"/><g transform="translate(8,6)"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z" fill="#FF1493" stroke="black" stroke-width="0.5"/></g></svg>`,
        label: 'Marine One (gold ring + heli)',
      },
    ],
  },
  {
    name: 'SATELLITES',
    color: 'text-sky-400 border-sky-500/30',
    items: [
      { svg: sat('#ff3333'), label: 'Military Recon / SAR (red)' },
      { svg: sat('#00e5ff'), label: 'Synthetic Aperture Radar (cyan)' },
      { svg: sat('#ffffff'), label: 'Signals Intelligence / ELINT (white)' },
      { svg: sat('#4488ff'), label: 'Navigation — GPS / GLONASS / BeiDou (blue)' },
      { svg: sat('#ff00ff'), label: 'Early Warning — Missile Detection (magenta)' },
      { svg: sat('#44ff44'), label: 'Commercial Imaging (green)' },
      { svg: sat('#ffdd00'), label: 'Space Station — ISS / Tiangong (gold)' },
      { svg: sat('#aaaaaa'), label: 'Unclassified / Other (grey)' },
    ],
  },
  {
    name: 'MARITIME',
    color: 'text-blue-400 border-blue-500/30',
    items: [
      { svg: ship('#ff2222'), label: 'Cargo / Tanker (red)' },
      { svg: ship('#f59e0b'), label: 'Military Vessel (amber)' },
      { svg: ship('white'), label: 'Cruise / Passenger / Yacht (white)' },
      { svg: ship('#FF69B4'), label: 'Tracked Yacht (pink)' },
      { svg: ship('#3b82f6'), label: 'Civilian / Unknown (blue)' },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="orange" stroke="black"><polygon points="3,21 21,21 20,4 16,4 16,3 12,3 12,4 4,4" /><rect x="15" y="6" width="3" height="10" /></svg>`,
        label: 'Aircraft Carrier (orange)',
      },
      { svg: clusterCircle('#3b82f6', '#1d4ed8'), label: 'Ship Cluster (count inside)' },
    ],
  },
  {
    name: 'GEOPHYSICAL',
    color: 'text-orange-400 border-orange-500/30',
    items: [{ svg: circle('#ffcc00'), label: 'Earthquake (yellow blob, size = magnitude)' }],
  },
  {
    name: 'WILDFIRES',
    color: 'text-red-400 border-red-500/30',
    items: [
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><path d="M12 1C8 7 5 10 5 14a7 7 0 0 0 14 0c0-4-3-7-7-13z" fill="#ff6600" stroke="#ffcc00" stroke-width="1"/></svg>`,
        label: 'Active wildfire / hotspot',
      },
      { svg: clusterCircle('#cc0000', '#ff3300'), label: 'Fire cluster (grouped hotspots)' },
    ],
  },
  {
    name: 'INCIDENTS & INTELLIGENCE',
    color: 'text-red-400 border-red-500/30',
    items: [
      { svg: triangle('#ffaa00'), label: 'GDELT / LiveUA event (yellow)' },
      { svg: triangle('#ff0000'), label: 'Violent / Kinetic event (red)' },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#ffff00" stroke="#ff0000" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>`,
        label: 'Threat Alert (news cluster)',
      },
    ],
  },
  {
    name: 'NEWS & OSINT',
    color: 'text-cyan-400 border-cyan-500/30',
    items: [
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="12" viewBox="0 0 40 24"><rect x="1" y="1" width="38" height="22" rx="3" fill="#111" stroke="cyan" stroke-width="1"/><text x="6" y="10" fill="red" font-size="6" font-family="monospace">!! ALERT</text><text x="6" y="17" fill="white" font-size="4" font-family="monospace">News Headline</text></svg>`,
        label: 'Geolocated news alert box',
      },
    ],
  },
  {
    name: 'GPS JAMMING / INTERFERENCE',
    color: 'text-red-400 border-red-500/30',
    items: [
      { svg: square('#ff0040'), label: 'High severity (>75% aircraft degraded)' },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" fill="#ff0040" stroke="#000" stroke-width="1" opacity="0.35" rx="2"/></svg>`,
        label: 'Medium severity (50-75% degraded)',
      },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" fill="#ff0040" stroke="#000" stroke-width="1" opacity="0.2" rx="2"/></svg>`,
        label: 'Low severity (25-50% degraded)',
      },
    ],
  },
  {
    name: 'INFRASTRUCTURE',
    color: 'text-purple-400 border-purple-500/30',
    items: [
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="1.5"><rect x="3" y="3" width="18" height="6" rx="1" fill="#2e1065"/><rect x="3" y="11" width="18" height="6" rx="1" fill="#2e1065"/><circle cx="7" cy="6" r="1" fill="#a78bfa"/><circle cx="7" cy="14" r="1" fill="#a78bfa"/></svg>`,
        label: 'Data Center',
      },
      { svg: circle('#888'), label: 'Internet Outage Zone (grey)' },
    ],
  },
  {
    name: 'SURVEILLANCE / CCTV',
    color: 'text-green-400 border-green-500/30',
    items: [
      { svg: dot('#22c55e'), label: 'Individual CCTV camera (green dot)' },
      { svg: clusterCircle('#22c55e', '#16a34a'), label: 'Camera cluster (count inside)' },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="cyan" stroke-width="2"><path d="M16.75 12h3.632a1 1 0 0 1 .894 1.447l-2.034 4.069a1 1 0 0 1-.894.553H5.652a1 1 0 0 1-.894-.553L2.724 13.447A1 1 0 0 1 3.618 12h3.632M14 12V8a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v4a4 4 0 1 0 8 0Z" /></svg>`,
        label: 'CCTV icon (detail view)',
      },
    ],
  },
  {
    name: 'SELECTION HUD',
    color: 'text-cyan-400 border-cyan-500/30',
    items: [
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><line x1="4" y1="12" x2="20" y2="12" stroke="#22d3ee" stroke-width="2" stroke-dasharray="3 3" opacity="0.5"/><circle cx="20" cy="12" r="2.5" fill="#22d3ee" opacity="0.4"/></svg>`,
        label: 'Predictive vector (~5 min ahead)',
      },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" stroke="#22d3ee" stroke-width="1" stroke-dasharray="4 3" opacity="0.2"/><circle cx="12" cy="12" r="5" fill="none" stroke="#22d3ee" stroke-width="1" stroke-dasharray="4 3" opacity="0.2"/></svg>`,
        label: 'Proximity rings (10 / 50 / 100nm)',
      },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><line x1="4" y1="12" x2="20" y2="12" stroke="#22d3ee" stroke-width="2" opacity="0.6"/></svg>`,
        label: 'Flight trail (position history)',
      },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><line x1="4" y1="12" x2="20" y2="12" stroke="cyan" stroke-width="2" opacity="0.8"/><circle cx="4" cy="12" r="2" fill="lime"/><circle cx="20" cy="12" r="2" fill="red"/></svg>`,
        label: 'Active route (origin → dest)',
      },
    ],
  },
  {
    name: 'SIGINT GRID',
    color: 'text-emerald-400 border-emerald-500/30',
    items: [
      { svg: dot('#22c55e'), label: 'APRS-IS station (green, isnād 0.7)' },
      { svg: triangle('#22c55e'), label: 'Meshtastic node (green triangle, isnād 0.5)' },
      { svg: dot('#f59e0b'), label: 'JS8Call station (amber, isnād 0.9)' },
    ],
  },
  {
    name: 'ORACLE SERVICE',
    color: 'text-cyan-400 border-cyan-500/30',
    items: [
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="12" viewBox="0 0 40 16"><rect x="1" y="1" width="38" height="14" rx="2" fill="#111" stroke="#22d3ee" stroke-width="1"/><text x="4" y="10" fill="#22d3ee" font-size="7" font-family="monospace" font-weight="bold">ORCL:7.2</text></svg>`,
        label: 'Oracle score badge (weighted risk)',
      },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="12" viewBox="0 0 40 16"><rect x="1" y="1" width="38" height="14" rx="2" fill="#111" stroke="#a855f7" stroke-width="1"/><text x="4" y="10" fill="#a855f7" font-size="7" font-family="monospace" font-weight="bold">MKT:23%</text></svg>`,
        label: 'Prediction market consensus',
      },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><text x="6" y="16" fill="#22c55e" font-size="14" font-family="monospace" font-weight="bold">▲</text></svg>`,
        label: 'Sentiment: ▲ positive / ▼ negative / — neutral',
      },
    ],
  },
  {
    name: 'OVERLAYS',
    color: 'text-gray-400 border-gray-500/30',
    items: [
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><rect width="24" height="24" fill="#0a0e1a" opacity="0.4"/><circle cx="12" cy="12" r="4" fill="#ffd700"/></svg>`,
        label: 'Day / Night terminator',
      },
      {
        svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><line x1="4" y1="4" x2="20" y2="4" stroke="red" stroke-width="2"/><line x1="4" y1="8" x2="20" y2="8" stroke="#ff6600" stroke-width="2"/></svg>`,
        label: 'Ukraine frontline',
      },
    ],
  },
];

const MapLegend = React.memo(function MapLegend({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggle = (name: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/70 backdrop-blur-sm z-[9998]"
            onClick={onClose}
          />

          {/* Legend Panel */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[520px] max-h-[80vh] bg-[var(--bg-secondary)]/95 backdrop-blur-sm border border-cyan-900/50 z-[9999] flex flex-col shadow-[0_0_60px_rgba(0,0,0,0.3)]"
          >
            {/* Header */}
            <div className="flex items-center justify-between p-5 border-b border-[var(--border-primary)]/80 flex-shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center">
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="cyan"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                    <path d="M12 3v12" />
                    <path d="m8 11 4 4 4-4" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-sm font-bold tracking-[0.2em] text-[var(--text-primary)] font-mono">
                    MAP LEGEND
                  </h2>
                  <span className="text-[9px] text-[var(--text-muted)] font-mono tracking-widest">
                    ICON REFERENCE KEY
                  </span>
                </div>
              </div>
              <button
                onClick={onClose}
                className="w-8 h-8 border border-[var(--border-primary)] hover:border-red-500/50 flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 transition-all hover:bg-red-950/20"
              >
                <X size={14} />
              </button>
            </div>

            {/* Legend Content */}
            <div className="flex-1 overflow-y-auto styled-scrollbar p-4 space-y-2">
              {LEGEND.map((cat) => {
                const isCollapsed = collapsed.has(cat.name);
                return (
                  <div
                    key={cat.name}
                    className="border border-[var(--border-primary)]/60 overflow-hidden"
                  >
                    {/* Category Header */}
                    <button
                      onClick={() => toggle(cat.name)}
                      className="w-full flex items-center justify-between px-3 py-2 bg-[var(--bg-secondary)]/50 hover:bg-[var(--bg-secondary)]/80 transition-colors"
                    >
                      <span
                        className={`text-[9px] font-mono tracking-widest font-bold px-2 py-0.5 border ${cat.color}`}
                      >
                        {cat.name}
                      </span>
                      {isCollapsed ? (
                        <ChevronDown size={12} className="text-[var(--text-muted)]" />
                      ) : (
                        <ChevronUp size={12} className="text-[var(--text-muted)]" />
                      )}
                    </button>

                    {/* Items */}
                    <AnimatePresence>
                      {!isCollapsed && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.15 }}
                          className="border-t border-[var(--border-primary)]/40"
                        >
                          <div className="grid grid-cols-1 gap-0">
                            {cat.items.map((item, idx) => (
                              <div
                                key={idx}
                                className="flex items-center gap-3 px-4 py-1.5 hover:bg-[var(--bg-secondary)]/30 transition-colors"
                              >
                                <IconImg svg={item.svg} />
                                <span className="text-[11px] text-[var(--text-secondary)] font-mono">
                                  {item.label}
                                </span>
                              </div>
                            ))}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                );
              })}
            </div>

            {/* Footer */}
            <div className="p-3 border-t border-[var(--border-primary)]/80 flex-shrink-0">
              <div className="text-[9px] text-[var(--text-muted)] font-mono text-center tracking-wider">
                {LEGEND.reduce((sum, c) => sum + c.items.length, 0)} ICON DEFINITIONS ACROSS{' '}
                {LEGEND.length} CATEGORIES
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
});

export default MapLegend;
