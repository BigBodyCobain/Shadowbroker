// Client for the Intelligence Investigation backend API.
//
// All calls use relative paths through the Next.js catch-all proxy
// (src/app/api/[...path]/route.ts), which injects the operator admin key for
// these sensitive routes server-side. Errors surface as thrown ApiError so the
// UI can render proper error states.

import type {
  Briefing,
  Entity,
  Evidence,
  Hypothesis,
  Investigation,
  InvestigationBundle,
  Note,
  TimelineItem,
} from '@/types/investigation';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    });
  } catch (e) {
    throw new ApiError(`Network error: ${(e as Error).message}`, 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail || `Request failed (${res.status})`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// -- Investigations --------------------------------------------------------- //
export function listInvestigations(status = ''): Promise<{ investigations: Investigation[]; count: number }> {
  const q = status ? `?status=${encodeURIComponent(status)}` : '';
  return req(`/api/investigations${q}`);
}

export function createInvestigation(body: {
  title: string;
  question?: string;
  description?: string;
  tags?: string[];
}): Promise<Investigation> {
  return req('/api/investigations', { method: 'POST', body: JSON.stringify(body) });
}

export function getInvestigation(id: string): Promise<InvestigationBundle> {
  return req(`/api/investigations/${encodeURIComponent(id)}`);
}

export function updateInvestigation(
  id: string,
  patch: Partial<{ title: string; question: string; description: string; status: string; tags: string[] }>,
): Promise<Investigation> {
  return req(`/api/investigations/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

export function deleteInvestigation(id: string): Promise<{ ok: boolean }> {
  return req(`/api/investigations/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

// -- Members ---------------------------------------------------------------- //
export function addEvent(
  invId: string,
  body: Record<string, unknown>,
): Promise<DomainEventLite> {
  return req(`/api/investigations/${encodeURIComponent(invId)}/events`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function addEvidence(invId: string, body: Record<string, unknown>): Promise<Evidence> {
  return req(`/api/investigations/${encodeURIComponent(invId)}/evidence`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function deleteEvidence(invId: string, evidenceId: string): Promise<{ ok: boolean }> {
  return req(
    `/api/investigations/${encodeURIComponent(invId)}/evidence/${encodeURIComponent(evidenceId)}`,
    { method: 'DELETE' },
  );
}

export function createHypothesis(
  invId: string,
  body: { statement: string; supporting_evidence_ids?: string[]; contradicting_evidence_ids?: string[] },
): Promise<Hypothesis> {
  return req(`/api/investigations/${encodeURIComponent(invId)}/hypotheses`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function updateHypothesis(
  invId: string,
  hypId: string,
  patch: Record<string, unknown>,
): Promise<Hypothesis> {
  return req(
    `/api/investigations/${encodeURIComponent(invId)}/hypotheses/${encodeURIComponent(hypId)}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
}

export function addNote(invId: string, body: string): Promise<Note> {
  return req(`/api/investigations/${encodeURIComponent(invId)}/notes`, {
    method: 'POST',
    body: JSON.stringify({ body }),
  });
}

export function getTimeline(invId: string): Promise<{ timeline: TimelineItem[] }> {
  return req(`/api/investigations/${encodeURIComponent(invId)}/timeline`);
}

export function getBriefing(invId: string): Promise<Briefing> {
  return req(`/api/investigations/${encodeURIComponent(invId)}/briefing`);
}

// -- Entities --------------------------------------------------------------- //
export function searchEntities(q: string, type = ''): Promise<{ entities: Entity[]; count: number }> {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (type) params.set('type', type);
  return req(`/api/entities/search?${params.toString()}`);
}

export function getEntity(
  id: string,
): Promise<{ entity: Entity; observations: unknown[]; relationships: unknown[] }> {
  return req(`/api/entities/${encodeURIComponent(id)}`);
}

// Minimal shape returned by addEvent (a domain Event dict).
type DomainEventLite = { id: string; title: string; classification: string };
