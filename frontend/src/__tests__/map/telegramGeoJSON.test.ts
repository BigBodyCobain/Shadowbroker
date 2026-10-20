import { describe, expect, it } from 'vitest';
import {
  applyTelegramAlertAvoidance,
  buildTelegramOsintGeoJSON,
  telegramClusterKey,
  telegramClusterNearNewsAlert,
  telegramMapPinCoords,
  TELEGRAM_ALERT_AVOID_METERS,
} from '@/components/map/geoJSONBuilders';

describe('telegramMapPinCoords', () => {
  it('stays on the geocoded city when no threat alert overlaps', () => {
    const [lat, lng] = telegramMapPinCoords(31.046, 34.851, false);
    expect(lat).toBe(31.046);
    expect(lng).toBe(34.851);
  });

  it('nudges ~5 mi northeast only when avoiding an alert', () => {
    const [lat, lng] = telegramMapPinCoords(31.046, 34.851, true);
    expect(lat).toBeGreaterThan(31.046);
    expect(lng).toBeGreaterThan(34.851);
    const toRad = (deg: number) => (deg * Math.PI) / 180;
    const dLat = toRad(lat - 31.046);
    const meters = 6371000 * dLat;
    expect(meters).toBeGreaterThan(4_000);
    expect(meters).toBeLessThan(TELEGRAM_ALERT_AVOID_METERS + 2_000);
  });
});

describe('telegramClusterNearNewsAlert', () => {
  it('detects news on the same city grid', () => {
    const news = [{ coords: [31.046, 34.851] as [number, number] }];
    expect(telegramClusterNearNewsAlert(31.049, 34.849, news)).toBe(true);
    expect(telegramClusterNearNewsAlert(50.45, 30.52, news)).toBe(false);
  });
});

describe('telegramClusterKey', () => {
  it('groups nearby coordinates to the same city bucket', () => {
    expect(telegramClusterKey(50.451, 30.521)).toBe(telegramClusterKey(50.449, 30.519));
  });
});

describe('buildTelegramOsintGeoJSON', () => {
  it('places the dot on the geocoded city by default', () => {
    const geo = buildTelegramOsintGeoJSON({
      posts: [
        {
          id: 'tg-1',
          title: 'Strike near Kyiv',
          coords: [50.45, 30.52],
        },
      ],
    });
    const feature = geo?.features[0];
    expect(feature).toBeTruthy();
    const [lng, lat] = feature!.geometry!.coordinates as [number, number];
    expect(lat).toBeCloseTo(50.45, 2);
    expect(lng).toBeCloseTo(30.52, 2);
  });

  it('merges posts in the same city into one pin', () => {
    const geo = buildTelegramOsintGeoJSON({
      posts: [
        { id: 'a', title: 'Post A', coords: [50.45, 30.52] },
        { id: 'b', title: 'Post B', coords: [50.451, 30.521] },
        { id: 'c', title: 'Post C', coords: [48.0, 37.8] },
      ],
    });
    expect(geo?.features).toHaveLength(2);
    const kyiv = geo?.features.find((f) => f.properties?.post_count === 2);
    expect(kyiv).toBeTruthy();
    expect(kyiv?.properties?.id).toBe(telegramClusterKey(50.45, 30.52));
  });
});

describe('applyTelegramAlertAvoidance', () => {
  it('offsets only clusters that share a grid cell with a news alert', () => {
    const geo = buildTelegramOsintGeoJSON({
      posts: [
        { id: 'il', title: 'Israel post', coords: [31.046, 34.851] },
        { id: 'ua', title: 'Kyiv post', coords: [50.45, 30.52] },
      ],
    });
    const placed = applyTelegramAlertAvoidance(geo, [{ coords: [31.046, 34.851] }]);
    const israel = placed?.features.find((f) => f.properties?.id === telegramClusterKey(31.046, 34.851));
    const kyiv = placed?.features.find((f) => f.properties?.id === telegramClusterKey(50.45, 30.52));
    const [ilLng, ilLat] = israel!.geometry!.coordinates as [number, number];
    const [uaLng, uaLat] = kyiv!.geometry!.coordinates as [number, number];
    expect(ilLat).toBeGreaterThan(31.046);
    expect(uaLat).toBeCloseTo(50.45, 2);
    expect(uaLng).toBeCloseTo(30.52, 2);
  });
});
