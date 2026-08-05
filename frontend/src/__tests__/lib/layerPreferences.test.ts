import { afterEach, describe, expect, it } from 'vitest';
import {
  DASHBOARD_PREFS_STORAGE_KEY,
  LAYER_PREFERENCES_STORAGE_KEY,
  clearActiveLayersPreference,
  getDefaultActiveLayers,
  getDefaultLayerSectionExpanded,
  loadActiveFilters,
  loadActiveLayers,
  loadLayerSectionExpanded,
  loadMapStyle,
  mergeLayerSectionExpanded,
  saveActiveFilters,
  saveActiveLayers,
  saveLayerSectionExpanded,
  saveMapStyle,
} from '@/lib/layerPreferences';

describe('layerPreferences', () => {
  afterEach(() => {
    localStorage.removeItem(DASHBOARD_PREFS_STORAGE_KEY);
    localStorage.removeItem(LAYER_PREFERENCES_STORAGE_KEY);
  });

  it('getDefaultActiveLayers returns a full boolean map', () => {
    const defaults = getDefaultActiveLayers();
    expect(defaults.flights).toBe(true);
    expect(defaults.firms).toBe(false);
    expect(Object.values(defaults).every((value) => typeof value === 'boolean')).toBe(true);
  });

  it('saveActiveLayers persists and loadActiveLayers restores', () => {
    const customized = { ...getDefaultActiveLayers(), flights: false, cctv: true };
    saveActiveLayers(customized);
    expect(loadActiveLayers()).toEqual(customized);
  });

  it('migrates legacy sb_active_layers_v1 storage', () => {
    localStorage.setItem(
      LAYER_PREFERENCES_STORAGE_KEY,
      JSON.stringify({ version: 1, layers: { flights: false } }),
    );
    expect(loadActiveLayers().flights).toBe(false);
  });

  it('persists map style without clobbering layers', () => {
    saveActiveLayers({ ...getDefaultActiveLayers(), flights: false });
    saveMapStyle('SATELLITE');
    expect(loadMapStyle()).toBe('SATELLITE');
    expect(loadActiveLayers().flights).toBe(false);
  });

  it('persists active filters', () => {
    saveActiveFilters({ airline: ['UAL'], ship_type: ['Cargo'] });
    expect(loadActiveFilters()).toEqual({ airline: ['UAL'], ship_type: ['Cargo'] });
  });

  it('persists layer section expand/collapse by stable id', () => {
    const defaults = getDefaultLayerSectionExpanded();
    saveLayerSectionExpanded({ ...defaults, aircraft: true, overlays: false });
    expect(loadLayerSectionExpanded().aircraft).toBe(true);
    expect(loadLayerSectionExpanded().overlays).toBe(false);
  });

  it('mergeLayerSectionExpanded keeps defaults for unknown section ids', () => {
    const defaults = getDefaultLayerSectionExpanded();
    const merged = mergeLayerSectionExpanded(defaults, { aircraft: true });
    expect(merged.aircraft).toBe(true);
    expect(merged.maritime).toBe(defaults.maritime);
  });

  it('clearActiveLayersPreference removes only layers from dashboard prefs', () => {
    saveActiveLayers({ ...getDefaultActiveLayers(), flights: false });
    saveMapStyle('SATELLITE');
    clearActiveLayersPreference();
    expect(loadActiveLayers()).toEqual(getDefaultActiveLayers());
    expect(loadMapStyle()).toBe('SATELLITE');
  });
});
