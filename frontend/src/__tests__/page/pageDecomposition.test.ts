/**
 * Sprint 4B regression tests — page.tsx decomposition boundary checks.
 *
 * These tests validate the frozen contract for page.tsx decomposition:
 *  1. InfonetTerminal onClose still calls leaveWormhole when wormhole is ready/running
 *  2. Initial /api/layers sync does NOT dispatch LAYER_TOGGLE_EVENT on first mount
 *  3. launchMeshChatTab preserves atomic leftOpen + leftMeshExpanded + meshChatLaunchRequest
 *  4. LocateBar extracted to page-local module
 *  5. SentinelInfoModal extracted to page-local module
 *  6. page.tsx retains all frozen-contract orchestration items
 *  7. MeshChat and MaplibreViewer integration boundaries remain intact
 *  8. No admin-session or proxy regression introduced
 */
import { describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

const APP_DIR = path.resolve(__dirname, '../../app');

function readAppFile(name: string): string {
  return fs.readFileSync(path.join(APP_DIR, name), 'utf-8');
}

// ─── Extraction verification ────────────────────────────────────────────────

describe('page.tsx decomposition — extraction targets', () => {
  it('LocateBar is defined in its own page-local module', () => {
    const locateBar = readAppFile('LocateBar.tsx');
    expect(locateBar).toMatch(/export\s+function\s+LocateBar/);
    expect(locateBar).toContain('onLocate');
    expect(locateBar).toContain('onOpenChange');
  });

  it('SentinelInfoModal is defined in its own page-local module', () => {
    const modal = readAppFile('SentinelInfoModal.tsx');
    expect(modal).toMatch(/export\s+function\s+SentinelInfoModal/);
    expect(modal).toContain('onClose');
    expect(modal).toContain('SENTINEL HUB IMAGERY');
  });

  it('page.tsx imports LocateBar from page-local module', () => {
    const page = readAppFile('page.tsx');
    expect(page).toMatch(/import\s*\{.*LocateBar.*\}\s*from\s+['"]\.\/LocateBar['"]/);
  });

  it('page.tsx imports SentinelInfoModal from page-local module', () => {
    const page = readAppFile('page.tsx');
    expect(page).toMatch(/import\s*\{.*SentinelInfoModal.*\}\s*from\s+['"]\.\/SentinelInfoModal['"]/);
  });

  it('page.tsx no longer defines LocateBar inline', () => {
    const page = readAppFile('page.tsx');
    // Should not have the old inline function definition
    expect(page).not.toMatch(/^function\s+LocateBar\s*\(/m);
  });
});

// ─── InfonetTerminal onClose wormhole teardown ──────────────────────────────

describe('page.tsx decomposition — InfonetTerminal onClose wormhole teardown', () => {
  const page = readAppFile('page.tsx');

  it('InfonetTerminal onClose delegates to teardownWormholeOnClose', () => {
    const infonetSection = page.slice(
      page.indexOf('<InfonetTerminal'),
      page.indexOf('</InfonetTerminal>') !== -1
        ? page.indexOf('</InfonetTerminal>')
        : page.indexOf('/>', page.indexOf('<InfonetTerminal')) + 2,
    );
    expect(infonetSection).toContain('teardownWormholeOnClose');
    expect(infonetSection).toContain('fetchWormholeState');
    expect(infonetSection).toContain('leaveWormhole');
  });

  it('page.tsx imports teardownWormholeOnClose from wormholeTeardown', () => {
    expect(page).toMatch(
      /import\s*\{[^}]*teardownWormholeOnClose[^}]*\}\s*from\s+['"]@\/lib\/wormholeTeardown['"]/,
    );
  });

  it('page.tsx imports leaveWormhole and fetchWormholeState from wormholeClient', () => {
    expect(page).toMatch(
      /import\s*\{[^}]*leaveWormhole[^}]*\}\s*from\s+['"]@\/mesh\/wormholeClient['"]/,
    );
    expect(page).toMatch(
      /import\s*\{[^}]*fetchWormholeState[^}]*\}\s*from\s+['"]@\/mesh\/wormholeClient['"]/,
    );
  });
});

// ─── /api/layers sync: first mount vs later changes ─────────────────────────

describe('page.tsx decomposition — /api/layers sync behavior', () => {
  const page = readAppFile('page.tsx');

  it('uses initialLayerSyncRef to distinguish first sync from later changes', () => {
    expect(page).toContain('initialLayerSyncRef');
    // Check that initialLayerSyncRef is created as a ref
    expect(page).toMatch(/initialLayerSyncRef\s*=\s*useRef\s*\(\s*false\s*\)/);
  });

  it('first mount sync passes false to triggerRefetch (no LAYER_TOGGLE_EVENT)', () => {
    // The code checks if initialLayerSyncRef.current is false, then calls syncLayers(false)
    expect(page).toMatch(/if\s*\(\s*!initialLayerSyncRef\.current\s*\)/);
    // After the check, it sets the ref to true and calls with false
    expect(page).toContain('syncLayers(false)');
  });

  it('subsequent changes dispatch LAYER_TOGGLE_EVENT via syncLayers(true)', () => {
    expect(page).toContain('syncLayers(true)');
  });

  it('LAYER_TOGGLE_EVENT is imported and dispatched inside syncLayers when triggerRefetch=true', () => {
    expect(page).toMatch(/import\s*\{[^}]*LAYER_TOGGLE_EVENT[^}]*\}/);
    expect(page).toMatch(/LAYER_TOGGLE_EVENT/);
    // dispatched conditionally on triggerRefetch
    expect(page).toMatch(/if\s*\(\s*triggerRefetch\s*\)/);
    expect(page).toContain('new Event(LAYER_TOGGLE_EVENT)');
  });

  it('activeLayers state is defined in page.tsx (not moved to hook/context)', () => {
    expect(page).toMatch(/\[activeLayers,\s*setActiveLayers\]\s*=\s*useState/);
  });
});

// ─── launchMeshChatTab atomic update ────────────────────────────────────────

describe('page.tsx decomposition — launchMeshChatTab atomicity', () => {
  const page = readAppFile('page.tsx');

  it('launchMeshChatTab sets leftOpen to true', () => {
    // Extract the launchMeshChatTab definition
    const idx = page.indexOf('launchMeshChatTab');
    const block = page.slice(idx, idx + 300);
    expect(block).toContain('setLeftOpen(true)');
  });

  it('launchMeshChatTab sets leftMeshExpanded to true', () => {
    const idx = page.indexOf('launchMeshChatTab');
    const block = page.slice(idx, idx + 300);
    expect(block).toContain('setLeftMeshExpanded(true)');
  });

  it('launchMeshChatTab sets meshChatLaunchRequest with tab, gate, peerId, showSas, and nonce', () => {
    const idx = page.indexOf('launchMeshChatTab');
    const block = page.slice(idx, idx + 500);
    expect(block).toContain('setMeshChatLaunchRequest');
    expect(block).toMatch(/tab.*gate.*peerId.*showSas.*nonce|nonce.*Date\.now/);
  });
});

// ─── MeshChat and MaplibreViewer integration boundaries ─────────────────────

describe('page.tsx decomposition — child component integration', () => {
  const page = readAppFile('page.tsx');

  it('MeshChat receives onFlyTo, expanded, onExpandedChange, onSettingsClick, onTerminalToggle, launchRequest props', () => {
    const meshChatIdx = page.indexOf('<MeshChat');
    const meshChatBlock = page.slice(meshChatIdx, meshChatIdx + 500);
    expect(meshChatBlock).toContain('onFlyTo');
    expect(meshChatBlock).toContain('expanded=');
    expect(meshChatBlock).toContain('onExpandedChange');
    expect(meshChatBlock).toContain('onSettingsClick');
    expect(meshChatBlock).toContain('onTerminalToggle');
    expect(meshChatBlock).toContain('launchRequest');
  });

  it('MaplibreViewer receives activeLayers and viewBoundsRef props', () => {
    const mapIdx = page.indexOf('<MaplibreViewer');
    const mapBlock = page.slice(mapIdx, mapIdx + 1500);
    expect(mapBlock).toContain('activeLayers');
    expect(mapBlock).toContain('viewBoundsRef');
  });

  it('page.tsx imports MeshChat from @/components/MeshChat', () => {
    expect(page).toMatch(/import\s+MeshChat\s+from\s+['"]@\/components\/MeshChat['"]/);
  });

  it('page.tsx imports MaplibreViewer dynamically', () => {
    expect(page).toMatch(/dynamic\s*\(\s*\(\)\s*=>\s*import\s*\(\s*['"]@\/components\/MaplibreViewer['"]\s*\)/);
  });
});

// ─── No admin-session or proxy regression ───────────────────────────────────

describe('page.tsx decomposition — no admin-session/proxy regression', () => {
  const page = readAppFile('page.tsx');

  it('page.tsx still uses useDataPolling at top level', () => {
    expect(page).toMatch(/useDataPolling\s*\(\s*\)/);
  });

  it('page.tsx still uses useBackendStatus', () => {
    expect(page).toContain('useBackendStatus');
  });

  it('page.tsx does not import admin session utilities directly (they stay in hooks)', () => {
    // Admin session handling is in useDataPolling and backend hooks, not page.tsx
    expect(page).not.toMatch(/adminSession|admin_session/i);
  });

  it('LocateBar uses backend proxy for geocoding (not direct-only)', () => {
    const locateBar = readAppFile('LocateBar.tsx');
    expect(locateBar).toContain('API_BASE');
    expect(locateBar).toContain('/api/geocode/search');
  });
});

// ─── page.tsx retains all frozen-contract orchestration ─────────────────────

describe('page.tsx decomposition — retained orchestration', () => {
  const page = readAppFile('page.tsx');

  it('page.tsx retains cycleStyle with atomic activeStyle + highres_satellite update', () => {
    expect(page).toMatch(/cycleStyle/);
    const idx = page.indexOf('cycleStyle');
    const block = page.slice(idx, idx + 300);
    expect(block).toContain('setActiveStyle');
    expect(block).toContain('highres_satellite');
  });

  it('page.tsx retains viewBoundsRef', () => {
    expect(page).toMatch(/viewBoundsRef\s*=\s*useRef/);
  });

  it('page.tsx retains SSR-safe localStorage hydration', () => {
    expect(page).toContain('localStorage.getItem');
    expect(page).toContain('sb_left_open');
    expect(page).toContain('sb_right_open');
  });

  it('page.tsx retains infonetOpen state', () => {
    expect(page).toMatch(/\[infonetOpen,\s*setInfonetOpen\]\s*=\s*useState/);
  });
});
