import { flattenCustomIntelEvents, parseAndBuildCustomIntel } from "@/lib/customIntel";
import type {
  CustomIntelDataset,
  CustomIntelEvent,
  CustomIntelFeatureProperties,
  CustomIntelMasterEvent,
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

const WEIGHT_TO_LEVEL: Record<number, number> = {
  1: 2,
  2: 4,
  3: 6,
  4: 8,
  5: 10,
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

export function getCustomIntelLevelLabel(weight?: number): string {
  const normalized = normalizeWeight(weight);
  return `${WEIGHT_TO_LEVEL[normalized]}/10`;
}

function parseDateValue(value?: string): number | null {
  if (!value) return null;
  const t = Date.parse(value);
  return Number.isFinite(t) ? t : null;
}

function eventDateMs(event: Pick<CustomIntelEvent, "date" | "end_date" | "start_date">): number | null {
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

function resolveEventId(storyId: string, eventId: string | undefined, index: number): string {
  return eventId && eventId.trim().length > 0 ? eventId : `${storyId}-${index}`;
}

function normalizeDedupeText(value?: string): string {
  return (value || "").trim().toLowerCase();
}

function normalizeCoord(value: number): string {
  return value.toFixed(5);
}

function getStoryEventKey(story: CustomIntelStory, event: CustomIntelEvent): string {
  const explicitId = toSafeString(event.id);
  if (explicitId) {
    return `${normalizeDedupeText(story.story_id)}:${normalizeDedupeText(explicitId)}`;
  }

  const fallbackDate = event.date || event.start_date || event.end_date || "";
  return [
    normalizeDedupeText(event.name),
    normalizeDedupeText(event.type),
    normalizeDedupeText(fallbackDate),
    normalizeCoord(event.geo.lat),
    normalizeCoord(event.geo.lng),
  ].join(":");
}

export function getCustomIntelEventKey(event: Pick<CustomIntelMasterEvent, "story_id" | "event_id" | "explicitEventId" | "name" | "type" | "date" | "start_date" | "end_date" | "geo">): string {
  if (event.explicitEventId) {
    return `${normalizeDedupeText(event.story_id)}:${normalizeDedupeText(event.event_id)}`;
  }

  const fallbackDate = event.date || event.start_date || event.end_date || "";
  return [
    normalizeDedupeText(event.name),
    normalizeDedupeText(event.type),
    normalizeDedupeText(fallbackDate),
    normalizeCoord(event.geo.lat),
    normalizeCoord(event.geo.lng),
  ].join(":");
}

function toMasterEvent(
  dataset: CustomIntelDataset,
  story: CustomIntelStory,
  event: CustomIntelEvent,
  eventIndex: number
): CustomIntelMasterEvent {
  const eventId = resolveEventId(story.story_id, event.id, eventIndex);
  const explicitEventId = Boolean(event.id && event.id.trim().length > 0);
  const dedupeKey = explicitEventId
    ? `${normalizeDedupeText(story.story_id)}:${normalizeDedupeText(eventId)}`
    : getStoryEventKey(story, event);

  return {
    masterEventId: `${dataset.datasetId}::${story.story_id}::${eventId}`,
    datasetId: dataset.datasetId,
    story_id: story.story_id,
    story_title: story.title,
    event_id: eventId,
    type: event.type,
    name: event.name,
    location_label: event.location_label,
    geo: {
      lat: event.geo.lat,
      lng: event.geo.lng,
    },
    date: event.date,
    start_date: event.start_date,
    end_date: event.end_date,
    description: event.description,
    weight: normalizeWeight(event.weight),
    confidence: event.confidence,
    sources: event.sources?.length ? event.sources : undefined,
    explicitEventId,
    dedupeKey,
    createdAt: dataset.createdAt,
    updatedAt: dataset.updatedAt,
  };
}

export function getEventSortTimestamp(event: Pick<CustomIntelMasterEvent, "date" | "end_date" | "start_date" | "updatedAt" | "createdAt">): number {
  return (
    parseDateValue(event.date) ??
    parseDateValue(event.end_date) ??
    parseDateValue(event.start_date) ??
    parseDateValue(event.updatedAt) ??
    parseDateValue(event.createdAt) ??
    0
  );
}

export function sortMasterEvents(events: CustomIntelMasterEvent[]): CustomIntelMasterEvent[] {
  return [...events].sort((a, b) => {
    const aw = normalizeWeight(a.weight);
    const bw = normalizeWeight(b.weight);
    if (bw !== aw) return bw - aw;

    const ad = getEventSortTimestamp(a);
    const bd = getEventSortTimestamp(b);
    if (bd !== ad) return bd - ad;

    return a.masterEventId.localeCompare(b.masterEventId);
  });
}

export function dedupeCustomIntelEvents(events: CustomIntelMasterEvent[]): CustomIntelMasterEvent[] {
  const map = new Map<string, CustomIntelMasterEvent>();
  for (const event of events) {
    const key = event.dedupeKey || getCustomIntelEventKey(event);
    if (!map.has(key)) {
      map.set(key, { ...event, dedupeKey: key });
    }
  }
  return sortMasterEvents(Array.from(map.values()));
}

export function flattenCustomIntelEventsFromDatasets(store: Pick<CustomIntelStore, "datasets">): CustomIntelMasterEvent[] {
  const masterEvents: CustomIntelMasterEvent[] = [];

  for (const dataset of store.datasets) {
    for (const story of dataset.stories) {
      for (let i = 0; i < story.events.length; i += 1) {
        masterEvents.push(toMasterEvent(dataset, story, story.events[i], i));
      }
    }
  }

  return dedupeCustomIntelEvents(masterEvents);
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

function withSyncedMasterEvents(
  store: CustomIntelStore,
  options?: { touchUpdatedAt?: boolean }
): CustomIntelStore {
  const touchUpdatedAt = options?.touchUpdatedAt ?? false;
  return {
    ...store,
    version: CUSTOM_INTEL_STORE_VERSION,
    masterEvents: flattenCustomIntelEventsFromDatasets(store),
    updatedAt: touchUpdatedAt ? nowIso() : toSafeString(store.updatedAt, nowIso()),
  };
}

export function createEmptyCustomIntelStore(): CustomIntelStore {
  return {
    version: CUSTOM_INTEL_STORE_VERSION,
    masterEvents: [],
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
  const existingEventKeys = new Set(store.masterEvents.map((event) => event.dedupeKey || getCustomIntelEventKey(event)));
  const seenIncoming = new Set<string>();
  const dedupedStories = normalized.stories
    .map((story) => {
      const events = story.events.filter((event) => {
        const key = getStoryEventKey(story, event);
        if (existingEventKeys.has(key) || seenIncoming.has(key)) return false;
        seenIncoming.add(key);
        return true;
      });
      return events.length > 0 ? { ...story, events } : null;
    })
    .filter((story): story is CustomIntelStory => Boolean(story));

  if (!dedupedStories.length) {
    return store;
  }

  const dedupedDataset = normalizeDataset({ ...normalized, stories: dedupedStories });
  const withUniqueId = { ...dedupedDataset, datasetId: ensureUniqueDatasetId(dedupedDataset.datasetId, used) };

  return withSyncedMasterEvents({
    ...store,
    datasets: sortDatasetsByDateInternal([...store.datasets, withUniqueId]),
  }, { touchUpdatedAt: true });
}

export function removeCustomIntelDataset(store: CustomIntelStore, datasetId: string): CustomIntelStore {
  return withSyncedMasterEvents({
    ...store,
    datasets: store.datasets.filter((d) => d.datasetId !== datasetId),
  }, { touchUpdatedAt: true });
}

export function toggleCustomIntelDatasetVisibility(store: CustomIntelStore, datasetId: string): CustomIntelStore {
  const datasets = store.datasets.map((d) =>
    d.datasetId === datasetId ? normalizeDataset({ ...d, visible: !d.visible, updatedAt: nowIso() }) : d
  );

  return withSyncedMasterEvents({
    ...store,
    datasets,
  }, { touchUpdatedAt: true });
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
        const resolvedId = resolveEventId(story.story_id, e.id, idx);
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

  return withSyncedMasterEvents({
    ...store,
    datasets: sortDatasetsByDateInternal(nextDatasets),
  }, { touchUpdatedAt: true });
}

export function removeCustomIntelEventByMasterEventId(
  store: CustomIntelStore,
  masterEventId: string
): CustomIntelStore {
  const target = store.masterEvents.find((event) => event.masterEventId === masterEventId);
  if (!target) return store;
  return removeCustomIntelEvent(store, target.datasetId, target.event_id);
}

export function getVisibleCustomIntelFeatures(
  store: CustomIntelStore
): GeoJSON.FeatureCollection<GeoJSON.Point, CustomIntelFeatureProperties> {
  const datasetById = new Map(store.datasets.map((dataset) => [dataset.datasetId, dataset]));
  const features: GeoJSON.Feature<GeoJSON.Point, CustomIntelFeatureProperties>[] = [];

  for (const event of store.masterEvents) {
    const dataset = datasetById.get(event.datasetId);
    if (!dataset) continue;

    features.push({
      type: "Feature",
      properties: {
        id: event.event_id,
        type: "custom_intel_event",
        dataset_id: event.datasetId,
        dataset_title: dataset.title,
        story_id: event.story_id,
        story_title: event.story_title,
        event_id: event.event_id,
        event_type: event.type,
        event_name: event.name,
        location_label: event.location_label,
        date: event.date,
        start_date: event.start_date,
        end_date: event.end_date,
        description: event.description,
        weight: normalizeWeight(event.weight),
        confidence: event.confidence,
        sources: event.sources,
        source_count: event.sources?.length ? event.sources.length : undefined,
        lat: event.geo.lat,
        lng: event.geo.lng,
      },
      geometry: {
        type: "Point",
        coordinates: [event.geo.lng, event.geo.lat],
      },
    });
  }

  return {
    type: "FeatureCollection",
    features,
  };
}

export function getCustomIntelSummary(store: CustomIntelStore): { datasets: number; stories: number; events: number } {
  const stories = store.datasets.reduce((sum, d) => sum + d.stories.length, 0);
  return {
    datasets: store.datasets.length,
    stories,
    events: store.masterEvents.length,
  };
}

export function getDatasetLatestDateLabel(dataset: CustomIntelDataset): string {
  const iso = dataset.latestEventDate || dataset.updatedAt || dataset.createdAt;
  const ms = parseDateValue(iso);
  if (!ms) return "N/A";
  return new Date(ms).toISOString().slice(0, 10);
}

export function getShortLocationLabel(locationLabel?: string): string {
  if (!locationLabel || !locationLabel.trim()) return "Unknown location";
  const parts = locationLabel.split(",").map((p) => p.trim()).filter(Boolean);
  if (parts.length >= 2) return `${parts[parts.length - 2]}, ${parts[parts.length - 1]}`;
  return locationLabel;
}

export function getEventDisplayTime(event: Pick<CustomIntelMasterEvent, "date" | "start_date" | "end_date">): string {
  const primary = event.date || event.start_date || event.end_date;
  if (!primary) return "UNKNOWN";
  const parsed = new Date(primary);
  if (Number.isNaN(parsed.getTime())) return primary;

  const hasTime = /T\d{2}:\d{2}/.test(primary);
  if (hasTime) {
    return parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  return parsed.toISOString().slice(0, 10);
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
  const json = serializeCustomIntelStore(store);
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
  const json = serializeCustomIntelStore(store);
  await navigator.clipboard.writeText(json);
}

export function validateCustomIntelStore(input: unknown): input is CustomIntelStore {
  if (!isRecord(input)) return false;
  if (!Array.isArray(input.datasets)) return false;
  if (typeof input.version !== "number") return false;
  return true;
}

function normalizeStoreForPersistence(input: CustomIntelStore): CustomIntelStore {
  const used = new Set<string>();
  const datasets: CustomIntelDataset[] = [];

  for (const raw of input.datasets) {
    const normalized = normalizeDataset(raw, generateDatasetId());
    const datasetId = ensureUniqueDatasetId(normalized.datasetId, used);
    datasets.push({ ...normalized, datasetId });
  }

  return withSyncedMasterEvents({
    version: CUSTOM_INTEL_STORE_VERSION,
    updatedAt: toSafeString(input.updatedAt, nowIso()),
    datasets: sortDatasetsByDateInternal(datasets),
    masterEvents: [],
  }, { touchUpdatedAt: false });
}

export function serializeCustomIntelStore(store: CustomIntelStore): string {
  return JSON.stringify(normalizeStoreForPersistence(store), null, 2);
}

export function parseCustomIntelStore(raw: string): CustomIntelStore {
  const parsed = JSON.parse(raw);
  return migrateCustomIntelStore(parsed);
}

export function migrateCustomIntelStore(input: unknown): CustomIntelStore {
  if (!validateCustomIntelStore(input)) {
    return createEmptyCustomIntelStore();
  }
  return normalizeStoreForPersistence(input as CustomIntelStore);
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
  window.localStorage.setItem(CUSTOM_INTEL_STORAGE_KEY, serializeCustomIntelStore(store));
}

export function mergeCustomIntelStores(current: CustomIntelStore, incoming: CustomIntelStore): CustomIntelStore {
  const a = migrateCustomIntelStore(current);
  const b = migrateCustomIntelStore(incoming);

  const used = new Set(a.datasets.map((d) => d.datasetId));
  let mergedStore = a;

  for (const dataset of b.datasets) {
    const nextId = ensureUniqueDatasetId(dataset.datasetId, used);
    mergedStore = appendCustomIntelDataset(
      mergedStore,
      normalizeDataset({ ...dataset, datasetId: nextId })
    );
  }

  return withSyncedMasterEvents({
    ...mergedStore,
    updatedAt: nowIso(),
  }, { touchUpdatedAt: true });
}

export function replaceCustomIntelStore(incoming: CustomIntelStore): CustomIntelStore {
  return withSyncedMasterEvents(migrateCustomIntelStore(incoming), { touchUpdatedAt: true });
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

export function getDatasetTitleById(store: CustomIntelStore, datasetId: string): string {
  return store.datasets.find((d) => d.datasetId === datasetId)?.title || "Unknown dataset";
}

export function getDatasetVisibilityById(store: CustomIntelStore, datasetId: string): boolean {
  const dataset = store.datasets.find((d) => d.datasetId === datasetId);
  return dataset ? dataset.visible : false;
}

export function getVisibleMasterEvents(store: CustomIntelStore): CustomIntelMasterEvent[] {
  return sortMasterEvents(store.masterEvents);
}

export function flattenDatasetEvents(dataset: CustomIntelDataset): GeoJSON.FeatureCollection<GeoJSON.Point, CustomIntelFeatureProperties> {
  return flattenCustomIntelEvents(dataset.stories);
}
