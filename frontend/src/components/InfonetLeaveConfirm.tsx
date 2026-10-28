'use client';

import React, { useEffect, useState } from 'react';
import { resolveInfonetLeave, subscribeInfonetLeave } from '@/lib/infonetLeaveNotice';

/** Mounted once; shows whenever requestInfonetLeave() needs confirmation. */
export default function InfonetLeaveConfirm() {
  const [open, setOpen] = useState(false);
  const [dontShowAgain, setDontShowAgain] = useState(false);

  useEffect(
    () =>
      subscribeInfonetLeave((pending) => {
        setOpen(Boolean(pending));
        if (pending) setDontShowAgain(false);
      }),
    [],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopImmediatePropagation();
        resolveInfonetLeave(false);
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/70 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="infonet-leave-title"
    >
      <div className="w-full max-w-md border border-cyan-800/50 bg-[#05090d] p-5 font-mono">
        <div id="infonet-leave-title" className="text-sm tracking-[0.2em] text-cyan-300">
          LEAVE INFONET?
        </div>
        <p className="mt-3 text-[12px] leading-relaxed text-cyan-100/80">
          Leaving disconnects your private connection. Tor and the Wormhole shut down so nothing private runs in the
          background, and new messages won&apos;t arrive until you come back.
        </p>
        <p className="mt-2 text-[12px] leading-relaxed text-cyan-100/60">
          Reconnecting next time can take up to a minute.
        </p>
        <label className="mt-4 flex items-center gap-2 text-[12px] text-cyan-200/80 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={dontShowAgain}
            onChange={(e) => setDontShowAgain(e.target.checked)}
            className="accent-cyan-500"
          />
          Don&apos;t show this again
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            autoFocus
            onClick={() => resolveInfonetLeave(false)}
            className="px-3 py-1.5 border border-cyan-500/40 text-[12px] tracking-[0.14em] text-cyan-100 hover:bg-cyan-900/30"
          >
            STAY CONNECTED
          </button>
          <button
            type="button"
            onClick={() => resolveInfonetLeave(true, dontShowAgain)}
            className="px-3 py-1.5 border border-gray-700 text-[12px] tracking-[0.14em] text-gray-300 hover:bg-gray-900"
          >
            DISCONNECT
          </button>
        </div>
      </div>
    </div>
  );
}
