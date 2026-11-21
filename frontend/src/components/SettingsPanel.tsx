'use client';

import { API_BASE } from '@/lib/api';
import { SettingsPanelNewsFeeds } from './SettingsPanelNewsFeeds';
import { SettingsPanelApiKeys } from './SettingsPanelApiKeys';
import { SettingsPanelProtocol } from './SettingsPanelProtocol';
import { SentinelTab } from './SettingsPanelSentinelTab';
import { SarSettingsTab } from './SettingsPanelSarTab';
import { clearAdminSession, hasAdminSession, primeAdminSession } from '@/lib/adminSession';
import { controlPlaneFetch, controlPlaneJson } from '@/lib/controlPlane';
import { isNativeProtectedSettingsReady } from '@/lib/nativeProtectedSettings';
import { useTranslation } from '@/i18n';
import {
  getPrivacyProfilePreference,
  getPrivacyStrictPreference,
  getSessionModePreference,
} from '@/lib/privacyBrowserStorage';
import {
  companionDisable,
  companionEnable,
  companionOpenBrowser,
  fetchCompanionStatus,
  isNativeDesktop,
  type CompanionStatus,
} from '@/lib/desktopCompanion';
import {
  getGateCompatTelemetryEventName,
  getGateCompatTelemetrySnapshot,
  type GateCompatTelemetrySnapshot,
} from '@/mesh/gateCompatTelemetry';
import {
  getBrowserGateLocalRuntimeEventName,
  getBrowserGateLocalRuntimeStatus,
  type BrowserGateLocalRuntimeStatus,
} from '@/mesh/meshGateWorkerClient';
import {
  fetchPrivacyProfileSnapshot,
  fetchRnsStatusSnapshot,
  invalidatePrivacyProfileCache,
  invalidateRnsStatusCache,
} from '@/mesh/controlPlaneStatusClient';
import {
  clearBrowserIdentityState,
  purgeBrowserContactGraph,
  purgeBrowserSigningMaterial,
  setSecureModeCached,
} from '@/mesh/meshIdentity';
import { purgeBrowserDmState } from '@/mesh/meshDmWorkerClient';
import {
  connectWormhole,
  disconnectWormhole,
  fetchWormholeSettings,
  fetchWormholeState,
  invalidateWormholeRuntimeCache,
  joinWormhole,
  restartWormhole,
  type WormholeState,
} from '@/mesh/wormholeClient';
import {
  fetchWormholeDmRootHealth,
  fetchWormholeIdentity,
  type WormholeDmRootHealth,
} from '@/mesh/wormholeIdentityClient';
import {
  formatLegacyCompatibilitySeenAt,
  hasLegacyCompatibilityActivity,
  summarizeLegacyCompatibility,
} from '@/mesh/wormholeCompatibility';
import type {
  ApiEntry,
  FeedEntry,
  EnvMeta,
  Tab,
} from './SettingsPanel.shared';
import {
  WEIGHT_LABELS,
  WEIGHT_COLORS,
  SETTINGS_FOCUS_KEY,
  WORMHOLE_RETURN_KEY,
  WORMHOLE_READY_EVENT,
  PRIVACY_SENSITIVE_BROWSER_KEYS,
  applySecureModeBoundary,
  migratePrivacySensitiveBrowserState,
  MAX_FEEDS,
  formatFeedSettingsError,
  validateFeedEntries,
  CATEGORY_COLORS,
  dmRootMonitorTone,
  dmRootMonitorLabel,
  dmRootUrgencyTone,
  formatAgeWindow,
} from './SettingsPanel.shared';

const SettingsPanel = React.memo(function SettingsPanel({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<Tab>('api-keys');

  // Native desktop bypass: when the native IPC bridge is present, protected
  // settings are authenticated through Rust-side admin-key ownership. The
  // browser admin-session flow is unnecessary and unavailable in packaged mode.
  const nativeProtected = isNativeProtectedSettingsReady();
  const { t, locale, setLocale } = useTranslation();

  // --- Admin Key (for protected endpoints) ---
  const [adminKey, setAdminKey] = useState('');
  const [adminSessionReady, setAdminSessionReady] = useState(false);
  const [adminSessionBusy, setAdminSessionBusy] = useState(false);
  const [adminSessionMsg, setAdminSessionMsg] = useState<string | null>(null);
  const [, setStrictPrivacy] = useState(() => getPrivacyStrictPreference());
  const [privacyProfile, setPrivacyProfile] = useState(() => getPrivacyProfilePreference());
  const [sessionMode, setSessionMode] = useState(() => getSessionModePreference());
  const [browserWipeBusy, setBrowserWipeBusy] = useState(false);
  const [browserWipeMsg, setBrowserWipeMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(
    null,
  );
  const [wormholeEnabled, setWormholeEnabled] = useState(false);
  const [wormholeSaving, setWormholeSaving] = useState(false);
  const [wormholeMsg, setWormholeMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(
    null,
  );
  const [wormholeTransport, setWormholeTransport] = useState('direct');
  const [wormholeSocksProxy, setWormholeSocksProxy] = useState('');
  const [wormholeSocksDns, setWormholeSocksDns] = useState(true);
  const [wormholeAnonymousMode, setWormholeAnonymousMode] = useState(false);
  const [wormholeDirty, setWormholeDirty] = useState(false);
  const [wormholeStatus, setWormholeStatus] = useState<WormholeState | null>(null);
  const [wormholeGuideNotice, setWormholeGuideNotice] = useState<string | null>(null);
  const [showAdvancedWormhole, setShowAdvancedWormhole] = useState(false);
  const [wormholeQuickState, setWormholeQuickState] = useState<'idle' | 'ready' | 'connecting' | 'active'>('idle');
  const [showOperatorTools, setShowOperatorTools] = useState(false);
  const [wormholeNodeId, setWormholeNodeId] = useState<string | null>(null);
  const [wormholeKeyCopied, setWormholeKeyCopied] = useState(false);
  const [gateCompatTelemetry, setGateCompatTelemetry] = useState<GateCompatTelemetrySnapshot>(
    () => getGateCompatTelemetrySnapshot(),
  );
  const [gateLocalRuntimeStatus, setGateLocalRuntimeStatus] = useState<BrowserGateLocalRuntimeStatus>(
    () => getBrowserGateLocalRuntimeStatus(),
  );
  const [dmRootHealth, setDmRootHealth] = useState<WormholeDmRootHealth | null>(null);
  const [dmRootHealthBusy, setDmRootHealthBusy] = useState(false);
  const [dmRootHealthMsg, setDmRootHealthMsg] = useState<string | null>(null);

  // --- Time Machine ---
  const [tmEnabled, setTmEnabled] = useState(false);
  const [tmSaving, setTmSaving] = useState(false);

  // Fetch Time Machine status when protocol tab opens
  useEffect(() => {
    if (!isOpen || activeTab !== 'protocol') return;
    fetch(`${API_BASE}/api/settings/timemachine`)
      .then((r) => r.json())
      .then((d) => setTmEnabled(!!d.enabled))
      .catch(() => {});
  }, [isOpen, activeTab]);

  const toggleTimeMachine = useCallback(async () => {
    setTmSaving(true);
    try {
      const res = await controlPlaneFetch('/api/settings/timemachine', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !tmEnabled }),
        requireAdminSession: false,
      });
      if (res.ok) {
        const data = await res.json();
        setTmEnabled(!!data.enabled);
      }
    } catch {}
    setTmSaving(false);
  }, [tmEnabled]);

  // --- Browser Companion (desktop-only) ---
  const [companionAvailable] = useState(() => isNativeDesktop());
  const [companion, setCompanion] = useState<CompanionStatus | null>(null);
  const [companionBusy, setCompanionBusy] = useState(false);
  const [companionError, setCompanionError] = useState<string | null>(null);

  const [companionLoadFailed, setCompanionLoadFailed] = useState(false);

  useEffect(() => {
    if (!isOpen || activeTab !== 'protocol' || !companionAvailable) return;
    setCompanionLoadFailed(false);
    fetchCompanionStatus()
      .then((s) => setCompanion(s))
      .catch(() => {
        setCompanion(null);
        setCompanionLoadFailed(true);
      });
  }, [isOpen, activeTab, companionAvailable]);

  useEffect(() => {
    const refreshTelemetry = () => setGateCompatTelemetry(getGateCompatTelemetrySnapshot());
    refreshTelemetry();
    if (typeof window === 'undefined') return;
    const eventName = getGateCompatTelemetryEventName();
    window.addEventListener(eventName, refreshTelemetry as EventListener);
    return () => {
      window.removeEventListener(eventName, refreshTelemetry as EventListener);
    };
  }, []);

  useEffect(() => {
    const refreshRuntimeStatus = () => setGateLocalRuntimeStatus(getBrowserGateLocalRuntimeStatus());
    refreshRuntimeStatus();
    if (typeof window === 'undefined') return;
    const eventName = getBrowserGateLocalRuntimeEventName();
    window.addEventListener(eventName, refreshRuntimeStatus as EventListener);
    return () => {
      window.removeEventListener(eventName, refreshRuntimeStatus as EventListener);
    };
  }, []);

  const toggleCompanion = useCallback(async () => {
    setCompanionBusy(true);
    setCompanionError(null);
    try {
      const result = companion?.enabled
        ? await companionDisable()
        : await companionEnable();
      if (result) setCompanion(result);
    } catch (e) {
      setCompanionError(e instanceof Error ? e.message : String(e));
    }
    setCompanionBusy(false);
  }, [companion?.enabled]);

  const openCompanionBrowser = useCallback(async () => {
    setCompanionBusy(true);
    setCompanionError(null);
    try {
      const result = await companionOpenBrowser();
      if (result) setCompanion(result);
    } catch (e) {
      setCompanionError(e instanceof Error ? e.message : String(e));
    }
    setCompanionBusy(false);
  }, []);

  const clearSessionIdentity = () => {
    if (typeof window === 'undefined') return;
    const keys = [
      'sb_mesh_pubkey',
      'sb_mesh_privkey',
      'sb_mesh_node_id',
      'sb_mesh_sovereignty_accepted',
      'sb_mesh_dh_pubkey',
      'sb_mesh_dh_privkey',
      'sb_mesh_dh_algo',
      'sb_mesh_dh_last_ts',
      'sb_mesh_contacts',
      'sb_mesh_dm_notify',
      'sb_mesh_sequence',
      'sb_mesh_algo',
    ];
    for (const key of keys) {
      try {
        sessionStorage.removeItem(key);
      } catch {
        /* ignore */
      }
    }
  };
  const [rnsStatus, setRnsStatus] = useState<{
    enabled: boolean;
    ready: boolean;
    configured_peers: number;
    active_peers: number;
  } | null>(null);
  const wipeLocalMeshTraces = useCallback(async () => {
    setBrowserWipeBusy(true);
    setBrowserWipeMsg(null);
    try {
      await clearBrowserIdentityState();
      await purgeBrowserDmState();
      for (const key of PRIVACY_SENSITIVE_BROWSER_KEYS) {
        try {
          localStorage.removeItem(key);
          sessionStorage.removeItem(key);
        } catch {
          /* ignore */
        }
      }
      setSessionModePreference(true);
      setSessionMode(true);
      setBrowserWipeMsg({
        type: 'ok',
        text: wormholeEnabled
          ? 'Browser-held mesh traces cleared. The local Wormhole agent stays running, but this tab will need to reconnect to it.'
          : 'Browser-held mesh traces cleared from this browser.',
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'unknown error';
      setBrowserWipeMsg({
        type: 'err',
        text: `Could not clear browser-held mesh traces: ${message}`,
      });
    } finally {
      setBrowserWipeBusy(false);
    }
  }, [wormholeEnabled]);
  const refreshAdminSession = useCallback(async () => {
    // In native desktop mode, protected settings are handled through Rust IPC
    // with native admin-key ownership — no browser admin-session needed.
    if (isNativeProtectedSettingsReady()) {
      setAdminSessionReady(true);
      setAdminSessionMsg(null);
      return true;
    }
    const ready = await hasAdminSession();
    setAdminSessionReady(ready);
    if (!ready) {
      setAdminSessionMsg((prev) => (prev === 'LOCAL SESSION PRIMED' ? null : prev));
    }
    return ready;
  }, []);

  useEffect(() => {
    if (activeTab !== 'protocol') {
      setShowOperatorTools(true);
    }
  }, [activeTab]);
  const ensureAdminSession = useCallback(async () => {
    // Native desktop: already authenticated via Rust IPC admin-key ownership.
    if (isNativeProtectedSettingsReady()) {
      setAdminSessionReady(true);
      setAdminSessionMsg(null);
      return;
    }
    try {
      await primeAdminSession(adminKey.trim() || undefined);
      setAdminSessionReady(true);
      if (adminKey.trim()) {
        setAdminKey('');
        setAdminSessionMsg('LOCAL SESSION PRIMED');
      } else {
        setAdminSessionMsg(null);
      }
    } catch (e) {
      const ready = await refreshAdminSession();
      setAdminSessionReady(ready);
      const message =
        e instanceof Error && e.message === 'admin_session_required'
          ? 'ADMIN SESSION REQUIRED'
          : e instanceof Error
            ? e.message
            : 'ADMIN SESSION FAILED';
      setAdminSessionMsg(message);
      throw e;
    }
  }, [adminKey, refreshAdminSession]);

  // --- API Keys state ---
  // API keys are write-only in-app. Values are sent once to the local backend,
  // stored server-side, and never returned to the browser.
  const [apis, setApis] = useState<ApiEntry[]>([]);
  const [apiKeyInputs, setApiKeyInputs] = useState<Record<string, string>>({});
  const [apiKeyEditing, setApiKeyEditing] = useState<Record<string, boolean>>({});
  const [apiKeySaving, setApiKeySaving] = useState<string | null>(null);
  const [apiKeyMsg, setApiKeyMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set(['Aviation', 'Maritime']),
  );
  const [envMeta, setEnvMeta] = useState<EnvMeta | null>(null);

  // --- News Feeds state ---
  const [feeds, setFeeds] = useState<FeedEntry[]>([]);
  const [feedsDirty, setFeedsDirty] = useState(false);
  const [feedSaving, setFeedSaving] = useState(false);
  const [feedMsg, setFeedMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const handleProtectedSettingsError = useCallback(
    async (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Protected settings request failed';
      if (
        message === 'Forbidden — admin key not configured' ||
        message === 'Forbidden — invalid or missing admin key'
      ) {
        await clearAdminSession();
        setAdminSessionReady(false);
        setAdminSessionMsg(
          message === 'Forbidden — admin key not configured'
            ? 'BACKEND ADMIN KEY NOT CONFIGURED'
            : 'ADMIN KEY INVALID OR EXPIRED',
        );
        setApis([]);
        setFeeds([]);
        setFeedsDirty(false);
        setDmRootHealth(null);
        setDmRootHealthMsg(message);
      }
      return message;
    },
    [],
  );

  const fetchKeys = useCallback(async () => {
    try {
      setApis(await controlPlaneJson<ApiEntry[]>('/api/settings/api-keys', {
        requireAdminSession: false,
      }));
      return true;
    } catch (e) {
      await handleProtectedSettingsError(e);
      return false;
    }
  }, [handleProtectedSettingsError]);

  const saveApiKey = useCallback(
    async (envKey: string | null) => {
      if (!envKey) return;
      const value = String(apiKeyInputs[envKey] || '').trim();
      if (!value) {
        setApiKeyMsg({ type: 'err', text: `Enter a value for ${envKey}.` });
        return;
      }
      setApiKeySaving(envKey);
      setApiKeyMsg(null);
      try {
        const result = await controlPlaneJson<{
          keys?: ApiEntry[];
          env?: EnvMeta;
        }>('/api/settings/api-keys', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [envKey]: value }),
          requireAdminSession: false,
        });
        if (result.keys) setApis(result.keys);
        if (result.env) setEnvMeta(result.env);
        setApiKeyInputs((prev) => ({ ...prev, [envKey]: '' }));
        setApiKeyEditing((prev) => ({ ...prev, [envKey]: false }));
        setApiKeyMsg({ type: 'ok', text: `${envKey} saved locally. Restart or refresh feeds to use it.` });
      } catch (e) {
        const message = e instanceof Error ? e.message : 'Could not save API key';
        setApiKeyMsg({ type: 'err', text: message });
      } finally {
        setApiKeySaving(null);
      }
    },
    [apiKeyInputs],
  );

  const fetchEnvMeta = useCallback(async () => {
    try {
      const res = await fetch('/api/settings/api-keys/meta');
      if (!res.ok) return;
      const data: EnvMeta = await res.json();
      setEnvMeta(data);
    } catch {
      // Non-fatal: the panel still works without the path hint.
    }
  }, []);

  const fetchFeeds = useCallback(async () => {
    try {
      setFeeds(
        await controlPlaneJson<FeedEntry[]>('/api/settings/news-feeds', {
          requireAdminSession: false,
        }),
      );
      setFeedsDirty(false);
      return true;
    } catch (e) {
      await handleProtectedSettingsError(e);
      return false;
    }
  }, [handleProtectedSettingsError]);

  const fetchWormhole = useCallback(async () => {
    try {
      const data = await fetchWormholeSettings(true);
      setWormholeEnabled(Boolean(data?.enabled));
      await applySecureModeBoundary(Boolean(data?.enabled));
      setWormholeTransport(String(data?.transport || 'direct'));
      setWormholeSocksProxy(String(data?.socks_proxy || ''));
      setWormholeSocksDns(Boolean(data?.socks_dns ?? true));
      setWormholeAnonymousMode(Boolean(data?.anonymous_mode));
      setWormholeDirty(false);
    } catch (e) {
      console.error('Failed to fetch wormhole settings', e);
    }
  }, []);

  const fetchPrivacyProfile = useCallback(async () => {
    try {
      const data = await fetchPrivacyProfileSnapshot(true);
      const profile = String(data?.profile || 'default');
      setPrivacyProfile(profile);
      if (typeof data?.wormhole_enabled === 'boolean') {
        setWormholeEnabled(Boolean(data.wormhole_enabled));
        await applySecureModeBoundary(Boolean(data.wormhole_enabled));
      }
      const high = profile === 'high';
      setStrictPrivacy(high);
      const nextSessionMode = high || getSessionModePreference();
      setSessionMode(nextSessionMode);
      setSessionModePreference(nextSessionMode);
      setPrivacyStrictPreference(high, { sessionMode: nextSessionMode });
      setPrivacyProfilePreference(profile, { sessionMode: nextSessionMode });
      migratePrivacySensitiveBrowserState();
    } catch (e) {
      console.error('Failed to fetch privacy profile', e);
    }
  }, []);

  const fetchRnsStatus = useCallback(async () => {
    try {
      setRnsStatus(await fetchRnsStatusSnapshot(true));
    } catch (e) {
      console.error('Failed to fetch RNS status', e);
    }
  }, []);

  const fetchWormholeStatus = useCallback(async () => {
    try {
      const state = await fetchWormholeState(true);
      setWormholeStatus(state);
      if (state.ready && !wormholeNodeId) {
        try {
          const id = await fetchWormholeIdentity();
          if (id?.node_id) setWormholeNodeId(id.node_id);
        } catch { /* identity fetch is best-effort */ }
      }
    } catch (e) {
      console.error('Failed to fetch wormhole status', e);
    }
  }, [wormholeNodeId]);

  const fetchDmRootHealth = useCallback(async () => {
    if (!nativeProtected && !adminSessionReady) {
      setDmRootHealth(null);
      setDmRootHealthMsg(null);
      return false;
    }
    setDmRootHealthBusy(true);
    setDmRootHealthMsg(null);
    try {
      const data = await fetchWormholeDmRootHealth();
      setDmRootHealth(data);
      return true;
    } catch (e) {
      const message = await handleProtectedSettingsError(e);
      setDmRootHealth(null);
      setDmRootHealthMsg(message);
      return false;
    } finally {
      setDmRootHealthBusy(false);
    }
  }, [adminSessionReady, handleProtectedSettingsError, nativeProtected]);

  useEffect(() => {
    if (isOpen) {
      if (typeof window !== 'undefined') {
        const focusTarget = sessionStorage.getItem(SETTINGS_FOCUS_KEY);
        if (focusTarget === 'wormhole-gates') {
          setActiveTab('protocol');
          setWormholeGuideNotice(
            'Gates use the Wormhole-backed experimental obfuscation lane. Press GET WORMHOLE KEY and we will walk the rest from here.',
          );
          sessionStorage.removeItem(SETTINGS_FOCUS_KEY);
        } else {
          setWormholeGuideNotice(null);
        }
      }
      void (async () => {
        const ready = await refreshAdminSession();
        await fetchKeys();
        if (ready) {
          await fetchFeeds();
        } else {
          setFeeds([]);
          setFeedsDirty(false);
        }
        void fetchWormhole();
        void fetchRnsStatus();
        void fetchPrivacyProfile();
        void fetchWormholeStatus();
      })();
    }
  }, [
    isOpen,
    fetchKeys,
    fetchFeeds,
    fetchWormhole,
    fetchRnsStatus,
    fetchPrivacyProfile,
    fetchWormholeStatus,
    refreshAdminSession,
  ]);

  useEffect(() => {
    if (!wormholeEnabled) {
      setWormholeQuickState('idle');
      return;
    }
    if (wormholeStatus?.ready) {
      setWormholeQuickState('active');
      if (typeof window !== 'undefined') {
        const returnTarget = sessionStorage.getItem(WORMHOLE_RETURN_KEY);
        if (returnTarget) {
          sessionStorage.removeItem(WORMHOLE_RETURN_KEY);
          sessionStorage.removeItem(SETTINGS_FOCUS_KEY);
          window.dispatchEvent(new CustomEvent(WORMHOLE_READY_EVENT, { detail: { target: returnTarget } }));
          onClose();
        }
      }
      return;
    }
    if (wormholeSaving || wormholeStatus?.running) {
      setWormholeQuickState('connecting');
      return;
    }
    setWormholeQuickState('ready');
  }, [onClose, wormholeEnabled, wormholeSaving, wormholeStatus]);

  useEffect(() => {
    if (!isOpen) return;
    if (activeTab === 'api-keys') {
      void fetchKeys();
      void fetchEnvMeta();
      return;
    }
    if (activeTab === 'news-feeds') {
      void fetchFeeds();
    }
  }, [isOpen, activeTab, fetchKeys, fetchEnvMeta, fetchFeeds]);

  useEffect(() => {
    if (!isOpen || activeTab !== 'protocol' || !showOperatorTools) return;
    if (!nativeProtected && !adminSessionReady) {
      setDmRootHealth(null);
      setDmRootHealthMsg(null);
      return;
    }
    void fetchDmRootHealth();
  }, [
    isOpen,
    activeTab,
    showOperatorTools,
    nativeProtected,
    adminSessionReady,
    fetchDmRootHealth,
  ]);

  const toggleCategory = (cat: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const grouped = apis.reduce<Record<string, ApiEntry[]>>((acc, api) => {
    if (!acc[api.category]) acc[api.category] = [];
    acc[api.category].push(api);
    return acc;
  }, {});

  // News Feeds handlers
  const updateFeed = (idx: number, field: keyof FeedEntry, value: string | number) => {
    setFeeds((prev) => prev.map((f, i) => (i === idx ? { ...f, [field]: value } : f)));
    setFeedsDirty(true);
    setFeedMsg(null);
  };

  const removeFeed = (idx: number) => {
    setFeeds((prev) => prev.filter((_, i) => i !== idx));
    setFeedsDirty(true);
    setFeedMsg(null);
  };

  const addFeed = () => {
    if (feeds.length >= MAX_FEEDS) return;
    setFeeds((prev) => [...prev, { name: '', url: '', weight: 3 }]);
    setFeedsDirty(true);
    setFeedMsg(null);
  };

  const saveFeeds = async () => {
    const validationError = validateFeedEntries(feeds);
    if (validationError) {
      setFeedMsg({ type: 'err', text: validationError });
      return;
    }
    setFeedSaving(true);
    setFeedMsg(null);
    try {
      const res = await controlPlaneFetch('/api/settings/news-feeds', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(feeds),
        requireAdminSession: false,
      });
      if (res.ok) {
        setFeedsDirty(false);
        setFeedMsg({
          type: 'ok',
          text: 'Feeds saved. Changes take effect on next news refresh (~30min) or manual /api/refresh.',
        });
      } else {
        const d = await res.json().catch(() => ({}));
        setFeedMsg({
          type: 'err',
          text: String(d.message || d.detail || 'Save failed'),
        });
      }
    } catch (error) {
      setFeedMsg({
        type: 'err',
        text: formatFeedSettingsError(error, 'Could not reach the settings API'),
      });
    } finally {
      setFeedSaving(false);
    }
  };

  const resetFeeds = async () => {
    setFeedMsg(null);
    try {
      const res = await controlPlaneFetch('/api/settings/news-feeds/reset', {
        method: 'POST',
        requireAdminSession: false,
      });
      if (res.ok) {
        const d = await res.json();
        setFeeds(d.feeds || []);
        setFeedsDirty(false);
        setFeedMsg({ type: 'ok', text: 'Reset to defaults' });
      } else {
        const d = await res.json().catch(() => ({}));
        setFeedMsg({
          type: 'err',
          text: String(d.message || d.detail || 'Reset failed'),
        });
      }
    } catch (error) {
      setFeedMsg({
        type: 'err',
        text: formatFeedSettingsError(error, 'Could not reach the settings API'),
      });
    }
  };

  const saveWormholeSettings = async (enabledOverride?: boolean) => {
    setWormholeSaving(true);
    setWormholeMsg(null);
    try {
      invalidateWormholeRuntimeCache();
      const next = typeof enabledOverride === 'boolean' ? enabledOverride : wormholeEnabled;
      const res = await controlPlaneFetch('/api/settings/wormhole', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: next,
          transport: wormholeTransport,
          socks_proxy: wormholeSocksProxy,
          socks_dns: wormholeSocksDns,
          anonymous_mode: wormholeAnonymousMode,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        invalidateWormholeRuntimeCache();
        setWormholeEnabled(Boolean(data?.enabled));
        await applySecureModeBoundary(Boolean(data?.enabled));
        setWormholeTransport(String(data?.transport || wormholeTransport));
        setWormholeSocksProxy(String(data?.socks_proxy || wormholeSocksProxy));
        setWormholeSocksDns(Boolean(data?.socks_dns ?? wormholeSocksDns));
        setWormholeAnonymousMode(Boolean(data?.anonymous_mode ?? wormholeAnonymousMode));
        setWormholeDirty(false);
        if (data?.runtime) setWormholeStatus(data.runtime as WormholeState);
        setWormholeMsg({
          type: 'ok',
          text: next
            ? data?.runtime?.ready
              ? 'Local agent connected with the updated settings.'
              : 'Settings saved. Local agent is starting.'
            : 'Local agent disabled and disconnected.',
        });
      } else {
        setWormholeMsg({ type: 'err', text: 'Failed to update local agent settings' });
      }
    } catch {
      setWormholeMsg({ type: 'err', text: 'Network error updating local agent settings' });
    } finally {
      setWormholeSaving(false);
    }
  };

  const toggleWormhole = async () => {
    await saveWormholeSettings(!wormholeEnabled);
  };

  const quickStartWormhole = async () => {
    setWormholeSaving(true);
    setWormholeQuickState('ready');
    setWormholeMsg(null);
    try {
      const data = await joinWormhole();
      invalidateWormholeRuntimeCache();
      if (data?.identity?.node_id) {
        setWormholeNodeId(data.identity.node_id);
      }
      setWormholeEnabled(Boolean(data?.settings?.enabled ?? data?.runtime?.configured ?? true));
      setWormholeTransport(String(data?.settings?.transport || 'direct'));
      setWormholeSocksProxy(String(data?.settings?.socks_proxy || ''));
      setWormholeSocksDns(Boolean(data?.settings?.socks_dns ?? true));
      setWormholeAnonymousMode(Boolean(data?.settings?.anonymous_mode ?? false));
      setWormholeDirty(false);
      await applySecureModeBoundary(true);
      setWormholeQuickState('connecting');
      const runtime = (data?.runtime as WormholeState | undefined) ?? (await fetchWormholeState(true));
      invalidateWormholeRuntimeCache();
      setWormholeStatus(runtime);
      setWormholeEnabled(Boolean(runtime.configured));
      setWormholeQuickState(runtime.ready ? 'active' : 'connecting');
      setWormholeMsg({
        type: 'ok',
        text: runtime.ready
          ? 'Wormhole key ready. Gates and the obfuscated inbox can open now.'
          : 'Wormhole key is provisioning. Wait for LOCAL AGENT ACTIVE.',
      });
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Wormhole quick start failed';
      setWormholeMsg({ type: 'err', text: message });
      setWormholeQuickState('idle');
    } finally {
      setWormholeSaving(false);
    }
  };

  const controlWormhole = async (action: 'connect' | 'disconnect' | 'restart') => {
    setWormholeSaving(true);
    setWormholeMsg(null);
    try {
      await ensureAdminSession();
      const runtime =
        action === 'connect'
          ? await connectWormhole()
          : action === 'disconnect'
            ? await disconnectWormhole()
            : await restartWormhole();
      invalidateWormholeRuntimeCache();
      setWormholeStatus(runtime);
      setWormholeEnabled(Boolean(runtime.configured));
      await applySecureModeBoundary(Boolean(runtime.configured));
      setWormholeMsg({
        type: 'ok',
        text:
          action === 'disconnect'
            ? 'Local agent disconnected.'
            : runtime.ready
              ? `Local agent ${action === 'restart' ? 'restarted' : 'connected'}.`
              : 'Local agent is starting. Mesh actions will unlock when ready.',
      });
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Local agent request failed';
      setWormholeMsg({ type: 'err', text: message });
    } finally {
      setWormholeSaving(false);
    }
  };

  const setHighPrivacy = async (enabled: boolean) => {
    const profile = enabled ? 'high' : 'default';
    const nextSessionMode = enabled || getSessionModePreference();
    setSessionModePreference(nextSessionMode);
    setPrivacyStrictPreference(enabled, { sessionMode: nextSessionMode });
    setPrivacyProfilePreference(profile, { sessionMode: nextSessionMode });
    setPrivacyProfile(profile);
    setStrictPrivacy(enabled);
    setSessionMode(nextSessionMode);
    migratePrivacySensitiveBrowserState();
    if (nextSessionMode) clearSessionIdentity();
    try {
      const res = await controlPlaneFetch('/api/settings/privacy-profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile }),
      });
      if (!res.ok) {
        setWormholeMsg({ type: 'err', text: 'Failed to save privacy profile' });
      } else {
        invalidatePrivacyProfileCache();
        invalidateRnsStatusCache();
        const data = await res.json().catch(() => ({}));
        const forcedWormhole = Boolean(data?.wormhole_enabled);
        if (forcedWormhole) {
          setWormholeEnabled(true);
          await applySecureModeBoundary(true);
        }
        setWormholeMsg({
          type: 'ok',
          text: forcedWormhole
            ? 'High Privacy requires the local agent. It was enabled for this device.'
            : 'Privacy profile saved.',
        });
      }
    } catch {
      setWormholeMsg({ type: 'err', text: 'Failed to save privacy profile' });
    }
  };

  const unlockAdminSession = async () => {
    setAdminSessionBusy(true);
    setAdminSessionMsg(null);
    try {
      await ensureAdminSession();
      await Promise.all([fetchKeys(), fetchFeeds()]);
    } catch (e) {
      const message = e instanceof Error ? e.message : 'ADMIN SESSION FAILED';
      if (message === 'Forbidden — admin key not configured') {
        await clearAdminSession();
        setAdminSessionReady(false);
        setAdminSessionMsg('BACKEND ADMIN KEY NOT CONFIGURED');
        return;
      }
      setAdminSessionMsg(message.toUpperCase());
    } finally {
      setAdminSessionBusy(false);
    }
  };

  const lockAdminSession = async () => {
    setAdminSessionBusy(true);
    setAdminSessionMsg(null);
    try {
      await clearAdminSession();
      setAdminKey('');
      setAdminSessionReady(false);
      setDmRootHealth(null);
      setDmRootHealthMsg(null);
      setAdminSessionMsg('LOCAL SESSION CLEARED');
    } finally {
      setAdminSessionBusy(false);
    }
  };

  const configuredTransport = (wormholeStatus?.transport || wormholeTransport || '').toLowerCase();
  const activeTransport = (wormholeStatus?.transport_active || '').toLowerCase();
  const effectiveTransport = activeTransport || configuredTransport || 'direct';
  const anonModeReady =
    Boolean(wormholeEnabled) &&
    Boolean(wormholeStatus?.ready) &&
    ['tor', 'tor_arti', 'i2p', 'mixnet'].includes(effectiveTransport) &&
    wormholeAnonymousMode;
  const rnsReady = Boolean(wormholeStatus?.rns_ready ?? rnsStatus?.ready);
  const recentPrivateFallback = Boolean(wormholeStatus?.recent_private_clearnet_fallback);
  const recentPrivateFallbackReason =
    wormholeStatus?.recent_private_clearnet_fallback_reason ||
    'An obfuscated-tier payload recently fell back to clearnet relay.';
  const legacyCompatibilityItems = summarizeLegacyCompatibility(wormholeStatus?.legacy_compatibility);
  const legacyCompatibilityActivity = hasLegacyCompatibilityActivity(
    wormholeStatus?.legacy_compatibility,
  );
  const legacyCompatibilityAllBlocked =
    legacyCompatibilityItems.length > 0 && legacyCompatibilityItems.every((item) => item.blocked);
  const gateCompatTopReasons = summarizeGateCompatTelemetry(gateCompatTelemetry, 3);
  const trustModeLabel = !wormholeEnabled
    ? 'PUBLIC / DEGRADED'
    : wormholeStatus?.ready && rnsReady
      ? 'EXPERIMENTAL / OBFUSCATED+'
      : 'EXPERIMENTAL / OBFUSCATED';
  const transportMismatch =
    Boolean(activeTransport) && Boolean(configuredTransport) && activeTransport !== configuredTransport;
  const wormholeQuickButtonLabel =
    wormholeQuickState === 'active'
      ? 'ACTIVE'
      : wormholeQuickState === 'connecting'
        ? 'CONNECTING'
        : wormholeQuickState === 'ready'
          ? 'READY'
          : 'GET WORMHOLE KEY';
  const dmRootCardTone = dmRootMonitorTone(
    showOperatorTools
      ? dmRootHealth?.monitoring?.state || (dmRootHealthMsg ? 'critical' : 'warning')
      : 'warning',
  );

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/70 backdrop-blur-sm z-[9998]"
            onClick={onClose}
          />

          {/* Settings Panel */}
          <motion.div
            initial={{ opacity: 0, x: -300 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -300 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="sb-drawer fixed left-0 top-0 bottom-0 w-[540px] max-w-[calc(100vw-24px)] z-[9999] flex flex-col overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-[var(--border-primary)]/80">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center">
                  <Settings size={16} className="text-cyan-400" />
                </div>
                <div>
                  <h2 className="sb-modal-title">
                    {t('settings.title').toUpperCase()}
                  </h2>
                  <span className="text-[11px] text-[var(--text-muted)] font-mono tracking-[0.18em] whitespace-nowrap">
                    SETTINGS &amp; DATA SOURCES
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {/*
                  UI language toggle. Locale change is purely client-side
                  (persists to localStorage('sb_locale')) — no network call,
                  no telemetry. See frontend/src/i18n/index.ts for the list
                  of available locales and CONTRIBUTING.md for the
                  translation-neutrality policy.
                */}
                <label
                  htmlFor="sb-locale-select"
                  className="text-[11px] tracking-[0.18em] uppercase text-[var(--text-muted)] font-mono"
                >
                  LANG
                </label>
                <select
                  id="sb-locale-select"
                  value={locale}
                  onChange={(e) => setLocale(e.target.value as Locale)}
                  aria-label="UI language"
                  className="h-8 px-2 border border-[var(--border-primary)] bg-[var(--bg-primary)]/60 text-[12px] font-mono text-[var(--text-secondary)] tracking-wider hover:border-cyan-500/50 focus:outline-none focus:border-cyan-500/80 transition-colors"
                >
                  {LOCALES.map((entry) => (
                    <option key={entry.code} value={entry.code}>
                      {entry.label}
                    </option>
                  ))}
                </select>
                <button
                  onClick={onClose}
                  className="w-8 h-8 border border-[var(--border-primary)] hover:border-red-500/50 flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 transition-all hover:bg-red-950/20"
                >
                  <X size={14} />
                </button>
              </div>
            </div>

            {/* Operator Tools */}
            {activeTab === 'protocol' && !showOperatorTools ? (
              <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-[var(--border-primary)]/40 bg-[var(--bg-primary)]/30">
                <div className="flex items-center gap-2 min-w-0">
                  <Shield size={12} className="text-cyan-400" />
                  <div className="min-w-0">
                    <div className="text-[13px] font-mono tracking-widest text-cyan-300">WORMHOLE FIRST-RUN</div>
                    <div className="text-[12px] font-mono text-[var(--text-muted)] mt-0.5">
                      Wormhole join below does not need operator tools. API/news tabs do.
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => setShowOperatorTools(true)}
                  className="px-2 py-1 border border-cyan-500/30 text-[12px] font-mono text-cyan-300/80 tracking-widest hover:text-cyan-200 hover:border-cyan-400/40"
                >
                  OPERATOR TOOLS
                </button>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--border-primary)]/40 bg-[var(--bg-primary)]/30">
                  <Shield
                    size={12}
                    className={adminSessionReady ? 'text-green-400' : 'text-yellow-500'}
                  />
                  <span className="text-[13px] font-mono tracking-widest text-[var(--text-muted)] whitespace-nowrap">
                    OPERATOR TOOLS
                  </span>
                  <input
                    type="password"
                    value={adminKey}
                    onChange={(e) => setAdminKey(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && adminKey.trim() && !adminSessionBusy) {
                        void unlockAdminSession();
                      }
                    }}
                    disabled={nativeProtected}
                    placeholder={
                      nativeProtected
                        ? 'Protected via native desktop bridge'
                        : adminSessionReady
                          ? 'Unlocked · key only to reseed'
                          : 'Operator key…'
                    }
                    className="flex-1 min-w-0 bg-[var(--bg-primary)]/60 border border-[var(--border-primary)] px-2 py-1 text-sm font-mono text-[var(--text-secondary)] outline-none focus:border-cyan-700 placeholder:text-[var(--text-muted)]/50"
                  />
                  {nativeProtected ? null : adminSessionReady ? (
                    <button
                      onClick={() => void lockAdminSession()}
                      disabled={adminSessionBusy}
                      className="px-2 py-1 border border-red-500/30 text-[12px] font-mono text-red-300/80 tracking-widest hover:text-red-200 hover:border-red-400/40 disabled:opacity-50"
                    >
                      LOCK
                    </button>
                  ) : (
                    <button
                      onClick={() => void unlockAdminSession()}
                      disabled={adminSessionBusy || !adminKey.trim()}
                      className="px-2 py-1 border border-cyan-500/30 text-[12px] font-mono text-cyan-300/80 tracking-widest hover:text-cyan-200 hover:border-cyan-400/40 disabled:opacity-50"
                    >
                      UNLOCK
                    </button>
                  )}
                  {activeTab === 'protocol' && (
                    <button
                      onClick={() => setShowOperatorTools(false)}
                      className="px-2 py-1 border border-[var(--border-primary)] text-[12px] font-mono text-[var(--text-muted)] tracking-widest hover:text-cyan-300 hover:border-cyan-500/40"
                    >
                      HIDE
                    </button>
                  )}
                  <span
                    className={`shrink-0 px-1.5 py-0.5 rounded-md border text-[10px] font-mono tracking-widest ${
                      adminSessionReady ? 'text-green-400/80 border-green-500/30' : 'text-yellow-400/80 border-yellow-500/30'
                    }`}
                  >
                    {nativeProtected ? 'NATIVE' : adminSessionReady ? 'ACTIVE' : 'LOCKED'}
                  </span>
                </div>
                {adminSessionMsg && (
                  <div className="px-4 py-1.5 border-b border-[var(--border-primary)]/20 bg-[var(--bg-primary)]/20">
                    <span
                      className={`text-[12px] font-mono tracking-widest ${
                        adminSessionReady ? 'text-green-300/80' : 'text-yellow-300/80'
                      }`}
                    >
                      {adminSessionMsg}
                    </span>
                  </div>
                )}
              </>
            )}
            {adminSessionMsg === 'BACKEND ADMIN KEY NOT CONFIGURED' && activeTab !== 'protocol' && (
              <div className="mx-4 mt-3 border border-yellow-500/25 bg-yellow-950/10 px-3 py-3 text-sm font-mono text-yellow-200/90 leading-relaxed">
                <div>
                  This is not an old market/API key problem. The backend admin secret itself is
                  not configured, so protected Settings tabs cannot load.
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    onClick={() => {
                      const el = document.querySelector<HTMLInputElement>('input[type="password"]');
                      el?.focus();
                    }}
                    className="px-3 py-1.5 border border-yellow-400/40 bg-yellow-950/20 text-[13px] font-mono tracking-[0.18em] text-yellow-200 hover:bg-yellow-950/30"
                  >
                    PASTE ADMIN KEY
                  </button>
                  <button
                    onClick={() => setActiveTab('protocol')}
                    className="px-3 py-1.5 border border-cyan-500/35 bg-cyan-950/18 text-[13px] font-mono tracking-[0.18em] text-cyan-200 hover:bg-cyan-950/28"
                  >
                    BACK TO WORMHOLE
                  </button>
                </div>
                <div className="mt-3 text-[13px] text-yellow-100/70">
                  Add <span className="text-cyan-300">ADMIN_KEY</span> to{' '}
                  <span className="text-cyan-300">backend/.env</span>, restart the backend, then
                  paste that same key above and unlock.
                </div>
              </div>
            )}

            <div className="grid grid-cols-5 min-w-0 shrink-0 border-b border-[var(--border-primary)]/60">
              <button
                onClick={() => setActiveTab('api-keys')}
                className={`min-w-0 px-1.5 py-3 text-[12px] font-mono tracking-wide font-bold transition-colors flex items-center justify-center gap-1 ${activeTab === 'api-keys' ? 'text-cyan-400 border-b-2 border-cyan-500 bg-cyan-950/10' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
              >
                <Key size={13} className="shrink-0" />
                <span className="truncate">{t('settings.general').toUpperCase()}</span>
              </button>
              <button
                onClick={() => setActiveTab('news-feeds')}
                className={`min-w-0 px-1.5 py-3 text-[12px] font-mono tracking-wide font-bold transition-colors flex items-center justify-center gap-1 ${activeTab === 'news-feeds' ? 'text-orange-400 border-b-2 border-orange-500 bg-orange-950/10' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
              >
                <Rss size={13} className="shrink-0" />
                <span className="truncate">{t('settings.feeds').toUpperCase()}</span>
                {feedsDirty && (
                  <span className="w-1.5 h-1.5 shrink-0 rounded-full bg-orange-400 animate-pulse" />
                )}
              </button>
              <button
                onClick={() => setActiveTab('sentinel')}
                className={`min-w-0 px-1.5 py-3 text-[12px] font-mono tracking-wide font-bold transition-colors flex items-center justify-center gap-1 ${activeTab === 'sentinel' ? 'text-purple-400 border-b-2 border-purple-500 bg-purple-950/10' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
              >
                <Satellite size={13} className="shrink-0" />
                <span className="truncate">SENTINEL</span>
              </button>
              <button
                onClick={() => setActiveTab('sar')}
                className={`min-w-0 px-1.5 py-3 text-[12px] font-mono tracking-wide font-bold transition-colors flex items-center justify-center gap-1 ${activeTab === 'sar' ? 'text-amber-400 border-b-2 border-amber-500 bg-amber-950/10' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
              >
                <Radar size={13} className="shrink-0" />
                <span className="truncate">{t('settings.sar').toUpperCase()}</span>
              </button>
              <button
                onClick={() => setActiveTab('protocol')}
                className={`min-w-0 px-1.5 py-3 text-[12px] font-mono tracking-wide font-bold transition-colors flex items-center justify-center gap-1 ${activeTab === 'protocol' ? 'text-green-400 border-b-2 border-green-500 bg-green-950/10' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
              >
                <Shield size={13} className="shrink-0" />
                <span className="truncate">{t('settings.infonet').toUpperCase()}</span>
              </button>
            </div>

            {/* ==================== API KEYS TAB ==================== */}
            {/* ==================== MESH PROTOCOL TAB ==================== */}
            {activeTab === 'protocol' && (
              <SettingsPanelProtocol ctx={{ adminSessionReady, showOperatorTools, envMeta, apis, t, locale, setLocale, activeTab, setActiveTab,
                wormholeState, wormholeSettings, wormholeLoading, wormholeError, wormholeDmRootHealth, rnsStatus,
                privacyProfile, privacyStrict, sessionMode, desktopCompanion, sentinelStatus, sentinelMigrated,
                handleConnect, handleDisconnect, handleRestart, handleJoin, handleSaveWormhole, refreshWormhole,
                handlePrivacyProfileChange, handlePrivacyStrictChange, handleSessionModeChange,
                openNodeModal, setOpenNodeModal, nodeModalMode, setNodeModalMode, copyToClipboard, copied,
                fetchKeys, fetchFeeds, fetchEnvMeta, fetchWormhole, fetchRns, fetchPrivacyProfile, fetchSentinelStatus,
                CATEGORY_COLORS, WEIGHT_COLORS, WEIGHT_LABELS, MAX_FEEDS,
                apiKeyInputs, apiKeyEditing, apiKeySaving, apiKeyMsg, setApiKeyInputs, setApiKeyEditing, setApiKeySaving, setApiKeyMsg,
                feedMsg, feedsDirty, feedSaving, feeds, updateFeed, removeFeed, addFeed, saveFeeds, resetFeeds,
                saved, editedKeys, revealedKeys, saving, handleKeyChange, handleSave, handleClear, copyEnvLine, categories,
              }} />
            )}

            {activeTab === 'api-keys' && (
              <SettingsPanelApiKeys
                ctx={{
                  envMeta, apis, categories, saved, editedKeys, revealedKeys, saving, t,
                  handleKeyChange, handleSave, handleClear, copyEnvLine, fetchKeys,
                  adminSessionReady, showOperatorTools, apiKeyInputs, apiKeyEditing, apiKeySaving, apiKeyMsg,
                  setApiKeyInputs, setApiKeyEditing, setApiKeySaving, setApiKeyMsg,
                  CATEGORY_COLORS,
                }}
              />
            )}

            {/* ==================== NEWS FEEDS TAB ==================== */}
            {activeTab === 'news-feeds' && (
              <SettingsPanelNewsFeeds
                feeds={feeds}
                feedMsg={feedMsg}
                feedsDirty={feedsDirty}
                feedSaving={feedSaving}
                updateFeed={updateFeed}
                removeFeed={removeFeed}
                addFeed={addFeed}
                saveFeeds={saveFeeds}
                resetFeeds={resetFeeds}
              />
            )}
            {activeTab === 'sentinel' && (
              <SentinelTab onGoToApiKeys={() => setActiveTab('api-keys')} />
            )}
            {activeTab === 'sar' && <SarSettingsTab />}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
});


export default SettingsPanel;
