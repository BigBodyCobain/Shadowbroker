// @ts-nocheck
'use client';

import { useCallback, useEffect, useState } from 'react';
import { controlPlaneFetch } from '@/lib/controlPlane';
import { fetchPrivacyProfileSnapshot, fetchRnsStatusSnapshot, invalidatePrivacyProfileCache, invalidateRnsStatusCache } from '@/mesh/controlPlaneStatusClient';
import { fetchWormholeSettings, fetchWormholeState, invalidateWormholeRuntimeCache, joinWormhole, connectWormhole, disconnectWormhole, restartWormhole, type WormholeState } from '@/mesh/wormholeClient';
import { fetchWormholeDmRootHealth, fetchWormholeIdentity, type WormholeDmRootHealth } from '@/mesh/wormholeIdentityClient';
import { hasLegacyCompatibilityActivity, summarizeLegacyCompatibility } from '@/mesh/wormholeCompatibility';
import { summarizeGateCompatTelemetry } from '@/mesh/gateCompatTelemetry';
import { applySecureModeBoundary, migratePrivacySensitiveBrowserState, SETTINGS_FOCUS_KEY, WORMHOLE_READY_EVENT, WORMHOLE_RETURN_KEY, dmRootMonitorTone } from './SettingsPanel.shared';
import { getSessionModePreference, setPrivacyProfilePreference, setPrivacyStrictPreference, setSessionModePreference } from '@/lib/privacyBrowserStorage';

export interface SettingsPanelWormholeOpts {
  isOpen: boolean; activeTab: string; onClose: () => void; nativeProtected: boolean;
  adminSessionReady: boolean; showOperatorTools: boolean;
  refreshAdminSession: () => Promise<boolean>;
  fetchKeys: () => Promise<any>; fetchFeeds: () => Promise<any>; fetchEnvMeta: () => Promise<any>;
  handleProtectedSettingsError: (e: unknown) => Promise<string>;
  ensureAdminSession: () => Promise<void>;
  setActiveTab: (t: any) => void; setFeeds: (v: any) => void; setFeedsDirty: (v: boolean) => void;
  clearSessionIdentity: () => void;
  privacyProfile: string; setPrivacyProfile: (v: string) => void;
  sessionMode: boolean; setSessionMode: (v: boolean) => void; setStrictPrivacy: (v: boolean) => void;
  gateCompatTelemetry: any;
}

export function useSettingsPanelWormhole(opts: SettingsPanelWormholeOpts) {
  const {
    isOpen, activeTab, onClose, nativeProtected,
    setActiveTab, setFeeds, setFeedsDirty, clearSessionIdentity,
    privacyProfile, setPrivacyProfile, sessionMode, setSessionMode, setStrictPrivacy,
    gateCompatTelemetry,
  } = opts;
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
    const [wormholeNodeId, setWormholeNodeId] = useState<string | null>(null);
    const [wormholeKeyCopied, setWormholeKeyCopied] = useState(false);
    const [dmRootHealth, setDmRootHealth] = useState<WormholeDmRootHealth | null>(null);
    const [dmRootHealthBusy, setDmRootHealthBusy] = useState(false);
    const [dmRootHealthMsg, setDmRootHealthMsg] = useState<string | null>(null);

    const [rnsStatus, setRnsStatus] = useState<{
      enabled: boolean;
      ready: boolean;
      configured_peers: number;
      active_peers: number;
    } | null>(null);

    const clearApisRef = React.useRef<() => void>(() => {});

    const clearFeedsRef = React.useRef<() => void>(() => {});
    const handleProtectedSettingsError = useCallback(
      async (error: unknown) => {
        const message = error instanceof Error ? error.message : 'Protected settings request failed';
        if (
          message === 'Forbidden — admin key not configured' ||
          message === 'Forbidden — invalid or missing admin key'
        ) {
          await clearAdminSession();
          setAdminSessionReadyRef.current(false);
          setAdminSessionMsgRef.current(
            message === 'Forbidden — admin key not configured'
              ? 'BACKEND ADMIN KEY NOT CONFIGURED'
              : 'ADMIN KEY INVALID OR EXPIRED',
          );
          clearApisRef.current();
          clearFeedsRef.current();
          setDmRootHealth(null);
          setDmRootHealthMsg(message);
        }
        return message;
      },
      [],
    );

    const {
      feeds, feedsDirty, feedSaving, feedMsg,
      fetchFeeds, updateFeed, removeFeed, addFeed, saveFeeds, resetFeeds, setFeedMsg, clearFeeds,
    } = useSettingsPanelFeeds(handleProtectedSettingsError);
    clearFeedsRef.current = clearFeeds;

    const {
      apis, apiKeyInputs, apiKeyEditing, apiKeySaving, apiKeyMsg,
      expandedCategories, envMeta, grouped,
      fetchKeys, saveApiKey, fetchEnvMeta, toggleCategory,
      setApiKeyInputs, setApiKeyEditing, setApiKeyMsg, clearApiKeys,
    } = useSettingsPanelApiKeys(handleProtectedSettingsError);
    clearApisRef.current = clearApiKeys;

    const {
      adminKey, setAdminKey, adminSessionReady, setAdminSessionReady, adminSessionBusy, adminSessionMsg, setAdminSessionMsg,
      showOperatorTools, setShowOperatorTools,
      refreshAdminSession, ensureAdminSession, unlockAdminSession, lockAdminSession,
    } = useSettingsPanelAdminSession({ activeTab, fetchKeys, fetchFeeds, setDmRootHealth, setDmRootHealthMsg });
    setAdminSessionReadyRef.current = setAdminSessionReady;
    setAdminSessionMsgRef.current = setAdminSessionMsg;


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


  return {
    wormholeEnabled, setWormholeEnabled, wormholeSaving, wormholeMsg, setWormholeMsg,
    wormholeTransport, setWormholeTransport, wormholeSocksProxy, setWormholeSocksProxy,
    wormholeSocksDns, setWormholeSocksDns, wormholeAnonymousMode, setWormholeAnonymousMode,
    wormholeDirty, setWormholeDirty, wormholeStatus, wormholeGuideNotice, showAdvancedWormhole, setShowAdvancedWormhole,
    wormholeQuickState, wormholeNodeId, setWormholeNodeId, wormholeKeyCopied, setWormholeKeyCopied,
    dmRootHealth, setDmRootHealth, dmRootHealthBusy, dmRootHealthMsg, setDmRootHealthMsg,
    rnsStatus,
    fetchWormhole, fetchPrivacyProfile, fetchRnsStatus, fetchWormholeStatus, fetchDmRootHealth,
    saveWormholeSettings, toggleWormhole, quickStartWormhole, controlWormhole, setHighPrivacy,
    configuredTransport, activeTransport, effectiveTransport, anonModeReady, rnsReady,
    recentPrivateFallback, recentPrivateFallbackReason, legacyCompatibilityItems, legacyCompatibilityActivity, legacyCompatibilityAllBlocked,
    gateCompatTopReasons, trustModeLabel, transportMismatch, wormholeQuickButtonLabel, dmRootCardTone,
  };
}
