"""transcription MCP server: transcription and diarization tools.

Launch with:
    python -m src.mcp.servers.transcription_server
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.application.dto.helpers import build_transcribe_params as _build_transcribe_params
from src.composition import build_runtime
from src.config import settings
from src.presentation.middleware.path_validator import validate_file_path

logger = logging.getLogger(__name__)


def _decode_audio_input(
    *,
    file_path: str | None,
    audio_base64: str | None,
    filename: str | None,
) -> tuple[str, bytes]:
    """Normalize audio input to (filename, bytes)."""
    if bool(file_path) == bool(audio_base64):
        raise ValueError("Provide exactly one of 'file_path' or 'audio_base64'.")

    if file_path:
        resolved = validate_file_path(file_path)
        return resolved.name, resolved.read_bytes()

    assert audio_base64 is not None
    try:
        content = base64.b64decode(audio_base64, validate=True)
    except Exception as exc:
        raise ValueError("Invalid audio_base64 payload.") from exc

    effective_name = (filename or "audio_upload.wav").strip() or "audio_upload.wav"
    return effective_name, content


def _decode_audio_to_tempfile(
    *,
    file_path: str | None,
    audio_base64: str | None,
    filename: str | None,
) -> tuple[str, list[str]]:
    """Return a usable file path for excerpt diarization plus cleanup paths."""
    cleanup_paths: list[str] = []

    if bool(file_path) == bool(audio_base64):
        raise ValueError("Provide exactly one of 'file_path' or 'audio_base64'.")

    if file_path:
        resolved = validate_file_path(file_path)
        source_path = str(resolved)
    else:
        assert audio_base64 is not None
        try:
            content = base64.b64decode(audio_base64, validate=True)
        except Exception as exc:
            raise ValueError("Invalid audio_base64 payload.") from exc

        suffix = Path((filename or "audio_upload.wav")).suffix or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            source_path = tmp.name
            cleanup_paths.append(tmp.name)

    ext = Path(source_path).suffix.lower()
    if ext != ".wav":
        wav_path = _AUDIO_FILES.convert_to_wav(source_path)
        cleanup_paths.append(wav_path)
        source_path = wav_path

    return source_path, cleanup_paths


@dataclass
class JobState:
    job_id: str
    status: str = "queued"
    progress: int = 0
    message: str = "Queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: dict[str, Any] | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


def _job_public(job: JobState) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "result": job.result,
        "error": job.error,
        "events": job.events,
    }


_RUNTIME = build_runtime()
_TRANSCRIBE_USE_CASE = _RUNTIME.transcribe_use_case
_EXCERPT_USE_CASE = _RUNTIME.excerpt_use_case
_GUIDED_USE_CASE = _RUNTIME.guided_transcribe_use_case
_AUDIO_FILES = _RUNTIME.audio_file_adapter
_PROJECT_STORE = _RUNTIME.project_store_adapter
_JOBS: dict[str, JobState] = {}

mcp = FastMCP("transcription-transcription")


@mcp.tool()
async def transcription_transcribe_audio(
    file_path: str | None = None,
    audio_base64: str | None = None,
    filename: str | None = None,
    language: str = "es-CL",
    model_size: str = "large-v3",
    min_speakers: int = 1,
    max_speakers: int = 2,
    vad_threshold: float = 0.25,
    noise_reduce: bool = True,
    reduction_db: int = 25,
    voice_enhance: bool = True,
    apply_gain: bool = True,
    target_lufs: float = -16.0,
    remove_silence: bool = True,
    silence_thresh: int = -45,
    min_silence_len: int = 250,
    beam_size: int = 5,
    best_of: int = 5,
    whisper_temp: float = 0.0,
    temperature_increment_on_fallback: float = 0.2,
    compression_ratio_threshold: float = 2.4,
    logprob_threshold: float = -1.0,
    no_speech_threshold: float = 0.6,
    condition_on_previous_text: bool = False,
    initial_prompt: str | None = None,
    length_penalty: float = 1.0,
    patience: float | None = None,
    suppress_blank: bool = True,
    suppress_tokens: str = "-1",
    word_timestamps: bool = False,
    keep_cache: bool = True,
    include_progress_events: bool = False,
) -> dict[str, Any]:
    """Run full transcription (diarization + ASR) and return transcript result."""
    input_filename, content = _decode_audio_input(
        file_path=file_path,
        audio_base64=audio_base64,
        filename=filename,
    )
    events: list[dict[str, Any]] = []

    def progress_callback(stage: str, progress: int, message: str, extra: dict | None = None):
        if include_progress_events:
            events.append(
                {
                    "stage": stage,
                    "progress": progress,
                    "message": message,
                    "extra": extra or {},
                    "timestamp": time.time(),
                }
            )

    params = _build_transcribe_params(
        language=language,
        model_size=model_size,
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
        progress_callback=progress_callback,
    )

    result = await _TRANSCRIBE_USE_CASE.execute(
        filename=input_filename,
        content=content,
        dest_dir=settings.ORIGINALS_DIR,
        params=params,
    )

    payload = result.model_dump()
    if include_progress_events:
        payload["progress_events"] = events
    return payload


async def _run_transcription_job(job: JobState, kwargs: dict[str, Any]) -> None:
    def progress_callback(stage: str, progress: int, message: str, extra: dict | None = None):
        job.status = "running"
        job.progress = max(0, min(100, int(progress)))
        job.message = message
        job.updated_at = time.time()
        job.events.append(
            {
                "stage": stage,
                "progress": job.progress,
                "message": message,
                "extra": extra or {},
                "timestamp": job.updated_at,
            }
        )

    try:
        params = _build_transcribe_params(
            language=kwargs["language"],
            model_size=kwargs["model_size"],
            min_speakers=kwargs["min_speakers"],
            max_speakers=kwargs["max_speakers"],
            vad_threshold=kwargs["vad_threshold"],
            noise_reduce=kwargs["noise_reduce"],
            reduction_db=kwargs["reduction_db"],
            voice_enhance=kwargs["voice_enhance"],
            apply_gain=kwargs["apply_gain"],
            target_lufs=kwargs["target_lufs"],
            remove_silence=kwargs["remove_silence"],
            silence_thresh=kwargs["silence_thresh"],
            min_silence_len=kwargs["min_silence_len"],
            beam_size=kwargs["beam_size"],
            best_of=kwargs["best_of"],
            whisper_temp=kwargs["whisper_temp"],
            temperature_increment_on_fallback=kwargs["temperature_increment_on_fallback"],
            compression_ratio_threshold=kwargs["compression_ratio_threshold"],
            logprob_threshold=kwargs["logprob_threshold"],
            no_speech_threshold=kwargs["no_speech_threshold"],
            condition_on_previous_text=kwargs["condition_on_previous_text"],
            initial_prompt=kwargs["initial_prompt"],
            length_penalty=kwargs["length_penalty"],
            patience=kwargs["patience"],
            suppress_blank=kwargs["suppress_blank"],
            suppress_tokens=kwargs["suppress_tokens"],
            word_timestamps=kwargs["word_timestamps"],
            keep_cache=kwargs["keep_cache"],
            progress_callback=progress_callback,
        )

        result = await _TRANSCRIBE_USE_CASE.execute(
            filename=kwargs["input_filename"],
            content=kwargs["content"],
            dest_dir=settings.ORIGINALS_DIR,
            params=params,
        )
        job.status = "done"
        job.progress = 100
        job.message = "Completed"
        job.result = result.model_dump()
        job.updated_at = time.time()
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        job.message = f"Error: {exc}"
        job.updated_at = time.time()
        logger.exception("[mcp] async transcription job failed")


def _resolve_canonical_audio(
    canonical_name: str | None,
    project_id: str | None,
    upload_filename: str,
) -> str:
    if canonical_name:
        return canonical_name

    if project_id:
        project = _PROJECT_STORE.load(project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        stem = upload_filename.rsplit(".", 1)[0].lower()
        stem_compact = stem.replace("_", "")
        for audio in project.audios:
            if audio.audio_path and os.path.basename(audio.audio_path) == upload_filename:
                return audio.canonical_name
            if audio.canonical_name.lower().replace("_", "") == stem_compact:
                return audio.canonical_name

        if project.audios:
            return project.audios[0].canonical_name

    base = upload_filename.rsplit(".", 1)[0].lower()
    normalized = "".join(ch if ch.isalnum() else "_" for ch in base)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_") or "audio"


async def _run_guided_job(job: JobState, kwargs: dict[str, Any]) -> None:
    try:
        job.status = "running"
        job.progress = 15
        job.message = "Running guided transcription"
        job.updated_at = time.time()
        job.events.append(
            {
                "stage": "guided",
                "progress": job.progress,
                "message": job.message,
                "timestamp": job.updated_at,
            }
        )

        result = await _GUIDED_USE_CASE.execute(
            audio_path=kwargs["audio_path"],
            canonical_name=kwargs["canonical_name"],
            params=kwargs["params"],
        )
        job.status = "done"
        job.progress = 100
        job.message = "Completed"
        job.result = result
        job.updated_at = time.time()
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        job.message = f"Error: {exc}"
        job.updated_at = time.time()
        logger.exception("[mcp] async guided transcription job failed")


@mcp.tool()
async def transcription_transcribe_audio_async(
    file_path: str | None = None,
    audio_base64: str | None = None,
    filename: str | None = None,
    language: str = "es-CL",
    model_size: str = "large-v3",
    min_speakers: int = 1,
    max_speakers: int = 2,
    vad_threshold: float = 0.25,
    noise_reduce: bool = True,
    reduction_db: int = 25,
    voice_enhance: bool = True,
    apply_gain: bool = True,
    target_lufs: float = -16.0,
    remove_silence: bool = True,
    silence_thresh: int = -45,
    min_silence_len: int = 250,
    beam_size: int = 5,
    best_of: int = 5,
    whisper_temp: float = 0.0,
    temperature_increment_on_fallback: float = 0.2,
    compression_ratio_threshold: float = 2.4,
    logprob_threshold: float = -1.0,
    no_speech_threshold: float = 0.6,
    condition_on_previous_text: bool = False,
    initial_prompt: str | None = None,
    length_penalty: float = 1.0,
    patience: float | None = None,
    suppress_blank: bool = True,
    suppress_tokens: str = "-1",
    word_timestamps: bool = False,
    keep_cache: bool = True,
) -> dict[str, Any]:
    """Queue full transcription and return a job id for polling."""
    input_filename, content = _decode_audio_input(
        file_path=file_path,
        audio_base64=audio_base64,
        filename=filename,
    )

    job_id = str(uuid.uuid4())
    job = JobState(job_id=job_id)
    _JOBS[job_id] = job

    task_kwargs = {
        "input_filename": input_filename,
        "content": content,
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
        "temperature_increment_on_fallback": temperature_increment_on_fallback,
        "compression_ratio_threshold": compression_ratio_threshold,
        "logprob_threshold": logprob_threshold,
        "no_speech_threshold": no_speech_threshold,
        "condition_on_previous_text": condition_on_previous_text,
        "initial_prompt": initial_prompt,
        "length_penalty": length_penalty,
        "patience": patience,
        "suppress_blank": suppress_blank,
        "suppress_tokens": suppress_tokens,
        "word_timestamps": word_timestamps,
        "keep_cache": keep_cache,
    }
    asyncio.create_task(_run_transcription_job(job, task_kwargs))
    return _job_public(job)


@mcp.tool()
async def transcription_transcribe_audio_guided(
    file_path: str | None = None,
    audio_base64: str | None = None,
    filename: str | None = None,
    canonical_name: str | None = None,
    project_id: str | None = None,
    top_n_references: int = 3,
    language: str = "es",
    model_size: str = "large-v3",
    min_speakers: int = 1,
    max_speakers: int = 4,
    vad_threshold: float = 0.25,
    noise_reduce: bool = True,
    reduction_db: int = 25,
    voice_enhance: bool = True,
    apply_gain: bool = True,
    target_lufs: float = -16.0,
    remove_silence: bool = True,
    silence_thresh: int = -45,
    min_silence_len: int = 250,
    beam_size: int = 5,
    best_of: int = 5,
    whisper_temp: float = 0.0,
    condition_on_previous_text: bool = False,
    word_timestamps: bool = False,
) -> dict[str, Any]:
    """Run reference-guided transcription aligned with POST /api/diarization/transcribe/guided."""
    input_filename, content = _decode_audio_input(
        file_path=file_path,
        audio_base64=audio_base64,
        filename=filename,
    )
    saved_path = await _AUDIO_FILES.save_upload(input_filename, content, settings.ORIGINALS_DIR)
    resolved_canonical = _resolve_canonical_audio(canonical_name, project_id, input_filename)

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
    return await _GUIDED_USE_CASE.execute(
        audio_path=saved_path,
        canonical_name=resolved_canonical,
        params=params,
    )


@mcp.tool()
async def transcription_transcribe_audio_guided_async(
    file_path: str | None = None,
    audio_base64: str | None = None,
    filename: str | None = None,
    canonical_name: str | None = None,
    project_id: str | None = None,
    top_n_references: int = 3,
    language: str = "es",
    model_size: str = "large-v3",
    min_speakers: int = 1,
    max_speakers: int = 4,
    vad_threshold: float = 0.25,
) -> dict[str, Any]:
    """Queue guided transcription aligned with POST /api/diarization/transcribe/guided/async."""
    input_filename, content = _decode_audio_input(
        file_path=file_path,
        audio_base64=audio_base64,
        filename=filename,
    )
    saved_path = await _AUDIO_FILES.save_upload(input_filename, content, settings.ORIGINALS_DIR)
    resolved_canonical = _resolve_canonical_audio(canonical_name, project_id, input_filename)

    job_id = str(uuid.uuid4())
    job = JobState(job_id=job_id)
    _JOBS[job_id] = job

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
    asyncio.create_task(
        _run_guided_job(
            job,
            {
                "audio_path": saved_path,
                "canonical_name": resolved_canonical,
                "params": params,
            },
        )
    )
    payload = _job_public(job)
    payload["canonical_name"] = resolved_canonical
    return payload


@mcp.tool()
def transcription_get_transcription_job(job_id: str) -> dict[str, Any]:
    """Fetch current status/result for an async transcription job."""
    job = _JOBS.get(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    return _job_public(job)


@mcp.tool()
def transcription_diarize_excerpt(
    start: float,
    end: float,
    file_path: str | None = None,
    audio_base64: str | None = None,
    filename: str | None = None,
    min_speakers: int = 1,
    max_speakers: int = 2,
    num_speakers: int | None = None,
) -> dict[str, Any]:
    """Diarize a single excerpt by path or base64 audio payload."""
    if start < 0 or end <= start:
        raise ValueError("Invalid time range. Ensure start >= 0 and end > start.")

    source_path = ""
    cleanup_paths: list[str] = []
    try:
        source_path, cleanup_paths = _decode_audio_to_tempfile(
            file_path=file_path,
            audio_base64=audio_base64,
            filename=filename,
        )
        result = _EXCERPT_USE_CASE.execute(
            file_path=source_path,
            start=start,
            end=end,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            num_speakers=num_speakers,
        )
        return result.model_dump()
    finally:
        for path in cleanup_paths:
            if path and os.path.exists(path):
                with contextlib.suppress(Exception):
                    os.remove(path)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for remote connectivity tests."""
    return JSONResponse({"status": "ok", "service": "transcription-transcription"})


def main() -> None:
    """Entrypoint for MCP server with configurable transport."""
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8121"))

    if transport == "stdio":
        mcp.run()
        return

    if transport not in {"sse", "streamable-http"}:
        raise ValueError(f"Unsupported MCP_TRANSPORT '{transport}'. Use: stdio, sse, streamable-http")

    if hasattr(mcp, "settings"):
        if hasattr(mcp.settings, "host"):
            mcp.settings.host = host
        if hasattr(mcp.settings, "port"):
            mcp.settings.port = port

    try:
        mcp.run(transport=transport, host=host, port=port)
    except TypeError:
        mcp.run(transport=transport)


if __name__ == "__main__":
    main()
