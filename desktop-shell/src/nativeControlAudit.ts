import type {
  DesktopControlAuditOutcome,
  DesktopControlAuditRecord,
  DesktopControlAuditReport,
} from '../../frontend/src/lib/desktopControlContract';
import type { NativeControlAuditEvent, NativeControlAuditTrail } from './types';

const DEFAULT_LIMIT = 100;

function incrementOutcome(
  counts: Partial<Record<DesktopControlAuditOutcome, number>>,
  outcome: DesktopControlAuditOutcome,
) {
  counts[outcome] = (counts[outcome] || 0) + 1;
}

export function createNativeControlAuditTrail(maxEntries: number = DEFAULT_LIMIT): NativeControlAuditTrail {
  const entries: DesktopControlAuditRecord[] = [];
  let totalRecorded = 0;

  return {
    record(event: NativeControlAuditEvent) {
      totalRecorded += 1;
      entries.push({
        ...event,
        recordedAt: Date.now(),
      });
      if (entries.length > maxEntries) {
        entries.splice(0, entries.length - maxEntries);
      }
    },
    snapshot(limit: number = 25): DesktopControlAuditReport {
      const recent = entries.slice(-Math.max(1, limit)).reverse();
      const byOutcome: Partial<Record<DesktopControlAuditOutcome, number>> = {};
      let lastProfileMismatch: DesktopControlAuditRecord | undefined;
      let lastDenied: DesktopControlAuditRecord | undefined;
      for (const entry of entries) {
        incrementOutcome(byOutcome, entry.outcome);
        if (entry.outcome === 'profile_warn' || entry.outcome === 'profile_denied') {
          lastProfileMismatch = entry;
        }
        if (entry.outcome === 'profile_denied' || entry.outcome === 'capability_denied') {
          lastDenied = entry;
        }
      }
      return {
        totalEvents: entries.length,
        totalRecorded,
        recent,
        byOutcome,
        lastProfileMismatch,
        lastDenied,
      };
    },
    clear() {
      totalRecorded = 0;
      entries.splice(0, entries.length);
    },
  };
}
