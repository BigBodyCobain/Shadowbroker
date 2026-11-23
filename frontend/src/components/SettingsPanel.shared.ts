import { setSecureModeCached } from '@/mesh/meshIdentity';
import { clearBrowserIdentityState, purgeBrowserContactGraph, purgeBrowserSigningMaterial } from '@/mesh/meshIdentity';
import { purgeBrowserDmState } from '@/mesh/meshDmWorkerClient';
import {
  formatGateCompatSeenAt,
  getGateCompatTelemetryEventName,
  getGateCompatTelemetrySnapshot,
  summarizeGateCompatTelemetry,
  type GateCompatTelemetrySnapshot,
} from '@/mesh/gateCompatTelemetry';
import {
  describeBrowserGateLocalRuntimeStatus,
  getBrowserGateLocalRuntimeEventName,
  getBrowserGateLocalRuntimeStatus,
  type BrowserGateLocalRuntimeStatus,
} from '@/mesh/meshGateWorkerClient';
import {
  isNativeDesktop,
  companionStatus as fetchCompanionStatus,
  companionEnable,
  companionDisable,
  companionOpenBrowser,
  type CompanionStatus,
} from '@/lib/desktopCompanion';
import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from '@/lib/motion';
import {
  Settings,
  ExternalLink,
  Key,
  Shield,
  X,
  Save,
  ChevronDown,
  ChevronUp,
  Rss,
  Plus,
  Trash2,
  RotateCcw,
  Satellite,
  Copy,
  Check,
  Radar,
} from 'lucide-react';
import {
  // Issue #298: Sentinel credentials now live server-side. The legacy
  // browser-storage helpers (getSentinelCredentials / setSentinelCredentials
  // / clearSentinelCredentials / getSentinelCredentialStorageMode) have
  // been removed from sentinelHub.ts. We use the new status check + the
  // one-time migration helper instead.
  checkBackendSentinelStatus,
  migrateLegacySentinelBrowserKeys,
} from '@/lib/sentinelHub';
import {
  getPrivacyProfilePreference,
  getPrivacyStrictPreference,
  getSessionModePreference,
  migrateSensitiveBrowserItems,
  setPrivacyProfilePreference,
  setPrivacyStrictPreference,
  setSessionModePreference,
} from '@/lib/privacyBrowserStorage';
import { useTranslation, LOCALES, type Locale } from '@/i18n';

export interface ApiEntry {
  id: string;
  name: string;
  description: string;
  category: string;
  url: string | null;
  required: boolean;
  has_key: boolean;
  env_key: string | null;
  is_set: boolean;
}

export interface FeedEntry {
  name: string;
  url: string;
  weight: number;
}

export interface EnvMeta {
  env_path: string;
  env_path_exists: boolean;
  env_path_writable: boolean;
  env_example_path: string;
  env_example_path_exists: boolean;
  operator_keys_env_path?: string;
  operator_keys_env_path_exists?: boolean;
  operator_keys_env_path_writable?: boolean;
}

export const WEIGHT_LABELS: Record<number, string> = {
  1: 'LOW',
  2: 'MED',
  3: 'STD',
  4: 'HIGH',
  5: 'CRIT',
};
export const WEIGHT_COLORS: Record<number, string> = {
  1: 'text-gray-400 border-gray-600',
  2: 'text-blue-400 border-blue-600',
  3: 'text-cyan-400 border-cyan-600',
  4: 'text-orange-400 border-orange-600',
  5: 'text-red-400 border-red-600',
};
export const SETTINGS_FOCUS_KEY = 'sb_settings_focus';
export const WORMHOLE_RETURN_KEY = 'sb_wormhole_return_target';
export const WORMHOLE_READY_EVENT = 'sb:wormhole-ready';
// Issue #298 (tg12): Sentinel credentials moved from browser storage to
// the backend ``.env`` (managed through the API Keys panel). The legacy
// keys (``sb_sentinel_client_id`` / ``sb_sentinel_client_secret`` /
// ``sb_sentinel_instance_id``) are no longer treated as sensitive
// browser state because they are no longer written. ``SentinelTab``
// runs ``migrateLegacySentinelBrowserKeys()`` once on mount to clear
// any leftover values from pre-#298 installs.
export const PRIVACY_SENSITIVE_BROWSER_KEYS = [
  'sb_infonet_head',
  'sb_infonet_head_history',
  'sb_infonet_peers',
] as const;

export async function applySecureModeBoundary(enabled: boolean): Promise<void> {
  setSecureModeCached(enabled);
  if (!enabled) return;
  purgeBrowserSigningMaterial();
  purgeBrowserContactGraph();
  await purgeBrowserDmState();
}

export function migratePrivacySensitiveBrowserState(): void {
  migrateSensitiveBrowserItems([...PRIVACY_SENSITIVE_BROWSER_KEYS]);
}

export const MAX_FEEDS = 50;

export function formatFeedSettingsError(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : String(error || '');
  if (!message) return fallback;
  if (message === 'admin_session_required') {
    return 'Admin key required — paste ADMIN_KEY in Settings and unlock operator tools.';
  }
  if (message === 'backend_unavailable' || message === 'local_control_plane_unavailable') {
    return 'Backend unavailable — check that the backend container is running.';
  }
  if (message === 'control_plane_rate_limited') {
    return 'Too many requests — wait a moment and try again.';
  }
  return message;
}

export function validateFeedEntries(feeds: FeedEntry[]): string | null {
  for (const [idx, feed] of feeds.entries()) {
    const name = feed.name.trim();
    const url = feed.url.trim();
    if (!name || !url) {
      return `Feed ${idx + 1} needs both a name and URL before saving.`;
    }
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol)) {
        return `Feed ${idx + 1} must use an http:// or https:// URL.`;
      }
    } catch {
      return `Feed ${idx + 1} has an invalid URL.`;
    }
  }
  return null;
}

// Category colors for the tactical UI
export const CATEGORY_COLORS: Record<string, string> = {
  Aviation: 'text-cyan-400 border-cyan-500/30 bg-cyan-950/20',
  Maritime: 'text-blue-400 border-blue-500/30 bg-blue-950/20',
  Geophysical: 'text-orange-400 border-orange-500/30 bg-orange-950/20',
  Space: 'text-purple-400 border-purple-500/30 bg-purple-950/20',
  Intelligence: 'text-red-400 border-red-500/30 bg-red-950/20',
  Geolocation: 'text-green-400 border-green-500/30 bg-green-950/20',
  Weather: 'text-yellow-400 border-yellow-500/30 bg-yellow-950/20',
  Markets: 'text-emerald-400 border-emerald-500/30 bg-emerald-950/20',
  SIGINT: 'text-rose-400 border-rose-500/30 bg-rose-950/20',
  Reconnaissance: 'text-green-400 border-green-500/30 bg-green-950/20',
};

export function dmRootMonitorTone(state: string | undefined): string {
  switch (String(state || '').toLowerCase()) {
    case 'ok':
      return 'border-green-500/35 bg-green-950/16 text-green-300';
    case 'warning':
      return 'border-yellow-500/35 bg-yellow-950/16 text-yellow-200';
    case 'critical':
      return 'border-red-500/35 bg-red-950/16 text-red-200';
    default:
      return 'border-cyan-500/25 bg-cyan-950/10 text-cyan-200';
  }
}

export function dmRootMonitorLabel(state: string | undefined): string {
  switch (String(state || '').toLowerCase()) {
    case 'ok':
      return 'HEALTHY';
    case 'warning':
      return 'ATTENTION';
    case 'critical':
      return 'BLOCKED';
    default:
      return 'UNKNOWN';
  }
}

export function dmRootUrgencyTone(urgency: string | undefined): string {
  switch (String(urgency || '').toLowerCase()) {
    case 'page':
      return 'border-red-500/35 bg-red-950/18 text-red-200';
    case 'ticket':
      return 'border-yellow-500/35 bg-yellow-950/18 text-yellow-200';
    case 'watch':
      return 'border-cyan-500/35 bg-cyan-950/18 text-cyan-200';
    default:
      return 'border-slate-600/35 bg-slate-900/18 text-slate-300';
  }
}

export function formatAgeWindow(ageS?: number, maxS?: number): string {
  const age = Math.max(0, Number(ageS || 0));
  const max = Math.max(0, Number(maxS || 0));
  const fmt = (value: number) => {
    if (value <= 0) return '0s';
    if (value < 60) return `${value}s`;
    if (value < 3600) return `${Math.round(value / 60)}m`;
    return `${Math.round(value / 3600)}h`;
  };
  return max > 0 ? `${fmt(age)} / ${fmt(max)} max` : fmt(age);
}

export type Tab = 'api-keys' | 'news-feeds' | 'sentinel' | 'sar' | 'protocol';

