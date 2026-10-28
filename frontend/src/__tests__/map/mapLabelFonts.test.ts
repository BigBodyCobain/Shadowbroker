/**
 * Regression: every overlay label layer must pin an explicit `text-font`.
 *
 * Without one, MapLibre falls back to "Open Sans Regular,Arial Unicode MS Regular",
 * which the keyless OpenFreeMap glyph endpoint does not serve (HTTP 404). The failed
 * glyph request errors every tile of the layer's source, so the whole source stops
 * rendering — e.g. the CCTV cluster count took the CCTV circles down with it.
 */
import { describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

const VIEWER = path.resolve(__dirname, '../../components/MaplibreViewer.tsx');

function layoutBlocks(source: string): { line: number; body: string }[] {
  const blocks: { line: number; body: string }[] = [];
  const marker = 'layout={{';
  let start = source.indexOf(marker);
  while (start !== -1) {
    let depth = 2;
    let i = start + marker.length;
    while (depth > 0 && i < source.length) {
      if (source[i] === '{') depth += 1;
      else if (source[i] === '}') depth -= 1;
      i += 1;
    }
    blocks.push({
      line: source.slice(0, start).split('\n').length,
      body: source.slice(start + marker.length, i),
    });
    start = source.indexOf(marker, i);
  }
  return blocks;
}

describe('MaplibreViewer label layers', () => {
  it('pin a text-font on every layout that renders text', () => {
    const source = fs.readFileSync(VIEWER, 'utf-8');
    const missing = layoutBlocks(source)
      .filter((b) => b.body.includes("'text-field'") && !b.body.includes("'text-font'"))
      .map((b) => `MaplibreViewer.tsx:${b.line}`);
    expect(missing).toEqual([]);
  });
});
