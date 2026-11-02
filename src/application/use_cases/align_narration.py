"""Use case: align source narration lines to timestamps from Whisper."""
from __future__ import annotations

import asyncio
import logging
import tempfile

from src.application.services.narration_aligner import (
    align_lines_to_segments,
    build_aligned_rows,
    parse_source_text,
    rows_to_csv,
)
from src.domain.ports.interfaces import ASRPort, AudioFilePort

logger = logging.getLogger(__name__)


class AlignNarrationUseCase:
    """Transcribe uploaded audio for timing only, without saving a transcript."""

    def __init__(self, asr: ASRPort, audio_files: AudioFilePort):
        self._asr = asr
        self._audio_files = audio_files

    async def execute(
        self,
        *,
        audio_filename: str,
        audio_content: bytes,
        source_content: str,
        language: str = "auto",
        model_size: str = "large-v3",
    ) -> dict:
        targets = parse_source_text(source_content)
        if not targets:
            raise ValueError("No source text lines found.")

        whisper_language = None if language.casefold() == "auto" else language.split("-", 1)[0]
        with tempfile.TemporaryDirectory(prefix="narration-align-") as temp_dir:
            audio_path = await self._audio_files.save_upload(
                audio_filename or "audio_upload", audio_content, temp_dir
            )
            wav_path = self._audio_files.convert_to_wav(audio_path)
            transcription = await asyncio.to_thread(
                self._asr.transcribe,
                wav_path,
                language=whisper_language,
                model_size=model_size,
                word_timestamps=False,
            )

        segments = transcription.get("segments") if isinstance(transcription, dict) else None
        if not isinstance(segments, list) or not segments:
            raise ValueError("Whisper returned no timed segments for this audio.")

        valid_segments = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            try:
                start = float(segment["start"])
                end = float(segment["end"])
                text = str(segment.get("text") or "").strip()
            except (KeyError, TypeError, ValueError):
                logger.warning("[aligner] ignoring malformed Whisper segment: %r", segment)
                continue
            if start < 0 or end < start or not text:
                logger.warning("[aligner] ignoring invalid Whisper segment: %r", segment)
                continue
            valid_segments.append({"start": start, "end": end, "text": text})
        if not valid_segments:
            raise ValueError("Whisper returned no valid timed segments for this audio.")

        assignments = align_lines_to_segments(targets, valid_segments)
        rows = build_aligned_rows(targets, valid_segments, assignments)
        return {
            "csv": rows_to_csv(rows),
            "rows": rows,
            "targets_count": len(targets),
            "segments_count": len(valid_segments),
        }
