import { useEffect } from 'react';
import type { MutableRefObject } from 'react';
import type maplibregl from 'maplibre-gl';
import { clampZoom } from '@/lib/mapZoom';
import { emitViewState, onRequest as onMapControlRequest } from '@/lib/mapControlBus';

export function useMapControlRequests(mapRef: MutableRefObject<any>) {
  useEffect(() => {
    let orbitRaf = 0;
    let moveendBound = false;
    const stopOrbit = () => {
      if (orbitRaf) cancelAnimationFrame(orbitRaf);
      orbitRaf = 0;
    };
    const unsub = onMapControlRequest((cmd) => {
      const map = mapRef.current?.getMap();
      if (!map) return { ok: false, action: cmd.type, error: 'map viewer is not ready' };
      if (!moveendBound) {
        moveendBound = true;
        map.on('moveend', () => {
          const c = map.getCenter();
          emitViewState({ center: { lat: c.lat, lng: c.lng }, zoom: map.getZoom() });
        });
      }
      switch (cmd.type) {
        case 'easeTo': {
          map.easeTo({ center: [cmd.lng, cmd.lat], zoom: cmd.zoom ?? map.getZoom(), duration: cmd.durationMs ?? 800 });
          return { ok: true, action: 'map_ease_to', center: { lat: cmd.lat, lng: cmd.lng }, zoom: cmd.zoom ?? map.getZoom() };
        }
        case 'zoom': {
          const steps = cmd.amount === 'little' ? 1 : cmd.amount === 'lot' ? 4 : 2;
          const target = clampZoom(map.getZoom() + (cmd.direction === 'in' ? steps : -steps));
          map.easeTo({ zoom: target, duration: 400 });
          return { ok: true, action: 'map_zoom', zoom: target };
        }
        case 'orbit': {
          stopOrbit();
          if (cmd.stop) {
            map.once('dragstart', stopOrbit);
            return { ok: true, action: 'map_orbit', orbiting: false };
          }
          if (orbitRaf) cancelAnimationFrame(orbitRaf);
          const speed = cmd.speed && cmd.speed > 0 ? cmd.speed : 1;
          const startedAt = performance.now();
          const baseBearing = map.getBearing();
          const frame = (t: number) => {
            if (!orbitRaf) return;
            map.jumpTo({
              center: [cmd.lng, cmd.lat],
              zoom: Math.max(map.getZoom(), 7),
              bearing: baseBearing + ((t - startedAt) / 1000) * 18 * speed,
            });
            orbitRaf = requestAnimationFrame(frame);
          };
          orbitRaf = requestAnimationFrame(frame);
          map.once('dragstart', stopOrbit);
          return { ok: true, action: 'map_orbit', orbiting: true };
        }
        case 'getViewState': {
          const c = map.getCenter();
          return {
            ok: true,
            action: 'get_view_state',
            view: { center: { lat: c.lat, lng: c.lng }, zoom: map.getZoom() },
          };
        }
        default:
          return { ok: false, action: (cmd as { type: string }).type, error: 'unsupported map command' };
      }
    });
    return () => {
      unsub();
      stopOrbit();
    };
  }, [mapRef]);
}
