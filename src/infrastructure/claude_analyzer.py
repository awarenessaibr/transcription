"""Claude transcript analyzer — implements TranscriptAnalyzerPort."""
from __future__ import annotations

import asyncio
import logging

import anthropic

from src.infrastructure.base_analyzer import BaseAnalyzerAdapter

logger = logging.getLogger(__name__)


class ClaudeAnalyzerAdapter(BaseAnalyzerAdapter):
    """Analyze transcripts using Anthropic Claude API. Implements TranscriptAnalyzerPort."""

    _log_label = "claude"

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
            max_tokens=4096,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw_text = response.content[0].text
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        return raw_text, tokens_in, tokens_out

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Sonnet pricing ($3/M in, $15/M out)."""
        return round((tokens_in * 3 + tokens_out * 15) / 1_000_000, 6)
