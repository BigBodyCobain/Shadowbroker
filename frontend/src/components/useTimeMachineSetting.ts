'use client';
import { useCallback, useEffect, useState } from 'react';
import { API_BASE } from '@/lib/api';
import { controlPlaneFetch } from '@/lib/controlPlane';

export function useTimeMachineSetting(isOpen: boolean, activeTab: string) {
  const [tmEnabled, setTmEnabled] = useState(false);
  const [tmSaving, setTmSaving] = useState(false);
  useEffect(() => {
    if (!isOpen || activeTab !== 'protocol') return;
    fetch(`${API_BASE}/api/settings/timemachine`).then((r) => r.json()).then((d) => setTmEnabled(!!d.enabled)).catch(() => {});
  }, [isOpen, activeTab]);
  const toggleTimeMachine = useCallback(async () => {
    setTmSaving(true);
    try {
      const res = await controlPlaneFetch('/api/settings/timemachine', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !tmEnabled }), requireAdminSession: false,
      });
      if (res.ok) { const data = await res.json(); setTmEnabled(!!data.enabled); }
    } catch {}
    setTmSaving(false);
  }, [tmEnabled]);
  return { tmEnabled, tmSaving, toggleTimeMachine };
}
