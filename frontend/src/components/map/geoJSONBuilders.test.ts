import { describe, it, expect } from 'vitest';
import {
  buildEarthquakesGeoJSON,
  buildFirmsGeoJSON,
  buildShipsGeoJSON,
  buildCarriersGeoJSON,
} from '@/components/map/geoJSONBuilders';
import type {
  Earthquake,
  FireHotspot,
  Ship,
  ActiveLayers,
} from '@/types/dashboard';

// Default active layers for ship tests
const allShipLayers: ActiveLayers = {
  flights: true,
  private: true,
  jets: true,
  military: true,
  tracked: true,
  satellites: true,
  earthquakes: true,
  cctv: false,
  ukraine_frontline: true,
  global_incidents: true,
  firms_fires: true,
  jamming: true,
  internet_outages: true,
  datacenters: true,
  gdelt: false,
  liveuamap: true,
  weather: true,
  uav: true,
  kiwisdr: false,
  ships_military: true,
  ships_cargo: true,
  ships_civilian: true,
  ships_passenger: true,
  ships_tracked_yachts: true,
};

describe('buildEarthquakesGeoJSON', () => {
  it('returns null for empty array', () => {
    expect(buildEarthquakesGeoJSON([])).toBeNull();
  });

  it('returns null for undefined', () => {
    expect(buildEarthquakesGeoJSON(undefined)).toBeNull();
  });

  it('builds valid FeatureCollection', () => {
    const quakes: Earthquake[] = [
      { id: 'eq1', mag: 5.2, lat: 35.0, lng: 139.0, place: 'Japan' },
      { id: 'eq2', mag: 3.1, lat: 40.0, lng: -74.0, place: 'New York' },
    ];
    const result = buildEarthquakesGeoJSON(quakes);
    expect(result).not.toBeNull();
    expect(result!.type).toBe('FeatureCollection');
    expect(result!.features).toHaveLength(2);
    expect(result!.features[0].properties?.type).toBe('earthquake');
    expect(result!.features[0].geometry).toEqual({ type: 'Point', coordinates: [139.0, 35.0] });
  });

  it('skips entries with null coordinates', () => {
    const quakes: Earthquake[] = [
      { id: 'eq1', mag: 5.2, lat: null as any, lng: 139.0, place: 'Bad' },
      { id: 'eq2', mag: 3.1, lat: 40.0, lng: -74.0, place: 'Good' },
    ];
    const result = buildEarthquakesGeoJSON(quakes);
    expect(result!.features).toHaveLength(1);
  });
});

describe('buildFirmsGeoJSON', () => {
  it('returns null for empty array', () => {
    expect(buildFirmsGeoJSON([])).toBeNull();
  });

  it('assigns correct icon by FRP intensity', () => {
    const fires: FireHotspot[] = [
      {
        lat: 10,
        lng: 20,
        frp: 2,
        brightness: 300,
        confidence: 'high',
        daynight: 'D',
        acq_date: '2025-01-01',
        acq_time: '1200',
      }, // yellow
      {
        lat: 10,
        lng: 21,
        frp: 10,
        brightness: 350,
        confidence: 'high',
        daynight: 'D',
        acq_date: '2025-01-01',
        acq_time: '1200',
      }, // orange
      {
        lat: 10,
        lng: 22,
        frp: 50,
        brightness: 400,
        confidence: 'high',
        daynight: 'N',
        acq_date: '2025-01-01',
        acq_time: '0000',
      }, // red
      {
        lat: 10,
        lng: 23,
        frp: 200,
        brightness: 500,
        confidence: 'high',
        daynight: 'N',
        acq_date: '2025-01-01',
        acq_time: '0000',
      }, // darkred
    ];
    const result = buildFirmsGeoJSON(fires)!;
    expect(result.features[0].properties?.iconId).toBe('fire-yellow');
    expect(result.features[1].properties?.iconId).toBe('fire-orange');
    expect(result.features[2].properties?.iconId).toBe('fire-red');
    expect(result.features[3].properties?.iconId).toBe('fire-darkred');
  });
});

describe('buildShipsGeoJSON', () => {
  const alwaysInView = () => true;
  const interpIdentity = (s: Ship): [number, number] => [s.lng!, s.lat!];

  it('returns null when all ship layers are off', () => {
    const layers = {
      ...allShipLayers,
      ships_military: false,
      ships_cargo: false,
      ships_civilian: false,
      ships_passenger: false,
      ships_tracked_yachts: false,
    };
    const ships: Ship[] = [{ name: 'Test', lat: 10, lng: 20, type: 'cargo' } as Ship];
    expect(buildShipsGeoJSON(ships, layers, alwaysInView, interpIdentity)).toBeNull();
  });

  it('filters out carriers (handled by buildCarriersGeoJSON)', () => {
    const ships: Ship[] = [
      { name: 'Cargo Ship', lat: 10, lng: 20, type: 'cargo', mmsi: '123' } as Ship,
      { name: 'USS Nimitz', lat: 30, lng: 40, type: 'carrier', mmsi: '456' } as Ship,
    ];
    const result = buildShipsGeoJSON(ships, allShipLayers, alwaysInView, interpIdentity);
    expect(result!.features).toHaveLength(1);
    expect(result!.features[0].properties?.name).toBe('Cargo Ship');
  });

  it('assigns correct icon by ship type', () => {
    const ships: Ship[] = [
      { name: 'Tanker', lat: 10, lng: 20, type: 'tanker', mmsi: '1' } as Ship,
      { name: 'Yacht', lat: 10, lng: 21, type: 'yacht', mmsi: '2' } as Ship,
      { name: 'Warship', lat: 10, lng: 22, type: 'military_vessel', mmsi: '3' } as Ship,
    ];
    const result = buildShipsGeoJSON(ships, allShipLayers, alwaysInView, interpIdentity)!;
    expect(result.features[0].properties?.iconId).toBe('svgShipRed');
    expect(result.features[1].properties?.iconId).toBe('svgShipWhite');
    expect(result.features[2].properties?.iconId).toBe('svgShipAmber');
  });
});

describe('buildCarriersGeoJSON', () => {
  it('returns null for empty ships', () => {
    expect(buildCarriersGeoJSON([])).toBeNull();
  });

  it('only includes carriers', () => {
    const ships: Ship[] = [
      { name: 'USS Nimitz', lat: 30, lng: 40, type: 'carrier', mmsi: '456', heading: 90 } as Ship,
      { name: 'Cargo Ship', lat: 10, lng: 20, type: 'cargo', mmsi: '123' } as Ship,
    ];
    const result = buildCarriersGeoJSON(ships)!;
    expect(result.features).toHaveLength(1);
    expect(result.features[0].properties?.name).toBe('USS Nimitz');
    expect(result.features[0].properties?.iconId).toBe('svgCarrier');
  });
});
