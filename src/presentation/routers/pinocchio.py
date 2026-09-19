"""Pinocchio frontend router.

Serves the Pinocchio HTML UI at `/` and `/pinocchio`, and exposes
`/api/pinocchio/*` aliases that 307-redirect to the canonical backend
routes (`/api/diarization/*`, `/api/transcripts/*`). 307 preserves both
HTTP method and request body, so multipart uploads work transparently.

English (`-en`) variants of the two main UIs are served alongside the
original templates; each falls back to its default counterpart when the
translated file is not present.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pinocchio"])

# Resolve template paths once
_TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "templates"
_PINOCCIO_TEMPLATE = _TEMPLATE_DIR / "pinocchio.html"
_REVISION_TEMPLATE = _TEMPLATE_DIR / "revision.html"
_CURADORIA_TEMPLATE = _TEMPLATE_DIR / "curadoria.html"
_PINOCCIO_EN_TEMPLATE = _TEMPLATE_DIR / "pinocchio-en.html"
_REVISION_EN_TEMPLATE = _TEMPLATE_DIR / "revision-en.html"
_SPEAKERS_REGISTRY_TEMPLATE = _TEMPLATE_DIR / "speakers-registry.html"
_LAW_REGISTRY_TEMPLATE = _TEMPLATE_DIR / "law-registry.html"


def _first_existing(*candidates: Path) -> Path:
    """Return the first template that exists, or the first candidate."""
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


@router.get("/", include_in_schema=False)
@router.get("/pinocchio", include_in_schema=False)
async def serve_pinocchio_ui() -> FileResponse:
    if not _PINOCCIO_TEMPLATE.exists():
        raise HTTPException(status_code=404, detail=f"UI template missing: {_PINOCCIO_TEMPLATE}")
    return FileResponse(str(_PINOCCIO_TEMPLATE), media_type="text/html")

@router.get("/revision", include_in_schema=False)
async def serve_revision() -> FileResponse:
    path = _REVISION_TEMPLATE if _REVISION_TEMPLATE.exists() else _PINOCCIO_TEMPLATE
    return FileResponse(str(path), media_type="text/html")

@router.get("/curadoria", include_in_schema=False)
async def serve_curadorias() -> FileResponse:
    path = _CURADORIA_TEMPLATE if _CURADORIA_TEMPLATE.exists() else _PINOCCIO_TEMPLATE
    return FileResponse(str(path), media_type="text/html")

@router.get("/speakers-registry", include_in_schema=False)
async def serve_speakers_registry() -> FileResponse:
    if not _SPEAKERS_REGISTRY_TEMPLATE.exists():
        raise HTTPException(status_code=404, detail=f"UI template missing: {_SPEAKERS_REGISTRY_TEMPLATE}")
    return FileResponse(str(_SPEAKERS_REGISTRY_TEMPLATE), media_type="text/html")


@router.get("/law-registry", include_in_schema=False)
async def serve_law_registry() -> FileResponse:
    """Law corpus registry browser (backed by /api/law/*)."""
    if not _LAW_REGISTRY_TEMPLATE.exists():
        raise HTTPException(status_code=404, detail=f"UI template missing: {_LAW_REGISTRY_TEMPLATE}")
    return FileResponse(str(_LAW_REGISTRY_TEMPLATE), media_type="text/html")


# ── English UI variants ───────────────────────────────────────────────────


@router.get("/pinocchio-en", include_in_schema=False)
async def serve_pinocchio_ui_en() -> FileResponse:
    """English Pinocchio UI, falling back to the default template."""
    path = _first_existing(_PINOCCIO_EN_TEMPLATE, _PINOCCIO_TEMPLATE)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"UI template missing: {path}")
    return FileResponse(str(path), media_type="text/html")


@router.get("/revision-en", include_in_schema=False)
async def serve_revision_en() -> FileResponse:
    """English revision UI, falling back to the default template."""
    path = _first_existing(_REVISION_EN_TEMPLATE, _REVISION_TEMPLATE, _PINOCCIO_TEMPLATE)
    return FileResponse(str(path), media_type="text/html")


# ── /api/pinocchio/* aliases (307 preserves method + body) ────────────────


def _redirect(target: str) -> RedirectResponse:
    return RedirectResponse(url=target, status_code=307)


@router.post("/api/pinocchio/transcribe", include_in_schema=False)
async def alias_transcribe() -> RedirectResponse:
    return _redirect("/api/diarization/transcribe")


@router.post("/api/pinocchio/transcribe/async", include_in_schema=False)
async def alias_transcribe_async() -> RedirectResponse:
    return _redirect("/api/diarization/transcribe/async")


@router.post("/api/pinocchio/transcribe/guided", include_in_schema=False)
async def alias_transcribe_guided() -> RedirectResponse:
    return _redirect("/api/diarization/transcribe/guided")


@router.post("/api/pinocchio/transcribe/guided/async", include_in_schema=False)
async def alias_transcribe_guided_async() -> RedirectResponse:
    return _redirect("/api/diarization/transcribe/guided/async")


@router.get("/api/pinocchio/transcripts", include_in_schema=False)
async def alias_list_transcripts() -> RedirectResponse:
    return _redirect("/api/transcripts")


@router.get("/api/pinocchio/transcripts/{transcript_id}", include_in_schema=False)
async def alias_get_transcript(transcript_id: str) -> RedirectResponse:
    return _redirect(f"/api/transcripts/{transcript_id}")


# ── Endpoints the legacy UI expects but that aren't implemented here ──────
# Return a structured 501 so the frontend shows a clear error rather than
# falling back to noisy network failures.


_NOT_IMPLEMENTED = {
    "error": "not_implemented",
    "detail": (
        "This endpoint is part of the legacy Pinocchio gateway and is not "
        "available in this transcription service build. Use the diarization "
        "and guided transcription endpoints instead."
    ),
}


@router.post("/api/pinocchio/transcribe/pyannote", include_in_schema=False)
async def alias_transcribe_pyannote() -> RedirectResponse:
    """Pyannote provider proxy alias to the canonical transcription route.

    The Pinocchio UI keeps a dedicated provider path. Route it to the same
    transcription pipeline so localhost deployments keep the refined workflow.
    """
    return _redirect("/api/diarization/transcribe")


@router.post("/api/pinocchio/voiceprint_from_file", include_in_schema=False)
async def stub_voiceprint() -> JSONResponse:
    return JSONResponse(_NOT_IMPLEMENTED, status_code=501)


