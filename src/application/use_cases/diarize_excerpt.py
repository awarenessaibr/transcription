"""Use case: Diarize an audio excerpt (no transcription)."""
from __future__ import annotations

import logging

from src.application.dto.schemas import ExcerptResult, SegmentResult
from src.domain.ports.interfaces import AudioFilePort, DiarizationPort

logger = logging.getLogger(__name__)


class DiarizeExcerptUseCase:
    """Crop audio range → diarize → return speaker turns."""

    def __init__(
        self,
        diarizer: DiarizationPort,
        audio_files: AudioFilePort,
    ):
        self._diarizer = diarizer
        self._audio_files = audio_files

    def execute(
        self,
        file_path: str,
        start: float,
        end: float,
        *,
        min_speakers: int = 1,
        max_speakers: int = 2,
        num_speakers: int | None = None,
    ) -> ExcerptResult:
        duration = self._audio_files.get_duration(file_path)
        if end > duration:
            raise ValueError(
                f"Requested chunk [{start:.3f}, {end:.3f}] lies outside "
                f"file bounds [0.0, {duration:.3f}]"
            )

        waveform, sample_rate = self._audio_files.crop_audio(file_path, start, end)

        turns = self._diarizer.diarize_waveform(
            waveform,
            sample_rate,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            num_speakers=num_speakers,
        )

        segments = [
            SegmentResult(
                index=idx,
                speaker=turn.speaker,
                start=turn.start,
                end=turn.end,
                duration=turn.duration,
            )
            for idx, turn in enumerate(turns, 1)
        ]

        return ExcerptResult(start=start, end=end, segments=segments)
