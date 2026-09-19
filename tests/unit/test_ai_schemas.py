"""Unit tests for Phase 2 DTOs (analyze, search)."""
from src.application.dto.schemas import (
    AnalyzeRequest,
    AnalyzeResult,
    SearchHit,
    SearchRequest,
    SearchResult,
)


class TestAnalyzeRequest:
    def test_required_id(self):
        r = AnalyzeRequest(transcript_id="t_123")
        assert r.transcript_id == "t_123"
        assert r.instructions == ""

    def test_with_instructions(self):
        r = AnalyzeRequest(transcript_id="t_1", instructions="Focus on names")
        assert r.instructions == "Focus on names"


class TestAnalyzeResult:
    def test_serialization(self):
        r = AnalyzeResult(
            transcript_id="t_1",
            analysis={"summary": "test"},
            meta={"model": "deepseek-v4-pro", "tokens_in": 10},
        )
        d = r.model_dump()
        assert d["analysis"]["summary"] == "test"
        assert d["meta"]["model"] == "deepseek-v4-pro"


class TestSearchRequest:
    def test_defaults(self):
        r = SearchRequest(query="hello")
        assert r.limit == 5

    def test_custom_limit(self):
        r = SearchRequest(query="test", limit=20)
        assert r.limit == 20


class TestSearchHit:
    def test_creation(self):
        h = SearchHit(
            transcript_id="t_1",
            segment_index=2,
            speaker="SPEAKER_00",
            start=1.0,
            end=3.0,
            text="hello",
            score=0.85,
        )
        assert h.score == 0.85
        assert h.source_file == ""


class TestSearchResult:
    def test_with_hits(self):
        r = SearchResult(
            query="test",
            hits=[
                SearchHit(
                    transcript_id="t_1", segment_index=1, speaker="A",
                    start=0, end=1, text="x", score=0.9,
                )
            ],
        )
        assert len(r.hits) == 1
        assert r.query == "test"

    def test_empty(self):
        r = SearchResult(query="nothing", hits=[])
        assert r.hits == []
