"""Speaker registry router.

Serves the speaker knowledge base consumed by ``templates/speakers-registry.html``:

  * ``GET /api/speakers/index``  — the generated ``data/speaker_index.json``
    (mapped speakers + per-transcript/segment appearances).
  * ``GET /api/speakers/files``  — the manifest of ``data/speakers/*.md`` files.
  * ``GET /api/speakers/{id}``   — a single speaker's raw markdown.

The markdown files themselves are also exposed read-only under ``/speakers``
(a ``StaticFiles`` mount in ``src/main.py``) so the registry can fetch them
directly.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/speakers", tags=["speakers"])

_SAFE_ID_RE = None  # compiled lazily to keep import cheap


def _safe_stem(name: str) -> str:
    """Reject path traversal; allow only a bare filename stem."""
    import re

    global _SAFE_ID_RE
    if _SAFE_ID_RE is None:
        _SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
    if not name or not _SAFE_ID_RE.match(name):
        raise HTTPException(status_code=400, detail=f"Invalid speaker id: {name!r}")
    return name


def _speakers_dir() -> Path:
    return Path(settings.SPEAKERS_DIR)


def _index_path() -> Path:
    return Path(settings.SPEAKER_INDEX_FILE)


@router.get("/index")
async def get_speaker_index() -> dict:
    """Return the full speaker index (summary + mapped speakers)."""
    path = _index_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Speaker index not found: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.exception("[speakers] invalid speaker index JSON")
        raise HTTPException(status_code=500, detail=f"Invalid speaker index: {e}") from e


@router.get("/files")
async def list_speaker_files() -> dict:
    """List the speaker markdown files available on disk."""
    directory = _speakers_dir()
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail=f"Speakers directory missing: {directory}")
    names = sorted(f.name for f in directory.glob("*.md"))
    return {"count": len(names), "files": names}


@router.get("/{speaker_id}", response_class=PlainTextResponse)
async def get_speaker_markdown(speaker_id: str) -> PlainTextResponse:
    """Return the raw markdown for a single speaker."""
    stem = _safe_stem(speaker_id.removesuffix(".md"))
    path = _speakers_dir() / f"{stem}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Speaker not found: {stem}")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")
