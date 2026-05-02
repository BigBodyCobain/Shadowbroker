'use client';

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Terminal, Radio, Globe, Key, LogOut, Activity, Vote, User, ArrowRightLeft, Briefcase, Mail, Brain, GitBranch, Cpu, KeyRound } from 'lucide-react';
import { getNodeIdentity, getWormholeIdentityDescriptor } from '@/mesh/meshIdentity';
import {
  activateWormholeGatePersona,
  createWormholeGatePersona,
  enterWormholeGate,
  fetchWormholeIdentity,
  listWormholeGatePersonas,
} from '@/mesh/wormholeIdentityClient';
import GateView from './GateView';
import MarketView from './MarketView';
import ProfileView from './ProfileView';
import MessagesView from './MessagesView';
import TerminalDashboard from './TerminalDashboard';
import WeatherWidget from './WeatherWidget';
import TrendingPosts from './TrendingPosts';
import HashchainEvents from './HashchainEvents';
import NetworkStats from './NetworkStats';
import AIQueryView from './AIQueryView';
import PetitionsView from './PetitionsView';
import UpgradeView from './UpgradeView';
import ResolutionView from './ResolutionView';
import GateShutdownView from './GateShutdownView';
import BootstrapView from './BootstrapView';
import FunctionKeyView from './FunctionKeyView';


const ASCII_HEADER = `
                          T H E
██╗███╗   ██╗███████╗██████╗  ███╗   ██╗███████╗████████╗
██║████╗  ██║██╔════╝██╔═══██╗████╗  ██║██╔════╝╚══██╔══╝
██║██╔██╗ ██║█████╗  ██║   ██║██╔██╗ ██║█████╗     ██║
██║██║╚██╗██║██╔══╝  ██║   ██║██║╚██╗██║██╔══╝     ██║
██║██║ ╚████║██║     ╚██████╔╝██║ ╚████║███████╗   ██║
╚═╝╚═╝  ╚═══╝╚═╝      ╚═════╝ ╚═╝  ╚═══╝╚══════╝   ╚═╝
                       C O M M O N S

         ======================================
          INFONET SOVEREIGN SHELL v0.1.1 (TEST)
            TEST-NET CONNECTION ESTABLISHED
         ======================================
`;

const COMING_SOON_MODULES: Record<string, { title: string; desc: string; status: string }> = {
  // BALLOT entry removed 2026-04-28: the BALLOT command now navigates
  // to PetitionsView (live governance DSL + petition lifecycle).
  GIGS: {
    title: 'GIGS — NETWORK BOUNTIES',
    desc: 'Decentralized work contracts, intelligence bounties, and mesh task allocation. Accept jobs, deliver payloads, and earn credits through verified proof-of-work completion.',
    status: 'MODULE STATUS: TESTNET ONLY — CONTRACT ENGINE IN DEVELOPMENT',
  },
  EXCHANGE: {
    title: 'EXCHANGE — DECENTRALIZED TRADING',
    desc: 'Zero-KYC peer-to-peer asset exchange. Trade crypto against credits with on-chain order books, stealth addresses, and privacy-preserving settlement.',
    status: 'MODULE STATUS: TESTNET ONLY — LIQUIDITY POOLS NOT YET ACTIVE',
  },
};

const GATES = [
  'infonet', 'general-talk', 'gathered-intel', 'tracked-planes',
  'ukraine-front', 'iran-front', 'world-news', 'prediction-markets',
  'finance', 'cryptography', 'cryptocurrencies', 'meet-chat', 'opsec-lab'
];
const GATE_LAUNCH_RETRY_DELAY_MS = 3000;
const GATE_LAUNCH_RETRY_ATTEMPTS = 20;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function isGateLaneStartingError(detail: string): boolean {
  const lowered = String(detail || '').trim().toLowerCase();
  return lowered.includes('obfuscated lane is still starting');
}

const SHELL_ANON_PERSONAS_KEY = 'sb_infonet_shell_anon_personas';

function readShellAnonPersonas(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(SHELL_ANON_PERSONAS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.map((value) => String(value || '').trim()).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function writeShellAnonPersonas(personas: string[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(SHELL_ANON_PERSONAS_KEY, JSON.stringify(personas));
  } catch {
    /* ignore */
  }
}

function allocateShellAnonPersona(): string {
  const existing = readShellAnonPersonas();
  const used = new Set(existing.map((persona) => persona.toLowerCase()));
  for (let attempt = 0; attempt < 10_000; attempt += 1) {
    const candidate = `anon_${Math.floor(100 + Math.random() * 9_900)}`;
    if (used.has(candidate.toLowerCase())) continue;
    writeShellAnonPersonas([...existing, candidate]);
    return candidate;
  }
  const fallback = `anon_${Date.now()}`;
  writeShellAnonPersonas([...existing, fallback]);
  return fallback;
}

const SECTIONS = [
  { name: 'HELP', icon: <Terminal size={14} className="mr-2" /> },
  { name: 'AI', icon: <Brain size={14} className="mr-2" /> },
  { name: 'BALLOT', icon: <Vote size={14} className="mr-2" /> },
  { name: 'UPGRADES', icon: <GitBranch size={14} className="mr-2" /> },
  { name: 'BOOTSTRAP', icon: <Cpu size={14} className="mr-2" /> },
  { name: 'F-KEYS', icon: <KeyRound size={14} className="mr-2" /> },
  { name: 'GIGS', icon: <Briefcase size={14} className="mr-2" /> },
  { name: 'MESH', icon: <Globe size={14} className="mr-2" /> },
  { name: 'GATES', icon: <Key size={14} className="mr-2" /> },
  { name: 'MARKETS', icon: <Activity size={14} className="mr-2" /> },
  { name: 'EXCHANGE', icon: <ArrowRightLeft size={14} className="mr-2" /> },
  { name: 'PROFILE', icon: <User size={14} className="mr-2" /> },
  { name: 'MESSAGES', icon: <Mail size={14} className="mr-2" /> },
  { name: 'EXIT', icon: <LogOut size={14} className="mr-2" /> },
];

interface CommandHistory {
  command: string;
  output: React.ReactNode;
}

interface InfonetShellProps {
  isOpen: boolean;
  onClose: () => void;
  onOpenLiveGate?: (gate: string) => void;
  onOpenDeadDrop?: (peerId: string, options?: { showSas?: boolean }) => void;
}

export default function InfonetShell({
  isOpen,
  onClose,
  onOpenLiveGate,
  onOpenDeadDrop,
}: InfonetShellProps) {
  const [input, setInput] = useState('');
  const [history, setHistory] = useState<CommandHistory[]>([]);
  const [isBooting, setIsBooting] = useState(true);
  const [bootText, setBootText] = useState<string[]>([]);

  // Navigation & State
  type ViewName =
    | 'terminal' | 'gate' | 'market' | 'profile' | 'messages' | 'ai'
    | 'petitions' | 'upgrades' | 'resolution' | 'gate-shutdown'
    | 'bootstrap' | 'function-keys';
  const [currentView, setCurrentView] = useState<ViewName>('terminal');
  const [activeGate, setActiveGate] = useState<string | null>(null);
  const [persona, setPersona] = useState<string | null>(null);
  const [activeGateMode, setActiveGateMode] = useState<'anonymous' | 'persona' | null>(null);
  const [inputMode, setInputMode] = useState<'normal' | 'persona'>('normal');
  const [pendingGate, setPendingGate] = useState<string | null>(null);
  const [isCitizen] = useState(false);
  const [comingSoonModule, setComingSoonModule] = useState<string | null>(null);
  const [wormholePromptKey, setWormholePromptKey] = useState('');
  // Targets for parameterized economy views.
  const [resolutionMarketId, setResolutionMarketId] = useState<string | null>(null);
  const [shutdownGateId, setShutdownGateId] = useState<string | null>(null);
  const [bootstrapMarketId, setBootstrapMarketId] = useState<string | null>(null);

  const endOfTerminalRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const gateLaunchAttemptRef = useRef(0);

  // Real mesh identity
  const nodeIdentity = useMemo(() => getNodeIdentity(), []);
  const wormholeDescriptor = useMemo(() => getWormholeIdentityDescriptor(), []);
  const promptHost = useMemo(
    () =>
      String(
        nodeIdentity?.publicKey || wormholePromptKey || wormholeDescriptor?.publicKey || 'no-public-key',
      ).trim() || 'no-public-key',
    [nodeIdentity?.publicKey, wormholeDescriptor?.publicKey, wormholePromptKey],
  );
  const shellPrompt = `${isCitizen ? 'citizen' : 'sovereign'}@${promptHost}:~$`;

  /* Reset + boot sequence when opened */
  useEffect(() => {
    if (!isOpen) return;

    // Reset state
    setHistory([]);
    setCurrentView('terminal');
    setActiveGate(null);
    setPersona(null);
    setActiveGateMode(null);
    setInputMode('normal');
    setPendingGate(null);
    setInput('');
    gateLaunchAttemptRef.current += 1;
    setIsBooting(true);
    setBootText([]);

    const bootLines = [
      'INITIALIZING KERNEL...',
      'LOADING MODULES: [OK]',
      'MOUNTING VFS: [OK]',
      'STARTING NETWORK INTERFACES...',
      'CONNECTING TO INFONET MESH...',
      'ESTABLISHING SECURE TUNNEL...',
      'HANDSHAKE COMPLETE.',
      'WELCOME SOVEREIGN.'
    ];

    let currentLine = 0;
    const interval = setInterval(() => {
      if (currentLine < bootLines.length) {
        setBootText(prev => [...prev, bootLines[currentLine]]);
        currentLine++;
      } else {
        clearInterval(interval);
        setTimeout(() => setIsBooting(false), 500);
      }
    }, 150);

    return () => clearInterval(interval);
  }, [isOpen]);

  /* Focus input after boot — scoped to container */
  useEffect(() => {
    if (!isBooting && isOpen) {
      inputRef.current?.focus();
      const container = containerRef.current;
      if (!container) return;
      const handleGlobalClick = () => {
        if (window.getSelection()?.toString()) return;
        inputRef.current?.focus();
      };
      container.addEventListener('click', handleGlobalClick);
      return () => container.removeEventListener('click', handleGlobalClick);
    }
  }, [isBooting, isOpen]);

  useEffect(() => {
    let cancelled = false;
    if (!isOpen || nodeIdentity?.publicKey) return;
    void (async () => {
      try {
        const identity = await fetchWormholeIdentity();
        if (!cancelled) {
          setWormholePromptKey(String(identity?.public_key || '').trim());
        }
      } catch {
        if (!cancelled) {
          setWormholePromptKey('');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isOpen, nodeIdentity?.publicKey]);

  /* Scroll to bottom */
  useEffect(() => {
    endOfTerminalRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history]);

  const handleNavigate = (view: 'terminal' | 'gate' | 'market' | 'profile' | 'messages' | 'ai', gate?: string) => {
    if (view === 'gate' && gate) {
      if (onOpenLiveGate) {
        setPendingGate(gate);
        setInputMode('persona');
        setHistory(prev => [...prev, {
          command: `join ${gate}`,
          output: (
            <span className="text-cyan-400">
              Type a gate face label to open the encrypted room, or type
              {' '}
              <span className="font-bold text-white">anon</span>
              {' '}
              for a rotating obfuscated session that opens the room under a fresh gate-scoped key.
              {' '}
              <span className="text-red-400">&apos;shadowbroker&apos; is reserved.</span>
            </span>
          )
        }]);
        return;
      }
      setActiveGate(gate);
      setActiveGateMode(persona ? 'persona' : 'anonymous');
    }
    setCurrentView(view);
  };

  const openGateWhenReady = async (
    gateTarget: string,
    operation: () => Promise<void>,
    options: { commandLabel: string; waitingOutput: React.ReactNode; failurePrefix: string },
  ) => {
    const launchId = ++gateLaunchAttemptRef.current;
    let waitingShown = false;
    for (let attempt = 0; attempt < GATE_LAUNCH_RETRY_ATTEMPTS; attempt += 1) {
      if (gateLaunchAttemptRef.current !== launchId) {
        return;
      }
      try {
        await operation();
        return;
      } catch (error) {
        const detail = error instanceof Error ? error.message : options.failurePrefix;
        if (!isGateLaneStartingError(detail)) {
          if (gateLaunchAttemptRef.current !== launchId) {
            return;
          }
          setHistory(prev => [...prev, {
            command: options.commandLabel,
            output: <span className="text-red-400">ERR: {detail}</span>,
          }]);
          return;
        }
        if (!waitingShown) {
          waitingShown = true;
          setHistory(prev => [...prev, {
            command: options.commandLabel,
            output: options.waitingOutput,
          }]);
        }
        if (attempt === GATE_LAUNCH_RETRY_ATTEMPTS - 1) {
          if (gateLaunchAttemptRef.current !== launchId) {
            return;
          }
          setHistory(prev => [...prev, {
            command: options.commandLabel,
            output: (
              <span className="text-red-400">
                ERR: The obfuscated lane is taking too long to come online. It is still warming up in the background.
              </span>
            ),
          }]);
          return;
        }
        await sleep(GATE_LAUNCH_RETRY_DELAY_MS);
      }
    }
  };

  const handleCommand = (cmd: string) => {
    const trimmedCmd = cmd.trim().toLowerCase();
    let output: React.ReactNode = '';

    if (trimmedCmd === '') return;

    if (inputMode === 'persona') {
      if (trimmedCmd === 'shadowbroker') {
        output = <span className="text-red-500 font-bold animate-pulse">ERR: Persona &apos;shadowbroker&apos; is reserved and cannot be claimed.</span>;
        setHistory(prev => [...prev, { command: cmd, output }]);
        return;
      }
      if (!pendingGate) {
        setInputMode('normal');
        output = <span className="text-red-400">ERR: No pending gate launch target.</span>;
        setHistory(prev => [...prev, { command: cmd, output }]);
        return;
      }
      const chosenPersona = trimmedCmd === 'anon' ? allocateShellAnonPersona() : cmd.trim();
      setPersona(chosenPersona);
      setInputMode('normal');
      const gateTarget = pendingGate;
      if (trimmedCmd === 'anon') {
        output = (
          <span className="text-amber-300">
            Rotating anonymous gate key for g/{gateTarget}...
          </span>
        );
        setHistory(prev => [...prev, { command: cmd, output }]);
        setPendingGate(null);
        void (async () => {
          await openGateWhenReady(
            gateTarget,
            async () => {
              await enterWormholeGate(gateTarget, true);
              setActiveGateMode('anonymous');
              setActiveGate(gateTarget);
              setCurrentView('gate');
            },
            {
              commandLabel: `gate ${gateTarget}`,
              waitingOutput: (
                <span className="text-cyan-400">
                  Warming the obfuscated lane for g/{gateTarget}. The room will open automatically as soon as it is ready.
                </span>
              ),
              failurePrefix: 'anonymous_gate_enter_failed',
            },
          );
        })();
        return;
      }
      output = <span className="text-green-400">Creating gate face &apos;{chosenPersona}&apos; for g/{gateTarget}...</span>;
      setHistory(prev => [...prev, { command: cmd, output }]);
      setPendingGate(null);
      void (async () => {
        await openGateWhenReady(
          gateTarget,
          async () => {
            const personas = await listWormholeGatePersonas(gateTarget);
            const existing = Array.isArray(personas?.personas)
              ? personas.personas.find(
                  (candidate) =>
                    String(candidate?.label || '').trim().toLowerCase() === chosenPersona.toLowerCase(),
                )
              : null;
            const result = existing?.persona_id
              ? await activateWormholeGatePersona(gateTarget, existing.persona_id)
              : await createWormholeGatePersona(gateTarget, chosenPersona);
            if (!result?.ok) {
              throw new Error(result?.detail || 'gate_face_create_failed');
            }
            setActiveGateMode('persona');
            setActiveGate(gateTarget);
            setCurrentView('gate');
          },
          {
            commandLabel: `join ${gateTarget}`,
            waitingOutput: (
              <span className="text-cyan-400">
                Warming the obfuscated lane for g/{gateTarget}. Your gate face will open automatically when the room is ready.
              </span>
            ),
            failurePrefix: 'gate_face_create_failed',
          },
        );
      })();
      return;
    }

    if (trimmedCmd === 'help') {
      output = (
        <div className="text-gray-400">
          <p>AVAILABLE COMMANDS:</p>
          <ul className="list-disc list-inside ml-2 mt-1">
            <li><span className="text-gray-300 font-bold">help</span> - Display this message</li>
            <li><span className="text-gray-300 font-bold">clear</span> - Clear terminal output</li>
            <li><span className="text-gray-300 font-bold">mesh</span> - Access public mesh ledger</li>
            <li><span className="text-gray-300 font-bold">radio</span> - Open SIGINT / radio surfaces</li>
            <li><span className="text-gray-300 font-bold">messages</span> - Open Secure Comms</li>
            <li><span className="text-gray-300 font-bold">profile</span> - View sovereign identity & ledger</li>
            <li><span className="text-gray-300 font-bold">ballot / petitions / governance</span> - File / sign / vote on petitions (DSL executor)</li>
            <li><span className="text-gray-300 font-bold">upgrades</span> - Upgrade-hash governance + Heavy-Node readiness</li>
            <li><span className="text-gray-300 font-bold">resolution [market_id]</span> - Evidence + dispute view</li>
            <li><span className="text-gray-300 font-bold">shutdown [gate_id]</span> - Gate suspend / shutdown / appeal lifecycle</li>
            <li><span className="text-gray-300 font-bold">bootstrap</span> - Bootstrap-mode resolution + ramp milestones</li>
            <li><span className="text-gray-300 font-bold">fkeys / function-keys</span> - Anonymous citizenship proof design</li>
            <li><span className="text-gray-300 font-bold">gigs</span> - View network bounties & jobs</li>
            <li><span className="text-gray-300 font-bold">markets</span> - View prediction markets</li>
            <li><span className="text-gray-300 font-bold">exchange</span> - Decentralized crypto exchange</li>
            <li><span className="text-gray-300 font-bold">wormhole</span> - Check secure tunneling status</li>
            <li><span className="text-gray-300 font-bold">gates</span> - List available obfuscated gates</li>
            <li><span className="text-gray-300 font-bold">join [gate]</span> - Choose anonymous entry or a gate face, then enter the room</li>
            <li><span className="text-gray-300 font-bold">exit</span> - Disconnect from Infonet</li>
          </ul>
        </div>
      );
    } else if (trimmedCmd === 'clear') {
      setHistory([]);
      return;
    } else if (trimmedCmd === 'gates') {
      output = (
        <div className="text-gray-400">
          <p>AVAILABLE OBFUSCATED GATES:</p>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-2">
            {GATES.map(gate => (
              <div key={gate} className="flex items-center cursor-pointer hover:text-gray-300 group" onClick={() => handleNavigate('gate', gate)}>
                <span className="text-gray-500 mr-2 group-hover:text-cyan-400 transition-colors">[{'>'}]</span>
                <span className="text-gray-300 group-hover:text-white transition-colors group-hover:drop-shadow-[0_0_5px_rgba(6,182,212,0.8)]">{gate}</span>
              </div>
            ))}
          </div>
        </div>
      );
    } else if (trimmedCmd.startsWith('join ') || trimmedCmd.startsWith('g/')) {
      const target = trimmedCmd.startsWith('g/') ? trimmedCmd.slice(2) : trimmedCmd.split(' ')[1];
      if (GATES.includes(target)) {
        handleNavigate('gate', target);
        return;
      } else {
        output = <span className="text-red-400">ERR: Gate &apos;{target}&apos; not found or access denied.</span>;
      }
    } else if (trimmedCmd === 'ai' || trimmedCmd === 'copilot' || trimmedCmd === 'openclaw') {
      handleNavigate('ai');
      return;
    } else if (trimmedCmd === 'markets') {
      handleNavigate('market');
      return;
    } else if (trimmedCmd === 'messages') {
      handleNavigate('messages');
      return;
    } else if (trimmedCmd === 'profile') {
      handleNavigate('profile');
      return;
    } else if (trimmedCmd === 'ballot' || trimmedCmd === 'petitions' || trimmedCmd === 'governance') {
      setCurrentView('petitions');
      return;
    } else if (trimmedCmd === 'upgrades' || trimmedCmd === 'upgrade') {
      setCurrentView('upgrades');
      return;
    } else if (trimmedCmd === 'bootstrap') {
      setBootstrapMarketId(null);
      setCurrentView('bootstrap');
      return;
    } else if (trimmedCmd === 'function-keys' || trimmedCmd === 'fkeys') {
      setCurrentView('function-keys');
      return;
    } else if (trimmedCmd.startsWith('resolution ')) {
      const mid = trimmedCmd.slice('resolution '.length).trim();
      if (mid) {
        setResolutionMarketId(mid);
        setCurrentView('resolution');
        return;
      }
      output = <span className="text-red-400">Usage: resolution &lt;market_id&gt;</span>;
    } else if (trimmedCmd.startsWith('shutdown ')) {
      const gid = trimmedCmd.slice('shutdown '.length).trim();
      if (gid) {
        setShutdownGateId(gid);
        setCurrentView('gate-shutdown');
        return;
      }
      output = <span className="text-red-400">Usage: shutdown &lt;gate_id&gt;</span>;
    } else if (trimmedCmd === 'work' || trimmedCmd === 'gigs') {
      setComingSoonModule('GIGS');
      return;
    } else if (trimmedCmd === 'exchange') {
      setComingSoonModule('EXCHANGE');
      return;
    } else if (trimmedCmd === 'mesh') {
      output = (
        <div className="text-gray-400">
          <p>SYNCING PUBLIC MESH LEDGER...</p>
          <p className="text-gray-500 mt-1">Block: #894921 | Hash: 0x9f8a...2b1c</p>
          <p className="text-gray-500">Block: #894920 | Hash: 0x3e1d...9a4f</p>
          <p className="text-gray-500">Block: #894919 | Hash: 0x7c2b...1e8d</p>
          <p className="text-green-400 mt-2">Ledger synchronized.</p>
        </div>
      );
    } else if (trimmedCmd === 'radio') {
      output = (
        <div className="text-gray-400">
          <p className="flex items-center"><Radio size={14} className="mr-2 animate-pulse text-red-400" /> SCANNING FREQUENCIES...</p>
          <p className="text-gray-500 mt-1">144.390 MHz - APRS traffic detected</p>
          <p className="text-gray-500">462.562 MHz - Encrypted burst</p>
          <p className="text-gray-500">8.992 MHz - EAM broadcast intercepted</p>
        </div>
      );
    } else if (trimmedCmd === 'wormhole') {
      output = (
        <div className="text-gray-400">
          <p>OBFUSCATED LANE STATUS:</p>
          <p className="text-gray-500 mt-1">Status: <span className="text-green-400">ONLINE</span></p>
          <p className="text-gray-500">Active Tunnels: 3</p>
          <p className="text-gray-500 mt-2">Use <span className="text-gray-300 font-bold">join [gate]</span> to open an obfuscated gate room.</p>
        </div>
      );
    } else if (trimmedCmd === 'whoami') {
      output = (
        <span className="text-gray-400">
          {`${persona || 'unassigned'}${nodeIdentity?.nodeId ? ` (${nodeIdentity.nodeId})` : ''}${nodeIdentity?.publicKey ? ` / ${nodeIdentity.publicKey}` : ''}`}
        </span>
      );
    } else if (trimmedCmd === 'date') {
      output = <span className="text-gray-400">{new Date().toISOString()}</span>;
    } else if (trimmedCmd === 'exit') {
      onClose();
      return;
    } else {
      output = <span className="text-red-400">Command not recognized: {trimmedCmd}. Type &apos;help&apos; for available commands.</span>;
    }

    setHistory(prev => [...prev, { command: cmd, output }]);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      if (inputMode === 'normal' && input.startsWith('g/') && searchMatch) {
        handleCommand(`join ${searchMatch}`);
      } else {
        handleCommand(input);
      }
      setInput('');
    } else if (e.key === 'Tab') {
      e.preventDefault();
      if (inputMode === 'normal' && input.startsWith('g/') && searchMatch) {
        setInput(`g/${searchMatch}`);
      }
    }
  };

  // Autocomplete logic
  const searchMatch = (inputMode === 'normal' && input.startsWith('g/'))
    ? GATES.find(g => g.startsWith(input.slice(2).toLowerCase()))
    : null;

  if (isBooting) {
    return (
      <div className="h-full bg-[#0a0a0a] text-gray-300 p-4 md:p-8 font-mono flex flex-col justify-end pb-20 overflow-hidden">
        <div className="space-y-1">
          {bootText.map((line, i) => (
            <div key={i} className="text-gray-400">{line}</div>
          ))}
          <div className="animate-pulse w-2 h-4 bg-white mt-2"></div>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="h-full bg-[#0a0a0a] text-gray-300 p-4 md:p-8 font-mono relative flex flex-col overflow-hidden">
      {currentView === 'terminal' && (
        <>
          {/* Top Navigation / Quick Launch */}
          <div className="flex flex-row justify-between items-center gap-2 mb-6 border-b border-gray-800/50 pb-4 shrink-0 overflow-x-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
            <div className="flex flex-nowrap gap-1.5">
              {SECTIONS.map((section) => (
                <button
                  key={section.name}
                  onClick={() => handleCommand(
                    section.name === 'PROFILE' ? 'profile' :
                    section.name === 'F-KEYS' ? 'fkeys' :
                    section.name.toLowerCase()
                  )}
                  className="flex items-center px-2 py-1 bg-cyan-900/10 border border-cyan-900/50 text-cyan-500 hover:bg-cyan-900/30 hover:text-cyan-400 hover:border-cyan-500/50 transition-all text-sm md:text-xs uppercase tracking-widest whitespace-nowrap"
                >
                  {section.icon}
                  {section.name === 'PROFILE' ? 'SOVEREIGN' : section.name}
                </button>
              ))}
            </div>
            <WeatherWidget />
          </div>

          {/* Main Terminal Area */}
          <div className="flex-1 overflow-y-auto pr-4 pb-4">
            <div className="flex flex-col lg:flex-row justify-between items-start gap-6 mb-8">
              <TrendingPosts />

              <div className="flex-1 flex flex-col items-center">
                <pre
                  className="text-white drop-shadow-[0_0_8px_rgba(156,163,175,0.8)] text-sm sm:text-xs md:text-sm leading-tight select-none text-left inline-block"
                  style={{ fontFamily: 'Consolas, "Courier New", monospace' }}
                >
                  {ASCII_HEADER}
                </pre>
                <div className="text-gray-400/80 text-center mt-4">
                  <p>Welcome to Infonet. Type <span className="text-green-400 font-bold">&apos;help&apos;</span> to see available commands.</p>
                  <p>Type <span className="text-green-400 font-bold">&apos;gates&apos;</span> or <span className="text-green-400 font-bold">g/</span> to view available chatrooms.</p>
                </div>
                <NetworkStats />
              </div>

              <HashchainEvents />
            </div>

            <div className="space-y-4">
              <TerminalDashboard onNavigate={(view) => handleNavigate(view)} onComingSoon={(mod) => setComingSoonModule(mod)} />

              {history.map((entry, i) => (
                <div key={i} className="space-y-1">
                  <div className="flex items-center text-white">
                    <span className="text-gray-500 mr-2 inline-block max-w-[45%] truncate" title={shellPrompt}>
                      {shellPrompt}
                    </span>
                    <span>{entry.command}</span>
                  </div>
                  <div className="ml-4 text-gray-300">
                    {entry.output}
                  </div>
                </div>
              ))}
              <div ref={endOfTerminalRef} />
            </div>
          </div>

          {/* Input Area */}
          <div className="shrink-0 pt-4 mt-2 border-t border-gray-800/50 z-10 relative">
            {searchMatch && input.length > 2 && (
              <div className="absolute bottom-full left-0 mb-2 bg-[#0a0a0a] border border-gray-800 p-2 text-xs text-gray-400 z-20">
                Jump to: <span className="text-white font-bold">g/{searchMatch}</span> [Press Tab to autocomplete, Enter to join]
              </div>
            )}
            <div className="flex items-center max-w-full">
              <span
                className={`text-gray-500 mr-2 ${inputMode === 'persona' ? 'whitespace-nowrap' : 'inline-block max-w-[45%] truncate'}`}
                title={inputMode === 'persona' ? 'Enter Persona:' : shellPrompt}
              >
                {inputMode === 'persona' ? 'Enter Persona: ' : shellPrompt}
              </span>
              <div className="relative flex-1 flex items-center">
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  className="w-full bg-transparent border-none outline-none text-white placeholder-gray-800 focus:ring-0 caret-transparent"
                  spellCheck={false}
                  autoComplete="off"
                  autoFocus
                />
                {/* Custom cursor */}
                <span
                  className="absolute animate-pulse w-2 h-4 bg-white pointer-events-none"
                  style={{ left: `${input.length}ch` }}
                ></span>
              </div>
            </div>
          </div>
        </>
      )}

      {currentView === 'gate' && activeGate && (
        <GateView
          gateName={activeGate}
          persona={persona || 'anon'}
          entryMode={activeGateMode}
          onBack={() => handleNavigate('terminal')}
          onNavigateGate={(gate) => handleNavigate('gate', gate)}
          onOpenLiveGate={onOpenLiveGate}
          onOpenShutdownPetition={(gate) => {
            setShutdownGateId(gate);
            setCurrentView('gate-shutdown');
          }}
          availableGates={GATES}
        />
      )}

      {currentView === 'market' && (
        <MarketView onBack={() => handleNavigate('terminal')} />
      )}

      {currentView === 'profile' && (
        <ProfileView
          onBack={() => handleNavigate('terminal')}
          persona={persona || 'unassigned'}
          isCitizen={isCitizen}
          nodeId={nodeIdentity?.nodeId}
          publicKey={nodeIdentity?.publicKey}
        />
      )}

      {currentView === 'messages' && (
        <MessagesView onBack={() => handleNavigate('terminal')} onOpenDeadDrop={onOpenDeadDrop} />
      )}

      {currentView === 'ai' && (
        <AIQueryView onBack={() => handleNavigate('terminal')} />
      )}

      {currentView === 'petitions' && (
        <PetitionsView onBack={() => setCurrentView('terminal')} />
      )}

      {currentView === 'upgrades' && (
        <UpgradeView onBack={() => setCurrentView('terminal')} />
      )}

      {currentView === 'resolution' && resolutionMarketId && (
        <ResolutionView
          marketId={resolutionMarketId}
          onBack={() => setCurrentView('terminal')}
        />
      )}

      {currentView === 'gate-shutdown' && shutdownGateId && (
        <GateShutdownView
          gateId={shutdownGateId}
          onBack={() => setCurrentView('terminal')}
        />
      )}

      {currentView === 'bootstrap' && (
        <BootstrapView
          marketId={bootstrapMarketId ?? undefined}
          onBack={() => setCurrentView('terminal')}
        />
      )}

      {currentView === 'function-keys' && (
        <FunctionKeyView onBack={() => setCurrentView('terminal')} />
      )}

      {/* Coming Soon Popup */}
      {comingSoonModule && COMING_SOON_MODULES[comingSoonModule] && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-[3px]">
          <div className="border border-cyan-500/30 bg-[#060a0f] shadow-[0_0_40px_rgba(6,182,212,0.1),inset_0_0_60px_rgba(6,182,212,0.03)] max-w-md w-full mx-4">
            {/* Header bar */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-cyan-900/40 bg-cyan-950/20">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse shadow-[0_0_6px_rgba(245,158,11,0.6)]" />
                <span className="text-[13px] tracking-[0.3em] text-amber-400/80 uppercase">System Notice</span>
              </div>
              <button
                onClick={() => setComingSoonModule(null)}
                className="text-gray-600 hover:text-white text-xs transition-colors"
              >
                [×]
              </button>
            </div>

            {/* Content */}
            <div className="p-6">
              <div className="text-cyan-400 text-xs tracking-[0.25em] uppercase font-bold mb-4">
                {COMING_SOON_MODULES[comingSoonModule].title}
              </div>

              <div className="border border-gray-800 bg-gray-900/20 p-3 mb-4">
                <p className="text-[11px] text-gray-400 leading-relaxed">
                  {COMING_SOON_MODULES[comingSoonModule].desc}
                </p>
              </div>

              <div className="flex items-center gap-2 mb-4 px-1">
                <span className="w-1 h-1 rounded-full bg-amber-500 animate-pulse" />
                <span className="text-[13px] tracking-[0.2em] text-amber-400/90 uppercase">
                  {COMING_SOON_MODULES[comingSoonModule].status}
                </span>
              </div>

              <div className="border-t border-gray-800 pt-4 flex items-center justify-between">
                <span className="text-[12px] text-gray-600 tracking-[0.2em] uppercase">
                  Infonet Sovereign Shell v0.1.1 — Test-Net
                </span>
                <button
                  onClick={() => setComingSoonModule(null)}
                  className="px-4 py-1.5 border border-cyan-900/50 bg-cyan-950/20 text-cyan-400 text-sm tracking-[0.2em] uppercase hover:bg-cyan-900/30 hover:border-cyan-500/40 transition-all"
                >
                  Acknowledged
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
