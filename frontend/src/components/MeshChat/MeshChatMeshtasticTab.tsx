'use client';
import React from 'react';
import { MSG_COLORS } from './types';

export function MeshChatMeshtasticTab({ p }: { p: any }) {
  const {
    activeChannels,
    activePublicMeshAddress,
    activeTab,
    address,
    addressed,
    after,
    amber,
    and,
    appear,
    are,
    auto,
    below,
    between,
    bg,
    black,
    blank,
    block,
    border,
    bridge,
    broadcast,
    broker,
    canUsePublicMeshInput,
    center,
    channel,
    checkbox,
    clear,
    colors,
    comma,
    connect,
    current,
    cursor,
    cyan,
    degraded,
    depend,
    direct,
    disables,
    displayPublicMeshSender,
    enabled,
    extra_roots,
    fade,
    filteredMeshMessages,
    flex,
    focus,
    font,
    from,
    full,
    gap,
    green,
    grid,
    handleMeshDirectTargetSubmit,
    handleSenderClick,
    has,
    has_password,
    has_psk,
    hearing,
    hover,
    identity,
    inbox,
    include_default_roots,
    inputRef,
    is,
    it,
    items,
    justify,
    keep,
    lane,
    last_error,
    leading,
    leave,
    length,
    load,
    map,
    mb,
    mesh,
    meshAddressDraft,
    meshChannel,
    meshChannels,
    meshDirectTarget,
    meshInboxMessages,
    meshMqttBusy,
    meshMqttConnected,
    meshMqttConnectionLabel,
    meshMqttEnabled,
    meshMqttForm,
    meshMqttRunning,
    meshMqttSettings,
    meshMqttStatusText,
    meshRegion,
    meshRoots,
    meshView,
    meshtastic,
    message,
    messages,
    messagesEndRef,
    mono,
    mt,
    muted,
    node,
    none,
    number,
    off,
    on,
    opacity,
    optional,
    or,
    outline,
    overflow,
    parse,
    password,
    pointer,
    port,
    press,
    preventDefault,
    primary,
    psk,
    pt,
    publishes,
    px,
    py,
    red,
    refreshMeshMqttSettings,
    root,
    runtime,
    saveMeshMqttSettings,
    saved,
    sb,
    scroll,
    scrollbar,
    secondary,
    see,
    send,
    separate,
    separated,
    setMeshAddressDraft,
    setMeshChannel,
    setMeshDirectTarget,
    setMeshMqttForm,
    setMeshRegion,
    setMeshView,
    setTimeout,
    settings,
    shrink,
    space,
    start,
    starting,
    styled,
    target,
    text,
    the,
    timeAgo,
    timestamp,
    to,
    toUpperCase,
    tracking,
    traffic,
    transition,
    underline,
    username,
    uses,
    uses_default_credentials,
    whitespace,
    wider,
    words,
    wrap,
    yet
  } = p;
  return (
<>
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
                      {meshRoots.map((r: any) => (
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
                      {meshChannels.map((ch: any) => (
                        <option key={ch} value={ch}>
                          {activeChannels.has(ch) ? `* ${ch}` : `  ${ch}`}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center gap-1 px-3 py-1 border-b border-[var(--border-primary)]/20 shrink-0 bg-green-950/10">
                    <div className="flex items-center gap-1 min-w-0 flex-wrap">
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
                      <button
                        onClick={() => setMeshView('settings')}
                        className={`px-2 py-0.5 text-[11px] font-mono tracking-wider border transition-colors ${
                          meshView === 'settings'
                            ? 'border-cyan-500/40 text-cyan-300 bg-cyan-950/20'
                            : 'border-[var(--border-primary)]/40 text-[var(--text-muted)] hover:text-cyan-300'
                        }`}
                      >
                        SETTINGS
                      </button>
                      <button
                        onClick={() => {
                          setMeshAddressDraft(meshDirectTarget || '');
                          setMeshView('message');
                        }}
                        className={`px-2 py-0.5 text-[11px] font-mono tracking-wider border transition-colors ${
                          meshView === 'message'
                            ? 'border-green-500/40 text-green-200 bg-green-950/25'
                            : 'border-[var(--border-primary)]/40 text-[var(--text-muted)] hover:text-green-300'
                        }`}
                      >
                        MESSAGE
                      </button>
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto styled-scrollbar sb-scroll-fade px-3 py-1.5 border-l-2 border-cyan-800/25">
                    {meshView === 'message' && (
                      <div className="space-y-2 py-1 text-[11px] font-mono">
                        <div className="border border-green-700/35 bg-green-950/10 p-2">
                          <div className="text-green-300 tracking-[0.18em]">DIRECT MESHTASTIC MESSAGE</div>
                          <div className="mt-1 text-[10px] text-[var(--text-muted)] leading-[1.5]">
                            Enter a public Meshtastic node address. Direct MQTT publishes are public/degraded and depend on the target mesh hearing the broker bridge.
                          </div>
                        </div>
                        <label className="block space-y-1">
                          <span className="text-[var(--text-muted)]">NODE ADDRESS</span>
                          <input
                            value={meshAddressDraft}
                            onChange={(e) => setMeshAddressDraft(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                handleMeshDirectTargetSubmit();
                              }
                            }}
                            placeholder="!1ee21986"
                            className="w-full border border-[var(--border-primary)] bg-black/30 px-2 py-1 text-green-200 outline-none placeholder:text-[var(--text-muted)] focus:border-green-500/50"
                          />
                        </label>
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            onClick={handleMeshDirectTargetSubmit}
                            className="border border-green-600/45 bg-green-950/20 px-2 py-1.5 text-green-300 hover:bg-green-950/35"
                          >
                            USE ADDRESS
                          </button>
                          <button
                            onClick={() => {
                              setMeshDirectTarget('');
                              setMeshAddressDraft('');
                              setMeshView('channel');
                              window.setTimeout(() => inputRef.current?.focus(), 0);
                            }}
                            className="border border-cyan-700/40 bg-cyan-950/15 px-2 py-1.5 text-cyan-300 hover:bg-cyan-950/25"
                          >
                            BROADCAST
                          </button>
                        </div>
                        {meshDirectTarget && (
                          <div className="border border-amber-600/30 bg-amber-950/10 p-2 text-amber-200/85 leading-[1.5]">
                            Active direct target: {meshDirectTarget.toUpperCase()}. Type in the input below and press send, or clear it to return to channel broadcast.
                          </div>
                        )}
                      </div>
                    )}
                    {meshView === 'settings' && (
                      <div className="space-y-2 py-1 text-[11px] font-mono">
                        <div className="border border-cyan-800/35 bg-cyan-950/10 p-2">
                          <div className="flex items-center justify-between gap-2">
                            <div>
                              <div className="text-cyan-300 tracking-[0.18em]">MESHTASTIC MQTT</div>
                              <div className="mt-1 text-[10px] text-[var(--text-muted)] leading-[1.5]">
                                Meshtastic MQTT is separate from Wormhole. Turning MQTT on disables the private Wormhole lane for Meshtastic Chat.
                              </div>
                            </div>
                            <span
                              className={`shrink-0 border px-2 py-1 text-[10px] tracking-[0.16em] ${
                                meshMqttConnected
                                  ? 'border-green-500/40 text-green-300'
                                  : meshMqttEnabled
                                    ? 'border-amber-500/40 text-amber-300'
                                    : 'border-red-500/35 text-red-300'
                              }`}
                            >
                              {meshMqttConnectionLabel}
                            </span>
                          </div>
                          {meshMqttSettings?.runtime?.last_error && (
                            <div className="mt-2 text-red-300/80">
                              LAST ERROR: {meshMqttSettings.runtime.last_error}
                            </div>
                          )}
                          {meshMqttRunning && !meshMqttConnected && !meshMqttSettings?.runtime?.last_error && (
                            <div className="mt-2 text-amber-300/80">
                              MQTT bridge is starting. Live messages appear after broker connect.
                            </div>
                          )}
                        </div>

                        <div className="grid grid-cols-[1fr_70px] gap-2">
                          <label className="space-y-1">
                            <span className="text-[var(--text-muted)]">BROKER</span>
                            <input
                              value={meshMqttForm.broker}
                              onChange={(e) => setMeshMqttForm((prev: any) => ({ ...prev, broker: e.target.value }))}
                              className="w-full border border-[var(--border-primary)] bg-black/30 px-2 py-1 text-cyan-200 outline-none focus:border-cyan-500/50"
                            />
                          </label>
                          <label className="space-y-1">
                            <span className="text-[var(--text-muted)]">PORT</span>
                            <input
                              value={meshMqttForm.port}
                              onChange={(e) => setMeshMqttForm((prev: any) => ({ ...prev, port: e.target.value }))}
                              className="w-full border border-[var(--border-primary)] bg-black/30 px-2 py-1 text-cyan-200 outline-none focus:border-cyan-500/50"
                            />
                          </label>
                        </div>

                        <label className="block space-y-1">
                          <span className="text-[var(--text-muted)]">BROKER LOGIN (optional)</span>
                          <input
                            value={meshMqttForm.username}
                            onChange={(e) => setMeshMqttForm((prev: any) => ({ ...prev, username: e.target.value }))}
                            placeholder="blank uses public Meshtastic default"
                            className="w-full border border-[var(--border-primary)] bg-black/30 px-2 py-1 text-cyan-200 outline-none focus:border-cyan-500/50"
                          />
                        </label>

                        <label className="block space-y-1">
                          <span className="text-[var(--text-muted)]">
                            BROKER PASSWORD {meshMqttSettings?.uses_default_credentials ? '(public default)' : meshMqttSettings?.has_password ? '(saved)' : ''}
                          </span>
                          <input
                            type="password"
                            value={meshMqttForm.password}
                            onChange={(e) => setMeshMqttForm((prev: any) => ({ ...prev, password: e.target.value }))}
                            placeholder={
                              meshMqttSettings?.uses_default_credentials
                                ? 'blank uses public Meshtastic default'
                                : meshMqttSettings?.has_password
                                  ? 'leave blank to keep saved password'
                                  : 'blank uses public Meshtastic default'
                            }
                            className="w-full border border-[var(--border-primary)] bg-black/30 px-2 py-1 text-cyan-200 outline-none placeholder:text-[var(--text-muted)] focus:border-cyan-500/50"
                          />
                        </label>

                        <label className="block space-y-1">
                          <span className="text-[var(--text-muted)]">
                            CHANNEL PSK HEX {meshMqttSettings?.has_psk ? '(saved)' : '(default LongFast if blank)'}
                          </span>
                          <input
                            type="password"
                            value={meshMqttForm.psk}
                            onChange={(e) => setMeshMqttForm((prev: any) => ({ ...prev, psk: e.target.value }))}
                            placeholder="blank uses default LongFast key"
                            className="w-full border border-[var(--border-primary)] bg-black/30 px-2 py-1 text-cyan-200 outline-none placeholder:text-[var(--text-muted)] focus:border-cyan-500/50"
                          />
                        </label>

                        <label className="flex items-center gap-2 border border-[var(--border-primary)]/40 bg-black/20 px-2 py-1 text-cyan-200">
                          <input
                            type="checkbox"
                            checked={meshMqttForm.include_default_roots}
                            onChange={(e) =>
                              setMeshMqttForm((prev: any) => ({ ...prev, include_default_roots: e.target.checked }))
                            }
                          />
                          DEFAULT PUBLIC ROOTS
                        </label>

                        <label className="block space-y-1">
                          <span className="text-[var(--text-muted)]">EXTRA ROOTS</span>
                          <input
                            value={meshMqttForm.extra_roots}
                            onChange={(e) => setMeshMqttForm((prev: any) => ({ ...prev, extra_roots: e.target.value }))}
                            placeholder="comma separated, optional"
                            className="w-full border border-[var(--border-primary)] bg-black/30 px-2 py-1 text-cyan-200 outline-none placeholder:text-[var(--text-muted)] focus:border-cyan-500/50"
                          />
                        </label>

                        <div className="grid grid-cols-3 gap-2 pt-1">
                          <button
                            onClick={() => void saveMeshMqttSettings({ enabled: true })}
                            disabled={meshMqttBusy}
                            className="border border-green-600/40 bg-green-950/20 px-2 py-1.5 text-green-300 hover:bg-green-950/35 disabled:opacity-50"
                          >
                            ENABLE
                          </button>
                          <button
                            onClick={() => void saveMeshMqttSettings({ enabled: false })}
                            disabled={meshMqttBusy}
                            className="border border-red-600/35 bg-red-950/15 px-2 py-1.5 text-red-300 hover:bg-red-950/25 disabled:opacity-50"
                          >
                            DISABLE
                          </button>
                          <button
                            onClick={() => void refreshMeshMqttSettings()}
                            disabled={meshMqttBusy}
                            className="border border-cyan-700/40 bg-cyan-950/15 px-2 py-1.5 text-cyan-300 hover:bg-cyan-950/25 disabled:opacity-50"
                          >
                            REFRESH
                          </button>
                        </div>
                        {meshMqttStatusText && (
                          <div className="text-[10px] text-cyan-200/80 leading-[1.5]">{meshMqttStatusText}</div>
                        )}
                      </div>
                    )}
                    {!canUsePublicMeshInput && meshView !== 'settings' && (
                      <div className="text-[12px] font-mono text-green-300/70 text-center py-4 leading-[1.65]">
                        Meshtastic Chat is off. Turn it on to connect the Meshtastic MQTT lane.
                      </div>
                    )}
                    {canUsePublicMeshInput && meshView === 'channel' && filteredMeshMessages.length === 0 && (
                      <div className="text-[12px] font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                        No messages from {meshRegion} / {meshChannel}
                      </div>
                    )}
                    {canUsePublicMeshInput && meshView === 'inbox' && (
                      <>
                        {!activePublicMeshAddress && (
                          <div className="text-[12px] font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            Create or load a public mesh identity to see direct Meshtastic traffic.
                          </div>
                        )}
                        {activePublicMeshAddress && meshInboxMessages.length === 0 && (
                          <div className="text-[12px] font-mono text-[var(--text-muted)] text-center py-4 leading-[1.65]">
                            No public direct messages addressed to {activePublicMeshAddress.toUpperCase()} yet.
                          </div>
                        )}
                        {meshInboxMessages.map((m: any, i: number) => (
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
                                  TO {activePublicMeshAddress.toUpperCase()}
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
                      filteredMeshMessages.map((m: any, i: number) => (
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

</>
  );
}
