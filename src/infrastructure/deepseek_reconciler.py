"""DeepSeek-powered transcript reconciliation.

Implements TranscriptReconcilerPort using the DeepSeek API (OpenAI-compatible).
Uses deepseek-v4-pro for structured chain-of-thought reconciliation.
"""
from __future__ import annotations

import asyncio
import logging

import openai

from src.infrastructure.base_reconciler import BaseReconcilerAdapter

logger = logging.getLogger(__name__)

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# deepseek-v4-pro pricing (USD per million tokens, as of 2025)
_PRICE_INPUT_PER_M = 0.55
_PRICE_OUTPUT_PER_M = 2.19


class DeepSeekReconcilerAdapter(BaseReconcilerAdapter):
    """Reconcile transcripts using DeepSeek reasoner. Implements TranscriptReconcilerPort."""

    _log_label = "deepseek-reconciler"

    def __init__(self, api_key: str, model: str = "deepseek-v4-pro"):
        self._client = openai.OpenAI(api_key=api_key, base_url=_DEEPSEEK_BASE_URL)
        self._model = model

    async def _call_api(self, user_prompt: str) -> tuple[str, int, int]:
        response = await asyncio.to_thread(
            self._client.chat.completions.create,
            model=self._model,
            max_tokens=8192,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw_response = response.choices[0].message.content or ""
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0
        return raw_response, tokens_in, tokens_out

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """deepseek-v4-pro pricing ($0.55/M in, $2.19/M out)."""
        return round(
            (tokens_in * _PRICE_INPUT_PER_M + tokens_out * _PRICE_OUTPUT_PER_M) / 1_000_000,
            6,
        )
