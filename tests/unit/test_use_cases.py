"""Unit tests for use cases with mock adapters."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.application.use_cases.diarize_excerpt import DiarizeExcerptUseCase
from src.domain.entities.transcript import DiarizationTurn


class TestDiarizeExcerptUseCase:
    def _make_use_case(self, duration=10.0, turns=None):
        diarizer = MagicMock()
        audio_files = MagicMock()
        audio_files.get_duration.return_value = duration
        audio_files.crop_audio.return_value = ("fake_waveform", 16000)
        default_turns = [
            DiarizationTurn(speaker="SPEAKER_00", start=0.0, end=1.5),
            DiarizationTurn(speaker="SPEAKER_01", start=1.5, end=3.0),
        ]
        diarizer.diarize_waveform.return_value = turns if turns is not None else default_turns
        return DiarizeExcerptUseCase(diarizer=diarizer, audio_files=audio_files), diarizer, audio_files

    def test_basic_excerpt(self):
        uc, diarizer, audio_files = self._make_use_case()
        result = uc.execute(file_path="test.wav", start=0.0, end=3.0)
        assert result.start == 0.0
        assert result.end == 3.0
        assert len(result.segments) == 2
        assert result.segments[0].speaker == "SPEAKER_00"
        assert result.segments[1].speaker == "SPEAKER_01"
        audio_files.crop_audio.assert_called_once_with("test.wav", 0.0, 3.0)

    def test_end_exceeds_duration_raises(self):
        uc, _, _ = self._make_use_case(duration=5.0)
        with pytest.raises(ValueError, match="outside"):
            uc.execute(file_path="test.wav", start=0.0, end=10.0)

    def test_empty_turns(self):
        uc, _, _ = self._make_use_case(turns=[])
        result = uc.execute(file_path="test.wav", start=0.0, end=3.0)
        assert result.segments == []

    def test_speaker_indexing(self):
        turns = [
            DiarizationTurn(speaker="A", start=0.0, end=1.0),
            DiarizationTurn(speaker="B", start=1.0, end=2.0),
            DiarizationTurn(speaker="A", start=2.0, end=3.0),
        ]
        uc, _, _ = self._make_use_case(turns=turns)
        result = uc.execute(file_path="test.wav", start=0.0, end=3.0)
        assert [s.index for s in result.segments] == [1, 2, 3]
        assert [s.speaker for s in result.segments] == ["A", "B", "A"]
