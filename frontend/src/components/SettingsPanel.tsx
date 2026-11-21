'use client';

import { SettingsPanelNewsFeeds } from './SettingsPanelNewsFeeds';
import { SettingsPanelApiKeys } from './SettingsPanelApiKeys';
import { SettingsPanelProtocol } from './SettingsPanelProtocol';
import { SentinelTab } from './SettingsPanelSentinelTab';
import { SarSettingsTab } from './SettingsPanelSarTab';
import { useSettingsPanelFeeds } from './useSettingsPanelFeeds';
import { useSettingsPanelApiKeys } from './useSettingsPanelApiKeys';
import { useSettingsPanelAdminSession } from './useSettingsPanelAdminSession';
import { useTimeMachineSetting } from './useTimeMachineSetting';
import { useCompanionSetting } from './useCompanionSetting';
import { useSettingsPanelGateStatus } from './useSettingsPanelGateStatus';
import { useSettingsPanelBrowserWipe } from './useSettingsPanelBrowserWipe';
import { useSettingsPanelWormhole } from './useSettingsPanelWormhole';
import { clearAdminSession } from '@/lib/adminSession';
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
  const [, setStrictPrivacy] = useState(() => getPrivacyStrictPreference());
  const [privacyProfile, setPrivacyProfile] = useState(() => getPrivacyProfilePreference());
  const [sessionMode, setSessionMode] = useState(() => getSessionModePreference());
  const wormholeEnabledRef = React.useRef(false);
  const { browserWipeBusy, browserWipeMsg, wipeLocalMeshTraces, clearSessionIdentity } = useSettingsPanelBrowserWipe({ wormholeEnabledRef, setSessionMode });
  const { gateCompatTelemetry, gateLocalRuntimeStatus } = useSettingsPanelGateStatus();
  const { tmEnabled, tmSaving, toggleTimeMachine } = useTimeMachineSetting(isOpen, activeTab);
  const { companionAvailable, companion, companionBusy, companionError, companionLoadFailed, toggleCompanion, openCompanionBrowser } = useCompanionSetting(isOpen, activeTab);

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
        setDmRootHealthRef.current(null);
        setDmRootHealthMsgRef.current(message);
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
  } = useSettingsPanelAdminSession({ activeTab, fetchKeys, fetchFeeds, setDmRootHealth: (v:any)=>setDmRootHealthRef.current(v), setDmRootHealthMsg: (v:string|null)=>setDmRootHealthMsgRef.current(v) });
  setAdminSessionReadyRef.current = setAdminSessionReady;
  setAdminSessionMsgRef.current = setAdminSessionMsg;

  const wh = useSettingsPanelWormhole({
    isOpen, activeTab, onClose, nativeProtected, adminSessionReady, showOperatorTools,
    refreshAdminSession, fetchKeys, fetchFeeds, fetchEnvMeta, handleProtectedSettingsError, ensureAdminSession,
    setActiveTab, setFeeds, setFeedsDirty, clearSessionIdentity,
    privacyProfile, setPrivacyProfile, sessionMode, setSessionMode, setStrictPrivacy,
    gateCompatTelemetry,
  });
  wormholeEnabledRef.current = wh.wormholeEnabled;
  setDmRootHealthRef.current = wh.setDmRootHealth;
  setDmRootHealthMsgRef.current = wh.setDmRootHealthMsg;
  const {
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
  } = wh;



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
              }} />
            )}

            {activeTab === 'api-keys' && (
              <SettingsPanelApiKeys
                ctx={{
                  envMeta, apis, grouped, expandedCategories, toggleCategory,
                  fetchKeys, adminSessionReady, showOperatorTools,
                  apiKeyInputs, apiKeyEditing, apiKeySaving, apiKeyMsg,
                  setApiKeyInputs, setApiKeyEditing, saveApiKey,
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
