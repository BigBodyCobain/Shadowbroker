import type { SelectedEntity } from '@/types/dashboard';

const GRAPH_TYPES = new Set(['aircraft', 'vessel', 'company', 'person', 'ip', 'country']);

const SELECTION_TO_GRAPH: Record<string, string> = {
  flight: 'aircraft',
  private_flight: 'aircraft',
  military_flight: 'aircraft',
  private_jet: 'aircraft',
  tracked_flight: 'aircraft',
  ship: 'vessel',
};

export function mapEntityToGraphType(type: string): string | null {
  const mapped = SELECTION_TO_GRAPH[type] || type;
  return GRAPH_TYPES.has(mapped) ? mapped : null;
}

export function isEntityGraphEligible(entity: SelectedEntity | null | undefined): boolean {
  if (!entity) return false;
  return mapEntityToGraphType(entity.type) !== null;
}
