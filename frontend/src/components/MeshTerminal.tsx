'use client';

import { MeshTerminalView } from './MeshTerminalView';
import { useMeshTerminalIntelCommands } from './MeshTerminalIntelCommands';
import { useMeshTerminalStatusCommands } from './MeshTerminalStatusCommands';
import { useMeshTerminalCmdStatus } from './MeshTerminalCmdStatus';
import { useMeshTerminalInfonetCommands } from './MeshTerminalInfonetCommands';
import { useMeshTerminalSendFlow } from './MeshTerminalSendFlow';
import { useMeshTerminalMarketsCommand } from './MeshTerminalMarketsCommand';
import { useMeshTerminalInboxPolling } from './useMeshTerminalInboxPolling';
import { useMeshTerminalBoot } from './useMeshTerminalBoot';
import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Terminal, X, GripHorizontal, Minus } from 'lucide-react';
import { motion, AnimatePresence } from '@/lib/motion';
import {
  getNodeIdentity,
  generateNodeKeys,
  getWormholeIdentityDescriptor,
  hasSovereignty,
  declineSovereignty,
  isDeclined,
  getDHPubKey,
  getDHAlgo,
  generateDHKeys,
  deriveSharedKey,
  decryptDM,
  getContacts,
  addContact,
  updateContact,
  blockContact,
  unblockContact,
  getDMNotify,
  setDMNotify,
  signEvent,
  signMessage,
  nextSequence,
  setSequence,
  createIdentityCandidate,
  persistIdentity,
  hydrateWormholeContacts,
  verifyEventSignature,
  getPublicKeyAlgo,
  migrateLegacyNodeIds,
  type NodeIdentity,
} from '@/mesh/meshIdentity';
import { ratchetEncryptDM, ratchetDecryptDM } from '@/mesh/meshDmWorkerClient';
import {
  buildMailboxClaims,
  countDmMailboxes,
  ensureRegisteredDmKey,
  fetchDmPublicKey,
  pollDmMailboxes,
  sendDmMessage,
  sharedMailboxToken,
} from '@/mesh/meshDmClient';
import { PROTOCOL_VERSION, buildSignaturePayload } from '@/mesh/meshProtocol';
import { validateEventPayload } from '@/mesh/meshSchema';
import { verifyMerkleProof } from '@/mesh/meshMerkle';
import { API_BASE } from '@/lib/api';
import { classifyTick, jitteredPollDelay, MAX_CATCHUP_POLLS } from '@/lib/dmPollScheduler';
import { getPrivacyStrictPreference } from '@/lib/privacyBrowserStorage';
import { getDesktopNativeControlAuditReport } from '@/lib/desktopBridge';
import {
  describeNativeControlError,
  extractNativeGateResyncTarget,
} from '@/lib/desktopControlContract';
import {
  getSensitiveBrowserItem,
  setSensitiveBrowserItem,
} from '@/lib/privacyBrowserStorage';
import {
  fetchInfonetNodeStatusSnapshot,
  type InfonetNodeStatusSnapshot,
} from '@/mesh/controlPlaneStatusClient';
import { fetchWormholeStatus, runWormholeDmSelftest } from '@/mesh/wormholeIdentityClient';
import {
  formatLegacyCompatibilitySeenAt,
  summarizeLegacyCompatibility,
} from '@/mesh/wormholeCompatibility';
import {
  formatGateCompatSeenAt,
  getGateCompatTelemetrySnapshot,
  summarizeGateCompatTelemetry,
} from '@/mesh/gateCompatTelemetry';
import {
  describeBrowserGateLocalRuntimeStatus,
  getBrowserGateLocalRuntimeStatus,
} from '@/mesh/meshGateWorkerClient';
import {
  fetchGateCatalogSnapshot,
  fetchGateDetailSnapshot,
  invalidateGateCatalogSnapshot,
  invalidateGateDetailSnapshot,
} from '@/mesh/gateCatalogSnapshot';
import { fetchGateMessageSnapshot } from '@/mesh/gateMessageSnapshot';
import {
  describeGateMessagePreview,
  fetchGateThreadPreviewSnapshot,
  invalidateGateThreadPreviewSnapshot,
} from '@/mesh/gatePreviewSnapshot';
import {
  clearWormholeGatePersona,
  createWormholeGatePersona,
  fetchWormholeGateKeyStatus,
  postWormholeGateMessage,
  prepareWormholeInteractiveLane,
  resyncWormholeGateState,
  rotateWormholeGateKey,
} from '@/mesh/wormholeIdentityClient';
import { fetchWormholeSettings } from '@/mesh/wormholeClient';
import {
  getMeshTerminalWriteLockReason,
  isMeshTerminalWriteCommand,
} from '@/lib/meshTerminalPolicy';
import {
  gateEnvelopeState,
  isEncryptedGateEnvelope,
} from '@/mesh/gateEnvelope';

import type {
  Props,
  TermLine,
  InfonetEventPayload,
  InfonetMessageRecord,
  InfonetEvent,
  InfonetMerkleProof,
  InfonetSyncResponse,
  GateSummary,
  GateDetailRecord,
  GateKeyStatusRecord,
  InboxPreviewRecord,
  GateThreadPreview,
  MeshStatusResponse,
  SearchRecord,
} from './MeshTerminal.shared';
import {
  API,
  INFONET_HEAD_KEY,
  INFONET_HEAD_HISTORY_KEY,
  INFONET_LOCATOR_LIMIT,
  INFONET_PEERS_KEY,
  DEFAULT_MESH_ROOTS,
  sortMeshRoots,
  SETTINGS_FOCUS_KEY,
  WORMHOLE_RETURN_KEY,
  WORMHOLE_READY_EVENT,
  DEFAULT_TERMINAL_SIZE,
  getTerminalSensitiveItem,
  setTerminalSensitiveItem,
  normalizeInfonetMessageRecord,
  formatNodeMode,
  shortNodeHash,
  formatNodeTime,
  summarizeNodePeer,
  describeBootstrapState,
  describeSyncOutcome,
  buildNodeRuntimeLines,
  WELCOME,
  QUICK_LAUNCHES,
  SOVEREIGNTY_DECLARATION,
  HELP_SECTIONS,
  GUIDE_TEXT,
  asSearchRecords,
  pickRecordText,
  pickRecordNumber,
  recordMatchesQuery,
  formatLatLng,
} from './MeshTerminal.shared';

export default function MeshTerminal({ isOpen, launchToken = 0, onClose, onDmCount, onSettingsClick }: Props) {
  useEffect(() => {
    void migrateLegacyNodeIds().catch((err) => {
      console.warn('[mesh] legacy node-id migration failed in MeshTerminal', err);
    });
  }, []);

  const [lines, setLines] = useState<TermLine[]>([...WELCOME]);
  const [input, setInput] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [histIdx, setHistIdx] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [hasBooted, setHasBooted] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [surfacePanel, setSurfacePanel] = useState<
    'home' | 'help' | 'apps' | 'mesh' | 'gates' | 'markets' | 'inbox' | 'dossier'
  >('home');
  const [gateCatalog, setGateCatalog] = useState<GateSummary[]>([]);
  const [gateCatalogLoading, setGateCatalogLoading] = useState(false);
  const [expandedGateId, setExpandedGateId] = useState<string | null>(null);
  const [expandedGateDetail, setExpandedGateDetail] = useState<GateDetailRecord | null>(null);
  const [expandedGateKey, setExpandedGateKey] = useState<GateKeyStatusRecord | null>(null);
  const [expandedGateMessages, setExpandedGateMessages] = useState<GateThreadPreview[]>([]);
  const [expandedGateLoading, setExpandedGateLoading] = useState<string | null>(null);
  const [activeGateComposeId, setActiveGateComposeId] = useState<string | null>(null);
  const [gateReplyTarget, setGateReplyTarget] = useState<string | null>(null);
  const [gateAccessPromptOpen, setGateAccessPromptOpen] = useState(false);
  const [gateAccessGranted, setGateAccessGranted] = useState(false);
  const [pendingGateCommand, setPendingGateCommand] = useState<string | null>(null);
  const [privateLanePromptOpen, setPrivateLanePromptOpen] = useState(false);
  const [privateLanePromptMode, setPrivateLanePromptMode] = useState<'enter' | 'activate'>(
    'activate',
  );
  const [privateLanePromptBusy, setPrivateLanePromptBusy] = useState(false);
  const [privateLanePromptStatus, setPrivateLanePromptStatus] = useState<{
    type: 'ok' | 'err' | 'dim';
    text: string;
  } | null>(null);
  const [surfaceMarkets, setSurfaceMarkets] = useState<SearchRecord[]>([]);
  const [surfaceMarketsLoading, setSurfaceMarketsLoading] = useState(false);
  const [expandedMarketIndex, setExpandedMarketIndex] = useState<number | null>(null);
  const [surfaceInbox, setSurfaceInbox] = useState<InboxPreviewRecord[]>([]);
  const [surfaceInboxLoading, setSurfaceInboxLoading] = useState(false);
  const [surfaceMeshCounts, setSurfaceMeshCounts] = useState<Record<string, number>>({});
  const [surfaceMeshLoading, setSurfaceMeshLoading] = useState(false);
  // Interactive send flow
  const [sendStep, setSendStep] = useState<null | 'dest' | 'msg'>(null);
  const [sendDest, setSendDest] = useState('');
  // Interactive DM flow
  const [dmStep, setDmStep] = useState<null | 'dest' | 'msg'>(null);
  const [dmDest, setDmDest] = useState('');
  // Sovereignty / identity
  const [sovereigntyPending, setSovereigntyPending] = useState(false);
  const [nodeIdentity, setNodeIdentity] = useState<NodeIdentity | null>(null);
  const [voteDirections, setVoteDirections] = useState<Record<string, 1 | -1>>({});
  const [, setContactsRevision] = useState(0);
  const [wormholeSecureRequired, setWormholeSecureRequired] = useState(false);
  const [wormholeReadyState, setWormholeReadyState] = useState(false);
  const [anonymousModeEnabled, setAnonymousModeEnabled] = useState(false);
  const [anonymousModeReady, setAnonymousModeReady] = useState(false);
  const [infonetNodeStatus, setInfonetNodeStatus] = useState<InfonetNodeStatusSnapshot | null>(null);
  const [infonetNodeStatusError, setInfonetNodeStatusError] = useState('');
  // Meshtastic region
  const [meshRegion, setMeshRegion] = useState('US');
  const [meshRoots, setMeshRoots] = useState<string[]>([...DEFAULT_MESH_ROOTS]);

  // Dragging state
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [centered, setCentered] = useState(true);
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(
    null,
  );

  // Resize state
  const [size, setSize] = useState(DEFAULT_TERMINAL_SIZE);
  const resizeRef = useRef<{
    startX: number;
    startY: number;
    origW: number;
    origH: number;
    origX: number;
    origY: number;
    edge: string;
  } | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const windowRef = useRef<HTMLDivElement>(null);
  const resetScrollToTopRef = useRef(false);
  const runQuickCommandRef = useRef<(command: string) => void>(() => {});

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const saved = window.localStorage.getItem('sb_terminal_surface');
    if (
      saved === 'help' ||
      saved === 'apps' ||
      saved === 'mesh' ||
      saved === 'markets' ||
      saved === 'inbox' ||
      saved === 'dossier'
    ) {
      setSurfacePanel(saved);
    } else if (saved === 'gates') {
      setSurfacePanel('home');
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem('sb_terminal_surface', surfacePanel);
  }, [surfacePanel]);

  useEffect(() => {
    if (scrollRef.current) {
      if (resetScrollToTopRef.current) {
        scrollRef.current.scrollTop = 0;
        resetScrollToTopRef.current = false;
      } else {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    }
  }, [lines]);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
    if (isOpen) {
      setMinimized(false);
      setCentered(true);
      setPos({ x: 0, y: 0 });
      setSize(DEFAULT_TERMINAL_SIZE);
      resetScrollToTopRef.current = true;
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || launchToken <= 0) return;
    setMinimized(false);
    setCentered(true);
    setPos({ x: 0, y: 0 });
    resetScrollToTopRef.current = true;
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [isOpen, launchToken]);

  const refreshPrivateLaneRuntime = useCallback(async () => {
    try {
      const [settings, status] = await Promise.all([
        fetchWormholeSettings(true),
        fetchWormholeStatus().catch(() => null),
      ]);
      const secureRequired = Boolean(settings?.enabled);
      const ready = Boolean(status?.ready);
      const anonymousEnabled = Boolean(settings?.anonymous_mode);
      const anonymousReady = Boolean(status?.anonymous_mode_ready);
      setWormholeSecureRequired(secureRequired);
      setAnonymousModeEnabled(anonymousEnabled);
      setWormholeReadyState(ready);
      setAnonymousModeReady(anonymousReady);
      return {
        secureRequired,
        ready,
        anonymousEnabled,
        anonymousReady,
        hasDescriptor: Boolean(getWormholeIdentityDescriptor()?.nodeId),
      };
    } catch {
      setWormholeSecureRequired(false);
      setAnonymousModeEnabled(false);
      setWormholeReadyState(false);
      setAnonymousModeReady(false);
      return {
        secureRequired: false,
        ready: false,
        anonymousEnabled: false,
        anonymousReady: false,
        hasDescriptor: Boolean(getWormholeIdentityDescriptor()?.nodeId),
      };
    }
  }, []);

  const openPrivateLanePrompt = useCallback(async () => {
    const runtime = await refreshPrivateLaneRuntime();
    setPrivateLanePromptMode(
      runtime.ready || runtime.secureRequired || runtime.hasDescriptor ? 'enter' : 'activate',
    );
    setPrivateLanePromptStatus(null);
    setPrivateLanePromptOpen(true);
  }, [refreshPrivateLaneRuntime]);

  useEffect(() => {
    if (!isOpen || launchToken <= 0) return;
    let cancelled = false;

    const preparePrompt = async () => {
      const runtime = await refreshPrivateLaneRuntime();
      if (cancelled) return;
      setPrivateLanePromptMode(
        runtime.ready || runtime.secureRequired || runtime.hasDescriptor ? 'enter' : 'activate',
      );
      setPrivateLanePromptStatus(null);
      setPrivateLanePromptOpen(true);
    };

    void preparePrompt();
    return () => {
      cancelled = true;
    };
  }, [isOpen, launchToken, refreshPrivateLaneRuntime]);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    const refreshSecurityState = async () => {
      const runtime = await refreshPrivateLaneRuntime();
      if (cancelled) return;
      setWormholeSecureRequired(runtime.secureRequired);
      setAnonymousModeEnabled(runtime.anonymousEnabled);
      setWormholeReadyState(runtime.ready);
      setAnonymousModeReady(runtime.anonymousReady);
    };

    refreshSecurityState();
    const interval = setInterval(refreshSecurityState, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [isOpen, refreshPrivateLaneRuntime]);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    const refreshNodeRuntime = async () => {
      try {
        const snapshot = await fetchInfonetNodeStatusSnapshot(true);
        if (cancelled) return;
        setInfonetNodeStatus(snapshot);
        setInfonetNodeStatusError('');
      } catch (error) {
        if (cancelled) return;
        const message =
          typeof error === 'object' && error !== null && 'message' in error
            ? String((error as { message?: string }).message || '')
            : '';
        setInfonetNodeStatusError(message || 'node runtime unavailable');
      }
    };

    void refreshNodeRuntime();
    const interval = window.setInterval(() => {
      void refreshNodeRuntime();
    }, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || surfacePanel !== 'gates') return;
    let cancelled = false;

    const loadGateCatalog = async () => {
      setGateCatalogLoading(true);
      try {
        if (cancelled) return;
        const gates = await fetchGateCatalogSnapshot();
        if (cancelled) return;
        setGateCatalog(gates);
      } catch {
        if (!cancelled) setGateCatalog([]);
      } finally {
        if (!cancelled) setGateCatalogLoading(false);
      }
    };

    void loadGateCatalog();
    return () => {
      cancelled = true;
    };
  }, [isOpen, surfacePanel]);

  useEffect(() => {
    if (!isOpen || surfacePanel !== 'markets') return;
    let cancelled = false;

    const loadMarkets = async () => {
      setSurfaceMarketsLoading(true);
      try {
        const res = await fetch(`${API}/api/mesh/oracle/markets`);
        const data = await res.json();
        if (cancelled) return;
        const markets = asSearchRecords(
          Array.isArray(data.markets)
            ? data.markets
            : Object.values((data.categories || {}) as Record<string, unknown>).flatMap((items) =>
                Array.isArray(items) ? items : [],
              ),
        );
        setSurfaceMarkets(markets.slice(0, 9));
      } catch {
        if (!cancelled) setSurfaceMarkets([]);
      } finally {
        if (!cancelled) setSurfaceMarketsLoading(false);
      }
    };

    loadMarkets();
    return () => {
      cancelled = true;
    };
  }, [isOpen, surfacePanel, meshRegion]);

  useEffect(() => {
    if (!isOpen || surfacePanel !== 'mesh') return;
    let cancelled = false;

    const loadMeshSurface = async () => {
      setSurfaceMeshLoading(true);
      try {
        const res = await fetch(`${API}/api/mesh/channels`);
        const data = await res.json();
        if (cancelled) return;
        const counts: Record<string, number> = {};
        const knownRoots = Array.isArray(data.known_roots) ? data.known_roots : [];
        Object.entries((data.roots || {}) as Record<string, { nodes?: number }>).forEach(
          ([root, entry]) => {
            counts[root] = Number(entry?.nodes || 0);
          },
        );
        const roots = sortMeshRoots(
          [...DEFAULT_MESH_ROOTS, ...knownRoots, ...Object.keys(counts), meshRegion],
          counts,
          meshRegion,
        );
        setMeshRoots(roots);
        setSurfaceMeshCounts(counts);
      } catch {
        if (!cancelled) setSurfaceMeshCounts({});
      } finally {
        if (!cancelled) setSurfaceMeshLoading(false);
      }
    };

    loadMeshSurface();
    return () => {
      cancelled = true;
    };
  }, [isOpen, surfacePanel, meshRegion]);

  useMeshTerminalInboxPolling({
    isOpen, surfacePanel, nodeIdentity, onDmCount,
    setSurfaceInbox, setSurfaceInboxLoading,
  });
        wormholeRequired: wormholeSecureRequired,
        wormholeReady: wormholeReadyState,
        anonymousMode: anonymousModeEnabled,
        anonymousModeReady: anonymousModeReady,
      }),
    [wormholeSecureRequired, wormholeReadyState, anonymousModeEnabled, anonymousModeReady],
  );
  const publicAgentReady = Boolean(nodeIdentity) && hasSovereignty();
  const privateLaneLabel = wormholeSecureRequired
    ? wormholeReadyState
      ? 'EXPERIMENTAL / OBFUSCATED'
      : 'LOCKED'
    : 'OFF / PUBLIC ONLY';
  const privateLaneDetail = wormholeSecureRequired
    ? wormholeReadyState
      ? 'Wormhole is live for encrypted gates and the obfuscated inbox.'
      : 'Wormhole is required for gates and obfuscated inbox, but it is not ready yet.'
    : 'Wormhole is off. Public mesh still works; obfuscated gates and inbox stay locked.';
  const nodeModeLabel = formatNodeMode(infonetNodeStatus?.node_mode);
  const nodeBootstrapLabel = describeBootstrapState(infonetNodeStatus);
  const nodeSyncLabel = describeSyncOutcome(infonetNodeStatus);

  // Re-focus input when command finishes (busy → false)
  useEffect(() => {
    if (!busy && isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [busy, isOpen]);

  // Auto-run status on first open
  useEffect(() => {
  useMeshTerminalBoot({
    isOpen, hasBooted, setHasBooted, setLines, setInfonetNodeStatus, setInfonetNodeStatusError, setSovereigntyPending,
  });

  // Load existing identity on mount
  useEffect(() => {
    const existing = getNodeIdentity();
    if (existing) setNodeIdentity(existing);
    void hydrateWormholeContacts()
      .then(() => {
        setContactsRevision((value) => value + 1);
      })
      .catch((err) => {
        console.warn('[mesh] contact hydration failed in MeshTerminal', err);
      });
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const refreshIdentity = () => {
      const next = getNodeIdentity();
      setNodeIdentity((prev) => {
        const prevId = prev?.nodeId || '';
        const nextId = next?.nodeId || '';
        const prevKey = prev?.publicKey || '';
        const nextKey = next?.publicKey || '';
        return prevId === nextId && prevKey === nextKey ? prev : next;
      });
      void hydrateWormholeContacts(true)
        .then(() => {
          setContactsRevision((value) => value + 1);
        })
        .catch((err) => {
          console.warn('[mesh] contact refresh failed in MeshTerminal', err);
        });
    };
    window.addEventListener('sb:identity-state-changed', refreshIdentity);
    window.addEventListener('storage', refreshIdentity);
    window.addEventListener('focus', refreshIdentity);
    return () => {
      window.removeEventListener('sb:identity-state-changed', refreshIdentity);
      window.removeEventListener('storage', refreshIdentity);
      window.removeEventListener('focus', refreshIdentity);
    };
  }, []);

  // DM unread count polling (jittered cadence around 15s when connected)
  useEffect(() => {
    if (!isOpen || !nodeIdentity || !hasSovereignty() || !getDMNotify() || surfacePanel === 'inbox') return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      if (cancelled) return;
      try {
        const claims = await buildMailboxClaims(getContacts());
        const data = await countDmMailboxes(API, nodeIdentity, claims);
        if (!cancelled && onDmCount) onDmCount(data.count || 0);
      } catch {
        /* ignore */
      }
      if (!cancelled) {
        timer = setTimeout(() => void tick(), jitteredPollDelay(15_000));
      }
    };
    void tick(); // immediate first poll
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [isOpen, nodeIdentity, onDmCount, surfacePanel]);

  // Escape to close
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  // ─── Drag handling ─────────────────────────────────────────

  const onDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      if (centered && windowRef.current) {
        // Convert from centered to absolute positioning
        const rect = windowRef.current.getBoundingClientRect();
        setPos({ x: rect.left, y: rect.top });
        setCentered(false);
      }
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        origX: centered ? windowRef.current?.getBoundingClientRect().left || 0 : pos.x,
        origY: centered ? windowRef.current?.getBoundingClientRect().top || 0 : pos.y,
      };

      const onMove = (ev: MouseEvent) => {
        if (!dragRef.current) return;
        setPos({
          x: dragRef.current.origX + (ev.clientX - dragRef.current.startX),
          y: dragRef.current.origY + (ev.clientY - dragRef.current.startY),
        });
        setCentered(false);
      };
      const onUp = () => {
        dragRef.current = null;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    },
    [centered, pos],
  );

  // ─── Resize handling ────────────────────────────────────────

  const onResizeStart = useCallback(
    (e: React.MouseEvent, edge: string) => {
      e.preventDefault();
      e.stopPropagation();
      // Convert from centered to absolute before resizing
      let curX = pos.x,
        curY = pos.y;
      if (centered && windowRef.current) {
        const rect = windowRef.current.getBoundingClientRect();
        curX = rect.left;
        curY = rect.top;
        setPos({ x: curX, y: curY });
        setCentered(false);
      }
      const rect = windowRef.current?.getBoundingClientRect();
      resizeRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        origW: rect?.width || size.w,
        origH: rect?.height || size.h,
        origX: curX,
        origY: curY,
        edge,
      };
      const onMove = (ev: MouseEvent) => {
        if (!resizeRef.current) return;
        const dx = ev.clientX - resizeRef.current.startX;
        const dy = ev.clientY - resizeRef.current.startY;
        const { edge: ed, origW, origH, origX, origY } = resizeRef.current;
        let newW = origW,
          newH = origH,
          newX = origX,
          newY = origY;
        // East: drag right edge outward
        if (ed.includes('e')) newW = Math.max(360, origW + dx);
        // West: drag left edge — shrinks width, moves position right
        if (ed.includes('w')) {
          newW = Math.max(360, origW - dx);
          newX = origX + (origW - newW);
        }
        // South: drag bottom edge down
        if (ed.includes('s')) newH = Math.max(250, origH + dy);
        // North: drag top edge — shrinks height, moves position down
        if (ed.includes('n')) {
          newH = Math.max(250, origH - dy);
          newY = origY + (origH - newH);
        }
        setSize({ w: newW, h: newH });
        setPos({ x: newX, y: newY });
        setCentered(false);
      };
      const onUp = () => {
        resizeRef.current = null;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    },
    [centered, size, pos],
  );

  // ─── Command helpers ───────────────────────────────────────

  const addLines = useCallback(
    (newLines: TermLine[]) => setLines((prev) => [...prev, ...newLines]),
    [],
  );
  const addOutput = useCallback((text: string) => addLines([{ text, type: 'output' }]), [addLines]);
  const addError = useCallback(
    (text: string) => addLines([{ text: `  ${text}`, type: 'error' }]),
    [addLines],
  );
  const addSystem = useCallback((text: string) => addLines([{ text, type: 'system' }]), [addLines]);
  const addGateResyncAction = useCallback(
    (err: unknown, gateIdHint?: string): boolean => {
      const gateId = String(extractNativeGateResyncTarget(err) || gateIdHint || '')
        .trim()
        .toLowerCase();
      if (!gateId) return false;
      addLines([
        {
          text: '  Gate state changed on another native path. Resync local gate state before retrying.',
          type: 'error',
          actionCommand: `gate resync ${gateId}`,
          actionLabel: 'RESYNC',
        },
      ]);
      return true;
    },
    [addLines],
  );

  const getInfonetHeadHistory = useCallback(() => {
    if (typeof window === 'undefined') return [];
    try {
      const raw = getTerminalSensitiveItem(INFONET_HEAD_HISTORY_KEY) || '[]';
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter((v) => typeof v === 'string') : [];
    } catch {
      return [];
    }
  }, []);
  const getInfonetHead = useCallback(
    () => getTerminalSensitiveItem(INFONET_HEAD_KEY),
    [],
  );
  const setInfonetHead = useCallback(
    (head: string) => {
      if (typeof window === 'undefined') return;
      setTerminalSensitiveItem(INFONET_HEAD_KEY, head);
      try {
        const history = getInfonetHeadHistory();
        const next = [head, ...history.filter((h) => h && h !== head)].slice(
        0,
        INFONET_LOCATOR_LIMIT,
      );
      setTerminalSensitiveItem(INFONET_HEAD_HISTORY_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
    },
    [getInfonetHeadHistory],
  );
  const getInfonetLocator = useCallback(() => {
    const head = getInfonetHead();
    const history = getInfonetHeadHistory();
    const merged = [head, ...history].filter(Boolean);
    const unique = Array.from(new Set(merged));
    const genesis = '0'.repeat(64);
    if (!unique.includes(genesis)) unique.push(genesis);
    return unique.slice(0, INFONET_LOCATOR_LIMIT);
  }, [getInfonetHead, getInfonetHeadHistory]);

  const getInfonetPeers = useCallback(() => {
    const envPeers = (process.env.NEXT_PUBLIC_INFONET_PEERS || '')
      .split(',')
      .map((p) => p.trim())
      .filter(Boolean);
    let stored: string[] = [];
    if (typeof window !== 'undefined') {
      try {
        const raw = getTerminalSensitiveItem(INFONET_PEERS_KEY) || '[]';
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) stored = parsed.filter((p) => typeof p === 'string');
      } catch {
        stored = [];
      }
    }
    const merged = [API, ...envPeers, ...stored].filter(Boolean);
    const normalized = merged.map((p) => p.replace(/\/+$/, ''));
    return Array.from(new Set(normalized));
  }, []);

  const setInfonetPeers = useCallback((peers: string[]) => {
    if (typeof window === 'undefined') return;
    const cleaned = peers
      .map((p) => p.trim().replace(/\/+$/, ''))
      .filter(Boolean);
    setTerminalSensitiveItem(INFONET_PEERS_KEY, JSON.stringify(cleaned));
  }, []);

  const { cmdStatus } = useMeshTerminalCmdStatus({
    addOutput, addError, addSystem, addLines,
    nodeIdentity, privateLaneDetail, privateLaneLabel,
    fetchInfonetNodeStatusSnapshot, setInfonetNodeStatus, setInfonetNodeStatusError, buildNodeRuntimeLines,
  });

  const { cmdApps, cmdNews, cmdJets, cmdPlaces, cmdDossier, cmdShodan } = useMeshTerminalIntelCommands({
    addError, addLines, addOutput, addSystem,
  });

  const { cmdMerkle, cmdSync, cmdRevoke, cmdRotate } = useMeshTerminalInfonetCommands({
    addError, addLines, addOutput, addSystem, nodeIdentity, setNodeIdentity,
    getInfonetLocator, getInfonetPeers, getPrivacyStrictPreference, setInfonetHead,
  } as any);

  const { cmdNode, cmdSignals, cmdLog, cmdNearest } = useMeshTerminalStatusCommands({
    addError, addLines, addOutput, addSystem, setInfonetNodeStatus, setInfonetNodeStatusError, fetchInfonetNodeStatusSnapshot, shortNodeHash, buildNodeRuntimeLines,
  });

  const voteScopeKey = useCallback((targetId: string, gateId: string = '') => {
    return `${(gateId || 'public').trim().toLowerCase()}::${String(targetId || '').trim()}`;
  }, []);

  const postGateMessage = useCallback(
    async (gateId: string, plaintext: string) => {
      const sendAttempt = async () => {
        let data;
        try {
          data = await postWormholeGateMessage(gateId, plaintext);
        } catch (error) {
          const detail = error instanceof Error ? error.message : 'Failed to post to gate';
          throw new Error(
            detail === 'gate_compat_fallback_consent_required' || detail.startsWith('gate_local_runtime_required:')
              ? 'Browser-local gate runtime is unavailable. Open the room view to resync local gate state or use native desktop.'
              : detail,
          );
        }
        if (!data?.ok) {
          const detail = String(data?.detail || 'Failed to post to gate');
          throw new Error(
            detail === 'gate_compat_fallback_consent_required' || detail.startsWith('gate_local_runtime_required:')
              ? 'Browser-local gate runtime is unavailable. Open the room view to resync local gate state or use native desktop.'
              : detail,
          );
        }
        return data;
      };

      return await sendAttempt();
    },
    [],
  );

  const requestGateAccess = useCallback((command: string | null = 'gates') => {
    setPendingGateCommand(command);
    setGateAccessPromptOpen(true);
  }, []);

  const activatePrivateLane = useCallback(
    async (nextCommand: string | null = 'gates') => {
      setPrivateLanePromptBusy(true);
      setPrivateLanePromptStatus({
        type: 'dim',
        text: 'Turning on Wormhole and preparing the obfuscated lane...',
      });
      try {
        const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
        let runtime = await refreshPrivateLaneRuntime();
        setWormholeSecureRequired(Boolean(prepared.settingsEnabled || runtime.secureRequired));
        setWormholeReadyState(Boolean(runtime.ready || prepared.ready));

        setPrivateLanePromptStatus({
          type: 'dim',
          text: 'Provisioning obfuscated identity and opening the Infonet Commons...',
        });
        const identity = prepared.identity;
        if (!identity) {
          throw new Error('Wormhole is still warming up in the background.');
        }
        setGateAccessGranted(true);
        setPrivateLanePromptStatus({
          type: 'ok',
          text: `Wormhole ready as ${identity.node_id}.`,
        });
        setPrivateLanePromptOpen(false);
        setGateAccessPromptOpen(false);
        setPendingGateCommand(null);
        addSystem(`  Wormhole obfuscated lane ready as ${identity.node_id}.`);
        addLines([
          {
            text: '  Participant-node sync stays on the backend lane. Wormhole now unlocks gates and the obfuscated commons.',
            type: 'dim',
          },
        ]);

        const commandToRun = nextCommand && nextCommand.trim() ? nextCommand : 'gates';
        const targetPanel = commandToRun === 'inbox' ? 'inbox' : 'gates';
        setSurfacePanel(targetPanel);
        window.setTimeout(() => runQuickCommandRef.current(commandToRun), 40);
      } catch (err) {
        const detail = describeNativeControlError(err) || (err instanceof Error ? err.message : '');
        setPrivateLanePromptStatus({
          type: 'err',
          text: detail || 'Failed to enter Wormhole.',
        });
        addError(detail || 'Failed to enter Wormhole.');
      } finally {
        setPrivateLanePromptBusy(false);
      }
    },
    [addError, addLines, addSystem, refreshPrivateLaneRuntime],
  );

  const routeToWormholeSetup = useCallback(() => {
    setGateAccessPromptOpen(false);
    setPendingGateCommand(null);
    setPrivateLanePromptMode('activate');
    setPrivateLanePromptOpen(true);
    void activatePrivateLane('gates');
  }, [activatePrivateLane]);

  const openGateCard = useCallback(
    async (gateId: string, options: { force?: boolean } = {}) => {
      if (!gateId) return;
      if (expandedGateId === gateId && expandedGateDetail) {
        setExpandedGateId(null);
        setExpandedGateDetail(null);
        setExpandedGateKey(null);
        setExpandedGateMessages([]);
        if (activeGateComposeId === gateId) {
          setActiveGateComposeId(null);
          setGateReplyTarget(null);
        }
        return;
      }
      setExpandedGateLoading(gateId);
      try {
        const [gateData, keyData, previews] = await Promise.all([
          fetchGateDetailSnapshot(gateId, options),
          fetchWormholeGateKeyStatus(gateId).catch(() => null),
          fetchGateThreadPreviewSnapshot(gateId, options).catch(() => []),
        ]);
        setExpandedGateId(gateId);
        setExpandedGateDetail(gateData);
        setExpandedGateKey(keyData && keyData.ok ? (keyData as GateKeyStatusRecord) : null);
        setActiveGateComposeId(gateId);
        setExpandedGateMessages(previews as GateThreadPreview[]);
      } catch {
        setExpandedGateId(gateId);
        setExpandedGateDetail(null);
        setExpandedGateKey(null);
        setExpandedGateMessages([]);
      } finally {
        setExpandedGateLoading(null);
      }
    },
    [activeGateComposeId, expandedGateDetail, expandedGateId],
  );

  const handleGatesCommand = async (d: any) => {
            if (!gateAccessGranted) {
              requestGateAccess('gates');
              return;
            }
            try {
              const gates = await fetchGateCatalogSnapshot();
              addSystem('');
              if (!gates.length) {
                addSystem('  No launch gates are available yet.');
              } else {
                addSystem(`  PRIVATE LAUNCH GATES (${gates.length})`);
                addLines([
                  {
                    text: '  Click a gate row to enter it, or use /gate <gate-id> if you want command mode.',
                    type: 'dim',
                  },
                ]);
                for (const g of gates) {
                  const rules = g.rules || {};
                  const reqStr = rules.min_overall_rep
                    ? `req: ${rules.min_overall_rep} rep`
                    : 'open';
                  addLines([
                    {
                      text: `    ${g.gate_id.padEnd(20)} ${(g.display_name || '').padEnd(20)} ${reqStr}  (${g.message_count} msgs)`,
                      type: 'output',
                      actionCommand: `gate ${g.gate_id}`,
                      actionLabel: 'ENTER',
                    },
                  ]);
                  if (g.description) {
                    addLines([{ text: `      ${g.description}`, type: 'dim' }]);
                  }
                }
                addLines([
                  {
                    text: '  Fixed launch catalog only. Gate creation is disabled in this testnet build.',
                    type: 'dim',
                  },
                ]);
              }
              addSystem('');
            } catch {
              addError('Failed to fetch gates');
            }
            return;
  };

  const handleGateCommand = async (args: string[], d: any) => {
            // Only the subcommands that mutate wormhole state need gate
            // access upfront. Plain `gate <id>` (view) and `gate audit` are
            // read-only paths that don't touch the wormhole supervisor or
            // require an admin session — let them run for any user.
            const needsWormholePrep = ['create', 'mask', 'anon', 'rekey', 'resync'].includes(
              String(args[0] || ''),
            );
            if (needsWormholePrep && !gateAccessGranted) {
              requestGateAccess(`gate ${args.join(' ')}`.trim());
              return;
            }
            // gate <id> | gate mask <id> | gate anon <id> | gate rekey <id> [reason] | gate audit [limit]
            if (args[0] === 'create') {
              addError('Gate creation is disabled. This testnet uses a fixed private launch catalog.');
            } else if (args[0] === 'audit') {
              const requested = Number.parseInt(String(args[1] || '5'), 10);
              const limit = Number.isFinite(requested) && requested > 0 ? Math.min(requested, 10) : 5;
              const report = getDesktopNativeControlAuditReport(limit);
              addSystem('');
              if (!report || report.totalEvents === 0) {
                addSystem('  NATIVE CONTROL AUDIT');
                addOutput('    No native session-profile audit events have been recorded yet.');
                addSystem('');
                return;
              }
              addSystem(
                `  NATIVE CONTROL AUDIT (${report.totalRecorded || report.totalEvents} recorded${report.totalRecorded > report.totalEvents ? `, ${report.totalEvents} shown` : ''})`,
              );
              addOutput(
                `    Outcomes:    allowed ${report.byOutcome.allowed || 0} | profile_warn ${report.byOutcome.profile_warn || 0} | denied ${(report.byOutcome.profile_denied || 0) + (report.byOutcome.capability_denied || 0) + (report.byOutcome.shim_refused || 0)}`,
              );
              if (report.lastProfileMismatch) {
                addOutput(
                  `    Last drift:  ${report.lastProfileMismatch.command}${report.lastProfileMismatch.targetRef ? ` [${report.lastProfileMismatch.targetRef}]` : ''} -> ${report.lastProfileMismatch.outcome} (${report.lastProfileMismatch.sessionProfile || 'unscoped'})`,
                );
              }
              report.recent.forEach((entry, index) => {
                addOutput(
                  `    ${String(index + 1).padStart(2, '0')}. ${entry.command}${entry.targetRef ? ` [${entry.targetRef}]` : ''}  ${entry.outcome}  profile=${entry.sessionProfile || 'unscoped'}  cap=${entry.expectedCapability}`,
                );
              });
              addSystem('');
            } else if (args[0] === 'mask') {
              const gateId = args[1];
              if (!gateId) {
                addError('Usage: gate mask <id>');
                return;
              }
              if (!wormholeSecureRequired || !wormholeReadyState) {
                addSystem('  Preparing Wormhole in the background for gate unlock...');
                try {
                  const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
                  setWormholeSecureRequired(Boolean(prepared.settingsEnabled));
                  setWormholeReadyState(Boolean(prepared.ready));
                } catch (err) {
                  addError(
                    describeNativeControlError(err) ||
                      (err instanceof Error ? err.message : 'Failed to prepare Wormhole.'),
                  );
                  return;
                }
              }
              if (anonymousModeEnabled && !anonymousModeReady) {
                addError('Hidden transport required for anonymous gate personas.');
                return;
              }
              try {
                const created = await createWormholeGatePersona(gateId, `persona-${Date.now().toString().slice(-4)}`);
                if (!created.ok) {
                  addError(created.detail || 'failed to create gate face');
                  return;
                }
                addSystem('');
                addSystem(`  GATE FACE READY: ${gateId}`);
                addOutput(`    Face:       ${created.identity?.label || created.identity?.persona_id || created.identity?.node_id || 'unknown'}`);
                addOutput('    Status:     encrypted gate content unlocked for this face');
                addSystem('');
              } catch (err) {
                addError(
                  describeNativeControlError(err) ||
                    (err instanceof Error && err.message) ||
                    'Failed to create gate face',
                );
              }
            } else if (args[0] === 'anon') {
              const gateId = args[1];
              if (!gateId) {
                addError('Usage: gate anon <id>');
                return;
              }
              try {
                const cleared = await clearWormholeGatePersona(gateId);
                if (!cleared.ok) {
                  addError(cleared.detail || 'failed to return to anonymous mode');
                  return;
                }
                addSystem('');
                addSystem(`  ANONYMOUS SESSION RESTORED: ${gateId}`);
                addOutput('    Status:     rotating anonymous gate key active for this room');
                addSystem('');
              } catch (err) {
                addError(describeNativeControlError(err) || 'Failed to switch to anonymous mode');
              }
            } else if (args[0] === 'rekey') {
              const gateId = args[1];
              const reason = args.slice(2).join('_') || 'operator_reset';
              if (!gateId) {
                addError('Usage: gate rekey <id> [reason]');
                return;
              }
              try {
                const rotated = await rotateWormholeGateKey(gateId, reason);
                if (!rotated.ok) {
                  addError(rotated.detail || 'failed to rotate gate key');
                  return;
                }
                addSystem('');
                addSystem(`  GATE KEY ROTATED: ${rotated.gate_id}`);
                addOutput(`    Epoch:      ${rotated.current_epoch}`);
                addOutput(`    Key:        ${(rotated.key_commitment || '').slice(0, 16)}...`);
                addOutput(`    Reason:     ${rotated.last_rotation_reason || reason}`);
                addSystem('');
              } catch (err) {
                addError(describeNativeControlError(err) || 'Failed to rotate gate key');
              }
            } else if (args[0] === 'resync') {
              const gateId = String(args[1] || '').trim().toLowerCase();
              if (!gateId) {
                addError('Usage: gate resync <id>');
                return;
              }
              try {
                const resynced = await resyncWormholeGateState(gateId);
                if (!resynced.ok) {
                  addError(resynced.detail || 'failed to resync gate state');
                  return;
                }
                addSystem('');
                addSystem(`  GATE STATE RESYNCED: ${resynced.gate_id || gateId}`);
                addOutput(`    Epoch:      ${resynced.epoch || 0}`);
                if (resynced.active_identity_scope) {
                  addOutput(`    Scope:      ${resynced.active_identity_scope}`);
                }
                if (resynced.active_persona_id) {
                  addOutput(`    Persona:    ${resynced.active_persona_id}`);
                }
                if (resynced.active_node_id) {
                  addOutput(`    Node:       ${String(resynced.active_node_id).slice(0, 16)}...`);
                }
                addSystem('');
              } catch (err) {
                if (!addGateResyncAction(err, gateId)) {
                  addError(describeNativeControlError(err) || 'Failed to resync gate state');
                }
              }
            } else if (args[0]) {
              // View gate details
              try {
                const gateId = String(args[0] || '').trim().toLowerCase();
                const [gateRes, keyStatus] = await Promise.all([
                  fetchGateDetailSnapshot(gateId),
                  fetchWormholeGateKeyStatus(gateId).catch(() => null),
                ]);
                const data = gateRes;
                if (data.ok === false) {
                  addError(data.detail || 'Failed to load gate details');
                  return;
                }
                addSystem('');
                addSystem(`  GATE: ${data.gate_id}`);
                addOutput(`    Name:     ${data.display_name || data.gate_id}`);
                if (data.description) addOutput(`    Brief:    ${data.description}`);
                if (data.welcome) addOutput(`    Welcome:  ${data.welcome}`);
                addOutput(`    Creator:  ${data.creator_node_id}`);
                addOutput(`    Messages: ${data.message_count || 0}`);
                const rules = data.rules || {};
                addOutput(`    Min Rep:  ${rules.min_overall_rep || 'none'}`);
                addOutput(`    Catalog:  ${data.fixed ? 'fixed launch gate' : 'dynamic gate'}`);
                if (keyStatus?.ok) {
                  addOutput(`    Epoch:     ${keyStatus.current_epoch || 0}`);
                  addOutput(
                    `    Key:       ${String(keyStatus.key_commitment || '').slice(0, 16) || 'pending'}${keyStatus.key_commitment ? '...' : ''}`,
                  );
                  addOutput(
                    `    Access:    ${keyStatus.has_local_access ? keyStatus.identity_scope || 'member' : 'locked'}`,
                  );
                  if (keyStatus.identity_scope === 'anonymous' && !keyStatus.has_local_access) {
                    addLines([
                      {
                        text: '    Anonymous gate session is active, but this install has not synced local gate access yet.',
                        type: 'dim',
                      },
                      {
                        text: `    Retry the room or switch to: gate mask ${gateId}`,
                        type: 'dim',
                      },
                    ]);
                  }
                  if (keyStatus.rekey_recommended) {
                    addOutput(
                      `    Rekey:     advised (${String(keyStatus.rekey_recommended_reason || 'review').replace(/_/g, ' ')})`,
                    );
                  }
                }
                addSystem('');
              } catch {
                addError('Failed to fetch gate details');
              }
            } else {
              addError('Usage: gate <id> | gate mask <id> | gate anon <id> | gate rekey <id> [reason] | gate resync <id> | gate audit [limit]');
            }
            return;
  };

  const { handleMarketsCommand } = useMeshTerminalMarketsCommand({
    addError, addLines, addOutput, addSystem, nodeIdentity, hasSovereignty, asSearchRecords,
  });

  const handleInfonetCommand = async (cmd: string, args: string[], d: any) => {
    switch (cmd) {
            case 'infonet': {
              // infonet — Infonet protocol status
              try {
                const data = await fetchInfonetNodeStatusSnapshot(true);
                setInfonetNodeStatus(data);
                setInfonetNodeStatusError('');
                addSystem('');
                addSystem('  INFONET STATUS');
                addOutput(`    Network:     ${data.network_id || 'sb-testnet-0'}`);
                addOutput(
                  `    Events:      ${data.total_events ?? 0} total (${data.active_events ?? 0} active)`,
                );
                addOutput(`    Head Hash:   ${data.head_hash || 'genesis'}`);
                addOutput(`    Known Nodes: ${data.known_nodes ?? 0}`);
                addOutput(`    Chain Size:  ${data.chain_size_kb ?? 0} KB`);
                addOutput(`    Unsigned:    ${data.unsigned_events ?? 0}`);
                addOutput(
                  `    Valid:       ${data.valid ? 'YES' : 'NO'} — ${data.validation || '?'}`,
                );
                addLines(buildNodeRuntimeLines(data));
                const types = data.event_types || {};
                if (Object.keys(types).length > 0) {
                  addSystem('    Event Breakdown:');
                  for (const [t, count] of Object.entries(types)) {
                    addOutput(`      ${String(t).padEnd(16)} ${count}`);
                  }
                }
                addSystem('');
              } catch {
                setInfonetNodeStatusError('node runtime unavailable');
                addError('Failed to reach Infonet');
              }
              return;
            }
            case 'node':
              await cmdNode();
              return;
            case 'merkle':
              await cmdMerkle();
              return;
            case 'sync':
              await cmdSync(parseInt(args[0]) || 100);
              return;
            case 'peers': {
              const sub = args[0]?.toLowerCase();
              const current = getInfonetPeers();
              if (!sub) {
                addSystem('');
                addSystem(`  INFONET PEERS (${current.length})`);
                for (const peer of current) {
                  addOutput(`    ${peer}`);
                }
                addLines([
                  {
                    text: "    note: this is the manual browser sync list; backend participant-node peers come from the local peer store and show up in 'node'",
                    type: 'dim',
                  },
                ]);
                addSystem('');
                return;
              }
              if (sub === 'add') {
                const url = args[1];
                if (!url) {
                  addError('Usage: peers add <url>');
                  return;
                }
                const next = Array.from(new Set([...current, url]));
                setInfonetPeers(next.filter((p) => p !== API));
                addSystem(`  Added peer: ${url}`);
                return;
              }
              if (sub === 'remove') {
                const url = args[1];
                if (!url) {
                  addError('Usage: peers remove <url>');
                  return;
                }
                const next = current.filter((p) => p !== url);
                setInfonetPeers(next.filter((p) => p !== API));
                addSystem(`  Removed peer: ${url}`);
                return;
              }
              if (sub === 'clear') {
                setInfonetPeers([]);
                addSystem('  Cleared stored peers.');
                return;
              }
              addError('Usage: peers [add|remove|clear] <url>');
              return;
            }
            case 'messages': {
              // messages [gate] — browse Infonet messages
              const msgGate = args[0] || '';
              try {
                const msgs = msgGate
                  ? await fetchGateMessageSnapshot(msgGate, 20)
                  : ((await fetch(`${API}/api/mesh/infonet/messages?limit=20`).then((res) =>
                      res.json(),
                    )).messages || []).map((message: InfonetMessageRecord) =>
                      normalizeInfonetMessageRecord(message),
                    );
                addSystem('');
                if (!msgs.length) {
                  addSystem(
                    msgGate ? `  No messages in gate '${msgGate}'` : '  No messages on Infonet yet',
                  );
                } else {
                  addSystem(
                    msgGate
                      ? `  MESSAGES IN g/${msgGate} (${msgs.length})`
                      : `  RECENT MESSAGES (${msgs.length})`,
                  );
                  for (const m of msgs) {
                    if (m.system_seed) {
                      addSystem(`    ${m.fixed_gate ? 'FIXED GATE NOTICE' : 'GATE NOTICE'} [${m.gate || msgGate || 'infonet'}]`);
                      addLines([{ text: `      ${await describeGateMessagePreview(m)}`, type: 'dim' }]);
                      continue;
                    }
                    const age = Math.floor((Date.now() / 1000 - m.timestamp) / 60);
                    const ageStr = age < 60 ? `${age}m` : `${Math.floor(age / 60)}h`;
                    const gateStr = m.gate ? ` [${m.gate}]` : '';
                    const ephStr = m.ephemeral ? ' (ephemeral)' : '';
                    const encState = gateEnvelopeState(m);
                    const encLabel =
                      encState === 'decrypted'
                        ? ' [enc:open]'
                        : encState === 'locked'
                          ? ' [enc:locked]'
                          : '';
                    addOutput(`    ${m.node_id || ''} ${ageStr} ago${gateStr}${ephStr}${encLabel}`);
                    addLines([{ text: `      ${await describeGateMessagePreview(m)}`, type: 'dim' }]);
                    if (isEncryptedGateEnvelope(m)) {
                      const metaBits = [];
                      if (Number(m.epoch ?? 0) > 0) {
                        metaBits.push(`epoch=${Number(m.epoch ?? 0)}`);
                      }
                      if (m.sender_ref) {
                        metaBits.push(`sender_ref=${String(m.sender_ref)}`);
                      }
                      if (metaBits.length) {
                        addLines([{ text: `      ${metaBits.join(' ')}`, type: 'dim' }]);
                      }
                    }
                    addLines([{ text: `      id: ${m.event_id.slice(0, 16)}...`, type: 'dim' }]);
                  }
                }
                addSystem('');
              } catch {
                addError('Failed to fetch messages');
              }
              return;
            }
            case 'event': {
              // event <event_id> — look up an Infonet event
              const evtId = args[0];
              if (!evtId) {
                addError('Usage: event <event_id>');
                return;
              }
              try {
                const res = await fetch(`${API}/api/mesh/infonet/event/${encodeURIComponent(evtId)}`);
                const data = await res.json();
                if (data.ok === false) {
                  addError(data.detail);
                  return;
                }
                addSystem('');
                addSystem(`  INFONET EVENT`);
                addOutput(`    ID:        ${data.event_id}`);
                addOutput(`    Type:      ${data.event_type}`);
                addOutput(`    Node:      ${data.node_id}`);
                addOutput(`    Seq:       ${data.sequence}`);
                addOutput(`    Prev Hash: ${(data.prev_hash || '').slice(0, 16)}...`);
                addOutput(`    Network:   ${data.network_id || '?'}`);
                const ts = new Date(data.timestamp * 1000).toLocaleString();
                addOutput(`    Time:      ${ts}`);
                if (data.signature) {
                  addOutput(`    Signature: ${data.signature.slice(0, 32)}...`);
                }
                addSystem('    Payload:');
                const payload = data.payload || {};
                for (const [k, v] of Object.entries(payload)) {
                  if (k.startsWith('_')) continue;
                  addLines([{ text: `      ${k}: ${String(v).slice(0, 60)}`, type: 'dim' }]);
                }
                addSystem('');
              } catch {
                addError('Failed to fetch event');
              }
              return;
            }
            case 'ledger': {
              // ledger [node_id] — view a node's Infonet activity
              const ledgerTarget = args[0] || (nodeIdentity?.nodeId ?? '');
              if (!ledgerTarget) {
                addError("Usage: ledger <node_id>  (or just 'ledger' for your own)");
                return;
              }
              try {
                const res = await fetch(
                  `${API}/api/mesh/infonet/node/${encodeURIComponent(ledgerTarget)}?limit=20`,
                );
                const data = await res.json();
                const events = data.events || [];
                addSystem('');
                if (!events.length) {
                  addSystem(`  No Infonet activity for ${ledgerTarget}`);
                } else {
                  addSystem(`  INFONET ACTIVITY: ${ledgerTarget} (${events.length} events)`);
                  for (const e of events) {
                    const age = Math.floor((Date.now() / 1000 - e.timestamp) / 60);
                    const ageStr =
                      age < 60
                        ? `${age}m`
                        : age < 1440
                          ? `${Math.floor(age / 60)}h`
                          : `${Math.floor(age / 1440)}d`;
                    const payload = e.payload || {};
                    let detail = '';
                    if (e.event_type === 'message' || e.event_type === 'gate_message') {
                      detail = (payload.message || '').slice(0, 40);
                    } else if (e.event_type === 'vote') {
                      detail = `${payload.vote > 0 ? '+1' : '-1'} on ${payload.target_id}`;
                    } else if (e.event_type === 'gate_create') {
                      detail = `created g/${payload.gate_id}`;
                    } else if (e.event_type === 'prediction') {
                      detail = `${payload.side} on ${(payload.market_title || '').slice(0, 30)}`;
                    } else if (e.event_type === 'stake') {
                      detail = `${payload.side} ${payload.amount} on ${payload.message_id}`;
                    } else if (e.event_type === 'key_rotate') {
                      detail = `rotated from ${String(payload.old_node_id || '').slice(0, 12)}`;
                    } else if (e.event_type === 'key_revoke') {
                      const until = payload.grace_until
                        ? new Date(Number(payload.grace_until) * 1000).toLocaleString()
                        : 'unknown';
                      detail = `revoked key (grace until ${until})`;
                    }
                    addOutput(`    [${e.event_type.padEnd(14)}] ${ageStr} ago  ${detail}`);
                  }
                }
                addSystem('');
              } catch {
                addError('Failed to fetch node activity');
              }
              return;
            }
            case 'rotate':
              await cmdRotate();
              return;
            case 'revoke':
              await cmdRevoke(args);
              return;
            // ─── Encrypted DM Commands ───────────────────────────
      default: return;
    }
  };

  const handleDmCommand = async (cmd: string, args: string[], d: any) => {
    switch (cmd) {
            case 'dm': {
              const sub = args[0]?.toLowerCase();

              if (sub === 'selftest' || sub === 'test') {
                addSystem('  Running local DM selftest...');
                try {
                  const data = await runWormholeDmSelftest(args.slice(1).join(' '));
                  const failedSteps = (data.steps || []).filter((step) => !step.ok);
                  const failedChecks = (data.privacy_checks || []).filter((check) => !check.ok);
                  if (data.ok) {
                    addSystem('  DM SELFTEST PASSED');
                  } else {
                    addError(
                      `DM selftest failed: ${failedSteps.length} step(s), ${failedChecks.length} privacy check(s) failed.`,
                    );
                  }
                  addOutput(`    Mode:       ${data.mode}`);
                  addOutput(`    Transport:  ${data.transport_tier}`);
                  addOutput(`    Run ID:     ${data.run_id}`);
                  addOutput(
                    `    Steps:      ${(data.steps || []).filter((step) => step.ok).length}/${(data.steps || []).length}`,
                  );
                  addOutput(
                    `    Warnings:   ${(data.steps || []).filter((step) => !step.ok && !step.required).length}`,
                  );
                  addOutput(
                    `    Privacy:    ${(data.privacy_checks || []).filter((check) => check.ok).length}/${(data.privacy_checks || []).length}`,
                  );
                  if (data.artifacts?.ciphertext_sha256) {
                    addLines([
                      {
                        text: `    Ciphertext: ${data.artifacts.ciphertext_sha256.slice(0, 24)}...`,
                        type: 'dim',
                      },
                    ]);
                  }
                  for (const check of data.privacy_checks || []) {
                    addLines([
                      {
                        text: `    [${check.ok ? 'OK' : 'FAIL'}] ${check.name}: ${check.detail || ''}`,
                        type: check.ok ? 'output' : 'error',
                      },
                    ]);
                  }
                  const limits = (data.unproven_by_this_test || []).slice(0, 3);
                  if (limits.length) {
                    addSystem('  Still unproven by this local test:');
                    for (const limit of limits) {
                      addLines([{ text: `    - ${limit}`, type: 'dim' }]);
                    }
                  }
                } catch (err) {
                  const msg =
                    typeof err === 'object' && err !== null && 'message' in err
                      ? String((err as { message?: string }).message)
                      : 'selftest failed';
                  addError(`DM selftest failed: ${msg}`);
                }
                addSystem('');
                return;
              }

              if (!nodeIdentity || !hasSovereignty()) {
                addError("Not connected. Type 'connect' to activate your Agent identity.");
                return;
              }

              // dm add <agent_id> [alias]
              if (sub === 'add') {
                const targetId = args[1];
                if (!targetId) {
                  addError('Usage: dm add <agent_id> [alias]');
                  return;
                }
                try {
                  const data = await fetchDmPublicKey(API, targetId, undefined, {
                    allowLegacyAgentId: true,
                  });
                  if (!data?.dh_pub_key) {
                    addError('Agent not found or has no DM keys.');
                    return;
                  }
                  const alias = args[2] || undefined;
                  addContact(targetId, data.dh_pub_key, alias, data.dh_algo);
                  updateContact(targetId, {
                    remotePrekeyLookupMode: String(data.lookup_mode || '').trim().toLowerCase(),
                  });
                  addSystem(`  Contact added: ${targetId}${alias ? ` (${alias})` : ''}`);
                  if (String(data.lookup_mode || '').trim().toLowerCase() === 'legacy_agent_id') {
                    addLines([
                      {
                        text: "  Legacy lookup only. Import or re-import a signed invite to replace stable-ID lookup.",
                        type: 'dim',
                      },
                    ]);
                  }
                } catch {
                  addError('Failed to fetch agent key');
                }
                return;
              }

              // dm block <agent_id>
              if (sub === 'block') {
                const targetId = args[1];
                if (!targetId) {
                  addError('Usage: dm block <agent_id>');
                  return;
                }
                blockContact(targetId);
                try {
                  const sequence = nextSequence();
                  const blockPayload = {
                    blocked_id: targetId,
                    action: 'block',
                    transport_lock: 'private_strong',
                  };
                  const v = validateEventPayload('dm_block', blockPayload);
                  if (!v.ok) {
                    addError(`Invalid payload: ${v.reason}`);
                    return;
                  }
                  const signature = await signEvent(
                    'dm_block',
                    nodeIdentity.nodeId,
                    sequence,
                    blockPayload,
                  );
                  await fetch(`${API}/api/mesh/dm/block`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      agent_id: nodeIdentity.nodeId,
                      blocked_id: targetId,
                      action: 'block',
                      transport_lock: 'private_strong',
                      public_key: nodeIdentity.publicKey,
                      public_key_algo: getPublicKeyAlgo(),
                      signature,
                      sequence,
                      protocol_version: PROTOCOL_VERSION,
                    }),
                  });
                } catch {
                  /* local block still works */
                }
                addSystem(`  Blocked ${targetId}. Their messages will be dropped.`);
                return;
              }

              // dm unblock <agent_id>
              if (sub === 'unblock') {
                const targetId = args[1];
                if (!targetId) {
                  addError('Usage: dm unblock <agent_id>');
                  return;
                }
                unblockContact(targetId);
                try {
                  const sequence = nextSequence();
                  const blockPayload = {
                    blocked_id: targetId,
                    action: 'unblock',
                    transport_lock: 'private_strong',
                  };
                  const v = validateEventPayload('dm_block', blockPayload);
                  if (!v.ok) {
                    addError(`Invalid payload: ${v.reason}`);
                    return;
                  }
                  const signature = await signEvent(
                    'dm_block',
                    nodeIdentity.nodeId,
                    sequence,
                    blockPayload,
                  );
                  await fetch(`${API}/api/mesh/dm/block`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      agent_id: nodeIdentity.nodeId,
                      blocked_id: targetId,
                      action: 'unblock',
                      transport_lock: 'private_strong',
                      public_key: nodeIdentity.publicKey,
                      public_key_algo: getPublicKeyAlgo(),
                      signature,
                      sequence,
                      protocol_version: PROTOCOL_VERSION,
                    }),
                  });
                } catch {
                  /* local unblock still works */
                }
                addSystem(`  Unblocked ${targetId}.`);
                return;
              }

              // dm notify on|off
              if (sub === 'notify') {
                const val = args[1]?.toLowerCase();
                if (val === 'on') {
                  setDMNotify(true);
                  addSystem('  DM notifications ON.');
                } else if (val === 'off') {
                  setDMNotify(false);
                  addSystem('  DM notifications OFF.');
                  if (onDmCount) onDmCount(0);
                } else {
                  addSystem(`  DM notifications: ${getDMNotify() ? 'ON' : 'OFF'}`);
                  addLines([{ text: '  Usage: dm notify on|off', type: 'dim' }]);
                }
                return;
              }

              // dm <agent_id> <message> — direct one-liner send
              if (sub && sub.startsWith('!sb_')) {
                const msg = args.slice(1).join(' ');
                if (!msg) {
                  // Start interactive DM with this recipient
                  setDmDest(sub);
                  setDmStep('msg');
                  addSystem('');
                  addSystem(`  DM to ${sub}`);
                  addLines([{ text: '  Type your private message:', type: 'dim' }]);
                  addSystem('');
                  return;
                }
                await doDMSend(sub, msg);
                return;
              }

              // bare "dm" — interactive flow
              if (!sub) {
                addSystem('');
                addSystem('  ENCRYPTED DM');
                addLines([{ text: '  Enter recipient Agent ID (e.g. !sb_a3f2c891):', type: 'dim' }]);
                addSystem('');
                setDmStep('dest');
                return;
              }

              addError('Usage: dm [agent_id] [msg] | dm add/block/unblock/notify');
              return;
            }
      default: return;
    }
  };

  const handleInboxCommand = async (cmd: string, args: string[], d: any) => {
    switch (cmd) {
            case 'inbox': {
              if (!nodeIdentity || !hasSovereignty()) {
                addError("Not connected. Type 'connect' to activate your Agent identity.");
                return;
              }
              addSystem('  Checking dead drop...');
              try {
                const claims = await buildMailboxClaims(getContacts());
                const data = await pollDmMailboxes(API, nodeIdentity, claims);
                const msgs = data.messages || [];
                if (msgs.length === 0) {
                  addSystem('  No pending messages.');
                  addSystem('');
                  return;
                }
                addSystem(`  ${msgs.length} message${msgs.length > 1 ? 's' : ''} retrieved:`);
                addSystem('');
                for (const m of msgs) {
                  const age = Math.floor((Date.now() / 1000 - m.timestamp) / 60);
                  const ageStr = age < 60 ? `${age}m ago` : `${Math.floor(age / 60)}h ago`;
                  try {
                    // Get sender's DH key
                    const contacts = getContacts();
                    let senderDH = contacts[m.sender_id]?.dhPubKey;
                    if (!senderDH) {
                      const contact = contacts[m.sender_id];
                      const keyData = await fetchDmPublicKey(
                        API,
                        m.sender_id,
                        contact?.invitePinnedPrekeyLookupHandle,
                      );
                      if (keyData?.dh_pub_key) {
                        senderDH = keyData.dh_pub_key as string;
                        addContact(m.sender_id, senderDH!, undefined, keyData.dh_algo);
                        updateContact(m.sender_id, {
                          dhAlgo: keyData.dh_algo || contact?.dhAlgo,
                          remotePrekeyLookupMode:
                            String(keyData.lookup_mode || '').trim().toLowerCase() ||
                            contact?.remotePrekeyLookupMode,
                        });
                      }
                    }
                    if (!senderDH) {
                      addOutput(`  [${m.sender_id}] ${ageStr} — (cannot decrypt: no key)`);
                      continue;
                    }
                    let plaintext = '';
                    try {
                      plaintext = await ratchetDecryptDM(m.sender_id, m.ciphertext);
                    } catch {
                      const sharedKey = await deriveSharedKey(senderDH);
                      plaintext = await decryptDM(m.ciphertext, sharedKey);
                    }
                    addOutput(`  [${m.sender_id}] ${ageStr}`);
                    addLines([{ text: `    ${plaintext}`, type: 'output' }]);
                  } catch {
                    addOutput(`  [${m.sender_id}] ${ageStr} — (decryption failed)`);
                  }
                  addSystem('');
                }
                // Clear badge
                if (onDmCount) onDmCount(0);
              } catch {
                addError('Failed to check inbox');
              }
              return;
            }
      default: return;
    }
  };

  const { doSend, doMeshSend, startInteractiveSend, doDMSend } = useMeshTerminalSendFlow({
    addError, addLines, addSystem, nodeIdentity, setSendStep,
  } as any);

  const handleSendCommand = async (args: string[]) => {
            if (!nodeIdentity || !hasSovereignty()) {
              if (isDeclined()) {
                addError("Read-only mode. Type 'connect' to activate your Agent identity.");
              } else {
                addLines([...SOVEREIGNTY_DECLARATION]);
                setSovereigntyPending(true);
              }
              setBusy(false);
              return;
            }
            if (args.length >= 2) {
              await doSend(args[0], args.slice(1).join(' '));
            } else {
              startInteractiveSend();
            }
  };

  const handleWhoamiCommand = async () => {
            addSystem('');
            addSystem('  IDENTITY LANES');
            if (nodeIdentity && hasSovereignty()) {
              addOutput(`    Public Agent: ${nodeIdentity.nodeId}`);
              addOutput(`    Public Key: ${nodeIdentity.publicKey.slice(0, 24)}...`);
              addSystem('    Status: ACTIVE — public mesh and perimeter sends sign with this key');
            } else if (isDeclined()) {
              addSystem('    Public Agent: READ-ONLY (declined)');
              addLines([{ text: "    Type 'connect' to create a public Agent.", type: 'dim' }]);
            } else {
              addLines([
                {
                  text: "    Public Agent: not connected — type 'connect' to create one.",
                  type: 'dim',
                },
              ]);
            }
            addOutput(`    Wormhole Lane: ${privateLaneLabel}`);
            addLines([{ text: `    ${privateLaneDetail}`, type: 'dim' }]);
            addSystem('');
  };

  const handleConnectCommand = async () => {
            if (nodeIdentity && hasSovereignty()) {
              addSystem(`  Public Agent already active as ${nodeIdentity.nodeId}. Type 'whoami' for lane status.`);
            } else {
              addLines([...SOVEREIGNTY_DECLARATION]);
              setSovereigntyPending(true);
            }
  };
  const handleRepCommand = async (args: string[]) => {
            const targetId = args[0];
            if (!targetId) { addError('Usage: rep <node_id>  (e.g. rep !sb_a3f2c891)'); return; }
            try {
              const res = await fetch(`${API}/api/mesh/reputation?node_id=${encodeURIComponent(targetId)}`);
              const data = await res.json();
              if (data.ok === false) { addError(data.detail); return; }
              addSystem('');
              addSystem(`  REPUTATION: ${data.node_id}`);
              addOutput(`    Overall: ${data.overall}`);
              addOutput('    Sources:');
              for (const [src, val] of Object.entries(data.breakdown || {})) {
                addOutput(`      ${String(src).padEnd(20)} ${Number(val).toFixed(1)}`);
              }
              addSystem('');
            } catch { addError('Failed to fetch reputation'); }
  };
  const handleMyrepCommand = async () => {
            if (!nodeIdentity) { addError('No identity. Run /whoami or connect first.'); return; }
            try {
              const res = await fetch(`${API}/api/mesh/reputation?node_id=${encodeURIComponent(nodeIdentity.nodeId)}`);
              const data = await res.json();
              if (data.ok === false) { addError(data.detail); return; }
              addSystem('');
              addSystem(`  YOUR REPUTATION: ${data.node_id}`);
              addOutput(`    Overall: ${data.overall}`);
              for (const [src, val] of Object.entries(data.breakdown || {})) {
                addOutput(`      ${String(src).padEnd(20)} ${Number(val).toFixed(1)}`);
              }
              addSystem('');
            } catch { addError('Failed to fetch reputation'); }
  };
  const handleThresholdCommand = (args: string[]) => {
            const n = parseInt(args[0]);
            if (isNaN(n) || n < 0) {
              const current = typeof window !== 'undefined' ? localStorage.getItem('sb_mesh_rep_threshold') || '0' : '0';
              addSystem(`  Current DM threshold: ${current} (min rep to receive messages)`);
              addLines([{ text: '  Usage: threshold <n>  (e.g. threshold 5)', type: 'dim' }]);
              return;
            }
            localStorage.setItem('sb_mesh_rep_threshold', String(n));
            addSystem(`  DM threshold set to ${n}. Only nodes with rep >= ${n} can message you.`);
  };

  const handleVoteCommand = async (args: string[]) => {
            // vote <agent_id> up|down [gate]
            if (!nodeIdentity || !hasSovereignty()) {
              addError("Not connected. Type 'connect' to activate your Agent identity.");
              return;
            }
            const vTarget = args[0];
            const vDir = args[1]?.toLowerCase();
            const voteGate =
              String(args[2] || activeGateComposeId || expandedGateId || '').trim().toLowerCase();
            if (!vTarget || !vDir || !['up', 'down'].includes(vDir)) {
              addError('Usage: vote <node_id> up|down [gate]');
              return;
            }
            try {
              const voteVal = vDir === 'up' ? 1 : -1;
              const existingVote = voteDirections[voteScopeKey(vTarget, voteGate)];
              if (existingVote === voteVal) {
                addSystem(
                  `  Vote already set to ${voteVal > 0 ? 'up' : 'down'} on ${vTarget}${voteGate ? ` in g/${voteGate}` : ''}.`,
                );
                return;
              }
              const sequence = nextSequence();
              const votePayload = { target_id: vTarget, vote: voteVal, gate: voteGate };
              const v = validateEventPayload('vote', votePayload);
              if (!v.ok) {
                addError(`Invalid payload: ${v.reason}`);
                return;
              }
              const signature = await signEvent('vote', nodeIdentity.nodeId, sequence, votePayload);
              const res = await fetch(`${API}/api/mesh/vote`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  voter_id: nodeIdentity.nodeId,
                  voter_pubkey: nodeIdentity.publicKey,
                  target_id: vTarget,
                  vote: voteVal,
                  gate: voteGate || undefined,
                  public_key_algo: getPublicKeyAlgo(),
                  voter_sig: signature,
                  sequence,
                  protocol_version: PROTOCOL_VERSION,
                }),
              });
              const data = await res.json();
              if (data.ok) {
                setVoteDirections((prev) => ({
                  ...prev,
                  [voteScopeKey(vTarget, voteGate)]: voteVal,
                }));
                addSystem(`  ${data.detail}`);
              } else {
                addError(data.detail);
              }
            } catch {
              addError('Failed to cast vote');
            }
            return;
  };

  const handleSayCommand = async (args: string[]) => {
          if (!gateAccessGranted) {
            requestGateAccess(`say ${args.join(' ')}`.trim());
            return;
          }
          // say <gate_id> <message>
          if (!wormholeSecureRequired || !wormholeReadyState) {
            addSystem('  Preparing Wormhole in the background for gate posting...');
            try {
              const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
              setWormholeSecureRequired(Boolean(prepared.settingsEnabled));
              setWormholeReadyState(Boolean(prepared.ready));
            } catch (err) {
              addError(
                describeNativeControlError(err) ||
                  (err instanceof Error ? err.message : 'Failed to prepare Wormhole.'),
              );
              return;
            }
          }
            const gateId = args[0];
            const gateMsg = args.slice(1).join(' ');
            if (!gateId || !gateMsg) {
              addError('Usage: say <gate_id> <message>');
              return;
          }
            try {
              const data = await postGateMessage(gateId, gateMsg);
              invalidateGateCatalogSnapshot();
              invalidateGateDetailSnapshot(gateId);
              invalidateGateThreadPreviewSnapshot(gateId);
              addSystem(`  ${data.detail || `Posted to g/${gateId}`}`);
            } catch (err) {
              const detail = err instanceof Error && err.message ? err.message : '';
              if (!addGateResyncAction(err, gateId)) {
                addError(describeNativeControlError(err) || detail || 'Failed to post to gate');
              }
            }
          return;
  };

  const handleSimpleCommand = async (cmd: string, args: string[]) => {
    switch (cmd) {
      case 'apps': cmdApps(); return;
      case 'news': await cmdNews(args.join(' ')); return;
      case 'jet': case 'jets': await cmdJets(args.join(' ')); return;
      case 'place': case 'places': await cmdPlaces(args.join(' ')); return;
      case 'dossier': case 'intel': await cmdDossier(args.join(' ')); return;
      case 'shodan': await cmdShodan(args); return;
      case 'log': await cmdLog(parseInt(args[0]) || 5); return;
      case 'nearest': case 'sdr': await cmdNearest(args[0], args[1]); return;
      default: return;
    }
  };

  const handleInteractivePromptInput = async (trimmed: string): Promise<boolean> => {
    // ─── Interactive send flow ─────────────────────────────
    if (sendStep === 'dest') {
      addLines([{ text: `  > ${trimmed}`, type: 'input' }]);
      setSendDest(trimmed);
      setSendStep('msg');
      addLines([{ text: `  Destination: ${trimmed}`, type: 'system' }]);
      addLines([{ text: '  Now type your message:', type: 'dim' }]);
      addSystem('');
      return true;
    }
    if (sendStep === 'msg') {
      addLines([{ text: `  > ${trimmed}`, type: 'input' }]);
      if (terminalWriteLockReason) {
        addError(terminalWriteLockReason);
        setSendStep(null);
        setSendDest('');
        return true;
      }
      setSendStep(null);
      setBusy(true);
      await doSend(sendDest, trimmed);
      setSendDest('');
      setBusy(false);
      return true;
    }

    // ─── Interactive DM flow ───────────────────────────────
    if (dmStep === 'dest') {
      addLines([{ text: `  > ${trimmed}`, type: 'input' }]);
      setDmDest(trimmed);
      setDmStep('msg');
      addLines([{ text: `  To: ${trimmed}`, type: 'system' }]);
      addLines([{ text: '  Type your private message:', type: 'dim' }]);
      addSystem('');
      return true;
    }
    if (dmStep === 'msg') {
      addLines([{ text: `  > ${trimmed}`, type: 'input' }]);
      if (terminalWriteLockReason) {
        addError(terminalWriteLockReason);
        setDmStep(null);
        setDmDest('');
        return true;
      }
      setDmStep(null);
      setBusy(true);
      await doDMSend(dmDest, trimmed);
      setDmDest('');
      setBusy(false);
      return true;
    }

    return false;
  };

  const handleGateChatModeInput = async (trimmed: string): Promise<boolean> => {
      if (gateChatMode && activeGateComposeId) {
      addLines([
        {
          text: `  > ${gateReplyTarget ? `@${gateReplyTarget} ` : ''}${trimmed}`,
          type: 'input',
        },
      ]);
      if (terminalWriteLockReason) {
        addError(terminalWriteLockReason);
        return true;
      }
      if (!wormholeSecureRequired || !wormholeReadyState) {
        addSystem('  Preparing Wormhole in the background for gate posting...');
        try {
          const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
          setWormholeSecureRequired(Boolean(prepared.settingsEnabled));
          setWormholeReadyState(Boolean(prepared.ready));
        } catch (err) {
          addError(describeNativeControlError(err) || (err instanceof Error ? err.message : 'Failed to prepare Wormhole.'));
          return true;
        }
      }
      setBusy(true);
      await (async () => {
        try {
          const messageToSend = gateReplyTarget ? `@${gateReplyTarget} ${trimmed}` : trimmed;
          await postGateMessage(activeGateComposeId, messageToSend);
          invalidateGateCatalogSnapshot();
          invalidateGateDetailSnapshot(activeGateComposeId);
          invalidateGateThreadPreviewSnapshot(activeGateComposeId);
          addSystem(`  Posted to g/${activeGateComposeId}`);
          setGateReplyTarget(null);
          await openGateCard(activeGateComposeId, { force: true });
        } catch (err) {
          const detail = err instanceof Error && err.message ? err.message : '';
          if (!addGateResyncAction(err, activeGateComposeId)) {
            addError(describeNativeControlError(err) || detail || 'Failed to post to gate');
          }
        } finally {
          setBusy(false);
        }
      })();
      return true;
    }

    return false;
  };

  const handleSovereigntyPromptInput = async (trimmed: string): Promise<boolean> => {
      // ─── Sovereignty declaration flow ───────────────────────
    if (sovereigntyPending) {
      addLines([{ text: `  > ${trimmed}`, type: 'input' }]);
      const lower = trimmed.toLowerCase();
      if (lower === 'accept') {
        if (terminalWriteLockReason) {
          addError(terminalWriteLockReason);
          addLines([
            {
              text: '  Mesh Terminal is read-only for sensitive actions until it is routed through Wormhole.',
              type: 'dim',
            },
          ]);
          return true;
        }
        setBusy(true);
        setSovereigntyPending(false);
        try {
          addSystem('  Generating Ed25519 keypair...');
          const identity = await generateNodeKeys();
          setNodeIdentity(identity);
          addSystem('');
          addSystem('  AGENT ACTIVATED');
          addOutput(`    Agent ID:   ${identity.nodeId}`);
          addOutput(`    Public Key: ${identity.publicKey.slice(0, 24)}...`);
          addSystem('    Private key stored locally — never leaves this device.');
          addSystem('');
          // Register DH public key for encrypted DMs
          const dhPub = getDHPubKey();
          if (dhPub) {
            try {
              await ensureRegisteredDmKey(API, identity, { force: true });
              addOutput('    Encrypted DM keys registered.');
            } catch {
              /* non-critical */
            }
          }
          addSystem('');
          addSystem('  You are now an agent on the Infonet.');
          addSystem("  Type 'help' for commands, 'send' to transmit, 'dm' for private messages.");
          addSystem('');
        } catch (err) {
          const msg =
            typeof err === 'object' && err !== null && 'message' in err
              ? String((err as { message?: string }).message)
              : 'unknown error';
          addError(
            msg === 'browser_identity_blocked_secure_mode'
              ? 'Browser identity generation is disabled in Wormhole secure mode'
              : `Key generation failed: ${msg}`,
          );
        }
        setBusy(false);
        return true;
      } else if (lower === 'decline') {
        setSovereigntyPending(false);
        declineSovereignty();
        addSystem('');
        addSystem('  Read-only mode active. You can view signals and status.');
        addLines([{ text: "  To activate later, type 'accept' when prompted.", type: 'dim' }]);
        addSystem('');
        return true;
      } else {
        addLines([{ text: "  Type 'accept' or 'decline'.", type: 'dim' }]);
        return true;
      }
    }

    return false;
  };

  const exec = useCallback(
    async (raw: string) => {
      const trimmed = raw.trim();
      if (!trimmed) return;

      const slashMode = trimmed.startsWith('/');
      const normalized = slashMode ? trimmed.slice(1).trim() : trimmed;
      const gateChatMode =
        !slashMode &&
        surfacePanel === 'gates' &&
        Boolean(activeGateComposeId) &&
        !sendStep &&
        !dmStep &&
        !sovereigntyPending;

      if (await handleGateChatModeInput(trimmed)) return;

      if (await handleSovereigntyPromptInput(trimmed)) return;
      if (await handleInteractivePromptInput(trimmed)) return;

      // ─── Normal command flow ───────────────────────────────
      addLines([{ text: `  > ${slashMode ? normalized : trimmed}`, type: 'input' }]);
      setHistory((prev) => [slashMode ? normalized : trimmed, ...prev.slice(0, 49)]);
      setHistIdx(-1);
      setBusy(true);

      const [cmd, ...args] = normalized.split(/\s+/);
      try {
        if (terminalWriteLockReason && isMeshTerminalWriteCommand(cmd, args)) {
          addError(terminalWriteLockReason);
          addLines([
            {
              text: '  Mesh Terminal remains read-only for these actions until it is routed through Wormhole.',
              type: 'dim',
            },
          ]);
          setBusy(false);
          return;
        }
        switch (cmd.toLowerCase()) {
          case 'help': {
            const section = String(args[0] || '').toLowerCase();
            if (!section) {
              addSystem('');
              addSystem('  HELP CATEGORIES');
              addOutput('    help mesh      Public mesh and radio commands');
              addOutput('    help gates     Encrypted gate commons commands');
              addOutput('    help inbox     Experimental obfuscated DM inbox commands');
              addOutput('    help markets   Prediction market and oracle commands');
              addOutput('    help infonet   Ledger, sync, and message browsing');
              addOutput('    help ops       Dossiers, news, Shodan, places, aircraft');
              addSystem('');
              addLines([{ text: '  Click the HELP cards above or type one of the categories for details.', type: 'dim' }]);
              break;
            }
            const sectionLines = HELP_SECTIONS[section];
            if (!sectionLines) {
              addError(`Unknown help category '${section}'. Try: mesh, gates, inbox, markets, infonet, ops`);
              break;
            }
            addSystem('');
            for (const line of sectionLines) {
              if (line.startsWith('  ') && !line.startsWith('    ')) addSystem(line);
              else addOutput(line);
            }
            addSystem('');
            break;
          }
          case 'guide':
            addLines([...GUIDE_TEXT]);
            break;
          case 'clear':
            setLines([
              { text: '', type: 'dim' },
              {
                text:
                  surfacePanel === 'gates' && activeGateComposeId
                    ? `  Cleared. Still inside g/${activeGateComposeId}. Type to post or /help gates for commands.`
                    : surfacePanel === 'mesh'
                      ? `  Cleared. Still in the MESH lane for ${meshRegion}. Type 'mesh listen 12' or 'mesh send <msg>'.`
                      : "  Cleared. Type 'help' for categories or 'clear' again any time.",
                type: 'system',
              },
              { text: '', type: 'dim' },
            ]);
            break;
          case 'status':
            await cmdStatus();
            break;
          case 'signals':
          case 'sig':
            await cmdSignals(parseInt(args[0]) || 10);
            break;
          case 'mesh':
          case 'radio': {
            await handleMeshCommand(cmd.toLowerCase(), args, {});
            break;
          }
          case 'send':
            await handleSendCommand(args);
            break;
          case 'whoami': {
            await handleWhoamiCommand();
            break;
          }
          case 'connect':
          case 'sovereignty':
          case 'sovereign':
          case 'activate':
          case 'join': {
            await handleConnectCommand();
            break;
          }
          case 'rep': {
            await handleRepCommand(args);
            break;
          }
          case 'myrep': {
            await handleMyrepCommand();
            break;
          }
          case 'vote': {
            await handleVoteCommand(args);
            break;
          }
          case 'threshold': {
            handleThresholdCommand(args);
            break;
          }
          case 'gates': {
            await handleGatesCommand({});
            break;
          }
          case 'gate': {
            await handleGateCommand(args, {});
            break;
          }
          case 'say': {
            await handleSayCommand(args);
            break;
          }
          case 'apps': case 'news': case 'jet': case 'jets': case 'place': case 'places': case 'dossier': case 'intel': case 'shodan': case 'log': case 'nearest': case 'sdr': {
            await handleSimpleCommand(cmd.toLowerCase(), args);
            break;
          }
          case 'infonet': {
            await handleInfonetCommand(cmd.toLowerCase(), args, {});
            break;
          }
          case 'dm': {
            await handleDmCommand(cmd.toLowerCase(), args, {});
            break;
          }
          case 'inbox': {
            await handleInboxCommand(cmd.toLowerCase(), args, {});
            break;
          }
          case 'contacts': {
            const contactMap = getContacts();
            const ids = Object.keys(contactMap);
            if (ids.length === 0) { addSystem("  No contacts. Use 'dm add <agent_id>' to add one."); break; }
            addSystem('');
            addSystem(`  CONTACTS (${ids.length})`);
            for (const id of ids) {
              const c = contactMap[id];
              addOutput(`    ${id}${c.alias ? ` (${c.alias})` : ''} — ${c.blocked ? 'BLOCKED' : 'active'}`);
            }
            addSystem('');
            break;
          }

          default: {
            const suggestions: Record<string, string> = {
              stat: 'status',
              stats: 'status',
              info: 'status',
              signal: 'signals',
              listen: 'signals',
              rx: 'signals',
              msg: 'send',
              message: 'send',
              tx: 'send',
              transmit: 'send',
              logs: 'log',
              history: 'log',
              audit: 'log',
              find: 'nearest',
              locate: 'nearest',
              meshtastic: 'mesh',
              lora: 'mesh',
              radio: 'mesh',
              region: 'mesh',
              tutorial: 'guide',
              intro: 'guide',
              howto: 'guide',
              how: 'guide',
              '?': 'help',
              commands: 'help',
              id: 'whoami',
              identity: 'whoami',
              me: 'whoami',
              node: 'whoami',
              agent: 'whoami',
              reputation: 'rep',
              score: 'rep',
              upvote: 'vote',
              downvote: 'vote',
              community: 'gates',
              rooms: 'gates',
              channels: 'gates',
              bet: 'predict',
              prediction: 'predict',
              forecast: 'predict',
              market: 'markets',
              bets: 'markets',
              predictions: 'markets',
              headlines: 'news',
              intel: 'dossier',
              brief: 'dossier',
              dossier: 'dossier',
              lookup: 'place',
              location: 'place',
              geo: 'place',
              jet: 'jets',
              aircraft: 'jets',
              plane: 'jets',
              recon: 'apps',
              tools: 'apps',
              surfaces: 'apps',
              staking: 'stake',
              wager: 'stake',
              blockchain: 'infonet',
              hashchain: 'infonet',
              chain: 'infonet',
              block: 'infonet',
              merkle: 'merkle',
              root: 'merkle',
              sync: 'sync',
              verify: 'sync',
              msgs: 'messages',
              browse: 'messages',
              feed: 'messages',
              events: 'infonet',
              activity: 'ledger',
              net: 'infonet',
              mail: 'inbox',
              email: 'inbox',
              unread: 'inbox',
              check: 'inbox',
              pm: 'dm',
              whisper: 'dm',
              private: 'dm',
              encrypt: 'dm',
              contact: 'contacts',
              friends: 'contacts',
              people: 'contacts',
            };
            const suggestion = suggestions[cmd.toLowerCase()];
            if (suggestion) {
              addLines([{ text: `  Did you mean '${suggestion}'?`, type: 'dim' }]);
            } else {
              addLines([
                {
                  text: `  '${cmd}' is not a command. Type 'help' to see what's available.`,
                  type: 'dim',
                },
              ]);
            }
          }
        }
      } catch (err) {
        const msg =
          typeof err === 'object' && err !== null && 'message' in err
            ? String((err as { message?: string }).message)
            : '';
        addError(msg || 'Something went wrong');
      }
      setBusy(false);
    },
    [
      addLines,
      addOutput,
      addError,
      addSystem,
      cmdStatus,
      cmdNode,
      cmdSignals,
      cmdMerkle,
      cmdSync,
      cmdRevoke,
      cmdRotate,
      getInfonetPeers,
      setInfonetPeers,
      doSend,
      doMeshSend,
      doDMSend,
      cmdLog,
      cmdNearest,
      sendStep,
      sendDest,
      startInteractiveSend,
      dmStep,
      dmDest,
      meshRegion,
      meshRoots,
      sovereigntyPending,
      terminalWriteLockReason,
      nodeIdentity,
      onDmCount,
      surfacePanel,
      activeGateComposeId,
      gateReplyTarget,
      gateAccessGranted,
      expandedGateId,
      voteDirections,
      voteScopeKey,
      wormholeSecureRequired,
      wormholeReadyState,
      anonymousModeEnabled,
      anonymousModeReady,
      privateLaneLabel,
      privateLaneDetail,
      addGateResyncAction,
      postGateMessage,
      requestGateAccess,
      openGateCard,
      cmdApps,
      cmdNews,
      cmdJets,
      cmdPlaces,
      cmdDossier,
      cmdShodan,
    ],
  );

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleWormholeReady = (event: Event) => {
      const target = (event as CustomEvent<{ target?: string }>).detail?.target || 'gates';
      if (target !== 'gates') return;
      setGateAccessGranted(true);
      setGateAccessPromptOpen(false);
      setPendingGateCommand(null);
      setSurfacePanel('gates');
      setTimeout(() => {
        void exec('gates');
        inputRef.current?.focus();
      }, 40);
    };
    window.addEventListener(WORMHOLE_READY_EVENT, handleWormholeReady as EventListener);
    return () => {
      window.removeEventListener(WORMHOLE_READY_EVENT, handleWormholeReady as EventListener);
    };
  }, [exec]);

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !busy) {
      exec(input);
      setInput('');
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (history.length > 0) {
        const next = Math.min(histIdx + 1, history.length - 1);
        setHistIdx(next);
        setInput(history[next]);
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (histIdx > 0) {
        setHistIdx(histIdx - 1);
        setInput(history[histIdx - 1]);
      } else {
        setHistIdx(-1);
        setInput('');
      }
    }
  };

  const runQuickCommand = useCallback(
    (command: string) => {
      if (busy) return;
      setInput('');
      void exec(command);
    },
    [busy, exec],
  );

  useEffect(() => {
    runQuickCommandRef.current = runQuickCommand;
  }, [runQuickCommand]);

  const openSurface = useCallback(
    (panel: (typeof QUICK_LAUNCHES)[number]['panel']) => {
      if (panel === 'gates' && !gateAccessGranted) {
        requestGateAccess('gates');
        return;
      }
      setSurfacePanel(panel);
    },
    [gateAccessGranted, requestGateAccess],
  );

  const chipTone = (tone: (typeof QUICK_LAUNCHES)[number]['tone']) => {
    switch (tone) {
      case 'green':
        return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:border-emerald-400/70 hover:bg-emerald-500/15';
      case 'pink':
        return 'border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300 hover:border-fuchsia-400/70 hover:bg-fuchsia-500/15';
      case 'yellow':
        return 'border-amber-400/40 bg-amber-400/10 text-amber-200 hover:border-amber-300/70 hover:bg-amber-400/15';
      default:
        return 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:border-cyan-400/70 hover:bg-cyan-500/15';
    }
  };

  const lineColor = (type: TermLine['type']) => {
    switch (type) {
      case 'input':
        return 'text-cyan-200';
      case 'output':
        return 'text-slate-200';
      case 'error':
        return 'text-rose-300';
      case 'system':
        return 'text-cyan-300/85';
      case 'header':
        return 'text-amber-200 font-semibold tracking-[0.18em]';
      case 'dim':
        return 'text-slate-500';
    }
  };

  const renderStyledLine = (line: TermLine, index: number) => {
    const tokenClasses: Array<{ pattern: RegExp; className: string }> = [
      { pattern: /\b(MESHTASTIC|MESH|RADIO)\b/gi, className: 'text-emerald-300' },
      { pattern: /\b(GATES?|COMMONS|INBOX|DM|DEAD DROP)\b/gi, className: 'text-fuchsia-300' },
      { pattern: /\b(MARKETS?|ORACLE|COMMANDS?|OPS|DOSSIER|PREDICT)\b/gi, className: 'text-amber-200' },
      { pattern: /\b(INFONET|SHODAN|STATUS|SIGNALS?)\b/gi, className: 'text-cyan-300' },
      { pattern: /\b(LOCKED|READ ONLY|FAILED|ERROR|DENIED)\b/gi, className: 'text-rose-300' },
      { pattern: /\b(READY|ACTIVE|OPEN|UNLOCK|YES)\b/gi, className: 'text-emerald-300' },
    ];

    const segments: Array<{ text: string; className?: string }> = [{ text: line.text }];
    for (const token of tokenClasses) {
      const nextSegments: Array<{ text: string; className?: string }> = [];
      for (const segment of segments) {
        if (segment.className) {
          nextSegments.push(segment);
          continue;
        }
        let lastIndex = 0;
        const regex = new RegExp(token.pattern.source, token.pattern.flags);
        let match: RegExpExecArray | null;
        while ((match = regex.exec(segment.text)) !== null) {
          if (match.index > lastIndex) {
            nextSegments.push({ text: segment.text.slice(lastIndex, match.index) });
          }
          nextSegments.push({ text: match[0], className: token.className });
          lastIndex = match.index + match[0].length;
        }
        if (lastIndex < segment.text.length) {
          nextSegments.push({ text: segment.text.slice(lastIndex) });
        }
      }
      segments.splice(0, segments.length, ...nextSegments);
    }

    const lineChrome =
      line.type === 'header'
        ? 'border-l-2 border-amber-300/35 pl-3 bg-amber-400/[0.03]'
        : line.type === 'error'
          ? 'border-l-2 border-rose-400/35 pl-3 bg-rose-400/[0.03]'
          : line.type === 'system'
            ? 'border-l border-cyan-400/20 pl-3'
            : line.type === 'input'
              ? 'border-l border-cyan-400/18 pl-3'
              : 'pl-3';

    const content = (
      <>
        {segments.map((segment, segmentIndex) => (
          <span key={`${index}-${segmentIndex}`} className={segment.className}>
            {segment.text || '\u00A0'}
          </span>
        ))}
      </>
    );

    if (line.actionCommand) {
      return (
        <button
          key={index}
          type="button"
          onClick={() => runQuickCommand(line.actionCommand!)}
          className={`group flex w-full items-center justify-between gap-3 text-[12px] leading-[1.8] whitespace-pre-wrap break-all border border-fuchsia-500/15 bg-fuchsia-500/[0.03] pr-3 text-left font-mono transition-all hover:border-fuchsia-400/35 hover:bg-fuchsia-500/[0.08] ${lineColor(line.type)} ${lineChrome}`}
        >
          <span className="min-w-0 flex-1">{content}</span>
          <span className="shrink-0 border border-fuchsia-500/25 px-2 py-0.5 text-[13px] tracking-[0.18em] text-fuchsia-200 transition-colors group-hover:border-fuchsia-400/45 group-hover:text-fuchsia-100">
            {line.actionLabel || 'OPEN'}
          </span>
        </button>
      );
    }

    return (
      <div
        key={index}
        className={`text-[12px] leading-[1.8] whitespace-pre-wrap break-all font-mono ${lineColor(line.type)} ${lineChrome}`}
      >
        {content}
      </div>
    );
  };

  const renderSurfacePanel = () => {
    const cardBase =
      'border bg-black/55 px-4 py-3 text-left font-mono transition-all hover:-translate-y-0.5';

    switch (surfacePanel) {
      case 'help':
        return (
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['MESH / RADIO', 'Public mesh root watch, signals, and LongFast send.', 'mesh', 'border-emerald-500/25 text-emerald-300', 'help mesh'],
              ['GATES (EXPERIMENTAL ENCRYPTION)', 'Open gate details, unlock a gate face, and post into the commons.', 'gates', 'border-fuchsia-500/25 text-fuchsia-300', 'help gates'],
              ['PRIVATE DM INBOX', 'Contacts, inbox previews, and private message flows.', 'inbox', 'border-cyan-500/25 text-cyan-300', 'help inbox'],
              ['MARKETS / ORACLE', 'Prediction markets, oracle profiles, and stakes.', 'markets', 'border-amber-400/25 text-amber-200', 'help markets'],
              ['INFONET', 'Messages, ledger, sync, and event views.', 'gates', 'border-cyan-500/25 text-cyan-300', 'help infonet'],
              ['OPS / DOSSIER', 'News, dossiers, Shodan, places, and aircraft.', 'apps', 'border-amber-400/25 text-amber-200', 'help ops'],
            ].map(([title, desc, _panel, tone, command]) => (
              <button
                key={title}
                type="button"
                onClick={() => runQuickCommand(String(command))}
                className={`${cardBase} ${tone}`}
              >
                <div className="text-sm tracking-[0.24em]">{title}</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc}</div>
                <div className="mt-3 text-[12px] tracking-[0.16em] text-slate-500">
                  {String(command)}
                </div>
              </button>
            ))}
          </div>
        );
      case 'apps':
        return (
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['MARKETS', 'Browse prediction markets', () => runQuickCommand('markets'), 'border-amber-400/25 text-amber-200'],
              ['DOSSIER PRESETS', 'Open guided dossier presets', () => openSurface('dossier'), 'border-fuchsia-500/25 text-fuchsia-300'],
              ['NEWS', 'Pull latest headlines', () => runQuickCommand('news'), 'border-cyan-500/25 text-cyan-300'],
              ['SHODAN', 'Search exposed hosts and services', () => runQuickCommand('shodan'), 'border-cyan-500/25 text-cyan-300'],
              ['MESH RADIO', 'Open the public mesh command lane', () => openSurface('mesh'), 'border-emerald-500/25 text-emerald-300'],
              ['PRIVATE DM INBOX', 'Check the experimental private dead drop', () => openSurface('inbox'), 'border-fuchsia-500/25 text-fuchsia-300'],
            ].map(([title, desc, action, tone]) => (
              <button key={title as string} type="button" onClick={action as () => void} className={`${cardBase} ${tone}`}>
                <div className="text-sm tracking-[0.24em]">{title as string}</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc as string}</div>
              </button>
            ))}
          </div>
        );
      case 'dossier':
        return (
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['PERSON', 'dossier elon musk', 'Build a quick person brief by name'],
              ['PLACE', 'dossier tel aviv', 'Summarize a place-based brief'],
              ['ORG', 'dossier spacex', 'Scan headlines, signals, and markets around an org'],
              ['JET / PLANE', 'jet musk', 'Look up operator or aircraft-linked records'],
              ['SITE', 'place ramstein', 'Check airports, bases, datacenters, power nodes'],
              ['NEWS FLASH', 'news taiwan', 'Pull a fast topical news sweep'],
            ].map(([title, command, desc]) => (
              <button
                key={title}
                type="button"
                onClick={() => runQuickCommand(String(command))}
                className={`${cardBase} border-fuchsia-500/25 text-fuchsia-300 hover:border-fuchsia-400/45 hover:bg-fuchsia-500/10`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm tracking-[0.24em]">{title}</div>
                  <div className="text-[12px] tracking-[0.16em] text-amber-200">{command}</div>
                </div>
                <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc}</div>
              </button>
            ))}
          </div>
        );
      case 'mesh':
        return (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="border border-emerald-500/20 bg-black/45 px-4 py-3 font-mono">
                <div className="text-sm tracking-[0.24em] text-emerald-300">PUBLIC MESH LANE</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-300">
                  {publicAgentReady
                    ? `Public Agent active as ${nodeIdentity?.nodeId || 'unknown'}`
                    : 'No public Agent yet. Type connect to create one for mesh posting.'}
                </div>
                <div className="mt-2 text-sm leading-5 text-emerald-200/75">
                  Meshtastic traffic is public / observable. Wormhole is not required here.
                </div>
              </div>
              <div className="border border-cyan-500/20 bg-black/45 px-4 py-3 font-mono">
                <div className="text-sm tracking-[0.24em] text-cyan-300">WORMHOLE OBFUSCATED LANE</div>
                <div className="mt-2 text-[11px] leading-6 text-slate-300">
                  {privateLaneLabel}
                </div>
                <div className="mt-2 text-sm leading-5 text-cyan-200/75">
                  {privateLaneDetail}
                </div>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {[
                !publicAgentReady
                  ? ['CONNECT', 'Create a public Agent identity for mesh posting', () => runQuickCommand('connect')]
                  : null,
                ['LISTEN', `Watch ${meshRegion} public mesh traffic`, () => runQuickCommand('mesh listen 12')],
                ['CHANNELS', 'See regional activity counts', () => runQuickCommand('mesh channels')],
                ['SIGNALS', 'Open the wider intercept board', () => runQuickCommand('signals 12')],
              ]
                .filter((x): x is [string, string, () => void] => x !== null)
                .map(([title, desc, action]) => (
                <button
                  key={title}
                  type="button"
                  onClick={action}
                  className={`${cardBase} border-emerald-500/25 text-emerald-300`}
                >
                  <div className="text-sm tracking-[0.24em]">{title}</div>
                  <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc}</div>
                </button>
              ))}
            </div>
            <div className="text-sm tracking-[0.26em] text-emerald-300">MESH ROOT CARDS</div>
            {surfaceMeshLoading ? (
              <div className="border border-emerald-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Loading mesh channels...
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-4">
                {Object.entries(surfaceMeshCounts)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 8)
                  .map(([region, count]) => (
                    <div
                      key={region}
                      className={`border px-4 py-3 font-mono transition-all hover:-translate-y-0.5 ${
                        region === meshRegion
                          ? 'border-emerald-400/45 bg-emerald-500/10'
                          : 'border-emerald-500/20 bg-black/50 hover:border-emerald-400/35 hover:bg-emerald-500/6'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="text-[11px] tracking-[0.22em] text-emerald-200">{region}</div>
                        <div className="text-sm text-emerald-300">{count}</div>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            setMeshRegion(region);
                            runQuickCommand(`mesh listen 12`);
                          }}
                          className="border border-emerald-500/20 bg-emerald-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-emerald-300 hover:bg-emerald-500/14"
                        >
                          LISTEN
                        </button>
                        <button
                          type="button"
                          onClick={() => setMeshRegion(region)}
                          className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                        >
                          SELECT
                        </button>
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
        );
      case 'markets':
        return (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-3">
              {[
                ['ALL MARKETS', 'Open the current market board', () => runQuickCommand('markets')],
                ['TAIWAN', 'Search Taiwan-linked markets', () => runQuickCommand('markets taiwan')],
                ['BITCOIN', 'Search BTC-linked markets', () => runQuickCommand('markets bitcoin')],
              ].map(([title, desc, action]) => (
                <button
                  key={title as string}
                  type="button"
                  onClick={action as () => void}
                  className={`${cardBase} border-amber-400/25 text-amber-200`}
                >
                  <div className="text-sm tracking-[0.24em]">{title as string}</div>
                  <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc as string}</div>
                </button>
              ))}
            </div>
            <div className="text-sm tracking-[0.26em] text-amber-200">LIVE MARKET CARDS</div>
            {surfaceMarketsLoading ? (
              <div className="border border-amber-400/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Loading market cards...
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-3">
                {surfaceMarkets.map((market, idx) => {
                  const title = pickRecordText(market, ['title', 'question']) || `market-${idx + 1}`;
                  const category = pickRecordText(market, ['category']) || 'market';
                  const pctValue =
                    typeof market.consensus_pct === 'number'
                      ? `${market.consensus_pct}%`
                      : typeof market.probability === 'number'
                        ? `${market.probability}%`
                        : '?%';
                  const expanded = expandedMarketIndex === idx;
                  return (
                    <div
                      key={`${title}-${idx}`}
                      className="border border-amber-400/20 bg-black/50 px-4 py-4 font-mono transition-all hover:-translate-y-0.5 hover:border-amber-300/45 hover:bg-amber-400/6"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="text-[11px] leading-6 text-amber-100">{title}</div>
                        <div className="border border-amber-400/20 bg-amber-400/8 px-2 py-1 text-[13px] text-amber-200">
                          {pctValue}
                        </div>
                      </div>
                      <div className="mt-2 text-[13px] tracking-[0.16em] text-slate-500">{category}</div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedMarketIndex((prev) => (prev === idx ? null : idx))
                          }
                          className="border border-amber-400/20 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                        >
                          {expanded ? 'HIDE' : 'OPEN'}
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`markets ${title}`)}
                          className="border border-amber-400/20 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                        >
                          BOARD
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`oracle ${nodeIdentity?.nodeId || ''}`.trim())}
                          className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                        >
                          PROFILE
                        </button>
                      </div>
                      {expanded && (
                        <div className="mt-4 border border-amber-400/15 bg-black/35 px-3 py-3 text-sm leading-6 text-slate-300">
                          <div className="text-[13px] tracking-[0.18em] text-amber-200">MARKET DETAIL</div>
                          <div className="mt-2">Question: {title}</div>
                          <div>Category: {category}</div>
                          <div>Consensus: {pctValue}</div>
                          <div className="mt-3 text-slate-500">
                            Use the board view to search for the exact market title, then route into prediction or oracle profile commands from the command line when you need precision.
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
      case 'inbox':
        const contactEntries = Object.entries(getContacts());
        return (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-3">
              {[
                ['CHECK INBOX', 'Pull pending experimental obfuscated DM messages', () => runQuickCommand('inbox')],
                ['CONTACTS', 'Show saved obfuscated contacts', () => runQuickCommand('contacts')],
                ['START DM', 'Begin an encrypted obfuscated message flow', () => runQuickCommand('dm')],
              ].map(([title, desc, action]) => (
                <button
                  key={title as string}
                  type="button"
                  onClick={action as () => void}
                  className={`${cardBase} border-cyan-500/25 text-cyan-300`}
                >
                  <div className="text-sm tracking-[0.24em]">{title as string}</div>
                  <div className="mt-2 text-[11px] leading-6 text-slate-400">{desc as string}</div>
                </button>
              ))}
            </div>
            <div className="text-sm tracking-[0.26em] text-cyan-300">EXPERIMENTAL PRIVATE DM INBOX</div>
            {surfaceInboxLoading ? (
              <div className="border border-cyan-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Checking inbox...
              </div>
            ) : surfaceInbox.length === 0 ? (
              <div className="border border-cyan-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                No inbox previews available.
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {surfaceInbox.map((message, idx) => (
                  <div
                    key={`${message.sender}-${idx}`}
                    className="border border-cyan-500/20 bg-black/50 px-4 py-4 font-mono transition-all hover:-translate-y-0.5 hover:border-cyan-400/35 hover:bg-cyan-500/6"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[11px] tracking-[0.18em] text-cyan-200">{message.sender}</div>
                      <div className="text-[13px] text-slate-500">{message.age}</div>
                    </div>
                    <div className="mt-3 text-[11px] leading-6 text-slate-300">
                      {message.text}
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => runQuickCommand('inbox')}
                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                      >
                        OPEN
                      </button>
                      <button
                        type="button"
                        onClick={() => runQuickCommand(`dm ${message.sender}`)}
                        className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-fuchsia-300 hover:bg-fuchsia-500/14"
                      >
                        REPLY
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="text-sm tracking-[0.26em] text-fuchsia-300">CONTACT CARDS</div>
            {contactEntries.length === 0 ? (
              <div className="border border-fuchsia-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                No saved contacts yet.
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {contactEntries.slice(0, 6).map(([contactId, contact]) => (
                  <div
                    key={contactId}
                    className="border border-fuchsia-500/20 bg-black/50 px-4 py-4 font-mono transition-all hover:-translate-y-0.5 hover:border-fuchsia-400/35 hover:bg-fuchsia-500/6"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[11px] tracking-[0.18em] text-fuchsia-200">
                        {contact.alias || contactId}
                      </div>
                      <div className="text-[13px] text-slate-500">
                        {contact.blocked ? 'BLOCKED' : 'ACTIVE'}
                      </div>
                    </div>
                    {contact.alias && (
                      <div className="mt-1 text-[13px] tracking-[0.14em] text-slate-500">{contactId}</div>
                    )}
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => runQuickCommand(`dm ${contactId}`)}
                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                      >
                        MESSAGE
                      </button>
                      <button
                        type="button"
                        onClick={() => runQuickCommand(contact.blocked ? `dm unblock ${contactId}` : `dm block ${contactId}`)}
                        className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-fuchsia-300 hover:bg-fuchsia-500/14"
                      >
                        {contact.blocked ? 'UNBLOCK' : 'BLOCK'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      case 'gates':
        return (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-sm tracking-[0.28em] text-fuchsia-300">
                GATES (EXPERIMENTAL ENCRYPTION)
              </div>
              <button
                type="button"
                onClick={() => runQuickCommand('gates')}
                className="border border-fuchsia-500/25 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] font-mono tracking-[0.22em] text-fuchsia-200 hover:bg-fuchsia-500/14"
              >
                OPEN GATE LOG
              </button>
            </div>
            {gateCatalogLoading ? (
              <div className="border border-fuchsia-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                Loading gate catalog...
              </div>
            ) : gateCatalog.length === 0 ? (
              <div className="border border-fuchsia-500/20 bg-black/45 px-4 py-5 text-[11px] font-mono text-slate-400">
                No launch gates available.
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {gateCatalog.map((gate) => {
                  const minRep = gate.rules?.min_overall_rep;
                  const expanded = expandedGateId === gate.gate_id;
                  return (
                    <div
                      key={gate.gate_id}
                      className="border border-fuchsia-500/20 bg-black/50 px-4 py-4 font-mono shadow-[inset_0_0_0_1px_rgba(217,70,239,0.04)] transition-all hover:-translate-y-0.5 hover:border-fuchsia-400/45 hover:bg-fuchsia-500/6"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-[11px] tracking-[0.22em] text-fuchsia-200">
                            {(gate.display_name || gate.gate_id).toUpperCase()}
                          </div>
                          <div className="mt-1 text-[13px] tracking-[0.16em] text-fuchsia-300/75">
                            {gate.gate_id}
                          </div>
                        </div>
                        <div className="text-[13px] text-slate-500">
                          {typeof gate.message_count === 'number' ? `${gate.message_count} msgs` : 'catalog'}
                        </div>
                      </div>
                      <div className="mt-3 min-h-[40px] text-[11px] leading-6 text-slate-400">
                        {gate.description || 'Encrypted commons lane.'}
                      </div>
                      <div className="mt-3 flex items-center justify-between text-[13px] tracking-[0.16em]">
                        <span className="text-amber-200">{minRep ? `REQ ${minRep} REP` : 'OPEN'}</span>
                        <span className="text-cyan-300">{gate.fixed ? 'FIXED LAUNCH GATE' : 'GATE'}</span>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => openGateCard(gate.gate_id)}
                          className="border border-cyan-500/25 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                        >
                          {expanded ? 'HIDE' : 'OPEN'}
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`messages ${gate.gate_id}`)}
                          className="border border-emerald-500/25 bg-emerald-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-emerald-300 hover:bg-emerald-500/14"
                        >
                          MESSAGES
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setActiveGateComposeId(gate.gate_id);
                            setGateReplyTarget(null);
                            setSurfacePanel('gates');
                            setTimeout(() => inputRef.current?.focus(), 40);
                          }}
                          className="border border-amber-400/25 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                        >
                          POST
                        </button>
                        <button
                          type="button"
                          onClick={() => runQuickCommand(`gate mask ${gate.gate_id}`)}
                          className="border border-fuchsia-500/25 bg-fuchsia-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-fuchsia-200 hover:bg-fuchsia-500/14"
                        >
                          UNLOCK
                        </button>
                      </div>
                      {expandedGateLoading === gate.gate_id && (
                        <div className="mt-4 border border-fuchsia-500/15 bg-black/35 px-3 py-3 text-sm text-slate-400">
                          Loading gate detail...
                        </div>
                      )}
                      {expanded && expandedGateDetail && (
                        <div className="mt-4 space-y-3 border border-fuchsia-500/15 bg-black/40 px-4 py-4">
                          <div className="grid gap-3 md:grid-cols-2">
                            <div>
                              <div className="text-[13px] tracking-[0.18em] text-fuchsia-300">WELCOME</div>
                              <div className="mt-2 text-[11px] leading-6 text-slate-400">
                                {expandedGateDetail.welcome || expandedGateDetail.description || 'Encrypted commons lane.'}
                              </div>
                            </div>
                            <div className="space-y-2 text-sm">
                              <div className="flex items-center justify-between">
                                <span className="text-slate-500">Creator</span>
                                <span className="text-cyan-300">{expandedGateDetail.creator_node_id || 'unknown'}</span>
                              </div>
                              <div className="flex items-center justify-between">
                                <span className="text-slate-500">Messages</span>
                                <span className="text-cyan-300">{expandedGateDetail.message_count || 0}</span>
                              </div>
                              {expandedGateKey && (
                                <>
                                  <div className="flex items-center justify-between">
                                    <span className="text-slate-500">Epoch</span>
                                    <span className="text-fuchsia-200">{String(expandedGateKey.current_epoch || 0)}</span>
                                  </div>
                                  <div className="flex items-center justify-between">
                                    <span className="text-slate-500">Access</span>
                                    <span className="text-emerald-300">
                                      {expandedGateKey.has_local_access
                                        ? String(expandedGateKey.identity_scope || 'member')
                                        : 'locked'}
                                    </span>
                                  </div>
                                </>
                              )}
                            </div>
                          </div>
                          {expandedGateMessages.length > 0 && (
                            <div>
                              <div className="text-[13px] tracking-[0.18em] text-fuchsia-300">THREAD SNAPSHOT</div>
                              <div className="mt-3 grid gap-3">
                                {expandedGateMessages.map((message, messageIndex) => (
                                  <div
                                    key={`${message.nodeId}-${messageIndex}`}
                                    className="border border-cyan-500/15 bg-black/35 px-3 py-3 text-left transition-all hover:border-cyan-400/30 hover:bg-cyan-500/6"
                                  >
                                    <div className="flex items-center justify-between gap-3">
                                      <div className="text-sm tracking-[0.16em] text-cyan-200">{message.nodeId}</div>
                                      <div className="text-[13px] text-slate-500">{message.age}</div>
                                    </div>
                                    <div className="mt-2 text-[11px] leading-6 text-slate-300">{message.text}</div>
                                    {message.encrypted && (
                                      <div className="mt-2 text-[13px] tracking-[0.16em] text-fuchsia-300">
                                        EXPERIMENTAL ENCRYPTION
                                      </div>
                                    )}
                                    <div className="mt-3 flex flex-wrap gap-2">
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`messages ${gate.gate_id}`)}
                                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                                      >
                                        THREAD
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => {
                                          setActiveGateComposeId(gate.gate_id);
                                          setGateReplyTarget(message.nodeId);
                                          setTimeout(() => inputRef.current?.focus(), 40);
                                        }}
                                        className="border border-amber-400/20 bg-amber-400/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-amber-200 hover:bg-amber-400/14"
                                      >
                                        REPLY
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`rep ${message.nodeId}`)}
                                        className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.18em] text-cyan-300 hover:bg-cyan-500/14"
                                      >
                                        REP
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`vote ${message.nodeId} up ${gate.gate_id}`)}
                                        className={`border px-3 py-1.5 text-[13px] tracking-[0.18em] transition-colors ${
                                          voteDirections[voteScopeKey(message.nodeId, gate.gate_id)] === 1
                                            ? 'border-emerald-400/35 bg-emerald-500/16 text-emerald-100'
                                            : 'border-emerald-500/20 bg-emerald-500/8 text-emerald-300 hover:bg-emerald-500/14'
                                        }`}
                                      >
                                        UP
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => runQuickCommand(`vote ${message.nodeId} down ${gate.gate_id}`)}
                                        className={`border px-3 py-1.5 text-[13px] tracking-[0.18em] transition-colors ${
                                          voteDirections[voteScopeKey(message.nodeId, gate.gate_id)] === -1
                                            ? 'border-rose-400/35 bg-rose-500/16 text-rose-100'
                                            : 'border-rose-500/20 bg-rose-500/8 text-rose-300 hover:bg-rose-500/14'
                                        }`}
                                      >
                                        DOWN
                                      </button>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      default:
        return null;
    }
  };

  const confirmGateAccess = useCallback(() => {
    if (!wormholeSecureRequired || !wormholeReadyState) {
      routeToWormholeSetup();
      return;
    }
    if (typeof window !== 'undefined') {
      try {
        sessionStorage.removeItem(WORMHOLE_RETURN_KEY);
      } catch {
        /* ignore */
      }
    }
    setGateAccessGranted(true);
    setGateAccessPromptOpen(false);
    const nextCommand = pendingGateCommand;
    setPendingGateCommand(null);
    setSurfacePanel('gates');
    if (nextCommand && nextCommand !== 'gates') {
      setTimeout(() => runQuickCommand(nextCommand), 40);
    } else {
      setTimeout(() => runQuickCommand('gates'), 40);
    }
  }, [
    pendingGateCommand,
    routeToWormholeSetup,
    runQuickCommand,
    wormholeReadyState,
    wormholeSecureRequired,
  ]);

  const confirmPrivateLanePrompt = useCallback(() => {
    void activatePrivateLane('gates');
  }, [activatePrivateLane]);

  const dismissPrivateLanePrompt = useCallback(() => {
    setPrivateLanePromptOpen(false);
    setPrivateLanePromptStatus(null);
    addSystem('  Staying on the public lane for now.');
    addLines([
      {
        text: "  Mesh stays public. Type 'gates' or tap ENTER WORMHOLE later when you want the obfuscated commons.",
        type: 'dim',
      },
    ]);
  }, [addLines, addSystem]);

  const denyGateAccess = useCallback(() => {
    setGateAccessPromptOpen(false);
    setPendingGateCommand(null);
    setSurfacePanel('home');
    if (typeof window !== 'undefined') {
      try {
        sessionStorage.removeItem(WORMHOLE_RETURN_KEY);
      } catch {
        /* ignore */
      }
    }
    addSystem('  Gate access denied. Infonet Commons gates remain restricted.');
  }, [addSystem]);

  // Position + size style
  const sizeStyle: React.CSSProperties = {
    width: size.w,
    height: size.h,
    maxWidth: 'calc(100vw - 4rem)',
    maxHeight: 'calc(100vh - 4rem)',
  };
  const absoluteStyle: React.CSSProperties = {
    position: 'fixed',
    top: pos.y,
    left: pos.x,
    ...sizeStyle,
  };

  return <MeshTerminalView p={{ Activate, AnimatePresence, Backend, Bootstrap, Commons, Enter, Experimental, Gates, GripHorizontal, If, Infonet, Last, Minimize, Minus, No, Obfuscated, Participant, Public, Terminal, Turn, What, Wormhole, Yes, _18, _1px, _26px, absolute, absoluteStyle, accept, active, activeGateComposeId, agent, alignItems, all, allowed, already, amber, an, and, animate, auto, autoComplete, backdrop, backend, background, behind, between, bg, black, blink_1s_step, block, blur, bold, bootstrap, bootstrap_peer_count, bootstrapped, border, bottom, broadcast, build, busy, button, callsign, caret, catch, center, centered, chain, chipTone, circle_at_50, circle_at_top, clear, click, col, colors, cols, command, commons, comms, communicate, configured, confirmGateAccess, confirmPrivateLanePrompt, const, contents, current, cursor, cyan, damping, deck, decline, denyGateAccess, dest, detected, dismissPrivateLanePrompt, display, div, dmStep, does, dossiers, emerald, encrypted, encryption, end_infinite, enter, err, events, exist, exists, exit, experimental, fixed, flex, focus, font, for, formatNodeTime, fuchsia, full, gap, gateAccessPromptOpen, gateReplyTarget, gates, getSelection, gradient, grid, gt, handleKey, hasSovereignty, head_hash, hidden, hosting, hover, identity, if, ignore, image, in, inbox, infonetNodeStatus, infonetNodeStatusError, initial, inline, input, inputRef, inset, inset_0_0_0_1px_rgba, intel, into, is, isCollapsed, isOpen, it, items, justify, justifyContent, known_nodes, lane, last_peer_url, launch, leading, left, length, lg, linear, lines, live, map, markets, max, mb, md, mesh, message, min, minimized, mono, motion, move, msg, mt, mx, ne, next, next_sync_due_at, node, nodeBootstrapLabel, nodeId, nodeIdentity, nodeModeLabel, nodeSyncLabel, nodes, none, not, now, nw, obfuscated, observable, off, ok, on, onClose, onDragStart, onResizeStart, onSettingsClick, once, one, only, openPrivateLanePrompt, openSurface, operator, or, outline, output, over, overflow, panel, participant, peer, pointer, pointerEvents, policy, position, post, prediction, private, privateLaneLabel, privateLanePromptBusy, privateLanePromptMode, privateLanePromptOpen, privateLanePromptStatus, provisions, public, push, push_peer_count, px, py, radial, read, relative, renderStyledLine, renderSurfacePanel, reply, require, resize, return, reused, rgba, right, rose, rounded, routing, runQuickCommand, sb_a3f2c891, scale, scrollRef, scrollbar, se, security, seed, select, semibold, sendStep, sends, separate, sessionStorage, setCentered, setInput, setItem, setMinimized, shadow, shortNodeHash, shrink, size, sizeStyle, slate, slice, sm, sovereigntyPending, space, span, spellCheck, spring, stay, stays, stiffness, straight, stronger, styled, summarizeNodePeer, sw, sync, sync_peer_count, sync_runtime, syncs, takes, target, terminal, terminalWriteLockReason, testnet, text, the, then, this, through, to, tone, top, total_events, tracking, transition, translate, transparent, transparent_18, transparent_1px, transparent_28, try, turns, typeof, under, use, void, white, windowRef, wipe, wormhole, wormholeReadyState, wormholeSecureRequired, wrap, xl, yet, you, your, zIndex }} />;
}
