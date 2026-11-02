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

        # Speaker constraints must be passed as *call* kwargs.  pyannote's
        # ``SpeakerDiarization.apply()`` reads only its own keyword arguments; assigning
        # ``pipeline.min_speakers`` merely parks an unused attribute on the instance
        # (``Pipeline.__setattr__`` does not forward it), so the bound was previously ignored
        # and diarization always ran with min=1, max=inf.
        kwargs = self._speaker_kwargs(min_speakers, max_speakers, num_speakers)

        # ``vad_threshold`` used to be written to ``pipeline.segmentation.threshold``.  With the
        # powerset segmentation model shipped in speaker-diarization-3.1 that value is never
        # consulted (``apply()`` skips the ``binarize(onset=...)`` branch), so it is reported
        # rather than silently pretended.
        if vad_threshold is not None:
            logger.debug(
                "[diarize] vad_threshold=%.3f is not honoured by the powerset segmentation "
                "model in pyannote >= 4; it is ignored",
                float(vad_threshold),
            )

        diarization = pipeline(audio_path, **kwargs)
        # pyannote >= 4 returns a DiarizeOutput wrapper; 3.x returns the Annotation directly.
        if hasattr(diarization, "exclusive_speaker_diarization"):
            diarization = diarization.exclusive_speaker_diarization
        return [
            DiarizationTurn(speaker=speaker, start=float(turn.start), end=float(turn.end))
            for turn, _, speaker in diarization.itertracks(yield_label=True)
        ]

    @staticmethod
    def _speaker_kwargs(
        min_speakers: int = 1,
        max_speakers: int = 2,
        num_speakers: int | None = None,
    ) -> dict[str, int]:
        """Build the speaker-count kwargs for ``SpeakerDiarization.apply()``.

        ``num_speakers`` wins when set; otherwise the min/max bounds are forwarded.  Bounds are
        normalised so an inverted pair (``min > max``) cannot reach pyannote, which would abort
        the whole run.
        """
        if num_speakers is not None:
            count = max(1, int(num_speakers))
            return {"num_speakers": count}

        low = max(1, int(min_speakers or 1))
        high = max(1, int(max_speakers or low))
        if high < low:
            logger.warning(
                "[diarize] max_speakers (%s) < min_speakers (%s); swapping to keep the run valid",
                high,
                low,
            )
            low, high = high, low
        return {"min_speakers": low, "max_speakers": high}

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

        kwargs = self._speaker_kwargs(min_speakers, max_speakers, num_speakers)

        diarization = pipeline({"waveform": waveform, "sample_rate": sample_rate}, **kwargs)
        # pyannote >= 4 returns a DiarizeOutput wrapper; 3.x returns the Annotation directly.
        if hasattr(diarization, "exclusive_speaker_diarization"):
            diarization = diarization.exclusive_speaker_diarization
        return [
            DiarizationTurn(speaker=speaker, start=float(turn.start), end=float(turn.end))
            for turn, _, speaker in diarization.itertracks(yield_label=True)
        ]
