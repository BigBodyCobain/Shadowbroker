"use client";

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, Clock, ChevronDown, ChevronUp } from 'lucide-react';
import React, { useEffect, useRef } from 'react';
import WikiImage from '@/components/WikiImage';

// Format time from pubish string "Tue, 24 Feb 2026 15:30:00 GMT" to "15:30"
function formatTime(pubDate: string) {
    try {
        const d = new Date(pubDate);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
        return "00:00";
    }
}

// ICAO type designator → Wikipedia article title
const AIRCRAFT_WIKI: Record<string, string> = {
    // Boeing widebodies
    B741: 'Boeing 747', B742: 'Boeing 747', B743: 'Boeing 747', B744: 'Boeing 747-400', B748: 'Boeing 747-8',
    B752: 'Boeing 757', B753: 'Boeing 757', B762: 'Boeing 767', B763: 'Boeing 767', B764: 'Boeing 767',
    B772: 'Boeing 777', B773: 'Boeing 777', B77L: 'Boeing 777', B77W: 'Boeing 777', B778: 'Boeing 777X',
    B788: 'Boeing 787 Dreamliner', B789: 'Boeing 787 Dreamliner', B78X: 'Boeing 787 Dreamliner',
    // Boeing narrowbodies
    B712: 'Boeing 717', B731: 'Boeing 737', B732: 'Boeing 737', B733: 'Boeing 737', B734: 'Boeing 737',
    B735: 'Boeing 737', B736: 'Boeing 737', B737: 'Boeing 737', B738: 'Boeing 737 Next Generation',
    B739: 'Boeing 737 Next Generation', B37M: 'Boeing 737 MAX', B38M: 'Boeing 737 MAX', B39M: 'Boeing 737 MAX',
    // Airbus widebodies
    A306: 'Airbus A300', A310: 'Airbus A310', A332: 'Airbus A330', A333: 'Airbus A330', A338: 'Airbus A330neo',
    A339: 'Airbus A330neo', A342: 'Airbus A340', A343: 'Airbus A340', A345: 'Airbus A340', A346: 'Airbus A340',
    A359: 'Airbus A350', A35K: 'Airbus A350', A388: 'Airbus A380',
    // Airbus narrowbodies
    A318: 'Airbus A318', A319: 'Airbus A319', A320: 'Airbus A320', A321: 'Airbus A321',
    A19N: 'Airbus A319neo', A20N: 'Airbus A320neo family', A21N: 'Airbus A321neo',
    // Embraer
    E135: 'Embraer ERJ 145 family', E145: 'Embraer ERJ 145 family', E170: 'Embraer E-Jet family',
    E175: 'Embraer E-Jet family', E190: 'Embraer E-Jet family', E195: 'Embraer E-Jet family',
    E290: 'Embraer E-Jet E2 family', E295: 'Embraer E-Jet E2 family',
    // Bombardier / CRJ
    CRJ1: 'Bombardier CRJ100/200', CRJ2: 'Bombardier CRJ100/200', CRJ7: 'Bombardier CRJ700 series',
    CRJ9: 'Bombardier CRJ700 series', CRJX: 'Bombardier CRJ700 series',
    // Turboprops
    DH8A: 'De Havilland Canada Dash 8', DH8B: 'De Havilland Canada Dash 8',
    DH8C: 'De Havilland Canada Dash 8', DH8D: 'De Havilland Canada Dash 8',
    AT45: 'ATR 42', AT46: 'ATR 42', AT72: 'ATR 72', AT76: 'ATR 72',
    // Bizjets
    C56X: 'Cessna Citation Excel', C680: 'Cessna Citation Sovereign', C750: 'Cessna Citation X',
    CL30: 'Bombardier Challenger 300', CL35: 'Bombardier Challenger 350',
    CL60: 'Bombardier Challenger 600 series', GL5T: 'Bombardier Global 5000',
    GLEX: 'Bombardier Global Express', GLF4: 'Gulfstream IV', GLF5: 'Gulfstream V',
    GLF6: 'Gulfstream G650', G280: 'Gulfstream G280', GA5C: 'Gulfstream G500/G600',
    GA6C: 'Gulfstream G500/G600', LJ35: 'Learjet 35', LJ45: 'Learjet 45', LJ60: 'Learjet 60',
    F900: 'Dassault Falcon 900', FA7X: 'Dassault Falcon 7X', FA8X: 'Dassault Falcon 8X',
    // Military common
    C130: 'Lockheed C-130 Hercules', C17: 'Boeing C-17 Globemaster III',
    KC35: 'Boeing KC-135 Stratotanker', KC46: 'Boeing KC-46 Pegasus', K35R: 'Boeing KC-135 Stratotanker',
    E3CF: 'Boeing E-3 Sentry', E6B: 'Boeing E-6 Mercury', P8: 'Boeing P-8 Poseidon',
    B52H: 'Boeing B-52 Stratofortress', F16: 'General Dynamics F-16 Fighting Falcon',
    F15: 'McDonnell Douglas F-15 Eagle', F18H: 'Boeing F/A-18E/F Super Hornet',
    F35: 'Lockheed Martin F-35 Lightning II', F22: 'Lockheed Martin F-22 Raptor',
    A10: 'Fairchild Republic A-10 Thunderbolt II', V22: 'Bell Boeing V-22 Osprey',
    C5M: 'Lockheed C-5 Galaxy', C2: 'Grumman C-2 Greyhound',
    EUFI: 'Eurofighter Typhoon', RFAL: 'Dassault Rafale', TORN: 'Panavia Tornado',
    // GA
    C172: 'Cessna 172', C182: 'Cessna 182 Skylane', C206: 'Cessna 206', C208: 'Cessna 208 Caravan',
    C210: 'Cessna 210 Centurion', PA28: 'Piper PA-28 Cherokee', PA32: 'Piper PA-32',
    PA46: 'Piper PA-46 Malibu', BE36: 'Beechcraft Bonanza', BE9L: 'Beechcraft King Air',
    BE20: 'Beechcraft Super King Air', B350: 'Beechcraft King Air 350', PC12: 'Pilatus PC-12',
    PC24: 'Pilatus PC-24', TBM7: 'Daher TBM', TBM8: 'Daher TBM', TBM9: 'Daher TBM',
    // Helicopters
    R44: 'Robinson R44', R22: 'Robinson R22', R66: 'Robinson R66',
    B06: 'Bell 206', B407: 'Bell 407', B412: 'Bell 412',
    EC35: 'Airbus Helicopters H135', EC45: 'Airbus Helicopters H145',
    S76: 'Sikorsky S-76', S92: 'Sikorsky S-92',
    // Russian / other
    SU95: 'Sukhoi Superjet 100', AN12: 'Antonov An-12', AN26: 'Antonov An-26',
    IL76: 'Ilyushin Il-76', IL96: 'Ilyushin Il-96',
    A400: 'Airbus A400M Atlas', C295: 'Airbus C-295',
};

// Module-level cache for Wikipedia thumbnails (persists across re-renders)
const _wikiThumbCache: Record<string, { url: string | null; loading: boolean }> = {};

function useAircraftImage(model: string | undefined): { imgUrl: string | null; wikiUrl: string | null; loading: boolean } {
    const [, forceUpdate] = useState(0);
    const wikiTitle = model ? AIRCRAFT_WIKI[model] : undefined;
    const wikiUrl = wikiTitle ? `https://en.wikipedia.org/wiki/${wikiTitle.replace(/ /g, '_')}` : null;

    useEffect(() => {
        if (!wikiTitle) return;
        const key = wikiTitle;
        if (_wikiThumbCache[key]) return; // Already fetched or in-flight
        _wikiThumbCache[key] = { url: null, loading: true };
        fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(wikiTitle)}`)
            .then(r => r.json())
            .then(d => {
                _wikiThumbCache[key] = { url: d.thumbnail?.source || null, loading: false };
                forceUpdate(n => n + 1);
            })
            .catch(() => {
                _wikiThumbCache[key] = { url: null, loading: false };
                forceUpdate(n => n + 1);
            });
    }, [wikiTitle]);

    if (!wikiTitle) return { imgUrl: null, wikiUrl: null, loading: false };
    const cached = _wikiThumbCache[wikiTitle];
    return { imgUrl: cached?.url || null, wikiUrl, loading: cached?.loading || false };
}


// Vessel type → Wikipedia article for generic ships (carriers have their own wiki field)
const VESSEL_TYPE_WIKI: Record<string, string> = {
    'tanker': 'https://en.wikipedia.org/wiki/Oil_tanker',
    'cargo': 'https://en.wikipedia.org/wiki/Container_ship',
    'passenger': 'https://en.wikipedia.org/wiki/Cruise_ship',
    'yacht': 'https://en.wikipedia.org/wiki/Superyacht',
    'military_vessel': 'https://en.wikipedia.org/wiki/Warship',
};

function NewsFeedInner({ data, selectedEntity, regionDossier, regionDossierLoading }: { data: any, selectedEntity?: { type: string, id: string | number, name?: string, callsign?: string, media_url?: string, extra?: any } | null, regionDossier?: any, regionDossierLoading?: boolean }) {
    const [isMinimized, setIsMinimized] = useState(false);
    const [expandedIndexes, setExpandedIndexes] = useState<number[]>([]);
    const itemRefs = useRef<(HTMLDivElement | null)[]>([]);

    // Intentionally omitting map click triggers for expanding
    // as we now show a contextual pop-up on the map directly.

    const toggleExpand = (idx: number) => {
        if (expandedIndexes.includes(idx)) {
            setExpandedIndexes(expandedIndexes.filter(i => i !== idx));
        } else {
            setExpandedIndexes([...expandedIndexes, idx]);
        }
    }

    const news = data?.news || [];

    // Determine the selected flight's model for Wikipedia thumbnail lookup
    // (must call hook unconditionally — React rules of hooks)
    const selectedFlightModel = (() => {
        if (!selectedEntity) return undefined;
        const { type, id } = selectedEntity;
        let flight: any = null;
        if (type === 'flight') flight = data?.commercial_flights?.[id as number];
        else if (type === 'private_flight') flight = data?.private_flights?.[id as number];
        else if (type === 'private_jet') flight = data?.private_jets?.[id as number];
        else if (type === 'military_flight') flight = data?.military_flights?.[id as number];
        else if (type === 'tracked_flight') flight = data?.tracked_flights?.[id as number];
        return flight?.model;
    })();
    const { imgUrl: aircraftImgUrl, wikiUrl: aircraftWikiUrl, loading: aircraftImgLoading } = useAircraftImage(selectedFlightModel);

    // Region Dossier (right-click intelligence)
    if (selectedEntity?.type === 'region_dossier') {
        const d = regionDossier;
        return (
            <motion.div
                initial={{ y: 50, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.4 }}
                className="w-full bg-black/60 backdrop-blur-md border border-emerald-800 rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(0,255,128,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
            >
                <div className="p-3 border-b border-emerald-500/30 bg-emerald-950/40 flex justify-between items-center">
                    <h2 className="text-xs tracking-widest font-bold text-emerald-400">REGION DOSSIER</h2>
                    <span className="text-[8px] text-gray-500">
                        {selectedEntity.extra ? `${selectedEntity.extra.lat.toFixed(3)}, ${selectedEntity.extra.lng.toFixed(3)}` : ''}
                    </span>
                </div>
                {regionDossierLoading ? (
                    <div className="p-6 flex items-center justify-center">
                        <span className="text-emerald-400 text-[10px] font-mono animate-pulse tracking-widest">COMPILING INTELLIGENCE...</span>
                    </div>
                ) : d && !d.error ? (
                    <div className="p-3 flex flex-col gap-1.5 max-h-[500px] overflow-y-auto styled-scrollbar text-[10px]">
                        {/* COUNTRY */}
                        <div className="text-[9px] text-emerald-500 tracking-widest font-bold border-b border-emerald-900/50 pb-1">COUNTRY LEVEL {d.country?.flag_emoji || ''}</div>
                        <div className="flex justify-between"><span className="text-gray-500">COUNTRY</span><span className="text-white font-bold">{d.country?.name}</span></div>
                        {d.country?.official_name && d.country.official_name !== d.country.name && (
                            <div className="flex justify-between"><span className="text-gray-500">OFFICIAL</span><span className="text-gray-300 text-right max-w-[180px]">{d.country.official_name}</span></div>
                        )}
                        <div className="flex justify-between"><span className="text-gray-500">LEADER</span><span className="text-emerald-400 font-bold">{d.country?.leader}</span></div>
                        <div className="flex justify-between"><span className="text-gray-500">GOVERNMENT</span><span className="text-white font-bold text-right max-w-[180px]">{d.country?.government_type}</span></div>
                        <div className="flex justify-between"><span className="text-gray-500">POPULATION</span><span className="text-white font-bold">{d.country?.population?.toLocaleString()}</span></div>
                        <div className="flex justify-between"><span className="text-gray-500">CAPITAL</span><span className="text-white font-bold">{d.country?.capital}</span></div>
                        <div className="flex justify-between"><span className="text-gray-500">LANGUAGES</span><span className="text-white text-right max-w-[180px]">{d.country?.languages?.join(', ')}</span></div>
                        {d.country?.currencies?.length > 0 && (
                            <div className="flex justify-between"><span className="text-gray-500">CURRENCY</span><span className="text-white text-right max-w-[180px]">{d.country.currencies.join(', ')}</span></div>
                        )}
                        <div className="flex justify-between"><span className="text-gray-500">REGION</span><span className="text-white">{d.country?.subregion || d.country?.region}</span></div>
                        {d.country?.area_km2 > 0 && (
                            <div className="flex justify-between"><span className="text-gray-500">AREA</span><span className="text-white">{d.country.area_km2.toLocaleString()} km²</span></div>
                        )}

                        {/* LOCAL */}
                        {(d.local?.name || d.local?.state) && (
                            <>
                                <div className="text-[9px] text-emerald-500 tracking-widest font-bold border-b border-emerald-900/50 pb-1 mt-2">LOCAL LEVEL</div>
                                {d.local.name && <div className="flex justify-between"><span className="text-gray-500">LOCALITY</span><span className="text-white font-bold">{d.local.name}</span></div>}
                                {d.local.state && <div className="flex justify-between"><span className="text-gray-500">STATE/PROVINCE</span><span className="text-white font-bold">{d.local.state}</span></div>}
                                {d.local.description && <div className="flex justify-between"><span className="text-gray-500">TYPE</span><span className="text-gray-300">{d.local.description}</span></div>}
                                {d.local.summary && (
                                    <div className="mt-1 p-2 bg-black/60 border border-emerald-800/50 rounded text-[9px] text-gray-300 leading-relaxed">
                                        <span className="text-emerald-400 font-bold">&gt;_ INTEL: </span>
                                        {d.local.summary.length > 500 ? d.local.summary.substring(0, 500) + '...' : d.local.summary}
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                ) : d?.error ? (
                    <div className="p-4 text-gray-400 text-[10px]">{d.error}</div>
                ) : (
                    <div className="p-4 text-red-400 text-[10px]">INTEL UNAVAILABLE</div>
                )}
            </motion.div>
        );
    }

    if (selectedEntity?.type === 'tracked_flight') {
        const flight = data?.tracked_flights?.[selectedEntity.id as number];
        if (flight) {
            const callsign = flight.callsign || "UNKNOWN";
            const alertColorMap: Record<string, string> = {
                'pink': 'text-pink-400', 'red': 'text-red-400',
                'darkblue': 'text-blue-400', 'white': 'text-white'
            };
            const alertBorderMap: Record<string, string> = {
                'pink': 'border-pink-500/30', 'red': 'border-red-500/30',
                'darkblue': 'border-blue-500/30', 'white': 'border-gray-500/30'
            };
            const alertBgMap: Record<string, string> = {
                'pink': 'bg-pink-950/40', 'red': 'bg-red-950/40',
                'darkblue': 'bg-blue-950/40', 'white': 'bg-gray-900/40'
            };
            const ac = flight.alert_color || 'white';
            const headerColor = alertColorMap[ac] || 'text-white';
            const borderColor = alertBorderMap[ac] || 'border-gray-500/30';
            const bgColor = alertBgMap[ac] || 'bg-gray-900/40';

            return (
                <motion.div
                    initial={{ y: 50, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.4 }}
                    className={`w-full bg-black/60 backdrop-blur-md border ${ac === 'pink' ? 'border-pink-800' : ac === 'red' ? 'border-red-800' : ac === 'darkblue' ? 'border-blue-800' : 'border-gray-600'} rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(255,20,147,0.2)] pointer-events-auto overflow-hidden flex-shrink-0`}
                >
                    <div className={`p-3 border-b ${borderColor} ${bgColor} flex justify-between items-center`}>
                        <h2 className={`text-xs tracking-widest font-bold ${headerColor} flex items-center gap-2`}>
                            ⚠ TRACKED AIRCRAFT — {flight.alert_category || "ALERT"}
                        </h2>
                        <span className="text-[10px] text-gray-500 font-mono">TRK: {callsign}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">OPERATOR</span>
                            {flight.alert_operator && flight.alert_operator !== "UNKNOWN" ? (
                                <a
                                    href={`https://en.wikipedia.org/wiki/${encodeURIComponent(flight.alert_operator.replace(/ /g, '_'))}`}
                                    target="_blank"
                                    rel="noreferrer"
                                    className={`text-xs font-bold underline ${headerColor} hover:opacity-80 transition-opacity`}
                                    title={`Search Wikipedia for ${flight.alert_operator}`}
                                >
                                    {flight.alert_operator}
                                </a>
                            ) : (
                                <span className={`text-xs font-bold ${headerColor}`}>UNKNOWN</span>
                            )}
                        </div>
                        {/* Owner/Operator Wikipedia photo */}
                        {flight.alert_operator && flight.alert_operator !== "UNKNOWN" && (
                            <div className="border-b border-gray-800 pb-2">
                                <WikiImage
                                    wikiUrl={`https://en.wikipedia.org/wiki/${encodeURIComponent(flight.alert_operator.replace(/ /g, '_'))}`}
                                    label={flight.alert_operator}
                                    maxH="max-h-36"
                                    accent={ac === 'pink' ? 'hover:border-pink-500/50' : ac === 'red' ? 'hover:border-red-500/50' : 'hover:border-cyan-500/50'}
                                />
                            </div>
                        )}
                        {/* Aircraft model Wikipedia photo */}
                        {aircraftImgUrl && (
                            <div className="border-b border-gray-800 pb-2">
                                <a href={aircraftWikiUrl || '#'} target="_blank" rel="noopener noreferrer" className="block">
                                    <img
                                        src={aircraftImgUrl}
                                        alt={AIRCRAFT_WIKI[flight.model] || flight.model}
                                        className={`w-full h-auto max-h-28 object-cover rounded border border-gray-700/50 ${ac === 'pink' ? 'hover:border-pink-500/50' : 'hover:border-cyan-500/50'} transition-colors`}
                                    />
                                </a>
                                {aircraftWikiUrl && (
                                    <a href={aircraftWikiUrl} target="_blank" rel="noopener noreferrer"
                                        className="text-[10px] text-cyan-400 hover:text-cyan-300 underline mt-1 inline-block">
                                        📖 {AIRCRAFT_WIKI[flight.model] || flight.model} — Wikipedia →
                                    </a>
                                )}
                            </div>
                        )}
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">CATEGORY</span>
                            <span className={`text-xs font-bold ${headerColor}`}>{flight.alert_category || "N/A"}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">AIRCRAFT</span>
                            <span className="text-white text-xs font-bold">{flight.alert_type || flight.model || "UNKNOWN"}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">REGISTRATION</span>
                            <span className="text-white text-xs font-bold">{flight.registration || "N/A"}</span>
                        </div>
                        {flight.alert_tag1 && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">INTEL TAG</span>
                                <span className={`text-xs font-bold ${headerColor}`}>{flight.alert_tag1}</span>
                            </div>
                        )}
                        {flight.alert_tag2 && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">SECONDARY</span>
                                <span className="text-white text-xs font-bold">{flight.alert_tag2}</span>
                            </div>
                        )}
                        {flight.alert_tag3 && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">DETAIL</span>
                                <span className="text-gray-400 text-xs">{flight.alert_tag3}</span>
                            </div>
                        )}
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">ALTITUDE</span>
                            <span className="text-white text-xs font-bold">{(Math.round((flight.alt || 0) / 0.3048)).toLocaleString()} ft</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">GROUND SPEED</span>
                            <span className="text-white text-xs font-bold">{flight.speed_knots ? `${flight.speed_knots} kts` : 'N/A'}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">HEADING</span>
                            <span className="text-white text-xs font-bold">{Math.round(flight.heading || 0)}°</span>
                        </div>
                        {flight.squawk && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">SQUAWK</span>
                                <span className={`text-xs font-bold ${flight.squawk === '7700' ? 'text-red-400 animate-pulse' : flight.squawk === '7600' ? 'text-yellow-400' : 'text-white'}`}>{flight.squawk}{flight.squawk === '7700' ? ' ⚠ EMERGENCY' : flight.squawk === '7600' ? ' COMMS LOST' : ''}</span>
                            </div>
                        )}
                        {flight.alert_link && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">REFERENCE</span>
                                <a href={flight.alert_link} target="_blank" rel="noreferrer" className={`text-xs font-bold underline ${headerColor} hover:opacity-80`}>
                                    View Intel Source
                                </a>
                            </div>
                        )}
                        {flight.icao24 && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">FLIGHT RECORD</span>
                                <a href={`https://adsb.lol/?icao=${flight.icao24}`} target="_blank" rel="noreferrer" className={`${headerColor} hover:opacity-80 text-xs font-bold underline`}>
                                    View History Log
                                </a>
                            </div>
                        )}
                    </div>
                </motion.div>
            )
        }
    }

    if (selectedEntity?.type === 'flight' || selectedEntity?.type === 'military_flight' || selectedEntity?.type === 'private_flight' || selectedEntity?.type === 'private_jet') {
        const flightsList = selectedEntity.type === 'flight' ? data?.commercial_flights
            : selectedEntity.type === 'private_flight' ? data?.private_flights
                : selectedEntity.type === 'private_jet' ? data?.private_jets
                    : data?.military_flights;
        const flight = flightsList?.[selectedEntity.id as number];

        if (flight) {
            const callsign = flight.callsign || "UNKNOWN";
            let airline = "UNKNOWN";

            if (selectedEntity.type === 'military_flight') {
                airline = "MILITARY ASSET";
            } else if (selectedEntity.type === 'private_jet') {
                airline = "PRIVATE JET";
            } else if (selectedEntity.type === 'private_flight') {
                airline = "PRIVATE / GA";
            } else if (flight.airline_code) {
                // Use the airline code resolved from adsb.lol routeset API
                const codeMap: Record<string, string> = {
                    "UAL": "UNITED AIRLINES", "DAL": "DELTA AIR LINES", "SWA": "SOUTHWEST AIRLINES",
                    "AAL": "AMERICAN AIRLINES", "BAW": "BRITISH AIRWAYS", "AFR": "AIR FRANCE",
                    "JBU": "JETBLUE AIRWAYS", "NKS": "SPIRIT AIRLINES", "THY": "TURKISH AIRLINES",
                    "UAE": "EMIRATES", "QFA": "QANTAS", "ACA": "AIR CANADA",
                    "FFT": "FRONTIER AIRLINES", "WJA": "WESTJET", "RPA": "REPUBLIC AIRWAYS",
                    "SKW": "SKYWEST AIRLINES", "ENY": "ENVOY AIR", "ASA": "ALASKA AIRLINES",
                    "HAL": "HAWAIIAN AIRLINES", "DLH": "LUFTHANSA", "KLM": "KLM",
                    "EZY": "EASYJET", "RYR": "RYANAIR", "SIA": "SINGAPORE AIRLINES",
                    "CPA": "CATHAY PACIFIC", "ANA": "ALL NIPPON AIRWAYS", "JAL": "JAPAN AIRLINES",
                    "QTR": "QATAR AIRWAYS", "ETD": "ETIHAD AIRWAYS", "SAS": "SAS SCANDINAVIAN"
                };
                airline = codeMap[flight.airline_code] || flight.airline_code;
            } else if (callsign !== "UNKNOWN") {
                airline = "COMMERCIAL FLIGHT";
            }

            return (
                <motion.div
                    initial={{ y: 50, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.4 }}
                    className="w-full bg-black/60 backdrop-blur-md border border-cyan-800 rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(0,128,255,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-cyan-500/30 bg-cyan-950/40 flex justify-between items-center">
                        <h2 className={`text-xs tracking-widest font-bold ${selectedEntity.type === 'military_flight' ? 'text-red-400' : selectedEntity.type === 'private_flight' ? 'text-orange-400' : selectedEntity.type === 'private_jet' ? 'text-purple-400' : 'text-cyan-400'} flex items-center gap-2`}>
                            {selectedEntity.type === 'military_flight' ? "MILITARY BOGEY INTERCEPT" : selectedEntity.type === 'private_flight' ? "PRIVATE TRANSPONDER" : selectedEntity.type === 'private_jet' ? "PRIVATE JET TRANSPONDER" : "COMMERCIAL TRANSPONDER"}
                        </h2>
                        <span className="text-[10px] text-gray-500 font-mono">TRK: {callsign}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">OPERATOR</span>
                            <span className="text-white text-xs font-bold">{airline}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">REGISTRATION</span>
                            <span className="text-white text-xs font-bold">{flight.registration || "N/A"}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">AIRCRAFT MODEL</span>
                            <span className="text-white text-xs font-bold">{flight.model || "UNKNOWN"}</span>
                        </div>
                        {/* Aircraft photo + Wikipedia link */}
                        {(aircraftImgUrl || aircraftImgLoading || aircraftWikiUrl) && (
                            <div className="border-b border-gray-800 pb-3">
                                {aircraftImgLoading && (
                                    <div className="w-full h-24 rounded bg-gray-800/60 animate-pulse" />
                                )}
                                {aircraftImgUrl && (
                                    <a href={aircraftWikiUrl || '#'} target="_blank" rel="noopener noreferrer" className="block">
                                        <img
                                            src={aircraftImgUrl}
                                            alt={AIRCRAFT_WIKI[flight.model] || flight.model}
                                            className="w-full h-auto max-h-32 object-cover rounded border border-gray-700/50 hover:border-cyan-500/50 transition-colors"
                                            style={{ imageRendering: 'auto' }}
                                        />
                                    </a>
                                )}
                                {aircraftWikiUrl && (
                                    <a href={aircraftWikiUrl} target="_blank" rel="noopener noreferrer"
                                        className="text-[10px] text-cyan-400 hover:text-cyan-300 underline mt-1 inline-block">
                                        📖 {AIRCRAFT_WIKI[flight.model] || flight.model} — Wikipedia →
                                    </a>
                                )}
                            </div>
                        )}
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">ALTITUDE</span>
                            <span className="text-white text-xs font-bold">{(Math.round((flight.alt || 0) / 0.3048)).toLocaleString()} ft</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">GROUND SPEED</span>
                            <span className="text-white text-xs font-bold">{flight.speed_knots ? `${flight.speed_knots} kts` : 'N/A'}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">HEADING</span>
                            <span className="text-white text-xs font-bold">{Math.round(flight.heading || 0)}°</span>
                        </div>
                        {flight.squawk && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">SQUAWK</span>
                                <span className={`text-xs font-bold ${flight.squawk === '7700' ? 'text-red-400 animate-pulse' : flight.squawk === '7600' ? 'text-yellow-400' : 'text-white'}`}>{flight.squawk}{flight.squawk === '7700' ? ' ⚠ EMERGENCY' : flight.squawk === '7600' ? ' COMMS LOST' : ''}</span>
                            </div>
                        )}
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">ROUTE</span>
                            <span className="text-cyan-400 text-xs font-bold">{flight.origin_name !== "UNKNOWN" ? `[${flight.origin_name}] → [${flight.dest_name}]` : "UNKNOWN"}</span>
                        </div>
                        {flight.icao24 && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">FLIGHT RECORD</span>
                                <a href={`https://adsb.lol/?icao=${flight.icao24}`} target="_blank" rel="noreferrer" className="text-cyan-400 hover:text-cyan-300 text-xs font-bold underline">
                                    View History Log
                                </a>
                            </div>
                        )}
                    </div>
                </motion.div>
            )
        }
    }

    if (selectedEntity?.type === 'ship') {
        const ship = data?.ships?.[selectedEntity.id as number];
        if (ship) {
            const vesselTypeLabels: Record<string, string> = {
                'tanker': 'TANKER',
                'cargo': 'CARGO VESSEL',
                'passenger': 'PASSENGER / CRUISE',
                'yacht': 'PRIVATE YACHT',
                'military_vessel': 'MILITARY VESSEL',
                'carrier': 'AIRCRAFT CARRIER',
            };
            const typeLabel = vesselTypeLabels[ship.type] || ship.type?.toUpperCase() || 'VESSEL';

            const headerColorMap: Record<string, string> = {
                'tanker': 'text-red-400',
                'cargo': 'text-red-400',
                'passenger': 'text-white',
                'yacht': 'text-blue-400',
                'military_vessel': 'text-yellow-400',
                'carrier': 'text-orange-400',
            };
            const headerColor = headerColorMap[ship.type] || 'text-gray-400';

            const headerTitleMap: Record<string, string> = {
                'tanker': 'AIS TANKER INTERCEPT',
                'cargo': 'AIS CARGO INTERCEPT',
                'passenger': 'AIS PASSENGER VESSEL',
                'yacht': 'AIS YACHT SIGNAL',
                'military_vessel': 'AIS MILITARY VESSEL',
                'carrier': 'CARRIER STRIKE GROUP',
            };
            const headerTitle = headerTitleMap[ship.type] || 'AIS VESSEL SIGNAL';

            return (
                <motion.div
                    initial={{ y: 50, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.4 }}
                    className="w-full bg-black/60 backdrop-blur-md border border-cyan-800 rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(0,128,255,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-cyan-500/30 bg-cyan-950/40 flex justify-between items-center">
                        <h2 className={`text-xs tracking-widest font-bold ${headerColor} flex items-center gap-2`}>
                            {headerTitle}
                        </h2>
                        <span className="text-[10px] text-gray-500 font-mono">MMSI: {ship.mmsi || 'N/A'}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">VESSEL NAME</span>
                            <span className="text-white text-xs font-bold text-right ml-4">{ship.name || 'UNKNOWN'}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">VESSEL TYPE</span>
                            <span className={`text-xs font-bold ${headerColor}`}>{typeLabel}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">FLAG STATE</span>
                            <span className="text-white text-xs font-bold">{ship.country || 'UNKNOWN'}</span>
                        </div>
                        {ship.callsign && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">CALLSIGN</span>
                                <span className="text-white text-xs font-bold">{ship.callsign}</span>
                            </div>
                        )}
                        {ship.imo > 0 && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">IMO NUMBER</span>
                                <span className="text-white text-xs font-bold">{ship.imo}</span>
                            </div>
                        )}
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">DESTINATION</span>
                            <span className={`text-xs font-bold ${ship.destination && ship.destination !== 'UNKNOWN' ? 'text-cyan-400' : 'text-orange-400'}`}>{ship.destination || 'UNKNOWN'}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">SPEED (SOG)</span>
                            <span className="text-white text-xs font-bold">{ship.type === 'carrier' ? 'UNKNOWN' : `${ship.sog || 0} kts`}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">COURSE (COG)</span>
                            <span className="text-white text-xs font-bold">{ship.type === 'carrier' ? 'UNKNOWN' : `${Math.round(ship.cog || 0)}°`}</span>
                        </div>
                        {ship.mmsi && (
                            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                                <span className="text-gray-500 text-[10px]">VESSEL RECORD</span>
                                <a href={`https://www.marinetraffic.com/en/ais/details/ships/mmsi:${ship.mmsi}`} target="_blank" rel="noreferrer" className="text-cyan-400 hover:text-cyan-300 text-xs font-bold underline">
                                    View on MarineTraffic
                                </a>
                            </div>
                        )}
                        {/* Ship/Carrier Wikipedia photo */}
                        {(ship.wiki || VESSEL_TYPE_WIKI[ship.type]) && (
                            <div className="border-t border-gray-800 pt-2">
                                <WikiImage
                                    wikiUrl={ship.wiki || VESSEL_TYPE_WIKI[ship.type]}
                                    label={ship.type === 'carrier' ? ship.name : typeLabel}
                                    maxH="max-h-32"
                                    accent={ship.type === 'carrier' ? 'hover:border-orange-500/50' : 'hover:border-cyan-500/50'}
                                />
                            </div>
                        )}
                    </div>
                </motion.div>
            )
        }
    }

    if (selectedEntity?.type === 'gdelt') {
        const gdeltItem = data?.gdelt?.[selectedEntity.id as number];
        if (gdeltItem && gdeltItem.properties) {
            const props = gdeltItem.properties;
            return (
                <motion.div
                    initial={{ y: 50, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.4 }}
                    className="w-full bg-black/60 backdrop-blur-md border border-orange-800 rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(255,140,0,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-orange-500/30 bg-orange-950/40 flex justify-between items-center">
                        <h2 className="text-xs tracking-widest font-bold text-orange-400 flex items-center gap-2">
                            <AlertTriangle size={14} className="text-orange-400" /> MILITARY INCIDENT CLUSTER
                        </h2>
                        <span className="text-[10px] text-gray-500 font-mono">ID: {selectedEntity.id}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">LOCATION</span>
                            <span className="text-white text-xs font-bold text-right ml-4">{props.name || 'UNKNOWN REGION'}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">ARTICLE COUNT</span>
                            <span className="text-orange-400 text-xs font-bold">{props.count || 1}</span>
                        </div>
                        <div className="flex flex-col gap-2 mt-2">
                            <span className="text-gray-500 text-[10px]">LATEST REPORTS:</span>
                            <div
                                className="text-white text-xs whitespace-normal [&_a]:text-orange-400 [&_a]:underline hover:[&_a]:text-orange-300 [&_br]:mb-2"
                                dangerouslySetInnerHTML={{ __html: props.html || 'No articles available.' }}
                            />
                        </div>
                    </div>
                </motion.div>
            )
        }
    }

    if (selectedEntity?.type === 'liveuamap') {
        const item = data?.liveuamap?.find((l: any) => String(l.id) === String(selectedEntity.id));
        if (item) {
            return (
                <motion.div
                    initial={{ y: 50, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.4 }}
                    className="w-full bg-black/60 backdrop-blur-md border border-yellow-800 rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(255,255,0,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-yellow-500/30 bg-yellow-950/40 flex justify-between items-center">
                        <h2 className="text-xs tracking-widest font-bold text-yellow-400 flex items-center gap-2">
                            <AlertTriangle size={14} className="text-yellow-400" /> REGIONAL TACTICAL EVENT
                        </h2>
                        <span className="text-[10px] text-gray-500 font-mono">ID: {item.id}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">REGION</span>
                            <span className="text-white text-xs font-bold text-right ml-4">{item.region || 'UNKNOWN'}</span>
                        </div>
                        <div className="flex flex-col gap-2 border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">DESCRIPTION</span>
                            <span className="text-yellow-400 text-xs font-bold leading-tight">{item.title}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2 mt-2">
                            <span className="text-gray-500 text-[10px]">REPORTED TIME</span>
                            <span className="text-white text-xs font-bold">{item.timestamp || 'UNKNOWN'}</span>
                        </div>
                        {item.link && (
                            <div className="flex justify-between items-center pb-2 mt-2">
                                <span className="text-gray-500 text-[10px]">SOURCE</span>
                                <a href={item.link} target="_blank" rel="noreferrer" className="text-yellow-400 hover:text-yellow-300 text-xs font-bold underline">
                                    View Liveuamap Report
                                </a>
                            </div>
                        )}
                    </div>
                </motion.div>
            )
        }
    }

    if (selectedEntity?.type === 'news') {
        const item = data?.news?.[selectedEntity.id as number];
        if (item) {
            return (
                <motion.div
                    initial={{ y: 50, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.4 }}
                    className="w-full bg-black/60 backdrop-blur-md border border-red-800 rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(255,0,0,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-red-500/30 bg-red-950/40 flex justify-between items-center">
                        <h2 className="text-xs tracking-widest font-bold text-red-400 flex items-center gap-2">
                            <AlertTriangle size={14} className="text-red-400" /> THREAT INTERCEPT
                        </h2>
                        <span className="text-[10px] text-gray-500 font-mono">LVL: {item.risk_score}/10</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">SOURCE</span>
                            <span className="text-white text-xs font-bold text-right ml-4">{item.source || 'UNKNOWN'}</span>
                        </div>
                        <div className="flex flex-col gap-2 border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">HEADLINE</span>
                            <span className="text-red-400 text-xs font-bold leading-tight">{item.title}</span>
                        </div>
                        {item.machine_assessment && (
                            <div className="mt-2 p-2 bg-black/60 border border-cyan-800/50 rounded-sm text-[9px] text-cyan-400 font-mono leading-tight relative overflow-hidden shadow-[inset_0_0_10px_rgba(0,255,255,0.05)]">
                                <div className="absolute top-0 left-0 w-[2px] h-full bg-cyan-500 animate-pulse"></div>
                                <span className="font-bold text-white">&gt;_ SYS.ANALYSIS: </span>
                                <span className="text-cyan-300 opacity-90">{item.machine_assessment}</span>
                            </div>
                        )}
                        {item.link && (
                            <div className="flex justify-between items-center pb-2 mt-2">
                                <span className="text-gray-500 text-[10px]">REFERENCE</span>
                                <a href={item.link} target="_blank" rel="noreferrer" className="text-red-400 hover:text-red-300 text-xs font-bold underline">
                                    View Source Article
                                </a>
                            </div>
                        )}
                    </div>
                </motion.div>
            )
        }
    }

    if (selectedEntity?.type === 'airport') {
        const apt = data?.airports?.find((a: any) => String(a.id) === String(selectedEntity.id));
        if (apt) {
            return (
                <motion.div
                    initial={{ y: 50, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.4 }}
                    className="w-full bg-black/60 backdrop-blur-md border border-cyan-800 rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(0,128,255,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-cyan-500/30 bg-cyan-950/40 flex justify-between items-center">
                        <h2 className="text-xs tracking-widest font-bold text-cyan-400 flex items-center gap-2">
                            AERONAUTICAL HUB
                        </h2>
                        <span className="text-[10px] text-gray-500 font-mono">IATA: {apt.iata}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">FACILITY NAME</span>
                            <span className="text-white text-[10px] font-bold text-right ml-4 break-words">{apt.name}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">COORDINATES</span>
                            <span className="text-white text-xs font-bold">{apt.lat.toFixed(4)}, {apt.lng.toFixed(4)}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                            <span className="text-gray-500 text-[10px]">STATUS</span>
                            <span className="text-green-400 animate-pulse text-xs font-bold">OPERATIONAL</span>
                        </div>
                    </div>
                </motion.div>
            )
        }
    }

    if (selectedEntity?.type === 'cctv') {
        return (
            <motion.div
                initial={{ y: 50, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.4 }}
                className="w-full bg-black/60 backdrop-blur-md border border-cyan-800 rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(0,128,255,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
            >
                <div className="p-3 border-b border-cyan-500/30 bg-cyan-950/40 flex justify-between items-center">
                    <h2 className="text-xs tracking-widest font-bold text-cyan-400 flex items-center gap-2">
                        <AlertTriangle size={14} className="text-red-400" /> {selectedEntity.extra?.last_updated
                            ? new Date(selectedEntity.extra.last_updated + 'Z').toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZoneName: 'short' }).toUpperCase() + ' — OPTIC INTERCEPT'
                            : 'OPTIC INTERCEPT'}
                    </h2>
                    <span className="text-[10px] text-gray-500 font-mono">ID: {selectedEntity.id}</span>
                </div>
                <div className="relative w-full h-48 bg-black flex items-center justify-center p-1">
                    {(() => {
                        const url = selectedEntity.media_url || '';
                        const mt = selectedEntity.extra?.media_type || (
                            url.includes('.mp4') || url.includes('.webm') ? 'video' :
                                url.includes('.m3u8') || url.includes('hls') ? 'hls' :
                                    url.includes('.mjpg') || url.includes('.mjpeg') || url.includes('mjpg') ? 'mjpeg' :
                                        url.includes('embed') || url.includes('maps/embed') ? 'embed' :
                                            url.includes('mapbox.com') ? 'satellite' : 'image'
                        );

                        if (mt === 'video') return (
                            <video
                                src={url}
                                autoPlay
                                loop
                                muted
                                playsInline
                                className="w-full h-full object-cover border border-cyan-900/50 rounded-sm filter contrast-125 saturate-50"
                            />
                        );
                        if (mt === 'hls') return (
                            <video
                                src={url}
                                autoPlay
                                muted
                                playsInline
                                className="w-full h-full object-cover border border-cyan-900/50 rounded-sm filter contrast-125 saturate-50"
                            />
                        );
                        if (mt === 'embed') return (
                            <iframe
                                src={url}
                                allowFullScreen
                                loading="lazy"
                                className="w-full h-full object-cover border border-cyan-900/50 rounded-sm filter contrast-125 saturate-50"
                            />
                        );
                        if (mt === 'mjpeg') return (
                            <img
                                src={url}
                                alt="MJPEG Feed"
                                className="w-full h-full object-cover border border-cyan-900/50 rounded-sm filter contrast-125 saturate-50"
                                onError={(e) => {
                                    const target = e.target as HTMLImageElement;
                                    target.src = "https://via.placeholder.com/400x300.png?text=FEED+UNAVAILABLE";
                                }}
                            />
                        );
                        // satellite / image — standard img with referrer policy for external tiles
                        return (
                            <img
                                src={url}
                                alt="CCTV Feed"
                                className="w-full h-full object-cover border border-cyan-900/50 rounded-sm filter contrast-125 saturate-50"
                                onError={(e) => {
                                    const target = e.target as HTMLImageElement;
                                    target.src = "https://via.placeholder.com/400x300.png?text=NO+SIGNAL";
                                }}
                            />
                        );
                    })()}

                    {/* Retro UI Overlay for the camera feed */}
                    <div className="absolute top-2 left-2 text-[8px] text-cyan-500 bg-black/50 px-1 py-0.5 rounded">
                        REC // 00:00:00:00
                    </div>
                </div>
                <div className="p-3 bg-black/40 text-[9px] text-cyan-500/70 font-mono tracking-widest flex justify-between items-center">
                    <span>{selectedEntity.name?.toUpperCase() || 'UNKNOWN MOUNT'}</span>
                    <span className="text-red-500 text-right">
                        {selectedEntity.extra?.last_updated
                            ? new Date(selectedEntity.extra.last_updated + 'Z').toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZoneName: 'short' })
                            : ''}
                    </span>
                </div>
            </motion.div>
        );
    }

    return (
        <motion.div
            initial={{ y: 50, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.2 }}
            className={`w-full bg-black/40 backdrop-blur-md border border-gray-800 rounded-xl flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(0,0,0,0.5)] pointer-events-auto overflow-hidden transition-all duration-300 ${isMinimized ? 'h-[50px] flex-shrink-0' : 'flex-1 min-h-0'}`}
        >
            <div
                className="p-3 border-b border-cyan-500/20 bg-cyan-950/20 relative overflow-hidden cursor-pointer hover:bg-cyan-900/30 transition-colors"
                onClick={() => setIsMinimized(!isMinimized)}
            >
                <div className="flex justify-between items-center relative z-10">
                    <h2 className="text-xs tracking-widest font-bold text-cyan-400 flex items-center gap-2">
                        <AlertTriangle size={14} /> GLOBAL THREAT INTERCEPT
                    </h2>
                    <button className="text-cyan-500 hover:text-white transition-colors">
                        {isMinimized ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                    </button>
                </div>

                <AnimatePresence>
                    {!isMinimized && (
                        <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            className="text-[9px] text-cyan-500/80 mt-1 flex items-center justify-between font-bold relative z-10"
                        >
                            <span className="px-1 border border-cyan-500/30">SYS.STATUS: MONITORING</span>
                            <span className="flex items-center gap-1"><Clock size={10} /> {data?.last_updated ? formatTime(data.last_updated) : "SCANNING"}</span>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>

            <AnimatePresence>
                {!isMinimized && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="flex-1 overflow-y-auto p-3 flex flex-col gap-2 styled-scrollbar"
                    >
                        {news.map((item: any, idx: number) => {
                            let bgClass, titleClass, badgeClass;
                            if (item.risk_score >= 9) {
                                bgClass = "bg-red-950/20 border-red-500/30";
                                titleClass = "text-red-300 font-bold";
                                badgeClass = "bg-red-500/10 text-red-400 border-red-500/30";
                            } else if (item.risk_score >= 7) {
                                bgClass = "bg-orange-950/20 border-orange-500/30";
                                titleClass = "text-orange-300 font-bold";
                                badgeClass = "bg-orange-500/10 text-orange-400 border-orange-500/30";
                            } else if (item.risk_score >= 4) {
                                bgClass = "bg-yellow-950/20 border-yellow-500/30";
                                titleClass = "text-yellow-300 font-bold";
                                badgeClass = "bg-yellow-500/10 text-yellow-500 border-yellow-500/30";
                            } else {
                                bgClass = "bg-green-950/20 border-green-500/30";
                                titleClass = "text-green-300 font-medium";
                                badgeClass = "bg-green-500/10 text-green-400 border-green-500/30";
                            }
                            const isExpanded = expandedIndexes.includes(idx);

                            return (
                                <motion.div
                                    key={idx}
                                    ref={(el) => { itemRefs.current[idx] = el; }}
                                    initial={{ opacity: 0, x: -10 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    transition={{ delay: 0.1 + (idx * 0.05) }}
                                    className={`p-2 rounded-sm border-l-[2px] border-r border-t border-b ${bgClass} flex flex-col gap-1 relative group shrink-0`}
                                >
                                    <div className="flex items-center justify-between text-[8px] text-gray-400 uppercase tracking-widest">
                                        <span className="font-bold flex items-center gap-1 text-cyan-600">
                                            &gt;_ {item.source}
                                        </span>
                                        <span>[{item.published ? formatTime(item.published) : ''}]</span>
                                    </div>

                                    <a href={item.link} target="_blank" rel="noreferrer" className={`text-[11px] ${titleClass} hover:text-white transition-colors leading-tight`}>
                                        {item.title}
                                    </a>

                                    {item.machine_assessment && (
                                        <div className="mt-1 p-1.5 bg-black/60 border border-cyan-800/50 rounded-sm text-[8.5px] text-cyan-400 font-mono leading-tight relative overflow-hidden shadow-[inset_0_0_10px_rgba(0,255,255,0.05)]">
                                            <div className="absolute top-0 left-0 w-[2px] h-full bg-cyan-500 animate-pulse"></div>
                                            <span className="font-bold text-white">&gt;_ SYS.ANALYSIS: </span>
                                            <span className="text-cyan-300 opacity-90">{item.machine_assessment}</span>
                                        </div>
                                    )}

                                    <div className="flex justify-between items-end mt-1 relative z-10">
                                        <span className={`text-[8px] font-bold px-1 rounded-sm border ${badgeClass}`}>
                                            LVL: {item.risk_score}/10
                                        </span>
                                        <div className="flex items-center gap-2">
                                            {item.cluster_count > 1 && (
                                                <button onClick={() => toggleExpand(idx)} className="text-[8px] font-bold text-cyan-500 bg-cyan-950/50 hover:text-white hover:bg-cyan-900 border border-cyan-500/30 px-1.5 py-0.5 rounded-sm transition-colors cursor-pointer">
                                                    {isExpanded ? '[- COLLAPSE]' : `[+${item.cluster_count - 1} SOURCES]`}
                                                </button>
                                            )}
                                            {item.coords && (
                                                <span className="text-[8px] text-gray-500 font-mono tracking-tighter">
                                                    {item.coords[0].toFixed(2)}, {item.coords[1].toFixed(2)}
                                                </span>
                                            )}
                                        </div>
                                    </div>

                                    <AnimatePresence>
                                        {isExpanded && item.articles && item.articles.length > 1 && (
                                            <motion.div
                                                initial={{ height: 0, opacity: 0 }}
                                                animate={{ height: "auto", opacity: 1 }}
                                                exit={{ height: 0, opacity: 0 }}
                                                className="mt-2 pt-2 border-t border-cyan-500/20 flex flex-col gap-2 overflow-hidden"
                                            >
                                                {item.articles.slice(1).map((subItem: any, subIdx: number) => (
                                                    <div key={subIdx} className="flex flex-col gap-0.5 pl-2 border-l border-cyan-500/20">
                                                        <div className="flex items-center justify-between text-[7.5px] text-gray-500 uppercase font-bold">
                                                            <span>&gt;_ {subItem.source}</span>
                                                            <span className={
                                                                subItem.risk_score >= 9 ? 'text-red-400' :
                                                                    subItem.risk_score >= 7 ? 'text-orange-400' :
                                                                        subItem.risk_score >= 4 ? 'text-yellow-500' :
                                                                            'text-green-400'
                                                            }>LVL: {subItem.risk_score}/10</span>
                                                        </div>
                                                        <a href={subItem.link} target="_blank" rel="noreferrer" className="text-[10px] text-gray-400 hover:text-white transition-colors leading-tight">
                                                            {subItem.title}
                                                        </a>
                                                    </div>
                                                ))}
                                            </motion.div>
                                        )}
                                    </AnimatePresence>
                                </motion.div>
                            )
                        })}
                        {news.length === 0 && (
                            <div className="text-cyan-500/50 text-[10px] tracking-widest font-bold text-center mt-6 animate-pulse">
                                INITIALIZING SECURE HANDSHAKE...
                            </div>
                        )}
                    </motion.div>
                )}
            </AnimatePresence>


        </motion.div>
    );
}

const NewsFeed = React.memo(NewsFeedInner);
export default NewsFeed;
