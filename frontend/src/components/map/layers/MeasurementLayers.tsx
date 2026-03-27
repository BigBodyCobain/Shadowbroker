import { Layer, Marker, Source } from 'react-map-gl/maplibre';

export function MeasurementLayers({
  measurePoints,
}: {
  measurePoints: { lat: number; lng: number }[] | undefined;
}) {
  if (!measurePoints || measurePoints.length === 0) return null;

  return (
    <>
      {measurePoints.length >= 2 && (
        <Source
          id="measure-lines"
          type="geojson"
          data={{
            type: 'FeatureCollection',
            features: [
              {
                type: 'Feature',
                properties: {},
                geometry: {
                  type: 'LineString',
                  coordinates: measurePoints.map((p) => [p.lng, p.lat]),
                },
              },
            ],
          }}
        >
          <Layer
            id="measure-lines-layer"
            type="line"
            paint={{
              'line-color': '#00ffff',
              'line-width': 2,
              'line-dasharray': [4, 3],
              'line-opacity': 0.8,
            }}
          />
        </Source>
      )}

      {measurePoints.map((pt, idx) => (
        <Marker key={`measure-${idx}`} longitude={pt.lng} latitude={pt.lat} anchor="center">
          <div className="flex flex-col items-center pointer-events-none">
            <div className="w-6 h-6 rounded-full border-2 border-cyan-400 animate-ping absolute opacity-20" />
            <div className="w-4 h-4 rounded-full bg-cyan-500 border-2 border-cyan-300 shadow-[0_0_12px_rgba(0,255,255,0.6)] flex items-center justify-center">
              <span className="text-[7px] font-mono font-bold text-black">{idx + 1}</span>
            </div>
          </div>
        </Marker>
      ))}
    </>
  );
}
