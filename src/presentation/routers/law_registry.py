"""Law corpus registry router.

Backs ``templates/law-registry.html``: reads the generated registry artifacts,
exposes the corpus Markdown, lets a reviewer inspect and edit a live Qdrant
payload, and runs ingestion as a pollable background job.

Endpoints
---------
``GET  /api/law/status``
    Corpus ↔ collection coverage snapshot. Labels the index actions.
``GET  /api/law/registry`` / ``/registry/markdown``
    The ``law_registry.json`` superset and its Markdown companion.
``POST /api/law/registry/refresh``
    Re-run validation and rewrite both artifacts.
``GET  /api/law/source?path=``
    Corpus Markdown, path-traversal safe.
``GET  /api/law/article?original_id=``
    Live payload + the payload recomputed from the corpus + a field-level diff.
``PATCH /api/law/payload``
    Apply an edit to one indexed point (never touches the dense vector).
``POST /api/law/index`` / ``GET /api/law/index/{job_id}``
    Start and poll an incremental or forced ingestion job.
``GET  /api/law/search``
    Dense (local) or BM25 (canonical) search, for spot-checking after a change.

Safety
------
* Edits go through :func:`~src.infrastructure.qdrant_law_index.build_payload_patch`,
  which rejects unknown/immutable keys, so a request cannot inject a vector or
  rewrite a derived field.
* An edit to a missing article is an error, never an implicit create, so a point
  can never materialise with a placeholder vector by accident.
* Writing to the shared ``canonical`` collections requires an explicit
  ``confirm: true`` in the request body.
* Only one ingestion job runs at a time.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from src.config import settings
from src.infrastructure.qdrant_law_index import (
    CANONICAL_COLLECTION,
    EDITABLE_PAYLOAD_FIELDS,
    LawArticle,
    PayloadEditError,
    QdrantLawIndex,
    registry_paths,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/law", tags=["law"])

Target = Literal["canonical", "local", "both"]
Mode = Literal["incremental", "force"]

#: Payload fields the UI may present as editable.
_EDITABLE = sorted(EDITABLE_PAYLOAD_FIELDS)


# ---------------------------------------------------------------------------
# Index singleton
# ---------------------------------------------------------------------------
_index_lock = threading.Lock()
_index: QdrantLawIndex | None = None
_override_index: QdrantLawIndex | None = None


def init_law_registry_router(index: QdrantLawIndex | None = None) -> None:
    """Inject a pre-built index (used by tests); ``None`` restores lazy default."""
    global _override_index
    _override_index = index


def get_index() -> QdrantLawIndex:
    """Lazily build the process-wide law index from settings."""
    global _index
    if _override_index is not None:
        return _override_index
    with _index_lock:
        if _index is None:
            _index = QdrantLawIndex.from_settings(
                law_dir=settings.LAW_DIR,
                canonical_collection=settings.LAW_COLLECTION,
                bm25_collection=settings.LAW_BM25_COLLECTION,
                local_collection=settings.LAW_LOCAL_COLLECTION,
                embed_model=settings.LAW_EMBED_MODEL,
                preferred_language=settings.LAW_PREFERRED_LANGUAGE,
            )
        return _index


def law_dir() -> Path:
    return Path(settings.LAW_DIR)


# ---------------------------------------------------------------------------
# Background index jobs
# ---------------------------------------------------------------------------
class JobCancelledError(RuntimeError):
    """Raised from a progress callback to abort an ingestion job."""


@dataclass
class IndexJob:
    """Mutable state of one ingestion run, polled by the UI."""

    id: str
    mode: Mode
    targets: list[str]
    dry_run: bool
    allow_new: bool
    recreate_local: bool
    multi_language: bool
    state: str = "queued"
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    #: ``phase -> {"done": int, "total": int}``
    progress: dict[str, dict[str, int]] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    cancel_requested: bool = False

    def request(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "targets": self.targets,
            "dry_run": self.dry_run,
            "allow_new": self.allow_new,
            "recreate_local": self.recreate_local,
            "multi_language": self.multi_language,
        }

    def as_dict(self) -> dict[str, Any]:
        phases = []
        for name, values in sorted(self.progress.items()):
            total = values.get("total") or 0
            done = values.get("done") or 0
            phases.append(
                {
                    "phase": name,
                    "done": done,
                    "total": total,
                    "percent": round(done / total * 100, 1) if total else 0.0,
                }
            )
        return {
            "id": self.id,
            "state": self.state,
            "mode": self.mode,
            "request": self.request(),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cancel_requested": self.cancel_requested,
            "phases": phases,
            "result": self.result,
            "error": self.error,
        }


_jobs: dict[str, IndexJob] = {}
_jobs_lock = threading.Lock()
_active_job_id: str | None = None


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _active_job() -> IndexJob | None:
    with _jobs_lock:
        if _active_job_id and _jobs.get(_active_job_id) is not None:
            job = _jobs[_active_job_id]
            if job.state in {"queued", "running"}:
                return job
        return None


def _run_job(job: IndexJob) -> None:
    """Execute an ingestion job on a worker thread."""
    global _active_job_id
    index = get_index()
    job.state = "running"
    job.started_at = _iso_now()

    def on_progress(phase: str, done: int, total: int) -> None:
        job.progress[phase] = {"done": done, "total": total}
        if job.cancel_requested:
            raise JobCancelledError("cancelled by operator")

    try:
        plan = index.build_plan()
        results = index.ingest(
            plan,
            targets=job.targets,
            dry_run=job.dry_run,
            allow_new=job.allow_new,
            recreate_local=job.recreate_local,
            multi_language=job.multi_language,
            only_missing=job.mode == "incremental",
            on_progress=on_progress,
        )
        job.result = {
            "corpus": {
                "articles": len(plan.articles),
                "unique_elis": len(plan.by_original_id),
                "files": len(plan.files),
            },
            "targets": {name: stats.as_dict() for name, stats in results.items()},
        }
        job.state = "cancelled" if job.cancel_requested else "done"
    except JobCancelledError:
        logger.warning("[law] ingestion job %s cancelled", job.id)
        job.state = "cancelled"
        job.error = "cancelled by operator"
    except Exception as exc:  # noqa: BLE001 — surfaced to the UI
        logger.exception("[law] ingestion job %s failed", job.id)
        job.state = "error"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        job.finished_at = _iso_now()
        with _jobs_lock:
            if _active_job_id == job.id:
                _active_job_id = None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class IndexRequest(BaseModel):
    """Start an ingestion job."""

    mode: Mode = Field("incremental", description="incremental = only not-yet-indexed; force = reindex all")
    target: Target = Field("local", description="local / canonical / both")
    dry_run: bool = False
    allow_new: bool = Field(
        False,
        description="canonical only: create missing articles with a placeholder dense vector",
    )
    recreate_local: bool = Field(False, description="drop and rebuild the local collection")
    multi_language: bool = False
    confirm: bool = Field(
        False,
        description="required when writing to the shared canonical collections",
    )


class PayloadPatchRequest(BaseModel):
    """Edit one indexed article's payload."""

    original_id: str
    fields: dict[str, Any] = Field(default_factory=dict)
    collection: str = CANONICAL_COLLECTION
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_source(rel_path: str) -> Path:
    """Resolve a corpus-relative Markdown path, rejecting traversal."""
    root = law_dir().resolve()
    candidate = (root / rel_path).resolve()
    if not candidate.is_relative_to(root) or candidate.suffix.lower() not in {".md", ".markdown"}:
        raise HTTPException(status_code=400, detail=f"Invalid corpus path: {rel_path!r}")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"Corpus file not found: {rel_path}")
    return candidate


def _corpus_article(index: QdrantLawIndex, original_id: str) -> LawArticle | None:
    """Re-parse the corpus (cheap enough at this size) and find one article."""
    plan = index.build_plan()
    return plan.by_original_id.get(original_id)


def _expected_payload(article: LawArticle, point_id: str) -> dict[str, Any]:
    """The payload the ingester would write today, for a structural diff."""
    return article.to_payload(point_id, include_framework_fields=True, include_extra=True)


def _field_diff(live: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Compare flat, reviewable fields between the live and expected payloads."""
    keys = ["title", "theme", "tags", "doc_type", "source_file", "content"]
    diff: dict[str, Any] = {}
    for key in keys:
        live_value = live.get(key)
        expected_value = expected.get(key)
        if key == "content":
            same = (live_value or "") == (expected_value or "")
            normalized = not same and (live_value or "").strip() == (expected_value or "").strip()
            diff[key] = "exact" if same else ("whitespace" if normalized else "drift")
        else:
            diff[key] = "exact" if live_value == expected_value else "drift"
    diff["_only_live"] = sorted(set(live) - set(expected))
    diff["_only_expected"] = sorted(set(expected) - set(live))
    return diff


def _registry_files() -> tuple[Path, Path]:
    json_path, md_path = registry_paths(law_dir())
    return json_path, md_path


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------
@router.get("/status")
def get_status() -> dict[str, Any]:
    """Corpus ↔ collection coverage snapshot (drives the index action labels)."""
    index = get_index()
    try:
        status = index.status()
    except Exception as exc:  # noqa: BLE001 — Qdrant may be unreachable
        logger.warning("[law] status lookup failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"Qdrant unavailable: {exc}") from exc

    json_path, md_path = _registry_files()
    payload = status.as_dict()
    payload["registry"] = {
        "json": str(json_path),
        "markdown": str(md_path),
        "json_exists": json_path.is_file(),
        "markdown_exists": md_path.is_file(),
        "json_modified": (
            datetime.fromtimestamp(json_path.stat().st_mtime, UTC).isoformat() if json_path.is_file() else None
        ),
    }
    payload["editable_fields"] = _EDITABLE
    payload["active_job"] = (_active_job().as_dict() if _active_job() else None)
    return payload


@router.get("/registry")
def get_registry() -> dict[str, Any]:
    """Return ``law_registry.json`` (generated in-memory when absent)."""
    json_path, _ = _registry_files()
    if json_path.is_file():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.exception("[law] invalid registry JSON")
            raise HTTPException(status_code=500, detail=f"Invalid registry JSON: {exc}") from exc

    # Not generated yet — build it on the fly without touching disk.
    index = get_index()
    plan = index.build_plan()
    report = index.validate(plan)
    return {
        "summary": {"generated_at": _iso_now(), "note": "generated on demand (not written to disk)"},
        "files": [],
        "qdrant_only_articles": [],
        "detail": report.as_dict(),
    }


@router.get("/registry/markdown", response_class=PlainTextResponse)
def get_registry_markdown() -> PlainTextResponse:
    """Return ``LAW_REGISTRY.md``."""
    _, md_path = _registry_files()
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="LAW_REGISTRY.md not found — run a registry refresh")
    return PlainTextResponse(md_path.read_text(encoding="utf-8"), media_type="text/markdown")


@router.post("/registry/refresh")
def refresh_registry() -> dict[str, Any]:
    """Re-validate the corpus and rewrite both registry artifacts."""
    from src.infrastructure.qdrant_law_index import write_registry

    index = get_index()
    plan = index.build_plan()
    try:
        report = index.validate(plan)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Qdrant unavailable: {exc}") from exc

    json_path, md_path = write_registry(plan, report, output_dir=law_dir())
    return {
        "ok": report.ok,
        "json": str(json_path),
        "markdown": str(md_path),
        "report": report.as_dict(),
    }


@router.get("/source", response_class=PlainTextResponse)
def get_source(path: str = Query(..., description="Corpus-relative path, e.g. BR/D7724_LAI_Regulamento.md")):
    """Return the raw Markdown of one corpus file."""
    return PlainTextResponse(_resolve_source(path).read_text(encoding="utf-8"), media_type="text/markdown")


@router.get("/article")
def get_article(
    original_id: str = Query(..., description="Article ELI, e.g. BR.D7724.C4.Art.23"),
    collection: str = Query(CANONICAL_COLLECTION),
) -> dict[str, Any]:
    """Live payload + the corpus-recomputed payload + a field-level diff."""
    index = get_index()
    try:
        live = index.get_article(original_id, collection=collection)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Qdrant unavailable: {exc}") from exc

    corpus = _corpus_article(index, original_id)
    if live is None and corpus is None:
        raise HTTPException(status_code=404, detail=f"Unknown article: {original_id}")

    point_id = (live or {}).get("id") or (corpus.point_id if corpus else "")
    expected = _expected_payload(corpus, point_id) if corpus else None

    response: dict[str, Any] = {
        "original_id": original_id,
        "collection": collection,
        "indexed": live is not None,
        "point_id": point_id,
        "live": live,
        "expected": expected,
        "editable_fields": _EDITABLE,
        "corpus": (
            {
                "title": corpus.title,
                "theme": corpus.theme,
                "tags": corpus.tags,
                "content": corpus.content,
                "source_file": corpus.source_file,
                "source_path": corpus.source_path,
                "doc_type": corpus.doc_type,
                "language": corpus.language,
                "jurisdiction": corpus.jurisdiction,
                "framework_code": corpus.framework_code,
                "sha256_short": corpus.sha256_short,
            }
            if corpus
            else None
        ),
    }
    if live is not None and expected is not None:
        response["diff"] = _field_diff(live, expected)
    return response


@router.get("/search")
def search(
    q: str = Query(..., min_length=1),
    target: Literal["local", "canonical"] = "local",
    limit: int = Query(5, ge=1, le=50),
    jurisdiction: str | None = None,
) -> dict[str, Any]:
    """Dense search on the local collection, BM25 on the canonical one."""
    index = get_index()
    try:
        hits = index.search(q, limit=limit, target=target, jurisdiction=jurisdiction)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Search failed: {exc}") from exc
    return {"query": q, "target": target, "hits": [hit.as_dict() for hit in hits]}


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------
@router.patch("/payload")
def patch_payload(request: PayloadPatchRequest) -> dict[str, Any]:
    """Apply an edit to an indexed article's payload (dense vector preserved)."""
    index = get_index()
    if not request.fields:
        raise HTTPException(status_code=400, detail="No fields supplied")

    try:
        return index.update_payload(
            request.original_id,
            request.fields,
            collection=request.collection,
            dry_run=request.dry_run,
        )
    except PayloadEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("[law] payload edit failed for %s", request.original_id)
        raise HTTPException(status_code=503, detail=f"Qdrant write failed: {exc}") from exc


@router.post("/index", status_code=202)
def start_index(request: IndexRequest) -> dict[str, Any]:
    """Start an ingestion job (poll ``GET /api/law/index/{job_id}``)."""
    global _active_job_id

    targets = ["canonical", "local"] if request.target == "both" else [request.target]
    if "canonical" in targets and not request.dry_run and not request.confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Writing to the shared collections ({settings.LAW_COLLECTION} + "
                f"{settings.LAW_BM25_COLLECTION}) requires confirm=true. "
                "Send dry_run=true to preview the change instead."
            ),
        )
    if request.recreate_local and request.mode == "incremental":
        raise HTTPException(status_code=400, detail="recreate_local conflicts with incremental mode")

    running = _active_job()
    if running is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Job {running.id} is still {running.state}; wait for it or cancel it first",
        )

    job = IndexJob(
        id=uuid.uuid4().hex[:12],
        mode=request.mode,
        targets=targets,
        dry_run=request.dry_run,
        allow_new=request.allow_new,
        recreate_local=request.recreate_local,
        multi_language=request.multi_language,
        created_at=_iso_now(),
    )
    with _jobs_lock:
        _jobs[job.id] = job
        _active_job_id = job.id

    thread = threading.Thread(target=_run_job, args=(job,), name=f"law-index-{job.id}", daemon=True)
    thread.start()
    logger.info(
        "[law] started job %s (mode=%s targets=%s dry_run=%s)",
        job.id,
        job.mode,
        targets,
        job.dry_run,
    )
    return job.as_dict()


@router.get("/index/{job_id}")
def get_index_job(job_id: str) -> dict[str, Any]:
    """Poll an ingestion job."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
    return job.as_dict()


@router.get("/index")
def list_index_jobs(limit: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
    """Recent ingestion jobs, newest first."""
    with _jobs_lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]
        active = _active_job_id
    return {"active_job_id": active, "jobs": [j.as_dict() for j in jobs]}


@router.post("/index/{job_id}/cancel")
def cancel_index_job(job_id: str) -> dict[str, Any]:
    """Request cooperative cancellation of a running job."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
    if job.state not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail=f"Job {job_id} already {job.state}")
    job.cancel_requested = True
    return job.as_dict()


__all__ = ["init_law_registry_router", "router"]
