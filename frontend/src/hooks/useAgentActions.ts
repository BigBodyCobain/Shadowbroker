/**
 * useAgentActions — polls for display actions pushed by the OpenClaw agent.
 *
 * When the agent sends a `show_satellite` or `show_sentinel` command,
 * the backend queues a display action. This hook picks it up and
 * triggers the same full-screen image viewer as a right-click dossier.
 *
 * Actions are consumed on read (destructive poll) so they don't pile up.
 */

import { useEffect, useRef, useCallback } from 'react';
import { API_BASE } from '@/lib/api';

interface AgentAction {
  action: string;
  source?: string;
  lat?: number;
  lng?: number;
  sentinel2?: Record<string, unknown>;
  preset?: string;
  caption?: string | null;
  ts?: number;
  // fly_to extras
  zoom?: number;
  aoi_id?: string;
}

/**
 * @param onShowImage — called when the agent wants to display satellite imagery.
 *   Receives {lat, lng} — the caller should trigger handleMapRightClick or
 *   equivalent to open the RegionDossierPanel.
 * @param onFlyTo — called when the agent wants to center the map on a point
 *   without opening imagery (e.g. sar_focus_aoi).
 */
export function useAgentActions(
  onShowImage: (coords: { lat: number; lng: number }) => void,
  onFlyTo?: (coords: { lat: number; lng: number; zoom?: number }) => void,
) {
  const onShowImageRef = useRef(onShowImage);
  onShowImageRef.current = onShowImage;
  const onFlyToRef = useRef(onFlyTo);
  onFlyToRef.current = onFlyTo;

  const poll = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/ai/agent-actions`);
      if (!res.ok) return;
      const data = await res.json();
      const actions: AgentAction[] = data.actions || [];

      for (const action of actions) {
        if (action.action === 'show_image' && action.lat != null && action.lng != null) {
          onShowImageRef.current({ lat: action.lat, lng: action.lng });
        } else if (
          action.action === 'fly_to' &&
          action.lat != null &&
          action.lng != null
        ) {
          onFlyToRef.current?.({
            lat: action.lat,
            lng: action.lng,
            zoom: action.zoom,
          });
        }
      }
    } catch {
      // Silent fail — agent actions are best-effort
    }
  }, []);

  useEffect(() => {
    // Poll every 3 seconds — lightweight endpoint, ~50 bytes when empty
    const interval = setInterval(poll, 3000);
    // Initial poll on mount
    poll();
    return () => clearInterval(interval);
  }, [poll]);
}
