'use client';

import React from 'react';
import { AnimatePresence, motion } from '@/lib/motion';

export function MeshTerminalView({ p }: { p: any }) {
  const {
    Activate,
    AnimatePresence,
    Backend,
    Bootstrap,
    Commons,
    Enter,
    Experimental,
    Gates,
    GripHorizontal,
    If,
    Infonet,
    Last,
    Minimize,
    Minus,
    No,
    Obfuscated,
    Participant,
    Public,
    Terminal,
    Turn,
    What,
    Wormhole,
    Yes,
    _18,
    _1px,
    _26px,
    absolute,
    absoluteStyle,
    accept,
    active,
    activeGateComposeId,
    agent,
    alignItems,
    all,
    allowed,
    already,
    amber,
    an,
    and,
    animate,
    auto,
    autoComplete,
    backdrop,
    backend,
    background,
    behind,
    between,
    bg,
    black,
    blink_1s_step,
    block,
    blur,
    bold,
    bootstrap,
    bootstrap_peer_count,
    bootstrapped,
    border,
    bottom,
    broadcast,
    build,
    busy,
    button,
    callsign,
    caret,
    catch,
    center,
    centered,
    chain,
    chipTone,
    circle_at_50,
    circle_at_top,
    clear,
    click,
    col,
    colors,
    cols,
    command,
    commons,
    comms,
    communicate,
    configured,
    confirmGateAccess,
    confirmPrivateLanePrompt,
    const,
    contents,
    current,
    cursor,
    cyan,
    damping,
    deck,
    decline,
    denyGateAccess,
    dest,
    detected,
    dismissPrivateLanePrompt,
    display,
    div,
    dmStep,
    does,
    dossiers,
    emerald,
    encrypted,
    encryption,
    end_infinite,
    enter,
    err,
    events,
    exist,
    exists,
    exit,
    experimental,
    fixed,
    flex,
    focus,
    font,
    for,
    formatNodeTime,
    fuchsia,
    full,
    gap,
    gateAccessPromptOpen,
    gateReplyTarget,
    gates,
    getSelection,
    gradient,
    grid,
    gt,
    handleKey,
    hasSovereignty,
    head_hash,
    hidden,
    hosting,
    hover,
    identity,
    if,
    ignore,
    image,
    in,
    inbox,
    infonetNodeStatus,
    infonetNodeStatusError,
    initial,
    inline,
    input,
    inputRef,
    inset,
    inset_0_0_0_1px_rgba,
    intel,
    into,
    is,
    isCollapsed,
    isOpen,
    it,
    items,
    justify,
    justifyContent,
    known_nodes,
    lane,
    last_peer_url,
    launch,
    leading,
    left,
    length,
    lg,
    linear,
    lines,
    live,
    map,
    markets,
    max,
    mb,
    md,
    mesh,
    message,
    min,
    minimized,
    mono,
    motion,
    move,
    msg,
    mt,
    mx,
    ne,
    next,
    next_sync_due_at,
    node,
    nodeBootstrapLabel,
    nodeId,
    nodeIdentity,
    nodeModeLabel,
    nodeSyncLabel,
    nodes,
    none,
    not,
    now,
    nw,
    obfuscated,
    observable,
    off,
    ok,
    on,
    onClose,
    onDragStart,
    onResizeStart,
    onSettingsClick,
    once,
    one,
    only,
    openPrivateLanePrompt,
    openSurface,
    operator,
    or,
    outline,
    output,
    over,
    overflow,
    panel,
    participant,
    peer,
    pointer,
    pointerEvents,
    policy,
    position,
    post,
    prediction,
    private,
    privateLaneLabel,
    privateLanePromptBusy,
    privateLanePromptMode,
    privateLanePromptOpen,
    privateLanePromptStatus,
    provisions,
    public,
    push,
    push_peer_count,
    px,
    py,
    radial,
    read,
    relative,
    renderStyledLine,
    renderSurfacePanel,
    reply,
    require,
    resize,
    return,
    reused,
    rgba,
    right,
    rose,
    rounded,
    routing,
    runQuickCommand,
    sb_a3f2c891,
    scale,
    scrollRef,
    scrollbar,
    se,
    security,
    seed,
    select,
    semibold,
    sendStep,
    sends,
    separate,
    sessionStorage,
    setCentered,
    setInput,
    setItem,
    setMinimized,
    shadow,
    shortNodeHash,
    shrink,
    size,
    sizeStyle,
    slate,
    slice,
    sm,
    sovereigntyPending,
    space,
    span,
    spellCheck,
    spring,
    stay,
    stays,
    stiffness,
    straight,
    stronger,
    styled,
    summarizeNodePeer,
    sw,
    sync,
    sync_peer_count,
    sync_runtime,
    syncs,
    takes,
    target,
    terminal,
    terminalWriteLockReason,
    testnet,
    text,
    the,
    then,
    this,
    through,
    to,
    tone,
    top,
    total_events,
    tracking,
    transition,
    translate,
    transparent,
    transparent_18,
    transparent_1px,
    transparent_28,
    try,
    turns,
    typeof,
    under,
    use,
    void,
    white,
    windowRef,
    wipe,
    wormhole,
    wormholeReadyState,
    wormholeSecureRequired,
    wrap,
    xl,
    yet,
    you,
    your,
    zIndex
  } = p as any;

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {privateLanePromptOpen && (
            <div className="fixed inset-0 z-[310] bg-black/60 backdrop-blur-[2px]">
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4">
                <div className="pointer-events-auto w-full max-w-lg border border-cyan-500/25 bg-black/95 p-5 font-mono shadow-[0_0_42px_rgba(34,211,238,0.12)]">
                  <div className="text-sm tracking-[0.28em] text-cyan-300">
                    {privateLanePromptMode === 'enter' ? 'ENTER WORMHOLE' : 'ACTIVATE WORMHOLE'}
                  </div>
                  <div className="mt-3 text-[13px] leading-7 text-slate-200">
                    {privateLanePromptMode === 'enter'
                      ? 'Obfuscated lane detected. Enter Wormhole now to sync into the Infonet Commons and communicate through gates.'
                      : 'No obfuscated lane is active yet. Activate Wormhole now and enter the Infonet Commons?'}
                  </div>
                  <div className="mt-4 border border-cyan-500/14 bg-cyan-950/10 px-4 py-3 text-sm leading-6 text-slate-300">
                    <div className="text-cyan-300">What this does</div>
                    <div className="mt-2">Wormhole turns on the obfuscated lane for gates and the obfuscated commons.</div>
                    <div>If a Wormhole identity already exists, it is reused. If one does not exist yet, it is bootstrapped once.</div>
                    <div>Participant-node sync and public chain hosting stay on the backend node lane.</div>
                    <div>Public mesh stays public and separate.</div>
                  </div>
                  {privateLanePromptStatus && (
                    <div
                      className={`mt-4 border px-3 py-2 text-sm leading-6 ${
                        privateLanePromptStatus.type === 'err'
                          ? 'border-rose-500/25 bg-rose-500/10 text-rose-200'
                          : privateLanePromptStatus.type === 'ok'
                            ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
                            : 'border-cyan-500/18 bg-cyan-500/8 text-cyan-200'
                      }`}
                    >
                      {privateLanePromptStatus.text}
                    </div>
                  )}
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={confirmPrivateLanePrompt}
                      disabled={privateLanePromptBusy}
                      className="border border-cyan-500/25 bg-cyan-500/10 px-4 py-2 text-sm tracking-[0.22em] text-cyan-100 transition-colors hover:bg-cyan-500/16 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {privateLanePromptBusy
                        ? 'ENTERING...'
                        : privateLanePromptMode === 'enter'
                          ? 'YES, ENTER'
                          : 'YES, GENERATE'}
                    </button>
                    <button
                      type="button"
                      onClick={dismissPrivateLanePrompt}
                      disabled={privateLanePromptBusy}
                      className="border border-slate-500/20 bg-white/5 px-4 py-2 text-sm tracking-[0.22em] text-slate-300 transition-colors hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      STAY PUBLIC
                    </button>
                    {onSettingsClick && (
                      <button
                        type="button"
                        onClick={() => {
                          if (typeof window !== 'undefined') {
                            try {
                              sessionStorage.setItem(SETTINGS_FOCUS_KEY, 'wormhole-gates');
                              sessionStorage.setItem(WORMHOLE_RETURN_KEY, 'gates');
                            } catch {
                              /* ignore */
                            }
                          }
                          onSettingsClick();
                        }}
                        disabled={privateLanePromptBusy}
                        className="border border-slate-500/20 bg-white/5 px-4 py-2 text-sm tracking-[0.22em] text-slate-400 transition-colors hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        ADVANCED
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
          {gateAccessPromptOpen && (
            <div className="fixed inset-0 z-[309] bg-black/55 backdrop-blur-[2px]">
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4">
                <div className="pointer-events-auto w-full max-w-md border border-fuchsia-500/25 bg-black/95 p-5 font-mono shadow-[0_0_40px_rgba(217,70,239,0.12)]">
                  <div className="text-sm tracking-[0.28em] text-fuchsia-300">
                    ENTER INFONET COMMONS
                  </div>
                  <div className="mt-3 text-[12px] leading-6 text-slate-300">
                    Gates live behind Wormhole in this build. Enter now?
                  </div>
                  <div className="mt-3 text-sm leading-5 text-slate-500">
                    {wormholeSecureRequired
                      ? wormholeReadyState
                        ? 'Yes takes you straight into the gates.'
                        : 'Yes turns on Wormhole and provisions an obfuscated lane identity, then sends you into gates.'
                      : 'Yes turns on Wormhole and provisions an obfuscated lane identity, then sends you into gates.'}
                  </div>
                  <div className="mt-4 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={confirmGateAccess}
                      className="border border-fuchsia-500/25 bg-fuchsia-500/10 px-4 py-2 text-sm tracking-[0.22em] text-fuchsia-200 transition-colors hover:bg-fuchsia-500/16"
                    >
                      YES
                    </button>
                    <button
                      type="button"
                      onClick={denyGateAccess}
                      className="border border-slate-500/20 bg-white/5 px-4 py-2 text-sm tracking-[0.22em] text-slate-300 transition-colors hover:bg-white/8"
                    >
                      NO
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
          {minimized && (
            <motion.button
              type="button"
              initial={{ opacity: 0, y: -24 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -24 }}
              onClick={() => {
                setMinimized(false);
                setCentered(true);
                setTimeout(() => inputRef.current?.focus(), 80);
              }}
              className="fixed top-0 left-1/2 -translate-x-1/2 z-[305] flex items-center gap-2 rounded-b border border-cyan-800/30 border-t-0 bg-cyan-950/40 px-4 py-1.5 text-cyan-700 transition-colors hover:bg-cyan-950/60 hover:text-cyan-300 hover:border-cyan-500/40"
            >
              <Terminal size={11} className="text-cyan-400" />
              <span className="text-[11px] font-mono font-bold tracking-[0.22em]">
                TERMINAL
              </span>
            </motion.button>
          )}

          {!minimized && (
            <div
              style={centered ? {
                position: 'fixed',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                zIndex: 300,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                pointerEvents: 'none',
              } : { display: 'contents' }}
            >
              <motion.div
                ref={windowRef}
                initial={{ opacity: 0, scale: 0.95, y: 16 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 16 }}
                transition={{ type: 'spring', damping: 28, stiffness: 350 }}
                style={centered ? { ...sizeStyle, pointerEvents: 'auto' } : absoluteStyle}
                className={centered
                  ? "z-[300] max-w-[95vw] max-h-[90vh] overflow-hidden border border-cyan-500/18 bg-black/96 text-slate-100 shadow-[0_30px_80px_rgba(0,0,0,0.78),0_0_0_1px_rgba(34,211,238,0.1),0_0_42px_rgba(34,211,238,0.05)] backdrop-blur-sm"
                  : "fixed z-[300] max-w-[95vw] max-h-[90vh] overflow-hidden border border-cyan-500/18 bg-black/96 text-slate-100 shadow-[0_30px_80px_rgba(0,0,0,0.78),0_0_0_1px_rgba(34,211,238,0.1),0_0_42px_rgba(34,211,238,0.05)] backdrop-blur-sm"
                }
              >
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.05),transparent_28%),radial-gradient(circle_at_50%_18%,rgba(217,70,239,0.05),transparent_18%),linear-gradient(180deg,rgba(2,4,8,0.995),rgba(0,0,0,0.995))]" />
              <div className="pointer-events-none absolute inset-0 opacity-[0.06] [background-image:linear-gradient(rgba(34,211,238,0.14)_1px,transparent_1px),linear-gradient(90deg,rgba(34,211,238,0.08)_1px,transparent_1px)] [background-size:100%_26px,26px_100%]" />

              <div
                onMouseDown={(e) => onResizeStart(e, 'n')}
                className="absolute top-0 left-2 right-2 h-1.5 cursor-n-resize z-[310]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 's')}
                className="absolute bottom-0 left-2 right-2 h-1.5 cursor-s-resize z-[310]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'w')}
                className="absolute left-0 top-2 bottom-2 w-1.5 cursor-w-resize z-[310]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'e')}
                className="absolute right-0 top-2 bottom-2 w-1.5 cursor-e-resize z-[310]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'nw')}
                className="absolute top-0 left-0 w-3 h-3 cursor-nw-resize z-[311]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'ne')}
                className="absolute top-0 right-0 w-3 h-3 cursor-ne-resize z-[311]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'sw')}
                className="absolute bottom-0 left-0 w-3 h-3 cursor-sw-resize z-[311]"
              />
              <div
                onMouseDown={(e) => onResizeStart(e, 'se')}
                className="absolute bottom-0 right-0 w-3 h-3 cursor-se-resize z-[311]"
              />

              <div className="relative flex h-full flex-col">
                <div
                  onMouseDown={onDragStart}
                  className="flex h-11 min-h-[44px] items-center justify-between border-b border-cyan-500/12 bg-[linear-gradient(90deg,rgba(4,8,12,0.98),rgba(6,10,14,0.96),rgba(10,4,12,0.94))] px-4 select-none cursor-move"
                >
                  <div className="flex items-center gap-2">
                    <GripHorizontal className="h-3.5 w-3.5 text-cyan-500/55" />
                    <div className="relative h-7 w-7 rounded-full border border-cyan-400/30 bg-cyan-500/8">
                      <div className="absolute inset-1 rounded-full border border-cyan-400/40" />
                      <div className="absolute inset-[9px] rounded-full bg-cyan-300 shadow-[0_0_14px_rgba(34,211,238,0.9)]" />
                      <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-cyan-400/20" />
                      <div className="absolute top-1/2 left-0 h-px w-full -translate-y-1/2 bg-cyan-400/20" />
                    </div>
                  </div>

                  <div className="text-center">
                    <div className="text-[12px] tracking-[0.32em] text-slate-500">
                      type clear to wipe output · gates require wormhole · mesh stays public
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        openSurface('inbox');
                        runQuickCommand('inbox');
                      }}
                      className="border border-cyan-500/18 bg-cyan-500/8 px-2.5 py-1 text-[12px] tracking-[0.18em] text-cyan-300 transition-colors hover:bg-cyan-500/14"
                    >
                      PRIVATE DM INBOX
                    </button>
                    {nodeIdentity && hasSovereignty() && (
                      <span className="border border-cyan-500/20 bg-cyan-500/10 px-2 py-1 text-[12px] tracking-[0.18em] text-cyan-300">
                        {nodeIdentity.nodeId.slice(0, 14)}
                      </span>
                    )}
                    {terminalWriteLockReason && (
                      <span className="border border-amber-400/25 bg-amber-400/10 px-2 py-1 text-[12px] tracking-[0.18em] text-amber-200">
                        READ ONLY
                      </span>
                    )}
                    {busy && (
                      <span className="border border-fuchsia-500/25 bg-fuchsia-500/10 px-2 py-1 text-[12px] tracking-[0.18em] text-fuchsia-200">
                        RUNNING
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => setMinimized(true)}
                      className="p-1.5 text-slate-500 transition-colors hover:bg-white/5 hover:text-amber-200"
                      title="Minimize terminal"
                    >
                      <Minus className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={onClose}
                      className="p-1.5 text-slate-500 transition-colors hover:bg-white/5 hover:text-rose-300"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                <div
                  ref={scrollRef}
                  className="relative flex-1 overflow-y-auto styled-scrollbar select-text"
                  onClick={() => {
                    const sel = window.getSelection();
                    if (!sel || sel.isCollapsed) inputRef.current?.focus();
                  }}
                >
                  <div className="mx-auto w-full max-w-[1180px] px-6 py-6">
                    <div className="mb-6 border border-cyan-500/14 bg-black/72 px-6 py-5 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.05)]">
                      <div className="flex flex-col items-center text-center">
                        <div className="relative mb-4 h-16 w-16 rounded-full border border-cyan-400/30 bg-cyan-500/8">
                          <div className="absolute inset-2 rounded-full border border-cyan-400/35" />
                          <div className="absolute inset-[18px] rounded-full bg-cyan-300 shadow-[0_0_20px_rgba(34,211,238,0.85)]" />
                          <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-cyan-400/20" />
                          <div className="absolute top-1/2 left-0 h-px w-full -translate-y-1/2 bg-cyan-400/20" />
                        </div>
                        <div className="text-sm tracking-[0.38em] text-cyan-300">INFONET</div>
                        <div className="mt-2 text-[30px] font-semibold leading-none tracking-[0.32em] text-cyan-100">
                          THE INFONET COMMONS
                        </div>
                        <div className="mt-2 text-sm tracking-[0.28em] text-fuchsia-300">
                          OPSINT DECK · COMMONS NODE
                        </div>
                        <div className="mt-4 max-w-[760px] text-[11px] leading-6 text-slate-400">
                          Experimental operator deck for encrypted gates, mesh comms, dossiers, prediction markets, and live intel routing.
                        </div>
                      </div>

                      <div className="mt-5 grid w-full gap-2 text-[13px] font-mono md:grid-cols-4">
                        <div className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-2 text-cyan-300">
                          INFONET · experimental encryption
                        </div>
                        <div className="border border-emerald-500/20 bg-emerald-500/8 px-3 py-2 text-emerald-300">
                          MESH · public / observable
                        </div>
                        <div className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-3 py-2 text-fuchsia-300">
                          GATES · experimental encryption
                        </div>
                        <div className="border border-amber-400/20 bg-amber-400/8 px-3 py-2 text-amber-200">
                          COMMANDS · type or click to launch
                        </div>
                      </div>

                      <div className="mt-5 grid gap-3 xl:grid-cols-[1.45fr_1fr]">
                        <div className="border border-cyan-500/16 bg-black/40 px-4 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-[13px] tracking-[0.24em] text-cyan-300">
                                PARTICIPANT NODE
                              </div>
                              <div className="mt-1 text-sm leading-5 text-slate-400">
                                Backend bootstrap is configured; the participant node syncs the testnet seed over the private seed lane.
                              </div>
                            </div>
                            <div className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-1.5 text-[13px] tracking-[0.22em] text-cyan-200">
                              {nodeModeLabel}
                            </div>
                          </div>

                          <div className="mt-3 grid gap-2 md:grid-cols-3 text-[13px] font-mono">
                            <div className="border border-emerald-500/20 bg-emerald-500/8 px-3 py-2 text-emerald-200">
                              <div className="text-[12px] tracking-[0.2em] text-emerald-300">CHAIN</div>
                              <div className="mt-1 text-[13px] text-emerald-100">
                                {shortNodeHash(infonetNodeStatus?.head_hash, 18)}
                              </div>
                              <div className="mt-1 text-[12px] text-emerald-200/70">
                                {Number(infonetNodeStatus?.total_events || 0)} events • {Number(infonetNodeStatus?.known_nodes || 0)} nodes
                              </div>
                            </div>
                            <div className="border border-cyan-500/20 bg-cyan-500/8 px-3 py-2 text-cyan-200">
                              <div className="text-[12px] tracking-[0.2em] text-cyan-300">PEERS</div>
                              <div className="mt-1 text-[13px] text-cyan-100">
                                {Number(infonetNodeStatus?.bootstrap?.sync_peer_count || 0)} sync
                              </div>
                              <div className="mt-1 text-[12px] text-cyan-200/70">
                                {Number(infonetNodeStatus?.bootstrap?.push_peer_count || 0)} push • {Number(infonetNodeStatus?.bootstrap?.bootstrap_peer_count || 0)} bootstrap
                              </div>
                            </div>
                            <div className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-3 py-2 text-fuchsia-200">
                              <div className="text-[12px] tracking-[0.2em] text-fuchsia-300">SYNC LOOP</div>
                              <div className="mt-1 text-[13px] text-fuchsia-100">{nodeSyncLabel}</div>
                              <div className="mt-1 text-[12px] text-fuchsia-200/70">
                                next {formatNodeTime(infonetNodeStatus?.sync_runtime?.next_sync_due_at)}
                              </div>
                            </div>
                          </div>

                          <div className="mt-3 border border-cyan-500/12 bg-cyan-950/8 px-3 py-2 text-[13px] font-mono leading-[1.65] text-slate-300">
                            <div className="flex items-center justify-between gap-3">
                              <span className="text-cyan-300">Bootstrap</span>
                              <span className="text-right text-slate-400">{nodeBootstrapLabel}</span>
                            </div>
                            <div className="mt-1 flex items-center justify-between gap-3">
                              <span className="text-cyan-300">Last peer</span>
                              <span className="text-right text-slate-400">
                                {summarizeNodePeer(infonetNodeStatus?.sync_runtime?.last_peer_url)}
                              </span>
                            </div>
                            {infonetNodeStatusError && (
                              <div className="mt-2 text-amber-200/80">{infonetNodeStatusError}</div>
                            )}
                          </div>
                        </div>

                        <div className="border border-amber-400/16 bg-amber-400/6 px-4 py-3 text-sm leading-6 text-amber-100/85">
                          <div className="text-[13px] font-mono tracking-[0.24em] text-amber-300">
                            PRIVATE SEED LANE
                          </div>
                        <div className="mt-2">
                          Participant-node bootstrap, sync, and public chain hosting use the backend private seed lane.
                        </div>
                        <div className="mt-2 text-amber-200/75">
                          Turn Wormhole on for gates, obfuscated inbox, and the stronger obfuscated lane only.
                        </div>
                        <div className="mt-3 border border-amber-400/16 bg-black/20 px-3 py-2 text-[13px] font-mono leading-[1.65] text-amber-100/80">
                          obfuscated lane now: {privateLaneLabel}
                        </div>
                        <button
                          type="button"
                          onClick={() => void openPrivateLanePrompt()}
                          disabled={busy || privateLanePromptBusy}
                          className="mt-3 inline-flex items-center border border-amber-300/20 bg-amber-400/10 px-3 py-2 text-[13px] font-mono tracking-[0.22em] text-amber-100 transition-colors hover:bg-amber-400/16 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {wormholeSecureRequired && wormholeReadyState
                            ? 'ENTER WORMHOLE'
                            : 'GENERATE PRIVATE KEY'}
                        </button>
                      </div>
                      </div>

                      <div className="mt-5 flex flex-wrap justify-center gap-2">
                        {QUICK_LAUNCHES.map((item) => (
                          <button
                            key={item.label}
                            type="button"
                            onClick={() => openSurface(item.panel)}
                            disabled={busy}
                            className={`px-3 py-2 text-sm font-mono tracking-[0.26em] transition-all disabled:cursor-not-allowed disabled:opacity-50 ${chipTone(item.tone)}`}
                          >
                            {item.label}
                          </button>
                        ))}
                      </div>

                      <div className="mt-5">
                        {renderSurfacePanel()}
                      </div>
                    </div>

                    <div className="space-y-1">
                      {lines.map((line, i) => renderStyledLine(line, i))}
                    </div>
                  </div>
                </div>

                <div className="border-t border-cyan-500/15 bg-[linear-gradient(180deg,rgba(7,11,15,0.98),rgba(5,8,12,0.98))] px-4 py-3">
                  <div className="mb-2 flex items-center justify-between text-[13px] font-mono tracking-[0.22em]">
                    <div className="flex items-center gap-3">
                      <span className="text-cyan-300">COMMAND LINE</span>
                      <span className="text-emerald-300">MESH / RADIO</span>
                      <span className="text-fuchsia-300">GATES / COMMONS</span>
                      <span className="text-amber-200">OPS / DOSSIER</span>
                      {activeGateComposeId && (
                        <span className="border border-fuchsia-500/20 bg-fuchsia-500/8 px-2 py-1 text-[12px] tracking-[0.16em] text-fuchsia-200">
                          POSTING TO g/{activeGateComposeId}
                        </span>
                      )}
                      {gateReplyTarget && (
                        <span className="border border-amber-400/20 bg-amber-400/8 px-2 py-1 text-[12px] tracking-[0.16em] text-amber-200">
                          REPLY @{gateReplyTarget}
                        </span>
                      )}
                    </div>
                    <span className="text-slate-500">
                      {activeGateComposeId
                        ? 'TYPE TO POST · / FOR COMMANDS · CLEAR KEEPS YOUR GATE OPEN'
                        : 'ENTER TO EXECUTE · TYPE CLEAR TO WIPE OUTPUT'}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 border border-cyan-500/20 bg-black/25 px-3 py-3 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.04)]">
                    <span className="shrink-0 text-[12px] text-cyan-300 select-none font-mono">
                      &gt;
                    </span>
                    <div className="flex-1 relative font-mono text-[12px]">
                      <input
                        ref={inputRef}
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKey}
                        disabled={busy}
                        className="w-full border-none bg-transparent font-mono text-[12px] text-cyan-100 outline-none caret-transparent placeholder:text-cyan-900/80"
                        placeholder={
                          busy
                            ? ''
                            : sovereigntyPending
                              ? 'accept or decline...'
                              : sendStep === 'dest'
                                ? "callsign or 'broadcast'..."
                                : sendStep === 'msg'
                                  ? 'type your message...'
                                : dmStep === 'dest'
                                    ? 'agent ID (e.g. !sb_a3f2c891)...'
                                : dmStep === 'msg'
                                      ? 'type your private message...'
                                      : terminalWriteLockReason
                                        ? 'read-only under Wormhole security policy...'
                                        : activeGateComposeId
                                          ? `post to g/${activeGateComposeId}${gateReplyTarget ? ` reply @${gateReplyTarget}` : ''}...`
                                          : 'enter command...'
                        }
                        spellCheck={false}
                        autoComplete="off"
                      />
                      {!busy && (
                        <span
                          className="absolute top-0 pointer-events-none h-full flex items-center"
                          style={{ left: `${input.length * 7.2}px` }}
                        >
                          <span className="inline-block h-[16px] w-[7px] bg-cyan-300 shadow-[0_0_10px_rgba(34,211,238,0.8)] animate-[blink_1s_step-end_infinite]" />
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
            </div>
          )}
        </>
      )}
    </AnimatePresence>
  );
}
  );
}
