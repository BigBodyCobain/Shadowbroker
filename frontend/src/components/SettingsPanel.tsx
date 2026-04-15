'use client';

import { API_BASE } from '@/lib/api';
import { clearAdminSession, hasAdminSession, primeAdminSession } from '@/lib/adminSession';
import { controlPlaneFetch, controlPlaneJson } from '@/lib/controlPlane';
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
import { fetchWormholeIdentity } from '@/mesh/wormholeIdentityClient';
import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Settings,
  ExternalLink,
  Key,
  Shield,
  X,
  Save,
  ChevronDown,
  ChevronUp,
  Rss,
  Plus,
  Trash2,
  RotateCcw,
  Satellite,
  Eye,
  EyeOff,
  Copy,
  Check,
} from 'lucide-react';
import {
  clearSentinelCredentials,
  getSentinelCredentialStorageMode,
  getSentinelCredentials,
  setSentinelCredentials,
} from '@/lib/sentinelHub';
import {
  getPrivacyProfilePreference,
  getPrivacyStrictPreference,
  getSessionModePreference,
  migrateSensitiveBrowserItems,
  setPrivacyProfilePreference,
  setPrivacyStrictPreference,
  setSessionModePreference,
} from '@/lib/privacyBrowserStorage';

interface ApiEntry {
  id: string;
  name: string;
  description: string;
  category: string;
  url: string | null;
  required: boolean;
  has_key: boolean;
  env_key: string | null;
  value_obfuscated: string | null;
  is_set: boolean;
}

interface FeedEntry {
  name: string;
  url: string;
  weight: number;
}

const WEIGHT_LABELS: Record<number, string> = {
  1: 'LOW',
  2: 'MED',
  3: 'STD',
  4: 'HIGH',
  5: 'CRIT',
};
const WEIGHT_COLORS: Record<number, string> = {
  1: 'text-gray-400 border-gray-600',
  2: 'text-blue-400 border-blue-600',
  3: 'text-cyan-400 border-cyan-600',
  4: 'text-orange-400 border-orange-600',
  5: 'text-red-400 border-red-600',
};
const SETTINGS_FOCUS_KEY = 'sb_settings_focus';
const WORMHOLE_RETURN_KEY = 'sb_wormhole_return_target';
const WORMHOLE_READY_EVENT = 'sb:wormhole-ready';
const PRIVACY_SENSITIVE_BROWSER_KEYS = [
  'sb_sentinel_client_id',
  'sb_sentinel_client_secret',
  'sb_sentinel_instance_id',
  'sb_infonet_head',
  'sb_infonet_head_history',
  'sb_infonet_peers',
] as const;

async function applySecureModeBoundary(enabled: boolean): Promise<void> {
  setSecureModeCached(enabled);
  if (!enabled) return;
  purgeBrowserSigningMaterial();
  purgeBrowserContactGraph();
  await purgeBrowserDmState();
}

function migratePrivacySensitiveBrowserState(): void {
  migrateSensitiveBrowserItems([...PRIVACY_SENSITIVE_BROWSER_KEYS]);
}

const MAX_FEEDS = 50;

// Category colors for the tactical UI
const CATEGORY_COLORS: Record<string, string> = {
  Aviation: 'text-cyan-400 border-cyan-500/30 bg-cyan-950/20',
  Maritime: 'text-blue-400 border-blue-500/30 bg-blue-950/20',
  Geophysical: 'text-orange-400 border-orange-500/30 bg-orange-950/20',
  Space: 'text-purple-400 border-purple-500/30 bg-purple-950/20',
  Intelligence: 'text-red-400 border-red-500/30 bg-red-950/20',
  Geolocation: 'text-green-400 border-green-500/30 bg-green-950/20',
  Weather: 'text-yellow-400 border-yellow-500/30 bg-yellow-950/20',
  Markets: 'text-emerald-400 border-emerald-500/30 bg-emerald-950/20',
  SIGINT: 'text-rose-400 border-rose-500/30 bg-rose-950/20',
  Reconnaissance: 'text-green-400 border-green-500/30 bg-green-950/20',
};

type Tab = 'api-keys' | 'news-feeds' | 'sentinel' | 'protocol';

const SettingsPanel = React.memo(function SettingsPanel({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<Tab>('api-keys');

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
  const [apis, setApis] = useState<ApiEntry[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set(['Aviation', 'Maritime']),
  );

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
      }
      return message;
    },
    [],
  );

  const fetchKeys = useCallback(async () => {
    try {
      setApis(await controlPlaneJson<ApiEntry[]>('/api/settings/api-keys'));
      return true;
    } catch (e) {
      await handleProtectedSettingsError(e);
      return false;
    }
  }, [handleProtectedSettingsError]);

  const fetchFeeds = useCallback(async () => {
    try {
      setFeeds(await controlPlaneJson<FeedEntry[]>('/api/settings/news-feeds'));
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
        if (ready) {
          await Promise.all([fetchKeys(), fetchFeeds()]);
        } else {
          setApis([]);
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
    if (!isOpen || !adminSessionReady) return;
    if (activeTab === 'api-keys') {
      void fetchKeys();
      return;
    }
    if (activeTab === 'news-feeds') {
      void fetchFeeds();
    }
  }, [isOpen, adminSessionReady, activeTab, fetchKeys, fetchFeeds]);

  // API Keys handlers
  const startEditing = (api: ApiEntry) => {
    setEditingId(api.id);
    setEditValue('');
  };

  const saveKey = async (api: ApiEntry) => {
    if (!api.env_key) return;
    setSaving(true);
    try {
      const res = await controlPlaneFetch('/api/settings/api-keys', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ env_key: api.env_key, value: editValue }),
      });
      if (res.ok) {
        setEditingId(null);
        fetchKeys();
      }
    } catch (e) {
      console.error('Failed to save API key', e);
    } finally {
      setSaving(false);
    }
  };

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
    setFeedSaving(true);
    setFeedMsg(null);
    try {
      const res = await controlPlaneFetch('/api/settings/news-feeds', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(feeds),
      });
      if (res.ok) {
        setFeedsDirty(false);
        setFeedMsg({
          type: 'ok',
          text: 'Feeds saved. Changes take effect on next news refresh (~30min) or manual /api/refresh.',
        });
      } else {
        const d = await res.json().catch(() => ({}));
        setFeedMsg({ type: 'err', text: d.message || 'Save failed' });
      }
    } catch {
      setFeedMsg({ type: 'err', text: 'Network error' });
    } finally {
      setFeedSaving(false);
    }
  };

  const resetFeeds = async () => {
    try {
      const res = await controlPlaneFetch('/api/settings/news-feeds/reset', {
        method: 'POST',
      });
      if (res.ok) {
        const d = await res.json();
        setFeeds(d.feeds || []);
        setFeedsDirty(false);
        setFeedMsg({ type: 'ok', text: 'Reset to defaults' });
      }
    } catch {
      setFeedMsg({ type: 'err', text: 'Reset failed' });
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
            className="fixed left-0 top-0 bottom-0 w-[480px] bg-[var(--bg-secondary)]/95 backdrop-blur-sm border-r border-cyan-900/50 z-[9999] flex flex-col shadow-[4px_0_40px_rgba(0,0,0,0.3)]"
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-[var(--border-primary)]/80">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center">
                  <Settings size={16} className="text-cyan-400" />
                </div>
                <div>
                  <h2 className="text-sm font-bold tracking-[0.2em] text-[var(--text-primary)] font-mono">
                    SYSTEM CONFIG
                  </h2>
                  <span className="text-[13px] text-[var(--text-muted)] font-mono tracking-widest">
                    SETTINGS &amp; DATA SOURCES
                  </span>
                </div>
              </div>
              <button
                onClick={onClose}
                className="w-8 h-8 border border-[var(--border-primary)] hover:border-red-500/50 flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 transition-all hover:bg-red-950/20"
              >
                <X size={14} />
              </button>
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
                    placeholder={
                      adminSessionReady
                        ? 'Operator tools unlocked. Enter key only to reseed or recover...'
                        : 'Enter operator key for protected settings tabs...'
                    }
                    className="flex-1 bg-[var(--bg-primary)]/60 border border-[var(--border-primary)] px-2 py-1 text-sm font-mono text-[var(--text-secondary)] outline-none focus:border-cyan-700 placeholder:text-[var(--text-muted)]/50"
                  />
                  {adminSessionReady ? (
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
                    className={`text-[12px] font-mono tracking-widest ${
                      adminSessionReady ? 'text-green-400/70' : 'text-yellow-400/70'
                    }`}
                  >
                    {adminSessionReady ? 'ACTIVE' : 'LOCKED'}
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

            <div className="flex border-b border-[var(--border-primary)]/60">
              <button
                onClick={() => setActiveTab('api-keys')}
                className={`flex-1 px-4 py-2.5 text-sm font-mono tracking-widest font-bold transition-colors flex items-center justify-center gap-1.5 ${activeTab === 'api-keys' ? 'text-cyan-400 border-b-2 border-cyan-500 bg-cyan-950/10' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
              >
                <Key size={10} />
                API KEYS
              </button>
              <button
                onClick={() => setActiveTab('news-feeds')}
                className={`flex-1 px-4 py-2.5 text-sm font-mono tracking-widest font-bold transition-colors flex items-center justify-center gap-1.5 ${activeTab === 'news-feeds' ? 'text-orange-400 border-b-2 border-orange-500 bg-orange-950/10' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
              >
                <Rss size={10} />
                NEWS FEEDS
                {feedsDirty && (
                  <span className="w-1.5 h-1.5 rounded-full bg-orange-400 animate-pulse" />
                )}
              </button>
              <button
                onClick={() => setActiveTab('sentinel')}
                className={`flex-1 px-4 py-2.5 text-sm font-mono tracking-widest font-bold transition-colors flex items-center justify-center gap-1.5 ${activeTab === 'sentinel' ? 'text-purple-400 border-b-2 border-purple-500 bg-purple-950/10' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
              >
                <Satellite size={10} />
                SENTINEL
              </button>
              <button
                onClick={() => setActiveTab('protocol')}
                className={`flex-1 px-4 py-2.5 text-sm font-mono tracking-widest font-bold transition-colors flex items-center justify-center gap-1.5 ${activeTab === 'protocol' ? 'text-green-400 border-b-2 border-green-500 bg-green-950/10' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
              >
                <Shield size={10} />
                MESH
              </button>
            </div>

            {/* ==================== API KEYS TAB ==================== */}
            {/* ==================== MESH PROTOCOL TAB ==================== */}
            {activeTab === 'protocol' && (
              <div className="flex-1 flex flex-col overflow-y-auto styled-scrollbar">
                <div className="mx-4 mt-4 p-3 border border-cyan-900/30 bg-cyan-950/12">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm text-cyan-300 font-mono tracking-[0.18em]">
                        WORMHOLE KEY SETUP
                      </div>
                      <div className="mt-2 text-sm text-[var(--text-secondary)] font-mono leading-relaxed">
                        One click enters Wormhole on the recommended path for gates and the obfuscated
                        inbox. Manual transport tuning stays hidden unless you ask for it.
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-[12px] text-[var(--text-muted)] font-mono tracking-[0.2em]">
                        STATUS
                      </div>
                      <div className="mt-1 text-[11px] font-mono text-cyan-200">
                        {wormholeStatus?.ready
                          ? 'ACTIVE'
                          : wormholeEnabled
                            ? 'TURN ON CONNECT'
                            : 'OFF'}
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 grid gap-2 text-[13px] font-mono text-[var(--text-muted)] leading-relaxed">
                    <div>1. Press <span className="text-green-300">GET WORMHOLE KEY</span>.</div>
                    <div>2. We handle the recommended setup path in the background.</div>
                    <div>3. Wait for <span className="text-green-300">ACTIVE</span>.</div>
                    <div>4. We send you straight back into gates.</div>
                  </div>
                  {wormholeGuideNotice && (
                    <div className="mt-3 border border-fuchsia-500/25 bg-fuchsia-950/12 px-3 py-2 text-sm font-mono text-fuchsia-200/90 leading-relaxed">
                      {wormholeGuideNotice}
                    </div>
                  )}
                  {adminSessionMsg === 'BACKEND ADMIN KEY NOT CONFIGURED' && (
                    <div className="mt-3 border border-cyan-500/20 bg-cyan-950/10 px-3 py-2 text-sm font-mono text-cyan-200/85 leading-relaxed">
                      Operator key is only needed for protected Settings tabs. Wormhole join below now
                      works without it.
                    </div>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      onClick={quickStartWormhole}
                      disabled={wormholeSaving || wormholeQuickState === 'active'}
                      className="px-3 py-1.5 border border-green-500/40 bg-green-950/20 text-[13px] font-mono tracking-[0.18em] text-green-300 hover:bg-green-950/30 disabled:opacity-40"
                    >
                      {wormholeQuickButtonLabel}
                    </button>
                    <button
                      onClick={() => setShowAdvancedWormhole((prev) => !prev)}
                      className="px-3 py-1.5 border border-cyan-500/35 bg-cyan-950/18 text-[13px] font-mono tracking-[0.18em] text-cyan-200 hover:bg-cyan-950/28"
                    >
                      {showAdvancedWormhole ? 'HIDE MANUAL SETUP' : 'MANUAL SETUP'}
                    </button>
                  </div>
                  {wormholeMsg && (
                    <div
                      className={`mt-3 px-3 py-2 text-sm font-mono leading-relaxed ${wormholeMsg.type === 'ok' ? 'text-green-300 bg-green-950/18 border border-green-900/30' : 'text-red-300 bg-red-950/18 border border-red-900/30'}`}
                    >
                      {wormholeMsg.text}
                    </div>
                  )}
                  {wormholeNodeId && (
                    <div className="mt-3 border border-cyan-500/20 bg-black/30 px-3 py-2">
                      <div className="text-[13px] font-mono tracking-[0.18em] text-[var(--text-muted)] mb-1">
                        YOUR WORMHOLE IDENTITY
                      </div>
                      <div className="flex items-center gap-2">
                        <code className="flex-1 text-[11px] font-mono text-cyan-300 break-all select-all">
                          {wormholeNodeId}
                        </code>
                        <button
                          onClick={async () => {
                            try {
                              await navigator.clipboard.writeText(wormholeNodeId);
                              setWormholeKeyCopied(true);
                              setTimeout(() => setWormholeKeyCopied(false), 2000);
                            } catch { /* clipboard not available */ }
                          }}
                          className="shrink-0 px-2 py-1 border border-cyan-500/30 text-cyan-400 hover:bg-cyan-950/30 transition-colors text-[13px] font-mono flex items-center gap-1"
                          title="Copy identity to clipboard"
                        >
                          {wormholeKeyCopied ? <Check size={10} /> : <Copy size={10} />}
                          {wormholeKeyCopied ? 'COPIED' : 'COPY'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {showAdvancedWormhole && (
                  <>
                {/* Privacy Mode */}
                <div className="mx-4 mt-4 p-3 border border-green-900/30 bg-green-950/10">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Shield size={12} className="text-green-500 mt-0.5 flex-shrink-0" />
                      <span className="text-sm text-[var(--text-secondary)] font-mono tracking-widest">
                        HIGH PRIVACY MODE (OPT-IN)
                      </span>
                    </div>
                    <button
                      onClick={() => {
                        const next = privacyProfile !== 'high';
                        setHighPrivacy(next);
                      }}
                      className={`px-2 py-1 border text-[13px] font-mono tracking-widest transition-colors ${privacyProfile === 'high' ? 'border-green-500/40 text-green-400 bg-green-950/20' : 'border-[var(--border-primary)] text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
                    >
                      {privacyProfile === 'high' ? 'ON' : 'OFF'}
                    </button>
                  </div>
                  <p className="text-sm text-[var(--text-muted)] font-mono leading-relaxed mt-2">
                    Enables High Privacy profile: session-only identity, stronger jitter, sharded
                    transport (when available), and stricter sync behavior. High Privacy requires
                    the local agent for mesh traffic and refuses clearnet fallback for obfuscated
                    sends. This does not make you anonymous or fully hidden.
                  </p>
                  {privacyProfile === 'high' && (
                    <div className="mt-2 p-2 border border-yellow-500/30 bg-yellow-950/10 text-sm text-yellow-200/90 font-mono leading-relaxed">
                      Recommendation: use a reputable VPN or hidden transport. A VPN can help hide
                      your IP from the backend and peers, but it does not eliminate metadata,
                      endpoint compromise, or traffic analysis risks.
                    </div>
                  )}
                </div>

                {/* Session Identity Mode */}
                <div className="mx-4 mt-3 p-3 border border-green-900/30 bg-green-950/10">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Shield size={12} className="text-green-500 mt-0.5 flex-shrink-0" />
                      <span className="text-sm text-[var(--text-secondary)] font-mono tracking-widest">
                        EPHEMERAL SESSION ID (RECOMMENDED)
                      </span>
                    </div>
                    <button
	                      onClick={() => {
	                        const next = !sessionMode;
	                        setSessionMode(next);
	                        setSessionModePreference(next);
	                        migratePrivacySensitiveBrowserState();
	                        if (next) clearSessionIdentity();
	                      }}
                      className={`px-2 py-1 border text-[13px] font-mono tracking-widest transition-colors ${sessionMode ? 'border-green-500/40 text-green-400 bg-green-950/20' : 'border-[var(--border-primary)] text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
                    >
                      {sessionMode ? 'ON' : 'OFF'}
                    </button>
                  </div>
                  <p className="text-sm text-[var(--text-muted)] font-mono leading-relaxed mt-2">
                    When enabled, agent keys are stored in session storage and reset on browser
                    close. Your identity will not persist across restarts.
                  </p>
                  <div className="mt-3 flex items-center justify-between gap-3 border border-[var(--border-primary)] bg-black/20 px-3 py-2">
                    <div className="min-w-0">
                      <div className="text-sm font-mono tracking-widest text-[var(--text-secondary)]">
                        WIPE LOCAL MESH TRACES
                      </div>
                      <p className="mt-1 text-sm font-mono leading-relaxed text-[var(--text-muted)]">
                        Clears browser-held mesh identities, DM ratchet state, cached contacts, and
                        privacy-sensitive browser storage. The local agent is not shut down.
                      </p>
                    </div>
                    <button
                      onClick={() => {
                        void wipeLocalMeshTraces();
                      }}
                      disabled={browserWipeBusy}
                      className={`shrink-0 px-2 py-1 border text-[13px] font-mono tracking-widest transition-colors ${
                        browserWipeBusy
                          ? 'border-[var(--border-primary)] text-[var(--text-muted)] opacity-60 cursor-not-allowed'
                          : 'border-yellow-500/40 text-yellow-300 bg-yellow-950/20 hover:text-yellow-200'
                      }`}
                    >
                      {browserWipeBusy ? 'WIPING' : 'WIPE NOW'}
                    </button>
                  </div>
                  {browserWipeMsg && (
                    <div
                      className={`mt-2 text-sm font-mono leading-relaxed ${
                        browserWipeMsg.type === 'ok' ? 'text-green-300' : 'text-red-300'
                      }`}
                    >
                      {browserWipeMsg.text}
                    </div>
                  )}
                </div>

                {/* Wormhole Mode */}
                <div className="mx-4 mt-3 p-3 border border-green-900/30 bg-green-950/10">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Shield size={12} className="text-green-500 mt-0.5 flex-shrink-0" />
                      <span className="text-sm text-[var(--text-secondary)] font-mono tracking-widest">
                        LOCAL MESH AGENT (OPT-IN)
                      </span>
                    </div>
                    <button
                      onClick={toggleWormhole}
                      disabled={wormholeSaving}
                      className={`px-2 py-1 border text-[13px] font-mono tracking-widest transition-colors ${wormholeEnabled ? 'border-green-500/40 text-green-400 bg-green-950/20' : 'border-[var(--border-primary)] text-[var(--text-muted)] hover:text-[var(--text-secondary)]'} ${wormholeSaving ? 'opacity-60 cursor-not-allowed' : ''}`}
                    >
                      {wormholeEnabled ? 'ON' : 'OFF'}
                    </button>
                  </div>
                  <p className="text-sm text-[var(--text-muted)] font-mono leading-relaxed mt-2">
                    Runs a local mesh agent that handles traffic directly, removing the backend
                    as a central observer. Experimental — does not guarantee privacy or anonymity.
                  </p>
                  <div className="mt-2 grid grid-cols-1 gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-mono text-[var(--text-muted)] tracking-widest">
                        TRANSPORT
                      </span>
                      <select
                        value={wormholeTransport}
                        onChange={(e) => {
                          setWormholeTransport(e.target.value);
                          setWormholeDirty(true);
                        }}
                        className="bg-[var(--bg-primary)]/60 border border-[var(--border-primary)] px-2 py-1 text-[13px] font-mono text-[var(--text-secondary)]"
                      >
                        <option value="direct">DIRECT</option>
                        <option value="tor">TOR (SOCKS5)</option>
                        <option value="i2p">I2P (SOCKS5)</option>
                        <option value="mixnet">MIXNET (SOCKS5)</option>
                      </select>
                    </div>
                    {(wormholeTransport === 'tor' ||
                      wormholeTransport === 'i2p' ||
                      wormholeTransport === 'mixnet') && (
                      <>
                        <input
                          type="text"
                          value={wormholeSocksProxy}
                          onChange={(e) => {
                            setWormholeSocksProxy(e.target.value);
                            setWormholeDirty(true);
                          }}
                          placeholder="SOCKS5 proxy (e.g. 127.0.0.1:9050)"
                          className="w-full bg-black/30 border border-[var(--border-primary)]/40 px-2 py-1 text-sm font-mono text-[var(--text-muted)] outline-none focus:border-cyan-500/50"
                        />
                        <div className="flex flex-wrap gap-1">
                          <button
                            onClick={() => {
                              setWormholeTransport('tor');
                              setWormholeSocksProxy('127.0.0.1:9050');
                              setWormholeDirty(true);
                            }}
                            className="px-2 py-1 border border-purple-500/30 text-purple-300 text-[12px] font-mono tracking-widest hover:bg-purple-950/20"
                          >
                            TOR 9050
                          </button>
                          <button
                            onClick={() => {
                              setWormholeTransport('tor');
                              setWormholeSocksProxy('127.0.0.1:9150');
                              setWormholeDirty(true);
                            }}
                            className="px-2 py-1 border border-purple-500/30 text-purple-300 text-[12px] font-mono tracking-widest hover:bg-purple-950/20"
                          >
                            TOR 9150
                          </button>
                          <button
                            onClick={() => {
                              setWormholeTransport('i2p');
                              setWormholeSocksProxy('127.0.0.1:4447');
                              setWormholeDirty(true);
                            }}
                            className="px-2 py-1 border border-blue-500/30 text-blue-300 text-[12px] font-mono tracking-widest hover:bg-blue-950/20"
                          >
                            I2P 4447
                          </button>
                          <button
                            onClick={() => {
                              setWormholeTransport('mixnet');
                              setWormholeSocksProxy('127.0.0.1:1080');
                              setWormholeDirty(true);
                            }}
                            className="px-2 py-1 border border-cyan-500/30 text-cyan-300 text-[12px] font-mono tracking-widest hover:bg-cyan-950/20"
                          >
                            MIXNET 1080
                          </button>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-[13px] font-mono text-[var(--text-muted)] tracking-widest">
                            PROXY DNS
                          </span>
                          <button
                            onClick={() => {
                              setWormholeSocksDns((prev) => !prev);
                              setWormholeDirty(true);
                            }}
                            className={`px-2 py-1 border text-[13px] font-mono tracking-widest transition-colors ${wormholeSocksDns ? 'border-green-500/40 text-green-400 bg-green-950/20' : 'border-[var(--border-primary)] text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
                          >
                            {wormholeSocksDns ? 'ON' : 'OFF'}
                          </button>
                        </div>
                        <div className="text-[13px] font-mono text-[var(--text-muted)] leading-relaxed">
                          Hidden transport requires a local SOCKS5 proxy (Tor/I2P/Mixnet) already
                          running. Save applies the new transport immediately.
                        </div>
                      </>
                    )}
                    <div className="flex items-center justify-between gap-2 border border-green-900/20 bg-black/20 px-2 py-2">
                      <div>
                        <div className="text-[13px] font-mono text-[var(--text-secondary)] tracking-widest">
                          HIDDEN TRANSPORT MODE
                        </div>
                        <div className="mt-1 text-[13px] font-mono text-[var(--text-muted)] leading-relaxed">
                          Public mesh writes fail closed unless the local agent is active on
                          Tor/I2P/Mixnet. Direct transport is blocked while this is on.
                        </div>
                      </div>
                      <button
                        onClick={() => {
                          setWormholeAnonymousMode((prev) => !prev);
                          setWormholeDirty(true);
                        }}
                        className={`px-2 py-1 border text-[13px] font-mono tracking-widest transition-colors ${wormholeAnonymousMode ? 'border-green-500/40 text-green-400 bg-green-950/20' : 'border-[var(--border-primary)] text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
                      >
                        {wormholeAnonymousMode ? 'ON' : 'OFF'}
                      </button>
                    </div>
                    {wormholeAnonymousMode && (
                      <div className="flex flex-col gap-1 text-[13px] font-mono">
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-1.5 py-0.5 border ${anonModeReady ? 'border-green-500/40 text-green-400 bg-green-950/20' : 'border-yellow-500/40 text-yellow-300 bg-yellow-950/10'}`}
                          >
                            {trustModeLabel}
                          </span>
                          <span className="text-[var(--text-muted)] leading-relaxed">
                            {anonModeReady
                              ? 'Hidden transport is active. Public gate posting routes through the local agent.'
                              : 'Connect the local agent over Tor, I2P, or Mixnet before posting publicly.'}
                          </span>
                        </div>
                        <div className="text-[var(--text-muted)] leading-relaxed">
                          Mesh Terminal stays read-only for sensitive posting and DM actions while
                          the hidden transport policy is active. Use MeshChat for the hardened path.
                        </div>
                        <div className="text-[var(--text-muted)] leading-relaxed">
                          Relay fallback reduces metadata protection compared with direct obfuscated
                          transport. Meshtastic/APRS remain degraded, integrity-only channels in
                          this phase.
                        </div>
                      </div>
                    )}
                    {!wormholeAnonymousMode && (
                      <div className="flex flex-col gap-1 text-[13px] font-mono">
                        <div className="flex items-center gap-2">
                          <span className="px-1.5 py-0.5 border border-orange-500/40 text-orange-300 bg-orange-950/20">
                            {trustModeLabel}
                          </span>
                          <span className="text-[var(--text-muted)] leading-relaxed">
                            Hidden transport is off. Public posting may use public or degraded
                            transports until you require Tor, I2P, or Mixnet.
                          </span>
                        </div>
                        <div className="text-[var(--text-muted)] leading-relaxed">
                          Meshtastic/APRS/JS8 remain public or degraded in this phase unless a
                          separate obfuscated transport is explicitly enabled.
                        </div>
                      </div>
                    )}
                    <button
                      onClick={() => saveWormholeSettings()}
                      disabled={!wormholeDirty || wormholeSaving}
                      className="px-2 py-1 border border-green-500/40 text-green-400 bg-green-950/20 hover:bg-green-950/30 transition-colors text-[13px] font-mono tracking-widest disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      {wormholeSaving ? 'SAVING...' : 'SAVE LOCAL AGENT SETTINGS'}
                    </button>
                    <div className="grid grid-cols-3 gap-2">
                      <button
                        onClick={() => controlWormhole('connect')}
                        disabled={wormholeSaving}
                        className="px-2 py-1 border border-green-500/40 text-green-400 bg-green-950/20 hover:bg-green-950/30 transition-colors text-[13px] font-mono tracking-widest disabled:opacity-40"
                      >
                        CONNECT
                      </button>
                      <button
                        onClick={() => controlWormhole('restart')}
                        disabled={wormholeSaving || !wormholeEnabled}
                        className="px-2 py-1 border border-yellow-500/40 text-yellow-300 bg-yellow-950/10 hover:bg-yellow-950/20 transition-colors text-[13px] font-mono tracking-widest disabled:opacity-40"
                      >
                        RESTART
                      </button>
                      <button
                        onClick={() => controlWormhole('disconnect')}
                        disabled={wormholeSaving || !wormholeEnabled}
                        className="px-2 py-1 border border-red-500/40 text-red-300 bg-red-950/10 hover:bg-red-950/20 transition-colors text-[13px] font-mono tracking-widest disabled:opacity-40"
                      >
                        DISCONNECT
                      </button>
                    </div>
                  </div>
                  {rnsStatus && (
                    <div className="mt-2 text-[13px] font-mono text-[var(--text-muted)] flex items-center gap-2">
                      <span
                        className={`px-1.5 py-0.5 border ${rnsStatus.ready ? 'border-green-500/40 text-green-400 bg-green-950/20' : 'border-yellow-500/40 text-yellow-400 bg-yellow-950/20'}`}
                      >
                        RNS {rnsStatus.ready ? 'READY' : rnsStatus.enabled ? 'STARTING' : 'OFF'}
                      </span>
                      <span>
                        peers {rnsStatus.active_peers}/{rnsStatus.configured_peers}
                      </span>
                    </div>
                  )}
                  {wormholeStatus && (
                    <div className="mt-1 space-y-2 text-[13px] font-mono text-[var(--text-muted)]">
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-1.5 py-0.5 border ${
                            wormholeStatus.ready
                              ? 'border-green-500/40 text-green-400 bg-green-950/20'
                              : wormholeStatus.running
                                ? 'border-yellow-500/40 text-yellow-300 bg-yellow-950/10'
                                : 'border-slate-600/40 text-slate-300 bg-slate-900/20'
                          }`}
                        >
                          {wormholeStatus.ready
                            ? 'LOCAL AGENT ACTIVE'
                            : wormholeStatus.running
                              ? 'LOCAL AGENT STARTING'
                              : wormholeStatus.configured
                                ? 'LOCAL AGENT IDLE'
                                : 'LOCAL AGENT OFF'}
                        </span>
                        {wormholeStatus.pid > 0 && <span>pid {wormholeStatus.pid}</span>}
                      </div>
                      <div className="flex items-center gap-2">
                      <span
                        className={`px-1.5 py-0.5 border ${
                          effectiveTransport !== 'direct'
                            ? 'border-purple-500/40 text-purple-300 bg-purple-950/20'
                            : 'border-slate-600/40 text-slate-300 bg-slate-900/20'
                        }`}
                      >
                        ACTIVE {effectiveTransport.toUpperCase()}
                      </span>
                      {transportMismatch && (
                        <span className="px-1.5 py-0.5 border border-yellow-500/40 text-yellow-300 bg-yellow-950/10">
                          FALLBACK
                        </span>
                      )}
                      {recentPrivateFallback && (
                        <span className="px-1.5 py-0.5 border border-red-500/40 text-red-300 bg-red-950/20">
                          PRIVACY DOWNGRADE
                        </span>
                      )}
                      {wormholeStatus.proxy_active && (
                        <span className="text-[12px] text-[var(--text-muted)]">
                          proxy {wormholeStatus.proxy_active}
                        </span>
                      )}
                      </div>
                      <div className="text-[13px] leading-relaxed">
                        Public transport identity, gate personas, and the obfuscated DM alias are
                        compartmentalized inside the local agent.
                      </div>
                      {recentPrivateFallback && (
                        <div className="text-[13px] text-red-300/90 leading-relaxed">
                          {recentPrivateFallbackReason}
                        </div>
                      )}
                      {wormholeStatus.last_error && (
                        <div className="text-[13px] text-red-300/90 leading-relaxed">
                          {wormholeStatus.last_error}
                        </div>
                      )}
                    </div>
                  )}
                </div>
                  </>
                )}
              </div>
            )}

            {activeTab === 'api-keys' && (
              <>
                {/* Info Banner */}
                <div className="mx-4 mt-4 p-3 border border-cyan-900/30 bg-cyan-950/10">
                  <div className="flex items-start gap-2">
                    <Shield size={12} className="text-cyan-500 mt-0.5 flex-shrink-0" />
                    <p className="text-sm text-[var(--text-secondary)] font-mono leading-relaxed">
                      API keys are stored locally in the backend{' '}
                      <span className="text-cyan-400">.env</span> file. Keys marked with{' '}
                      <Key size={8} className="inline text-yellow-500" /> are required for full
                      functionality. Public APIs need no key.
                    </p>
                  </div>
                </div>

                {/* API List */}
                <div className="flex-1 overflow-y-auto styled-scrollbar p-4 space-y-3">
                  {Object.entries(grouped).map(([category, categoryApis]) => {
                    const colorClass =
                      CATEGORY_COLORS[category] || 'text-gray-400 border-gray-700 bg-gray-900/20';
                    const isExpanded = expandedCategories.has(category);
                    return (
                      <div
                        key={category}
                        className="border border-[var(--border-primary)]/60 overflow-hidden"
                      >
                        <button
                          onClick={() => toggleCategory(category)}
                          className="w-full flex items-center justify-between px-4 py-2.5 bg-[var(--bg-secondary)]/50 hover:bg-[var(--bg-secondary)]/80 transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            <span
                              className={`text-[13px] font-mono tracking-widest font-bold px-2 py-0.5 border ${colorClass}`}
                            >
                              {category.toUpperCase()}
                            </span>
                            <span className="text-sm text-[var(--text-muted)] font-mono">
                              {categoryApis.length}{' '}
                              {categoryApis.length === 1 ? 'service' : 'services'}
                            </span>
                          </div>
                          {isExpanded ? (
                            <ChevronUp size={12} className="text-[var(--text-muted)]" />
                          ) : (
                            <ChevronDown size={12} className="text-[var(--text-muted)]" />
                          )}
                        </button>
                        <AnimatePresence>
                          {isExpanded && (
                            <motion.div
                              initial={{ height: 0, opacity: 0 }}
                              animate={{ height: 'auto', opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }}
                              transition={{ duration: 0.2 }}
                            >
                              {categoryApis.map((api) => (
                                <div
                                  key={api.id}
                                  className="border-t border-[var(--border-primary)]/40 px-4 py-3 hover:bg-[var(--bg-secondary)]/30 transition-colors"
                                >
                                  <div className="flex items-center justify-between mb-1">
                                    <div className="flex items-center gap-2">
                                      {api.required && (
                                        <Key size={10} className="text-yellow-500" />
                                      )}
                                      <span className="text-xs font-mono text-[var(--text-primary)] font-medium">
                                        {api.name}
                                      </span>
                                    </div>
                                    <div className="flex items-center gap-1.5">
                                      {api.has_key ? (
                                        api.is_set ? (
                                          <span className="text-[12px] font-mono px-1.5 py-0.5 border border-green-500/30 text-green-400 bg-green-950/20">
                                            KEY SET
                                          </span>
                                        ) : (
                                          <span className="text-[12px] font-mono px-1.5 py-0.5 border border-yellow-500/30 text-yellow-400 bg-yellow-950/20">
                                            MISSING
                                          </span>
                                        )
                                      ) : (
                                        <span className="text-[12px] font-mono px-1.5 py-0.5 border border-[var(--border-primary)] text-[var(--text-muted)]">
                                          PUBLIC
                                        </span>
                                      )}
                                      {api.url && (
                                        <a
                                          href={api.url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="text-[var(--text-muted)] hover:text-cyan-400 transition-colors"
                                          onClick={(e) => e.stopPropagation()}
                                        >
                                          <ExternalLink size={10} />
                                        </a>
                                      )}
                                    </div>
                                  </div>
                                  <p className="text-sm text-[var(--text-muted)] font-mono leading-relaxed mb-2">
                                    {api.description}
                                  </p>
                                  {api.has_key && (
                                    <div className="mt-2">
                                      {editingId === api.id ? (
                                        <div className="flex gap-2">
                                          <input
                                            type="text"
                                            value={editValue}
                                            onChange={(e) => setEditValue(e.target.value)}
                                            className="flex-1 bg-black/60 border border-cyan-900/50 px-2 py-1.5 text-[11px] font-mono text-cyan-300 outline-none focus:border-cyan-500/70 transition-colors"
                                            placeholder="Enter API key..."
                                            autoFocus
                                          />
                                          <button
                                            onClick={() => saveKey(api)}
                                            disabled={saving}
                                            className="px-3 py-1.5 bg-cyan-500/20 border border-cyan-500/40 text-cyan-400 hover:bg-cyan-500/30 transition-colors text-sm font-mono flex items-center gap-1"
                                          >
                                            <Save size={10} />
                                            {saving ? '...' : 'SAVE'}
                                          </button>
                                          <button
                                            onClick={() => setEditingId(null)}
                                            className="px-2 py-1.5 border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:border-[var(--border-secondary)] transition-colors text-sm font-mono"
                                          >
                                            ESC
                                          </button>
                                        </div>
                                      ) : (
                                        <div className="flex items-center gap-1.5">
                                          <div
                                            className="flex-1 bg-[var(--bg-primary)]/40 border border-[var(--border-primary)] px-2.5 py-1.5 font-mono text-[11px] cursor-pointer hover:border-[var(--border-secondary)] transition-colors select-none"
                                            onClick={() => startEditing(api)}
                                          >
                                            <span className="text-[var(--text-muted)] tracking-wider">
                                              {api.is_set
                                                ? api.value_obfuscated
                                                : 'Click to set key...'}
                                            </span>
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </div>
                    );
                  })}
                </div>

                {/* Footer */}
                <div className="p-4 border-t border-[var(--border-primary)]/80">
                  <div className="flex items-center justify-between text-[13px] text-[var(--text-muted)] font-mono">
                    <span>{apis.length} REGISTERED APIs</span>
                    <span>{apis.filter((a) => a.has_key).length} KEYS CONFIGURED</span>
                  </div>
                </div>
              </>
            )}

            {/* ==================== NEWS FEEDS TAB ==================== */}
            {activeTab === 'news-feeds' && (
              <>
                {/* Info Banner */}
                <div className="mx-4 mt-4 p-3 border border-orange-900/30 bg-orange-950/10">
                  <div className="flex items-start gap-2">
                    <Rss size={12} className="text-orange-500 mt-0.5 flex-shrink-0" />
                    <p className="text-sm text-[var(--text-secondary)] font-mono leading-relaxed">
                      Configure RSS/Atom feeds for the Threat Intel news panel. Each feed is scored
                      by keyword heuristics and weighted by the priority you set. Up to{' '}
                      <span className="text-orange-400">{MAX_FEEDS}</span> sources.
                    </p>
                  </div>
                </div>

                {/* Feed List */}
                <div className="flex-1 overflow-y-auto styled-scrollbar p-4 space-y-2">
                  {feeds.map((feed, idx) => (
                    <div
                      key={idx}
                      className="border border-[var(--border-primary)]/60 p-3 hover:border-[var(--border-secondary)]/60 transition-colors group"
                    >
                      {/* Row 1: Name + Weight + Delete */}
                      <div className="flex items-center gap-2 mb-2">
                        <input
                          type="text"
                          value={feed.name}
                          onChange={(e) => updateFeed(idx, 'name', e.target.value)}
                          className="flex-1 bg-transparent border-b border-[var(--border-primary)] text-xs font-mono text-[var(--text-primary)] outline-none focus:border-cyan-500/70 transition-colors px-1 py-0.5"
                          placeholder="Source name..."
                        />
                        {/* Weight selector */}
                        <div className="flex items-center gap-1">
                          {[1, 2, 3, 4, 5].map((w) => (
                            <button
                              key={w}
                              onClick={() => updateFeed(idx, 'weight', w)}
                              className={`w-5 h-5 text-[12px] font-mono font-bold border transition-all ${feed.weight === w ? WEIGHT_COLORS[w] + ' bg-black/40' : 'border-[var(--border-primary)]/40 text-[var(--text-muted)]/50 hover:border-[var(--border-secondary)]'}`}
                              title={WEIGHT_LABELS[w]}
                            >
                              {w}
                            </button>
                          ))}
                          <span
                            className={`text-[12px] font-mono ml-1 w-7 ${WEIGHT_COLORS[feed.weight]?.split(' ')[0] || 'text-gray-400'}`}
                          >
                            {WEIGHT_LABELS[feed.weight] || 'STD'}
                          </span>
                        </div>
                        <button
                          onClick={() => removeFeed(idx)}
                          className="w-6 h-6 flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 hover:bg-red-950/20 transition-all opacity-0 group-hover:opacity-100"
                          title="Remove feed"
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                      {/* Row 2: URL */}
                      <input
                        type="text"
                        value={feed.url}
                        onChange={(e) => updateFeed(idx, 'url', e.target.value)}
                        className="w-full bg-black/30 border border-[var(--border-primary)]/40 px-2 py-1 text-sm font-mono text-[var(--text-muted)] outline-none focus:border-cyan-500/50 focus:text-cyan-300 transition-colors"
                        placeholder="https://example.com/rss.xml"
                      />
                    </div>
                  ))}

                  {/* Add Feed Button */}
                  <button
                    onClick={addFeed}
                    disabled={feeds.length >= MAX_FEEDS}
                    className="w-full py-2.5 border border-dashed border-[var(--border-primary)]/60 text-[var(--text-muted)] hover:border-orange-500/50 hover:text-orange-400 hover:bg-orange-950/10 transition-all text-sm font-mono flex items-center justify-center gap-1.5 disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <Plus size={10} />
                    ADD FEED ({feeds.length}/{MAX_FEEDS})
                  </button>
                </div>

                {/* Status message */}
                {feedMsg && (
                  <div
                    className={`mx-4 mb-2 px-3 py-2 text-sm font-mono ${feedMsg.type === 'ok' ? 'text-green-400 bg-green-950/20 border border-green-900/30' : 'text-red-400 bg-red-950/20 border border-red-900/30'}`}
                  >
                    {feedMsg.text}
                  </div>
                )}

                {/* Footer */}
                <div className="p-4 border-t border-[var(--border-primary)]/80">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={saveFeeds}
                      disabled={!feedsDirty || feedSaving}
                      className="flex-1 px-4 py-2 bg-orange-500/20 border border-orange-500/40 text-orange-400 hover:bg-orange-500/30 transition-colors text-sm font-mono flex items-center justify-center gap-1.5 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      <Save size={10} />
                      {feedSaving ? 'SAVING...' : 'SAVE FEEDS'}
                    </button>
                    <button
                      onClick={resetFeeds}
                      className="px-3 py-2 border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:border-[var(--border-secondary)] transition-all text-sm font-mono flex items-center gap-1.5"
                      title="Reset to defaults"
                    >
                      <RotateCcw size={10} />
                      RESET
                    </button>
                  </div>
                  <div className="flex items-center justify-between text-[13px] text-[var(--text-muted)] font-mono mt-2">
                    <span>
                      {feeds.length}/{MAX_FEEDS} SOURCES
                    </span>
                    <span>WEIGHT: 1=LOW 5=CRITICAL</span>
                  </div>
                </div>
              </>
            )}

            {/* ==================== SENTINEL HUB TAB ==================== */}
            {activeTab === 'sentinel' && <SentinelTab />}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
});

// ─── Sentinel Hub Settings Tab ─────────────────────────────────────────────
function SentinelTab() {
  const [clientId, setClientId] = useState(() => getSentinelCredentials().clientId);
  const [clientSecret, setClientSecret] = useState(() => getSentinelCredentials().clientSecret);
  const [testing, setTesting] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [dirty, setDirty] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const storageMode = getSentinelCredentialStorageMode();

  const save = () => {
    setSentinelCredentials(clientId.trim(), clientSecret.trim());
    setDirty(false);
    setStatus({
      ok: true,
      msg: `Credentials saved to browser ${storageMode === 'session' ? 'session' : 'local'} storage.`,
    });
  };

  const testConnection = async () => {
    setTesting(true);
    setStatus(null);
    try {
      const resp = await fetch(`${API_BASE}/api/sentinel/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          client_id: clientId.trim(),
          client_secret: clientSecret.trim(),
        }),
      });
      if (resp.ok) {
        setStatus({ ok: true, msg: 'Connected — token acquired successfully.' });
      } else {
        const text = await resp.text().catch(() => '');
        setStatus({ ok: false, msg: `Auth failed (${resp.status}): ${text.slice(0, 120)}` });
      }
    } catch (err) {
      const msg =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message?: string }).message)
          : 'unknown';
      setStatus({ ok: false, msg: `Network error: ${msg}` });
    } finally {
      setTesting(false);
    }
  };

  const clear = () => {
    clearSentinelCredentials();
    setClientId('');
    setClientSecret('');
    setDirty(false);
    setStatus({ ok: true, msg: 'Credentials cleared.' });
  };

  const inputCls =
    'w-full bg-[var(--bg-primary)]/60 border border-[var(--border-primary)] px-3 py-2 text-[11px] font-mono text-[var(--text-secondary)] outline-none focus:border-purple-500 placeholder:text-[var(--text-muted)]/50 transition-colors';

  return (
    <div className="flex-1 flex flex-col overflow-y-auto styled-scrollbar">
      {/* Setup Guide */}
      <div className="mx-4 mt-4 p-3 border border-purple-900/30 bg-purple-950/10">
        <div className="flex items-start gap-2">
          <Satellite size={12} className="text-purple-400 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-[var(--text-secondary)] font-mono leading-relaxed space-y-2">
            <p className="text-purple-300 font-bold">COPERNICUS SENTINEL HUB SETUP</p>
            <p className="text-[var(--text-muted)]">
              Sentinel Hub gives you access to ESA satellite imagery (Sentinel-2 true color,
              NDVI vegetation, false color IR, moisture index). Free tier: 10,000 processing
              units/month. Follow each step below:
            </p>
            <div className="space-y-1.5 mt-1">
              <p>
                <span className="text-purple-400 font-bold">STEP 1:</span>{' '}
                Go to{' '}
                <a
                  href="https://dataspace.copernicus.eu"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-purple-400 underline hover:text-purple-300"
                >
                  dataspace.copernicus.eu
                </a>
                {' '}&rarr; click <span className="text-white">Register</span> (top right) &rarr;
                create a free account. Pick <span className="text-white">Public</span> for
                User Category.
              </p>
              <p>
                <span className="text-purple-400 font-bold">STEP 2:</span>{' '}
                Once logged in, go to{' '}
                <a
                  href="https://shapps.dataspace.copernicus.eu/dashboard/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-purple-400 underline hover:text-purple-300"
                >
                  Sentinel Hub Dashboard
                </a>
                {' '}&rarr; click your <span className="text-white">user icon</span> (top right)
                {' '}&rarr; <span className="text-white">User Settings</span>
                {' '}&rarr; <span className="text-white">OAuth clients</span> tab &rarr;{' '}
                click <span className="text-cyan-400">&quot;+ Create new&quot;</span>.
                Give it any name (e.g. &quot;ShadowBroker&quot;). Copy the{' '}
                <span className="text-white">Client ID</span> and{' '}
                <span className="text-white">Client Secret</span> it shows you.
              </p>
              <p>
                <span className="text-purple-400 font-bold">STEP 3:</span>{' '}
                Paste both values in the fields below, hit{' '}
                <span className="text-cyan-400">SAVE</span>, then{' '}
                <span className="text-cyan-400">TEST CONNECTION</span> to verify.
                That&apos;s it!
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Credential Inputs */}
      <div className="p-4 space-y-3">
        <div>
          <label className="text-[13px] font-mono text-[var(--text-muted)] tracking-widest mb-1 block">
            CLIENT ID
          </label>
          <input
            type="text"
            value={clientId}
            onChange={(e) => {
              setClientId(e.target.value);
              setDirty(true);
            }}
            placeholder="sh-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            spellCheck={false}
            autoComplete="off"
            className={inputCls}
          />
        </div>
        <div>
          <label className="text-[13px] font-mono text-[var(--text-muted)] tracking-widest mb-1 block">
            CLIENT SECRET
          </label>
          <input
            type={showSecret ? 'text' : 'password'}
            value={clientSecret}
            onChange={(e) => {
              setClientSecret(e.target.value);
              setDirty(true);
            }}
            placeholder="Paste client secret here..."
            spellCheck={false}
            autoComplete="new-password"
            className={inputCls}
          />
          <button
            type="button"
            onClick={() => setShowSecret((current) => !current)}
            className="mt-2 inline-flex items-center gap-1.5 text-[13px] font-mono text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
          >
            {showSecret ? <EyeOff size={10} /> : <Eye size={10} />}
            {showSecret ? 'HIDE SECRET' : 'SHOW SECRET'}
          </button>
        </div>
      </div>

      {/* Status */}
      {status && (
        <div
          className={`mx-4 mb-2 px-3 py-2 text-sm font-mono ${status.ok ? 'text-green-400 bg-green-950/20 border border-green-900/30' : 'text-red-400 bg-red-950/20 border border-red-900/30'}`}
        >
          {status.msg}
        </div>
      )}

      {/* Actions */}
      <div className="p-4 border-t border-[var(--border-primary)]/80 mt-auto">
        <div className="flex items-center gap-2">
          <button
            onClick={save}
            disabled={!dirty}
            className="flex-1 px-4 py-2 bg-purple-500/20 border border-purple-500/40 text-purple-400 hover:bg-purple-500/30 transition-colors text-sm font-mono flex items-center justify-center gap-1.5 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Save size={10} />
            SAVE
          </button>
          <button
            onClick={testConnection}
            disabled={testing || !clientId || !clientSecret}
            className="flex-1 px-4 py-2 bg-cyan-500/20 border border-cyan-500/40 text-cyan-400 hover:bg-cyan-500/30 transition-colors text-sm font-mono flex items-center justify-center gap-1.5 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {testing ? 'TESTING...' : 'TEST CONNECTION'}
          </button>
          <button
            onClick={clear}
            className="px-3 py-2 border border-[var(--border-primary)] text-[var(--text-muted)] hover:text-red-400 hover:border-red-500/50 hover:bg-red-950/10 transition-all text-sm font-mono flex items-center gap-1.5"
            title="Clear credentials"
          >
            <Trash2 size={10} />
          </button>
        </div>
        {/* Usage Meter */}
        <UsageMeter />

        <div className="mt-2 p-2 border border-[var(--border-primary)]/40 bg-[var(--bg-primary)]/30">
          <p className="text-[13px] text-[var(--text-muted)] font-mono leading-relaxed">
            Credentials stay in browser-only storage and never touch ShadowBroker servers.
            {storageMode === 'session'
              ? ' Current privacy mode keeps them in session storage only.'
              : ' Current privacy mode keeps them in local storage for persistence.'}
          </p>
        </div>
      </div>
    </div>
  );
}

function UsageMeter() {
  const [usage, setUsage] = useState({ month: '', tiles: 0, pu: 0 });

  useEffect(() => {
    // Import dynamically to avoid SSR issues
    import('@/lib/sentinelHub').then(({ getSentinelUsage }) => {
      setUsage(getSentinelUsage());
    });
    // Refresh every 10s when tab is active
    const id = setInterval(() => {
      import('@/lib/sentinelHub').then(({ getSentinelUsage }) => {
        setUsage(getSentinelUsage());
      });
    }, 10_000);
    return () => clearInterval(id);
  }, []);

  const maxRequests = 10_000;
  const maxPU = 10_000;
  const pct = Math.min(100, (usage.tiles / maxRequests) * 100);
  const barColor =
    pct < 50 ? 'bg-purple-500' : pct < 80 ? 'bg-yellow-500' : 'bg-red-500';
  const textColor =
    pct < 50 ? 'text-purple-400' : pct < 80 ? 'text-yellow-400' : 'text-red-400';

  return (
    <div className="mt-3 p-3 border border-purple-900/30 bg-purple-950/10">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[13px] font-mono text-purple-400 tracking-widest">
          MONTHLY USAGE
        </span>
        <span className="text-[13px] font-mono text-[var(--text-muted)]">
          {usage.month || '—'}
        </span>
      </div>
      {/* Progress bar */}
      <div className="w-full h-1.5 rounded-full bg-[var(--bg-primary)] mb-2">
        <div
          className={`h-full rounded-full ${barColor} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <div className={`text-[11px] font-mono font-bold ${textColor}`}>
            {usage.tiles.toLocaleString()}
          </div>
          <div className="text-[12px] font-mono text-[var(--text-muted)]">
            / {maxRequests.toLocaleString()} tiles
          </div>
        </div>
        <div>
          <div className={`text-[11px] font-mono font-bold ${textColor}`}>
            {usage.pu.toLocaleString()}
          </div>
          <div className="text-[12px] font-mono text-[var(--text-muted)]">
            / {maxPU.toLocaleString()} PU
          </div>
        </div>
        <div>
          <div className="text-[11px] font-mono font-bold text-[var(--text-secondary)]">
            {Math.round(100 - pct)}%
          </div>
          <div className="text-[12px] font-mono text-[var(--text-muted)]">remaining</div>
        </div>
      </div>
    </div>
  );
}

export default SettingsPanel;
