import type * as GeoJSON from 'geojson';
// Shared map constants
// Extracted from MaplibreViewer.tsx

// Empty GeoJSON constant — avoids recreating empty objects on every render
export const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
