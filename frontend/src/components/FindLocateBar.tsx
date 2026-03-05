"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import { Search, Crosshair, Plane, Shield, Star, Ship, X, Database } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { trackedOperators } from '../lib/trackedData';

interface FindLocateBarProps {
    data: any;
    onLocate: (lat: number, lng: number, entityId: string, entityType: string) => void;
    onFilter?: (filterType: string, filterValue: string) => void;
}

interface SearchResult {
    id: string;
    label: string;
    sublabel: string;
    category: string;
    categoryColor: string;
    lat: number;
    lng: number;
    entityType: string;
}

export default function FindLocateBar({ data, onLocate, onFilter }: FindLocateBarProps) {
    const [query, setQuery] = useState("");
    const [isOpen, setIsOpen] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener("mousedown", handler);
        return () => document.removeEventListener("mousedown", handler);
    }, []);

    // Build searchable index from all data
    const allEntities = useMemo(() => {
        const results: SearchResult[] = [];

        // Commercial flights
        for (const f of data?.commercial_flights || []) {
            const uid = f.icao24 || f.registration || f.callsign || '';
            results.push({
                id: `flight-${uid}`,
                label: f.callsign || uid,
                sublabel: `${f.model || 'Unknown'} · ${f.airline_code || 'Commercial'}`,
                category: "COMMERCIAL",
                categoryColor: "text-cyan-400",
                lat: f.lat,
                lng: f.lng,
                entityType: "flight",
            });
        }

        // Private flights
        for (const f of [...(data?.private_flights || []), ...(data?.private_jets || [])]) {
            const uid = f.icao24 || f.registration || f.callsign || '';
            const type = f.type === 'private_jet' ? 'private_jet' : 'private_flight';
            results.push({
                id: `${type === 'private_jet' ? 'private-jet' : 'private-flight'}-${uid}`,
                label: f.callsign || f.registration || uid,
                sublabel: `${f.model || 'Unknown'} · Private`,
                category: "PRIVATE",
                categoryColor: "text-orange-400",
                lat: f.lat,
                lng: f.lng,
                entityType: type,
            });
        }

        // Military flights
        for (const f of data?.military_flights || []) {
            const uid = f.icao24 || f.registration || f.callsign || '';
            results.push({
                id: `mil-flight-${uid}`,
                label: f.callsign || uid,
                sublabel: `${f.model || 'Unknown'} · ${f.military_type || 'Military'}`,
                category: "MILITARY",
                categoryColor: "text-yellow-400",
                lat: f.lat,
                lng: f.lng,
                entityType: "military_flight",
            });
        }

        // Tracked flights
        for (const f of data?.tracked_flights || []) {
            const uid = f.icao24 || f.registration || f.callsign || '';
            const operator = f.alert_operator || 'Unknown Operator';
            const category = f.alert_category || 'Tracked';
            const type = f.alert_type || f.model || 'Unknown';
            results.push({
                id: `tracked-${uid}`,
                label: operator,
                sublabel: `${category} · ${type} (${f.registration || uid})`,
                category: "TRACKED",
                categoryColor: "text-pink-400",
                lat: f.lat,
                lng: f.lng,
                entityType: "tracked_flight",
            });
        }

        // Ships
        for (const s of data?.ships || []) {
            results.push({
                id: `ship-${s.mmsi || s.name || ''}`,
                label: s.name || "UNKNOWN",
                sublabel: `${s.type || 'Vessel'} · ${s.destination || 'Unknown dest'}`,
                category: "MARITIME",
                categoryColor: "text-blue-400",
                lat: s.lat,
                lng: s.lng,
                entityType: "ship",
            });
        }

        // Database Records - Tracked Operators
        for (const op of trackedOperators) {
            results.push({
                id: `tracked-db-${op}`,
                label: op,
                sublabel: `Database Record · Operator`,
                category: "DATABASE",
                categoryColor: "text-purple-400",
                lat: 0,
                lng: 0,
                entityType: "database_operator",
            });
        }

        return results;
    }, [data]);

    // Filter results based on query
    const filtered = useMemo(() => {
        if (!query.trim()) return [];
        const q = query.toLowerCase();
        return allEntities
            .filter(e => {
                const searchable = `${e.label} ${e.sublabel} ${e.id}`.toLowerCase();
                return searchable.includes(q);
            })
            .slice(0, 12);
    }, [query, allEntities]);

    const handleSelect = (result: SearchResult) => {
        if (result.entityType === "database_operator") {
            if (onFilter) onFilter("tracked_owner", result.label);
        } else {
            onLocate(result.lat, result.lng, result.id, result.entityType);
        }
        setQuery("");
        setIsOpen(false);
    };

    const categoryIcons: Record<string, React.ReactNode> = {
        COMMERCIAL: <Plane size={10} className="text-cyan-400" />,
        PRIVATE: <Plane size={10} className="text-orange-400" />,
        MILITARY: <Shield size={10} className="text-yellow-400" />,
        TRACKED: <Star size={10} className="text-pink-400" />,
        MARITIME: <Ship size={10} className="text-blue-400" />,
        DATABASE: <Database size={10} className="text-purple-400" />,
    };

    return (
        <div ref={containerRef} className="relative w-full pointer-events-auto">
            <div className="flex items-center gap-2 bg-black/40 backdrop-blur-md border border-gray-800 rounded-lg px-3 py-2 focus-within:border-cyan-500/40 transition-colors">
                <Search size={12} className="text-gray-500 flex-shrink-0" />
                <input
                    ref={inputRef}
                    type="text"
                    value={query}
                    placeholder="Find aircraft or vessel..."
                    className="flex-1 bg-transparent text-[10px] text-gray-300 font-mono tracking-wider outline-none placeholder:text-gray-600"
                    onChange={(e) => {
                        setQuery(e.target.value);
                        setIsOpen(true);
                    }}
                    onFocus={() => setIsOpen(true)}
                />
                {query && (
                    <button onClick={() => { setQuery(""); setIsOpen(false); }} className="text-gray-600 hover:text-white transition-colors">
                        <X size={10} />
                    </button>
                )}
                <Crosshair size={12} className="text-gray-600 flex-shrink-0" />
            </div>

            <AnimatePresence>
                {isOpen && filtered.length > 0 && (
                    <motion.div
                        initial={{ opacity: 0, y: -4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -4 }}
                        className="absolute top-full left-0 right-0 mt-1 bg-black/90 backdrop-blur-md border border-gray-800 rounded-lg overflow-hidden z-50 shadow-[0_8px_30px_rgba(0,0,0,0.6)]"
                    >
                        <div className="max-h-[300px] overflow-y-auto styled-scrollbar">
                            {filtered.map((r, idx) => (
                                <button
                                    key={`${r.id}-${idx}`}
                                    onClick={() => handleSelect(r)}
                                    className="w-full flex items-center gap-3 px-3 py-2 hover:bg-cyan-950/30 transition-colors text-left border-b border-gray-800/50 last:border-0 group"
                                >
                                    <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center rounded bg-gray-900 border border-gray-800 group-hover:border-cyan-800">
                                        {categoryIcons[r.category]}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-[10px] text-gray-200 font-mono tracking-wide truncate">{r.label}</div>
                                        <div className="text-[8px] text-gray-500 font-mono truncate">{r.sublabel}</div>
                                    </div>
                                    <span className={`text-[7px] font-bold tracking-widest ${r.categoryColor} flex-shrink-0`}>
                                        {r.category}
                                    </span>
                                </button>
                            ))}
                        </div>
                        <div className="px-3 py-1.5 border-t border-gray-800 bg-black/50 text-[8px] text-gray-600 font-mono tracking-widest">
                            {filtered.length} RESULT{filtered.length !== 1 ? 'S' : ''} — CLICK TO LOCATE
                        </div>
                    </motion.div>
                )}
                {isOpen && query.trim() && filtered.length === 0 && (
                    <motion.div
                        initial={{ opacity: 0, y: -4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -4 }}
                        className="absolute top-full left-0 right-0 mt-1 bg-black/90 backdrop-blur-md border border-gray-800 rounded-lg z-50 p-4 text-center"
                    >
                        <div className="text-[9px] text-gray-600 font-mono tracking-widest">NO MATCHING ASSETS</div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
