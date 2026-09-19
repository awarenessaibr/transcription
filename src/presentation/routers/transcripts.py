"""Transcript intelligence router — analyze, search, list, SSE stream, curation, metadata."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
import unicodedata
from dataclasses import replace as _replace
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.application.dto.schemas import AnalyzeRequest, SearchRequest
from src.config import settings
from src.domain.entities.transcript import Segment, Speaker, Transcript
from src.domain.entities.patch import Patch, PatchOp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/transcripts", tags=["transcripts"])

# Injected by composition root
_analyze_use_case = None
_search_use_case = None
_store = None
_index = None
_auditor = None
_patcher = None
_validate_refine_use_case = None
_asr = None
_audio_files = None
_event_store: list = []


def init_transcript_router(
    analyze_use_case,
    search_use_case,
    store,
    index=None,
    *,
    auditor=None,
    patcher=None,
    validate_refine_use_case=None,
    asr_adapter=None,
    audio_file_adapter=None,
    event_store=None,   # 👈 ADD THIS
):
    global _analyze_use_case, _search_use_case, _store, _index
    global _auditor, _patcher, _validate_refine_use_case, _asr, _audio_files
    global _event_store   # 👈 ADD THIS

    _analyze_use_case = analyze_use_case
    _search_use_case = search_use_case
    _store = store
    _index = index
    _auditor = auditor
    _patcher = patcher
    _validate_refine_use_case = validate_refine_use_case
    _asr = asr_adapter
    _audio_files = audio_file_adapter
    if event_store is not None:
        _event_store = event_store

# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename_stem(name: str) -> str:
    if not name:
        return ""
    base = os.path.basename(str(name)).strip()
    stem, _ext = os.path.splitext(base)
    cleaned = _SAFE_NAME_RE.sub("_", stem).strip("._-")
    return cleaned[:180]


# ------------------------------------------------------------------
# Segment audio (cut from source, cached on disk; uploads replace)
# ------------------------------------------------------------------
def _data_root_dir() -> str:
    base = os.path.dirname(settings.AUDIO_DIR) or settings.AUDIO_DIR
    if not os.path.isdir(base):
        base = "/home/leandrodisconzi/transcription/data"
    return base


def _segment_audio_dir(transcript_id: str) -> str:
    safe = _sanitize_filename_stem(transcript_id) or f"transcript_{abs(hash(transcript_id))}"
    d = os.path.join(_data_root_dir(), "segment_audio", safe)
    os.makedirs(d, exist_ok=True)
    return d


_AUDIO_EXTS = ("wav", "mp3", "m4a", "mp4")
# Tokens that carry no disambiguating value when matching a transcript to its source audio.
_NOISE_TOKENS = {"json", "curated", "final", "v1", "v2", "v3", "att", "aux", "sup"}
_TRANSCRIPT_ID_PREFIXES = ("json_", "json-", "json.")


def _normalize_for_match(value: str) -> str:
    """Lowercase, strip accents/diacritics, and collapse any non-alphanumeric run to a single space."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _candidate_stems(transcript, transcript_id: str) -> list[str]:
    """Ordered, normalized candidate stems derived from every identifying field available."""
    stems: list[str] = []

    def add(value: str) -> None:
        norm = _normalize_for_match(value)
        if norm and norm not in stems:
            stems.append(norm)

    add(transcript.source_file)
    add(os.path.splitext(os.path.basename(transcript.source_file or ""))[0])
    add(getattr(transcript, "audio_id", ""))
    add(getattr(transcript, "title", ""))
    add(getattr(transcript, "transcript_id", "") or transcript_id)

    tid = getattr(transcript, "transcript_id", "") or transcript_id
    lowered = tid.lower()
    for prefix in _TRANSCRIPT_ID_PREFIXES:
        if lowered.startswith(prefix):
            add(tid[len(prefix):])
            break

    return stems


def _stem_tokens(stem: str) -> set[str]:
    return {tok for tok in stem.split() if tok not in _NOISE_TOKENS}


def _match_score(audio_tokens: set[str], cand_tokens: set[str]) -> float:
    """Jaccard overlap, with a hard requirement that any number the candidate specifies
    must also appear in the audio filename (disambiguates 'Benítez.m4a' vs 'Benítez 29.m4a')."""
    if not audio_tokens or not cand_tokens:
        return 0.0
    audio_nums = {t for t in audio_tokens if t.isdigit()}
    cand_nums = {t for t in cand_tokens if t.isdigit()}
    if cand_nums and not cand_nums <= audio_nums:
        return 0.0
    inter = audio_tokens & cand_tokens
    union = audio_tokens | cand_tokens
    return len(inter) / len(union) if union else 0.0


def _iter_audio_files(folder: str) -> list[str]:
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.rsplit(".", 1)[-1].lower() in _AUDIO_EXTS)


def _locate_source_audio(transcript, transcript_id: str) -> Optional[str]:
    """Find the full source recording for a transcript (mirrors retranscribe logic)."""
    # 1) Fast path: exact filename (source_file or transcript_id fallback).
    audio_filename = transcript.source_file or f"{transcript_id}.m4a"
    search_names = [audio_filename, audio_filename + ".wav", os.path.basename(audio_filename)]
    for folder in [settings.AUDIO_DIR, settings.ORIGINALS_DIR, "/home/leandrodisconzi/transcription/data/audio"]:
        for name in search_names:
            possible_path = os.path.join(folder, name)
            if os.path.exists(possible_path):
                return possible_path

    # 2) Legacy stem match (kept for exact underscore/space-prefix behaviour).
    stems = [transcript_id]
    if transcript.source_file:
        stems.append(transcript.source_file)
        base = os.path.splitext(transcript.source_file)[0]
        if "_" in base:
            parts = base.split("_", 1)
            if parts[0] in ("audio", "segments"):
                stems.append(parts[1])
    for folder in [settings.AUDIO_DIR, settings.ORIGINALS_DIR]:
        for f in _iter_audio_files(folder):
            fl = os.path.splitext(f)[0].lower()
            for stem in stems:
                if fl == stem.lower() or fl.startswith(stem.lower().replace(" ", "_")):
                    return os.path.join(folder, f)

    # 3) Fuzzy match: accent-insensitive, prefix-aware, numeric-preserving token overlap.
    candidates = _candidate_stems(transcript, transcript_id)
    best_path = None
    best_score = 0.0
    for folder in [settings.AUDIO_DIR, settings.ORIGINALS_DIR]:
        for f in _iter_audio_files(folder):
            audio_tokens = _stem_tokens(_normalize_for_match(os.path.splitext(f)[0]))
            if not audio_tokens:
                continue
            for stem in candidates:
                score = _match_score(audio_tokens, _stem_tokens(stem))
                if score > best_score:
                    best_score = score
                    best_path = os.path.join(folder, f)

    if best_score >= 0.5:
        return best_path
    return None


def _extract_segment_cached(audio_path: str, seg_dir: str, segment_index: int, start_ms: int, end_ms: int) -> str:
    """Cut [start_ms, end_ms) from source audio, caching the result on disk."""
    cache_path = os.path.join(seg_dir, f"cut_{segment_index}_{int(start_ms)}_{int(end_ms)}.wav")
    if os.path.exists(cache_path):
        return cache_path

    temp_wav = None
    source_path = audio_path
    if not audio_path.lower().endswith(".wav"):
        _, ext = os.path.splitext(audio_path)
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
            shutil.copy(audio_path, tf.name)
            temp_copy = tf.name
        temp_wav = _audio_files.convert_to_wav(temp_copy)  # removes temp_copy
        source_path = temp_wav
    try:
        _audio_files.extract_segment(source_path, int(start_ms), int(end_ms), cache_path)
    finally:
        if temp_wav and os.path.exists(temp_wav):
            os.remove(temp_wav)
    return cache_path


# ------------------------------------------------------------------
# Pydantic models for new metadata and review endpoints
# ------------------------------------------------------------------
class MetadataUpdate(BaseModel):
    """Update transcript metadata (top‑level fields)."""
    title: Optional[str] = None
    subtitle: Optional[str] = None
    recording_datetime: Optional[str] = None
    location: Optional[str] = None
    audio_id: Optional[str] = None
    case_id: Optional[str] = None
    narrative_id: Optional[str] = None
    chronological_order: Optional[int] = None
    prior_stage: Optional[str] = None
    next_stage: Optional[str] = None
    classification: Optional[str] = None
    participants: Optional[List[Dict[str, Any]]] = None
    violations_cited: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    forensic_clusters: Optional[Dict[str, Any]] = None
    key_evidentiary_findings: Optional[List[Dict[str, Any]]] = None
    corrections_applied: Optional[List[Dict[str, Any]]] = None
    # optional: replace entire segment list
    segments: Optional[List[Dict[str, Any]]] = None


class SegmentUpdate(BaseModel):
    """Segment‑level edits (reviewed status, patches, text, speaker, start/end)."""
    reviewed_indices: List[int] = []
    patches: List["PatchPayload"] = Field(default_factory=list)
    edited_texts: Dict[int, str] = {}
    edited_speakers: Dict[int, str] = {}
    edited_starts: Dict[int, float] = {}
    edited_ends: Dict[int, float] = {}
    edited_correction_notes: Dict[int, str] = {}
    edited_backchannel_events: Dict[int, str] = {}
    recording_datetime: Optional[str] = None


class ReviewIndexPayload(BaseModel):
    collection: str = "reviewed_transcripts"
    create_if_missing: bool = True


class BatchIngestPayload(BaseModel):
    """Payload for the incremental batch-ingest queue.

    ``mode`` controls what gets indexed:
      * ``reviewed`` -> only segments flagged ``reviewed`` (default; mirrors the
                        per-transcript "Index in Qdrant" button)
      * ``all``      -> every segment of every transcript
    """
    source_dir: str = "data/transcripts/"
    qdrant_collection: str = "reviewed_transcripts"
    mode: str = "reviewed"
    reindex: bool = True


class ImportSegmentPayload(BaseModel):
    index: int | None = None
    speaker: str | None = None
    start: float | int | None = 0.0
    end: float | int | None = None
    text: str | None = ""
    reviewed: bool | None = False


class ImportRunPayload(BaseModel):
    transcript_id: str | None = None
    source_file: str | None = None
    filename: str | None = None
    language: str | None = None
    timestamp: str | None = None
    provider: str | None = None
    metadata: dict | None = None
    segments: list[ImportSegmentPayload] = Field(default_factory=list)


class ImportTranscriptsPayload(BaseModel):
    runs: list[ImportRunPayload] = Field(default_factory=list)
    overwrite: bool = False
    rename_by_filename: bool = True


class CSVImportPayload(BaseModel):
    filename: str
    overwrite: bool = True


class ReviewSavePayload(BaseModel):
    reviewed_indices: list[int]
    edited_texts: dict[str, str] | None = None
    edited_speakers: dict[str, str] | None = None
    recording_datetime: str | None = None


class RetranscribeSegmentsPayload(BaseModel):
    segment_indices: list[int]
    whisper_model: str = "large-v3"
    language: str = "es"
    beam_size: int = 5
    best_of: int = 5
    whisper_temp: float = 0.0
    condition_on_previous_text: bool = False
    include_reviewed: bool = False
    volume_gain_db: float = 0.0
    vad_enabled: bool = False
    vad_trigger_level: float = 7.0
    no_speech_threshold: float = 0.6
    initial_prompt: str | None = None


class PatchPayload(BaseModel):
    op: str
    segment_indices: list[int] = Field(default_factory=list)
    new_text: str | None = None
    new_speaker: str | None = None
    new_start: float | None = None
    new_end: float | None = None
    insert_after_index: int | None = None
    note: str | None = ""


class PatchSegmentsPayload(BaseModel):
    patches: list[PatchPayload] = Field(default_factory=list)
    save_as_new_id: bool = True


class RefinePayload(BaseModel):
    canonical_name: str | None = None
    use_acoustic_probes: bool = True
    apply_patches: bool = True
    save_as_new_id: bool = True
    max_acoustic_windows: int = 8


# ------------------------------------------------------------------
# Existing endpoints (list, get, import, analyze, search, index, etc.)
# ------------------------------------------------------------------
@router.get("")
async def list_transcripts():
    ids = _store.list_ids()
    return {"transcripts": sorted(ids, reverse=True)}


def _transcript_to_dict(transcript) -> dict:
    """Serialize a Transcript to the canonical API shape.

    Shared by ``GET /{transcript_id}`` and the review-save response so the
    frontend can apply the saved state without a follow-up round-trip.
    """
    return {
        "transcript_id": transcript.transcript_id,
        "source_file": transcript.source_file,
        "language": transcript.language,
        "timestamp": transcript.timestamp,
        "provider": transcript.provider,
        "original_transcript_id": transcript.original_transcript_id,
        "metadata": transcript.metadata or {},
        "title": transcript.title or "",
        "subtitle": transcript.subtitle or "",
        "recording_datetime": transcript.recording_datetime or "",
        "location": transcript.location or "",
        "audio_id": transcript.audio_id or "",
        "case_id": transcript.case_id or "",
        "narrative_id": transcript.narrative_id or "",
        "chronological_order": transcript.chronological_order,
        "prior_stage": transcript.prior_stage or "",
        "next_stage": transcript.next_stage or "",
        "classification": transcript.classification or "",
        "participants": transcript.participants or [],
        "violations_cited": transcript.violations_cited or [],
        "tags": transcript.tags or [],
        "forensic_clusters": transcript.forensic_clusters or {},
        "key_evidentiary_findings": transcript.key_evidentiary_findings or [],
        "corrections_applied": transcript.corrections_applied or [],
        "segments": [
            {
                "index": s.index,
                "speaker": s.speaker.label,
                "start": s.start,
                "end": s.end,
                "duration": s.duration,
                "text": s.text,
                "reviewed": getattr(s, "reviewed", False),
                "correction_note": getattr(s, "correction_note", ""),
                "backchannel_events": getattr(s, "backchannel_events", ""),
            }
            for s in transcript.segments
        ],
    }


@router.get("/{transcript_id}")
async def get_transcript(transcript_id: str):
    transcript = await asyncio.to_thread(_store.load, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")
    return _transcript_to_dict(transcript)


@router.post("/import")
async def import_transcripts(payload: ImportTranscriptsPayload):
    if _store is None:
        raise HTTPException(status_code=503, detail="Transcript store not initialized")
    if not payload.runs:
        raise HTTPException(status_code=400, detail="No runs provided for import")

    existing_ids = set(_store.list_ids())
    imported_ids = []
    skipped = []
    errors = []

    for idx, run in enumerate(payload.runs):
        try:
            segments = []
            for seg_idx, seg in enumerate(run.segments):
                start = float(seg.start or 0.0)
                if start < 0:
                    start = 0.0
                end_raw = seg.end if seg.end is not None else start
                end = float(end_raw)
                if end < start:
                    end = start
                speaker_label = (seg.speaker or f"SPEAKER_{seg_idx:02d}").strip() or f"SPEAKER_{seg_idx:02d}"
                segment_index = seg.index if seg.index is not None else seg_idx
                segments.append(
                    Segment(
                        index=int(segment_index),
                        speaker=Speaker(label=speaker_label),
                        start=start,
                        end=end,
                        text=str(seg.text or ""),
                        reviewed=bool(seg.reviewed),
                    )
                )
            if not segments:
                skipped.append({"index": idx, "reason": "empty_segments"})
                continue

            incoming_id = (run.transcript_id or "").strip()
            source_file = (run.source_file or run.filename or "").strip()
            filename_stem = _sanitize_filename_stem(run.filename or run.source_file or "")

            if payload.rename_by_filename and filename_stem:
                desired_id = filename_stem
            elif incoming_id:
                desired_id = incoming_id
            elif filename_stem:
                desired_id = filename_stem
            else:
                desired_id = f"imported_{int(time.time() * 1000)}_{idx + 1}"

            transcript_id = desired_id
            if not payload.overwrite and transcript_id in existing_ids:
                nonce = 1
                while transcript_id in existing_ids:
                    nonce += 1
                    transcript_id = f"{desired_id}_{nonce}"

            transcript = Transcript(
                transcript_id=transcript_id,
                segments=segments,
                source_file=source_file,
                language=(run.language or "es"),
                metadata=(run.metadata or {}),
                timestamp=(run.timestamp or ""),
                provider=(run.provider or ""),
                original_transcript_id=(incoming_id if incoming_id and incoming_id != transcript_id else ""),
            )
            _store.save(transcript)
            existing_ids.add(transcript_id)
            imported_ids.append(transcript_id)
        except Exception as e:
            errors.append({"index": idx, "transcript_id": run.transcript_id, "error": str(e)})

    return {
        "total_runs": len(payload.runs),
        "imported": len(imported_ids),
        "imported_ids": imported_ids,
        "skipped": skipped,
        "errors": errors,
    }


@router.post("/analyze")
async def analyze_transcript(payload: AnalyzeRequest):
    if _analyze_use_case is None:
        raise HTTPException(status_code=503, detail="Transcript analysis not configured")
    try:
        result = await _analyze_use_case.execute(payload.transcript_id, instructions=payload.instructions)
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("[error] analysis failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/search")
async def search_transcripts(payload: SearchRequest):
    if _search_use_case is None:
        raise HTTPException(status_code=503, detail="Transcript search not configured")
    try:
        result = await _search_use_case.execute(payload.query, limit=payload.limit)
        return result.model_dump()
    except Exception as e:
        logger.exception("[error] search failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{transcript_id}/index")
async def index_transcript(transcript_id: str, collection: str | None = Query(default=None)):
    if _index is None:
        raise HTTPException(status_code=503, detail="Vector indexing not configured")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")
    if collection:
        n = await _index.index(transcript, collection_name=collection)
    else:
        n = await _index.index(transcript)
    return {"transcript_id": transcript_id, "segments_indexed": n}


@router.post("/index-all")
async def index_all_transcripts():
    if _index is None:
        raise HTTPException(status_code=503, detail="Vector indexing not configured")
    ids = _store.list_ids()
    total = 0
    errors = []
    for tid in ids:
        transcript = _store.load(tid)
        if transcript is None:
            continue
        try:
            n = await _index.index(transcript)
            total += n
        except Exception as e:
            errors.append({"transcript_id": tid, "error": str(e)})
    return {"transcripts_processed": len(ids), "segments_indexed": total, "errors": errors}


@router.post("/batch_ingest")
async def batch_ingest(payload: BatchIngestPayload):
    """Index every transcript in the store, one at a time (queue).

    Each transcript is loaded, (optionally) cleared from the target collection
    and re-indexed before moving on to the next file. This keeps memory/CPU
    bounded and produces a deterministic, resumable-ish ingestion order.
    """
    if _index is None:
        raise HTTPException(status_code=503, detail="Vector indexing not configured")
    if _store is None:
        raise HTTPException(status_code=503, detail="Transcript store not configured")

    collection = (payload.qdrant_collection or "").strip() or "reviewed_transcripts"
    mode = (payload.mode or "reviewed").strip().lower()
    only_reviewed = mode != "all"

    ids = sorted(_store.list_ids())
    processed = 0
    skipped = 0
    segments_indexed = 0
    errors: list[dict] = []

    for tid in ids:
        transcript = _store.load(tid)
        if transcript is None:
            skipped += 1
            continue

        segments = transcript.segments
        if only_reviewed:
            segments = [s for s in segments if getattr(s, "reviewed", False)]

        # Clear the transcript's existing points up-front so that a transcript
        # whose reviewed segments were later un-reviewed does not leave stale
        # vectors behind. Mirrors the per-transcript "Index in Qdrant" button.
        if payload.reindex:
            try:
                await _index.delete(tid, collection_name=collection)
            except Exception as del_exc:  # noqa: BLE001 — deletion is best-effort
                logger.warning("[batch_ingest] delete failed for %s: %s", tid, del_exc)

        if not segments:
            skipped += 1
            continue

        target = _replace(transcript, segments=segments) if only_reviewed else transcript
        try:
            n = await _index.index(target, collection_name=collection)
            segments_indexed += n
            processed += 1
        except Exception as e:  # noqa: BLE001 — keep the queue going
            logger.exception("[batch_ingest] indexing failed for %s", tid)
            errors.append({"transcript_id": tid, "error": str(e)})

    return {
        "collection": collection,
        "source_dir": payload.source_dir,
        "mode": mode,
        "transcripts_found": len(ids),
        "processed": processed,
        "skipped": skipped,
        "segments_indexed": segments_indexed,
        "errors": errors,
    }


# ------------------------------------------------------------------
# SSE progress (unchanged)
# ------------------------------------------------------------------
_progress: dict[str, list[dict]] = {}
_jobs: dict[str, dict] = {}
_JOB_RETENTION_SEC = 3600


def _now_ts() -> float:
    return time.time()


def _cleanup_jobs() -> None:
    now = _now_ts()
    stale_ids = []
    for job_id, job in _jobs.items():
        updated_at = float(job.get("updated_at", now))
        if now - updated_at > _JOB_RETENTION_SEC:
            stale_ids.append(job_id)
    for job_id in stale_ids:
        _jobs.pop(job_id, None)
        _progress.pop(job_id, None)


def start_progress_job(job_id: str, filename: str | None = None) -> None:
    _cleanup_jobs()
    now = _now_ts()
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "stage": "upload",
        "progress": 0,
        "message": "Job enfileirado",
        "filename": filename,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "ended_at": None,
        "elapsed_s": 0.0,
        "result": None,
        "error": None,
    }
    _progress[job_id] = []
    emit_progress(job_id, "queued", {
        "job_id": job_id,
        "status": "queued",
        "stage": "upload",
        "progress": 0,
        "message": "Job enfileirado",
    })


def update_progress_job(job_id: str, *, stage: str, progress: int, message: str, status: str = "running", extra: dict | None = None) -> None:
    now = _now_ts()
    job = _jobs.get(job_id)
    if job is None:
        start_progress_job(job_id)
        job = _jobs[job_id]
    if job.get("started_at") is None and status == "running":
        job["started_at"] = now
    job.update({
        "status": status,
        "stage": stage,
        "progress": max(0, min(100, int(progress))),
        "message": message,
        "updated_at": now,
    })
    started_at = job.get("started_at") or job.get("created_at") or now
    job["elapsed_s"] = round(max(0.0, now - float(started_at)), 2)
    payload = {
        "job_id": job_id,
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "message": job["message"],
        "elapsed_s": job["elapsed_s"],
    }
    if extra:
        payload.update(extra)
    emit_progress(job_id, "progress", payload)


def complete_progress_job(job_id: str, result: dict) -> None:
    now = _now_ts()
    job = _jobs.get(job_id)
    if job is None:
        start_progress_job(job_id)
        job = _jobs[job_id]
    started_at = job.get("started_at") or job.get("created_at") or now
    elapsed_s = round(max(0.0, now - float(started_at)), 2)
    job.update({
        "status": "done",
        "stage": "transcription",
        "progress": 100,
        "message": "Concluído",
        "result": result,
        "updated_at": now,
        "ended_at": now,
        "elapsed_s": elapsed_s,
        "error": None,
    })
    emit_progress(job_id, "done", {
        "job_id": job_id,
        "status": "done",
        "stage": "transcription",
        "progress": 100,
        "message": "Concluído",
        "elapsed_s": elapsed_s,
    })


def fail_progress_job(job_id: str, error: str) -> None:
    now = _now_ts()
    job = _jobs.get(job_id)
    if job is None:
        start_progress_job(job_id)
        job = _jobs[job_id]
    started_at = job.get("started_at") or job.get("created_at") or now
    elapsed_s = round(max(0.0, now - float(started_at)), 2)
    job.update({
        "status": "error",
        "message": error,
        "updated_at": now,
        "ended_at": now,
        "elapsed_s": elapsed_s,
        "error": error,
    })
    emit_progress(job_id, "error", {
        "job_id": job_id,
        "status": "error",
        "message": error,
        "stage": job.get("stage") or "transcription",
        "progress": int(job.get("progress") or 0),
        "elapsed_s": elapsed_s,
    })


def get_progress_job(job_id: str) -> dict | None:
    _cleanup_jobs()
    job = _jobs.get(job_id)
    return dict(job) if job else None


def emit_progress(job_id: str, event_type: str, data: dict) -> None:
    if job_id not in _progress:
        _progress[job_id] = []
    _progress[job_id].append({"event": event_type, "data": data})


@router.get("/status/{job_id}")
async def get_progress_status(job_id: str):
    job = get_progress_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@router.get("/stream/{job_id}")
async def stream_progress(job_id: str, request: Request):
    async def event_generator():
        cursor = 0
        while True:
            if await request.is_disconnected():
                break
            events = _progress.get(job_id, [])
            while cursor < len(events):
                ev = events[cursor]
                yield {"event": ev["event"], "data": json.dumps(ev["data"])}
                cursor += 1
                if ev["event"] in ("done", "error"):
                    _progress.pop(job_id, None)
                    return
            await asyncio.sleep(0.3)
    return EventSourceResponse(event_generator())


# ------------------------------------------------------------------
# Audit, refine, patch (unchanged)
# ------------------------------------------------------------------
def _audit_to_payload(report) -> dict:
    return {
        "transcript_id": report.transcript_id,
        "counts_by_kind": report.kind_counts(),
        "counts_by_severity": report.severity_counts(),
        "anomalies": [
            {
                "kind": a.kind.value,
                "severity": a.severity.value,
                "segment_indices": list(a.segment_indices),
                "start": a.start,
                "end": a.end,
                "hint": a.hint,
                "detail": a.detail_dict(),
            }
            for a in report.anomalies
        ],
    }


@router.post("/{transcript_id}/audit")
async def audit_transcript_route(transcript_id: str):
    if _auditor is None or _store is None:
        raise HTTPException(status_code=503, detail="Auditor not configured")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")
    return _audit_to_payload(_auditor.audit(transcript))


@router.post("/{transcript_id}/refine")
async def refine_transcript_route(transcript_id: str, payload: RefinePayload | None = None):
    if _validate_refine_use_case is None:
        raise HTTPException(status_code=503, detail="Validate/refine use case not configured")
    body = payload or RefinePayload()
    try:
        result = await _validate_refine_use_case.execute(
            transcript_id,
            canonical_name=body.canonical_name,
            use_acoustic_probes=body.use_acoustic_probes,
            apply_patches=body.apply_patches,
            save_as_new_id=body.save_as_new_id,
            max_acoustic_windows=body.max_acoustic_windows,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("[error] refine failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return result.model_dump()


@router.post("/{transcript_id}/patch")
async def patch_transcript_route(transcript_id: str, payload: PatchSegmentsPayload):
    if _patcher is None or _store is None:
        raise HTTPException(status_code=503, detail="Patcher not configured")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    parsed = []
    for raw in payload.patches:
        try:
            op = PatchOp(raw.op)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"unknown patch op: {raw.op}") from exc
        parsed.append(
            Patch(
                op=op,
                segment_indices=tuple(int(i) for i in raw.segment_indices),
                new_text=raw.new_text,
                new_speaker=raw.new_speaker,
                new_start=raw.new_start,
                new_end=raw.new_end,
                insert_after_index=raw.insert_after_index,
                note=raw.note or "",
            )
        )

    patched, applied = _patcher.apply(transcript, parsed)
    if payload.save_as_new_id:
        new_id = f"{transcript_id}_patched_{int(time.time())}"
        patched = _replace(
            patched,
            transcript_id=new_id,
            original_transcript_id=transcript_id,
        )
    _store.save(patched)

    return {
        "transcript_id_in": transcript_id,
        "transcript_id_out": patched.transcript_id,
        "patches_applied": [
            {
                "op": p.op.value,
                "segment_indices": list(p.segment_indices),
                "new_text": p.new_text,
                "new_speaker": p.new_speaker,
                "new_start": p.new_start,
                "new_end": p.new_end,
                "insert_after_index": p.insert_after_index,
                "note": p.note,
            }
            for p in applied
        ],
    }


# ------------------------------------------------------------------
# CSV import / listing
# ------------------------------------------------------------------
@router.get("/csv/list")
async def list_csvs():
    csv_dir = os.path.join(os.path.dirname(settings.AUDIO_DIR), "csv")
    if not os.path.isdir(csv_dir):
        csv_dir = "/home/leandrodisconzi/transcription/data/csv"
    if not os.path.isdir(csv_dir):
        return {"csvs": []}
    files = [f for f in os.listdir(csv_dir) if f.endswith(".csv")]
    return {"csvs": sorted(files)}


@router.post("/csv/import")
async def import_csv(payload: CSVImportPayload):
    import csv
    csv_dir = os.path.join(os.path.dirname(settings.AUDIO_DIR), "csv")
    if not os.path.isdir(csv_dir):
        csv_dir = "/home/leandrodisconzi/transcription/data/csv"
    csv_path = os.path.join(csv_dir, payload.filename)
    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail=f"CSV file not found: {payload.filename}")

    stem, _ = os.path.splitext(payload.filename)
    transcript_id = _sanitize_filename_stem(payload.filename) or stem

    segments = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                idx = int(row.get("index", len(segments) + 1))
            except (ValueError, TypeError):
                idx = len(segments) + 1
            speaker_label = row.get("speaker", f"SPEAKER_{idx:02d}").strip()
            try:
                start = float(row.get("start", 0.0))
            except (ValueError, TypeError):
                start = 0.0
            try:
                end = float(row.get("end", start))
            except (ValueError, TypeError):
                end = start
            text = row.get("text", "").strip()
            segments.append(
                Segment(
                    index=idx,
                    speaker=Speaker(label=speaker_label),
                    start=start,
                    end=end,
                    text=text,
                    reviewed=False
                )
            )

    if not segments:
        raise HTTPException(status_code=400, detail="CSV file contains no valid segments.")

    audio_file = ""
    for ext in [".m4a", ".mp3", ".wav"]:
        audio_names = [
            stem.replace("segments_", "audio_") + ext,
            stem + ext,
            payload.filename.replace(".csv", ext)
        ]
        for audio_name in audio_names:
            possible_path = os.path.join(settings.AUDIO_DIR, audio_name)
            if os.path.exists(possible_path):
                audio_file = audio_name
                break
            possible_path = os.path.join(settings.ORIGINALS_DIR, audio_name)
            if os.path.exists(possible_path):
                audio_file = audio_name
                break
        if audio_file:
            break

    transcript = Transcript(
        transcript_id=transcript_id,
        segments=segments,
        source_file=audio_file or (stem.replace("segments_", "audio_") + ".m4a"),
        language="es",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(csv_path))),
        provider="csv_import",
    )
    _store.save(transcript)
    return {"status": "imported", "transcript_id": transcript_id, "segments": len(segments), "source_file": transcript.source_file}


# ------------------------------------------------------------------
# Review & curation endpoints (enhanced)
# ------------------------------------------------------------------
@router.get("/review/list")
async def list_transcripts_review(collection: str = Query("reviewed_transcripts")):
    """List transcripts with review progress.

    Vector-store counts come from a single non-blocking scan
    (:meth:`counts_by_transcript`) instead of one synchronous ``count()`` per
    transcript on the event loop, and transcript files are read off-loop too.
    """
    ids = await asyncio.to_thread(_store.list_ids)

    qdrant_counts: dict[str, int] = {}
    if _index is not None:
        counter = getattr(_index, "counts_by_transcript", None)
        try:
            if counter is not None:
                qdrant_counts = await counter(collection_name=collection)
            else:  # defensive fallback for custom index adapters
                qdrant_counts = await asyncio.to_thread(_legacy_counts, ids, collection)
        except Exception as e:
            logger.warning("[qdrant] failed to query reviewed counts: %s", e)

    def _build() -> list[dict]:
        out = []
        for tid in ids:
            t = _store.load(tid)
            if not t:
                continue
            total_segs = len(t.segments)
            reviewed_segs = sum(1 for s in t.segments if getattr(s, "reviewed", False))
            completeness = round(reviewed_segs / total_segs, 4) if total_segs > 0 else 0.0
            out.append({
                "transcript_id": tid,
                "source_file": t.source_file,
                "total_segments": total_segs,
                "reviewed_segments": reviewed_segs,
                "completeness": completeness,
                "qdrant_indexed_segments": qdrant_counts.get(tid, 0),
                "timestamp": t.timestamp,
            })
        out.sort(key=lambda x: (x["completeness"], x["transcript_id"]), reverse=True)
        return out

    return {"transcripts": await asyncio.to_thread(_build)}


def _legacy_counts(ids: list[str], collection: str) -> dict[str, int]:
    """Fallback per-transcript count for index adapters lacking the batch call."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = _index._client
    collections = [c.name for c in client.get_collections().collections]
    if collection not in collections:
        return {}
    counts: dict[str, int] = {}
    for tid in ids:
        res = client.count(
            collection_name=collection,
            count_filter=Filter(must=[FieldCondition(key="transcript_id", match=MatchValue(value=tid))]),
        )
        counts[tid] = res.count
    return counts


@router.put("/{transcript_id}")
async def update_transcript_metadata(transcript_id: str, update: MetadataUpdate):
    """Update metadata fields of a transcript. Preserves segments unless `segments` is provided."""
    transcript = await asyncio.to_thread(_store.load, transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    update_dict = update.model_dump(exclude_unset=True)
    # Update simple fields (top-level)
    for key, value in update_dict.items():
        if key == "segments":
            continue
        if value is not None:
            setattr(transcript, key, value)

    # If full segment list is provided, replace it
    if update.segments is not None:
        new_segments = []
        for seg_dict in update.segments:
            new_segments.append(
                Segment(
                    index=seg_dict.get("index", len(new_segments)),
                    speaker=Speaker(label=seg_dict.get("speaker", "UNKNOWN")),
                    start=float(seg_dict.get("start", 0.0)),
                    end=float(seg_dict.get("end", 0.0)),
                    text=seg_dict.get("text", ""),
                    reviewed=seg_dict.get("reviewed", False),
                )
            )
        transcript.segments = new_segments

    await asyncio.to_thread(_store.save, transcript)
    return {"status": "ok", "transcript_id": transcript_id, "updated_fields": list(update_dict.keys())}


@router.post("/{transcript_id}/review/save")
async def save_review(transcript_id: str, payload: SegmentUpdate):
    base = await asyncio.to_thread(_store.load, transcript_id)
    if not base:
        raise HTTPException(status_code=404, detail="Transcript not found")

    now = time.time()

    def emit(seg_idx: int, event_type: str, event_payload: dict):
        _event_store.append({
            "transcript_id": transcript_id,
            "segment_index": seg_idx,
            "type": event_type,
            "payload": event_payload,
            "timestamp": now,
        })

    # Sync reviewed state and curation columns FIRST, in the original index space
    # (the same space the patches reference). Applying them after patching would
    # map the indices onto post-insert/post-delete positions and flag the wrong
    # segments. Missing keys keep their stored value; an explicit "" clears it.
    reviewed_set = {int(i) for i in payload.reviewed_indices}
    base = _replace(
        base,
        segments=[
            _replace(
                seg,
                reviewed=(seg.index in reviewed_set),
                correction_note=payload.edited_correction_notes.get(
                    seg.index, getattr(seg, "correction_note", "")
                ),
                backchannel_events=payload.edited_backchannel_events.get(
                    seg.index, getattr(seg, "backchannel_events", "")
                ),
            )
            for seg in base.segments
        ],
    )

    applied: list[Patch] = []
    skipped: list[dict] = []
    patched = base

    # Apply structural/text patches if patcher is available
    if payload.patches and _patcher is not None:
        parsed = []
        for raw in payload.patches:
            try:
                op = PatchOp(raw.op)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"unknown patch op: {raw.op}") from exc
            parsed.append(
                Patch(
                    op=op,
                    segment_indices=tuple(int(i) for i in raw.segment_indices),
                    new_text=raw.new_text,
                    new_speaker=raw.new_speaker,
                    new_start=raw.new_start,
                    new_end=raw.new_end,
                    insert_after_index=raw.insert_after_index,
                    note=raw.note or "",
                )
            )
        patched, applied, skipped_pairs = _patcher.apply_with_report(base, parsed)
        skipped = [
            {
                "op": p.op.value,
                "segment_indices": list(p.segment_indices),
                "reason": reason,
            }
            for p, reason in skipped_pairs
        ]
    elif payload.patches:
        # Patches requested but no patch engine wired up: report them rather than
        # silently dropping the user's structural edits.
        skipped = [
            {
                "op": raw.op,
                "segment_indices": list(raw.segment_indices),
                "reason": "patch engine not configured",
            }
            for raw in payload.patches
        ]

    for idx in payload.reviewed_indices:
        if 0 <= idx < len(patched.segments):
            emit(idx, "segment_reviewed", {})

    for idx, text in payload.edited_texts.items():
        emit(idx, "segment_text_edited", {"text": text})
    for idx, spk in payload.edited_speakers.items():
        emit(idx, "segment_speaker_edited", {"speaker": spk})
    for idx, start in payload.edited_starts.items():
        emit(idx, "segment_time_edited", {"start": start})
    for idx, end in payload.edited_ends.items():
        emit(idx, "segment_time_edited", {"end": end})

    # Curation columns were already applied to the base above; record the events.
    for idx, note in payload.edited_correction_notes.items():
        emit(idx, "segment_correction_note_edited", {"correction_note": note})
    for idx, events in payload.edited_backchannel_events.items():
        emit(idx, "segment_backchannel_events_edited", {"backchannel_events": events})

    # Off-load the synchronous, atomic disk write so it never blocks the loop.
    await asyncio.to_thread(_store.save, patched)

    return {
        "status": "ok",
        "partial": bool(skipped),
        "applied_count": len(applied),
        "skipped": skipped,
        # Canonical post-save state so the client updates in place instead of
        # re-fetching the transcript and re-listing afterwards.
        "transcript": _transcript_to_dict(patched),
        "events_written": len(payload.reviewed_indices)
        + len(payload.edited_texts)
        + len(payload.edited_speakers)
        + len(payload.edited_starts)
        + len(payload.edited_ends)
        + len(payload.edited_correction_notes)
        + len(payload.edited_backchannel_events),
    }
            
@router.post("/{transcript_id}/review/index")
async def index_reviewed_segments(transcript_id: str, payload: ReviewIndexPayload = ReviewIndexPayload()):
    if _index is None:
        raise HTTPException(status_code=503, detail="Vector indexing not configured")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    reviewed_segments = [s for s in transcript.segments if getattr(s, "reviewed", False)]
    collection_name = (payload.collection or "").strip() or "reviewed_transcripts"

    await _index.delete(transcript_id, collection_name=collection_name)

    if not reviewed_segments:
        return {"transcript_id": transcript_id, "segments_indexed": 0, "message": "No reviewed segments. Existing points cleared."}

    reviewed_transcript = _replace(transcript, segments=reviewed_segments)
    n = await _index.index(reviewed_transcript, collection_name=collection_name)
    return {"transcript_id": transcript_id, "segments_indexed": n, "collection": collection_name}


def _apply_gain_db(path: str, gain_db: float) -> None:
    """Apply volume gain (dB) to a WAV file in place, before ASR."""
    if not gain_db:
        return
    from pydub import AudioSegment
    seg = AudioSegment.from_wav(path)
    seg.apply_gain(float(gain_db)).export(path, format="wav")


def _vad_trim_segment(path: str, trigger_level: float = 7.0) -> None:
    """Trim leading/trailing silence from a WAV using torchaudio's VAD.

    Rewrites the file in place with the [first speech start, last speech end]
    region. Leaves the file untouched when no speech is detected, the file is
    too short, or the trim would leave less than 50 ms of audio.
    """
    import torchaudio
    waveform, sr = torchaudio.load(path)
    if waveform.shape[-1] <= sr:
        return  # too short to benefit
    try:
        regions = torchaudio.functional.vad(waveform, sr, trigger_level=float(trigger_level))
    except Exception:
        return
    if not regions:
        return
    start_frame = int(regions[0][0].item())
    end_frame = int(regions[-1][1].item())
    if end_frame <= start_frame:
        return
    trimmed = waveform[:, start_frame:end_frame]
    if trimmed.shape[-1] < sr * 0.05:
        return
    torchaudio.save(path, trimmed, sr, format="wav", channels_first=True)


@router.post("/{transcript_id}/retranscribe_segments")
async def retranscribe_segments(transcript_id: str, payload: RetranscribeSegmentsPayload):
    if _asr is None or _audio_files is None:
        raise HTTPException(status_code=503, detail="ASR or Audio processor not initialized")

    from pydub import AudioSegment
    from src.domain.chilean_spanish import post_process_chilean_spanish
    import tempfile, shutil

    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    audio_path = _locate_source_audio(transcript, transcript_id)
    if not audio_path:
        raise HTTPException(
            status_code=400,
            detail=f"Could not locate audio file for '{transcript.source_file or transcript_id}' or '{transcript_id}'",
        )

    # Prepare WAV source
    temp_wav_source = None
    source_path = audio_path
    if not audio_path.lower().endswith(".wav"):
        # Copy to temp, then convert
        _, ext = os.path.splitext(audio_path)
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
            shutil.copy(audio_path, tf.name)
            temp_copy = tf.name
        temp_wav_source = _audio_files.convert_to_wav(temp_copy)
        source_path = temp_wav_source

    indices_set = set(payload.segment_indices)
    updated_segments = []
    updated_texts: dict[int, str] = {}

    try:
        for s in transcript.segments:
            if s.index in indices_set and (payload.include_reviewed or not getattr(s, "reviewed", False)):
                start_ms = int(s.start * 1000)
                end_ms = int(s.end * 1000)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as turn_file:
                    turn_path = turn_file.name
                try:
                    uploaded_path = os.path.join(_segment_audio_dir(transcript_id), f"upload_{s.index}.wav")
                    if os.path.exists(uploaded_path):
                        shutil.copy(uploaded_path, turn_path)
                    else:
                        _audio_files.extract_segment(source_path, start_ms, end_ms, turn_path)
                    if payload.volume_gain_db:
                        _apply_gain_db(turn_path, payload.volume_gain_db)
                    if payload.vad_enabled:
                        _vad_trim_segment(turn_path, payload.vad_trigger_level)
                    asr_result = _asr.transcribe(
                        turn_path,
                        language=payload.language,
                        model_size=payload.whisper_model,
                        temperature=payload.whisper_temp,
                        beam_size=payload.beam_size,
                        best_of=payload.best_of,
                        condition_on_previous_text=payload.condition_on_previous_text,
                        no_speech_threshold=payload.no_speech_threshold,
                        initial_prompt=payload.initial_prompt,
                    )
                    raw_text = asr_result.get("text", "") if isinstance(asr_result, dict) else asr_result
                    resolved_lang = asr_result.get("language") if isinstance(asr_result, dict) else None
                    is_spanish = resolved_lang in ("es", "es-CL") or (payload.language or "").startswith("es")
                    text = post_process_chilean_spanish(raw_text) if is_spanish else raw_text
                    updated_texts[s.index] = text
                    updated_segments.append(
                        Segment(
                            index=s.index,
                            speaker=s.speaker,
                            start=s.start,
                            end=s.end,
                            text=text,
                            reviewed=False
                        )
                    )
                finally:
                    if os.path.exists(turn_path):
                        os.remove(turn_path)
            else:
                updated_segments.append(s)
    finally:
        if temp_wav_source and os.path.exists(temp_wav_source):
            os.remove(temp_wav_source)

    transcript.segments = updated_segments
    _store.save(transcript)
    return {
        "status": "updated",
        "transcript_id": transcript_id,
        "updated_indices": list(updated_texts.keys()),
        "updated_texts": updated_texts,
    }


# ------------------------------------------------------------------
# Per-segment audio: play / download / upload replacement / regenerate
# ------------------------------------------------------------------
@router.get("/{transcript_id}/segment_audio/{segment_index}")
async def get_segment_audio(
    transcript_id: str,
    segment_index: int,
    start: float | None = Query(default=None),
    end: float | None = Query(default=None),
):
    """Return a segment's audio. Serves an uploaded replacement when present,
    otherwise cuts [start, end) (or the stored segment times) from the source."""
    if _store is None or _audio_files is None:
        raise HTTPException(status_code=503, detail="Audio store not initialized")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    seg_dir = _segment_audio_dir(transcript_id)
    upload_path = os.path.join(seg_dir, f"upload_{segment_index}.wav")
    if os.path.exists(upload_path):
        return FileResponse(upload_path, media_type="audio/wav", filename=f"segment_{segment_index}.wav")

    seg = next((s for s in transcript.segments if s.index == segment_index), None)
    s_start = float(start) if start is not None else (seg.start if seg else 0.0)
    s_end = float(end) if end is not None else (seg.end if seg else s_start)
    if s_end < s_start:
        s_end = s_start

    audio_path = _locate_source_audio(transcript, transcript_id)
    if not audio_path:
        raise HTTPException(
            status_code=404,
            detail=f"Could not locate source audio for transcript '{transcript_id}'",
        )

    try:
        cache_path = _extract_segment_cached(
            audio_path, seg_dir, segment_index, int(s_start * 1000), int(s_end * 1000)
        )
    except Exception as e:
        logger.exception("[error] segment audio cut failed")
        raise HTTPException(status_code=500, detail=f"Failed to cut segment audio: {e}") from e
    return FileResponse(cache_path, media_type="audio/wav", filename=f"segment_{segment_index}.wav")


@router.post("/{transcript_id}/segment_audio/{segment_index}")
async def upload_segment_audio(
    transcript_id: str, segment_index: int, file: UploadFile = File(...)
):
    """Upload a replacement audio clip for one segment (converted to WAV)."""
    if _store is None or _audio_files is None:
        raise HTTPException(status_code=503, detail="Audio store not initialized")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    seg_dir = _segment_audio_dir(transcript_id)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".wav", ".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".aac", ".wma", ".webm"):
        ext = ".wav"
    tmp_path = os.path.join(seg_dir, f"upload_{segment_index}_incoming{ext}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        wav_path = _audio_files.convert_to_wav(tmp_path)  # converts + removes tmp_path
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        logger.exception("[error] segment audio upload conversion failed")
        raise HTTPException(status_code=500, detail=f"Failed to convert uploaded audio: {e}") from e

    final_path = os.path.join(seg_dir, f"upload_{segment_index}.wav")
    if wav_path != final_path:
        os.replace(wav_path, final_path)
    return {"status": "ok", "transcript_id": transcript_id, "segment_index": segment_index, "path": final_path}


@router.post("/{transcript_id}/segment_audio/{segment_index}/regenerate")
async def regenerate_segment_audio(transcript_id: str, segment_index: int):
    """Drop an uploaded replacement so the audio is re-cut from source on next fetch."""
    if _store is None:
        raise HTTPException(status_code=503, detail="Transcript store not initialized")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")
    seg_dir = _segment_audio_dir(transcript_id)
    upload_path = os.path.join(seg_dir, f"upload_{segment_index}.wav")
    if os.path.exists(upload_path):
        os.remove(upload_path)
    return {"status": "ok", "transcript_id": transcript_id, "segment_index": segment_index}


@router.get("/audio/list")
async def list_audio_files():
    try:
        files = sorted(os.listdir(settings.AUDIO_DIR))
        audio_files = [f for f in files if os.path.isfile(os.path.join(settings.AUDIO_DIR, f))]
        return {"audio_dir": settings.AUDIO_DIR, "files": audio_files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Backward compatibility: the old /pinocchio/review endpoint
# ------------------------------------------------------------------
@router.get("/pinocchio/review/{transcript_id}")
async def get_review_transcript(transcript_id: str):
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")
    return {
        "transcript_id": transcript.transcript_id,
        "segments": [
            {
                "index": s.index,
                "speaker": s.speaker.label,
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "reviewed": getattr(s, "reviewed", False),
                "correction_note": getattr(s, "correction_note", ""),
                "backchannel_events": getattr(s, "backchannel_events", ""),
            }
            for s in transcript.segments
        ],
    }


@router.post("/pinocchio/review/{transcript_id}")
async def save_review_legacy(transcript_id: str, payload: ReviewSavePayload):
    """Legacy endpoint – delegates to the new /review/save implementation."""
    segment_update = SegmentUpdate(
        reviewed_indices=payload.reviewed_indices,
        edited_texts={int(k): v for k, v in (payload.edited_texts or {}).items()},
        edited_speakers={int(k): v for k, v in (payload.edited_speakers or {}).items()},
        recording_datetime=payload.recording_datetime,
    )
    return await save_review(transcript_id, segment_update)