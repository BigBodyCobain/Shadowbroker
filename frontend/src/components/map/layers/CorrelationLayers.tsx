import { Layer, Source } from 'react-map-gl/maplibre';
import { EMPTY_FC } from '@/components/map/mapConstants';

export function CorrelationLayers() {
  return (
    <Source id="correlations" type="geojson" data={EMPTY_FC}>
      {/* RF Anomaly — grey */}
      <Layer
        id="corr-rf-fill"
        type="fill"
        filter={['==', ['get', 'corr_type'], 'rf_anomaly']}
        minzoom={3}
        paint={{ 'fill-color': '#6b7280', 'fill-opacity': ['get', 'opacity'] }}
      />
      <Layer
        id="corr-rf-outline"
        type="line"
        filter={['==', ['get', 'corr_type'], 'rf_anomaly']}
        minzoom={3}
        paint={{ 'line-color': '#6b7280', 'line-width': 1.5, 'line-opacity': 0.6 }}
      />
      <Layer
        id="corr-rf-label"
        type="symbol"
        filter={['==', ['get', 'corr_type'], 'rf_anomaly']}
        minzoom={3}
        layout={{
          'text-font': ['Noto Sans Bold'],
          'text-field': ['concat', 'RF ANOMALY\n', ['get', 'drivers']],
          'text-size': ['interpolate', ['linear'], ['zoom'], 3, 7, 5, 9, 8, 11],
          'text-allow-overlap': false,
          'text-ignore-placement': false,
        }}
        paint={{ 'text-color': '#9ca3af', 'text-halo-color': '#000000', 'text-halo-width': 1.5 }}
      />
      {/* Military Buildup — red dashed */}
      <Layer
        id="corr-mil-fill"
        type="fill"
        filter={['==', ['get', 'corr_type'], 'military_buildup']}
        minzoom={3}
        paint={{ 'fill-color': '#dc2626', 'fill-opacity': ['get', 'opacity'] }}
      />
      <Layer
        id="corr-mil-outline"
        type="line"
        filter={['==', ['get', 'corr_type'], 'military_buildup']}
        minzoom={3}
        paint={{ 'line-color': '#dc2626', 'line-width': 2, 'line-opacity': 0.7, 'line-dasharray': [4, 2] }}
      />
      <Layer
        id="corr-mil-label"
        type="symbol"
        filter={['==', ['get', 'corr_type'], 'military_buildup']}
        minzoom={3}
        layout={{
          'text-font': ['Noto Sans Bold'],
          'text-field': ['concat', 'MIL BUILDUP\n', ['get', 'drivers']],
          'text-size': ['interpolate', ['linear'], ['zoom'], 3, 7, 5, 9, 8, 11],
          'text-allow-overlap': false,
          'text-ignore-placement': false,
        }}
        paint={{ 'text-color': '#f87171', 'text-halo-color': '#000000', 'text-halo-width': 1.5 }}
      />
      {/* Infrastructure Cascade — black */}
      <Layer
        id="corr-infra-fill"
        type="fill"
        filter={['==', ['get', 'corr_type'], 'infra_cascade']}
        minzoom={3}
        paint={{ 'fill-color': '#1f2937', 'fill-opacity': ['get', 'opacity'] }}
      />
      <Layer
        id="corr-infra-outline"
        type="line"
        filter={['==', ['get', 'corr_type'], 'infra_cascade']}
        minzoom={3}
        paint={{ 'line-color': '#374151', 'line-width': 1.5, 'line-opacity': 0.7 }}
      />
      <Layer
        id="corr-infra-label"
        type="symbol"
        filter={['==', ['get', 'corr_type'], 'infra_cascade']}
        minzoom={3}
        layout={{
          'text-font': ['Noto Sans Bold'],
          'text-field': ['concat', 'INFRA CASCADE\n', ['get', 'drivers']],
          'text-size': ['interpolate', ['linear'], ['zoom'], 3, 7, 5, 9, 8, 11],
          'text-allow-overlap': false,
          'text-ignore-placement': false,
        }}
        paint={{ 'text-color': '#9ca3af', 'text-halo-color': '#000000', 'text-halo-width': 1.5 }}
      />
      {/* Possible Contradiction — amber pulsing, hypothesis not verdict */}
      <Layer
        id="corr-contra-fill"
        type="fill"
        filter={['==', ['get', 'corr_type'], 'contradiction']}
        minzoom={2}
        paint={{ 'fill-color': '#f59e0b', 'fill-opacity': ['get', 'opacity'] }}
      />
      <Layer
        id="corr-contra-outline"
        type="line"
        filter={['==', ['get', 'corr_type'], 'contradiction']}
        minzoom={2}
        paint={{ 'line-color': '#f59e0b', 'line-width': 2, 'line-opacity': 0.7, 'line-dasharray': [6, 3] }}
      />
      <Layer
        id="corr-contra-label"
        type="symbol"
        filter={['==', ['get', 'corr_type'], 'contradiction']}
        minzoom={2}
        layout={{
          'text-font': ['Noto Sans Bold'],
          'text-field': ['concat', '? CONTRADICTION\n', ['get', 'context'], ' · ', ['get', 'drivers']],
          'text-size': ['interpolate', ['linear'], ['zoom'], 2, 7, 5, 9, 8, 11],
          'text-allow-overlap': false,
          'text-ignore-placement': false,
        }}
        paint={{ 'text-color': '#fbbf24', 'text-halo-color': '#000000', 'text-halo-width': 1.5 }}
      />
      {/* Analysis Zone fill */}
      <Layer
        id="corr-analysis-fill"
        type="fill"
        filter={['==', ['get', 'corr_type'], 'analysis_zone']}
        paint={{
          'fill-color': ['match', ['get', 'zone_category'], 'contradiction', '#f59e0b', 'warning', '#ef4444', 'observation', '#3b82f6', 'hypothesis', '#a855f7', '#06b6d4'],
          'fill-opacity': ['get', 'opacity'],
        }}
      />
      <Layer
        id="corr-analysis-outline"
        type="line"
        filter={['==', ['get', 'corr_type'], 'analysis_zone']}
        paint={{
          'line-color': ['match', ['get', 'zone_category'], 'contradiction', '#f59e0b', 'warning', '#ef4444', 'observation', '#3b82f6', 'hypothesis', '#a855f7', '#06b6d4'],
          'line-width': 1.5,
          'line-dasharray': [4, 3],
          'line-opacity': 0.7,
        }}
      />
      <Layer
        id="corr-analysis-label"
        type="symbol"
        filter={['==', ['get', 'corr_type'], 'analysis_zone']}
        minzoom={2}
        layout={{
          'text-font': ['Noto Sans Bold'],
          'text-field': ['concat', ['get', 'zone_title'], '\n', ['get', 'drivers']],
          'text-size': ['interpolate', ['linear'], ['zoom'], 2, 7, 5, 9, 8, 11],
          'text-allow-overlap': false,
          'text-ignore-placement': false,
          'text-max-width': 18,
        }}
        paint={{ 'text-color': '#67e8f9', 'text-halo-color': '#000000', 'text-halo-width': 1.5 }}
      />
    </Source>
  );
}
