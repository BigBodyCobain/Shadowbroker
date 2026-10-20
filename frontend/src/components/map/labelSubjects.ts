import type { Ship, TrackedFlight } from '@/types/dashboard';
import { shipFeatureId, trackedFlightFeatureId } from '@/components/map/featureIds';

/**
 * HTML labels are rendered from the raw store arrays, while the icons come
 * from the worker-built GeoJSON that already has the operator's data filters
 * applied. Restrict the label subjects to entities that actually have an icon
 * so a filtered-out aircraft or yacht does not keep its name on the map.
 */
function featureIds(fc: GeoJSON.FeatureCollection | null | undefined): Set<string> | null {
  if (!fc) return null;
  const ids = new Set<string>();
  for (const feature of fc.features) {
    const id = feature.properties?.id;
    if (id != null) ids.add(String(id));
  }
  return ids;
}

export function trackedFlightsWithIcons(
  flights: TrackedFlight[] | undefined,
  fc: GeoJSON.FeatureCollection | null | undefined,
): TrackedFlight[] {
  const ids = featureIds(fc);
  if (!ids || !flights?.length) return [];
  return flights.filter((f) => ids.has(trackedFlightFeatureId(f)));
}

export function shipsWithIcons(
  ships: Ship[] | undefined,
  fc: GeoJSON.FeatureCollection | null | undefined,
): Ship[] {
  const ids = featureIds(fc);
  if (!ids || !ships?.length) return [];
  return ships.filter((s) => ids.has(shipFeatureId(s)));
}
