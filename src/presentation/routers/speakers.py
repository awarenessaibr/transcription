"""Speaker registry router.

Serves the speaker knowledge base consumed by ``templates/speakers-registry.html``
and the resolution surface used by the Pinocchio capture UI:

Read (existing)
  * ``GET /api/speakers/index``  — the generated ``data/speaker_index.json``
    (mapped speakers + per-transcript/segment appearances).
  * ``GET /api/speakers/files``  — the manifest of ``data/speakers/*.md`` files.
  * ``GET /api/speakers/{id}``   — a single speaker's raw markdown.

Resolution (new)
  * ``GET  /api/speakers/candidates``      — the known cast for a recording.
  * ``POST /api/speakers/resolve``         — propose ``SPEAKER_nn -> SPK-...``.
  * ``POST /api/speakers/map``             — apply a confirmed mapping.
  * ``GET  /api/speakers/map/{id}``        — the mapping stored on a transcript.
  * ``POST /api/speakers/segment-map/rebuild`` — regenerate the consumable map.
  * ``GET  /api/speakers/segment-map``     — the consumable map (external use).

The route order matters: ``/{speaker_id}`` is declared last so it cannot shadow
the literal paths above.

The markdown files are also exposed read-only under ``/speakers`` (a
``StaticFiles`` mount in ``src/main.py``) so the registry can fetch them directly.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from src.config import settings
from src.infrastructure.speaker_registry_store import SpeakerRegistryStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/speakers", tags=["speakers"])

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Injected by the composition root.
_store = None
_registry: SpeakerRegistryStore | None = None


def init_speakers_router(transcript_store) -> None:
    """Wire the transcript store used for resolve/apply/rebuild."""
    global _store, _registry
    _store = transcript_store
    _registry = SpeakerRegistryStore(settings.SPEAKERS_DIR, settings.SPEAKER_INDEX_FILE)


def _require_store():
    if _store is None:
        raise HTTPException(status_code=503, detail="Transcript store not configured")
    return _store


def _require_registry() -> SpeakerRegistryStore:
    if _registry is None:
        # Allow read-only use before init (e.g. tests hitting /index only).
        return SpeakerRegistryStore(settings.SPEAKERS_DIR, settings.SPEAKER_INDEX_FILE)
    return _registry


def _safe_stem(name: str) -> str:
    """Reject path traversal; allow only a bare filename stem."""
    if not name or not _SAFE_ID_RE.match(name):
        raise HTTPException(status_code=400, detail=f"Invalid speaker id: {name!r}")
    return name


def _speakers_dir() -> Path:
    return Path(settings.SPEAKERS_DIR)


def _index_path() -> Path:
    return Path(settings.SPEAKER_INDEX_FILE)


def _load_transcript(transcript_id: str):
    store = _require_store()
    try:
        transcript = store.load(transcript_id)
    except Exception as exc:  # invalid id (traversal etc.) or unreadable file
        raise HTTPException(status_code=400, detail=f"Invalid transcript id: {exc}") from exc
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")
    return transcript


def _all_transcripts() -> list:
    store = _require_store()
    out = []
    for tid in store.list_ids():
        try:
            t = store.load(tid)
        except Exception:
            logger.warning("[speakers] skipping unreadable transcript %s", tid)
            continue
        if t is not None:
            out.append(t)
    return out


# ── read: registry ────────────────────────────────────────────────────────


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


# ── resolution ────────────────────────────────────────────────────────────


@router.get("/candidates")
async def get_candidates(transcript_id: str) -> dict:
    """The known cast for a recording, and the profiles behind it.

    Answers "who could this be?" before any label is resolved. For a new run over
    a known recording this is derived from the peer transcripts sharing its
    ``audio_id``, which is what makes a fresh diarization tractable.
    """
    registry = _require_registry()
    transcript = _load_transcript(transcript_id)
    peers = SpeakerRegistryStore.audio_peers(_all_transcripts(), transcript)
    cast_ids = registry.known_cast_for(transcript, peer_transcript_ids=peers)
    profiles = registry.load_profiles()
    return {
        "transcript_id": transcript_id,
        "audio_id": transcript.audio_id,
        "peer_transcripts": peers,
        "known_cast": [
            profiles[s].to_dict() if s in profiles else {"speaker_id": s} for s in cast_ids
        ],
        "registry_size": len(profiles),
        "note": (
            "no known cast for this recording; resolution falls back to content "
            "signals (verbatim statements, alias labels)"
            if not cast_ids
            else ""
        ),
    }


class ResolveRequest(BaseModel):
    transcript_id: str
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


@router.post("/resolve")
async def resolve_transcript(payload: ResolveRequest) -> dict:
    """Propose a label -> speaker mapping for a transcript. Writes nothing."""
    registry = _require_registry()
    transcript = _load_transcript(payload.transcript_id)
    peers = SpeakerRegistryStore.audio_peers(_all_transcripts(), transcript)
    resolution = registry.resolve(
        transcript, peer_transcript_ids=peers
    )
    body = resolution.to_dict()
    from src.application.services.speaker_resolver import proposals_to_map

    body["proposed_map"] = proposals_to_map(
        resolution, min_confidence=payload.min_confidence
    )
    body["peer_transcripts"] = peers
    return body


class SpeakerMapRequest(BaseModel):
    transcript_id: str
    speaker_map: dict[str, str] = Field(default_factory=dict)
    reason: str = "speaker mapping (review UI)"
    dry_run: bool = False


def _mapping_payload(transcript) -> dict:
    """The mapping as it currently stands on a transcript.

    Prefers the per-segment ``speaker_id`` (what :func:`apply_speaker_map`
    writes) and falls back to the participants' ``segment_labels`` (how the
    pre-existing corpus records it), so both generations report the same shape.
    """
    labels = sorted({s.speaker.label for s in transcript.segments or []})
    by_segment = {
        s.speaker.label: s.speaker_id
        for s in (transcript.segments or [])
        if s.speaker_id
    }
    by_participant = SpeakerRegistryStore.participant_labels(transcript)
    mapping = {lbl: by_segment.get(lbl) or by_participant[lbl] for lbl in labels if lbl in by_segment or lbl in by_participant}
    return {
        "transcript_id": transcript.transcript_id,
        "audio_id": transcript.audio_id,
        "labels": labels,
        "speaker_map": mapping,
        "resolved_count": len(mapping),
        "unresolved_labels": [lbl for lbl in labels if lbl not in mapping],
        "source": "segment.speaker_id" if by_segment else "participants",
    }


@router.post("/map")
async def apply_speaker_map(payload: SpeakerMapRequest) -> dict:
    """Apply a confirmed ``raw label -> speaker id`` mapping to a transcript.

    This is the only endpoint here that writes. It sets ``segment.speaker_id``,
    registers the label on the owning participant (the bridge the existing index
    generator reads), and appends an auditable ``corrections_applied`` entry. It
    never rewrites ``segment.speaker``, so nothing keyed on the raw/curated label
    breaks.
    """
    registry = _require_registry()
    store = _require_store()
    transcript = _load_transcript(payload.transcript_id)

    if not payload.speaker_map:
        raise HTTPException(status_code=400, detail="speaker_map must not be empty")

    updated, report = registry.apply_map(
        transcript, payload.speaker_map, reason=payload.reason
    )
    report["dry_run"] = payload.dry_run
    if not payload.dry_run:
        try:
            store.save(updated)
        except ValueError as exc:  # schema gate refused the document
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        report["saved"] = True
    else:
        report["saved"] = False
    report.update(_mapping_payload(updated if not payload.dry_run else updated))
    return report


@router.get("/map/{transcript_id}")
async def get_speaker_map(transcript_id: str) -> dict:
    """The mapping currently stored on a transcript."""
    transcript = _load_transcript(transcript_id)
    return _mapping_payload(transcript)


# ── consumable artifact ───────────────────────────────────────────────────


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Same tmp+fsync+replace discipline as the transcript store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            logger.warning("[speakers] could not remove temp file %s", tmp)
        raise


@router.post("/segment-map/rebuild")
async def rebuild_segment_map() -> dict:
    """Regenerate the consumable speaker+segment map from the transcripts.

    Also refreshes ``data/speaker_index.json`` so the registry UI reflects any
    mappings applied since it was last built.
    """
    registry = _require_registry()
    transcripts = _all_transcripts()
    payload = registry.build_segment_map(transcripts)

    out = Path(settings.SPEAKER_MAP_FILE)
    _write_json_atomic(out, payload)
    await _refresh_speaker_index(transcripts)

    return {
        "written": str(out),
        "schema_version": payload["schema_version"],
        "speaker_count": payload["speaker_count"],
        "transcript_count": payload["transcript_count"],
        "unresolved_labels": len(payload["unresolved_segment_labels"]),
    }


@router.get("/segment-map")
async def get_segment_map() -> dict:
    """The consumable speaker+segment map, built on demand when absent.

    Shape is stable and ``schema_version``-guarded; see
    :meth:`SpeakerRegistryStore.build_segment_map`.
    """
    path = Path(settings.SPEAKER_MAP_FILE)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("[speakers] rebuilding invalid segment map at %s", path)
    registry = _require_registry()
    return registry.build_segment_map(_all_transcripts())


async def _refresh_speaker_index(transcripts: list) -> None:
    """Rewrite ``speaker_index.json`` at the CONFIGURED path, in-process.

    Deliberately does not shell out to ``scripts/generate_speaker_index_v3.py``:
    that script hardcodes ``data/speaker_index.json``, so it ignores
    ``SPEAKER_INDEX_FILE`` and writes into the repository even when the app is
    configured elsewhere (which it did, from a test, in an earlier revision).
    """
    import asyncio

    registry = _require_registry()
    payload = await asyncio.to_thread(registry.build_speaker_index, transcripts)
    _write_json_atomic(_index_path(), payload)


# ── single speaker (declared last so it cannot shadow literal paths) ───────


@router.get("/{speaker_id}", response_class=PlainTextResponse)
async def get_speaker_markdown(speaker_id: str) -> PlainTextResponse:
    """Return the raw markdown for a single speaker."""
    stem = _safe_stem(speaker_id.removesuffix(".md"))
    path = _speakers_dir() / f"{stem}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Speaker not found: {stem}")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")
