"use client";

import { API_BASE } from "@/lib/api";
import React, { useMemo, useState, useEffect, useCallback, useRef } from "react";
import Map, { Source, Layer, MapRef, ViewState, Popup, Marker } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { computeNightPolygon } from "@/utils/solarTerminator";
import ScaleBar from "@/components/ScaleBar";
import maplibregl from "maplibre-gl";
import { AlertTriangle } from "lucide-react";
import WikiImage from "@/components/WikiImage";
import { useTheme } from "@/lib/ThemeContext";

const svgPlaneCyan = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="cyan" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`)}`;
const svgPlaneYellow = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`)}`;
const svgPlaneOrange = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="#FF8C00" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`)}`;
const svgPlanePurple = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="#9B59B6" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`)}`;
const svgFighter = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="M12 2L14 8L18 10L14 16L15 22L12 20L9 22L10 16L6 10L10 8L12 2Z"/></svg>`)}`;
const svgHeli = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="black" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgHeliCyan = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="cyan" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="cyan" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgHeliOrange = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="#FF8C00" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#FF8C00" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgHeliPurple = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="#9B59B6" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#9B59B6" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgTanker = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /><line x1="12" y1="20" x2="12" y2="24" stroke="yellow" stroke-width="2" /></svg>`)}`;
const svgRecon = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /><ellipse cx="12" cy="11" rx="5" ry="3" fill="none" stroke="red" stroke-width="1.5"/></svg>`)}`;
const svgPlanePink = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="#FF1493" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`)}`;
const svgPlaneAlertRed = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="#FF2020" stroke="black"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`)}`;
const svgPlaneDarkBlue = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="#1A3A8A" stroke="#4A80D0"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`)}`;
const svgPlaneWhiteAlert = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="white" stroke="#ff0000" stroke-width="2"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`)}`;
const svgHeliPink = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="#FF1493" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#FF1493" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgHeliAlertRed = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="#ff0000" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#ff0000" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgHeliDarkBlue = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="#000080" stroke="#4A80D0"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#4A80D0" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgHeliBlue = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="#3b82f6" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#3b82f6" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgHeliLime = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="#32CD32" stroke="black"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#32CD32" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgHeliWhiteAlert = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="white" stroke="#666"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#999" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgPlaneBlack = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="#222" stroke="#444"><path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" /></svg>`)}`;
const svgHeliBlack = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="#222" stroke="#444"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#444" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;
const svgDrone = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="orange" stroke="black"><path d="M12 2L15 8H9L12 2Z" /><rect x="8" y="8" width="8" height="2" /><path d="M4 10L10 14H14L20 10V12L14 16H10L4 12V10Z" /><circle cx="12" cy="14" r="2" fill="red"/></svg>`)}`;
const svgDataCenter = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="1.5"><rect x="3" y="3" width="18" height="6" rx="1" fill="#2e1065"/><rect x="3" y="11" width="18" height="6" rx="1" fill="#2e1065"/><circle cx="7" cy="6" r="1" fill="#a78bfa"/><circle cx="7" cy="14" r="1" fill="#a78bfa"/><line x1="11" y1="6" x2="17" y2="6" stroke="#a78bfa" stroke-width="1"/><line x1="11" y1="14" x2="17" y2="14" stroke="#a78bfa" stroke-width="1"/><line x1="12" y1="19" x2="12" y2="22" stroke="#a78bfa" stroke-width="1.5"/></svg>`)}`;
const svgShipGray = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="12" height="24" viewBox="0 0 24 24" fill="none"><path d="M6 20 L6 8 L12 2 L18 8 L18 20 C18 22 6 22 6 20 Z" fill="gray" stroke="#000" stroke-width="1"/><polygon points="12,6 16,16 8,16" fill="#fff" stroke="#000" stroke-width="1"/></svg>`)}`;
const svgShipRed = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="16" height="32" viewBox="0 0 24 24" fill="none"><path d="M6 22 L6 6 L12 2 L18 6 L18 22 Z" fill="#ff2222" stroke="#000" stroke-width="1"/><rect x="8" y="15" width="8" height="4" fill="#880000" stroke="#000" stroke-width="1"/><rect x="8" y="7" width="8" height="6" fill="#444" stroke="#000" stroke-width="1"/></svg>`)}`;
const svgShipYellow = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="14" height="34" viewBox="0 0 24 24" fill="none"><path d="M7 22 L7 6 L12 1 L17 6 L17 22 Z" fill="yellow" stroke="#000" stroke-width="1"/><rect x="9" y="8" width="6" height="8" fill="#555" stroke="#000" stroke-width="1"/><circle cx="12" cy="18" r="1.5" fill="#000"/><line x1="12" y1="18" x2="12" y2="24" stroke="#000" stroke-width="1.5"/></svg>`)}`;
const svgShipBlue = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="16" height="32" viewBox="0 0 24 24" fill="none"><path d="M6 22 L6 6 L12 2 L18 6 L18 22 Z" fill="#3b82f6" stroke="#000" stroke-width="1"/></svg>`)}`;
const svgShipWhite = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="18" height="36" viewBox="0 0 24 24" fill="none"><path d="M5 21 L5 8 L12 2 L19 8 L19 21 C19 23 5 23 5 21 Z" fill="white" stroke="#000" stroke-width="1"/><rect x="7" y="10" width="10" height="8" fill="#90cdf4" stroke="#000" stroke-width="1"/><circle cx="12" cy="14" r="2" fill="yellow" stroke="#000"/></svg>`)}`;
const svgCarrier = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="orange" stroke="black"><polygon points="3,21 21,21 20,4 16,4 16,3 12,3 12,4 4,4" /><rect x="15" y="6" width="3" height="10" /></svg>`)}`;
const svgCctv = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="cyan" stroke-width="2"><path d="M16.75 12h3.632a1 1 0 0 1 .894 1.447l-2.034 4.069a1 1 0 0 1-.894.553H5.652a1 1 0 0 1-.894-.553L2.724 13.447A1 1 0 0 1 3.618 12h3.632M14 12V8a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v4a4 4 0 1 0 8 0Z" /></svg>`)}`;
const svgWarning = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="yellow" stroke="black"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>`)}`;
const svgThreat = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="#ffff00" stroke="#ff0000" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>`)}`;
const svgTriangleYellow = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="#ffaa00" stroke="#000" stroke-width="1"><path d="M1 21h22L12 2 1 21z"/></svg>`)}`;
const svgTriangleRed = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="#ff0000" stroke="#fff" stroke-width="1"><path d="M1 21h22L12 2 1 21z"/></svg>`)}`;

// --- Aircraft type-specific SVG paths (top-down silhouettes) ---
// Airliner: wide swept wings with engine pods, narrow fuselage
const AIRLINER_PATH = "M12 2C11.2 2 10.5 2.8 10.5 3.5V8.5L3 13V15L10.5 12.5V18L8 19.5V21L12 19.5L16 21V19.5L13.5 18V12.5L21 15V13L13.5 8.5V3.5C13.5 2.8 12.8 2 12 2Z M5.5 13.5L3.5 14.5 M18.5 13.5L20.5 14.5";
// Turboprop: straight high wings, shorter body
const TURBOPROP_PATH = "M12 3C11.3 3 10.8 3.5 10.8 4V9L3 12V13.5L10.8 11.5V18.5L9 19.5V21L12 20L15 21V19.5L13.2 18.5V11.5L21 13.5V12L13.2 9V4C13.2 3.5 12.7 3 12 3Z";
// Bizjet: sleek, small swept wings, T-tail
const BIZJET_PATH = "M12 1.5C11.4 1.5 11 2 11 2.8V9L5 12.5V14L11 12V18.5L8.5 20V21.5L12 20.5L15.5 21.5V20L13 18.5V12L19 14V12.5L13 9V2.8C13 2 12.6 1.5 12 1.5Z";

// --- Fire icon SVGs for FIRMS hotspots (multi-tongue flame, unmistakably fire) ---
function makeFireSvg(fill: string, innerFill: string, size = 18) {
    // Multi-forked flame: main body + left tongue + right tongue + inner glow
    return `data:image/svg+xml;utf8,${encodeURIComponent(
        `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 28">` +
        // Main flame body (wide base, pointed top)
        `<path d="M12 1C12 1 9 5 8 8C7 11 5.5 13 5.5 16.5C5.5 20.5 8 23.5 12 23.5C16 23.5 18.5 20.5 18.5 16.5C18.5 13 17 11 16 8C15 5 12 1 12 1Z" fill="${fill}" stroke="rgba(0,0,0,0.7)" stroke-width="0.7"/>` +
        // Left tongue (forks out left from top)
        `<path d="M10 8C10 8 7.5 4.5 7 2.5C7 2.5 6 5.5 7 9C7.5 10.5 8.5 11.5 9.5 12" fill="${fill}" stroke="rgba(0,0,0,0.5)" stroke-width="0.4"/>` +
        // Right tongue (forks out right from top)
        `<path d="M14 8C14 8 16.5 4.5 17 2.5C17 2.5 18 5.5 17 9C16.5 10.5 15.5 11.5 14.5 12" fill="${fill}" stroke="rgba(0,0,0,0.5)" stroke-width="0.4"/>` +
        // Inner bright core
        `<path d="M12 8C12 8 10.5 11 10.5 14.5C10.5 17.5 11 19.5 12 20C13 19.5 13.5 17.5 13.5 14.5C13.5 11 12 8 12 8Z" fill="${innerFill}" opacity="0.85"/>` +
        `</svg>`
    )}`;
}
const svgFireYellow = makeFireSvg('#ffcc00', '#fff5aa', 16);
const svgFireOrange = makeFireSvg('#ff8800', '#ffcc00', 18);
const svgFireRed = makeFireSvg('#ff2200', '#ff8800', 20);
const svgFireDarkRed = makeFireSvg('#cc0000', '#ff2200', 22);
// Larger fire icons for cluster markers (visually distinct from Global Incidents circles)
const svgFireClusterSmall = makeFireSvg('#ff6600', '#ffcc00', 32);
const svgFireClusterMed = makeFireSvg('#ff3300', '#ff8800', 40);
const svgFireClusterLarge = makeFireSvg('#cc0000', '#ff3300', 48);
const svgFireClusterXL = makeFireSvg('#880000', '#cc0000', 56);

function makeAircraftSvg(type: 'airliner' | 'turboprop' | 'bizjet' | 'generic', fill: string, stroke = 'black', size = 20) {
    const paths: Record<string, string> = { airliner: AIRLINER_PATH, turboprop: TURBOPROP_PATH, bizjet: BIZJET_PATH, generic: "M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" };
    const p = paths[type] || paths.generic;
    // Airliner gets engine pod circles
    const extras = type === 'airliner' ? `<circle cx="7" cy="12.5" r="1.2" fill="${fill}" stroke="${stroke}" stroke-width="0.5"/><circle cx="17" cy="12.5" r="1.2" fill="${fill}" stroke="${stroke}" stroke-width="0.5"/>` : '';
    return `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="${stroke}"><path d="${p}"/>${extras}</svg>`)}`;
}

// POTUS fleet — oversized hot pink with yellow halo ring
const svgPotusPlane = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><circle cx="16" cy="16" r="15" fill="none" stroke="gold" stroke-width="2" stroke-dasharray="4 2"/><g transform="translate(4,4)"><path d="${AIRLINER_PATH}" fill="#FF1493" stroke="black"/><circle cx="7" cy="12.5" r="1.2" fill="#FF1493" stroke="black" stroke-width="0.5"/><circle cx="17" cy="12.5" r="1.2" fill="#FF1493" stroke="black" stroke-width="0.5"/></g></svg>`)}`;
const svgPotusHeli = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><circle cx="16" cy="16" r="15" fill="none" stroke="gold" stroke-width="2" stroke-dasharray="4 2"/><g transform="translate(6,4)"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z" fill="#FF1493" stroke="black"/><circle cx="12" cy="12" r="8" fill="none" stroke="#FF1493" stroke-dasharray="2 2" stroke-width="1"/></g></svg>`)}`;

// POTUS fleet ICAO hex codes (verified FAA registry)
const POTUS_ICAOS = new Set(['ADFDF8','ADFDF9','AE0865','AE5E76','AE5E77','AE5E79']);

// Pre-built aircraft SVGs by type & color
const svgAirlinerCyan = makeAircraftSvg('airliner', 'cyan');
const svgAirlinerOrange = makeAircraftSvg('airliner', '#FF8C00');
const svgAirlinerPurple = makeAircraftSvg('airliner', '#9B59B6');
const svgAirlinerYellow = makeAircraftSvg('airliner', 'yellow');
const svgAirlinerPink = makeAircraftSvg('airliner', '#FF1493', 'black', 22);
const svgAirlinerRed = makeAircraftSvg('airliner', '#FF2020', 'black', 22);
const svgAirlinerDarkBlue = makeAircraftSvg('airliner', '#1A3A8A', '#4A80D0', 22);
const svgAirlinerBlue = makeAircraftSvg('airliner', '#3b82f6', 'black', 22);
const svgAirlinerLime = makeAircraftSvg('airliner', '#32CD32', 'black', 22);
const svgAirlinerBlack = makeAircraftSvg('airliner', '#222', '#555', 22);
const svgAirlinerWhite = makeAircraftSvg('airliner', 'white', '#666', 22);

const svgTurbopropCyan = makeAircraftSvg('turboprop', 'cyan');
const svgTurbopropOrange = makeAircraftSvg('turboprop', '#FF8C00');
const svgTurbopropPurple = makeAircraftSvg('turboprop', '#9B59B6');
const svgTurbopropYellow = makeAircraftSvg('turboprop', 'yellow');
const svgTurbopropPink = makeAircraftSvg('turboprop', '#FF1493', 'black', 22);
const svgTurbopropRed = makeAircraftSvg('turboprop', '#FF2020', 'black', 22);
const svgTurbopropDarkBlue = makeAircraftSvg('turboprop', '#1A3A8A', '#4A80D0', 22);
const svgTurbopropBlue = makeAircraftSvg('turboprop', '#3b82f6', 'black', 22);
const svgTurbopropLime = makeAircraftSvg('turboprop', '#32CD32', 'black', 22);
const svgTurbopropBlack = makeAircraftSvg('turboprop', '#222', '#555', 22);
const svgTurbopropWhite = makeAircraftSvg('turboprop', 'white', '#666', 22);

const svgBizjetCyan = makeAircraftSvg('bizjet', 'cyan');
const svgBizjetOrange = makeAircraftSvg('bizjet', '#FF8C00');
const svgBizjetPurple = makeAircraftSvg('bizjet', '#9B59B6');
const svgBizjetYellow = makeAircraftSvg('bizjet', 'yellow');
const svgBizjetPink = makeAircraftSvg('bizjet', '#FF1493', 'black', 22);
const svgBizjetRed = makeAircraftSvg('bizjet', '#FF2020', 'black', 22);
const svgBizjetDarkBlue = makeAircraftSvg('bizjet', '#1A3A8A', '#4A80D0', 22);
const svgBizjetBlue = makeAircraftSvg('bizjet', '#3b82f6', 'black', 22);
const svgBizjetLime = makeAircraftSvg('bizjet', '#32CD32', 'black', 22);
const svgBizjetBlack = makeAircraftSvg('bizjet', '#222', '#555', 22);
const svgBizjetWhite = makeAircraftSvg('bizjet', 'white', '#666', 22);

// Grey variants for grounded/parked aircraft (altitude 0)
const svgAirlinerGrey = makeAircraftSvg('airliner', '#555', '#333');
const svgTurbopropGrey = makeAircraftSvg('turboprop', '#555', '#333');
const svgBizjetGrey = makeAircraftSvg('bizjet', '#555', '#333');
const svgHeliGrey = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="#555" stroke="#333"><path d="M10 6L10 14L8 16L8 18L10 17L12 22L14 17L16 18L16 16L14 14L14 6C14 4 13 2 12 2C11 2 10 4 10 6Z"/><circle cx="12" cy="12" r="8" fill="none" stroke="#555" stroke-dasharray="2 2" stroke-width="1"/></svg>`)}`;

// Grey icon map for grounded aircraft
const GROUNDED_ICON_MAP: Record<string, string> = { heli: 'svgHeliGrey', turboprop: 'svgTurbopropGrey', bizjet: 'svgBizjetGrey', airliner: 'svgAirlinerGrey' };

// Per-layer color maps (module-level to avoid re-allocation every render tick)
const COLOR_MAP_COMMERCIAL: Record<string, string> = { heli: 'svgHeliCyan', turboprop: 'svgTurbopropCyan', bizjet: 'svgBizjetCyan', airliner: 'svgAirlinerCyan' };
const COLOR_MAP_PRIVATE: Record<string, string> = { heli: 'svgHeliOrange', turboprop: 'svgTurbopropOrange', bizjet: 'svgBizjetOrange', airliner: 'svgAirlinerOrange' };
const COLOR_MAP_JETS: Record<string, string> = { heli: 'svgHeliPurple', turboprop: 'svgTurbopropPurple', bizjet: 'svgBizjetPurple', airliner: 'svgAirlinerPurple' };
const COLOR_MAP_MILITARY: Record<string, string> = { heli: 'svgHeli', turboprop: 'svgTurbopropYellow', bizjet: 'svgBizjetYellow', airliner: 'svgAirlinerYellow' };
const MIL_SPECIAL_MAP: Record<string, string> = { fighter: 'svgFighter', tanker: 'svgTanker', recon: 'svgRecon' };

// ICAO type code -> aircraft shape classification
const HELI_TYPES = new Set(['R22', 'R44', 'R66', 'B06', 'B05', 'B47G', 'B105', 'B212', 'B222', 'B230', 'B407', 'B412', 'B429', 'B430', 'B505', 'BK17', 'S55', 'S58', 'S61', 'S64', 'S70', 'S76', 'S92', 'A109', 'A119', 'A139', 'A169', 'A189', 'AW09', 'EC20', 'EC25', 'EC30', 'EC35', 'EC45', 'EC55', 'EC75', 'H125', 'H130', 'H135', 'H145', 'H155', 'H160', 'H175', 'H215', 'H225', 'AS32', 'AS35', 'AS50', 'AS55', 'AS65', 'MD52', 'MD60', 'MDHI', 'MD90', 'NOTR', 'HUEY', 'GAMA', 'CABR', 'EXE', 'R300', 'R480', 'LAMA', 'ALLI', 'PUMA', 'NH90', 'CH47', 'UH1', 'UH60', 'AH64', 'MI8', 'MI24', 'MI26', 'MI28', 'KA52', 'K32', 'LYNX', 'WILD', 'MRLX', 'A149', 'A119']);
const TURBOPROP_TYPES = new Set(['AT43', 'AT45', 'AT72', 'AT73', 'AT75', 'AT76', 'B190', 'B350', 'BE20', 'BE30', 'BE40', 'BE9L', 'BE99', 'C130', 'C160', 'C208', 'C212', 'C295', 'CN35', 'D228', 'D328', 'DHC2', 'DHC3', 'DHC4', 'DHC5', 'DHC6', 'DHC7', 'DHC8', 'DO28', 'DH8A', 'DH8B', 'DH8C', 'DH8D', 'E110', 'E120', 'F27', 'F406', 'F50', 'G159', 'G73T', 'J328', 'JS31', 'JS32', 'JS41', 'L188', 'MA60', 'M28', 'N262', 'P68', 'P180', 'PA31', 'PA42', 'PC12', 'PC21', 'PC24', 'S2', 'S340', 'SF34', 'SF50', 'SW4', 'TRIS', 'TBM7', 'TBM8', 'TBM9', 'C30J', 'C5M', 'AN12', 'AN24', 'AN26', 'AN30', 'AN32', 'IL18', 'L410', 'Y12', 'BALL', 'AEST', 'AC68', 'AC80', 'AC90', 'AC95', 'AC11', 'C172', 'C182', 'C206', 'C210', 'C310', 'C337', 'C402', 'C414', 'C421', 'C425', 'C441', 'M20P', 'M20T', 'PA28', 'PA32', 'PA34', 'PA44', 'PA46', 'PA60', 'P28A', 'P28B', 'P28R', 'P32R', 'P46T', 'SR20', 'SR22', 'DA40', 'DA42', 'DA62', 'RV10', 'BE33', 'BE35', 'BE36', 'BE55', 'BE58', 'DR40', 'TB20', 'AA5']);
const BIZJET_TYPES = new Set(['ASTR', 'C25A', 'C25B', 'C25C', 'C25M', 'C500', 'C501', 'C510', 'C525', 'C526', 'C550', 'C551', 'C560', 'C56X', 'C650', 'C680', 'C700', 'C750', 'CL30', 'CL35', 'CL60', 'CONI', 'CRJX', 'E35L', 'E45X', 'E50P', 'E55P', 'F2TH', 'F900', 'FA10', 'FA20', 'FA50', 'FA7X', 'FA8X', 'G100', 'G150', 'G200', 'G280', 'GA5C', 'GA6C', 'GALX', 'GL5T', 'GL7T', 'GLEX', 'GLF2', 'GLF3', 'GLF4', 'GLF5', 'GLF6', 'H25A', 'H25B', 'H25C', 'HA4T', 'HDJT', 'LJ23', 'LJ24', 'LJ25', 'LJ28', 'LJ31', 'LJ35', 'LJ40', 'LJ45', 'LJ55', 'LJ60', 'LJ70', 'LJ75', 'MU30', 'PC24', 'PRM1', 'SBR1', 'SBR2', 'WW24', 'BE40', 'BLCF']);

function classifyAircraft(model: string, category?: string): 'heli' | 'turboprop' | 'bizjet' | 'airliner' {
    const m = (model || '').toUpperCase();
    if (category === 'heli' || HELI_TYPES.has(m)) return 'heli';
    if (BIZJET_TYPES.has(m)) return 'bizjet';
    if (TURBOPROP_TYPES.has(m)) return 'turboprop';
    return 'airliner';
}

// --- Smooth position interpolation helpers ---
// Given heading (degrees) and speed (knots), compute new lat/lng after dt seconds
function interpolatePosition(lat: number, lng: number, headingDeg: number, speedKnots: number, dtSeconds: number, maxDist = 0, maxDt = 65): [number, number] {
    if (!speedKnots || speedKnots <= 0 || dtSeconds <= 0) return [lat, lng];
    // Cap interpolation time to prevent runaway drift when data is stale
    const clampedDt = Math.min(dtSeconds, maxDt);
    // 1 knot = 1 nautical mile/hour = 1852 m/h
    const speedMps = speedKnots * 0.5144; // meters per second
    const dist = maxDist > 0 ? Math.min(speedMps * clampedDt, maxDist) : speedMps * clampedDt;
    const R = 6371000; // Earth radius in meters
    const headingRad = (headingDeg * Math.PI) / 180;
    const latRad = (lat * Math.PI) / 180;
    const lngRad = (lng * Math.PI) / 180;
    const newLatRad = Math.asin(
        Math.sin(latRad) * Math.cos(dist / R) +
        Math.cos(latRad) * Math.sin(dist / R) * Math.cos(headingRad)
    );
    const newLngRad = lngRad + Math.atan2(
        Math.sin(headingRad) * Math.sin(dist / R) * Math.cos(latRad),
        Math.cos(dist / R) - Math.sin(latRad) * Math.sin(newLatRad)
    );
    return [(newLatRad * 180) / Math.PI, (newLngRad * 180) / Math.PI];
}

const darkStyle = {
    version: 8,
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: {
        'carto-dark': {
            type: 'raster',
            tiles: [
                "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
                "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
                "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
                "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png"
            ],
            tileSize: 256
        }
    },
    layers: [
        { id: 'carto-dark-layer', type: 'raster', source: 'carto-dark', minzoom: 0, maxzoom: 22 },
        { id: 'imagery-ceiling', type: 'background', paint: { 'background-opacity': 0 } }
    ]
};

const lightStyle = {
    version: 8,
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: {
        'carto-light': {
            type: 'raster',
            tiles: [
                "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
                "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
                "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
                "https://d.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png"
            ],
            tileSize: 256
        }
    },
    layers: [
        { id: 'carto-light-layer', type: 'raster', source: 'carto-light', minzoom: 0, maxzoom: 22 },
        { id: 'imagery-ceiling', type: 'background', paint: { 'background-opacity': 0 } }
    ]
};

// Satellite icon SVG builder — module-level constant (no re-creation per render)
const makeSatSvg = (color: string) => {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
        <rect x="9" y="9" width="6" height="6" rx="1" fill="${color}" stroke="#0a0e1a" stroke-width="0.5"/>
        <rect x="1" y="10" width="7" height="4" rx="1" fill="${color}" opacity="0.7" stroke="#0a0e1a" stroke-width="0.3"/>
        <rect x="16" y="10" width="7" height="4" rx="1" fill="${color}" opacity="0.7" stroke="#0a0e1a" stroke-width="0.3"/>
        <line x1="8" y1="12" x2="1" y2="12" stroke="${color}" stroke-width="0.8"/>
        <line x1="16" y1="12" x2="23" y2="12" stroke="${color}" stroke-width="0.8"/>
        <circle cx="12" cy="12" r="1.5" fill="#fff" opacity="0.8"/>
    </svg>`;
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
};
const MISSION_COLORS: Record<string, string> = {
    'military_recon': '#ff3333', 'military_sar': '#ff3333',
    'sar': '#00e5ff', 'sigint': '#ffffff',
    'navigation': '#4488ff', 'early_warning': '#ff00ff',
    'commercial_imaging': '#44ff44', 'space_station': '#ffdd00'
};
const MISSION_ICON_MAP: Record<string, string> = {
    'military_recon': 'sat-mil', 'military_sar': 'sat-mil',
    'sar': 'sat-sar', 'sigint': 'sat-sigint',
    'navigation': 'sat-nav', 'early_warning': 'sat-ew',
    'commercial_imaging': 'sat-com', 'space_station': 'sat-station'
};

// Empty GeoJSON constant — avoids recreating empty objects on every render
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

// Imperatively push GeoJSON data to a MapLibre source, bypassing React reconciliation.
// This is critical for high-volume layers (flights, ships, satellites, fires) where
// React's prop diffing on thousands of coordinate arrays causes memory pressure.
function useImperativeSource(map: MapRef | null, sourceId: string, geojson: any, debounceMs = 0) {
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    useEffect(() => {
        if (!map) return;
        const push = () => {
            const src = map.getSource(sourceId) as any;
            if (src && typeof src.setData === 'function') {
                src.setData(geojson || EMPTY_FC);
            }
        };
        if (debounceMs > 0) {
            if (timerRef.current) clearTimeout(timerRef.current);
            timerRef.current = setTimeout(push, debounceMs);
            return () => { if (timerRef.current) clearTimeout(timerRef.current); };
        }
        push();
    }, [map, sourceId, geojson, debounceMs]);
}

const MaplibreViewer = ({ data, activeLayers, onEntityClick, flyToLocation, selectedEntity, onMouseCoords, onRightClick, regionDossier, regionDossierLoading, onViewStateChange, measureMode, onMeasureClick, measurePoints, gibsDate, gibsOpacity }: any) => {
    const mapRef = useRef<MapRef>(null);
    const [mapReady, setMapReady] = useState(false);
    const { theme } = useTheme();
    const mapThemeStyle = useMemo(() => theme === 'light' ? lightStyle : darkStyle, [theme]);

    const [viewState, setViewState] = useState<ViewState>({
        longitude: 0,
        latitude: 20,
        zoom: 2,
        bearing: 0,
        pitch: 0,
        padding: { top: 0, bottom: 0, left: 0, right: 0 }
    });

    // Viewport bounds for culling off-screen features [west, south, east, north]
    // Buffer extends bounds by ~20% so features near edges don't pop in/out
    const [mapBounds, setMapBounds] = useState<[number, number, number, number]>([-180, -90, 180, 90]);
    const boundsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const updateBounds = useCallback(() => {
        const map = mapRef.current?.getMap();
        if (!map) return;
        const b = map.getBounds();
        const latRange = b.getNorth() - b.getSouth();
        const lngRange = b.getEast() - b.getWest();
        const buf = 0.2; // 20% buffer
        setMapBounds([
            b.getWest() - lngRange * buf,
            b.getSouth() - latRange * buf,
            b.getEast() + lngRange * buf,
            b.getNorth() + latRange * buf
        ]);
    }, []);

    // Fast bounds check — used by all GeoJSON builders and Marker loops
    const inView = useCallback((lat: number, lng: number) =>
        lng >= mapBounds[0] && lng <= mapBounds[2] && lat >= mapBounds[1] && lat <= mapBounds[3],
        [mapBounds]
    );

    const [dynamicRoute, setDynamicRoute] = useState<any>(null);
    const prevCallsign = useRef<string | null>(null);
    const [shipClusters, setShipClusters] = useState<any[]>([]);
    const [eqClusters, setEqClusters] = useState<any[]>([]);

    // --- Smooth interpolation: tick counter triggers GeoJSON recalc every second ---
    const [interpTick, setInterpTick] = useState(0);
    const dataTimestamp = useRef<number>(Date.now());

    // Track when flight/ship/satellite data actually changes (new fetch arrived)
    useEffect(() => {
        dataTimestamp.current = Date.now();
    }, [data?.commercial_flights, data?.ships, data?.satellites]);

    // Tick every 2s between data refreshes to animate positions
    // Satellites move ~7km/s so need frequent updates for smooth motion
    useEffect(() => {
        const timer = setInterval(() => setInterpTick(t => t + 1), 2000);
        return () => clearInterval(timer);
    }, []);

    // --- Solar Terminator: recompute the night polygon every 60 seconds ---
    const [nightGeoJSON, setNightGeoJSON] = useState<any>(() => computeNightPolygon());
    useEffect(() => {
        const timer = setInterval(() => setNightGeoJSON(computeNightPolygon()), 60000);
        return () => clearInterval(timer);
    }, []);

    useEffect(() => {
        let isMounted = true;

        let callsign = null;
        let entityLat = 0;
        let entityLng = 0;
        if (selectedEntity && data) {
            let entity = null;
            if (selectedEntity.type === 'flight') entity = data?.commercial_flights?.[selectedEntity.id as number];
            else if (selectedEntity.type === 'private_flight') entity = data?.private_flights?.[selectedEntity.id as number];
            else if (selectedEntity.type === 'military_flight') entity = data?.military_flights?.[selectedEntity.id as number];
            else if (selectedEntity.type === 'private_jet') entity = data?.private_jets?.[selectedEntity.id as number];
            else if (selectedEntity.type === 'tracked_flight') entity = data?.tracked_flights?.[selectedEntity.id as number];

            if (entity && entity.callsign) {
                callsign = entity.callsign;
                entityLat = entity.lat ?? 0;
                entityLng = entity.lng ?? 0;
            }
        }

        if (callsign && callsign !== prevCallsign.current) {
            prevCallsign.current = callsign;
            fetch(`${API_BASE}/api/route/${callsign}?lat=${entityLat}&lng=${entityLng}`)
                .then(res => res.json())
                .then(routeData => {
                    if (isMounted) setDynamicRoute(routeData);
                })
                .catch(() => {
                    if (isMounted) setDynamicRoute(null);
                });
        } else if (!callsign) {
            prevCallsign.current = null;
            if (isMounted) setDynamicRoute(null);
        }

        return () => { isMounted = false; };
    }, [selectedEntity, data]);

    useEffect(() => {
        if (flyToLocation && mapRef.current) {
            mapRef.current.flyTo({
                center: [flyToLocation.lng, flyToLocation.lat],
                zoom: 8,
                duration: 1500
            });
        }
    }, [flyToLocation]);

    const earthquakesGeoJSON = useMemo(() => {
        if (!activeLayers.earthquakes || !data?.earthquakes) return null;
        return {
            type: 'FeatureCollection',
            features: data.earthquakes.map((eq: any, i: number) => {
                if (eq.lat == null || eq.lng == null) return null;
                return {
                    type: 'Feature',
                    properties: {
                        id: i,
                        type: 'earthquake',
                        name: `[M${eq.mag}]\n${eq.place || 'Unknown Location'}`,
                        title: eq.title
                    },
                    geometry: { type: 'Point', coordinates: [eq.lng, eq.lat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.earthquakes, data?.earthquakes]);

    // GPS Jamming zones — 1°×1° grid squares colored by severity
    const jammingGeoJSON = useMemo(() => {
        if (!activeLayers.gps_jamming || !data?.gps_jamming?.length) return null;
        return {
            type: 'FeatureCollection' as const,
            features: data.gps_jamming.map((zone: any, i: number) => {
                const halfDeg = 0.5;
                const lat = zone.lat;
                const lng = zone.lng;
                return {
                    type: 'Feature' as const,
                    properties: {
                        id: i,
                        severity: zone.severity,
                        ratio: zone.ratio,
                        degraded: zone.degraded,
                        total: zone.total,
                        opacity: zone.severity === 'high' ? 0.45 : zone.severity === 'medium' ? 0.3 : 0.18
                    },
                    geometry: {
                        type: 'Polygon' as const,
                        coordinates: [[
                            [lng - halfDeg, lat - halfDeg],
                            [lng + halfDeg, lat - halfDeg],
                            [lng + halfDeg, lat + halfDeg],
                            [lng - halfDeg, lat + halfDeg],
                            [lng - halfDeg, lat - halfDeg]
                        ]]
                    }
                };
            })
        };
    }, [activeLayers.gps_jamming, data?.gps_jamming]);

    // CCTV cameras — clustered green dots
    const cctvGeoJSON = useMemo(() => {
        if (!activeLayers.cctv || !data?.cctv?.length) return null;
        return {
            type: 'FeatureCollection' as const,
            features: data.cctv.filter((c: any) => c.lat != null && c.lon != null && inView(c.lat, c.lon)).map((c: any, i: number) => ({
                type: 'Feature' as const,
                properties: {
                    id: c.id || i,
                    type: 'cctv',
                    name: c.direction_facing || 'Camera',
                    source_agency: c.source_agency || 'Unknown',
                    media_url: c.media_url || '',
                    media_type: c.media_type || 'image'
                },
                geometry: { type: 'Point' as const, coordinates: [c.lon, c.lat] }
            }))
        };
    }, [activeLayers.cctv, data?.cctv, inView]);

    // KiwiSDR receivers — clustered amber dots
    const kiwisdrGeoJSON = useMemo(() => {
        if (!activeLayers.kiwisdr || !data?.kiwisdr?.length) return null;
        return {
            type: 'FeatureCollection' as const,
            features: data.kiwisdr.filter((k: any) => k.lat != null && k.lon != null && inView(k.lat, k.lon)).map((k: any, i: number) => ({
                type: 'Feature' as const,
                properties: {
                    id: i,
                    type: 'kiwisdr',
                    name: k.name || 'Unknown SDR',
                    url: k.url || '',
                    users: k.users || 0,
                    users_max: k.users_max || 0,
                    bands: k.bands || '',
                    antenna: k.antenna || '',
                    location: k.location || '',
                },
                geometry: { type: 'Point' as const, coordinates: [k.lon, k.lat] }
            }))
        };
    }, [activeLayers.kiwisdr, data?.kiwisdr, inView]);

    // FIRMS fires — heat-colored dots by FRP (Fire Radiative Power)
    const firmsGeoJSON = useMemo(() => {
        if (!activeLayers.firms || !data?.firms_fires?.length) return null;
        return {
            type: 'FeatureCollection' as const,
            features: data.firms_fires.map((f: any, i: number) => {
                const frp = f.frp || 0;
                const iconId = frp >= 100 ? 'fire-darkred' : frp >= 20 ? 'fire-red' : frp >= 5 ? 'fire-orange' : 'fire-yellow';
                return {
                    type: 'Feature' as const,
                    properties: {
                        id: i,
                        type: 'firms_fire',
                        name: `Fire ${frp.toFixed(1)} MW`,
                        frp,
                        iconId,
                        brightness: f.brightness || 0,
                        confidence: f.confidence || '',
                        daynight: f.daynight === 'D' ? 'Day' : 'Night',
                        acq_date: f.acq_date || '',
                        acq_time: f.acq_time || '',
                    },
                    geometry: { type: 'Point' as const, coordinates: [f.lng, f.lat] }
                };
            })
        };
    }, [activeLayers.firms, data?.firms_fires]);

    // Internet outages — region-level with backend-geocoded coordinates
    const internetOutagesGeoJSON = useMemo(() => {
        if (!activeLayers.internet_outages || !data?.internet_outages?.length) return null;
        return {
            type: 'FeatureCollection' as const,
            features: data.internet_outages.map((o: any) => {
                const lat = o.lat;
                const lng = o.lng;
                if (lat == null || lng == null) return null;
                const severity = o.severity || 0;
                const region = o.region_name || o.region_code || '?';
                const country = o.country_name || o.country_code || '';
                const label = `${region}, ${country}`;
                const detail = `${label}\n${severity}% drop · ${o.datasource || 'IODA'}`;
                return {
                    type: 'Feature' as const,
                    properties: {
                        id: o.region_code || region,
                        type: 'internet_outage',
                        name: label,
                        country,
                        region,
                        level: o.level,
                        severity,
                        datasource: o.datasource || '',
                        detail,
                    },
                    geometry: { type: 'Point' as const, coordinates: [lng, lat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.internet_outages, data?.internet_outages]);

    const dataCentersGeoJSON = useMemo(() => {
        if (!activeLayers.datacenters || !data?.datacenters?.length) return null;
        return {
            type: 'FeatureCollection' as const,
            features: data.datacenters.map((dc: any, i: number) => ({
                type: 'Feature' as const,
                properties: {
                    id: `dc-${i}`,
                    type: 'datacenter',
                    name: dc.name || 'Unknown',
                    company: dc.company || '',
                    city: dc.city || '',
                    country: dc.country || '',
                },
                geometry: { type: 'Point' as const, coordinates: [dc.lng, dc.lat] }
            }))
        };
    }, [activeLayers.datacenters, data?.datacenters]);

    // Load Images into the Map Style once loaded
    const onMapLoad = useCallback((e: any) => {
        const map = e.target;

        // Track which images are still loading so we can retry on styleimagemissing
        const pendingImages: Record<string, string> = {};

        const loadImg = (id: string, url: string) => {
            if (!map.hasImage(id)) {
                pendingImages[id] = url;
                const img = new Image();
                img.crossOrigin = "anonymous";
                img.src = url;
                img.onload = () => {
                    if (!map.hasImage(id)) map.addImage(id, img);
                    delete pendingImages[id];
                };
            }
        };

        // Suppress "image not found" warnings — retry when the async load finishes
        map.on('styleimagemissing', (ev: any) => {
            const id = ev.id;
            const url = pendingImages[id];
            if (url) {
                const img = new Image();
                img.crossOrigin = "anonymous";
                img.src = url;
                img.onload = () => {
                    if (!map.hasImage(id)) map.addImage(id, img);
                    delete pendingImages[id];
                };
            }
        });

        // Critical icons — needed immediately for default-on layers
        loadImg('svgPlaneCyan', svgPlaneCyan);
        loadImg('svgPlaneYellow', svgPlaneYellow);
        loadImg('svgPlaneOrange', svgPlaneOrange);
        loadImg('svgPlanePurple', svgPlanePurple);
        loadImg('svgHeli', svgHeli);
        loadImg('svgHeliCyan', svgHeliCyan);
        loadImg('svgHeliOrange', svgHeliOrange);
        loadImg('svgHeliPurple', svgHeliPurple);
        loadImg('svgHeliBlue', svgHeliBlue);
        loadImg('svgHeliLime', svgHeliLime);
        loadImg('svgFighter', svgFighter);
        loadImg('svgTanker', svgTanker);
        loadImg('svgRecon', svgRecon);
        loadImg('svgAirlinerCyan', svgAirlinerCyan);
        loadImg('svgAirlinerOrange', svgAirlinerOrange);
        loadImg('svgAirlinerPurple', svgAirlinerPurple);
        loadImg('svgAirlinerYellow', svgAirlinerYellow);
        loadImg('svgTurbopropCyan', svgTurbopropCyan);
        loadImg('svgTurbopropOrange', svgTurbopropOrange);
        loadImg('svgTurbopropPurple', svgTurbopropPurple);
        loadImg('svgTurbopropYellow', svgTurbopropYellow);
        loadImg('svgBizjetCyan', svgBizjetCyan);
        loadImg('svgBizjetOrange', svgBizjetOrange);
        loadImg('svgBizjetPurple', svgBizjetPurple);
        loadImg('svgBizjetYellow', svgBizjetYellow);
        loadImg('svgAirlinerGrey', svgAirlinerGrey);
        loadImg('svgTurbopropGrey', svgTurbopropGrey);
        loadImg('svgBizjetGrey', svgBizjetGrey);
        loadImg('svgHeliGrey', svgHeliGrey);
        loadImg('svgShipGray', svgShipGray);
        loadImg('svgShipRed', svgShipRed);
        loadImg('svgShipYellow', svgShipYellow);
        loadImg('svgShipBlue', svgShipBlue);
        loadImg('svgShipWhite', svgShipWhite);
        loadImg('svgCarrier', svgCarrier);
        loadImg('svgWarning', svgWarning);
        loadImg('icon-threat', svgThreat);

        // Deferred icons — for off-by-default layers and rare variants
        // Loaded in next frame to avoid blocking initial map render
        setTimeout(() => {
            loadImg('svgPlanePink', svgPlanePink);
            loadImg('svgPlaneAlertRed', svgPlaneAlertRed);
            loadImg('svgPlaneDarkBlue', svgPlaneDarkBlue);
            loadImg('svgPlaneWhiteAlert', svgPlaneWhiteAlert);
            loadImg('svgPlaneBlack', svgPlaneBlack);
            loadImg('svgHeliPink', svgHeliPink);
            loadImg('svgHeliAlertRed', svgHeliAlertRed);
            loadImg('svgHeliDarkBlue', svgHeliDarkBlue);
            loadImg('svgHeliWhiteAlert', svgHeliWhiteAlert);
            loadImg('svgHeliBlack', svgHeliBlack);
            loadImg('svgPotusPlane', svgPotusPlane);
            loadImg('svgPotusHeli', svgPotusHeli);
            loadImg('svgAirlinerPink', svgAirlinerPink);
            loadImg('svgAirlinerRed', svgAirlinerRed);
            loadImg('svgAirlinerDarkBlue', svgAirlinerDarkBlue);
            loadImg('svgAirlinerBlue', svgAirlinerBlue);
            loadImg('svgAirlinerLime', svgAirlinerLime);
            loadImg('svgAirlinerBlack', svgAirlinerBlack);
            loadImg('svgAirlinerWhite', svgAirlinerWhite);
            loadImg('svgTurbopropPink', svgTurbopropPink);
            loadImg('svgTurbopropRed', svgTurbopropRed);
            loadImg('svgTurbopropDarkBlue', svgTurbopropDarkBlue);
            loadImg('svgTurbopropBlue', svgTurbopropBlue);
            loadImg('svgTurbopropLime', svgTurbopropLime);
            loadImg('svgTurbopropBlack', svgTurbopropBlack);
            loadImg('svgTurbopropWhite', svgTurbopropWhite);
            loadImg('svgBizjetPink', svgBizjetPink);
            loadImg('svgBizjetRed', svgBizjetRed);
            loadImg('svgBizjetDarkBlue', svgBizjetDarkBlue);
            loadImg('svgBizjetBlue', svgBizjetBlue);
            loadImg('svgBizjetLime', svgBizjetLime);
            loadImg('svgBizjetBlack', svgBizjetBlack);
            loadImg('svgBizjetWhite', svgBizjetWhite);
            loadImg('svgDrone', svgDrone);
            loadImg('svgCctv', svgCctv);
            loadImg('icon-liveua-yellow', svgTriangleYellow);
            loadImg('icon-liveua-red', svgTriangleRed);
            // FIRMS fire icons
            loadImg('fire-yellow', svgFireYellow);
            loadImg('fire-orange', svgFireOrange);
            loadImg('fire-red', svgFireRed);
            loadImg('fire-darkred', svgFireDarkRed);
            loadImg('fire-cluster-sm', svgFireClusterSmall);
            loadImg('fire-cluster-md', svgFireClusterMed);
            loadImg('fire-cluster-lg', svgFireClusterLarge);
            loadImg('fire-cluster-xl', svgFireClusterXL);
            // Data center icon
            loadImg('datacenter', svgDataCenter);
            // Satellite mission-type icons
            loadImg('sat-mil', makeSatSvg('#ff3333'));
            loadImg('sat-sar', makeSatSvg('#00e5ff'));
            loadImg('sat-sigint', makeSatSvg('#ffffff'));
            loadImg('sat-nav', makeSatSvg('#4488ff'));
            loadImg('sat-ew', makeSatSvg('#ff00ff'));
            loadImg('sat-com', makeSatSvg('#44ff44'));
            loadImg('sat-station', makeSatSvg('#ffdd00'));
            loadImg('sat-gen', makeSatSvg('#aaaaaa'));
        }, 0);

        setMapReady(true);
    }, []);

    // Build a set of tracked icao24s to exclude from other flight layers
    const trackedIcaoSet = useMemo(() => {
        const s = new Set<string>();
        if (data?.tracked_flights) {
            for (const t of data.tracked_flights) {
                if (t.icao24) s.add(t.icao24.toLowerCase());
            }
        }
        return s;
    }, [data?.tracked_flights]);

    // Elapsed seconds since last data refresh (used for position interpolation)
    // interpTick dependency forces recalculation every 1s tick
    const dtSeconds = useMemo(() => {
        void interpTick; // use the tick to trigger recalc
        return (Date.now() - dataTimestamp.current) / 1000;
    }, [interpTick]);

    // Helper: interpolate a flight's position if airborne and has speed+heading
    const interpFlight = (f: any): [number, number] => {
        // Fast path: skip trig for stationary/grounded/no-speed aircraft
        if (!f.speed_knots || f.speed_knots <= 0 || dtSeconds <= 0) return [f.lng, f.lat];
        if (f.alt != null && f.alt <= 100) return [f.lng, f.lat];
        // Only interpolate if enough time has passed to matter (>1s)
        if (dtSeconds < 1) return [f.lng, f.lat];
        const heading = f.true_track || f.heading || 0;
        const [newLat, newLng] = interpolatePosition(f.lat, f.lng, heading, f.speed_knots, dtSeconds);
        return [newLng, newLat];
    };

    // Helper: interpolate a ship's position using SOG + heading
    const interpShip = (s: any): [number, number] => {
        if (typeof s.sog !== 'number' || !s.sog || s.sog <= 0 || dtSeconds <= 0) return [s.lng, s.lat];
        const heading = (typeof s.cog === 'number' ? s.cog : 0) || s.heading || 0;
        const [newLat, newLng] = interpolatePosition(s.lat, s.lng, heading, s.sog, dtSeconds);
        return [newLng, newLat];
    };

    // Helper: interpolate a satellite's position between API updates
    // Satellites have deterministic orbits so linear interpolation over 60s is accurate
    // maxDt=65 allows full interval coverage (60s update + 5s buffer)
    const interpSat = (s: any): [number, number] => {
        if (!s.speed_knots || s.speed_knots <= 0 || dtSeconds < 1) return [s.lng, s.lat];
        const [newLat, newLng] = interpolatePosition(s.lat, s.lng, s.heading || 0, s.speed_knots, dtSeconds, 0, 65);
        return [newLng, newLat];
    };

    // Satellite GeoJSON with interpolated positions
    const satellitesGeoJSON = useMemo(() => {
        if (!activeLayers.satellites || !data?.satellites?.length) return null;
        return {
            type: 'FeatureCollection' as const,
            features: data.satellites.filter((s: any) => s.lat != null && s.lng != null && inView(s.lat, s.lng)).map((s: any, i: number) => ({
                type: 'Feature' as const,
                properties: {
                    id: s.id || i,
                    type: 'satellite',
                    name: s.name,
                    mission: s.mission || 'general',
                    sat_type: s.sat_type || 'Satellite',
                    country: s.country || '',
                    alt_km: s.alt_km || 0,
                    wiki: s.wiki || '',
                    color: MISSION_COLORS[s.mission] || '#aaaaaa',
                    iconId: MISSION_ICON_MAP[s.mission] || 'sat-gen'
                },
                geometry: { type: 'Point' as const, coordinates: interpSat(s) }
            }))
        };
    }, [activeLayers.satellites, data?.satellites, dtSeconds, inView]);


    // Create GeoJSON collections dynamically (this runs ultra fast in pure JS)
    const commFlightsGeoJSON = useMemo(() => {
        if (!activeLayers.flights || !data?.commercial_flights) return null;
        return {
            type: 'FeatureCollection',
            features: data.commercial_flights.map((f: any, i: number) => {
                if (f.lat == null || f.lng == null) return null;
                if (!inView(f.lat, f.lng)) return null;
                if (f.icao24 && trackedIcaoSet.has(f.icao24.toLowerCase())) return null;
                const acType = classifyAircraft(f.model, f.aircraft_category);
                const grounded = f.alt != null && f.alt <= 100;
                const [iLng, iLat] = interpFlight(f);
                return {
                    type: 'Feature',
                    properties: { id: i, type: 'flight', callsign: f.callsign || f.icao24, rotation: f.true_track || f.heading || 0, iconId: grounded ? GROUNDED_ICON_MAP[acType] : COLOR_MAP_COMMERCIAL[acType] },
                    geometry: { type: 'Point', coordinates: [iLng, iLat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.flights, data?.commercial_flights, trackedIcaoSet, dtSeconds, inView]);

    const privFlightsGeoJSON = useMemo(() => {
        if (!activeLayers.private || !data?.private_flights) return null;
        return {
            type: 'FeatureCollection',
            features: data.private_flights.map((f: any, i: number) => {
                if (f.lat == null || f.lng == null) return null;
                if (!inView(f.lat, f.lng)) return null;
                if (f.icao24 && trackedIcaoSet.has(f.icao24.toLowerCase())) return null;
                const acType = classifyAircraft(f.model, f.aircraft_category);
                const grounded = f.alt != null && f.alt <= 100;
                const [iLng, iLat] = interpFlight(f);
                return {
                    type: 'Feature',
                    properties: { id: i, type: 'private_flight', callsign: f.callsign || f.icao24, rotation: f.heading || 0, iconId: grounded ? GROUNDED_ICON_MAP[acType] : COLOR_MAP_PRIVATE[acType] },
                    geometry: { type: 'Point', coordinates: [iLng, iLat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.private, data?.private_flights, trackedIcaoSet, dtSeconds, inView]);

    const privJetsGeoJSON = useMemo(() => {
        if (!activeLayers.jets || !data?.private_jets) return null;
        return {
            type: 'FeatureCollection',
            features: data.private_jets.map((f: any, i: number) => {
                if (f.lat == null || f.lng == null) return null;
                if (!inView(f.lat, f.lng)) return null;
                if (f.icao24 && trackedIcaoSet.has(f.icao24.toLowerCase())) return null;
                const acType = classifyAircraft(f.model, f.aircraft_category);
                const grounded = f.alt != null && f.alt <= 100;
                const [iLng, iLat] = interpFlight(f);
                return {
                    type: 'Feature',
                    properties: { id: i, type: 'private_jet', callsign: f.callsign || f.icao24, rotation: f.heading || 0, iconId: grounded ? GROUNDED_ICON_MAP[acType] : COLOR_MAP_JETS[acType] },
                    geometry: { type: 'Point', coordinates: [iLng, iLat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.jets, data?.private_jets, trackedIcaoSet, dtSeconds, inView]);

    const milFlightsGeoJSON = useMemo(() => {
        if (!activeLayers.military || !data?.military_flights) return null;

        return {
            type: 'FeatureCollection',
            features: data.military_flights.map((f: any, i: number) => {
                if (f.lat == null || f.lng == null) return null;
                if (!inView(f.lat, f.lng)) return null;
                if (f.icao24 && trackedIcaoSet.has(f.icao24.toLowerCase())) return null;
                const milType = f.military_type || 'default';
                const grounded = f.alt != null && f.alt <= 100;
                let iconId = MIL_SPECIAL_MAP[milType];
                if (!iconId) {
                    const acType = classifyAircraft(f.model, f.aircraft_category);
                    iconId = grounded ? GROUNDED_ICON_MAP[acType] : COLOR_MAP_MILITARY[acType];
                } else if (grounded) {
                    const acType = classifyAircraft(f.model, f.aircraft_category);
                    iconId = GROUNDED_ICON_MAP[acType];
                }
                const [iLng, iLat] = interpFlight(f);
                return {
                    type: 'Feature',
                    properties: { id: i, type: 'military_flight', callsign: f.callsign || f.icao24, rotation: f.heading || 0, iconId },
                    geometry: { type: 'Point', coordinates: [iLng, iLat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.military, data?.military_flights, trackedIcaoSet, dtSeconds, inView]);

    const shipsGeoJSON = useMemo(() => {
        if (!(activeLayers.ships_important || activeLayers.ships_civilian || activeLayers.ships_passenger) || !data?.ships) return null;

        return {
            type: 'FeatureCollection',
            features: data.ships.map((s: any, i: number) => {
                if (s.lat == null || s.lng == null) return null;
                if (!inView(s.lat, s.lng)) return null;

                const isImportant = s.type === 'carrier' || s.type === 'military_vessel' || s.type === 'tanker' || s.type === 'cargo';
                const isPassenger = s.type === 'passenger';

                // Carriers are now handled by a dedicated unclustered source
                if (s.type === 'carrier') return null;

                if (isImportant && activeLayers?.ships_important === false) return null;
                if (isPassenger && activeLayers?.ships_passenger === false) return null;
                if (!isImportant && !isPassenger && activeLayers?.ships_civilian === false) return null;

                let iconId = 'svgShipBlue';
                if (s.type === 'carrier') {
                    iconId = 'svgCarrier';
                } else if (s.type === 'tanker' || s.type === 'cargo') {
                    iconId = 'svgShipRed';
                } else if (s.type === 'yacht' || s.type === 'passenger') {
                    iconId = 'svgShipWhite';
                } else if (s.type === 'military_vessel') {
                    iconId = 'svgShipYellow';
                }

                const [iLng, iLat] = interpShip(s);
                return {
                    type: 'Feature',
                    properties: { id: i, type: 'ship', name: s.name, rotation: s.heading || 0, iconId },
                    geometry: { type: 'Point', coordinates: [iLng, iLat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.ships_important, activeLayers.ships_civilian, activeLayers.ships_passenger, data?.ships, inView]);

    // Extract ship cluster positions from the map source for HTML labels
    const shipClusterHandlerRef = useRef<(() => void) | null>(null);
    useEffect(() => {
        const map = mapRef.current?.getMap();
        if (!map || !shipsGeoJSON) { setShipClusters([]); return; }

        // Remove previous handler if it exists
        if (shipClusterHandlerRef.current) {
            map.off('moveend', shipClusterHandlerRef.current);
            map.off('sourcedata', shipClusterHandlerRef.current);
        }

        const update = () => {
            try {
                const features = map.querySourceFeatures('ships');
                const clusters = features
                    .filter((f: any) => f.properties?.cluster)
                    .map((f: any) => ({
                        lng: (f.geometry as any).coordinates[0],
                        lat: (f.geometry as any).coordinates[1],
                        count: f.properties.point_count_abbreviated || f.properties.point_count,
                        id: f.properties.cluster_id
                    }));
                const seen = new Set();
                const unique = clusters.filter((c: any) => { if (seen.has(c.id)) return false; seen.add(c.id); return true; });
                setShipClusters(unique);
            } catch { setShipClusters([]); }
        };
        shipClusterHandlerRef.current = update;

        map.on('moveend', update);
        map.on('sourcedata', update);
        setTimeout(update, 500);

        return () => { map.off('moveend', update); map.off('sourcedata', update); };
    }, [shipsGeoJSON]);

    // Extract earthquake cluster positions from the map source for HTML labels
    const eqClusterHandlerRef = useRef<(() => void) | null>(null);
    useEffect(() => {
        const map = mapRef.current?.getMap();
        if (!map || !earthquakesGeoJSON) { setEqClusters([]); return; }

        if (eqClusterHandlerRef.current) {
            map.off('moveend', eqClusterHandlerRef.current);
            map.off('sourcedata', eqClusterHandlerRef.current);
        }

        const update = () => {
            try {
                const features = map.querySourceFeatures('earthquakes');
                const clusters = features
                    .filter((f: any) => f.properties?.cluster)
                    .map((f: any) => ({
                        lng: (f.geometry as any).coordinates[0],
                        lat: (f.geometry as any).coordinates[1],
                        count: f.properties.point_count_abbreviated || f.properties.point_count,
                        id: f.properties.cluster_id
                    }));
                const seen = new Set();
                const unique = clusters.filter((c: any) => { if (seen.has(c.id)) return false; seen.add(c.id); return true; });
                setEqClusters(unique);
            } catch { setEqClusters([]); }
        };
        eqClusterHandlerRef.current = update;

        map.on('moveend', update);
        map.on('sourcedata', update);
        setTimeout(update, 500);

        return () => { map.off('moveend', update); map.off('sourcedata', update); };
    }, [earthquakesGeoJSON]);

    const carriersGeoJSON = useMemo(() => {
        if (!activeLayers.ships_important || !data?.ships) return null;
        return {
            type: 'FeatureCollection',
            features: data.ships.map((s: any, i: number) => {
                if (s.type !== 'carrier' || s.lat == null || s.lng == null) return null;
                const [iLng, iLat] = interpShip(s);
                return {
                    type: 'Feature',
                    properties: { id: i, type: 'ship', name: s.name, rotation: s.heading || 0, iconId: 'svgCarrier' },
                    geometry: { type: 'Point', coordinates: [iLng, iLat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.ships_important, data?.ships]);

    const activeRouteGeoJSON = useMemo(() => {
        if (!selectedEntity || !data) return null;

        let entity = null;
        if (selectedEntity.type === 'flight') entity = data?.commercial_flights?.[selectedEntity.id as number];
        else if (selectedEntity.type === 'private_flight') entity = data?.private_flights?.[selectedEntity.id as number];
        else if (selectedEntity.type === 'military_flight') entity = data?.military_flights?.[selectedEntity.id as number];
        else if (selectedEntity.type === 'private_jet') entity = data?.private_jets?.[selectedEntity.id as number];
        else if (selectedEntity.type === 'tracked_flight') entity = data?.tracked_flights?.[selectedEntity.id as number];
        else if (selectedEntity.type === 'ship') entity = data?.ships?.[selectedEntity.id as number];

        if (!entity) return null;

        const currentLoc = [entity.lng, entity.lat];
        let originLoc = entity.origin_loc; // [lng, lat]
        let destLoc = entity.dest_loc; // [lng, lat]

        if (dynamicRoute && dynamicRoute.orig_loc && dynamicRoute.dest_loc) {
            originLoc = dynamicRoute.orig_loc;
            destLoc = dynamicRoute.dest_loc;
            // Also override display names so NewsFeed shows the resolved airport info
            if (dynamicRoute.origin_name) entity.origin_name = dynamicRoute.origin_name;
            if (dynamicRoute.dest_name) entity.dest_name = dynamicRoute.dest_name;
        }

        const features = [];
        if (originLoc) {
            features.push({
                type: 'Feature',
                properties: { type: 'route-origin' },
                geometry: { type: 'LineString', coordinates: [currentLoc, originLoc] }
            });
        }
        if (destLoc) {
            features.push({
                type: 'Feature',
                properties: { type: 'route-dest' },
                geometry: { type: 'LineString', coordinates: [currentLoc, destLoc] }
            });
        }

        if (features.length === 0) return null;
        return { type: 'FeatureCollection', features };
    }, [selectedEntity, data, dynamicRoute]);

    // Trail history GeoJSON: shows where the SELECTED aircraft has been (only for no-route flights)
    const trailGeoJSON = useMemo(() => {
        if (!selectedEntity || !data) return null;

        let entity = null;
        if (selectedEntity.type === 'flight') entity = data?.commercial_flights?.[selectedEntity.id as number];
        else if (selectedEntity.type === 'private_flight') entity = data?.private_flights?.[selectedEntity.id as number];
        else if (selectedEntity.type === 'military_flight') entity = data?.military_flights?.[selectedEntity.id as number];
        else if (selectedEntity.type === 'private_jet') entity = data?.private_jets?.[selectedEntity.id as number];
        else if (selectedEntity.type === 'tracked_flight') entity = data?.tracked_flights?.[selectedEntity.id as number];

        if (!entity || !entity.trail || entity.trail.length < 2) return null;
        // Only show trail if this flight has no known route
        if (entity.origin_name && entity.origin_name !== 'UNKNOWN') return null;

        const coords = entity.trail.map((p: number[]) => [p[1], p[0]]);
        if (entity.lat != null && entity.lng != null) {
            coords.push([entity.lng, entity.lat]);
        }

        return {
            type: 'FeatureCollection',
            features: [{
                type: 'Feature',
                properties: { type: 'trail' },
                geometry: { type: 'LineString', coordinates: coords }
            }]
        };
    }, [selectedEntity, data]);

    const spreadAlerts = useMemo(() => {
        if (!data?.news) return [];

        // 1. Prepare items with screen-space coordinates (Mercator approx)
        // We use a relative pixel projection based on zoom to detect visual collisions.
        const pixelsPerDeg = 256 * Math.pow(2, viewState.zoom) / 360;

        // Use original array mapping to preserve correct indices for the popup/selection logic
        // Estimate each box's rendered height based on its content.
        // CSS: padding 5px top/bottom, title maxWidth 160px at 9px font (~18 chars/line),
        // header "!! ALERT LVL X !!" = 14px, title lines * 13px each, footer 12px if present
        const estimateBoxH = (n: any) => {
            const titleLen = (n.title || '').length;
            const titleLines = Math.max(1, Math.ceil(titleLen / 20)); // ~20 chars per line at 9px in 160px
            const hasFooter = (n.cluster_count || 1) > 1;
            return 10 + 14 + (titleLines * 13) + (hasFooter ? 14 : 0) + 10; // padding + header + title + footer + padding
        };

        let items = data.news
            .map((n: any, idx: number) => ({ ...n, originalIdx: idx }))
            .filter((n: any) => n.coords)
            .map((n: any) => ({
                ...n,
                x: n.coords[1] * pixelsPerDeg,
                y: -n.coords[0] * pixelsPerDeg,
                offsetX: 0,
                offsetY: 0,
                boxH: estimateBoxH(n),
            }));

        // Box width is consistent (minWidth 120 + padding, titles up to 160px + 16px padding)
        const BOX_W = 180;
        const GAP = 6; // Minimum gap between boxes
        const MAX_OFFSET = 350;

        // 2. Grid-based Collision Resolution (O(n) per iteration instead of O(n²))
        const CELL_W = BOX_W + GAP;
        const CELL_H = 100; // Approximate max box height + gap
        const maxIter = 30;
        for (let iter = 0; iter < maxIter; iter++) {
            let moved = false;
            // Build spatial grid
            const grid: Record<string, number[]> = {};
            for (let i = 0; i < items.length; i++) {
                const cx = Math.floor((items[i].x + items[i].offsetX) / CELL_W);
                const cy = Math.floor((items[i].y + items[i].offsetY) / CELL_H);
                const key = `${cx},${cy}`;
                (grid[key] ??= []).push(i);
            }
            // Check collisions only within same/adjacent cells
            const checked = new Set<string>();
            for (const key in grid) {
                const [cx, cy] = key.split(',').map(Number);
                for (let dx = -1; dx <= 1; dx++) {
                    for (let dy = -1; dy <= 1; dy++) {
                        const nk = `${cx + dx},${cy + dy}`;
                        if (!grid[nk]) continue;
                        const pairKey = cx + dx < cx || (cx + dx === cx && cy + dy < cy) ? `${nk}|${key}` : `${key}|${nk}`;
                        if (key !== nk && checked.has(pairKey)) continue;
                        checked.add(pairKey);
                        const cellA = grid[key];
                        const cellB = key === nk ? cellA : grid[nk];
                        for (const i of cellA) {
                            const startJ = key === nk ? cellA.indexOf(i) + 1 : 0;
                            for (let jIdx = startJ; jIdx < cellB.length; jIdx++) {
                                const j = cellB[jIdx];
                                if (i === j) continue;
                                const a = items[i], b = items[j];
                                const adx = Math.abs((a.x + a.offsetX) - (b.x + b.offsetX));
                                const ady = Math.abs((a.y + a.offsetY) - (b.y + b.offsetY));
                                const minDistX = BOX_W + GAP;
                                const minDistY = (a.boxH + b.boxH) / 2 + GAP;
                                if (adx < minDistX && ady < minDistY) {
                                    moved = true;
                                    const overlapX = minDistX - adx;
                                    const overlapY = minDistY - ady;
                                    if (overlapY < overlapX) {
                                        const push = (overlapY / 2) + 1;
                                        if ((a.y + a.offsetY) <= (b.y + b.offsetY)) { a.offsetY -= push; b.offsetY += push; }
                                        else { a.offsetY += push; b.offsetY -= push; }
                                    } else {
                                        const push = (overlapX / 2) + 1;
                                        if ((a.x + a.offsetX) <= (b.x + b.offsetX)) { a.offsetX -= push; b.offsetX += push; }
                                        else { a.offsetX += push; b.offsetX -= push; }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            if (!moved) break;
        }

        // Clamp offsets so boxes stay near their origin
        for (const item of items) {
            item.offsetX = Math.max(-MAX_OFFSET, Math.min(MAX_OFFSET, item.offsetX));
            item.offsetY = Math.max(-MAX_OFFSET, Math.min(MAX_OFFSET, item.offsetY));
        }

        return items.map((item: any) => ({
            ...item,
            showLine: Math.abs(item.offsetX) > 5 || Math.abs(item.offsetY) > 5
        }));
    }, [data?.news, Math.round(viewState.zoom)]);

    const trackedFlightsGeoJSON = useMemo(() => {
        if (!activeLayers.tracked || !data?.tracked_flights) return null;

        // Tracked icon maps by aircraft shape and alert color
        const trackedIconMap: Record<string, Record<string, string>> = {
            heli: { '#ff1493': 'svgHeliPink', pink: 'svgHeliPink', red: 'svgHeliAlertRed', blue: 'svgHeliBlue', darkblue: 'svgHeliDarkBlue', yellow: 'svgHeli', orange: 'svgHeliOrange', purple: 'svgHeliPurple', '#32cd32': 'svgHeliLime', black: 'svgHeliBlack', white: 'svgHeliWhiteAlert' },
            airliner: { '#ff1493': 'svgAirlinerPink', pink: 'svgAirlinerPink', red: 'svgAirlinerRed', blue: 'svgAirlinerBlue', darkblue: 'svgAirlinerDarkBlue', yellow: 'svgAirlinerYellow', orange: 'svgAirlinerOrange', purple: 'svgAirlinerPurple', '#32cd32': 'svgAirlinerLime', black: 'svgAirlinerBlack', white: 'svgAirlinerWhite' },
            turboprop: { '#ff1493': 'svgTurbopropPink', pink: 'svgTurbopropPink', red: 'svgTurbopropRed', blue: 'svgTurbopropBlue', darkblue: 'svgTurbopropDarkBlue', yellow: 'svgTurbopropYellow', orange: 'svgTurbopropOrange', purple: 'svgTurbopropPurple', '#32cd32': 'svgTurbopropLime', black: 'svgTurbopropBlack', white: 'svgTurbopropWhite' },
            bizjet: { '#ff1493': 'svgBizjetPink', pink: 'svgBizjetPink', red: 'svgBizjetRed', blue: 'svgBizjetBlue', darkblue: 'svgBizjetDarkBlue', yellow: 'svgBizjetYellow', orange: 'svgBizjetOrange', purple: 'svgBizjetPurple', '#32cd32': 'svgBizjetLime', black: 'svgBizjetBlack', white: 'svgBizjetWhite' },
        };

        return {
            type: 'FeatureCollection',
            features: data.tracked_flights.map((f: any, i: number) => {
                if (f.lat == null || f.lng == null) return null;

                const alertColor = f.alert_color || 'white';
                const acType = classifyAircraft(f.model, f.aircraft_category);
                const grounded = f.alt != null && f.alt <= 100;
                const icaoHex = (f.icao24 || '').toUpperCase();
                // POTUS fleet gets oversized gold-ringed icon
                const isPotus = POTUS_ICAOS.has(icaoHex);
                const potusIcon = acType === 'heli' ? 'svgPotusHeli' : 'svgPotusPlane';
                const iconId = grounded ? GROUNDED_ICON_MAP[acType] : isPotus ? potusIcon : (trackedIconMap[acType]?.[alertColor] || trackedIconMap.airliner[alertColor] || 'svgAirlinerWhite');

                const displayName = f.alert_operator || f.operator || f.owner || f.name || f.callsign || f.icao24 || "UNKNOWN";

                const [iLng, iLat] = interpFlight(f);
                return {
                    type: 'Feature',
                    properties: { id: i, type: 'tracked_flight', callsign: String(displayName), rotation: f.heading || 0, iconId },
                    geometry: { type: 'Point', coordinates: [iLng, iLat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.tracked, data?.tracked_flights, dtSeconds]);

    const uavGeoJSON = useMemo(() => {
        if (!activeLayers.military || !data?.uavs) return null;
        return {
            type: 'FeatureCollection',
            features: data.uavs.map((uav: any, i: number) => {
                if (uav.lat == null || uav.lng == null || !inView(uav.lat, uav.lng)) return null;
                return {
                    type: 'Feature',
                    properties: {
                        id: uav.id || `uav-${i}`,
                        type: 'uav',
                        callsign: uav.callsign,
                        rotation: uav.heading || 0,
                        iconId: 'svgDrone',
                        name: uav.aircraft_model || uav.callsign,
                        country: uav.country || '',
                        uav_type: uav.uav_type || '',
                        alt: uav.alt || 0,
                        wiki: uav.wiki || '',
                        speed_knots: uav.speed_knots || 0,
                        icao24: uav.icao24 || '',
                        registration: uav.registration || '',
                        squawk: uav.squawk || '',
                    },
                    geometry: { type: 'Point', coordinates: [uav.lng, uav.lat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.military, data?.uavs, inView]);

    // UAV range circles removed — real ADS-B drones don't have a fixed orbit center

    const gdeltGeoJSON = useMemo(() => {
        if (!activeLayers.global_incidents || !data?.gdelt) return null;
        return {
            type: 'FeatureCollection',
            features: data.gdelt.map((g: any, i: number) => {
                if (!g.geometry || !g.geometry.coordinates) return null;
                const [gLng, gLat] = g.geometry.coordinates;
                if (!inView(gLat, gLng)) return null;
                return {
                    type: 'Feature',
                    properties: { id: i, type: 'gdelt', title: g.title },
                    geometry: g.geometry
                };
            }).filter(Boolean)
        };
    }, [activeLayers.global_incidents, data?.gdelt, inView]);

    const liveuaGeoJSON = useMemo(() => {
        if (!activeLayers.global_incidents || !data?.liveuamap) return null;
        return {
            type: 'FeatureCollection',
            features: data.liveuamap.map((incident: any, i: number) => {
                if (incident.lat == null || incident.lng == null || !inView(incident.lat, incident.lng)) return null;
                const isViolent = /bomb|missil|strike|attack|kill|destroy|fire|shoot|expl|raid/i.test(incident.title || "");
                return {
                    type: 'Feature',
                    properties: { id: incident.id, type: 'liveuamap', title: incident.title, iconId: isViolent ? 'icon-liveua-red' : 'icon-liveua-yellow' },
                    geometry: { type: 'Point', coordinates: [incident.lng, incident.lat] }
                };
            }).filter(Boolean)
        };
    }, [activeLayers.global_incidents, data?.liveuamap, inView]);

    const frontlineGeoJSON = useMemo(() => {
        if (!activeLayers.ukraine_frontline || !data?.frontlines) return null;
        return data.frontlines; // Frontlines is already a fully formed GeoJSON FeatureCollection
    }, [activeLayers.ukraine_frontline, data?.frontlines]);



    const activeInteractiveLayerIds = [
        commFlightsGeoJSON && 'commercial-flights-layer',
        privFlightsGeoJSON && 'private-flights-layer',
        privJetsGeoJSON && 'private-jets-layer',
        milFlightsGeoJSON && 'military-flights-layer',
        shipsGeoJSON && 'ships-clusters-layer',
        shipsGeoJSON && 'ships-layer',
        carriersGeoJSON && 'carriers-layer',
        trackedFlightsGeoJSON && 'tracked-flights-layer',
        uavGeoJSON && 'uav-layer',
        gdeltGeoJSON && 'gdelt-layer',
        liveuaGeoJSON && 'liveuamap-layer',
        frontlineGeoJSON && 'ukraine-frontline-layer',
        earthquakesGeoJSON && 'earthquakes-layer',
        satellitesGeoJSON && 'satellites-layer',
        cctvGeoJSON && 'cctv-layer',
        kiwisdrGeoJSON && 'kiwisdr-layer',
        internetOutagesGeoJSON && 'internet-outages-layer',
        dataCentersGeoJSON && 'datacenters-layer',
        firmsGeoJSON && 'firms-viirs-layer'
    ].filter(Boolean) as string[];


    // --- Imperative source updates for high-volume layers ---
    // Bypasses React reconciliation of huge GeoJSON FeatureCollections.
    // The <Source data={EMPTY_FC}> mounts the source; the hook pushes real data.
    const mapForHook = mapReady ? mapRef.current : null;
    // Flights & UAVs: immediate (they move fast, stale = visually wrong)
    useImperativeSource(mapForHook, 'commercial-flights', commFlightsGeoJSON);
    useImperativeSource(mapForHook, 'private-flights', privFlightsGeoJSON);
    useImperativeSource(mapForHook, 'private-jets', privJetsGeoJSON);
    useImperativeSource(mapForHook, 'military-flights', milFlightsGeoJSON);
    useImperativeSource(mapForHook, 'tracked-flights', trackedFlightsGeoJSON);
    useImperativeSource(mapForHook, 'uavs', uavGeoJSON);
    // Satellites & fires: 2s debounce (slow-changing, high feature count)
    useImperativeSource(mapForHook, 'satellites', satellitesGeoJSON, 2000);
    useImperativeSource(mapForHook, 'firms-fires', firmsGeoJSON, 2000);

    const handleMouseMove = useCallback((evt: any) => {
        if (onMouseCoords) onMouseCoords({ lat: evt.lngLat.lat, lng: evt.lngLat.lng });
    }, [onMouseCoords]);

    const opacityFilter: any = selectedEntity
        ? ['case', ['all', ['==', ['get', 'type'], selectedEntity.type], ['==', ['get', 'id'], selectedEntity.id]], 1.0, 0.0]
        : 1.0;

    return (
        <div className={`relative h-full w-full z-0 isolate ${selectedEntity && ['region_dossier', 'gdelt', 'liveuamap', 'news'].includes(selectedEntity.type) ? 'map-focus-active' : ''}`}>
            <Map
                ref={mapRef}
                reuseMaps
                maxTileCacheSize={200}
                fadeDuration={0}
                initialViewState={viewState}
                onMove={evt => {
                    setViewState(evt.viewState);
                    onViewStateChange?.({ zoom: evt.viewState.zoom, latitude: evt.viewState.latitude });
                    // Debounce bounds update to avoid thrashing during drag
                    if (boundsTimerRef.current) clearTimeout(boundsTimerRef.current);
                    boundsTimerRef.current = setTimeout(updateBounds, 300);
                }}
                onMouseMove={handleMouseMove}
                onContextMenu={(evt) => {
                    evt.preventDefault();
                    onRightClick?.({ lat: evt.lngLat.lat, lng: evt.lngLat.lng });
                }}
                mapStyle={mapThemeStyle as any}
                mapLib={maplibregl}
                onLoad={onMapLoad}
                onIdle={updateBounds}
                interactiveLayerIds={activeInteractiveLayerIds}
                onClick={(e) => {
                    // Measurement mode: place waypoints instead of selecting entities
                    if (measureMode && onMeasureClick) {
                        onMeasureClick({ lat: e.lngLat.lat, lng: e.lngLat.lng });
                        return;
                    }
                    if (selectedEntity) {
                        onEntityClick?.(null);
                    } else if (e.features && e.features.length > 0) {
                        const feature = e.features[0];
                        const props = feature.properties || {};
                        onEntityClick?.({
                            id: props.id,
                            type: props.type,
                            name: props.name,
                            media_url: props.media_url,
                            extra: props
                        });
                    } else {
                        onEntityClick?.(null);
                    }
                }}
            >
                {/* Esri World Imagery — high-res static satellite (zoom 0-18+) */}
                {activeLayers.highres_satellite && (
                    <Source
                        id="esri-world-imagery"
                        type="raster"
                        tiles={['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}']}
                        tileSize={256}
                        maxzoom={18}
                        attribution="Esri, Maxar, Earthstar Geographics"
                    >
                        <Layer
                            id="esri-world-imagery-layer"
                            type="raster"
                            beforeId="imagery-ceiling"
                            paint={{
                                'raster-opacity': 1,
                                'raster-fade-duration': 300
                            }}
                        />
                    </Source>
                )}

                {/* NASA GIBS MODIS Terra — daily satellite imagery overlay */}
                {activeLayers.gibs_imagery && gibsDate && (
                    <Source
                        key={`gibs-${gibsDate}`}
                        id="gibs-modis"
                        type="raster"
                        tiles={[`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/${gibsDate}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`]}
                        tileSize={256}
                        maxzoom={9}
                    >
                        <Layer
                            id="gibs-modis-layer"
                            type="raster"
                            beforeId="imagery-ceiling"
                            paint={{
                                'raster-opacity': gibsOpacity ?? 0.6,
                                'raster-fade-duration': 0
                            }}
                        />
                    </Source>
                )}

                {/* NASA FIRMS VIIRS — fire hotspot icons from FIRMS CSV feed */}
                {/* firms-fires: data pushed imperatively via useImperativeSource */}
                    <Source id="firms-fires" type="geojson" data={EMPTY_FC as any} cluster={true} clusterRadius={40} clusterMaxZoom={10}>
                        {/* Cluster fire icons — flame shape to differentiate from Global Incidents circles */}
                        <Layer
                            id="firms-clusters"
                            type="symbol"
                            filter={['has', 'point_count']}
                            layout={{
                                'icon-image': ['step', ['get', 'point_count'],
                                    'fire-cluster-sm', 10, 'fire-cluster-md', 50, 'fire-cluster-lg', 200, 'fire-cluster-xl'],
                                'icon-size': ['step', ['get', 'point_count'], 1.0, 10, 1.1, 50, 1.2, 200, 1.3],
                                'icon-allow-overlap': true,
                                'icon-ignore-placement': true,
                                'text-field': '{point_count_abbreviated}',
                                'text-font': ['Noto Sans Bold'],
                                'text-size': ['step', ['get', 'point_count'], 9, 10, 10, 50, 11, 200, 12],
                                'text-offset': [0, 0.15],
                                'text-allow-overlap': true,
                            }}
                            paint={{
                                'text-color': '#ffffff',
                                'text-halo-color': 'rgba(0,0,0,0.8)',
                                'text-halo-width': 1.2,
                            }}
                        />
                        {/* Individual fire icons — flame shape sized by FRP */}
                        <Layer
                            id="firms-viirs-layer"
                            type="symbol"
                            filter={['!', ['has', 'point_count']]}
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': ['interpolate', ['linear'], ['zoom'],
                                    2, 0.4,
                                    5, 0.6,
                                    8, 0.8,
                                    12, 1.0
                                ],
                                'icon-allow-overlap': true,
                                'icon-ignore-placement': true,
                            }}
                        />
                    </Source>

                {/* SOLAR TERMINATOR — night overlay */}
                {activeLayers.day_night && nightGeoJSON && (
                    <Source id="night-overlay" type="geojson" data={nightGeoJSON as any}>
                        <Layer
                            id="night-overlay-layer"
                            type="fill"
                            paint={{
                                'fill-color': '#0a0e1a',
                                'fill-opacity': 0.35,
                            }}
                        />
                    </Source>
                )}

                {/* commercial/private/military flights: data pushed imperatively */}
                    <Source id="commercial-flights" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="commercial-flights-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                    <Source id="private-flights" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="private-flights-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                    <Source id="private-jets" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="private-jets-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                    <Source id="military-flights" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="military-flights-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                {shipsGeoJSON && (
                    <Source
                        id="ships"
                        type="geojson"
                        data={shipsGeoJSON as any}
                        cluster={true}
                        clusterMaxZoom={8}
                        clusterRadius={40}
                    >
                        {/* Clustered circles */}
                        <Layer
                            id="ships-clusters-layer"
                            type="circle"
                            filter={['has', 'point_count']}
                            paint={{
                                'circle-opacity': opacityFilter,
                                'circle-stroke-opacity': opacityFilter,
                                'circle-color': 'rgba(30, 64, 175, 0.85)',
                                'circle-radius': [
                                    'step',
                                    ['get', 'point_count'],
                                    12,
                                    10, 15,
                                    100, 20,
                                    1000, 25,
                                    5000, 30
                                ],
                                'circle-stroke-width': 2,
                                'circle-stroke-color': 'rgba(59, 130, 246, 1.0)'
                            }}
                        />

                        {/* Cluster count - rendered via HTML markers below */}
                        <Layer
                            id="ships-cluster-count-layer"
                            type="circle"
                            filter={['has', 'point_count']}
                            paint={{ 'circle-radius': 0, 'circle-opacity': 0 }}
                        />

                        {/* Unclustered individual ships (Cargo, Tankers, etc.) */}
                        <Layer
                            id="ships-layer"
                            type="symbol"
                            minzoom={4}
                            filter={['!', ['has', 'point_count']]}
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{
                                'icon-opacity': opacityFilter
                            }}
                        />
                    </Source>
                )}

                {carriersGeoJSON && (
                    <Source id="carriers" type="geojson" data={carriersGeoJSON as any}>
                        <Layer
                            id="carriers-layer"
                            type="symbol"
                            layout={{
                                'icon-image': 'svgCarrier',
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>
                )}


                {activeRouteGeoJSON && (
                    <Source id="active-route" type="geojson" data={activeRouteGeoJSON as any}>
                        <Layer
                            id="active-route-layer"
                            type="line"
                            paint={{
                                'line-color': [
                                    'match',
                                    ['get', 'type'],
                                    'route-origin', '#38bdf8', // light blue
                                    'route-dest', '#fcd34d', // yellow
                                    '#ffffff'
                                ],
                                'line-width': 2,
                                'line-dasharray': [2, 2],
                                'line-opacity': 0.8
                            }}
                        />
                    </Source>
                )}

                {/* Flight trail history (where the aircraft has been) */}
                {trailGeoJSON && (
                    <Source id="flight-trail" type="geojson" data={trailGeoJSON as any}>
                        <Layer
                            id="flight-trail-layer"
                            type="line"
                            paint={{
                                'line-color': '#22d3ee',
                                'line-width': 2,
                                'line-opacity': 0.6,
                            }}
                        />
                    </Source>
                )}

                {/* tracked-flights & UAVs: data pushed imperatively */}
                    <Source id="tracked-flights" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="tracked-flights-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                    <Source id="uavs" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="uav-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                                'icon-rotate': ['get', 'rotation'],
                                'icon-rotation-alignment': 'map'
                            }}
                            paint={{ 'icon-opacity': opacityFilter }}
                        />
                    </Source>

                {/* UAV range circles removed — real ADS-B data has no fixed orbit */}

                {gdeltGeoJSON && (
                    <Source id="gdelt" type="geojson" data={gdeltGeoJSON as any}>
                        <Layer
                            id="gdelt-layer"
                            type="circle"
                            minzoom={4}
                            paint={{
                                'circle-radius': 5,
                                'circle-color': '#ff8c00',
                                'circle-stroke-color': '#ff0000',
                                'circle-stroke-width': 1,
                                'circle-opacity': 0.7
                            }}
                        />
                    </Source>
                )}

                {liveuaGeoJSON && (
                    <Source id="liveuamap" type="geojson" data={liveuaGeoJSON as any}>
                        <Layer
                            id="liveuamap-layer"
                            type="symbol"
                            minzoom={4}
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': 0.8,
                                'icon-allow-overlap': true,
                            }}
                        />
                    </Source>
                )}

                {/* HTML labels for ship cluster counts (hidden when any entity popup is active) */}
                {shipsGeoJSON && !selectedEntity && shipClusters.map((c: any) => (
                    <Marker key={`sc-${c.id}`} longitude={c.lng} latitude={c.lat} anchor="center" style={{ zIndex: 1 }}>
                        <div style={{ color: '#fff', fontSize: '11px', fontFamily: 'monospace', fontWeight: 'bold', textShadow: '0 0 3px #000, 0 0 3px #000', pointerEvents: 'none', textAlign: 'center' }}>
                            {c.count}
                        </div>
                    </Marker>
                ))}

                {/* HTML labels for tracked flights — color-matched, zoom-gated for non-HVA */}
                {trackedFlightsGeoJSON && !selectedEntity && data?.tracked_flights?.map((f: any, i: number) => {
                    if (f.lat == null || f.lng == null) return null;
                    if (!inView(f.lat, f.lng)) return null;

                    const alertColor = f.alert_color || '#ff1493';
                    // Always hide military labels (yellow) — too many, clutters map
                    if (alertColor === 'yellow') return null;
                    // Hide black (PIA) labels — they want to stay hidden
                    if (alertColor === 'black') return null;

                    // Only show non-HVA/non-red labels when zoomed in (~2000mi or closer = zoom >= 5)
                    const isHighPriority = alertColor === '#ff1493' || alertColor === 'pink' || alertColor === 'red';
                    if (!isHighPriority && viewState.zoom < 5) return null;

                    let displayName = f.alert_operator || f.operator || f.owner || f.name || f.callsign || f.icao24 || "UNKNOWN";
                    // Strip redundant "Private" labels — tells you nothing
                    if (displayName === 'Private' || displayName === 'private') return null;

                    // Map alert_color to a visible label color (some hex colors render near-white)
                    const labelColorMap: Record<string, string> = {
                        '#ff1493': '#ff1493', pink: '#ff1493', red: '#ff4444',
                        blue: '#3b82f6', orange: '#FF8C00', '#32cd32': '#32cd32',
                        purple: '#b266ff', white: '#cccccc',
                    };
                    const grounded = f.alt != null && f.alt <= 100;
                    const labelColor = grounded ? '#888' : (labelColorMap[alertColor] || alertColor);
                    const [iLng, iLat] = interpFlight(f);

                    return (
                        <Marker key={`tf-label-${i}`} longitude={iLng} latitude={iLat} anchor="top" offset={[0, 10]} style={{ zIndex: 2 }}>
                            <div style={{
                                color: labelColor,
                                fontSize: '10px',
                                fontFamily: 'monospace',
                                fontWeight: 'bold',
                                textShadow: '0 0 3px #000, 0 0 3px #000, 1px 1px 2px #000',
                                whiteSpace: 'nowrap',
                                pointerEvents: 'none'
                            }}>
                                {String(displayName)}
                            </div>
                        </Marker>
                    );
                })}

                {/* HTML labels for carriers (orange names, with ESTIMATED badge for OSINT positions) */}
                {carriersGeoJSON && !selectedEntity && data?.ships?.map((s: any, i: number) => {
                    if (s.type !== 'carrier' || s.lat == null || s.lng == null) return null;
                    if (!inView(s.lat, s.lng)) return null;
                    const [iLng, iLat] = interpShip(s);
                    return (
                        <Marker key={`carrier-label-${i}`} longitude={iLng} latitude={iLat} anchor="top" offset={[0, 12]} style={{ zIndex: 2 }}>
                            <div style={{ fontFamily: 'monospace', textShadow: '0 0 3px #000, 0 0 3px #000, 1px 1px 2px #000', whiteSpace: 'nowrap', pointerEvents: 'none', textAlign: 'center' }}>
                                <div style={{ color: '#ffaa00', fontSize: '11px', fontWeight: 'bold' }}>
                                    [[{s.name}]]
                                </div>
                                {s.estimated && (
                                    <div style={{ color: '#ff6644', fontSize: '8px', letterSpacing: '1.5px' }}>
                                        EST. POSITION — OSINT
                                    </div>
                                )}
                            </div>
                        </Marker>
                    );
                })}

                {/* HTML labels for earthquake cluster counts (hidden when any entity popup is active) */}
                {earthquakesGeoJSON && !selectedEntity && eqClusters.map((c: any) => (
                    <Marker key={`eqc-${c.id}`} longitude={c.lng} latitude={c.lat} anchor="center" style={{ zIndex: 1 }}>
                        <div style={{ color: '#fff', fontSize: '11px', fontFamily: 'monospace', fontWeight: 'bold', textShadow: '0 0 3px #000, 0 0 3px #000', pointerEvents: 'none', textAlign: 'center' }}>
                            {c.count}
                        </div>
                    </Marker>
                ))}

                {/* HTML labels for UAVs (orange names) */}
                {uavGeoJSON && !selectedEntity && data?.uavs?.map((uav: any, i: number) => {
                    if (uav.lat == null || uav.lng == null) return null;
                    if (!inView(uav.lat, uav.lng)) return null;
                    const name = uav.aircraft_model ? `[UAV: ${uav.aircraft_model}]` : `[UAV: ${uav.callsign}]`;
                    return (
                        <Marker key={`uav-label-${i}`} longitude={uav.lng} latitude={uav.lat} anchor="top" offset={[0, 10]} style={{ zIndex: 2 }}>
                            <div style={{ color: '#ff8c00', fontSize: '10px', fontFamily: 'monospace', fontWeight: 'bold', textShadow: '0 0 3px #000, 0 0 3px #000, 1px 1px 2px #000', whiteSpace: 'nowrap', pointerEvents: 'none' }}>
                                {name}
                            </div>
                        </Marker>
                    );
                })}

                {/* HTML labels for earthquakes (yellow) - only show when zoomed in (~2000 miles = zoom ~5) */}
                {earthquakesGeoJSON && !selectedEntity && viewState.zoom >= 5 && data?.earthquakes?.map((eq: any, i: number) => {
                    if (eq.lat == null || eq.lng == null) return null;
                    if (!inView(eq.lat, eq.lng)) return null;
                    return (
                        <Marker key={`eq-label-${i}`} longitude={eq.lng} latitude={eq.lat} anchor="top" offset={[0, 14]} style={{ zIndex: 1 }}>
                            <div style={{ color: '#ffcc00', fontSize: '10px', fontFamily: 'monospace', fontWeight: 'bold', textShadow: '0 0 3px #000, 0 0 3px #000, 1px 1px 2px #000', whiteSpace: 'nowrap', pointerEvents: 'none' }}>
                                [M{eq.mag}] {eq.place || ''}
                            </div>
                        </Marker>
                    );
                })}

                {/* Maplibre HTML Custom Markers for high-importance Threat Overlays (highest z-index) */}
                {activeLayers.global_incidents && spreadAlerts.map((n: any) => {
                    const idx = n.originalIdx;
                    const count = n.cluster_count || 1;
                    const score = n.risk_score || 0;

                    let riskColor = '#22c55e'; // Green (1-3)
                    if (score >= 9) riskColor = '#ef4444'; // Red (9-10)
                    else if (score >= 7) riskColor = '#f97316'; // Orange (7-8)
                    else if (score >= 4) riskColor = '#eab308'; // Yellow (4-6)
                    else if (score >= 1) riskColor = '#3b82f6'; // Blue (1-3)

                    // Hide alerts when any entity is selected (focus mode)
                    // For news: only show the selected alert. For all others: hide all alerts.
                    let isVisible = viewState.zoom >= 1;
                    if (selectedEntity) {
                        if (selectedEntity.type === 'news') {
                            if (selectedEntity.id !== idx) isVisible = false;
                        } else {
                            isVisible = false;
                        }
                    }

                    return (
                        <Marker
                            key={`threat-${idx}`}
                            longitude={n.coords[1]}
                            latitude={n.coords[0]}
                            anchor="center"
                            offset={[n.offsetX, n.offsetY]}
                            style={{ zIndex: 50 + score }}
                            onClick={(e) => {
                                e.originalEvent.stopPropagation();
                                onEntityClick?.({ id: idx, type: 'news' });
                            }}
                        >
                            <div className="relative group/alert">
                                {/* Connector Line for scattered markers (Speech Bubble Line) */}
                                {n.showLine && isVisible && (
                                    <svg className="absolute pointer-events-none" style={{ left: '50%', top: '50%', width: 1, height: 1, overflow: 'visible', zIndex: -1 }}>
                                        <line x1={0} y1={0} x2={-n.offsetX} y2={-n.offsetY} stroke={riskColor} strokeWidth="1.5" strokeDasharray="3,3" className="opacity-80" />
                                        <circle cx={-n.offsetX} cy={-n.offsetY} r="2" fill={riskColor} />
                                    </svg>
                                )}

                                <div
                                    className="cursor-pointer transition-all duration-300 relative"
                                    style={{
                                        opacity: isVisible ? 1.0 : 0.0,
                                        pointerEvents: isVisible ? 'auto' : 'none',
                                        backgroundColor: 'rgba(5, 5, 5, 0.95)',
                                        border: `1.5px solid ${riskColor}`,
                                        borderRadius: '4px',
                                        padding: '5px 8px',
                                        color: riskColor,
                                        fontFamily: 'monospace',
                                        fontSize: '9px',
                                        fontWeight: 'bold',
                                        textAlign: 'center',
                                        boxShadow: `0 0 12px ${riskColor}60`,
                                        zIndex: 10,
                                        lineHeight: '1.2',
                                        minWidth: '120px'
                                    }}
                                >
                                    {/* Bubble Tail / Triangle */}
                                    {n.showLine && isVisible && (
                                        <div
                                            className="absolute"
                                            style={{
                                                width: 0,
                                                height: 0,
                                                borderLeft: '6px solid transparent',
                                                borderRight: '6px solid transparent',
                                                // If above origin, point down. If below, point up.
                                                borderTop: n.offsetY < 0 ? `6px solid ${riskColor}` : 'none',
                                                borderBottom: n.offsetY > 0 ? `6px solid ${riskColor}` : 'none',
                                                left: '50%',
                                                [n.offsetY < 0 ? 'bottom' : 'top']: '-6px',
                                                transform: 'translateX(-50%)'
                                            }}
                                        />
                                    )}

                                    <div className="absolute inset-0 border border-current rounded opacity-50 animate-pulse" style={{ color: riskColor, zIndex: -1 }}></div>
                                    <div style={{ fontSize: '10px', letterSpacing: '0.5px' }}>!! ALERT LVL {score} !!</div>
                                    <div style={{ color: '#fff', fontSize: '9px', marginTop: '2px', maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                        {n.title}
                                    </div>
                                    {count > 1 && (
                                        <div style={{ color: riskColor, opacity: 0.8, fontSize: '8px', marginTop: '2px' }}>
                                            [+{count - 1} ACTIVE THREATS IN AREA]
                                        </div>
                                    )}
                                </div>
                            </div>
                        </Marker>
                    );
                })}

                {frontlineGeoJSON && (
                    <Source id="frontlines" type="geojson" data={frontlineGeoJSON as any}>
                        <Layer
                            id="ukraine-frontline-layer"
                            type="fill"
                            paint={{
                                'fill-color': '#ff0000',
                                'fill-opacity': 0.3,
                                'fill-outline-color': '#ff5500'
                            }}
                        />
                    </Source>
                )}

                {earthquakesGeoJSON && (
                    <Source
                        id="earthquakes"
                        type="geojson"
                        data={earthquakesGeoJSON as any}
                        cluster={true}
                        clusterMaxZoom={10}
                        clusterRadius={60}
                    >
                        {/* Earthquake cluster circles */}
                        <Layer
                            id="eq-clusters-layer"
                            type="circle"
                            filter={['has', 'point_count']}
                            paint={{
                                'circle-color': 'rgba(255, 170, 0, 0.85)',
                                'circle-radius': [
                                    'step',
                                    ['get', 'point_count'],
                                    12,
                                    5, 16,
                                    10, 20,
                                    20, 24
                                ],
                                'circle-stroke-width': 2,
                                'circle-stroke-color': 'rgba(255, 200, 0, 1.0)'
                            }}
                        />
                        {/* Individual (unclustered) earthquake icons */}
                        <Layer
                            id="earthquakes-layer"
                            type="symbol"
                            filter={['!', ['has', 'point_count']]}
                            layout={{
                                'icon-image': 'icon-threat',
                                'icon-size': 0.5,
                                'icon-allow-overlap': true
                            }}
                            paint={{ 'icon-opacity': 1.0 }}
                        />
                    </Source>
                )}

                {/* GPS Jamming Zones — red translucent grid squares */}
                {jammingGeoJSON && (
                    <Source id="gps-jamming" type="geojson" data={jammingGeoJSON as any}>
                        <Layer
                            id="gps-jamming-fill"
                            type="fill"
                            paint={{
                                'fill-color': '#ff0040',
                                'fill-opacity': ['get', 'opacity']
                            }}
                        />
                        <Layer
                            id="gps-jamming-outline"
                            type="line"
                            paint={{
                                'line-color': '#ff0040',
                                'line-width': 1.5,
                                'line-opacity': 0.6
                            }}
                        />
                        <Layer
                            id="gps-jamming-label"
                            type="symbol"
                            layout={{
                                'text-field': ['concat', 'GPS JAM ', ['to-string', ['round', ['*', 100, ['get', 'ratio']]]], '%'],
                                'text-size': [
                                    'interpolate', ['linear'], ['zoom'],
                                    2, 8,
                                    5, 10,
                                    8, 12
                                ],
                                'text-allow-overlap': false,
                                'text-ignore-placement': false
                            }}
                            paint={{
                                'text-color': '#ff4060',
                                'text-halo-color': '#000000',
                                'text-halo-width': 1.5
                            }}
                        />
                    </Source>
                )}

                {/* CCTV Cameras — clustered green dots */}
                {cctvGeoJSON && (
                    <Source id="cctv" type="geojson" data={cctvGeoJSON as any} cluster={true} clusterRadius={50} clusterMaxZoom={14}>
                        {/* Cluster circles — green, sized by count */}
                        <Layer
                            id="cctv-clusters"
                            type="circle"
                            filter={['has', 'point_count']}
                            paint={{
                                'circle-color': '#22c55e',
                                'circle-radius': [
                                    'step', ['get', 'point_count'],
                                    14, 10,
                                    18, 50,
                                    24, 200,
                                    30
                                ],
                                'circle-opacity': 0.8,
                                'circle-stroke-width': 2,
                                'circle-stroke-color': '#16a34a'
                            }}
                        />
                        {/* Cluster count labels */}
                        <Layer
                            id="cctv-cluster-count"
                            type="symbol"
                            filter={['has', 'point_count']}
                            layout={{
                                'text-field': '{point_count_abbreviated}',
                                'text-size': 12,
                                'text-allow-overlap': true
                            }}
                            paint={{
                                'text-color': '#ffffff',
                                'text-halo-color': '#000000',
                                'text-halo-width': 1
                            }}
                        />
                        {/* Individual camera dots */}
                        <Layer
                            id="cctv-layer"
                            type="circle"
                            filter={['!', ['has', 'point_count']]}
                            paint={{
                                'circle-color': '#22c55e',
                                'circle-radius': [
                                    'interpolate', ['linear'], ['zoom'],
                                    2, 2,
                                    8, 4,
                                    14, 6
                                ],
                                'circle-opacity': 0.9,
                                'circle-stroke-width': 1,
                                'circle-stroke-color': '#16a34a'
                            }}
                        />
                    </Source>
                )}

                {/* KiwiSDR Receivers — clustered amber dots */}
                {kiwisdrGeoJSON && (
                    <Source id="kiwisdr" type="geojson" data={kiwisdrGeoJSON as any} cluster={true} clusterRadius={50} clusterMaxZoom={14}>
                        <Layer
                            id="kiwisdr-clusters"
                            type="circle"
                            filter={['has', 'point_count']}
                            paint={{
                                'circle-color': '#f59e0b',
                                'circle-radius': ['step', ['get', 'point_count'], 14, 10, 18, 50, 24, 200, 30],
                                'circle-opacity': 0.8,
                                'circle-stroke-width': 2,
                                'circle-stroke-color': '#d97706'
                            }}
                        />
                        <Layer
                            id="kiwisdr-cluster-count"
                            type="symbol"
                            filter={['has', 'point_count']}
                            layout={{ 'text-field': '{point_count_abbreviated}', 'text-size': 12, 'text-allow-overlap': true }}
                            paint={{ 'text-color': '#ffffff', 'text-halo-color': '#000000', 'text-halo-width': 1 }}
                        />
                        <Layer
                            id="kiwisdr-layer"
                            type="circle"
                            filter={['!', ['has', 'point_count']]}
                            paint={{
                                'circle-color': '#f59e0b',
                                'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 2, 8, 4, 14, 6],
                                'circle-opacity': 0.9,
                                'circle-stroke-width': 1,
                                'circle-stroke-color': '#d97706'
                            }}
                        />
                    </Source>
                )}

                {/* Internet Outages — region-level grey markers with % and labels */}
                {internetOutagesGeoJSON && (
                    <Source id="internet-outages" type="geojson" data={internetOutagesGeoJSON as any}>
                        {/* Outer ring */}
                        <Layer
                            id="internet-outages-pulse"
                            type="circle"
                            paint={{
                                'circle-radius': ['interpolate', ['linear'], ['get', 'severity'], 0, 14, 50, 18, 80, 22],
                                'circle-color': 'rgba(180, 180, 180, 0.1)',
                                'circle-stroke-width': 1.5,
                                'circle-stroke-color': 'rgba(180, 180, 180, 0.35)',
                            }}
                        />
                        {/* Inner solid circle — all grey, size conveys severity */}
                        <Layer
                            id="internet-outages-layer"
                            type="circle"
                            paint={{
                                'circle-radius': ['interpolate', ['linear'], ['get', 'severity'], 0, 6, 50, 9, 80, 12],
                                'circle-color': '#888888',
                                'circle-stroke-width': 2,
                                'circle-stroke-color': 'rgba(0, 0, 0, 0.6)',
                                'circle-opacity': 0.9
                            }}
                        />
                        {/* Severity % inside circle */}
                        <Layer
                            id="internet-outages-pct"
                            type="symbol"
                            layout={{
                                'text-field': ['case', ['>', ['get', 'severity'], 0], ['concat', ['to-string', ['get', 'severity']], '%'], '!'],
                                'text-size': 9,
                                'text-font': ['Noto Sans Bold'],
                                'text-allow-overlap': true,
                                'text-ignore-placement': true,
                            }}
                            paint={{
                                'text-color': '#ffffff',
                                'text-halo-color': 'rgba(0,0,0,0.8)',
                                'text-halo-width': 1,
                            }}
                        />
                        {/* Region name label below — grey */}
                        <Layer
                            id="internet-outages-label"
                            type="symbol"
                            layout={{
                                'text-field': ['get', 'region'],
                                'text-size': 10,
                                'text-font': ['Noto Sans Bold'],
                                'text-offset': [0, 1.8],
                                'text-anchor': 'top',
                                'text-allow-overlap': false,
                            }}
                            paint={{
                                'text-color': '#aaaaaa',
                                'text-halo-color': 'rgba(0,0,0,0.9)',
                                'text-halo-width': 1.5,
                            }}
                        />
                    </Source>
                )}

                {/* Data Center positions */}
                {dataCentersGeoJSON && (
                    <Source id="datacenters" type="geojson" data={dataCentersGeoJSON as any} cluster={true} clusterRadius={30} clusterMaxZoom={8}>
                        {/* Cluster circles */}
                        <Layer
                            id="datacenters-clusters"
                            type="circle"
                            filter={['has', 'point_count']}
                            paint={{
                                'circle-color': '#7c3aed',
                                'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 50, 20],
                                'circle-opacity': 0.7,
                                'circle-stroke-width': 1,
                                'circle-stroke-color': '#a78bfa',
                            }}
                        />
                        <Layer
                            id="datacenters-cluster-count"
                            type="symbol"
                            filter={['has', 'point_count']}
                            layout={{
                                'text-field': '{point_count_abbreviated}',
                                'text-font': ['Noto Sans Bold'],
                                'text-size': 10,
                                'text-allow-overlap': true,
                            }}
                            paint={{
                                'text-color': '#e9d5ff',
                            }}
                        />
                        {/* Individual DC icons */}
                        <Layer
                            id="datacenters-layer"
                            type="symbol"
                            filter={['!', ['has', 'point_count']]}
                            layout={{
                                'icon-image': 'datacenter',
                                'icon-size': ['interpolate', ['linear'], ['zoom'], 2, 0.5, 6, 0.7, 10, 1.0],
                                'icon-allow-overlap': true,
                                'text-field': ['step', ['zoom'], '', 6, ['get', 'name']],
                                'text-font': ['Noto Sans Regular'],
                                'text-size': 9,
                                'text-offset': [0, 1.2],
                                'text-anchor': 'top',
                                'text-allow-overlap': false,
                            }}
                            paint={{
                                'text-color': '#c4b5fd',
                                'text-halo-color': 'rgba(0,0,0,0.9)',
                                'text-halo-width': 1,
                            }}
                        />
                    </Source>
                )}

                {/* Satellite positions — mission-type icons */}
                {/* satellites: data pushed imperatively */}
                    <Source id="satellites" type="geojson" data={EMPTY_FC as any}>
                        <Layer
                            id="satellites-layer"
                            type="symbol"
                            layout={{
                                'icon-image': ['get', 'iconId'],
                                'icon-size': [
                                    'interpolate', ['linear'], ['zoom'],
                                    0, 0.4,
                                    3, 0.5,
                                    6, 0.7,
                                    10, 1.0
                                ],
                                'icon-allow-overlap': true,
                            }}
                        />
                    </Source>

                {/* Satellite click popup */}
                {selectedEntity?.type === 'satellite' && (() => {
                    const sat = data?.satellites?.find((s: any) => s.id === selectedEntity.id);
                    if (!sat) return null;
                    const missionLabels: Record<string, string> = {
                        military_recon: '🔴 MILITARY RECON', military_sar: '🔴 MILITARY SAR',
                        sar: '🔷 SAR IMAGING', sigint: '🟠 SIGINT / ELINT',
                        navigation: '🔵 NAVIGATION', early_warning: '🟣 EARLY WARNING',
                        commercial_imaging: '🟢 COMMERCIAL IMAGING', space_station: '🏠 SPACE STATION',
                        communication: '📡 COMMUNICATION'
                    };
                    return (
                        <Popup
                            longitude={sat.lng} latitude={sat.lat}
                            closeButton={false} closeOnClick={false}
                            onClose={() => onEntityClick?.(null)}
                            anchor="bottom" offset={12}
                        >
                            <div style={{
                                background: 'rgba(10,14,26,0.95)', border: '1px solid rgba(0,200,255,0.3)',
                                borderRadius: 6, padding: '10px 14px', color: '#e0e6f0',
                                fontFamily: 'monospace', fontSize: 11, minWidth: 220, maxWidth: 320
                            }}>
                                <div style={{ color: '#00c8ff', fontWeight: 700, fontSize: 13, marginBottom: 6, letterSpacing: 1 }}>
                                    🛰️ {sat.name}
                                </div>
                                <div style={{ color: '#8899aa', marginBottom: 4 }}>
                                    NORAD ID: <span style={{ color: '#fff' }}>{sat.id}</span>
                                </div>
                                {sat.sat_type && (
                                    <div style={{ marginBottom: 4 }}>
                                        Type: <span style={{ color: '#ffcc00' }}>{sat.sat_type}</span>
                                    </div>
                                )}
                                {sat.country && (
                                    <div style={{ marginBottom: 4 }}>
                                        Country: <span style={{ color: '#fff' }}>{sat.country}</span>
                                    </div>
                                )}
                                {sat.mission && (
                                    <div style={{ marginBottom: 4, fontWeight: 600 }}>
                                        {missionLabels[sat.mission] || `⚪ ${sat.mission.toUpperCase()}`}
                                    </div>
                                )}
                                <div style={{ marginBottom: 4 }}>
                                    Altitude: <span style={{ color: '#44ff88' }}>{sat.alt_km?.toLocaleString()} km</span>
                                </div>
                                {sat.wiki && (
                                    <div className="mt-2 border-t border-[var(--border-primary)]/50 pt-2">
                                        <WikiImage wikiUrl={sat.wiki} label={sat.sat_type || sat.name} maxH="max-h-28" accent="hover:border-cyan-500/50" />
                                    </div>
                                )}
                            </div>
                        </Popup>
                    );
                })()}

                {/* UAV click popup — real ADS-B detected drones */}
                {selectedEntity?.type === 'uav' && (() => {
                    const uav = data?.uavs?.find((u: any) => u.id === selectedEntity.id);
                    if (!uav) return null;
                    return (
                        <Popup
                            longitude={uav.lng} latitude={uav.lat}
                            closeButton={false} closeOnClick={false}
                            onClose={() => onEntityClick?.(null)}
                            anchor="bottom" offset={12}
                        >
                            <div style={{
                                background: 'rgba(10,14,26,0.95)', border: '1px solid rgba(255,68,68,0.4)',
                                borderRadius: 6, padding: '10px 14px', color: '#e0e6f0',
                                fontFamily: 'monospace', fontSize: 11, minWidth: 220, maxWidth: 320
                            }}>
                                <div style={{ color: '#ff4444', fontWeight: 700, fontSize: 13, marginBottom: 6, letterSpacing: 1 }}>
                                    {uav.callsign}
                                </div>
                                <div style={{ color: '#ff8844', fontSize: 9, marginBottom: 6, letterSpacing: 1.5, textTransform: 'uppercase' as const }}>
                                    LIVE ADS-B TRANSPONDER
                                </div>
                                {uav.aircraft_model && (
                                    <div style={{ marginBottom: 4 }}>
                                        Model: <span style={{ color: '#fff' }}>{uav.aircraft_model}</span>
                                    </div>
                                )}
                                {uav.uav_type && (
                                    <div style={{ marginBottom: 4 }}>
                                        Classification: <span style={{ color: '#ffcc00' }}>{uav.uav_type}</span>
                                    </div>
                                )}
                                {uav.country && (
                                    <div style={{ marginBottom: 4 }}>
                                        Registration: <span style={{ color: '#fff' }}>{uav.country}</span>
                                    </div>
                                )}
                                {uav.icao24 && (
                                    <div style={{ marginBottom: 4 }}>
                                        ICAO: <span style={{ color: '#888' }}>{uav.icao24}</span>
                                    </div>
                                )}
                                <div style={{ marginBottom: 4 }}>
                                    Altitude: <span style={{ color: '#44ff88' }}>{uav.alt?.toLocaleString()} m</span>
                                </div>
                                {uav.speed_knots > 0 && (
                                    <div style={{ marginBottom: 4 }}>
                                        Speed: <span style={{ color: '#00e5ff' }}>{uav.speed_knots} kn</span>
                                    </div>
                                )}
                                {uav.squawk && (
                                    <div style={{ marginBottom: 4 }}>
                                        Squawk: <span style={{ color: '#888' }}>{uav.squawk}</span>
                                    </div>
                                )}
                                {uav.wiki && (
                                    <div className="mt-2 border-t border-[var(--border-primary)]/50 pt-2">
                                        <WikiImage wikiUrl={uav.wiki} label={uav.callsign} maxH="max-h-28" accent="hover:border-red-500/50" />
                                    </div>
                                )}
                            </div>
                        </Popup>
                    );
                })()}

                {/* Ship / carrier click popup */}
                {selectedEntity?.type === 'ship' && (() => {
                    const ship = data?.ships?.[selectedEntity.id as number];
                    if (!ship) return null;
                    const [iLng, iLat] = interpShip(ship);
                    return (
                        <Popup
                            longitude={iLng} latitude={iLat}
                            closeButton={false} closeOnClick={false}
                            onClose={() => onEntityClick?.(null)}
                            anchor="bottom" offset={12}
                        >
                            <div style={{
                                background: 'rgba(10,14,26,0.95)', border: `1px solid ${ship.type === 'carrier' ? 'rgba(255,170,0,0.5)' : 'rgba(59,130,246,0.4)'}`,
                                borderRadius: 6, padding: '10px 14px', color: '#e0e6f0',
                                fontFamily: 'monospace', fontSize: 11, minWidth: 220, maxWidth: 320
                            }}>
                                <div className="flex justify-between items-start mb-1">
                                    <div style={{ color: ship.type === 'carrier' ? '#ffaa00' : '#3b82f6', fontWeight: 700, fontSize: 13, letterSpacing: 1 }}>
                                        {ship.name || 'UNKNOWN VESSEL'}
                                    </div>
                                    <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] ml-2">✕</button>
                                </div>
                                {ship.estimated && (
                                    <div style={{ color: '#ff6644', fontSize: 9, marginBottom: 6, letterSpacing: 1.5, textTransform: 'uppercase' as const, borderBottom: '1px solid rgba(255,102,68,0.3)', paddingBottom: 4 }}>
                                        ESTIMATED POSITION — {ship.source || 'OSINT DERIVED'}
                                    </div>
                                )}
                                {ship.type && (
                                    <div style={{ marginBottom: 4 }}>
                                        Type: <span style={{ color: '#fff', textTransform: 'capitalize' as const }}>{ship.type.replace('_', ' ')}</span>
                                    </div>
                                )}
                                {ship.mmsi && (
                                    <div style={{ marginBottom: 4 }}>
                                        MMSI: <span style={{ color: '#888' }}>{ship.mmsi}</span>
                                    </div>
                                )}
                                {ship.imo && (
                                    <div style={{ marginBottom: 4 }}>
                                        IMO: <span style={{ color: '#888' }}>{ship.imo}</span>
                                    </div>
                                )}
                                {ship.callsign && (
                                    <div style={{ marginBottom: 4 }}>
                                        Callsign: <span style={{ color: '#00e5ff' }}>{ship.callsign}</span>
                                    </div>
                                )}
                                {ship.country && (
                                    <div style={{ marginBottom: 4 }}>
                                        Flag: <span style={{ color: '#fff' }}>{ship.country}</span>
                                    </div>
                                )}
                                {ship.destination && (
                                    <div style={{ marginBottom: 4 }}>
                                        Destination: <span style={{ color: '#44ff88' }}>{ship.destination}</span>
                                    </div>
                                )}
                                {typeof ship.sog === 'number' && ship.sog > 0 && (
                                    <div style={{ marginBottom: 4 }}>
                                        Speed: <span style={{ color: '#00e5ff' }}>{ship.sog.toFixed(1)} kn</span>
                                    </div>
                                )}
                                {ship.heading != null && (
                                    <div style={{ marginBottom: 4 }}>
                                        Heading: <span style={{ color: '#888' }}>{Math.round(ship.heading)}°</span>
                                    </div>
                                )}
                                {ship.last_osint_update && (
                                    <div style={{ marginBottom: 4 }}>
                                        Last OSINT Update: <span style={{ color: '#888' }}>{new Date(ship.last_osint_update).toLocaleDateString()}</span>
                                    </div>
                                )}
                            </div>
                        </Popup>
                    );
                })()}

                {/* Data Center click popup */}
                {selectedEntity?.type === 'datacenter' && (() => {
                    const dc = data?.datacenters?.find((_: any, i: number) => `dc-${i}` === selectedEntity.id);
                    if (!dc) return null;
                    // Check if any internet outage is in the same country
                    const outagesInCountry = (data?.internet_outages || []).filter((o: any) =>
                        o.country_name && dc.country && o.country_name.toLowerCase() === dc.country.toLowerCase()
                    );
                    return (
                        <Popup
                            longitude={dc.lng}
                            latitude={dc.lat}
                            closeButton={false}
                            closeOnClick={false}
                            onClose={() => onEntityClick?.(null)}
                            className="threat-popup"
                            maxWidth="280px"
                        >
                            <div style={{ background: '#1a1035', padding: '10px 14px', borderRadius: 8, border: '1px solid rgba(167,139,250,0.4)', fontFamily: 'monospace', fontSize: 11, color: '#e9d5ff', minWidth: 200 }}>
                                <div style={{ fontWeight: 'bold', fontSize: 13, color: '#a78bfa', marginBottom: 6, borderBottom: '1px solid rgba(167,139,250,0.2)', paddingBottom: 4 }}>
                                    {dc.name}
                                </div>
                                {dc.company && (
                                    <div style={{ marginBottom: 4 }}>
                                        Operator: <span style={{ color: '#c4b5fd' }}>{dc.company}</span>
                                    </div>
                                )}
                                {dc.city && (
                                    <div style={{ marginBottom: 4 }}>
                                        Location: <span style={{ color: '#fff' }}>{dc.city}{dc.country ? `, ${dc.country}` : ''}</span>
                                    </div>
                                )}
                                {!dc.city && dc.country && (
                                    <div style={{ marginBottom: 4 }}>
                                        Country: <span style={{ color: '#fff' }}>{dc.country}</span>
                                    </div>
                                )}
                                {outagesInCountry.length > 0 && (
                                    <div style={{ marginTop: 6, padding: '4px 8px', background: 'rgba(255,0,0,0.15)', border: '1px solid rgba(255,80,80,0.4)', borderRadius: 4, fontSize: 10, color: '#ff6b6b' }}>
                                        OUTAGE IN REGION — {outagesInCountry.map((o: any) => `${o.region_name} (${o.severity}%)`).join(', ')}
                                    </div>
                                )}
                                <div style={{ marginTop: 6, fontSize: 9, color: '#7c3aed', letterSpacing: '0.05em' }}>
                                    DATA CENTER
                                </div>
                            </div>
                        </Popup>
                    );
                })()}

                {
                    selectedEntity?.type === 'gdelt' && data?.gdelt?.[selectedEntity.id as number] && (
                        <Popup
                            longitude={data.gdelt[selectedEntity.id as number].geometry.coordinates[0]}
                            latitude={data.gdelt[selectedEntity.id as number].geometry.coordinates[1]}
                            closeButton={false}
                            closeOnClick={false}
                            onClose={() => onEntityClick?.(null)}
                            anchor="bottom"
                            offset={15}
                        >
                            <div className="bg-[var(--bg-secondary)]/90 backdrop-blur-md border border-orange-800 rounded-lg flex flex-col z-[100] font-mono shadow-[0_4px_30px_rgba(255,140,0,0.4)] pointer-events-auto overflow-hidden w-[300px]">
                                <div className="p-2 border-b border-orange-500/30 bg-orange-950/40 flex justify-between items-center">
                                    <h2 className="text-[10px] tracking-widest font-bold text-orange-400 flex items-center gap-1">
                                        <AlertTriangle size={12} className="text-orange-400" /> NEWS ON THE GROUND
                                    </h2>
                                    <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">✕</button>
                                </div>
                                <div className="p-3 flex flex-col gap-2">
                                    <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1">
                                        <span className="text-[var(--text-muted)] text-[9px]">LOCATION</span>
                                        <span className="text-white text-[10px] font-bold text-right ml-2 break-words max-w-[150px]">{data.gdelt[selectedEntity.id as number].properties?.name || 'UNKNOWN REGION'}</span>
                                    </div>
                                    <div className="flex flex-col gap-1 mt-1">
                                        <span className="text-[var(--text-muted)] text-[9px]">LATEST REPORTS: ({data.gdelt[selectedEntity.id as number].properties?.count || 1})</span>
                                        <div className="flex flex-col gap-2 max-h-[200px] overflow-y-auto styled-scrollbar mt-1">
                                            {(() => {
                                                const urls: string[] = data.gdelt[selectedEntity.id as number].properties?._urls_list || [];
                                                const headlines: string[] = data.gdelt[selectedEntity.id as number].properties?._headlines_list || [];
                                                if (urls.length === 0) return <span className="text-[var(--text-muted)] text-[10px]">No articles available.</span>;
                                                return urls.map((url: string, idx: number) => {
                                                    const headline = headlines[idx] || '';
                                                    let domain = '';
                                                    try { domain = new URL(url).hostname.replace('www.', ''); } catch { domain = ''; }
                                                    return (
                                                        <a
                                                            key={idx}
                                                            href={url}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            onClick={(e) => e.stopPropagation()}
                                                            className="block py-1.5 border-b border-[var(--border-primary)]/50 last:border-0 cursor-pointer group"
                                                            style={{ pointerEvents: 'all' }}
                                                        >
                                                            <span className="text-orange-400 text-[11px] font-bold leading-tight group-hover:text-orange-300 block">
                                                                {headline || domain || 'View Article'}
                                                            </span>
                                                            {headline && domain && (
                                                                <span className="text-[var(--text-muted)] text-[9px] block mt-0.5">{domain}</span>
                                                            )}
                                                        </a>
                                                    );
                                                });
                                            })()}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </Popup>
                    )
                }

                {
                    selectedEntity?.type === 'liveuamap' && data?.liveuamap?.find((l: any) => String(l.id) === String(selectedEntity.id)) && (() => {
                        const item = data.liveuamap.find((l: any) => String(l.id) === String(selectedEntity.id));
                        return (
                            <Popup
                                longitude={item.lng}
                                latitude={item.lat}
                                closeButton={false}
                                closeOnClick={false}
                                onClose={() => onEntityClick?.(null)}
                                anchor="bottom"
                                offset={15}
                            >
                                <div className="bg-[var(--bg-secondary)]/90 backdrop-blur-md border border-yellow-800 rounded-lg flex flex-col z-[100] font-mono shadow-[0_4px_30px_rgba(255,255,0,0.3)] pointer-events-auto overflow-hidden w-[280px]">
                                    <div className="p-2 border-b border-yellow-500/30 bg-yellow-950/40 flex justify-between items-center">
                                        <h2 className="text-[10px] tracking-widest font-bold text-yellow-400 flex items-center gap-1">
                                            <AlertTriangle size={12} className="text-yellow-400" /> REGIONAL TACTICAL EVENT
                                        </h2>
                                        <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">✕</button>
                                    </div>
                                    <div className="p-3 flex flex-col gap-2">
                                        <div className="flex flex-col gap-1 border-b border-[var(--border-primary)] pb-1">
                                            <span className="text-yellow-400 text-[10px] font-bold leading-tight">{item.title}</span>
                                        </div>
                                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1 mt-1">
                                            <span className="text-[var(--text-muted)] text-[9px]">TIME</span>
                                            <span className="text-white text-[9px] font-bold">{item.timestamp || 'UNKNOWN'}</span>
                                        </div>
                                        {item.link && (
                                            <div className="flex justify-between items-center mt-1">
                                                <a href={item.link} target="_blank" rel="noreferrer" className="text-yellow-400 hover:text-yellow-300 text-[9px] font-bold underline">
                                                    View Source Report
                                                </a>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </Popup>
                        );
                    })()
                }

                {
                    selectedEntity?.type === 'news' && data?.news?.[selectedEntity.id as number] && (() => {
                        const item = data.news[selectedEntity.id as number];
                        let threatColor = "text-yellow-400";
                        let borderColor = "border-yellow-800";
                        let bgHeaderColor = "bg-yellow-950/40";
                        let shadowColor = "rgba(255,255,0,0.3)";
                        if (item.risk_score >= 8) {
                            threatColor = "text-red-400";
                            borderColor = "border-red-800";
                            bgHeaderColor = "bg-red-950/40";
                            shadowColor = "rgba(255,0,0,0.3)";
                        } else if (item.risk_score <= 4) {
                            threatColor = "text-green-400";
                            borderColor = "border-green-800";
                            bgHeaderColor = "bg-green-950/40";
                            shadowColor = "rgba(0,255,0,0.3)";
                        }

                        if (!item || !item.coords) return null;

                        return (
                            <Popup
                                longitude={item.coords[1]}
                                latitude={item.coords[0]}
                                closeButton={false}
                                closeOnClick={false}
                                onClose={() => onEntityClick?.(null)}
                                anchor="bottom"
                                offset={25}
                            >
                                <div className={`bg-[var(--bg-secondary)]/90 backdrop-blur-md border ${borderColor} rounded-lg flex flex-col z-[100] font-mono shadow-[0_4px_30px_${shadowColor}] pointer-events-auto overflow-hidden w-[280px]`}>
                                    <div className={`p-2 border-b ${borderColor}/50 ${bgHeaderColor} flex justify-between items-center`}>
                                        <h2 className={`text-[10px] tracking-widest font-bold ${threatColor} flex items-center gap-1`}>
                                            <AlertTriangle size={12} className={threatColor} /> THREAT INTERCEPT
                                        </h2>
                                        <div className="flex items-center gap-2">
                                            <span className={`text-[10px] ${threatColor} font-mono font-bold animate-pulse`}>LVL: {item.risk_score}/10</span>
                                            <button onClick={() => onEntityClick?.(null)} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">✕</button>
                                        </div>
                                    </div>
                                    <div className="p-3 flex flex-col gap-2">
                                        <div className="flex flex-col gap-1 border-b border-[var(--border-primary)] pb-1">
                                            <span className={`text-[10px] font-bold leading-tight ${threatColor}`}>{item.title}</span>
                                        </div>
                                        <div className="flex justify-between items-center border-b border-[var(--border-primary)] pb-1 mt-1">
                                            <span className="text-[var(--text-muted)] text-[9px]">SOURCE</span>
                                            <span className="text-white text-[9px] font-bold text-right ml-2">{item.source || 'UNKNOWN'}</span>
                                        </div>
                                        {item.machine_assessment && (
                                            <div className="mt-1 p-2 bg-black/60 border border-cyan-800/50 rounded-sm text-[8px] text-cyan-400 font-mono leading-tight relative overflow-hidden shadow-[inset_0_0_10px_rgba(0,255,255,0.05)]">
                                                <div className="absolute top-0 left-0 w-[2px] h-full bg-cyan-500 animate-pulse"></div>
                                                <span className="font-bold text-white">&gt;_ SYS.ANALYSIS: </span>
                                                <span className="text-cyan-300 opacity-90">{item.machine_assessment}</span>
                                            </div>
                                        )}
                                        {item.link && (
                                            <div className="flex justify-between items-center mt-1">
                                                <a href={item.link} target="_blank" rel="noreferrer" className={`${threatColor} hover:text-red-300 text-[9px] font-bold underline`}>
                                                    View Details
                                                </a>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </Popup>
                        );
                    })()
                }

                {/* REGION DOSSIER — location pin on map (full intel shown in right panel) */}
                {selectedEntity?.type === 'region_dossier' && selectedEntity.extra && (
                    <Marker
                        longitude={selectedEntity.extra.lng}
                        latitude={selectedEntity.extra.lat}
                        anchor="bottom"
                        style={{ zIndex: 10 }}
                    >
                        <div className="flex flex-col items-center pointer-events-none">
                            {/* Pulsing ring */}
                            <div className="w-8 h-8 rounded-full border-2 border-emerald-500 animate-ping absolute opacity-30" />
                            {/* Pin dot */}
                            <div className="w-4 h-4 rounded-full bg-emerald-500 border-2 border-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.6)]" />
                            {/* Label */}
                            <div className="mt-2 bg-black/80 border border-emerald-800 rounded px-2 py-1 text-[9px] font-mono text-emerald-400 tracking-widest whitespace-nowrap shadow-[0_0_10px_rgba(16,185,129,0.3)]">
                                {regionDossierLoading ? 'COMPILING...' : '▶ INTEL TARGET'}
                            </div>
                        </div>
                    </Marker>
                )}

                {/* SENTINEL-2 IMAGERY — floating intel card on map near right-click */}
                {selectedEntity?.type === 'region_dossier' && selectedEntity.extra && regionDossier?.sentinel2 && !regionDossierLoading && (
                    <Popup
                        longitude={selectedEntity.extra.lng}
                        latitude={selectedEntity.extra.lat}
                        anchor="top-left"
                        offset={[20, -10]}
                        closeButton={false}
                        closeOnClick={false}
                        className="sentinel-popup"
                        maxWidth="320px"
                    >
                        <div className="bg-black/90 backdrop-blur-md border border-blue-500/50 rounded-lg overflow-hidden shadow-[0_0_25px_rgba(59,130,246,0.3)] pointer-events-auto" style={{ width: 300 }}>
                            {/* Header bar */}
                            <div className="flex items-center justify-between px-3 py-1.5 bg-blue-950/60 border-b border-blue-500/30">
                                <div className="flex items-center gap-2">
                                    <div className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                                    <span className="text-[9px] text-blue-400 font-mono tracking-[0.2em] font-bold">SENTINEL-2 IMAGERY</span>
                                </div>
                                <span className="text-[8px] text-blue-300/60 font-mono">{selectedEntity.extra.lat.toFixed(3)}, {selectedEntity.extra.lng.toFixed(3)}</span>
                            </div>

                            {regionDossier.sentinel2.found ? (
                                <>
                                    {/* Metadata row */}
                                    <div className="flex items-center justify-between px-3 py-1.5 text-[9px] font-mono border-b border-blue-900/40">
                                        <span className="text-blue-300">{regionDossier.sentinel2.platform}</span>
                                        <span className="text-cyan-400 font-bold">{regionDossier.sentinel2.datetime?.slice(0, 10)}</span>
                                        <span className="text-blue-300">{regionDossier.sentinel2.cloud_cover?.toFixed(0)}% cloud</span>
                                    </div>

                                    {/* Thumbnail */}
                                    {regionDossier.sentinel2.thumbnail_url ? (
                                        <a href={regionDossier.sentinel2.fullres_url || regionDossier.sentinel2.thumbnail_url} target="_blank" rel="noopener noreferrer">
                                            <img
                                                src={regionDossier.sentinel2.thumbnail_url}
                                                alt="Sentinel-2 scene"
                                                className="w-full block hover:brightness-110 transition-all cursor-pointer"
                                                style={{ maxHeight: 220, objectFit: 'cover' }}
                                            />
                                        </a>
                                    ) : (
                                        <div className="px-3 py-4 text-[9px] text-blue-300/50 font-mono text-center">Scene found — no preview available</div>
                                    )}

                                    {/* Footer */}
                                    <div className="px-3 py-1 bg-blue-950/40 text-[7px] text-blue-400/50 font-mono tracking-widest text-center">
                                        CLICK IMAGE TO OPEN FULL RESOLUTION
                                    </div>
                                </>
                            ) : (
                                <div className="px-3 py-4 text-[9px] text-blue-300/50 font-mono text-center">
                                    No clear imagery in last 30 days
                                </div>
                            )}
                        </div>
                    </Popup>
                )}

                {/* MEASUREMENT LINES */}
                {measurePoints && measurePoints.length >= 2 && (
                    <Source id="measure-lines" type="geojson" data={{
                        type: 'FeatureCollection',
                        features: [{
                            type: 'Feature',
                            properties: {},
                            geometry: {
                                type: 'LineString',
                                coordinates: measurePoints.map((p: any) => [p.lng, p.lat])
                            }
                        }]
                    } as any}>
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

                {/* MEASUREMENT WAYPOINTS */}
                {measurePoints && measurePoints.map((pt: any, idx: number) => (
                    <Marker key={`measure-${idx}`} longitude={pt.lng} latitude={pt.lat} anchor="center">
                        <div className="flex flex-col items-center pointer-events-none">
                            <div className="w-6 h-6 rounded-full border-2 border-cyan-400 animate-ping absolute opacity-20" />
                            <div className="w-4 h-4 rounded-full bg-cyan-500 border-2 border-cyan-300 shadow-[0_0_12px_rgba(0,255,255,0.6)] flex items-center justify-center">
                                <span className="text-[7px] font-mono font-bold text-black">{idx + 1}</span>
                            </div>
                        </div>
                    </Marker>
                ))}

            </Map>
        </div>
    );
}

import dynamic from "next/dynamic";

export default dynamic(() => Promise.resolve(MaplibreViewer), {
    ssr: false
});
