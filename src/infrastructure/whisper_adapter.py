"""Whisper ASR adapter — implements ASRPort."""
from __future__ import annotations

import logging

from src.infrastructure.model_manager import ModelManager

logger = logging.getLogger(__name__)


class WhisperASRAdapter:
    """Transcribes audio using OpenAI Whisper. Implements ASRPort."""

    def __init__(self, model_manager: ModelManager):
        self._mm = model_manager

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        **kwargs,
    ) -> dict:
        model_size = kwargs.pop("model_size", "large-v3")
        model = self._mm.get_whisper_model(model_size)
        transcribe_kwargs = dict(
            temperature=kwargs.get("temperature", 0.0),
            beam_size=kwargs.get("beam_size", 5),
            best_of=kwargs.get("best_of", 5),
            compression_ratio_threshold=kwargs.get("compression_ratio_threshold", 2.4),
            logprob_threshold=kwargs.get("logprob_threshold", -1.0),
            no_speech_threshold=kwargs.get("no_speech_threshold", 0.6),
            condition_on_previous_text=kwargs.get("condition_on_previous_text", False),
            initial_prompt=kwargs.get("initial_prompt"),
            length_penalty=kwargs.get("length_penalty", 1.0),
            patience=kwargs.get("patience"),
            suppress_blank=kwargs.get("suppress_blank", True),
            suppress_tokens=kwargs.get("suppress_tokens", [-1]),
            verbose=False,
            word_timestamps=kwargs.get("word_timestamps", False),
        )
        if language is not None:
            transcribe_kwargs["language"] = language
        result = model.transcribe(audio_path, **transcribe_kwargs)
        return {"text": result.get("text", ""), "language": result.get("language")}

    def clear_cache(self):
        self._mm.clear_cache()
