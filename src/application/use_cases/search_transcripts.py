"""Use case: Semantic search across transcripts."""
from __future__ import annotations

import logging

from src.application.dto.schemas import SearchHit, SearchResult
from src.domain.ports.interfaces import TranscriptIndexPort

logger = logging.getLogger(__name__)


class SearchTranscriptsUseCase:
    """Semantic search over indexed transcript segments."""

    def __init__(self, index: TranscriptIndexPort):
        self._index = index

    async def execute(self, query: str, *, limit: int = 5) -> SearchResult:
        raw_hits = await self._index.search(query, limit=limit)

        hits = [
            SearchHit(
                transcript_id=h["transcript_id"],
                segment_index=h["segment_index"],
                speaker=h["speaker"],
                start=h["start"],
                end=h["end"],
                text=h["text"],
                source_file=h.get("source_file", ""),
                score=h["score"],
            )
            for h in raw_hits
        ]

        logger.info("[search] query=%r hits=%d", query[:80], len(hits))
        return SearchResult(query=query, hits=hits)
