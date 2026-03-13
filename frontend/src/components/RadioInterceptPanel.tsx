"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { RadioReceiver, Activity, Play, Square, FastForward, ChevronDown, ChevronUp } from 'lucide-react';

export default function RadioInterceptPanel({ data, isEavesdropping, setIsEavesdropping, eavesdropLocation, cameraCenter, selectedEntity }: { data: any, isEavesdropping?: boolean, setIsEavesdropping?: (val: boolean) => void, eavesdropLocation?: { lat: number, lng: number } | null, cameraCenter?: { lat: number, lng: number } | null, selectedEntity?: { type: string, id: string | number, extra?: any } | null }) {
    const [isMinimized, setIsMinimized] = useState(true);
    const [feeds, setFeeds] = useState<any[]>([]);
    const [activeFeed, setActiveFeed] = useState<any | null>(null);
    const [isPlaying, setIsPlaying] = useState(false);
    const [isScanning, setIsScanning] = useState(false);
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const [volume, setVolume] = useState(0.8);
    const scanTimeoutRef = useRef<NodeJS.Timeout | null>(null);

    // Fetch the top feeds on mount
    useEffect(() => {
        const fetchFeeds = async () => {
            try {
                const res = await fetch(`${API_BASE}/api/radio/top`);
                if (res.ok) {
                    const json = await res.json();
                    setFeeds(json);
                }
            } catch (e) {
                console.error("Failed to fetch radio feeds", e);
            }
        };
        fetchFeeds();
        // Refresh every 5 minutes
        const interval = setInterval(fetchFeeds, 300000);
        return () => clearInterval(interval);
    }, []);

    // Handle Eavesdrop Map Clicks
    useEffect(() => {
        if (eavesdropLocation && isEavesdropping) {
            const fetchNearest = async () => {
                try {
                    // Show a temporary state
                    setFeeds(prev => [{
                        id: 'scanning-nearest',
                        name: 'TRIANGULATING SIGNAL...',
                        location: `LAT:${eavesdropLocation.lat.toFixed(2)} LNG:${eavesdropLocation.lng.toFixed(2)}`,
                        listeners: 0,
                        category: 'SIGINT'
                    }, ...prev]);

                    const res = await fetch(`${API_BASE}/api/radio/nearest?lat=${eavesdropLocation.lat}&lng=${eavesdropLocation.lng}`);
                    if (res.ok) {
                        const system = await res.json();
                        if (system && system.shortName) {
                            // Valid OpenMHZ system found! Fetch recent calls
                            const callRes = await fetch(`${API_BASE}/api/radio/openmhz/calls/${system.shortName}`);
                            if (callRes.ok) {
                                const calls = await callRes.json();
                                if (calls && calls.length > 0) {
                                    // Found bursts!
                                    const latest = calls[0];
                                    const openMhzFeed = {
                                        id: `openmhz-${system.shortName}-${latest.id}`,
                                        name: `${system.name} (TG:${latest.talkgroupNum})`,
                                        location: `${system.city}, ${system.state}`,
                                        listeners: system.clientCount || 0,
                                        category: 'TRUNKED INTERCEPT',
                                        stream_url: latest.url
                                    };

                                    // Remove the triangulating placeholder and add the new intercept
                                    setFeeds(prev => {
                                        const clean = prev.filter(f => f.id !== 'scanning-nearest');
                                        // Avoid duplicates if we clicked the same place twice
                                        if (clean.find(f => f.id === openMhzFeed.id)) return clean;
                                        return [openMhzFeed, ...clean];
                                    });
                                    // Auto-play the intercept
                                    playFeed(openMhzFeed);
                                } else {
                                    // Provide failure feedback
                                    setFeeds(prev => {
                                        const clean = prev.filter(f => f.id !== 'scanning-nearest');
                                        return [{
                                            id: `failed-${Date.now()}`,
                                            name: `NO RECENT COMMS (${system.shortName})`,
                                            location: `${system.city}, ${system.state}`,
                                            category: 'DEAD AIR',
                                            listeners: 0
                                        }, ...clean];
                                    });
                                }
                            }
                        } else {
                            // Provide failure feedback
                            setFeeds(prev => {
                                const clean = prev.filter(f => f.id !== 'scanning-nearest');
                                return [{
                                    id: `failed-${Date.now()}`,
                                    name: 'NO LOCAL REPEATERS FOUND',
                                    location: 'UNKNOWN',
                                    category: 'ENCRYPTED / VOID',
                                    listeners: 0
                                }, ...clean];
                            });
                        }
                    }
                } catch (e) {
                    console.error("Nearest system lookup failed", e);
                }
            };
            fetchNearest();
        }
    }, [eavesdropLocation]);

    const playFeed = (feed: any) => {
        if (isScanning && scanTimeoutRef.current) {
            clearTimeout(scanTimeoutRef.current);
            setIsScanning(false);
        }
        setActiveFeed(feed);
        setIsPlaying(true);
    };

    const stopFeed = () => {
        if (isScanning && scanTimeoutRef.current) {
            clearTimeout(scanTimeoutRef.current);
            setIsScanning(false);
        }
        setActiveFeed(null);
        setIsPlaying(false);
    };

    // Handle Audio Element Play/Stop
    useEffect(() => {
        if (activeFeed && isPlaying) {
            if (!audioRef.current) {
                const audio = new Audio(activeFeed.stream_url);
                audioRef.current = audio;
            } else {
                audioRef.current.src = activeFeed.stream_url;
            }
            audioRef.current.volume = volume;
            audioRef.current.play().catch(e => console.log("Audio play blocked", e));
        } else {
            if (audioRef.current) {
                audioRef.current.pause();
                audioRef.current.src = "";
            }
        }
    }, [activeFeed, isPlaying]);

    useEffect(() => {
        if (audioRef.current) {
            audioRef.current.volume = volume;
        }
    }, [volume]);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            if (audioRef.current) {
                audioRef.current.pause();
                audioRef.current.src = "";
            }
            if (scanTimeoutRef.current) {
                clearTimeout(scanTimeoutRef.current);
            }
        };
    }, []);

    const toggleScan = () => {
        if (isScanning) {
            setIsScanning(false);
            if (scanTimeoutRef.current) clearTimeout(scanTimeoutRef.current);
            stopFeed();
        } else {
            setIsScanning(true);
            scanNextFeed();
        }
    };

    const scanNextFeed = async () => {
        if (!isScanning) return;

        // Try localized scan first if we have a camera center or eavesdrop location
        const scanLoc = eavesdropLocation || cameraCenter;

        let localFeedFound = false;

        if (scanLoc) {
            try {
                const res = await fetch(`${API_BASE}/api/radio/nearest-list?lat=${scanLoc.lat}&lng=${scanLoc.lng}&limit=3`);
                if (res.ok) {
                    const systems = await res.json();

                    // Try to find a system with an active unplayed burst
                    for (const system of systems) {
                        if (system && system.shortName) {
                            const callRes = await fetch(`${API_BASE}/api/radio/openmhz/calls/${system.shortName}`);
                            if (callRes.ok) {
                                const calls = await callRes.json();
                                if (calls && calls.length > 0) {
                                    // Normally we would track played calls. For now just pick random recent one.
                                    const randomCall = calls[Math.floor(Math.random() * Math.min(calls.length, 3))];
                                    const openMhzFeed = {
                                        id: `openmhz-${system.shortName}-${randomCall.id}`,
                                        name: `${system.name} (TG:${randomCall.talkgroupNum})`,
                                        location: `${system.city}, ${system.state}`,
                                        listeners: system.clientCount || 0,
                                        category: 'TRUNKED INTERCEPT',
                                        stream_url: randomCall.url
                                    };

                                    // Replace feeds list visually with this active sector
                                    setFeeds(prev => {
                                        if (prev.find(f => f.id === openMhzFeed.id)) return prev;
                                        return [openMhzFeed, ...prev].slice(0, 10);
                                    });
                                    setActiveFeed(openMhzFeed);
                                    setIsPlaying(true);
                                    localFeedFound = true;
                                    break;
                                }
                            }
                        }
                    }
                }
            } catch (e) {
                console.error("Auto scan local query failed", e);
            }
        }

        if (!localFeedFound && feeds.length > 0) {
            // Fallback: Pick a random hot feed or cycle them
            const randomIdx = Math.floor(Math.random() * Math.min(feeds.length, 10)); // Pick from top 10
            setActiveFeed(feeds[randomIdx]);
            setIsPlaying(true);
        }

        // Scan for 15 seconds then switch
        scanTimeoutRef.current = setTimeout(() => {
            if (isScanning) scanNextFeed();
        }, 15000);
    };

    return (
        <motion.div
            initial={{ opacity: 0, x: 50 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 1, delay: 0.2 }}
            className="w-full flex flex-col bg-[var(--bg-primary)]/40 backdrop-blur-md border border-cyan-900/50 rounded-xl pointer-events-auto shadow-[0_4px_30px_rgba(0,0,0,0.2)] relative overflow-hidden max-h-full"
        >
            <div
                className="flex items-center justify-between p-3 border-b border-cyan-900/50 cursor-pointer bg-cyan-950/20 hover:bg-cyan-900/30 transition-colors"
                onClick={() => setIsMinimized(!isMinimized)}
            >
                <div className="flex items-center gap-2 text-cyan-400">
                    <RadioReceiver size={14} className={isPlaying ? "animate-pulse" : ""} />
                    <span className="text-[10px] font-mono tracking-widest font-semibold">SIGINT INTERCEPT</span>
                    {isPlaying && <Activity size={12} className="text-red-500 animate-pulse ml-2" />}
                </div>
                <button className="text-cyan-500 hover:text-cyan-300 transition-colors">
                    {isMinimized ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </button>
            </div>

            <AnimatePresence>
                {!isMinimized && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="flex flex-col overflow-hidden"
                    >
                        {/* Audio Player Controls */}
                        <div className="p-4 border-b border-cyan-900/40 bg-[var(--bg-primary)]/60">
                            <div className="flex items-center justify-between mb-3">
                                <div className="flex flex-col">
                                    <span className="text-xs text-cyan-300 font-mono tracking-wide">
                                        {activeFeed ? activeFeed.name : "NO SIGNAL"}
                                    </span>
                                    <span className="text-[9px] text-[var(--text-muted)] font-mono">
                                        {activeFeed ? `LOCATION: ${activeFeed.location.toUpperCase()}` : "AWAITING TUNING..."}
                                    </span>
                                </div>
                                {activeFeed && (
                                    <div className="flex items-center gap-1 bg-red-950/40 border border-red-900/50 px-2 py-0.5 rounded text-[9px] text-red-400 font-mono">
                                        <Activity size={10} className="animate-pulse" />
                                        LIVE
                                    </div>
                                )}
                            </div>

                            <div className="flex items-center gap-4">
                                <button
                                    onClick={activeFeed ? stopFeed : () => feeds.length > 0 && playFeed(feeds[0])}
                                    className={`p-2 rounded-full border ${activeFeed ? 'border-red-500/50 text-red-500 hover:bg-red-950/50' : 'border-cyan-700 text-cyan-500 hover:bg-cyan-900/50'} transition-colors`}
                                >
                                    {activeFeed ? <Square size={14} /> : <Play size={14} className="ml-0.5" />}
                                </button>

                                <button
                                    onClick={toggleScan}
                                    className={`px-3 py-1.5 rounded text-[10px] font-mono border tracking-wider flex items-center gap-2 ${isScanning ? 'bg-cyan-900/60 border-cyan-400 text-cyan-300' : 'border-cyan-800 text-cyan-600 hover:border-cyan-600'} transition-colors`}
                                >
                                    <FastForward size={12} />
                                    {isScanning ? 'SCANNING...' : 'AUTO SCAN'}
                                </button>

                                <button
                                    onClick={() => setIsEavesdropping && setIsEavesdropping(!isEavesdropping)}
                                    className={`px-3 py-1.5 rounded text-[10px] font-mono border tracking-wider flex items-center gap-2 ${isEavesdropping ? 'bg-red-900/60 border-red-500 text-red-300 animate-pulse' : 'border-cyan-800 text-cyan-600 hover:border-cyan-600'} transition-colors`}
                                    title="Click on the globe to intercept local signals"
                                >
                                    EAVESDROP
                                </button>

                                <input
                                    type="range"
                                    min="0" max="1" step="0.05"
                                    value={volume}
                                    onChange={(e) => setVolume(parseFloat(e.target.value))}
                                    className="w-20 accent-cyan-500"
                                    title="Volume"
                                />
                            </div>

                            {/* Fake Waveform Visualizer */}
                            <div className="mt-4 flex items-end gap-[2px] h-8 opacity-70">
                                {Array.from({ length: 48 }).map((_, i) => (
                                    <motion.div
                                        key={i}
                                        className={`w-1 rounded-t-sm ${isPlaying ? 'bg-cyan-500' : 'bg-cyan-900/50'}`}
                                        animate={{
                                            height: isPlaying
                                                ? ['10%', `${Math.random() * 80 + 20}%`, '10%']
                                                : '10%'
                                        }}
                                        transition={{
                                            repeat: Infinity,
                                            duration: Math.random() * 0.5 + 0.3,
                                            ease: "easeInOut"
                                        }}
                                    />
                                ))}
                            </div>
                        </div>

                        {/* KiwiSDR Tuner — appears when a KiwiSDR node is clicked on the map */}
                        {selectedEntity?.type === 'kiwisdr' && selectedEntity.extra?.url && (
                            <div className="p-3 border-b border-amber-900/40 bg-amber-950/10">
                                <div className="text-[9px] text-amber-400 font-mono tracking-widest mb-2 flex items-center gap-2">
                                    <RadioReceiver size={10} />
                                    SDR TUNER: {(selectedEntity.extra.name || 'REMOTE RECEIVER').toUpperCase().slice(0, 60)}
                                </div>
                                <div className="text-[8px] text-[var(--text-muted)] font-mono mb-2">
                                    {selectedEntity.extra.location && <span>{selectedEntity.extra.location} · </span>}
                                    {selectedEntity.extra.antenna && <span>{selectedEntity.extra.antenna.slice(0, 80)} · </span>}
                                    {selectedEntity.extra.users !== undefined && <span>{selectedEntity.extra.users}/{selectedEntity.extra.users_max} users</span>}
                                </div>
                                <div className="flex items-center gap-2 mt-1">
                                    <a
                                        href={selectedEntity.extra.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="flex-1 text-center px-4 py-2.5 rounded border border-amber-500/50 bg-amber-950/30 text-amber-400 hover:bg-amber-900/40 hover:border-amber-400 text-[10px] font-mono tracking-widest transition-colors"
                                    >
                                        OPEN SDR RECEIVER →
                                    </a>
                                </div>
                                {selectedEntity.extra.bands && (
                                    <div className="text-[8px] text-[var(--text-muted)] font-mono mt-2">
                                        BANDS: {(Number(selectedEntity.extra.bands.split('-')[0]) / 1e6).toFixed(0)}-{(Number(selectedEntity.extra.bands.split('-')[1]) / 1e6).toFixed(0)} MHz
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Feed List */}
                        <div className="flex-col overflow-y-auto styled-scrollbar max-h-64 p-2">
                            {feeds.length === 0 ? (
                                <div className="text-[10px] text-cyan-700 font-mono text-center p-4">SEARCHING FREQUENCIES...</div>
                            ) : (
                                feeds.map((feed: any, idx: number) => (
                                    <div
                                        key={feed.id}
                                        onClick={() => playFeed(feed)}
                                        className={`p-2 mb-1 rounded cursor-pointer border-l-2 ${activeFeed?.id === feed.id ? 'bg-cyan-900/30 border-cyan-400' : 'border-transparent hover:bg-white/5'} flex justify-between items-center transition-colors`}
                                    >
                                        <div className="flex flex-col overflow-hidden pr-2">
                                            <span className={`text-[11px] font-mono truncate ${activeFeed?.id === feed.id ? 'text-cyan-300' : 'text-[var(--text-secondary)]'}`}>
                                                {feed.name}
                                            </span>
                                            <span className="text-[9px] text-[var(--text-muted)] font-mono truncate">
                                                {feed.location} | {feed.category}
                                            </span>
                                        </div>
                                        <div className="flex flex-col items-end flex-shrink-0">
                                            <span className="text-[10px] text-cyan-600 font-mono flex items-center gap-1">
                                                <Activity size={10} />
                                                {feed.listeners.toLocaleString()}
                                            </span>
                                            <span className="text-[8px] text-[var(--text-muted)] font-mono mt-0.5">LSTN</span>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
}
