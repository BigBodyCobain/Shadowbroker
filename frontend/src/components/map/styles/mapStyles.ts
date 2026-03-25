const GLYPHS = "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf";

const buildRasterStyle = (
    sourceId: string,
    layerId: string,
    tiles: string[],
    attribution?: string
) => ({
    version: 8,
    glyphs: GLYPHS,
    sources: {
        [sourceId]: {
            type: "raster",
            tiles,
            tileSize: 256,
            ...(attribution ? { attribution } : {}),
        },
    },
    layers: [
        { id: layerId, type: "raster", source: sourceId, minzoom: 0, maxzoom: 22 },
        { id: "imagery-ceiling", type: "background", paint: { "background-opacity": 0 } },
    ],
});

export const darkStyle = buildRasterStyle("carto-dark", "carto-dark-layer", [
    "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
    "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
    "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
    "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
]);

export const lightStyle = buildRasterStyle("carto-light", "carto-light-layer", [
    "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
    "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
    "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
    "https://d.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
]);

export const streetsStyle = buildRasterStyle(
    "osm-streets",
    "osm-streets-layer",
    ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
    "© OpenStreetMap contributors"
);

export const terrainStyle = buildRasterStyle(
    "opentopomap",
    "opentopomap-layer",
    [
        "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
        "https://b.tile.opentopomap.org/{z}/{x}/{y}.png",
        "https://c.tile.opentopomap.org/{z}/{x}/{y}.png",
    ],
    "Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)"
);
