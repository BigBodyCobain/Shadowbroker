import type {
  CustomIntelEvent,
  CustomIntelFeatureProperties,
  CustomIntelImpactZone,
  CustomIntelInput,
  CustomIntelSourceLink,
  CustomIntelStory,
  CustomIntelSummary,
} from "@/types/dashboard";

interface ParsedCustomIntel {
  stories: CustomIntelStory[];
  features: GeoJSON.FeatureCollection<GeoJSON.Point, CustomIntelFeatureProperties>;
  summary: CustomIntelSummary;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function toStringOrEmpty(v: unknown): string {
  return typeof v === "string" ? v.trim() : "";
}

function toWeight(v: unknown): number {
  if (typeof v !== "number" || !Number.isFinite(v)) return 1;
  return Math.max(1, Math.min(5, Math.round(v)));
}

function toConfidence(v: unknown): number | undefined {
  if (typeof v !== "number" || !Number.isFinite(v)) return undefined;
  return v;
}

function toValidSourceLinks(raw: unknown): CustomIntelSourceLink[] {
  if (!Array.isArray(raw)) return [];

  const links: CustomIntelSourceLink[] = [];
  for (const item of raw) {
    if (!isRecord(item)) continue;
    const name = toStringOrEmpty(item.name);
    const url = toStringOrEmpty(item.url);
    if (!name || !url) continue;

    try {
      const parsed = new URL(url);
      if (!["http:", "https:"].includes(parsed.protocol)) continue;
      links.push({ name, url: parsed.toString() });
    } catch {
      continue;
    }
  }

  return links;
}

function toImpactZones(raw: unknown): CustomIntelImpactZone[] {
  if (!Array.isArray(raw)) return [];
  const zones: CustomIntelImpactZone[] = [];

  for (const item of raw) {
    if (!isRecord(item)) continue;
    const products = Array.isArray(item.products)
      ? item.products.filter((p): p is string => typeof p === "string" && p.trim().length > 0)
      : [];

    zones.push({
      type: toStringOrEmpty(item.type),
      name: toStringOrEmpty(item.name),
      scope: toStringOrEmpty(item.scope),
      products,
    });
  }

  return zones;
}

function toEvent(raw: unknown): CustomIntelEvent | null {
  if (!isRecord(raw)) return null;

  const geo = isRecord(raw.geo) ? raw.geo : null;
  const lat = geo && typeof geo.lat === "number" ? geo.lat : NaN;
  const lng = geo && typeof geo.lng === "number" ? geo.lng : NaN;

  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;

  return {
    id: toStringOrEmpty(raw.id) || undefined,
    type: toStringOrEmpty(raw.type) || "unknown",
    name: toStringOrEmpty(raw.name) || "Unnamed Event",
    location_label: toStringOrEmpty(raw.location_label) || "Unknown Location",
    geo: { lat, lng },
    date: toStringOrEmpty(raw.date) || undefined,
    start_date: toStringOrEmpty(raw.start_date) || undefined,
    end_date: toStringOrEmpty(raw.end_date) || undefined,
    description: toStringOrEmpty(raw.description) || undefined,
    weight: toWeight(raw.weight),
    confidence: toConfidence(raw.confidence),
    sources: toValidSourceLinks(raw.sources),
  };
}

export function parseCustomIntelInput(raw: string): unknown {
  const trimmed = raw.trim();
  if (!trimmed) {
    throw new Error("Paste JSON to populate Custom Intel.");
  }

  try {
    return JSON.parse(trimmed);
  } catch {
    throw new Error("Invalid JSON. Check syntax and try again.");
  }
}

export function normalizeCustomIntelStories(input: CustomIntelInput): CustomIntelStory[] {
  const storiesRaw = Array.isArray(input) ? input : [input];
  const stories: CustomIntelStory[] = [];

  for (const item of storiesRaw) {
    const validated = validateCustomIntelStory(item);
    if (validated) stories.push(validated);
  }

  return stories;
}

export function validateCustomIntelStory(story: unknown): CustomIntelStory | null {
  if (!isRecord(story)) return null;

  const storyId = toStringOrEmpty(story.story_id);
  const title = toStringOrEmpty(story.title);
  const rawEvents = Array.isArray(story.events) ? story.events : [];

  if (!storyId || !title || rawEvents.length === 0) return null;

  const events = rawEvents
    .map(toEvent)
    .filter((e): e is CustomIntelEvent => Boolean(e));

  if (events.length === 0) return null;

  return {
    story_id: storyId,
    title,
    events,
    impact_zones: toImpactZones(story.impact_zones),
  };
}

export function flattenCustomIntelEvents(
  stories: CustomIntelStory[]
): GeoJSON.FeatureCollection<GeoJSON.Point, CustomIntelFeatureProperties> {
  const features: GeoJSON.Feature<GeoJSON.Point, CustomIntelFeatureProperties>[] = [];

  for (const story of stories) {
    story.events.forEach((event, eventIndex) => {
      const eventId = event.id && event.id.trim().length > 0 ? event.id : `${story.story_id}-${eventIndex}`;
      const weight = toWeight(event.weight);

      features.push({
        type: "Feature",
        properties: {
          id: eventId,
          type: "custom_intel_event",
          story_id: story.story_id,
          story_title: story.title,
          event_id: eventId,
          event_type: event.type,
          event_name: event.name,
          location_label: event.location_label,
          date: event.date,
          start_date: event.start_date,
          end_date: event.end_date,
          description: event.description,
          weight,
          confidence: toConfidence(event.confidence),
          sources: event.sources?.length ? event.sources : undefined,
          source_count: event.sources?.length ? event.sources.length : undefined,
          lat: event.geo.lat,
          lng: event.geo.lng,
        },
        geometry: {
          type: "Point",
          coordinates: [event.geo.lng, event.geo.lat],
        },
      });
    });
  }

  return {
    type: "FeatureCollection",
    features,
  };
}

export function parseAndBuildCustomIntel(raw: string): ParsedCustomIntel {
  const parsed = parseCustomIntelInput(raw);

  if (!isRecord(parsed) && !Array.isArray(parsed)) {
    throw new Error("Custom Intel JSON must be an object or an array of objects.");
  }

  const stories = normalizeCustomIntelStories(parsed as CustomIntelInput);
  if (stories.length === 0) {
    throw new Error("No valid stories found. Ensure each story has story_id, title, and at least one event with geo.lat/lng.");
  }

  const features = flattenCustomIntelEvents(stories);
  if (features.features.length === 0) {
    throw new Error("No valid events found to map.");
  }

  return {
    stories,
    features,
    summary: {
      stories: stories.length,
      events: features.features.length,
    },
  };
}
