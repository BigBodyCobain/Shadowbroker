/**
 * Sprint 4C regression tests — MaplibreViewer decomposition boundary checks.
 *
 * These tests validate the frozen contract for MaplibreViewer decomposition:
 *  1. CctvFullscreenModal extracted to MaplibreViewer-local module
 *  2. Popup components extracted to MaplibreViewer/popups/
 *  3. CCTV proxy URL construction stays in MaplibreViewer (not in CctvFullscreenModal)
 *  4. Popup components receive explicit props (not parent-scope captures)
 *  5. Selection/dismissal: entity click → onClose dispatches onEntityClick(null)
 *  6. MaplibreViewer retains <Map>, mapRef, useImperativeSource, Source/Layer, useViewportBounds
 *  7. No keyed subscription regression (useDataKeys, not useDataSnapshot)
 *  8. No mega-hook extraction (no useMapController)
 */
import { describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

const COMP_DIR = path.resolve(__dirname, '../../components');

function readComp(name: string): string {
  return fs.readFileSync(path.join(COMP_DIR, name), 'utf-8');
}

// ─── CctvFullscreenModal extraction ────────────────────────────────────────

describe('MaplibreViewer decomposition — CctvFullscreenModal extraction', () => {
  it('CctvFullscreenModal is defined in its own MaplibreViewer-local module', () => {
    const modal = readComp('MaplibreViewer/CctvFullscreenModal.tsx');
    expect(modal).toMatch(/export\s+function\s+CctvFullscreenModal/);
    expect(modal).toContain('onClose');
  });

  it('CctvFullscreenModal exports CctvFullscreenModalProps interface', () => {
    const modal = readComp('MaplibreViewer/CctvFullscreenModal.tsx');
    expect(modal).toMatch(/export\s+interface\s+CctvFullscreenModalProps/);
    expect(modal).toContain('url: string');
    expect(modal).toContain('mediaType: string');
    expect(modal).toContain('isVideo: boolean');
    expect(modal).toContain('cameraName: string');
    expect(modal).toContain('sourceAgency: string');
    expect(modal).toContain('cameraId: string');
  });

  it('MaplibreViewer imports CctvFullscreenModal from extracted module', () => {
    const viewer = readComp('MaplibreViewer.tsx');
    expect(viewer).toMatch(
      /import\s*\{.*CctvFullscreenModal.*\}\s*from\s+['"]@\/components\/MaplibreViewer\/CctvFullscreenModal['"]/,
    );
  });

  it('MaplibreViewer no longer defines CctvFullscreenModal inline', () => {
    const viewer = readComp('MaplibreViewer.tsx');
    expect(viewer).not.toMatch(/^function\s+CctvFullscreenModal\s*\(/m);
  });

  it('CctvFullscreenModal does NOT contain proxy URL logic (stays in MaplibreViewer)', () => {
    const modal = readComp('MaplibreViewer/CctvFullscreenModal.tsx');
    // Proxy construction (/api/cctv/media?url=) must stay in MaplibreViewer
    expect(modal).not.toContain('/api/cctv/media');
    expect(modal).not.toContain('encodeURIComponent');
  });
});

// ─── CCTV proxy URL behavior ───────────────────────────────────────────────

describe('MaplibreViewer decomposition — CCTV proxy URL behavior', () => {
  const viewer = readComp('MaplibreViewer.tsx');

  it('CCTV section delegates proxy URL construction to buildCctvProxyUrl', () => {
    expect(viewer).toContain('buildCctvProxyUrl(rawUrl)');
    expect(viewer).toMatch(
      /import\s*\{[^}]*buildCctvProxyUrl[^}]*\}\s*from\s+['"]@\/lib\/cctvProxy['"]/,
    );
  });

  it('CCTV section passes proxied URL to CctvFullscreenModal', () => {
    // The pattern: url={url} where url is the proxied URL
    const cctvSection = viewer.slice(
      viewer.indexOf("selectedEntity?.type === 'cctv'"),
      viewer.indexOf('</CctvFullscreenModal>') !== -1
        ? viewer.indexOf('</CctvFullscreenModal>')
        : viewer.indexOf('/>', viewer.indexOf('<CctvFullscreenModal')) + 2,
    );
    expect(cctvSection).toContain('<CctvFullscreenModal');
    expect(cctvSection).toContain('url={url}');
  });
});

// ─── Popup explicit props ──────────────────────────────────────────────────

describe('MaplibreViewer decomposition — popup explicit props', () => {
  it('SatellitePopup receives sat and onClose props', () => {
    const popup = readComp('MaplibreViewer/popups/SatellitePopup.tsx');
    expect(popup).toMatch(/export\s+interface\s+SatellitePopupProps/);
    expect(popup).toContain('sat: Satellite');
    expect(popup).toContain('onClose: () => void');
  });

  it('ShipPopup receives ship, longitude, latitude, onClose props', () => {
    const popup = readComp('MaplibreViewer/popups/ShipPopup.tsx');
    expect(popup).toMatch(/export\s+interface\s+ShipPopupProps/);
    expect(popup).toContain('ship: Ship');
    expect(popup).toContain('longitude: number');
    expect(popup).toContain('latitude: number');
    expect(popup).toContain('onClose: () => void');
  });

  it('SigintPopup receives data, lat, lng, kiwisdrs, setTrackedSdr, onClose props', () => {
    const popup = readComp('MaplibreViewer/popups/SigintPopup.tsx');
    expect(popup).toMatch(/export\s+interface\s+SigintPopupProps/);
    expect(popup).toContain('data: SigintData');
    expect(popup).toContain('lat: number');
    expect(popup).toContain('lng: number');
    expect(popup).toContain('kiwisdrs: KiwiSDR[]');
    expect(popup).toContain('setTrackedSdr');
    expect(popup).toContain('onClose: () => void');
  });

  it('MilitaryBasePopup receives base, oracleIntel, onClose props', () => {
    const popup = readComp('MaplibreViewer/popups/MilitaryBasePopup.tsx');
    expect(popup).toMatch(/export\s+interface\s+MilitaryBasePopupProps/);
    expect(popup).toContain('base: MilitaryBase');
    expect(popup).toContain('oracleIntel');
    expect(popup).toContain('onClose: () => void');
  });

  it('RegionDossierPanel receives sentinel2, lat, lng, onClose props', () => {
    const popup = readComp('MaplibreViewer/popups/RegionDossierPanel.tsx');
    expect(popup).toMatch(/export\s+interface\s+RegionDossierPanelProps/);
    expect(popup).toContain('sentinel2: Sentinel2Data');
    expect(popup).toContain('lat: number');
    expect(popup).toContain('lng: number');
    expect(popup).toContain('onClose: () => void');
  });

  it('SigintPopup imports SigintSendForm and MeshtasticChannelFeed from SigintPanels', () => {
    const popup = readComp('MaplibreViewer/popups/SigintPopup.tsx');
    expect(popup).toMatch(
      /import\s*\{[^}]*SigintSendForm[^}]*\}\s*from\s+['"]@\/components\/map\/panels\/SigintPanels['"]/,
    );
    expect(popup).toMatch(
      /import\s*\{[^}]*MeshtasticChannelFeed[^}]*\}\s*from\s+['"]@\/components\/map\/panels\/SigintPanels['"]/,
    );
  });

  it('SigintPopup computes nearestSdr internally (not passed from parent)', () => {
    const popup = readComp('MaplibreViewer/popups/SigintPopup.tsx');
    expect(popup).toContain('findNearestSdr');
  });
});

// ─── Selection / dismissal behavior ────────────────────────────────────────

describe('MaplibreViewer decomposition — selection and dismissal', () => {
  const viewer = readComp('MaplibreViewer.tsx');

  it('satellite popup calls onEntityClick(null) on close', () => {
    const satSection = viewer.slice(
      viewer.indexOf("selectedEntity?.type === 'satellite'"),
      viewer.indexOf("selectedEntity?.type === 'satellite'") + 500,
    );
    expect(satSection).toContain('<SatellitePopup');
    expect(satSection).toContain('onClose={() => onEntityClick?.(null)}');
  });

  it('ship popup calls onEntityClick(null) on close', () => {
    const shipSection = viewer.slice(
      viewer.indexOf('{/* Ship / carrier click popup */}'),
      viewer.indexOf('{/* Ship / carrier click popup */}') + 800,
    );
    expect(shipSection).toContain('<ShipPopup');
    expect(shipSection).toContain('onClose={() => onEntityClick?.(null)}');
  });

  it('sigint popup calls onEntityClick(null) on close', () => {
    const sigintSection = viewer.slice(
      viewer.indexOf('{/* SIGINT signal click popup */}'),
      viewer.indexOf('{/* SIGINT signal click popup */}') + 1200,
    );
    expect(sigintSection).toContain('<SigintPopup');
    expect(sigintSection).toContain('onClose={() => onEntityClick?.(null)}');
  });

  it('military base popup calls onEntityClick(null) on close', () => {
    const milSection = viewer.slice(
      viewer.indexOf("selectedEntity?.type === 'military_base'"),
      viewer.indexOf("selectedEntity?.type === 'military_base'") + 600,
    );
    expect(milSection).toContain('<MilitaryBasePopup');
    expect(milSection).toContain('onClose={() => onEntityClick?.(null)}');
  });

  it('region dossier panel calls onEntityClick(null) on close', () => {
    const rdSection = viewer.slice(
      viewer.indexOf('{/* SENTINEL-2 IMAGERY'),
      viewer.indexOf('{/* SENTINEL-2 IMAGERY') + 500,
    );
    expect(rdSection).toContain('<RegionDossierPanel');
    expect(rdSection).toContain('onClose={() => onEntityClick(null)}');
  });

  it('CCTV fullscreen modal calls onEntityClick(null) on close', () => {
    const cctvSection = viewer.slice(
      viewer.indexOf("selectedEntity?.type === 'cctv'"),
      viewer.indexOf("selectedEntity?.type === 'cctv'") + 1600,
    );
    expect(cctvSection).toContain('<CctvFullscreenModal');
    expect(cctvSection).toContain('onClose={() => onEntityClick(null)}');
  });
});

// ─── MaplibreViewer retains core responsibilities ──────────────────────────

describe('MaplibreViewer decomposition — retained core', () => {
  const viewer = readComp('MaplibreViewer.tsx');

  it('MaplibreViewer retains <Map> component', () => {
    expect(viewer).toContain('<Map');
    expect(viewer).toContain('</Map>');
  });

  it('MaplibreViewer retains mapRef', () => {
    expect(viewer).toMatch(/mapRef\s*=\s*useRef/);
  });

  it('MaplibreViewer retains mapInitRef', () => {
    expect(viewer).toMatch(/mapInitRef\s*=\s*useRef/);
  });

  it('MaplibreViewer retains initializeMap', () => {
    expect(viewer).toContain('initializeMap');
  });

  it('MaplibreViewer retains useImperativeSource calls', () => {
    expect(viewer).toContain('useImperativeSource');
  });

  it('MaplibreViewer retains Source and Layer declarations', () => {
    expect(viewer).toContain('<Source');
    expect(viewer).toContain('<Layer');
  });

  it('MaplibreViewer retains useViewportBounds', () => {
    expect(viewer).toContain('useViewportBounds');
  });

  it('MaplibreViewer retains activeInteractiveLayerIds', () => {
    expect(viewer).toContain('activeInteractiveLayerIds');
  });

  it('MaplibreViewer retains worker hooks', () => {
    expect(viewer).toContain('useDynamicMapLayersWorker');
    expect(viewer).toContain('useStaticMapLayersWorker');
  });
});

// ─── No keyed subscription regression ──────────────────────────────────────

describe('MaplibreViewer decomposition — no keyed subscription regression', () => {
  const viewer = readComp('MaplibreViewer.tsx');

  it('MaplibreViewer uses useDataKeys (keyed subscription model)', () => {
    expect(viewer).toContain('useDataKeys');
  });

  it('MaplibreViewer does NOT use useDataSnapshot', () => {
    expect(viewer).not.toContain('useDataSnapshot');
  });

  it('MaplibreViewer imports useDataKeys from @/hooks/useDataStore', () => {
    expect(viewer).toMatch(
      /import\s*\{[^}]*useDataKeys[^}]*\}\s*from\s+['"]@\/hooks\/useDataStore['"]/,
    );
  });
});

// ─── No mega-hook extraction ───────────────────────────────────────────────

describe('MaplibreViewer decomposition — no mega-hook', () => {
  it('no useMapController hook exists', () => {
    const viewerDir = path.join(COMP_DIR, 'MaplibreViewer');
    const files = fs.readdirSync(viewerDir, { recursive: true }) as string[];
    const hookFiles = files.filter(
      (f: string) => f.includes('useMapController') || f.includes('use-map-controller'),
    );
    expect(hookFiles).toHaveLength(0);
  });

  it('MaplibreViewer does not import useMapController', () => {
    const viewer = readComp('MaplibreViewer.tsx');
    expect(viewer).not.toContain('useMapController');
  });
});

// ─── Popup components use Popup from react-map-gl ──────────────────────────

describe('MaplibreViewer decomposition — popup components own their Popup wrapper', () => {
  const popupFiles = [
    'MaplibreViewer/popups/SatellitePopup.tsx',
    'MaplibreViewer/popups/ShipPopup.tsx',
    'MaplibreViewer/popups/SigintPopup.tsx',
    'MaplibreViewer/popups/MilitaryBasePopup.tsx',
  ];

  for (const file of popupFiles) {
    const name = path.basename(file, '.tsx');
    it(`${name} imports Popup from react-map-gl/maplibre`, () => {
      const content = readComp(file);
      expect(content).toMatch(
        /import\s*\{[^}]*Popup[^}]*\}\s*from\s+['"]react-map-gl\/maplibre['"]/,
      );
    });

    it(`${name} renders a <Popup> component`, () => {
      const content = readComp(file);
      expect(content).toContain('<Popup');
    });
  }

  it('RegionDossierPanel renders a fixed overlay (not a map Popup)', () => {
    const content = readComp('MaplibreViewer/popups/RegionDossierPanel.tsx');
    expect(content).not.toContain('<Popup');
    expect(content).toContain("position: 'fixed'");
  });

  it('CctvFullscreenModal renders a fixed overlay (not a map Popup)', () => {
    const content = readComp('MaplibreViewer/CctvFullscreenModal.tsx');
    expect(content).not.toContain('<Popup');
    expect(content).toContain("position: 'fixed'");
  });
});

// ─── Data lookups stay in MaplibreViewer ────────────────────────────────────

describe('MaplibreViewer decomposition — data lookups in parent', () => {
  it('satellite lookup stays in MaplibreViewer', () => {
    const viewer = readComp('MaplibreViewer.tsx');
    expect(viewer).toContain("data?.satellites?.find");
  });

  it('ship lookup stays in MaplibreViewer', () => {
    const viewer = readComp('MaplibreViewer.tsx');
    expect(viewer).toContain("data?.ships?.find");
  });

  it('sigint lookup stays in MaplibreViewer', () => {
    const viewer = readComp('MaplibreViewer.tsx');
    expect(viewer).toContain("data?.sigint?.find");
  });

  it('military_bases lookup stays in MaplibreViewer', () => {
    const viewer = readComp('MaplibreViewer.tsx');
    expect(viewer).toContain("data?.military_bases?.find");
  });

  it('popup components do NOT access data store directly', () => {
    const popupFiles = [
      'MaplibreViewer/popups/SatellitePopup.tsx',
      'MaplibreViewer/popups/ShipPopup.tsx',
      'MaplibreViewer/popups/SigintPopup.tsx',
      'MaplibreViewer/popups/MilitaryBasePopup.tsx',
      'MaplibreViewer/popups/RegionDossierPanel.tsx',
    ];
    for (const file of popupFiles) {
      const content = readComp(file);
      expect(content).not.toContain('useDataKeys');
      expect(content).not.toContain('useDataSnapshot');
      expect(content).not.toContain('useDataStore');
    }
  });
});
