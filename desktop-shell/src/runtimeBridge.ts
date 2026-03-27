import type {
  DesktopControlCommand,
  DesktopControlPayloadMap,
  LocalControlInvokeMeta,
} from '../../frontend/src/lib/desktopControlContract';
import { createNativeControlAuditTrail } from './nativeControlAudit';
import { createNativeControlRouter } from './nativeControlRouter';
import type {
  NativeControlAuditEvent,
  NativeControlExecutor,
  NativeControlHandlerContext,
} from './types';

async function defaultExecutor<T = unknown>(baseUrl: string, path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data?.ok === false) {
    throw new Error(data?.detail || data?.message || 'native_control_request_failed');
  }
  return data as T;
}

export function createRuntimeBridge(ctx: NativeControlHandlerContext) {
  const auditTrail = ctx.auditTrail || createNativeControlAuditTrail();
  const auditControlUse = (event: NativeControlAuditEvent) => {
    auditTrail.record(event);
    ctx.auditControlUse?.(event);
  };
  const exec: NativeControlExecutor = <T = unknown>(path: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    if (ctx.adminKey && !headers.has('X-Admin-Key')) {
      headers.set('X-Admin-Key', ctx.adminKey);
    }
    return defaultExecutor<T>(ctx.backendBaseUrl, path, { ...init, headers });
  };
  function invocationContext(meta?: LocalControlInvokeMeta): NativeControlHandlerContext {
    const baseCtx: NativeControlHandlerContext = {
      ...ctx,
      auditTrail,
      auditControlUse,
    };
    if (ctx.sessionProfile || !meta?.sessionProfileHint) {
      return baseCtx;
    }
    return {
      ...baseCtx,
      sessionProfile: meta.sessionProfileHint,
    };
  }
  return {
    invokeLocalControl<C extends DesktopControlCommand>(
      command: C,
      payload: DesktopControlPayloadMap[C],
      meta?: LocalControlInvokeMeta,
    ) {
      return createNativeControlRouter(invocationContext(meta), exec).invoke(command, payload, meta);
    },
    getNativeControlAuditReport(limit?: number) {
      return auditTrail.snapshot(limit);
    },
    clearNativeControlAuditReport() {
      auditTrail.clear();
    },
  };
}
