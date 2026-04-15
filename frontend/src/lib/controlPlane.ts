import { primeAdminSession } from '@/lib/adminSession';
import type {
  DesktopControlCapability,
  DesktopControlSessionProfile,
} from '@/lib/desktopControlContract';
import {
  canInvokeLocalControl,
  hasLocalControlBridge,
  localControlFetch,
} from '@/lib/localControlTransport';

type ControlPlaneOptions = RequestInit & {
  requireAdminSession?: boolean;
  capabilityIntent?: DesktopControlCapability;
  sessionProfileHint?: DesktopControlSessionProfile;
  enforceProfileHint?: boolean;
};

export async function controlPlaneFetch(
  path: string,
  options: ControlPlaneOptions = {},
): Promise<Response> {
  const {
    requireAdminSession = true,
    capabilityIntent,
    sessionProfileHint,
    enforceProfileHint,
    ...init
  } = options;
  const nativePrivilegedPath = hasLocalControlBridge() && canInvokeLocalControl(path, init);
  if (requireAdminSession && !nativePrivilegedPath) {
    await primeAdminSession();
  }
  return localControlFetch(path, {
    ...init,
    capabilityIntent,
    sessionProfileHint,
    enforceProfileHint,
  });
}

export async function controlPlaneJson<T>(
  path: string,
  options: ControlPlaneOptions = {},
): Promise<T> {
  const res = await controlPlaneFetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data?.ok === false) {
    throw new Error(data?.detail || data?.message || 'control_plane_request_failed');
  }
  return data as T;
}
