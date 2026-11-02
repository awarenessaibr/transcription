"""Pinocchio frontend router.

Serves the two active UIs:

* ``/``, ``/pinocchio`` and ``/pinocchio-en`` -> ``templates/pinocchio-en.html``
* ``/revision`` and ``/revision-en``           -> ``templates/revision-en.html``
* ``/aligner``                                 -> ``templates/aligner.html``

The Spanish twins (``pinocchio.html`` / ``revision.html``) were retired in favour
of the English pair; the Spanish URLs are kept as aliases so existing links and
bookmarks continue to work. ``/curadoria`` was removed along with its template.

It also exposes ``/api/pinocchio/*`` aliases that 307-redirect to the canonical
backend routes (``/api/diarization/*``, ``/api/transcripts/*``). 307 preserves
both HTTP method and request body, so multipart uploads work transparently.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pinocchio"])

# Resolve template paths once. The English variants are canonical.
_TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "templates"
_PINOCCIO_TEMPLATE = _TEMPLATE_DIR / "pinocchio-en.html"
_REVISION_TEMPLATE = _TEMPLATE_DIR / "revision-en.html"
_ALIGNER_TEMPLATE = _TEMPLATE_DIR / "aligner.html"
_SPEAKERS_REGISTRY_TEMPLATE = _TEMPLATE_DIR / "speakers-registry.html"


def _serve(path: Path) -> FileResponse:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"UI template missing: {path}")
    return FileResponse(str(path), media_type="text/html")


@router.get("/", include_in_schema=False)
@router.get("/pinocchio", include_in_schema=False)
@router.get("/pinocchio-en", include_in_schema=False)
async def serve_pinocchio_ui() -> FileResponse:
    """Capture / diarization / analysis UI."""
    return _serve(_PINOCCIO_TEMPLATE)


@router.get("/revision", include_in_schema=False)
@router.get("/revision-en", include_in_schema=False)
async def serve_revision() -> FileResponse:
    """Transcript curation & review UI."""
    return _serve(_REVISION_TEMPLATE)


@router.get("/speakers-registry", include_in_schema=False)
async def serve_speakers_registry() -> FileResponse:
    return _serve(_SPEAKERS_REGISTRY_TEMPLATE)


@router.get("/aligner", include_in_schema=False)
async def serve_aligner() -> FileResponse:
    """Narration-to-audio timestamp alignment UI."""
    return _serve(_ALIGNER_TEMPLATE)


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
