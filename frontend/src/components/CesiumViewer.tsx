"use client";

import { useEffect, useRef, useState } from "react";
import * as satellite from 'satellite.js';

export default function CesiumViewer({ data, activeLayers, activeFilters, effects, onEntityClick, selectedEntity, flyToLocation, isEavesdropping, onEavesdropClick, onCameraMove }: { data: any, activeLayers: any, activeFilters?: Record<string, string[]>, effects: any, onEntityClick?: any, selectedEntity?: any, flyToLocation?: { lat: number, lng: number, ts: number } | null, isEavesdropping?: boolean, onEavesdropClick?: (loc: { lat: number, lng: number }) => void, onCameraMove?: (loc: { lat: number, lng: number }) => void }) {
    const cesiumContainer = useRef<HTMLDivElement>(null);
    const viewerRef = useRef<any>(null);
    const flightBillboardsRef = useRef<any>(null);
    const flightLabelsRef = useRef<any>(null);
    const flightPrimitivesRef = useRef<Map<string, { billboard: any, label: any }>>(new Map());
    const shipDataSourceRef = useRef<any>(null);
    const cctvDataSourceRef = useRef<any>(null);
    const [cesiumLoaded, setCesiumLoaded] = useState(false);
    const [popupPosition, setPopupPosition] = useState<{ x: number, y: number } | null>(null);

    // Fly camera to a specific location when triggered by Find/Locate
    useEffect(() => {
        if (!flyToLocation || !viewerRef.current) return;
        const Cesium = (window as any).Cesium;
        if (!Cesium) return;
        viewerRef.current.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(flyToLocation.lng, flyToLocation.lat, 50000),
            orientation: {
                heading: 0,
                pitch: Cesium.Math.toRadians(-45),
                roll: 0,
            },
            duration: 2.0,
        });
    }, [flyToLocation]);

    // Poll for the CDN script to finish downloading
    useEffect(() => {
        const interval = setInterval(() => {
            if (typeof window !== "undefined" && (window as any).Cesium) {
                // Configure base URL before initialization
                (window as any).CESIUM_BASE_URL = "https://cesium.com/downloads/cesiumjs/releases/1.115/Build/Cesium/";
                setCesiumLoaded(true);
                clearInterval(interval);
            }
        }, 100);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        if (!cesiumLoaded || !cesiumContainer.current || viewerRef.current) return;

        const Cesium = (window as any).Cesium;

        // Allow Cesium to use default credentials for its Ion assets if needed (we'll mostly bypass)
        // Cesium.Ion.defaultAccessToken = 'YOUR_EXPERIMENTAL_OR_FREE_TOKEN';

        viewerRef.current = new Cesium.Viewer(cesiumContainer.current, {
            animation: false,
            baseLayerPicker: false,
            fullscreenButton: false,
            geocoder: false,
            homeButton: false,
            infoBox: false,
            sceneModePicker: false,
            selectionIndicator: false,
            timeline: false,
            navigationHelpButton: false,
            navigationInstructionsInitiallyVisible: false,
            scene3DOnly: true,
            skyAtmosphere: false,
            skyBox: false,
            // Automatically render when changes occur
            requestRenderMode: false,
        });

        // Remove the default cesium credit banner for tactical purity
        const credit = viewerRef.current.bottomContainer;
        if (credit) credit.style.display = "none";

        const scene = viewerRef.current.scene;
        scene.globe.baseColor = Cesium.Color.BLACK;

        // High-resolution Satellite layer via Mapbox for a realistic earth
        const mapboxToken = "YOUR_MAPBOX_TOKEN_HERE";
        const baseImageryProvider = new Cesium.UrlTemplateImageryProvider({
            // Using satellite-streets-v12 gives us country/state borders baked into the map
            url: `https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/tiles/256/{z}/{x}/{y}?access_token=${mapboxToken}`,
            credit: ""
        });
        viewerRef.current.imageryLayers.removeAll();
        viewerRef.current.imageryLayers.addImageryProvider(baseImageryProvider);

        // CartoDB Dark Matter LABELS overlay removed to prevent duplication with Mapbox Streets

        // Google Photorealistic 3D Tiles removed to fix loading errors on localhost

        // Set initial camera view
        viewerRef.current.camera.setView({
            destination: Cesium.Cartesian3.fromDegrees(-95.0, 39.0, 20000000.0)
        });
        // Add TomTom Traffic Flow Layer (Raster)
        const trafficProvider = new Cesium.UrlTemplateImageryProvider({
            url: "https://api.tomtom.com/traffic/map/4/tile/flow/relative/{z}/{x}/{y}.png?key=uLndz1KvLDpwetYRwoiw8wKwk9i23sWG",
            credit: ""
        });
        viewerRef.current.trafficLayer = viewerRef.current.imageryLayers.addImageryProvider(trafficProvider);
        viewerRef.current.trafficLayer.show = false; // default off

        // ── Primitive Collections for Fast Rendering ──
        const Cesium2 = (window as any).Cesium;

        const flightBillboards = new Cesium2.BillboardCollection({ disableDepthTestDistance: 1000000.0 });
        const flightLabels = new Cesium2.LabelCollection({ disableDepthTestDistance: 1000000.0 });
        viewerRef.current.scene.primitives.add(flightBillboards);
        viewerRef.current.scene.primitives.add(flightLabels);
        flightBillboardsRef.current = flightBillboards;
        flightLabelsRef.current = flightLabels;

        const shipDS = new Cesium2.CustomDataSource('ships');
        shipDS.clustering.enabled = true;
        shipDS.clustering.pixelRange = 40;
        shipDS.clustering.minimumClusterSize = 3;
        viewerRef.current.dataSources.add(shipDS);
        shipDataSourceRef.current = shipDS;

        shipDS.clustering.clusterEvent.addEventListener((clusteredEntities: any[], cluster: any) => {
            const count = clusteredEntities.length;
            const radius = Math.min(10 + Math.log2(count) * 4, 30);
            cluster.billboard.show = false;
            cluster.label.show = true;
            cluster.label.text = String(count);
            cluster.label.font = `bold ${Math.max(10, Math.min(radius, 14))}px monospace`;
            cluster.label.fillColor = Cesium2.Color.WHITE;
            cluster.label.outlineColor = Cesium2.Color.BLACK;
            cluster.label.outlineWidth = 2;
            cluster.label.style = Cesium2.LabelStyle.FILL_AND_OUTLINE;
            cluster.label.horizontalOrigin = Cesium2.HorizontalOrigin.CENTER;
            cluster.label.verticalOrigin = Cesium2.VerticalOrigin.CENTER;
            cluster.label.disableDepthTestDistance = 1000000.0;
            cluster.point.show = true;
            cluster.point.pixelSize = radius;
            cluster.point.color = Cesium2.Color.fromCssColorString('rgba(0, 100, 255, 0.7)');
            cluster.point.outlineColor = Cesium2.Color.fromCssColorString('rgba(100, 150, 255, 0.9)');
            cluster.point.outlineWidth = 2;
            cluster.point.disableDepthTestDistance = 1000000.0;
        });

        // CCTV clustering
        const cctvDS = new Cesium2.CustomDataSource('cctv');
        cctvDS.clustering.enabled = true;
        cctvDS.clustering.pixelRange = 50;
        cctvDS.clustering.minimumClusterSize = 5;
        viewerRef.current.dataSources.add(cctvDS);
        cctvDataSourceRef.current = cctvDS;

        cctvDS.clustering.clusterEvent.addEventListener((clusteredEntities: any[], cluster: any) => {
            const count = clusteredEntities.length;
            const radius = Math.min(10 + Math.log2(count) * 4, 35);
            cluster.billboard.show = false;
            cluster.label.show = true;
            cluster.label.text = String(count);
            cluster.label.font = `bold ${Math.max(9, Math.min(radius, 14))}px monospace`;
            cluster.label.fillColor = Cesium2.Color.WHITE;
            cluster.label.outlineColor = Cesium2.Color.BLACK;
            cluster.label.outlineWidth = 2;
            cluster.label.style = Cesium2.LabelStyle.FILL_AND_OUTLINE;
            cluster.label.horizontalOrigin = Cesium2.HorizontalOrigin.CENTER;
            cluster.label.verticalOrigin = Cesium2.VerticalOrigin.CENTER;
            cluster.label.disableDepthTestDistance = 1000000.0;
            cluster.point.show = true;
            cluster.point.pixelSize = radius;
            cluster.point.color = Cesium2.Color.fromCssColorString('rgba(0, 200, 50, 0.7)');
            cluster.point.outlineColor = Cesium2.Color.fromCssColorString('rgba(100, 255, 100, 0.9)');
            cluster.point.outlineWidth = 2;
            cluster.point.disableDepthTestDistance = 1000000.0;
        });

        // Lighting and Bloom Settings
        scene.globe.enableLighting = true; // Provides dynamic day/night terminator line

        if (scene.postProcessStages) {
            const bloom = scene.postProcessStages.bloom;
            // Disable bloom by default to prevent washed out continents
            bloom.enabled = false;
            bloom.uniforms.glowOnly = false;
            bloom.uniforms.contrast = 120;
            bloom.uniforms.brightness = -0.1;
            bloom.uniforms.delta = 0.9;
            bloom.uniforms.sigma = 1.5;
            bloom.uniforms.stepSize = 0.5;

            const nvgShader = `
                uniform sampler2D colorTexture;
                in vec2 v_textureCoordinates;
        void main() {
                    vec4 color = texture(colorTexture, v_textureCoordinates);
                    float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
                    vec3 nvg = vec3(0.0, lum * 2.0, 0.0);
                    float dist = distance(v_textureCoordinates, vec2(0.5));
            nvg *= smoothstep(0.8, 0.2, dist);
            out_FragColor = vec4(nvg, 1.0);
        }
        `;
            const flirShader = `
                uniform sampler2D colorTexture;
                in vec2 v_textureCoordinates;
        void main() {
                    vec4 color = texture(colorTexture, v_textureCoordinates);
                    float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
                    vec3 col;
            if (lum < 0.25) col = mix(vec3(0, 0, 1), vec3(0, 1, 1), lum * 4.0);
            else if (lum < 0.5) col = mix(vec3(0, 1, 1), vec3(0, 1, 0), (lum - 0.25) * 4.0);
            else if (lum < 0.75) col = mix(vec3(0, 1, 0), vec3(1, 1, 0), (lum - 0.5) * 4.0);
            else col = mix(vec3(1, 1, 0), vec3(1, 0, 0), (lum - 0.75) * 4.0);
            out_FragColor = vec4(col, 1.0);
        }
        `;
            const crtShader = `
                uniform sampler2D colorTexture;
                in vec2 v_textureCoordinates;
        void main() {
                    vec2 uv = v_textureCoordinates;
                    vec4 color = texture(colorTexture, uv);
            color.rgb -= sin(uv.y * 800.0) * 0.05;
                    float r = texture(colorTexture, uv + vec2(0.002, 0.0)).r;
                    float b = texture(colorTexture, uv - vec2(0.002, 0.0)).b;
            out_FragColor = vec4(r, color.g, b, 1.0);
        }
        `;

            viewerRef.current.customStages = {
                NVG: new Cesium.PostProcessStage({ fragmentShader: nvgShader }),
                FLIR: new Cesium.PostProcessStage({ fragmentShader: flirShader }),
                CRT: new Cesium.PostProcessStage({ fragmentShader: crtShader })
            };
            scene.postProcessStages.add(viewerRef.current.customStages.NVG);
            scene.postProcessStages.add(viewerRef.current.customStages.FLIR);
            scene.postProcessStages.add(viewerRef.current.customStages.CRT);
            viewerRef.current.customStages.NVG.enabled = false;
            viewerRef.current.customStages.FLIR.enabled = false;
            viewerRef.current.customStages.CRT.enabled = false;
        }

        return () => {
            // Cleanup on unmount (often skipped in dev hot-reload but good practice)
            if (viewerRef.current && typeof window !== "undefined" && !(window as any).nextHotReload) {
                viewerRef.current.destroy();
                viewerRef.current = null;
            }
        };
    }, [cesiumLoaded]);

    // Setup input handler for picking
    useEffect(() => {
        if (!viewerRef.current) return;
        const Cesium = (window as any).Cesium;
        const viewer = viewerRef.current;

        const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
        handler.setInputAction((movement: any) => {
            // Eavesdrop Mode: Intercept clicks on the globe to get Lat/Lng instead of picking entities
            if (isEavesdropping && onEavesdropClick) {
                const ray = viewer.camera.getPickRay(movement.position);
                const earthPosition = viewer.scene.globe.pick(ray, viewer.scene);
                if (earthPosition) {
                    const cartographic = Cesium.Cartographic.fromCartesian(earthPosition);
                    const lng = Cesium.Math.toDegrees(cartographic.longitude);
                    const lat = Cesium.Math.toDegrees(cartographic.latitude);
                    onEavesdropClick({ lat, lng });
                }
                return; // Suppress normal entity selection during Eavesdrop
            }

            const pickedObject = viewer.scene.pick(movement.position);
            if (Cesium.defined(pickedObject) && pickedObject.id) {
                const entityId = pickedObject.id.id || pickedObject.id;
                if (typeof entityId === 'string') {
                    if (entityId.startsWith('news-')) {
                        const idx = parseInt(entityId.split('-')[1]);
                        onEntityClick?.({ type: 'news', id: idx, entityId: entityId });
                    } else if (entityId.startsWith('gdelt-')) {
                        const idx = parseInt(entityId.split('-')[1]);
                        onEntityClick?.({ type: 'gdelt', id: idx, entityId: entityId });
                    } else if (entityId.startsWith('private-jet-')) {
                        const icao = entityId.replace('private-jet-', '');
                        const flight = data?.private_jets?.find((f: any) => (f.icao24 || f.registration || f.callsign) === icao);
                        if (flight) {
                            onEntityClick?.({ type: 'private_jet', id: flight.icao24 || icao, callsign: flight.callsign, entityId: entityId });
                        }
                    } else if (entityId.startsWith('private-flight-')) {
                        const icao = entityId.replace('private-flight-', '');
                        const flight = data?.private_flights?.find((f: any) => (f.icao24 || f.registration || f.callsign) === icao);
                        if (flight) {
                            onEntityClick?.({ type: 'private_flight', id: flight.icao24 || icao, callsign: flight.callsign, entityId: entityId });
                        }
                    } else if (entityId.startsWith('flight-')) {
                        const icao = entityId.replace('flight-', '');
                        const flight = data?.commercial_flights?.find((f: any) => (f.icao24 || f.registration || f.callsign) === icao);
                        if (flight) {
                            onEntityClick?.({ type: 'flight', id: flight.icao24 || icao, callsign: flight.callsign, entityId: entityId });
                        }
                    } else if (entityId.startsWith('mil-flight-')) {
                        const icao = entityId.replace('mil-flight-', '');
                        const flight = data?.military_flights?.find((f: any) => (f.icao24 || f.registration || f.callsign) === icao);
                        if (flight) {
                            onEntityClick?.({ type: 'military_flight', id: flight.icao24 || icao, callsign: flight.callsign, entityId: entityId });
                        }
                    } else if (entityId.startsWith('tracked-')) {
                        const icao = entityId.replace('tracked-', '');
                        const flight = data?.tracked_flights?.find((f: any) => (f.icao24 || f.registration || f.callsign) === icao);
                        if (flight) {
                            onEntityClick?.({ type: 'tracked_flight', id: flight.icao24 || icao, callsign: flight.callsign, entityId: entityId });
                        }
                    } else if (entityId.startsWith('uav-entity-')) {
                        const uavIcao = entityId.replace('uav-entity-', '');
                        const uav = data?.uavs?.find((u: any) => u.icao24 === uavIcao);
                        if (uav) {
                            onEntityClick?.({ type: 'uav', id: uav.icao24 || uavIcao, callsign: uav.callsign, entityId: entityId });
                        }
                    } else if (entityId.startsWith('ship-')) {
                        const shipKey = entityId.replace('ship-', '');
                        const ship = data?.ships?.find((s: any) => String(s.mmsi) === shipKey);
                        if (ship) {
                            onEntityClick?.({ type: 'ship', id: ship.mmsi, name: ship.name, entityId: entityId });
                        }
                    } else if (entityId.startsWith('cctv-')) {
                        const entity = viewer.entities.getById(entityId);
                        // The CCTV ID is the remaining part
                        const cctvId = entityId.replace('cctv-', '');
                        // Find the camera in data
                        const cam = data?.cctv?.find((c: any) => String(c.id) === cctvId);
                        onEntityClick?.({ type: 'cctv', id: cctvId, name: cam?.name || cam?.direction_facing, media_url: cam?.media_url, entityId: entityId });
                    } else if (entityId.startsWith('satellite-')) {
                        const satId = entityId.replace('satellite-', '');
                        const sat = data?.satellites?.find((c: any) => String(c.id) === satId);
                        onEntityClick?.({ type: 'satellite', id: satId, name: sat?.name, tle1: sat?.tle1, tle2: sat?.tle2, entityId: entityId });
                    } else if (entityId.startsWith('apt-')) {
                        const aptId = entityId.replace('apt-', '');
                        const apt = data?.airports?.find((a: any) => String(a.id) === aptId);
                        onEntityClick?.({ type: 'airport', id: aptId, name: apt?.name, iata: apt?.iata, entityId: entityId });
                    } else if (entityId.startsWith('gdelt-')) {
                        const idx = parseInt(entityId.replace('gdelt-', ''));
                        if (!isNaN(idx) && data?.gdelt?.[idx]) {
                            onEntityClick?.({ type: 'gdelt', id: idx, entityId: entityId });
                        }
                    } else {
                        // Click on empty space or unhandled entity
                        onEntityClick?.(null);
                    }
                }
            } else {
                onEntityClick?.(null);
            }
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

        return () => {
            handler.destroy();
        };
    }, [cesiumLoaded, data, onEntityClick, isEavesdropping, onEavesdropClick]);

    // Effect to track the selected entity's screen position
    useEffect(() => {
        if (!viewerRef.current || !selectedEntity || !selectedEntity.entityId) {
            setPopupPosition(null);
            return;
        }

        const viewer = viewerRef.current;
        const Cesium = (window as any).Cesium;

        const updatePopupPosition = () => {
            let position: any = null;

            // 1. Search viewer.entities first
            let entity = viewer.entities.getById(selectedEntity.entityId);
            if (!entity && cctvDataSourceRef.current) entity = cctvDataSourceRef.current.entities.getById(selectedEntity.entityId);
            if (!entity && shipDataSourceRef.current) entity = shipDataSourceRef.current.entities.getById(selectedEntity.entityId);

            if (entity && entity.position) {
                const time = viewer.clock.currentTime;
                position = entity.position.getValue(time);
            }

            // 2. Search Primitives
            if (!position && selectedEntity.entityId) {
                const isFlight = selectedEntity.entityId.startsWith('flight-') || selectedEntity.entityId.startsWith('private-flight-') || selectedEntity.entityId.startsWith('private-jet-') || selectedEntity.entityId.startsWith('mil-flight-') || selectedEntity.entityId.startsWith('tracked-');
                if (isFlight) {
                    const uid = selectedEntity.entityId.split('-').slice(1).join('-'); // Handles 'flight-icao', 'private-flight-icao', etc.
                    position = flightPrimitivesRef.current.get(uid)?.billboard?.position;
                }
            }

            if (position) {
                const canvasPosition = Cesium.SceneTransforms.wgs84ToWindowCoordinates(viewer.scene, position);
                if (canvasPosition) {
                    setPopupPosition({ x: canvasPosition.x, y: canvasPosition.y });
                    return;
                }
            }

            setPopupPosition(null);
        };

        let lastMoveReport = 0;
        const updateCameraCenter = () => {
            if (!onCameraMove) return;
            const now = Date.now();
            if (now - lastMoveReport < 1000) return; // Throttle to 1s

            // Find center of screen
            const canvas = viewer.scene.canvas;
            const center = new Cesium.Cartesian2(canvas.clientWidth / 2, canvas.clientHeight / 2);
            const ray = viewer.camera.getPickRay(center);
            const earthPosition = viewer.scene.globe.pick(ray, viewer.scene);

            if (earthPosition) {
                const cartographic = Cesium.Cartographic.fromCartesian(earthPosition);
                const lng = Cesium.Math.toDegrees(cartographic.longitude);
                const lat = Cesium.Math.toDegrees(cartographic.latitude);
                onCameraMove({ lat, lng });
                lastMoveReport = now;
            }
        };

        // Initial update and attach to render loop
        updatePopupPosition();
        viewer.scene.preRender.addEventListener(updatePopupPosition);
        viewer.camera.changed.addEventListener(updateCameraCenter);

        return () => {
            viewer.scene.preRender.removeEventListener(updatePopupPosition);
            viewer.camera.changed.removeEventListener(updateCameraCenter);
        };
    }, [selectedEntity, onCameraMove]);

    // Effect to update data entities and effects
    useEffect(() => {
        if (!viewerRef.current || !data) return;
        const Cesium = (window as any).Cesium;
        const viewer = viewerRef.current;
        const occluder = new Cesium.EllipsoidalOccluder(Cesium.Ellipsoid.WGS84, viewer.camera.positionWC);
        const cameraHeight = viewer.camera.positionCartographic.height;

        // Instead of removing all, we should manage entities by ID for performance
        // For now, wipe and redraw as prototyping is small relative to Cesium engine
        // Handle Entities gracefully to prevent stutter
        viewer.entities.suspendEvents();
        const shipDS = shipDataSourceRef.current;
        const cctvDS = cctvDataSourceRef.current;
        if (shipDS) shipDS.entities.suspendEvents();
        if (cctvDS) cctvDS.entities.suspendEvents();

        const touchedIds = new Set<string>();
        const touchedCctvIds = new Set<string>();
        const touchedShipIds = new Set<string>(); // Added for ship cleanup

        const addOrUpdate = (props: any) => {
            if (!props.id) props.id = "gen-" + Math.random().toString(36).substr(2, 9);
            touchedIds.add(props.id);
            const existing = viewer.entities.getById(props.id);
            if (existing) {
                if (props.position) existing.position = props.position;
                if (props.show !== undefined) {
                    existing.show = props.show;
                } else {
                    existing.show = true;
                }

                if (props.label && existing.label) {
                    existing.label.text = props.label.text;
                    if (props.label.show !== undefined) {
                        existing.label.show = props.label.show;
                    } else {
                        existing.label.show = true;
                    }
                }

                if (props.billboard && existing.billboard) {
                    existing.billboard.rotation = props.billboard.rotation;
                    existing.billboard.image = props.billboard.image;
                }
                if (props.polyline && existing.polyline) {
                    existing.polyline.positions = props.polyline.positions;
                }

                if (props.point && existing.point) {
                    if (props.point.show !== undefined) existing.point.show = props.point.show;
                    else existing.point.show = true;
                    if (props.point.distanceDisplayCondition !== undefined) existing.point.distanceDisplayCondition = props.point.distanceDisplayCondition;
                }

                if (props.ellipse && existing.ellipse) {
                    if (props.ellipse.show !== undefined) existing.ellipse.show = props.ellipse.show;
                    else existing.ellipse.show = true;
                    if (props.ellipse.distanceDisplayCondition !== undefined) existing.ellipse.distanceDisplayCondition = props.ellipse.distanceDisplayCondition;
                }
            } else {
                viewer.entities.add(props);
            }
        };

        const updatePrimitive = (uid: string, props: any, mapRef: Map<string, any>, billboardsRef: any, labelsRef: any) => {
            let prims = mapRef.get(uid);
            if (!props.show) {
                if (prims) {
                    prims.billboard.show = false;
                    prims.label.show = false;
                }
                return;
            }

            if (!prims) {
                const b = billboardsRef.add({ ...props.billboard, position: props.position, id: props.id });
                const l = labelsRef.add({ ...props.label, position: props.position, id: props.id });
                prims = { billboard: b, label: l };
                mapRef.set(uid, prims);
            }

            prims.billboard.position = props.position;
            prims.billboard.show = props.show;
            if (props.billboard.image !== undefined) prims.billboard.image = props.billboard.image;
            if (props.billboard.rotation !== undefined) prims.billboard.rotation = props.billboard.rotation;

            prims.label.position = props.position;
            prims.label.show = props.label.show !== false ? props.show : false;
            if (props.label.text !== undefined) prims.label.text = props.label.text;
        };

        const svgToBase64 = (svg: string) => `data:image/svg+xml;base64,${btoa(svg)}`;
        const svgPlaneCyan = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="cyan" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`);
        const svgPlaneYellow = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`);
        const svgPlaneOrange = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#FF8C00" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`);
        const svgPlanePurple = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#9B59B6" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`);

        const svgFighter = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="M12 2L14 8L18 10L14 16L15 22L12 20L9 22L10 16L6 10L10 8L12 2Z"/></svg>`);
        const svgHeli = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="black" stroke-dasharray="2 2" stroke-width="1"/></svg>`);
        const svgHeliCyan = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="cyan" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="cyan" stroke-dasharray="2 2" stroke-width="1"/></svg>`);
        const svgHeliOrange = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#FF8C00" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#FF8C00" stroke-dasharray="2 2" stroke-width="1"/></svg>`);
        const svgHeliPurple = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#9B59B6" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#9B59B6" stroke-dasharray="2 2" stroke-width="1"/></svg>`);
        const svgTanker = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /><line x1="12" y1="20" x2="12" y2="24" stroke="yellow" stroke-width="2" /></svg>`);
        const svgRecon = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /><ellipse cx="12" cy="11" rx="5" ry="3" fill="none" stroke="red" stroke-width="1.5"/></svg>`);

        const milIconMap: any = {
            'fighter': svgFighter,
            'heli': svgHeli,
            'tanker': svgTanker,
            'cargo': svgPlaneYellow,
            'recon': svgRecon,
            'default': svgPlaneYellow
        };

        // Tracked aircraft SVGs (Plane-Alert DB)
        const svgPlanePink = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#FF1493" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`);
        const svgPlaneAlertRed = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#FF2020" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`);
        const svgPlaneDarkBlue = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#1A3A8A" stroke="#4A80D0"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`);
        const svgPlaneWhiteAlert = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" stroke="#666"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`);

        const svgHeliPink = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#FF1493" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#FF1493" stroke-dasharray="2 2" stroke-width="1"/></svg>`);
        const svgHeliAlertRed = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#FF2020" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#FF2020" stroke-dasharray="2 2" stroke-width="1"/></svg>`);
        const svgHeliDarkBlue = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#1A3A8A" stroke="#4A80D0"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#4A80D0" stroke-dasharray="2 2" stroke-width="1"/></svg>`);
        const svgHeliWhiteAlert = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" stroke="#666"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="white" stroke-dasharray="2 2" stroke-width="1"/></svg>`);

        const trackedPlaneIcons: any = {
            'pink': svgPlanePink, 'red': svgPlaneAlertRed, 'darkblue': svgPlaneDarkBlue, 'white': svgPlaneWhiteAlert
        };
        const trackedHeliIcons: any = {
            'pink': svgHeliPink, 'red': svgHeliAlertRed, 'darkblue': svgHeliDarkBlue, 'white': svgHeliWhiteAlert
        };
        const trackedColorMap: any = {
            'pink': Cesium.Color.fromCssColorString('#FF1493'),
            'red': Cesium.Color.fromCssColorString('#FF2020'),
            'darkblue': Cesium.Color.fromCssColorString('#1A3A8A'),
            'white': Cesium.Color.WHITE
        };

        // Parked/landed aircraft SVGs (dark/black)
        const svgPlaneBlack = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#222" stroke="#444"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`);
        const svgHeliBlack = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#222" stroke="#444"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#444" stroke-dasharray="2 2" stroke-width="1"/></svg>`);
        const COLOR_BLACK = Cesium.Color.fromCssColorString('#222222');

        // Detect parked/landed aircraft: altitude near 0 AND low ground speed
        const isOnGround = (f: any) => {
            const alt = f.alt || 0; // already in meters
            const spd = f.speed_knots || 0;
            return alt <= 500 && spd < 30;
        };

        // Render accumulated flight trail as a polyline
        const renderTrail = (f: any, uid: string, trailColor: any, show: boolean) => {
            const trail = f.trail;
            if (!trail || trail.length < 2) return;

            const trailId = `trail-${uid}`;
            // Build positions array from trail points [lat, lng, alt, ts]
            const positions = trail.map((p: number[]) =>
                Cesium.Cartesian3.fromDegrees(p[1], p[0], Math.max(p[2] || 0, 100))
            );
            // Add current position as final point
            positions.push(Cesium.Cartesian3.fromDegrees(f.lng, f.lat, Math.max(f.alt || 0, 100)));

            addOrUpdate({
                id: trailId,
                show: show,
                polyline: {
                    positions: positions,
                    width: 2,
                    material: new Cesium.PolylineGlowMaterialProperty({
                        glowPower: 0.15,
                        color: trailColor
                    }),
                    disableDepthTestDistance: 1000000.0
                }
            });
        };

        // Filter matching helpers (multi-select: OR logic across selected values)
        const filters = activeFilters || {};
        const matchesAny = (value: string, selectedValues: string[]) => {
            if (!selectedValues || selectedValues.length === 0) return true;
            const v = (value || '').toLowerCase();
            return selectedValues.some(sv => v.includes(sv.toLowerCase()));
        };
        const matchesCommercialFilter = (f: any) => {
            if (filters.commercial_departure?.length) {
                if (!matchesAny(f.origin_name, filters.commercial_departure)) return false;
            }
            if (filters.commercial_arrival?.length) {
                if (!matchesAny(f.dest_name, filters.commercial_arrival)) return false;
            }
            if (filters.commercial_airline?.length) {
                if (!matchesAny(f.airline_code, filters.commercial_airline)) return false;
            }
            return true;
        };
        const matchesPrivateFilter = (f: any) => {
            if (filters.private_callsign?.length) {
                const cs = (f.callsign || '').toLowerCase();
                const reg = (f.registration || '').toLowerCase();
                if (!filters.private_callsign.some(sv => {
                    const q = sv.toLowerCase();
                    return cs.includes(q) || reg.includes(q);
                })) return false;
            }
            if (filters.private_aircraft_type?.length) {
                if (!matchesAny(f.model, filters.private_aircraft_type)) return false;
            }
            return true;
        };
        const matchesMilitaryFilter = (f: any) => {
            if (filters.military_country?.length) {
                const reg = (f.registration || '').toLowerCase();
                const country = (f.country || '').toLowerCase();
                if (!filters.military_country.some(sv => {
                    const q = sv.toLowerCase();
                    return reg.includes(q) || country.includes(q);
                })) return false;
            }
            if (filters.military_aircraft_type?.length) {
                if (!matchesAny(f.military_type, filters.military_aircraft_type)) return false;
            }
            return true;
        };
        const matchesTrackedFilter = (f: any) => {
            if (filters.tracked_category?.length) {
                if (!matchesAny(f.alert_category, filters.tracked_category)) return false;
            }
            if (filters.tracked_owner?.length) {
                const op = (f.alert_operator || '').toLowerCase();
                const t1 = (f.alert_tag1 || '').toLowerCase();
                const t2 = (f.alert_tag2 || '').toLowerCase();
                const t3 = (f.alert_tag3 || '').toLowerCase();
                const cs = (f.callsign || '').toLowerCase();
                if (!filters.tracked_owner.some(sv => {
                    const q = sv.toLowerCase();
                    return op.includes(q) || t1.includes(q) || t2.includes(q) || t3.includes(q) || cs.includes(q);
                })) return false;
            }
            return true;
        };
        const matchesShipFilter = (f: any) => {
            if (filters.ship_name?.length) {
                if (!matchesAny(f.name, filters.ship_name)) return false;
            }
            if (filters.ship_type?.length) {
                if (!matchesAny(f.type, filters.ship_type)) return false;
            }
            return true;
        };

        // ── Cross-category filter hiding ──
        // When ANY air filter is active, categories WITHOUT their own filters should hide.
        // This ensures filtering Lufthansa hides all private/military/tracked unless they also have filters.
        const hasCommercialFilter = !!(filters.commercial_departure?.length || filters.commercial_arrival?.length || filters.commercial_airline?.length);
        const hasPrivateFilter = !!(filters.private_callsign?.length || filters.private_aircraft_type?.length);
        const hasMilitaryFilter = !!(filters.military_country?.length || filters.military_aircraft_type?.length);
        const hasTrackedFilter = !!(filters.tracked_category?.length || filters.tracked_owner?.length);
        const hasShipFilter = !!(filters.ship_name?.length || filters.ship_type?.length);
        const hasAnyAirFilter = hasCommercialFilter || hasPrivateFilter || hasMilitaryFilter || hasTrackedFilter;
        const hasAnyFilter = hasAnyAirFilter || hasShipFilter;
        const svgDrone = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="orange" stroke="black"><path d="M12 2L15 8H9L12 2Z" /><rect x="8" y="8" width="8" height="2" /><path d="M4 10L10 14H14L20 10V12L14 16H10L4 12V10Z" /><circle cx="12" cy="14" r="2" fill="red"/></svg>`);
        const svgShipGray = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="gray" stroke="black" stroke-width="1.5"><path d="M12 22V8" /><path d="M5 12H19" /><path d="M9 22H15" /><circle cx="12" cy="5" r="3" /><path d="M12 22C8 22 4 19 4 15V13M12 22C16 22 20 19 20 15V13" /></svg>`);
        const svgShipRed = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="red" stroke="black" stroke-width="1.5"><path d="M12 22V8" /><path d="M5 12H19" /><path d="M9 22H15" /><circle cx="12" cy="5" r="3" /><path d="M12 22C8 22 4 19 4 15V13M12 22C16 22 20 19 20 15V13" /></svg>`);
        const svgShipYellow = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="yellow" stroke="black" stroke-width="1.5"><path d="M12 22V8" /><path d="M5 12H19" /><path d="M9 22H15" /><circle cx="12" cy="5" r="3" /><path d="M12 22C8 22 4 19 4 15V13M12 22C16 22 20 19 20 15V13" /></svg>`);
        const svgShipBlue = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#3b82f6" stroke="black" stroke-width="1.5"><path d="M12 22V8" /><path d="M5 12H19" /><path d="M9 22H15" /><circle cx="12" cy="5" r="3" /><path d="M12 22C8 22 4 19 4 15V13M12 22C16 22 20 19 20 15V13" /></svg>`);
        const svgShipWhite = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" stroke="black" stroke-width="1.5"><path d="M12 22V8" /><path d="M5 12H19" /><path d="M9 22H15" /><circle cx="12" cy="5" r="3" /><path d="M12 22C8 22 4 19 4 15V13M12 22C16 22 20 19 20 15V13" /></svg>`);
        const svgCarrier = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="orange" stroke="black"><polygon points="3,21 21,21 20,4 16,4 16,3 12,3 12,4 4,4" /><rect x="15" y="6" width="3" height="10" /></svg>`);
        const svgCctv = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="cyan" stroke-width="2"><path d="M16.75 12h3.632a1 1 0 0 1 .894 1.447l-2.034 4.069a1 1 0 0 1-.894.553H5.652a1 1 0 0 1-.894-.553L2.724 13.447A1 1 0 0 1 3.618 12h3.632M14 12V8a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v4a4 4 0 1 0 8 0Z" /></svg>`);
        const svgWarning = svgToBase64(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>`);

        // Apply Post-Process Effects
        if (viewer.scene.postProcessStages) {
            viewer.scene.postProcessStages.bloom.enabled = effects?.bloom ?? true;
            if (viewer.customStages) {
                viewer.customStages.NVG.enabled = effects?.style === 'NVG';
                viewer.customStages.FLIR.enabled = effects?.style === 'FLIR';
                viewer.customStages.CRT.enabled = effects?.style === 'CRT';
            }
        }

        // Apply Traffic Layer visibility
        if (viewer.trafficLayer) {
            viewer.trafficLayer.show = activeLayers?.traffic !== false;
        }

        // Process DeepStateMap Ukraine Frontlines (GeoJSON parsing)
        const frontlineId = "deepstate-frontline";
        if (data.frontlines && activeLayers?.ukraine_frontline !== false) {
            // Check if we already loaded it so we don't spam the Cesium entity system with huge polygons
            if (!viewer.dataSources.getByName(frontlineId).length) {
                // GeoJSON processing
                Cesium.GeoJsonDataSource.load(data.frontlines, {
                    stroke: Cesium.Color.RED,
                    fill: Cesium.Color.RED.withAlpha(0.2),
                    strokeWidth: 2
                }).then((dataSource: any) => {
                    dataSource.name = frontlineId;
                    viewer.dataSources.add(dataSource);

                    const entities = dataSource.entities.values;
                    for (let i = 0; i < entities.length; i++) {
                        const entity = entities[i];
                        const status = entity.properties?.status?.getValue(); // 1=Liberated, 2=Occupied, 3=Contested (approximation)
                        let polyColor = Cesium.Color.RED.withAlpha(0.3); // Default occupied
                        let outlineColor = Cesium.Color.RED;

                        if (status === 1) {
                            // Liberated
                            polyColor = Cesium.Color.GREEN.withAlpha(0.2);
                            outlineColor = Cesium.Color.GREEN;
                        } else if (status === 3) {
                            // Contested
                            polyColor = Cesium.Color.ORANGE.withAlpha(0.2);
                            outlineColor = Cesium.Color.ORANGE;
                        }

                        if (entity.polygon) {
                            entity.polygon.material = polyColor;
                            entity.polygon.outlineColor = outlineColor;
                            entity.polygon.outlineWidth = 2;
                        }
                    }
                });
            } else {
                // Make sure it's visible if already loaded
                const ds = viewer.dataSources.getByName(frontlineId)[0];
                if (ds && !ds.show) ds.show = true;
            }
        } else {
            // Hide it if turned off
            const ds = viewer.dataSources.getByName(frontlineId)[0];
            if (ds && ds.show) ds.show = false;
        }

        // Process GDELT Global Military Incidents
        if (data.gdelt && activeLayers?.global_incidents !== false) {
            data.gdelt.forEach((incident: any, idx: number) => {
                const geom = incident.geometry;
                if (!geom || geom.type !== 'Point' || !geom.coordinates) return;

                const lng = geom.coordinates[0];
                const lat = geom.coordinates[1];
                const id = `gdelt-${idx}`;
                const isSelected = selectedEntity?.id === id;

                addOrUpdate({
                    id: id,
                    position: Cesium.Cartesian3.fromDegrees(lng, lat, 0),
                    point: {
                        pixelSize: 8,
                        color: Cesium.Color.ORANGE,
                        outlineColor: Cesium.Color.RED,
                        outlineWidth: 2,
                        disableDepthTestDistance: 4000000.0,
                        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 5000000.0)
                    },
                    ellipse: {
                        semiMinorAxis: 15000,
                        semiMajorAxis: 15000,
                        material: Cesium.Color.RED.withAlpha(0.3),
                        outline: true,
                        outlineColor: Cesium.Color.ORANGE,
                        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 5000000.0)
                    }
                });
            });
        }

        // Process News Alerts (Risk Coordinates)
        if (data.news) {
            data.news.forEach((n: any, idx: number) => {
                if (n.coords && n.coords.length === 2) {
                    let riskColorHex = '#22c55e'; // Green (1-3)
                    if (n.risk_score >= 9) riskColorHex = '#ef4444'; // Red (9-10)
                    else if (n.risk_score >= 7) riskColorHex = '#f97316'; // Orange (7-8)
                    else if (n.risk_score >= 4) riskColorHex = '#eab308'; // Yellow (4-6)
                    const currentPos = Cesium.Cartesian3.fromDegrees(n.coords[1], n.coords[0], 0);
                    // Cull if on the other side of the planet
                    if (!occluder.isPointVisible(currentPos)) return;

                    const color = Cesium.Color.fromCssColorString(riskColorHex);

                    addOrUpdate({
                        id: `news-${idx}`,
                        position: currentPos,
                        point: {
                            pixelSize: n.risk_score >= 8 ? 16 : 8,
                            color: Cesium.Color.fromCssColorString('rgba(0,0,0,0)'),
                            outlineColor: color,
                            outlineWidth: 3
                        },
                        ellipse: {
                            semiMinorAxis: n.risk_score * 40000,
                            semiMajorAxis: n.risk_score * 40000,
                            material: color.withAlpha(0.2),
                            outline: true,
                            outlineColor: color
                        },
                        label: {
                            text: n.cluster_count > 1 ? `!! ALERT LVL ${n.risk_score} !!\n${n.title.substring(0, 30)}...\n[+${n.cluster_count - 1} MORE]` : `!! ALERT LVL ${n.risk_score}!!\n${n.title.substring(0, 30)}...`,
                            font: 'bold 10px monospace',
                            fillColor: color,
                            backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                            showBackground: true,
                            style: Cesium.LabelStyle.FILL,
                            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                            pixelOffset: new Cesium.Cartesian2(0, -16),
                            // Pushes it forward from planes, but not through the earth
                            eyeOffset: new Cesium.Cartesian3(0, 0, -100000),
                            disableDepthTestDistance: Number.POSITIVE_INFINITY // Always overlays over planes now that backface culling handles planet occlusion
                        }
                    });
                }
            });
        }

        // Process Commercial Flights (teal)
        if (data.commercial_flights && activeLayers?.flights !== false) {
            const anyFlightSelected = selectedEntity?.type === 'flight' || selectedEntity?.type === 'military_flight' || selectedEntity?.type === 'private_flight' || selectedEntity?.type === 'private_jet';
            const selectedFlightIdx = selectedEntity?.type === 'flight' ? String(selectedEntity.entityId).replace('flight-', '') : null;
            const seenIds = new Set<string>();

            data.commercial_flights.forEach((f: any, idx: number) => {
                if (hasAnyAirFilter && !hasCommercialFilter) return;
                if (!matchesCommercialFilter(f)) return;
                const uid = f.icao24 || f.registration || f.callsign || `unk-${idx}`;
                const currentPos = Cesium.Cartesian3.fromDegrees(f.lng, f.lat, f.alt || 5000);

                // Culling: Skip rendering heavily if planes are behind the planet
                if (!occluder.isPointVisible(currentPos)) return;

                const id = `flight-${uid}`;
                const isSelected = selectedFlightIdx === String(uid);
                const showEntity = !anyFlightSelected || isSelected;
                seenIds.add(uid);

                updatePrimitive(uid, {
                    id: id,
                    show: showEntity,
                    position: currentPos,
                    billboard: {
                        image: isOnGround(f) ? (f.aircraft_category === 'heli' ? svgHeliBlack : svgPlaneBlack) : (f.aircraft_category === 'heli' ? svgHeliCyan : svgPlaneCyan),
                        width: 14, height: 14,
                        rotation: Cesium.Math.toRadians(-f.heading || 0),
                        disableDepthTestDistance: 1000000.0
                    },
                    label: {
                        show: isSelected,
                        text: `[${f.callsign || 'FLT'} ]`,
                        font: '10px monospace',
                        fillColor: Cesium.Color.CYAN,
                        backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                        showBackground: true,
                        style: Cesium.LabelStyle.FILL,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -12),
                        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 10000000.0),
                        disableDepthTestDistance: 1000000.0
                    }
                }, flightPrimitivesRef.current, flightBillboardsRef.current, flightLabelsRef.current);

                // Draw accumulated trail for unrouted flights ONLY if selected to avoid crashing the 16-bit WebGL array limits
                if (isSelected) renderTrail(f, uid, Cesium.Color.CYAN.withAlpha(0.5), isSelected);
            });

            // Cull disappeared flights
            for (const [uid, prims] of Array.from(flightPrimitivesRef.current.entries())) {
                if (!seenIds.has(uid) && prims.billboard.id.startsWith('flight-')) {
                    flightBillboardsRef.current.remove(prims.billboard);
                    flightLabelsRef.current.remove(prims.label);
                    flightPrimitivesRef.current.delete(uid);
                }
            }
        } else if (flightPrimitivesRef.current.size > 0) {
            flightBillboardsRef.current.removeAll();
            flightLabelsRef.current.removeAll();
            flightPrimitivesRef.current.clear();
        }

        // Process Private Flights (orange)
        if (data.private_flights && activeLayers?.private !== false) {
            const now = Cesium.JulianDate.now();
            const future = Cesium.JulianDate.addSeconds(now, 30, new Cesium.JulianDate());

            const anyFlightSelected = selectedEntity?.type === 'flight' || selectedEntity?.type === 'military_flight' || selectedEntity?.type === 'private_flight' || selectedEntity?.type === 'private_jet';
            const selectedPrivateIdx = selectedEntity?.type === 'private_flight' ? String(selectedEntity.entityId).replace('private-flight-', '') : null;
            const seenIds = new Set<string>();

            const orangeColor = Cesium.Color.fromCssColorString('#FF8C00');

            data.private_flights.forEach((f: any, idx: number) => {
                if (hasAnyAirFilter && !hasPrivateFilter) return;
                if (!matchesPrivateFilter(f)) return;
                const uid = f.icao24 || f.registration || f.callsign || `unk-${idx}`;
                const currentPos = Cesium.Cartesian3.fromDegrees(f.lng, f.lat, f.alt || 3000);
                if (!occluder.isPointVisible(currentPos)) return;

                const id = `private-flight-${uid}`;
                const isSelected = selectedPrivateIdx === String(uid);
                const showEntity = !anyFlightSelected || isSelected;
                seenIds.add(uid);

                updatePrimitive(uid, {
                    id: id,
                    show: showEntity,
                    position: currentPos,
                    billboard: {
                        image: isOnGround(f) ? (f.aircraft_category === 'heli' ? svgHeliBlack : svgPlaneBlack)
                            : f.aircraft_category === 'heli' ? svgHeliOrange
                                : svgPlaneOrange,
                        width: 12, height: 12,
                        rotation: Cesium.Math.toRadians(-f.heading || 0),
                        disableDepthTestDistance: 1000000.0
                    },
                    label: {
                        show: isSelected,
                        text: `[${f.callsign || 'PVT'} ]`,
                        font: '10px monospace',
                        fillColor: orangeColor,
                        backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                        showBackground: true,
                        style: Cesium.LabelStyle.FILL,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -12),
                        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 10000000.0),
                        disableDepthTestDistance: 1000000.0
                    }
                }, flightPrimitivesRef.current, flightBillboardsRef.current, flightLabelsRef.current);
                if (isSelected) renderTrail(f, uid, Cesium.Color.fromCssColorString('#FF8C00').withAlpha(0.5), isSelected);
            });
            // Cull disappeared flights
            for (const [uid, prims] of Array.from(flightPrimitivesRef.current.entries())) {
                if (!seenIds.has(uid) && prims.billboard.id.startsWith('private-flight-')) { // Only remove if it's a private flight and not seen
                    flightBillboardsRef.current.remove(prims.billboard);
                    flightLabelsRef.current.remove(prims.label);
                    flightPrimitivesRef.current.delete(uid);
                }
            }
        }

        // Process Private Jets (purple)
        if (data.private_jets && activeLayers?.jets !== false) {
            const now = Cesium.JulianDate.now();
            const future = Cesium.JulianDate.addSeconds(now, 30, new Cesium.JulianDate());

            const anyFlightSelected = selectedEntity?.type === 'flight' || selectedEntity?.type === 'military_flight' || selectedEntity?.type === 'private_flight' || selectedEntity?.type === 'private_jet';
            const selectedJetIdx = selectedEntity?.type === 'private_jet' ? String(selectedEntity.entityId).replace('private-jet-', '') : null;
            const seenIds = new Set<string>();

            const purpleColor = Cesium.Color.fromCssColorString('#9B59B6');

            data.private_jets.forEach((f: any, idx: number) => {
                if (hasAnyAirFilter && !hasPrivateFilter) return;
                if (!matchesPrivateFilter(f)) return;
                const uid = f.icao24 || f.registration || f.callsign || `unk-${idx}`;
                const currentPos = Cesium.Cartesian3.fromDegrees(f.lng, f.lat, f.alt || 8000);
                if (!occluder.isPointVisible(currentPos)) return;

                const id = `private-jet-${uid}`;
                const isSelected = selectedJetIdx === String(uid);
                const showEntity = !anyFlightSelected || isSelected;
                seenIds.add(uid);

                updatePrimitive(uid, {
                    id: id,
                    show: showEntity,
                    position: currentPos,
                    billboard: {
                        image: isOnGround(f) ? (f.aircraft_category === 'heli' ? svgHeliBlack : svgPlaneBlack)
                            : f.aircraft_category === 'heli' ? svgHeliPurple
                                : svgPlanePurple,
                        width: 14, height: 14,
                        rotation: Cesium.Math.toRadians(-f.heading || 0),
                        disableDepthTestDistance: 1000000.0
                    },
                    label: {
                        show: isSelected,
                        text: `[${f.callsign || 'JET'} ]`,
                        font: '10px monospace',
                        fillColor: purpleColor,
                        backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                        showBackground: true,
                        style: Cesium.LabelStyle.FILL,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -12),
                        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 10000000.0),
                        disableDepthTestDistance: 1000000.0
                    }
                }, flightPrimitivesRef.current, flightBillboardsRef.current, flightLabelsRef.current);
                if (isSelected) renderTrail(f, uid, Cesium.Color.fromCssColorString('#9B59B6').withAlpha(0.5), isSelected);
            });
            // Cull disappeared flights
            for (const [uid, prims] of Array.from(flightPrimitivesRef.current.entries())) {
                if (!seenIds.has(uid) && prims.billboard.id.startsWith('private-jet-')) { // Only remove if it's a private jet and not seen
                    flightBillboardsRef.current.remove(prims.billboard);
                    flightLabelsRef.current.remove(prims.label);
                    flightPrimitivesRef.current.delete(uid);
                }
            }
        }

        // Process Military Flights
        if (data.military_flights && activeLayers?.military !== false) {
            const now = Cesium.JulianDate.now();
            const future = Cesium.JulianDate.addSeconds(now, 30, new Cesium.JulianDate());

            const anyFlightSelected = selectedEntity?.type === 'flight' || selectedEntity?.type === 'military_flight';
            const selectedMilFlightIdx = selectedEntity?.type === 'military_flight' ? String(selectedEntity.id) : null;
            const seenIds = new Set<string>();

            data.military_flights.forEach((f: any, idx: number) => {
                if (hasAnyAirFilter && !hasMilitaryFilter) return;
                if (!matchesMilitaryFilter(f)) return;
                const uid = f.icao24 || f.registration || f.callsign || `unk-${idx}`;
                const startPos = Cesium.Cartesian3.fromDegrees(f.lng, f.lat, f.alt || 8000);
                if (!occluder.isPointVisible(startPos)) return;

                const id = `mil-flight-${uid}`;
                const isSelected = selectedMilFlightIdx === String(idx);
                const showEntity = !anyFlightSelected || isSelected;
                seenIds.add(uid);

                let positionProp = viewer.entities.getById(id)?.position;

                if (!positionProp || !(positionProp instanceof Cesium.SampledPositionProperty)) {
                    positionProp = new Cesium.SampledPositionProperty();
                    positionProp.forwardExtrapolationType = Cesium.ExtrapolationType.EXTRAPOLATE;
                    positionProp.backwardExtrapolationType = Cesium.ExtrapolationType.HOLD;
                }

                (positionProp as any).addSample(now, startPos);

                // Use actual ground speed from ADS-B (knots → m/s) or fallback
                const speedMps = f.speed_knots ? f.speed_knots * 0.514444 : 400;
                const distanceMeters = speedMps * 30;

                const R = 6371e3;
                const lat1 = f.lat * Math.PI / 180;
                const lon1 = f.lng * Math.PI / 180;
                const brng = f.heading * Math.PI / 180;

                const lat2 = Math.asin(Math.sin(lat1) * Math.cos(distanceMeters / R) +
                    Math.cos(lat1) * Math.sin(distanceMeters / R) * Math.cos(brng));
                const lon2 = lon1 + Math.atan2(Math.sin(brng) * Math.sin(distanceMeters / R) * Math.cos(lat1),
                    Math.cos(distanceMeters / R) - Math.sin(lat1) * Math.sin(lat2));

                const endPos = Cesium.Cartesian3.fromDegrees(lon2 * 180 / Math.PI, lat2 * 180 / Math.PI, f.alt || 8000);
                (positionProp as any).addSample(future, endPos);

                updatePrimitive(uid, {
                    id: id,
                    show: showEntity,
                    position: positionProp,
                    billboard: {
                        image: isOnGround(f) ? svgPlaneBlack : (milIconMap[f.military_type || 'default'] || svgPlaneYellow),
                        width: 18,
                        height: 18,
                        rotation: Cesium.Math.toRadians(-f.heading || 0),
                        disableDepthTestDistance: 1000000.0
                    },
                    label: {
                        show: isSelected, // Only show label when isolated
                        text: `[${f.callsign} ]`,
                        font: 'bold 10px monospace',
                        fillColor: Cesium.Color.YELLOW,
                        backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                        showBackground: true,
                        style: Cesium.LabelStyle.FILL,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -14),
                        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 12000000.0),
                        disableDepthTestDistance: 1000000.0
                    }
                }, flightPrimitivesRef.current, flightBillboardsRef.current, flightLabelsRef.current);
                if (isSelected) renderTrail(f, uid, Cesium.Color.YELLOW.withAlpha(0.5), isSelected);
            });
            // Cull disappeared flights
            for (const [uid, prims] of Array.from(flightPrimitivesRef.current.entries())) {
                if (!seenIds.has(uid) && prims.billboard.id.startsWith('mil-flight-')) { // Only remove if it's a military flight and not seen
                    flightBillboardsRef.current.remove(prims.billboard);
                    flightLabelsRef.current.remove(prims.label);
                    flightPrimitivesRef.current.delete(uid);
                }
            }
        }

        // Process Tracked/Alert Flights (Plane-Alert DB)
        if (data.tracked_flights && activeLayers?.tracked !== false) {
            const now = Cesium.JulianDate.now();
            const future = Cesium.JulianDate.addSeconds(now, 30, new Cesium.JulianDate());

            const anyFlightSelected = selectedEntity?.type === 'flight' || selectedEntity?.type === 'military_flight' || selectedEntity?.type === 'private_flight' || selectedEntity?.type === 'private_jet' || selectedEntity?.type === 'tracked_flight';
            const selectedTrackedIdx = selectedEntity?.type === 'tracked_flight' ? String(selectedEntity.entityId).replace('tracked-', '') : null;
            const seenIds = new Set<string>();

            data.tracked_flights.forEach((f: any, idx: number) => {
                if (hasAnyAirFilter && !hasTrackedFilter) return;
                if (!matchesTrackedFilter(f)) return;
                const uid = f.icao24 || f.registration || f.callsign || `unk-${idx}`;
                const currentPos = Cesium.Cartesian3.fromDegrees(f.lng, f.lat, f.alt || 5000);
                if (!occluder.isPointVisible(currentPos)) return;

                const id = `tracked-${uid}`;
                const isSelected = selectedTrackedIdx === String(uid);
                const showEntity = !anyFlightSelected || isSelected;
                seenIds.add(uid);

                const alertColor = f.alert_color || 'white';
                const cesiumColor = trackedColorMap[alertColor] || Cesium.Color.WHITE;
                const planeIcon = f.aircraft_category === 'heli'
                    ? (trackedHeliIcons[alertColor] || svgHeliWhiteAlert)
                    : (trackedPlaneIcons[alertColor] || svgPlaneWhiteAlert);

                updatePrimitive(uid, {
                    id: id,
                    show: showEntity,
                    position: currentPos,
                    billboard: {
                        image: isOnGround(f) ? (f.aircraft_category === 'heli' ? svgHeliBlack : svgPlaneBlack) : planeIcon,
                        width: 16, height: 16,
                        rotation: Cesium.Math.toRadians(-f.heading || 0),
                        disableDepthTestDistance: 1000000.0
                    },
                    label: {
                        show: isSelected,
                        text: `⚠ ${f.alert_operator || f.callsign || 'TRACKED'}`,
                        font: 'bold 10px monospace',
                        fillColor: cesiumColor,
                        backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.85)'),
                        showBackground: true,
                        style: Cesium.LabelStyle.FILL,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -14),
                        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 12000000.0),
                        disableDepthTestDistance: 1000000.0
                    }
                }, flightPrimitivesRef.current, flightBillboardsRef.current, flightLabelsRef.current);
                const trailAlertColor = f.alert_color || 'white';
                const trailClr = trackedColorMap[trailAlertColor] || Cesium.Color.WHITE;
                if (isSelected) renderTrail(f, uid, trailClr.withAlpha(0.5), isSelected);
            });
            // Cull disappeared flights
            for (const [uid, prims] of Array.from(flightPrimitivesRef.current.entries())) {
                if (!seenIds.has(uid) && prims.billboard.id.startsWith('tracked-')) { // Only remove if it's a tracked flight and not seen
                    flightBillboardsRef.current.remove(prims.billboard);
                    flightLabelsRef.current.remove(prims.label);
                    flightPrimitivesRef.current.delete(uid);
                }
            }
        }

        // Process UAV Loitering Patterns
        if (data.uavs && activeLayers?.military !== false) {
            data.uavs.forEach((uav: any, idx: number) => {
                // Drone entity
                addOrUpdate({
                    id: `uav-entity-${idx}`,
                    position: Cesium.Cartesian3.fromDegrees(uav.lng, uav.lat, uav.alt || 10000),
                    point: {
                        pixelSize: 6,
                        color: Cesium.Color.ORANGE,
                        disableDepthTestDistance: 1000000.0
                    },
                    billboard: {
                        image: svgDrone,
                        width: 18,
                        height: 18,
                        rotation: Cesium.Math.toRadians(-uav.heading || 0),
                        disableDepthTestDistance: 1000000.0
                    },
                    label: {
                        text: `[UAV: ${uav.callsign} ]`,
                        font: 'bold 10px monospace',
                        fillColor: Cesium.Color.ORANGE,
                        backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                        showBackground: true,
                        style: Cesium.LabelStyle.FILL,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -14),
                        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 15000000.0),
                        disableDepthTestDistance: 1000000.0
                    }
                });

                // Loitering Orbit Ring
                addOrUpdate({
                    id: `uav-orbit-${idx}`,
                    polyline: {
                        positions: Cesium.Cartesian3.fromDegreesArrayHeights(uav.path),
                        width: 1,
                        material: new Cesium.PolylineDashMaterialProperty({
                            color: Cesium.Color.ORANGE.withAlpha(0.3),
                            dashLength: 8.0
                        })
                    }
                });

                // Tracked Center Point (Area of Interest)
                addOrUpdate({
                    id: `uav-target-${idx}`,
                    position: Cesium.Cartesian3.fromDegrees(uav.center[1], uav.center[0], 0),
                    point: {
                        pixelSize: 4,
                        color: Cesium.Color.RED.withAlpha(0.5),
                        outlineColor: Cesium.Color.RED,
                        outlineWidth: 1,
                        disableDepthTestDistance: 1000000.0
                    }
                });
            });
        }

        // Project Triangulated Flight Paths
        if (selectedEntity?.type === 'flight' || selectedEntity?.type === 'military_flight' || selectedEntity?.type === 'private_flight' || selectedEntity?.type === 'private_jet' || selectedEntity?.type === 'tracked_flight') {
            const fList = selectedEntity.type === 'flight' ? data.commercial_flights
                : selectedEntity.type === 'private_flight' ? data.private_flights
                    : selectedEntity.type === 'private_jet' ? data.private_jets
                        : selectedEntity.type === 'tracked_flight' ? data.tracked_flights
                            : data.military_flights;
            const flight = fList?.find((f: any) => f.icao24 === selectedEntity.id);
            if (flight && flight.origin_loc && flight.dest_loc) {
                const color = selectedEntity.type === 'flight' ? Cesium.Color.CYAN
                    : selectedEntity.type === 'private_flight' ? Cesium.Color.fromCssColorString('#FF8C00')
                        : selectedEntity.type === 'private_jet' ? Cesium.Color.fromCssColorString('#9B59B6')
                            : selectedEntity.type === 'tracked_flight' ? (trackedColorMap[flight.alert_color] || Cesium.Color.WHITE)
                                : Cesium.Color.YELLOW;

                // Add Polyline Arc from origin, through current position, to destination
                addOrUpdate({
                    id: `sel-poly-${selectedEntity.entityId}`,
                    polyline: {
                        positions: Cesium.Cartesian3.fromDegreesArrayHeights([
                            flight.origin_loc[0], flight.origin_loc[1], 0,
                            flight.lng, flight.lat, flight.alt || 5000,
                            flight.dest_loc[0], flight.dest_loc[1], 0
                        ]),
                        width: 2,
                        material: new Cesium.PolylineDashMaterialProperty({
                            color: color,
                            dashLength: 16.0
                        })
                    }
                });
            }
        }

        // Project Holographic 3D CCTV Video
        if (selectedEntity?.type === 'cctv') {
            const cam = data?.cctv?.find((c: any) => String(c.id) === String(selectedEntity.id));
            if (cam && !cam.media_url?.includes('embed')) {
                const isVideo = cam.media_url?.includes('.mp4');
                let material: any = Cesium.Color.LIME.withAlpha(0.2);
                const lng = cam.lng !== undefined ? cam.lng : cam.lon;

                try {
                    if (isVideo) {
                        const videoElement = document.createElement('video');
                        videoElement.crossOrigin = 'anonymous';
                        videoElement.src = cam.media_url;
                        videoElement.autoplay = true;
                        videoElement.loop = true;
                        videoElement.muted = true;
                        videoElement.play().catch(() => { }); // Catch autoplay errors silently

                        material = new Cesium.ImageMaterialProperty({
                            image: videoElement,
                            color: Cesium.Color.WHITE.withAlpha(0.9)
                        });
                    } else {
                        material = new Cesium.ImageMaterialProperty({
                            image: cam.media_url,
                            color: Cesium.Color.WHITE.withAlpha(0.9)
                        });
                    }

                    // A wall stands vertical. Calculate a 400m wide line facing mostly south for visibility.
                    // To maintain aspect ratio and prevent severe distortion, use a smaller width.
                    // ~200 meters wide, centered on the camera.
                    const widthOffset = 0.001;

                    addOrUpdate({
                        id: `holo-cctv-${cam.id}`,
                        wall: {
                            positions: Cesium.Cartesian3.fromDegreesArrayHeights([
                                lng - widthOffset, cam.lat, 200,
                                lng + widthOffset, cam.lat, 200
                            ]),
                            maximumHeights: [600, 600],
                            minimumHeights: [200, 200],
                            material: material,
                            outline: true,
                            outlineColor: Cesium.Color.LIME
                        }
                    });
                } catch (e) { }
            }
        }

        // Process Ships and Carriers
        if (data.ships) {
            const importantTypes = new Set(['carrier', 'military_vessel', 'tanker', 'cargo']);
            data.ships.forEach((s: any, idx: number) => {
                if (hasShipFilter && !matchesShipFilter(s)) return;
                const isImportant = importantTypes.has(s.type);
                const isPassenger = s.type === 'passenger';

                // Category-based filtering
                if (s.type === 'carrier' && activeLayers?.satellites === false) return;
                if (isImportant && s.type !== 'carrier' && activeLayers?.ships_important === false) return;
                if (isPassenger && activeLayers?.ships_passenger === false) return;
                if (!isImportant && !isPassenger && activeLayers?.ships_civilian === false) return;

                let svg = svgShipWhite;
                let color = Cesium.Color.WHITE;
                let width = 10, height = 10;
                if (s.type === 'carrier') {
                    svg = svgCarrier;
                    color = Cesium.Color.ORANGE;
                    width = 24;
                    height = 24;
                } else if (s.type === 'tanker' || s.type === 'cargo') {
                    svg = svgShipRed;
                    color = Cesium.Color.RED;
                    width = 12;
                    height = 12;
                } else if (s.type === 'yacht') {
                    svg = svgShipWhite;
                    color = Cesium.Color.WHITE;
                    width = 12;
                    height = 12;
                } else if (s.type === 'military_vessel') {
                    svg = svgShipYellow;
                    color = Cesium.Color.YELLOW;
                    width = 14;
                    height = 14;
                } else if (s.type === 'passenger') {
                    svg = svgShipWhite;
                    color = Cesium.Color.WHITE;
                    width = 14;
                    height = 14;
                }

                const currentPos = Cesium.Cartesian3.fromDegrees(s.lng, s.lat, 0);
                if (!occluder.isPointVisible(currentPos)) return;

                const shipId = s.mmsi ? `ship-${s.mmsi}` : `ship-${idx}`;

                let entity = shipDS.entities.getById(shipId);
                if (!entity) {
                    shipDS.entities.add({
                        id: shipId,
                        position: currentPos,
                        billboard: {
                            image: svg,
                            width: width, height: height,
                            rotation: Cesium.Math.toRadians(-s.heading || 0),
                            disableDepthTestDistance: 1000000.0
                        },
                        label: {
                            text: s.type === 'carrier' ? `[[${s.name}]]` : `[${s.name} ]`,
                            font: s.type === 'carrier' ? 'bold 12px monospace' : '9px monospace',
                            fillColor: color,
                            backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                            showBackground: true,
                            style: Cesium.LabelStyle.FILL,
                            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                            pixelOffset: new Cesium.Cartesian2(0, -(height / 2 + 6)),
                            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, s.type === 'carrier' ? 12000000.0 : 3000000.0),
                            disableDepthTestDistance: 1000000.0
                        }
                    });
                } else {
                    entity.position = currentPos as any;
                    if (entity.billboard) {
                        entity.billboard.rotation = Cesium.Math.toRadians(-s.heading || 0) as any;
                    }
                }

                touchedShipIds.add(shipId);
            });
        }

        // Process Earthquakes
        if (data.earthquakes && activeLayers?.earthquakes !== false) {
            data.earthquakes.forEach((q: any) => {
                const color = q.mag > 5 ? Cesium.Color.RED : Cesium.Color.ORANGE;
                addOrUpdate({
                    id: `quake - ${q.id}`,
                    position: Cesium.Cartesian3.fromDegrees(q.lng, q.lat, 0),
                    point: {
                        pixelSize: q.mag * 3,
                        color: Cesium.Color.fromCssColorString('rgba(0,0,0,0)'),
                        outlineColor: color,
                        outlineWidth: 2
                    },
                    label: {
                        text: `[M${q.mag.toFixed(1)} ]\n${q.place.substring(0, 20)}`,
                        font: 'bold 9px monospace',
                        fillColor: color,
                        backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                        showBackground: true,
                        style: Cesium.LabelStyle.FILL,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -10),
                        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 5000000.0)
                    }
                });
            });
        }

        // Process Weather Radar
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
        }

        // Process Airports
        if (data.airports) {
            const findByIcao = (list: any[]) => list?.find((f: any) => f.icao24 === selectedEntity?.id);
            const selectedFlight = (selectedEntity?.type === 'flight' || selectedEntity?.type === 'military_flight' || selectedEntity?.type === 'private_flight' || selectedEntity?.type === 'private_jet' || selectedEntity?.type === 'tracked_flight')
                ? (selectedEntity?.type === 'flight' ? findByIcao(data.commercial_flights)
                    : selectedEntity?.type === 'private_flight' ? findByIcao(data.private_flights)
                        : selectedEntity?.type === 'private_jet' ? findByIcao(data.private_jets)
                            : selectedEntity?.type === 'tracked_flight' ? findByIcao(data.tracked_flights)
                                : findByIcao(data.military_flights))
                : null;

            data.airports.forEach((apt: any) => {
                const isExplicitlySelected = selectedEntity?.type === 'airport' && String(selectedEntity.id) === String(apt.id);
                const isOrigin = selectedFlight && selectedFlight.origin_name && selectedFlight.origin_name.startsWith(apt.iata);
                const isDest = selectedFlight && selectedFlight.dest_name && selectedFlight.dest_name.startsWith(apt.iata);

                const showAirport = isExplicitlySelected || isOrigin || isDest;

                addOrUpdate({
                    id: `apt-${apt.id}`,
                    show: showAirport,
                    position: Cesium.Cartesian3.fromDegrees(apt.lng, apt.lat, 0),
                    point: {
                        pixelSize: 6,
                        color: Cesium.Color.WHITE,
                        outlineColor: Cesium.Color.BLACK,
                        outlineWidth: 2,
                        disableDepthTestDistance: 1000000.0
                    },
                    label: {
                        show: showAirport,
                        text: `(${apt.iata}: ${apt.name})`,
                        font: 'bold 10px monospace',
                        fillColor: Cesium.Color.WHITE,
                        backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                        showBackground: true,
                        style: Cesium.LabelStyle.FILL,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                        pixelOffset: new Cesium.Cartesian2(0, -10),
                        // Only show labels when reasonably zoomed in to prevent map clutter (approx 5M meters)
                        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 5000000.0)
                    }
                });
            });
        }

        // Process CCTV (clustered)
        if (data.cctv && activeLayers?.cctv !== false && cctvDS) {
            data.cctv.forEach((cam: any) => {
                const lng = cam.lon !== undefined ? cam.lon : cam.lng;
                if (lng === undefined || cam.lat === undefined) return;

                const cctvId = `cctv-${cam.id}`;
                touchedCctvIds.add(cctvId);

                const existing = cctvDS.entities.getById(cctvId);
                if (existing) {
                    existing.position = Cesium.Cartesian3.fromDegrees(lng, cam.lat, 0);
                } else {
                    cctvDS.entities.add({
                        id: cctvId,
                        position: Cesium.Cartesian3.fromDegrees(lng, cam.lat, 0),
                        point: {
                            pixelSize: 8,
                            color: Cesium.Color.LIME,
                            outlineColor: Cesium.Color.BLACK,
                            outlineWidth: 2,
                            disableDepthTestDistance: 1000000.0
                        },
                        label: {
                            text: `[CCTV: ${cam.direction_facing ? cam.direction_facing.substring(0, 15) : 'Camera'}... ]`,
                            font: 'bold 10px monospace',
                            fillColor: Cesium.Color.LIME,
                            backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                            showBackground: true,
                            style: Cesium.LabelStyle.FILL,
                            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                            pixelOffset: new Cesium.Cartesian2(0, -10),
                            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 500000.0)
                        }
                    });
                }
            });
        } else if (cctvDS) {
            // Layer toggled off — remove all CCTV entities
            cctvDS.entities.removeAll();
        }

        // Bikeshare removed per user request


        // Process Traffic Accidents/Signs removed per User request to declutter CCTV

        // Process Satellites
        if (data.satellites && activeLayers?.satellites !== false) {
            const date = new Date();
            data.satellites.forEach((sat: any, idx: number) => {
                try {
                    const satrec = satellite.twoline2satrec(sat.tle1, sat.tle2);
                    const positionAndVelocity = satellite.propagate(satrec, date);
                    const gmst = satellite.gstime(date);
                    if (positionAndVelocity && (positionAndVelocity as any).position && typeof (positionAndVelocity as any).position !== 'boolean') {
                        const positionGd = satellite.eciToGeodetic((positionAndVelocity as any).position, gmst);
                        const longitude = satellite.degreesLong(positionGd.longitude);
                        const latitude = satellite.degreesLat(positionGd.latitude);
                        const height = positionGd.height * 1000;

                        addOrUpdate({
                            id: `satellite-${sat.id}`,
                            position: Cesium.Cartesian3.fromDegrees(longitude, latitude, height),
                            point: {
                                pixelSize: 6,
                                color: Cesium.Color.AQUA,
                                disableDepthTestDistance: 1000000.0
                            },
                            label: {
                                text: `[ SAT: ${sat.name} ]`,
                                font: 'bold 10px monospace',
                                fillColor: Cesium.Color.AQUA,
                                backgroundColor: Cesium.Color.fromCssColorString('rgba(0,0,0,0.8)'),
                                showBackground: true,
                                style: Cesium.LabelStyle.FILL,
                                verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                                pixelOffset: new Cesium.Cartesian2(0, -10),
                                distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 10000000.0),
                                disableDepthTestDistance: 1000000.0
                            }
                        });

                        // Add Orbital Path (sampled for performance)
                        if (idx % 20 === 0) { // Only show paths for every 20th satellite
                            const orbitPoints = [];
                            for (let i = 0; i < 90; i += 5) {
                                const futureDate = new Date(date.getTime() + i * 60000);
                                const fPV = satellite.propagate(satrec, futureDate);
                                const fGmst = satellite.gstime(futureDate);
                                if (fPV && (fPV as any).position && typeof (fPV as any).position !== 'boolean') {
                                    const fGd = satellite.eciToGeodetic((fPV as any).position, fGmst);
                                    orbitPoints.push(satellite.degreesLong(fGd.longitude));
                                    orbitPoints.push(satellite.degreesLat(fGd.latitude));
                                    orbitPoints.push(fGd.height * 1000);
                                }
                            }
                            if (orbitPoints.length > 3) {
                                addOrUpdate({
                                    polyline: {
                                        positions: Cesium.Cartesian3.fromDegreesArrayHeights(orbitPoints),
                                        width: 1,
                                        material: new Cesium.PolylineGlowMaterialProperty({
                                            glowPower: 0.1,
                                            color: Cesium.Color.AQUA.withAlpha(0.3)
                                        })
                                    }
                                });
                            }
                        }
                    }
                } catch (e) { }
            });
        }

        // Draw orbital path if satellite selected
        if (selectedEntity && selectedEntity.type === 'satellite') {
            try {
                const satrec = satellite.twoline2satrec(selectedEntity.tle1, selectedEntity.tle2);
                const positions = [];
                const date = new Date();
                // 100 minutes forward for LEO orbit track
                for (let i = 0; i <= 100; i++) {
                    const d = new Date(date.getTime() + i * 60000);
                    const p = satellite.propagate(satrec, d);
                    if (p && (p as any).position && typeof (p as any).position !== 'boolean') {
                        const gmst = satellite.gstime(d);
                        const posGd = satellite.eciToGeodetic((p as any).position, gmst);
                        positions.push(satellite.degreesLong(posGd.longitude));
                        positions.push(satellite.degreesLat(posGd.latitude));
                        positions.push(posGd.height * 1000);
                    }
                }

                if (positions.length > 0) {
                    addOrUpdate({
                        id: `orbit - ${selectedEntity.entityId}`,
                        polyline: {
                            positions: Cesium.Cartesian3.fromDegreesArrayHeights(positions),
                            width: 2,
                            material: new Cesium.PolylineDashMaterialProperty({
                                color: Cesium.Color.CYAN,
                                dashLength: 16.0
                            })
                        }
                    });
                }
            } catch (e) { }
        }

        // Prune unused entities from viewer.entities
        const allEntities = viewer.entities.values;
        for (let i = allEntities.length - 1; i >= 0; i--) {
            const e = allEntities[i];
            if (!touchedIds.has(e.id)) {
                viewer.entities.remove(e);
            }
        }
        viewer.entities.resumeEvents();

        // Prune stale ships from clustered data source
        if (shipDS) {
            const entities = shipDS.entities.values;
            for (let i = entities.length - 1; i >= 0; i--) {
                const id = entities[i].id;
                if (!touchedShipIds.has(id)) {
                    shipDS.entities.removeById(id);
                }
            }
            shipDS.entities.resumeEvents();
        }

        // Prune stale CCTV from clustered data source
        if (cctvDS) {
            const entities = cctvDS.entities.values;
            for (let i = entities.length - 1; i >= 0; i--) {
                const id = entities[i].id;
                if (!touchedCctvIds.has(id)) {
                    cctvDS.entities.removeById(id);
                }
            }
            cctvDS.entities.resumeEvents();
        }
    }, [data, activeLayers, effects, selectedEntity]);

    return (
        <div
            ref={cesiumContainer}
            className={`absolute inset-0 z-0 h-full w-full bg-black ${isEavesdropping ? 'cursor-crosshair' : 'cursor-default'}`}
            style={{ pointerEvents: 'auto' }}
        >
            {/* IN-MAP CONTEXT OVERLAYS */}
            {selectedEntity && selectedEntity.type === 'news' && popupPosition && (
                <div
                    className="absolute z-50 pointer-events-auto transform -translate-x-1/2 -translate-y-full pb-8"
                    style={{ left: popupPosition.x, top: popupPosition.y }}
                >
                    <div className="w-[300px] bg-black/80 backdrop-blur-md border border-cyan-500/30 rounded-lg p-3 shadow-[0_0_15px_rgba(0,255,255,0.2)]">
                        {(() => {
                            const cluster = data?.news?.[selectedEntity.id as number];
                            if (!cluster) return null;
                            return (
                                <div className="flex flex-col gap-2 font-mono">
                                    {cluster.machine_assessment && (
                                        <div className="mb-2 p-2 bg-black/80 border border-cyan-800/80 rounded-sm text-[9px] text-cyan-400 font-mono leading-tight relative overflow-hidden shadow-[inset_0_0_15px_rgba(0,255,255,0.1)] shrink-0">
                                            <div className="absolute top-0 left-0 w-[2px] h-full bg-cyan-500 animate-pulse"></div>
                                            <span className="font-bold text-white">&gt;_ SYS.ANALYSIS: </span>
                                            <span className="text-cyan-300 opacity-90">{cluster.machine_assessment}</span>
                                        </div>
                                    )}

                                    <div className="flex flex-col gap-3 max-h-[300px] overflow-y-auto styled-scrollbar pr-1">
                                        {cluster.articles && cluster.articles.map((item: any, idx: number) => {
                                            const isHigh = item.risk_score >= 5;
                                            const titleClass = isHigh ? "text-red-300 font-bold" : "text-cyan-300 font-medium";
                                            return (
                                                <div key={idx} className="flex flex-col gap-1 pb-2 border-b border-cyan-500/20 last:border-0 last:pb-0">
                                                    <div className="flex items-center justify-between text-[9px] uppercase tracking-widest">
                                                        <span className="font-bold flex items-center gap-1 text-cyan-500">
                                                            &gt;_ {item.source}
                                                        </span>
                                                        <span className={isHigh ? "text-red-500" : "text-cyan-500"}>LVL: {item.risk_score}/10</span>
                                                    </div>
                                                    <a href={item.link} target="_blank" rel="noreferrer" className={`text-xs ${titleClass} hover:text-white transition-colors leading-relaxed`}>
                                                        {item.title}
                                                    </a>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            );
                        })()}
                        <div className="absolute left-1/2 bottom-0 w-[1px] h-8 bg-cyan-500/50 transform -translate-x-1/2" />
                    </div>
                </div>
            )}

            {selectedEntity && selectedEntity.type === 'cctv' && popupPosition && (
                <div
                    className="absolute z-50 pointer-events-auto transform -translate-x-1/2 -translate-y-full pb-8"
                    style={{ left: popupPosition.x, top: popupPosition.y }}
                >
                    <div className="w-[320px] bg-black/80 backdrop-blur-md border border-lime-500/30 rounded-lg p-2 shadow-[0_0_15px_rgba(0,255,0,0.2)]">
                        {(() => {
                            const cam = data?.cctv?.find((c: any) => String(c.id) === String(selectedEntity.id));
                            if (!cam) return null;
                            return (
                                <div className="flex flex-col gap-2 font-mono">
                                    <div className="flex items-center justify-between text-[9px] uppercase tracking-widest border-b border-lime-500/20 pb-1">
                                        <span className="font-bold flex items-center gap-1 text-lime-500">
                                            &gt;_ {cam.source_agency || 'INTERCEPT'}
                                        </span>
                                        <span className="text-lime-500 animate-pulse">LIVE</span>
                                    </div>
                                    <div className="relative w-full h-12 border border-lime-900/50 bg-black/50 flex flex-col items-center justify-center p-1 rounded-sm">
                                        <div className="text-[10px] text-lime-500 font-bold tracking-widest animate-pulse">
                                            [ FEED DIVERTED TO HOLOGRAPHIC MESH ]
                                        </div>
                                        <div className="absolute top-1 left-1 text-[7px] text-lime-600">
                                            REC // {cam.id}
                                        </div>
                                    </div>
                                    <div className="text-[10px] text-lime-400 font-bold leading-tight">
                                        {cam.direction_facing || 'UNKNOWN MOUNT'}
                                    </div>
                                </div>
                            );
                        })()}
                        {/* Connecting line to the marker */}
                        <div className="absolute left-1/2 bottom-0 w-[1px] h-8 bg-lime-500/50 transform -translate-x-1/2" />
                    </div>
                </div>
            )}

            {selectedEntity && selectedEntity.type === 'gdelt' && popupPosition && (
                <div
                    className="absolute z-50 pointer-events-auto transform -translate-x-1/2 -translate-y-full pb-8"
                    style={{ left: popupPosition.x, top: popupPosition.y }}
                >
                    <div className="w-[320px] bg-black/80 backdrop-blur-md border border-orange-500/30 rounded-lg p-3 shadow-[0_0_15px_rgba(255,165,0,0.2)]">
                        {(() => {
                            const incident = data?.gdelt?.[selectedEntity.id as number];
                            if (!incident) return null;
                            const props = incident.properties || {};
                            // Use regex to strip GDELT's inline a-tags so we can render cleanly or just render dangerously
                            return (
                                <div className="flex flex-col gap-2 font-mono">
                                    <div className="flex items-center justify-between text-[9px] uppercase tracking-widest border-b border-orange-500/20 pb-1">
                                        <span className="font-bold flex items-center gap-1 text-orange-500">
                                            &gt;_ KINETIC EVENT
                                        </span>
                                        <span className="text-red-500 font-bold animate-pulse">MILITARY</span>
                                    </div>
                                    <div className="text-[11px] text-orange-300 font-bold leading-tight mt-1">
                                        {props.location || props.name || 'UNKNOWN LOCATION'}
                                    </div>
                                    <div className="text-[10px] text-gray-300 mt-2 leading-relaxed preview-html"
                                        dangerouslySetInnerHTML={{ __html: props.html || 'No summary available.' }}
                                    />
                                </div>
                            );
                        })()}
                        <div className="absolute left-1/2 bottom-0 w-[1px] h-8 bg-orange-500/50 transform -translate-x-1/2" />
                    </div>
                </div>
            )}
        </div>
    );
}
