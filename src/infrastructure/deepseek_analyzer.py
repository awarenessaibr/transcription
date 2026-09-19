"""DeepSeek transcript analyzer.

Implements TranscriptAnalyzerPort using DeepSeek's OpenAI-compatible API.
"""
from __future__ import annotations

import asyncio
import logging

import openai

from src.infrastructure.base_analyzer import BaseAnalyzerAdapter

logger = logging.getLogger(__name__)

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Approximate pricing in USD per million tokens for deepseek-v4-flash.
_PRICE_INPUT_PER_M = 0.27
_PRICE_OUTPUT_PER_M = 1.10


class DeepSeekAnalyzerAdapter(BaseAnalyzerAdapter):
    """Analyze transcripts using DeepSeek chat models."""

    _log_label = "deepseek-analyzer"

    def __init__(self, api_key: str, model: str = "deepseek-v4-flash"):
        self._client = openai.OpenAI(api_key=api_key, base_url=_DEEPSEEK_BASE_URL)
        self._model = model

    async def _call_api(self, user_prompt: str) -> tuple[str, int, int]:
        response = await asyncio.to_thread(
            self._client.chat.completions.create,
            model=self._model,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw_text = (response.choices[0].message.content or "").strip()
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0
        return raw_text, tokens_in, tokens_out

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        return round(
            (tokens_in * _PRICE_INPUT_PER_M + tokens_out * _PRICE_OUTPUT_PER_M) / 1_000_000,
            6,
        )
