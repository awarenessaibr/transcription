from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.application.use_cases.transcribe_audio import TranscribeAudioUseCase
from src.domain.entities.transcript import DiarizationTurn


class DummyASR:
    def transcribe(self, *_args, **_kwargs) -> str:
        return "texto de teste"


class DummyDiarizer:
    def diarize(self, *_args, **_kwargs):
        return [DiarizationTurn(speaker="SPEAKER_00", start=0.0, end=1.0)]


class DummyProcessor:
    def process(self, audio_path: str, _params: dict) -> str:
        base, ext = Path(audio_path).with_suffix(""), Path(audio_path).suffix
        processed_path = f"{base}_processed{ext or '.wav'}"
        shutil.copyfile(audio_path, processed_path)
        return processed_path


class DummyStore:
    def __init__(self):
        self.saved = {}

    def save(self, transcript):
        self.saved[transcript.transcript_id] = transcript
        return transcript.transcript_id

    def load(self, transcript_id: str):
        return self.saved.get(transcript_id)

    def list_ids(self):
        return list(self.saved.keys())


class DummyAudioFiles:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.counter = 0
        self.last_saved_path: str | None = None
        self.last_processed_path: str | None = None

    async def save_upload(self, filename: str, content: bytes, dest_dir: str) -> str:
        self.counter += 1
        stem = Path(filename).stem
        out = Path(dest_dir) / f"{stem} {self.counter}.wav"
        out.write_bytes(content)
        self.last_saved_path = str(out)
        return str(out)

    def convert_to_wav(self, audio_path: str) -> str:
        return audio_path

    def extract_segment(self, audio_path: str, _start_ms: int, _end_ms: int, out_path: str) -> str:
        Path(out_path).write_bytes(Path(audio_path).read_bytes())
        return out_path

    def get_duration(self, _audio_path: str) -> float:
        return 1.0


@pytest.mark.asyncio
async def test_transcribe_uses_saved_audio_name_and_keeps_audio_files(tmp_path):
    audio_files = DummyAudioFiles(tmp_path)
    store = DummyStore()
    use_case = TranscribeAudioUseCase(
        asr=DummyASR(),
        diarizer=DummyDiarizer(),
        processor=DummyProcessor(),
        store=store,
        audio_files=audio_files,
        index=None,
    )

    result = await use_case.execute(
        filename="segment_0088.wav",
        content=b"wav-bytes",
        dest_dir=str(tmp_path),
        params={},
    )

    assert result.transcript_id == "segment_0088_1"
    saved = store.load(result.transcript_id)
    assert saved is not None
    assert saved.source_file == "segment_0088 1.wav"
    assert Path(audio_files.last_saved_path).exists()
    assert saved.metadata["saved_audio_file"] == "segment_0088 1.wav"
    assert saved.metadata["processed_audio_file"] == "segment_0088 1_processed.wav"
    assert (tmp_path / "segment_0088 1_processed.wav").exists()


@pytest.mark.asyncio
async def test_transcribe_can_cleanup_audio_files_when_disabled(tmp_path):
    audio_files = DummyAudioFiles(tmp_path)
    store = DummyStore()
    use_case = TranscribeAudioUseCase(
        asr=DummyASR(),
        diarizer=DummyDiarizer(),
        processor=DummyProcessor(),
        store=store,
        audio_files=audio_files,
        index=None,
    )

    result = await use_case.execute(
        filename="sample.wav",
        content=b"wav-bytes",
        dest_dir=str(tmp_path),
        params={"keep_audio_artifacts": False},
    )

    assert result.transcript_id == "sample_1"
    assert not (tmp_path / "sample 1.wav").exists()
    assert not (tmp_path / "sample 1_processed.wav").exists()
