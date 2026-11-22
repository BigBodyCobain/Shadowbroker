// @ts-nocheck
'use client';

import React from 'react';
import { AnimatePresence, motion } from '@/lib/motion';
import { Shield, ExternalLink, Key, Copy, Check, ChevronDown, ChevronUp, Radar, Save } from 'lucide-react';

export function SettingsPanelProtocol({ ctx }: { ctx: Record<string, any> }) {
  const {
    Active,
    Age,
    Auto,
    Browser,
    Chat,
    Clears,
    Companion,
    Configured,
    Connect,
    Could,
    Current,
    Direct,
    Enables,
    Experimental,
    External,
    Hidden,
    High,
    Identity,
    Loading,
    Machine,
    Manual,
    Mesh,
    Meshtastic,
    Mixnet,
    Mode,
    No,
    One,
    Open,
    Operator,
    Press,
    Privacy,
    Public,
    Recommendation,
    Records,
    Relay,
    RotateCcw,
    Runs,
    Session,
    Settings,
    Snapshots,
    Terminal,
    The,
    This,
    Time,
    Tor,
    Try,
    Unlock,
    Use,
    Wait,
    We,
    When,
    Wormhole,
    Your,
    above,
    across,
    action,
    actions,
    active,
    active_peers,
    adminSessionMsg,
    adminSessionReady,
    after,
    age_s,
    agent,
    alerts,
    alias,
    all,
    allowed,
    already,
    amber,
    analysis,
    and,
    anonModeReady,
    anonymity,
    anonymous,
    app,
    applies,
    are,
    as,
    ask,
    assurance,
    at,
    auto,
    available,
    back,
    backend,
    background,
    before,
    behavior,
    below,
    between,
    bg,
    black,
    blocked,
    blockedCount,
    blocking,
    blue,
    border,
    bridge,
    browser,
    browserWipeBusy,
    browserWipeMsg,
    but,
    cached,
    can,
    center,
    central,
    channels,
    clearSessionIdentity,
    clearnet,
    click,
    clipboard,
    close,
    closed,
    col,
    colors,
    companion,
    companionAvailable,
    companionBusy,
    companionError,
    companionLoadFailed,
    compared,
    compartmentalized,
    compat,
    compressed,
    compromise,
    configured,
    configured_peers,
    connect,
    contacts,
    controlWormhole,
    count,
    current,
    cursor,
    cutoff,
    cyan,
    day,
    degraded,
    describeBrowserGateLocalRuntimeStatus,
    desktop,
    detail,
    did,
    direct,
    directly,
    disconnect,
    dmRootCardTone,
    dmRootHealth,
    dmRootHealthBusy,
    dmRootHealthMsg,
    dmRootMonitorLabel,
    dmRootUrgencyTone,
    does,
    down,
    effectiveTransport,
    eliminate,
    enabled,
    endpoint,
    enters,
    entity,
    error,
    explicitly,
    export_path,
    external,
    fail,
    fallback,
    fetchDmRootHealth,
    final,
    flex,
    flights,
    focus,
    font,
    formatAgeWindow,
    formatGateCompatSeenAt,
    formatLegacyCompatibilitySeenAt,
    freshness,
    freshness_window_s,
    from,
    fuchsia,
    full,
    fully,
    gap,
    gate,
    gateCompatTelemetry,
    gateCompatTopReasons,
    gateLocalRuntimeStatus,
    gates,
    green,
    grid,
    guarantee,
    guidance,
    gzip,
    handle,
    handles,
    hard,
    hardened,
    health,
    health_state,
    held,
    help,
    hidden,
    hide,
    high,
    historical,
    hourly,
    hover,
    i2p,
    identities,
    identity,
    immediately,
    inbox,
    inline,
    inside,
    integrity,
    into,
    is,
    issues,
    it,
    items,
    jitter,
    join,
    justify,
    keys,
    last,
    lastAt,
    lastSeenAt,
    last_error,
    leading,
    leave,
    ledger,
    legacy,
    legacyCompatibilityActivity,
    legacyCompatibilityAllBlocked,
    legacyCompatibilityItems,
    length,
    live,
    load,
    local,
    localhost,
    locally,
    low,
    machine,
    make,
    map,
    may,
    mb,
    mesh,
    metadata,
    middot,
    migratePrivacySensitiveBrowserState,
    mixnet,
    monitoring,
    mono,
    month,
    mt,
    muted,
    mx,
    native,
    nativeProtected,
    need,
    needed,
    never,
    next_action,
    next_action_detail,
    none,
    not,
    now,
    nowrap,
    obfuscated,
    observed,
    observer,
    of,
    off,
    ok,
    on,
    only,
    opacity,
    openCompanionBrowser,
    operator,
    or,
    orange,
    outline,
    over,
    overflow,
    page,
    peers,
    persist,
    personas,
    phase,
    pid,
    playback,
    policy,
    positions,
    posting,
    primary,
    privacy,
    privacyProfile,
    profile,
    protection,
    proxy,
    proxy_active,
    publicly,
    purple,
    px,
    py,
    quickStartWormhole,
    ratchet,
    read,
    readback,
    ready,
    reason,
    recent,
    recentGates,
    recentPrivateFallback,
    recentPrivateFallbackReason,
    recentTargets,
    recommended,
    recorded,
    red,
    reduces,
    refuses,
    regular,
    relaxed,
    remain,
    remediation,
    remove,
    removing,
    reopening,
    replaceAll,
    reputable,
    require,
    required,
    requiredCount,
    requires,
    reset,
    respond,
    restart,
    restarting,
    restarts,
    right,
    risk,
    risks,
    rnsStatus,
    rooms,
    root,
    rounded,
    routes,
    runbook,
    running,
    runtime,
    satellites,
    saveWormholeSettings,
    scrollbar,
    scrubber,
    secondary,
    see,
    seen,
    send,
    sends,
    sensitive,
    separate,
    service,
    session,
    sessionMode,
    setHighPrivacy,
    setSessionMode,
    setSessionModePreference,
    setShowAdvancedWormhole,
    setShowOperatorTools,
    setWormholeAnonymousMode,
    setWormholeDirty,
    setWormholeKeyCopied,
    setWormholeSocksDns,
    setWormholeSocksProxy,
    setWormholeTransport,
    setup,
    sharded,
    ships,
    showAdvancedWormhole,
    showOperatorTools,
    shrink,
    shut,
    size,
    slate,
    slice,
    sm,
    snapshots,
    source,
    source_label,
    source_ref,
    space,
    start,
    state,
    status,
    status_line,
    stays,
    storage,
    stored,
    straight,
    stricter,
    strong_trust_blocked,
    stronger,
    styled,
    sync,
    tabs,
    targetDate,
    targetVersion,
    text,
    that,
    the,
    through,
    ticket,
    timeline,
    tmEnabled,
    tmSaving,
    to,
    toUpperCase,
    toggleCompanion,
    toggleTimeMachine,
    toggleWormhole,
    tools,
    tor,
    totalRequired,
    totalUsed,
    tracking,
    traffic,
    transition,
    transparency,
    transport,
    transportMismatch,
    transports,
    trust,
    trustModeLabel,
    tuning,
    unavailable,
    unless,
    until,
    urgency,
    url,
    used,
    usedCount,
    via,
    violet,
    visible,
    warning,
    watch,
    when,
    whitespace,
    widest,
    will,
    wipeLocalMeshTraces,
    within,
    without,
    witness,
    works,
    wormholeAnonymousMode,
    wormholeDirty,
    wormholeEnabled,
    wormholeGuideNotice,
    wormholeKeyCopied,
    wormholeMsg,
    wormholeNodeId,
    wormholeQuickButtonLabel,
    wormholeQuickState,
    wormholeSaving,
    wormholeSocksDns,
    wormholeSocksProxy,
    wormholeStatus,
    wormholeTransport,
    wrap,
    writeText,
    writes,
    yellow,
    yet,
    you,
    your,
    zero
  } = ctx as any;

  return (
<>
              <div className="flex-1 min-h-0 flex flex-col overflow-y-auto styled-scrollbar">
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

                <div className={`mx-4 mt-4 p-3 border ${dmRootCardTone}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-mono tracking-[0.18em]">DM ROOT HEALTH</div>
                      <div className="mt-2 text-sm font-mono leading-relaxed text-[var(--text-secondary)]">
                        External witness freshness, transparency readback, and the next operator
                        action for strong DM trust.
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`px-2 py-1 border text-[11px] font-mono tracking-[0.18em] ${dmRootCardTone}`}
                      >
                        {!showOperatorTools
                          ? 'HIDDEN'
                          : dmRootHealth
                            ? dmRootMonitorLabel(dmRootHealth.monitoring?.state)
                            : dmRootHealthBusy
                              ? 'LOADING'
                              : dmRootHealthMsg
                                ? 'BLOCKED'
                                : 'UNKNOWN'}
                      </span>
                      {showOperatorTools && (nativeProtected || adminSessionReady) && (
                        <button
                          onClick={() => void fetchDmRootHealth()}
                          disabled={dmRootHealthBusy}
                          className="px-2 py-1 border border-cyan-500/30 text-[12px] font-mono tracking-[0.18em] text-cyan-200 hover:bg-cyan-950/20 disabled:opacity-50"
                        >
                          <span className="inline-flex items-center gap-1">
                            <RotateCcw size={11} />
                            REFRESH
                          </span>
                        </button>
                      )}
                    </div>
                  </div>

                  {!showOperatorTools ? (
                    <div className="mt-3 border border-cyan-500/20 bg-black/20 px-3 py-3 text-sm font-mono text-[var(--text-muted)] leading-relaxed">
                      Wormhole join stays visible without operator tools. Open operator tools to see
                      external witness freshness, transparency readback, and remediation guidance.
                      <div className="mt-3">
                        <button
                          onClick={() => setShowOperatorTools(true)}
                          className="px-3 py-1.5 border border-cyan-500/35 bg-cyan-950/18 text-[13px] font-mono tracking-[0.18em] text-cyan-200 hover:bg-cyan-950/28"
                        >
                          SHOW TOOLS
                        </button>
                      </div>
                    </div>
                  ) : !nativeProtected && !adminSessionReady ? (
                    <div className="mt-3 border border-yellow-500/25 bg-yellow-950/12 px-3 py-3 text-sm font-mono text-yellow-200/90 leading-relaxed">
                      Unlock operator tools above to load live DM root health, external witness
                      freshness, and transparency monitoring status.
                    </div>
                  ) : dmRootHealthBusy && !dmRootHealth ? (
                    <div className="mt-3 border border-cyan-500/20 bg-black/20 px-3 py-3 text-sm font-mono text-cyan-200/80">
                      Loading current DM root health...
                    </div>
                  ) : dmRootHealth ? (
                    <div className="mt-3 grid gap-2">
                      <div className="grid grid-cols-2 gap-2">
                        <div className="border border-[var(--border-primary)]/50 bg-black/20 px-3 py-2">
                          <div className="text-[12px] font-mono tracking-[0.18em] text-[var(--text-muted)]">
                            SUMMARY
                          </div>
                          <div className="mt-1 text-[13px] font-mono text-[var(--text-secondary)]">
                            {String(dmRootHealth.state || '').replaceAll('_', ' ').toUpperCase()}
                          </div>
                          <div className="mt-1 text-[12px] font-mono text-[var(--text-muted)] leading-relaxed">
                            {dmRootHealth.detail}
                          </div>
                        </div>
                        <div className="border border-[var(--border-primary)]/50 bg-black/20 px-3 py-2">
                          <div className="text-[12px] font-mono tracking-[0.18em] text-[var(--text-muted)]">
                            STRONG TRUST
                          </div>
                          <div
                            className={`mt-1 text-[13px] font-mono ${
                              dmRootHealth.strong_trust_blocked ? 'text-red-300' : 'text-green-300'
                            }`}
                          >
                            {dmRootHealth.strong_trust_blocked ? 'BLOCKED' : 'CURRENT'}
                          </div>
                          <div className="mt-1 text-[12px] font-mono text-[var(--text-muted)]">
                            {dmRootHealth.monitoring?.status_line || 'Operator monitoring active.'}
                          </div>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2">
                        <div className="border border-[var(--border-primary)]/50 bg-black/20 px-3 py-2">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-[12px] font-mono tracking-[0.18em] text-[var(--text-muted)]">
                              WITNESS
                            </div>
                            <span
                              className={`px-1.5 py-0.5 border text-[11px] font-mono tracking-widest ${dmRootUrgencyTone(
                                dmRootHealth.witness.health_state === 'error'
                                  ? 'page'
                                  : dmRootHealth.witness.health_state === 'warning'
                                    ? 'ticket'
                                    : 'watch',
                              )}`}
                            >
                              {String(dmRootHealth.witness.state || '').replaceAll('_', ' ').toUpperCase()}
                            </span>
                          </div>
                          <div className="mt-2 text-[12px] font-mono text-[var(--text-muted)]">
                            Age {formatAgeWindow(dmRootHealth.witness.age_s, dmRootHealth.witness.freshness_window_s)}
                          </div>
                          <div className="mt-1 text-[12px] font-mono text-[var(--text-muted)]">
                            {dmRootHealth.witness.source_label ||
                              dmRootHealth.witness.source_ref ||
                              dmRootHealth.witness.detail ||
                              'Configured witness source unavailable.'}
                          </div>
                        </div>

                        <div className="border border-[var(--border-primary)]/50 bg-black/20 px-3 py-2">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-[12px] font-mono tracking-[0.18em] text-[var(--text-muted)]">
                              TRANSPARENCY
                            </div>
                            <span
                              className={`px-1.5 py-0.5 border text-[11px] font-mono tracking-widest ${dmRootUrgencyTone(
                                dmRootHealth.transparency.health_state === 'error'
                                  ? 'page'
                                  : dmRootHealth.transparency.health_state === 'warning'
                                    ? 'ticket'
                                    : 'watch',
                              )}`}
                            >
                              {String(dmRootHealth.transparency.state || '').replaceAll('_', ' ').toUpperCase()}
                            </span>
                          </div>
                          <div className="mt-2 text-[12px] font-mono text-[var(--text-muted)]">
                            Age{' '}
                            {formatAgeWindow(
                              dmRootHealth.transparency.age_s,
                              dmRootHealth.transparency.freshness_window_s,
                            )}
                          </div>
                          <div className="mt-1 text-[12px] font-mono text-[var(--text-muted)]">
                            {dmRootHealth.transparency.source_ref ||
                              dmRootHealth.transparency.export_path ||
                              dmRootHealth.transparency.detail ||
                              'Configured ledger readback unavailable.'}
                          </div>
                        </div>
                      </div>

                      {dmRootHealth.alerts.length > 0 && (
                        <div className="border border-[var(--border-primary)]/50 bg-black/20 px-3 py-2">
                          <div className="text-[12px] font-mono tracking-[0.18em] text-[var(--text-muted)]">
                            ACTIVE ALERTS
                          </div>
                          <div className="mt-2 grid gap-2">
                            {dmRootHealth.alerts.slice(0, 2).map((alert: any) => (
                              <div
                                key={`${alert.code}-${alert.target}`}
                                className={`border px-2 py-2 text-[12px] font-mono leading-relaxed ${
                                  alert.blocking
                                    ? 'border-red-500/30 bg-red-950/12 text-red-200'
                                    : 'border-yellow-500/30 bg-yellow-950/12 text-yellow-200'
                                }`}
                              >
                                <div className="tracking-[0.16em]">
                                  {alert.code.replaceAll('_', ' ').toUpperCase()}
                                </div>
                                <div className="mt-1 text-[var(--text-secondary)]">{alert.detail}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="border border-[var(--border-primary)]/50 bg-black/20 px-3 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-[12px] font-mono tracking-[0.18em] text-[var(--text-muted)]">
                            NEXT ACTION
                          </div>
                          <span
                            className={`px-1.5 py-0.5 border text-[11px] font-mono tracking-widest ${dmRootUrgencyTone(
                              dmRootHealth.runbook?.urgency,
                            )}`}
                          >
                            {String(dmRootHealth.runbook?.urgency || 'none').toUpperCase()}
                          </span>
                        </div>
                        <div className="mt-2 text-[13px] font-mono text-[var(--text-secondary)]">
                          {(
                            dmRootHealth.runbook?.next_action_detail &&
                            'title' in dmRootHealth.runbook.next_action_detail &&
                            dmRootHealth.runbook.next_action_detail.title
                          ) ||
                            dmRootHealth.runbook?.next_action ||
                            'No action required.'}
                        </div>
                        <div className="mt-1 text-[12px] font-mono text-[var(--text-muted)] leading-relaxed">
                          {(
                            dmRootHealth.runbook?.next_action_detail &&
                            'summary' in dmRootHealth.runbook.next_action_detail &&
                            dmRootHealth.runbook.next_action_detail.summary
                          ) ||
                            dmRootHealth.monitoring?.status_line ||
                            'Current external assurance is within policy.'}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-3 border border-red-500/25 bg-red-950/12 px-3 py-3 text-sm font-mono text-red-200/90 leading-relaxed">
                      {dmRootHealthMsg || 'Could not load DM root health.'}
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
                          the hidden transport policy is active. Use Meshtastic Chat for the hardened path.
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
                      {legacyCompatibilityItems.length > 0 && (
                        <div className="border border-cyan-900/25 bg-black/20 px-3 py-2">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-[12px] font-mono tracking-[0.18em] text-cyan-300">
                              LEGACY SUNSET
                            </div>
                            <div className="text-[11px] font-mono text-[var(--text-muted)]">
                              {legacyCompatibilityAllBlocked
                                ? 'DESKTOP DEFAULT: BLOCKING'
                                : 'COMPATIBILITY STILL OPEN'}
                            </div>
                          </div>
                          <div className="mt-2 space-y-2">
                            {legacyCompatibilityItems.map((item: any) => (
                              <div key={item.key} className="space-y-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span
                                    className={`px-1.5 py-0.5 border ${
                                      item.blocked
                                        ? 'border-green-500/40 text-green-300 bg-green-950/20'
                                        : 'border-yellow-500/40 text-yellow-300 bg-yellow-950/15'
                                    }`}
                                  >
                                    {item.blocked ? 'BLOCKED' : 'ALLOWING'}
                                  </span>
                                  <span className="text-[var(--text-secondary)]">{item.label}</span>
                                  <span className="text-[var(--text-muted)]">
                                    seen {item.count}
                                    {item.blockedCount > 0 ? ` • blocked ${item.blockedCount}` : ''}
                                  </span>
                                </div>
                                <div className="text-[12px] leading-relaxed text-[var(--text-muted)]">
                                  {item.blocked ? 'remove after' : 'target'} {item.targetVersion} / {item.targetDate}
                                  {item.lastSeenAt > 0
                                    ? ` • last seen ${formatLegacyCompatibilitySeenAt(item.lastSeenAt)}`
                                    : ' • never observed'}
                                </div>
                                {item.recentTargets.length > 0 && (
                                  <div className="text-[12px] leading-relaxed text-yellow-200/80">
                                    recent {item.recentTargets.join(' • ')}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                          {!legacyCompatibilityActivity && (
                            <div className="mt-2 text-[12px] leading-relaxed text-green-300/80">
                              No live legacy traffic observed in this runtime. When this stays at
                              zero, the final hard cutoff is low risk.
                            </div>
                          )}
                        </div>
                      )}
                      <div className="border border-amber-900/25 bg-black/20 px-3 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-[12px] font-mono tracking-[0.18em] text-amber-300">
                            GATE COMPAT
                          </div>
                          <div className="text-[11px] font-mono text-[var(--text-muted)]">
                            required {gateCompatTelemetry.totalRequired} • used {gateCompatTelemetry.totalUsed}
                          </div>
                        </div>
                        <div className="mt-2 text-[12px] leading-relaxed text-[var(--text-muted)]">
                          {describeBrowserGateLocalRuntimeStatus(gateLocalRuntimeStatus)}
                        </div>
                        {gateCompatTopReasons.length > 0 ? (
                          <div className="mt-2 space-y-2">
                            {gateCompatTopReasons.map((item: any) => (
                              <div key={item.reason} className="space-y-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="text-[var(--text-secondary)]">{item.label}</span>
                                  <span className="text-[var(--text-muted)]">
                                    need {item.requiredCount}
                                    {item.usedCount > 0 ? ` • used ${item.usedCount}` : ''}
                                  </span>
                                </div>
                                <div className="text-[12px] leading-relaxed text-[var(--text-muted)]">
                                  {item.lastAt > 0
                                    ? `last seen ${formatGateCompatSeenAt(item.lastAt)}`
                                    : 'never observed'}
                                  {item.recentGates.length > 0
                                    ? ` • rooms ${item.recentGates.join(' • ')}`
                                    : ''}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="mt-2 text-[12px] leading-relaxed text-green-300/80">
                            No browser gate compat issues recorded for this profile yet.
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
                  </>
                )}

                {/* ── Time Machine ────────────────────────── */}
                <div className="mx-4 mt-4 mb-4 p-3 border border-amber-900/30 bg-amber-950/8">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm text-amber-300 font-mono tracking-[0.18em]">
                        TIME MACHINE
                      </div>
                      <div className="mt-1.5 text-[12px] text-[var(--text-secondary)] font-mono leading-relaxed">
                        Records hourly snapshots of all entity positions (flights, ships, satellites)
                        for historical playback via the timeline scrubber.
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={toggleTimeMachine}
                      disabled={tmSaving}
                      className={`px-4 py-1.5 text-[12px] font-mono tracking-[0.18em] border rounded-sm transition-colors whitespace-nowrap ${
                        tmEnabled
                          ? 'text-amber-300 border-amber-500/40 bg-amber-950/30 hover:bg-amber-950/50'
                          : 'text-[var(--text-muted)] border-slate-600/40 bg-slate-900/20 hover:bg-slate-900/40'
                      } disabled:opacity-40`}
                    >
                      {tmSaving ? '...' : tmEnabled ? 'ON' : 'OFF'}
                    </button>
                  </div>
                  <div className="mt-2 p-2 border border-amber-500/15 bg-black/20 text-[11px] font-mono text-amber-200/70 leading-relaxed">
                    <span className="text-amber-400">STORAGE:</span> ~5-8 MB/day &middot; ~200 MB/month (gzip compressed).
                    Snapshots are stored locally and never leave your machine.
                    {tmEnabled && (
                      <span className="text-amber-300"> Auto-snapshots are running.</span>
                    )}
                  </div>
                </div>

                {/* ── Browser Companion (desktop-only) ───── */}
                {companionAvailable && (companion || companionLoadFailed) && (
                  <div className="mx-4 mt-4 mb-4 p-3 border border-violet-900/30 bg-violet-950/8">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm text-violet-300 font-mono tracking-[0.18em]">
                          BROWSER COMPANION
                        </div>
                        <div className="mt-1.5 text-[12px] text-[var(--text-secondary)] font-mono leading-relaxed">
                          {companionLoadFailed
                            ? 'Could not load companion status from the native bridge.'
                            : <>
                                Open this app in a regular browser on localhost.
                                {companion?.enabled && companion.url && (
                                  <span className="text-violet-300"> Active at {companion.url}</span>
                                )}
                              </>
                          }
                        </div>
                      </div>
                      {companion && (
                        <div className="flex gap-2">
                          {companion.enabled && (
                            <button
                              type="button"
                              onClick={openCompanionBrowser}
                              disabled={companionBusy}
                              className="px-3 py-1.5 text-[12px] font-mono tracking-[0.18em] border text-violet-300 border-violet-500/40 bg-violet-950/30 hover:bg-violet-950/50 rounded-sm transition-colors whitespace-nowrap disabled:opacity-40"
                            >
                              {companionBusy ? '...' : 'OPEN'}
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={toggleCompanion}
                            disabled={companionBusy}
                            className={`px-4 py-1.5 text-[12px] font-mono tracking-[0.18em] border rounded-sm transition-colors whitespace-nowrap ${
                              companion.enabled
                                ? 'text-violet-300 border-violet-500/40 bg-violet-950/30 hover:bg-violet-950/50'
                                : 'text-[var(--text-muted)] border-slate-600/40 bg-slate-900/20 hover:bg-slate-900/40'
                            } disabled:opacity-40`}
                          >
                            {companionBusy ? '...' : companion.enabled ? 'ON' : 'OFF'}
                          </button>
                        </div>
                      )}
                    </div>
                    {companion?.warning && (
                      <div className="mt-2 p-2 border border-violet-500/15 bg-black/20 text-[11px] font-mono text-violet-200/70 leading-relaxed">
                        <span className="text-violet-400">REDUCED TRUST:</span>{' '}
                        {companion.warning}
                      </div>
                    )}
                    {companionLoadFailed && (
                      <div className="mt-2 p-2 border border-amber-500/20 bg-amber-950/15 text-[11px] font-mono text-amber-300/90 leading-relaxed">
                        Companion service unavailable. The native bridge did not respond. Try reopening Settings or restarting the app.
                      </div>
                    )}
                    {companionError && (
                      <div className="mt-2 p-2 border border-red-500/20 bg-red-950/15 text-[11px] font-mono text-red-300/90 leading-relaxed">
                        {companionError}
                      </div>
                    )}
                  </div>
                )}

              </div>
</>
  );
}
