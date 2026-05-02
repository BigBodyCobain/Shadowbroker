export interface LegacyCompatibilitySunsetEntry {
  target_version?: string;
  target_date?: string;
  status?: string;
  block_env?: string;
  blocked?: boolean;
}

export interface LegacyCompatibilityUsageBucket {
  count?: number;
  blocked_count?: number;
  last_seen_at?: number;
  recent_targets?: Array<Record<string, unknown>>;
}

export interface LegacyCompatibilitySnapshot {
  sunset?: {
    legacy_node_id_binding?: LegacyCompatibilitySunsetEntry;
    legacy_agent_id_lookup?: LegacyCompatibilitySunsetEntry;
  };
  usage?: {
    legacy_node_id_binding?: LegacyCompatibilityUsageBucket;
    legacy_agent_id_lookup?: LegacyCompatibilityUsageBucket;
  };
}

export interface LegacyCompatibilitySummaryItem {
  key: 'legacy_node_id_binding' | 'legacy_agent_id_lookup';
  label: string;
  blocked: boolean;
  count: number;
  blockedCount: number;
  lastSeenAt: number;
  targetVersion: string;
  targetDate: string;
  recentTargets: string[];
}

function safeInt(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : 0;
}

function shortId(value: unknown): string {
  const text = String(value || '').trim().toLowerCase();
  if (!text) return 'unknown';
  if (text.length <= 14) return text;
  return `${text.slice(0, 10)}...`;
}

function normalizeKinds(value: unknown): string {
  const items = Array.isArray(value)
    ? value
        .map((item) => String(item || '').trim().toLowerCase())
        .filter(Boolean)
    : [];
  return items.length ? items.join(', ') : 'compat';
}

function formatRecentTargets(
  key: LegacyCompatibilitySummaryItem['key'],
  entries: Array<Record<string, unknown>> | undefined,
): string[] {
  const normalized = Array.isArray(entries) ? entries : [];
  if (key === 'legacy_node_id_binding') {
    return normalized
      .slice(0, 2)
      .map((entry) => `${shortId(entry.node_id)} -> ${shortId(entry.current_node_id)}`);
  }
  return normalized
    .slice(0, 2)
    .map((entry) => `${shortId(entry.agent_id)} (${normalizeKinds(entry.lookup_kinds)})`);
}

export function formatLegacyCompatibilitySeenAt(timestamp: number): string {
  if (!timestamp) return 'never';
  try {
    return new Date(timestamp * 1000).toISOString().replace('T', ' ').slice(0, 16) + 'Z';
  } catch {
    return 'never';
  }
}

export function summarizeLegacyCompatibility(
  snapshot: LegacyCompatibilitySnapshot | null | undefined,
): LegacyCompatibilitySummaryItem[] {
  const current = snapshot || {};
  const nodeSunset = current.sunset?.legacy_node_id_binding || {};
  const lookupSunset = current.sunset?.legacy_agent_id_lookup || {};
  const nodeUsage = current.usage?.legacy_node_id_binding || {};
  const lookupUsage = current.usage?.legacy_agent_id_lookup || {};

  return [
    {
      key: 'legacy_node_id_binding',
      label: 'Legacy node-ID compat',
      blocked: Boolean(nodeSunset.blocked),
      count: safeInt(nodeUsage.count),
      blockedCount: safeInt(nodeUsage.blocked_count),
      lastSeenAt: safeInt(nodeUsage.last_seen_at),
      targetVersion: String(nodeSunset.target_version || '').trim() || 'n/a',
      targetDate: String(nodeSunset.target_date || '').trim() || 'n/a',
      recentTargets: formatRecentTargets(
        'legacy_node_id_binding',
        nodeUsage.recent_targets,
      ),
    },
    {
      key: 'legacy_agent_id_lookup',
      label: 'Legacy agent lookup',
      blocked: Boolean(lookupSunset.blocked),
      count: safeInt(lookupUsage.count),
      blockedCount: safeInt(lookupUsage.blocked_count),
      lastSeenAt: safeInt(lookupUsage.last_seen_at),
      targetVersion: String(lookupSunset.target_version || '').trim() || 'n/a',
      targetDate: String(lookupSunset.target_date || '').trim() || 'n/a',
      recentTargets: formatRecentTargets(
        'legacy_agent_id_lookup',
        lookupUsage.recent_targets,
      ),
    },
  ];
}

export function hasLegacyCompatibilityActivity(
  snapshot: LegacyCompatibilitySnapshot | null | undefined,
): boolean {
  return summarizeLegacyCompatibility(snapshot).some(
    (item) => item.count > 0 || item.blockedCount > 0,
  );
}
