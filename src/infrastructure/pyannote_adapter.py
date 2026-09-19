"""Pyannote diarization adapter — implements DiarizationPort."""
from __future__ import annotations

import logging

from src.domain.entities.transcript import DiarizationTurn
from src.infrastructure.model_manager import ModelManager

logger = logging.getLogger(__name__)


class PyAnnoteDiarizerAdapter:
    """Speaker diarization using Pyannote. Implements DiarizationPort."""

    def __init__(self, model_manager: ModelManager, auth_token: str | None = None):
        self._mm = model_manager
        self._auth_token = auth_token

    def diarize(
        self,
        audio_path: str,
        *,
        min_speakers: int = 1,
        max_speakers: int = 2,
        num_speakers: int | None = None,
        vad_threshold: float = 0.25,
    ) -> list[DiarizationTurn]:
        pipeline = self._mm.get_diarization_pipeline(self._auth_token)
        if pipeline is None:
            raise RuntimeError(
                "Diarization pipeline is not available — "
                "ensure HF_TOKEN / PYANNOTE_AUTH_TOKEN is set and has access to pyannote/speaker-diarization-3.1"
            )
        pipeline.segmentation.threshold = vad_threshold
        pipeline.min_speakers = min_speakers
        pipeline.max_speakers = max_speakers

        diarization = pipeline(audio_path)
        # pyannote >= 4 returns a DiarizeOutput wrapper; 3.x returns the Annotation directly.
        if hasattr(diarization, "exclusive_speaker_diarization"):
            diarization = diarization.exclusive_speaker_diarization
        return [
            DiarizationTurn(speaker=speaker, start=float(turn.start), end=float(turn.end))
            for turn, _, speaker in diarization.itertracks(yield_label=True)
        ]

    def diarize_waveform(
        self,
        waveform,
        sample_rate: int,
        *,
        min_speakers: int = 1,
        max_speakers: int = 2,
        num_speakers: int | None = None,
    ) -> list[DiarizationTurn]:
        pipeline = self._mm.get_diarization_pipeline(self._auth_token)
        if pipeline is None:
            raise RuntimeError(
                "Diarization pipeline is not available — "
                "ensure HF_TOKEN / PYANNOTE_AUTH_TOKEN is set and has access to pyannote/speaker-diarization-3.1"
            )

        kwargs = {}
        if num_speakers is not None:
            kwargs["num_speakers"] = num_speakers
        else:
            kwargs["min_speakers"] = min_speakers
            kwargs["max_speakers"] = max_speakers

        diarization = pipeline({"waveform": waveform, "sample_rate": sample_rate}, **kwargs)
        # pyannote >= 4 returns a DiarizeOutput wrapper; 3.x returns the Annotation directly.
        if hasattr(diarization, "exclusive_speaker_diarization"):
            diarization = diarization.exclusive_speaker_diarization
        return [
            DiarizationTurn(speaker=speaker, start=float(turn.start), end=float(turn.end))
            for turn, _, speaker in diarization.itertracks(yield_label=True)
        ]
