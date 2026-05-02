// UAP (UFO) and Wastewater SVG icon builders for MapLibre symbol layers

/**
 * Purple UFO silhouette — classic saucer shape with dome and glow.
 * 36×36 viewport for a "healthy sized" icon on the map.
 */
export const makeUfoSvg = (): string => {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 36 36">
    <!-- outer glow ring -->
    <ellipse cx="18" cy="22" rx="16" ry="7" fill="none" stroke="#c084fc" stroke-width="1" opacity="0.4"/>
    <!-- saucer body -->
    <ellipse cx="18" cy="22" rx="14" ry="5.5" fill="#7c3aed" stroke="#a855f7" stroke-width="1"/>
    <!-- dome -->
    <ellipse cx="18" cy="18" rx="7" ry="6" fill="#8b5cf6" stroke="#c084fc" stroke-width="0.8"/>
    <!-- dome highlight -->
    <ellipse cx="16" cy="16" rx="3" ry="2.5" fill="#c4b5fd" opacity="0.35"/>
    <!-- saucer lights -->
    <circle cx="7" cy="22" r="1.2" fill="#e9d5ff" opacity="0.9"/>
    <circle cx="13" cy="24" r="1.2" fill="#e9d5ff" opacity="0.9"/>
    <circle cx="18" cy="25" r="1.2" fill="#e9d5ff" opacity="0.9"/>
    <circle cx="23" cy="24" r="1.2" fill="#e9d5ff" opacity="0.9"/>
    <circle cx="29" cy="22" r="1.2" fill="#e9d5ff" opacity="0.9"/>
    <!-- bottom beam hint -->
    <line x1="15" y1="27" x2="13" y2="33" stroke="#c084fc" stroke-width="0.6" opacity="0.25"/>
    <line x1="18" y1="27" x2="18" y2="34" stroke="#c084fc" stroke-width="0.6" opacity="0.3"/>
    <line x1="21" y1="27" x2="23" y2="33" stroke="#c084fc" stroke-width="0.6" opacity="0.25"/>
  </svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
};

/**
 * Larger UFO for cluster icons — 80×80, bold and unmissable at continental zoom.
 */
export const makeUfoClusterSvg = (): string => {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 80 80">
    <!-- glow rings -->
    <circle cx="40" cy="40" r="38" fill="#7c3aed" opacity="0.2"/>
    <circle cx="40" cy="40" r="32" fill="#7c3aed" opacity="0.15"/>
    <!-- outer glow ring -->
    <ellipse cx="40" cy="46" rx="32" ry="13" fill="none" stroke="#c084fc" stroke-width="1.8" opacity="0.6"/>
    <!-- saucer body -->
    <ellipse cx="40" cy="46" rx="28" ry="10" fill="#7c3aed" stroke="#a855f7" stroke-width="1.8"/>
    <!-- dome -->
    <ellipse cx="40" cy="38" rx="14" ry="12" fill="#8b5cf6" stroke="#c084fc" stroke-width="1.2"/>
    <!-- dome highlight -->
    <ellipse cx="35" cy="34" rx="5" ry="4" fill="#c4b5fd" opacity="0.3"/>
    <!-- saucer lights -->
    <circle cx="16" cy="46" r="2.2" fill="#e9d5ff" opacity="0.95"/>
    <circle cx="26" cy="50" r="2.2" fill="#e9d5ff" opacity="0.95"/>
    <circle cx="40" cy="52" r="2.2" fill="#e9d5ff" opacity="0.95"/>
    <circle cx="54" cy="50" r="2.2" fill="#e9d5ff" opacity="0.95"/>
    <circle cx="64" cy="46" r="2.2" fill="#e9d5ff" opacity="0.95"/>
    <!-- bottom beam -->
    <line x1="34" y1="56" x2="30" y2="70" stroke="#c084fc" stroke-width="1.2" opacity="0.35"/>
    <line x1="40" y1="56" x2="40" y2="72" stroke="#c084fc" stroke-width="1.2" opacity="0.4"/>
    <line x1="46" y1="56" x2="50" y2="70" stroke="#c084fc" stroke-width="1.2" opacity="0.35"/>
  </svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
};

/**
 * Water droplet icon for wastewater plants.
 * @param fill — fill colour (#00e5ff for clean, #ff2222 for alert)
 * @param stroke — optional stroke override
 */
export const makeWaterDropSvg = (fill: string, stroke?: string): string => {
  const s = stroke || fill;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="24" viewBox="0 0 24 34">
    <!-- drop body -->
    <path d="M12,2 Q12,2 4,16 A10,10 0 0,0 20,16 Q12,2 12,2 Z"
          fill="${fill}" stroke="${s}" stroke-width="1.2" stroke-linejoin="round"/>
    <!-- inner highlight -->
    <path d="M12,5 Q12,5 6,16 A8,8 0 0,0 18,16 Q12,5 12,5 Z"
          fill="${fill}" opacity="0.5" stroke="none"/>
    <!-- shine -->
    <ellipse cx="9" cy="18" rx="2.5" ry="3.5" fill="white" opacity="0.18" transform="rotate(-15,9,18)"/>
  </svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
};

/**
 * Larger water droplet for cluster icons — 64×80, bold at continental zoom.
 * @param fill — fill colour
 */
export const makeWaterDropClusterSvg = (fill: string): string => {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="28" viewBox="0 0 64 80">
    <!-- glow -->
    <ellipse cx="32" cy="46" rx="28" ry="30" fill="${fill}" opacity="0.18"/>
    <!-- drop body -->
    <path d="M32,6 Q32,6 10,42 A24,24 0 0,0 54,42 Q32,6 32,6 Z"
          fill="${fill}" stroke="${fill}" stroke-width="2" stroke-linejoin="round"/>
    <!-- inner highlight -->
    <path d="M32,14 Q32,14 15,42 A19,19 0 0,0 49,42 Q32,14 32,14 Z"
          fill="${fill}" opacity="0.45" stroke="none"/>
    <!-- shine -->
    <ellipse cx="24" cy="46" rx="6" ry="9" fill="white" opacity="0.18" transform="rotate(-15,24,46)"/>
  </svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
};

// Keep old exports as aliases for backward compat with geoJSONBuilders icon names
export const makeWastewaterSvg = makeWaterDropSvg;
