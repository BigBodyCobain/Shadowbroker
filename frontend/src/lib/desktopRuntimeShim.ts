import { API_BASE } from '@/lib/api';
import {
  controlCommandCapability,
  extractGateTargetRef,
  type DesktopControlAuditRecord,
  type DesktopControlAuditReport,
  type DesktopControlCommand,
  type LocalControlInvokeMeta,
} from '@/lib/desktopControlContract';
import { commandToHttpRequest } from '@/lib/desktopControlRouting';
import type { ShadowbrokerDesktopRuntime } from '@/lib/desktopBridge';

export function createHttpBackedDesktopRuntime(): ShadowbrokerDesktopRuntime {
  const auditEntries: DesktopControlAuditRecord[] = [];
  let totalRecorded = 0;
  const recordAudit = (entry: Omit<DesktopControlAuditRecord, 'recordedAt'>) => {
    totalRecorded += 1;
    auditEntries.push({ ...entry, recordedAt: Date.now() });
    if (auditEntries.length > 50) {
      auditEntries.splice(0, auditEntries.length - 50);
    }
  };
  const snapshotAudit = (limit: number = 10): DesktopControlAuditReport => {
    const recent = auditEntries.slice(-Math.max(1, limit)).reverse();
    const byOutcome: DesktopControlAuditReport['byOutcome'] = {};
    let lastDenied: DesktopControlAuditRecord | undefined;
    for (const entry of auditEntries) {
      byOutcome[entry.outcome] = (byOutcome[entry.outcome] || 0) + 1;
      if (entry.outcome === 'shim_refused' || entry.outcome === 'profile_denied') {
        lastDenied = entry;
      }
    }
    return {
      totalEvents: auditEntries.length,
      totalRecorded,
      recent,
      byOutcome,
      lastDenied,
    };
  };
  return {
    async invokeLocalControl<T = unknown>(
      command: DesktopControlCommand,
      payload?: unknown,
      meta?: LocalControlInvokeMeta,
    ): Promise<T> {
      if (meta?.enforceProfileHint) {
        recordAudit({
          command,
          expectedCapability: controlCommandCapability(command),
          declaredCapability: meta.capability,
          targetRef: extractGateTargetRef(command, payload),
          sessionProfileHint: meta.sessionProfileHint,
          enforceProfileHint: true,
          profileAllows: false,
          allowedCapabilitiesConfigured: false,
          enforced: true,
          outcome: 'shim_refused',
        });
        console.warn(
          '[desktop-shim] strict native session-profile enforcement is unavailable in the HTTP-backed shim',
          { command, sessionProfileHint: meta.sessionProfileHint },
        );
        throw new Error('desktop_runtime_shim_enforcement_inactive');
      }
      const request = commandToHttpRequest(command, payload);
      const res = await fetch(`${API_BASE}${request.path}`, {
        method: request.method,
        headers: request.payload ? { 'Content-Type': 'application/json' } : undefined,
        body: request.payload ? JSON.stringify(request.payload) : undefined,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.ok === false) {
        throw new Error(data?.detail || data?.message || 'desktop_shim_request_failed');
      }
      return data as T;
    },
    getNativeControlAuditReport(limit?: number) {
      return snapshotAudit(limit);
    },
    clearNativeControlAuditReport() {
      totalRecorded = 0;
      auditEntries.splice(0, auditEntries.length);
    },
  };
}
