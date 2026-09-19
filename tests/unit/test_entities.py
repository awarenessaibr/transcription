"""Unit tests for domain entities."""
from src.domain.entities.transcript import (
    AudioFile,
    DiarizationTurn,
    Segment,
    Speaker,
    Transcript,
)


class TestSpeaker:
    def test_create(self):
        s = Speaker(label="SPEAKER_00")
        assert s.label == "SPEAKER_00"

    def test_frozen(self):
        s = Speaker(label="X")
        try:
            s.label = "Y"
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


class TestSegment:
    def test_duration(self):
        seg = Segment(index=1, speaker=Speaker("A"), start=1.0, end=3.5, text="hello")
        assert seg.duration == 2.5

    def test_duration_rounds(self):
        seg = Segment(index=1, speaker=Speaker("A"), start=0.0, end=1.1111)
        assert seg.duration == 1.111

    def test_default_text(self):
        seg = Segment(index=1, speaker=Speaker("A"), start=0, end=1)
        assert seg.text == ""

    def test_frozen(self):
        seg = Segment(index=1, speaker=Speaker("A"), start=0, end=1)
        try:
            seg.text = "changed"
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


class TestDiarizationTurn:
    def test_duration(self):
        turn = DiarizationTurn(speaker="SPEAKER_01", start=2.0, end=5.0)
        assert turn.duration == 3.0

    def test_frozen(self):
        turn = DiarizationTurn(speaker="X", start=0, end=1)
        try:
            turn.speaker = "Y"
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


class TestTranscript:
    def test_empty(self):
        t = Transcript(transcript_id="test_1")
        assert t.segments == []
        assert t.source_file == ""
        assert t.language == "es"

    def test_with_segments(self):
        segs = [
            Segment(index=1, speaker=Speaker("A"), start=0, end=1, text="hi"),
            Segment(index=2, speaker=Speaker("B"), start=1, end=3, text="bye"),
        ]
        t = Transcript(transcript_id="t1", segments=segs, source_file="test.wav")
        assert len(t.segments) == 2
        assert t.segments[0].speaker.label == "A"

    def test_mutable(self):
        t = Transcript(transcript_id="t1")
        t.segments.append(Segment(index=1, speaker=Speaker("X"), start=0, end=1))
        assert len(t.segments) == 1


class TestAudioFile:
    def test_default_format(self):
        af = AudioFile(path="/tmp/test.wav")
        assert af.format == "wav"

    def test_nonexistent_file(self):
        af = AudioFile(path="/nonexistent/path/audio.wav")
        assert af.exists is False
