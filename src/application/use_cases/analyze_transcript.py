"""Use case: Analyze a transcript with Claude."""
from __future__ import annotations

import logging

from src.application.dto.schemas import AnalyzeResult
from src.domain.ports.interfaces import TranscriptAnalyzerPort, TranscriptStorePort

logger = logging.getLogger(__name__)


class AnalyzeTranscriptUseCase:
    """Load a transcript and run LLM analysis on it."""

    def __init__(
        self,
        analyzer: TranscriptAnalyzerPort,
        store: TranscriptStorePort,
    ):
        self._analyzer = analyzer
        self._store = store

    async def execute(
        self,
        transcript_id: str,
        *,
        instructions: str = "",
    ) -> AnalyzeResult:
        transcript = self._store.load(transcript_id)
        if transcript is None:
            raise ValueError(f"Transcript not found: {transcript_id}")

        analysis = await self._analyzer.analyze(
            transcript, instructions=instructions
        )

        meta = analysis.pop("_meta", {})

        logger.info(
            "[analyze] transcript=%s model=%s cost=$%.4f",
            transcript_id,
            meta.get("model", "unknown"),
            meta.get("cost_usd", 0),
        )

        return AnalyzeResult(
            transcript_id=transcript_id,
            analysis=analysis,
            meta=meta,
        )
