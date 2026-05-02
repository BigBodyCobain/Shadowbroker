'use client';

import React, { useCallback, useEffect, useRef } from 'react';

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * In-app modal confirmation dialog — replaces browser `window.confirm()`.
 *
 * Renders a centered dark-themed overlay with CONFIRM / CANCEL buttons.
 * Supports Escape to cancel and Enter to confirm.
 */
const ConfirmDialog: React.FC<Props> = ({
  open,
  title,
  message,
  confirmLabel = 'CONFIRM',
  cancelLabel = 'CANCEL',
  danger = true,
  onConfirm,
  onCancel,
}) => {
  const confirmBtnRef = useRef<HTMLButtonElement>(null);

  // Auto-focus the confirm button when the dialog opens
  useEffect(() => {
    if (open) {
      setTimeout(() => confirmBtnRef.current?.focus(), 50);
    }
  }, [open]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      e.stopPropagation();
      e.nativeEvent.stopImmediatePropagation();
      if (e.key === 'Escape') onCancel();
      if (e.key === 'Enter') onConfirm();
    },
    [onConfirm, onCancel],
  );

  if (!open) return null;

  const accentColor = danger ? '#ef4444' : '#8b5cf6';

  return (
    <div
      className="fixed inset-0 flex items-center justify-center"
      style={{ zIndex: 99999, background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(2px)' }}
      onClick={onCancel}
      onKeyDown={handleKeyDown}
    >
      <div
        className="bg-[#0d0d1a] border-2 font-mono text-white max-w-sm w-full mx-4"
        style={{
          borderColor: `${accentColor}88`,
          boxShadow: `0 20px 60px rgba(0,0,0,0.8), 0 0 0 1px ${accentColor}33`,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="px-4 py-2.5 border-b text-[11px] uppercase tracking-[0.2em] font-bold"
          style={{ borderColor: `${accentColor}44`, background: `${accentColor}15`, color: accentColor }}
        >
          {title}
        </div>

        {/* Body */}
        <div className="px-4 py-4">
          <p className="text-[12px] text-gray-300 leading-relaxed whitespace-pre-wrap">{message}</p>
        </div>

        {/* Actions */}
        <div className="flex gap-2 px-4 pb-4">
          <button
            ref={confirmBtnRef}
            type="button"
            onClick={onConfirm}
            className="flex-1 py-2 text-[11px] font-mono tracking-wider border transition-colors"
            style={{
              background: `${accentColor}30`,
              borderColor: `${accentColor}66`,
              color: danger ? '#fca5a5' : '#c4b5fd',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = `${accentColor}50`;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = `${accentColor}30`;
            }}
          >
            {confirmLabel}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-[11px] font-mono tracking-wider border border-gray-600/40 text-gray-400 hover:text-white hover:border-gray-500/60 transition-colors"
          >
            {cancelLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmDialog;
