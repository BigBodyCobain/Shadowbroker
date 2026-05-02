/**
 * AI Intel API client — frontend functions for interacting with
 * the /api/ai/* endpoints.
 */

import { API_BASE } from '@/lib/api';
import type {
  AIIntelPin,
  AIIntelLayer,
  AIIntelStatus,
  AIIntelGeoJSON,
  SatelliteScene,
  NewsNearResult,
  PinCategory,
  EntityAttachment,
  AIIntelPinComment,
} from '@/types/aiIntel';

const AI_API = `${API_BASE}/api/ai`;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function aiGet<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(`${AI_API}${path}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== undefined) url.searchParams.set(k, String(v));
    });
  }
  const resp = await fetch(url.toString());
  if (!resp.ok) throw new Error(`AI Intel API error: ${resp.status}`);
  return resp.json();
}

async function aiPost<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${AI_API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`AI Intel API error: ${resp.status}`);
  return resp.json();
}

async function aiPatch<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${AI_API}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`AI Intel API error: ${resp.status}`);
  return resp.json();
}

async function aiDelete<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${AI_API}${path}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v);
    });
  }
  const resp = await fetch(url.toString(), { method: 'DELETE' });
  if (!resp.ok) throw new Error(`AI Intel API error: ${resp.status}`);
  return resp.json();
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

export async function fetchAIIntelStatus(): Promise<AIIntelStatus> {
  return aiGet('/status');
}

// ---------------------------------------------------------------------------
// Layers
// ---------------------------------------------------------------------------

export async function fetchLayers(): Promise<{ ok: boolean; count: number; layers: AIIntelLayer[] }> {
  return aiGet('/layers');
}

export async function createLayer(layer: {
  name: string;
  description?: string;
  source?: string;
  color?: string;
  feed_url?: string;
  feed_interval?: number;
}): Promise<{ ok: boolean; layer: AIIntelLayer }> {
  return aiPost('/layers', layer);
}

export async function updateLayer(
  layerId: string,
  updates: Partial<Pick<AIIntelLayer, 'name' | 'description' | 'visible' | 'color'>>,
): Promise<{ ok: boolean; layer: AIIntelLayer }> {
  return aiPatch(`/layers/${layerId}`, updates);
}

export async function deleteLayer(
  layerId: string,
): Promise<{ ok: boolean; layer_id: string; pins_removed: number }> {
  return aiDelete(`/layers/${layerId}`);
}

export async function refreshLayerFeed(
  layerId: string,
): Promise<{ ok: boolean; layer: AIIntelLayer }> {
  return aiPost(`/layers/${layerId}/refresh`, {});
}

// ---------------------------------------------------------------------------
// Pins
// ---------------------------------------------------------------------------

export async function fetchAIIntelPins(
  category?: string,
  source?: string,
  layer_id?: string,
  limit?: number,
): Promise<{ ok: boolean; count: number; pins: AIIntelPin[] }> {
  return aiGet('/pins', {
    ...(category ? { category } : {}),
    ...(source ? { source } : {}),
    ...(layer_id ? { layer_id } : {}),
    ...(limit ? { limit } : {}),
  });
}

export async function fetchAIIntelGeoJSON(layer_id?: string): Promise<AIIntelGeoJSON> {
  return aiGet('/pins/geojson', layer_id ? { layer_id } : {});
}

export async function createAIIntelPin(pin: {
  lat: number;
  lng: number;
  label: string;
  category?: PinCategory;
  layer_id?: string;
  color?: string;
  description?: string;
  source?: string;
  entity_attachment?: EntityAttachment;
}): Promise<{ ok: boolean; pin: AIIntelPin }> {
  return aiPost('/pins', pin);
}

export async function createAIIntelPinsBatch(
  pins: Array<{
    lat: number;
    lng: number;
    label: string;
    category?: PinCategory;
    description?: string;
    layer_id?: string;
    entity_attachment?: EntityAttachment;
  }>,
  layer_id?: string,
): Promise<{ ok: boolean; created: number; pins: AIIntelPin[] }> {
  return aiPost('/pins/batch', { pins, layer_id: layer_id || '' });
}

export async function deleteAIIntelPin(
  pinId: string,
): Promise<{ ok: boolean; deleted: string }> {
  return aiDelete(`/pins/${pinId}`);
}

export async function fetchAIIntelPin(
  pinId: string,
): Promise<{ ok: boolean; pin: AIIntelPin }> {
  return aiGet(`/pins/${pinId}`);
}

export async function updateAIIntelPin(
  pinId: string,
  updates: Partial<Pick<AIIntelPin, 'label' | 'description' | 'category' | 'color'>>,
): Promise<{ ok: boolean; pin: AIIntelPin }> {
  return aiPatch(`/pins/${pinId}`, updates);
}

export async function addAIIntelPinComment(
  pinId: string,
  comment: {
    text: string;
    author?: 'user' | 'agent' | 'openclaw';
    author_label?: string;
    reply_to?: string;
  },
): Promise<{ ok: boolean; pin: AIIntelPin }> {
  return aiPost(`/pins/${pinId}/comments`, comment);
}

export async function deleteAIIntelPinComment(
  pinId: string,
  commentId: string,
): Promise<{ ok: boolean; deleted: string }> {
  return aiDelete(`/pins/${pinId}/comments/${commentId}`);
}

// Re-export for convenience (some consumers may want the type).
export type { AIIntelPinComment };

export async function clearAIIntelPins(
  category?: string,
  source?: string,
): Promise<{ ok: boolean; removed: number }> {
  return aiDelete('/pins', {
    ...(category ? { category } : {}),
    ...(source ? { source } : {}),
  });
}

// ---------------------------------------------------------------------------
// Satellite Imagery
// ---------------------------------------------------------------------------

export async function fetchSatelliteImages(
  lat: number,
  lng: number,
  count: number = 3,
): Promise<{
  ok: boolean;
  lat: number;
  lng: number;
  scenes: SatelliteScene[];
  count: number;
  source: string;
}> {
  return aiGet('/satellite-images', { lat, lng, count });
}

// ---------------------------------------------------------------------------
// News Near
// ---------------------------------------------------------------------------

export async function fetchNewsNear(
  lat: number,
  lng: number,
  radius: number = 500,
): Promise<NewsNearResult> {
  return aiGet('/news-near', { lat, lng, radius });
}

// ---------------------------------------------------------------------------
// Data Injection
// ---------------------------------------------------------------------------

export async function injectData(
  layer: string,
  items: Record<string, unknown>[],
  mode: 'append' | 'replace' = 'append',
): Promise<{ ok: boolean; layer: string; injected: number; total: number }> {
  return aiPost('/inject', { layer, items, mode });
}

export async function clearInjectedData(
  layer?: string,
): Promise<{ ok: boolean; removed: number; layer: string }> {
  return aiDelete('/inject', layer ? { layer } : {});
}
