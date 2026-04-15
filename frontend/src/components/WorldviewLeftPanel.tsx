'use client';

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Plane,
  AlertTriangle,
  Activity,
  Satellite,
  Cctv,
  ChevronDown,
  ChevronUp,
  Ship,
  Eye,
  Anchor,
  Settings,
  Sun,
  Moon,
  BookOpen,
  Radio,
  Play,
  Pause,
  Square,
  FastForward,
  Globe,
  Flame,
  Wifi,
  Server,
  Shield,
  Zap,
  ToggleLeft,
  ToggleRight,
  Palette,
  CloudLightning,
  Mountain,
  Wind,
  Fish,
  TrainFront,
  Search,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { onTileLoadingChange, resetTileLoading } from '@/lib/sentinelHub';
import packageJson from '../../package.json';
import { useTheme } from '@/lib/ThemeContext';

function relativeTime(iso: string | undefined): string {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso + 'Z').getTime();
  if (diff < 0) return 'now';
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
  flights: 'commercial_flights',
  private: 'private_flights',
  jets: 'private_jets',
  military: 'military_flights',
  tracked: 'military_flights',
  earthquakes: 'earthquakes',
  satellites: 'satellites',
  ships_military: 'ships',
  ships_cargo: 'ships',
  ships_civilian: 'ships',
  ships_passenger: 'ships',
  ships_tracked_yachts: 'ships',
  ukraine_frontline: 'frontlines',
  global_incidents: 'gdelt',
  cctv: 'cctv',
  gps_jamming: 'commercial_flights',
  kiwisdr: 'kiwisdr',
  psk_reporter: 'psk_reporter',
  satnogs: 'satnogs_stations',
  tinygs: 'tinygs_satellites',
  firms: 'firms_fires',
  internet_outages: 'internet_outages',
  datacenters: 'datacenters',
  power_plants: 'power_plants',
  sigint_meshtastic: 'sigint',
  sigint_aprs: 'sigint',
  ukraine_alerts: 'ukraine_alerts',
  weather_alerts: 'weather_alerts',
  air_quality: 'air_quality',
  volcanoes: 'volcanoes',
  fishing_activity: 'fishing_activity',
  shodan_overlay: '',
  correlations: 'correlations',
};

// POTUS fleet ICAO hex codes for client-side filtering
const POTUS_ICAOS: Record<string, { label: string; type: string }> = {
  ADFDF8: { label: 'Air Force One (82-8000)', type: 'AF1' },
  ADFDF9: { label: 'Air Force One (92-9000)', type: 'AF1' },
  ADFEB7: { label: 'Air Force Two (98-0001)', type: 'AF2' },
  ADFEB8: { label: 'Air Force Two (98-0002)', type: 'AF2' },
  ADFEB9: { label: 'Air Force Two (99-0003)', type: 'AF2' },
  ADFEBA: { label: 'Air Force Two (99-0004)', type: 'AF2' },
  AE4AE6: { label: 'Air Force Two (09-0015)', type: 'AF2' },
  AE4AE8: { label: 'Air Force Two (09-0016)', type: 'AF2' },
  AE4AEA: { label: 'Air Force Two (09-0017)', type: 'AF2' },
  AE4AEC: { label: 'Air Force Two (19-0018)', type: 'AF2' },
  AE0865: { label: 'Marine One (VH-3D)', type: 'M1' },
  AE5E76: { label: 'Marine One (VH-92A)', type: 'M1' },
  AE5E77: { label: 'Marine One (VH-92A)', type: 'M1' },
  AE5E79: { label: 'Marine One (VH-92A)', type: 'M1' },
};
import type {
  ActiveLayers,
  SelectedEntity,
  KiwiSDR,
  Scanner,
  TrackedFlight,
} from '@/types/dashboard';
import { useDataSnapshot } from '@/hooks/useDataStore';

// ---------------------------------------------------------------------------
// ScannerTracker — in-app audio player for tracked police scanner systems
// ---------------------------------------------------------------------------
function ScannerTracker({
  scanner,
  onRelease,
  onFlyTo,
}: {
  scanner: Scanner;
  onRelease: () => void;
  onFlyTo: () => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [activeBurst, setActiveBurst] = useState<{
    id: string;
    talkgroup: string;
    url: string;
  } | null>(null);
  const [volume, setVolume] = useState(0.8);
  const [isScanning, setIsScanning] = useState(false);
  const isScanningRef = useRef(false);
  const scanTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    const timer = scanTimerRef.current;
    return () => {
      isScanningRef.current = false;
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = '';
      }
      if (timer) clearTimeout(timer);
    };
  }, []);

  // Sync volume
  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume;
  }, [volume]);

  const fetchAndPlay = async () => {
    if (!scanner.shortName) return;
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/radio/openmhz/calls/${scanner.shortName}`);
      if (!res.ok) {
        setIsLoading(false);
        return;
      }
      const calls = await res.json();
      if (!calls?.length) {
        setIsLoading(false);
        return;
      }
      const pick = calls[Math.floor(Math.random() * Math.min(calls.length, 5))];
      const burst = {
        id: pick.id || pick._id || String(Date.now()),
        talkgroup: String(pick.talkgroupNum || '???'),
        url: pick.url,
      };
      setActiveBurst(burst);
      // Play
      if (!audioRef.current) audioRef.current = new Audio();
      audioRef.current.src = burst.url;
      audioRef.current.volume = volume;
      audioRef.current.onended = () => {
        if (isScanningRef.current) fetchAndPlay();
        else {
          setIsPlaying(false);
          setActiveBurst(null);
        }
      };
      await audioRef.current.play();
      setIsPlaying(true);
    } catch (e) {
      console.error('Scanner audio error', e);
    }
    setIsLoading(false);
  };

  const stop = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
    }
    setIsPlaying(false);
    setActiveBurst(null);
    if (isScanning) {
      setIsScanning(false);
      isScanningRef.current = false;
      if (scanTimerRef.current) clearTimeout(scanTimerRef.current);
    }
  };

  const toggleScan = () => {
    if (isScanning) {
      stop();
      return;
    }
    setIsScanning(true);
    isScanningRef.current = true;
    fetchAndPlay();
  };

  return (
    <div className="bg-red-950/20 border border-red-500/40 p-3 -mt-1 shadow-[0_0_15px_rgba(220,38,38,0.1)]">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Radio size={14} className="text-red-400" />
          <span className="text-[12px] text-red-400 font-mono tracking-widest font-bold">
            SCANNER TRACKER
          </span>
          {isPlaying && (
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-full bg-red-500/20 border border-red-500/40 text-red-400 animate-pulse">
              LIVE
            </span>
          )}
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            stop();
            onRelease();
          }}
          className="text-[8px] font-mono text-[var(--text-muted)] hover:text-red-400 border border-[var(--border-primary)] hover:border-red-400/40 px-1.5 py-0.5 transition-colors"
        >
          RELEASE
        </button>
      </div>

      {/* System info */}
      <div className="flex flex-col p-2 border border-red-500/20 bg-red-950/10 mb-2">
        <span className="text-[10px] font-bold font-mono text-red-300 truncate">
          {(scanner.name || 'UNKNOWN SYSTEM').toUpperCase()}
        </span>
        <span className="text-[8px] text-[var(--text-muted)] font-mono">
          {[scanner.city, scanner.state].filter(Boolean).join(', ')}
          {scanner.clientCount > 0 && <span> · {scanner.clientCount} listeners</span>}
        </span>
        {activeBurst && (
          <span className="text-[8px] text-red-400 font-mono mt-1">
            TALKGROUP: {activeBurst.talkgroup}
          </span>
        )}
      </div>

      {/* Audio controls */}
      <div className="flex items-center gap-2 mb-2">
        <button
          onClick={isPlaying ? stop : fetchAndPlay}
          disabled={isLoading}
          className={`p-1.5 rounded-full border ${isPlaying ? 'border-red-500/50 text-red-400 hover:bg-red-950/50' : 'border-red-700/50 text-red-500 hover:bg-red-950/30'} transition-colors ${isLoading ? 'opacity-50' : ''}`}
          title={isPlaying ? 'Stop' : 'Play latest intercept'}
        >
          {isPlaying ? <Square size={12} /> : <Play size={12} className="ml-0.5" />}
        </button>
        <button
          onClick={toggleScan}
          className={`px-2 py-1 text-[9px] font-mono border tracking-wider flex items-center gap-1.5 ${isScanning ? 'bg-red-900/60 border-red-400 text-red-300 animate-pulse' : 'border-red-800/50 text-red-600 hover:border-red-500'} transition-colors`}
          title="Auto-scan: continuously play intercepted bursts"
        >
          <FastForward size={10} />
          {isScanning ? 'SCANNING...' : 'AUTO SCAN'}
        </button>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={volume}
          onChange={(e) => setVolume(parseFloat(e.target.value))}
          className="w-16 accent-red-500 ml-auto"
          title="Volume"
        />
      </div>

      {/* Waveform visualizer */}
      <div className="flex items-end gap-[2px] h-6 opacity-70 mb-2">
        {Array.from({ length: 36 }).map((_, i) => (
          <motion.div
            key={i}
            className={`w-[3px] rounded-t-sm ${isPlaying ? 'bg-red-500' : 'bg-red-900/40'}`}
            animate={{
              height: isPlaying ? ['10%', `${Math.random() * 80 + 20}%`, '10%'] : '10%',
            }}
            transition={{
              repeat: Infinity,
              duration: Math.random() * 0.5 + 0.3,
              ease: 'easeInOut',
            }}
          />
        ))}
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2">
        <button
          onClick={onFlyTo}
          className="flex-1 text-center px-2 py-1.5 border border-[var(--border-primary)] hover:border-red-400/50 hover:text-red-400 text-[var(--text-muted)] text-[9px] font-mono tracking-widest transition-colors flex items-center justify-center gap-1.5"
        >
          <Globe size={10} /> RE-LOCK
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SdrTracker — in-app KiwiSDR receiver for tracked SDR stations
// Opens a compact popup window (KiwiSDR uses HTTP + WebSockets so iframes
// are blocked by mixed-content policies on HTTPS pages).
// ---------------------------------------------------------------------------
function SdrTracker({
  sdr,
  onRelease,
  onFlyTo,
}: {
  sdr: KiwiSDR;
  onRelease: () => void;
  onFlyTo: () => void;
}) {
  const [isListening, setIsListening] = useState(false);
  const popupRef = useRef<Window | null>(null);

  // Poll to detect when user closes the popup
  useEffect(() => {
    if (!isListening || !popupRef.current) return;
    const timer = setInterval(() => {
      if (popupRef.current?.closed) {
        setIsListening(false);
        popupRef.current = null;
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [isListening]);

  // Close popup on unmount / release
  useEffect(() => {
    return () => {
      popupRef.current?.close();
    };
  }, []);

  const openReceiver = () => {
    if (popupRef.current && !popupRef.current.closed) {
      popupRef.current.focus();
      return;
    }
    if (!sdr.url) return;
    const tuneUrl = `${sdr.url}${sdr.url.includes('?') ? '&' : '?'}n=ShadowBroker`;
    popupRef.current = window.open(
      tuneUrl,
      'kiwisdr_receiver',
      'width=800,height=600,menubar=no,toolbar=no,location=no,status=no',
    );
    setIsListening(true);
  };

  const closeReceiver = () => {
    popupRef.current?.close();
    popupRef.current = null;
    setIsListening(false);
  };

  return (
    <div className="bg-amber-950/20 border border-amber-500/40 p-3 -mt-1 shadow-[0_0_15px_rgba(245,158,11,0.1)]">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Radio size={14} className="text-amber-400" />
          <span className="text-[12px] text-amber-400 font-mono tracking-widest font-bold">
            SDR TRACKER
          </span>
          {isListening && (
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-400 animate-pulse">
              LIVE
            </span>
          )}
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            closeReceiver();
            onRelease();
          }}
          className="text-[8px] font-mono text-[var(--text-muted)] hover:text-red-400 border border-[var(--border-primary)] hover:border-red-400/40 px-1.5 py-0.5 transition-colors"
        >
          RELEASE
        </button>
      </div>

      {/* System info */}
      <div className="flex flex-col p-2 border border-amber-500/20 bg-amber-950/10 mb-2">
        <span className="text-[10px] font-bold font-mono text-amber-300 truncate">
          {(sdr.name || 'REMOTE RECEIVER').toUpperCase()}
        </span>
        <span className="text-[8px] text-[var(--text-muted)] font-mono">
          {sdr.location && <span>{sdr.location} · </span>}
          {sdr.antenna && <span>{sdr.antenna.slice(0, 40)}</span>}
        </span>
        {sdr.bands && (
          <span className="text-[8px] text-amber-400/70 font-mono mt-0.5">
            {(Number(sdr.bands.split('-')[0]) / 1e6).toFixed(0)}-
            {(Number(sdr.bands.split('-')[1]) / 1e6).toFixed(0)} MHz
            {sdr.users !== undefined && ` · ${sdr.users}/${sdr.users_max || '?'} users`}
          </span>
        )}
      </div>

      {/* Waveform visualizer — shows when receiver is open */}
      {isListening && (
        <div className="flex items-end gap-[2px] h-5 opacity-60 mb-2">
          {Array.from({ length: 36 }).map((_, i) => (
            <motion.div
              key={i}
              className="w-[3px] rounded-t-sm bg-amber-500"
              animate={{ height: ['10%', `${Math.random() * 80 + 20}%`, '10%'] }}
              transition={{
                repeat: Infinity,
                duration: Math.random() * 0.5 + 0.3,
                ease: 'easeInOut',
              }}
            />
          ))}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-2">
        <button
          onClick={onFlyTo}
          className="flex-1 text-center px-2 py-1.5 border border-[var(--border-primary)] hover:border-amber-400/50 hover:text-amber-400 text-[var(--text-muted)] text-[9px] font-mono tracking-widest transition-colors flex items-center justify-center gap-1.5"
        >
          <Globe size={10} /> RE-LOCK
        </button>
        {sdr.url && (
          <button
            onClick={isListening ? closeReceiver : openReceiver}
            className={`flex-1 text-center px-2 py-1.5 border text-[9px] font-mono tracking-widest transition-colors flex items-center justify-center gap-1.5 ${
              isListening
                ? 'border-amber-400 bg-amber-500/20 text-amber-300'
                : 'border-amber-500/50 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 hover:border-amber-400'
            }`}
          >
            {isListening ? (
              <>
                <Square size={10} /> CLOSE
              </>
            ) : (
              <>
                <Play size={10} /> TUNE IN
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}

const WorldviewLeftPanel = React.memo(function WorldviewLeftPanel({
  activeLayers,
  setActiveLayers,
  onSettingsClick,
  onLegendClick,
  gibsDate,
  setGibsDate,
  gibsOpacity,
  setGibsOpacity,
  onEntityClick,
  onFlyTo,
  trackedSdr,
  setTrackedSdr,
  trackedScanner,
  setTrackedScanner,
  shodanResultCount = 0,
  sentinelDate,
  setSentinelDate,
  sentinelOpacity,
  setSentinelOpacity,
  sentinelPreset,
  setSentinelPreset,
  isMinimized: isMinimizedProp,
  onMinimizedChange,
}: {
  activeLayers: ActiveLayers;
  setActiveLayers: React.Dispatch<React.SetStateAction<ActiveLayers>>;
  onSettingsClick?: () => void;
  onLegendClick?: () => void;
  gibsDate?: string;
  setGibsDate?: (d: string) => void;
  gibsOpacity?: number;
  setGibsOpacity?: (o: number) => void;
  onEntityClick?: (entity: SelectedEntity) => void;
  onFlyTo?: (lat: number, lng: number) => void;
  trackedSdr?: KiwiSDR | null;
  setTrackedSdr?: (sdr: KiwiSDR | null) => void;
  trackedScanner?: Scanner | null;
  setTrackedScanner?: (s: Scanner | null) => void;
  shodanResultCount?: number;
  sentinelDate?: string;
  setSentinelDate?: (d: string) => void;
  sentinelOpacity?: number;
  setSentinelOpacity?: (o: number) => void;
  sentinelPreset?: string;
  setSentinelPreset?: (p: string) => void;
  isMinimized?: boolean;
  onMinimizedChange?: (minimized: boolean) => void;
}) {
  const data = useDataSnapshot() as import('@/types/dashboard').DashboardData;
  const [internalMinimized, setInternalMinimized] = useState(true);
  const isMinimized = isMinimizedProp !== undefined ? isMinimizedProp : internalMinimized;
  const setIsMinimized = (val: boolean | ((prev: boolean) => boolean)) => {
    const newVal = typeof val === 'function' ? val(isMinimized) : val;
    setInternalMinimized(newVal);
    onMinimizedChange?.(newVal);
  };
  const { theme, toggleTheme, hudColor, cycleHudColor } = useTheme();
  const [gibsPlaying, setGibsPlaying] = useState(false);
  const [potusEnabled, setPotusEnabled] = useState(true);
  const gibsIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Sentinel tile loading feedback
  const [sentinelInflight, setSentinelInflight] = useState(0);
  const [sentinelLoaded, setSentinelLoaded] = useState(0);
  useEffect(() => {
    const unsub = onTileLoadingChange((inflight, loaded) => {
      setSentinelInflight(inflight);
      setSentinelLoaded(loaded);
    });
    return unsub;
  }, []);
  // Reset counters when sentinel layer is toggled off or settings change
  useEffect(() => {
    if (activeLayers.sentinel_hub) {
      resetTileLoading();
    }
  }, [activeLayers.sentinel_hub, sentinelPreset, sentinelDate]);

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
    return () => {
      if (gibsIntervalRef.current) clearInterval(gibsIntervalRef.current);
    };
  }, [gibsPlaying, gibsDate, setGibsDate]);

  // Compute ship category counts (memoized — ships array can be 1000+ items)
  const {
    militaryShipCount,
    cargoShipCount,
    passengerShipCount,
    civilianShipCount,
    trackedYachtCount,
  } = useMemo(() => {
    const ships = data?.ships;
    if (!ships || !ships.length)
      return {
        militaryShipCount: 0,
        cargoShipCount: 0,
        passengerShipCount: 0,
        civilianShipCount: 0,
        trackedYachtCount: 0,
      };
    let military = 0,
      cargo = 0,
      passenger = 0,
      civilian = 0,
      trackedYacht = 0;
    for (const s of ships) {
      if (s.yacht_alert) {
        trackedYacht++;
        continue;
      }
      const t = s.type;
      if (t === 'carrier' || t === 'military_vessel') military++;
      else if (t === 'tanker' || t === 'cargo') cargo++;
      else if (t === 'passenger') passenger++;
      else civilian++;
    }
    return {
      militaryShipCount: military,
      cargoShipCount: cargo,
      passengerShipCount: passenger,
      civilianShipCount: civilian,
      trackedYachtCount: trackedYacht,
    };
  }, [data?.ships]);

  // Compute SIGINT source counts
  const { meshtasticCount, aprsCount } = useMemo(() => {
    const totals = data?.sigint_totals;
    if (totals) {
      return {
        meshtasticCount: Number(totals.meshtastic || 0),
        aprsCount: Number(totals.aprs || 0) + Number(totals.js8call || 0),
      };
    }
    const sigs = data?.sigint;
    if (!sigs || !sigs.length) return { meshtasticCount: 0, aprsCount: 0 };
    let mesh = 0,
      aprs = 0;
    for (const s of sigs) {
      if (s.source === 'meshtastic') mesh++;
      else aprs++;
    }
    return { meshtasticCount: mesh, aprsCount: aprs };
  }, [data?.sigint, data?.sigint_totals]);

  const cctvCount = Number(data?.cctv_total || data?.cctv?.length || 0);
  const satnogsCount = Number(data?.satnogs_total || data?.satnogs_stations?.length || 0);
  const tinygsCount = Number(data?.tinygs_total || data?.tinygs_satellites?.length || 0);

  // Find POTUS fleet planes currently airborne from tracked flights
  const potusFlights = useMemo(() => {
    const tracked = data?.tracked_flights;
    if (!tracked) return [];
    const results: {
      index: number;
      flight: TrackedFlight;
      meta: { label: string; type: string };
    }[] = [];
    for (let i = 0; i < tracked.length; i++) {
      const f = tracked[i];
      const icao = (f.icao24 || '').toUpperCase();
      if (POTUS_ICAOS[icao]) {
        results.push({ index: i, flight: f, meta: POTUS_ICAOS[icao] });
      }
    }
    return results;
  }, [data?.tracked_flights]);

  const sections = [
    {
      label: 'AIRCRAFT',
      icon: Plane,
      layers: [
        {
          id: 'flights',
          name: 'Commercial Flights',
          source: 'adsb.lol',
          count: data?.commercial_flights?.length || 0,
          icon: Plane,
        },
        {
          id: 'private',
          name: 'Private Flights',
          source: 'adsb.lol',
          count: data?.private_flights?.length || 0,
          icon: Plane,
        },
        {
          id: 'jets',
          name: 'Private Jets',
          source: 'adsb.lol',
          count: data?.private_jets?.length || 0,
          icon: Plane,
        },
        {
          id: 'military',
          name: 'Military Flights',
          source: 'adsb.lol',
          count: data?.military_flights?.length || 0,
          icon: AlertTriangle,
        },
        {
          id: 'tracked',
          name: 'Tracked Aircraft',
          source: 'Plane-Alert DB',
          count: data?.tracked_flights?.length || 0,
          icon: Eye,
        },
        {
          id: 'gps_jamming',
          name: 'GPS Jamming',
          source: 'ADS-B NACp',
          count: data?.gps_jamming?.length || 0,
          icon: Radio,
        },
      ],
    },
    {
      label: 'MARITIME',
      icon: Ship,
      layers: [
        {
          id: 'ships_military',
          name: 'Military / Carriers',
          source: 'AIS Stream',
          count: militaryShipCount,
          icon: Ship,
        },
        {
          id: 'ships_cargo',
          name: 'Cargo / Tankers',
          source: 'AIS Stream',
          count: cargoShipCount,
          icon: Ship,
        },
        {
          id: 'ships_civilian',
          name: 'Civilian Vessels',
          source: 'AIS Stream',
          count: civilianShipCount,
          icon: Anchor,
        },
        {
          id: 'ships_passenger',
          name: 'Cruise / Passenger',
          source: 'AIS Stream',
          count: passengerShipCount,
          icon: Anchor,
        },
        {
          id: 'ships_tracked_yachts',
          name: 'Tracked Yachts',
          source: 'Yacht-Alert DB',
          count: trackedYachtCount,
          icon: Eye,
        },
        {
          id: 'fishing_activity',
          name: 'Fishing Activity',
          source: 'Global Fishing Watch',
          count: data?.fishing_activity?.length || 0,
          icon: Fish,
        },
      ],
    },
    {
      label: 'SPACE',
      icon: Satellite,
      layers: [
        {
          id: 'satellites',
          name: 'Satellites',
          source:
            data?.satellite_source === 'celestrak'
              ? 'CelesTrak SGP4'
              : data?.satellite_source === 'tle_api'
                ? 'TLE API · SGP4'
                : data?.satellite_source === 'disk_cache'
                  ? 'Cached · SGP4 (est.)'
                  : 'CelesTrak SGP4',
          count: data?.satellites?.length || 0,
          icon: Satellite,
        },
        {
          id: 'gibs_imagery',
          name: 'MODIS Terra (Daily)',
          source: 'NASA GIBS',
          count: null,
          icon: Globe,
        },
        {
          id: 'highres_satellite',
          name: 'High-Res Satellite',
          source: 'Esri World Imagery',
          count: null,
          icon: Satellite,
        },
        {
          id: 'sentinel_hub',
          name: 'Sentinel Hub',
          source: 'Copernicus CDSE',
          count: null,
          icon: Satellite,
        },
        {
          id: 'viirs_nightlights',
          name: 'VIIRS Night Lights',
          source: 'NASA GIBS',
          count: null,
          icon: Moon,
        },
      ],
    },
    {
      label: 'HAZARDS',
      icon: AlertTriangle,
      layers: [
        {
          id: 'earthquakes',
          name: 'Earthquakes (24h)',
          source: 'USGS',
          count: data?.earthquakes?.length || 0,
          icon: Activity,
        },
        {
          id: 'firms',
          name: 'Fire Hotspots (24h)',
          source: 'NASA FIRMS VIIRS',
          count: data?.firms_fires?.length || 0,
          icon: Flame,
        },
        {
          id: 'ukraine_alerts',
          name: 'Ukraine Air Raids',
          source: 'alerts.in.ua',
          count: data?.ukraine_alerts?.length || 0,
          icon: AlertTriangle,
        },
        {
          id: 'weather_alerts',
          name: 'Severe Weather',
          source: 'NOAA/NWS',
          count: data?.weather_alerts?.length || 0,
          icon: CloudLightning,
        },
        {
          id: 'volcanoes',
          name: 'Volcanoes',
          source: 'Smithsonian GVP',
          count: data?.volcanoes?.length || 0,
          icon: Mountain,
        },
        {
          id: 'air_quality',
          name: 'Air Quality',
          source: 'OpenAQ',
          count: data?.air_quality?.length || 0,
          icon: Wind,
        },
      ],
    },
    {
      label: 'INFRASTRUCTURE',
      icon: Server,
      layers: [
        {
          id: 'cctv',
          name: 'CCTV Mesh',
          source: 'CCTV Mesh + Street View',
          count: cctvCount,
          icon: Cctv,
        },
        {
          id: 'datacenters',
          name: 'Data Centers',
          source: 'DC Map (GitHub)',
          count: data?.datacenters?.length || 0,
          icon: Server,
        },
        {
          id: 'internet_outages',
          name: 'Internet Outages',
          source: 'IODA + RIPE Atlas',
          count: data?.internet_outages?.length || 0,
          icon: Wifi,
        },
        {
          id: 'power_plants',
          name: 'Power Plants',
          source: 'WRI (Static)',
          count: data?.power_plants?.length || 0,
          icon: Zap,
        },
        {
          id: 'military_bases',
          name: 'Military Bases',
          source: 'OSINT (Static)',
          count: data?.military_bases?.length || 0,
          icon: Shield,
        },
        {
          id: 'trains',
          name: 'Live Trains',
          source: 'Amtraker + DigiTraffic',
          count: data?.trains?.length || 0,
          icon: TrainFront,
        },
      ],
    },
    {
      label: 'SHODAN',
      icon: Search,
      layers: [
        {
          id: 'shodan_overlay',
          name: 'Shodan Overlay',
          source: 'Operator Search',
          count: shodanResultCount,
          icon: Search,
        },
      ],
    },
    {
      label: 'SIGINT',
      icon: Radio,
      layers: [
        {
          id: 'kiwisdr',
          name: 'SDR Receivers',
          source: 'KiwiSDR.com',
          count: data?.kiwisdr?.length || 0,
          icon: Radio,
        },
        {
          id: 'psk_reporter',
          name: 'HF Digital Spots',
          source: 'PSK Reporter',
          count: data?.psk_reporter?.length || 0,
          icon: Radio,
        },
        {
          id: 'satnogs',
          name: 'Sat Ground Stations',
          source: 'SatNOGS',
          count: satnogsCount,
          icon: Satellite,
        },
        {
          id: 'tinygs',
          name: 'LoRa Satellites',
          source: 'TinyGS',
          count: tinygsCount,
          icon: Satellite,
        },
        {
          id: 'scanners',
          name: 'Police Scanners',
          source: 'OpenMHZ',
          count: data?.scanners?.length || 0,
          icon: Radio,
        },
        {
          id: 'sigint_meshtastic',
          name: 'Meshtastic',
          source: 'LoRa MQTT',
          count: meshtasticCount,
          icon: Radio,
        },
        {
          id: 'sigint_aprs',
          name: 'APRS / JS8Call',
          source: 'APRS-IS / JS8',
          count: aprsCount,
          icon: Radio,
        },
      ],
    },
    {
      label: 'OVERLAYS',
      icon: Globe,
      layers: [
        {
          id: 'ukraine_frontline',
          name: 'Ukraine Frontline',
          source: 'DeepStateMap',
          count: data?.frontlines ? 1 : 0,
          icon: AlertTriangle,
        },
        {
          id: 'global_incidents',
          name: 'Global Incidents',
          source: 'GDELT',
          count: data?.gdelt?.length || 0,
          icon: Activity,
        },
        {
          id: 'correlations',
          name: 'Correlations',
          source: 'Cross-Layer Analysis',
          count: data?.correlations?.length || 0,
          icon: Zap,
        },
        {
          id: 'day_night',
          name: 'Day / Night Cycle',
          source: 'Solar Calc',
          count: null,
          icon: Sun,
        },
      ],
    },
  ];

  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    sections.forEach((s) => {
      initial[s.label] = false;
    });
    return initial;
  });

  const shipIcon = (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 21c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1 .6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1" />
      <path d="M19.38 20A11.6 11.6 0 0 0 21 14l-9-4-9 4c0 2.9.94 5.34 2.81 7.76" />
      <path d="M19 13V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6" />
    </svg>
  );

  return (
    <motion.div
      initial={{ opacity: 0, x: -50 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 1 }}
      className={`w-full flex flex-col pointer-events-none ${isMinimized ? 'flex-shrink-0' : 'flex-1 min-h-[300px]'}`}
    >
      {/* Header */}
      <div className="mb-6 pointer-events-auto">
        <div className="text-[10px] text-[var(--text-secondary)] font-mono tracking-widest mb-1">
          TOP SECRET // SI-TK // NOFORN
        </div>
        <div className="text-[10px] text-[var(--text-muted)] font-mono tracking-widest mb-4">
          KH11-4094 OPS-4168
        </div>
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold tracking-[0.2em] text-[var(--text-heading)]">FLIR</h1>
          <button
            onClick={toggleTheme}
            className={`w-7 h-7 border border-[var(--border-primary)] hover:border-cyan-500/50 flex items-center justify-center ${theme === 'dark' ? 'text-cyan-400' : 'text-[var(--text-muted)]'} hover:text-cyan-300 transition-all hover:bg-[var(--hover-accent)]`}
            title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
          >
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          </button>
          <button
            onClick={cycleHudColor}
            className={`w-7 h-7 border border-[var(--border-primary)] hover:border-cyan-500/50 flex items-center justify-center text-cyan-400 hover:text-cyan-300 transition-all hover:bg-[var(--hover-accent)]`}
            title={hudColor === 'cyan' ? 'Switch to Matrix HUD' : 'Switch to Cyan HUD'}
          >
            <Palette size={14} />
          </button>
          {onSettingsClick && (
            <button
              onClick={onSettingsClick}
              className={`w-7 h-7 border border-[var(--border-primary)] hover:border-cyan-500/50 flex items-center justify-center ${theme === 'dark' ? 'text-cyan-400' : 'text-[var(--text-muted)]'} hover:text-cyan-300 transition-all hover:bg-[var(--hover-accent)] group`}
              title="System Settings"
            >
              <Settings
                size={14}
                className="group-hover:rotate-90 transition-transform duration-300"
              />
            </button>
          )}
          {onLegendClick && (
            <button
              onClick={onLegendClick}
              className={`h-7 px-2 border border-[var(--border-primary)] hover:border-cyan-500/50 flex items-center justify-center gap-1 ${theme === 'dark' ? 'text-cyan-400' : 'text-[var(--text-muted)]'} hover:text-cyan-300 transition-all hover:bg-[var(--hover-accent)]`}
              title="Map Legend / Icon Key"
            >
              <BookOpen size={12} />
              <span className="text-[8px] font-mono tracking-widest font-bold">KEY</span>
            </button>
          )}
          <span
            className={`h-7 px-2 border border-[var(--border-primary)] flex items-center justify-center text-[8px] ${theme === 'dark' ? 'text-cyan-400' : 'text-[var(--text-muted)]'} font-mono tracking-widest select-none`}
          >
            v{packageJson.version}
          </span>
        </div>
      </div>

      {/* Data Layers Box */}
      <div className={`bg-[#0a0a0a]/90 backdrop-blur-sm border border-cyan-900/40 pointer-events-auto flex flex-col relative overflow-hidden max-h-full ${isMinimized ? 'flex-shrink-0' : 'flex-1 min-h-0'}`}>
        {/* Header / Toggle */}
        <div 
          className="flex justify-between items-center p-4 cursor-pointer hover:bg-[var(--bg-secondary)]/50 transition-colors border-b border-[var(--border-primary)]/50"
          onClick={() => setIsMinimized(!isMinimized)}
        >
          <span
            className="text-[12px] text-[var(--text-muted)] font-mono tracking-widest"
          >
            DATA LAYERS
          </span>
          <div className="flex items-center gap-2">
            <button
              title={
                Object.entries(activeLayers)
                  .filter(([k]) => !['gibs_imagery', 'highres_satellite', 'sentinel_hub', 'viirs_nightlights'].includes(k))
                  .every(([, v]) => v)
                  ? 'Disable all layers'
                  : 'Enable all layers'
              }
              className={`${
                Object.entries(activeLayers)
                  .filter(([k]) => !['gibs_imagery', 'highres_satellite', 'sentinel_hub', 'viirs_nightlights'].includes(k))
                  .every(([, v]) => v)
                  ? 'text-cyan-400'
                  : 'text-[var(--text-muted)]'
              } hover:text-cyan-400 transition-colors`}
              onClick={(e) => {
                e.stopPropagation();
                const excluded = new Set(['gibs_imagery', 'highres_satellite', 'sentinel_hub', 'viirs_nightlights']);
                const allOn = Object.entries(activeLayers)
                  .filter(([k]) => !excluded.has(k))
                  .every(([, v]) => v);
                setActiveLayers((prev: ActiveLayers) => {
                  const next = { ...prev } as ActiveLayers;
                  for (const k of Object.keys(prev) as Array<keyof ActiveLayers>) {
                    next[k] = excluded.has(k) ? prev[k] : !allOn;
                  }
                  return next;
                });
              }}
            >
              {Object.entries(activeLayers)
                .filter(([k]) => !['gibs_imagery', 'highres_satellite', 'sentinel_hub', 'viirs_nightlights'].includes(k))
                .every(([, v]) => v) ? (
                <ToggleRight size={16} />
              ) : (
                <ToggleLeft size={16} />
              )}
            </button>
            <button
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              {isMinimized ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
            </button>
          </div>
        </div>

        <AnimatePresence>
          {!isMinimized && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-y-auto styled-scrollbar"
            >
              <div className="flex flex-col gap-6 p-4 pt-2 pb-6">
                {/* SDR TRACKER — pinned to TOP when active, with embedded receiver */}
                {trackedSdr && (
                  <SdrTracker
                    sdr={trackedSdr}
                    onRelease={() => setTrackedSdr?.(null)}
                    onFlyTo={() => onFlyTo?.(trackedSdr.lat, trackedSdr.lon)}
                  />
                )}

                {/* SCANNER TRACKER — pinned when active, with in-app audio player */}
                {trackedScanner && (
                  <ScannerTracker
                    scanner={trackedScanner}
                    onRelease={() => setTrackedScanner?.(null)}
                    onFlyTo={() => onFlyTo?.(trackedScanner.lat, trackedScanner.lng)}
                  />
                )}

                {/* POTUS Fleet — pinned to TOP when aircraft are active */}
                {potusEnabled && potusFlights.length > 0 && (
                  <div className="bg-[#ff1493]/5 border border-[#ff1493]/30 p-3 -mt-1">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Shield size={14} className="text-[#ff1493]" />
                        <span className="text-[12px] text-[#ff1493] font-mono tracking-widest font-bold">
                          POTUS FLEET
                        </span>
                        <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-full bg-[#ff1493]/20 border border-[#ff1493]/40 text-[#ff1493] animate-pulse">
                          {potusFlights.length} ACTIVE
                        </span>
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setPotusEnabled(false);
                        }}
                        className="text-[8px] font-mono text-[var(--text-muted)] hover:text-[#ff1493] border border-[var(--border-primary)] hover:border-[#ff1493]/40 px-1.5 py-0.5 transition-colors"
                        title="Hide POTUS Fleet tracker"
                      >
                        HIDE
                      </button>
                    </div>
                    <div className="flex flex-col gap-2">
                      {potusFlights.map((pf) => {
                        const color =
                          pf.meta.type === 'AF1'
                            ? '#ff1493'
                            : pf.meta.type === 'M1'
                              ? '#ff1493'
                              : '#3b82f6';
                        const alt = pf.flight.alt || 0;
                        const speed = pf.flight.speed_knots || 0;
                        return (
                          <div
                            key={pf.flight.icao24}
                            className="flex items-center justify-between p-2 border cursor-pointer transition-all hover:bg-[var(--bg-secondary)]/60"
                            style={{ borderColor: `${color}40`, background: `${color}10` }}
                            onClick={() => {
                              if (onFlyTo && pf.flight.lat != null && pf.flight.lng != null) {
                                onFlyTo(pf.flight.lat, pf.flight.lng);
                              }
                              if (onEntityClick) {
                                onEntityClick({ type: 'tracked_flight', id: pf.flight.icao24 });
                              }
                            }}
                          >
                            <div className="flex flex-col">
                              <span className="text-[10px] font-bold font-mono" style={{ color }}>
                                {pf.meta.label}
                              </span>
                              <span className="text-[8px] text-[var(--text-muted)] font-mono mt-0.5">
                                {alt > 0 ? `${Math.round(alt).toLocaleString()} ft` : 'GND'} ·{' '}
                                {speed > 0 ? `${Math.round(speed)} kts` : 'STATIC'}
                              </span>
                            </div>
                            <div className="flex items-center gap-1.5">
                              <div
                                className="w-1.5 h-1.5 rounded-full animate-pulse"
                                style={{ backgroundColor: color }}
                              />
                              <span className="text-[8px] font-mono" style={{ color }}>
                                TRACK
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {sections.map((section) => {
                  const SectionIcon = section.icon;
                  const sectionLayerIds = section.layers.map((l) => l.id);
                  const allOn = sectionLayerIds.every(
                    (id) => activeLayers[id as keyof typeof activeLayers],
                  );
                  const anyOn = sectionLayerIds.some(
                    (id) => activeLayers[id as keyof typeof activeLayers],
                  );
                  const expanded = expandedSections[section.label] ?? true;
                  const totalCount = section.layers.reduce(
                    (sum, l) => sum + ((l.count as number) || 0),
                    0,
                  );

                  return (
                    <div key={section.label} className="flex flex-col">
                      {/* Section header */}
                      <div className="flex items-center justify-between mb-1">
                        <div
                          className="flex items-center gap-2 cursor-pointer flex-1"
                          onClick={() =>
                            setExpandedSections((prev) => ({ ...prev, [section.label]: !expanded }))
                          }
                        >
                          <SectionIcon
                            size={12}
                            className={`${
                              section.label === 'SHODAN'
                                ? anyOn
                                  ? 'text-green-400'
                                  : 'text-green-700/70'
                                : anyOn
                                  ? 'text-cyan-400'
                                  : 'text-[var(--text-muted)]'
                            } transition-colors`}
                          />
                          <span
                            className={`text-[11px] font-mono tracking-[0.2em] font-bold ${
                              section.label === 'SHODAN' ? 'text-green-400' : 'text-[var(--text-muted)]'
                            }`}
                          >
                            {section.label}
                          </span>
                          {anyOn && totalCount > 0 && (
                            <span
                              className={`text-[8px] font-mono ${
                                section.label === 'SHODAN' ? 'text-green-500/70' : 'text-cyan-500/50'
                              }`}
                            >
                              {totalCount.toLocaleString()}
                            </span>
                          )}
                          {expanded ? (
                            <ChevronUp size={10} className="text-[var(--text-muted)]" />
                          ) : (
                            <ChevronDown size={10} className="text-[var(--text-muted)]" />
                          )}
                        </div>
                        <button
                          className="relative w-8 h-4 rounded-full transition-colors shrink-0"
                          style={{
                            backgroundColor: allOn
                              ? section.label === 'SHODAN' ? 'rgb(34 197 94 / 0.5)' : 'rgb(6 182 212 / 0.5)'
                              : anyOn
                                ? 'rgb(6 182 212 / 0.25)'
                                : 'rgb(100 116 139 / 0.3)',
                          }}
                          onClick={() => {
                            setActiveLayers((prev: ActiveLayers) => {
                              const next = { ...prev } as ActiveLayers;
                              for (const id of sectionLayerIds as Array<keyof ActiveLayers>) {
                                next[id] = !allOn;
                              }
                              return next;
                            });
                          }}
                          title={
                            allOn ? `Disable all ${section.label}` : `Enable all ${section.label}`
                          }
                        >
                          <span
                            className="absolute top-0.5 w-3 h-3 rounded-full transition-all"
                            style={{
                              left: allOn ? '18px' : anyOn ? '10px' : '2px',
                              backgroundColor: allOn
                                ? section.label === 'SHODAN' ? 'rgb(74 222 128)' : 'rgb(34 211 238)'
                                : anyOn
                                  ? 'rgb(34 211 238 / 0.6)'
                                  : 'rgb(148 163 184 / 0.5)',
                            }}
                          />
                        </button>
                      </div>

                      {/* Section layers (collapsible) */}
                      {expanded && (
                        <div className="flex flex-col gap-3 ml-1 pl-3 border-l border-[var(--border-primary)]/30 mt-2 mb-2">
                          {section.layers.map((layer) => {
                            const Icon = layer.icon;
                            const active =
                              activeLayers[layer.id as keyof typeof activeLayers] || false;

                            return (
                              <div key={layer.id} className="flex flex-col">
                                <div
                                  className="flex items-start justify-between group cursor-pointer"
                                  onClick={() =>
                                    setActiveLayers((prev: ActiveLayers) => ({
                                      ...prev,
                                      [layer.id]: !active,
                                    }))
                                  }
                                >
                                  <div className="flex gap-3">
                                    <div
                                      className={`mt-0.5 ${
                                        layer.id === 'shodan_overlay'
                                          ? active
                                            ? 'text-green-400'
                                            : 'text-green-700/70 group-hover:text-green-500'
                                          : active
                                            ? 'text-cyan-400'
                                            : 'text-gray-600 group-hover:text-gray-400'
                                      } transition-colors`}
                                    >
                                      {layer.id.startsWith('ships_') ? (
                                        shipIcon
                                      ) : (
                                        <Icon size={14} strokeWidth={1.5} />
                                      )}
                                    </div>
                                    <div className="flex flex-col">
                                      <span
                                        className={`text-[12px] font-medium ${
                                          layer.id === 'shodan_overlay'
                                            ? active
                                              ? 'text-green-300'
                                              : 'text-green-700/70'
                                            : active
                                              ? 'text-[var(--text-primary)]'
                                              : 'text-[var(--text-secondary)]'
                                        } tracking-wide`}
                                      >
                                        {layer.name}
                                      </span>
                                      <span className="text-[8px] text-[var(--text-muted)] font-mono tracking-wider mt-0.5">
                                        {layer.id === 'shodan_overlay'
                                          ? layer.source
                                          : (
                                              <>
                                                {layer.source} ·{' '}
                                                {active
                                                  ? (() => {
                                                      const fKey = FRESHNESS_MAP[layer.id];
                                                      const freshness =
                                                        fKey && data?.freshness?.[fKey];
                                                      const rt = freshness
                                                        ? relativeTime(freshness)
                                                        : '';
                                                      return rt ? (
                                                        <span className="text-cyan-500/70">
                                                          {rt}
                                                        </span>
                                                      ) : (
                                                        'LIVE'
                                                      );
                                                    })()
                                                  : 'OFF'}
                                              </>
                                            )}
                                      </span>
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    {active && (layer.count ?? 0) > 0 && (
                                      <span className="text-[9px] text-gray-300 font-mono">
                                        {(layer.count ?? 0).toLocaleString()}
                                      </span>
                                    )}
                                    {layer.id !== 'shodan_overlay' && (
                                      <div
                                        className={`text-[8px] font-mono tracking-wider px-1.5 py-0.5 rounded-full border ${
                                          active
                                            ? layer.id === 'shodan_overlay'
                                              ? 'border-green-500/50 text-green-400 bg-green-950/30 shadow-[0_0_10px_rgba(34,197,94,0.2)]'
                                              : layer.id === 'sentinel_hub'
                                                ? 'border-purple-500/50 text-purple-400 bg-purple-950/30 shadow-[0_0_10px_rgba(168,85,247,0.2)]'
                                                : 'border-cyan-500/50 text-cyan-400 bg-cyan-950/30 shadow-[0_0_10px_rgba(34,211,238,0.2)]'
                                          : 'border-[var(--border-primary)] text-[var(--text-muted)] bg-transparent'
                                        }`}
                                      >
                                        {active
                                          ? layer.id === 'sentinel_hub'
                                            ? 'SCAN'
                                            : 'ON'
                                          : 'OFF'}
                                      </div>
                                    )}
                                  </div>
                                </div>
                                {/* GIBS Imagery inline controls */}
                                {active &&
                                  layer.id === 'gibs_imagery' &&
                                  gibsDate &&
                                  setGibsDate &&
                                  setGibsOpacity && (
                                    <div
                                      className="ml-7 mt-2 flex flex-col gap-2"
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      <div className="flex items-center gap-2">
                                        <button
                                          onClick={() => setGibsPlaying((p) => !p)}
                                          className="w-5 h-5 flex items-center justify-center border border-cyan-500/30 text-cyan-400 hover:bg-cyan-950/30 transition-colors"
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
                                            const diff = Math.round(
                                              (yesterday.getTime() - selected.getTime()) / 86400000,
                                            );
                                            return 29 - Math.max(0, Math.min(29, diff));
                                          })()}
                                          onChange={(e) => {
                                            const daysAgo = 29 - parseInt(e.target.value);
                                            const d = new Date();
                                            d.setDate(d.getDate() - 1 - daysAgo);
                                            setGibsDate(d.toISOString().slice(0, 10));
                                          }}
                                          className="flex-1 h-1 accent-cyan-500 cursor-pointer"
                                        />
                                      </div>
                                      <div className="flex items-center justify-between">
                                        <span className="text-[8px] text-cyan-400 font-mono">
                                          {gibsDate}
                                        </span>
                                        <div className="flex items-center gap-1">
                                          <span className="text-[8px] text-[var(--text-muted)] font-mono">
                                            OPC
                                          </span>
                                          <input
                                            type="range"
                                            min={0}
                                            max={100}
                                            value={Math.round((gibsOpacity ?? 0.6) * 100)}
                                            onChange={(e) =>
                                              setGibsOpacity(parseInt(e.target.value) / 100)
                                            }
                                            className="w-16 h-1 accent-cyan-500 cursor-pointer"
                                          />
                                        </div>
                                      </div>
                                    </div>
                                  )}
                                {/* Sentinel Hub inline controls */}
                                {active &&
                                  layer.id === 'sentinel_hub' &&
                                  sentinelDate &&
                                  setSentinelDate &&
                                  setSentinelOpacity &&
                                  setSentinelPreset && (
                                    <div
                                      className="ml-7 mt-2 flex flex-col gap-2"
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      {/* Preset selector + loading indicator */}
                                      <div className="flex items-center gap-2">
                                        <select
                                          value={sentinelPreset || 'TRUE-COLOR'}
                                          onChange={(e) => setSentinelPreset(e.target.value)}
                                          className="flex-1 bg-[var(--bg-primary)]/80 border border-purple-500/30 px-2 py-1 text-[9px] font-mono text-purple-300 outline-none focus:border-purple-500 cursor-pointer"
                                        >
                                          <option value="TRUE-COLOR">True Color (S2)</option>
                                          <option value="FALSE-COLOR">False Color IR</option>
                                          <option value="NDVI">NDVI</option>
                                          <option value="MOISTURE-INDEX">Moisture Index</option>
                                        </select>
                                        {sentinelInflight > 0 ? (
                                          <span className="text-[8px] font-mono text-purple-400 animate-pulse whitespace-nowrap">
                                            {sentinelInflight} tile{sentinelInflight !== 1 ? 's' : ''}…
                                          </span>
                                        ) : sentinelLoaded > 0 ? (
                                          <span className="text-[8px] font-mono text-purple-500/60 whitespace-nowrap">
                                            {sentinelLoaded} loaded
                                          </span>
                                        ) : null}
                                      </div>
                                      {/* Date slider — 0-29 days back */}
                                      <div className="flex items-center gap-2">
                                        <input
                                          type="range"
                                          min={0}
                                          max={29}
                                          value={(() => {
                                            const today = new Date();
                                            const selected = new Date(sentinelDate + 'T00:00:00');
                                            const diff = Math.round(
                                              (today.getTime() - selected.getTime()) / 86400000,
                                            );
                                            return 29 - Math.max(0, Math.min(29, diff));
                                          })()}
                                          onChange={(e) => {
                                            const daysAgo = 29 - parseInt(e.target.value);
                                            const d = new Date();
                                            d.setDate(d.getDate() - daysAgo);
                                            setSentinelDate(d.toISOString().slice(0, 10));
                                          }}
                                          className="flex-1 h-1 accent-purple-500 cursor-pointer"
                                        />
                                      </div>
                                      <div className="flex items-center justify-between">
                                        <span className="text-[8px] text-purple-400 font-mono">
                                          {sentinelDate}
                                        </span>
                                        <div className="flex items-center gap-1">
                                          <span className="text-[8px] text-[var(--text-muted)] font-mono">
                                            OPC
                                          </span>
                                          <input
                                            type="range"
                                            min={0}
                                            max={100}
                                            value={Math.round((sentinelOpacity ?? 0.6) * 100)}
                                            onChange={(e) =>
                                              setSentinelOpacity(parseInt(e.target.value) / 100)
                                            }
                                            className="w-16 h-1 accent-purple-500 cursor-pointer"
                                          />
                                        </div>
                                      </div>
                                    </div>
                                  )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}

                {/* POTUS Fleet — bottom section when inactive or hidden */}
                {(potusFlights.length === 0 || !potusEnabled) && (
                  <div className="border-t border-[var(--border-primary)]/50 pt-4 mt-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Shield size={14} className="text-[var(--text-muted)]" />
                        <span className="text-[10px] text-[var(--text-muted)] font-mono tracking-widest">
                          POTUS FLEET
                        </span>
                      </div>
                      {!potusEnabled ? (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setPotusEnabled(true);
                          }}
                          className="text-[8px] font-mono text-[var(--text-muted)] hover:text-[#ff1493] border border-[var(--border-primary)] hover:border-[#ff1493]/40 px-1.5 py-0.5 transition-colors"
                        >
                          SHOW
                        </button>
                      ) : (
                        <span className="text-[8px] font-mono text-[var(--text-muted)]">
                          NO ACTIVE AIRCRAFT
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
});

export default WorldviewLeftPanel;
