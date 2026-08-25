/**
 * voiceGroundingTypes — the `sb.grounding.v1` client grounding-snapshot
 * contract (voice-agent plan §2.4 / U5).
 *
 * Composed client-side from the operator's actual store (never screenshots);
 * ≤6 KB serialized; truncated entities-first, then news verdicts. The backend
 * validates this schema on receipt (`validate_grounding_snapshot`) and uses it
 * both as the picker-loop grounding header source and the hud-summary input.
 */

export const GROUNDING_SCHEMA_ID = 'sb.grounding.v1';
export const GROUNDING_SNAPSHOT_MAX_BYTES = 6 * 1024;

export type FreshnessDispositionValue = 'live' | 'aging' | 'stale' | 'unknown';

export interface GroundingView {
  /** Coarsened viewport bounds [south, west, north, east]; null = world zoom. */
  bounds: { south: number; west: number; north: number; east: number } | null;
  zoom: number | null;
  scale_class: 'world' | 'region' | 'local';
}

export interface GroundingEntityRef {
  id: string;
  name: string;
  layer: string;
}

export interface GroundingNewsVerdict {
  title: string;
  sentiment: number | null;
  bucket: 'NEGATIVE' | 'POSITIVE' | 'NEUTRAL';
  machine_assessment: string;
}

export interface GroundingFreshnessEntry {
  age_s: number | null;
  disposition: FreshnessDispositionValue;
  expected_cadence_s: number | null;
}

export interface GroundingHealthEntry {
  ok: boolean;
  error: string | null;
}

/** The wire object. Kept structurally open so backend additions never break
 *  composition, but every declared field is honest and bounded. */
export interface GroundingSnapshot {
  schema: typeof GROUNDING_SCHEMA_ID;
  generated_at: string;
  view: GroundingView;
  session: { mode: string | null };
  layers: { active: string[]; inactive_count: number };
  counts: Record<string, number>;
  entities: GroundingEntityRef[];
  correlations: Array<Record<string, unknown>>;
  verdicts: { news: GroundingNewsVerdict[] };
  freshness: Record<string, GroundingFreshnessEntry>;
  health: Record<string, GroundingHealthEntry>;
}

export interface HudSummaryResponse {
  ok: boolean;
  summary: string;
  model?: string;
  generated_at?: string;
  mode: 'full' | 'mesh_lean';
  deduped?: boolean;
}
