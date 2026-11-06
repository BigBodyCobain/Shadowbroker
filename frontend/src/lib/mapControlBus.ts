/**
 * mapControlBus — typed singleton between voice tool executors (clientTools)
 * and the MaplibreViewer instance (voice-agent plan U4, §3.5).
 *
 * Executors `send(cmd)` a camera verb; MaplibreViewer registers exactly one
 * handler via `onRequest` in a single additive useEffect and answers with the
 * standard `{ok, action, ...evidence}` envelope. flyTo-family verbs keep
 * flowing through the existing tested `flyToLocation` prop — only ease-to,
 * zoom, orbit and view-state queries ride this bus.
 *
 * A send() without a live viewer — or one that never answers — resolves
 * `{ok:false}` after `timeoutMs` (8 s default) so a dead tab can never wedge
 * the calling loop.
 */

export interface ViewStateSnapshot {
  center: { lat: number; lng: number };
  zoom: number;
}

export type MapBusCommand =
  | { type: 'easeTo'; lat: number; lng: number; zoom?: number; durationMs?: number }
  | { type: 'orbit'; lng: number; lat: number; radiusKm?: number; speed?: number; stop?: boolean }
  | { type: 'zoom'; direction: 'in' | 'out'; amount: 'little' | 'medium' | 'lot' }
  | { type: 'getViewState' };

export interface MapBusResult {
  ok: boolean;
  action: string;
  error?: string;
  cancelled?: boolean;
  [key: string]: unknown;
}

type MapRequestHandler = (cmd: MapBusCommand) => MapBusResult | Promise<MapBusResult>;
type ViewStateListener = (vs: ViewStateSnapshot) => void;

const DEFAULT_TIMEOUT_MS = 8000;

let requestHandler: MapRequestHandler | null = null;
const viewStateListeners = new Set<ViewStateListener>();

/** Register the viewer's command handler. Returns an unsubscribe function. */
export function onRequest(handler: MapRequestHandler): () => void {
  requestHandler = handler;
  return () => {
    if (requestHandler === handler) requestHandler = null;
  };
}

/** Send one camera verb to the viewer, resolving to a tool-result envelope. */
export async function send(cmd: MapBusCommand, timeoutMs: number = DEFAULT_TIMEOUT_MS): Promise<MapBusResult> {
  const handler = requestHandler;
  if (!handler) {
    return { ok: false, action: cmd.type, error: 'map viewer is not connected' };
  }
  let timer: ReturnType<typeof setTimeout> | null = null;
  const timeout = new Promise<MapBusResult>((resolve) => {
    timer = setTimeout(
      () => resolve({ ok: false, action: cmd.type, error: 'operator client did not respond' }),
      Math.max(0, timeoutMs),
    );
  });
  try {
    return await Promise.race([Promise.resolve(handler(cmd)), timeout]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/** Subscribe to camera snapshots emitted by the viewer (moveend). */
export function onViewState(cb: ViewStateListener): () => void {
  viewStateListeners.add(cb);
  return () => {
    viewStateListeners.delete(cb);
  };
}

/** Viewer-side push of the latest camera snapshot. */
export function emitViewState(vs: ViewStateSnapshot): void {
  for (const cb of viewStateListeners) {
    try {
      cb(vs);
    } catch {
      // Listener errors must never break the map render loop.
    }
  }
}
