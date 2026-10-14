import type { Ship } from '@/types/dashboard';

/**
 * Operator vessel filters from the Data Filters panel. Shared by the worker
 * (regular ship icons) and the main thread (carrier icons and labels) so every
 * ship source honours the same name / type selection.
 */
export function filterShipsByActiveFilters<T extends Pick<Ship, 'name' | 'type'>>(
  ships: T[] | undefined,
  activeFilters: Record<string, string[]> | undefined,
): T[] {
  if (!ships) return [];
  const nameSet = activeFilters?.ship_name?.length ? new Set(activeFilters.ship_name) : null;
  const typeSet = activeFilters?.ship_type?.length ? new Set(activeFilters.ship_type) : null;
  if (!nameSet && !typeSet) return ships;
  return ships.filter((s) => {
    if (nameSet && !nameSet.has(s.name)) return false;
    if (typeSet && !typeSet.has(s.type)) return false;
    return true;
  });
}
