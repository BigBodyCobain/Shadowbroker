import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { join } from 'path';

const viewer = readFileSync(
  join(process.cwd(), 'src/components/MaplibreViewer.tsx'),
  'utf8',
);

describe('MaplibreViewer bounds camera', () => {
  it('derives zoom from bounds via cameraForBounds', () => {
    expect(viewer).toContain('cameraForBounds');
  });

  it('caps the fit, because a tiny bounds otherwise flies to maxZoom 22', () => {
    expect(viewer).toMatch(/maxZoom:\s*ZOOM_MAX/);
  });

  it('handles cameraForBounds returning undefined on oversized padding', () => {
    expect(viewer).toContain('ZOOM_FALLBACK');
  });

  it('leaves the agent fly-to path untouched', () => {
    expect(viewer).toContain('zoom: flyToLocation.zoom ?? 8,');
  });
});
