"""Investigation workspace REST API.

All routes require local-operator authorization (same trust model as the recon
and admin surfaces). The heavy lifting lives in
:mod:`services.investigation_service`; this module is a thin, validated HTTP
shell with rate limiting and predictable error mapping.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import require_local_operator
from limiter import limiter
from services import investigation_service as svc
from storage import get_store

router = APIRouter(dependencies=[Depends(require_local_operator)])


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class InvestigationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(default="", max_length=1000)
    description: str = Field(default="", max_length=5000)
    author: str = Field(default="operator", max_length=120)
    tags: list[str] = Field(default_factory=list)
    focus: dict = Field(default_factory=dict)


class InvestigationUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    question: Optional[str] = Field(default=None, max_length=1000)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[str] = Field(default=None, max_length=40)
    tags: Optional[list[str]] = None
    focus: Optional[dict] = None


class EntityAdd(BaseModel):
    entity_id: Optional[str] = Field(default=None, max_length=120)
    # Or ingest a live telemetry record directly into the domain and attach it.
    record: Optional[dict] = None
    entity_type: str = Field(default="other", max_length=40)
    layer: str = Field(default="", max_length=80)
    source_name: str = Field(default="", max_length=120)


class EventCreate(BaseModel):
    type: str = Field(default="generic", max_length=80)
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=2000)
    classification: str = Field(default="derived_event", max_length=40)
    occurred_at: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    severity: str = Field(default="info", max_length=20)
    explanation: str = Field(default="", max_length=2000)
    entity_ids: list[str] = Field(default_factory=list)
    confidence: Optional[dict] = None


class EvidenceCreate(BaseModel):
    kind: str = Field(default="observation", max_length=40)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    classification: str = Field(default="raw_observation", max_length=40)
    provenance: Optional[dict] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    occurred_at: Optional[str] = None
    ref_type: str = Field(default="", max_length=40)
    ref_id: str = Field(default="", max_length=120)
    confidence: Optional[dict] = None
    data: dict = Field(default_factory=dict)


class HypothesisCreate(BaseModel):
    statement: str = Field(min_length=1, max_length=2000)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    author: str = Field(default="operator", max_length=120)


class HypothesisUpdate(BaseModel):
    statement: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = Field(default=None, max_length=40)
    supporting_evidence_ids: Optional[list[str]] = None
    contradicting_evidence_ids: Optional[list[str]] = None


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    author: str = Field(default="operator", max_length=120)


def _not_found(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=f"not found: {exc}")


# --------------------------------------------------------------------------- #
# Investigations
# --------------------------------------------------------------------------- #
@router.get("/api/investigations")
@limiter.limit("60/minute")
async def list_investigations(
    request: Request,
    status: str = Query(default="", max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    items = svc.list_investigations(status=status, limit=limit)
    return {"investigations": [i.to_dict() for i in items], "count": len(items)}


@router.post("/api/investigations", status_code=201)
@limiter.limit("30/minute")
async def create_investigation(request: Request, body: InvestigationCreate) -> dict:
    try:
        inv = svc.create_investigation(
            title=body.title,
            question=body.question,
            description=body.description,
            author=body.author,
            tags=body.tags,
            focus=body.focus,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return inv.to_dict()


@router.get("/api/investigations/{inv_id}")
@limiter.limit("120/minute")
async def get_investigation(request: Request, inv_id: str) -> dict:
    try:
        return svc.get_investigation_bundle(inv_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.patch("/api/investigations/{inv_id}")
@limiter.limit("60/minute")
async def update_investigation(request: Request, inv_id: str, body: InvestigationUpdate) -> dict:
    try:
        inv = svc.update_investigation(inv_id, actor="operator", **body.model_dump(exclude_none=True))
    except KeyError as exc:
        raise _not_found(exc) from exc
    return inv.to_dict()


@router.delete("/api/investigations/{inv_id}")
@limiter.limit("30/minute")
async def delete_investigation(request: Request, inv_id: str) -> dict:
    ok = svc.delete_investigation(inv_id, actor="operator")
    if not ok:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "deleted": inv_id}


# --------------------------------------------------------------------------- #
# Members
# --------------------------------------------------------------------------- #
@router.post("/api/investigations/{inv_id}/entities", status_code=201)
@limiter.limit("60/minute")
async def add_entity(request: Request, inv_id: str, body: EntityAdd) -> dict:
    try:
        entity_id = body.entity_id
        if entity_id is None and body.record is not None:
            ent = svc.ingest_entity_from_record(
                body.record, entity_type=body.entity_type, layer=body.layer, source_name=body.source_name
            )
            entity_id = ent.id
        if not entity_id:
            raise HTTPException(status_code=400, detail="entity_id or record required")
        inv = svc.add_entity_to_investigation(inv_id, entity_id, actor="operator")
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return inv.to_dict()


@router.delete("/api/investigations/{inv_id}/entities/{entity_id}")
@limiter.limit("60/minute")
async def remove_entity(request: Request, inv_id: str, entity_id: str) -> dict:
    try:
        inv = svc.remove_entity_from_investigation(inv_id, entity_id, actor="operator")
    except KeyError as exc:
        raise _not_found(exc) from exc
    return inv.to_dict()


@router.post("/api/investigations/{inv_id}/events", status_code=201)
@limiter.limit("60/minute")
async def add_event(request: Request, inv_id: str, body: EventCreate) -> dict:
    try:
        ev = svc.add_event(inv_id, actor="operator", **body.model_dump())
    except KeyError as exc:
        raise _not_found(exc) from exc
    return ev.to_dict()


@router.post("/api/investigations/{inv_id}/evidence", status_code=201)
@limiter.limit("60/minute")
async def add_evidence(request: Request, inv_id: str, body: EvidenceCreate) -> dict:
    try:
        evd = svc.add_evidence(inv_id, actor="operator", **body.model_dump())
    except KeyError as exc:
        raise _not_found(exc) from exc
    return evd.to_dict()


@router.delete("/api/investigations/{inv_id}/evidence/{evidence_id}")
@limiter.limit("60/minute")
async def delete_evidence(request: Request, inv_id: str, evidence_id: str) -> dict:
    ok = get_store().delete_evidence(evidence_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "deleted": evidence_id}


@router.post("/api/investigations/{inv_id}/hypotheses", status_code=201)
@limiter.limit("60/minute")
async def create_hypothesis(request: Request, inv_id: str, body: HypothesisCreate) -> dict:
    try:
        hyp = svc.create_hypothesis(
            inv_id,
            statement=body.statement,
            supporting_evidence_ids=body.supporting_evidence_ids,
            contradicting_evidence_ids=body.contradicting_evidence_ids,
            author=body.author,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return hyp.to_dict()


@router.patch("/api/investigations/{inv_id}/hypotheses/{hyp_id}")
@limiter.limit("60/minute")
async def update_hypothesis(request: Request, inv_id: str, hyp_id: str, body: HypothesisUpdate) -> dict:
    try:
        hyp = svc.update_hypothesis(hyp_id, actor="operator", **body.model_dump(exclude_none=True))
    except KeyError as exc:
        raise _not_found(exc) from exc
    return hyp.to_dict()


@router.post("/api/investigations/{inv_id}/notes", status_code=201)
@limiter.limit("60/minute")
async def add_note(request: Request, inv_id: str, body: NoteCreate) -> dict:
    try:
        note = svc.add_note(inv_id, body.body, author=body.author)
    except KeyError as exc:
        raise _not_found(exc) from exc
    return note.to_dict()


@router.get("/api/investigations/{inv_id}/timeline")
@limiter.limit("120/minute")
async def timeline(request: Request, inv_id: str) -> dict:
    try:
        return {"timeline": svc.build_timeline(inv_id)}
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/api/investigations/{inv_id}/briefing")
@limiter.limit("30/minute")
async def briefing(request: Request, inv_id: str) -> dict:
    try:
        return svc.generate_briefing(inv_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


# --------------------------------------------------------------------------- #
# Domain entities (read)
# --------------------------------------------------------------------------- #
@router.get("/api/entities/search")
@limiter.limit("120/minute")
async def search_entities(
    request: Request,
    q: str = Query(default="", max_length=200),
    type: str = Query(default="", max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    items = get_store().search_entities(query=q, etype=type, limit=limit)
    return {"entities": [e.to_dict() for e in items], "count": len(items)}


@router.get("/api/entities/{entity_id}")
@limiter.limit("120/minute")
async def get_entity(request: Request, entity_id: str) -> dict:
    st = get_store()
    ent = st.get_entity(entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="not found")
    observations = st.observations_for_entity(entity_id, limit=200)
    relationships = st.relationships_for_entity(entity_id)
    return {
        "entity": ent.to_dict(),
        "observations": [o.to_dict() for o in observations],
        "relationships": [r.to_dict() for r in relationships],
    }


@router.get("/api/domain/stats")
@limiter.limit("60/minute")
async def domain_stats(request: Request) -> dict:
    return get_store().stats()
