import { describe, it, expect } from 'vitest';
import {
  buildEarthquakesGeoJSON,
  buildJammingGeoJSON,
  buildCctvGeoJSON,
  buildKiwisdrGeoJSON,
  buildFirmsGeoJSON,
  buildInternetOutagesGeoJSON,
  buildDataCentersGeoJSON,
  buildGdeltGeoJSON,
  buildLiveuaGeoJSON,
  buildFrontlineGeoJSON,
  buildScannerGeoJSON,
  buildMilitaryBasesGeoJSON,
  buildTrainsGeoJSON,
} from '@/components/map/geoJSONBuilders';
import type {
  Earthquake,
  GPSJammingZone,
  FireHotspot,
  InternetOutage,
  DataCenter,
  GDELTIncident,
  LiveUAmapIncident,
  CCTVCamera,
  KiwiSDR,
  Scanner,
  MilitaryBase,
  Train,
} from '@/types/dashboard';

// ─── Military Bases ────────────────────────────────────────────────────────

describe('buildMilitaryBasesGeoJSON', () => {
    it('returns null for empty/undefined input', () => {
        expect(buildMilitaryBasesGeoJSON(undefined)).toBeNull();
        expect(buildMilitaryBasesGeoJSON([])).toBeNull();
    });

    it('builds valid Feature for ASDF branch base', () => {
        const bases: MilitaryBase[] = [
            { name: 'Naha Air Base', country: 'Japan', operator: 'ASDF 9th Air Wing', branch: 'asdf', lat: 26.196, lng: 127.646 },
        ];
        const result = buildMilitaryBasesGeoJSON(bases);
        expect(result).not.toBeNull();
        expect(result!.type).toBe('FeatureCollection');
        expect(result!.features).toHaveLength(1);

        const f = result!.features[0];
        expect(f.geometry).toEqual({ type: 'Point', coordinates: [127.646, 26.196] });
        expect(f.properties?.type).toBe('military_base');
        expect(f.properties?.branch).toBe('asdf');
        expect(f.properties?.name).toBe('Naha Air Base');
    });
});

// ─── Earthquakes ────────────────────────────────────────────────────────────

describe('buildEarthquakesGeoJSON', () => {
  it('returns null for empty/undefined input', () => {
    expect(buildEarthquakesGeoJSON(undefined)).toBeNull();
    expect(buildEarthquakesGeoJSON([])).toBeNull();
  });

  it('builds valid FeatureCollection from earthquake data', () => {
    const earthquakes: Earthquake[] = [
      { id: 'eq1', mag: 5.2, lat: 35.0, lng: 139.0, place: 'Japan' },
      { id: 'eq2', mag: 3.1, lat: 40.0, lng: -120.0, place: 'California', title: 'Test Title' },
    ];
    const result = buildEarthquakesGeoJSON(earthquakes);
    expect(result).not.toBeNull();
    expect(result!.type).toBe('FeatureCollection');
    expect(result!.features).toHaveLength(2);

    const f0 = result!.features[0];
    expect(f0.geometry).toEqual({ type: 'Point', coordinates: [139.0, 35.0] });
    expect(f0.properties?.type).toBe('earthquake');
    expect(f0.properties?.name).toContain('M5.2');
    expect(f0.properties?.name).toContain('Japan');
  });

  it('filters out entries with null lat/lng', () => {
    const earthquakes = [
      { id: 'eq1', mag: 5.0, lat: null as any, lng: 10.0, place: 'X' },
      { id: 'eq2', mag: 3.0, lat: 20.0, lng: 30.0, place: 'Y' },
    ];
    const result = buildEarthquakesGeoJSON(earthquakes);
    expect(result!.features).toHaveLength(1);
  });

  it('includes title when present', () => {
    const earthquakes: Earthquake[] = [
      { id: 'eq1', mag: 4.0, lat: 10.0, lng: 20.0, place: 'Test', title: 'Big One' },
    ];
    const result = buildEarthquakesGeoJSON(earthquakes);
    expect(result!.features[0].properties?.title).toBe('Big One');
  });
});

// ─── GPS Jamming ────────────────────────────────────────────────────────────

describe('buildJammingGeoJSON', () => {
  it('returns null for empty input', () => {
    expect(buildJammingGeoJSON(undefined)).toBeNull();
    expect(buildJammingGeoJSON([])).toBeNull();
  });

  it('builds polygon features with correct opacity mapping', () => {
    const zones: GPSJammingZone[] = [
      { lat: 50, lng: 30, severity: 'high', ratio: 0.8, degraded: 100, total: 125 },
      { lat: 45, lng: 35, severity: 'medium', ratio: 0.5, degraded: 50, total: 100 },
      { lat: 40, lng: 25, severity: 'low', ratio: 0.2, degraded: 20, total: 100 },
    ];
    const result = buildJammingGeoJSON(zones);
    expect(result!.features).toHaveLength(3);
    expect(result!.features[0].properties?.opacity).toBe(0.45);
    expect(result!.features[1].properties?.opacity).toBe(0.3);
    expect(result!.features[2].properties?.opacity).toBe(0.18);
  });

  it('builds correct 1°×1° polygon geometry', () => {
    const zones: GPSJammingZone[] = [
      { lat: 50, lng: 30, severity: 'high', ratio: 0.8, degraded: 100, total: 125 },
    ];
    const result = buildJammingGeoJSON(zones);
    const geom = result!.features[0].geometry;
    expect(geom.type).toBe('Polygon');
    if (geom.type === 'Polygon') {
      const ring = geom.coordinates[0];
      expect(ring).toHaveLength(5); // Closed ring
      expect(ring[0]).toEqual([29.5, 49.5]);
      expect(ring[2]).toEqual([30.5, 50.5]);
    }
  });
});

// ─── CCTV ───────────────────────────────────────────────────────────────────

describe('buildCctvGeoJSON', () => {
  it('returns null for empty input', () => {
    expect(buildCctvGeoJSON(undefined)).toBeNull();
  });

  it('builds features from camera data', () => {
    const cameras: CCTVCamera[] = [
      { id: 'cam1', lat: 40.7, lon: -74.0, direction_facing: 'North', source_agency: 'DOT' },
    ];
    const result = buildCctvGeoJSON(cameras);
    expect(result!.features).toHaveLength(1);
    expect(result!.features[0].properties?.type).toBe('cctv');
    expect(result!.features[0].properties?.name).toBe('North');
  });

  it('respects inView filter', () => {
    const cameras: CCTVCamera[] = [
      { id: 'cam1', lat: 40.7, lon: -74.0 },
      { id: 'cam2', lat: 10.0, lon: 20.0 },
    ];
    const inView = (lat: number, _lng: number) => lat > 30;
    const result = buildCctvGeoJSON(cameras, inView);
    expect(result!.features).toHaveLength(1);
  });
});

// ─── KiwiSDR ────────────────────────────────────────────────────────────────

describe('buildKiwisdrGeoJSON', () => {
  it('returns null for empty input', () => {
    expect(buildKiwisdrGeoJSON(undefined)).toBeNull();
  });

  it('builds features with SDR properties', () => {
    const receivers: KiwiSDR[] = [
      {
        lat: 52.0,
        lon: 13.0,
        name: 'Berlin SDR',
        url: 'http://test.com',
        users: 3,
        users_max: 8,
        bands: 'HF',
        antenna: 'Long Wire',
        location: 'Berlin',
      },
    ];
    const result = buildKiwisdrGeoJSON(receivers);
    expect(result!.features).toHaveLength(1);
    expect(result!.features[0].properties?.name).toBe('Berlin SDR');
    expect(result!.features[0].properties?.users).toBe(3);
  });
});

// ─── FIRMS Fires ────────────────────────────────────────────────────────────

describe('buildFirmsGeoJSON', () => {
  it('returns null for empty input', () => {
    expect(buildFirmsGeoJSON(undefined)).toBeNull();
  });

  it('classifies fires by FRP thresholds', () => {
    const fires: FireHotspot[] = [
      {
        lat: 10,
        lng: 20,
        frp: 150,
        brightness: 400,
        confidence: 'high',
        daynight: 'D',
        acq_date: '2024-01-01',
        acq_time: '1200',
      },
      {
        lat: 11,
        lng: 21,
        frp: 50,
        brightness: 350,
        confidence: 'medium',
        daynight: 'N',
        acq_date: '2024-01-01',
        acq_time: '0100',
      },
      {
        lat: 12,
        lng: 22,
        frp: 10,
        brightness: 300,
        confidence: 'low',
        daynight: 'D',
        acq_date: '2024-01-01',
        acq_time: '1400',
      },
      {
        lat: 13,
        lng: 23,
        frp: 2,
        brightness: 250,
        confidence: 'low',
        daynight: 'D',
        acq_date: '2024-01-01',
        acq_time: '1500',
      },
    ];
    const result = buildFirmsGeoJSON(fires);
    expect(result!.features).toHaveLength(4);
    expect(result!.features[0].properties?.iconId).toBe('fire-darkred');
    expect(result!.features[1].properties?.iconId).toBe('fire-red');
    expect(result!.features[2].properties?.iconId).toBe('fire-orange');
    expect(result!.features[3].properties?.iconId).toBe('fire-yellow');
  });

  it('formats daynight correctly', () => {
    const fires: FireHotspot[] = [
      {
        lat: 10,
        lng: 20,
        frp: 5,
        brightness: 300,
        confidence: 'low',
        daynight: 'D',
        acq_date: '2024-01-01',
        acq_time: '1200',
      },
      {
        lat: 11,
        lng: 21,
        frp: 5,
        brightness: 300,
        confidence: 'low',
        daynight: 'N',
        acq_date: '2024-01-01',
        acq_time: '0100',
      },
    ];
    const result = buildFirmsGeoJSON(fires);
    expect(result!.features[0].properties?.daynight).toBe('Day');
    expect(result!.features[1].properties?.daynight).toBe('Night');
  });
});

// ─── Internet Outages ───────────────────────────────────────────────────────

describe('buildInternetOutagesGeoJSON', () => {
  it('returns null for empty input', () => {
    expect(buildInternetOutagesGeoJSON(undefined)).toBeNull();
  });

  it('builds features with detail string', () => {
    const outages: InternetOutage[] = [
      {
        region_code: 'TX',
        region_name: 'Texas',
        country_code: 'US',
        country_name: 'United States',
        lat: 31.0,
        lng: -100.0,
        severity: 45,
        level: 'region',
        datasource: 'bgp',
      },
    ];
    const result = buildInternetOutagesGeoJSON(outages);
    expect(result!.features).toHaveLength(1);
    expect(result!.features[0].properties?.detail).toContain('Texas');
    expect(result!.features[0].properties?.detail).toContain('45% drop');
  });

  it('filters out entries with null coordinates', () => {
    const outages: InternetOutage[] = [
      {
        region_code: 'TX',
        region_name: 'Texas',
        country_code: 'US',
        country_name: 'United States',
        lat: null as any,
        lng: null as any,
        severity: 20,
        level: 'region',
        datasource: 'bgp',
      },
      {
        region_code: 'CA',
        region_name: 'California',
        country_code: 'US',
        country_name: 'United States',
        lat: 37.0,
        lng: -122.0,
        severity: 30,
        level: 'region',
        datasource: 'bgp',
      },
    ];
    const result = buildInternetOutagesGeoJSON(outages);
    expect(result!.features).toHaveLength(1);
  });
});

// ─── Data Centers ───────────────────────────────────────────────────────────

describe('buildDataCentersGeoJSON', () => {
  it('returns null for empty input', () => {
    expect(buildDataCentersGeoJSON(undefined)).toBeNull();
  });

  it('builds features with datacenter properties', () => {
    const dcs: DataCenter[] = [
      {
        lat: 40.0,
        lng: -74.0,
        name: 'NYC-DC1',
        company: 'Equinix',
        street: '123 Main',
        city: 'New York',
        country: 'US',
        zip: '10001',
      },
    ];
    const result = buildDataCentersGeoJSON(dcs);
    expect(result!.features).toHaveLength(1);
    expect(result!.features[0].properties?.id).toBe('dc-0');
    expect(result!.features[0].properties?.company).toBe('Equinix');
  });
});

// ─── GDELT ──────────────────────────────────────────────────────────────────

describe('buildGdeltGeoJSON', () => {
  it('returns null for empty input', () => {
    expect(buildGdeltGeoJSON(undefined)).toBeNull();
  });

  it('builds features from GDELT incidents', () => {
    const gdelt: GDELTIncident[] = [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [30, 50] },
        properties: { name: 'Protest', count: 5, _urls_list: [], _headlines_list: [] },
      },
    ];
    const result = buildGdeltGeoJSON(gdelt);
    expect(result!.features).toHaveLength(1);
    expect(result!.features[0].properties?.type).toBe('gdelt');
    expect(result!.features[0].properties?.title).toBe('Protest');
  });

  it('filters by inView when provided', () => {
    const gdelt: GDELTIncident[] = [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [30, 50] },
        properties: { name: 'A', count: 1, _urls_list: [], _headlines_list: [] },
      },
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [100, 10] },
        properties: { name: 'B', count: 1, _urls_list: [], _headlines_list: [] },
      },
    ];
    const inView = (lat: number, _lng: number) => lat > 30;
    const result = buildGdeltGeoJSON(gdelt, inView);
    expect(result!.features).toHaveLength(1);
  });

  it('filters out entries without geometry', () => {
    const gdelt: GDELTIncident[] = [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [30, 50] },
        properties: { name: 'Good', count: 1, _urls_list: [], _headlines_list: [] },
      },
      {
        type: 'Feature',
        geometry: null as any,
        properties: { name: 'Bad', count: 1, _urls_list: [], _headlines_list: [] },
      },
    ];
    const result = buildGdeltGeoJSON(gdelt);
    expect(result!.features).toHaveLength(1);
  });
});

describe('buildTrainsGeoJSON', () => {
  it('builds all trains when no inView filter is provided', () => {
    const trains: Train[] = [
      {
        id: 'amtrak-1',
        name: 'Empire Builder',
        number: '7',
        source: 'amtrak',
        source_label: 'Amtraker',
        operator: 'Amtrak',
        country: 'US',
        speed_kmh: 88,
        heading: 90,
        status: 'active',
        route: 'SEA-CHI',
        lat: 47.6,
        lng: -122.3,
      },
      {
        id: 'fin-1',
        name: 'Pendolino',
        number: 'S 94',
        source: 'digitraffic',
        source_label: 'Digitraffic',
        operator: 'VR',
        country: 'FI',
        speed_kmh: 120,
        heading: 180,
        status: 'active',
        route: 'HEL-TKU',
        lat: 60.17,
        lng: 24.94,
      },
    ];

    const result = buildTrainsGeoJSON(trains);
    expect(result).not.toBeNull();
    expect(result!.features).toHaveLength(2);
  });
});

// ─── LiveUAMap ──────────────────────────────────────────────────────────────

describe('buildLiveuaGeoJSON', () => {
  it('returns null for empty input', () => {
    expect(buildLiveuaGeoJSON(undefined)).toBeNull();
  });

  it('classifies violent incidents with red icon', () => {
    const incidents: LiveUAmapIncident[] = [
      { id: '1', lat: 48.0, lng: 35.0, title: 'Missile strike in Kharkiv', date: '2024-01-01' },
      { id: '2', lat: 49.0, lng: 36.0, title: 'Humanitarian aid delivery', date: '2024-01-01' },
    ];
    const result = buildLiveuaGeoJSON(incidents);
    expect(result!.features).toHaveLength(2);
    expect(result!.features[0].properties?.iconId).toBe('icon-liveua-red');
    expect(result!.features[1].properties?.iconId).toBe('icon-liveua-yellow');
  });

  it('filters by inView when provided', () => {
    const incidents: LiveUAmapIncident[] = [
      { id: '1', lat: 48.0, lng: 35.0, title: 'Test', date: '2024-01-01' },
      { id: '2', lat: 10.0, lng: 20.0, title: 'Far away', date: '2024-01-01' },
    ];
    const inView = (lat: number, _lng: number) => lat > 30;
    const result = buildLiveuaGeoJSON(incidents, inView);
    expect(result!.features).toHaveLength(1);
  });
});

// ─── Frontline ──────────────────────────────────────────────────────────────

describe('buildFrontlineGeoJSON', () => {
  it('returns null for null/undefined input', () => {
    expect(buildFrontlineGeoJSON(null)).toBeNull();
    expect(buildFrontlineGeoJSON(undefined)).toBeNull();
  });

  it('returns the input unchanged when valid', () => {
    const fc = {
      type: 'FeatureCollection' as const,
      features: [
        {
          type: 'Feature' as const,
          properties: { name: 'zone', zone_id: 1 },
          geometry: {
            type: 'Polygon' as const,
            coordinates: [
              [
                [30, 48],
                [31, 49],
                [30, 49],
                [30, 48],
              ],
            ] as [number, number][][],
          },
        },
      ],
    };
    const result = buildFrontlineGeoJSON(fc);
    expect(result).toBe(fc); // Same reference — passthrough
  });

  it('returns null for empty features array', () => {
    const fc = { type: 'FeatureCollection' as const, features: [] };
    expect(buildFrontlineGeoJSON(fc)).toBeNull();
  });
});

// ─── Scanners ───────────────────────────────────────────────────────────────

describe('buildScannerGeoJSON', () => {
  it('returns null for empty input', () => {
    expect(buildScannerGeoJSON(undefined)).toBeNull();
    expect(buildScannerGeoJSON([])).toBeNull();
  });

  it('builds features with scanner properties', () => {
    const scanners: Scanner[] = [
      {
        shortName: 'TEST',
        name: 'Test System',
        lat: 39.0,
        lng: -104.0,
        city: 'Denver',
        state: 'CO',
        clientCount: 5,
        description: 'Demo',
      },
    ];
    const result = buildScannerGeoJSON(scanners);
    expect(result!.features).toHaveLength(1);
    expect(result!.features[0].properties?.type).toBe('scanner');
    expect(result!.features[0].properties?.name).toBe('Test System');
  });
});
