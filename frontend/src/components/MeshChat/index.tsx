'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import AgentShellPanel from './AgentShellPanel';
import InfonetTerminalPanel from './InfonetTerminalPanel';
import { MeshChatMeshtasticTab } from './MeshChatMeshtasticTab';
import { MeshChatInputBar } from './MeshChatInputBar';
import { MeshGatePersonaPrompt } from './MeshGatePersonaPrompt';
import { MeshSenderPopup } from './MeshSenderPopup';
import { MeshMuteDialog } from './MeshMuteDialog';
import {
  INFONET_FLYOUT_MIN_HEIGHT,
  INFONET_FLYOUT_WIDTH,
  measureMeshChatFlyout,
  SHELL_FLYOUT_MIN_HEIGHT,
  SHELL_FLYOUT_WIDTH,
  type MeshChatFlyoutRect } from './meshChatFlyout';
import { endInfonetTerminalSession } from '@/lib/infonetTerminalSession';
import { requestInfonetLeave } from '@/lib/infonetLeaveNotice';
import { motion, AnimatePresence } from '@/lib/motion';
import {
  Antenna,
  Minus,
  Plus,
  Send,
  ArrowUp,
  ArrowDown,
  Radio,
  Shield,
  Terminal,
  SquareTerminal,
  UserPlus,
  Lock,
  Check,
  X,
  Ban,
  MapPin,
  EyeOff,
  Eye } from 'lucide-react';
import {
  isEncryptedGateEnvelope,
  gateEnvelopeState,
  gateEnvelopeDisplayText } from '@/mesh/gateEnvelope';
import {
  getContactTrustSummary,
  rootWitnessBadgeLabel,
  rootWitnessContinuityLabel } from '@/mesh/contactTrustSummary';
import {
  shortTrustFingerprint } from '@/mesh/meshPrivacyHints';
import {
  shouldAllowRequestActions } from '@/mesh/requestSenderRecovery';
import { useMeshChatController } from './useMeshChatController';
import { RepBadge } from './RepBadge';
import { timeAgo } from './utils';
import { MSG_COLORS } from './types';
import type { MeshChatProps, Tab } from './types';

function describeGateCompatConsentPrompt(action: string): string {
  switch (String(action || '')) {
    case 'decrypt':
      return 'Use compatibility mode for this room to read messages on this device.';
    case 'compose':
    case 'post':
      return 'Use compatibility mode for this room to send messages on this device.';
    default:
      return 'Use compatibility mode for this room on this device.';
  }
}

function describeGateCompatReason(reason: string, gateId: string): string {
  const normalizedGate = String(gateId || '').trim().toLowerCase();
  const detail = String(reason || '').trim().toLowerCase();
  if (!detail || detail === 'browser_local_gate_crypto_unavailable') {
    return 'Local gate crypto failed on this device.';
  }
  if (detail === 'browser_gate_worker_unavailable') {
    return 'This runtime cannot use the local gate worker.';
  }
  if (detail.startsWith('browser_gate_state_resync_required:')) {
    return normalizedGate
      ? `Local ${normalizedGate} state needs a resync on this device.`
      : 'Local gate state needs a resync on this device.';
  }
  if (
    detail.startsWith('browser_gate_state_mapping_missing_group:') ||
    detail === 'browser_gate_state_active_member_missing'
  ) {
    return 'Local gate state is incomplete on this device.';
  }
  if (detail === 'worker_gate_wrap_key_missing') {
    return 'Secure local gate storage is unavailable in this browser.';
  }
  if (detail === 'gate_mls_decrypt_failed') {
    return 'Local gate decrypt failed on this device.';
  }
  return 'Local gate crypto failed on this device.';
}

// ─── Presentational Shell ──────────────────────────────────────────────────
// Calls the controller hook and renders the full MeshChat UI.
// NO direct trust-mutating imports — all mutations go through the hook.

const MeshChat = React.memo(function MeshChat(props: MeshChatProps) {
  const panelBoxRef = useRef<HTMLDivElement>(null);
  const [shellExpanded, setShellExpanded] = useState(false);
  const [shellFlyout, setShellFlyout] = useState<MeshChatFlyoutRect | null>(null);
  const [shellDockHeight, setShellDockHeight] = useState(0);
  const [infonetExpanded, setInfonetExpanded] = useState(true);
  const [infonetFlyout, setInfonetFlyout] = useState<MeshChatFlyoutRect | null>(null);
  const [infonetDockHeight, setInfonetDockHeight] = useState(0);
  const ctrl = useMeshChatController(props);
  const {
    // UI state
    expanded,
    setExpanded,
    activeTab,
    setActiveTab,
    inputValue,
    setInputValue,
    busy,
    sendError,
    setSendError,
    identityWizardOpen,
    setIdentityWizardOpen,
    infonetUnlockOpen,
    setInfonetUnlockOpen,
    deadDropUnlockOpen,
    setDeadDropUnlockOpen,
    identityWizardBusy,
    identityWizardStatus,
    setIdentityWizardStatus,
    meshQuickStatus,
    meshSessionActive,
    publicMeshAddress,
    activePublicMeshAddress,
    meshView,
    setMeshView,
    meshDirectTarget,
    setMeshDirectTarget,
    meshAddressDraft,
    setMeshAddressDraft,
    meshMqttSettings,
    meshMqttForm,
    setMeshMqttForm,
    meshMqttBusy,
    meshMqttStatusText,
    meshMqttEnabled,
    meshMqttRunning,
    meshMqttConnected,
    meshMqttConnectionLabel,
    saveMeshMqttSettings,
    refreshMeshMqttSettings,
    // Identity
    identity,
    publicIdentity,
    hasStoredPublicLaneIdentity,
    hasPublicLaneIdentity,
    canUsePublicMeshInput,
    hasId,
    shouldShowIdentityWarning,
    wormholeEnabled,
    wormholeReadyState,
    wormholeRnsReady,
    wormholeRnsPeers,
    wormholeRnsDirectReady,
    privateInfonetReady,
    publicMeshBlockedByWormhole,
    anonymousModeEnabled,
    anonymousModeReady,
    anonymousPublicBlocked,
    anonymousDmBlocked,
    unresolvedSenderSealCount,
    privacyProfile,
    // Frozen contract items
    enqueueDmSend,
    flushDmQueue,
    secureDmBlocked,
    selectedGateAccessReady,
    selectedGateKeyStatus,
    // InfoNet
    gates,
    selectedGate,
    setSelectedGate,
    filteredInfoMessages,
    infoVerification,
    reps,
    votedOn,
    gateReplyContext,
    setGateReplyContext,
    showCreateGate,
    setShowCreateGate,
    newGateId,
    setNewGateId,
    newGateName,
    setNewGateName,
    newGateMinRep,
    setNewGateMinRep,
    gateError,
    setGateError,
    gateCompatConsentPrompt,
    gateResyncTarget,
    gatePersonaBusy,
    gateKeyBusy,
    gateResyncBusy,
    gatePersonaPromptOpen,
    selectedGatePersonaList,
    selectedGateActivePersona,
    selectedGateActivePersonaId,
    selectedGateCompatActive,
    selectedGateMeta,
    nativeAuditReport,
    nativeAuditSummary,
    gatePersonaPromptTitle,
    gatePersonaPromptPersonaList,
    gatePersonaDraftLabel,
    setGatePersonaDraftLabel,
    gatePersonaPromptError,
    setGatePersonaPromptError,
    gatePersonaPromptGateId,
    // Meshtastic
    meshRegion,
    setMeshRegion,
    meshRoots,
    meshChannel,
    setMeshChannel,
    meshChannels,
    activeChannels,
    filteredMeshMessages,
    meshInboxMessages,
    // Dead Drop / DM
    contacts,
    contactList,
    selectedContact,
    setSelectedContact,
    selectedContactInfo,
    dmView,
    setDmView,
    dmMessages,
    setDmMessages,
    dmMaintenanceBusy,
    lastDmTransport,
    sasPhrase,
    showSas,
    setShowSas,
    sasConfirmInput,
    setSasConfirmInput,
    geoHintEnabled,
    decoyEnabled,
    dmUnread,
    accessRequests,
    pendingSent,
    addContactId,
    setAddContactId,
    showAddContact,
    setShowAddContact,
    totalDmNotify,
    dmTransportMode,
    dmTransportStatus,
    dmTrustHint,
    dmTrustPrimaryAction,
    // Mute
    mutedUsers,
    mutedArray,
    senderPopup,
    setSenderPopup,
    muteConfirm,
    setMuteConfirm,
    senderPopupContact,
    // Handlers
    handleSend,
    handleVote,
    handleCreateGate,
    handleCreateGatePersona,
    handleSelectGatePersona,
    handleRetireGatePersona,
    handleRotateGateKey,
    handleResyncGateState,
    handleApproveGateCompatFallback,
    handleUnlockEncryptedGate,
    handleReplyToGateMessage,
    handleReplyToMeshAddress,
    handleSenderClick,
    handleMute,
    handleUnmute,
    handleLocateUser,
    handleRequestAccess,
    handleAcceptRequest,
    handleDenyRequest,
    handleBlockDM,
    handleVouch,
    openChat,
    handleCreatePublicIdentity,
    handleQuickCreatePublicIdentity,
    handleActivatePublicMeshSession,
    handleLeaveWormholeForPublicMesh,
    handleResetPublicIdentity,
    handleBootstrapPrivateIdentity,
    enterInfonetWormholeLane,
    infonetLaunchGate,
    clearInfonetLaunchGate,
    handleRefreshSelectedContact,
    handleResetSelectedContact,
    handleTrustSelectedRemotePrekey,
    handleConfirmSelectedContactSas,
    handleRecoverSelectedContactRootContinuity,
    openIdentityWizard,
    openGatePersonaPrompt,
    closeGatePersonaPrompt,
    submitGatePersonaPrompt,
    selectSavedGatePersona,
    remainAnonymousInGate,
    displayPublicMeshSender,
    voteScopeKey,
    openTerminal,
    focusInputComposer,
    refreshNativeAuditReport,
    // Derived display
    inputDisabled,
    privateLaneHint,
    privateInfonetBlockedDetail,
    privateInfonetTransportReady,
    dashboardRestrictedTab,
    dashboardRestrictedTitle,
    dashboardRestrictedDetail,
    wormholeDescriptor,
    // Refs
    messagesEndRef,
    inputRef,
    popupRef,
    cursorMirrorRef,
    cursorMarkerRef,
    inputCursorIndex,
    setInputCursorIndex,
    inputFocused,
    setInputFocused,
    handlePanelClick,
    syncCursorPosition,
    recentPrivateFallback,
    recentPrivateFallbackReason,
    onSettingsClick } = ctrl;

  useEffect(() => {
    if (activeTab !== 'dms') {
      setShellExpanded(false);
    }
  }, [activeTab]);
  const selectedContactTrustSummary = selectedContactInfo
    ? getContactTrustSummary(selectedContactInfo)
    : null;
  const dmTrustPrimaryActionRequiresInviteImport =
    selectedContactTrustSummary?.recommendedAction === 'import_invite';
  const dmTrustPrimaryButtonLabel =
    dmTrustPrimaryActionRequiresInviteImport || !showSas ? dmTrustPrimaryAction : 'HIDE SAS';
  const handleDmTrustPrimaryAction = () => {
    if (dmTrustPrimaryActionRequiresInviteImport) {
      openTerminal();
      return;
    }
    setShowSas((prev) => !prev);
  };
  const handleRequestComposerAction = () => {
    const pasted = addContactId.trim();
    if (!pasted) return;
    void handleRequestAccess(pasted);
  };
  const meshActivationText =
    publicMeshBlockedByWormhole
      ? hasStoredPublicLaneIdentity
        ? 'Wormhole is active. Turning Meshtastic Chat on will turn Wormhole off and use your saved Meshtastic key.'
        : 'Wormhole is active. Turning Meshtastic Chat on will turn Wormhole off and mint a separate Meshtastic key.'
      : hasStoredPublicLaneIdentity
        ? 'Meshtastic Chat is off. Turn it on to use your saved Meshtastic key.'
        : 'Meshtastic posting needs a radio key. One tap gets you a fresh address.';
  const handleMeshActivationAction = () => {
    if (hasStoredPublicLaneIdentity) {
      void handleActivatePublicMeshSession();
      return;
    }
    if (publicMeshBlockedByWormhole) {
      void handleLeaveWormholeForPublicMesh();
      return;
    }
    void handleQuickCreatePublicIdentity();
  };
  const normalizeMeshDirectAddress = (value: string) => {
    const compact = value.trim().replace(/^!/, '').toLowerCase();
    return /^[0-9a-f]{8}$/.test(compact) ? `!${compact}` : '';
  };
  const handleMeshDirectTargetSubmit = () => {
    const target = normalizeMeshDirectAddress(meshAddressDraft);
    if (!target) {
      setSendError('enter node address like !1ee21986');
      window.setTimeout(() => setSendError(''), 4000);
      return;
    }
    setMeshDirectTarget(target);
    setMeshView('channel');
    window.setTimeout(() => inputRef.current?.focus(), 0);
  };
  const meshActivationLabel = identityWizardBusy
    ? 'GETTING MESHTASTIC KEY'
    : hasStoredPublicLaneIdentity
      ? 'TURN ON MESHTASTIC'
      : publicMeshBlockedByWormhole
        ? 'TURN OFF WORMHOLE FOR MESHTASTIC'
        : 'GET MESHTASTIC KEY';
  const meshActivationSideLabel = identityWizardBusy
    ? 'WORKING...'
    : hasStoredPublicLaneIdentity
      ? 'USE SAVED KEY'
      : publicMeshBlockedByWormhole
        ? 'AUTO DISABLE'
        : 'ONE TAP';

  const handleShellExpandedChange = useCallback((next: boolean) => {
    if (next && panelBoxRef.current) {
      const anchor = panelBoxRef.current.getBoundingClientRect();
      setShellDockHeight(anchor.height);
      setShellFlyout(measureMeshChatFlyout(anchor, SHELL_FLYOUT_WIDTH, SHELL_FLYOUT_MIN_HEIGHT));
    } else {
      setShellFlyout(null);
      setShellDockHeight(0);
    }
    setShellExpanded(next);
  }, []);

  const handleInfonetExpandedChange = useCallback((next: boolean) => {
    if (next && panelBoxRef.current) {
      const anchor = panelBoxRef.current.getBoundingClientRect();
      setInfonetDockHeight(anchor.height);
      setInfonetFlyout(measureMeshChatFlyout(anchor, INFONET_FLYOUT_WIDTH, INFONET_FLYOUT_MIN_HEIGHT));
    } else {
      setInfonetFlyout(null);
      setInfonetDockHeight(0);
    }
    setInfonetExpanded(next);
  }, []);

  const handleInfonetTeardown = useCallback(() => {
    void endInfonetTerminalSession();
  }, []);

  const panelFlyout =
    activeTab === 'infonet' ? infonetFlyout : activeTab === 'dms' ? shellFlyout : null;
  const panelDockHeight =
    activeTab === 'infonet' ? infonetDockHeight : activeTab === 'dms' ? shellDockHeight : 0;
  const panelFlyoutMinHeight =
    activeTab === 'infonet' ? INFONET_FLYOUT_MIN_HEIGHT : SHELL_FLYOUT_MIN_HEIGHT;

  useEffect(() => {
    if (!shellExpanded) return;
    const syncFlyout = () => {
      setShellFlyout((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          width: Math.min(SHELL_FLYOUT_WIDTH, Math.max(320, window.innerWidth - 48)),
          height: Math.min(
            Math.max(prev.height, SHELL_FLYOUT_MIN_HEIGHT),
            window.innerHeight - prev.top - 36,
          ) };
      });
    };
    window.addEventListener('resize', syncFlyout);
    return () => window.removeEventListener('resize', syncFlyout);
  }, [shellExpanded]);

  useEffect(() => {
    if (!infonetExpanded) return;
    const syncFlyout = () => {
      setInfonetFlyout((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          width: Math.min(INFONET_FLYOUT_WIDTH, Math.max(320, window.innerWidth - 48)),
          height: Math.min(
            Math.max(prev.height, INFONET_FLYOUT_MIN_HEIGHT),
            window.innerHeight - prev.top - 36,
          ) };
      });
    };
    window.addEventListener('resize', syncFlyout);
    return () => window.removeEventListener('resize', syncFlyout);
  }, [infonetExpanded]);

  useEffect(() => {
    if (!expanded && shellExpanded) {
      handleShellExpandedChange(false);
    }
  }, [expanded, shellExpanded, handleShellExpandedChange]);

  useEffect(() => {
    if (activeTab !== 'dms' && shellExpanded) {
      handleShellExpandedChange(false);
    }
  }, [activeTab, shellExpanded, handleShellExpandedChange]);

  useEffect(() => {
    if (activeTab !== 'infonet' && infonetExpanded) {
      handleInfonetExpandedChange(false);
    }
  }, [activeTab, infonetExpanded, handleInfonetExpandedChange]);

  useEffect(() => {
    if (activeTab === 'infonet' && expanded && infonetExpanded && !infonetFlyout && panelBoxRef.current) {
      handleInfonetExpandedChange(true);
    }
  }, [activeTab, expanded, infonetExpanded, infonetFlyout, handleInfonetExpandedChange]);

  const infonetSessionWasActiveRef = useRef(false);
  useEffect(() => {
    const infonetActive = activeTab === 'infonet' && expanded;
    if (infonetActive) {
      infonetSessionWasActiveRef.current = true;
      return;
    }
    if (!infonetSessionWasActiveRef.current) return;
    infonetSessionWasActiveRef.current = false;
    handleInfonetTeardown();
  }, [activeTab, expanded, handleInfonetTeardown]);

  return (
    <div
      onClick={handlePanelClick}
      className={`pointer-events-auto flex flex-col ${expanded ? 'flex-1 min-h-[236px]' : 'flex-shrink-0'}`}
    >
      {panelFlyout && panelDockHeight > 0 && (
        <div aria-hidden className="pointer-events-none shrink-0" style={{ height: panelDockHeight }} />
      )}

      {/* Single unified box — matches Data Layers panel skin */}
      <div
        ref={panelBoxRef}
        className={`sb-panel flex flex-col relative overflow-hidden ${
          panelFlyout ? 'z-[210] shadow-[0_0_28px_rgba(8,145,178,0.14)]' : ''
        }`}
        style={{
          boxShadow: panelFlyout
            ? undefined
            : undefined,
          ...(expanded ? { flex: panelFlyout ? undefined : '1 1 0', minHeight: panelFlyout ? undefined : 0 } : {}),
          ...(panelFlyout
            ? {
                position: 'fixed',
                top: panelFlyout.top,
                left: panelFlyout.left,
                width: panelFlyout.width,
                height: panelFlyout.height,
                minHeight: panelFlyoutMinHeight,
                maxHeight: `calc(100vh - ${panelFlyout.top}px - 2.25rem)` }
            : {}) }}
      >
        {/* HEADER */}
        <div
          onClick={() => {
            if (expanded && activeTab === 'infonet') {
              requestInfonetLeave(() => setExpanded(false));
            } else {
              setExpanded(!expanded);
            }
          }}
          className="flex items-center justify-between px-3 py-2.5 cursor-pointer hover:bg-cyan-950/30 transition-colors border-b border-cyan-900/40 shrink-0 select-none"
        >
          <div className="flex items-center gap-2">
            <Antenna size={16} className="text-cyan-400" />
            <span className="sb-title text-cyan-400">
              COMMS
            </span>
            {totalDmNotify > 0 && (
              <span className="text-[11px] font-mono px-1.5 py-0.5 bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-[blink_1s_step-end_infinite]" />
                {totalDmNotify}
              </span>
            )}
          </div>
          {expanded ? (
            <Minus size={16} className="text-cyan-400" />
          ) : (
            <Plus size={16} className="text-cyan-400" />
          )}
        </div>

        {/* EXPANDED BODY */}
        {expanded && (
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            {/* TAB BAR — segmented control */}
            <div className="sb-seg flex items-center gap-1 shrink-0" role="tablist" aria-label="Chat mode">
              {[
                {
                  key: 'dms' as Tab,
                  label: 'SHELL',
                  icon: <SquareTerminal size={10} />,
                  badge: 0 },
                { key: 'infonet' as Tab, label: 'INFONET', icon: <Shield size={10} />, badge: 0 },
                { key: 'meshtastic' as Tab, label: 'MESHTASTIC', icon: <Radio size={10} />, badge: 0 },
              ].map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => {
                    if (activeTab === 'infonet' && tab.key !== 'infonet') {
                      requestInfonetLeave(() => setActiveTab(tab.key));
                    } else {
                      setActiveTab(tab.key);
                    }
                  }}
                  role="tab"
                  aria-selected={activeTab === tab.key}
                  className={`sb-seg-btn flex-auto px-2 flex items-center justify-center gap-1.5 text-[11px] font-mono tracking-[0.06em] transition-colors ${
                    activeTab === tab.key
                      ? 'is-active text-cyan-200 font-bold'
                      : 'text-[var(--text-muted)] hover:text-cyan-300'
                  }`}
                >
                  <span className="sb-seg-icon">{tab.icon}</span>
                  {tab.key === 'meshtastic' ? (
                    <>
                      <span className="sb-label-long">{tab.label}</span>
                      <span className="sb-label-short">MESH</span>
                    </>
                  ) : (
                    <span>{tab.label}</span>
                  )}
                  {tab.badge > 0 && (
                    <span className="ml-0.5 w-1.5 h-1.5 rounded-full bg-cyan-400 animate-[blink_1s_step-end_infinite]" />
                  )}
                </button>
              ))}
              <button
                onClick={() => {
                  setIdentityWizardStatus(null);
                  setIdentityWizardOpen(true);
                }}
                className="sb-seg-btn shrink-0 w-8 flex items-center justify-center text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
                title="Identity and OPSEC setup"
                aria-label="Identity and OPSEC setup"
              >
                <UserPlus size={11} />
              </button>
            </div>

            {privacyProfile === 'high' && !wormholeEnabled && activeTab !== 'dms' && activeTab !== 'infonet' && (
              <div className="px-3 py-2 text-sm font-mono text-red-400/90 border-b border-red-900/30 bg-red-950/20 leading-[1.65] shrink-0">
                High Privacy is ON but Wormhole is OFF. Private messaging is blocked until
                Wormhole is enabled.
              </div>
            )}

            {activeTab !== 'dms' && activeTab !== 'infonet' && activeTab !== 'meshtastic' && wormholeEnabled && !wormholeReadyState && (
              <div className="px-3 py-2 text-sm font-mono text-red-400/90 border-b border-red-900/30 bg-red-950/20 leading-[1.65] shrink-0">
                Wormhole secure mode is enabled but the local agent is not ready. Dead Drop is
                blocked until Wormhole is running.
              </div>
            )}

            {activeTab !== 'dms' && activeTab !== 'infonet' && activeTab !== 'meshtastic' && wormholeEnabled && wormholeReadyState && (
              <div className="px-3 py-2 text-sm font-mono text-yellow-400/80 border-b border-yellow-900/20 bg-yellow-950/10 leading-[1.65] shrink-0">
                Wormhole secure mode is active. Experimental private-lane operations are routed
                through the local agent and current secure transport paths.
              </div>
            )}

            {activeTab !== 'dms' && activeTab !== 'infonet' && activeTab !== 'meshtastic' && wormholeEnabled && wormholeReadyState && !wormholeRnsReady && (
              <div className="px-3 py-2 text-sm font-mono text-amber-300/90 border-b border-amber-900/30 bg-amber-950/20 leading-[1.65] shrink-0">
                TRANSITIONAL PRIVATE LANE. Wormhole is up and gate chat is available on the
                transitional lane. Reticulum is still warming — Dead Drop / DM requires the
                stronger PRIVATE / STRONG tier and is managed separately.
              </div>
            )}

            {activeTab !== 'dms' && activeTab !== 'infonet' && activeTab !== 'meshtastic' && anonymousModeEnabled && !anonymousModeReady && (
              <div className="px-3 py-2 text-sm font-mono text-red-400/90 border-b border-red-900/30 bg-red-950/20 leading-[1.65] shrink-0">
                Anonymous mode is active, but hidden transport is not ready. Dead Drop is blocked
                until Wormhole is running over Tor, I2P, or Mixnet.
              </div>
            )}

            {/* No identity warning */}
            {shouldShowIdentityWarning && activeTab !== 'dms' && activeTab !== 'infonet' && (
              <div className="px-3 py-2 text-sm font-mono text-yellow-500/80 border-b border-yellow-900/20 bg-yellow-950/10 leading-[1.65] shrink-0">
                <Lock size={9} className="inline mr-1" />
                Run <span className="text-cyan-400">connect</span> in MeshTerminal first, or open
                <button
                  onClick={() => {
                    setIdentityWizardStatus(null);
                    setIdentityWizardOpen(true);
                  }}
                  className="ml-1 text-cyan-400 hover:text-cyan-300 underline underline-offset-2"
                >
                  IDENTITY SETUP
                </button>
              </div>
            )}

            {privateLaneHint && activeTab !== 'dms' && activeTab !== 'infonet' && (
              <div
                className={`px-3 py-2 border-b leading-[1.65] shrink-0 ${
                  privateLaneHint.severity === 'danger'
                    ? 'border-red-900/30 bg-red-950/20 text-red-300'
                    : 'border-amber-900/30 bg-amber-950/10 text-amber-200'
                }`}
              >
                <div className="text-[13px] font-mono tracking-[0.18em] mb-1">
                  {privateLaneHint.title}
                </div>
                <div className="text-sm font-mono">{privateLaneHint.detail}</div>
              </div>
            )}

            {/* CONTENT AREA */}
            <div className="flex-1 overflow-hidden flex flex-col min-h-0">
              {activeTab === 'dms' && (
                <AgentShellPanel
                  active={expanded && activeTab === 'dms'}
                  expanded={shellExpanded}
                  onExpandedChange={handleShellExpandedChange}
                />
              )}
              {activeTab === 'infonet' && (
                <InfonetTerminalPanel
                  active={expanded && activeTab === 'infonet'}
                  expanded={infonetExpanded}
                  wormholeBusy={identityWizardBusy}
                  launchGate={infonetLaunchGate}
                  onExpandedChange={handleInfonetExpandedChange}
                  onEnterWormhole={enterInfonetWormholeLane}
                  onTeardown={handleInfonetTeardown}
                  onLaunchGateConsumed={clearInfonetLaunchGate}
                  onOpenDeadDrop={props.onOpenDeadDrop}
                />
              )}

              <MeshChatMeshtasticTab p={{ activeChannels, activePublicMeshAddress, activeTab, canUsePublicMeshInput, displayPublicMeshSender, filteredMeshMessages, handleMeshDirectTargetSubmit, handleSenderClick, identity, inputRef, meshAddressDraft, meshChannel, meshChannels, meshDirectTarget, meshInboxMessages, meshMqttBusy, meshMqttConnected, meshMqttConnectionLabel, meshMqttEnabled, meshMqttForm, meshMqttRunning, meshMqttSettings, meshMqttStatusText, meshRegion, meshRoots, meshView, messagesEndRef, refreshMeshMqttSettings, saveMeshMqttSettings, setMeshAddressDraft, setMeshChannel, setMeshDirectTarget, setMeshMqttForm, setMeshRegion, setMeshView, timeAgo }} />
              {/* Dead Drop chat UI: Infonet Terminal → Messages */}
            </div>

            <MeshChatInputBar p={{ activeTab, sendError, canUsePublicMeshInput, meshDirectTarget, activePublicMeshAddress, meshRegion, meshChannel, publicMeshBlockedByWormhole, hasStoredPublicLaneIdentity, meshQuickStatus, openIdentityWizard, meshAddressDraft, setMeshAddressDraft, handleMeshDirectTargetSubmit, handleActivatePublicMeshSession, handleLeaveWormholeForPublicMesh, identityWizardBusy,    inputDisabled, privateLaneHint, inputRef, inputValue, setInputValue, handleSend, busy,  expanded,  dashboardRestrictedTab, dashboardRestrictedTitle, privateInfonetBlockedDetail, privateInfonetTransportReady }} />
          </div>
        )}

      <MeshGatePersonaPrompt p={{ gatePersonaPromptOpen, gatePersonaPromptTitle, closeGatePersonaPrompt,  gatePersonaBusy, submitGatePersonaPrompt, setActiveTab,  selectSavedGatePersona, remainAnonymousInGate, gatePersonaPromptError, gatePersonaDraftLabel}} />
      <MeshSenderPopup senderPopup={senderPopup} popupRef={popupRef} mutedUsers={mutedUsers} handleUnmute={handleUnmute} setMuteConfirm={setMuteConfirm} handleReplyToMeshAddress={handleReplyToMeshAddress} handleLocateUser={handleLocateUser} hasId={hasId} identity={identity} senderPopupContact={senderPopupContact} setSenderPopup={setSenderPopup} requestInfonetLeave={requestInfonetLeave} setActiveTab={setActiveTab} openChat={openChat} handleRequestAccess={handleRequestAccess} handleBlockDM={handleBlockDM} />

      <MeshMuteDialog muteConfirm={muteConfirm} setMuteConfirm={setMuteConfirm} setSenderPopup={setSenderPopup} handleMute={handleMute} />
      </div>
    </div>
  );
});

export default MeshChat;
