'use client';

import { useCallback, useEffect, useState } from 'react';
import { clearAdminSession, hasAdminSession, primeAdminSession } from '@/lib/adminSession';
import { isNativeProtectedSettingsReady } from '@/lib/nativeProtectedSettings';

export function useSettingsPanelAdminSession(opts: {
  activeTab: string;
  fetchKeys: () => Promise<unknown>;
  fetchFeeds: () => Promise<unknown>;
  setDmRootHealth: (v: any) => void;
  setDmRootHealthMsg: (v: string | null) => void;
}) {
  const { activeTab, fetchKeys, fetchFeeds, setDmRootHealth, setDmRootHealthMsg } = opts;
  const [adminKey, setAdminKey] = useState('');
  const [adminSessionReady, setAdminSessionReady] = useState(false);
  const [adminSessionBusy, setAdminSessionBusy] = useState(false);
  const [adminSessionMsg, setAdminSessionMsg] = useState<string | null>(null);
  const [showOperatorTools, setShowOperatorTools] = useState(false);

  const refreshAdminSession = useCallback(async () => {
    if (isNativeProtectedSettingsReady()) {
      setAdminSessionReady(true);
      setAdminSessionMsg(null);
      return true;
    }
    const ready = await hasAdminSession();
    setAdminSessionReady(ready);
    if (!ready) {
      setAdminSessionMsg((prev) => (prev === 'LOCAL SESSION PRIMED' ? null : prev));
    }
    return ready;
  }, []);

  useEffect(() => {
    if (activeTab !== 'protocol') setShowOperatorTools(true);
  }, [activeTab]);

  const ensureAdminSession = useCallback(async () => {
    if (isNativeProtectedSettingsReady()) {
      setAdminSessionReady(true);
      setAdminSessionMsg(null);
      return;
    }
    try {
      await primeAdminSession(adminKey.trim() || undefined);
      setAdminSessionReady(true);
      if (adminKey.trim()) {
        setAdminKey('');
        setAdminSessionMsg('LOCAL SESSION PRIMED');
      } else {
        setAdminSessionMsg(null);
      }
    } catch (e) {
      const ready = await refreshAdminSession();
      setAdminSessionReady(ready);
      const message =
        e instanceof Error && e.message === 'admin_session_required'
          ? 'ADMIN SESSION REQUIRED'
          : e instanceof Error
            ? e.message
            : 'ADMIN SESSION FAILED';
      setAdminSessionMsg(message);
      throw e;
    }
  }, [adminKey, refreshAdminSession]);

  const unlockAdminSession = async () => {
    setAdminSessionBusy(true);
    setAdminSessionMsg(null);
    try {
      await ensureAdminSession();
      await Promise.all([fetchKeys(), fetchFeeds()]);
    } catch (e) {
      const message = e instanceof Error ? e.message : 'ADMIN SESSION FAILED';
      if (message === 'Forbidden — admin key not configured') {
        await clearAdminSession();
        setAdminSessionReady(false);
        setAdminSessionMsg('BACKEND ADMIN KEY NOT CONFIGURED');
        return;
      }
      setAdminSessionMsg(message.toUpperCase());
    } finally {
      setAdminSessionBusy(false);
    }
  };

  const lockAdminSession = async () => {
    setAdminSessionBusy(true);
    setAdminSessionMsg(null);
    try {
      await clearAdminSession();
      setAdminKey('');
      setAdminSessionReady(false);
      setDmRootHealth(null);
      setDmRootHealthMsg(null);
      setAdminSessionMsg('LOCAL SESSION CLEARED');
    } finally {
      setAdminSessionBusy(false);
    }
  };

  return {
    adminKey, setAdminKey, adminSessionReady, setAdminSessionReady, adminSessionBusy, adminSessionMsg, setAdminSessionMsg,
    showOperatorTools, setShowOperatorTools,
    refreshAdminSession, ensureAdminSession, unlockAdminSession, lockAdminSession,
  };
}
