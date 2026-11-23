'use client';
import React from 'react';

export function MeshMuteDialog({ muteConfirm, setMuteConfirm, setSenderPopup, handleMute }: any) {
  if (!muteConfirm) return null;
  return (
    <div className="fixed inset-0 z-[600] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--bg-primary)] border border-[var(--border-primary)] p-4 max-w-[260px] w-full">
        <div className="text-sm font-mono text-[var(--text-secondary)] mb-1">CONFIRM MUTE</div>
        <div className="text-[13px] font-mono text-[var(--text-muted)] mb-3 leading-[1.65]">
          Mute <span className="text-cyan-400">{muteConfirm.slice(0, 16)}</span>? Their messages will be hidden. You can unmute from Dead Drop &gt; MUTED.
        </div>
        <div className="flex items-center gap-2 justify-end">
          <button onClick={() => { setMuteConfirm(null); setSenderPopup(null); }} className="text-[13px] font-mono px-3 py-1 bg-[var(--bg-secondary)]/50 text-[var(--text-muted)] hover:bg-[var(--bg-secondary)] transition-colors">CANCEL</button>
          <button onClick={() => handleMute(muteConfirm)} className="text-[13px] font-mono px-3 py-1 bg-red-900/30 text-red-400 hover:bg-red-800/40 transition-colors">MUTE</button>
        </div>
      </div>
    </div>
  );
}
