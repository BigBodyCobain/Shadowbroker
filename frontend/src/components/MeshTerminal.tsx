'use client';

import { MeshTerminalView } from './MeshTerminalView';
import { useMeshTerminalIntelCommands } from './MeshTerminalIntelCommands';
import { useMeshTerminalStatusCommands } from './MeshTerminalStatusCommands';
import { useMeshTerminalCmdStatus } from './MeshTerminalCmdStatus';
import { useMeshTerminalInfonetCommand } from './MeshTerminalInfonetCommand';
import { useMeshTerminalInfonetCommands } from './MeshTerminalInfonetCommands';
import { useMeshTerminalSendFlow } from './MeshTerminalSendFlow';
import { useMeshTerminalGateCommand } from './MeshTerminalGateCommand';
import { useMeshTerminalDmCommand } from './MeshTerminalDmCommand';
import { useMeshTerminalVoteCommand } from './MeshTerminalVoteCommand';
import { useMeshTerminalSayCommand } from './MeshTerminalSayCommand';
import { useMeshTerminalInboxCommand } from './MeshTerminalInboxCommand';
import { useMeshTerminalPanels } from './MeshTerminalPanels';
import { useMeshTerminalMarketsCommand } from './MeshTerminalMarketsCommand';
import { useMeshTerminalInboxPolling } from './useMeshTerminalInboxPolling';
import { useMeshTerminalBoot } from './useMeshTerminalBoot';
import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
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
  type NodeIdentity } from '@/mesh/meshIdentity';
import { ratchetEncryptDM, ratchetDecryptDM } from '@/mesh/meshDmWorkerClient';
import {
  buildMailboxClaims,
  countDmMailboxes,
  ensureRegisteredDmKey,
  fetchDmPublicKey,
  pollDmMailboxes,
  sendDmMessage,
  sharedMailboxToken } from '@/mesh/meshDmClient';
import { PROTOCOL_VERSION, buildSignaturePayload } from '@/mesh/meshProtocol';
import { validateEventPayload } from '@/mesh/meshSchema';
import { verifyMerkleProof } from '@/mesh/meshMerkle';
import { API_BASE } from '@/lib/api';
import { classifyTick, jitteredPollDelay, MAX_CATCHUP_POLLS } from '@/lib/dmPollScheduler';
import { getPrivacyStrictPreference } from '@/lib/privacyBrowserStorage';
import { getDesktopNativeControlAuditReport } from '@/lib/desktopBridge';
import {
  describeNativeControlError,
  extractNativeGateResyncTarget } from '@/lib/desktopControlContract';
import {
  getSensitiveBrowserItem,
  setSensitiveBrowserItem } from '@/lib/privacyBrowserStorage';
import {
  fetchInfonetNodeStatusSnapshot,
  type InfonetNodeStatusSnapshot } from '@/mesh/controlPlaneStatusClient';
import { fetchWormholeStatus, runWormholeDmSelftest } from '@/mesh/wormholeIdentityClient';
import {
  formatLegacyCompatibilitySeenAt,
  summarizeLegacyCompatibility } from '@/mesh/wormholeCompatibility';
import {
  formatGateCompatSeenAt,
  getGateCompatTelemetrySnapshot,
  summarizeGateCompatTelemetry } from '@/mesh/gateCompatTelemetry';
import {
  describeBrowserGateLocalRuntimeStatus,
  getBrowserGateLocalRuntimeStatus } from '@/mesh/meshGateWorkerClient';
import {
  fetchGateCatalogSnapshot,
  fetchGateDetailSnapshot,
  invalidateGateCatalogSnapshot,
  invalidateGateDetailSnapshot } from '@/mesh/gateCatalogSnapshot';
import { fetchGateMessageSnapshot } from '@/mesh/gateMessageSnapshot';
import {
  describeGateMessagePreview,
  fetchGateThreadPreviewSnapshot,
  invalidateGateThreadPreviewSnapshot } from '@/mesh/gatePreviewSnapshot';
import {
  clearWormholeGatePersona,
  createWormholeGatePersona,
  fetchWormholeGateKeyStatus,
  postWormholeGateMessage,
  prepareWormholeInteractiveLane,
  resyncWormholeGateState,
  rotateWormholeGateKey } from '@/mesh/wormholeIdentityClient';
import { fetchWormholeSettings } from '@/mesh/wormholeClient';
import {
  getMeshTerminalWriteLockReason,
  isMeshTerminalWriteCommand } from '@/lib/meshTerminalPolicy';
import {
  gateEnvelopeState,
  isEncryptedGateEnvelope } from '@/mesh/gateEnvelope';

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
  SearchRecord } from './MeshTerminal.shared';
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
  formatLatLng } from './MeshTerminal.shared';

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
        hasDescriptor: Boolean(getWormholeIdentityDescriptor()?.nodeId) };
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
        hasDescriptor: Boolean(getWormholeIdentityDescriptor()?.nodeId) };
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
    setSurfaceInbox, setSurfaceInboxLoading });
  const publicAgentReady = Boolean(nodeIdentity) && hasSovereignty();
  const privateLaneLabel = wormholeSecureRequired
    ? wormholeReadyState
      ? 'EXPERIMENTAL / OBFUSCATED'
      : 'LOCKED'
    : 'OFF / PUBLIC ONLY';
  const privateLaneDetail = wormholeSecureRequired
    ? wormholeReadyState
      ? 'Wormhole is live for encrypted gates and the obfuscated inbox.'
      : 'Wormhole is required for gates and obfuscated  but it is not ready yet.'
    : 'Wormhole is off. Public mesh still works; obfuscated gates and inbox stay locked.';
  const nodeModeLabel = formatNodeMode(infonetNodeStatus?.node_mode);
  const nodeBootstrapLabel = describeBootstrapState(infonetNodeStatus);
  const nodeSyncLabel = describeSyncOutcome(infonetNodeStatus);
  const terminalWriteLockReason = getMeshTerminalWriteLockReason({
    wormholeRequired: wormholeSecureRequired,
    wormholeReady: wormholeReadyState,
    anonymousMode: anonymousModeEnabled,
    anonymousModeReady: anonymousModeReady,
  });

  // Re-focus input when command finishes (busy → false)
  useEffect(() => {
    if (!busy && isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [busy, isOpen]);

  // Auto-run status on first open
  useMeshTerminalBoot({
    isOpen, hasBooted, setHasBooted, setLines, setInfonetNodeStatus, setInfonetNodeStatusError, setSovereigntyPending });

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
        origY: centered ? windowRef.current?.getBoundingClientRect().top || 0 : pos.y };

      const onMove = (ev: MouseEvent) => {
        if (!dragRef.current) return;
        setPos({
          x: dragRef.current.origX + (ev.clientX - dragRef.current.startX),
          y: dragRef.current.origY + (ev.clientY - dragRef.current.startY) });
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
        edge };
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
          actionLabel: 'RESYNC' },
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
    fetchInfonetNodeStatusSnapshot, setInfonetNodeStatus, setInfonetNodeStatusError, buildNodeRuntimeLines });

  const { cmdApps, cmdNews, cmdJets, cmdPlaces, cmdDossier, cmdShodan } = useMeshTerminalIntelCommands({
    addError, addLines, addOutput, addSystem });

  const { cmdMerkle, cmdSync, cmdRevoke, cmdRotate } = useMeshTerminalInfonetCommands({
    addError, addLines, addOutput, addSystem, nodeIdentity, setNodeIdentity,
    getInfonetLocator, getInfonetPeers, getPrivacyStrictPreference, setInfonetHead } as any);

  const { cmdNode, cmdSignals, cmdLog, cmdNearest } = useMeshTerminalStatusCommands({
    addError, addLines, addOutput, addSystem, setInfonetNodeStatus, setInfonetNodeStatusError, fetchInfonetNodeStatusSnapshot, shortNodeHash, buildNodeRuntimeLines });

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
              : detail
          );
        }
        if (!data?.ok) {
          const detail = String(data?.detail || 'Failed to post to gate');
          throw new Error(
            detail === 'gate_compat_fallback_consent_required' || detail.startsWith('gate_local_runtime_required:')
              ? 'Browser-local gate runtime is unavailable. Open the room view to resync local gate state or use native desktop.'
              : detail
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
        text: 'Turning on Wormhole and preparing the obfuscated lane...' });
      try {
        const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
        let runtime = await refreshPrivateLaneRuntime();
        setWormholeSecureRequired(Boolean(prepared.settingsEnabled || runtime.secureRequired));
        setWormholeReadyState(Boolean(runtime.ready || prepared.ready));

        setPrivateLanePromptStatus({
          type: 'dim',
          text: 'Provisioning obfuscated identity and opening the Infonet Commons...' });
        const identity = prepared.identity;
        if (!identity) {
          throw new Error('Wormhole is still warming up in the background.');
        }
        setGateAccessGranted(true);
        setPrivateLanePromptStatus({
          type: 'ok',
          text: `Wormhole ready as ${identity.node_id}.` });
        setPrivateLanePromptOpen(false);
        setGateAccessPromptOpen(false);
        setPendingGateCommand(null);
        addSystem(`  Wormhole obfuscated lane ready as ${identity.node_id}.`);
        addLines([
          {
            text: '  Participant-node sync stays on the backend lane. Wormhole now unlocks gates and the obfuscated commons.',
            type: 'dim' },
        ]);

        const commandToRun = nextCommand && nextCommand.trim() ? nextCommand : 'gates';
        const targetPanel = commandToRun === 'inbox' ? 'inbox' : 'gates';
        setSurfacePanel(targetPanel);
        window.setTimeout(() => runQuickCommandRef.current(commandToRun), 40);
      } catch (err) {
        const detail = describeNativeControlError(err) || (err instanceof Error ? err.message : '');
        setPrivateLanePromptStatus({
          type: 'err',
          text: detail || 'Failed to enter Wormhole.' });
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
                    type: 'dim' },
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
                      actionLabel: 'ENTER' },
                  ]);
                  if (g.description) {
                    addLines([{ text: `      ${g.description}`, type: 'dim' }]);
                  }
                }
                addLines([
                  {
                    text: '  Fixed launch catalog only. Gate creation is disabled in this testnet build.',
                    type: 'dim' },
                ]);
              }
              addSystem('');
            } catch {
              addError('Failed to fetch gates');
            }
            return;
  };

  const { handleGateCommand } = useMeshTerminalGateCommand({
    addError, addLines, addOutput, addSystem,
    gateAccessGranted, requestGateAccess,
    wormholeSecureRequired, wormholeReadyState,
    setWormholeSecureRequired, setWormholeReadyState,
    anonymousModeEnabled, anonymousModeReady,
    addGateResyncAction,
  });

  const { handleMarketsCommand } = useMeshTerminalMarketsCommand({
    addError, addLines, addOutput, addSystem, nodeIdentity, hasSovereignty, asSearchRecords });

  const { handleInfonetCommand } = useMeshTerminalInfonetCommand({ addError, addLines, addOutput, addSystem, nodeIdentity });

  const {
    handleInboxCommand,
    handleSendCommand,
    handleWhoamiCommand,
    handleConnectCommand,
    handleRepCommand,
    handleMyrepCommand,
    handleThresholdCommand,
    doSend,
    doMeshSend,
    startInteractiveSend,
    doDMSend,
  } = useMeshTerminalInboxCommand({
    addError, addLines, addOutput, addSystem,
    nodeIdentity, setSovereigntyPending, setBusy,
    privateLaneLabel, privateLaneDetail, onDmCount, setSendStep,
  });

  const { handleDmCommand } = useMeshTerminalDmCommand({
    addError, addLines, addOutput, addSystem, nodeIdentity,
    doDMSend, onDmCount, setDmDest, setDmStep,
  });

  const { handleVoteCommand } = useMeshTerminalVoteCommand({addError,addSystem,addOutput,addLines,nodeIdentity,hasSovereignty});
  const { handleSayCommand } = useMeshTerminalSayCommand({addError,addSystem,addOutput,addLines,nodeIdentity,hasSovereignty,postGateMessage,invalidateGateCatalogSnapshot,invalidateGateDetailSnapshot,invalidateGateThreadPreviewSnapshot,addGateResyncAction});

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

  const handleGateChatModeInput = async (trimmed: string, gateChatMode: boolean): Promise<boolean> => {
      if (gateChatMode && activeGateComposeId) {
      addLines([
        {
          text: `  > ${gateReplyTarget ? `@${gateReplyTarget} ` : ''}${trimmed}`,
          type: 'input' },
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
          if (!addGateResyncAction( activeGateComposeId)) {
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
              type: 'dim' },
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
              await ensureRegisteredDmKey(API, nodeIdentity!, { force: true });
              addOutput('    Encrypted DM keys registered.');
            } catch {
              /* non-critical */
            }
          }
          addSystem('');
          addSystem('  You are now an agent on the Infonet.');
          addSystem("  Type 'help' for  'send' to transmit, 'dm' for private messages.");
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
        addLines([{ text: "  To activate  type 'accept' when prompted.", type: 'dim' }]);
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

      if (await handleGateChatModeInput(trimmed, gateChatMode)) return;

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
              type: 'dim' },
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
              addOutput('    help infonet   Ledger,  and message browsing');
              addOutput('    help ops       Dossiers,    aircraft');
              addSystem('');
              addLines([{ text: '  Click the HELP cards above or type one of the categories for details.', type: 'dim' }]);
              break;
            }
            const sectionLines = HELP_SECTIONS[section];
            if (!sectionLines) {
              addError(`Unknown help category '${section}'. Try:      ops`);
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
                type: 'system' },
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
            if (args.length === 0) {
              addError('Usage: mesh <message>');
            } else {
              await doMeshSend(args.join(' '), meshRegion);
            }
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
              people: 'contacts' };
            const suggestion = suggestions[cmd.toLowerCase()];
            if (suggestion) {
              addLines([{ text: `  Did you mean '${suggestion}'?`, type: 'dim' }]);
            } else {
              addLines([
                {
                  text: `  '${cmd}' is not a command. Type 'help' to see what's available.`,
                  type: 'dim' },
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

  const { renderStyledLine, renderSurfacePanel } = useMeshTerminalPanels({                                                  activatePrivateLane,   addLines, addSystem,                                                                   expandedGateDetail, expandedGateId, expandedGateKey, expandedGateLoading, expandedGateMessages, expandedMarketIndex,                 gateCatalog, gateCatalogLoading,   getContacts,                  input, inputRef,                lineColor,            meshRegion,            nodeIdentity,         openGateCard, openSurface,        pendingGateCommand,  pickRecordText,               privateLaneDetail, privateLaneLabel,    publicAgentReady,                 routeToWormholeSetup,  runQuickCommand,       setActiveGateComposeId, setExpandedMarketIndex, setGateAccessGranted, setGateAccessPromptOpen, setGateReplyTarget, setMeshRegion, setPendingGateCommand, setPrivateLanePromptOpen, setPrivateLanePromptStatus, setSurfacePanel,                    surfaceInbox, surfaceInboxLoading, surfaceMarkets, surfaceMarketsLoading, surfaceMeshCounts, surfaceMeshLoading, surfacePanel,                            voteDirections, voteScopeKey,       wormholeReadyState, wormholeSecureRequired});
  return <MeshTerminalView p={{  AnimatePresence,       GripHorizontal,     Minus,     Terminal,            activeGateComposeId,                              busy,     centered,  chipTone,                            dmStep,                  formatNodeTime,    gateAccessPromptOpen, gateReplyTarget,  getSelection,    handleKey, hasSovereignty,         infonetNodeStatus, infonetNodeStatusError,   input, inputRef,       isOpen,              lines,          minimized,  motion,         nodeBootstrapLabel,  nodeIdentity, nodeModeLabel, nodeSyncLabel,           onClose, onDragStart, onResizeStart, onSettingsClick,    openPrivateLanePrompt, openSurface,                privateLaneLabel, privateLanePromptBusy, privateLanePromptMode, privateLanePromptOpen, privateLanePromptStatus,         renderStyledLine, renderSurfacePanel,          runQuickCommand,   scrollRef,       sendStep,    setCentered, setInput,  setMinimized,  shortNodeHash,       sovereigntyPending,           summarizeNodePeer,                              windowRef,   wormholeReadyState, wormholeSecureRequired}} />;
}
