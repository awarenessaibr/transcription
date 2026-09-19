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
``POST /api/law/suggest``
    Ask an LLM to review the payload — including the ``norm_type`` / ``scope`` /
    ``direction`` / ``sanctions`` enrichment fields — and save a report of the
    proposed populations (read-only; the reviewer applies what it picks through
    ``PATCH /payload``).
``GET  /api/law/reports`` / ``/reports/{name}``
    List and read the saved enrichment reports.
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
* The enrichment fields exist on the schema-v1 (local) payload only, and
  ``build_payload_patch`` enforces that, so the shared canonical shape cannot
  grow a second, unmanaged copy of them.
* Writing to the shared ``canonical`` collections requires an explicit
  ``confirm: true`` in the request body.
* Only one ingestion job runs at a time.
* Reports are written under ``<law_dir>/_mapping/enrichment/`` — inside the
  directory the corpus parser ignores, so a report can never be ingested as a
  law document.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from src.config import settings
from src.infrastructure.law_enrichment import (
    ENRICHMENT_FIELD_KINDS,
    ENRICHMENT_FIELDS,
    REPORT_SUBDIR,
    is_report_name,
    list_reports,
    load_record,
    normalize_value,
    record_applied,
    render_report,
    vocabulary_block,
    write_report,
)
from src.infrastructure.llm import LLMError, call_llm_json
from src.infrastructure.qdrant_law_index import (
    CANONICAL_COLLECTION,
    EDITABLE_PAYLOAD_FIELDS,
    ENRICHMENT_PAYLOAD_FIELDS,
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


def _editable_field_kinds(live: Mapping[str, Any] | None) -> dict[str, str]:
    """Editor shape for every field ``build_payload_patch`` will accept here.

    A field the live payload cannot hold is simply absent, so the UI can disable
    (rather than offer and then reject) it: the enrichment fields exist on the
    schema-v1 payload only, and ``tags`` is only a list there.
    """
    live_map: Mapping[str, Any] = live if isinstance(live, Mapping) else {}
    local_schema = "schema_version" in live_map
    kinds: dict[str, str] = {}
    for name in _EDITABLE:
        if name in ENRICHMENT_PAYLOAD_FIELDS:
            if not local_schema:
                continue
            kinds[name] = "list" if ENRICHMENT_FIELD_KINDS.get(name) == "array" else "scalar_nullable"
        elif name == "tags" and local_schema:
            kinds[name] = "list"
        else:
            kinds[name] = "string"
    return kinds


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
        "field_kinds": _editable_field_kinds(live),
        "enrichment_fields": list(ENRICHMENT_PAYLOAD_FIELDS),
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
    """Apply an edit to an indexed article's payload (dense vector preserved).

    When the edit touches an enrichment field and the article has a saved review
    report, the change is appended to that report — an enrichment without a trail
    would be indistinguishable from a guess later on.
    """
    index = get_index()
    if not request.fields:
        raise HTTPException(status_code=400, detail="No fields supplied")

    touched = sorted(set(request.fields) & set(ENRICHMENT_PAYLOAD_FIELDS))
    before: dict[str, Any] = {}
    if touched and not request.dry_run:
        try:
            live = index.get_article(request.original_id, collection=request.collection)
        except Exception:  # noqa: BLE001 — a report nicety may never fail the write
            live = None
        before = dict(live or {})

    try:
        result = index.update_payload(
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

    if touched and result.get("applied"):
        rows = [{"field": name, "from": before.get(name), "to": result["patch"].get(name)} for name in touched]
        try:
            amended = record_applied(law_dir(), request.original_id, rows)
        except OSError as exc:  # the write succeeded; the trail is best-effort
            logger.warning("[law] could not amend the review report for %s: %s", request.original_id, exc)
        else:
            if amended is not None:
                result["report_path"] = str(amended)
                result["report_name"] = amended.name
    return result


# ---------------------------------------------------------------------------
# LLM-assisted payload review
# ---------------------------------------------------------------------------
#: ``text`` is the BM25 alias of ``content`` — ``build_payload_patch`` keeps the
#: two in step — so reviewing both would only produce duplicate rows.
_REVIEW_EXCLUDED_FIELDS: frozenset[str] = frozenset({"text"})

#: The allow-list is derived from the writer, so the model can never propose a
#: key ``build_payload_patch`` would reject.
_REVIEWABLE_FIELDS: frozenset[str] = EDITABLE_PAYLOAD_FIELDS - _REVIEW_EXCLUDED_FIELDS

#: Fields worth filling in when the payload has nothing recorded for them yet.
#: The enrichment fields come first: they are the ones a bare ingestion leaves
#: empty, and the ones the local collection indexes as keywords.
_DEFAULT_REVIEW_FIELDS: tuple[str, ...] = (
    *ENRICHMENT_FIELDS,
    "title",
    "theme",
    "tags",
    "doc_type",
    "source_file",
)

#: Maximum characters of source Markdown handed to the model.
_SNIPPET_CHARS = 4000

#: Base instruction set. The enrichment taxonomy is appended per request, so a
#: pure metadata review is not told about fields it may not touch.
_SUGGEST_SYSTEM = """\
You review payload metadata for a legal knowledge base that ingests statutes,
regulations, cases and soft-law instruments from many jurisdictions.

You receive one JSON object with:
  - allowed_fields: the ONLY field names you may propose a value for
  - CURRENT:   the payload currently stored in the index
  - EXPECTED:  what the offline ingester would compute from the corpus today
  - SNIPPET:   source Markdown covering this article (may be truncated)
  - vocabulary: the controlled vocabulary and the decision rules for the
    classification fields (the enrichment fields, plus doc_type when it is in
    allowed_fields; omitted entirely when no such field is in scope)

Return a minimal set of field updates that IMPROVE the payload.

Rules:
  1. "field" must be exactly one of allowed_fields. Never invent a field name.
  2. Only propose a change when SNIPPET or EXPECTED gives concrete evidence.
     When in doubt, do not propose anything.
  3. Prefer high-confidence, low-risk edits:
       - fill in an empty string, an empty list, a null or an "unknown" value
       - fix an obvious typo or a stray Markdown escape character
     Do not rewrite a value that is already meaningful.
  4. Preserve the JSON type of the CURRENT value: if current is a list, the
     suggestion must be a list of the same kind; if it is a string, the
     suggestion must be a string. Never convert one into the other. A null
     current value takes whatever type the field's rule prescribes.
  5. For the classification fields, follow the "vocabulary" rules exactly and
     prefer a token from the controlled vocabulary. Propose a new lower-case
     snake_case token only when no listed token fits, and say so in the
     rationale.
  6. Keep values short. "content" is the article body: only propose it when it
     is listed in allowed_fields, and never truncate it.
  7. Every suggestion needs:
       - "rationale": one sentence, why the value fits
       - "justification": two to four sentences of legal reasoning
       - "evidence": a verbatim span copied from SNIPPET that licenses the
         value (empty string when the evidence is purely structural)
       - "confidence": "low", "medium" or "high"
  8. Fill "summary" with one sentence on the state of the article's metadata.
  9. Fill "decision_logic" with the heuristics you actually applied, keyed by
     field name, so a reviewer can reuse them on other articles.
 10. If nothing should change, return an empty suggestions array.

Respond with strict JSON and nothing else — no prose, no markdown fences:
{"summary": "...",
 "suggestions": [
   {"field": "...", "current": <any>, "suggested": <any>, "rationale": "...",
    "justification": "...", "evidence": "...", "confidence": "low|medium|high"}
 ],
 "decision_logic": {"<field>": "..."}}
"""


class SuggestRequest(BaseModel):
    """Ask an LLM to review a payload and save a report (read-only)."""

    original_id: str
    collection: str = CANONICAL_COLLECTION
    fields: list[str] | None = Field(
        None,
        description="Which fields to ask about; default = the reviewable fields that are empty or 'unknown'.",
    )
    include_content: bool = Field(
        False,
        description="Also propose content edits (off by default — highest hallucination risk).",
    )
    instructions: str | None = Field(None, description="Optional extra guidance for the model")
    provider: str | None = Field(None, description="LLM provider id; defaults to the configured provider")
    model: str | None = Field(None, description="Model id; defaults to the provider's first catalog model")
    save_report: bool = Field(
        True,
        description="Write the review report to <law_dir>/_mapping/enrichment/ (nothing is written to Qdrant).",
    )


def _is_empty(value: Any) -> bool:
    """Whether a payload value records nothing (used to pick review candidates)."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "unknown", "n/a", "none", "null"}
    if isinstance(value, list | tuple | dict | set):
        return not value
    return False


def _review_field_list(live: Mapping[str, Any], requested: list[str] | None, include_content: bool) -> list[str]:
    """Resolve the field allow-list for one review request.

    ``content`` is always opt-in: it is dropped from an explicit request too,
    unless ``include_content`` is set, because it is the highest-risk field. The
    enrichment fields are dropped when the payload has no schema-v1 shape,
    because that payload cannot hold them.
    """
    enrichment_ok = "schema_version" in live
    if requested:
        unknown = sorted(set(requested) - EDITABLE_PAYLOAD_FIELDS)
        if unknown:
            raise HTTPException(status_code=400, detail=f"field(s) not editable: {', '.join(unknown)}")
        fields = [
            f
            for f in requested
            if f in _REVIEWABLE_FIELDS
            and (f != "content" or include_content)
            and (enrichment_ok or f not in ENRICHMENT_PAYLOAD_FIELDS)
        ]
        if not fields:
            raise HTTPException(status_code=400, detail="no reviewable field requested")
        return fields

    fields = [f for f in _DEFAULT_REVIEW_FIELDS if f in _REVIEWABLE_FIELDS and (enrichment_ok or f not in ENRICHMENT_FIELDS)]
    for field_name in sorted(_REVIEWABLE_FIELDS):
        if field_name == "content" or field_name in fields:
            continue
        if field_name in ENRICHMENT_PAYLOAD_FIELDS and not enrichment_ok:
            continue
        if _is_empty(live.get(field_name)):
            fields.append(field_name)
    if include_content and "content" not in fields:
        fields.append("content")
    return fields


def _expected_review_payload(article: LawArticle, live: Mapping[str, Any], point_id: str) -> dict[str, Any]:
    """The payload the ingester would write today, in the shape the live one uses."""
    if "schema_version" in live:  # schema-v1 (local) payloads have a different shape
        return article.local_payload()
    return _expected_payload(article, point_id)


def _source_snippet(article: LawArticle, live: Mapping[str, Any], max_chars: int = _SNIPPET_CHARS) -> str:
    """Best-effort source context for one article; never raises."""
    text = ""
    try:
        text = _resolve_source(article.source_path).read_text(encoding="utf-8", errors="replace")
    except (HTTPException, OSError):
        text = ""
    if not text:
        text = str(live.get("content") or article.content or "")
    if not text:
        return ""

    needle = (article.content or "").strip()[:120]
    if needle and needle in text:
        start = max(0, text.index(needle) - max_chars // 4)
        return text[start : start + max_chars]
    return text[:max_chars]


def _confidence(value: Any) -> str:
    level = str(value or "medium").strip().lower()
    return level if level in {"low", "medium", "high"} else "medium"


def _type_compatible(existing: Any, suggested: Any) -> bool:
    """Reject a suggestion the shared PATCH validator would refuse anyway."""
    if isinstance(existing, list):
        return isinstance(suggested, list) and all(isinstance(item, str) for item in suggested)
    return isinstance(suggested, str)


def _kind_compatible(field_name: str, existing: Any, suggested: Any) -> bool:
    """Type check against the field's *declared* shape, not its current value.

    An enrichment field has one fixed kind, so a payload that happens to record
    ``sanctions: null`` instead of ``[]`` must not cause every sanctions
    proposal to be dropped as a type mismatch.
    """
    kind = ENRICHMENT_FIELD_KINDS.get(field_name)
    if kind == "array":
        return isinstance(suggested, list) and all(isinstance(item, str) for item in suggested)
    if kind == "scalar":
        return suggested is None or isinstance(suggested, str)
    return _type_compatible(existing, suggested)


def _clean_suggestions(
    raw: Any, live: Mapping[str, Any], fields: list[str]
) -> tuple[list[dict[str, Any]], int]:
    """Keep only suggestions on an allowed field that really change the payload.

    Enrichment values are lifted onto the controlled vocabulary first — so a
    model that answers ``dever`` or ``Prohibition`` still lands on ``duty`` /
    ``prohibitive`` — and the rewrite is reported rather than applied silently.
    A token that stays unknown is kept and flagged; it is evidence of a concept
    the vocabulary is missing, not noise.
    """
    allowed = set(fields)
    clean: list[dict[str, Any]] = []
    dropped = 0
    for item in raw or []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        field_name = item.get("field")
        suggested = item.get("suggested")
        if field_name not in allowed:
            dropped += 1
            continue

        renames: list[dict[str, str]] = []
        unknown: list[str] = []
        if field_name in ENRICHMENT_PAYLOAD_FIELDS:
            suggested, renames, unknown = normalize_value(field_name, suggested)

        if not _kind_compatible(field_name, live.get(field_name), suggested):
            dropped += 1
            continue
        if live.get(field_name) == suggested:
            dropped += 1
            continue
        clean.append(
            {
                "field": field_name,
                "current": live.get(field_name),
                "suggested": suggested,
                "rationale": str(item.get("rationale") or "").strip(),
                "justification": str(item.get("justification") or "").strip(),
                "evidence": str(item.get("evidence") or "").strip(),
                "confidence": _confidence(item.get("confidence")),
                "normalized_from": renames,
                "unknown_tokens": unknown,
                "vocabulary": "proposal" if unknown else "controlled",
            }
        )
    # Enrichment first, in the report's canonical order, then the rest.
    order = {name: index for index, name in enumerate((*ENRICHMENT_FIELDS, "tags", "doc_type", "theme", "title"))}
    clean.sort(key=lambda row: (order.get(str(row["field"]), 99), str(row["field"])))
    return clean, dropped


@router.post("/suggest")
def suggest_payload(request: SuggestRequest) -> dict[str, Any]:
    """Review one article's payload with an LLM and save a report.

    Read-only with respect to Qdrant: nothing in the index is written here. The
    caller reviews the checklist and applies what it wants through
    ``PATCH /payload``, so the write path stays the single, already-trusted one.
    The *report* is written to ``<law_dir>/_mapping/enrichment/`` — that
    directory is excluded from corpus discovery, and it is what makes the review
    auditable after the fact.
    """
    index = get_index()
    try:
        live = index.get_article(request.original_id, collection=request.collection)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Qdrant unavailable: {exc}") from exc

    corpus = _corpus_article(index, request.original_id)
    if live is None and corpus is None:
        raise HTTPException(status_code=404, detail=f"Unknown article: {request.original_id}")

    live_view: dict[str, Any] = live or {}
    fields = _review_field_list(live_view, request.fields, request.include_content)
    enrichment_in_scope = [name for name in ENRICHMENT_FIELDS if name in fields]

    notes: list[str] = []
    if live_view and "schema_version" not in live_view:
        notes.append(
            "This payload uses the shared canonical schema, which does not carry the enrichment "
            "fields — switch the modal to the local collection to review them."
        )

    point_id = live_view.get("id") or (corpus.point_id if corpus else "")
    expected_view = _expected_review_payload(corpus, live_view, point_id) if corpus else {}
    snippet = _source_snippet(corpus, live_view) if corpus else ""

    def _slice(source: Mapping[str, Any]) -> dict[str, Any]:
        out = {key: source[key] for key in fields if key in source}
        # Context the model needs even when it may not edit these.
        for key in ("title", "framework_code", "jurisdiction", "language", "source_file"):
            if key in source:
                out.setdefault(key, source[key])
        return out

    user_prompt = json.dumps(
        {
            "allowed_fields": fields,
            "CURRENT": _slice(live_view),
            "EXPECTED": _slice(expected_view),
            "SNIPPET": snippet,
            # Pass every reviewed field, not just the enrichment ones: `doc_type`
            # is reviewed alongside them and carries its own taxonomy, without
            # which the model has no token to propose and declines the field.
            "vocabulary": vocabulary_block(fields) or "",
            "extra_instructions": request.instructions or "",
        },
        ensure_ascii=False,
        indent=2,
    )

    try:
        result = call_llm_json(
            _SUGGEST_SYSTEM,
            user_prompt,
            provider=request.provider,
            model=request.model,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("[law] LLM review failed for %s", request.original_id)
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}") from exc

    result = result or {}
    suggestions, dropped = _clean_suggestions(result.get("suggestions"), live_view, fields)

    record: dict[str, Any] = {
        "original_id": request.original_id,
        "collection": request.collection,
        "title": live_view.get("title") or (corpus.title if corpus else ""),
        "source_path": (corpus.source_path if corpus else None) or live_view.get("source_path") or "",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": request.provider or "",
        "model": result.get("_model") or "",
        "fields_reviewed": fields,
        "enrichment_fields": enrichment_in_scope,
        "include_content": request.include_content,
        "summary": str(result.get("summary") or "").strip(),
        "suggestions": suggestions,
        "dropped": dropped,
        "current": {name: live_view.get(name) for name in fields},
        "decision_logic": result.get("decision_logic") if isinstance(result.get("decision_logic"), dict) else {},
        "applied": (load_record(law_dir(), request.original_id) or {}).get("applied") or [],
    }

    report_path: str | None = None
    if request.save_report:
        try:
            written = write_report(law_dir(), record)
            report_path = str(written)
        except OSError as exc:  # a read-only corpus must not fail the review
            logger.warning("[law] could not save the review report for %s: %s", request.original_id, exc)
            notes.append(f"The report could not be saved: {exc}")

    return {
        "original_id": request.original_id,
        "collection": request.collection,
        "mode": "enrichment" if enrichment_in_scope else "metadata",
        "fields_reviewed": fields,
        "enrichment_fields": enrichment_in_scope,
        "suggestions": suggestions,
        "dropped": dropped,
        "summary": record["summary"],
        "decision_logic": record["decision_logic"],
        "notes": notes,
        "report": render_report(record),
        "report_path": report_path,
        "report_name": Path(report_path).name if report_path else None,
        "saved": report_path is not None,
        "model": result.get("_model"),
        "usage": result.get("_usage"),
    }


@router.get("/reports")
def get_reports() -> dict[str, Any]:
    """List the saved enrichment reports (newest first)."""
    return {"reports": list_reports(law_dir())}


@router.get("/reports/{name}", response_class=PlainTextResponse)
def get_report(name: str) -> PlainTextResponse:
    """Return one saved enrichment report as Markdown."""
    if not is_report_name(name):
        raise HTTPException(status_code=400, detail=f"Invalid report name: {name!r}")
    base = (law_dir() / "_mapping" / REPORT_SUBDIR).resolve()
    candidate = (base / name).resolve()
    if not candidate.is_relative_to(base) or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"Report not found: {name}")
    return PlainTextResponse(candidate.read_text(encoding="utf-8"), media_type="text/markdown")


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
