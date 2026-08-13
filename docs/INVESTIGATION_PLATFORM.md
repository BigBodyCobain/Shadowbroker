# Intelligence Investigation Platform

ShadowBroker is evolving from a real-time OSINT map dashboard into an
**intelligence investigation platform**. The map remains central, but it is now
a visualization/analysis surface for a structured investigation workflow:

```
QUESTION → INVESTIGATION → EVIDENCE → CORRELATION → ANALYSIS → HYPOTHESIS → HUMAN DECISION
```

This document describes the investigation layer added on top of the existing
aggregator. **The live telemetry pipeline, map, mesh, and agent channel are
unchanged** — the investigation layer is additive.

---

## Core primitives

The domain model (`backend/domain/`) introduces first-class analytical objects
the aggregator previously lacked:

| Primitive | Purpose |
|---|---|
| **Source** | Provenance origin (feed/api/channel/document). Untrusted by default. |
| **Entity** | A stable, identified thing (aircraft, vessel, person, org, IP…) with a natural key so repeated observations resolve to one entity. |
| **Observation** | A raw, timestamped, source-attributed measurement of an entity. Always a fact. |
| **Event** | A meaningful occurrence derived from observations, with an explanation of *why* it exists. |
| **Relationship** | A typed edge between entities. |
| **Investigation** | An analyst workspace grouping a question, entities, events and evidence. |
| **Evidence** | An artifact (with provenance + classification) supporting or contradicting an event/hypothesis. |
| **Hypothesis** | An inference — **always** classified as a hypothesis, never a fact. |
| **Alert** | A meaningful change: what / when / where / why it matters / evidence / confidence. |

### Fact vs inference is structural

Every analytic product carries a `Classification` on an epistemic ladder:

```
raw_observation → derived_event → analysis → hypothesis
   (fact)            (fact)      (inference)  (inference)
```

This is enforced in the data layer (`domain/classification.py`) and surfaced in
the UI with distinct visual treatment (facts solid/cyan, analysis amber,
hypotheses dashed/violet). A hypothesis can never be reclassified below the
inference line.

### Provenance travels with the data

`Provenance` records `source`, `source_url`, `observed_at` (when it happened)
and `ingested_at` (when we recorded it) — kept distinct to avoid re-stamping
stale data as "now". Every observation and evidence item can answer *"where did
this come from?"*.

### Confidence is explainable and honest

`domain/confidence.py` combines enumerated supporting/contradicting factors in
log-odds space from a neutral prior. It is:

- **bounded** — never claims certainty (clamped to 5–95%);
- **monotonic** — more support never lowers, more contradiction never raises;
- **symmetric** and **deterministic**;
- **degrading** — below a minimum evidence mass it returns a *qualitative*
  label instead of a fabricated number.

Hypothesis confidence is derived from its linked evidence (weighted by each
item's classification), so the number is always explainable.

---

## Storage

`backend/storage/` is a thread-safe SQLite repository (WAL) using a
**document + projected columns** layout: the full model JSON lives in a `doc`
column plus a few indexed columns (type, investigation_id, lat/lng, timestamps)
for spatial-lite and time-range queries.

SQLite was chosen deliberately over Postgres/PostGIS/Redis: investigation
artifacts are low-volume analyst products, not the telemetry firehose, and
SQLite is already a project dependency. The live in-memory telemetry store is
untouched. DB path defaults to `backend/data/investigations.db`
(override with `INVESTIGATION_DB_PATH`).

---

## REST API

All routes require **local-operator** authorization (loopback or admin key;
the Next.js proxy injects the admin key for these prefixes). Rate-limited.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/investigations` | List investigations |
| POST | `/api/investigations` | Create |
| GET | `/api/investigations/{id}` | Full bundle (entities, events, evidence, hypotheses, notes, timeline) |
| PATCH | `/api/investigations/{id}` | Update |
| DELETE | `/api/investigations/{id}` | Delete (cascades evidence/hypotheses/notes) |
| POST | `/api/investigations/{id}/entities` | Attach entity (by id, or ingest a live telemetry record) |
| POST | `/api/investigations/{id}/events` | Add a derived event |
| POST | `/api/investigations/{id}/evidence` | Attach evidence |
| POST | `/api/investigations/{id}/hypotheses` | Create hypothesis (confidence derived from evidence) |
| PATCH | `/api/investigations/{id}/hypotheses/{hid}` | Update hypothesis |
| POST | `/api/investigations/{id}/notes` | Add note |
| GET | `/api/investigations/{id}/timeline` | Merged chronological timeline |
| GET | `/api/investigations/{id}/briefing` | Structured, fact/inference-separated briefing |
| GET | `/api/entities/search` | Search stored entities |
| GET | `/api/entities/{id}` | Entity + observations + relationships |
| GET | `/api/domain/stats` | Store counts |

---

## AI analyst tool layer

The AI operates as an analyst **over structured data**, never by scraping the
UI. `backend/agents/` provides a typed tool registry exposed at:

- `GET /api/agent/tools` — machine-readable manifest with typed schemas and the
  caller's granted scopes.
- `POST /api/agent/tools/invoke` — validated, scope-enforced, audited invocation
  returning a structured `{ok, tool, scope, data, error, meta}` envelope.
- `GET /api/agent/audit` — recent tool-call audit trail.

Tools include `search_entities`, `get_entity`, `search_events`,
`get_events_near_location`, `get_activity_timeline`, `compare_time_ranges`,
`find_anomalies` (bridges the correlation engine to explainable events),
`get_evidence`, `generate_briefing`, plus write tools `create_investigation`,
`update_investigation`, `add_event`, `add_evidence`, `create_hypothesis`.

**Authorization** is per-tool by scope (`read` / `write` / `act`), derived from
the existing coarse `OPENCLAW_ACCESS_TIER` setting but enforced per tool — an
upgrade over the previous single global boolean. Every call is schema-validated
and written to the audit log.

**Prompt-injection defense (`agents/untrusted.py`):** all external OSINT content
returned by tools is wrapped in an untrusted-data envelope
(`_untrusted_external_data: true`, source, `suspected_injection` flag). External
text is DATA, never instructions. Suspicious content is *flagged, not silently
mutated*, so evidence is preserved and auditable.

---

## Correlation → events

`domain/correlation_adapter.py` maps the existing correlation engine's alerts
into `analysis`-classified `Event`s. Each carries the engine's `drivers` as an
explanation ("Correlated because: …") and an evidence-derived, bounded
confidence — no black-box conclusions.

---

## Frontend

The **Investigation Workspace** (`frontend/src/components/investigation/`) is a
full-screen overlay opened from the map's **⌕ Investigate** button. It provides:

- an investigation list + create form;
- a tabbed detail view: Overview, Timeline, Entities, Evidence, Hypotheses,
  Briefing;
- fact/inference visual separation (`ClassificationBadge`) and explainable
  confidence (`ConfidenceMeter`) throughout;
- "Show on map" actions that reuse the main MapLibre map's fly-to;
- proper loading / empty / error states everywhere.

The existing single-page map app is otherwise unchanged.

---

## Testing

- Backend: `domain`, `storage`, confidence, investigation API, agent tools,
  injection boundary, correlation engine (first coverage), and the P0 security
  fixes are unit- and API-tested (see `backend/tests/test_confidence.py`,
  `test_domain_models.py`, `test_investigation_store.py`,
  `test_investigations_api.py`, `test_agent_tools.py`, `test_agent_tools_api.py`,
  `test_correlation_engine.py`, `test_security_hardening.py`).
- Frontend: `src/__tests__/investigation/` covers the primitives and API client.

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `INVESTIGATION_DB_PATH` | `backend/data/investigations.db` | SQLite path for the investigation store |
| `OPENCLAW_ACCESS_TIER` | `restricted` | `restricted` → AI tools get read scope only; `full` → read+write+act |
| `MESH_PEER_PUSH_SECRET` | *(unset → per-node auto-generated)* | Fleet peer-push HMAC; **never commit a shared value** |
