'use client';

import { useCallback } from 'react';
import { API_BASE } from '@/lib/api';
import type { MeshMqttForm, MeshMqttSettings } from './useMeshChatController.helpers';
import { describeMeshChatControlError, errorMessage } from './useMeshChatController.helpers';

export function useMeshMqttSettings(ctx: any) {
  const {
    meshMqttForm,
    setMeshMqttSettings,
    setMeshMqttForm,
    setMeshMqttBusy,
    setMeshMqttStatusText,
    setWormholeEnabled,
    setWormholeReadyState,
    setWormholeRnsReady,
    setWormholeRnsDirectReady,
    setWormholeRnsPeers,
    setSecureModeCached,
  } = ctx;

  const applyMeshMqttSettings = useCallback((data: MeshMqttSettings) => {
    setMeshMqttSettings(data);
    setMeshMqttForm((prev: any) => ({
      broker: data.broker || prev.broker || 'mqtt.meshtastic.org',
      port: String(data.port || prev.port || '1883'),
      username: data.uses_default_credentials ? '' : data.username || prev.username || '',
      password: '',
      psk: '',
      include_default_roots: Boolean(data.include_default_roots),
      extra_roots: data.extra_roots || '',
      extra_topics: data.extra_topics || '',
    }));
  }, [setMeshMqttForm, setMeshMqttSettings]);

  const refreshMeshMqttSettings = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/settings/meshtastic-mqtt`, { cache: 'no-store' });
      if (!res.ok) return null;
      const data = (await res.json()) as MeshMqttSettings;
      applyMeshMqttSettings(data);
      return data;
    } catch {
      return null;
    }
  }, [applyMeshMqttSettings]);

  const saveMeshMqttSettings = useCallback(
    async (updates: Partial<MeshMqttForm> & { enabled?: boolean } = {}) => {
      setMeshMqttBusy(true);
      setMeshMqttStatusText('');
      try {
        const nextForm = { ...meshMqttForm, ...updates };
        const body: Record<string, unknown> = {
          broker: nextForm.broker.trim() || 'mqtt.meshtastic.org',
          port: Number.parseInt(nextForm.port, 10) || 1883,
          username: nextForm.username.trim(),
          include_default_roots: Boolean(nextForm.include_default_roots),
          extra_roots: nextForm.extra_roots.trim(),
          extra_topics: nextForm.extra_topics.trim(),
        };
        if (!nextForm.username.trim() && !nextForm.password.trim()) {
          body.password = '';
        }
        if (typeof updates.enabled === 'boolean') {
          body.enabled = updates.enabled;
        }
        if (nextForm.password.trim()) {
          body.password = nextForm.password;
        }
        if (nextForm.psk.trim()) {
          body.psk = nextForm.psk.trim();
        }
        const res = await fetch(`${API_BASE}/api/settings/meshtastic-mqtt`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const data = await res.clone().json().catch(() => null) as
            | { detail?: unknown; message?: unknown; error?: unknown }
            | null;
          const detail =
            String(data?.detail || data?.message || data?.error || '').trim() ||
            (await res.text().catch(() => '')).trim();
          throw new Error(describeMeshChatControlError(detail || `HTTP ${res.status}`));
        }
        const data = (await res.json()) as MeshMqttSettings;
        applyMeshMqttSettings(data);
        if (data.enabled) {
          setWormholeEnabled(false);
          setWormholeReadyState(false);
          setWormholeRnsReady(false);
          setWormholeRnsDirectReady(false);
          setWormholeRnsPeers({ active: 0, configured: 0 });
          setSecureModeCached(false);
        }
        const status = data.runtime?.connected
          ? 'MQTT bridge connected.'
          : data.enabled
            ? 'MQTT bridge enabled. Connection may take a few seconds.'
            : 'MQTT bridge disabled.';
        setMeshMqttStatusText(status);
        return { ok: true as const, text: status, data };
      } catch (err) {
        const text = describeMeshChatControlError(errorMessage(err, 'MQTT settings update failed'));
        setMeshMqttStatusText(text);
        return { ok: false as const, text };
      } finally {
        setMeshMqttBusy(false);
      }
    },
    [applyMeshMqttSettings, meshMqttForm, setMeshMqttBusy, setMeshMqttStatusText, setSecureModeCached, setWormholeEnabled, setWormholeReadyState, setWormholeRnsDirectReady, setWormholeRnsPeers, setWormholeRnsReady],
  );

  const enableMeshMqttBridge = useCallback(async () => {
    const result = await saveMeshMqttSettings({ enabled: true });
    if (!result.ok) {
      throw new Error(result.text);
    }
    return result;
  }, [saveMeshMqttSettings]);

  return { applyMeshMqttSettings, refreshMeshMqttSettings, saveMeshMqttSettings, enableMeshMqttBridge };
}
