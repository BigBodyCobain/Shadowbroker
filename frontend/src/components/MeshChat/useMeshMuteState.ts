'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { getNodeIdentity } from '@/mesh/meshIdentity';
import { getMutedList, saveMutedList } from './storage';
import type { SenderPopup } from './types';

export function useMeshMuteState() {
  const [mutedUsers, setMutedUsers] = useState<Set<string>>(new Set());
  const [senderPopup, setSenderPopup] = useState<SenderPopup | null>(null);
  const [muteConfirm, setMuteConfirm] = useState<string | null>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    void getMutedList(getNodeIdentity()?.nodeId).then((ids) => {
      if (!cancelled) {
        setMutedUsers(new Set(ids));
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!senderPopup) return;
    const handle = (e: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        setSenderPopup(null);
      }
    };
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [senderPopup]);

  const handleMute = useCallback((userId: string) => {
    setMutedUsers((prev) => {
      const updated = new Set(prev);
      updated.add(userId);
      void saveMutedList([...updated], getNodeIdentity()?.nodeId);
      return updated;
    });
    setSenderPopup(null);
    setMuteConfirm(null);
  }, []);

  const handleUnmute = useCallback((userId: string) => {
    setMutedUsers((prev) => {
      const updated = new Set(prev);
      updated.delete(userId);
      void saveMutedList([...updated], getNodeIdentity()?.nodeId);
      return updated;
    });
    setSenderPopup(null);
  }, []);

  return {
    mutedUsers,
    setMutedUsers,
    senderPopup,
    setSenderPopup,
    muteConfirm,
    setMuteConfirm,
    popupRef,
    handleMute,
    handleUnmute,
  };
}
