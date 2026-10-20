'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
  Github,
  Download,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  ExternalLink,
  X,
  Terminal,
  Server,
  Copy,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { useTranslation } from '@/i18n';
import { controlPlaneFetch } from '@/lib/controlPlane';
import {
  checkDesktopUpdaterUpdate,
  classifyUpdateRuntime,
  getDesktopUpdateContext,
  getPreferredManualUpdateUrl,
  getUpdateAction,
  installDesktopUpdaterUpdate,
  type GitHubLatestRelease,
  type UpdateActionKind,
} from '@/lib/updateRuntime';
import {
  requestMeshTerminalOpen,
  subscribeSecureMeshTerminalLauncherOpen,
  subscribeInfonetSessionEnd,
} from '@/lib/meshTerminalLauncher';
import { purgeBrowserContactGraph, purgeBrowserSigningMaterial, setSecureModeCached, getNodeIdentity, generateNodeKeys } from '@/mesh/meshIdentity';
import { purgeBrowserDmState } from '@/mesh/meshDmWorkerClient';
import {
  fetchInfonetNodeStatusSnapshot,
  joinInfonetSwarm,
  startTorHiddenService,
  type InfonetNodeStatusSnapshot,
} from '@/mesh/controlPlaneStatusClient';
import {
  fetchWormholeStatus,
  prepareWormholeInteractiveLane,
  isWormholePrepAbortedError,
} from '@/mesh/wormholeIdentityClient';
import { fetchWormholeSettings } from '@/mesh/wormholeClient';
import packageJson from '../../package.json';

type UpdateStatus =
  | 'idle'
  | 'checking'
  | 'available'
  | 'uptodate'
  | 'error'
  | 'confirming'
  | 'updating'
  | 'restarting'
  | 'update_error'
  | 'docker_update';

const DEFAULT_RELEASES_URL = 'https://github.com/BigBodyCobain/Shadowbroker/releases/latest';
const AUTO_UPDATE_DETAIL =
  'This runtime can use the backend-managed update path. Docker deployments will show pull instructions instead of modifying files in place.';
const DESKTOP_UPDATER_DETAIL =
  'This packaged desktop app can install the signed update in place. It will restart ShadowBroker after the installer finishes.';

function packagedUpdateDetail(ownsLocalBackend: boolean): string {
  if (ownsLocalBackend) {
    return 'This desktop installer updates the app and its bundled local backend together.';
  }
  return 'This packaged desktop app updates through a new installer download. It does not update the separately running backend service.';
}

interface TopRightControlsProps {
  onTerminalToggle?: () => void;
  onInfonetToggle?: () => void;
  dmCount?: number;
  onSettingsClick?: () => void;
  onMeshChatNavigate?: (tab: 'infonet' | 'meshtastic' | 'dms') => void;
}

export default function TopRightControls({
  onTerminalToggle,
  onInfonetToggle,
  dmCount,
  onMeshChatNavigate,
}: TopRightControlsProps = {}) {
  const { t } = useTranslation();
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus>('idle');
  const [latestVersion, setLatestVersion] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState('');
  const [manualUpdateUrl, setManualUpdateUrl] = useState(DEFAULT_RELEASES_URL);
  const [releasePageUrl, setReleasePageUrl] = useState(DEFAULT_RELEASES_URL);
  const [dockerCommands, setDockerCommands] = useState('');
  // Pre-detection initial value: the right action depends on the runtime.
  // For desktop installs (Tauri webview), the default should be
  // ``manual_download`` so that clicking Update before the async runtime
  // probe completes opens the release page in a browser instead of POSTing
  // to /api/system/update — which throws ``admin_session_required`` on
  // fresh sessions and confused v0.9.79/v0.9.8 users with a cryptic error.
  // ``window.__TAURI__`` is injected synchronously by Tauri before React
  // mounts, so this check is safe to do at useState init time.
  const initialUpdateAction: UpdateActionKind =
    typeof window !== 'undefined' && (window as { __TAURI__?: unknown }).__TAURI__
      ? 'manual_download'
      : 'auto_apply';
  const [updateAction, setUpdateAction] = useState<UpdateActionKind>(initialUpdateAction);
  const [updateDetail, setUpdateDetail] = useState(AUTO_UPDATE_DETAIL);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [launcherOpen, setLauncherOpen] = useState(false);
  const [nodeStep, setNodeStep] = useState<'prompt' | 'terms' | 'activating' | 'disable'>('prompt');
  const [activatingPhase, setActivatingPhase] = useState<'keys' | 'peers' | 'swarm' | 'sync' | 'done'>('keys');
  const activatingPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activatingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [activatingTimedOut, setActivatingTimedOut] = useState(false);
  const [nodeStatus, setNodeStatus] = useState<InfonetNodeStatusSnapshot | null>(null);
  const [nodeStatusError, setNodeStatusError] = useState('');
  const [portalReady, setPortalReady] = useState(false);
  const [nodeToggleBusy, setNodeToggleBusy] = useState(false);
  const [nodeToggleError, setNodeToggleError] = useState('');
  const [terminalLauncherOpen, setTerminalLauncherOpen] = useState(false);
  const [terminalLaunchBusy, setTerminalLaunchBusy] = useState(false);
  const [terminalLaunchError, setTerminalLaunchError] = useState('');
  const [terminalPrivateEnabled, setTerminalPrivateEnabled] = useState(false);
  const [terminalPrivateReady, setTerminalPrivateReady] = useState(false);
  const [terminalTransportTier, setTerminalTransportTier] = useState('public_degraded');

  const currentVersion = packageJson.version;
  const launchTerminalDirect = () => {
    if (onTerminalToggle) {
      onTerminalToggle();
      return;
    }
    if (onInfonetToggle) {
      onInfonetToggle();
      return;
    }
    requestMeshTerminalOpen('top-right-controls');
  };

  const openTerminalLauncher = useCallback(async () => {
    setTerminalLaunchError('');
    try {
      const [settings, status] = await Promise.all([
        fetchWormholeSettings(true).catch(() => null),
        fetchWormholeStatus().catch(() => null),
      ]);
      const enabled = Boolean(settings?.enabled ?? status?.running ?? status?.ready ?? false);
      const ready = Boolean(status?.ready);
      setTerminalPrivateEnabled(enabled);
      setTerminalPrivateReady(ready);
      setTerminalTransportTier(
        String(status?.transport_tier || status?.transport_active || 'public_degraded'),
      );
    } catch (error) {
      const message =
        typeof error === 'object' && error !== null && 'message' in error
          ? String((error as { message?: string }).message || '')
          : '';
      setTerminalPrivateEnabled(false);
      setTerminalPrivateReady(false);
      setTerminalTransportTier('public_degraded');
      setTerminalLaunchError(message || 'Private-lane status unavailable.');
    }
    setTerminalLauncherOpen(true);
  }, []);

  useEffect(() => {
    return subscribeSecureMeshTerminalLauncherOpen(() => {
      void openTerminalLauncher();
    });
  }, [openTerminalLauncher]);

  useEffect(() => {
    return subscribeInfonetSessionEnd(() => {
      setTerminalLaunchBusy(false);
      setTerminalLaunchError('');
    });
  }, []);

  const closeTerminalLauncher = () => {
    setTerminalLaunchBusy(false);
    setTerminalLauncherOpen(false);
    setTerminalLaunchError('');
  };

  const applySecureModeBoundary = async (enabled: boolean) => {
    setSecureModeCached(enabled);
    if (!enabled) return;
    purgeBrowserSigningMaterial();
    purgeBrowserContactGraph();
    await purgeBrowserDmState();
  };

  const continueTerminalLaunchInBackground = useCallback(async () => {
    try {
      const prepared = await prepareWormholeInteractiveLane({ bootstrapIdentity: true });
      const settings = await fetchWormholeSettings(true).catch(() => null);
      let runtime = await fetchWormholeStatus().catch(() => null);
      const enabled = Boolean(
        settings?.enabled ?? prepared.settingsEnabled ?? runtime?.running ?? runtime?.ready ?? false,
      );
      const identityNodeId = String(prepared.identity?.node_id || '').trim();
      await applySecureModeBoundary(enabled);

      runtime = await fetchWormholeStatus().catch(() => runtime);

      setTerminalPrivateEnabled(enabled);
      setTerminalPrivateReady(Boolean(runtime?.ready ?? prepared.ready ?? false));
      setTerminalTransportTier(
        String(
          runtime?.transport_tier ||
            runtime?.transport_active ||
            prepared.transportTier ||
            'private_control_only',
        ),
      );
      setTerminalLaunchError('');
      setSecureModeCached(enabled);
      if (identityNodeId) {
        console.info('[top-right] Wormhole terminal launch ready', identityNodeId);
      }
    } catch (error) {
      if (isWormholePrepAbortedError(error)) {
        return;
      }
      const message =
        typeof error === 'object' && error !== null && 'message' in error
          ? String((error as { message?: string }).message || '')
          : '';
      const settings = await fetchWormholeSettings(true).catch(() => null);
      const runtime = await fetchWormholeStatus().catch(() => null);
      setTerminalPrivateEnabled(Boolean(settings?.enabled ?? runtime?.running ?? runtime?.ready ?? false));
      setTerminalPrivateReady(Boolean(runtime?.ready));
      setTerminalTransportTier(
        String(runtime?.transport_tier || runtime?.transport_active || 'public_degraded'),
      );
      setTerminalLaunchError(message || 'Wormhole is still warming up in the background.');
    } finally {
      setTerminalLaunchBusy(false);
    }
  }, [applySecureModeBoundary]);

  const activateWormholeAndLaunchTerminal = async () => {
    setTerminalLaunchBusy(true);
    setTerminalLaunchError('');
    setTerminalPrivateEnabled(true);
    setTerminalPrivateReady(false);
    setTerminalLauncherOpen(false);
    launchTerminalDirect();
    void continueTerminalLaunchInBackground();
  };

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      if (activatingPollRef.current) clearInterval(activatingPollRef.current);
      if (activatingTimeoutRef.current) clearTimeout(activatingTimeoutRef.current);
    };
  }, []);

  const refreshNodeStatus = async () => {
    const data = await fetchInfonetNodeStatusSnapshot(true);
    setNodeStatus(data);
    setNodeStatusError('');
    return data;
  };

  const stopActivatingPolls = useCallback(() => {
    if (activatingPollRef.current) { clearInterval(activatingPollRef.current); activatingPollRef.current = null; }
    if (activatingTimeoutRef.current) { clearTimeout(activatingTimeoutRef.current); activatingTimeoutRef.current = null; }
  }, []);

  const setNodeEnabled = async (enabled: boolean) => {
    setNodeToggleBusy(true);
    setNodeToggleError('');
    try {
      // Auto-generate keys on first activation
      if (enabled) {
        setActivatingPhase('keys');
        setActivatingTimedOut(false);
        setNodeStep('activating');
        const existing = getNodeIdentity();
        if (!existing) {
          await generateNodeKeys();
        }
        setActivatingPhase('peers');
        const torStatus = await startTorHiddenService();
        if (!torStatus?.running || !torStatus?.onion_address) {
          throw new Error(torStatus?.detail || 'Tor onion service did not start');
        }
      }

      const res = await controlPlaneFetch('/api/settings/node', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
        requireAdminSession: false,
      });
      const data = (await res.json().catch(() => ({}))) as {
        detail?: string;
        message?: string;
      };
      if (!res.ok) {
        throw new Error(data?.detail || data?.message || 'Node settings update failed');
      }
      await refreshNodeStatus();

      if (enabled) {
        setActivatingPhase('swarm');
        await joinInfonetSwarm().catch(() => null);
        await refreshNodeStatus();
        setActivatingPhase('sync');
        // Start fast-polling for sync progress
        stopActivatingPolls();
        activatingPollRef.current = setInterval(async () => {
          try {
            const snap = await fetchInfonetNodeStatusSnapshot(true);
            setNodeStatus(snap);
            const outcome = String(snap?.sync_runtime?.last_outcome || '').toLowerCase();
            if (outcome === 'ok' || outcome === 'solo') {
              setActivatingPhase('done');
              stopActivatingPolls();
              // Auto-transition to 'disable' after brief success display
              setTimeout(() => setNodeStep('disable'), 2500);
            }
          } catch { /* ignore poll errors */ }
        }, 3000);
        // Timeout after 90s
        activatingTimeoutRef.current = setTimeout(() => {
          setActivatingTimedOut(true);
        }, 90000);
      } else {
        // Disabling — close modal
        setLauncherOpen(false);
        setNodeStep('prompt');
      }
    } catch (error) {
      const message =
        typeof error === 'object' && error !== null && 'message' in error
          ? String((error as { message?: string }).message || '')
          : '';
      setNodeToggleError(message || 'Node settings update failed');
      if (enabled) setNodeStep('terms'); // Go back to terms on error
    } finally {
      setNodeToggleBusy(false);
    }
  };

  useEffect(() => {
    setPortalReady(true);
  }, []);

  useEffect(() => {
    let alive = true;
    const fetchWormhole = async () => {
      try {
        const data = await fetchWormholeSettings();
        const enabled = Boolean(data?.enabled);
        await applySecureModeBoundary(enabled);
      } catch {
        /* ignore */
      }
    };
    const fetchNodeStatus = async () => {
      try {
        const data = await fetchInfonetNodeStatusSnapshot(true);
        if (alive) {
          setNodeStatus(data);
          setNodeStatusError('');
        }
      } catch (error) {
        if (!alive) return;
        const message =
          typeof error === 'object' && error !== null && 'message' in error
            ? String((error as { message?: string }).message || '')
            : '';
        setNodeStatusError(message || 'node runtime unavailable');
      }
    };

    const poll = () => {
      fetchWormhole();
      fetchNodeStatus();
    };
    poll();
    const interval = setInterval(poll, 15000);
    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, []);

  const checkForUpdates = async () => {
    setUpdateStatus('checking');
    try {
      const desktopContext = await getDesktopUpdateContext();
      const runtime = classifyUpdateRuntime(desktopContext);
      const res = await fetch(
        'https://api.github.com/repos/BigBodyCobain/Shadowbroker/releases/latest',
      );
      if (!res.ok) throw new Error('Failed to fetch');
      const data = (await res.json()) as GitHubLatestRelease;

      const latest = data.tag_name?.replace('v', '') || data.name?.replace('v', '');
      const current = currentVersion.replace('v', '');
      const releaseUrl =
        typeof data.html_url === 'string' && data.html_url.trim().length > 0
          ? data.html_url
          : DEFAULT_RELEASES_URL;
      const platform = desktopContext?.platform || 'unknown';
      const ownsLocalBackend = Boolean(desktopContext?.owns_local_backend);
      setReleasePageUrl(releaseUrl);
      setManualUpdateUrl(getPreferredManualUpdateUrl(data, runtime, platform));
      let resolvedAction = getUpdateAction(runtime);
      let resolvedDetail =
        runtime === 'desktop_packaged'
          ? packagedUpdateDetail(ownsLocalBackend)
          : AUTO_UPDATE_DETAIL;

      if (runtime === 'desktop_packaged') {
        try {
          const desktopUpdate = await checkDesktopUpdaterUpdate();
          if (desktopUpdate?.version) {
            resolvedAction = 'desktop_updater';
            resolvedDetail = DESKTOP_UPDATER_DETAIL;
            setLatestVersion(desktopUpdate.version.replace(/^v/i, ''));
            setUpdateAction(resolvedAction);
            setUpdateDetail(resolvedDetail);
            setUpdateStatus('available');
            return;
          }
        } catch (desktopUpdaterError) {
          console.warn('Desktop updater check failed; falling back to release download:', desktopUpdaterError);
        }
      }

      setUpdateAction(resolvedAction);
      setUpdateDetail(
        resolvedDetail,
      );

      if (latest && latest !== current) {
        setLatestVersion(latest);
        setUpdateStatus('available');
      } else {
        setUpdateStatus('uptodate');
        setTimeout(() => setUpdateStatus('idle'), 3000);
      }
    } catch (err) {
      console.error('Update check failed:', err);
      setUpdateStatus('error');
      setTimeout(() => setUpdateStatus('idle'), 3000);
    }
  };

  const startRestartPolling = () => {
    setUpdateStatus('restarting');

    // Poll /api/health until backend comes back
    pollRef.current = setInterval(async () => {
      try {
        const h = await fetch(`${API_BASE}/api/health`);
        if (h.ok) {
          if (pollRef.current) clearInterval(pollRef.current);
          if (timeoutRef.current) clearTimeout(timeoutRef.current);
          window.location.reload();
        }
      } catch {
        // Backend still down — keep polling
      }
    }, 3000);

    // Give up after 90 seconds
    timeoutRef.current = setTimeout(() => {
      if (pollRef.current) clearInterval(pollRef.current);
      setErrorMessage('Restart timed out — the app may need to be started manually.');
      setUpdateStatus('update_error');
    }, 90000);
  };

  const triggerUpdate = async () => {
    if (updateAction === 'manual_download') {
      window.open(manualUpdateUrl, '_blank', 'noopener,noreferrer');
      setUpdateStatus('idle');
      return;
    }

    if (updateAction === 'desktop_updater') {
      setUpdateStatus('updating');
      setErrorMessage('');
      try {
        await installDesktopUpdaterUpdate();
        setUpdateStatus('restarting');
      } catch (err) {
        const message =
          typeof err === 'object' && err !== null && 'message' in err
            ? String((err as { message?: string }).message)
            : '';
        setErrorMessage(
          message === 'desktop_update_installed_restart_required'
            ? 'Update installed. Restart ShadowBroker to finish applying it.'
            : message || 'Desktop updater failed. Use manual download if this keeps happening.',
        );
        setUpdateStatus('update_error');
      }
      return;
    }

    setUpdateStatus('updating');
    setErrorMessage('');
    try {
      const res = await controlPlaneFetch('/api/system/update', { method: 'POST' });
      const data = (await res.json().catch(() => ({}))) as {
        ok?: boolean;
        status?: string;
        message?: string;
        detail?: string;
        manual_url?: string;
        release_url?: string;
        docker_commands?: string;
      };
      if (typeof data.manual_url === 'string' && data.manual_url.trim().length > 0) {
        setManualUpdateUrl(data.manual_url);
      }
      if (typeof data.release_url === 'string' && data.release_url.trim().length > 0) {
        setReleasePageUrl(data.release_url);
      }
      if (data?.status === 'docker') {
        setDockerCommands(data.docker_commands || 'docker compose pull && docker compose up -d');
        setUpdateStatus('docker_update');
        return;
      }
      if (data?.status === 'manual') {
        const targetUrl =
          typeof data.manual_url === 'string' && data.manual_url.trim().length > 0
            ? data.manual_url
            : manualUpdateUrl;
        window.open(targetUrl, '_blank', 'noopener,noreferrer');
        setUpdateStatus('idle');
        return;
      }
      if (!res.ok || data?.ok === false || data?.status === 'error') {
        const message = data?.detail || data?.message || 'control_plane_request_failed';
        const error = new Error(message) as Error & { manualUrl?: string };
        error.manualUrl = data?.manual_url;
        throw error;
      }

      startRestartPolling();
    } catch (err) {
      // The update extracts files over the project, which causes the Next.js
      // dev server to hot-reload and drop the proxy connection mid-request.
      // A network error during update likely means it SUCCEEDED and the
      // server is restarting — transition to polling instead of showing failure.
      const message =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : '';
      const isNetworkDrop = err instanceof TypeError || message === 'Failed to fetch';
      if (isNetworkDrop) {
        startRestartPolling();
      } else {
        const manualUrl =
          typeof err === 'object' && err !== null && 'manualUrl' in err
            ? String((err as { manualUrl?: string }).manualUrl || '')
            : '';
        if (manualUrl) {
          setManualUpdateUrl(manualUrl);
        }
        setErrorMessage(message || 'Unknown error');
        setUpdateStatus('update_error');
      }
    }
  };

  // ── Confirmation Dialog ──
  const renderConfirmDialog = () => (
    <div className="absolute top-full right-0 mt-2 w-72 z-[9999]">
      <div className="bg-[var(--bg-primary)]/95 backdrop-blur-sm border border-cyan-800/60 shadow-[0_4px_30px_rgba(0,255,255,0.15)] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-primary)]">
          <span className="text-[10px] font-mono tracking-widest text-cyan-400">
            {t('update.autoUpdate').toUpperCase()} v{currentVersion} → v{latestVersion}
          </span>
          <button
            onClick={() => setUpdateStatus('available')}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={12} />
          </button>
        </div>

        {/* Actions */}
        <div className="p-3 flex flex-col gap-2">
          <p className="text-[9px] font-mono text-[var(--text-muted)] leading-relaxed">
            {updateDetail}
          </p>
          <button
            onClick={triggerUpdate}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-cyan-500/10 border border-cyan-500/40 hover:bg-cyan-500/20 transition-all text-[10px] text-cyan-400 font-mono tracking-widest"
          >
            <Download size={12} />
            {updateAction === 'manual_download'
              ? t('update.downloadInstaller')
              : updateAction === 'desktop_updater'
                ? t('update.installUpdate')
                : t('update.autoUpdate')}
          </button>

          <a
            href={updateAction === 'manual_download' ? releasePageUrl : manualUpdateUrl}
            target="_blank"
            rel="noreferrer"
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] hover:border-[var(--text-muted)] transition-all text-[10px] text-[var(--text-muted)] font-mono tracking-widest"
          >
            <ExternalLink size={12} />
            {updateAction === 'manual_download' ? t('update.viewRelease') : t('update.manualDownload')}
          </a>

          <button
            onClick={() => setUpdateStatus('available')}
            className="w-full flex items-center justify-center px-3 py-1.5 text-[9px] text-[var(--text-muted)] font-mono tracking-widest hover:text-[var(--text-secondary)] transition-colors"
          >
            {t('update.cancel')}
          </button>
        </div>
      </div>
    </div>
  );

  // ── Error Dialog ──
  const renderErrorDialog = () => (
    <div className="absolute top-full right-0 mt-2 w-72 z-[9999]">
      <div className="bg-[var(--bg-primary)]/95 backdrop-blur-sm border border-red-800/60 shadow-[0_4px_30px_rgba(255,0,0,0.1)] overflow-hidden">
        <div className="px-3 py-2 border-b border-red-900/40">
          <span className="text-[10px] font-mono tracking-widest text-red-400">{t('update.updateFailed')}</span>
        </div>
        <div className="p-3 flex flex-col gap-2">
          <p className="text-[9px] font-mono text-[var(--text-muted)] leading-relaxed break-words">
            {errorMessage}
          </p>
          <button
            onClick={() => setUpdateStatus('confirming')}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-cyan-500/10 border border-cyan-500/40 hover:bg-cyan-500/20 transition-all text-[10px] text-cyan-400 font-mono tracking-widest"
          >
            <RefreshCw size={12} />
            {t('update.tryAgain')}
          </button>
          <a
            href={updateAction === 'manual_download' ? releasePageUrl : manualUpdateUrl}
            target="_blank"
            rel="noreferrer"
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] hover:border-[var(--text-muted)] transition-all text-[10px] text-[var(--text-muted)] font-mono tracking-widest"
          >
            <ExternalLink size={12} />
            {updateAction === 'manual_download' ? t('update.viewRelease') : t('update.manualDownload')}
          </a>
        </div>
      </div>
    </div>
  );

  // ── Docker Update Dialog ──
  const renderDockerDialog = () => (
    <div className="absolute top-full right-0 mt-2 w-80 z-[9999]">
      <div className="bg-[var(--bg-primary)]/95 backdrop-blur-sm border border-cyan-800/60 shadow-[0_4px_30px_rgba(0,255,255,0.15)] overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-primary)]">
          <span className="text-[10px] font-mono tracking-widest text-cyan-400">
            {t('update.dockerUpdate')} — v{latestVersion}
          </span>
          <button
            onClick={() => setUpdateStatus('idle')}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={12} />
          </button>
        </div>
        <div className="p-3 flex flex-col gap-2">
          <p className="text-[9px] font-mono text-[var(--text-muted)] leading-relaxed">
            {t('update.dockerUpdateDetail')}
          </p>
          <div className="relative bg-black/40 border border-[var(--border-primary)] p-2 group">
            <code className="text-[9px] font-mono text-green-400 break-all">{dockerCommands}</code>
            <button
              onClick={() => navigator.clipboard.writeText(dockerCommands)}
              className="absolute top-1 right-1 p-1 opacity-0 group-hover:opacity-100 transition-opacity text-[var(--text-muted)] hover:text-cyan-400"
              title="Copy command"
            >
              <Copy size={10} />
            </button>
          </div>
          <a
            href={releasePageUrl}
            target="_blank"
            rel="noreferrer"
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] hover:border-[var(--text-muted)] transition-all text-[10px] text-[var(--text-muted)] font-mono tracking-widest"
          >
            <ExternalLink size={12} />
            {t('update.viewRelease')}
          </a>
        </div>
      </div>
    </div>
  );

  const nodeMode = String(nodeStatus?.node_mode || 'participant').trim().toUpperCase();
  const nodeEnabled = Boolean(nodeStatus?.node_enabled);
  const syncOutcomeRaw = String(nodeStatus?.sync_runtime?.last_outcome || 'idle')
    .trim()
    .toLowerCase();
  const syncError = String(nodeStatus?.sync_runtime?.last_error || '').trim().toLowerCase();
  const syncOutcome = !nodeEnabled
    ? 'OFF'
    : syncOutcomeRaw === 'solo' || syncError === 'no active sync peers'
      ? 'SOLO'
      : syncOutcomeRaw === 'ok'
        ? 'CONNECTED'
        : syncOutcomeRaw === 'running'
          ? 'SYNCING'
          : syncOutcomeRaw === 'fork'
            ? 'FORK STOP'
            : syncOutcomeRaw === 'error'
              ? 'SYNC ISSUE'
              : 'ACTIVE';
  const bootstrapFailed = Boolean(nodeStatus?.bootstrap?.last_bootstrap_error);
  const nodeIndicatorClass =
    !nodeEnabled
      ? 'bg-rose-400'
      : syncOutcomeRaw === 'solo' || syncError === 'no active sync peers'
        ? 'bg-cyan-400'
      : syncOutcomeRaw === 'ok'
      ? 'bg-green-400'
      : syncOutcomeRaw === 'fork' || bootstrapFailed
        ? 'bg-amber-400'
      : syncOutcomeRaw === 'error'
          ? 'bg-rose-400'
          : 'bg-cyan-400';
  const nodeTitle = !nodeEnabled
    ? `${nodeMode} node • off`
    : bootstrapFailed
      ? `${nodeMode} node • bootstrap warning`
      : `${nodeMode} node • ${syncOutcome.toLowerCase()}`;
  const closeLauncher = () => {
    stopActivatingPolls();
    setLauncherOpen(false);
    setNodeStep('prompt');
    setNodeToggleError('');
    setActivatingTimedOut(false);
  };

  // Uniform button style (matches UPDATES button)
  const btnBase = 'flex items-center justify-center gap-1 px-2 py-1.5 bg-[var(--bg-primary)]/70 border border-[var(--border-primary)] hover:border-cyan-500/50 hover:bg-[var(--hover-accent)] transition-all text-[10px] text-[var(--text-secondary)] font-mono cursor-pointer flex-1';

  const nodeLauncherModal =
    portalReady && launcherOpen
      ? createPortal(
          <div className="fixed inset-0 z-[1200] flex items-center justify-center p-4">
            <button
              type="button"
              aria-label="Close node launcher"
              onClick={closeLauncher}
              className="absolute inset-0 bg-black/70 backdrop-blur-[2px]"
            />
            <div className="relative z-[1201] w-full max-w-[520px] border border-cyan-700/40 bg-[var(--bg-primary)]/96 backdrop-blur-sm shadow-[0_0_32px_rgba(0,255,255,0.12)]">
              <div className="flex items-center justify-between px-4 py-3 border-b border-cyan-900/30">
                <div>
                  <div className="text-[10px] font-mono tracking-[0.24em] text-cyan-300">
                    {nodeStep === 'disable'
                      ? t('node.nodeActivated')
                      : nodeStep === 'activating'
                        ? t('node.activatingNode')
                        : nodeStep === 'prompt'
                          ? t('node.activateNode')
                          : t('node.stipulations')}
                  </div>
                  <div className="mt-1 text-[9px] font-mono text-[var(--text-muted)]">
                    {nodeMode} • {syncOutcome} • participant-node sync does not require Wormhole
                  </div>
                </div>
                <button
                  type="button"
                  onClick={closeLauncher}
                  className="text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
                  title="Close node launcher"
                >
                  <X size={13} />
                </button>
              </div>
              <div className="px-5 py-5 space-y-4">
                {nodeStep === 'disable' ? (
                  <>
                    <div className="border border-cyan-500/20 bg-cyan-950/10 px-4 py-4 text-[10px] font-mono text-cyan-100 leading-[1.8]">
                      {t('node.nodeActivated')}.
                      {(() => { const id = getNodeIdentity(); return id?.nodeId ? (
                        <div className="mt-2 text-[9px] text-cyan-400 font-mono tracking-wide">
                          {id.nodeId}
                        </div>
                      ) : null; })()}
                      <div className="mt-2 text-[9px] text-cyan-200/70 normal-case tracking-normal flex flex-wrap gap-x-3">
                        <span>{syncOutcome.toLowerCase()}</span>
                        {(nodeStatus?.total_events ?? 0) > 0 && <span>{nodeStatus?.total_events} {t('node.events')}</span>}
                        {(nodeStatus?.bootstrap?.sync_peer_count ?? 0) > 0 && (
                          <span>
                            {nodeStatus?.bootstrap?.sync_peer_count} {t('node.peers')}
                            {(nodeStatus?.bootstrap?.swarm_sync_peer_count ?? 0) > 0
                              ? ` (${nodeStatus?.bootstrap?.swarm_sync_peer_count} swarm)`
                              : ''}
                          </span>
                        )}
                      </div>
                      <div className="mt-3 text-[11px] text-[var(--text-muted)] normal-case tracking-normal leading-[1.8]">
                        {t('node.keepSyncing')}
                      </div>
                    </div>
                    {nodeToggleError && (
                      <div className="border border-amber-500/40 bg-amber-950/20 px-4 py-3 text-[9px] font-mono text-amber-200 leading-[1.7]">
                        {nodeToggleError}
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-3">
                      <button
                        type="button"
                        onClick={() => void setNodeEnabled(false)}
                        disabled={nodeToggleBusy}
                        className="px-4 py-3 border border-rose-500/40 bg-rose-950/20 hover:bg-rose-950/35 disabled:opacity-50 text-[11px] font-mono text-rose-300 tracking-[0.18em]"
                      >
                        {nodeToggleBusy ? t('node.turningOff') : t('node.turnOff')}
                      </button>
                      <button
                        type="button"
                        onClick={closeLauncher}
                        disabled={nodeToggleBusy}
                        className="px-4 py-3 border border-[var(--border-primary)] hover:border-cyan-500/40 disabled:opacity-50 text-[11px] font-mono text-[var(--text-muted)] tracking-[0.18em]"
                      >
                        {t('node.keepOn')}
                      </button>
                    </div>
                  </>
                ) : nodeStep === 'activating' ? (
                  <>
                    <div className="border border-cyan-500/20 bg-black/30 px-4 py-4 space-y-3">
                      {/* Step: Generate identity */}
                      <div className="flex items-center gap-3 text-[10px] font-mono">
                        {activatingPhase === 'keys' ? (
                          <RefreshCw size={11} className="text-cyan-400 animate-spin shrink-0" />
                        ) : (
                          <CheckCircle2 size={11} className="text-green-400 shrink-0" />
                        )}
                        <span className={activatingPhase === 'keys' ? 'text-cyan-300' : 'text-green-300'}>
                          {activatingPhase === 'keys' ? t('node.generatingIdentity') : t('node.identityReady')}
                        </span>
                        {activatingPhase !== 'keys' && (() => { const id = getNodeIdentity(); return id?.nodeId ? (
                          <span className="text-[11px] text-cyan-400/70 ml-auto">{id.nodeId}</span>
                        ) : null; })()}
                      </div>
                      {/* Step: Connect to relay */}
                      <div className="flex items-center gap-3 text-[10px] font-mono">
                        {activatingPhase === 'keys' ? (
                          <span className="w-[11px] h-[11px] shrink-0" />
                        ) : activatingPhase === 'peers' ? (
                          <RefreshCw size={11} className="text-cyan-400 animate-spin shrink-0" />
                        ) : (
                          <CheckCircle2 size={11} className="text-green-400 shrink-0" />
                        )}
                        <span className={
                          activatingPhase === 'keys' ? 'text-[var(--text-muted)]'
                          : activatingPhase === 'peers' ? 'text-cyan-300'
                          : 'text-green-300'
                        }>
                          {activatingPhase === 'keys' ? t('node.preparingTransport')
                          : activatingPhase === 'peers' ? t('node.findingPeers')
                          : t('node.peersReady')}
                        </span>
                      </div>
                      {/* Step: Register with swarm */}
                      <div className="flex items-center gap-3 text-[10px] font-mono">
                        {activatingPhase === 'keys' || activatingPhase === 'peers' ? (
                          <span className="w-[11px] h-[11px] shrink-0" />
                        ) : activatingPhase === 'swarm' ? (
                          <RefreshCw size={11} className="text-cyan-400 animate-spin shrink-0" />
                        ) : (
                          <CheckCircle2 size={11} className="text-green-400 shrink-0" />
                        )}
                        <span className={
                          activatingPhase === 'keys' || activatingPhase === 'peers' ? 'text-[var(--text-muted)]'
                          : activatingPhase === 'swarm' ? 'text-cyan-300'
                          : 'text-green-300'
                        }>
                          {activatingPhase === 'swarm'
                            ? 'Registering with swarm...'
                            : activatingPhase === 'keys' || activatingPhase === 'peers'
                              ? 'Join private Infonet swarm'
                              : `Swarm ready${(nodeStatus?.bootstrap?.swarm_sync_peer_count ?? 0) > 0
                                ? ` (${nodeStatus?.bootstrap?.swarm_sync_peer_count} discovered)`
                                : ''}`}
                        </span>
                      </div>
                      {/* Step: Sync chain */}
                      <div className="flex items-center gap-3 text-[10px] font-mono">
                        {(activatingPhase === 'keys' || activatingPhase === 'peers' || activatingPhase === 'swarm') ? (
                          <span className="w-[11px] h-[11px] shrink-0" />
                        ) : activatingPhase === 'sync' ? (
                          <RefreshCw size={11} className="text-cyan-400 animate-spin shrink-0" />
                        ) : (
                          <CheckCircle2 size={11} className="text-green-400 shrink-0" />
                        )}
                        <span className={
                          (activatingPhase === 'keys' || activatingPhase === 'peers' || activatingPhase === 'swarm') ? 'text-[var(--text-muted)]'
                          : activatingPhase === 'sync' ? 'text-cyan-300'
                          : 'text-green-300'
                        }>
                          {activatingPhase === 'done'
                            ? (syncOutcomeRaw === 'solo'
                              ? `${t('node.soloNodeReady')} — ${nodeStatus?.total_events ?? 0} ${t('node.events')}`
                              : `${t('node.synced')} — ${nodeStatus?.total_events ?? 0} ${t('node.events')}`)
                            : activatingPhase === 'sync'
                              ? `${t('node.syncingChain')}${(nodeStatus?.total_events ?? 0) > 0 ? ` ${nodeStatus?.total_events} ${t('node.events')}` : ''}`
                              : t('node.syncingChain')}
                        </span>
                      </div>
                      {/* Done banner */}
                      {activatingPhase === 'done' && (
                        <>
                          <div className="mt-2 border border-green-500/30 bg-green-950/20 px-3 py-2 text-[10px] font-mono text-green-300 tracking-[0.15em] text-center">
                            {t('node.nodeOnline')}
                          </div>
                          <div className="mt-1 text-[11px] font-mono text-[var(--text-muted)] leading-[1.8] normal-case tracking-normal">
                            {t('node.keepSyncing')}
                          </div>
                        </>
                      )}
                    </div>
                    {activatingTimedOut && activatingPhase !== 'done' && (
                      <div className="border border-amber-500/40 bg-amber-950/20 px-4 py-3 text-[9px] font-mono text-amber-200 leading-[1.7]">
                        {t('node.syncTakingLong')}
                      </div>
                    )}
                    {nodeToggleError && (
                      <div className="border border-amber-500/40 bg-amber-950/20 px-4 py-3 text-[9px] font-mono text-amber-200 leading-[1.7]">
                        {nodeToggleError}
                      </div>
                    )}
                    {(activatingTimedOut || activatingPhase === 'done') && (
                      <button
                        type="button"
                        onClick={closeLauncher}
                        className="w-full px-4 py-3 border border-cyan-500/40 bg-cyan-950/20 hover:bg-cyan-950/35 text-[11px] font-mono text-cyan-300 tracking-[0.18em]"
                      >
                        {t('node.close')}
                      </button>
                    )}
                  </>
                ) : nodeStep === 'prompt' ? (
                  <>
                    <div className="border border-cyan-500/20 bg-cyan-950/10 px-4 py-4 text-[10px] font-mono text-cyan-100 leading-[1.8]">
                      {t('node.activatePrompt')}
                    </div>
                    {(bootstrapFailed || nodeStatusError || nodeToggleError) && (
                      <div className="border border-amber-500/40 bg-amber-950/20 px-4 py-3 text-[9px] font-mono text-amber-200 leading-[1.7]">
                        {nodeToggleError || nodeStatusError || nodeStatus?.bootstrap?.last_bootstrap_error || 'Node runtime warning detected.'}
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-3">
                      <button
                        type="button"
                        onClick={() => setNodeStep('terms')}
                        className="px-4 py-3 border border-cyan-500/40 bg-cyan-950/20 hover:bg-cyan-950/35 text-[11px] font-mono text-cyan-300 tracking-[0.18em]"
                      >
                        {t('node.yes')}
                      </button>
                      <button
                        type="button"
                        onClick={closeLauncher}
                        className="px-4 py-3 border border-[var(--border-primary)] hover:border-cyan-500/40 text-[11px] font-mono text-[var(--text-muted)] tracking-[0.18em]"
                      >
                        {t('node.no')}
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="border border-cyan-500/20 bg-black/30 px-4 py-4 text-[9px] font-mono text-slate-200 leading-[1.85]">
                      <div className="text-cyan-300 tracking-[0.18em]">{t('node.termsTitle')}</div>
                      <ul className="mt-3 space-y-2 list-disc pl-5">
                        <li>{t('node.term1')}</li>
                        <li>{t('node.term2')}</li>
                        <li>{t('node.term3')}</li>
                        <li>{t('node.term4')}</li>
                        <li>{t('node.term5')}</li>
                      </ul>
                    </div>
                    <div className="text-[11px] font-mono uppercase tracking-[0.2em] text-cyan-300/80">
                      {nodeMode} • {syncOutcome}
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <button
                        type="button"
                        onClick={() => void setNodeEnabled(true)}
                        disabled={nodeToggleBusy}
                        className="px-4 py-3 border border-cyan-500/40 bg-cyan-950/20 hover:bg-cyan-950/35 disabled:opacity-50 text-[11px] font-mono text-cyan-300 tracking-[0.18em]"
                      >
                        {nodeToggleBusy ? t('node.activating') : t('node.agree')}
                      </button>
                      <button
                        type="button"
                        onClick={closeLauncher}
                        disabled={nodeToggleBusy}
                        className="px-4 py-3 border border-[var(--border-primary)] hover:border-cyan-500/40 disabled:opacity-50 text-[11px] font-mono text-[var(--text-muted)] tracking-[0.18em]"
                      >
                        {t('node.disagree')}
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>,
          document.body,
        )
      : null;

  const terminalStatusLabel = terminalPrivateReady
    ? t('terminal.privateLaneReady')
    : terminalPrivateEnabled
      ? t('terminal.privateLaneStarting')
      : t('terminal.privateLaneOffline');
  const terminalStatusTone = terminalPrivateReady
    ? 'text-emerald-300'
    : terminalPrivateEnabled
      ? 'text-amber-300'
      : 'text-cyan-300';
  const terminalLauncherModal =
    portalReady && terminalLauncherOpen
      ? createPortal(
          <div className="fixed inset-0 z-[1200] flex items-center justify-center p-4">
            <button
              type="button"
              aria-label="Close terminal launcher"
              onClick={closeTerminalLauncher}
              className="absolute inset-0 bg-black/70 backdrop-blur-[2px]"
            />
            <div className="relative z-[1201] w-full max-w-[640px] border border-cyan-700/40 bg-[var(--bg-primary)]/96 backdrop-blur-sm shadow-[0_0_32px_rgba(0,255,255,0.12)]">
              <div className="flex items-center justify-between px-4 py-3 border-b border-cyan-900/30">
                <div>
                  <div className="text-[13px] font-mono tracking-[0.24em] text-cyan-300">
                    {t('terminal.infonetTerminal')}
                  </div>
                  <div className={`mt-1 text-[11px] font-mono ${terminalStatusTone}`}>
                    {terminalStatusLabel} • {terminalTransportTier}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={closeTerminalLauncher}
                  className="text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
                  title="Close terminal launcher"
                >
                  <X size={16} />
                </button>
              </div>
              <div className="px-5 py-5 space-y-4">
                <div className="border border-cyan-500/20 bg-cyan-950/10 px-4 py-4 text-[13px] font-mono text-cyan-100 leading-[1.8]">
                  {terminalPrivateReady
                    ? t('terminal.enterTerminal')
                    : t('terminal.terminalDetail')}
                  <div className="mt-2 text-[12px] text-cyan-200/70 normal-case tracking-normal">
                    {terminalPrivateReady
                      ? t('terminal.identityReady')
                      : t('terminal.identityNotReady')}
                  </div>
                </div>
                {terminalLaunchError && (
                  <div className="border border-amber-500/40 bg-amber-950/20 px-4 py-3 text-[12px] font-mono text-amber-200 leading-[1.7]">
                    {terminalLaunchError}
                  </div>
                )}
                <div className="border border-cyan-500/20 bg-black/30 px-4 py-4 text-[12px] font-mono text-slate-200 leading-[1.85]">
                  <div className="text-cyan-300 tracking-[0.18em]">{t('terminal.beforeYouEnter')}</div>
                  <ul className="mt-3 space-y-2 list-disc pl-5">
                    <li>{t('terminal.termTerminal1')}</li>
                    <li>{t('terminal.termTerminal2')}</li>
                    <li>{t('terminal.termTerminal3')}</li>
                  </ul>
                </div>
                <div className="border border-amber-500/20 bg-amber-950/10 px-4 py-3 text-[12px] font-mono text-amber-200/80 leading-[1.85]">
                  <div className="text-amber-300 tracking-[0.18em]">{t('terminal.wormholeCleanup')}</div>
                  <div className="mt-2">
                    {t('terminal.cleanupDetail')}
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <button
                    type="button"
                    onClick={() => void activateWormholeAndLaunchTerminal()}
                    disabled={terminalLaunchBusy}
                    className="px-4 py-3 border border-cyan-500/40 bg-cyan-950/20 hover:bg-cyan-950/35 disabled:opacity-50 text-[13px] font-mono text-cyan-300 tracking-[0.16em]"
                  >
                    {terminalLaunchBusy
                      ? t('terminal.entering')
                      : terminalPrivateReady
                        ? t('terminal.enterWormhole')
                        : t('terminal.activateWormhole')}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      closeTerminalLauncher();
                      onMeshChatNavigate?.('meshtastic');
                    }}
                    disabled={terminalLaunchBusy}
                    className="px-4 py-3 border border-[var(--border-primary)] hover:border-cyan-500/40 disabled:opacity-50 text-[13px] font-mono text-[var(--text-muted)] tracking-[0.16em]"
                  >
                    {t('terminal.goToMesh')}
                  </button>
                  <button
                    type="button"
                    onClick={closeTerminalLauncher}
                    disabled={terminalLaunchBusy}
                    className="px-4 py-3 border border-[var(--border-primary)] hover:border-cyan-500/40 disabled:opacity-50 text-[13px] font-mono text-[var(--text-muted)] tracking-[0.16em]"
                  >
                    {t('update.cancel')}
                  </button>
                </div>
              </div>
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <>
    {terminalLauncherModal}
    {nodeLauncherModal}
    <div className="relative flex items-center gap-1.5 mb-1 w-full">
      {/* Node runtime / private lane */}
      <button
        type="button"
        onClick={() => {
          setNodeStep(nodeEnabled ? 'disable' : 'prompt');
          setNodeToggleError('');
          setLauncherOpen(true);
        }}
        className={`relative ${btnBase}`}
        title={nodeTitle}
      >
        <Server size={11} className="text-cyan-400" />
        <span className="tracking-wider">{t('controls.node')}</span>
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${nodeIndicatorClass}`} />
      </button>

      {/* Terminal toggle */}
      <button
        type="button"
        onClick={() => void openTerminalLauncher()}
        className={`relative ${btnBase}`}
        title="Open Mesh Terminal"
      >
        <Terminal size={11} className="text-cyan-400" />
        <span className="tracking-wider">{t('controls.terminal')}</span>
        {(dmCount ?? 0) > 0 && (
          <span className="absolute -top-1.5 -right-1.5 bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[14px] h-[14px] flex items-center justify-center px-0.5 shadow-[0_0_6px_rgba(239,68,68,0.5)]">
            {(dmCount ?? 0) > 9 ? '9+' : dmCount}
          </span>
        )}
      </button>

      {/* ── Update Available → opens confirmation ── */}
      {updateStatus === 'available' && (
        <button
          onClick={() => setUpdateStatus('confirming')}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-green-500/10 backdrop-blur-sm border border-green-500/50 hover:bg-green-500/20 transition-all text-[10px] text-green-400 font-mono cursor-pointer shadow-[0_0_15px_rgba(34,197,94,0.3)]"
        >
          <Download size={12} className="w-3 h-3" />
          <span className="tracking-widest">v{latestVersion} UPDATE!</span>
        </button>
      )}

      {/* ── Confirming → show dialog ── */}
      {updateStatus === 'confirming' && (
        <>
          <button className="flex items-center gap-1.5 px-2.5 py-1.5 bg-green-500/10 backdrop-blur-sm border border-green-500/50 text-[10px] text-green-400 font-mono shadow-[0_0_15px_rgba(34,197,94,0.3)]">
            <Download size={12} className="w-3 h-3" />
            <span className="tracking-widest">v{latestVersion} UPDATE!</span>
          </button>
          {renderConfirmDialog()}
        </>
      )}

      {/* ── Updating → spinner ── */}
      {updateStatus === 'updating' && (
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-cyan-500/10 backdrop-blur-sm border border-cyan-500/50 text-[10px] text-cyan-400 font-mono">
          <RefreshCw size={12} className="w-3 h-3 animate-spin" />
          <span className="tracking-widest">{t('update.downloadingUpdate')}</span>
        </div>
      )}

      {/* ── Restarting → spinner + waiting ── */}
      {updateStatus === 'restarting' && (
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-cyan-500/10 backdrop-blur-sm border border-cyan-500/50 text-[10px] text-cyan-400 font-mono shadow-[0_0_15px_rgba(0,255,255,0.2)]">
          <RefreshCw size={12} className="w-3 h-3 animate-spin" />
          <span className="tracking-widest">{t('update.restarting')}</span>
        </div>
      )}

      {/* ── Error → show error dialog ── */}
      {updateStatus === 'update_error' && (
        <>
          <button
            onClick={() => setUpdateStatus('confirming')}
            className="flex items-center gap-1.5 px-2.5 py-1.5 bg-red-500/10 backdrop-blur-sm border border-red-500/50 hover:bg-red-500/20 transition-all text-[10px] text-red-400 font-mono"
          >
            <AlertCircle size={12} className="w-3 h-3" />
            <span className="tracking-widest">{t('update.updateFailed')}</span>
          </button>
          {renderErrorDialog()}
        </>
      )}

      {/* ── Docker update → show pull instructions ── */}
      {updateStatus === 'docker_update' && (
        <>
          <button
            onClick={() => setUpdateStatus('docker_update')}
            className="flex items-center gap-1.5 px-2.5 py-1.5 bg-cyan-500/10 backdrop-blur-sm border border-cyan-500/50 text-[10px] text-cyan-400 font-mono shadow-[0_0_15px_rgba(0,255,255,0.2)]"
          >
            <Terminal size={12} className="w-3 h-3" />
            <span className="tracking-widest">{t('update.dockerUpdate')}</span>
          </button>
          {renderDockerDialog()}
        </>
      )}

      {/* ── Default states: idle / checking / uptodate / check-error ── */}
      {!['available', 'confirming', 'updating', 'restarting', 'update_error', 'docker_update'].includes(
        updateStatus,
      ) && (
        <button
          onClick={checkForUpdates}
          disabled={updateStatus === 'checking'}
          className={`${btnBase} disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          {updateStatus === 'checking' && (
            <Github size={11} className="animate-spin text-cyan-400" />
          )}
          {updateStatus === 'idle' && <Github size={11} className="text-cyan-400" />}
          {updateStatus === 'uptodate' && <CheckCircle2 size={11} className="text-green-400" />}
          {updateStatus === 'error' && <AlertCircle size={11} className="text-red-400" />}

          <span className="tracking-wider">
            {updateStatus === 'checking'
              ? t('controls.checking')
              : updateStatus === 'uptodate'
                ? t('controls.upToDate')
                : updateStatus === 'error'
                  ? t('controls.checkFailed')
                  : t('controls.updates')}
          </span>
        </button>
      )}
    </div>
    </>
  );
}
