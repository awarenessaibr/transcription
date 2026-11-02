from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.services.narration_aligner import (
    align_lines_to_segments,
    build_aligned_rows,
    parse_source_text,
    rows_to_csv,
)
from src.application.use_cases.align_narration import AlignNarrationUseCase
from src.presentation.routers.alignment import init_alignment_router, router
from src.presentation.routers.pinocchio import router as pinocchio_router


def test_parse_text_with_page_markers_extracts_spoken_text():
    targets = parse_source_text("Página 4\nFirst sentence.\nPágina 5: Second sentence.")

    assert [(target.page, target.text) for target in targets] == [
        ("4", "First sentence."),
        ("5", "Second sentence."),
    ]


def test_parse_csv_case_insensitively_and_preserve_pages():
    targets = parse_source_text('Start_ms,Page,Text\n0,12,"A sentence, with a comma"\n')

    assert [(target.page, target.text) for target in targets] == [
        ("12", "A sentence, with a comma"),
    ]


def test_alignment_returns_monotonic_rows_and_flags_poor_match():
    targets = parse_source_text("Hello there.\nA completely unrelated sentence.")
    segments = [
        {"start": 0.1, "end": 0.8, "text": "Hello there."},
        {"start": 1.0, "end": 1.6, "text": "Unmatched speech."},
    ]
    assignments = align_lines_to_segments(targets, segments)
    rows = build_aligned_rows(targets, segments, assignments)

    assert rows[0]["start_ms"] == 100
    assert rows[0]["end_ms"] == 800
    assert rows[1]["start_ms"] >= rows[0]["end_ms"]
    assert rows[1]["needs_review"] is True
    assert rows_to_csv(rows).splitlines()[0] == "start_ms,end_ms,page,text"
    assert next(csv.reader(io.StringIO(rows_to_csv(rows))))[2] == "page"


class FakeASR:
    def __init__(self):
        self.call = None

    def transcribe(self, audio_path, **kwargs):
        self.call = (audio_path, kwargs)
        return {
            "segments": [
                {"start": 0.2, "end": 0.9, "text": "Hola mundo."},
                {"start": 1.1, "end": 1.8, "text": "Hasta luego."},
            ]
        }


class FakeAudioFiles:
    async def save_upload(self, filename: str, content: bytes, dest_dir: str) -> str:
        path = Path(dest_dir) / filename
        path.write_bytes(content)
        return str(path)

    def convert_to_wav(self, audio_path: str) -> str:
        return audio_path


@pytest.mark.asyncio
async def test_use_case_transcribes_once_without_persisting_and_cleans_temp_audio():
    asr = FakeASR()
    use_case = AlignNarrationUseCase(asr=asr, audio_files=FakeAudioFiles())

    result = await use_case.execute(
        audio_filename="voice.wav",
        audio_content=b"wav bytes",
        source_content="Página 2\nHola mundo.\nHasta luego.",
        language="es-CL",
        model_size="small",
    )

    assert result["targets_count"] == 2
    assert result["rows"][0]["page"] == "2"
    assert result["rows"][0]["start_ms"] == 200
    assert asr.call[1]["language"] == "es"
    assert asr.call[1]["word_timestamps"] is False
    assert not Path(asr.call[0]).exists()


def test_aligner_page_is_served_by_main_ui_router():
    app = FastAPI()
    app.include_router(pinocchio_router)

    response = TestClient(app).get("/aligner")

    assert response.status_code == 200
    assert "Narration Aligner" in response.text
    assert "/api/alignment/narration" in response.text


def test_alignment_api_calls_wired_use_case():
    class FakeAlignUseCase:
        async def execute(self, **kwargs):
            return {"rows": [{"text": "hello"}], "csv": "text\nhello\n"}

    app = FastAPI()
    init_alignment_router(FakeAlignUseCase())
    app.include_router(router)

    response = TestClient(app).post(
        "/api/alignment/narration",
        files={
            "audio": ("voice.wav", b"audio", "audio/wav"),
            "text": ("lines.txt", b"hello", "text/plain"),
        },
    )

    assert response.status_code == 200
    assert response.json()["rows"] == [{"text": "hello"}]
