// @ts-nocheck
import { useMemo } from 'react';
import type maplibregl from 'maplibre-gl';
import { useImperativeSource } from './useImperativeSource';

export function useMapImperativeSources(p: any) {
  const map = p.map as maplibregl.Map | null;
  useImperativeSource(map, 'commercial-flights', p.commFlightsGeoJSON);
  useImperativeSource(map, 'private-flights', p.privFlightsGeoJSON);
  useImperativeSource(map, 'private-jets', p.privJetsGeoJSON);
  useImperativeSource(map, 'military-flights', p.milFlightsGeoJSON);
  useImperativeSource(map, 'tracked-flights', p.trackedFlightsGeoJSON);
  useImperativeSource(map, 'uavs', p.uavGeoJSON);
  useImperativeSource(map, 'satellites', p.satellitesGeoJSON);
  useImperativeSource(map, 'tinygs', p.tinygsGeoJSON);
  useImperativeSource(map, 'cctv', p.cctvGeoJSON, 75);
  useImperativeSource(map, 'kiwisdr', p.kiwisdrGeoJSON, 75);
  useImperativeSource(map, 'psk-reporter', p.pskReporterGeoJSON, 75);
  useImperativeSource(map, 'satnogs', p.satnogsGeoJSON, 75);
  useImperativeSource(map, 'scanners', p.scannerGeoJSON, 75);
  useImperativeSource(map, 'firms-fires', p.firmsGeoJSON, 900);
  useImperativeSource(map, 'internet-outages', p.internetOutagesGeoJSON, 100);
  useImperativeSource(map, 'datacenters', p.dataCentersGeoJSON, 120);
  useImperativeSource(map, 'power-plants', p.powerPlantsGeoJSON, 140);
  useImperativeSource(map, 'viirs-change-nodes', p.viirsChangeNodesGeoJSON, 120);
  useImperativeSource(map, 'military-bases', p.militaryBasesGeoJSON, 75);
  useImperativeSource(map, 'gdelt', p.gdeltGeoJSON, 75);
  useImperativeSource(map, 'liveuamap', p.liveuaGeoJSON, 75);
  useImperativeSource(map, 'air-quality-source', p.airQualityGeoJSON, 100);
  useImperativeSource(map, 'volcanoes-source', p.volcanoesGeoJSON, 100);
  useImperativeSource(map, 'fishing-source', p.fishingGeoJSON, 100);
  useImperativeSource(map, 'uap-sightings-source', p.uapSightingsGeoJSON, 100);
  useImperativeSource(map, 'wastewater-source', p.wastewaterGeoJSON, 100);
  useImperativeSource(map, 'crowdthreat-source', p.crowdthreatGeoJSON, 100);
  useImperativeSource(map, 'malware-source', p.malwareGeoJSON, 100);
  useImperativeSource(map, 'telegram-osint-source', p.telegramOsintGeoJSONPlaced, 100);
  useImperativeSource(map, 'submarine-cables-source', p.submarineCablesGeoJSON, 600);
  useImperativeSource(map, 'ships', p.shipsGeoJSON, 75);
  useImperativeSource(map, 'meshtastic-source', p.meshtasticGeoJSON, 60);
  useImperativeSource(map, 'aprs-source', p.aprsGeoJSON, 60);
  useImperativeSource(map, 'trains', p.trainsGeoJSON, 60);
  useImperativeSource(map, 'sar-aois', p.sarAoisGeoJSON, 120);
  useImperativeSource(map, 'sar-anomalies', p.sarAnomaliesGeoJSON, 120);
  useImperativeSource(map, 'night-overlay', p.nightGeoJSON, 250);

  const terminatorLine = useMemo<GeoJSON.FeatureCollection>(() => {
    const poly = p.nightGeoJSON.features[0]?.geometry;
    const ring = poly && poly.type === 'Polygon' ? poly.coordinates[0] : [];
    const line = ring.filter(([lng, lat]: [number, number]) => Math.abs(lat) < 84.9 && Math.abs(lng) <= 180).slice(0, 361);
    return {
      type: 'FeatureCollection',
      features: line.length > 1 ? [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: line } }] : [],
    };
  }, [p.nightGeoJSON]);
  useImperativeSource(map, 'night-twilight', terminatorLine, 250);

  useImperativeSource(map, 'frontlines', p.frontlineGeoJSON, 200);
  useImperativeSource(map, 'earthquakes', p.earthquakesGeoJSON, 100);
  useImperativeSource(map, 'gps-jamming', p.jammingGeoJSON, 150);
  useImperativeSource(map, 'gt-risk-source', p.gtRiskGeoJSON, 150);
  useImperativeSource(map, 'correlations', p.correlationsGeoJSON, 100);
  useImperativeSource(map, 'shodan-overlay', p.shodanGeoJSON, 100);
  useImperativeSource(map, 'ai-intel-source', p.aiIntelGeoJSON, 80);
  useImperativeSource(map, 'ukraine-alerts-source', p.ukraineAlertsGeoJSON, 120);
  useImperativeSource(map, 'ukraine-alert-labels-source', p.ukraineAlertLabelsGeoJSON, 120);
  useImperativeSource(map, 'weather-alerts-source', p.weatherAlertsGeoJSON, 120);
  useImperativeSource(map, 'weather-alert-labels-source', p.weatherAlertLabelsGeoJSON, 120);
  useImperativeSource(map, 'carriers', p.carriersGeoJSON, 75);
  useImperativeSource(map, 'active-route', p.activeRouteGeoJSON, 50);
  useImperativeSource(map, 'flight-trail', p.trailGeoJSON, 40);
  useImperativeSource(map, 'predictive-path', p.predictiveGeoJSON, 40);
  useImperativeSource(map, 'proximity-rings', p.proximityRingsGeoJSON, 60);
}
