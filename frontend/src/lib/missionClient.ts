import { API_BASE } from './api';
import { executeClientVerb, type ClientToolContext, type ToolResult } from './clientTools';
import type { GroundingSnapshot } from './voiceGroundingTypes';

export interface MissionRole {
  role: 'coordinator' | 'researcher' | 'analyst' | 'reviewer';
  provider: string;
  model: string;
  max_calls: number;
  calls?: number;
}
export interface MissionEvidence {
  id: string;
  title: string;
  url: string;
  summary: string;
  tool: string;
  at: number;
  pinned: boolean;
  ok?: boolean;
}
export interface MissionSummary {
  id: string;
  objective: string;
  status: string;
  reason: string;
  calls: number;
  max_calls: number;
  updated_at: number;
}
export interface Mission extends MissionSummary {
  history_truncated?: boolean;
  revision: number;
  owner: string;
  role_index: number;
  roles: MissionRole[];
  pending: {
    id: string;
    kind: string;
    owner: string;
    tool: string;
    args: Record<string, unknown>;
    started: boolean;
    deadline?: number;
  } | null;
  events: Array<{
    id: string;
    kind: string;
    text: string;
    at: number;
    role?: string;
    ok?: boolean;
    result?: string;
  }>;
  evidence: MissionEvidence[];
  reports: Array<{ role: string; text: string; at: number }>;
}
export interface Watch {
  id: string;
  type: string;
  params: Record<string, unknown>;
  paused?: boolean;
  fires: number;
  last_checked?: number;
  last_fired?: number;
  last_alert?: unknown;
  mission_id?: string;
}
export interface MissionConfiguration {
  provider: string;
  model: string;
  providers: Array<{ id: string; label: string }>;
  role_purposes: Record<string, string>;
}
export type MissionBindings = ClientToolContext & {
  selectedEntity?: { id: string | number; type: string } | null;
};

export async function missionRequest<T>(
  path: string,
  body?: unknown,
  method?: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${API_BASE}/api/voice/${path}`, {
    method: method || (body === undefined ? 'GET' : 'POST'),
    ...(body === undefined
      ? {}
      : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    signal,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item: { msg?: string }) => item.msg || 'Invalid request').join('; ')
      : data.detail;
    throw new Error(String(detail || data.error || `HTTP ${response.status}`));
  }
  return data as T;
}

export async function executeMissionAction(
  mission: Mission,
  dashboard: string,
  bindings: () => MissionBindings,
  getSnapshot: () => Promise<GroundingSnapshot>,
  signal: AbortSignal,
): Promise<Mission> {
  const action = mission.pending;
  if (!action || action.kind !== 'client' || action.owner !== dashboard || action.started)
    throw new Error('Unconfirmed browser action: skip it explicitly before resuming');
  signal.throwIfAborted();
  const started = await missionRequest<{ mission: Mission }>(
    `missions/${mission.id}/client-start`,
    { dashboard, action_id: action.id },
    undefined,
    signal,
  );
  if (started.mission.status !== 'waiting_client') return started.mission;
  signal.throwIfAborted();
  let result: ToolResult;
  let snapshot: GroundingSnapshot | undefined;
  try {
    result = await executeClientVerb(action.tool, action.args, bindings());
    snapshot = await getSnapshot();
    const currentBindings = bindings();
    const selection =
      'selectedEntity' in currentBindings ? currentBindings.selectedEntity : snapshot.selection;
    if ('selectedEntity' in currentBindings)
      snapshot = {
        ...snapshot,
        selection: selection
          ? { id: String(selection.id).slice(0, 64), type: selection.type.slice(0, 32) }
          : null,
      };
    if (result.ok && (action.tool === 'open_article' || action.tool === 'select_entity')) {
      const article = result.article as { id?: string } | undefined;
      const entity = result.entity as { id?: string; layer?: string } | undefined;
      const expected = article?.id || entity?.id;
      const expectedType = article ? 'news' : entity?.layer;
      if (
        !expected ||
        String(selection?.id ?? '') !== expected ||
        (expectedType && selection?.type !== expectedType)
      )
        result = {
          ...result,
          ok: false,
          error: 'Requested selection was not confirmed by the dashboard',
        };
    }
    if (result.ok && action.tool === 'clear_selection' && selection)
      result = {
        ...result,
        ok: false,
        error: 'Selection clear was not confirmed by the dashboard',
      };
  } catch (error) {
    result = {
      ok: false,
      action: action.tool,
      error: error instanceof Error ? error.message : 'Dashboard action failed',
    };
  }
  if (new TextEncoder().encode(JSON.stringify(result)).length > 12000)
    result = {
      ok: false,
      action: action.tool,
      error: 'Dashboard result exceeded the receipt limit',
    };
  // Send the outcome even if cancellation arrived after execution. The server
  // records it without restarting a paused/cancelled mission.
  const receipt = await missionRequest<{ mission: Mission }>(`missions/${mission.id}/receipt`, {
    dashboard,
    action_id: action.id,
    result,
    ...(snapshot ? { snapshot } : {}),
  });
  return receipt.mission;
}
