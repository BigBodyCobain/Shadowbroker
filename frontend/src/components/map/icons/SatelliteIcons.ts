// Satellite icon SVG builder and mission-type mappings
// Extracted from MaplibreViewer.tsx — pure data, no JSX

export const makeSatSvg = (color: string) => {
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

export const MISSION_COLORS: Record<string, string> = {
  military_recon: '#ff3333',
  military_sar: '#ff3333',
  sar: '#00e5ff',
  sigint: '#ffffff',
  navigation: '#4488ff',
  early_warning: '#ff00ff',
  commercial_imaging: '#44ff44',
  space_station: '#ffdd00',
};

/** Special ISS icon — larger with built-in golden dashed halo ring */
export const makeISSSvg = () => {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
    <circle cx="16" cy="16" r="14" fill="none" stroke="#ffdd00" stroke-width="1.5" stroke-dasharray="4 2" opacity="0.9"/>
    <rect x="13" y="13" width="6" height="6" rx="1" fill="#ffdd00" stroke="#0a0e1a" stroke-width="0.5"/>
    <rect x="3" y="14" width="9" height="4" rx="1" fill="#ffdd00" opacity="0.7" stroke="#0a0e1a" stroke-width="0.3"/>
    <rect x="20" y="14" width="9" height="4" rx="1" fill="#ffdd00" opacity="0.7" stroke="#0a0e1a" stroke-width="0.3"/>
    <line x1="12" y1="16" x2="3" y2="16" stroke="#ffdd00" stroke-width="0.8"/>
    <line x1="20" y1="16" x2="29" y2="16" stroke="#ffdd00" stroke-width="0.8"/>
    <circle cx="16" cy="16" r="1.5" fill="#fff" opacity="0.9"/>
  </svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
};

/** Train icon SVG — small locomotive shape */
export const makeTrainSvg = (color: string) => {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">
    <rect x="3" y="4" width="12" height="9" rx="2" fill="${color}" stroke="#0a0e1a" stroke-width="0.5"/>
    <rect x="5" y="6" width="3" height="2.5" rx="0.5" fill="#0a0e1a" opacity="0.5"/>
    <rect x="10" y="6" width="3" height="2.5" rx="0.5" fill="#0a0e1a" opacity="0.5"/>
    <circle cx="6" cy="14.5" r="1.3" fill="${color}" stroke="#0a0e1a" stroke-width="0.3"/>
    <circle cx="12" cy="14.5" r="1.3" fill="${color}" stroke="#0a0e1a" stroke-width="0.3"/>
    <line x1="9" y1="10" x2="9" y2="12" stroke="#fff" stroke-width="0.8" opacity="0.6"/>
  </svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
};

export const MISSION_ICON_MAP: Record<string, string> = {
  military_recon: 'sat-mil',
  military_sar: 'sat-mil',
  sar: 'sat-sar',
  sigint: 'sat-sigint',
  navigation: 'sat-nav',
  early_warning: 'sat-ew',
  commercial_imaging: 'sat-com',
  space_station: 'sat-station',
};
