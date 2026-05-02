"use client";

import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, Clock, Minus, Plus, ExternalLink, Brain, Loader2 } from 'lucide-react';
import React, { useEffect, useRef, useCallback } from 'react';
import WikiImage from '@/components/WikiImage';
import type { SelectedEntity, RegionDossier, FimiData } from "@/types/dashboard";
import { useDataKeys } from '@/hooks/useDataStore';
import { lookupShodanHost } from '@/lib/shodanClient';
import type { ShodanHost } from '@/types/shodan';

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
    // Military — US
    C130: 'Lockheed C-130 Hercules', C30J: 'Lockheed Martin C-130J Super Hercules',
    C17: 'Boeing C-17 Globemaster III',
    KC35: 'Boeing KC-135 Stratotanker', KC46: 'Boeing KC-46 Pegasus', K35R: 'Boeing KC-135 Stratotanker',
    E3CF: 'Boeing E-3 Sentry', E3TF: 'Boeing E-3 Sentry', E6B: 'Boeing E-6 Mercury',
    P8: 'Boeing P-8 Poseidon', P8A: 'Boeing P-8 Poseidon',
    B52H: 'Boeing B-52 Stratofortress', B1: 'Rockwell B-1 Lancer', B1B: 'Rockwell B-1 Lancer',
    B2: 'Northrop Grumman B-2 Spirit', B21: 'Northrop Grumman B-21 Raider',
    F16: 'General Dynamics F-16 Fighting Falcon', F16C: 'General Dynamics F-16 Fighting Falcon',
    F15: 'McDonnell Douglas F-15 Eagle', F15E: 'McDonnell Douglas F-15E Strike Eagle',
    F18: 'Boeing F/A-18E/F Super Hornet', F18H: 'Boeing F/A-18E/F Super Hornet',
    FA18: 'Boeing F/A-18E/F Super Hornet',
    F35: 'Lockheed Martin F-35 Lightning II', F22: 'Lockheed Martin F-22 Raptor',
    A10: 'Fairchild Republic A-10 Thunderbolt II', V22: 'Bell Boeing V-22 Osprey',
    C5M: 'Lockheed C-5 Galaxy', C5: 'Lockheed C-5 Galaxy', C2: 'Grumman C-2 Greyhound',
    C40: 'Boeing C-40 Clipper', C37: 'Gulfstream V',
    E4B: 'Boeing E-4', E8: 'Northrop Grumman E-8 Joint STARS',
    RC135: 'Boeing RC-135', RC35: 'Boeing RC-135', R135: 'Boeing RC-135',
    U2: 'Lockheed U-2', U2S: 'Lockheed U-2',
    RQ4: 'Northrop Grumman RQ-4 Global Hawk', MQ9: 'General Atomics MQ-9 Reaper',
    MQ4C: 'Northrop Grumman MQ-4C Triton',
    H60: 'Sikorsky UH-60 Black Hawk', MH60: 'Sikorsky SH-60 Seahawk',
    CH47: 'Boeing CH-47 Chinook', H47: 'Boeing CH-47 Chinook',
    AH64: 'Boeing AH-64 Apache', H64: 'Boeing AH-64 Apache',
    EP3: 'Lockheed EP-3', P3: 'Lockheed P-3 Orion',
    T38: 'Northrop T-38 Talon', T6: 'Beechcraft T-6 Texan II',
    // Military — NATO / Allied
    EUFI: 'Eurofighter Typhoon', RFAL: 'Dassault Rafale', TORN: 'Panavia Tornado',
    GROB: 'Grob G 120TP', GRIS: 'Saab JAS 39 Gripen', J39: 'Saab JAS 39 Gripen',
    F4: 'McDonnell Douglas F-4 Phantom II', HAWK: 'BAE Systems Hawk',
    MRTT: 'Airbus A330 MRTT', A310M: 'Airbus A310 MRTT',
    P1: 'Kawasaki P-1', C1: 'Kawasaki C-1', C2JP: 'Kawasaki C-2 (aircraft)',
    // Military — Russian
    SU27: 'Sukhoi Su-27', SU30: 'Sukhoi Su-30', SU34: 'Sukhoi Su-34', SU35: 'Sukhoi Su-35',
    SU57: 'Sukhoi Su-57', MIG29: 'Mikoyan MiG-29', MIG31: 'Mikoyan MiG-31',
    TU95: 'Tupolev Tu-95', TU160: 'Tupolev Tu-160', TU22M: 'Tupolev Tu-22M',
    IL78: 'Ilyushin Il-78', A50: 'Beriev A-50',
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

/**
 * Maps plane_alert_db `ac_type` substrings → correct Wikipedia article titles.
 * The ac_type field often includes variant suffixes (e.g. "KC-135R", "F-16AM")
 * that don't correspond to Wikipedia article names. Checked in order — first match wins.
 */
const AC_TYPE_WIKI_OVERRIDES: [RegExp, string][] = [
    // US Fighters & Attack
    [/F-?22/i, 'Lockheed Martin F-22 Raptor'],
    [/F-?35/i, 'Lockheed Martin F-35 Lightning II'],
    [/F-?16/i, 'General Dynamics F-16 Fighting Falcon'],
    [/F-?15E/i, 'McDonnell Douglas F-15E Strike Eagle'],
    [/F-?15/i, 'McDonnell Douglas F-15 Eagle'],
    [/F.?\/A.?18/i, 'Boeing F/A-18E/F Super Hornet'],
    [/F-?18/i, 'Boeing F/A-18E/F Super Hornet'],
    [/A-?10/i, 'Fairchild Republic A-10 Thunderbolt II'],
    // US Bombers
    [/B-?52/i, 'Boeing B-52 Stratofortress'],
    [/B-?1B|B-?1\b/i, 'Rockwell B-1 Lancer'],
    [/B-?2\b/i, 'Northrop Grumman B-2 Spirit'],
    [/B-?21/i, 'Northrop Grumman B-21 Raider'],
    // US Tankers & Transport
    [/KC-?135/i, 'Boeing KC-135 Stratotanker'],
    [/KC-?46/i, 'Boeing KC-46 Pegasus'],
    [/KC-?10/i, 'McDonnell Douglas KC-10 Extender'],
    [/C-?17/i, 'Boeing C-17 Globemaster III'],
    [/C-?130J/i, 'Lockheed Martin C-130J Super Hercules'],
    [/C-?130/i, 'Lockheed C-130 Hercules'],
    [/C-?5/i, 'Lockheed C-5 Galaxy'],
    [/V-?22/i, 'Bell Boeing V-22 Osprey'],
    // US ISR & Special
    [/P-?8/i, 'Boeing P-8 Poseidon'],
    [/E-?3/i, 'Boeing E-3 Sentry'],
    [/E-?6/i, 'Boeing E-6 Mercury'],
    [/E-?4/i, 'Boeing E-4'],
    [/E-?8|Joint.?STARS/i, 'Northrop Grumman E-8 Joint STARS'],
    [/RC-?135/i, 'Boeing RC-135'],
    [/EP-?3/i, 'Lockheed EP-3'],
    [/P-?3/i, 'Lockheed P-3 Orion'],
    [/U-?2/i, 'Lockheed U-2'],
    [/RQ-?4|Global.?Hawk/i, 'Northrop Grumman RQ-4 Global Hawk'],
    [/MQ-?9|Reaper/i, 'General Atomics MQ-9 Reaper'],
    [/MQ-?4C|Triton/i, 'Northrop Grumman MQ-4C Triton'],
    // US Helicopters
    [/AH-?64|Apache/i, 'Boeing AH-64 Apache'],
    [/CH-?47|Chinook/i, 'Boeing CH-47 Chinook'],
    [/UH-?60|Black.?Hawk/i, 'Sikorsky UH-60 Black Hawk'],
    [/SH-?60|MH-?60|Seahawk/i, 'Sikorsky SH-60 Seahawk'],
    // NATO / Allied
    [/Eurofighter|Typhoon/i, 'Eurofighter Typhoon'],
    [/Rafale/i, 'Dassault Rafale'],
    [/Tornado/i, 'Panavia Tornado'],
    [/Gripen/i, 'Saab JAS 39 Gripen'],
    [/A400M/i, 'Airbus A400M Atlas'],
    [/A330\s*MRTT|Voyager/i, 'Airbus A330 MRTT'],
    [/Hawk\s*T/i, 'BAE Systems Hawk'],
    // Russian
    [/Su-?57/i, 'Sukhoi Su-57'],
    [/Su-?35/i, 'Sukhoi Su-35'],
    [/Su-?34/i, 'Sukhoi Su-34'],
    [/Su-?30/i, 'Sukhoi Su-30'],
    [/Su-?27/i, 'Sukhoi Su-27'],
    [/Su-?25/i, 'Sukhoi Su-25'],
    [/MiG-?31/i, 'Mikoyan MiG-31'],
    [/MiG-?29/i, 'Mikoyan MiG-29'],
    [/Tu-?160/i, 'Tupolev Tu-160'],
    [/Tu-?95/i, 'Tupolev Tu-95'],
    [/Tu-?22M/i, 'Tupolev Tu-22M'],
    [/Il-?76/i, 'Ilyushin Il-76'],
    [/Il-?78/i, 'Ilyushin Il-78'],
    [/A-?50\b/i, 'Beriev A-50'],
    // Chinese
    [/J-?20/i, 'Chengdu J-20'],
    [/J-?16/i, 'Shenyang J-16'],
    [/J-?10/i, 'Chengdu J-10'],
    [/Y-?20/i, 'Xi\'an Y-20'],
];

/** Resolve a plane_alert_db ac_type string to a Wikipedia article title. */
function resolveAcTypeWiki(acType: string): string | null {
    for (const [pattern, wikiTitle] of AC_TYPE_WIKI_OVERRIDES) {
        if (pattern.test(acType)) return wikiTitle;
    }
    return null;
}

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

function NewsFeedInner({ selectedEntity, regionDossier, regionDossierLoading, onArticleClick }: { selectedEntity?: SelectedEntity | null, regionDossier?: RegionDossier | null, regionDossierLoading?: boolean, onArticleClick?: (idx: number, lat?: number, lng?: number, title?: string) => void }) {
    const data = useDataKeys([
      'news', 'fimi', 'commercial_flights', 'private_flights', 'private_jets',
      'military_flights', 'tracked_flights', 'ships', 'gdelt', 'liveuamap',
      'airports', 'last_updated', 'threat_level',
    ] as const);
    const [isMinimized, setIsMinimized] = useState(false);
    const [expandedIndexes, setExpandedIndexes] = useState<number[]>([]);
    const [fimiExpanded, setFimiExpanded] = useState(false);
    const [aiSummaryOpen, setAiSummaryOpen] = useState(false);
    const [aiSummary, setAiSummary] = useState<any>(null);
    const [aiSummaryLoading, setAiSummaryLoading] = useState(false);
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
    const fimi: FimiData | undefined = data?.fimi;

    // Cross-reference: check if a news article title matches any FIMI disinfo keywords
    const fimiKeywords = useMemo(() => fimi?.disinfo_keywords || [], [fimi?.disinfo_keywords]);
    const checkDisinfoLinked = useCallback((title: string): boolean => {
        if (fimiKeywords.length === 0) return false;
        const titleLower = title.toLowerCase();
        return fimiKeywords.some(kw => titleLower.includes(kw));
    }, [fimiKeywords]);

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
    const [shodanDetail, setShodanDetail] = useState<ShodanHost | null>(null);
    const [shodanLoading, setShodanLoading] = useState(false);
    const [shodanError, setShodanError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        const host = (selectedEntity?.extra || {}) as Record<string, any>;
        const ip = selectedEntity?.type === 'shodan_host' ? String(host.ip || '').trim() : '';
        if (!ip) {
            setShodanDetail(null);
            setShodanLoading(false);
            setShodanError(null);
            return;
        }
        if (Array.isArray(host.services) && host.services.length > 0) {
            setShodanDetail(host as unknown as ShodanHost);
            setShodanLoading(false);
            setShodanError(null);
            return;
        }
        setShodanLoading(true);
        setShodanError(null);
        lookupShodanHost(ip)
            .then((resp) => {
                if (cancelled) return;
                setShodanDetail(resp.host);
            })
            .catch((err) => {
                if (cancelled) return;
                setShodanError(err instanceof Error ? err.message : 'Failed to load host detail');
            })
            .finally(() => {
                if (cancelled) return;
                setShodanLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [selectedEntity]);

    // Region Dossier (right-click intelligence)
    if (selectedEntity?.type === 'region_dossier') {
        const d = regionDossier;
        return (
            <motion.div
                initial={{ y: 50, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.4 }}
                className="w-full bg-black/60 backdrop-blur-sm border border-emerald-800 flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(0,255,128,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
            >
                <div className="p-3 border-b border-emerald-500/30 bg-emerald-950/40 flex justify-between items-center">
                    <h2 className="text-sm tracking-widest font-bold text-emerald-400">REGION DOSSIER</h2>
                    <span className="text-[10px] text-[var(--text-muted)]">
                        {selectedEntity.extra ? `${selectedEntity.extra.lat.toFixed(3)}, ${selectedEntity.extra.lng.toFixed(3)}` : ''}
                    </span>
                </div>
                {regionDossierLoading ? (
                    <div className="p-6 flex items-center justify-center">
                        <span className="text-emerald-400 text-[12px] font-mono tracking-widest">COMPILING INTELLIGENCE...</span>
                    </div>
                ) : d && !d.error ? (
                    <div className="p-3 flex flex-col gap-2 max-h-[500px] overflow-y-auto styled-scrollbar text-[12px]">
                        {d.warning && (
                            <div className="mb-2 p-2 bg-amber-950/40 border border-amber-800/50 text-[11px] text-amber-300 leading-relaxed">
                                {d.warning}
                            </div>
                        )}
                        {/* COUNTRY */}
                        <div className="text-[11px] text-emerald-500 tracking-widest font-bold border-b border-emerald-900/50 pb-1">COUNTRY LEVEL {d.country?.flag_emoji || ''}</div>
                        <div className="flex justify-between"><span className="text-[var(--text-muted)]">COUNTRY</span><span className="text-[var(--text-primary)] font-bold">{d.country?.name}</span></div>
                        {d.country?.official_name && d.country.official_name !== d.country.name && (
                            <div className="flex justify-between"><span className="text-[var(--text-muted)]">OFFICIAL</span><span className="text-[var(--text-secondary)] text-right max-w-[180px]">{d.country.official_name}</span></div>
                        )}
                        <div className="flex justify-between"><span className="text-[var(--text-muted)]">LEADER</span><span className="text-emerald-400 font-bold">{d.country?.leader}</span></div>
                        <div className="flex justify-between"><span className="text-[var(--text-muted)]">GOVERNMENT</span><span className="text-[var(--text-primary)] font-bold text-right max-w-[180px]">{d.country?.government_type}</span></div>
                        <div className="flex justify-between"><span className="text-[var(--text-muted)]">POPULATION</span><span className="text-[var(--text-primary)] font-bold">{d.country?.population?.toLocaleString()}</span></div>
                        <div className="flex justify-between"><span className="text-[var(--text-muted)]">CAPITAL</span><span className="text-[var(--text-primary)] font-bold">{d.country?.capital}</span></div>
                        <div className="flex justify-between"><span className="text-[var(--text-muted)]">LANGUAGES</span><span className="text-[var(--text-primary)] text-right max-w-[180px]">{d.country?.languages?.join(', ')}</span></div>
                        {d.country?.currencies?.length > 0 && (
                            <div className="flex justify-between"><span className="text-[var(--text-muted)]">CURRENCY</span><span className="text-[var(--text-primary)] text-right max-w-[180px]">{d.country.currencies.join(', ')}</span></div>
                        )}
                        <div className="flex justify-between"><span className="text-[var(--text-muted)]">REGION</span><span className="text-[var(--text-primary)]">{d.country?.subregion || d.country?.region}</span></div>
                        {d.country?.area_km2 > 0 && (
                            <div className="flex justify-between"><span className="text-[var(--text-muted)]">AREA</span><span className="text-[var(--text-primary)]">{d.country.area_km2.toLocaleString()} km²</span></div>
                        )}

                        {/* LOCAL */}
                        {(d.local?.name || d.local?.state) && (
                            <>
                                <div className="text-[11px] text-emerald-500 tracking-widest font-bold border-b border-emerald-900/50 pb-1 mt-2">LOCAL LEVEL</div>
                                {d.local.name && <div className="flex justify-between"><span className="text-[var(--text-muted)]">LOCALITY</span><span className="text-[var(--text-primary)] font-bold">{d.local.name}</span></div>}
                                {d.local.state && <div className="flex justify-between"><span className="text-[var(--text-muted)]">STATE/PROVINCE</span><span className="text-[var(--text-primary)] font-bold">{d.local.state}</span></div>}
                                {d.local.description && <div className="flex justify-between"><span className="text-[var(--text-muted)]">TYPE</span><span className="text-[var(--text-secondary)]">{d.local.description}</span></div>}
                                {d.local.summary && (
                                    <div className="mt-1 p-2 bg-black/60 border border-emerald-800/50 text-[11px] text-[var(--text-secondary)] leading-relaxed">
                                        <span className="text-emerald-400 font-bold">&gt;_ INTEL: </span>
                                        {d.local.summary.length > 500 ? d.local.summary.substring(0, 500) + '...' : d.local.summary}
                                    </div>
                                )}
                            </>
                        )}

                        {/* Sentinel-2 imagery now shown as map popup — see MaplibreViewer */}
                    </div>
                ) : d?.error ? (
                    <div className="p-4 text-[var(--text-secondary)] text-[12px]">{d.error}</div>
                ) : (
                    <div className="p-4 text-red-400 text-[12px]">INTEL UNAVAILABLE</div>
                )}
            </motion.div>
        );
    }

    if (selectedEntity?.type === 'shodan_host') {
        const baseHost = (selectedEntity.extra || {}) as Record<string, any>;
        const host = (shodanDetail || baseHost) as Record<string, any>;
        const portLabel = host.port ? `${host.ip}:${host.port}` : (host.ip || selectedEntity.name || 'UNKNOWN HOST');
        return (
            <motion.div
                initial={{ y: 50, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.4 }}
                className="w-full bg-black/60 backdrop-blur-sm border border-green-800 flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(34,197,94,0.16)] pointer-events-auto overflow-hidden flex-shrink-0"
            >
                <div className="p-3 border-b border-green-500/30 bg-green-950/30 flex justify-between items-center">
                    <h2 className="text-xs tracking-widest font-bold text-green-400 flex items-center gap-2">
                        SHODAN HOST DOSSIER
                    </h2>
                    <span className="text-[10px] text-green-300 font-mono">{portLabel}</span>
                </div>

                <div className="p-4 flex flex-col gap-2 text-[10px]">
                    <div className="text-[11px] text-green-500 tracking-widest font-bold border-b border-green-900/50 pb-1">
                        ATTRIBUTION
                    </div>
                    <div className="text-green-300/90">
                        Data from Shodan · Operator-supplied API key · Local session overlay
                    </div>
                    {shodanLoading && (
                        <div className="mt-2 text-green-500/80">Loading full host detail...</div>
                    )}
                    {shodanError && (
                        <div className="mt-2 border border-red-900/40 bg-red-950/20 p-2 text-red-300">
                            {shodanError}
                        </div>
                    )}

                    <div className="text-[11px] text-green-500 tracking-widest font-bold border-b border-green-900/50 pb-1 mt-2">
                        HOST
                    </div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">IP</span><span className="text-green-300 font-bold">{host.ip || 'UNKNOWN'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">PORT</span><span className="text-[var(--text-primary)]">{host.port || host.ports?.[0] || 'UNKNOWN'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">ORG</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.org || 'UNKNOWN'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">ASN</span><span className="text-[var(--text-primary)]">{host.asn || 'UNKNOWN'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">ISP</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.isp || 'UNKNOWN'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">OS</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.os || 'UNKNOWN'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">PRODUCT</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.product || host.transport || 'UNKNOWN'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">SEEN</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.timestamp || host.services?.[0]?.timestamp || 'UNKNOWN'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">LOCATION</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.location_label || host.country_name || 'UNMAPPED'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">COORDS</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.lat != null && host.lng != null ? `${Number(host.lat).toFixed(4)}, ${Number(host.lng).toFixed(4)}` : 'UNMAPPED'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">HOSTNAMES</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.hostnames?.length ? host.hostnames.join(', ') : 'NONE'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">DOMAINS</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.domains?.length ? host.domains.join(', ') : 'NONE'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">TAGS</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.tags?.length ? host.tags.join(', ') : 'NONE'}</span></div>
                    <div className="flex justify-between"><span className="text-[var(--text-muted)]">VULNS</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.vulns?.length ? host.vulns.join(', ') : 'NONE'}</span></div>
                    {Array.isArray(host.ports) && host.ports.length > 0 && (
                        <div className="flex justify-between"><span className="text-[var(--text-muted)]">ALL PORTS</span><span className="text-[var(--text-primary)] text-right max-w-[190px]">{host.ports.slice(0, 20).join(', ')}</span></div>
                    )}
                    {Array.isArray(host.services) && host.services.length > 0 && (
                        <>
                            <div className="text-[11px] text-green-500 tracking-widest font-bold border-b border-green-900/50 pb-1 mt-2">
                                SERVICES
                            </div>
                            <div className="flex flex-col gap-2">
                                {host.services.slice(0, 8).map((service: Record<string, any>, idx: number) => (
                                    <div key={`${service.port || 'svc'}-${idx}`} className="border border-green-900/40 bg-black/40 p-2">
                                        <div className="flex justify-between text-[10px]">
                                            <span className="text-green-300 font-bold">
                                                {service.port || '?'} / {service.transport || 'tcp'}
                                            </span>
                                            <span className="text-[var(--text-muted)]">{service.timestamp || 'UNKNOWN'}</span>
                                        </div>
                                        <div className="mt-1 text-[var(--text-primary)]">
                                            {service.product || 'Unknown service'}
                                        </div>
                                        {service.tags?.length > 0 && (
                                            <div className="mt-1 text-[11px] text-green-500/80">
                                                TAGS: {service.tags.join(', ')}
                                            </div>
                                        )}
                                        {service.banner_excerpt && (
                                            <div className="mt-1 text-[11px] text-green-300/90 leading-relaxed">
                                                {service.banner_excerpt}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                    {host.data_snippet && (
                        <div className="mt-2 border border-green-900/50 bg-black/50 p-2 text-[11px] text-green-300/90 leading-relaxed">
                            <span className="text-green-400 font-bold">&gt;_ BANNER: </span>
                            {host.data_snippet}
                        </div>
                    )}
                </div>
            </motion.div>
        );
    }

    if (selectedEntity?.type === 'tracked_flight') {
        const flight = data?.tracked_flights?.find((f: any) => f.icao24 === selectedEntity.id);
        if (flight) {
            const callsign = flight.callsign || "UNKNOWN";
            const alertColorMap: Record<string, string> = {
                '#ff1493': 'text-[#ff1493]', pink: 'text-[#ff1493]', red: 'text-red-400', yellow: 'text-yellow-400',
                blue: 'text-blue-400', orange: 'text-orange-400', '#32cd32': 'text-[#32cd32]', purple: 'text-purple-400',
                black: 'text-gray-400', white: 'text-white'
            };
            const alertBorderMap: Record<string, string> = {
                '#ff1493': 'border-[#ff1493]/30', pink: 'border-[#ff1493]/30', red: 'border-red-500/30', yellow: 'border-yellow-500/30',
                blue: 'border-blue-500/30', orange: 'border-orange-500/30', '#32cd32': 'border-[#32cd32]/30', purple: 'border-purple-500/30',
                black: 'border-gray-500/30', white: 'border-[var(--border-primary)]/30'
            };
            const alertBgMap: Record<string, string> = {
                '#ff1493': 'bg-[#ff1493]/10', pink: 'bg-[#ff1493]/10', red: 'bg-red-950/40', yellow: 'bg-yellow-950/40',
                blue: 'bg-blue-950/40', orange: 'bg-orange-950/40', '#32cd32': 'bg-lime-950/40', purple: 'bg-purple-950/40',
                black: 'bg-gray-900/40', white: 'bg-[var(--bg-panel)]'
            };
            const ac = flight.alert_color || 'white';
            const headerColor = alertColorMap[ac] || 'text-white';
            const borderColor = alertBorderMap[ac] || 'border-[var(--border-primary)]/30';
            const bgColor = alertBgMap[ac] || 'bg-[var(--bg-panel)]';

            const shadowColor = (ac === 'pink' || ac === '#ff1493') ? 'rgba(255,20,147,0.4)'
                : ac === 'red' ? 'rgba(255,32,32,0.2)'
                : ac === 'yellow' ? 'rgba(255,255,0,0.2)'
                : ac === 'blue' ? 'rgba(59,130,246,0.2)'
                : ac === 'orange' ? 'rgba(255,140,0,0.3)'
                : ac === '#32cd32' ? 'rgba(50,205,50,0.2)'
                : ac === 'purple' ? 'rgba(155,89,182,0.2)'
                : 'rgba(255,255,255,0.1)';

            return (
                <motion.div
                    initial={{ y: 50, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.4 }}
                    className={`w-full bg-black/60 backdrop-blur-sm border ${(ac === 'pink' || ac === '#ff1493') ? 'border-[#ff1493]' : ac === 'red' ? 'border-red-800' : ac === 'yellow' ? 'border-yellow-800' : ac === 'blue' ? 'border-blue-800' : ac === 'orange' ? 'border-orange-800' : ac === '#32cd32' ? 'border-lime-800' : ac === 'purple' ? 'border-purple-800' : 'border-[var(--border-secondary)]'} flex flex-col z-10 font-mono shadow-[0_4px_30px_${shadowColor}] pointer-events-auto overflow-hidden flex-shrink-0`}
                >
                    <div className={`p-3 border-b ${borderColor} ${bgColor} flex justify-between items-center`}>
                        <h2 className={`text-xs tracking-widest font-bold ${headerColor} flex items-center gap-2`}>
                            ⚠ TRACKED AIRCRAFT — {flight.alert_category || "ALERT"}
                        </h2>
                        <span className="text-[10px] text-[var(--text-muted)] font-mono">TRK: {callsign}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">OPERATOR</span>
                            {flight.alert_operator && flight.alert_operator !== "UNKNOWN" ? (() => {
                                const wikiSlug = flight.alert_wiki || flight.alert_operator.replace(/\s*\(.*?\)\s*/g, '').trim().replace(/ /g, '_');
                                const wikiHref = `https://en.wikipedia.org/wiki/${encodeURIComponent(wikiSlug)}`;
                                const operatorHref = flight.alert_link || wikiHref;
                                return (
                                    <a
                                        href={operatorHref}
                                        target="_blank"
                                        rel="noreferrer"
                                        className={`text-xs font-bold underline ${headerColor} hover:opacity-80 transition-opacity`}
                                        title={flight.alert_link ? `View reference for ${flight.alert_operator}` : `Search Wikipedia for ${flight.alert_operator}`}
                                    >
                                        {flight.alert_operator}
                                    </a>
                                );
                            })() : (
                                <span className={`text-xs font-bold ${headerColor}`}>UNKNOWN</span>
                            )}
                        </div>
                        {/* Primary image: military → aircraft model photo; everything else → operator/company photo */}
                        {(() => {
                            // Categories where the aircraft model should be the primary image
                            const MILITARY_CATEGORIES = new Set([
                                'USAF', 'RAF', 'GAF', 'Royal Navy Fleet Air Arm', 'Army Air Corps',
                                'Other Air Forces', 'Other Navies', 'United States Navy',
                                'United States Marine Corps', 'Special Forces', 'Gunship', 'Nuclear',
                                'UAV', 'Coastguard', 'Da Comrade', 'Hired Gun', 'Oxcart', 'Zoomies',
                                'Toy Soldiers', 'Police Forces', 'Flying Doctors', 'Aerial Firefighter',
                            ]);
                            const cat = flight.alert_category || '';
                            const isMilitary = MILITARY_CATEGORIES.has(cat);

                            // Resolve aircraft model wiki info (for link or image depending on context)
                            let acWikiTitle = flight.model ? AIRCRAFT_WIKI[flight.model] : undefined;
                            if (!acWikiTitle && flight.alert_type && flight.alert_type !== "UNKNOWN") {
                                acWikiTitle = resolveAcTypeWiki(flight.alert_type) || flight.alert_type;
                            }
                            const acModelWikiUrl = acWikiTitle ? `https://en.wikipedia.org/wiki/${acWikiTitle.replace(/ /g, '_')}` : null;

                            // Resolve operator wiki info
                            const operatorSlug = flight.alert_wiki || (flight.alert_operator && flight.alert_operator !== "UNKNOWN"
                                ? flight.alert_operator.replace(/\s*\(.*?\)\s*/g, '').trim().replace(/ /g, '_')
                                : null);
                            const operatorWikiUrl = operatorSlug ? `https://en.wikipedia.org/wiki/${encodeURIComponent(operatorSlug)}` : null;

                            const accentClass = ac === 'pink' ? 'hover:border-pink-500/50' : ac === 'red' ? 'hover:border-red-500/50' : 'hover:border-cyan-500/50';

                            if (isMilitary) {
                                // MILITARY: aircraft model photo as primary image, operator as text link above
                                return acModelWikiUrl ? (
                                    <div className="border-b border-[var(--border-primary)] pb-2">
                                        <WikiImage
                                            wikiUrl={acModelWikiUrl}
                                            label={acWikiTitle || flight.model}
                                            maxH="max-h-36"
                                            accent={accentClass}
                                        />
                                    </div>
                                ) : null;
                            }

                            // NON-MILITARY (tracked jets, celebs, companies, airlines):
                            // Operator/company photo as primary image
                            // Aircraft model as a text link below
                            return (
                                <>
                                    {operatorWikiUrl && (
                                        <div className="border-b border-[var(--border-primary)] pb-2">
                                            <WikiImage
                                                wikiUrl={operatorWikiUrl}
                                                label={flight.alert_operator || 'Operator'}
                                                maxH="max-h-36"
                                                accent={accentClass}
                                            />
                                        </div>
                                    )}
                                    {acModelWikiUrl && (
                                        <div className="border-b border-[var(--border-primary)] pb-1">
                                            <a href={acModelWikiUrl} target="_blank" rel="noopener noreferrer"
                                                className="text-[10px] text-cyan-400 hover:text-cyan-300 underline inline-block">
                                                📖 {acWikiTitle || flight.alert_type || flight.model} — Wikipedia →
                                            </a>
                                        </div>
                                    )}
                                </>
                            );
                        })()}
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">CATEGORY</span>
                            <span className={`text-xs font-bold ${headerColor}`}>{flight.alert_category || "N/A"}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">AIRCRAFT</span>
                            {(() => {
                                const acLabel = flight.alert_type || flight.model || "UNKNOWN";
                                let acLink = flight.model ? AIRCRAFT_WIKI[flight.model] : undefined;
                                if (!acLink && flight.alert_type && flight.alert_type !== "UNKNOWN") {
                                    acLink = resolveAcTypeWiki(flight.alert_type) || undefined;
                                }
                                const acHref = acLink ? `https://en.wikipedia.org/wiki/${acLink.replace(/ /g, '_')}` : null;
                                return acHref ? (
                                    <a href={acHref} target="_blank" rel="noreferrer"
                                        className="text-xs font-bold text-cyan-400 hover:text-cyan-300 underline transition-opacity">
                                        {acLabel}
                                    </a>
                                ) : (
                                    <span className="text-[var(--text-primary)] text-xs font-bold">{acLabel}</span>
                                );
                            })()}
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">REGISTRATION</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{flight.registration || "N/A"}</span>
                        </div>
                        {flight.alert_tags && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">INTEL TAGS</span>
                                <span className={`text-xs font-bold text-right max-w-[200px] ${headerColor}`}>{flight.alert_tags}</span>
                            </div>
                        )}
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">ALTITUDE</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{(Math.round((flight.alt || 0) / 0.3048)).toLocaleString()} ft</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">GROUND SPEED</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{flight.speed_knots ? `${flight.speed_knots} kts` : 'N/A'}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">HEADING</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{Math.round(flight.heading || 0)}°</span>
                        </div>
                        {flight.squawk && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">SQUAWK</span>
                                <span className={`text-xs font-bold ${flight.squawk === '7700' ? 'text-red-400 animate-pulse' : flight.squawk === '7600' ? 'text-yellow-400' : 'text-[var(--text-primary)]'}`}>{flight.squawk}{flight.squawk === '7700' ? ' ⚠ EMERGENCY' : flight.squawk === '7600' ? ' COMMS LOST' : ''}</span>
                            </div>
                        )}
                        <div className="border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px] block mb-1.5">EMISSIONS ESTIMATE</span>
                            <div className="flex gap-3">
                                <div className="flex-1 bg-[var(--bg-primary)]/50 border border-[var(--border-primary)] px-2 py-1.5">
                                    <div className="text-[11px] text-[var(--text-muted)] tracking-widest">FUEL BURN</div>
                                    <div className="text-xs font-bold text-orange-400">{flight.emissions ? <>{flight.emissions.fuel_gph} <span className="text-[11px] text-[var(--text-muted)] font-normal">GPH</span></> : 'UNKNOWN'}</div>
                                </div>
                                <div className="flex-1 bg-[var(--bg-primary)]/50 border border-[var(--border-primary)] px-2 py-1.5">
                                    <div className="text-[11px] text-[var(--text-muted)] tracking-widest">CO2 OUTPUT</div>
                                    <div className="text-xs font-bold text-red-400">{flight.emissions ? <>{flight.emissions.co2_kg_per_hour.toLocaleString()} <span className="text-[11px] text-[var(--text-muted)] font-normal">KG/HR</span></> : 'UNKNOWN'}</div>
                                </div>
                            </div>
                        </div>
                        {flight.alert_link && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">REFERENCE</span>
                                <a href={flight.alert_link} target="_blank" rel="noreferrer" className={`text-xs font-bold underline ${headerColor} hover:opacity-80`}>
                                    View Intel Source
                                </a>
                            </div>
                        )}
                        {flight.alert_socials && (flight.alert_socials.twitter || flight.alert_socials.instagram) && (
                            <div className="border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px] block mb-1.5">SOCIALS</span>
                                <div className="flex gap-2">
                                    {flight.alert_socials.twitter && (
                                        <a href={`https://x.com/${flight.alert_socials.twitter}`} target="_blank" rel="noreferrer"
                                            className="flex items-center gap-1 px-2 py-1 text-[10px] font-mono border border-[var(--border-primary)] hover:border-cyan-500/50 hover:bg-cyan-950/30 text-cyan-400 transition-colors">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                                            @{flight.alert_socials.twitter}
                                        </a>
                                    )}
                                    {flight.alert_socials.instagram && (
                                        <a href={`https://instagram.com/${flight.alert_socials.instagram}`} target="_blank" rel="noreferrer"
                                            className="flex items-center gap-1 px-2 py-1 text-[10px] font-mono border border-[var(--border-primary)] hover:border-pink-500/50 hover:bg-pink-950/30 text-pink-400 transition-colors">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="2" width="20" height="20" rx="5"/><circle cx="12" cy="12" r="5"/><circle cx="17.5" cy="6.5" r="1.5"/></svg>
                                            @{flight.alert_socials.instagram}
                                        </a>
                                    )}
                                </div>
                            </div>
                        )}
                        {flight.icao24 && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">FLIGHT RECORD</span>
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
        const flight = flightsList?.find((f: any) => f.icao24 === selectedEntity.id);

        if (flight) {
            const callsign = flight.callsign || "UNKNOWN";
            let airline = "UNKNOWN";

            if (selectedEntity.type === 'military_flight') {
                const mil = flight as import('@/types/dashboard').MilitaryFlight;
                const milCountry = mil.country;
                airline = mil.force
                    ? `${milCountry} ${mil.force}`.trim()
                    : (milCountry && milCountry !== 'Military Asset' && milCountry !== 'Unknown'
                        ? milCountry : "MILITARY ASSET");
            } else if (selectedEntity.type === 'private_jet') {
                airline = "PRIVATE JET";
            } else if (selectedEntity.type === 'private_flight') {
                airline = "PRIVATE / GA";
            } else if ('airline_code' in flight && flight.airline_code) {
                // Use the airline code resolved from adsb.lol routeset API
                const codeMap: Record<string, string> = {
                    "UAL": "United Airlines", "DAL": "Delta Air Lines", "SWA": "Southwest Airlines",
                    "AAL": "American Airlines", "BAW": "British Airways", "AFR": "Air France",
                    "JBU": "JetBlue Airways", "NKS": "Spirit Airlines", "THY": "Turkish Airlines",
                    "UAE": "Emirates", "QFA": "Qantas", "ACA": "Air Canada",
                    "FFT": "Frontier Airlines", "WJA": "WestJet", "RPA": "Republic Airways",
                    "SKW": "SkyWest Airlines", "ENY": "Envoy Air", "ASA": "Alaska Airlines",
                    "HAL": "Hawaiian Airlines", "DLH": "Lufthansa", "KLM": "KLM",
                    "EZY": "EasyJet", "RYR": "Ryanair", "SIA": "Singapore Airlines",
                    "CPA": "Cathay Pacific", "ANA": "All Nippon Airways", "JAL": "Japan Airlines",
                    "QTR": "Qatar Airways", "ETD": "Etihad Airways", "SAS": "SAS Scandinavian"
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
                    className="w-full bg-black/85 border border-[var(--border-primary)] flex flex-col z-10 font-mono pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-[var(--border-primary)]/30 bg-[var(--bg-secondary)]/40 flex justify-between items-center">
                        <h2 className={`text-xs tracking-widest font-bold ${selectedEntity.type === 'military_flight' ? 'text-red-400' : selectedEntity.type === 'private_flight' ? 'text-orange-400' : selectedEntity.type === 'private_jet' ? 'text-purple-400' : 'text-cyan-400'} flex items-center gap-2`}>
                            {selectedEntity.type === 'military_flight' ? "MILITARY BOGEY INTERCEPT" : selectedEntity.type === 'private_flight' ? "PRIVATE TRANSPONDER" : selectedEntity.type === 'private_jet' ? "PRIVATE JET TRANSPONDER" : "COMMERCIAL TRANSPONDER"}
                        </h2>
                        <span className="text-[10px] text-[var(--text-muted)] font-mono">TRK: {callsign}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">OPERATOR</span>
                            {selectedEntity.type !== 'military_flight' && airline && airline !== 'COMMERCIAL FLIGHT' && airline !== 'UNKNOWN' ? (
                                <a
                                    href={`https://en.wikipedia.org/wiki/${encodeURIComponent(airline.replace(/ /g, '_'))}`}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-xs font-bold text-cyan-400 hover:text-cyan-300 underline"
                                >
                                    {airline}
                                </a>
                            ) : (
                                <span className="text-[var(--text-primary)] text-xs font-bold">{airline}</span>
                            )}
                        </div>
                        {/* Commercial: Airline company Wikipedia image */}
                        {selectedEntity.type !== 'military_flight' && airline && airline !== 'COMMERCIAL FLIGHT' && airline !== 'UNKNOWN' && (
                            <div className="border-b border-[var(--border-primary)] pb-2">
                                <WikiImage
                                    wikiUrl={`https://en.wikipedia.org/wiki/${encodeURIComponent(airline.replace(/ /g, '_'))}`}
                                    label={airline}
                                    maxH="max-h-32"
                                    accent="hover:border-cyan-500/50"
                                />
                            </div>
                        )}
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">REGISTRATION</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{flight.registration || "N/A"}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">AIRCRAFT MODEL</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{flight.model || "UNKNOWN"}</span>
                        </div>
                        {/* Military: Aircraft model Wikipedia image (gold accent) */}
                        {selectedEntity.type === 'military_flight' && (() => {
                            // Resolve model to Wikipedia article — ICAO code first, then ac_type regex
                            const milAcType = (flight as Record<string, any>).alert_type as string | undefined;
                            const milWikiTitle = (flight.model ? AIRCRAFT_WIKI[flight.model] : undefined)
                                || (milAcType ? resolveAcTypeWiki(milAcType) : null)
                                || (flight.model ? resolveAcTypeWiki(flight.model) : null);
                            const milModelUrl = milWikiTitle ? `https://en.wikipedia.org/wiki/${milWikiTitle.replace(/ /g, '_')}` : null;
                            if (milModelUrl) {
                                return (
                                    <div className="border-b border-[var(--border-primary)] pb-3">
                                        <WikiImage
                                            wikiUrl={milModelUrl}
                                            label={milWikiTitle || flight.model}
                                            maxH="max-h-36"
                                            accent="hover:border-amber-400/60"
                                        />
                                    </div>
                                );
                            }
                            // Fall back to cached thumbnail if available
                            if (aircraftImgUrl || aircraftImgLoading) {
                                return (
                                    <div className="border-b border-[var(--border-primary)] pb-3">
                                        {aircraftImgLoading && (
                                            <div className="w-full h-24 bg-[var(--bg-tertiary)]/60" />
                                        )}
                                        {aircraftImgUrl && (
                                            <a href={aircraftWikiUrl || '#'} target="_blank" rel="noopener noreferrer" className="block">
                                                <img
                                                    src={aircraftImgUrl}
                                                    alt={AIRCRAFT_WIKI[flight.model] || flight.model}
                                                    className="w-full h-auto max-h-32 object-cover border border-amber-500/30 hover:border-amber-400/60 transition-colors"
                                                    style={{ imageRendering: 'auto' }}
                                                />
                                            </a>
                                        )}
                                        {aircraftWikiUrl && (
                                            <a href={aircraftWikiUrl} target="_blank" rel="noopener noreferrer"
                                                className="text-[10px] text-amber-400 hover:text-amber-300 underline mt-1 inline-block">
                                                📖 {AIRCRAFT_WIKI[flight.model] || flight.model} — Wikipedia →
                                            </a>
                                        )}
                                    </div>
                                );
                            }
                            return null;
                        })()}
                        {/* Non-military: Aircraft model photo (secondary, below airline image) */}
                        {selectedEntity.type !== 'military_flight' && (aircraftImgUrl || aircraftImgLoading || aircraftWikiUrl) && (
                            <div className="border-b border-[var(--border-primary)] pb-3">
                                {aircraftImgLoading && (
                                    <div className="w-full h-24 bg-[var(--bg-tertiary)]/60" />
                                )}
                                {aircraftImgUrl && (
                                    <a href={aircraftWikiUrl || '#'} target="_blank" rel="noopener noreferrer" className="block">
                                        <img
                                            src={aircraftImgUrl}
                                            alt={AIRCRAFT_WIKI[flight.model] || flight.model}
                                            className="w-full h-auto max-h-32 object-cover border border-[var(--border-primary)]/50 hover:border-cyan-500/50 transition-colors"
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
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">ALTITUDE</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{(Math.round((flight.alt || 0) / 0.3048)).toLocaleString()} ft</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">GROUND SPEED</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{flight.speed_knots ? `${flight.speed_knots} kts` : 'N/A'}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">HEADING</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{Math.round(flight.heading || 0)}°</span>
                        </div>
                        {flight.squawk && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">SQUAWK</span>
                                <span className={`text-xs font-bold ${flight.squawk === '7700' ? 'text-red-400 animate-pulse' : flight.squawk === '7600' ? 'text-yellow-400' : 'text-[var(--text-primary)]'}`}>{flight.squawk}{flight.squawk === '7700' ? ' ⚠ EMERGENCY' : flight.squawk === '7600' ? ' COMMS LOST' : ''}</span>
                            </div>
                        )}
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">ROUTE</span>
                            <span className="text-cyan-400 text-xs font-bold">{flight.origin_name !== "UNKNOWN" ? `[${flight.origin_name}] → [${flight.dest_name}]` : "UNKNOWN"}</span>
                        </div>
                        <div className="border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px] block mb-1.5">EMISSIONS ESTIMATE</span>
                            <div className="flex gap-3">
                                <div className="flex-1 bg-[var(--bg-primary)]/50 border border-[var(--border-primary)] px-2 py-1.5">
                                    <div className="text-[11px] text-[var(--text-muted)] tracking-widest">FUEL BURN</div>
                                    <div className="text-xs font-bold text-orange-400">{flight.emissions ? <>{flight.emissions.fuel_gph} <span className="text-[11px] text-[var(--text-muted)] font-normal">GPH</span></> : 'UNKNOWN'}</div>
                                </div>
                                <div className="flex-1 bg-[var(--bg-primary)]/50 border border-[var(--border-primary)] px-2 py-1.5">
                                    <div className="text-[11px] text-[var(--text-muted)] tracking-widest">CO2 OUTPUT</div>
                                    <div className="text-xs font-bold text-red-400">{flight.emissions ? <>{flight.emissions.co2_kg_per_hour.toLocaleString()} <span className="text-[11px] text-[var(--text-muted)] font-normal">KG/HR</span></> : 'UNKNOWN'}</div>
                                </div>
                            </div>
                        </div>
                        {flight.icao24 && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">FLIGHT RECORD</span>
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
        const ship = data?.ships?.find((s: any) => s.mmsi === selectedEntity.id);
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
            const headerColor = headerColorMap[ship.type] || 'text-[var(--text-secondary)]';

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
                    className="w-full bg-black/85 border border-[var(--border-primary)] flex flex-col z-10 font-mono pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-[var(--border-primary)]/30 bg-[var(--bg-secondary)]/40 flex justify-between items-center">
                        <h2 className={`text-xs tracking-widest font-bold ${headerColor} flex items-center gap-2`}>
                            {headerTitle}
                        </h2>
                        <span className="text-[10px] text-[var(--text-muted)] font-mono">MMSI: {ship.mmsi || 'N/A'}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">VESSEL NAME</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold text-right ml-4">{ship.name || 'UNKNOWN'}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">VESSEL TYPE</span>
                            <span className={`text-xs font-bold ${headerColor}`}>{typeLabel}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">FLAG STATE</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{ship.country || 'UNKNOWN'}</span>
                        </div>
                        {ship.callsign && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">CALLSIGN</span>
                                <span className="text-[var(--text-primary)] text-xs font-bold">{ship.callsign}</span>
                            </div>
                        )}
                        {(ship.imo ?? 0) > 0 && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">IMO NUMBER</span>
                                <span className="text-[var(--text-primary)] text-xs font-bold">{ship.imo}</span>
                            </div>
                        )}
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">DESTINATION</span>
                            <span className={`text-xs font-bold ${ship.destination && ship.destination !== 'UNKNOWN' ? 'text-cyan-400' : 'text-orange-400'}`}>{ship.destination || 'UNKNOWN'}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">SPEED (SOG)</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{ship.type === 'carrier' ? 'UNKNOWN' : `${ship.sog || 0} kts`}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">COURSE (COG)</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{ship.type === 'carrier' ? 'UNKNOWN' : `${Math.round(ship.cog || 0)}°`}</span>
                        </div>
                        {ship.mmsi && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">VESSEL RECORD</span>
                                <a href={`https://www.marinetraffic.com/en/ais/details/ships/mmsi:${ship.mmsi}`} target="_blank" rel="noreferrer" className="text-cyan-400 hover:text-cyan-300 text-xs font-bold underline">
                                    View on MarineTraffic
                                </a>
                            </div>
                        )}
                        {/* Ship/Carrier Wikipedia photo */}
                        {(ship.wiki || VESSEL_TYPE_WIKI[ship.type]) && (
                            <div className="border-t border-[var(--border-primary)] pt-2">
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
        const gdeltItem = data?.gdelt?.find((g: any) => (g.properties?.name || String(g.geometry?.coordinates)) === selectedEntity.id);
        if (gdeltItem && gdeltItem.properties) {
            const props = gdeltItem.properties;
            return (
                <motion.div
                    initial={{ y: 50, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.4 }}
                    className="w-full bg-black/85 border border-orange-800 flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(255,140,0,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-orange-500/30 bg-orange-950/40 flex justify-between items-center">
                        <h2 className="text-xs tracking-widest font-bold text-orange-400 flex items-center gap-2">
                            <AlertTriangle size={14} className="text-orange-400" /> MILITARY INCIDENT CLUSTER
                        </h2>
                        <span className="text-[10px] text-[var(--text-muted)] font-mono">ID: {selectedEntity.id}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">LOCATION</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold text-right ml-4">{props.name || 'UNKNOWN REGION'}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">ARTICLE COUNT</span>
                            <span className="text-orange-400 text-xs font-bold">{props.count || 1}</span>
                        </div>
                        <div className="flex flex-col gap-2 mt-2">
                            <span className="text-[var(--text-muted)] text-[10px]">LATEST REPORTS:</span>
                            <div className="flex flex-col gap-1 max-h-[250px] overflow-y-auto styled-scrollbar">
                                {(() => {
                                    const urls: string[] = props._urls_list || [];
                                    const headlines: string[] = props._headlines_list || [];
                                    if (urls.length === 0) return <span className="text-[var(--text-muted)] text-[10px]">No articles available.</span>;
                                    return urls.map((url: string, idx: number) => {
                                        const headline = headlines[idx] || '';
                                        let domain = '';
                                        try { domain = new URL(url).hostname.replace('www.', ''); } catch { domain = ''; }
                                        return (
                                            <a
                                                key={idx}
                                                href={url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="block py-1.5 border-b border-[var(--border-primary)]/50 last:border-0 cursor-pointer group"
                                            >
                                                <span className="text-orange-400 text-[11px] font-bold leading-tight group-hover:text-orange-300 block">
                                                    {headline || domain || 'View Article'}
                                                </span>
                                                {headline && domain && (
                                                    <span className="text-[var(--text-muted)] text-[11px] block mt-0.5">{domain}</span>
                                                )}
                                            </a>
                                        );
                                    });
                                })()}
                            </div>
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
                    className="w-full bg-black/85 border border-yellow-800 flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(255,255,0,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-yellow-500/30 bg-yellow-950/40 flex justify-between items-center">
                        <h2 className="text-xs tracking-widest font-bold text-yellow-400 flex items-center gap-2">
                            <AlertTriangle size={14} className="text-yellow-400" /> REGIONAL TACTICAL EVENT
                        </h2>
                        <span className="text-[10px] text-[var(--text-muted)] font-mono">ID: {item.id}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">REGION</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold text-right ml-4">{item.region || 'UNKNOWN'}</span>
                        </div>
                        <div className="flex flex-col gap-2 border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">DESCRIPTION</span>
                            <span className="text-yellow-400 text-xs font-bold leading-tight">{item.title}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2 mt-2">
                            <span className="text-[var(--text-muted)] text-[10px]">REPORTED TIME</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{item.timestamp || 'UNKNOWN'}</span>
                        </div>
                        {item.link && (
                            <div className="flex justify-between items-center pb-2 mt-2">
                                <span className="text-[var(--text-muted)] text-[10px]">SOURCE</span>
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
                    className="w-full bg-black/85 border border-red-800 flex flex-col z-10 font-mono shadow-[0_4px_30px_rgba(255,0,0,0.2)] pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-red-500/30 bg-red-950/40 flex justify-between items-center">
                        <h2 className="text-xs tracking-widest font-bold text-red-400 flex items-center gap-2">
                            <AlertTriangle size={14} className="text-red-400" /> THREAT INTERCEPT
                        </h2>
                        <span className="text-[10px] text-[var(--text-muted)] font-mono">LVL: {item.risk_score}/10</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">SOURCE</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold text-right ml-4">{item.source || 'UNKNOWN'}</span>
                        </div>
                        <div className="flex flex-col gap-2 border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">HEADLINE</span>
                            <span className="text-red-400 text-xs font-bold leading-tight">{item.title}</span>
                        </div>
                        {item.oracle_score != null && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">ORACLE SCORE</span>
                                <span className={`text-xs font-bold ${item.oracle_score >= 7 ? 'text-red-400' : item.oracle_score >= 4 ? 'text-yellow-400' : 'text-green-400'}`}>
                                    {item.oracle_score}/10 [{item.oracle_score >= 7 ? 'CRITICAL' : item.oracle_score >= 4 ? 'ELEVATED' : 'ROUTINE'}]
                                </span>
                            </div>
                        )}
                        {item.sentiment != null && (
                            <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px]">SENTIMENT</span>
                                <span className={`text-xs font-bold ${item.sentiment <= -0.05 ? 'text-red-400' : item.sentiment >= 0.05 ? 'text-green-400' : 'text-gray-400'}`}>
                                    {item.sentiment > 0 ? '+' : ''}{item.sentiment.toFixed(2)} [{item.sentiment <= -0.05 ? 'NEGATIVE' : item.sentiment >= 0.05 ? 'POSITIVE' : 'NEUTRAL'}]
                                </span>
                            </div>
                        )}
                        {item.prediction_odds && item.prediction_odds.consensus_pct != null && (
                            <div className="border-b border-[var(--border-primary)] pb-2">
                                <span className="text-[var(--text-muted)] text-[10px] block mb-1.5">MARKET CORRELATION</span>
                                <div className="p-2 bg-purple-950/30 border border-purple-500/30 rounded-sm">
                                    <div className="text-[10px] text-purple-300 font-bold leading-tight mb-1">{item.prediction_odds.title}</div>
                                    <div className="flex items-center gap-3 text-[11px] font-mono">
                                        <span className="text-white font-bold">CONSENSUS: {item.prediction_odds.consensus_pct}%</span>
                                        {item.prediction_odds.polymarket_pct != null && <span className="text-cyan-400">Polymarket {item.prediction_odds.polymarket_pct}%</span>}
                                        {item.prediction_odds.kalshi_pct != null && <span className="text-orange-400">Kalshi {item.prediction_odds.kalshi_pct}%</span>}
                                    </div>
                                </div>
                            </div>
                        )}
                        {item.machine_assessment && (
                            <div className="mt-2 p-2 bg-black/60 border border-cyan-800/50 rounded-sm text-[11px] text-cyan-400 font-mono leading-tight relative overflow-hidden shadow-[inset_0_0_10px_rgba(0,255,255,0.05)]">
                                <div className="absolute top-0 left-0 w-[2px] h-full bg-cyan-500 animate-pulse"></div>
                                <span className="font-bold text-white">&gt;_ SYS.ANALYSIS: </span>
                                <span className="text-cyan-300 opacity-90">{item.machine_assessment}</span>
                            </div>
                        )}
                        {item.link && (
                            <div className="flex justify-between items-center pb-2 mt-2">
                                <span className="text-[var(--text-muted)] text-[10px]">REFERENCE</span>
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
                    className="w-full bg-black/85 border border-[var(--border-primary)] flex flex-col z-10 font-mono pointer-events-auto overflow-hidden flex-shrink-0"
                >
                    <div className="p-3 border-b border-[var(--border-primary)]/30 bg-[var(--bg-secondary)]/40 flex justify-between items-center">
                        <h2 className="text-xs tracking-widest font-bold text-cyan-400 flex items-center gap-2">
                            AERONAUTICAL HUB
                        </h2>
                        <span className="text-[10px] text-[var(--text-muted)] font-mono">IATA: {apt.iata}</span>
                    </div>

                    <div className="p-4 flex flex-col gap-3">
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">FACILITY NAME</span>
                            <span className="text-[var(--text-primary)] text-[10px] font-bold text-right ml-4 break-words">{apt.name}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">COORDINATES</span>
                            <span className="text-[var(--text-primary)] text-xs font-bold">{apt.lat.toFixed(4)}, {apt.lng.toFixed(4)}</span>
                        </div>
                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-2">
                            <span className="text-[var(--text-muted)] text-[10px]">STATUS</span>
                            <span className="text-green-400 text-xs font-bold">OPERATIONAL</span>
                        </div>
                    </div>
                </motion.div>
            )
        }
    }

    /* CCTV is now handled by the fullscreen OPTIC INTERCEPT modal in MaplibreViewer */
    if (selectedEntity?.type === 'cctv') return null;

    return (
        <motion.div
            initial={{ y: 50, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.2 }}
            className={`w-full bg-[#0a0a0a]/90 backdrop-blur-sm border border-cyan-900/40 flex flex-col z-10 font-mono pointer-events-auto overflow-hidden transition-all duration-300 ${isMinimized ? 'flex-shrink-0' : 'flex-1 min-h-0'}`}
        >
            <div
                className="px-3 py-2.5 border-b border-cyan-900/40 relative overflow-hidden cursor-pointer hover:bg-cyan-950/30 transition-colors"
                onClick={() => setIsMinimized(!isMinimized)}
            >
                <div className="flex items-center justify-between relative z-10">
                    <div className="flex items-center gap-2">
                        <AlertTriangle size={16} className="text-cyan-400" />
                        <span className="text-[12px] text-cyan-400 font-mono tracking-widest font-bold">
                            GLOBAL THREAT INTERCEPT
                        </span>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                const next = !aiSummaryOpen;
                                setAiSummaryOpen(next);
                                if (next && !aiSummary) {
                                    setAiSummaryLoading(true);
                                    fetch('/api/ai/news/summary')
                                        .then(r => r.json())
                                        .then(d => { setAiSummary(d); setAiSummaryLoading(false); })
                                        .catch(() => setAiSummaryLoading(false));
                                }
                            }}
                            className={`p-0.5 rounded-sm transition-colors ${
                                aiSummaryOpen
                                    ? 'text-purple-400 bg-purple-900/30 border border-purple-700/40'
                                    : 'text-gray-600 hover:text-purple-400 border border-transparent hover:border-purple-700/30'
                            }`}
                            title="AI Intelligence Brief"
                        >
                            <Brain size={14} />
                        </button>
                        {isMinimized ? (
                            <Plus size={16} className="text-cyan-400" />
                        ) : (
                            <Minus size={16} className="text-cyan-400" />
                        )}
                    </div>
                </div>

                <AnimatePresence>
                    {!isMinimized && (
                        <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            className="text-[10px] text-cyan-500/80 mt-1 flex items-center justify-between font-bold relative z-10"
                        >
                            <span className="px-1 border border-cyan-500/30">SYS.STATUS: MONITORING</span>
                            <span className="flex items-center gap-1"><Clock size={10} /> {data?.last_updated ? formatTime(data.last_updated) : "SCANNING"}</span>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>

            {/* Threat Level Indicator */}
            <AnimatePresence>
                {!isMinimized && data?.threat_level && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="px-3 pt-2 pb-1"
                    >
                        <div
                            className={`flex items-center gap-2 px-2 py-1.5 border rounded-sm font-mono ${
                                data.threat_level.level === 'SEVERE' ? 'bg-red-950/40 border-red-500/50' :
                                data.threat_level.level === 'HIGH' ? 'bg-orange-950/40 border-orange-500/50' :
                                data.threat_level.level === 'ELEVATED' ? 'bg-yellow-950/40 border-yellow-500/50' :
                                data.threat_level.level === 'GUARDED' ? 'bg-blue-950/40 border-blue-500/50' :
                                'bg-green-950/40 border-green-500/50'
                            }`}
                        >
                            <div className={`w-2 h-2 rounded-full ${
                                data.threat_level.level === 'SEVERE' || data.threat_level.level === 'HIGH' ? 'animate-pulse' : ''
                            }`} style={{ backgroundColor: data.threat_level.color }} />
                            <span className="text-[12px] font-bold tracking-wider" style={{ color: data.threat_level.color }}>
                                THREAT: {data.threat_level.level}
                            </span>
                            <span className="text-[12px] text-[var(--text-muted)] ml-auto">
                                {data.threat_level.score}/100
                            </span>
                        </div>
                        {/* Threat drivers removed — the level bar is sufficient */}
                    </motion.div>
                )}
            </AnimatePresence>

            {/* AI Intelligence Brief */}
            <AnimatePresence>
                {!isMinimized && aiSummaryOpen && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="px-3 pt-1 pb-2 overflow-hidden"
                    >
                        <div className="border border-purple-500/30 bg-purple-950/10 rounded-sm">
                            <div className="flex items-center gap-2 px-2 py-1.5 border-b border-purple-500/20">
                                <Brain size={12} className="text-purple-400" />
                                <span className="text-[11px] font-bold tracking-wider text-purple-400">AI INTELLIGENCE BRIEF</span>
                                <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse ml-auto" />
                            </div>
                            {aiSummaryLoading ? (
                                <div className="p-3 flex items-center gap-2 text-[10px] text-purple-300">
                                    <Loader2 size={12} className="animate-spin" />
                                    COMPILING INTELLIGENCE BRIEF...
                                </div>
                            ) : aiSummary ? (
                                <div className="p-2 flex flex-col gap-2 text-[10px]">
                                    <div className="text-purple-200 font-mono leading-relaxed">
                                        {aiSummary.summary}
                                    </div>
                                    {aiSummary.top_stories?.length > 0 && (
                                        <div>
                                            <div className="text-[11px] text-purple-400 tracking-widest font-bold mb-1">TOP STORIES</div>
                                            <div className="flex flex-col gap-1">
                                                {aiSummary.top_stories.slice(0, 5).map((s: any, i: number) => (
                                                    <a key={i} href={s.link} target="_blank" rel="noreferrer" className="text-[11px] text-purple-200/80 hover:text-white transition-colors truncate">
                                                        <span className={`mr-1 ${
                                                            s.risk_score >= 9 ? 'text-red-400' :
                                                            s.risk_score >= 7 ? 'text-orange-400' :
                                                            s.risk_score >= 4 ? 'text-yellow-400' : 'text-green-400'
                                                        }`}>●</span>
                                                        [{s.risk_score}/10] {s.title}
                                                    </a>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                    {aiSummary.keywords?.length > 0 && (
                                        <div>
                                            <div className="text-[11px] text-purple-400 tracking-widest font-bold mb-1">TRENDING KEYWORDS</div>
                                            <div className="flex flex-wrap gap-1">
                                                {aiSummary.keywords.slice(0, 10).map((kw: any, i: number) => (
                                                    <span key={i} className="text-[10px] px-1 py-0.5 bg-purple-950/50 border border-purple-500/20 text-purple-300 rounded-sm">
                                                        {kw.word} ({kw.count})
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                    {aiSummary.threat_distribution && (
                                        <div>
                                            <div className="text-[11px] text-purple-400 tracking-widest font-bold mb-1">THREAT BREAKDOWN</div>
                                            <div className="flex gap-1">
                                                {Object.entries(aiSummary.threat_distribution).map(([level, count]) => (
                                                    <span key={level} className={`text-[10px] px-1.5 py-0.5 border rounded-sm font-bold ${
                                                        level === 'CRITICAL' ? 'bg-red-950/40 border-red-500/30 text-red-400' :
                                                        level === 'HIGH' ? 'bg-orange-950/40 border-orange-500/30 text-orange-400' :
                                                        level === 'ELEVATED' ? 'bg-yellow-950/40 border-yellow-500/30 text-yellow-400' :
                                                        level === 'MODERATE' ? 'bg-blue-950/40 border-blue-500/30 text-blue-400' :
                                                        'bg-green-950/40 border-green-500/30 text-green-400'
                                                    }`}>
                                                        {level}: {count as number}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                    <button
                                        onClick={() => {
                                            setAiSummaryLoading(true);
                                            setAiSummary(null);
                                            fetch('/api/ai/news/summary')
                                                .then(r => r.json())
                                                .then(d => { setAiSummary(d); setAiSummaryLoading(false); })
                                                .catch(() => setAiSummaryLoading(false));
                                        }}
                                        className="text-[11px] text-purple-500 hover:text-purple-300 transition-colors self-end"
                                    >
                                        ↻ REFRESH BRIEF
                                    </button>
                                </div>
                            ) : (
                                <div className="p-3 text-[10px] text-purple-300/50">No data available.</div>
                            )}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* DISINFORMATION INDEX — compact bar or major alert takeover */}
            <AnimatePresence>
                {!isMinimized && fimi && fimi.narratives && fimi.narratives.length > 0 && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="px-3 pt-1 pb-1"
                    >
                        {/* Compact bar */}
                        <button
                            onClick={() => setFimiExpanded(!fimiExpanded)}
                            className={`w-full flex items-center gap-2 px-2 py-1.5 border rounded-sm font-mono cursor-pointer transition-colors ${
                                fimi.major_wave
                                    ? 'bg-amber-950/50 border-amber-500/60 hover:bg-amber-950/70'
                                    : 'bg-purple-950/30 border-purple-500/30 hover:bg-purple-950/50'
                            }`}
                        >
                            <div className={`w-2 h-2 rounded-full ${
                                fimi.major_wave ? 'bg-amber-400 animate-pulse' : 'bg-purple-400'
                            }`} />
                            <span className={`text-[11px] font-bold tracking-wider ${
                                fimi.major_wave ? 'text-amber-400' : 'text-purple-400'
                            }`}>
                                {fimi.major_wave
                                    ? `⚠ MAJOR DISINFORMATION ALERT${fimi.major_wave_target ? ` — ${fimi.major_wave_target.toUpperCase()}` : ''}`
                                    : '⚠ DISINFORMATION INDEX'
                                }
                            </span>
                            <span className="text-[11px] text-[var(--text-muted)] ml-auto flex items-center gap-1">
                                {Object.keys(fimi.threat_actors).length > 0 && (
                                    <span className="text-red-400">
                                        {Object.keys(fimi.threat_actors)[0]}
                                    </span>
                                )}
                                <span>{fimi.narratives.length} NARR</span>
                                {fimiExpanded ? <Minus size={10} /> : <Plus size={10} />}
                            </span>
                        </button>

                        {/* Expanded weekly report */}
                        <AnimatePresence>
                            {fimiExpanded && (
                                <motion.div
                                    initial={{ height: 0, opacity: 0 }}
                                    animate={{ height: "auto", opacity: 1 }}
                                    exit={{ height: 0, opacity: 0 }}
                                    className="mt-1 border border-purple-500/20 bg-black/40 rounded-sm overflow-hidden"
                                >
                                    {/* Threat Actor Bar */}
                                    {Object.keys(fimi.threat_actors).length > 0 && (
                                        <div className="px-2 py-1.5 border-b border-purple-500/10">
                                            <div className="text-[11px] text-purple-400 tracking-widest font-bold mb-1">THREAT ACTORS</div>
                                            <div className="flex gap-1 h-2 rounded-sm overflow-hidden">
                                                {(() => {
                                                    const total = Object.values(fimi.threat_actors).reduce((a, b) => a + b, 0);
                                                    const actorColors: Record<string, string> = {
                                                        'Russia': 'bg-red-500', 'China': 'bg-amber-500',
                                                        'Iran': 'bg-purple-500', 'North Korea': 'bg-pink-500',
                                                        'Belarus': 'bg-orange-500',
                                                    };
                                                    return Object.entries(fimi.threat_actors).map(([actor, count]) => (
                                                        <div
                                                            key={actor}
                                                            className={`${actorColors[actor] || 'bg-gray-500'} transition-all`}
                                                            style={{ width: `${(count / total) * 100}%` }}
                                                            title={`${actor}: ${count} mentions`}
                                                        />
                                                    ));
                                                })()}
                                            </div>
                                            <div className="flex gap-2 mt-1 flex-wrap">
                                                {Object.entries(fimi.threat_actors).map(([actor, count]) => (
                                                    <span key={actor} className="text-[10px] text-[var(--text-muted)]">
                                                        <span className={`font-bold ${
                                                            actor === 'Russia' ? 'text-red-400' :
                                                            actor === 'China' ? 'text-amber-400' :
                                                            actor === 'Iran' ? 'text-purple-400' :
                                                            'text-gray-400'
                                                        }`}>{actor}</span> {count}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {/* Top Narratives */}
                                    <div className="px-2 py-1.5 border-b border-purple-500/10">
                                        <div className="text-[11px] text-purple-400 tracking-widest font-bold mb-1">LATEST NARRATIVES</div>
                                        <div className="flex flex-col gap-1 max-h-[120px] overflow-y-auto styled-scrollbar">
                                            {fimi.narratives.slice(0, 5).map((n, i) => (
                                                <a
                                                    key={i}
                                                    href={n.link}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                    className="text-[11px] text-[var(--text-secondary)] hover:text-purple-300 transition-colors leading-tight flex items-start gap-1"
                                                >
                                                    <ExternalLink size={8} className="text-purple-500 mt-0.5 flex-shrink-0" />
                                                    <span className="flex-1">{n.title}</span>
                                                </a>
                                            ))}
                                        </div>
                                    </div>

                                    {/* Debunked Claims */}
                                    {fimi.claims.length > 0 && (
                                        <div className="px-2 py-1.5 border-b border-purple-500/10">
                                            <div className="text-[11px] text-red-400 tracking-widest font-bold mb-1">DEBUNKED CLAIMS ({fimi.claims.length})</div>
                                            <div className="flex flex-col gap-0.5 max-h-[80px] overflow-y-auto styled-scrollbar">
                                                {fimi.claims.slice(0, 5).map((c, i) => (
                                                    <a
                                                        key={i}
                                                        href={c.url}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        className="text-[11px] text-red-300/70 hover:text-red-300 transition-colors truncate"
                                                    >
                                                        ✕ {c.title}
                                                    </a>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {/* Target Countries */}
                                    {Object.keys(fimi.targets).length > 0 && (
                                        <div className="px-2 py-1.5">
                                            <div className="text-[11px] text-purple-400 tracking-widest font-bold mb-1">TARGETS</div>
                                            <div className="flex flex-wrap gap-1">
                                                {Object.entries(fimi.targets).slice(0, 10).map(([target, count]) => (
                                                    <span key={target} className="text-[10px] px-1 py-0.5 bg-purple-950/50 border border-purple-500/20 text-purple-300 rounded-sm">
                                                        {target} ({count})
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {/* Source attribution */}
                                    <div className="px-2 py-1 border-t border-purple-500/10 flex justify-between items-center">
                                        <a href={fimi.source_url} target="_blank" rel="noreferrer" className="text-[10px] text-purple-500 hover:text-purple-300 transition-colors">
                                            Source: {fimi.source}
                                        </a>
                                        <span className="text-[10px] text-[var(--text-muted)]">
                                            {fimi.last_fetched ? new Date(fimi.last_fetched).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                                        </span>
                                    </div>
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </motion.div>
                )}
            </AnimatePresence>

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
                            const isBreaking = item.breaking === true;
                            if (isBreaking) {
                                bgClass = "bg-red-950/30 border-red-500/60";
                                titleClass = "text-red-300 font-bold";
                                badgeClass = "bg-red-500/20 text-red-300 border-red-400/50";
                            } else if (item.risk_score >= 9) {
                                bgClass = "bg-red-950/20 border-red-500/30";
                                titleClass = "text-cyan-300 font-bold";
                                badgeClass = "bg-red-500/10 text-red-400 border-red-500/30";
                            } else if (item.risk_score >= 7) {
                                bgClass = "bg-orange-950/20 border-orange-500/30";
                                titleClass = "text-cyan-300 font-bold";
                                badgeClass = "bg-orange-500/10 text-orange-400 border-orange-500/30";
                            } else if (item.risk_score >= 4) {
                                bgClass = "bg-yellow-950/20 border-yellow-500/30";
                                titleClass = "text-cyan-300 font-bold";
                                badgeClass = "bg-yellow-500/10 text-yellow-500 border-yellow-500/30";
                            } else {
                                bgClass = "bg-green-950/20 border-green-500/30";
                                titleClass = "text-cyan-300 font-medium";
                                badgeClass = "bg-green-500/10 text-green-400 border-green-500/30";
                            }
                            const isExpanded = expandedIndexes.includes(idx);

                            return (
                                <motion.div
                                    key={idx}
                                    ref={(el) => { itemRefs.current[idx] = el; }}
                                    initial={idx < 15 ? { opacity: 0, x: -10 } : { opacity: 1, x: 0 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    transition={idx < 15 ? { delay: 0.1 + (idx * 0.05) } : { duration: 0 }}
                                    className={`p-2 rounded-sm border-l-[2px] border-r border-t border-b ${bgClass} flex flex-col gap-1 relative group shrink-0`}
                                >
                                    <div className="flex items-center justify-between text-[12px] text-[var(--text-secondary)] uppercase tracking-widest">
                                        <span className="font-bold flex items-center gap-1 text-white">
                                            {isBreaking && <span className="text-red-400 mr-1">BREAKING</span>}
                                            &gt;_ {item.source}
                                        </span>
                                        <span>[{item.published ? formatTime(item.published) : ''}]</span>
                                    </div>

                                    <button
                                        onClick={() => onArticleClick?.(idx, item.coords?.[0], item.coords?.[1], item.title)}
                                        className={`text-left text-[12px] ${titleClass} hover:text-[var(--text-primary)] transition-colors leading-tight cursor-pointer`}
                                    >
                                        {item.title}
                                    </button>

                                    {item.machine_assessment && (
                                        <div className="mt-1 p-1.5 bg-black/60 border border-cyan-800/50 rounded-sm text-[11px] text-cyan-400 font-mono leading-tight relative overflow-hidden shadow-[inset_0_0_10px_rgba(0,255,255,0.05)]">
                                            <div className="absolute top-0 left-0 w-[2px] h-full bg-cyan-500 animate-pulse"></div>
                                            <span className="font-bold text-white">&gt;_ SYS.ANALYSIS: </span>
                                            <span className="text-cyan-300 opacity-90">{item.machine_assessment}</span>
                                        </div>
                                    )}
                                    {item.prediction_odds && item.prediction_odds.consensus_pct != null && (
                                        <div className="mt-1 px-1.5 py-1 bg-purple-950/30 border border-purple-500/30 rounded-sm text-[11px] font-mono flex items-center gap-1.5">
                                            <span className="text-purple-400 font-bold">MKT</span>
                                            <span className="text-purple-300 truncate flex-1" title={item.prediction_odds.title}>{item.prediction_odds.title}</span>
                                            <span className="text-white font-bold whitespace-nowrap">{item.prediction_odds.consensus_pct}%</span>
                                        </div>
                                    )}

                                    <div className="flex items-center gap-1.5 mt-1 relative z-10 flex-wrap">
                                        <span className={`text-[11px] font-bold font-mono px-1.5 py-0.5 rounded-sm border ${badgeClass}`}>
                                            {isBreaking ? 'BREAKING' : `LVL: ${item.risk_score}/10`}
                                        </span>
                                        {item.sentiment != null && (
                                            <span className={`text-[11px] font-bold font-mono px-1.5 py-0.5 rounded-sm border ${
                                                item.sentiment < -0.1 ? 'bg-red-500/10 text-red-400 border-red-500/30' :
                                                item.sentiment > 0.1 ? 'bg-green-500/10 text-green-400 border-green-500/30' :
                                                'bg-gray-500/10 text-gray-400 border-gray-500/30'
                                            }`}>
                                                {item.sentiment < -0.1 ? '▼' : item.sentiment > 0.1 ? '▲' : '—'}{' '}
                                                {item.sentiment > 0 ? '+' : ''}{item.sentiment.toFixed(2)}
                                            </span>
                                        )}
                                        {item.oracle_score != null && (
                                            <span className={`text-[11px] font-bold font-mono px-1.5 py-0.5 rounded-sm border ${
                                                item.oracle_score >= 7 ? 'bg-orange-500/10 text-orange-400 border-orange-500/30' :
                                                item.oracle_score >= 4 ? 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30' :
                                                'bg-cyan-500/10 text-cyan-400 border-cyan-500/30'
                                            }`}>
                                                ⚡ {item.oracle_score.toFixed(1)}
                                            </span>
                                        )}
                                        {checkDisinfoLinked(item.title) && (
                                            <span className="text-[11px] font-bold font-mono px-1.5 py-0.5 rounded-sm border bg-amber-500/15 text-amber-400 border-amber-500/40 animate-pulse" title="This article echoes known disinformation narratives tracked by EUvsDisinfo">
                                                ⚠ DISINFORMATION-LINKED
                                            </span>
                                        )}
                                        {item.cluster_count > 1 && (
                                            <button onClick={() => toggleExpand(idx)} className="text-[11px] font-bold font-mono text-cyan-500 bg-[var(--bg-secondary)]/50 hover:text-[var(--text-primary)] hover:bg-[var(--hover-accent)] border border-cyan-500/30 px-1.5 py-0.5 rounded-sm transition-colors cursor-pointer">
                                                {isExpanded ? '- COLLAPSE' : `+${item.cluster_count - 1} SOURCES`}
                                            </button>
                                        )}
                                        {item.coords && (
                                            <span className="text-[11px] text-[var(--text-muted)] font-mono tracking-tighter ml-auto">
                                                {item.coords[0].toFixed(2)}, {item.coords[1].toFixed(2)}
                                            </span>
                                        )}
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
                                                        <div className="flex items-center justify-between text-[11px] uppercase font-bold">
                                                            <span className="text-white">&gt;_ {subItem.source}</span>
                                                            <span className={
                                                                subItem.risk_score >= 9 ? 'text-red-400' :
                                                                    subItem.risk_score >= 7 ? 'text-orange-400' :
                                                                        subItem.risk_score >= 4 ? 'text-yellow-500' :
                                                                            'text-green-400'
                                                            }>LVL: {subItem.risk_score}/10</span>
                                                        </div>
                                                        <a href={subItem.link} target="_blank" rel="noreferrer" className="text-[11px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors leading-tight">
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
                            <div className="text-cyan-500/50 text-[10px] tracking-widest font-bold text-center mt-6">
                                NO NEWS ITEMS LOADED
                                <div className="mt-2 text-[11px] font-normal tracking-normal text-cyan-600/80">
                                    Feed ingest is empty or still warming up.
                                </div>
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
