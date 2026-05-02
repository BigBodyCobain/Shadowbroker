/**
 * Sprint 4D behavioral tests — MaplibreViewer CCTV proxy, subscription isolation,
 * and parent-owned interpolation.
 *
 * These tests exercise actual runtime logic:
 *  1. buildCctvProxyUrl — proxy construction with various URL inputs
 *  2. Popup components do not own keyed subscriptions or map lifecycle
 *  3. Parent-owned interpolation: ShipPopup receives pre-interpolated coords
 */
import { describe, expect, it } from 'vitest';
import { buildCctvProxyUrl } from '@/lib/cctvProxy';
import * as fs from 'fs';
import * as path from 'path';

const POPUP_DIR = path.resolve(__dirname, '../../components/MaplibreViewer/popups');
const COMP_DIR = path.resolve(__dirname, '../../components');

function readPopup(name: string): string {
  return fs.readFileSync(path.join(POPUP_DIR, name), 'utf-8');
}

// ─── buildCctvProxyUrl runtime behavior ───────────────────────────────────

describe('MaplibreViewer behavior — buildCctvProxyUrl', () => {
  it('proxies http:// URLs through /api/cctv/media', () => {
    const result = buildCctvProxyUrl('http://example.com/stream.mjpg');
    expect(result).toBe('/api/cctv/media?url=http%3A%2F%2Fexample.com%2Fstream.mjpg');
  });

  it('proxies https:// URLs through /api/cctv/media', () => {
    const result = buildCctvProxyUrl('https://cdn.dot.gov/cam/42.m3u8');
    expect(result).toBe('/api/cctv/media?url=https%3A%2F%2Fcdn.dot.gov%2Fcam%2F42.m3u8');
  });

  it('passes through relative URLs unchanged', () => {
    expect(buildCctvProxyUrl('/local/stream.mp4')).toBe('/local/stream.mp4');
  });

  it('passes through empty string unchanged', () => {
    expect(buildCctvProxyUrl('')).toBe('');
  });

  it('passes through data: URIs unchanged', () => {
    expect(buildCctvProxyUrl('data:image/png;base64,abc')).toBe('data:image/png;base64,abc');
  });

  it('correctly encodes special characters in URLs', () => {
    const url = 'http://cam.example.com/view?id=42&token=a b';
    const result = buildCctvProxyUrl(url);
    expect(result).toContain('/api/cctv/media?url=');
    // Decode and verify roundtrip
    const encoded = result.replace('/api/cctv/media?url=', '');
    expect(decodeURIComponent(encoded)).toBe(url);
  });

  it('handles URLs with fragments and query params', () => {
    const url = 'https://cam.example.com/stream#t=0?quality=hd';
    const result = buildCctvProxyUrl(url);
    expect(result).toContain('/api/cctv/media?url=');
    const encoded = result.replace('/api/cctv/media?url=', '');
    expect(decodeURIComponent(encoded)).toBe(url);
  });
});

// ─── MaplibreViewer wiring — uses buildCctvProxyUrl ───────────────────────

describe('MaplibreViewer behavior — CCTV proxy wiring', () => {
  const viewer = fs.readFileSync(path.join(COMP_DIR, 'MaplibreViewer.tsx'), 'utf-8');

  it('MaplibreViewer calls buildCctvProxyUrl(rawUrl) in CCTV section', () => {
    expect(viewer).toContain('buildCctvProxyUrl(rawUrl)');
  });

  it('MaplibreViewer imports buildCctvProxyUrl from @/lib/cctvProxy', () => {
    expect(viewer).toMatch(
      /import\s*\{[^}]*buildCctvProxyUrl[^}]*\}\s*from\s+['"]@\/lib\/cctvProxy['"]/,
    );
  });

  it('CCTV proxy URL is assigned to `url` and passed to CctvFullscreenModal', () => {
    const cctvSection = viewer.slice(
      viewer.indexOf("selectedEntity?.type === 'cctv'"),
      viewer.indexOf("selectedEntity?.type === 'cctv'") + 1600,
    );
    expect(cctvSection).toContain('const url = buildCctvProxyUrl(rawUrl)');
    expect(cctvSection).toContain('url={url}');
    expect(cctvSection).toContain('<CctvFullscreenModal');
  });
});

// ─── Popup subscription isolation ─────────────────────────────────────────

describe('MaplibreViewer behavior — popup components have no keyed subscriptions', () => {
  const popupFiles = [
    'SatellitePopup.tsx',
    'ShipPopup.tsx',
    'SigintPopup.tsx',
    'MilitaryBasePopup.tsx',
    'RegionDossierPanel.tsx',
  ];

  const FORBIDDEN_HOOKS = [
    'useDataKeys',
    'useDataSnapshot',
    'useDataStore',
    'useImperativeSource',
    'useViewportBounds',
    'useInterpolation',
  ];

  for (const file of popupFiles) {
    const name = path.basename(file, '.tsx');
    it(`${name} does not import any data-store or map-lifecycle hooks`, () => {
      const content = readPopup(file);
      for (const hook of FORBIDDEN_HOOKS) {
        expect(content).not.toContain(hook);
      }
    });

    it(`${name} does not reference mapRef or mapInitRef`, () => {
      const content = readPopup(file);
      expect(content).not.toContain('mapRef');
      expect(content).not.toContain('mapInitRef');
    });
  }
});

// ─── Parent-owned interpolation for popup positions ───────────────────────

describe('MaplibreViewer behavior — parent-owned interpolation feeds popup coords', () => {
  const viewer = fs.readFileSync(path.join(COMP_DIR, 'MaplibreViewer.tsx'), 'utf-8');

  it('MaplibreViewer calls interpShip before passing coords to ShipPopup', () => {
    // Find the ship popup section
    const shipSection = viewer.slice(
      viewer.indexOf('{/* Ship / carrier click popup */}'),
      viewer.indexOf('{/* Ship / carrier click popup */}') + 800,
    );
    // interpShip must be called, and its result fed into ShipPopup props
    expect(shipSection).toContain('interpShip(ship)');
    expect(shipSection).toContain('longitude={iLng}');
    expect(shipSection).toContain('latitude={iLat}');
  });

  it('ShipPopup receives longitude and latitude as props (not computing them)', () => {
    const shipPopup = readPopup('ShipPopup.tsx');
    expect(shipPopup).toContain('longitude: number');
    expect(shipPopup).toContain('latitude: number');
    // Must NOT contain interpolation logic
    expect(shipPopup).not.toContain('interpolatePosition');
    expect(shipPopup).not.toContain('interpShip');
    expect(shipPopup).not.toContain('useInterpolation');
  });

  it('MaplibreViewer owns useInterpolation hook', () => {
    expect(viewer).toContain('useInterpolation');
    expect(viewer).toMatch(/interpShip/);
    expect(viewer).toMatch(/interpFlight/);
  });
});
