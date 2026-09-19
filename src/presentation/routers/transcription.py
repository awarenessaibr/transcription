"""Transcription router — thin presentation layer."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from src.application.dto.helpers import build_transcribe_params as _build_transcribe_params

from .transcripts import (
    complete_progress_job,
    fail_progress_job,
    start_progress_job,
    update_progress_job,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diarization", tags=["transcription"])

# Will be injected by main.py composition root
_transcribe_use_case = None
_originals_dir = None
_guided_use_case = None
_audio_file_adapter = None
_project_store = None


def init_transcription_router(
    transcribe_use_case,
    originals_dir: str,
    guided_use_case=None,
    audio_file_adapter=None,
    project_store=None,
):
    global _transcribe_use_case, _originals_dir, _guided_use_case
    global _audio_file_adapter, _project_store
    _transcribe_use_case = transcribe_use_case
    _originals_dir = originals_dir
    _guided_use_case = guided_use_case
    _audio_file_adapter = audio_file_adapter
    _project_store = project_store


@router.post("/transcribe")
async def diarization_transcribe(
    file: UploadFile = File(..., description="Audio file (wav, mp3, m4a, etc.)"),
    # General
    language: str = Form("auto", description="Locale code. Use 'auto' for automatic language detection."),
    whisper_model: str = Form("large-v3", alias="model_size", description="Whisper model name."),
    min_speakers: int = Form(1, description="Minimum expected speakers."),
    max_speakers: int = Form(2, description="Maximum expected speakers."),
    vad_threshold: float = Form(0.25, description="Voice activity threshold."),
    # Preprocessing
    noise_reduce: bool = Form(True, description="Enable noise reduction."),
    reduction_db: int = Form(25, description="Noise reduction strength."),
    voice_enhance: bool = Form(True, description="Band-pass + compression."),
    apply_gain: bool = Form(True, description="Loudness normalization."),
    target_lufs: float = Form(-16.0, description="Target LUFS loudness."),
    remove_silence: bool = Form(True, description="Trim silence before diarization."),
    silence_thresh: int = Form(-45, description="Silence threshold dBFS."),
    min_silence_len: int = Form(250, description="Minimum silence length (ms)."),
    # Whisper decoding
    beam_size: int = Form(5, description="Beam search width."),
    best_of: int = Form(5, description="Number of candidates when sampling."),
    whisper_temp: float = Form(0.0, description="Sampling temperature."),
    temperature_increment_on_fallback: float = Form(0.2, description="Increment if retry."),
    compression_ratio_threshold: float = Form(2.4, description="Retry if too compressible."),
    logprob_threshold: float = Form(-1.0, description="Retry if avg logprob below."),
    no_speech_threshold: float = Form(0.6, description="Silence probability threshold."),
    condition_on_previous_text: bool = Form(False, description="Use prev text as context."),
    initial_prompt: str | None = Form(None, description="Optional priming text."),
    length_penalty: float = Form(1.0, description=">1 longer; <1 shorter."),
    patience: float | None = Form(None, description="Beam search patience."),
    suppress_blank: bool = Form(True, description="Suppress blank tokens."),
    suppress_tokens: str = Form("-1", description="Token IDs to suppress."),
    word_timestamps: bool = Form(False, description="Per-word timestamps."),
    # Control
    keep_cache: bool = Form(True, description="Keep loaded models cached."),
    skip_diarization: bool = Form(False, description="Skip speaker diarization and return a single segment."),
):
    try:
        content = await file.read()
        filename = file.filename or "audio_upload"

        params = _build_transcribe_params(
            language=language,
            model_size=whisper_model,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            vad_threshold=vad_threshold,
            noise_reduce=noise_reduce,
            reduction_db=reduction_db,
            voice_enhance=voice_enhance,
            apply_gain=apply_gain,
            target_lufs=target_lufs,
            remove_silence=remove_silence,
            silence_thresh=silence_thresh,
            min_silence_len=min_silence_len,
            beam_size=beam_size,
            best_of=best_of,
            whisper_temp=whisper_temp,
            temperature_increment_on_fallback=temperature_increment_on_fallback,
            compression_ratio_threshold=compression_ratio_threshold,
            logprob_threshold=logprob_threshold,
            no_speech_threshold=no_speech_threshold,
            condition_on_previous_text=condition_on_previous_text,
            initial_prompt=initial_prompt,
            length_penalty=length_penalty,
            patience=patience,
            suppress_blank=suppress_blank,
            suppress_tokens=suppress_tokens,
            word_timestamps=word_timestamps,
            keep_cache=keep_cache,
            skip_diarization=skip_diarization,
        )

        result = await _transcribe_use_case.execute(
            filename=filename,
            content=content,
            dest_dir=_originals_dir,
            params=params,
        )
        return result.model_dump()

    except Exception as e:
        logger.exception("[error] transcription failure")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/transcribe/async")
async def diarization_transcribe_async(
    file: UploadFile = File(..., description="Audio file (wav, mp3, m4a, etc.)"),
    # General
    language: str = Form("auto", description="Locale code. Use 'auto' for automatic language detection."),
    whisper_model: str = Form("large-v3", alias="model_size", description="Whisper model name."),
    min_speakers: int = Form(1, description="Minimum expected speakers."),
    max_speakers: int = Form(2, description="Maximum expected speakers."),
    vad_threshold: float = Form(0.25, description="Voice activity threshold."),
    # Preprocessing
    noise_reduce: bool = Form(True, description="Enable noise reduction."),
    reduction_db: int = Form(25, description="Noise reduction strength."),
    voice_enhance: bool = Form(True, description="Band-pass + compression."),
    apply_gain: bool = Form(True, description="Loudness normalization."),
    target_lufs: float = Form(-16.0, description="Target LUFS loudness."),
    remove_silence: bool = Form(True, description="Trim silence before diarization."),
    silence_thresh: int = Form(-45, description="Silence threshold dBFS."),
    min_silence_len: int = Form(250, description="Minimum silence length (ms)."),
    # Whisper decoding
    beam_size: int = Form(5, description="Beam search width."),
    best_of: int = Form(5, description="Number of candidates when sampling."),
    whisper_temp: float = Form(0.0, description="Sampling temperature."),
    temperature_increment_on_fallback: float = Form(0.2, description="Increment if retry."),
    compression_ratio_threshold: float = Form(2.4, description="Retry if too compressible."),
    logprob_threshold: float = Form(-1.0, description="Retry if avg logprob below."),
    no_speech_threshold: float = Form(0.6, description="Silence probability threshold."),
    condition_on_previous_text: bool = Form(False, description="Use prev text as context."),
    initial_prompt: str | None = Form(None, description="Optional priming text."),
    length_penalty: float = Form(1.0, description=">1 longer; <1 shorter."),
    patience: float | None = Form(None, description="Beam search patience."),
    suppress_blank: bool = Form(True, description="Suppress blank tokens."),
    suppress_tokens: str = Form("-1", description="Token IDs to suppress."),
    word_timestamps: bool = Form(False, description="Per-word timestamps."),
    # Control
    keep_cache: bool = Form(True, description="Keep loaded models cached."),
    skip_diarization: bool = Form(False, description="Skip speaker diarization and return a single segment."),
):
    """Create async transcription job and return job_id for status/SSE tracking."""
    content = await file.read()
    filename = file.filename or "audio_upload"
    job_id = str(uuid.uuid4())

    start_progress_job(job_id, filename)

    params = _build_transcribe_params(
        language=language,
        model_size=whisper_model,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        vad_threshold=vad_threshold,
        noise_reduce=noise_reduce,
        reduction_db=reduction_db,
        voice_enhance=voice_enhance,
        apply_gain=apply_gain,
        target_lufs=target_lufs,
        remove_silence=remove_silence,
        silence_thresh=silence_thresh,
        min_silence_len=min_silence_len,
        beam_size=beam_size,
        best_of=best_of,
        whisper_temp=whisper_temp,
        temperature_increment_on_fallback=temperature_increment_on_fallback,
        compression_ratio_threshold=compression_ratio_threshold,
        logprob_threshold=logprob_threshold,
        no_speech_threshold=no_speech_threshold,
        condition_on_previous_text=condition_on_previous_text,
        initial_prompt=initial_prompt,
        length_penalty=length_penalty,
        patience=patience,
        suppress_blank=suppress_blank,
        suppress_tokens=suppress_tokens,
        word_timestamps=word_timestamps,
        keep_cache=keep_cache,
        skip_diarization=skip_diarization,
    )

    def _progress_callback(stage: str, progress: int, message: str, extra: dict | None = None):
        update_progress_job(
            job_id,
            stage=stage,
            progress=progress,
            message=message,
            extra=extra,
        )

    params["job_id"] = job_id
    params["progress_callback"] = _progress_callback

    async def _run_transcription_job():
        try:
            update_progress_job(job_id, stage="upload", progress=3, message="Upload recebido")
            result = await asyncio.to_thread(
                lambda: asyncio.run(
                    _transcribe_use_case.execute(
                        filename=filename,
                        content=content,
                        dest_dir=_originals_dir,
                        params=params,
                    )
                )
            )
            complete_progress_job(job_id, result.model_dump())
        except Exception as e:
            logger.exception("[error] async transcription failure job_id=%s", job_id)
            fail_progress_job(job_id, str(e))

    asyncio.create_task(_run_transcription_job())

    return {
        "job_id": job_id,
        "status": "queued",
        "status_url": f"/api/transcripts/status/{job_id}",
        "stream_url": f"/api/transcripts/stream/{job_id}",
    }


# ─────────────────────────────────────────────────────────────────────────
# Reference-guided transcription
# ─────────────────────────────────────────────────────────────────────────


def _resolve_canonical_audio(
    canonical_name: str | None,
    project_id: str | None,
    upload_filename: str,
) -> str:
    """Resolve canonical_name from explicit value or project audio entry."""
    if canonical_name:
        return canonical_name
    if project_id and _project_store is not None:
        project = _project_store.load(project_id)
        if project is None:
            raise HTTPException(
                status_code=404, detail=f"project {project_id} not found"
            )
        # Match by filename
        stem = upload_filename.rsplit(".", 1)[0].lower()
        for audio in project.audios:
            if audio.audio_path and os.path.basename(audio.audio_path) == upload_filename:
                return audio.canonical_name
            if audio.canonical_name.lower().replace("_", "") == stem.replace("_", ""):
                return audio.canonical_name
        if project.audios:
            # Fall back to first audio entry
            return project.audios[0].canonical_name
    # Last resort: derive a canonical_name from the filename
    base = upload_filename.rsplit(".", 1)[0].lower()
    base = "".join(c if c.isalnum() else "_" for c in base)
    while "__" in base:
        base = base.replace("__", "_")
    return base.strip("_") or "audio"


@router.post("/transcribe/guided")
async def diarization_transcribe_guided(
    file: UploadFile = File(..., description="Audio file (wav, mp3, m4a, etc.)"),
    canonical_name: str | None = Form(
        None, description="Reference store key. If omitted and project_id is given, resolved from project."
    ),
    project_id: str | None = Form(None, description="Optional project to attach this run to."),
    top_n_references: int = Form(3, description="Top-N priors to send to the reconciler."),
    language: str = Form("auto", description="Whisper language code. Use 'auto' for automatic language detection."),
    model_size: str = Form("large-v3", description="Whisper model name."),
    min_speakers: int = Form(1),
    max_speakers: int = Form(4),
    vad_threshold: float = Form(0.25),
    noise_reduce: bool = Form(True),
    reduction_db: int = Form(25),
    voice_enhance: bool = Form(True),
    apply_gain: bool = Form(True),
    target_lufs: float = Form(-16.0),
    remove_silence: bool = Form(True),
    silence_thresh: int = Form(-45),
    min_silence_len: int = Form(250),
    beam_size: int = Form(5),
    best_of: int = Form(5),
    whisper_temp: float = Form(0.0),
    condition_on_previous_text: bool = Form(False),
    word_timestamps: bool = Form(False),
):
    """Run reference-guided transcription using prior corrected transcripts.

    Pipeline: load top-N references + narrative → Whisper (initial_prompt from
    best ref) → diarization → LLM reconciliation → save + index.
    """
    if _guided_use_case is None or _audio_file_adapter is None:
        raise HTTPException(
            status_code=503,
            detail="Guided pipeline unavailable (configure ANTHROPIC_API_KEY or DEEPSEEK_API_KEY).",
        )

    filename = file.filename or "audio_upload"
    content = await file.read()
    audio_path = await _audio_file_adapter.save_upload(filename, content, _originals_dir)
    cn = _resolve_canonical_audio(canonical_name, project_id, filename)

    params = {
        "language": language,
        "model_size": model_size,
        "min_speakers": min_speakers,
        "max_speakers": max_speakers,
        "vad_threshold": vad_threshold,
        "noise_reduce": noise_reduce,
        "reduction_db": reduction_db,
        "voice_enhance": voice_enhance,
        "apply_gain": apply_gain,
        "target_lufs": target_lufs,
        "remove_silence": remove_silence,
        "silence_thresh": silence_thresh,
        "min_silence_len": min_silence_len,
        "beam_size": beam_size,
        "best_of": best_of,
        "whisper_temp": whisper_temp,
        "condition_on_previous_text": condition_on_previous_text,
        "word_timestamps": word_timestamps,
        "top_n_references": top_n_references,
        "project_id": project_id or "",
    }
    try:
        return await _guided_use_case.execute(
            audio_path=audio_path, canonical_name=cn, params=params
        )
    except Exception as exc:
        logger.exception("[error] guided transcription failed for %s", cn)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/transcribe/guided/async")
async def diarization_transcribe_guided_async(
    file: UploadFile = File(..., description="Audio file (wav, mp3, m4a, etc.)"),
    canonical_name: str | None = Form(None),
    project_id: str | None = Form(None),
    top_n_references: int = Form(3),
    language: str = Form("auto", description="Whisper language code. Use 'auto' for automatic language detection."),
    model_size: str = Form("large-v3"),
    min_speakers: int = Form(1),
    max_speakers: int = Form(4),
    vad_threshold: float = Form(0.25),
):
    """Async variant: returns a job_id for SSE/status tracking."""
    if _guided_use_case is None or _audio_file_adapter is None:
        raise HTTPException(status_code=503, detail="Guided pipeline unavailable")

    filename = file.filename or "audio_upload"
    content = await file.read()
    audio_path = await _audio_file_adapter.save_upload(filename, content, _originals_dir)
    cn = _resolve_canonical_audio(canonical_name, project_id, filename)
    job_id = str(uuid.uuid4())
    start_progress_job(job_id, filename)

    params = {
        "language": language,
        "model_size": model_size,
        "min_speakers": min_speakers,
        "max_speakers": max_speakers,
        "vad_threshold": vad_threshold,
        "top_n_references": top_n_references,
        "project_id": project_id or "",
        "job_id": job_id,
    }

    async def _run():
        try:
            update_progress_job(job_id, stage="upload", progress=3, message="Upload recebido")
            result = await _guided_use_case.execute(
                audio_path=audio_path, canonical_name=cn, params=params
            )
            complete_progress_job(job_id, result)
        except Exception as exc:
            logger.exception("[error] async guided job_id=%s", job_id)
            fail_progress_job(job_id, str(exc))

    asyncio.create_task(_run())
    return {
        "job_id": job_id,
        "canonical_name": cn,
        "status": "queued",
        "status_url": f"/api/transcripts/status/{job_id}",
        "stream_url": f"/api/transcripts/stream/{job_id}",
    }
