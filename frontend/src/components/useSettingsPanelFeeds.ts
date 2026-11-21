'use client';

import { useCallback, useState } from 'react';
import { controlPlaneFetch, controlPlaneJson } from '@/lib/controlPlane';
import { formatFeedSettingsError, MAX_FEEDS, validateFeedEntries, type FeedEntry } from './SettingsPanel.shared';

export function useSettingsPanelFeeds(handleProtectedSettingsError: (error: unknown) => Promise<void>) {
  const [feeds, setFeeds] = useState<FeedEntry[]>([]);
  const [feedsDirty, setFeedsDirty] = useState(false);
  const [feedSaving, setFeedSaving] = useState(false);
  const [feedMsg, setFeedMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const fetchFeeds = useCallback(async () => {
    try {
      setFeeds(
        await controlPlaneJson<FeedEntry[]>('/api/settings/news-feeds', {
          requireAdminSession: false,
        }),
      );
      setFeedsDirty(false);
      return true;
    } catch (e) {
      await handleProtectedSettingsError(e);
      return false;
    }
  }, [handleProtectedSettingsError]);

  const updateFeed = (idx: number, field: keyof FeedEntry, value: string | number) => {
    setFeeds((prev) => prev.map((f, i) => (i === idx ? { ...f, [field]: value } : f)));
    setFeedsDirty(true);
    setFeedMsg(null);
  };

  const removeFeed = (idx: number) => {
    setFeeds((prev) => prev.filter((_, i) => i !== idx));
    setFeedsDirty(true);
    setFeedMsg(null);
  };

  const addFeed = () => {
    if (feeds.length >= MAX_FEEDS) return;
    setFeeds((prev) => [...prev, { name: '', url: '', weight: 3 }]);
    setFeedsDirty(true);
    setFeedMsg(null);
  };

  const saveFeeds = async () => {
    const validationError = validateFeedEntries(feeds);
    if (validationError) {
      setFeedMsg({ type: 'err', text: validationError });
      return;
    }
    setFeedSaving(true);
    setFeedMsg(null);
    try {
      const res = await controlPlaneFetch('/api/settings/news-feeds', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(feeds),
        requireAdminSession: false,
      });
      if (res.ok) {
        setFeedsDirty(false);
        setFeedMsg({
          type: 'ok',
          text: 'Feeds saved. Changes take effect on next news refresh (~30min) or manual /api/refresh.',
        });
      } else {
        const d = await res.json().catch(() => ({}));
        setFeedMsg({
          type: 'err',
          text: String(d.message || d.detail || 'Save failed'),
        });
      }
    } catch (error) {
      setFeedMsg({
        type: 'err',
        text: formatFeedSettingsError(error, 'Could not reach the settings API'),
      });
    } finally {
      setFeedSaving(false);
    }
  };

  const resetFeeds = async () => {
    setFeedMsg(null);
    try {
      const res = await controlPlaneFetch('/api/settings/news-feeds/reset', {
        method: 'POST',
        requireAdminSession: false,
      });
      if (res.ok) {
        const d = await res.json();
        setFeeds(d.feeds || []);
        setFeedsDirty(false);
        setFeedMsg({ type: 'ok', text: 'Reset to defaults' });
      } else {
        const d = await res.json().catch(() => ({}));
        setFeedMsg({
          type: 'err',
          text: String(d.message || d.detail || 'Reset failed'),
        });
      }
    } catch (error) {
      setFeedMsg({
        type: 'err',
        text: formatFeedSettingsError(error, 'Could not reach the settings API'),
      });
    }
  };

  const clearFeeds = useCallback(() => { setFeeds([]); setFeedsDirty(false); setFeedMsg(null); }, []);
  return { feeds, feedsDirty, feedSaving, feedMsg, fetchFeeds, updateFeed, removeFeed, addFeed, saveFeeds, resetFeeds, setFeedMsg, clearFeeds };
}
