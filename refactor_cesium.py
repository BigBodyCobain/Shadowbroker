import re

with open('frontend/src/components/CesiumViewer.tsx', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace removeAll with diffing setup
setup_code = """        // Handle Entities gracefully to prevent stutter
        viewer.entities.suspendEvents();
        const touchedIds = new Set<string>();

        const addOrUpdate = (props: any) => {
            if (!props.id) props.id = "gen-" + Math.random().toString(36).substr(2, 9);
            touchedIds.add(props.id);
            const existing = viewer.entities.getById(props.id);
            if (existing) {
                if (props.position) existing.position = props.position;
                if (props.label && existing.label) existing.label.text = props.label.text;
                if (props.billboard && existing.billboard) {
                    existing.billboard.rotation = props.billboard.rotation;
                    existing.billboard.image = props.billboard.image;
                }
                if (props.polyline && existing.polyline) existing.polyline.positions = props.polyline.positions;
            } else {
                viewer.entities.add(props);
            }
        };"""

code = code.replace("        viewer.entities.removeAll();", setup_code)

# Replace all viewer.entities.add({ with addOrUpdate({
code = code.replace("viewer.entities.add({", "addOrUpdate({")

# Add missing IDs for flight origin/dest/polyline dynamically
code = re.sub(
    r"addOrUpdate\(\{\s*position: Cesium\.Cartesian3\.fromDegrees\(flight\.origin_loc",
    r"addOrUpdate({\n                    id: `sel-origin-${selectedEntity.entityId}`,\n                    position: Cesium.Cartesian3.fromDegrees(flight.origin_loc",
    code
)
code = re.sub(
    r"addOrUpdate\(\{\s*position: Cesium\.Cartesian3\.fromDegrees\(flight\.dest_loc",
    r"addOrUpdate({\n                    id: `sel-dest-${selectedEntity.entityId}`,\n                    position: Cesium.Cartesian3.fromDegrees(flight.dest_loc",
    code
)
code = re.sub(
    r"addOrUpdate\(\{\s*polyline: \{\s*positions: Cesium\.Cartesian3\.fromDegreesArrayHeights\(\[",
    r"addOrUpdate({\n                    id: `sel-poly-${selectedEntity.entityId}`,\n                    polyline: {\n                        positions: Cesium.Cartesian3.fromDegreesArrayHeights([",
    code
)

# Weather layer pruning
code = code.replace(
"""        // Process Weather Radar
        if (data.weather && activeLayers?.weather !== false) {
            let weatherLayer = viewer.imageryLayers._layers.find((l: any) => l.imageryProvider.url && l.imageryProvider.url.includes("rainviewer"));
            if (!weatherLayer) {
                viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
                    url: `${data.weather.host} / v2 / radar / ${data.weather.time} / 256 / { z } / { x } / { y } / 2 / 1_1.png`,
                    credit: ""
                }), 1); // Add just above base map
            }
        } else {
            const weatherLayer = viewer.imageryLayers._layers.find((l: any) => l.imageryProvider.url && l.imageryProvider.url.includes("rainviewer"));
            if (weatherLayer) viewer.imageryLayers.remove(weatherLayer);
        }""",
"""        // Process Weather Radar
        if (data.weather && activeLayers?.weather !== false) {
            const targetUrl = `${data.weather.host}/v2/radar/${data.weather.time}/256/{z}/{x}/{y}/2/1_1.png`;
            let weatherLayer = viewer.imageryLayers._layers.find((l: any) => l.imageryProvider.url && l.imageryProvider.url.includes("rainviewer"));
            
            if (weatherLayer && weatherLayer.imageryProvider.url !== targetUrl) {
                viewer.imageryLayers.remove(weatherLayer);
                weatherLayer = null;
            }
            if (!weatherLayer) {
                viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
                    url: targetUrl,
                    credit: ""
                }), 1);
            }
        } else {
            const weatherLayer = viewer.imageryLayers._layers.find((l: any) => l.imageryProvider.url && l.imageryProvider.url.includes("rainviewer"));
            if (weatherLayer) viewer.imageryLayers.remove(weatherLayer);
        }"""
)

# Insert resume events
code = code.replace(
    "    }, [data, activeLayers, effects, selectedEntity]);",
"""
        // Prune unused entities
        const allEntities = viewer.entities.values;
        for (let i = allEntities.length - 1; i >= 0; i--) {
            const e = allEntities[i];
            if (!touchedIds.has(e.id)) {
                viewer.entities.remove(e);
            }
        }
        viewer.entities.resumeEvents();
    }, [data, activeLayers, effects, selectedEntity]);"""
)

with open('frontend/src/components/CesiumViewer.tsx', 'w', encoding='utf-8') as f:
    f.write(code)

print("CesiumViewer refactored.")
