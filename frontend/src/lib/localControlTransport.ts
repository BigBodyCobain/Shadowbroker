import { API_BASE } from '@/lib/api';
import type {
  DesktopControlCapability,
  DesktopControlSessionProfile,
  LocalControlInvokeRequest,
} from '@/lib/desktopControlContract';
import { httpRequestToInvokeRequest } from '@/lib/desktopControlRouting';

export interface LocalControlBridgeResponse {
  status: number;
  headers?: Record<string, string>;
  bodyText?: string;
}

export interface LocalControlBridgeRequest {
  path: string;
  method: string;
  headers: Record<string, string>;
  bodyText?: string;
}

export type LocalControlFetchOptions = RequestInit & {
  capabilityIntent?: DesktopControlCapability;
  sessionProfileHint?: DesktopControlSessionProfile;
  enforceProfileHint?: boolean;
};

export interface ShadowbrokerLocalControlBridge {
  request?(input: LocalControlBridgeRequest): Promise<LocalControlBridgeResponse>;
  invoke?<T = unknown>(input: LocalControlInvokeRequest): Promise<T>;
}

function getDesktopBridge(): ShadowbrokerLocalControlBridge | null {
  if (typeof window === 'undefined') return null;
  return window.__SHADOWBROKER_LOCAL_CONTROL__ || null;
}

export function hasLocalControlBridge(): boolean {
  return Boolean(getDesktopBridge());
}

export function canInvokeLocalControl(path: string, init: RequestInit = {}): boolean {
  const bridge = getDesktopBridge();
  if (!bridge?.invoke) return false;
  return Boolean(
    httpRequestToInvokeRequest(path, String(init.method || 'GET'), normalizeBody(init.body)),
  );
}

function normalizeHeaders(headers?: HeadersInit): Record<string, string> {
  const normalized = new Headers(headers);
  const result: Record<string, string> = {};
  normalized.forEach((value, key) => {
    result[key] = value;
  });
  return result;
}

function normalizeBody(body: BodyInit | null | undefined): string | undefined {
  if (body == null) return undefined;
  if (typeof body === 'string') return body;
  if (body instanceof URLSearchParams) return body.toString();
  return undefined;
}

export async function localControlFetch(
  path: string,
  init: LocalControlFetchOptions = {},
): Promise<Response> {
  const bridge = getDesktopBridge();
  if (!bridge) {
    return fetch(`${API_BASE}${path}`, init);
  }
  const { capabilityIntent, sessionProfileHint, enforceProfileHint, ...requestInit } = init;
  const invokeRequest = bridge.invoke
    ? httpRequestToInvokeRequest(
        path,
        String(requestInit.method || 'GET'),
        normalizeBody(requestInit.body),
      )
    : null;
  if (bridge.invoke && invokeRequest) {
    try {
      const data = await bridge.invoke({
        ...invokeRequest,
        meta: {
          ...invokeRequest.meta,
          ...(capabilityIntent ? { capability: capabilityIntent } : {}),
          ...(sessionProfileHint ? { sessionProfileHint } : {}),
          ...(enforceProfileHint ? { enforceProfileHint: true } : {}),
        },
      } as LocalControlInvokeRequest);
      return new Response(JSON.stringify(data ?? {}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : typeof error === 'string' ? error : '';
      if (!message.includes('desktop_runtime_shim_enforcement_inactive')) {
        throw error;
      }
    }
  }
  if (!bridge.request) {
    return fetch(`${API_BASE}${path}`, requestInit);
  }
  const response = await bridge.request({
    path,
    method: requestInit.method || 'GET',
    headers: normalizeHeaders(requestInit.headers),
    bodyText: normalizeBody(requestInit.body),
  });
  return new Response(response.bodyText || '', {
    status: response.status,
    headers: response.headers,
  });
}
