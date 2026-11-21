import { useMemo } from 'react';
import { trackedFlightsWithIcons, shipsWithIcons } from '@/components/map/mapHelpers';
import { filterShipsByActiveFilters } from '@/components/map/shipFilterUtils';
import { buildCarriersGeoJSON } from '@/components/map/geojsonBuilders';

export function useMapLabelData(ctx: any) {
  const { data, dynamicMapLayers } = ctx;
  const trackedFlightsForLabels = useMemo(
    () => trackedFlightsWithIcons(data?.tracked_flights, dynamicMapLayers.trackedFlightsGeoJSON),
    [data?.tracked_flights, dynamicMapLayers.trackedFlightsGeoJSON],
  );
  const shipsForYachtLabels = useMemo(
    () => shipsWithIcons(data?.ships, dynamicMapLayers.shipsGeoJSON),
    [data?.ships, dynamicMapLayers.shipsGeoJSON],
  );
  return { trackedFlightsForLabels, shipsForYachtLabels };
}

export function useMapCarrierData(ctx: any) {
  const { activeLayers, data, activeFilters } = ctx;
  const carrierShips = useMemo(
    () => (activeLayers.ships_military ? filterShipsByActiveFilters(data?.ships, activeFilters) : []),
    [activeLayers.ships_military, data?.ships, activeFilters],
  );
  const carriersGeoJSON = useMemo(
    () => (activeLayers.ships_military ? buildCarriersGeoJSON(carrierShips) : null),
    [activeLayers.ships_military, carrierShips],
  );
  return { carrierShips, carriersGeoJSON };
}
