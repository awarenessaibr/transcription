"""Unit tests for application DTOs (Pydantic schemas)."""
from src.application.dto.schemas import (
    ExcerptRequest,
    ExcerptResult,
    PreprocessingParams,
    SegmentResult,
    TimingResult,
    TranscribeRequest,
    TranscribeResult,
    WhisperDecodingParams,
)


class TestPreprocessingParams:
    def test_defaults(self):
        p = PreprocessingParams()
        assert p.noise_reduce is True
        assert p.reduction_db == 25
        assert p.voice_enhance is True
        assert p.apply_gain is True
        assert p.target_lufs == -16.0
        assert p.remove_silence is True
        assert p.silence_thresh == -45
        assert p.min_silence_len == 250


class TestWhisperDecodingParams:
    def test_defaults(self):
        w = WhisperDecodingParams()
        assert w.beam_size == 5
        assert w.whisper_temp == 0.0
        assert w.suppress_tokens == "-1"
        assert w.initial_prompt is None
        assert w.patience is None


class TestTranscribeRequest:
    def test_defaults(self):
        r = TranscribeRequest()
        assert r.language == "es-CL"
        assert r.model_size == "large-v3"
        assert r.min_speakers == 1
        assert r.max_speakers == 2

    def test_custom(self):
        r = TranscribeRequest(language="en-US", model_size="small", max_speakers=5)
        assert r.language == "en-US"
        assert r.max_speakers == 5


class TestExcerptRequest:
    def test_required_fields(self):
        r = ExcerptRequest(file_path="/data/test.wav", start=1.0, end=5.0)
        assert r.file_path == "/data/test.wav"
        assert r.start == 1.0
        assert r.end == 5.0
        assert r.num_speakers is None


class TestSegmentResult:
    def test_creation(self):
        s = SegmentResult(index=1, speaker="SPEAKER_00", start=0.0, end=2.5, duration=2.5, text="hello")
        assert s.index == 1
        assert s.speaker == "SPEAKER_00"

    def test_default_text(self):
        s = SegmentResult(index=1, speaker="A", start=0, end=1, duration=1.0)
        assert s.text == ""


class TestTimingResult:
    def test_defaults_zero(self):
        t = TimingResult()
        assert t.save_s == 0.0
        assert t.total_s == 0.0


class TestTranscribeResult:
    def test_serialization(self):
        r = TranscribeResult(
            transcript_id="t_123",
            segments=[SegmentResult(index=1, speaker="A", start=0, end=1, duration=1.0, text="hi")],
            timings=TimingResult(total_s=5.0),
            params={"model_size": "large-v3"},
        )
        d = r.model_dump()
        assert d["transcript_id"] == "t_123"
        assert len(d["segments"]) == 1
        assert d["timings"]["total_s"] == 5.0


class TestExcerptResult:
    def test_empty_segments(self):
        r = ExcerptResult(start=1.0, end=3.0, segments=[])
        assert r.start == 1.0
        assert r.segments == []
