// @ts-nocheck
'use client';
import React from 'react';
import { Send } from 'lucide-react';

export function MeshChatInputBar({ p }: { p: any }) {
  const { activeTab, sendError, canUsePublicMeshInput, meshDirectTarget, activePublicMeshAddress, meshRegion, meshChannel, publicMeshBlockedByWormhole, hasStoredPublicLaneIdentity, meshQuickStatus, openIdentityWizard, meshAddressDraft, setMeshAddressDraft, handleMeshDirectTargetSubmit, handleActivatePublicMeshSession, handleLeaveWormholeForPublicMesh, identityWizardBusy, canUseMeshtasticChat, meshSendBlocked, meshSendBlockedReason, inputDisabled, privateLaneHint, inputRef, inputValue, setInputValue, handleSend, busy, sendDecoy, expanded, openSettings, dashboardRestrictedTab, dashboardRestrictedTitle, privateInfonetBlockedDetail, privateInfonetTransportReady } = p;
  return (
<>
            {/* INPUT BAR */}
            {activeTab === 'dms' || activeTab === 'infonet' ? null : (
            <div className="mx-2 mb-2 mt-1 border border-cyan-800/40 bg-black/30 shrink-0 relative">
              <span className="absolute -top-[7px] left-3 bg-[var(--bg-primary)] px-1 text-[11px] font-mono text-cyan-700/60 tracking-[0.15em] select-none">INPUT</span>
              {/* Destination indicator / error */}
              <div className="flex items-center gap-1 px-3 pt-2.5 pb-0">
                {sendError ? (
                  <>
                    <span className="text-[11px] font-mono tracking-widest text-red-400/80 uppercase animate-pulse">
                      ✕ {sendError}
                    </span>
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
                    {canUsePublicMeshInput
                      ? meshDirectTarget
                        ? `→ MESHTASTIC / TO ${meshDirectTarget.toUpperCase()} / FROM ${activePublicMeshAddress.toUpperCase()}`
                        : `→ MESHTASTIC / ${meshRegion} / ${meshChannel} / ${activePublicMeshAddress.toUpperCase()}`
                      : publicMeshBlockedByWormhole
                        ? '→ MESHTASTIC BLOCKED / WORMHOLE ACTIVE'
                        : hasStoredPublicLaneIdentity
                          ? '→ MESHTASTIC OFF'
                          : '→ MESHTASTIC LOCKED'}
                  </span>
                )}
              </div>
              {activeTab === 'meshtastic' && !sendError && (!canUsePublicMeshInput || meshQuickStatus) && (
                <div
                  className={`px-3 pt-1 text-[12px] font-mono leading-[1.5] ${
                    meshQuickStatus?.type === 'err'
                      ? 'text-red-300/80'
                      : meshQuickStatus?.type === 'ok'
                        ? 'text-green-300/80'
                        : 'text-green-300/70'
                  }`}
                >
                  {meshQuickStatus?.text || meshActivationText}
                </div>
              )}
              <div className="flex items-center gap-2 px-3 pb-2 pt-1">
                {activeTab === 'meshtastic' && !canUsePublicMeshInput ? (
                  <button
                    onClick={handleMeshActivationAction}
                    disabled={identityWizardBusy}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-green-700/40 bg-green-950/15 text-green-300 hover:bg-green-950/25 hover:border-green-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Radio size={11} />
                      {meshActivationLabel}
                    </span>
                    <span className="text-[12px] font-mono text-green-300/70">
                      {meshActivationSideLabel}
                    </span>
                  </button>
                ) : activeTab === 'meshtastic' && meshDirectTarget ? (
                  <button
                    onClick={() => {
                      setMeshDirectTarget('');
                      setMeshAddressDraft('');
                    }}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-amber-700/40 bg-amber-950/10 text-amber-200 hover:bg-amber-950/20 hover:border-amber-500/50 transition-colors"
                  >
                    <span className="inline-flex items-center gap-2 text-sm font-mono tracking-[0.2em]">
                      <Send size={11} />
                      DIRECT TO {meshDirectTarget.toUpperCase()}
                    </span>
                    <span className="text-[12px] font-mono text-amber-200/70">RETURN TO CHANNEL</span>
                  </button>
                ) : (
                  <>
                    <span className="text-[11px] text-cyan-400 select-none shrink-0 font-mono" style={{ textShadow: '0 0 6px rgba(34,211,238,0.4)' }}>
                      &gt;
                    </span>
                    <div className="relative flex-1">
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
</>
  );
}
