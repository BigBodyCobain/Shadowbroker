import { describe, expect, it } from 'vitest';

import {
  formatLegacyCompatibilitySeenAt,
  hasLegacyCompatibilityActivity,
  summarizeLegacyCompatibility,
  type LegacyCompatibilitySnapshot,
} from '@/mesh/wormholeCompatibility';

describe('wormholeCompatibility helpers', () => {
  it('summarizes empty snapshots with zeroed metrics', () => {
    const items = summarizeLegacyCompatibility(undefined);

    expect(items).toHaveLength(2);
    expect(items[0]).toMatchObject({
      key: 'legacy_node_id_binding',
      blocked: false,
      count: 0,
      blockedCount: 0,
      targetVersion: 'n/a',
      targetDate: 'n/a',
      recentTargets: [],
    });
    expect(items[1]).toMatchObject({
      key: 'legacy_agent_id_lookup',
      blocked: false,
      count: 0,
      blockedCount: 0,
      targetVersion: 'n/a',
      targetDate: 'n/a',
      recentTargets: [],
    });
    expect(hasLegacyCompatibilityActivity(undefined)).toBe(false);
  });

  it('formats legacy usage, block state, and recent targets', () => {
    const snapshot: LegacyCompatibilitySnapshot = {
      sunset: {
        legacy_node_id_binding: {
          target_version: '0.10.0',
          target_date: '2026-06-01',
          blocked: true,
        },
        legacy_agent_id_lookup: {
          target_version: '0.10.0',
          target_date: '2026-06-01',
          blocked: false,
        },
      },
      usage: {
        legacy_node_id_binding: {
          count: 4,
          blocked_count: 2,
          last_seen_at: 1712345678,
          recent_targets: [
            {
              node_id: 'abcdef0123456789',
              current_node_id: 'fedcba9876543210abcdef0123456789',
            },
          ],
        },
        legacy_agent_id_lookup: {
          count: 3,
          blocked_count: 1,
          last_seen_at: 1712345000,
          recent_targets: [
            {
              agent_id: 'agent-xyz-0123456789',
              lookup_kinds: ['prekey_bundle', 'dh_pubkey'],
            },
          ],
        },
      },
    };

    const items = summarizeLegacyCompatibility(snapshot);

    expect(items[0]).toMatchObject({
      blocked: true,
      count: 4,
      blockedCount: 2,
      targetVersion: '0.10.0',
      targetDate: '2026-06-01',
    });
    expect(items[0].recentTargets[0]).toContain('abcdef0123...');
    expect(items[0].recentTargets[0]).toContain('fedcba9876...');
    expect(items[1]).toMatchObject({
      blocked: false,
      count: 3,
      blockedCount: 1,
      targetVersion: '0.10.0',
      targetDate: '2026-06-01',
    });
    expect(items[1].recentTargets[0]).toContain('agent-xyz-...');
    expect(items[1].recentTargets[0]).toContain('prekey_bundle, dh_pubkey');
    expect(hasLegacyCompatibilityActivity(snapshot)).toBe(true);
  });

  it('formats seen timestamps as stable UTC text', () => {
    expect(formatLegacyCompatibilitySeenAt(0)).toBe('never');
    expect(formatLegacyCompatibilitySeenAt(1712345678)).toBe('2024-04-05 19:34Z');
  });
});
