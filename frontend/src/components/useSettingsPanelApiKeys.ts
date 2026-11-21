'use client';

import { useCallback, useMemo, useState } from 'react';
import { controlPlaneJson } from '@/lib/controlPlane';
import type { ApiEntry, EnvMeta } from './SettingsPanel.shared';

export function useSettingsPanelApiKeys(handleProtectedSettingsError: (error: unknown) => Promise<void>) {
  const [apis, setApis] = useState<ApiEntry[]>([]);
  const [apiKeyInputs, setApiKeyInputs] = useState<Record<string, string>>({});
  const [apiKeyEditing, setApiKeyEditing] = useState<Record<string, boolean>>({});
  const [apiKeySaving, setApiKeySaving] = useState<string | null>(null);
  const [apiKeyMsg, setApiKeyMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['Aviation', 'Maritime']));
  const [envMeta, setEnvMeta] = useState<EnvMeta | null>(null);

  const fetchKeys = useCallback(async () => {
    try {
      setApis(await controlPlaneJson<ApiEntry[]>('/api/settings/api-keys', { requireAdminSession: false }));
      return true;
    } catch (e) {
      await handleProtectedSettingsError(e);
      return false;
    }
  }, [handleProtectedSettingsError]);

  const saveApiKey = useCallback(async (envKey: string | null) => {
    if (!envKey) return;
    const value = String(apiKeyInputs[envKey] || '').trim();
    if (!value) {
      setApiKeyMsg({ type: 'err', text: `Enter a value for ${envKey}.` });
      return;
    }
    setApiKeySaving(envKey);
    setApiKeyMsg(null);
    try {
      const result = await controlPlaneJson<{ keys?: ApiEntry[]; env?: EnvMeta }>('/api/settings/api-keys', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [envKey]: value }),
        requireAdminSession: false,
      });
      if (result.keys) setApis(result.keys);
      if (result.env) setEnvMeta(result.env);
      setApiKeyInputs((prev) => ({ ...prev, [envKey]: '' }));
      setApiKeyEditing((prev) => ({ ...prev, [envKey]: false }));
      setApiKeyMsg({ type: 'ok', text: `${envKey} saved locally. Restart or refresh feeds to use it.` });
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Could not save API key';
      setApiKeyMsg({ type: 'err', text: message });
    } finally {
      setApiKeySaving(null);
    }
  }, [apiKeyInputs]);

  const fetchEnvMeta = useCallback(async () => {
    try {
      const res = await fetch('/api/settings/api-keys/meta');
      if (!res.ok) return;
      const data: EnvMeta = await res.json();
      setEnvMeta(data);
    } catch {
      // Non-fatal
    }
  }, []);

  const toggleCategory = useCallback((cat: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }, []);

  const grouped = useMemo(() => apis.reduce<Record<string, ApiEntry[]>>((acc, api) => {
    if (!acc[api.category]) acc[api.category] = [];
    acc[api.category].push(api);
    return acc;
  }, {}), [apis]);

  const clearApiKeys = useCallback(() => { setApis([]); setApiKeyMsg(null); }, []);

  return {
    apis, apiKeyInputs, apiKeyEditing, apiKeySaving, apiKeyMsg,
    expandedCategories, envMeta, grouped,
    fetchKeys, saveApiKey, fetchEnvMeta, toggleCategory,
    setApiKeyInputs, setApiKeyEditing, setApiKeyMsg, clearApiKeys,
  };
}
