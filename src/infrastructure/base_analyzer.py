"""Base analyzer adapter — shared logic for LLM transcript analysis.

Subclasses (ClaudeAnalyzerAdapter, DeepSeekAnalyzerAdapter) provide:
  - _log_label: str identifier for logging
  - _create_client(api_key) -> client
  - _call_api(user_prompt) -> (raw_text, tokens_in, tokens_out)
  - _estimate_cost(tokens_in, tokens_out) -> float
"""
from __future__ import annotations

import asyncio
import json
import logging

from src.domain.entities.transcript import Transcript

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a legal transcript analyst specializing in Chilean Spanish audio recordings.

Analyze the transcript and return a JSON object with these fields:
- "summary": A 2-4 sentence summary of the conversation in Spanish.
- "key_facts": A list of the most important factual claims or events mentioned.
- "entities": A list of objects {"name": str, "type": str} for people, places, \
organisations, dates, and legal references mentioned.
- "speakers": A list of objects {"label": str, "likely_role": str} guessing each \
speaker's role (e.g. "passenger", "police officer", "airline staff").
- "sentiment": Overall tone — one of "neutral", "confrontational", "cooperative", \
"distressed", "formal".
- "language_notes": Any notable Chilean Spanish expressions, slang, or dialect features.

Respond ONLY with valid JSON. No markdown fences, no commentary."""


class BaseAnalyzerAdapter:
    """Shared transcript analysis logic. Implements TranscriptAnalyzerPort."""

    _log_label: str = "analyzer"

    # ---- subclasses must implement ----

    def _create_client(self, api_key: str):
        """Create and return the LLM client."""
        raise NotImplementedError

    async def _call_api(self, user_prompt: str) -> tuple[str, int, int]:
        """Call the LLM API. Returns (raw_text, tokens_in, tokens_out)."""
        raise NotImplementedError

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Estimate USD cost from token counts."""
        raise NotImplementedError

    # ---- shared logic ----

    async def analyze(
        self,
        transcript: Transcript,
        *,
        instructions: str = "",
    ) -> dict:
        text = "\n".join(
            f"[{seg.speaker.label}] ({seg.start:.1f}s – {seg.end:.1f}s): {seg.text}"
            for seg in transcript.segments
        )
        if not text.strip():
            return {"error": "Empty transcript — nothing to analyze."}

        user_prompt = f"Analyze this transcript:\n\n{text}"
        if instructions:
            user_prompt += f"\n\nAdditional instructions: {instructions}"

        raw_text, tokens_in, tokens_out = await self._call_api(user_prompt)

        try:
            analysis = json.loads(raw_text)
        except json.JSONDecodeError:
            analysis = {"raw_response": raw_text}

        analysis["_meta"] = {
            "model": self._model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": self._estimate_cost(tokens_in, tokens_out),
        }

        logger.info(
            "[%s] analyzed transcript=%s tokens_in=%d tokens_out=%d",
            self._log_label,
            transcript.transcript_id,
            tokens_in,
            tokens_out,
        )
        return analysis

    @property
    def _system_prompt(self) -> str:
        return _SYSTEM_PROMPT
