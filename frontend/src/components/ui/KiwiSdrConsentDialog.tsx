'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

interface Props {
  open: boolean;
  initialCallsign?: string;
  mode?: 'consent' | 'edit';
  onConfirm: (callsign: string) => void;
  onCancel: () => void;
}

const KiwiSdrConsentDialog: React.FC<Props> = ({
  open,
  initialCallsign = '',
  mode = 'consent',
  onConfirm,
  onCancel,
}) => {
  const [callsign, setCallsign] = useState(initialCallsign);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setCallsign(initialCallsign);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open, initialCallsign]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      e.stopPropagation();
      e.nativeEvent.stopImmediatePropagation();
      if (e.key === 'Escape') onCancel();
      if (e.key === 'Enter') onConfirm(callsign.trim());
    },
    [onConfirm, onCancel, callsign],
  );

  if (!open) return null;

  const accent = '#ec4899';
  const isEdit = mode === 'edit';

  return (
    <div
      className="fixed inset-0 flex items-center justify-center"
      style={{ zIndex: 99999, background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(2px)' }}
      onClick={onCancel}
      onKeyDown={handleKeyDown}
    >
      <div
        className="bg-[#0d0d1a] border-2 font-mono text-white max-w-md w-full mx-4"
        style={{
          borderColor: `${accent}88`,
          boxShadow: `0 20px 60px rgba(0,0,0,0.8), 0 0 0 1px ${accent}33`,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="px-4 py-2.5 border-b text-[11px] uppercase tracking-[0.2em] font-bold"
          style={{ borderColor: `${accent}44`, background: `${accent}15`, color: accent }}
        >
          {isEdit ? 'Edit KiwiSDR Callsign' : 'KiwiSDR — First Use'}
        </div>

        <div className="px-4 py-4 space-y-3">
          {!isEdit && (
            <div className="text-[12px] text-gray-300 leading-relaxed space-y-2">
              <p>
                KiwiSDR receivers are <span className="text-pink-300">volunteer-operated</span>{' '}
                by amateur radio operators. Each receiver has a limited number of user slots
                (usually 4–8) and shares the operator&apos;s home internet bandwidth.
              </p>
              <p>
                Please be respectful: close the popup when you&apos;re done listening, and
                identify yourself with a callsign or handle below so operators know who&apos;s
                connecting.
              </p>
            </div>
          )}

          <div className="space-y-1.5">
            <label className="block text-[11px] uppercase tracking-widest text-pink-400 font-bold">
              Your Callsign or Handle
            </label>
            <input
              ref={inputRef}
              type="text"
              value={callsign}
              onChange={(e) => setCallsign(e.target.value)}
              placeholder="e.g. KD9ABC or anon-1234 (optional)"
              maxLength={32}
              className="w-full bg-black/40 border border-pink-500/40 focus:border-pink-400 focus:outline-none px-2.5 py-1.5 text-[13px] text-pink-200 font-mono tracking-wide"
            />
            <p className="text-[10px] text-gray-500 leading-snug">
              Shown to the SDR operator in their user list. Leave blank to let KiwiSDR prompt
              you on first connect.
            </p>
          </div>
        </div>

        <div className="flex gap-2 px-4 pb-4">
          <button
            type="button"
            onClick={() => onConfirm(callsign.trim())}
            className="flex-1 py-2 text-[11px] font-mono tracking-wider border transition-colors"
            style={{
              background: `${accent}30`,
              borderColor: `${accent}66`,
              color: '#fbcfe8',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = `${accent}50`;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = `${accent}30`;
            }}
          >
            {isEdit ? 'SAVE' : 'CONTINUE'}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-[11px] font-mono tracking-wider border border-gray-600/40 text-gray-400 hover:text-white hover:border-gray-500/60 transition-colors"
          >
            CANCEL
          </button>
        </div>
      </div>
    </div>
  );
};

export default KiwiSdrConsentDialog;
