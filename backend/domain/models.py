"""Domain entities for the investigation platform.

These are plain dataclasses with explicit ``to_dict`` / ``from_dict`` so the
:mod:`storage` layer can persist them to SQLite (JSON columns for nested
value objects) without an ORM. Nested value objects — :class:`Provenance` and
:class:`~domain.confidence.Confidence` — serialise to embedded dicts.

Every analytic product (Event, Evidence, Hypothesis, Alert) carries a
:class:`~domain.classification.Classification`, keeping the fact/inference
boundary explicit at the data layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from domain._util import canonical_id, coerce_iso, new_id, now_iso, valid_coord
from domain.classification import (
    AlertStatus,
    Classification,
    EntityType,
    EvidenceKind,
    HypothesisStatus,
    InvestigationStatus,
    Severity,
)
from domain.confidence import Confidence, unknown


# --------------------------------------------------------------------------- #
# Value objects
# --------------------------------------------------------------------------- #
@dataclass
class Provenance:
    """Where a datum came from and when — the answer to "how do we know?".

    ``observed_at`` is when the world event/measurement happened; ``ingested_at``
    is when ShadowBroker recorded it. Keeping them distinct prevents the classic
    OSINT bug of re-stamping stale editorial data as "now".
    """

    source_id: Optional[str] = None
    source_name: str = ""
    source_url: str = ""
    observed_at: Optional[str] = None
    ingested_at: str = field(default_factory=now_iso)
    method: str = ""  # e.g. "ADS-B", "AIS", "scrape", "shadowbroker-correlation"
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "observed_at": self.observed_at,
            "ingested_at": self.ingested_at,
            "method": self.method,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: object) -> "Provenance":
        if isinstance(d, Provenance):
            return d
        if not isinstance(d, dict):
            return cls()
        return cls(
            source_id=d.get("source_id"),
            source_name=str(d.get("source_name", "") or ""),
            source_url=str(d.get("source_url", "") or ""),
            observed_at=coerce_iso(d.get("observed_at")),
            ingested_at=coerce_iso(d.get("ingested_at")) or now_iso(),
            method=str(d.get("method", "") or ""),
            note=str(d.get("note", "") or ""),
        )


# --------------------------------------------------------------------------- #
# Source
# --------------------------------------------------------------------------- #
@dataclass
class Source:
    """A first-class provenance origin (a feed, API, channel, or document set)."""

    id: str = field(default_factory=lambda: new_id("src"))
    kind: str = "feed"  # feed | api | channel | scrape | document | derived
    name: str = ""
    url: str = ""
    reliability: str = "unrated"  # unrated | low | medium | high (qualitative)
    trusted: bool = False  # False => content is treated as untrusted external data
    first_seen: str = field(default_factory=now_iso)
    last_seen: str = field(default_factory=now_iso)
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "url": self.url,
            "reliability": self.reliability,
            "trusted": self.trusted,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "attributes": self.attributes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Source":
        return cls(
            id=d.get("id") or new_id("src"),
            kind=str(d.get("kind", "feed")),
            name=str(d.get("name", "") or ""),
            url=str(d.get("url", "") or ""),
            reliability=str(d.get("reliability", "unrated")),
            trusted=bool(d.get("trusted", False)),
            first_seen=coerce_iso(d.get("first_seen")) or now_iso(),
            last_seen=coerce_iso(d.get("last_seen")) or now_iso(),
            attributes=dict(d.get("attributes") or {}),
        )


# --------------------------------------------------------------------------- #
# Entity
# --------------------------------------------------------------------------- #
@dataclass
class Entity:
    """A stable, identified thing that persists across observations."""

    id: str = ""
    type: EntityType = EntityType.OTHER
    label: str = ""
    canonical_key: str = ""  # stable natural key: icao24, mmsi, norad, ip, ...
    aliases: list[str] = field(default_factory=list)
    lat: Optional[float] = None
    lng: Optional[float] = None
    first_seen: str = field(default_factory=now_iso)
    last_seen: str = field(default_factory=now_iso)
    attributes: dict = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        self.type = EntityType.coerce(self.type)
        if not self.id:
            self.id = canonical_id("ent", self.type.value, self.canonical_key or self.label)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "label": self.label,
            "canonical_key": self.canonical_key,
            "aliases": self.aliases,
            "lat": self.lat,
            "lng": self.lng,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "attributes": self.attributes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Entity":
        coord = valid_coord(d.get("lat"), d.get("lng"))
        return cls(
            id=d.get("id", ""),
            type=EntityType.coerce(d.get("type")),
            label=str(d.get("label", "") or ""),
            canonical_key=str(d.get("canonical_key", "") or ""),
            aliases=list(d.get("aliases") or []),
            lat=coord[0] if coord else None,
            lng=coord[1] if coord else None,
            first_seen=coerce_iso(d.get("first_seen")) or now_iso(),
            last_seen=coerce_iso(d.get("last_seen")) or now_iso(),
            attributes=dict(d.get("attributes") or {}),
            created_at=coerce_iso(d.get("created_at")) or now_iso(),
            updated_at=coerce_iso(d.get("updated_at")) or now_iso(),
        )


# --------------------------------------------------------------------------- #
# Observation (RAW)
# --------------------------------------------------------------------------- #
@dataclass
class Observation:
    """A single timestamped, source-attributed measurement of an entity.

    Always :attr:`Classification.RAW_OBSERVATION` — the ground-truth rung.
    """

    id: str = field(default_factory=lambda: new_id("obs"))
    entity_id: Optional[str] = None
    layer: str = ""  # originating telemetry layer, e.g. "commercial_flights"
    kind: str = "position"
    lat: Optional[float] = None
    lng: Optional[float] = None
    observed_at: Optional[str] = None
    ingested_at: str = field(default_factory=now_iso)
    provenance: Provenance = field(default_factory=Provenance)
    data: dict = field(default_factory=dict)
    classification: Classification = Classification.RAW_OBSERVATION

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "layer": self.layer,
            "kind": self.kind,
            "lat": self.lat,
            "lng": self.lng,
            "observed_at": self.observed_at,
            "ingested_at": self.ingested_at,
            "provenance": self.provenance.to_dict(),
            "data": self.data,
            "classification": self.classification.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Observation":
        coord = valid_coord(d.get("lat"), d.get("lng"))
        return cls(
            id=d.get("id") or new_id("obs"),
            entity_id=d.get("entity_id"),
            layer=str(d.get("layer", "") or ""),
            kind=str(d.get("kind", "position") or "position"),
            lat=coord[0] if coord else None,
            lng=coord[1] if coord else None,
            observed_at=coerce_iso(d.get("observed_at")),
            ingested_at=coerce_iso(d.get("ingested_at")) or now_iso(),
            provenance=Provenance.from_dict(d.get("provenance")),
            data=dict(d.get("data") or {}),
            classification=Classification.RAW_OBSERVATION,
        )


# --------------------------------------------------------------------------- #
# Event (DERIVED / ANALYSIS)
# --------------------------------------------------------------------------- #
@dataclass
class Event:
    """A meaningful occurrence derived from observations.

    Defaults to :attr:`Classification.DERIVED_EVENT`; a correlation/analysis
    product may set :attr:`Classification.ANALYSIS`. ``explanation`` states
    *why* this event exists — no black-box conclusions.
    """

    id: str = field(default_factory=lambda: new_id("evt"))
    type: str = "generic"
    title: str = ""
    summary: str = ""
    classification: Classification = Classification.DERIVED_EVENT
    occurred_at: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    severity: Severity = Severity.INFO
    entity_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    explanation: str = ""
    confidence: Confidence = field(default_factory=unknown)
    attributes: dict = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if not isinstance(self.classification, Classification):
            self.classification = Classification(str(self.classification))
        self.severity = Severity.coerce(self.severity)
        self.confidence = Confidence.from_dict(self.confidence)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "summary": self.summary,
            "classification": self.classification.value,
            "occurred_at": self.occurred_at,
            "lat": self.lat,
            "lng": self.lng,
            "severity": self.severity.value,
            "entity_ids": self.entity_ids,
            "source_ids": self.source_ids,
            "evidence_ids": self.evidence_ids,
            "explanation": self.explanation,
            "confidence": self.confidence.to_dict(),
            "attributes": self.attributes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        coord = valid_coord(d.get("lat"), d.get("lng"))
        classification = d.get("classification", Classification.DERIVED_EVENT.value)
        try:
            classification = Classification(str(classification))
        except ValueError:
            classification = Classification.DERIVED_EVENT
        return cls(
            id=d.get("id") or new_id("evt"),
            type=str(d.get("type", "generic") or "generic"),
            title=str(d.get("title", "") or ""),
            summary=str(d.get("summary", "") or ""),
            classification=classification,
            occurred_at=coerce_iso(d.get("occurred_at")),
            lat=coord[0] if coord else None,
            lng=coord[1] if coord else None,
            severity=Severity.coerce(d.get("severity")),
            entity_ids=list(d.get("entity_ids") or []),
            source_ids=list(d.get("source_ids") or []),
            evidence_ids=list(d.get("evidence_ids") or []),
            explanation=str(d.get("explanation", "") or ""),
            confidence=Confidence.from_dict(d.get("confidence")),
            attributes=dict(d.get("attributes") or {}),
            created_at=coerce_iso(d.get("created_at")) or now_iso(),
        )


# --------------------------------------------------------------------------- #
# Relationship
# --------------------------------------------------------------------------- #
@dataclass
class Relationship:
    """A typed, optionally-directed edge between two entities."""

    id: str = field(default_factory=lambda: new_id("rel"))
    src_entity_id: str = ""
    dst_entity_id: str = ""
    type: str = "related_to"  # operates | owns | located_at | member_of | ...
    directed: bool = True
    source_id: Optional[str] = None
    confidence: Confidence = field(default_factory=unknown)
    attributes: dict = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        self.confidence = Confidence.from_dict(self.confidence)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "src_entity_id": self.src_entity_id,
            "dst_entity_id": self.dst_entity_id,
            "type": self.type,
            "directed": self.directed,
            "source_id": self.source_id,
            "confidence": self.confidence.to_dict(),
            "attributes": self.attributes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Relationship":
        return cls(
            id=d.get("id") or new_id("rel"),
            src_entity_id=str(d.get("src_entity_id", "") or ""),
            dst_entity_id=str(d.get("dst_entity_id", "") or ""),
            type=str(d.get("type", "related_to") or "related_to"),
            directed=bool(d.get("directed", True)),
            source_id=d.get("source_id"),
            confidence=Confidence.from_dict(d.get("confidence")),
            attributes=dict(d.get("attributes") or {}),
            created_at=coerce_iso(d.get("created_at")) or now_iso(),
        )


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #
@dataclass
class Evidence:
    """An artifact that supports or contradicts an event or hypothesis.

    Evidence preserves provenance and its own classification, so a report can
    always separate raw source data from ShadowBroker-derived data.
    """

    id: str = field(default_factory=lambda: new_id("evd"))
    investigation_id: Optional[str] = None
    kind: EvidenceKind = EvidenceKind.OBSERVATION
    title: str = ""
    description: str = ""
    classification: Classification = Classification.RAW_OBSERVATION
    provenance: Provenance = field(default_factory=Provenance)
    lat: Optional[float] = None
    lng: Optional[float] = None
    occurred_at: Optional[str] = None
    ref_type: str = ""  # observation | event | correlation | pin | external
    ref_id: str = ""
    confidence: Confidence = field(default_factory=unknown)
    data: dict = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    created_by: str = "analyst"

    def __post_init__(self) -> None:
        self.kind = EvidenceKind.coerce(self.kind)
        if not isinstance(self.classification, Classification):
            try:
                self.classification = Classification(str(self.classification))
            except ValueError:
                self.classification = Classification.RAW_OBSERVATION
        self.provenance = Provenance.from_dict(self.provenance)
        self.confidence = Confidence.from_dict(self.confidence)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "investigation_id": self.investigation_id,
            "kind": self.kind.value,
            "title": self.title,
            "description": self.description,
            "classification": self.classification.value,
            "provenance": self.provenance.to_dict(),
            "lat": self.lat,
            "lng": self.lng,
            "occurred_at": self.occurred_at,
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
            "confidence": self.confidence.to_dict(),
            "data": self.data,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Evidence":
        coord = valid_coord(d.get("lat"), d.get("lng"))
        classification = d.get("classification", Classification.RAW_OBSERVATION.value)
        try:
            classification = Classification(str(classification))
        except ValueError:
            classification = Classification.RAW_OBSERVATION
        return cls(
            id=d.get("id") or new_id("evd"),
            investigation_id=d.get("investigation_id"),
            kind=EvidenceKind.coerce(d.get("kind")),
            title=str(d.get("title", "") or ""),
            description=str(d.get("description", "") or ""),
            classification=classification,
            provenance=Provenance.from_dict(d.get("provenance")),
            lat=coord[0] if coord else None,
            lng=coord[1] if coord else None,
            occurred_at=coerce_iso(d.get("occurred_at")),
            ref_type=str(d.get("ref_type", "") or ""),
            ref_id=str(d.get("ref_id", "") or ""),
            confidence=Confidence.from_dict(d.get("confidence")),
            data=dict(d.get("data") or {}),
            created_at=coerce_iso(d.get("created_at")) or now_iso(),
            created_by=str(d.get("created_by", "analyst") or "analyst"),
        )


# --------------------------------------------------------------------------- #
# Hypothesis
# --------------------------------------------------------------------------- #
@dataclass
class Hypothesis:
    """A candidate inference — ALWAYS classified as a hypothesis, never a fact."""

    id: str = field(default_factory=lambda: new_id("hyp"))
    investigation_id: Optional[str] = None
    statement: str = ""
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    classification: Classification = Classification.HYPOTHESIS
    confidence: Confidence = field(default_factory=unknown)
    supporting_evidence_ids: list[str] = field(default_factory=list)
    contradicting_evidence_ids: list[str] = field(default_factory=list)
    author: str = "analyst"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        self.status = HypothesisStatus.coerce(self.status)
        self.confidence = Confidence.from_dict(self.confidence)
        # A hypothesis can never be reclassified below the inference line.
        self.classification = Classification.HYPOTHESIS

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "investigation_id": self.investigation_id,
            "statement": self.statement,
            "status": self.status.value,
            "classification": self.classification.value,
            "confidence": self.confidence.to_dict(),
            "supporting_evidence_ids": self.supporting_evidence_ids,
            "contradicting_evidence_ids": self.contradicting_evidence_ids,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Hypothesis":
        return cls(
            id=d.get("id") or new_id("hyp"),
            investigation_id=d.get("investigation_id"),
            statement=str(d.get("statement", "") or ""),
            status=HypothesisStatus.coerce(d.get("status")),
            confidence=Confidence.from_dict(d.get("confidence")),
            supporting_evidence_ids=list(d.get("supporting_evidence_ids") or []),
            contradicting_evidence_ids=list(d.get("contradicting_evidence_ids") or []),
            author=str(d.get("author", "analyst") or "analyst"),
            created_at=coerce_iso(d.get("created_at")) or now_iso(),
            updated_at=coerce_iso(d.get("updated_at")) or now_iso(),
        )


# --------------------------------------------------------------------------- #
# Note
# --------------------------------------------------------------------------- #
@dataclass
class Note:
    id: str = field(default_factory=lambda: new_id("note"))
    investigation_id: Optional[str] = None
    body: str = ""
    author: str = "analyst"
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "investigation_id": self.investigation_id,
            "body": self.body,
            "author": self.author,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Note":
        return cls(
            id=d.get("id") or new_id("note"),
            investigation_id=d.get("investigation_id"),
            body=str(d.get("body", "") or ""),
            author=str(d.get("author", "analyst") or "analyst"),
            created_at=coerce_iso(d.get("created_at")) or now_iso(),
        )


# --------------------------------------------------------------------------- #
# Investigation
# --------------------------------------------------------------------------- #
@dataclass
class Investigation:
    """An analyst workspace grouping a question, entities, events and evidence."""

    id: str = field(default_factory=lambda: new_id("inv"))
    title: str = ""
    question: str = ""
    description: str = ""
    status: InvestigationStatus = InvestigationStatus.OPEN
    author: str = "analyst"
    tags: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    # Map/temporal focus for the workspace view.
    focus: dict = field(default_factory=dict)  # {lat,lng,zoom,bbox,time_from,time_to}
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        self.status = InvestigationStatus.coerce(self.status)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "question": self.question,
            "description": self.description,
            "status": self.status.value,
            "author": self.author,
            "tags": self.tags,
            "entity_ids": self.entity_ids,
            "event_ids": self.event_ids,
            "focus": self.focus,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Investigation":
        return cls(
            id=d.get("id") or new_id("inv"),
            title=str(d.get("title", "") or ""),
            question=str(d.get("question", "") or ""),
            description=str(d.get("description", "") or ""),
            status=InvestigationStatus.coerce(d.get("status")),
            author=str(d.get("author", "analyst") or "analyst"),
            tags=list(d.get("tags") or []),
            entity_ids=list(d.get("entity_ids") or []),
            event_ids=list(d.get("event_ids") or []),
            focus=dict(d.get("focus") or {}),
            created_at=coerce_iso(d.get("created_at")) or now_iso(),
            updated_at=coerce_iso(d.get("updated_at")) or now_iso(),
        )


# --------------------------------------------------------------------------- #
# Alert
# --------------------------------------------------------------------------- #
@dataclass
class Alert:
    """A meaningful change requiring attention.

    Every alert answers WHAT / WHEN / WHERE / WHY IT MATTERS, with linked
    evidence and an explainable confidence — never a bare notification.
    """

    id: str = field(default_factory=lambda: new_id("alr"))
    type: str = "generic"
    title: str = ""
    what: str = ""
    why: str = ""  # why it matters
    occurred_at: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    severity: Severity = Severity.LOW
    status: AlertStatus = AlertStatus.NEW
    classification: Classification = Classification.ANALYSIS
    confidence: Confidence = field(default_factory=unknown)
    evidence_ids: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    investigation_id: Optional[str] = None
    attributes: dict = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        self.severity = Severity.coerce(self.severity)
        self.status = AlertStatus.coerce(self.status)
        self.confidence = Confidence.from_dict(self.confidence)
        if not isinstance(self.classification, Classification):
            try:
                self.classification = Classification(str(self.classification))
            except ValueError:
                self.classification = Classification.ANALYSIS

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "what": self.what,
            "why": self.why,
            "occurred_at": self.occurred_at,
            "lat": self.lat,
            "lng": self.lng,
            "severity": self.severity.value,
            "status": self.status.value,
            "classification": self.classification.value,
            "confidence": self.confidence.to_dict(),
            "evidence_ids": self.evidence_ids,
            "entity_ids": self.entity_ids,
            "investigation_id": self.investigation_id,
            "attributes": self.attributes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Alert":
        coord = valid_coord(d.get("lat"), d.get("lng"))
        return cls(
            id=d.get("id") or new_id("alr"),
            type=str(d.get("type", "generic") or "generic"),
            title=str(d.get("title", "") or ""),
            what=str(d.get("what", "") or ""),
            why=str(d.get("why", "") or ""),
            occurred_at=coerce_iso(d.get("occurred_at")),
            lat=coord[0] if coord else None,
            lng=coord[1] if coord else None,
            severity=Severity.coerce(d.get("severity")),
            status=AlertStatus.coerce(d.get("status")),
            classification=d.get("classification", Classification.ANALYSIS.value),
            confidence=Confidence.from_dict(d.get("confidence")),
            evidence_ids=list(d.get("evidence_ids") or []),
            entity_ids=list(d.get("entity_ids") or []),
            investigation_id=d.get("investigation_id"),
            attributes=dict(d.get("attributes") or {}),
            created_at=coerce_iso(d.get("created_at")) or now_iso(),
        )
