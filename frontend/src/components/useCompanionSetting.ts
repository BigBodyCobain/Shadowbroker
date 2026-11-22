'use client';
import { useCallback, useEffect, useState } from 'react';
import { companionDisable, companionEnable, companionOpenBrowser, companionStatus as fetchCompanionStatus, isNativeDesktop, type CompanionStatus } from '@/lib/desktopCompanion';

export function useCompanionSetting(isOpen: boolean, activeTab: string) {
  const [companionAvailable] = useState(() => isNativeDesktop());
  const [companion, setCompanion] = useState<CompanionStatus | null>(null);
  const [companionBusy, setCompanionBusy] = useState(false);
  const [companionError, setCompanionError] = useState<string | null>(null);
  const [companionLoadFailed, setCompanionLoadFailed] = useState(false);
  useEffect(() => {
    if (!isOpen || activeTab !== 'protocol' || !companionAvailable) return;
    setCompanionLoadFailed(false);
    fetchCompanionStatus().then((s: any) => setCompanion(s)).catch(() => { setCompanion(null); setCompanionLoadFailed(true); });
  }, [isOpen, activeTab, companionAvailable]);
  const toggleCompanion = useCallback(async () => {
    setCompanionBusy(true); setCompanionError(null);
    try { const result = companion?.enabled ? await companionDisable() : await companionEnable(); if (result) setCompanion(result); }
    catch (e) { setCompanionError(e instanceof Error ? e.message : String(e)); }
    setCompanionBusy(false);
  }, [companion?.enabled]);
  const openCompanionBrowser = useCallback(async () => {
    setCompanionBusy(true); setCompanionError(null);
    try { const result = await companionOpenBrowser(); if (result) setCompanion(result); }
    catch (e) { setCompanionError(e instanceof Error ? e.message : String(e)); }
    setCompanionBusy(false);
  }, []);
  return { companionAvailable, companion, companionBusy, companionError, companionLoadFailed, toggleCompanion, openCompanionBrowser };
}
