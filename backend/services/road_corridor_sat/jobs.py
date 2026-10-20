"""In-memory job queue for on-demand Analyze Here runs."""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_jobs: dict[str, AnalyzeJob] = {}


@dataclass
class AnalyzeJob:
    job_id: str
    lat: float
    lon: float
    status: str = "queued"
    message: str = "Queued"
    progress: int = 0
    result: dict[str, Any] | None = None
    error: str | None = None


def get_job(job_id: str) -> AnalyzeJob | None:
    with _lock:
        return _jobs.get(job_id)


def get_latest_job() -> AnalyzeJob | None:
    with _lock:
        if not _jobs:
            return None
        return max(_jobs.values(), key=lambda j: j.job_id)


def _running_job() -> AnalyzeJob | None:
    with _lock:
        for job in _jobs.values():
            if job.status in {"queued", "running"}:
                return job
    return None


def _prune_jobs(max_keep: int = 8) -> None:
    with _lock:
        if len(_jobs) <= max_keep:
            return
        ordered = sorted(_jobs.items(), key=lambda item: item[0], reverse=True)
        for job_id, _ in ordered[max_keep:]:
            _jobs.pop(job_id, None)


def _worker(job_id: str, lat: float, lon: float, label: str | None) -> None:
    from services.fetchers.road_corridor_sat import refresh_road_corridor_store

    from .pipeline import analyze_corridor
    from .viewport import adhoc_preset_id, bbox_around_point, default_label_for_point

    job = get_job(job_id)
    if job is None:
        return

    def progress(msg: str, pct: int | None = None) -> None:
        with _lock:
            current = _jobs.get(job_id)
            if current is None:
                return
            current.message = msg
            if pct is not None:
                current.progress = pct

    with _lock:
        job.status = "running"
        job.message = "Starting road corridor analysis"
        job.progress = 0

    try:
        bbox = bbox_around_point(lat, lon)
        preset_id = adhoc_preset_id(lat, lon)
        corridor_label = label or default_label_for_point(lat, lon)
        result = analyze_corridor(
            preset_id=preset_id,
            label=corridor_label,
            bbox=bbox,
            country="adhoc",
            category="viewport",
            progress_cb=progress,
        )
        refresh_road_corridor_store()
        with _lock:
            current = _jobs.get(job_id)
            if current is None:
                return
            current.status = "ok" if result.get("status") == "ok" else "error"
            current.result = result
            current.error = result.get("error")
            current.message = (
                f"{result.get('total_detections', 0)} signatures · "
                f"{len(result.get('daily_counts') or [])} days"
            )
            current.progress = 100
    except Exception as exc:
        logger.exception("road corridor analyze job %s failed", job_id)
        with _lock:
            current = _jobs.get(job_id)
            if current is None:
                return
            current.status = "error"
            current.error = str(exc)
            current.message = "Analysis failed"
            current.progress = 100


def enqueue_analyze(lat: float, lon: float, label: str | None = None) -> AnalyzeJob:
    running = _running_job()
    if running is not None:
        raise RuntimeError("analysis_already_running")

    job_id = uuid.uuid4().hex[:12]
    job = AnalyzeJob(job_id=job_id, lat=lat, lon=lon)
    with _lock:
        _jobs[job_id] = job
        _prune_jobs()

    thread = threading.Thread(
        target=_worker,
        args=(job_id, lat, lon, label),
        name=f"road-corridor-analyze-{job_id}",
        daemon=True,
    )
    thread.start()
    return job


def job_to_dict(job: AnalyzeJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "lat": job.lat,
        "lon": job.lon,
        "status": job.status,
        "message": job.message,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
    }
