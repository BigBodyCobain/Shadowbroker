import { flattenCustomIntelEvents, parseAndBuildCustomIntel } from "@/lib/customIntel";
import type {
  CustomIntelDataset,
  CustomIntelEvent,
  CustomIntelFeatureProperties,
  CustomIntelStory,
  CustomIntelStore,
} from "@/types/dashboard";

export const CUSTOM_INTEL_STORE_VERSION = 1;
export const CUSTOM_INTEL_STORAGE_KEY = "shadowbroker.customIntelStore.v1";

export type CustomIntelImportMode = "merge" | "replace";

export const CUSTOM_INTEL_WEIGHT_COLORS: Record<number, { fill: string; stroke: string; text: string }> = {
  1: { fill: "#14b8a6", stroke: "#5eead4", text: "text-teal-300" },
  2: { fill: "#22c55e", stroke: "#86efac", text: "text-green-300" },
  3: { fill: "#eab308", stroke: "#fde047", text: "text-yellow-300" },
  4: { fill: "#f97316", stroke: "#fdba74", text: "text-orange-300" },
  5: { fill: "#ef4444", stroke: "#fca5a5", text: "text-red-300" },
};

function nowIso(): string {
  return new Date().toISOString();
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function toSafeString(v: unknown, fallback = ""): string {
  return typeof v === "string" && v.trim().length > 0 ? v.trim() : fallback;
}

export function normalizeWeight(weight?: number): number {
  if (typeof weight !== "number" || !Number.isFinite(weight)) return 1;
  return Math.max(1, Math.min(5, Math.round(weight)));
}

export function getCustomIntelWeightColor(weight?: number): { fill: string; stroke: string; text: string } {
  return CUSTOM_INTEL_WEIGHT_COLORS[normalizeWeight(weight)];
}

function parseDateValue(value?: string): number | null {
  if (!value) return null;
  const t = Date.parse(value);
  return Number.isFinite(t) ? t : null;
}

function eventDateMs(event: CustomIntelEvent): number | null {
  const candidates = [
    parseDateValue(event.date),
    parseDateValue(event.end_date),
    parseDateValue(event.start_date),
  ].filter((v): v is number => v != null);
  if (!candidates.length) return null;
  return Math.max(...candidates);
}

function latestStoryDateMs(story: CustomIntelStory): number | null {
  const dates = story.events.map(eventDateMs).filter((v): v is number => v != null);
  return dates.length ? Math.max(...dates) : null;
}

function sortEventsByDate(events: CustomIntelEvent[], fallbackIso?: string): CustomIntelEvent[] {
  const fallbackMs = parseDateValue(fallbackIso) ?? 0;
  return [...events].sort((a, b) => {
    const ad = eventDateMs(a) ?? fallbackMs;
    const bd = eventDateMs(b) ?? fallbackMs;
    if (bd !== ad) return bd - ad;

    const aid = toSafeString(a.id);
    const bid = toSafeString(b.id);
    return aid.localeCompare(bid);
  });
}

export function sortStoriesByDate(stories: CustomIntelStory[], fallbackIso?: string): CustomIntelStory[] {
  const fallbackMs = parseDateValue(fallbackIso) ?? 0;
  return [...stories]
    .map((story) => ({ ...story, events: sortEventsByDate(story.events, fallbackIso) }))
    .sort((a, b) => {
      const ad = latestStoryDateMs(a) ?? fallbackMs;
      const bd = latestStoryDateMs(b) ?? fallbackMs;
      if (bd !== ad) return bd - ad;
      return a.story_id.localeCompare(b.story_id);
    });
}

function deriveDatasetLatestDateMs(dataset: CustomIntelDataset): number {
  const dates = dataset.stories
    .map((s) => latestStoryDateMs(s))
    .filter((v): v is number => v != null);

  if (dates.length) return Math.max(...dates);
  return parseDateValue(dataset.updatedAt) ?? parseDateValue(dataset.createdAt) ?? 0;
}

export function deriveDatasetLatestEventDate(dataset: CustomIntelDataset): string | undefined {
  const ms = deriveDatasetLatestDateMs(dataset);
  if (!ms) return undefined;
  return new Date(ms).toISOString();
}

function deriveDatasetEventCount(stories: CustomIntelStory[]): number {
  return stories.reduce((sum, s) => sum + s.events.length, 0);
}

export function deriveDatasetMaxWeight(dataset: CustomIntelDataset): number {
  let max = 1;
  for (const story of dataset.stories) {
    for (const event of story.events) {
      const w = normalizeWeight(event.weight);
      if (w > max) max = w;
    }
  }
  return max;
}

function generateDatasetId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `dataset-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function ensureUniqueDatasetId(id: string, used: Set<string>): string {
  if (!used.has(id)) {
    used.add(id);
    return id;
  }
  let candidate = id;
  while (used.has(candidate)) {
    candidate = generateDatasetId();
  }
  used.add(candidate);
  return candidate;
}

function normalizeDataset(dataset: CustomIntelDataset, idFallback?: string): CustomIntelDataset {
  const createdAt = toSafeString(dataset.createdAt, nowIso());
  const updatedAt = toSafeString(dataset.updatedAt, createdAt);
  const stories = sortStoriesByDate(dataset.stories ?? [], updatedAt).map((story) => ({
    ...story,
    events: story.events.map((event) => ({ ...event, weight: normalizeWeight(event.weight) })),
  }));
  const eventCount = deriveDatasetEventCount(stories);
  const latestEventDate = deriveDatasetLatestEventDate({ ...dataset, stories, createdAt, updatedAt, eventCount, visible: dataset.visible });

  return {
    datasetId: toSafeString(dataset.datasetId, idFallback || generateDatasetId()),
    story_id: dataset.story_id,
    title: toSafeString(dataset.title, stories.length === 1 ? stories[0].title : "Imported Intel Dataset"),
    createdAt,
    updatedAt,
    visible: dataset.visible !== false,
    stories,
    eventCount,
    latestEventDate,
  };
}

export function createEmptyCustomIntelStore(): CustomIntelStore {
  return {
    version: CUSTOM_INTEL_STORE_VERSION,
    datasets: [],
    updatedAt: nowIso(),
  };
}

function sortDatasetsByDateInternal(datasets: CustomIntelDataset[]): CustomIntelDataset[] {
  return [...datasets].sort((a, b) => {
    const aMs = parseDateValue(a.latestEventDate) ?? deriveDatasetLatestDateMs(a);
    const bMs = parseDateValue(b.latestEventDate) ?? deriveDatasetLatestDateMs(b);
    if (bMs !== aMs) return bMs - aMs;
    return b.updatedAt.localeCompare(a.updatedAt);
  });
}

export function sortDatasetsByDate(datasets: CustomIntelDataset[]): CustomIntelDataset[] {
  return sortDatasetsByDateInternal(datasets);
}

function touchStore(store: CustomIntelStore): CustomIntelStore {
  return {
    ...store,
    version: CUSTOM_INTEL_STORE_VERSION,
    updatedAt: nowIso(),
  };
}

export function normalizeCustomIntelDataset(raw: string): CustomIntelDataset {
  const parsed = parseAndBuildCustomIntel(raw);
  const createdAt = nowIso();
  const stories = sortStoriesByDate(parsed.stories, createdAt).map((story) => ({
    ...story,
    events: story.events.map((event) => ({
      ...event,
      weight: normalizeWeight(event.weight),
    })),
  }));

  const dataset: CustomIntelDataset = {
    datasetId: generateDatasetId(),
    story_id: stories.length === 1 ? stories[0].story_id : undefined,
    title: stories.length === 1 ? stories[0].title : `${stories.length} Intel Stories`,
    createdAt,
    updatedAt: createdAt,
    visible: true,
    stories,
    eventCount: deriveDatasetEventCount(stories),
    latestEventDate: undefined,
  };

  return normalizeDataset(dataset);
}

export function appendCustomIntelDataset(store: CustomIntelStore, dataset: CustomIntelDataset): CustomIntelStore {
  const used = new Set(store.datasets.map((d) => d.datasetId));
  const normalized = normalizeDataset(dataset, generateDatasetId());
  const withUniqueId = { ...normalized, datasetId: ensureUniqueDatasetId(normalized.datasetId, used) };

  return touchStore({
    ...store,
    datasets: sortDatasetsByDateInternal([...store.datasets, withUniqueId]),
  });
}

export function removeCustomIntelDataset(store: CustomIntelStore, datasetId: string): CustomIntelStore {
  return touchStore({
    ...store,
    datasets: store.datasets.filter((d) => d.datasetId !== datasetId),
  });
}

export function toggleCustomIntelDatasetVisibility(store: CustomIntelStore, datasetId: string): CustomIntelStore {
  const datasets = store.datasets.map((d) =>
    d.datasetId === datasetId ? normalizeDataset({ ...d, visible: !d.visible, updatedAt: nowIso() }) : d
  );

  return touchStore({
    ...store,
    datasets,
  });
}

export function removeCustomIntelEvent(
  store: CustomIntelStore,
  datasetId: string,
  eventId: string
): CustomIntelStore {
  const nextDatasets: CustomIntelDataset[] = [];

  for (const dataset of store.datasets) {
    if (dataset.datasetId !== datasetId) {
      nextDatasets.push(dataset);
      continue;
    }

    const nextStories: CustomIntelStory[] = [];

    for (const story of dataset.stories) {
      const nextEvents = story.events.filter((e, idx) => {
        const resolvedId = e.id && e.id.trim() ? e.id : `${story.story_id}-${idx}`;
        return resolvedId !== eventId;
      });

      if (nextEvents.length > 0) {
        nextStories.push({ ...story, events: sortEventsByDate(nextEvents, dataset.updatedAt) });
      }
    }

    if (nextStories.length > 0) {
      nextDatasets.push(normalizeDataset({
        ...dataset,
        stories: nextStories,
        updatedAt: nowIso(),
      }));
    }
  }

  return touchStore({
    ...store,
    datasets: sortDatasetsByDateInternal(nextDatasets),
  });
}

export function getVisibleCustomIntelFeatures(
  store: CustomIntelStore
): GeoJSON.FeatureCollection<GeoJSON.Point, CustomIntelFeatureProperties> {
  const features: GeoJSON.Feature<GeoJSON.Point, CustomIntelFeatureProperties>[] = [];

  for (const dataset of store.datasets) {
    if (!dataset.visible) continue;
    const datasetFc = flattenCustomIntelEvents(dataset.stories);

    for (const feature of datasetFc.features) {
      const props = feature.properties;
      features.push({
        ...feature,
        properties: {
          ...props,
          dataset_id: dataset.datasetId,
          dataset_title: dataset.title,
          weight: normalizeWeight(props.weight),
        },
      });
    }
  }

  return {
    type: "FeatureCollection",
    features,
  };
}

export function getCustomIntelSummary(store: CustomIntelStore): { datasets: number; stories: number; events: number } {
  const stories = store.datasets.reduce((sum, d) => sum + d.stories.length, 0);
  const events = store.datasets.reduce((sum, d) => sum + d.eventCount, 0);
  return {
    datasets: store.datasets.length,
    stories,
    events,
  };
}

export function getDatasetLatestDateLabel(dataset: CustomIntelDataset): string {
  const iso = dataset.latestEventDate || dataset.updatedAt || dataset.createdAt;
  const ms = parseDateValue(iso);
  if (!ms) return "N/A";
  return new Date(ms).toISOString().slice(0, 10);
}

function timestampForFilename(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}-${hh}${mi}${ss}`;
}

export function exportCustomIntelStore(store: CustomIntelStore): void {
  const normalized = migrateCustomIntelStore(store);
  const json = JSON.stringify(normalized, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `custom-intel-store-${timestampForFilename()}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function copyCustomIntelStoreToClipboard(store: CustomIntelStore): Promise<void> {
  const normalized = migrateCustomIntelStore(store);
  const json = JSON.stringify(normalized, null, 2);
  await navigator.clipboard.writeText(json);
}

export function validateCustomIntelStore(input: unknown): input is CustomIntelStore {
  if (!isRecord(input)) return false;
  if (!Array.isArray(input.datasets)) return false;
  if (typeof input.version !== "number") return false;
  return true;
}

export function migrateCustomIntelStore(input: unknown): CustomIntelStore {
  if (!validateCustomIntelStore(input)) {
    return createEmptyCustomIntelStore();
  }

  const inStore = input as CustomIntelStore;
  const used = new Set<string>();
  const datasets: CustomIntelDataset[] = [];

  for (const raw of inStore.datasets) {
    const normalized = normalizeDataset(raw, generateDatasetId());
    const datasetId = ensureUniqueDatasetId(normalized.datasetId, used);
    datasets.push({ ...normalized, datasetId });
  }

  return {
    version: CUSTOM_INTEL_STORE_VERSION,
    updatedAt: toSafeString(inStore.updatedAt, nowIso()),
    datasets: sortDatasetsByDateInternal(datasets),
  };
}

export function loadCustomIntelStore(): CustomIntelStore {
  if (typeof window === "undefined") return createEmptyCustomIntelStore();
  const raw = window.localStorage.getItem(CUSTOM_INTEL_STORAGE_KEY);
  if (!raw) return createEmptyCustomIntelStore();

  try {
    const parsed = JSON.parse(raw);
    return migrateCustomIntelStore(parsed);
  } catch {
    return createEmptyCustomIntelStore();
  }
}

export function saveCustomIntelStore(store: CustomIntelStore): void {
  if (typeof window === "undefined") return;
  const normalized = migrateCustomIntelStore(store);
  window.localStorage.setItem(CUSTOM_INTEL_STORAGE_KEY, JSON.stringify(normalized));
}

export function mergeCustomIntelStores(current: CustomIntelStore, incoming: CustomIntelStore): CustomIntelStore {
  const a = migrateCustomIntelStore(current);
  const b = migrateCustomIntelStore(incoming);

  const used = new Set(a.datasets.map((d) => d.datasetId));
  const merged = [...a.datasets];

  for (const dataset of b.datasets) {
    const nextId = ensureUniqueDatasetId(dataset.datasetId, used);
    merged.push(normalizeDataset({ ...dataset, datasetId: nextId }));
  }

  return touchStore({
    version: CUSTOM_INTEL_STORE_VERSION,
    updatedAt: nowIso(),
    datasets: sortDatasetsByDateInternal(merged),
  });
}

export function replaceCustomIntelStore(incoming: CustomIntelStore): CustomIntelStore {
  return touchStore(migrateCustomIntelStore(incoming));
}

export function importCustomIntelStore(
  current: CustomIntelStore,
  input: unknown,
  mode: CustomIntelImportMode
): CustomIntelStore {
  const incoming = migrateCustomIntelStore(input);
  if (mode === "replace") return replaceCustomIntelStore(incoming);
  return mergeCustomIntelStores(current, incoming);
}
