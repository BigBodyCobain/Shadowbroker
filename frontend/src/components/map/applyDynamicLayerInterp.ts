import { interpolatePosition } from '@/utils/positioning';
import type { DynamicMapLayersResult } from '@/components/map/dynamicMapLayers.worker';

const UNBOUNDED_INTERP_SECONDS = Number.POSITIVE_INFINITY;

type InterpProps = {
  baseLat?: number;
  baseLng?: number;
  spd?: number | null;
  hdg?: number | null;
  alt?: number | null;
  kind?: 'flight' | 'ship';
};

function interpCoords(props: InterpProps, dtSeconds: number): [number, number] | null {
  const lat = props.baseLat;
  const lng = props.baseLng;
  if (typeof lat !== 'number' || typeof lng !== 'number') return null;
  const spd = props.spd;
  if (!spd || spd <= 0 || dtSeconds <= 0) return [lng, lat];

  if (props.kind === 'flight') {
    if (props.alt != null && props.alt <= 100) return [lng, lat];
    if (dtSeconds < 1) return [lng, lat];
  }

  const heading = props.hdg || 0;
  const [newLat, newLng] = interpolatePosition(
    lat,
    lng,
    heading,
    spd,
    dtSeconds,
    0,
    UNBOUNDED_INTERP_SECONDS,
  );
  return [newLng, newLat];
}

function applyInterpToCollection(
  fc: GeoJSON.FeatureCollection | null,
  dtSeconds: number,
): GeoJSON.FeatureCollection | null {
  if (!fc?.features?.length || dtSeconds <= 0) return fc;

  let changed = false;
  const features = fc.features.map((feature) => {
    const props = (feature.properties || {}) as InterpProps;
    if (props.baseLat == null || props.baseLng == null) return feature;
    if (!props.spd || props.spd <= 0) return feature;

    const coords = interpCoords(props, dtSeconds);
    if (!coords) return feature;

    const geom = feature.geometry;
    if (!geom || geom.type !== 'Point') return feature;
    const [oldLng, oldLat] = geom.coordinates;
    if (oldLng === coords[0] && oldLat === coords[1]) return feature;

    changed = true;
    return {
      ...feature,
      geometry: {
        type: 'Point' as const,
        coordinates: coords,
      },
    };
  });

  if (!changed) return fc;
  return { type: 'FeatureCollection', features };
}

/**
 * Re-apply dead-reckoning between backend polls without rebuilding layer
 * FeatureCollections in the dynamic map worker.
 *
 * Expects features stamped with baseLat/baseLng/spd/hdg(/alt/kind) by the worker.
 */
export function applyDynamicLayerInterp(
  layers: DynamicMapLayersResult,
  dtSeconds: number,
): DynamicMapLayersResult {
  if (dtSeconds <= 0) return layers;
  return {
    commercialFlightsGeoJSON: applyInterpToCollection(layers.commercialFlightsGeoJSON, dtSeconds),
    privateFlightsGeoJSON: applyInterpToCollection(layers.privateFlightsGeoJSON, dtSeconds),
    privateJetsGeoJSON: applyInterpToCollection(layers.privateJetsGeoJSON, dtSeconds),
    militaryFlightsGeoJSON: applyInterpToCollection(layers.militaryFlightsGeoJSON, dtSeconds),
    trackedFlightsGeoJSON: applyInterpToCollection(layers.trackedFlightsGeoJSON, dtSeconds),
    shipsGeoJSON: applyInterpToCollection(layers.shipsGeoJSON, dtSeconds),
    meshtasticGeoJSON: layers.meshtasticGeoJSON,
    aprsGeoJSON: layers.aprsGeoJSON,
  };
}
