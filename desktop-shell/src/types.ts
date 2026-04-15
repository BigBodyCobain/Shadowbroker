import type {
  DesktopControlAuditEvent,
  DesktopControlAuditReport,
  DesktopControlCapability,
  DesktopControlCommand,
  DesktopControlPayloadMap,
  DesktopControlSessionProfile,
  LocalControlInvokeMeta,
} from '../../frontend/src/lib/desktopControlContract';

export type NativeControlHandlerContext = {
  backendBaseUrl: string;
  wormholeBaseUrl: string;
  adminKey?: string;
  allowedCapabilities?: DesktopControlCapability[];
  sessionProfile?: DesktopControlSessionProfile;
  enforceSessionProfile?: boolean;
  auditControlUse?: (event: NativeControlAuditEvent) => void;
  auditTrail?: NativeControlAuditTrail;
};

export type NativeControlExecutor = <T = unknown>(
  path: string,
  init?: RequestInit,
) => Promise<T>;

export type NativeControlHandlerMap = {
  [K in DesktopControlCommand]: (
    payload: DesktopControlPayloadMap[K],
    ctx: NativeControlHandlerContext,
    exec: NativeControlExecutor,
  ) => Promise<unknown>;
};

export type NativeControlInvokeMeta = LocalControlInvokeMeta;

export type NativeControlAuditEvent = DesktopControlAuditEvent;

export type NativeControlAuditTrail = {
  record: (event: NativeControlAuditEvent) => void;
  snapshot: (limit?: number) => DesktopControlAuditReport;
  clear: () => void;
};
