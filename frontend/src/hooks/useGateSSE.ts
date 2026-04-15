import { useEffect, useRef } from 'react';
import { API_BASE } from '@/lib/api';

/**
 * Subscribe to the backend SSE gate-event stream.
 * Delivers ALL gate events (encrypted blobs) — the client filters by gate_id locally.
 * The server never learns which gates a client cares about (privacy-preserving broadcast).
 *
 * Falls back gracefully: if the stream fails the browser's EventSource auto-reconnects.
 */
export function useGateSSE(onEvent: (gateId: string) => void) {
  const callbackRef = useRef(onEvent);
  callbackRef.current = onEvent;

  useEffect(() => {
    const es = new EventSource(`${API_BASE}/api/mesh/gate/stream`);

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.gate_id && typeof data.gate_id === 'string') {
          callbackRef.current(data.gate_id);
        }
      } catch {
        /* ignore parse errors */
      }
    };

    // Browser auto-reconnects EventSource on error — no manual retry needed.

    return () => es.close();
  }, []);
}
