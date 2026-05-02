import { API_BASE } from '@/lib/api';
import { hasLocalControlBridge } from '@/lib/localControlTransport';

export interface GateCatalogEntry {
  gate_id: string;
  display_name?: string;
  description?: string;
  message_count?: number;
  fixed?: boolean;
  rules?: {
    min_overall_rep?: number;
  };
}

export interface GateDetailSnapshot {
  ok?: boolean;
  gate_id: string;
  display_name?: string;
  description?: string;
  welcome?: string;
  creator_node_id?: string;
  message_count?: number;
  fixed?: boolean;
  rules?: {
    min_overall_rep?: number;
  };
  detail?: string;
}

const GATE_CATALOG_BROWSER_TTL_MS = 18_000;
const GATE_CATALOG_NATIVE_TTL_MS = 6_000;
const GATE_DETAIL_BROWSER_TTL_MS = 15_000;
const GATE_DETAIL_NATIVE_TTL_MS = 5_000;

let gateCatalogCache: { value: GateCatalogEntry[]; expiresAt: number } | null = null;
const gateDetailCache = new Map<string, { value: GateDetailSnapshot; expiresAt: number }>();

function normalizeGateId(gateId: string): string {
  return String(gateId || '').trim().toLowerCase();
}

function gateCatalogTtlMs(): number {
  return hasLocalControlBridge()
    ? GATE_CATALOG_NATIVE_TTL_MS
    : GATE_CATALOG_BROWSER_TTL_MS;
}

function gateDetailTtlMs(): number {
  return hasLocalControlBridge()
    ? GATE_DETAIL_NATIVE_TTL_MS
    : GATE_DETAIL_BROWSER_TTL_MS;
}

export function invalidateGateCatalogSnapshot(): void {
  gateCatalogCache = null;
}

export function invalidateGateDetailSnapshot(gateId?: string): void {
  const normalized = normalizeGateId(gateId || '');
  if (!normalized) {
    gateDetailCache.clear();
    return;
  }
  gateDetailCache.delete(normalized);
}

export async function fetchGateCatalogSnapshot(
  options: { force?: boolean } = {},
): Promise<GateCatalogEntry[]> {
  if (!options.force && gateCatalogCache && gateCatalogCache.expiresAt > Date.now()) {
    return gateCatalogCache.value;
  }
  try {
    const response = await fetch(`${API_BASE}/api/mesh/gate/list`);
    const data = await response.json().catch(() => ({}));
    const gates = Array.isArray(data?.gates) ? (data.gates as GateCatalogEntry[]) : [];
    gateCatalogCache = {
      value: gates,
      expiresAt: Date.now() + gateCatalogTtlMs(),
    };
    return gates;
  } catch {
    return gateCatalogCache?.value || [];
  }
}

export async function fetchGateDetailSnapshot(
  gateId: string,
  options: { force?: boolean } = {},
): Promise<GateDetailSnapshot> {
  const normalizedGate = normalizeGateId(gateId);
  const cached = gateDetailCache.get(normalizedGate);
  if (!options.force && cached && cached.expiresAt > Date.now()) {
    return cached.value;
  }
  const response = await fetch(`${API_BASE}/api/mesh/gate/${encodeURIComponent(normalizedGate)}`);
  const data = await response.json().catch(() => ({}));
  const detail = {
    ...(data && typeof data === 'object' ? data : {}),
    gate_id: normalizeGateId(String((data as { gate_id?: string } | null)?.gate_id || normalizedGate)),
  } as GateDetailSnapshot;
  if (response.ok && detail.ok !== false) {
    gateDetailCache.set(normalizedGate, {
      value: detail,
      expiresAt: Date.now() + gateDetailTtlMs(),
    });
  }
  return detail;
}
