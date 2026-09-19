"""Integration tests for audio file adapter."""
from __future__ import annotations

import os
import struct
import wave

import pytest

from src.infrastructure.audio_file_adapter import AudioFileAdapter


def _create_wav(path: str, duration_s: float = 1.0, sample_rate: int = 16000):
    """Create a minimal valid WAV file for testing."""
    n_samples = int(sample_rate * duration_s)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))


class TestAudioFileAdapter:
    @pytest.mark.asyncio
    async def test_save_upload(self, tmp_path):
        adapter = AudioFileAdapter()
        content = b"fake audio content"
        path = await adapter.save_upload("test_audio.wav", content, str(tmp_path))
        assert os.path.exists(path)
        with open(path, "rb") as f:
            assert f.read() == content

    def test_convert_to_wav_already_wav(self, tmp_path):
        adapter = AudioFileAdapter()
        wav_path = str(tmp_path / "test.wav")
        _create_wav(wav_path)
        result = adapter.convert_to_wav(wav_path)
        assert result.endswith(".wav")
        assert os.path.exists(result)

    def test_get_duration(self, tmp_path):
        adapter = AudioFileAdapter()
        wav_path = str(tmp_path / "test.wav")
        _create_wav(wav_path, duration_s=2.0)
        duration = adapter.get_duration(wav_path)
        assert abs(duration - 2.0) < 0.1

    def test_extract_segment(self, tmp_path):
        adapter = AudioFileAdapter()
        wav_path = str(tmp_path / "source.wav")
        _create_wav(wav_path, duration_s=3.0)
        out_path = str(tmp_path / "segment.wav")
        result = adapter.extract_segment(wav_path, 0, 1000, out_path)
        assert os.path.exists(result)
