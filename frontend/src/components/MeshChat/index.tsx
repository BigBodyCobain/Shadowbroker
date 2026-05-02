'use client';

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
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
  UserPlus,
  Lock,
  Check,
  X,
  Ban,
  MapPin,
  EyeOff,
  Eye,
} from 'lucide-react';
import {
  isEncryptedGateEnvelope,
  gateEnvelopeState,
  gateEnvelopeDisplayText,
} from '@/mesh/gateEnvelope';
import {
  getContactTrustSummary,
  rootWitnessBadgeLabel,
  rootWitnessContinuityLabel,
} from '@/mesh/contactTrustSummary';
import {
  shortTrustFingerprint,
} from '@/mesh/meshPrivacyHints';
import {
  shouldAllowRequestActions,
} from '@/mesh/requestSenderRecovery';
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
    publicMeshAddress,
    meshView,
    setMeshView,
    meshDirectTarget,
    setMeshDirectTarget,
    // Identity
    identity,
    publicIdentity,
    hasPublicLaneIdentity,
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
    handleLeaveWormholeForPublicMesh,
    handleResetPublicIdentity,
    handleBootstrapPrivateIdentity,
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
    onSettingsClick,
  } = ctrl;
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
    const targetId = addContactId.trim();
    if (!targetId) return;
    const inviteLookupHandle = String(
      contacts[targetId]?.invitePinnedPrekeyLookupHandle || '',
    ).trim();
    if (!inviteLookupHandle) {
      openTerminal();
    }
    void handleRequestAccess(targetId);
  };

  return (
    <div
      onClick={handlePanelClick}
      className={`pointer-events-auto flex flex-col ${expanded ? 'flex-1 min-h-[300px]' : 'flex-shrink-0'}`}
    >
      {/* Single unified box — matches Data Layers panel skin */}
      <div
        className={`bg-[#0a0a0a]/90 backdrop-blur-sm border border-cyan-900/40 flex flex-col relative overflow-hidden`}
        style={{ boxShadow: '0 0 15px rgba(8,145,178,0.06), inset 0 0 20px rgba(0,0,0,0.4)', ...(expanded ? { flex: '1 1 0', minHeight: 0 } : {}) }}
      >
        {/* HEADER */}
        <div
          onClick={() => setExpanded(!expanded)}
          className="flex items-center justify-between px-3 py-2.5 cursor-pointer hover:bg-cyan-950/30 transition-colors border-b border-cyan-900/40 shrink-0 select-none"
        >
          <div className="flex items-center gap-2">
            <Antenna size={16} className="text-cyan-400" />
            <span className="text-[12px] text-cyan-400 font-mono tracking-widest font-bold">
              MESH CHAT
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
            {/* TAB BAR */}
            <div className="flex border-b border-[var(--border-primary)]/50 shrink-0">
              {[
                { key: 'infonet' as Tab, label: 'INFONET', icon: <Shield size={10} />, badge: 0 },
                { key: 'meshtastic' as Tab, label: 'MESH', icon: <Radio size={10} />, badge: 0 },
                {
                  key: 'dms' as Tab,
                  label: 'DEAD DROP',
                  icon: <Lock size={10} />,
                  badge: totalDmNotify,
                },
              ].map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => {
                    setActiveTab(tab.key);
                    if (tab.key === 'dms') setDmView('contacts');
                  }}
                  className={`flex-1 flex items-center justify-center gap-1 py-1.5 text-[12px] font-mono tracking-wider transition-colors ${
                    activeTab === tab.key
                      ? 'text-cyan-300 bg-cyan-950/50 font-bold border-b border-cyan-500/50'
                      : 'text-[var(--text-muted)] hover:text-cyan-600 border-b border-cyan-900/20'
                  }`}
                >
                  {tab.icon}
                  {tab.label}
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
                className="px-3 flex items-center justify-center border-b border-cyan-900/20 text-[var(--text-muted)] hover:text-cyan-400 hover:bg-cyan-950/30 transition-colors"
                title="Identity and OPSEC setup"
              >
                <UserPlus size={11} />
              </button>
            </div>

            {privacyProfile === 'high' && !wormholeEnabled && (
              <div className="px-3 py-2 text-sm font-mono text-red-400/90 border-b border-red-900/30 bg-red-950/20 leading-[1.65] shrink-0">
                High Privacy is ON but Wormhole is OFF. Private messaging is blocked until
                Wormhole is enabled.
              </div>
            )}

            {activeTab !== 'meshtastic' && wormholeEnabled && !wormholeReadyState && (
              <div className="px-3 py-2 text-sm font-mono text-red-400/90 border-b border-red-900/30 bg-red-950/20 leading-[1.65] shrink-0">
                Wormhole secure mode is enabled but the local agent is not ready. Dead Drop is
                blocked until Wormhole is running.
              </div>
            )}

            {activeTab !== 'meshtastic' && wormholeEnabled && wormholeReadyState && (
              <div className="px-3 py-2 text-sm font-mono text-yellow-400/80 border-b border-yellow-900/20 bg-yellow-950/10 leading-[1.65] shrink-0">
                Wormhole secure mode is active. Experimental private-lane operations are routed
                through the local agent and current secure transport paths.
              </div>
            )}

            {activeTab !== 'meshtastic' && wormholeEnabled && wormholeReadyState && !wormholeRnsReady && (
              <div className="px-3 py-2 text-sm font-mono text-amber-300/90 border-b border-amber-900/30 bg-amber-950/20 leading-[1.65] shrink-0">
                TRANSITIONAL PRIVATE LANE. Wormhole is up and gate chat is available on the
                transitional lane. Reticulum is still warming — Dead Drop / DM requires the
                stronger PRIVATE / STRONG tier and is managed separately.
              </div>
            )}

            {anonymousModeEnabled && !anonymousModeReady && (
              <div className="px-3 py-2 text-sm font-mono text-red-400/90 border-b border-red-900/30 bg-red-950/20 leading-[1.65] shrink-0">
                Anonymous mode is active, but hidden transport is not ready. Dead Drop is blocked
                until Wormhole is running over Tor, I2P, or Mixnet.
              </div>
            )}

            {/* No identity warning */}
            {shouldShowIdentityWarning && (
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

            {privateLaneHint && (
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
              {dashboardRestrictedTab && (
                <div className="flex-1 overflow-y-auto styled-scrollbar px-4 py-6 border-l-2 border-cyan-800/25 flex items-center justify-center">
                  <div className="max-w-md w-full border border-cyan-900/30 bg-cyan-950/10 px-5 py-6 text-center">
                    <div className="inline-flex items-center justify-center w-11 h-11 border border-cyan-700/40 bg-black/30 text-cyan-300 mb-3">
                      {activeTab === 'infonet' ? <Shield size={17} /> : <Lock size={17} />}
                    </div>
                    <div className="text-sm font-mono tracking-[0.24em] text-cyan-300 mb-2">
                      {dashboardRestrictedTitle}
                    </div>
                    <div className="text-sm font-mono text-[var(--text-secondary)] leading-[1.75]">
                      {dashboardRestrictedDetail}
                    </div>
                    <div className="mt-3 text-[13px] font-mono text-cyan-300/70 leading-[1.7]">
                      Use the terminal to enter Wormhole, join private gates, and work secure contact
                      flows until the dashboard client lands.
                    </div>
                  </div>
                </div>
              )}
              {/* ─── InfoNet Tab ─── */}
              {!dashboardRestrictedTab && activeTab === 'infonet' && (
                <>
                  {!privateInfonetReady ? (
                    <div className="flex-1 overflow-y-auto styled-scrollbar px-4 py-6 border-l-2 border-cyan-800/25 flex items-center justify-center">
                      <div className="max-w-sm w-full border border-cyan-900/30 bg-cyan-950/10 px-4 py-5 text-center">
                        <div className="inline-flex items-center justify-center w-10 h-10 border border-cyan-700/40 bg-black/30 text-cyan-300 mb-3">
                          <Shield size={16} />
                        </div>
                        <div className="text-sm font-mono tracking-[0.24em] text-cyan-300 mb-2">
                          PRIVATE INFONET LOCKED
                        </div>
                        <div className="text-sm font-mono text-[var(--text-secondary)] leading-[1.7]">
                          Gate chat is available on the transitional private lane through Wormhole.
                        </div>
                        <div className="mt-2 text-[13px] font-mono text-cyan-300/70">
                          Use the unlock prompt below for the full private-lane brief. Dead Drop /
                          DM is a separate, stronger private lane for direct messaging.
                        </div>
                      </div>
                    </div>
                  ) : (
                    <>
                  <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-[var(--border-primary)]/30 shrink-0">
                    <select
                      value={selectedGate}
                      onChange={(e) => setSelectedGate(e.target.value)}
                      className="flex-1 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-sm font-mono text-cyan-300 px-2 py-1 outline-none focus:border-cyan-700/50"
                    >
                      <option value="">All Gates</option>
                      {gates.map((g) => (
                        <option key={g.gate_id} value={g.gate_id}>
                          {g.display_name || g.gate_id}{g.fixed ? ' [FIXED]' : ''} ({g.message_count})
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => {
                        setShowCreateGate(false);
                        setGateError('Launch catalog is fixed for this testnet build');
                      }}
                      disabled
                      className="p-1 text-[var(--text-muted)]/50 disabled:opacity-40"
                      title="Fixed launch gate catalog"
                    >
                      <Plus size={12} />
                    </button>
                  </div>

                  {privateInfonetReady && !wormholeRnsReady && (
                    <div className="px-3 py-2 border-b border-amber-900/20 bg-amber-950/10 shrink-0">
                      <div className="text-[12px] font-mono tracking-[0.28em] text-amber-300/90">
                        TRANSITIONAL PRIVATE LANE
                      </div>
                      <div className="mt-1 text-sm font-mono text-amber-100/80 leading-[1.65]">
                        Gate chat is live on the transitional private lane. Timing and membership
                        activity remain visible to the service on this lane.
                      </div>
                      <div className="mt-1 text-[13px] font-mono text-amber-300/70 leading-[1.6]">
                        Dead Drop / DM is a separate, stronger lane requiring PRIVATE / STRONG
                        transport. Use Dead Drop for the strongest content and metadata privacy.
                      </div>
                      <div className="mt-1 text-[13px] font-mono text-amber-300/75">
                        RNS peers {wormholeRnsPeers.active}/{wormholeRnsPeers.configured}
                        {wormholeRnsDirectReady
                          ? ' • direct private DM path ready'
                          : ' • direct peer paths still warming'}
                      </div>
                    </div>
                  )}

                  {selectedGate && wormholeEnabled && wormholeReadyState && (
                    <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-[var(--border-primary)]/20 shrink-0 bg-cyan-950/10">
                      <div className="text-[12px] font-mono tracking-[0.28em] text-cyan-400/80 whitespace-nowrap">
                        GATE FACE
                      </div>
                      <select
                        value={selectedGateActivePersonaId || '__anon__'}
                        onChange={(e) => void handleSelectGatePersona(e.target.value)}
                        disabled={gatePersonaBusy || anonymousPublicBlocked}
                        className="flex-1 bg-[var(--bg-secondary)]/40 border border-[var(--border-primary)] text-[13px] font-mono text-cyan-300 px-2 py-1 outline-none focus:border-cyan-700/50 disabled:opacity-60"
                      >
                        <option value="__anon__">ANON SESSION</option>
                        {selectedGatePersonaList.map((persona) => (
                          <option key={persona.persona_id || persona.node_id} value={persona.persona_id || ''}>
                            {persona.label || persona.persona_id || persona.node_id.slice(0, 10)}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => openGatePersonaPrompt()}
                        disabled={gatePersonaBusy || anonymousPublicBlocked}
                        className="px-2 py-1 text-[12px] font-mono tracking-[0.2em] border border-cyan-700/40 text-cyan-300 hover:bg-cyan-950/40 disabled:opacity-60 transition-colors"
                        title="Create a gate-local face"
                      >
                        NEW FACE
                      </button>
                      <button
                        onClick={() => void handleRetireGatePersona()}
                        disabled={
                          gatePersonaBusy ||
                          anonymousPublicBlocked ||
                          !selectedGateActivePersonaId
                        }
                        className="px-2 py-1 text-[12px] font-mono tracking-[0.2em] border border-red-700/40 text-red-300 hover:bg-red-950/40 disabled:opacity-60 transition-colors"
                        title="Retire the active gate persona"
                      >
                        RETIRE
                      </button>
                    </div>
                  )}

                  {selectedGate && wormholeEnabled && wormholeReadyState && (
                    <div className="px-3 py-1.5 border-b border-[var(--border-primary)]/20 shrink-0 bg-[var(--bg-secondary)]/20 text-[12px] font-mono text-[var(--text-muted)] leading-relaxed">
                      <div className="text-cyan-300/80 mb-1">
                        {selectedGateActivePersona
                          ? `Active face: ${selectedGateActivePersona.label || selectedGateActivePersona.persona_id || selectedGateActivePersona.node_id}`
                          : 'Active face: anonymous session'}
                        {selectedGatePersonaList.length > 0
                          ? ` | saved personas: ${selectedGatePersonaList.length}`
                          : ' | no saved personas yet'}
                      </div>
                      Anonymous gate entry rotates to a fresh gate-scoped session identity and
                      does not emit a public join/leave breadcrumb.
                    </div>
                  )}

                  {selectedGate && wormholeEnabled && wormholeReadyState && selectedGateKeyStatus && (
                    <div className="px-3 py-2 border-b border-cyan-900/20 bg-cyan-950/5 shrink-0">
                      <div className="flex items-center gap-2 text-[12px] font-mono tracking-[0.24em] text-cyan-300/90">
                        <span>GATE KEY</span>
                        <span className="text-cyan-500/60">/</span>
                        <span>EPOCH {selectedGateKeyStatus.current_epoch || 0}</span>
                        {selectedGateKeyStatus.rekey_recommended && (
                          <span className="border border-amber-700/60 px-1 text-amber-300">
                            REKEY ADVISED
                          </span>
                        )}
                        <button
                          onClick={() => void handleRotateGateKey()}
                          disabled={gateKeyBusy}
                          className="ml-auto px-2 py-1 text-[12px] font-mono tracking-[0.2em] border border-cyan-700/40 text-cyan-300 hover:bg-cyan-950/40 disabled:opacity-60 transition-colors"
                          title="Rotate the current gate content key"
                        >
                          {gateKeyBusy ? 'ROTATING' : 'ROTATE KEY'}
                        </button>
                      </div>
                      <div className="mt-1 text-[13px] font-mono text-cyan-100/80 leading-[1.65]">
                        {selectedGateKeyStatus.has_local_access
                          ? `Access live via ${selectedGateKeyStatus.identity_scope || 'member'} identity ${String(selectedGateKeyStatus.sender_ref || selectedGateKeyStatus.identity_node_id || '').slice(0, 16)}`
                          : selectedGateKeyStatus.identity_scope === 'anonymous'
                          ? 'Anonymous gate session is active, but this install has not synced gate access yet. Refresh or reopen the gate if it does not clear.'
                          : 'No local gate key access yet. Enter the gate through Wormhole to unwrap the current epoch.'}
                      </div>
                      <div className="mt-1 text-[12px] font-mono text-cyan-300/65 leading-[1.65]">
                        {selectedGateKeyStatus.key_commitment
                          ? `KEY ${selectedGateKeyStatus.key_commitment.slice(0, 12)}`
                          : 'KEY PENDING'}
                        {selectedGateKeyStatus.previous_epoch
                          ? ` • previous epoch ${selectedGateKeyStatus.previous_epoch}`
                          : ''}
                        {selectedGateKeyStatus.last_rotated_at
                          ? ` • rotated ${timeAgo(selectedGateKeyStatus.last_rotated_at)}`
                          : ''}
                      </div>
                      {nativeAuditSummary && (
                        <div className="mt-2 border border-cyan-900/30 bg-cyan-950/20 px-2 py-1.5 text-[12px] font-mono text-cyan-200/75 leading-[1.7]">
                          <div className="flex items-center gap-2 text-cyan-300/85 tracking-[0.18em]">
                            <span>NATIVE AUDIT</span>
                            <span className="text-cyan-500/60">/</span>
                            <span>
                              {nativeAuditReport?.totalRecorded || nativeAuditReport?.totalEvents || 0} RECORDED
                            </span>
                            {nativeAuditReport &&
                              nativeAuditReport.totalRecorded > nativeAuditReport.totalEvents && (
                                <span className="text-cyan-400/60">
                                  ({nativeAuditReport.totalEvents} shown)
                                </span>
                              )}
                            <button
                              onClick={() => refreshNativeAuditReport(5)}
                              className="ml-auto px-1.5 py-0.5 border border-cyan-800/40 text-cyan-300/80 hover:bg-cyan-950/40 transition-colors"
                              title="Refresh native session-profile audit report"
                            >
                              REFRESH
                            </button>
                          </div>
                          <div className="mt-1">
                            {nativeAuditSummary.recent
                              ? `Last: ${nativeAuditSummary.recent.command}${nativeAuditSummary.recent.targetRef ? ` [${nativeAuditSummary.recent.targetRef}]` : ''} -> ${nativeAuditSummary.recent.outcome}`
                              : 'No native gate audit events yet.'}
                          </div>
                          <div className="text-cyan-300/60">
                            Profile mismatches: {nativeAuditSummary.mismatchCount} • denied: {nativeAuditSummary.deniedCount}
                          </div>
                          {nativeAuditReport?.lastProfileMismatch && (
                            <div className="text-amber-300/70">
                              {`Last mismatch: ${nativeAuditReport.lastProfileMismatch.command}${nativeAuditReport.lastProfileMismatch.targetRef ? ` [${nativeAuditReport.lastProfileMismatch.targetRef}]` : ''} (${nativeAuditReport.lastProfileMismatch.sessionProfile || 'unscoped'} -> ${nativeAuditReport.lastProfileMismatch.expectedCapability})`}
                            </div>
                          )}
                        </div>
                      )}
                      {selectedGateKeyStatus.rekey_recommended_reason && (
                        <div className="mt-1 text-[12px] font-mono text-amber-300/75 leading-[1.6]">
                          Rekey recommendation: {selectedGateKeyStatus.rekey_recommended_reason.replace(/_/g, ' ')}
                        </div>
                      )}
                      {selectedGateKeyStatus.identity_scope === 'anonymous' &&
                        !selectedGateKeyStatus.has_local_access && (
                        <div className="mt-2 flex items-center gap-2">
                          <button
                            onClick={() => void handleUnlockEncryptedGate()}
                            disabled={gatePersonaBusy}
                            className="px-2 py-1 text-[12px] font-mono tracking-[0.2em] border border-cyan-700/40 text-cyan-300 hover:bg-cyan-950/40 disabled:opacity-60 transition-colors"
                          >
                            {gatePersonaBusy
                              ? 'UNLOCKING'
                              : selectedGatePersonaList.length > 0
                                ? 'USE SAVED FACE'
                                : 'CREATE GATE FACE'}
                          </button>
                          <span className="text-[12px] font-mono text-cyan-300/55">
                            {selectedGatePersonaList.length > 0
                              ? 'Switch to a saved face if this install still cannot unlock the room anonymously.'
                              : 'Create a gate-local face only if anonymous unlock still fails on this install.'}
                          </span>
                          {selectedContactInfo && (
                            <>
                              {selectedContactInfo.remotePrekeyTransparencyConflict && (
                                <div className="mt-2 text-[13px] font-mono text-red-200/85 leading-[1.7]">
                                  prekey history conflict observed and trust stays degraded until you
                                  explicitly acknowledge the changed fingerprint.
                                </div>
                              )}
                              {selectedContactInfo.remotePrekeyLookupMode === 'legacy_agent_id' && (
                                <div className="mt-2 text-[13px] font-mono text-yellow-200/85 leading-[1.7]">
                                  bootstrap path: legacy direct agent ID lookup.
                                  {selectedContactInfo.invitePinnedPrekeyLookupHandle
                                    ? ' Refresh from the signed invite to tighten lookup privacy.'
                                    : ' Import or re-import a signed invite to avoid stable-ID lookup.'}
                                </div>
                              )}
                              {selectedContactInfo.remotePrekeyLookupMode === 'invite_lookup_handle' && (
                                <div className="mt-2 text-[13px] font-mono text-cyan-200/85 leading-[1.7]">
                                  bootstrap path: invite-scoped lookup handle. Stable agent ID was not
                                  required on the lookup path.
                                </div>
                              )}
                              {dmTrustPrimaryActionRequiresInviteImport && (
                                <div className="mt-2 text-[13px] font-mono text-emerald-200/85 leading-[1.7]">
                                  next step: import or re-import a signed invite in Secure Messages before
                                  trusting this contact as a verified first-contact anchor.
                                </div>
                              )}
                              {(selectedContactInfo.witness_count ?? 0) > 0 && (
                                <div className="mt-2 text-[13px] font-mono text-cyan-200/75 leading-[1.7]">
                                  witness observations: {selectedContactInfo.witness_count}
                                  {selectedContactInfo.witness_checked_at
                                    ? `, last seen ${timeAgo(
                                        selectedContactInfo.witness_checked_at > 1_000_000_000_000
                                          ? selectedContactInfo.witness_checked_at
                                          : selectedContactInfo.witness_checked_at * 1000,
                                      )}`
                                    : ''}
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      )}
                      {selectedGate && gateResyncTarget === selectedGate && (
                        <div className="mt-2 border border-amber-500/30 bg-amber-950/15 px-2 py-2">
                          <div className="text-[12px] font-mono tracking-[0.18em] text-amber-300/90">
                            GATE STATE DRIFT
                          </div>
                          <div className="mt-1 text-[12px] font-mono text-amber-100/80 leading-[1.7]">
                            Native gate state changed on another path. Resync this gate locally before retrying decrypt or post actions.
                          </div>
                          <div className="mt-2 flex items-center gap-2">
                            <button
                              onClick={() => void handleResyncGateState(selectedGate)}
                              disabled={gateResyncBusy}
                              className="px-2 py-1 text-[12px] font-mono tracking-[0.2em] border border-amber-500/40 text-amber-200 hover:bg-amber-950/30 disabled:opacity-60 transition-colors"
                            >
                              {gateResyncBusy ? 'RESYNCING' : 'RESYNC GATE STATE'}
                            </button>
                            <span className="text-[12px] font-mono text-amber-300/60">
                              Required only when native desktop fails closed on gate-state drift.
                            </span>
                          </div>
                        </div>
                      )}
                      {selectedGate && gateError && !showCreateGate && !gateCompatConsentPrompt && (
                        <div className="mt-2 text-[12px] font-mono text-red-300/85 leading-[1.7]">
                          {gateError}
                        </div>
                      )}
                      {selectedGate && gateCompatConsentPrompt && !showCreateGate && (
                        <div className="mt-2 border border-amber-500/30 bg-amber-950/15 px-3 py-2">
                          <div className="text-[12px] font-mono tracking-[0.18em] text-amber-300/90">
                            COMPAT MODE
                          </div>
                          <div className="mt-1 text-[12px] font-mono text-amber-100/85 leading-[1.7]">
                            {describeGateCompatConsentPrompt(gateCompatConsentPrompt.action)}
                          </div>
                          <div className="mt-1 text-[12px] font-mono text-amber-300/60 leading-[1.7]">
                            {describeGateCompatReason(
                              gateCompatConsentPrompt.reason,
                              gateCompatConsentPrompt.gateId,
                            )}
                          </div>
                          <div className="mt-2 flex items-center gap-2">
                            <button
                              onClick={() => void handleApproveGateCompatFallback()}
                              className="px-2 py-1 text-[12px] font-mono tracking-[0.2em] border border-amber-500/40 text-amber-100 hover:bg-amber-950/30 transition-colors"
                            >
                              ENABLE FOR ROOM
                            </button>
                            <span className="text-[12px] font-mono text-amber-300/60">
                              Weaker privacy on this device.
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {selectedGateMeta && (
                    <div className="px-3 py-2 border-b border-cyan-900/20 bg-cyan-950/10 shrink-0">
                      <div className="flex items-center gap-2 text-[12px] font-mono tracking-[0.24em] text-cyan-300/90">
                        <span>{selectedGateMeta.fixed ? 'FIXED GATE' : 'PRIVATE GATE'}</span>
                        <span className="text-cyan-500/60">/</span>
                        <span>{selectedGateMeta.display_name || selectedGateMeta.gate_id}</span>
                        {selectedGateCompatActive ? (
                          <>
                            <span className="text-cyan-500/60">/</span>
                            <span className="border border-amber-500/40 bg-amber-950/20 px-1.5 py-0.5 text-[10px] tracking-[0.18em] text-amber-200">
                              COMPAT
                            </span>
                          </>
                        ) : null}
                      </div>
                      {selectedGateMeta.description && (
                        <div className="mt-1 text-sm font-mono text-cyan-100/80 leading-[1.65]">
                          {selectedGateMeta.description}
                        </div>
                      )}
                      <div className="mt-1 text-[12px] font-mono text-cyan-300/65">
                        {selectedGateMeta.rules?.min_overall_rep
                          ? `ENTRY FLOOR ${selectedGateMeta.rules.min_overall_rep} REP`
                          : 'ENTRY FLOOR OPEN'}
                        {' • '}
                        {selectedGateMeta.message_count} MSGS
                      </div>
                    </div>
                  )}

                  {/* Create gate form */}
                  <AnimatePresence>
                    {showCreateGate && (
                      <motion.div
                        initial={{ height: 0 }}
                        animate={{ height: 'auto' }}
                        exit={{ height: 0 }}
                        className="overflow-hidden border-b border-[var(--border-primary)]/30 shrink-0"
                      >
                        <div className="px-3 py-2 space-y-1.5">
                          <div className="text-[12px] font-mono text-[var(--text-muted)] leading-relaxed mb-1">
                            Gates are rep-gated communities. Only nodes meeting the minimum
                            reputation can post.
                          </div>
                          <input
                            value={newGateId}
                            onChange={(e) => {
                              setNewGateId(e.target.value);
                              setGateError('');
                            }}
                            placeholder="gate-id (alphanumeric + hyphens, max 32)"
                            className="w-full bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-sm font-mono text-cyan-300 px-2 py-1 outline-none placeholder:text-[var(--text-muted)]"
                          />
                          <input
                            value={newGateName}
                            onChange={(e) => setNewGateName(e.target.value)}
                            placeholder="Display Name (optional)"
                            className="w-full bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-sm font-mono text-cyan-300 px-2 py-1 outline-none placeholder:text-[var(--text-muted)]"
                          />
                          <div className="flex items-center gap-2">
                            <label
                              className="text-[13px] font-mono text-[var(--text-muted)]"
                              title="Minimum overall reputation score needed to post in this gate. 0 = open to all."
                            >
                              MIN REP:
                            </label>
                            <input
                              type="number"
                              min={0}
                              value={newGateMinRep}
                              onChange={(e) => setNewGateMinRep(parseInt(e.target.value) || 0)}
                              className="w-16 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-sm font-mono text-cyan-300 px-2 py-1 outline-none"
                            />
                            <span className="text-[12px] text-[var(--text-muted)] font-mono">
                              {newGateMinRep === 0 ? 'open' : 'gated'}
                            </span>
                            <button
                              onClick={handleCreateGate}
                              disabled={!newGateId.trim() || !hasId}
                              className="ml-auto text-[13px] font-mono px-2 py-1 bg-cyan-900/20 text-cyan-400 hover:bg-cyan-800/30 disabled:opacity-30 transition-colors"
                            >
                              CREATE
                            </button>
                          </div>
                          {gateError && (
                            <div className="text-[13px] font-mono text-red-400 mt-0.5">
                              {gateError}
                            </div>
                          )}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Messages — terminal log style */}
                  <div className="flex-1 overflow-y-auto styled-scrollbar px-3 py-1.5 border-l-2 border-cyan-800/25">
                    {filteredInfoMessages.length === 0 && (
                      <div className="py-4 space-y-3">
                        <div className="text-sm font-mono text-[var(--text-muted)] text-center leading-[1.65]">
                          {selectedGate ? 'No messages in this gate yet' : 'Select a gate or browse all'}
                        </div>
                        {selectedGateMeta && (
                          <div className="border border-cyan-900/30 bg-cyan-950/10 px-3 py-3 max-w-xl mx-auto">
                            <div className="text-[12px] font-mono tracking-[0.28em] text-cyan-300/85">
                              SYSTEM WELCOME
                            </div>
                            <div className="mt-2 text-sm font-mono text-cyan-100/80 leading-[1.7]">
                              {selectedGateMeta.welcome || selectedGateMeta.description || 'Private gate is live. Say something worth keeping.'}
                            </div>
                            <div className="mt-2 text-[13px] font-mono text-cyan-300/65 leading-[1.7]">
                              Start with a source, a thesis, a clean question, or a useful observation.
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                    {filteredInfoMessages.map((m, i) => (
                      m.system_seed ? (
                        <div key={m.event_id} className="border border-cyan-900/30 bg-cyan-950/10 px-3 py-3 max-w-xl">
                          <div className="text-[12px] font-mono tracking-[0.28em] text-cyan-300/85">
                            {m.fixed_gate ? 'FIXED GATE NOTICE' : 'GATE NOTICE'}
                          </div>
                          <div className="mt-2 text-sm font-mono text-cyan-100/80 leading-[1.7]">
                            {m.message}
                          </div>
                        </div>
                      ) : (
                      <div key={m.event_id} className="group py-0.5 leading-[1.65]">
                        <div className="flex gap-1.5 text-sm font-mono">
                          <RepBadge rep={m.node_id ? (reps[m.node_id] ?? 0) : 0} />
                          {m.node_id ? (
                            <button
                              onClick={(e) =>
                                handleSenderClick(String(m.node_id), e, 'infonet', {
                                  publicKey: String(m.public_key || ''),
                                  publicKeyAlgo: String(m.public_key_algo || ''),
                                })
                              }
                              className="text-green-400 shrink-0 hover:text-green-300 hover:underline cursor-pointer"
                              title={m.public_key ? `PUBLIC KEY: ${m.public_key}` : String(m.node_id)}
                            >
                              {m.node_id.slice(0, 12)}
                            </button>
                          ) : null}
                          {isEncryptedGateEnvelope(m) && (
                            <span
                              className={`text-[12px] font-mono px-1 border ${
                                gateEnvelopeState(m) === 'decrypted'
                                  ? 'text-cyan-300 border-cyan-700/60'
                                  : 'text-amber-300 border-amber-700/60'
                              }`}
                            >
                              {gateEnvelopeState(m) === 'decrypted' ? 'DECRYPTED' : 'KEY LOCKED'}
                            </span>
                          )}
                          {infoVerification[m.event_id] && (
                            <span
                              className={`text-[12px] font-mono px-1 border ${
                                infoVerification[m.event_id] === 'verified'
                                  ? 'text-green-400 border-green-700/60'
                                  : infoVerification[m.event_id] === 'failed'
                                    ? 'text-red-400 border-red-700/60'
                                    : 'text-yellow-400 border-yellow-700/60'
                              }`}
                            >
                              {infoVerification[m.event_id] === 'verified'
                                ? 'VERIFIED'
                                : infoVerification[m.event_id] === 'failed'
                                  ? 'FAILED'
                                  : 'UNSIGNED'}
                            </span>
                          )}
                          <span
                            className={`${MSG_COLORS[i % MSG_COLORS.length]} break-words whitespace-pre-wrap flex-1 ${
                              isEncryptedGateEnvelope(m) && !String(m.decrypted_message || '').trim()
                                ? 'italic opacity-80'
                                : ''
                            }`}
                          >
                            {gateEnvelopeDisplayText(m)}
                          </span>
                          <span className="text-[var(--text-muted)] shrink-0 text-[13px]">
                            {timeAgo(m.timestamp)}
                          </span>
                        </div>
                        {isEncryptedGateEnvelope(m) && (
                          <div className="ml-6 mt-0.5 text-[12px] font-mono text-cyan-500/60 tracking-[0.14em]">
                            EPOCH {m.epoch ?? 0}
                            {m.sender_ref ? ` / ${m.sender_ref}` : ''}
                          </div>
                        )}
                        {hasId && m.node_id && m.node_id !== identity!.nodeId && (
                          <div className="flex items-center gap-0.5 ml-6">
                            <button
                              onClick={() => handleReplyToGateMessage(m)}
                              className={`px-1.5 py-0.5 text-[12px] font-mono tracking-[0.14em] transition-colors ${
                                gateReplyContext?.eventId === m.event_id
                                  ? 'text-amber-200 border border-amber-500/30 bg-amber-500/12'
                                  : 'text-cyan-600/70 border border-cyan-700/20 hover:text-amber-200 hover:border-amber-500/30 hover:bg-amber-500/10'
                              }`}
                            >
                              REPLY
                            </button>
                            <button
                              onClick={() => handleVote(String(m.node_id), 1, String(m.gate || selectedGate || ''))}
                              className={`p-0.5 transition-colors ${
                                votedOn[voteScopeKey(String(m.node_id), String(m.gate || selectedGate || ''))] === 1
                                  ? 'text-cyan-400'
                                  : 'text-cyan-600/60 hover:text-cyan-400'
                              }`}
                            >
                              <ArrowUp size={9} />
                            </button>
                            <span
                              className={`text-[12px] font-mono min-w-[14px] text-center ${
                                (reps[m.node_id] ?? 0) > 0
                                  ? 'text-cyan-500'
                                  : (reps[m.node_id] ?? 0) < 0
                                    ? 'text-red-400'
                                    : 'text-cyan-600/60'
                              }`}
                            >
                              {reps[m.node_id] ?? 0}
                            </span>
                            <button
                              onClick={() => handleVote(String(m.node_id), -1, String(m.gate || selectedGate || ''))}
                              className={`p-0.5 transition-colors ${
                                votedOn[voteScopeKey(String(m.node_id), String(m.gate || selectedGate || ''))] === -1
                                  ? 'text-red-400'
                                  : 'text-cyan-600/60 hover:text-red-400'
                              }`}
                            >
                              <ArrowDown size={9} />
                            </button>
                          </div>
                        )}
                      </div>
                      )
                    ))}
                    <div ref={messagesEndRef} />
                  </div>
                    </>
                  )}
                </>
              )}

              {/* ─── Meshtastic Tab ─── */}
              {activeTab === 'meshtastic' && (
                <>
                  <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-[var(--border-primary)]/30 shrink-0">
                    <select
                      value={meshRegion}
                      onChange={(e) => setMeshRegion(e.target.value)}
                      title="Meshtastic MQTT root"
                      className="bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-[12px] font-mono text-cyan-300 px-2 py-1 outline-none focus:border-cyan-700/50"
                      style={{ width: '132px' }}
                    >
                      {meshRoots.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                    <select
                      value={meshChannel}
                      onChange={(e) => setMeshChannel(e.target.value)}
                      className="flex-1 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-[12px] font-mono text-green-400 px-2 py-1 outline-none focus:border-cyan-700/50"
                    >
                      {meshChannels.map((ch) => (
                        <option key={ch} value={ch}>
                          {activeChannels.has(ch) ? `* ${ch}` : `  ${ch}`}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center justify-between gap-2 px-3 py-1 border-b border-[var(--border-primary)]/20 shrink-0 bg-green-950/10">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => setMeshView('channel')}
                        className={`px-2 py-0.5 text-[11px] font-mono tracking-wider border transition-colors ${
                          meshView === 'channel'
                            ? 'border-green-500/40 text-green-300 bg-green-950/30'
                            : 'border-[var(--border-primary)]/40 text-[var(--text-muted)] hover:text-green-300'
                        }`}
                      >
                        CHANNEL
                      </button>
                      <button
                        onClick={() => setMeshView('inbox')}
                        className={`px-2 py-0.5 text-[11px] font-mono tracking-wider border transition-colors ${
                          meshView === 'inbox'
                            ? 'border-amber-500/40 text-amber-300 bg-amber-950/20'
                            : 'border-[var(--border-primary)]/40 text-[var(--text-muted)] hover:text-amber-300'
                        }`}
                      >
                        INBOX
                      </button>
                    </div>
                    <div className="text-[10px] font-mono text-[var(--text-muted)] truncate">
                      {publicMeshAddress ? `ADDR ${publicMeshAddress.toUpperCase()}` : 'NO PUBLIC MESH ADDRESS'}
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto styled-scrollbar px-3 py-1.5 border-l-2 border-cyan-800/25">
                    {meshView === 'channel' && filteredMeshMessages.length === 0 && (
                      <div className="text-[12px] font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                        No messages from {meshRegion} / {meshChannel}
                      </div>
                    )}
                    {meshView === 'inbox' && (
                      <>
                        {!publicMeshAddress && (
                          <div className="text-[12px] font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            Create or load a public mesh identity to see direct Meshtastic traffic.
                          </div>
                        )}
                        {publicMeshAddress && meshInboxMessages.length === 0 && (
                          <div className="text-[12px] font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            No public direct messages addressed to {publicMeshAddress.toUpperCase()} yet.
                          </div>
                        )}
                        {meshInboxMessages.map((m, i) => (
                          <div key={`${m.timestamp}-${i}`} className="py-0.5 leading-[1.65]">
                            <div className="flex items-start gap-1.5 text-[12px] font-mono">
                              <button
                                onClick={(e) => handleSenderClick(m.from, e, 'meshtastic')}
                                className="text-amber-300 shrink-0 hover:text-amber-200 hover:underline cursor-pointer"
                              >
                                {displayPublicMeshSender(m.from)}
                              </button>
                              <div className="flex-1 min-w-0">
                                <div className="text-[10px] text-amber-200/70 mb-0.5">
                                  TO {publicMeshAddress.toUpperCase()}
                                </div>
                                <div className="break-words whitespace-pre-wrap text-amber-100/90">
                                  {m.text}
                                </div>
                              </div>
                              <span className="text-[var(--text-muted)] shrink-0 text-[11px]">
                                {timeAgo(
                                  typeof m.timestamp === 'number'
                                    ? m.timestamp
                                    : Date.parse(m.timestamp || ''),
                                )}
                              </span>
                            </div>
                          </div>
                        ))}
                      </>
                    )}
                    {meshView === 'channel' &&
                      filteredMeshMessages.map((m, i) => (
                        <div key={`${m.timestamp}-${i}`} className="py-0.5 leading-[1.65]">
                          <div className="flex gap-1.5 text-[12px] font-mono">
                            <button
                              onClick={(e) => handleSenderClick(m.from, e, 'meshtastic')}
                              className="text-green-400 shrink-0 hover:text-green-300 hover:underline cursor-pointer"
                            >
                              {displayPublicMeshSender(m.from)}
                            </button>
                            <span
                              className={`${MSG_COLORS[i % MSG_COLORS.length]} break-words whitespace-pre-wrap flex-1`}
                            >
                              {m.text}
                            </span>
                            <span className="text-[var(--text-muted)] shrink-0 text-[11px]">
                              {timeAgo(
                                typeof m.timestamp === 'number'
                                  ? m.timestamp
                                  : Date.parse(m.timestamp || ''),
                              )}
                            </span>
                          </div>
                        </div>
                      ))}
                    <div ref={messagesEndRef} />
                  </div>
                </>
              )}

              {/* ─── Dead Drop Tab ─── */}
              {!dashboardRestrictedTab && activeTab === 'dms' && (
                <>
                  {/* Sub-nav: Contacts | Inbox | Muted | (back to contacts from chat) */}
                  <div className="flex items-center gap-1 px-3 py-1.5 border-b border-[var(--border-primary)]/30 shrink-0">
                    {dmView === 'chat' ? (
                      <>
                        <button
                          onClick={() => {
                            setDmView('contacts');
                            setSelectedContact('');
                            setDmMessages([]);
                          }}
                          className="text-[13px] font-mono text-[var(--text-muted)] hover:text-cyan-400 transition-colors"
                        >
                          &lt; BACK
                        </button>
                        <span className="text-sm font-mono text-cyan-400 ml-2 truncate">
                          {selectedContact.slice(0, 16)}
                        </span>
                        {(() => {
                          const c = contacts[selectedContact];
                          if (!c) return null;
                          const trust = getContactTrustSummary(c);
                          if (trust?.transparencyConflict) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-red-500/40 text-red-300 bg-red-950/20">
                                HISTORY CONFLICT
                              </span>
                            );
                          }
                          if (trust?.state === 'continuity_broken') {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-red-500/40 text-red-300 bg-red-950/20">
                                CONTINUITY BROKEN
                              </span>
                            );
                          }
                          if (trust?.state === 'mismatch') {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-orange-500/40 text-orange-300 bg-orange-950/20">
                                PREKEY CHANGED
                              </span>
                            );
                          }
                          if (trust?.registryMismatch) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-red-500/40 text-red-400 bg-red-950/20">
                                KEY MISMATCH
                              </span>
                            );
                          }
                          if (trust?.state === 'sas_verified') {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-green-500/40 text-green-400 bg-green-950/20">
                                SAS VERIFIED
                              </span>
                            );
                          }
                          if (trust?.state === 'invite_pinned') {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-emerald-500/40 text-emerald-300 bg-emerald-950/20">
                                INVITE PINNED
                              </span>
                            );
                          }
                          if (trust?.state === 'tofu_pinned') {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-amber-500/30 text-amber-300 bg-amber-950/10">
                                TOFU ONLY
                              </span>
                            );
                          }
                          return null;
                        })()}
                        {(() => {
                          const c = contacts[selectedContact];
                          if (!c) return null;
                          if (c.witness_count && c.witness_count > 0) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-cyan-500/30 text-cyan-300 bg-cyan-950/10">
                                WITNESSED {c.witness_count}
                              </span>
                            );
                          }
                          return null;
                        })()}
                        {(() => {
                          const c = contacts[selectedContact];
                          if (!c) return null;
                          if (c.vouch_count && c.vouch_count > 0) {
                            return (
                              <span className="ml-2 text-[12px] font-mono px-1.5 py-0.5 border border-purple-500/30 text-purple-300 bg-purple-950/10">
                                VOUCHES {c.vouch_count}
                              </span>
                            );
                          }
                          return null;
                        })()}
                        <button
                          onClick={handleDmTrustPrimaryAction}
                          className="ml-auto text-[12px] font-mono px-2 py-0.5 border border-cyan-800/40 text-cyan-400/90 hover:text-cyan-300 hover:border-cyan-600/60 transition-colors"
                        >
                          {dmTrustPrimaryButtonLabel}
                        </button>
                        <button
                          onClick={() => handleVouch(selectedContact)}
                          className="ml-2 text-[12px] font-mono px-2 py-0.5 border border-purple-800/40 text-purple-400/90 hover:text-purple-300 hover:border-purple-600/60 transition-colors"
                        >
                          VOUCH
                        </button>
                        <button
                          onClick={() => void handleRefreshSelectedContact()}
                          disabled={dmMaintenanceBusy}
                          className="ml-2 text-[12px] font-mono px-2 py-0.5 border border-amber-800/40 text-amber-300/90 hover:text-amber-200 hover:border-amber-600/60 transition-colors disabled:opacity-40"
                        >
                          REFRESH
                        </button>
                        <button
                          onClick={() => void handleResetSelectedContact()}
                          disabled={dmMaintenanceBusy}
                          className="ml-2 text-[12px] font-mono px-2 py-0.5 border border-red-800/40 text-red-300/90 hover:text-red-200 hover:border-red-600/60 transition-colors disabled:opacity-40"
                        >
                          RESET
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => setDmView('contacts')}
                          className={`text-[13px] font-mono px-2 py-0.5 transition-colors ${
                            dmView === 'contacts'
                              ? 'text-cyan-400 bg-cyan-950/30'
                              : 'text-[var(--text-muted)] hover:text-gray-400'
                          }`}
                        >
                          CONTACTS
                        </button>
                        <button
                          onClick={() => setDmView('inbox')}
                          className={`text-[13px] font-mono px-2 py-0.5 transition-colors flex items-center gap-1 ${
                            dmView === 'inbox'
                              ? 'text-cyan-400 bg-cyan-950/30'
                              : 'text-[var(--text-muted)] hover:text-gray-400'
                          }`}
                        >
                          INBOX
                          {accessRequests.length > 0 && (
                            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-[blink_1s_step-end_infinite]" />
                          )}
                        </button>
                        <button
                          onClick={() => setDmView('muted')}
                          className={`text-[13px] font-mono px-2 py-0.5 transition-colors flex items-center gap-1 ${
                            dmView === 'muted'
                              ? 'text-cyan-400 bg-cyan-950/30'
                              : 'text-[var(--text-muted)] hover:text-gray-400'
                          }`}
                        >
                          <EyeOff size={8} />
                          MUTED
                          {mutedArray.length > 0 && (
                            <span className="text-[11px] text-[var(--text-muted)]">
                              ({mutedArray.length})
                            </span>
                          )}
                        </button>
                        <button
                          onClick={() => setShowAddContact(!showAddContact)}
                          disabled={secureDmBlocked}
                          className="ml-auto p-1 hover:bg-[var(--hover-accent)] text-[var(--text-muted)] hover:text-cyan-400 transition-colors"
                          title="Request access"
                        >
                          <UserPlus size={11} />
                        </button>
                      </>
                    )}
                  </div>
                  {dmView === 'chat' && showSas && sasPhrase && (
                    <div className="px-3 pb-1 text-[13px] font-mono text-cyan-400/80 border-b border-[var(--border-primary)]/20">
                      SAS: <span className="text-cyan-300">{sasPhrase}</span>
                      {selectedContactInfo &&
                        selectedContactTrustSummary?.state === 'invite_pinned' && (
                        <div className="mt-1 text-[12px] font-mono text-emerald-300/90 leading-[1.65]">
                          This contact was anchored by an imported signed invite. SAS is still useful
                          as an extra continuity check.
                        </div>
                      )}
                      {selectedContactInfo &&
                        selectedContactTrustSummary?.state === 'tofu_pinned' && (
                        <div className="mt-1 text-[12px] font-mono text-amber-300/90 leading-[1.65]">
                          First contact is still TOFU-only. Compare this phrase out of band before
                          treating the sender as verified.
                        </div>
                      )}
                      {selectedContactInfo &&
                        selectedContactTrustSummary?.state !== 'sas_verified' &&
                        selectedContactTrustSummary?.state !== 'mismatch' &&
                        selectedContactTrustSummary?.state !== 'continuity_broken' &&
                        !selectedContactTrustSummary?.transparencyConflict && (
                        <div className="mt-2 flex items-center gap-1.5">
                          <input
                            value={sasConfirmInput}
                            onChange={(e) => setSasConfirmInput(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                void handleConfirmSelectedContactSas();
                              }
                            }}
                            placeholder="Type the phrase you both confirmed"
                            className="flex-1 min-w-0 bg-black/30 border border-cyan-900/30 px-2 py-1 text-[12px] font-mono text-cyan-100 placeholder:text-cyan-700/70 focus:outline-none focus:border-cyan-600/60"
                          />
                          <button
                            onClick={() => void handleConfirmSelectedContactSas()}
                            disabled={dmMaintenanceBusy}
                            className="text-[12px] font-mono px-2 py-1 border border-emerald-800/40 text-emerald-300 hover:text-emerald-200 hover:border-emerald-600/60 transition-colors disabled:opacity-40"
                          >
                            CONFIRM SAS
                          </button>
                        </div>
                      )}
                      {selectedContactInfo &&
                        selectedContactTrustSummary?.state === 'continuity_broken' &&
                        selectedContactTrustSummary?.rootMismatch && (
                        <>
                          <div className="mt-1 text-[12px] font-mono text-red-300/90 leading-[1.65]">
                            {`${rootWitnessContinuityLabel(selectedContactTrustSummary)} changed for this contact.`}{' '}
                            Compare the SAS phrase for the newly observed root, then recover only if
                            the ceremony checks out.
                          </div>
                          <div className="mt-2 flex items-center gap-1.5">
                            <input
                              value={sasConfirmInput}
                              onChange={(e) => setSasConfirmInput(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  void handleRecoverSelectedContactRootContinuity();
                                }
                              }}
                              placeholder="Type the phrase you both confirmed for the new root"
                              className="flex-1 min-w-0 bg-black/30 border border-red-900/30 px-2 py-1 text-[12px] font-mono text-cyan-100 placeholder:text-red-700/70 focus:outline-none focus:border-red-600/60"
                            />
                            <button
                              onClick={() => void handleRecoverSelectedContactRootContinuity()}
                              disabled={dmMaintenanceBusy}
                              className="text-[12px] font-mono px-2 py-1 border border-red-800/40 text-red-300 hover:text-red-200 hover:border-red-600/60 transition-colors disabled:opacity-40"
                            >
                              RECOVER ROOT
                            </button>
                          </div>
                        </>
                      )}
                      {selectedContactInfo?.remotePrekeyMismatch && (
                        <div className="mt-2 text-[12px] font-mono text-red-300/85 leading-[1.65]">
                          {selectedContactTrustSummary?.rootMismatch
                            ? `${rootWitnessContinuityLabel(selectedContactTrustSummary)} changed. Recover only after you compare the new SAS phrase out of band.`
                            : 'Acknowledge the changed fingerprint first, then compare and confirm SAS again.'}
                        </div>
                      )}
                    </div>
                  )}

                  {activeTab === 'dms' && !secureDmBlocked && (
                    <div className="px-3 py-1.5 border-b border-[var(--border-primary)]/20 shrink-0 flex items-center gap-2">
                      <span
                        className={`text-[12px] font-mono px-1.5 py-0.5 border ${dmTransportStatus.className}`}
                      >
                        {dmTransportStatus.label}
                      </span>
                      <span className="text-[12px] font-mono text-[var(--text-muted)]">
                        {dmTransportMode === 'reticulum'
                          ? 'Direct private delivery active.'
                          : dmTransportMode === 'hidden'
                            ? 'Hidden transport active.'
                            : dmTransportMode === 'relay'
                              ? 'Relay fallback active.'
                              : dmTransportMode === 'ready'
                                ? 'Private lane ready.'
                        : 'Lower-trust mode.'}
                      </span>
                    </div>
                  )}

                  {activeTab === 'dms' && unresolvedSenderSealCount > 0 && (
                    <div className="px-3 py-2 border-b border-red-900/30 bg-red-950/18 text-red-300 leading-[1.65] shrink-0">
                      <div className="text-[13px] font-mono tracking-[0.18em] mb-1">
                        UNRESOLVED SEALED SENDERS
                      </div>
                      <div className="text-sm font-mono">
                        {unresolvedSenderSealCount} sealed-sender message
                        {unresolvedSenderSealCount === 1 ? '' : 's'} could not be mapped to a
                        trusted contact or verified sender key. Keep Wormhole reachable and refresh
                        contact trust before relying on them.
                      </div>
                    </div>
                  )}

                  {activeTab === 'dms' && dmView === 'chat' && dmTrustHint && selectedContactInfo && (
                    <div
                      className={`px-3 py-2 border-b leading-[1.65] shrink-0 ${
                        dmTrustHint.severity === 'danger'
                          ? 'border-red-900/30 bg-red-950/20 text-red-300'
                          : 'border-amber-900/30 bg-amber-950/10 text-amber-200'
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="text-[13px] font-mono tracking-[0.18em] mb-1">
                            {dmTrustHint.title}
                          </div>
                          <div className="text-sm font-mono">{dmTrustHint.detail}</div>
                          {selectedContactInfo.remotePrekeyMismatch && (
                            <div className="mt-2 text-[13px] font-mono text-red-200/85">
                              pinned {shortTrustFingerprint(selectedContactInfo.remotePrekeyFingerprint)} • observed{' '}
                              {shortTrustFingerprint(selectedContactInfo.remotePrekeyObservedFingerprint)}
                            </div>
                          )}
                          {!selectedContactInfo.remotePrekeyMismatch &&
                            selectedContactInfo.remotePrekeyRootMismatch && (
                            <div className="mt-2 text-[13px] font-mono text-red-200/85">
                              pinned root {shortTrustFingerprint(selectedContactInfo.remotePrekeyRootFingerprint)} •
                              observed root{' '}
                              {shortTrustFingerprint(selectedContactInfo.remotePrekeyObservedRootFingerprint)}
                            </div>
                          )}
                          {!selectedContactInfo.remotePrekeyMismatch &&
                            selectedContactTrustSummary?.state === 'tofu_pinned' &&
                            selectedContactInfo.remotePrekeyFingerprint && (
                            <div className="mt-2 text-[13px] font-mono text-amber-200/85">
                              first-sight pin {shortTrustFingerprint(selectedContactInfo.remotePrekeyFingerprint)} •
                              verify before sensitive use
                            </div>
                          )}
                          {!selectedContactInfo.remotePrekeyMismatch &&
                            selectedContactTrustSummary?.state === 'invite_pinned' &&
                            (selectedContactInfo.invitePinnedTrustFingerprint ||
                              selectedContactInfo.remotePrekeyFingerprint) && (
                            <div className="mt-2 text-[13px] font-mono text-emerald-200/85">
                              invite pin{' '}
                              {shortTrustFingerprint(
                                selectedContactInfo.invitePinnedTrustFingerprint ||
                                  selectedContactInfo.remotePrekeyFingerprint,
                              )}{' '}
                              •
                              {selectedContactTrustSummary?.rootAttested &&
                              (selectedContactInfo.invitePinnedRootFingerprint ||
                                selectedContactInfo.remotePrekeyRootFingerprint)
                                ? ` ${rootWitnessBadgeLabel(selectedContactTrustSummary).toLowerCase()} ${shortTrustFingerprint(
                                    selectedContactInfo.invitePinnedRootFingerprint ||
                                      selectedContactInfo.remotePrekeyRootFingerprint,
                                  )} •`
                                : ''}{' '}
                              imported out of band before first contact
                            </div>
                          )}
                          {selectedContactTrustSummary?.state === 'continuity_broken' &&
                            selectedContactTrustSummary?.rootMismatch && (
                            <div className="mt-2 text-[13px] font-mono text-red-200/85 leading-[1.7]">
                              {`${rootWitnessContinuityLabel(selectedContactTrustSummary).toLowerCase()} broke for this contact.`}{' '}
                              Re-verify SAS or replace the signed invite before trusting the new
                              root.
                            </div>
                          )}
                          {selectedContactInfo.remotePrekeyTransparencyConflict && (
                            <div className="mt-2 text-[13px] font-mono text-red-200/85 leading-[1.7]">
                              prekey history conflict observed and trust stays degraded until you
                              explicitly acknowledge the changed fingerprint.
                            </div>
                          )}
                          {selectedContactInfo.remotePrekeyLookupMode === 'legacy_agent_id' && (
                            <div className="mt-2 text-[13px] font-mono text-yellow-200/85 leading-[1.7]">
                              bootstrap path: legacy direct agent ID lookup.
                              {selectedContactInfo.invitePinnedPrekeyLookupHandle
                                ? ' Refresh from the signed invite to tighten lookup privacy.'
                                : ' Import or re-import a signed invite to avoid stable-ID lookup.'}
                            </div>
                          )}
                          {selectedContactInfo.remotePrekeyLookupMode === 'invite_lookup_handle' && (
                            <div className="mt-2 text-[13px] font-mono text-cyan-200/85 leading-[1.7]">
                              bootstrap path: invite-scoped lookup handle. Stable agent ID was not
                              required on the lookup path.
                            </div>
                          )}
                          {(selectedContactInfo.witness_count ?? 0) > 0 && (
                            <div className="mt-2 text-[13px] font-mono text-cyan-200/75 leading-[1.7]">
                              witness observations: {selectedContactInfo.witness_count}
                              {selectedContactInfo.witness_checked_at
                                ? `, last seen ${timeAgo(
                                    selectedContactInfo.witness_checked_at > 1_000_000_000_000
                                      ? selectedContactInfo.witness_checked_at
                                      : selectedContactInfo.witness_checked_at * 1000,
                                  )}`
                                : ''}
                            </div>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <button
                            onClick={handleDmTrustPrimaryAction}
                            className="text-[12px] font-mono px-2 py-0.5 border border-cyan-800/40 text-cyan-300 hover:text-cyan-200 hover:border-cyan-600/60 transition-colors"
                          >
                            {dmTrustPrimaryButtonLabel}
                          </button>
                          {selectedContactInfo.remotePrekeyMismatch &&
                            !selectedContactTrustSummary?.rootMismatch && (
                            <button
                              onClick={() => void handleTrustSelectedRemotePrekey()}
                              disabled={dmMaintenanceBusy}
                              className="text-[12px] font-mono px-2 py-0.5 border border-orange-700/40 text-orange-300 hover:text-orange-200 hover:border-orange-500/60 transition-colors disabled:opacity-40"
                            >
                              TRUST NEW KEY
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Add contact / request access form */}
                  <AnimatePresence>
                    {showAddContact && dmView !== 'chat' && !secureDmBlocked && (
                      <motion.div
                        initial={{ height: 0 }}
                        animate={{ height: 'auto' }}
                        exit={{ height: 0 }}
                        className="overflow-hidden border-b border-[var(--border-primary)]/30 shrink-0"
                      >
                        <div className="px-3 py-2 space-y-1.5">
                          <div className="text-[13px] font-mono text-[var(--text-muted)] leading-[1.65]">
                            Enter an Agent ID for a contact you already pinned with a signed invite
                            to request Dead Drop access. If you only have older local state, use
                            terminal <span className="text-yellow-400">dm add</span> only for
                            legacy migration.
                          </div>
                          <div className="flex items-center gap-1.5">
                            <input
                              value={addContactId}
                              onChange={(e) => setAddContactId(e.target.value)}
                              placeholder="!sb_a3f2c891..."
                              className="flex-1 bg-[var(--bg-secondary)]/50 border border-[var(--border-primary)] text-sm font-mono text-cyan-300 px-2 py-1 outline-none placeholder:text-[var(--text-muted)]"
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  handleRequestComposerAction();
                                }
                              }}
                            />
                            <button
                              onClick={handleRequestComposerAction}
                              disabled={!addContactId.trim() || !hasId}
                              className="text-[13px] font-mono px-2 py-1 bg-cyan-900/20 text-cyan-400 hover:bg-cyan-800/30 disabled:opacity-30 transition-colors"
                            >
                              REQUEST
                            </button>
                          </div>
                          {pendingSent.includes(addContactId.trim()) && (
                            <div className="text-[13px] font-mono text-yellow-500/70">
                              Request already sent
                            </div>
                          )}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Content area */}
                  <div className="flex-1 overflow-y-auto styled-scrollbar px-3 py-1.5 space-y-0.5 border-l-2 border-cyan-800/25">
                    {secureDmBlocked && (
                      <div className="flex h-full min-h-[220px] items-center justify-center py-6">
                        <div className="max-w-sm w-full border border-cyan-900/30 bg-cyan-950/10 px-4 py-5 text-center">
                          <div className="inline-flex items-center justify-center w-10 h-10 border border-cyan-700/40 bg-black/30 text-cyan-300 mb-3">
                            <Lock size={16} />
                          </div>
                          <div className="text-sm font-mono tracking-[0.24em] text-cyan-300 mb-2">
                            DEAD DROP LOCKED
                          </div>
                          <div className="text-sm font-mono text-[var(--text-secondary)] leading-[1.7]">
                            Need Wormhole activated.
                          </div>
                          <div className="mt-2 text-[13px] font-mono text-cyan-300/70">
                            Contacts, inbox, and private messages unlock once the private lane is up.
                          </div>
                        </div>
                      </div>
                    )}

                    {/* CONTACTS VIEW */}
                    {!secureDmBlocked && dmView === 'contacts' && (
                      <>
                        {contactList.length === 0 && (
                          <div className="text-sm font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            No contacts yet. Use <span className="text-cyan-500/70">+</span> to
                            request access.
                          </div>
                        )}
                        {contactList.map(([id, c]) => {
                          const trust = getContactTrustSummary(c);
                          return (
                          <div
                            key={id}
                            className="flex items-center gap-2 py-1.5 border-b border-[var(--border-primary)]/30 last:border-0 cursor-pointer hover:bg-[var(--bg-secondary)]/50 px-1 -mx-1 transition-colors"
                            onClick={() => openChat(id)}
                          >
                            <Lock size={10} className="text-[var(--text-muted)] shrink-0" />
                            <span className="text-sm font-mono text-cyan-300 truncate">
                              {c.alias || id.slice(0, 16)}
                            </span>
                            {c.remotePrekeyMismatch && (
                              <span className="text-[11px] font-mono px-1.5 py-0.5 border border-orange-500/40 text-orange-300 bg-orange-950/20">
                                REVERIFY
                              </span>
                            )}
                            {!c.remotePrekeyMismatch && c.verify_mismatch && (
                              <span className="text-[11px] font-mono px-1.5 py-0.5 border border-red-500/40 text-red-300 bg-red-950/20">
                                MISMATCH
                              </span>
                            )}
                            {!c.remotePrekeyMismatch && !c.verify_mismatch && trust?.state === 'invite_pinned' && (
                              <span className="text-[11px] font-mono px-1.5 py-0.5 border border-emerald-500/40 text-emerald-300 bg-emerald-950/20">
                                INVITE PINNED
                              </span>
                            )}
                            {!c.remotePrekeyMismatch && !c.verify_mismatch && trust?.state === 'sas_verified' && (
                              <span className="text-[11px] font-mono px-1.5 py-0.5 border border-green-500/40 text-green-400 bg-green-950/20">
                                SAS VERIFIED
                              </span>
                            )}
                            {!c.remotePrekeyMismatch &&
                              !c.verify_mismatch &&
                              !c.remotePrekeyTransparencyConflict &&
                              c.remotePrekeyLookupMode === 'legacy_agent_id' && (
                              <span className="text-[11px] font-mono px-1.5 py-0.5 border border-yellow-500/30 text-yellow-300 bg-yellow-950/10">
                                LEGACY LOOKUP
                              </span>
                            )}
                            {!c.remotePrekeyMismatch && !c.verify_mismatch && c.remotePrekeyTransparencyConflict && (
                              <span className="text-[11px] font-mono px-1.5 py-0.5 border border-red-500/40 text-red-300 bg-red-950/20">
                                HISTORY CONFLICT
                              </span>
                            )}
                            {!c.remotePrekeyMismatch &&
                              !c.verify_mismatch &&
                              trust?.state === 'tofu_pinned' && (
                              <span className="text-[11px] font-mono px-1.5 py-0.5 border border-amber-500/30 text-amber-300 bg-amber-950/10">
                                TOFU ONLY
                              </span>
                            )}
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleBlockDM(id);
                              }}
                              className="ml-auto p-0.5 text-[var(--text-muted)] hover:text-red-400 hover:bg-red-900/20 transition-colors"
                              title="Block"
                            >
                              <Ban size={10} />
                            </button>
                          </div>
                          );
                        })}
                        {pendingSent.length > 0 && (
                          <>
                            <div className="text-[13px] font-mono text-[var(--text-muted)] mt-2 mb-1">
                              PENDING SENT
                            </div>
                            {pendingSent.map((id) => (
                              <div
                                key={id}
                                className="flex items-center gap-2 py-1 text-sm font-mono text-[var(--text-muted)]"
                              >
                                <span className="w-1.5 h-1.5 rounded-full bg-yellow-600/50" />
                                <span className="truncate">{id.slice(0, 16)}</span>
                                <span className="ml-auto text-[12px] text-[var(--text-muted)]">
                                  awaiting
                                </span>
                              </div>
                            ))}
                          </>
                        )}
                      </>
                    )}

                    {/* INBOX VIEW — access requests */}
                    {!secureDmBlocked && dmView === 'inbox' && (
                      <>
                        {accessRequests.length === 0 && (
                          <div className="text-sm font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            No incoming requests
                          </div>
                        )}
                        {accessRequests.map((req) => {
                          const requestActionsAllowed = shouldAllowRequestActions(req);
                          const recoveryState = req.sender_recovery_state;
                          return (
                            <div
                              key={req.sender_id}
                              className="py-2 border-b border-[var(--border-primary)]/30 last:border-0"
                            >
                              <div className="flex items-center gap-1.5">
                                <UserPlus size={10} className="text-cyan-500 shrink-0" />
                                <span className="text-sm font-mono text-cyan-300 truncate">
                                  {req.sender_id.slice(0, 16)}
                                </span>
                                {recoveryState === 'verified' && (
                                  <span className="text-[12px] font-mono px-1.5 py-0.5 border border-green-500/30 text-green-400 bg-green-950/20">
                                    VERIFIED
                                  </span>
                                )}
                                {recoveryState === 'pending' && (
                                  <span className="text-[12px] font-mono px-1.5 py-0.5 border border-yellow-500/30 text-yellow-300 bg-yellow-950/20">
                                    RECOVERY PENDING
                                  </span>
                                )}
                                {recoveryState === 'failed' && (
                                  <span className="text-[12px] font-mono px-1.5 py-0.5 border border-red-500/30 text-red-300 bg-red-950/20">
                                    RECOVERY FAILED
                                  </span>
                                )}
                                <span className="text-[12px] font-mono text-[var(--text-muted)] ml-auto shrink-0">
                                  {timeAgo(req.timestamp)}
                                </span>
                              </div>
                              <div className="text-[13px] font-mono text-[var(--text-muted)] mt-0.5 leading-[1.65]">
                                Requesting Dead Drop access
                              </div>
                              {req.geo_hint && (
                                <div className="text-[12px] font-mono text-[var(--text-muted)] mt-0.5">
                                  Geo hint (not proof): {req.geo_hint}
                                </div>
                              )}
                              {!requestActionsAllowed && (
                                <div className="text-[12px] font-mono text-yellow-300 mt-0.5 leading-[1.65]">
                                  Sender authority is not verified yet. Actions stay disabled until
                                  local recovery succeeds.
                                </div>
                              )}
                              <div className="flex items-center gap-1.5 mt-1.5">
                                <button
                                  onClick={() => handleAcceptRequest(req.sender_id)}
                                  disabled={!requestActionsAllowed}
                                  className={`flex items-center gap-1 text-[13px] font-mono px-2 py-0.5 transition-colors ${
                                    requestActionsAllowed
                                      ? 'bg-cyan-900/20 text-cyan-400 hover:bg-cyan-800/30'
                                      : 'bg-cyan-950/10 text-cyan-700 cursor-not-allowed opacity-50'
                                  }`}
                                >
                                  <Check size={9} /> ACCEPT
                                </button>
                                <button
                                  onClick={() => handleDenyRequest(req.sender_id)}
                                  disabled={!requestActionsAllowed}
                                  className={`flex items-center gap-1 text-[13px] font-mono px-2 py-0.5 transition-colors ${
                                    requestActionsAllowed
                                      ? 'bg-gray-900/30 text-gray-400 hover:bg-gray-800/40'
                                      : 'bg-gray-950/20 text-gray-600 cursor-not-allowed opacity-50'
                                  }`}
                                >
                                  <X size={9} /> DENY
                                </button>
                                <button
                                  onClick={() => handleBlockDM(req.sender_id)}
                                  disabled={!requestActionsAllowed}
                                  className={`flex items-center gap-1 text-[13px] font-mono px-2 py-0.5 ml-auto transition-colors ${
                                    requestActionsAllowed
                                      ? 'text-[var(--text-muted)] hover:text-red-400 hover:bg-red-900/20'
                                      : 'text-[var(--text-muted)] opacity-50 cursor-not-allowed'
                                  }`}
                                >
                                  <Ban size={9} /> BLOCK
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </>
                    )}

                    {/* MUTED LIST VIEW */}
                    {!secureDmBlocked && dmView === 'muted' && (
                      <>
                        {mutedArray.length === 0 && (
                          <div className="text-sm font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            No muted users
                          </div>
                        )}
                        {mutedArray.map((uid) => (
                          <div
                            key={uid}
                            className="flex items-center gap-2 py-1.5 border-b border-[var(--border-primary)]/30 last:border-0 px-1 -mx-1"
                          >
                            <EyeOff size={10} className="text-[var(--text-muted)] shrink-0" />
                            <span className="text-sm font-mono text-[var(--text-secondary)] truncate flex-1">
                              {uid.slice(0, 20)}
                            </span>
                            <button
                              onClick={() => handleUnmute(uid)}
                              className="flex items-center gap-1 text-[12px] font-mono px-2 py-0.5 bg-cyan-900/20 text-cyan-500 hover:bg-cyan-800/30 transition-colors"
                            >
                              <Eye size={8} /> UNMUTE
                            </button>
                          </div>
                        ))}
                      </>
                    )}

                    {/* CHAT VIEW */}
                    {!secureDmBlocked && dmView === 'chat' && (
                      <>
                        {dmMessages.length === 0 && (
                          <div className="text-sm font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            <Lock size={11} className="inline mr-1 mb-0.5" />
                            E2E encrypted dead drop — no messages yet
                          </div>
                        )}
                        {dmMessages.map((m) => (
                          <div key={m.msg_id} className="py-0.5 leading-[1.65]">
                            <div className="flex gap-1.5 text-sm font-mono">
                              <span
                                className={`shrink-0 ${
                                  m.sender_id === identity?.nodeId
                                    ? 'text-cyan-500'
                                    : 'text-cyan-400'
                                }`}
                              >
                                {m.sender_id === identity?.nodeId
                                  ? 'you'
                                  : m.sender_id.slice(0, 12)}
                              </span>
                              {m.sender_id !== identity?.nodeId && m.seal_verified === true && (
                                <span className="text-[12px] font-mono px-1.5 py-0.5 border border-green-500/30 text-green-400 bg-green-950/20">
                                  VERIFIED
                                </span>
                              )}
                              {m.sender_id !== identity?.nodeId && m.seal_resolution_failed && (
                                <span className="text-[12px] font-mono px-1.5 py-0.5 border border-red-500/30 text-red-300 bg-red-950/20">
                                  SEAL UNRESOLVED
                                </span>
                              )}
                              {m.sender_id !== identity?.nodeId &&
                                !m.seal_resolution_failed &&
                                m.seal_verified === false && (
                                <span className="text-[12px] font-mono px-1.5 py-0.5 border border-red-500/30 text-red-400 bg-red-950/20">
                                  UNVERIFIED
                                </span>
                              )}
                              {m.transport && (
                                <span
                                  className={`text-[12px] font-mono px-1.5 py-0.5 border ${
                                    m.transport === 'reticulum'
                                      ? 'border-green-500/30 text-green-400 bg-green-950/20'
                                      : 'border-yellow-500/30 text-yellow-400 bg-yellow-950/20'
                                  }`}
                                >
                                  {m.transport === 'reticulum' ? 'DIRECT' : 'RELAY'}
                                </span>
                              )}
                              <span className="text-[var(--text-secondary)] break-words whitespace-pre-wrap flex-1">
                                {m.plaintext || '[encrypted]'}
                              </span>
                              <span className="text-[var(--text-muted)] shrink-0 text-[13px]">
                                {timeAgo(m.timestamp)}
                              </span>
                            </div>
                          </div>
                        ))}
                      </>
                    )}
                    <div ref={messagesEndRef} />
                  </div>
                </>
              )}
            </div>

            {/* INPUT BAR */}
            {dashboardRestrictedTab ? (
              <div className="mx-2 mb-2 mt-1 border border-cyan-800/40 bg-black/30 shrink-0 relative">
                <span className="absolute -top-[7px] left-3 bg-[var(--bg-primary)] px-1 text-[11px] font-mono text-cyan-700/60 tracking-[0.15em] select-none">
                  ACCESS
                </span>
                <div className="px-3 py-3 flex flex-col gap-2">
                  <div className="text-[12px] font-mono tracking-widest text-[var(--text-muted)] uppercase">
                    {activeTab === 'infonet'
                      ? '→ PRIVATE INFONET / TERMINAL ONLY'
                      : '→ DEAD DROP / TERMINAL ONLY'}
                  </div>
                  <div className="text-[13px] font-mono text-[var(--text-secondary)] leading-[1.65]">
                    {activeTab === 'infonet'
                      ? 'Private gate posting and reading are restricted to the terminal for now. Dashboard support is coming soon.'
                      : 'Secure messages are restricted to the terminal for now. Dashboard inbox, requests, and compose are coming soon.'}
                  </div>
                  <button
                    onClick={openTerminal}
                    className="mt-1 w-full flex items-center justify-between gap-2 px-3 py-2 border border-cyan-700/40 bg-cyan-950/15 text-cyan-300 hover:bg-cyan-950/25 hover:border-cyan-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Terminal size={11} />
                      OPEN TERMINAL
                    </span>
                    <span className="text-[12px] font-mono text-cyan-300/70">
                      COMING TO DASHBOARD SOON
                    </span>
                  </button>
                </div>
              </div>
            ) : (
            <div className="mx-2 mb-2 mt-1 border border-cyan-800/40 bg-black/30 shrink-0 relative">
              <span className="absolute -top-[7px] left-3 bg-[var(--bg-primary)] px-1 text-[11px] font-mono text-cyan-700/60 tracking-[0.15em] select-none">INPUT</span>
              {/* Destination indicator / error */}
              <div className="flex items-center gap-1 px-3 pt-2.5 pb-0">
                {sendError ? (
                  <>
                    <span className="text-[11px] font-mono tracking-widest text-red-400/80 uppercase animate-pulse">
                      ✕ {sendError}
                    </span>
                    {activeTab === 'infonet' && selectedGate && gateResyncTarget === selectedGate && (
                      <button
                        onClick={() => void handleResyncGateState(selectedGate)}
                        disabled={gateResyncBusy}
                        className="px-1.5 py-0.5 text-[11px] font-mono tracking-[0.16em] border border-amber-700/40 text-amber-200 hover:bg-amber-950/20 disabled:opacity-60 transition-colors"
                      >
                        {gateResyncBusy ? 'RESYNCING' : 'RESYNC'}
                      </button>
                    )}
                    {activeTab === 'meshtastic' && (
                      <button
                        onClick={() =>
                          openIdentityWizard({
                            type: 'err',
                            text: 'Public mesh send needs a working public identity. Create or reset it here.',
                          })
                        }
                        className="ml-auto px-1.5 py-0.5 text-[11px] font-mono tracking-[0.16em] border border-red-700/40 text-red-300 hover:bg-red-950/20 transition-colors"
                      >
                        FIX
                      </button>
                    )}
                  </>
                ) : (
                  <span className="text-[11px] font-mono tracking-widest text-[var(--text-muted)] uppercase">
                    {activeTab === 'infonet'
                      ? privateInfonetReady
                        ? `→ INFONET${selectedGate ? ` / ${selectedGate}` : ''}${privateInfonetTransportReady ? '' : ' / EXPERIMENTAL ENCRYPTION'}`
                        : '→ PRIVATE LANE LOCKED'
                      : activeTab === 'meshtastic'
                        ? hasPublicLaneIdentity
                          ? meshDirectTarget
                            ? `→ MESH / TO ${meshDirectTarget.toUpperCase()}`
                            : `→ MESH / ${meshRegion} / ${meshChannel}`
                          : '→ MESH LOCKED'
                        : activeTab === 'dms' && secureDmBlocked
                          ? '→ DEAD DROP LOCKED'
                        : dmView === 'chat' && selectedContact
                          ? `→ DEAD DROP / ${selectedContact.slice(0, 14)}`
                          : '→ SELECT TARGET'}
                  </span>
                )}
              </div>
              {activeTab === 'meshtastic' && !hasPublicLaneIdentity && !sendError && (
                <div
                  className={`px-3 pt-1 text-[12px] font-mono leading-[1.5] ${
                    meshQuickStatus?.type === 'err'
                      ? 'text-red-300/80'
                      : meshQuickStatus?.type === 'ok'
                        ? 'text-green-300/80'
                        : 'text-green-300/70'
                  }`}
                >
                  {meshQuickStatus?.text ||
                    (publicMeshBlockedByWormhole
                      ? 'Wormhole is active. Turn it off here and we will mint a separate public mesh key for you.'
                      : 'Public mesh posting needs a mesh key. One tap gets you a fresh address.')}
                </div>
              )}
              <div className="flex items-center gap-2 px-3 pb-2 pt-1">
                {activeTab === 'infonet' && !privateInfonetReady ? (
                  <button
                    onClick={() => setInfonetUnlockOpen(true)}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-cyan-700/40 bg-cyan-950/15 text-cyan-300 hover:bg-cyan-950/25 hover:border-cyan-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Shield size={11} />
                      UNLOCK INFONET
                    </span>
                    <span className="text-[12px] font-mono text-cyan-300/70">
                      OPEN PRIVATE LANE BRIEF
                    </span>
                  </button>
                ) : activeTab === 'dms' && secureDmBlocked ? (
                  <button
                    onClick={() => setDeadDropUnlockOpen(true)}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-cyan-700/40 bg-cyan-950/15 text-cyan-300 hover:bg-cyan-950/25 hover:border-cyan-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Lock size={11} />
                      UNLOCK DEAD DROP
                    </span>
                    <span className="text-[12px] font-mono text-cyan-300/70">
                      NEED WORMHOLE
                    </span>
                  </button>
                ) : activeTab === 'meshtastic' && !hasPublicLaneIdentity ? (
                  <button
                    onClick={() => {
                      if (publicMeshBlockedByWormhole) {
                        void handleLeaveWormholeForPublicMesh();
                        return;
                      }
                      void handleQuickCreatePublicIdentity();
                    }}
                    disabled={identityWizardBusy}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-green-700/40 bg-green-950/15 text-green-300 hover:bg-green-950/25 hover:border-green-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Radio size={11} />
                      {identityWizardBusy
                        ? 'GETTING MESH KEY'
                        : publicMeshBlockedByWormhole
                          ? 'TURN OFF WORMHOLE FOR MESH'
                          : 'GET MESH KEY'}
                    </span>
                    <span className="text-[12px] font-mono text-green-300/70">
                      {identityWizardBusy
                        ? 'WORKING...'
                        : publicMeshBlockedByWormhole
                          ? 'AUTO FIX'
                          : 'ONE TAP'}
                    </span>
                  </button>
                ) : activeTab === 'meshtastic' && meshDirectTarget ? (
                  <button
                    onClick={() => setMeshDirectTarget('')}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-amber-700/40 bg-amber-950/10 text-amber-200 hover:bg-amber-950/20 hover:border-amber-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Send size={11} />
                      DIRECT TO {meshDirectTarget.toUpperCase()}
                    </span>
                    <span className="text-[12px] font-mono text-amber-200/70">RETURN TO CHANNEL</span>
                  </button>
                ) : activeTab === 'infonet' &&
                  privateInfonetReady &&
                  selectedGateKeyStatus?.identity_scope === 'anonymous' &&
                  !selectedGateKeyStatus?.has_local_access ? (
                  <button
                    onClick={() => void handleUnlockEncryptedGate()}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-amber-700/40 bg-amber-950/10 text-amber-200 hover:bg-amber-950/20 hover:border-amber-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Lock size={11} />
                      UNLOCK ENCRYPTED GATE
                    </span>
                    <span className="text-[12px] font-mono text-amber-200/70">
                      {selectedGatePersonaList.length > 0 ? 'USE GATE FACE' : 'CREATE GATE FACE'}
                    </span>
                  </button>
                ) : (
                  <>
                    <span className="text-[11px] text-cyan-400 select-none shrink-0 font-mono" style={{ textShadow: '0 0 6px rgba(34,211,238,0.4)' }}>
                      &gt;
                    </span>
                    <div className="relative flex-1">
                      {activeTab === 'infonet' && gateReplyContext && (
                        <div className="mb-2 flex items-center justify-between gap-2 rounded border border-amber-500/20 bg-amber-500/8 px-2 py-1 text-[12px] font-mono tracking-[0.14em] text-amber-100">
                          <span>
                            REPLYING TO {gateReplyContext.nodeId.slice(0, 12)} / {gateReplyContext.eventId.slice(0, 8)}
                          </span>
                          <button
                            onClick={() => setGateReplyContext(null)}
                            className="text-amber-200/80 transition-colors hover:text-amber-100"
                          >
                            CLEAR
                          </button>
                        </div>
                      )}
                      <div
                        ref={cursorMirrorRef}
                        aria-hidden="true"
                        className="absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-[11px] font-mono leading-[1.65] pointer-events-none invisible"
                      >
                        {inputValue.slice(0, inputCursorIndex)}
                        <span ref={cursorMarkerRef} className="inline-block w-0 h-[14px] align-text-top" />
                        {inputValue.slice(inputCursorIndex) || ' '}
                      </div>
                      <textarea
                        ref={inputRef}
                        value={inputValue}
                        onChange={(e) => {
                          setInputValue(e.target.value);
                          setInputCursorIndex(e.target.selectionStart ?? e.target.value.length);
                        }}
                        onSelect={syncCursorPosition}
                        onClick={syncCursorPosition}
                        onKeyUp={syncCursorPosition}
                        onFocus={() => {
                          setInputFocused(true);
                          syncCursorPosition();
                        }}
                        onBlur={() => setInputFocused(false)}
                        onScroll={() => {
                          const mirror = cursorMirrorRef.current;
                          if (mirror && inputRef.current) mirror.scrollTop = inputRef.current.scrollTop;
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            handleSend();
                          }
                        }}
                        placeholder=""
                        disabled={inputDisabled}
                        rows={1}
                        className="w-full bg-transparent text-[11px] font-mono text-cyan-400 outline-none border-none resize-none placeholder:text-[var(--text-muted)] disabled:opacity-30 leading-[1.65] caret-transparent min-h-[18px] max-h-24 pr-1"
                      />
                      {!busy && !inputDisabled && inputFocused && (
                        <span
                          className="absolute pointer-events-none w-[7px] h-[14px] bg-cyan-400/90 animate-[blink_1s_step-end_infinite]"
                          style={{
                            left: `${cursorMarkerRef.current?.offsetLeft ?? 0}px`,
                            top: `${cursorMarkerRef.current?.offsetTop ?? 1}px`,
                            boxShadow: '0 0 8px rgba(34,211,238,0.45)',
                          }}
                        />
                      )}
                    </div>
                    <button
                      onClick={handleSend}
                      disabled={!inputValue.trim() || inputDisabled}
                      className="p-1 border border-cyan-800/40 text-cyan-500 hover:text-cyan-300 hover:border-cyan-500/50 hover:bg-cyan-950/30 disabled:opacity-20 transition-colors"
                    >
                      <Send size={10} />
                    </button>
                  </>
                )}
              </div>
            </div>
            )}
          </div>
        )}
      </div>

      {gatePersonaPromptOpen && (
        <div className="fixed inset-0 z-[455] bg-black/80 backdrop-blur-sm p-4 flex items-center justify-center">
          <div className="w-full max-w-md border border-fuchsia-800/50 bg-[var(--bg-primary)] shadow-[0_0_34px_rgba(236,72,153,0.12)]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-fuchsia-800/40">
              <div>
                <div className="text-sm font-mono tracking-[0.24em] text-fuchsia-300">
                  GATE FACE
                </div>
                <div className="text-[13px] font-mono text-[var(--text-muted)] mt-1">
                  {gatePersonaPromptTitle
                    ? `Entering ${String(gatePersonaPromptTitle).toUpperCase()}`
                    : 'Choose how you enter this gate'}
                </div>
              </div>
              <button
                onClick={closeGatePersonaPrompt}
                className="text-[var(--text-muted)] hover:text-fuchsia-300 transition-colors"
                title="Close gate face chooser"
              >
                <X size={13} />
              </button>
            </div>

            <div className="px-4 py-4 space-y-3">
              <div className="border border-fuchsia-800/25 bg-fuchsia-950/10 px-3 py-3 text-sm font-mono text-fuchsia-100/85 leading-[1.7]">
                Stay anonymous in this gate or create a gate-only face. Face names stay inside
                this gate and cannot be changed in this build.
              </div>

              {gatePersonaPromptPersonaList.length > 0 && (
                <div className="border border-cyan-800/25 bg-cyan-950/10 px-3 py-3">
                  <div className="text-[12px] font-mono tracking-[0.18em] text-cyan-300 mb-2">
                    SAVED FACES
                  </div>
                  <div className="space-y-2">
                    {gatePersonaPromptPersonaList.map((persona) => (
                      <button
                        key={persona.persona_id || persona.node_id}
                        onClick={() => void selectSavedGatePersona(String(persona.persona_id || ''))}
                        disabled={gatePersonaBusy}
                        className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-cyan-700/35 bg-black/20 text-left text-sm font-mono text-cyan-200 hover:bg-cyan-950/20 hover:border-cyan-500/50 disabled:opacity-50 transition-colors"
                      >
                        <span>
                          {persona.label || persona.persona_id || String(persona.node_id || '').slice(0, 12)}
                        </span>
                        <span className="text-[12px] tracking-[0.16em] text-cyan-300/70">
                          USE FACE
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="border border-fuchsia-800/25 bg-black/20 px-3 py-3 space-y-2">
                <div className="text-[12px] font-mono tracking-[0.18em] text-fuchsia-300">
                  CREATE NEW FACE
                </div>
                <input
                  value={gatePersonaDraftLabel}
                  onChange={(e) => {
                    setGatePersonaDraftLabel(e.target.value.slice(0, 24));
                    setGatePersonaPromptError('');
                  }}
                  placeholder="gate name / handle"
                  className="w-full bg-black/30 border border-fuchsia-700/35 text-sm font-mono text-fuchsia-100 px-3 py-2 outline-none placeholder:text-fuchsia-200/35 focus:border-fuchsia-500/55"
                />
                <div className="text-[12px] font-mono text-fuchsia-200/55 leading-[1.5]">
                  Example: `signalfox`, `source-a`, `ops-lantern`
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => void submitGatePersonaPrompt()}
                    disabled={gatePersonaBusy || gatePersonaDraftLabel.trim().length < 2}
                    className="px-3 py-1.5 border border-fuchsia-600/40 bg-fuchsia-950/20 text-sm font-mono tracking-[0.18em] text-fuchsia-200 hover:bg-fuchsia-950/30 hover:border-fuchsia-400/50 disabled:opacity-50 transition-colors"
                  >
                    {gatePersonaBusy ? 'CREATING' : 'CREATE FACE'}
                  </button>
                  <button
                    onClick={remainAnonymousInGate}
                    disabled={gatePersonaBusy}
                    className="px-3 py-1.5 border border-amber-700/35 bg-amber-950/10 text-sm font-mono tracking-[0.18em] text-amber-200 hover:bg-amber-950/20 hover:border-amber-500/50 disabled:opacity-50 transition-colors"
                  >
                    REMAIN ANONYMOUS
                  </button>
                </div>
              </div>

              {gatePersonaPromptError && (
                <div className="border border-red-700/35 bg-red-950/10 px-3 py-2 text-sm font-mono text-red-300">
                  {gatePersonaPromptError}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {identityWizardOpen && (
        <div className="fixed inset-0 z-[450] bg-black/75 backdrop-blur-sm p-3 flex items-center justify-center">
          <div className="w-full max-w-md border border-cyan-800/50 bg-[var(--bg-primary)] shadow-[0_0_30px_rgba(0,255,255,0.08)]">
            <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-primary)]/40">
                <div>
                <div className="text-sm font-mono tracking-[0.24em] text-cyan-400">KEY SETUP</div>
                <div className="text-[13px] font-mono text-[var(--text-muted)] mt-1">
                  Get a public mesh key or enter Wormhole.
                </div>
              </div>
              <button
                onClick={() => setIdentityWizardOpen(false)}
                className="text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
                title="Close identity setup"
              >
                <X size={13} />
              </button>
            </div>

            <div className="px-3 py-3 space-y-2.5">
              <div className="grid grid-cols-2 gap-2 text-[12px] font-mono">
                <div className="border border-amber-500/20 bg-amber-950/10 px-2.5 py-2 text-amber-200/85 leading-[1.5]">
                  <div className="text-amber-300 tracking-[0.18em] mb-1">PUBLIC MESH</div>
                  Public lane. One tap gets you a posting key.
                </div>
                <div className="border border-cyan-500/20 bg-cyan-950/10 px-2.5 py-2 text-cyan-200/85 leading-[1.5]">
                  <div className="text-cyan-300 tracking-[0.18em] mb-1">WORMHOLE</div>
                  Gates run on a transitional private lane. Dead Drop / DM is a separate, stronger private lane.
                </div>
              </div>

              <div className="border border-[var(--border-primary)]/40 bg-black/20 px-3 py-2">
                <div className="text-[13px] font-mono tracking-[0.18em] text-cyan-300 mb-1">
                  CURRENT STATE
                </div>
                <div className="grid grid-cols-1 gap-1 text-[13px] font-mono text-[var(--text-secondary)] leading-[1.5]">
                  <div>Public mesh key: {hasPublicLaneIdentity ? 'active' : 'not issued'}</div>
                  <div>Public mesh address: {hasPublicLaneIdentity && publicMeshAddress ? publicMeshAddress.toUpperCase() : 'not ready'}</div>
                  <div>Wormhole lane: {wormholeEnabled && wormholeReadyState ? 'active' : wormholeEnabled ? 'starting' : 'off'}</div>
                  <div>Wormhole descriptor: {wormholeDescriptor?.nodeId || 'not cached yet'}</div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-2">
                <button
                  onClick={() => {
                    if (publicMeshBlockedByWormhole) {
                      void handleLeaveWormholeForPublicMesh();
                      return;
                    }
                    void handleCreatePublicIdentity();
                  }}
                  disabled={identityWizardBusy}
                  className="w-full text-left px-3 py-2 border border-green-500/30 bg-green-950/10 hover:bg-green-950/20 text-sm font-mono text-green-300 disabled:opacity-50"
                >
                  {hasPublicLaneIdentity
                    ? 'MESH KEY ACTIVE'
                    : publicMeshBlockedByWormhole
                      ? 'TURN OFF WORMHOLE FOR MESH'
                      : 'GET MESH KEY'}
                  <div className="mt-1 text-[13px] text-green-200/70 normal-case tracking-normal leading-[1.45]">
                    {hasPublicLaneIdentity
                      ? 'Your public mesh key is already live for posting.'
                      : publicMeshBlockedByWormhole
                        ? 'One tap turns Wormhole off and mints a separate public mesh key.'
                        : 'One tap for a working mesh key and address.'}
                  </div>
                </button>

                <button
                  onClick={() => void handleBootstrapPrivateIdentity()}
                  disabled={identityWizardBusy}
                  className="w-full text-left px-3 py-2 border border-cyan-500/30 bg-cyan-950/10 hover:bg-cyan-950/20 text-sm font-mono text-cyan-300 disabled:opacity-50"
                >
                  {wormholeEnabled && wormholeReadyState ? 'ENTER INFONET' : 'GET WORMHOLE KEY'}
                  <div className="mt-1 text-[13px] text-cyan-200/70 normal-case tracking-normal leading-[1.45]">
                    {wormholeEnabled && wormholeReadyState
                      ? 'Wormhole is already live. Jump straight into gates and the private inbox.'
                      : 'Use this for gates, experimental obfuscation, and the private inbox.'}
                  </div>
                </button>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => void handleResetPublicIdentity()}
                    disabled={identityWizardBusy}
                    className="flex-1 text-left px-3 py-2 border border-red-500/30 bg-red-950/10 hover:bg-red-950/20 text-sm font-mono text-red-300 disabled:opacity-50"
                  >
                    RESET PUBLIC IDENTITY
                  </button>
                  {publicMeshBlockedByWormhole && (
                    <button
                      onClick={() => void handleLeaveWormholeForPublicMesh()}
                      disabled={identityWizardBusy}
                      className="px-3 py-2 border border-green-500/30 bg-green-950/10 text-sm font-mono text-green-300 hover:bg-green-950/20 disabled:opacity-50"
                    >
                      TURN OFF WORMHOLE
                    </button>
                  )}
                  {onSettingsClick && (
                    <button
                      onClick={() => {
                        setIdentityWizardOpen(false);
                        onSettingsClick();
                      }}
                      className="px-3 py-2 border border-[var(--border-primary)] text-sm font-mono text-[var(--text-secondary)] hover:text-cyan-300 hover:border-cyan-500/40"
                    >
                      OPEN SETTINGS
                    </button>
                  )}
                </div>
              </div>

              {identityWizardStatus && (
                <div
                  className={`px-3 py-2 border text-sm font-mono leading-[1.65] ${
                    identityWizardStatus.type === 'ok'
                      ? 'border-green-500/30 bg-green-950/10 text-green-300'
                      : 'border-red-500/30 bg-red-950/10 text-red-300'
                  }`}
                >
                  {identityWizardStatus.text}
                </div>
              )}

              <div className="text-[12px] font-mono text-[var(--text-muted)] leading-[1.5]">
                Testnet note: mesh is public, gates use experimental encryption, and Dead Drop is the strongest current lane.
              </div>
            </div>
          </div>
        </div>
      )}

      {infonetUnlockOpen && (
        <div className="fixed inset-0 z-[460] bg-black/80 backdrop-blur-sm p-4 flex items-center justify-center">
          <div className="w-full max-w-xl border border-cyan-800/50 bg-[var(--bg-primary)] shadow-[0_0_34px_rgba(0,255,255,0.1)]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-primary)]/40">
              <div>
                <div className="text-sm font-mono tracking-[0.24em] text-cyan-400">
                  PRIVATE INFONET LOCKED
                </div>
                <div className="text-[13px] font-mono text-[var(--text-muted)] mt-1">
                  INFONET is the private Wormhole lane. Public perimeter traffic stays under MESH.
                </div>
              </div>
              <button
                onClick={() => setInfonetUnlockOpen(false)}
                className="text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
                title="Close private lane brief"
              >
                <X size={13} />
              </button>
            </div>

            <div className="px-4 py-4 space-y-4">
              <div className="border border-cyan-800/30 bg-cyan-950/10 px-3 py-3 text-sm font-mono text-[var(--text-secondary)] leading-[1.8] space-y-2">
                <div>
                  INFONET is the private lane now. Public perimeter traffic lives under the
                  <span className="text-green-300"> MESH </span>
                  tab.
                </div>
                <div>{privateInfonetBlockedDetail}</div>
                <div>
                  Use Wormhole to enter private gates, personas, gate chat, and the serious
                  testnet path.
                </div>
              </div>

              <div className="border border-amber-500/20 bg-amber-950/10 px-3 py-3 text-sm font-mono text-amber-100/85 leading-[1.75]">
                <div className="text-[13px] tracking-[0.18em] text-amber-300 mb-1">TRUST MODES</div>
                <div><span className="text-orange-300">PUBLIC / DEGRADED</span> — public mesh and perimeter feeds.</div>
                <div><span className="text-yellow-300">PRIVATE / TRANSITIONAL</span> — Wormhole lane active. Gate chat is available on this lane, but metadata resistance is reduced until Reticulum is ready.</div>
                <div><span className="text-green-300">PRIVATE / STRONG</span> — Wormhole and Reticulum are both ready. Dead Drop / DM requires this tier for the strongest content and transport privacy.</div>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => {
                    setInfonetUnlockOpen(false);
                    onSettingsClick?.();
                  }}
                  className="px-3 py-1.5 border border-cyan-500/40 bg-cyan-950/20 text-sm font-mono text-cyan-300 hover:bg-cyan-950/35 transition-colors"
                >
                  OPEN WORMHOLE
                </button>
                <button
                  onClick={() => {
                    setInfonetUnlockOpen(false);
                    openTerminal();
                  }}
                  className="px-3 py-1.5 border border-green-500/40 bg-green-950/20 text-sm font-mono text-green-300 hover:bg-green-950/35 transition-colors inline-flex items-center gap-1.5"
                >
                  <Terminal size={11} />
                  TERMINAL
                </button>
                <button
                  onClick={() => {
                    setInfonetUnlockOpen(false);
                    setActiveTab('meshtastic');
                  }}
                  className="px-3 py-1.5 border border-amber-500/40 bg-amber-950/20 text-sm font-mono text-amber-300 hover:bg-amber-950/35 transition-colors"
                >
                  GO TO MESH
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {deadDropUnlockOpen && (
        <div className="fixed inset-0 z-[460] bg-black/80 backdrop-blur-sm p-4 flex items-center justify-center">
          <div className="w-full max-w-lg border border-cyan-800/50 bg-[var(--bg-primary)] shadow-[0_0_34px_rgba(0,255,255,0.1)]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-primary)]/40">
              <div>
                <div className="text-sm font-mono tracking-[0.24em] text-cyan-400">
                  DEAD DROP LOCKED
                </div>
                <div className="text-[13px] font-mono text-[var(--text-muted)] mt-1">
                  Dead Drop is the private inbox lane. Public mesh does not substitute for it.
                </div>
              </div>
              <button
                onClick={() => setDeadDropUnlockOpen(false)}
                className="text-[var(--text-muted)] hover:text-cyan-300 transition-colors"
                title="Close dead drop brief"
              >
                <X size={13} />
              </button>
            </div>

            <div className="px-4 py-4 space-y-4">
              <div className="border border-cyan-800/30 bg-cyan-950/10 px-3 py-3 text-sm font-mono text-[var(--text-secondary)] leading-[1.8] space-y-2">
                <div>Need Wormhole activated.</div>
                <div>
                  Dead Drop handles private contacts, inbox requests, and message exchange on the
                  private lane.
                </div>
                <div>
                  Public mesh stays public. Dead Drop does not downgrade into the perimeter just to
                  look available.
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => {
                    setDeadDropUnlockOpen(false);
                    onSettingsClick?.();
                  }}
                  className="px-3 py-1.5 border border-cyan-500/40 bg-cyan-950/20 text-sm font-mono text-cyan-300 hover:bg-cyan-950/35 transition-colors"
                >
                  OPEN WORMHOLE
                </button>
                <button
                  onClick={() => {
                    setDeadDropUnlockOpen(false);
                    openTerminal();
                  }}
                  className="px-3 py-1.5 border border-green-500/40 bg-green-950/20 text-sm font-mono text-green-300 hover:bg-green-950/35 transition-colors inline-flex items-center gap-1.5"
                >
                  <Terminal size={11} />
                  TERMINAL
                </button>
                <button
                  onClick={() => {
                    setDeadDropUnlockOpen(false);
                    setActiveTab('meshtastic');
                  }}
                  className="px-3 py-1.5 border border-amber-500/40 bg-amber-950/20 text-sm font-mono text-amber-300 hover:bg-amber-950/35 transition-colors"
                >
                  GO TO MESH
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── SENDER POPUP (fixed position) ─── */}
      {senderPopup && (
        <div
          ref={popupRef}
          className="fixed z-[500] bg-[var(--bg-primary)]/95 border border-[var(--border-primary)] shadow-[0_4px_20px_rgba(0,0,0,0.4)] backdrop-blur-sm py-1 min-w-[140px]"
          style={{ left: senderPopup.x, top: senderPopup.y }}
        >
          <div className="px-3 py-1 border-b border-[var(--border-primary)]/50">
            <span className="text-[13px] font-mono text-cyan-400 tracking-wider">
              {senderPopup.userId.slice(0, 16)}
            </span>
          </div>

          {senderPopup.tab === 'infonet' && (
            <div className="px-3 py-2 border-b border-[var(--border-primary)]/50">
              <div className="text-[12px] font-mono text-[var(--text-muted)] tracking-[0.18em]">
                PUBLIC KEY
              </div>
              <div
                className="mt-1 text-[12px] font-mono text-green-300/90 break-all leading-[1.55]"
                title={senderPopup.publicKey || 'not advertised on this event'}
              >
                {senderPopup.publicKey || 'not advertised on this event'}
              </div>
              {senderPopup.publicKeyAlgo ? (
                <div className="mt-1 text-[12px] font-mono text-cyan-500/80">
                  {senderPopup.publicKeyAlgo}
                </div>
              ) : null}
            </div>
          )}

          {/* MUTE / UNMUTE */}
          {mutedUsers.has(senderPopup.userId) ? (
            <button
              onClick={() => handleUnmute(senderPopup.userId)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]/50 transition-colors"
            >
              <Eye size={10} /> UNMUTE
            </button>
          ) : (
            <button
              onClick={() => setMuteConfirm(senderPopup.userId)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-red-400/80 hover:bg-red-900/10 transition-colors"
            >
              <EyeOff size={10} /> MUTE
            </button>
          )}

          {/* LOCATE — meshtastic only */}
          {senderPopup.tab === 'meshtastic' && (
            <>
              <button
                onClick={() => handleReplyToMeshAddress(senderPopup.userId)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-green-300 hover:bg-green-950/20 transition-colors"
              >
                <Send size={10} /> REPLY
              </button>
              <button
                onClick={() => handleLocateUser(senderPopup.userId)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]/50 transition-colors"
              >
                <MapPin size={10} /> LOCATE
              </button>
            </>
          )}

          {/* CONTACT PATH — infonet only */}
          {senderPopup.tab === 'infonet' && hasId && senderPopup.userId !== identity?.nodeId && (
            <>
              {senderPopupContact && !senderPopupContact.blocked ? (
                <button
                  onClick={() => {
                    setActiveTab('dms');
                    openChat(senderPopup.userId);
                    setSenderPopup(null);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-green-300 hover:bg-green-950/20 transition-colors"
                >
                  <Send size={10} /> OPEN DM
                </button>
              ) : (
                <button
                  onClick={() => {
                    handleRequestAccess(senderPopup.userId);
                    setSenderPopup(null);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]/50 transition-colors"
                >
                  <UserPlus size={10} /> REQUEST CONTACT
                </button>
              )}
              {!senderPopupContact?.blocked ? (
                <button
                  onClick={() => {
                    void handleBlockDM(senderPopup.userId);
                    setSenderPopup(null);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-red-400/80 hover:bg-red-900/10 transition-colors"
                >
                  <Ban size={10} /> BLOCK
                </button>
              ) : (
                <div className="px-3 py-1.5 text-[12px] font-mono text-red-300/70 tracking-[0.18em]">
                  CONTACT BLOCKED
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ─── MUTE CONFIRMATION DIALOG ─── */}
      {muteConfirm && (
        <div className="fixed inset-0 z-[600] flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-[var(--bg-primary)] border border-[var(--border-primary)] p-4 max-w-[260px] w-full">
            <div className="text-sm font-mono text-[var(--text-secondary)] mb-1">
              CONFIRM MUTE
            </div>
            <div className="text-[13px] font-mono text-[var(--text-muted)] mb-3 leading-[1.65]">
              Mute <span className="text-cyan-400">{muteConfirm.slice(0, 16)}</span>? Their messages
              will be hidden. You can unmute from Dead Drop &gt; MUTED.
            </div>
            <div className="flex items-center gap-2 justify-end">
              <button
                onClick={() => {
                  setMuteConfirm(null);
                  setSenderPopup(null);
                }}
                className="text-[13px] font-mono px-3 py-1 bg-[var(--bg-secondary)]/50 text-[var(--text-muted)] hover:bg-[var(--bg-secondary)] transition-colors"
              >
                CANCEL
              </button>
              <button
                onClick={() => handleMute(muteConfirm)}
                className="text-[13px] font-mono px-3 py-1 bg-red-900/30 text-red-400 hover:bg-red-800/40 transition-colors"
              >
                MUTE
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

export default MeshChat;
