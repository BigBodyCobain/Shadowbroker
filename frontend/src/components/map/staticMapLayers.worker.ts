/// <reference lib="webworker" />

import {
  buildAirQualityGeoJSON,
  buildCctvGeoJSON,
  buildDataCentersGeoJSON,
  buildFirmsGeoJSON,
  buildFishingActivityGeoJSON,
  buildGdeltGeoJSON,
  buildInternetOutagesGeoJSON,
  buildKiwisdrGeoJSON,
  buildLiveuaGeoJSON,
  buildPskReporterGeoJSON,
  buildMilitaryBasesGeoJSON,
  buildPowerPlantsGeoJSON,
  buildSatnogsStationsGeoJSON,
  buildScannerGeoJSON,
  buildTrainsGeoJSON,
  buildVIIRSChangeNodesGeoJSON,
  buildVolcanoesGeoJSON,
} from '@/components/map/geoJSONBuilders';
import type {
  AirQualityStation,
  CCTVCamera,
  DataCenter,
  FireHotspot,
  FishingEvent,
  GDELTIncident,
  InternetOutage,
  KiwiSDR,
  LiveUAmapIncident,
  PSKSpot,
  MilitaryBase,
  PowerPlant,
  SatNOGSStation,
  Scanner,
  Train,
  VIIRSChangeNode,
  Volcano,
} from '@/types/dashboard';

type BoundsTuple = [number, number, number, number];
type FC = GeoJSON.FeatureCollection | null;

export type StaticMapLayersDataPayload = {
  cctv?: CCTVCamera[];
  kiwisdr?: KiwiSDR[];
  pskReporter?: PSKSpot[];
  satnogsStations?: SatNOGSStation[];
  scanners?: Scanner[];
  firmsFires?: FireHotspot[];
  internetOutages?: InternetOutage[];
  datacenters?: DataCenter[];
  powerPlants?: PowerPlant[];
  viirsChangeNodes?: VIIRSChangeNode[];
  militaryBases?: MilitaryBase[];
  gdelt?: GDELTIncident[];
  liveuamap?: LiveUAmapIncident[];
  airQuality?: AirQualityStation[];
  volcanoes?: Volcano[];
  fishingActivity?: FishingEvent[];
  trains?: Train[];
};

export type StaticMapLayersBuildPayload = {
  bounds: BoundsTuple;
  activeLayers: {
    cctv: boolean;
    kiwisdr: boolean;
    psk_reporter: boolean;
    satnogs: boolean;
    scanners: boolean;
    firms: boolean;
    internet_outages: boolean;
    datacenters: boolean;
    power_plants: boolean;
    viirs_nightlights: boolean;
    military_bases: boolean;
    global_incidents: boolean;
    air_quality: boolean;
    volcanoes: boolean;
    fishing_activity: boolean;
    trains: boolean;
  };
};

export type StaticMapLayersResult = {
  cctvGeoJSON: FC;
  kiwisdrGeoJSON: FC;
  pskReporterGeoJSON: FC;
  satnogsGeoJSON: FC;
  scannerGeoJSON: FC;
  firmsGeoJSON: FC;
  internetOutagesGeoJSON: FC;
  dataCentersGeoJSON: FC;
  powerPlantsGeoJSON: FC;
  viirsChangeNodesGeoJSON: FC;
  militaryBasesGeoJSON: FC;
  gdeltGeoJSON: FC;
  liveuaGeoJSON: FC;
  airQualityGeoJSON: FC;
  volcanoesGeoJSON: FC;
  fishingGeoJSON: FC;
  trainsGeoJSON: FC;
};

type SyncRequest = {
  id: string;
  action: 'sync_static_layers';
  payload: StaticMapLayersDataPayload;
};

type BuildRequest = {
  id: string;
  action: 'build_static_layers';
  payload: StaticMapLayersBuildPayload;
};

type WorkerRequest = SyncRequest | BuildRequest;

type WorkerResponse = {
  id: string;
  ok: boolean;
  result?: StaticMapLayersResult | true;
  error?: string;
};

let staticData: StaticMapLayersDataPayload = {};

function createInView(bounds: BoundsTuple) {
  return (lat: number, lng: number) =>
    lng >= bounds[0] && lng <= bounds[2] && lat >= bounds[1] && lat <= bounds[3];
}

function buildStaticLayers(payload: StaticMapLayersBuildPayload): StaticMapLayersResult {
  const inView = createInView(payload.bounds);

  return {
    cctvGeoJSON: payload.activeLayers.cctv ? buildCctvGeoJSON(staticData.cctv, inView) : null,
    kiwisdrGeoJSON: payload.activeLayers.kiwisdr ? buildKiwisdrGeoJSON(staticData.kiwisdr, inView) : null,
    pskReporterGeoJSON: payload.activeLayers.psk_reporter
      ? buildPskReporterGeoJSON(staticData.pskReporter, inView)
      : null,
    satnogsGeoJSON: payload.activeLayers.satnogs
      ? buildSatnogsStationsGeoJSON(staticData.satnogsStations, inView)
      : null,
    scannerGeoJSON: payload.activeLayers.scanners ? buildScannerGeoJSON(staticData.scanners, inView) : null,
    firmsGeoJSON: payload.activeLayers.firms ? buildFirmsGeoJSON(staticData.firmsFires) : null,
    internetOutagesGeoJSON: payload.activeLayers.internet_outages
      ? buildInternetOutagesGeoJSON(staticData.internetOutages)
      : null,
    dataCentersGeoJSON: payload.activeLayers.datacenters
      ? buildDataCentersGeoJSON(staticData.datacenters)
      : null,
    powerPlantsGeoJSON: payload.activeLayers.power_plants
      ? buildPowerPlantsGeoJSON(staticData.powerPlants)
      : null,
    viirsChangeNodesGeoJSON: payload.activeLayers.viirs_nightlights
      ? buildVIIRSChangeNodesGeoJSON(staticData.viirsChangeNodes)
      : null,
    militaryBasesGeoJSON: payload.activeLayers.military_bases
      ? buildMilitaryBasesGeoJSON(staticData.militaryBases)
      : null,
    gdeltGeoJSON: payload.activeLayers.global_incidents ? buildGdeltGeoJSON(staticData.gdelt) : null,
    liveuaGeoJSON: payload.activeLayers.global_incidents
      ? buildLiveuaGeoJSON(staticData.liveuamap, inView)
      : null,
    airQualityGeoJSON: payload.activeLayers.air_quality ? buildAirQualityGeoJSON(staticData.airQuality) : null,
    volcanoesGeoJSON: payload.activeLayers.volcanoes ? buildVolcanoesGeoJSON(staticData.volcanoes) : null,
    fishingGeoJSON: payload.activeLayers.fishing_activity
      ? buildFishingActivityGeoJSON(staticData.fishingActivity)
      : null,
    trainsGeoJSON: payload.activeLayers.trains ? buildTrainsGeoJSON(staticData.trains) : null,
  };
}

self.onmessage = (event: MessageEvent<WorkerRequest>) => {
  const message = event.data;

  try {
    if (message.action === 'sync_static_layers') {
      staticData = message.payload;
      const response: WorkerResponse = { id: message.id, ok: true, result: true };
      self.postMessage(response);
      return;
    }

    const result = buildStaticLayers(message.payload);
    const response: WorkerResponse = {
      id: message.id,
      ok: true,
      result,
    };
    self.postMessage(response);
  } catch (error) {
    const response: WorkerResponse = {
      id: message.id,
      ok: false,
      error: error instanceof Error ? error.message : 'unknown_worker_error',
    };
    self.postMessage(response);
  }
};
