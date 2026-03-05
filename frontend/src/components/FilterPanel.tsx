"use client";

import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronUp, Filter, Plane, Shield, Star, Ship, SlidersHorizontal } from 'lucide-react';
import AdvancedFilterModal from './AdvancedFilterModal';
import { airlineNames } from '../lib/airlineCodes';
import { trackedCategories, trackedOperators } from '../lib/trackedData';

interface FilterPanelProps {
    data: any;
    activeFilters: Record<string, string[]>;
    setActiveFilters: (filters: Record<string, string[]>) => void;
}

type ModalConfig = {
    title: string;
    icon: React.ReactNode;
    accentColor: string;
    accentColorName: string;
    fields: { key: string; label: string; options: string[]; optionLabels?: Record<string, string> }[];
};

export default function FilterPanel({ data, activeFilters, setActiveFilters }: FilterPanelProps) {
    const [isMinimized, setIsMinimized] = useState(true);
    const [openModal, setOpenModal] = useState<string | null>(null);

    // ── Extract unique values from live data ──

    // Commercial: departures, arrivals, airlines
    const uniqueOrigins = useMemo(() => {
        const origins = new Set<string>();
        for (const f of data?.commercial_flights || []) {
            if (f.origin_name && f.origin_name !== 'UNKNOWN') origins.add(f.origin_name);
        }
        return Array.from(origins).sort();
    }, [data?.commercial_flights]);

    const uniqueDestinations = useMemo(() => {
        const dests = new Set<string>();
        for (const f of data?.commercial_flights || []) {
            if (f.dest_name && f.dest_name !== 'UNKNOWN') dests.add(f.dest_name);
        }
        return Array.from(dests).sort();
    }, [data?.commercial_flights]);

    const uniqueAirlines = useMemo(() => {
        const airlines = new Set<string>();
        for (const f of data?.commercial_flights || []) {
            if (f.airline_code && f.airline_code.trim()) airlines.add(f.airline_code.trim());
        }
        return Array.from(airlines).sort();
    }, [data?.commercial_flights]);

    const airlineLabels = useMemo(() => {
        const labels: Record<string, string> = {};
        for (const code of uniqueAirlines) {
            const name = airlineNames[code];
            if (name) {
                labels[code] = `${code} - ${name}`;
            } else {
                labels[code] = code;
            }
        }
        return labels;
    }, [uniqueAirlines]);

    // Private: callsigns + aircraft types
    const uniquePrivateCallsigns = useMemo(() => {
        const callsigns = new Set<string>();
        for (const f of [...(data?.private_flights || []), ...(data?.private_jets || [])]) {
            if (f.callsign) callsigns.add(f.callsign);
            if (f.registration) callsigns.add(f.registration);
        }
        return Array.from(callsigns).sort();
    }, [data?.private_flights, data?.private_jets]);

    const uniquePrivateAircraftTypes = useMemo(() => {
        const types = new Set<string>();
        for (const f of [...(data?.private_flights || []), ...(data?.private_jets || [])]) {
            if (f.model && f.model !== 'Unknown') types.add(f.model);
        }
        return Array.from(types).sort();
    }, [data?.private_flights, data?.private_jets]);

    // Military: country + aircraft type
    const uniqueMilCountries = useMemo(() => {
        const countries = new Set<string>();
        for (const f of data?.military_flights || []) {
            if (f.country) countries.add(f.country);
            else if (f.registration) countries.add(f.registration);
        }
        return Array.from(countries).sort();
    }, [data?.military_flights]);

    const uniqueMilAircraftTypes = useMemo(() => {
        const types = new Set<string>();
        for (const f of data?.military_flights || []) {
            if (f.military_type && f.military_type !== 'default') types.add(f.military_type);
        }
        return Array.from(types).sort();
    }, [data?.military_flights]);

    // Tracked: operators + categories
    const uniqueTrackedOperators = useMemo(() => {
        const ops = new Set<string>(trackedOperators);
        for (const f of data?.tracked_flights || []) {
            if (f.alert_operator) ops.add(f.alert_operator);
            if (f.alert_tag1) ops.add(f.alert_tag1);
            if (f.alert_tag2) ops.add(f.alert_tag2);
        }
        return Array.from(ops).sort();
    }, [data?.tracked_flights]);

    const uniqueTrackedCategories = useMemo(() => {
        const cats = new Set<string>(trackedCategories);
        for (const f of data?.tracked_flights || []) {
            if (f.alert_category) cats.add(f.alert_category);
        }
        return Array.from(cats).sort();
    }, [data?.tracked_flights]);

    // Maritime: vessel names + vessel types (using 'type' field, not 'ship_type')
    const uniqueShipNames = useMemo(() => {
        const names = new Set<string>();
        for (const s of data?.ships || []) {
            if (s.name && s.name !== 'UNKNOWN') names.add(s.name);
        }
        return Array.from(names).sort();
    }, [data?.ships]);

    const uniqueVesselTypes = useMemo(() => {
        const types = new Set<string>();
        for (const s of data?.ships || []) {
            // Use 'type' field from AIS stream (tanker, cargo, passenger, yacht, etc.)
            if (s.type && s.type !== 'unknown') types.add(s.type);
        }
        return Array.from(types).sort();
    }, [data?.ships]);

    // ── Modal configs ──

    const modalConfigs: Record<string, ModalConfig> = {
        commercial: {
            title: 'COMMERCIAL FLIGHTS',
            icon: <Plane size={13} className="text-cyan-400" />,
            accentColor: '#00bcd4',
            accentColorName: 'cyan',
            fields: [
                { key: 'commercial_departure', label: 'DEPARTURE', options: uniqueOrigins },
                { key: 'commercial_arrival', label: 'ARRIVAL', options: uniqueDestinations },
                { key: 'commercial_airline', label: 'AIRLINE', options: uniqueAirlines, optionLabels: airlineLabels },
            ]
        },
        private: {
            title: 'PRIVATE / JETS',
            icon: <Plane size={13} className="text-orange-400" />,
            accentColor: '#FF8C00',
            accentColorName: 'orange',
            fields: [
                { key: 'private_callsign', label: 'CALLSIGN / REG', options: uniquePrivateCallsigns },
                { key: 'private_aircraft_type', label: 'AIRCRAFT TYPE', options: uniquePrivateAircraftTypes },
            ]
        },
        military: {
            title: 'MILITARY',
            icon: <Shield size={13} className="text-yellow-400" />,
            accentColor: '#EAB308',
            accentColorName: 'yellow',
            fields: [
                { key: 'military_country', label: 'COUNTRY / REG', options: uniqueMilCountries },
                { key: 'military_aircraft_type', label: 'AIRCRAFT TYPE', options: uniqueMilAircraftTypes },
            ]
        },
        tracked: {
            title: 'TRACKED AIRCRAFT',
            icon: <Star size={13} className="text-pink-400" />,
            accentColor: '#EC4899',
            accentColorName: 'pink',
            fields: [
                { key: 'tracked_category', label: 'CATEGORY', options: uniqueTrackedCategories },
                { key: 'tracked_owner', label: 'OPERATOR / ENTITY', options: uniqueTrackedOperators },
            ]
        },
        ships: {
            title: 'MARITIME VESSELS',
            icon: <Ship size={13} className="text-blue-400" />,
            accentColor: '#3B82F6',
            accentColorName: 'blue',
            fields: [
                { key: 'ship_name', label: 'VESSEL NAME', options: uniqueShipNames },
                { key: 'ship_type', label: 'VESSEL TYPE', options: uniqueVesselTypes },
            ]
        }
    };

    const clearAll = () => setActiveFilters({});

    const activeCount = Object.values(activeFilters).reduce((acc, arr) => acc + arr.length, 0);

    const getCountForCategory = (category: string) => {
        const config = modalConfigs[category];
        if (!config) return 0;
        return config.fields.reduce((acc, f) => acc + (activeFilters[f.key]?.length || 0), 0);
    };

    const handleModalApply = (categoryKey: string, modalFilters: Record<string, string[]>) => {
        const config = modalConfigs[categoryKey];
        const next = { ...activeFilters };
        for (const field of config.fields) {
            delete next[field.key];
        }
        for (const [key, values] of Object.entries(modalFilters)) {
            if (values.length > 0) next[key] = values;
        }
        setActiveFilters(next);
    };

    const sections = [
        { key: 'commercial', title: 'COMMERCIAL FLIGHTS', icon: <Plane size={11} className="text-cyan-400" />, color: 'cyan' },
        { key: 'private', title: 'PRIVATE / JETS', icon: <Plane size={11} className="text-orange-400" />, color: 'orange' },
        { key: 'military', title: 'MILITARY', icon: <Shield size={11} className="text-yellow-400" />, color: 'yellow' },
        { key: 'tracked', title: 'TRACKED AIRCRAFT', icon: <Star size={11} className="text-pink-400" />, color: 'pink' },
        { key: 'ships', title: 'MARITIME VESSELS', icon: <Ship size={11} className="text-blue-400" />, color: 'blue' },
    ];

    const borderColors: Record<string, string> = {
        cyan: 'border-cyan-500/20 hover:border-cyan-500/40',
        orange: 'border-orange-500/20 hover:border-orange-500/40',
        yellow: 'border-yellow-500/20 hover:border-yellow-500/40',
        pink: 'border-pink-500/20 hover:border-pink-500/40',
        blue: 'border-blue-500/20 hover:border-blue-500/40',
    };
    const textColors: Record<string, string> = {
        cyan: 'text-cyan-400',
        orange: 'text-orange-400',
        yellow: 'text-yellow-400',
        pink: 'text-pink-400',
        blue: 'text-blue-400',
    };
    const bgColors: Record<string, string> = {
        cyan: 'bg-cyan-500/10',
        orange: 'bg-orange-500/10',
        yellow: 'bg-yellow-500/10',
        pink: 'bg-pink-500/10',
        blue: 'bg-blue-500/10',
    };

    return (
        <>
            <motion.div
                initial={{ y: -30, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.6, delay: 0.3 }}
                className="w-full bg-black/40 backdrop-blur-md border border-gray-800 rounded-xl z-10 flex flex-col font-mono text-sm shadow-[0_4px_30px_rgba(0,0,0,0.5)] pointer-events-auto flex-shrink-0"
            >
                {/* Header Toggle */}
                <div
                    className="flex justify-between items-center p-3 cursor-pointer hover:bg-gray-900/50 transition-colors border-b border-gray-800/50"
                    onClick={() => setIsMinimized(!isMinimized)}
                >
                    <div className="flex items-center gap-2">
                        <Filter size={12} className="text-cyan-500" />
                        <span className="text-[10px] text-gray-500 font-mono tracking-widest">DATA FILTERS</span>
                        {activeCount > 0 && (
                            <span className="text-[9px] bg-cyan-500/20 text-cyan-400 px-1.5 py-0.5 rounded-sm">
                                {activeCount} ACTIVE
                            </span>
                        )}
                    </div>
                    <button className="text-gray-500 hover:text-white transition-colors">
                        {isMinimized ? <SlidersHorizontal size={14} /> : <ChevronUp size={14} />}
                    </button>
                </div>

                <AnimatePresence>
                    {!isMinimized && (
                        <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            className="overflow-y-auto styled-scrollbar flex flex-col gap-2 p-3 pt-2 max-h-[400px]"
                        >
                            {activeCount > 0 && (
                                <button
                                    onClick={clearAll}
                                    className="text-[9px] text-red-400 hover:text-red-300 tracking-widest self-end mb-1"
                                >
                                    CLEAR ALL FILTERS
                                </button>
                            )}

                            {sections.map(section => {
                                const count = getCountForCategory(section.key);
                                return (
                                    <div
                                        key={section.key}
                                        className={`border rounded-lg transition-all cursor-pointer group ${borderColors[section.color] || 'border-gray-800'} hover:bg-black/30`}
                                        onClick={() => setOpenModal(section.key)}
                                    >
                                        <div className="flex items-center justify-between p-2.5 px-3">
                                            <div className="flex items-center gap-2">
                                                {section.icon}
                                                <span className="text-[9px] text-gray-400 tracking-widest group-hover:text-gray-200 transition-colors">{section.title}</span>
                                                {count > 0 && (
                                                    <span className={`text-[8px] ${bgColors[section.color]} ${textColors[section.color]} px-1.5 py-0.5 rounded-sm`}>
                                                        {count}
                                                    </span>
                                                )}
                                            </div>
                                            <SlidersHorizontal size={10} className="text-gray-600 group-hover:text-gray-400 transition-colors" />
                                        </div>
                                    </div>
                                );
                            })}
                        </motion.div>
                    )}
                </AnimatePresence>
            </motion.div>

            {/* Render active modal */}
            <AnimatePresence>
                {openModal && modalConfigs[openModal] && (
                    <AdvancedFilterModal
                        key={openModal}
                        title={modalConfigs[openModal].title}
                        icon={modalConfigs[openModal].icon}
                        accentColor={modalConfigs[openModal].accentColor}
                        accentColorName={modalConfigs[openModal].accentColorName}
                        fields={modalConfigs[openModal].fields}
                        activeFilters={activeFilters}
                        onApply={(filters) => handleModalApply(openModal, filters)}
                        onClose={() => setOpenModal(null)}
                    />
                )}
            </AnimatePresence>
        </>
    );
}
