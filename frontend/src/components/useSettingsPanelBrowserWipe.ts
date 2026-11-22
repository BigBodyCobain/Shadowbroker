// @ts-nocheck
'use client';
import React, { useCallback, useState } from 'react';
import { clearBrowserIdentityState } from '@/mesh/meshIdentity';
import { purgeBrowserDmState } from '@/mesh/meshDmWorkerClient';
import { PRIVACY_SENSITIVE_BROWSER_KEYS } from './SettingsPanel.shared';
import { setSessionModePreference } from '@/lib/privacyBrowserStorage';

export function useSettingsPanelBrowserWipe(opts: { wormholeEnabledRef: React.MutableRefObject<boolean>; setSessionMode: (v: boolean) => void }) {
  const { wormholeEnabledRef, setSessionMode } = opts;
  const [browserWipeBusy, setBrowserWipeBusy] = useState(false);
  const [browserWipeMsg, setBrowserWipeMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const clearSessionIdentity = useCallback(() => {
    if (typeof window === 'undefined') return;
    const keys = ['sb_mesh_pubkey','sb_mesh_privkey','sb_mesh_node_id','sb_mesh_sovereignty_accepted','sb_mesh_dh_pubkey','sb_mesh_dh_privkey','sb_mesh_dh_algo','sb_mesh_dh_last_ts','sb_mesh_contacts','sb_mesh_dm_notify','sb_mesh_sequence','sb_mesh_algo'];
    for (const key of keys) { try { sessionStorage.removeItem(key); } catch {} }
  }, []);

  const wipeLocalMeshTraces = useCallback(async () => {
    setBrowserWipeBusy(true); setBrowserWipeMsg(null);
    try {
      await clearBrowserIdentityState(); await purgeBrowserDmState();
      for (const key of PRIVACY_SENSITIVE_BROWSER_KEYS) { try { localStorage.removeItem(key); sessionStorage.removeItem(key); } catch {} }
      setSessionModePreference(true); setSessionMode(true);
      setBrowserWipeMsg({ type: 'ok', text: wormholeEnabledRef.current ? 'Browser-held mesh traces cleared. The local Wormhole agent stays running, but this tab will need to reconnect to it.' : 'Browser-held mesh traces cleared from this browser.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'unknown error';
      setBrowserWipeMsg({ type: 'err', text: `Could not clear browser-held mesh traces: ${message}` });
    } finally { setBrowserWipeBusy(false); }
  }, [wormholeEnabledRef, setSessionMode]);

  return { browserWipeBusy, browserWipeMsg, wipeLocalMeshTraces, clearSessionIdentity };
}
