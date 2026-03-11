"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Plane, AlertTriangle, Activity, Satellite, Cctv, ChevronDown, ChevronUp, Ship, Eye, Anchor, Settings, Sun, Moon, BookOpen, Radio, Play, Pause, Globe, Flame, Wifi, Server, Shield } from "lucide-react";
import { useTheme } from "@/lib/ThemeContext";

function relativeTime(iso: string | undefined): string {
    if (!iso) return "";
    const diff = Date.now() - new Date(iso + "Z").getTime();
    if (diff < 0) return "now";
    const sec = Math.floor(diff / 1000);
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    return `${Math.floor(hr / 24)}d ago`;
}

// Map layer IDs to freshness keys from the backend source_timestamps dict
const FRESHNESS_MAP: Record<string, string> = {
    flights: "commercial_flights",
    private: "private_flights",
    jets: "private_jets",
    military: "military_flights",
    tracked: "military_flights",
    earthquakes: "earthquakes",
    satellites: "satellites",
    ships_important: "ships",
    ships_civilian: "ships",
    ships_passenger: "ships",
    ukraine_frontline: "frontlines",
    global_incidents: "gdelt",
    cctv: "cctv",
    gps_jamming: "commercial_flights",
    kiwisdr: "kiwisdr",
    firms: "firms_fires",
    internet_outages: "internet_outages",
    datacenters: "datacenters",
};

// POTUS fleet ICAO hex codes for client-side filtering
const POTUS_ICAOS: Record<string, { label: string; type: string }> = {
    'ADFDF8': { label: 'Air Force One (82-8000)', type: 'AF1' },
    'ADFDF9': { label: 'Air Force One (92-9000)', type: 'AF1' },
    'ADFEB7': { label: 'Air Force Two (98-0001)', type: 'AF2' },
    'ADFEB8': { label: 'Air Force Two (98-0002)', type: 'AF2' },
    'ADFEB9': { label: 'Air Force Two (99-0003)', type: 'AF2' },
    'ADFEBA': { label: 'Air Force Two (99-0004)', type: 'AF2' },
    'AE4AE6': { label: 'Air Force Two (09-0015)', type: 'AF2' },
    'AE4AE8': { label: 'Air Force Two (09-0016)', type: 'AF2' },
    'AE4AEA': { label: 'Air Force Two (09-0017)', type: 'AF2' },
    'AE4AEC': { label: 'Air Force Two (19-0018)', type: 'AF2' },
    'AE0865': { label: 'Marine One (VH-3D)', type: 'M1' },
    'AE5E76': { label: 'Marine One (VH-92A)', type: 'M1' },
    'AE5E77': { label: 'Marine One (VH-92A)', type: 'M1' },
    'AE5E79': { label: 'Marine One (VH-92A)', type: 'M1' },
};

const WorldviewLeftPanel = React.memo(function WorldviewLeftPanel({ data, activeLayers, setActiveLayers, onSettingsClick, onLegendClick, gibsDate, setGibsDate, gibsOpacity, setGibsOpacity, onEntityClick, onFlyTo }: { data: any; activeLayers: any; setActiveLayers: any; onSettingsClick?: () => void; onLegendClick?: () => void; gibsDate?: string; setGibsDate?: (d: string) => void; gibsOpacity?: number; setGibsOpacity?: (o: number) => void; onEntityClick?: (entity: { type: string; id: number; extra?: any }) => void; onFlyTo?: (lat: number, lng: number) => void }) {
    const [isMinimized, setIsMinimized] = useState(false);
    const { theme, toggleTheme } = useTheme();
    const [gibsPlaying, setGibsPlaying] = useState(false);
    const gibsIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // GIBS time slider play/pause animation
    useEffect(() => {
        if (!gibsPlaying || !setGibsDate) {
            if (gibsIntervalRef.current) clearInterval(gibsIntervalRef.current);
            gibsIntervalRef.current = null;
            return;
        }
        gibsIntervalRef.current = setInterval(() => {
            if (!gibsDate) return;
            const d = new Date(gibsDate + 'T00:00:00');
            d.setDate(d.getDate() + 1);
            const yesterday = new Date();
            yesterday.setDate(yesterday.getDate() - 1);
            if (d > yesterday) {
                const start = new Date();
                start.setDate(start.getDate() - 30);
                setGibsDate(start.toISOString().slice(0, 10));
            } else {
                setGibsDate(d.toISOString().slice(0, 10));
            }
        }, 1500);
        return () => { if (gibsIntervalRef.current) clearInterval(gibsIntervalRef.current); };
    }, [gibsPlaying, gibsDate, setGibsDate]);

    // Compute ship category counts (memoized — ships array can be 1000+ items)
    const { importantShipCount, passengerShipCount, civilianShipCount } = useMemo(() => {
        const ships = data?.ships;
        if (!ships || !ships.length) return { importantShipCount: 0, passengerShipCount: 0, civilianShipCount: 0 };
        let important = 0, passenger = 0, civilian = 0;
        for (const s of ships) {
            const t = s.type;
            if (t === 'carrier' || t === 'military_vessel' || t === 'tanker' || t === 'cargo') important++;
            else if (t === 'passenger') passenger++;
            else civilian++;
        }
        return { importantShipCount: important, passengerShipCount: passenger, civilianShipCount: civilian };
    }, [data?.ships]);

    // Find POTUS fleet planes currently airborne from tracked flights
    const potusFlights = useMemo(() => {
        const tracked = data?.tracked_flights;
        if (!tracked) return [];
        const results: { index: number; flight: any; meta: { label: string; type: string } }[] = [];
        for (let i = 0; i < tracked.length; i++) {
            const f = tracked[i];
            const icao = (f.icao24 || '').toUpperCase();
            if (POTUS_ICAOS[icao]) {
                results.push({ index: i, flight: f, meta: POTUS_ICAOS[icao] });
            }
        }
        return results;
    }, [data?.tracked_flights]);

    const layers = [
        { id: "flights", name: "Commercial Flights", source: "adsb.lol", count: data?.commercial_flights?.length || 0, icon: Plane },
        { id: "private", name: "Private Flights", source: "adsb.lol", count: data?.private_flights?.length || 0, icon: Plane },
        { id: "jets", name: "Private Jets", source: "adsb.lol", count: data?.private_jets?.length || 0, icon: Plane },
        { id: "military", name: "Military Flights", source: "adsb.lol", count: data?.military_flights?.length || 0, icon: AlertTriangle },
        { id: "tracked", name: "Tracked Aircraft", source: "Plane-Alert DB", count: data?.tracked_flights?.length || 0, icon: Eye },
        { id: "earthquakes", name: "Earthquakes (24h)", source: "USGS", count: data?.earthquakes?.length || 0, icon: Activity },
        { id: "satellites", name: "Satellites", source: "CelesTrak SGP4", count: data?.satellites?.length || 0, icon: Satellite },
        { id: "ships_important", name: "Carriers / Mil / Cargo", source: "AIS Stream", count: importantShipCount, icon: Ship },
        { id: "ships_civilian", name: "Civilian Vessels", source: "AIS Stream", count: civilianShipCount, icon: Anchor },
        { id: "ships_passenger", name: "Cruise / Passenger", source: "AIS Stream", count: passengerShipCount, icon: Anchor },
        { id: "ukraine_frontline", name: "Ukraine Frontline", source: "DeepStateMap", count: data?.frontlines ? 1 : 0, icon: AlertTriangle },
        { id: "global_incidents", name: "Global Incidents", source: "GDELT", count: data?.gdelt?.length || 0, icon: Activity },
        { id: "cctv", name: "CCTV Mesh", source: "CCTV Mesh + Street View", count: data?.cctv?.length || 0, icon: Cctv },
        { id: "gps_jamming", name: "GPS Jamming", source: "ADS-B NACp", count: data?.gps_jamming?.length || 0, icon: Radio },
        { id: "gibs_imagery", name: "MODIS Terra (Daily)", source: "NASA GIBS", count: null, icon: Globe },
        { id: "highres_satellite", name: "High-Res Satellite", source: "Esri World Imagery", count: null, icon: Satellite },
        { id: "kiwisdr", name: "KiwiSDR Receivers", source: "KiwiSDR.com", count: data?.kiwisdr?.length || 0, icon: Radio },
        { id: "firms", name: "Fire Hotspots (24h)", source: "NASA FIRMS VIIRS", count: data?.firms_fires?.length || 0, icon: Flame },
        { id: "internet_outages", name: "Internet Outages", source: "IODA / Georgia Tech", count: data?.internet_outages?.length || 0, icon: Wifi },
        { id: "datacenters", name: "Data Centers", source: "DC Map (GitHub)", count: data?.datacenters?.length || 0, icon: Server },
        { id: "day_night", name: "Day / Night Cycle", source: "Solar Calc", count: null, icon: Sun },
    ];

    const shipIcon = <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2 21c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1 .6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1" /><path d="M19.38 20A11.6 11.6 0 0 0 21 14l-9-4-9 4c0 2.9.94 5.34 2.81 7.76" /><path d="M19 13V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6" /></svg>;

    return (
        <motion.div
            initial={{ opacity: 0, x: -50 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 1 }}
            className="w-full flex-1 min-h-0 flex flex-col pointer-events-none"
        >
            {/* Header */}
            <div className="mb-6 pointer-events-auto">
                <div className="text-[10px] text-[var(--text-secondary)] font-mono tracking-widest mb-1">TOP SECRET // SI-TK // NOFORN</div>
                <div className="text-[10px] text-[var(--text-muted)] font-mono tracking-widest mb-4">KH11-4094 OPS-4168</div>
                <div className="flex items-center gap-3">
                    <h1 className="text-2xl font-bold tracking-[0.2em] text-[var(--text-heading)]">FLIR</h1>
                    <button
                        onClick={toggleTheme}
                        className="w-7 h-7 rounded-lg border border-[var(--border-primary)] hover:border-cyan-500/50 flex items-center justify-center text-[var(--text-muted)] hover:text-cyan-400 transition-all hover:bg-[var(--hover-accent)]"
                        title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
                    >
                        {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
                    </button>
                    {onSettingsClick && (
                        <button
                            onClick={onSettingsClick}
                            className="w-7 h-7 rounded-lg border border-[var(--border-primary)] hover:border-cyan-500/50 flex items-center justify-center text-[var(--text-muted)] hover:text-cyan-400 transition-all hover:bg-[var(--hover-accent)] group"
                            title="System Settings"
                        >
                            <Settings size={14} className="group-hover:rotate-90 transition-transform duration-300" />
                        </button>
                    )}
                    {onLegendClick && (
                        <button
                            onClick={onLegendClick}
                            className="h-7 px-2 rounded-lg border border-[var(--border-primary)] hover:border-cyan-500/50 flex items-center justify-center gap-1 text-[var(--text-muted)] hover:text-cyan-400 transition-all hover:bg-[var(--hover-accent)]"
                            title="Map Legend / Icon Key"
                        >
                            <BookOpen size={12} />
                            <span className="text-[8px] font-mono tracking-widest font-bold">KEY</span>
                        </button>
                    )}
                </div>
            </div>

            {/* Data Layers Box */}
            <div className="bg-[var(--bg-primary)]/40 backdrop-blur-md border border-[var(--border-primary)] rounded-xl pointer-events-auto shadow-[0_4px_30px_rgba(0,0,0,0.2)] flex flex-col relative overflow-hidden max-h-full">

                {/* Header / Toggle */}
                <div
                    className="flex justify-between items-center p-4 cursor-pointer hover:bg-[var(--bg-secondary)]/50 transition-colors border-b border-[var(--border-primary)]/50"
                    onClick={() => setIsMinimized(!isMinimized)}
                >
                    <span className="text-[10px] text-[var(--text-muted)] font-mono tracking-widest">DATA LAYERS</span>
                    <button className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
                        {isMinimized ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                    </button>
                </div>

                <AnimatePresence>
                    {!isMinimized && (
                        <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            className="overflow-y-auto styled-scrollbar"
                        >
                            <div className="flex flex-col gap-6 p-4 pt-2 pb-6">
                                {layers.map((layer, idx) => {
                                    const Icon = layer.icon;
                                    const active = activeLayers[layer.id as keyof typeof activeLayers] || false;

                                    return (
                                        <div key={idx} className="flex flex-col">
                                            <div
                                                className="flex items-start justify-between group cursor-pointer"
                                                onClick={() => setActiveLayers((prev: any) => ({ ...prev, [layer.id]: !active }))}
                                            >
                                                <div className="flex gap-3">
                                                    <div className={`mt-1 ${active ? 'text-cyan-400' : 'text-gray-600 group-hover:text-gray-400'} transition-colors`}>
                                                        {(['ships_important', 'ships_civilian', 'ships_passenger'].includes(layer.id)) ? shipIcon : <Icon size={16} strokeWidth={1.5} />}
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className={`text-sm font-medium ${active ? 'text-[var(--text-primary)]' : 'text-[var(--text-secondary)]'} tracking-wide`}>{layer.name}</span>
                                                        <span className="text-[9px] text-[var(--text-muted)] font-mono tracking-wider mt-0.5">{layer.source} · {active ? (() => {
                                                            const fKey = FRESHNESS_MAP[layer.id];
                                                            const freshness = fKey && data?.freshness?.[fKey];
                                                            const rt = freshness ? relativeTime(freshness) : '';
                                                            return rt ? <span className="text-cyan-500/70">{rt}</span> : 'LIVE';
                                                        })() : 'OFF'}</span>
                                                    </div>
                                                </div>
                                                <div className="flex items-center gap-3">
                                                    {active && layer.count > 0 && (
                                                        <span className="text-[10px] text-gray-300 font-mono">{layer.count.toLocaleString()}</span>
                                                    )}
                                                    <div className={`text-[9px] font-mono tracking-wider px-2 py-0.5 rounded-full border ${active
                                                        ? 'border-cyan-500/50 text-cyan-400 bg-cyan-950/30 shadow-[0_0_10px_rgba(34,211,238,0.2)]'
                                                        : 'border-[var(--border-primary)] text-[var(--text-muted)] bg-transparent'
                                                        }`}>
                                                        {active ? 'ON' : 'OFF'}
                                                    </div>
                                                </div>
                                            </div>
                                            {/* GIBS Imagery inline controls: time slider + play/pause + opacity */}
                                            {active && layer.id === 'gibs_imagery' && gibsDate && setGibsDate && setGibsOpacity && (
                                                <div className="ml-7 mt-2 flex flex-col gap-2" onClick={e => e.stopPropagation()}>
                                                    <div className="flex items-center gap-2">
                                                        <button
                                                            onClick={() => setGibsPlaying(p => !p)}
                                                            className="w-5 h-5 flex items-center justify-center rounded border border-cyan-500/30 text-cyan-400 hover:bg-cyan-950/30 transition-colors"
                                                        >
                                                            {gibsPlaying ? <Pause size={10} /> : <Play size={10} />}
                                                        </button>
                                                        <input
                                                            type="range"
                                                            min={0}
                                                            max={29}
                                                            value={(() => {
                                                                const yesterday = new Date();
                                                                yesterday.setDate(yesterday.getDate() - 1);
                                                                const selected = new Date(gibsDate + 'T00:00:00');
                                                                const diff = Math.round((yesterday.getTime() - selected.getTime()) / 86400000);
                                                                return 29 - Math.max(0, Math.min(29, diff));
                                                            })()}
                                                            onChange={e => {
                                                                const daysAgo = 29 - parseInt(e.target.value);
                                                                const d = new Date();
                                                                d.setDate(d.getDate() - 1 - daysAgo);
                                                                setGibsDate(d.toISOString().slice(0, 10));
                                                            }}
                                                            className="flex-1 h-1 accent-cyan-500 cursor-pointer"
                                                        />
                                                    </div>
                                                    <div className="flex items-center justify-between">
                                                        <span className="text-[8px] text-cyan-400 font-mono">{gibsDate}</span>
                                                        <div className="flex items-center gap-1">
                                                            <span className="text-[8px] text-[var(--text-muted)] font-mono">OPC</span>
                                                            <input
                                                                type="range"
                                                                min={0}
                                                                max={100}
                                                                value={Math.round((gibsOpacity ?? 0.6) * 100)}
                                                                onChange={e => setGibsOpacity(parseInt(e.target.value) / 100)}
                                                                className="w-16 h-1 accent-cyan-500 cursor-pointer"
                                                            />
                                                        </div>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )
                                })}

                                {/* POTUS Fleet Tracker */}
                                <div className="border-t border-[var(--border-primary)]/50 pt-4 mt-2">
                                    <div className="flex items-center gap-2 mb-3">
                                        <Shield size={14} className="text-[#ff1493]" />
                                        <span className="text-[10px] text-[#ff1493] font-mono tracking-widest font-bold">POTUS FLEET</span>
                                        {potusFlights.length > 0 && (
                                            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-full bg-[#ff1493]/20 border border-[#ff1493]/40 text-[#ff1493] animate-pulse">
                                                {potusFlights.length} ACTIVE
                                            </span>
                                        )}
                                    </div>
                                    {potusFlights.length === 0 ? (
                                        <div className="ml-5 text-[9px] text-[var(--text-muted)] font-mono">
                                            No POTUS fleet aircraft currently airborne
                                        </div>
                                    ) : (
                                        <div className="flex flex-col gap-2 ml-1">
                                            {potusFlights.map((pf) => {
                                                const color = pf.meta.type === 'AF1' ? '#ff1493' : pf.meta.type === 'M1' ? '#ff1493' : '#3b82f6';
                                                const alt = pf.flight.alt_baro || pf.flight.alt || 0;
                                                const speed = pf.flight.gs || pf.flight.speed || 0;
                                                return (
                                                    <div
                                                        key={pf.flight.icao24}
                                                        className="flex items-center justify-between p-2 rounded-lg border cursor-pointer transition-all hover:bg-[var(--bg-secondary)]/60"
                                                        style={{ borderColor: `${color}40`, background: `${color}10` }}
                                                        onClick={() => {
                                                            if (onFlyTo && pf.flight.lat != null && pf.flight.lng != null) {
                                                                onFlyTo(pf.flight.lat, pf.flight.lng);
                                                            }
                                                            if (onEntityClick) {
                                                                onEntityClick({ type: 'tracked_flight', id: pf.index });
                                                            }
                                                        }}
                                                    >
                                                        <div className="flex flex-col">
                                                            <span className="text-[10px] font-bold font-mono" style={{ color }}>{pf.meta.label}</span>
                                                            <span className="text-[8px] text-[var(--text-muted)] font-mono mt-0.5">
                                                                {alt > 0 ? `${Math.round(alt).toLocaleString()} ft` : 'GND'} · {speed > 0 ? `${Math.round(speed)} kts` : 'STATIC'}
                                                            </span>
                                                        </div>
                                                        <div className="flex items-center gap-1.5">
                                                            <div className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: color }} />
                                                            <span className="text-[8px] font-mono" style={{ color }}>TRACK</span>
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>
        </motion.div>
    );
});

export default WorldviewLeftPanel;
