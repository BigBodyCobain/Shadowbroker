import { useEffect, useRef, useState } from 'react';
import type { DependencyList } from 'react';
import type {
  StaticMapLayersBuildPayload,
  StaticMapLayersDataPayload,
  StaticMapLayersResult,
} from '@/components/map/staticMapLayers.worker';

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

const EMPTY_RESULT: StaticMapLayersResult = {
  cctvGeoJSON: null,
  kiwisdrGeoJSON: null,
  pskReporterGeoJSON: null,
  satnogsGeoJSON: null,
  scannerGeoJSON: null,
  firmsGeoJSON: null,
  internetOutagesGeoJSON: null,
  dataCentersGeoJSON: null,
  powerPlantsGeoJSON: null,
  viirsChangeNodesGeoJSON: null,
  militaryBasesGeoJSON: null,
  gdeltGeoJSON: null,
  liveuaGeoJSON: null,
  airQualityGeoJSON: null,
  volcanoesGeoJSON: null,
  fishingGeoJSON: null,
  trainsGeoJSON: null,
};

let worker: Worker | null = null;
let reqCounter = 0;
const pending = new Map<
  string,
  {
    resolve: (value: StaticMapLayersResult | true) => void;
    reject: (error: Error) => void;
  }
>();

function ensureWorker(): Worker {
  if (worker) return worker;
  worker = new Worker(new URL('../staticMapLayers.worker.ts', import.meta.url), { type: 'module' });
  worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
    const msg = event.data;
    const handler = pending.get(msg.id);
    if (!handler) return;
    pending.delete(msg.id);
    if (msg.ok && msg.result !== undefined) {
      handler.resolve(msg.result);
    } else {
      handler.reject(new Error(msg.error || 'worker_error'));
    }
  };
  return worker;
}

function callWorker(request: WorkerRequest): Promise<StaticMapLayersResult | true> {
  return new Promise((resolve, reject) => {
    pending.set(request.id, { resolve, reject });
    try {
      ensureWorker().postMessage(request);
    } catch (error) {
      pending.delete(request.id);
      reject(error as Error);
    }
  });
}

function nextRequestId(prefix: string): string {
  return `${prefix}_${Date.now()}_${reqCounter++}`;
}

export function useStaticMapLayersWorker(
  dataPayload: StaticMapLayersDataPayload,
  dataDeps: DependencyList,
  buildPayload: StaticMapLayersBuildPayload,
  buildDeps: DependencyList,
): StaticMapLayersResult {
  const [result, setResult] = useState<StaticMapLayersResult>(EMPTY_RESULT);
  const [syncVersion, setSyncVersion] = useState(0);
  const syncVersionRef = useRef(0);
  const buildRequestVersionRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = nextRequestId('mapsync');
    const currentSyncVersion = ++syncVersionRef.current;

    callWorker({ id: requestId, action: 'sync_static_layers', payload: dataPayload })
      .then(() => {
        if (!cancelled) {
          setSyncVersion(currentSyncVersion);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error('Static map layer worker sync failed', error);
        }
      });

    return () => {
      cancelled = true;
    };
  }, dataDeps);

  useEffect(() => {
    let cancelled = false;
    const requestVersion = ++buildRequestVersionRef.current;
    const requestId = nextRequestId('mapbuild');

    callWorker({ id: requestId, action: 'build_static_layers', payload: buildPayload })
      .then((next) => {
        if (
          !cancelled &&
          requestVersion === buildRequestVersionRef.current &&
          next !== true
        ) {
          setResult(next);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error('Static map layer worker build failed', error);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [syncVersion, ...buildDeps]);

  return result;
}
