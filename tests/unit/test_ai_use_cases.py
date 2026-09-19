"""Unit tests for AnalyzeTranscript and SearchTranscripts use cases."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.use_cases.analyze_transcript import AnalyzeTranscriptUseCase
from src.application.use_cases.search_transcripts import SearchTranscriptsUseCase
from src.domain.entities.transcript import Segment, Speaker, Transcript


@pytest.fixture
def sample_transcript():
    return Transcript(
        transcript_id="t_test",
        segments=[
            Segment(index=1, speaker=Speaker("SPEAKER_00"), start=0.0, end=2.0, text="Hola po"),
            Segment(index=2, speaker=Speaker("SPEAKER_01"), start=2.0, end=4.0, text="Chao weón"),
        ],
        source_file="test.wav",
        language="es",
    )


class TestAnalyzeTranscriptUseCase:
    @pytest.mark.asyncio
    async def test_analyze_success(self, sample_transcript):
        analyzer = AsyncMock()
        analyzer.analyze.return_value = {
            "summary": "Short conversation.",
            "entities": [],
            "_meta": {"model": "deepseek-v4-pro", "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001},
        }
        store = MagicMock()
        store.load.return_value = sample_transcript

        uc = AnalyzeTranscriptUseCase(analyzer=analyzer, store=store)
        result = await uc.execute("t_test")

        assert result.transcript_id == "t_test"
        assert result.analysis["summary"] == "Short conversation."
        assert result.meta["model"] == "deepseek-v4-pro"
        store.load.assert_called_once_with("t_test")

    @pytest.mark.asyncio
    async def test_analyze_not_found(self):
        store = MagicMock()
        store.load.return_value = None
        analyzer = AsyncMock()

        uc = AnalyzeTranscriptUseCase(analyzer=analyzer, store=store)
        with pytest.raises(ValueError, match="not found"):
            await uc.execute("nonexistent")

    @pytest.mark.asyncio
    async def test_analyze_with_instructions(self, sample_transcript):
        analyzer = AsyncMock()
        analyzer.analyze.return_value = {"summary": "Custom.", "_meta": {}}
        store = MagicMock()
        store.load.return_value = sample_transcript

        uc = AnalyzeTranscriptUseCase(analyzer=analyzer, store=store)
        await uc.execute("t_test", instructions="Focus on legal issues")

        analyzer.analyze.assert_called_once()
        call_kwargs = analyzer.analyze.call_args
        assert call_kwargs.kwargs["instructions"] == "Focus on legal issues"


class TestSearchTranscriptsUseCase:
    @pytest.mark.asyncio
    async def test_search_returns_hits(self):
        index = AsyncMock()
        index.search.return_value = [
            {
                "transcript_id": "t_1",
                "segment_index": 3,
                "speaker": "SPEAKER_00",
                "start": 5.0,
                "end": 8.0,
                "text": "mentioned the flight",
                "source_file": "audio.wav",
                "score": 0.92,
            }
        ]

        uc = SearchTranscriptsUseCase(index=index)
        result = await uc.execute("flight delay", limit=5)

        assert result.query == "flight delay"
        assert len(result.hits) == 1
        assert result.hits[0].score == 0.92
        assert result.hits[0].text == "mentioned the flight"
        index.search.assert_called_once_with("flight delay", limit=5)

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        index = AsyncMock()
        index.search.return_value = []

        uc = SearchTranscriptsUseCase(index=index)
        result = await uc.execute("something obscure")
        assert result.hits == []
