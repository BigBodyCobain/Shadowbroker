'use client';
import React from 'react';
import { Ban, Eye, EyeOff, MapPin, Send, UserPlus } from 'lucide-react';

export function MeshSenderPopup({ senderPopup, popupRef, mutedUsers, handleUnmute, setMuteConfirm, handleReplyToMeshAddress, handleLocateUser, hasId, identity, senderPopupContact, setSenderPopup, requestInfonetLeave, setActiveTab, openChat, handleRequestAccess, handleBlockDM }: any) {
  if (!senderPopup) return null;
  return (
    <div ref={popupRef} className="fixed z-[500] bg-[var(--bg-primary)]/95 border border-[var(--border-primary)] shadow-[0_4px_20px_rgba(0,0,0,0.4)] backdrop-blur-sm py-1 min-w-[140px]" style={{ left: senderPopup.x, top: senderPopup.y }}>
      <div className="px-3 py-1 border-b border-[var(--border-primary)]/50">
        <span className="text-[13px] font-mono text-cyan-400 tracking-wider">{senderPopup.userId.slice(0, 16)}</span>
      </div>
      {senderPopup.tab === 'infonet' && (
        <div className="px-3 py-2 border-b border-[var(--border-primary)]/50">
          <div className="text-[12px] font-mono text-[var(--text-muted)] tracking-[0.18em]">PUBLIC KEY</div>
          <div className="mt-1 text-[12px] font-mono text-green-300/90 break-all leading-[1.55]" title={senderPopup.publicKey || 'not advertised on this event'}>{senderPopup.publicKey || 'not advertised on this event'}</div>
          {senderPopup.publicKeyAlgo ? <div className="mt-1 text-[12px] font-mono text-cyan-500/80">{senderPopup.publicKeyAlgo}</div> : null}
        </div>
      )}
      {mutedUsers.has(senderPopup.userId) ? (
        <button onClick={() => handleUnmute(senderPopup.userId)} className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]/50 transition-colors"><Eye size={10} /> UNMUTE</button>
      ) : (
        <button onClick={() => setMuteConfirm(senderPopup.userId)} className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-red-400/80 hover:bg-red-900/10 transition-colors"><EyeOff size={10} /> MUTE</button>
      )}
      {senderPopup.tab === 'meshtastic' && (
        <>
          <button onClick={() => handleReplyToMeshAddress(senderPopup.userId)} className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-green-300 hover:bg-green-950/20 transition-colors"><Send size={10} /> REPLY</button>
          <button onClick={() => handleLocateUser(senderPopup.userId)} className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]/50 transition-colors"><MapPin size={10} /> LOCATE</button>
        </>
      )}
      {senderPopup.tab === 'infonet' && hasId && senderPopup.userId !== identity?.nodeId && (
        <>
          {senderPopupContact && !senderPopupContact.blocked ? (
            <button onClick={() => { const userId = senderPopup.userId; setSenderPopup(null); requestInfonetLeave(() => { setActiveTab('dms'); openChat(userId); }); }} className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-green-300 hover:bg-green-950/20 transition-colors"><Send size={10} /> OPEN DM</button>
          ) : (
            <button onClick={() => { handleRequestAccess(senderPopup.userId); setSenderPopup(null); }} className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]/50 transition-colors"><UserPlus size={10} /> REQUEST CONTACT</button>
          )}
          {!senderPopupContact?.blocked ? (
            <button onClick={() => { void handleBlockDM(senderPopup.userId); setSenderPopup(null); }} className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] font-mono text-red-400/80 hover:bg-red-900/10 transition-colors"><Ban size={10} /> BLOCK</button>
          ) : (
            <div className="px-3 py-1.5 text-[12px] font-mono text-red-300/70 tracking-[0.18em]">CONTACT BLOCKED</div>
          )}
        </>
      )}
    </div>
  );
}
