"""Investigation service — domain operations over the store + live telemetry.

This is the single place that:
* creates and mutates investigations, evidence, hypotheses and notes;
* ingests *live* telemetry records into first-class Entities/Observations with
  provenance (bridging the real-time aggregator to the domain layer);
* derives explainable hypothesis confidence from linked evidence;
* assembles an investigation timeline and a structured briefing that keeps
  facts and inferences visibly separate.

Both the REST router (:mod:`routers.investigations`) and the typed AI tool
layer (:mod:`agents.tools`) call these functions, so behaviour and validation
live in one tested place.
"""

from __future__ import annotations

from typing import Any, Optional

from domain._util import coerce_iso, now_iso, valid_coord
from domain.classification import (
    Classification,
    EntityType,
    EvidenceKind,
    HypothesisStatus,
    Severity,
)
from domain.confidence import Confidence, Factor, score_confidence, unknown
from domain.models import (
    Entity,
    Event,
    Evidence,
    Hypothesis,
    Investigation,
    Note,
    Observation,
    Provenance,
    Source,
)
from storage import get_store
from storage.store import Store

# Weight a supporting/contradicting evidence item contributes to a hypothesis
# confidence, by its epistemic quality. Raw facts count more than reports.
_EVIDENCE_WEIGHT = {
    Classification.RAW_OBSERVATION: 0.7,
    Classification.DERIVED_EVENT: 0.6,
    Classification.ANALYSIS: 0.45,
    Classification.HYPOTHESIS: 0.3,
}


def _store() -> Store:
    return get_store()


# --------------------------------------------------------------------------- #
# Investigations
# --------------------------------------------------------------------------- #
def create_investigation(
    *,
    title: str,
    question: str = "",
    description: str = "",
    author: str = "analyst",
    tags: Optional[list[str]] = None,
    focus: Optional[dict] = None,
) -> Investigation:
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    inv = Investigation(
        title=title[:200],
        question=(question or "").strip()[:1000],
        description=(description or "").strip()[:5000],
        author=(author or "analyst")[:120],
        tags=[str(t)[:60] for t in (tags or [])][:32],
        focus=dict(focus or {}),
    )
    _store().upsert_investigation(inv)
    _store().audit(author, "create_investigation", scope="write", detail={"id": inv.id, "title": inv.title})
    return inv


def update_investigation(inv_id: str, *, actor: str = "analyst", **fields: Any) -> Investigation:
    inv = _store().get_investigation(inv_id)
    if inv is None:
        raise KeyError(inv_id)
    for key in ("title", "question", "description", "author"):
        if key in fields and fields[key] is not None:
            setattr(inv, key, str(fields[key]))
    if "status" in fields and fields["status"]:
        from domain.classification import InvestigationStatus

        inv.status = InvestigationStatus.coerce(fields["status"])
    if "tags" in fields and fields["tags"] is not None:
        inv.tags = [str(t)[:60] for t in fields["tags"]][:32]
    if "focus" in fields and fields["focus"] is not None:
        inv.focus = dict(fields["focus"])
    _store().upsert_investigation(inv)
    _store().audit(actor, "update_investigation", scope="write", detail={"id": inv.id})
    return inv


def list_investigations(*, status: str = "", limit: int = 100) -> list[Investigation]:
    return _store().list_investigations(status=status, limit=limit)


def delete_investigation(inv_id: str, *, actor: str = "analyst") -> bool:
    ok = _store().delete_investigation(inv_id)
    if ok:
        _store().audit(actor, "delete_investigation", scope="write", detail={"id": inv_id})
    return ok


def get_investigation_bundle(inv_id: str) -> dict:
    """Full workspace payload: investigation + members + timeline + confidence."""
    st = _store()
    inv = st.get_investigation(inv_id)
    if inv is None:
        raise KeyError(inv_id)
    entities = [st.get_entity(eid) for eid in inv.entity_ids]
    entities = [e for e in entities if e is not None]
    events = [st.get_event(eid) for eid in inv.event_ids]
    events = [e for e in events if e is not None]
    evidence = st.evidence_for_investigation(inv_id)
    hypotheses = st.hypotheses_for_investigation(inv_id)
    notes = st.notes_for_investigation(inv_id)
    timeline = build_timeline(inv_id)
    return {
        "investigation": inv.to_dict(),
        "entities": [e.to_dict() for e in entities],
        "events": [e.to_dict() for e in events],
        "evidence": [e.to_dict() for e in evidence],
        "hypotheses": [h.to_dict() for h in hypotheses],
        "notes": [n.to_dict() for n in notes],
        "timeline": timeline,
        "counts": {
            "entities": len(entities),
            "events": len(events),
            "evidence": len(evidence),
            "hypotheses": len(hypotheses),
            "notes": len(notes),
        },
    }


# --------------------------------------------------------------------------- #
# Entities / Observations (bridge from live telemetry)
# --------------------------------------------------------------------------- #
def _ensure_source(name: str, *, kind: str = "feed", url: str = "", trusted: bool = False) -> Source:
    """Idempotently register a Source by name (deterministic id)."""
    from domain._util import canonical_id

    sid = canonical_id("src", name)
    st = _store()
    existing = st.get_source(sid)
    if existing:
        existing.last_seen = now_iso()
        st.upsert_source(existing)
        return existing
    src = Source(id=sid, kind=kind, name=name or "unknown", url=url, trusted=trusted)
    st.upsert_source(src)
    return src


# Untrusted-by-default: content scraped/relayed from these origins must never be
# treated as trusted instructions. Trust is a property of the SOURCE, not the text.
_TRUSTED_SOURCE_HINTS = ("opensky", "adsb", "ais", "aisstream", "satellite", "sentinel", "usni", "noaa", "usgs")


def _source_trusted(name: str) -> bool:
    low = (name or "").lower()
    return any(h in low for h in _TRUSTED_SOURCE_HINTS)


def ingest_entity_from_record(
    record: dict,
    *,
    entity_type: str,
    layer: str = "",
    source_name: str = "",
) -> Entity:
    """Upsert an Entity (+ one Observation) from a live telemetry dict.

    Identity is resolved by a natural key (icao24/mmsi/norad/id) so repeated
    ingestions attach to one Entity. Provenance is preserved on the Observation.
    """
    et = EntityType.coerce(entity_type)
    key = str(
        record.get("icao24")
        or record.get("mmsi")
        or record.get("norad")
        or record.get("id")
        or record.get("callsign")
        or record.get("name")
        or ""
    ).strip()
    label = str(record.get("name") or record.get("callsign") or record.get("label") or key or et.value)
    coord = valid_coord(record.get("lat"), record.get("lng") if record.get("lng") is not None else record.get("lon"))
    src_name = source_name or str(record.get("source") or layer or "telemetry")
    src = _ensure_source(src_name, kind="feed", trusted=_source_trusted(src_name))

    st = _store()
    existing = st.find_entity_by_key(et.value, key) if key else None
    if existing:
        ent = existing
        ent.label = label or ent.label
        if coord:
            ent.lat, ent.lng = coord
        ent.last_seen = now_iso()
        # merge a few useful attributes without clobbering
        for k in ("registration", "model", "country", "operator", "type", "flag"):
            if record.get(k) is not None:
                ent.attributes[k] = record[k]
    else:
        ent = Entity(
            type=et,
            canonical_key=key,
            label=label,
            lat=coord[0] if coord else None,
            lng=coord[1] if coord else None,
            attributes={k: record[k] for k in ("registration", "model", "country", "operator", "type", "flag") if record.get(k) is not None},
        )
    st.upsert_entity(ent)

    obs = Observation(
        entity_id=ent.id,
        layer=layer,
        kind="position" if coord else "record",
        lat=coord[0] if coord else None,
        lng=coord[1] if coord else None,
        observed_at=coerce_iso(record.get("timestamp") or record.get("observed_at") or record.get("published")),
        provenance=Provenance(
            source_id=src.id,
            source_name=src.name,
            source_url=str(record.get("source_url") or src.url or ""),
            method=str(record.get("source") or layer or ""),
            observed_at=coerce_iso(record.get("timestamp") or record.get("published")),
        ),
        data={k: v for k, v in record.items() if k not in ("trail",) and not str(k).startswith("_")},
    )
    st.add_observation(obs)
    return ent


def add_entity_to_investigation(inv_id: str, entity_id: str, *, actor: str = "analyst") -> Investigation:
    st = _store()
    inv = st.get_investigation(inv_id)
    if inv is None:
        raise KeyError(inv_id)
    if st.get_entity(entity_id) is None:
        raise ValueError(f"unknown entity {entity_id}")
    if entity_id not in inv.entity_ids:
        inv.entity_ids.append(entity_id)
        st.upsert_investigation(inv)
        st.audit(actor, "add_entity", scope="write", detail={"investigation": inv_id, "entity": entity_id})
    return inv


def remove_entity_from_investigation(inv_id: str, entity_id: str, *, actor: str = "analyst") -> Investigation:
    st = _store()
    inv = st.get_investigation(inv_id)
    if inv is None:
        raise KeyError(inv_id)
    inv.entity_ids = [e for e in inv.entity_ids if e != entity_id]
    st.upsert_investigation(inv)
    return inv


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #
def add_event(
    inv_id: Optional[str],
    *,
    type: str,
    title: str,
    summary: str = "",
    classification: str = Classification.DERIVED_EVENT.value,
    occurred_at: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    severity: str = Severity.INFO.value,
    explanation: str = "",
    entity_ids: Optional[list[str]] = None,
    confidence: Optional[dict] = None,
    actor: str = "analyst",
) -> Event:
    try:
        cls = Classification(classification)
    except ValueError:
        cls = Classification.DERIVED_EVENT
    coord = valid_coord(lat, lng) if lat is not None and lng is not None else None
    ev = Event(
        type=str(type)[:80],
        title=str(title)[:300],
        summary=str(summary)[:2000],
        classification=cls,
        occurred_at=coerce_iso(occurred_at),
        lat=coord[0] if coord else None,
        lng=coord[1] if coord else None,
        severity=Severity.coerce(severity),
        explanation=str(explanation)[:2000],
        entity_ids=list(entity_ids or []),
        confidence=Confidence.from_dict(confidence) if confidence else unknown("event recorded without scored confidence"),
    )
    st = _store()
    st.upsert_event(ev)
    if inv_id:
        inv = st.get_investigation(inv_id)
        if inv is None:
            raise KeyError(inv_id)
        if ev.id not in inv.event_ids:
            inv.event_ids.append(ev.id)
            st.upsert_investigation(inv)
    st.audit(actor, "add_event", scope="write", detail={"investigation": inv_id, "event": ev.id})
    return ev


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #
def add_evidence(
    inv_id: str,
    *,
    kind: str = EvidenceKind.OBSERVATION.value,
    title: str,
    description: str = "",
    classification: str = Classification.RAW_OBSERVATION.value,
    provenance: Optional[dict] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    occurred_at: Optional[str] = None,
    ref_type: str = "",
    ref_id: str = "",
    confidence: Optional[dict] = None,
    data: Optional[dict] = None,
    actor: str = "analyst",
) -> Evidence:
    st = _store()
    if st.get_investigation(inv_id) is None:
        raise KeyError(inv_id)
    try:
        cls = Classification(classification)
    except ValueError:
        cls = Classification.RAW_OBSERVATION
    coord = valid_coord(lat, lng) if lat is not None and lng is not None else None
    evd = Evidence(
        investigation_id=inv_id,
        kind=EvidenceKind.coerce(kind),
        title=str(title)[:300],
        description=str(description)[:5000],
        classification=cls,
        provenance=Provenance.from_dict(provenance) if provenance else Provenance(),
        lat=coord[0] if coord else None,
        lng=coord[1] if coord else None,
        occurred_at=coerce_iso(occurred_at),
        ref_type=str(ref_type)[:40],
        ref_id=str(ref_id)[:120],
        confidence=Confidence.from_dict(confidence) if confidence else unknown("evidence recorded without scored confidence"),
        data=dict(data or {}),
        created_by=actor,
    )
    st.add_evidence(evd)
    st.audit(actor, "add_evidence", scope="write", detail={"investigation": inv_id, "evidence": evd.id})
    return evd


# --------------------------------------------------------------------------- #
# Hypotheses (confidence derived from evidence)
# --------------------------------------------------------------------------- #
def _confidence_from_evidence(
    supporting_ids: list[str], contradicting_ids: list[str]
) -> Confidence:
    st = _store()
    sup: list[Factor] = []
    con: list[Factor] = []
    for eid in supporting_ids:
        evd = st.get_evidence(eid)
        if evd is None:
            continue
        w = _EVIDENCE_WEIGHT.get(evd.classification, 0.4)
        sup.append(Factor(evd.title or evd.kind.value, weight=w, note=evd.classification.label))
    for eid in contradicting_ids:
        evd = st.get_evidence(eid)
        if evd is None:
            continue
        w = _EVIDENCE_WEIGHT.get(evd.classification, 0.4)
        con.append(Factor(evd.title or evd.kind.value, weight=w, note=evd.classification.label))
    if not sup and not con:
        return unknown("no evidence linked to hypothesis yet")
    return score_confidence(sup, con)


def create_hypothesis(
    inv_id: str,
    *,
    statement: str,
    supporting_evidence_ids: Optional[list[str]] = None,
    contradicting_evidence_ids: Optional[list[str]] = None,
    author: str = "analyst",
) -> Hypothesis:
    st = _store()
    if st.get_investigation(inv_id) is None:
        raise KeyError(inv_id)
    statement = (statement or "").strip()
    if not statement:
        raise ValueError("statement is required")
    sup = list(supporting_evidence_ids or [])
    con = list(contradicting_evidence_ids or [])
    hyp = Hypothesis(
        investigation_id=inv_id,
        statement=statement[:2000],
        supporting_evidence_ids=sup,
        contradicting_evidence_ids=con,
        confidence=_confidence_from_evidence(sup, con),
        author=author,
    )
    st.upsert_hypothesis(hyp)
    st.audit(author, "create_hypothesis", scope="write", detail={"investigation": inv_id, "hypothesis": hyp.id})
    return hyp


def update_hypothesis(
    hyp_id: str,
    *,
    statement: Optional[str] = None,
    status: Optional[str] = None,
    supporting_evidence_ids: Optional[list[str]] = None,
    contradicting_evidence_ids: Optional[list[str]] = None,
    actor: str = "analyst",
) -> Hypothesis:
    st = _store()
    hyp = st.get_hypothesis(hyp_id)
    if hyp is None:
        raise KeyError(hyp_id)
    if statement is not None:
        hyp.statement = str(statement)[:2000]
    if status is not None:
        hyp.status = HypothesisStatus.coerce(status)
    if supporting_evidence_ids is not None:
        hyp.supporting_evidence_ids = list(supporting_evidence_ids)
    if contradicting_evidence_ids is not None:
        hyp.contradicting_evidence_ids = list(contradicting_evidence_ids)
    # Recompute confidence whenever evidence links change.
    hyp.confidence = _confidence_from_evidence(hyp.supporting_evidence_ids, hyp.contradicting_evidence_ids)
    st.upsert_hypothesis(hyp)
    st.audit(actor, "update_hypothesis", scope="write", detail={"hypothesis": hyp_id})
    return hyp


# --------------------------------------------------------------------------- #
# Notes
# --------------------------------------------------------------------------- #
def add_note(inv_id: str, body: str, *, author: str = "analyst") -> Note:
    st = _store()
    if st.get_investigation(inv_id) is None:
        raise KeyError(inv_id)
    note = Note(investigation_id=inv_id, body=str(body)[:10000], author=author)
    st.add_note(note)
    return note


# --------------------------------------------------------------------------- #
# Timeline + briefing
# --------------------------------------------------------------------------- #
def build_timeline(inv_id: str) -> list[dict]:
    """Chronological, classification-tagged timeline of an investigation.

    Merges events, evidence and (per-entity) observations into one ordered
    stream so the UI can render a single temporal axis and jump to the map.
    """
    st = _store()
    inv = st.get_investigation(inv_id)
    if inv is None:
        raise KeyError(inv_id)
    items: list[dict] = []
    for eid in inv.event_ids:
        ev = st.get_event(eid)
        if ev is None:
            continue
        items.append({
            "ts": ev.occurred_at or ev.created_at,
            "kind": "event",
            "classification": ev.classification.value,
            "title": ev.title or ev.type,
            "summary": ev.summary,
            "lat": ev.lat,
            "lng": ev.lng,
            "severity": ev.severity.value,
            "ref_id": ev.id,
        })
    for evd in st.evidence_for_investigation(inv_id):
        items.append({
            "ts": evd.occurred_at or evd.created_at,
            "kind": "evidence",
            "classification": evd.classification.value,
            "title": evd.title,
            "summary": evd.description,
            "lat": evd.lat,
            "lng": evd.lng,
            "source": evd.provenance.source_name,
            "ref_id": evd.id,
        })
    items.sort(key=lambda x: x.get("ts") or "")
    return items


def generate_briefing(inv_id: str) -> dict:
    """Structured, evidence-first briefing that separates fact from inference.

    Returns sections (summary, key facts, analysis, hypotheses with confidence,
    contradicting evidence, entities, timeline, recommended next steps) rather
    than free prose — and never promotes a hypothesis to a fact.
    """
    st = _store()
    inv = st.get_investigation(inv_id)
    if inv is None:
        raise KeyError(inv_id)

    evidence = st.evidence_for_investigation(inv_id)
    hypotheses = st.hypotheses_for_investigation(inv_id)
    events = [st.get_event(e) for e in inv.event_ids]
    events = [e for e in events if e is not None]
    entities = [st.get_entity(e) for e in inv.entity_ids]
    entities = [e for e in entities if e is not None]

    facts = [e for e in evidence if e.classification.is_fact]
    inferences = [e for e in evidence if e.classification.is_inference]
    contradicting_ids: set[str] = set()
    for h in hypotheses:
        contradicting_ids.update(h.contradicting_evidence_ids)
    contradicting = [st.get_evidence(cid) for cid in contradicting_ids]
    contradicting = [c for c in contradicting if c is not None]

    # Recommended next steps: derived, deterministic, honest.
    next_steps: list[str] = []
    if not entities:
        next_steps.append("Attach the key entities involved to anchor the investigation.")
    if not facts:
        next_steps.append("Collect at least one raw observation to ground the analysis in fact.")
    for h in hypotheses:
        if not h.supporting_evidence_ids:
            next_steps.append(f"Gather supporting evidence for hypothesis: \"{h.statement[:80]}\".")
        if h.confidence.qualitative or (h.confidence.score is not None and h.confidence.score < 0.6):
            next_steps.append(f"Seek corroboration or contradiction for: \"{h.statement[:80]}\".")
    if not next_steps:
        next_steps.append("Review contradicting evidence and consider closing or escalating.")

    return {
        "investigation": {"id": inv.id, "title": inv.title, "question": inv.question, "status": inv.status.value},
        "generated_at": now_iso(),
        "summary": {
            "question": inv.question or inv.title,
            "entities": len(entities),
            "facts": len(facts),
            "inferences": len(inferences),
            "hypotheses": len(hypotheses),
        },
        "key_facts": [
            {"title": e.title, "classification": e.classification.value, "source": e.provenance.source_name, "id": e.id}
            for e in facts
        ],
        "analysis": [
            {"title": e.title, "description": e.description, "classification": e.classification.value, "id": e.id}
            for e in inferences
        ],
        "hypotheses": [
            {
                "statement": h.statement,
                "status": h.status.value,
                "classification": h.classification.value,  # always 'hypothesis'
                "confidence": h.confidence.to_dict(),
                "supporting": h.supporting_evidence_ids,
                "contradicting": h.contradicting_evidence_ids,
            }
            for h in hypotheses
        ],
        "contradicting_evidence": [
            {"title": c.title, "classification": c.classification.value, "id": c.id} for c in contradicting
        ],
        "entities": [{"id": e.id, "type": e.type.value, "label": e.label} for e in entities],
        "events": [{"id": e.id, "type": e.type, "title": e.title, "classification": e.classification.value} for e in events],
        "timeline": build_timeline(inv_id),
        "recommended_next_steps": next_steps[:8],
        "caveat": "Hypotheses are inferences, not confirmed facts. Confidence is bounded and evidence-derived.",
    }
