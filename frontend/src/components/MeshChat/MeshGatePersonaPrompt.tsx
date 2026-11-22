'use client';
import React from 'react';
import { Terminal, X } from 'lucide-react';
export function MeshGatePersonaPrompt({ p }: { p: any }) {
  const {
    gatePersonaPromptOpen, gatePersonaPromptTitle, closeGatePersonaPrompt, gatePersonas, gatePersonaBusy,
    submitGatePersonaPrompt, setActiveTab, openSettings, selectSavedGatePersona, remainAnonymousInGate,
    gatePersonaPromptError, gatePersonaDraftLabel, setGatePersonaDraftLabel,
    gatePersonaPromptPersonaList, setGatePersonaPromptError,
    wormholeEnabled, wormholeReadyState, handleResetPublicIdentity, identityWizardBusy,
    publicMeshBlockedByWormhole, handleLeaveWormholeForPublicMesh, onSettingsClick,
    setIdentityWizardOpen, identityWizardStatus, infonetUnlockOpen, setInfonetUnlockOpen,
    privateInfonetBlockedDetail, openTerminal, deadDropUnlockOpen, setDeadDropUnlockOpen,
    identityWizardOpen, hasPublicLaneIdentity, hasStoredPublicLaneIdentity, publicMeshAddress,
    wormholeDescriptor, handleActivatePublicMeshSession, handleCreatePublicIdentity, handleBootstrapPrivateIdentity,
  } = p as any;
  const personaList = gatePersonaPromptPersonaList || gatePersonas || [];
  return (
<>
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

              {personaList.length > 0 && (
                <div className="border border-cyan-800/25 bg-cyan-950/10 px-3 py-3">
                  <div className="text-[12px] font-mono tracking-[0.18em] text-cyan-300 mb-2">
                    SAVED FACES
                  </div>
                  <div className="space-y-2">
                    {personaList.map((persona: any) => (
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
          <div className="w-full max-w-md sb-panel sb-modal">
            <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-primary)]/40">
                <div>
                <div className="text-sm font-mono tracking-[0.24em] text-cyan-400">KEY SETUP</div>
                <div className="text-[13px] font-mono text-[var(--text-muted)] mt-1">
                  Get a Meshtastic radio key or enter Wormhole.
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
                  <div>Meshtastic key: {hasPublicLaneIdentity ? 'active' : hasStoredPublicLaneIdentity ? 'saved / off' : 'not issued'}</div>
                  <div>Meshtastic address: {publicMeshAddress ? publicMeshAddress.toUpperCase() : 'not ready'}</div>
                  <div>Wormhole lane: {wormholeEnabled && wormholeReadyState ? 'active' : wormholeEnabled ? 'starting' : 'off'}</div>
                  <div>Wormhole descriptor: {wormholeDescriptor?.nodeId || 'not cached yet'}</div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-2">
                <button
                  onClick={() => {
                    if (hasStoredPublicLaneIdentity) {
                      void handleActivatePublicMeshSession();
                      return;
                    }
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
                    ? 'MESHTASTIC KEY ACTIVE'
                    : hasStoredPublicLaneIdentity
                      ? 'TURN ON MESHTASTIC'
                    : publicMeshBlockedByWormhole
                      ? 'TURN OFF WORMHOLE FOR MESHTASTIC'
                      : 'GET MESHTASTIC KEY'}
                  <div className="mt-1 text-[13px] text-green-200/70 normal-case tracking-normal leading-[1.45]">
                    {hasPublicLaneIdentity
                      ? 'Your Meshtastic key is already live for posting.'
                      : hasStoredPublicLaneIdentity
                        ? 'Use your saved Meshtastic key. This turns Wormhole off first if it is active.'
                      : publicMeshBlockedByWormhole
                        ? 'One tap turns Wormhole off and mints a separate Meshtastic key.'
                        : 'One tap for a working Meshtastic key and address.'}
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
          <div className="w-full max-w-xl sb-panel sb-modal">
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
          <div className="w-full max-w-lg sb-panel sb-modal">
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


</>
  );
}
