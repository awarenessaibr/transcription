"""Claude-powered transcript reconciliation.

Implements TranscriptReconcilerPort. Takes raw Whisper output + reference
transcript and produces a reconciled result with named speakers, corrected
text, and confidence annotations.
"""
from __future__ import annotations

import asyncio
import logging

import anthropic

from src.infrastructure.base_reconciler import BaseReconcilerAdapter

logger = logging.getLogger(__name__)


class ClaudeReconcilerAdapter(BaseReconcilerAdapter):
    """Reconcile transcripts using Anthropic Claude. Implements TranscriptReconcilerPort."""

    _log_label = "reconciler"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-pro",
        base_url: str = "https://api.deepseek.com/anthropic",
    ):
        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self._model = model

    async def _call_api(self, user_prompt: str) -> tuple[str, int, int]:
        response = await asyncio.to_thread(
            self._client.messages.create,
            model=self._model,
            max_tokens=8192,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw_response = response.content[0].text
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        return raw_response, tokens_in, tokens_out

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Sonnet pricing ($3/M in, $15/M out)."""
        return round((tokens_in * 3 + tokens_out * 15) / 1_000_000, 6)
