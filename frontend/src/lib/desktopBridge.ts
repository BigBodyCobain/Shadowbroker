import { createHttpBackedDesktopRuntime } from '@/lib/desktopRuntimeShim';
import type {
  DesktopControlAuditReport,
  DesktopControlCommand,
  LocalControlInvokeMeta,
  LocalControlInvokeRequest,
} from '@/lib/desktopControlContract';
import type { ShadowbrokerLocalControlBridge } from '@/lib/localControlTransport';

export interface ShadowbrokerDesktopRuntime {
  invokeLocalControl?<T = unknown>(
    command: DesktopControlCommand,
    payload?: unknown,
    meta?: LocalControlInvokeMeta,
  ): Promise<T>;
  getNativeControlAuditReport?(limit?: number): DesktopControlAuditReport;
  clearNativeControlAuditReport?(): void;
}

function buildDesktopControlBridge(
  runtime: ShadowbrokerDesktopRuntime,
): ShadowbrokerLocalControlBridge | null {
  if (!runtime.invokeLocalControl) return null;
  return {
    invoke<T = unknown>(input: LocalControlInvokeRequest): Promise<T> {
      return runtime.invokeLocalControl!(input.command, input.payload, input.meta);
    },
  };
}

export function installDesktopControlBridge(runtime: ShadowbrokerDesktopRuntime): boolean {
  if (typeof window === 'undefined') return false;
  const bridge = buildDesktopControlBridge(runtime);
  if (!bridge) return false;
  window.__SHADOWBROKER_LOCAL_CONTROL__ = bridge;
  window.__SHADOWBROKER_DESKTOP__ = runtime;
  return true;
}

export function bootstrapDesktopControlBridge(): boolean {
  if (typeof window === 'undefined') return false;
  const runtime =
    window.__SHADOWBROKER_DESKTOP__ ||
    (process.env.NEXT_PUBLIC_ENABLE_DESKTOP_BRIDGE_SHIM === '1'
      ? createHttpBackedDesktopRuntime()
      : undefined);
  if (!runtime) return false;
  return installDesktopControlBridge(runtime);
}

export function getDesktopNativeControlAuditReport(limit?: number): DesktopControlAuditReport | null {
  if (typeof window === 'undefined') return null;
  const runtime = window.__SHADOWBROKER_DESKTOP__;
  return runtime?.getNativeControlAuditReport?.(limit) || null;
}
