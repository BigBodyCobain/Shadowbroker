import { useEffect, useRef, useState } from 'react';
import type { DependencyList } from 'react';
import type {
  DynamicMapLayersBuildPayload,
  DynamicMapLayersDataPayload,
  DynamicMapLayersResult,
} from '@/components/map/dynamicMapLayers.worker';

type SyncRequest = {
  id: string;
  action: 'sync_dynamic_layers';
  payload: DynamicMapLayersDataPayload;
};

type BuildRequest = {
  id: string;
  action: 'build_dynamic_layers';
  payload: DynamicMapLayersBuildPayload;
};

type WorkerRequest = SyncRequest | BuildRequest;

type WorkerResponse = {
  id: string;
  ok: boolean;
  result?: DynamicMapLayersResult;
  error?: string;
};

const EMPTY_RESULT: DynamicMapLayersResult = {
  commercialFlightsGeoJSON: null,
  privateFlightsGeoJSON: null,
  privateJetsGeoJSON: null,
  militaryFlightsGeoJSON: null,
  trackedFlightsGeoJSON: null,
  shipsGeoJSON: null,
  meshtasticGeoJSON: null,
  aprsGeoJSON: null,
};

let worker: Worker | null = null;
let reqCounter = 0;
const pending = new Map<
  string,
  {
    resolve: (value: DynamicMapLayersResult) => void;
    reject: (error: Error) => void;
  }
>();

function ensureWorker(): Worker {
  if (worker) return worker;
  worker = new Worker(new URL('../dynamicMapLayers.worker.ts', import.meta.url), { type: 'module' });
  worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
    const msg = event.data;
    const handler = pending.get(msg.id);
    if (!handler) return;
    pending.delete(msg.id);
    if (msg.ok && msg.result) {
      handler.resolve(msg.result);
    } else {
      handler.reject(new Error(msg.error || 'worker_error'));
    }
  };
  return worker;
}

function callWorker(request: WorkerRequest): Promise<DynamicMapLayersResult> {
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

export function useDynamicMapLayersWorker(
  dataPayload: DynamicMapLayersDataPayload,
  dataDeps: DependencyList,
  buildPayload: DynamicMapLayersBuildPayload,
  buildDeps: DependencyList,
): DynamicMapLayersResult {
  const [result, setResult] = useState<DynamicMapLayersResult>(EMPTY_RESULT);
  const [syncVersion, setSyncVersion] = useState(0);
  const syncVersionRef = useRef(0);
  const requestVersionRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const id = `mapw_sync_${Date.now()}_${reqCounter++}`;
    const currentSyncVersion = ++syncVersionRef.current;

    callWorker({ id, action: 'sync_dynamic_layers', payload: dataPayload })
      .then(() => {
        if (!cancelled) {
          setSyncVersion(currentSyncVersion);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error('Dynamic map layer worker sync failed', error);
        }
      });

    return () => {
      cancelled = true;
    };
  }, dataDeps);

  useEffect(() => {
    let cancelled = false;
    const requestVersion = ++requestVersionRef.current;
    const id = `mapw_build_${Date.now()}_${reqCounter++}`;

    callWorker({ id, action: 'build_dynamic_layers', payload: buildPayload })
      .then((next) => {
        if (!cancelled && requestVersion === requestVersionRef.current) {
          setResult(next);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error('Dynamic map layer worker build failed', error);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [syncVersion, ...buildDeps]);

  return result;
}
