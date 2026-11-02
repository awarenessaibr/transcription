"""Narration alignment API — thin presentation layer."""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from src.application.use_cases.align_narration import AlignNarrationUseCase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alignment", tags=["alignment"])
_align_use_case: AlignNarrationUseCase | None = None


def init_alignment_router(align_use_case: AlignNarrationUseCase) -> None:
    global _align_use_case
    _align_use_case = align_use_case


@router.post("/narration")
async def align_narration(
    audio: UploadFile = File(..., description="Narration audio file."),
    text: UploadFile = File(..., description="Source text or CSV with a text column."),
    language: str = Form("auto", description="Whisper language or auto detection."),
    whisper_model: str = Form("large-v3", description="Whisper model name."),
):
    audio_content = await audio.read()
    source_content = await text.read()
    if not audio_content:
        raise HTTPException(status_code=400, detail="Empty audio upload.")
    if not source_content:
        raise HTTPException(status_code=400, detail="Empty text upload.")

    try:
        decoded_source = source_content.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded_source = source_content.decode("latin-1")

    try:
        if _align_use_case is None:
            raise HTTPException(status_code=503, detail="Narration alignment is unavailable.")
        return await _align_use_case.execute(
            audio_filename=audio.filename or "audio_upload",
            audio_content=audio_content,
            source_content=decoded_source,
            language=language,
            model_size=whisper_model,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[error] narration alignment failed")
        raise HTTPException(status_code=500, detail="Narration alignment failed.") from exc
