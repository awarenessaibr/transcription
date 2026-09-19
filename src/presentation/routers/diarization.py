"""Diarization excerpt router — thin presentation layer."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.presentation.middleware.path_validator import validate_file_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diarization", tags=["diarization"])

# Will be injected by main.py composition root
_excerpt_use_case = None
_audio_files = None
_transcript_dir: str | None = None


def init_diarization_router(excerpt_use_case, audio_files, transcript_dir: str | None = None):
    global _excerpt_use_case, _audio_files, _transcript_dir
    _excerpt_use_case = excerpt_use_case
    _audio_files = audio_files
    _transcript_dir = transcript_dir


def _save_excerpt_result(result_data: dict) -> str:
    """Persist excerpt/diarization result to the transcripts directory."""
    if not _transcript_dir:
        return ""
    transcript_id = f"excerpt_{int(time.time())}"
    path = os.path.join(_transcript_dir, f"{transcript_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    logger.info("[store] saved excerpt result to %s", path)
    return transcript_id


@router.post("/excerpt")
async def diarization_excerpt(
    audio: UploadFile | None = File(None, description="Upload audio file (wav, mp3, m4a)"),
    file_path: str | None = Form(None, description="Existing backend file path"),
    start: float = Form(..., description="Start time in seconds"),
    end: float = Form(..., description="End time in seconds"),
    min_speakers: int = Form(1, description="Minimum expected speakers"),
    max_speakers: int = Form(2, description="Maximum expected speakers"),
    num_speakers: int | None = Form(None, description="Exact number of speakers"),
):
    """Return diarization for a specific audio excerpt."""
    if (audio is None and not file_path) or (audio is not None and file_path):
        raise HTTPException(status_code=400, detail="Provide either 'audio' upload or 'file_path', not both.")
    if start < 0 or end <= start:
        raise HTTPException(status_code=400, detail="Invalid start/end times.")

    temp_path = None
    try:
        if audio:
            original_filename = audio.filename or "audio_upload"
            _, ext = os.path.splitext(original_filename)
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext or ".wav") as f:
                content = await audio.read()
                f.write(content)
                temp_path = f.name
            temp_path = _audio_files.convert_to_wav(temp_path)
            source_path = temp_path
        else:
            try:
                validate_file_path(file_path)
            except (ValueError, FileNotFoundError) as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            source_path = file_path

        result = _excerpt_use_case.execute(
            file_path=source_path,
            start=start,
            end=end,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            num_speakers=num_speakers,
        )
        result_data = result.model_dump()
        transcript_id = _save_excerpt_result(result_data)
        if transcript_id:
            result_data["transcript_id"] = transcript_id
        return result_data

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("[error] excerpt diarization failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        if temp_path and os.path.exists(temp_path):
            import contextlib
            with contextlib.suppress(Exception):
                os.remove(temp_path)


class ExcerptByPathRequest(BaseModel):
    file_path: str = Field(..., description="Existing backend file path")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    min_speakers: int = Field(1, description="Minimum expected speakers")
    max_speakers: int = Field(2, description="Maximum expected speakers")
    num_speakers: int | None = Field(None, description="Exact number of speakers")


@router.post("/excerpt_by_path")
async def diarization_excerpt_by_path(payload: ExcerptByPathRequest):
    """Diarize an excerpt using a server-side file path (JSON body)."""
    try:
        validate_file_path(payload.file_path)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if payload.start < 0 or payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="Invalid start/end times.")

    temp_wav = None
    try:
        source_path = payload.file_path
        # Convert non-WAV formats (m4a, mp3, etc.) to WAV before diarization.
        _, ext = os.path.splitext(source_path)
        if ext.lower() not in (".wav",):
            temp_wav = _audio_files.convert_to_wav(source_path)
            source_path = temp_wav

        result = _excerpt_use_case.execute(
            file_path=source_path,
            start=payload.start,
            end=payload.end,
            min_speakers=payload.min_speakers,
            max_speakers=payload.max_speakers,
            num_speakers=payload.num_speakers,
        )
        result_data = result.model_dump()
        transcript_id = _save_excerpt_result(result_data)
        if transcript_id:
            result_data["transcript_id"] = transcript_id
        return result_data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("[error] excerpt_by_path failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        if temp_wav and os.path.exists(temp_wav):
            os.unlink(temp_wav)
