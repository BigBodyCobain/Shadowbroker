// Types for the Intelligence Investigation platform (mirror of the backend
// domain models in backend/domain/).

export type Classification =
  | 'raw_observation'
  | 'derived_event'
  | 'analysis'
  | 'hypothesis';

export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical';

export type InvestigationStatus =
  | 'open'
  | 'active'
  | 'on_hold'
  | 'closed'
  | 'archived';

export type HypothesisStatus =
  | 'proposed'
  | 'supported'
  | 'contradicted'
  | 'confirmed'
  | 'refuted'
  | 'inconclusive';

export interface ConfidenceFactor {
  label: string;
  weight: number;
  note?: string;
}

export interface Confidence {
  score: number | null;
  percent: number | null;
  label: string;
  qualitative: boolean;
  method: string;
  supporting: ConfidenceFactor[];
  contradicting: ConfidenceFactor[];
  rationale: string;
}

export interface Provenance {
  source_id: string | null;
  source_name: string;
  source_url: string;
  observed_at: string | null;
  ingested_at: string;
  method: string;
  note: string;
}

export interface Investigation {
  id: string;
  title: string;
  question: string;
  description: string;
  status: InvestigationStatus;
  author: string;
  tags: string[];
  entity_ids: string[];
  event_ids: string[];
  focus: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Entity {
  id: string;
  type: string;
  label: string;
  canonical_key: string;
  aliases: string[];
  lat: number | null;
  lng: number | null;
  first_seen: string;
  last_seen: string;
  attributes: Record<string, unknown>;
}

export interface DomainEvent {
  id: string;
  type: string;
  title: string;
  summary: string;
  classification: Classification;
  occurred_at: string | null;
  lat: number | null;
  lng: number | null;
  severity: Severity;
  entity_ids: string[];
  evidence_ids: string[];
  explanation: string;
  confidence: Confidence;
  created_at: string;
}

export interface Evidence {
  id: string;
  investigation_id: string | null;
  kind: string;
  title: string;
  description: string;
  classification: Classification;
  provenance: Provenance;
  lat: number | null;
  lng: number | null;
  occurred_at: string | null;
  ref_type: string;
  ref_id: string;
  confidence: Confidence;
  created_at: string;
  created_by: string;
}

export interface Hypothesis {
  id: string;
  investigation_id: string | null;
  statement: string;
  status: HypothesisStatus;
  classification: 'hypothesis';
  confidence: Confidence;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  author: string;
  created_at: string;
  updated_at: string;
}

export interface Note {
  id: string;
  investigation_id: string | null;
  body: string;
  author: string;
  created_at: string;
}

export interface TimelineItem {
  ts: string | null;
  kind: string;
  classification: Classification;
  title: string;
  summary?: string;
  lat?: number | null;
  lng?: number | null;
  severity?: string;
  source?: string;
  ref_id: string;
}

export interface InvestigationBundle {
  investigation: Investigation;
  entities: Entity[];
  events: DomainEvent[];
  evidence: Evidence[];
  hypotheses: Hypothesis[];
  notes: Note[];
  timeline: TimelineItem[];
  counts: {
    entities: number;
    events: number;
    evidence: number;
    hypotheses: number;
    notes: number;
  };
}

export interface Briefing {
  investigation: { id: string; title: string; question: string; status: string };
  generated_at: string;
  summary: {
    question: string;
    entities: number;
    facts: number;
    inferences: number;
    hypotheses: number;
  };
  key_facts: Array<{ title: string; classification: string; source: string; id: string }>;
  analysis: Array<{ title: string; description: string; classification: string; id: string }>;
  hypotheses: Array<{
    statement: string;
    status: string;
    classification: string;
    confidence: Confidence;
    supporting: string[];
    contradicting: string[];
  }>;
  contradicting_evidence: Array<{ title: string; classification: string; id: string }>;
  entities: Array<{ id: string; type: string; label: string }>;
  events: Array<{ id: string; type: string; title: string; classification: string }>;
  timeline: TimelineItem[];
  recommended_next_steps: string[];
  caveat: string;
}

export const CLASSIFICATION_META: Record<
  Classification,
  { label: string; kind: 'fact' | 'inference'; short: string }
> = {
  raw_observation: { label: 'Raw observation', kind: 'fact', short: 'FACT' },
  derived_event: { label: 'Derived event', kind: 'fact', short: 'DERIVED' },
  analysis: { label: 'Analysis', kind: 'inference', short: 'ANALYSIS' },
  hypothesis: { label: 'Hypothesis', kind: 'inference', short: 'HYPOTHESIS' },
};
