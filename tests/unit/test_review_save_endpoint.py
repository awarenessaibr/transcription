"""Router-level test for POST /api/transcripts/{id}/review/save.

There was no test for this endpoint at all, which is why its central defect went
unnoticed: it accepted ``edited_texts`` / ``edited_speakers`` / ``edited_starts``
/ ``edited_ends``, reported them in ``events_written``, returned ``status: ok``
-- and never wrote them to the transcript. A reviewer's corrections were lost on
reload (docs/REDUCED_CORE_MANIFEST.md section 6.2).

The test drives the real endpoint through a real ``JSONTranscriptStore`` on a
temporary copy of a real corpus file, so it exercises serialisation, patching and
the response contract together. Nothing is written into ``data/``.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.services.transcript_patcher import TranscriptPatcher
from src.infrastructure.json_store import JSONTranscriptStore
from src.presentation.routers import transcripts as transcripts_router

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "data" / "transcripts"

SOURCE = CORPUS / "I-002_04_NAR-06_STG_6_jetbridge_standoff.json"

pytestmark = pytest.mark.skipif(
    not SOURCE.exists(), reason="real transcript corpus not present"
)


@pytest.fixture()
def client(tmp_path: Path):
    """A TestClient whose transcript store points at a throwaway corpus copy."""
    data_dir = tmp_path / "transcripts"
    data_dir.mkdir()
    shutil.copy2(SOURCE, data_dir / SOURCE.name)

    store = JSONTranscriptStore(str(data_dir))
    transcripts_router.init_transcript_router(
        analyze_use_case=None,
        search_use_case=None,
        store=store,
        index=None,
        auditor=None,
        patcher=TranscriptPatcher(),
    )
    app = FastAPI()
    app.include_router(transcripts_router.router)
    with TestClient(app) as c:
        yield c, store
    # Reset module globals so other tests do not inherit this store.
    transcripts_router.init_transcript_router(None, None, None, None)


def _load(store: JSONTranscriptStore) -> dict:
    transcript = store.load(SOURCE.stem)
    assert transcript is not None
    return {
        "texts": {s.index: s.text for s in transcript.segments},
        "speakers": {s.index: s.speaker.label for s in transcript.segments},
        "starts": {s.index: s.start for s in transcript.segments},
        "ends": {s.index: s.end for s in transcript.segments},
        "recording_datetime": transcript.recording_datetime,
    }


def test_edited_text_is_persisted(client) -> None:
    c, store = client
    res = c.post(
        f"/api/transcripts/{SOURCE.stem}/review/save",
        json={"edited_texts": {"0": "TEXTO CORREGIDO"}},
    )
    assert res.status_code == 200, res.text
    assert _load(store)["texts"][0] == "TEXTO CORREGIDO"


def test_edited_speaker_is_persisted(client) -> None:
    c, store = client
    res = c.post(
        f"/api/transcripts/{SOURCE.stem}/review/save",
        json={"edited_speakers": {"0": "SPK-passenger-leandro"}},
    )
    assert res.status_code == 200, res.text
    assert _load(store)["speakers"][0] == "SPK-passenger-leandro"


def test_edited_timing_is_persisted(client) -> None:
    c, store = client
    before = _load(store)
    res = c.post(
        f"/api/transcripts/{SOURCE.stem}/review/save",
        json={"edited_starts": {"1": 12.5}, "edited_ends": {"1": 14.25}},
    )
    assert res.status_code == 200, res.text
    after = _load(store)
    assert after["starts"][1] == 12.5
    assert after["ends"][1] == 14.25
    assert after["starts"][1] != before["starts"].get(1) or before["starts"].get(1) == 12.5


def test_all_four_edit_maps_survive_a_reload(client) -> None:
    """The regression that matters: edits must still be there after re-reading."""
    c, store = client
    c.post(
        f"/api/transcripts/{SOURCE.stem}/review/save",
        json={
            "edited_texts": {"2": "hola mundo"},
            "edited_speakers": {"2": "dgac_official"},
            "edited_starts": {"2": 3.0},
            "edited_ends": {"2": 4.5},
        },
    )
    # Re-read from disk through a brand-new store instance.
    fresh = JSONTranscriptStore(store._dir)  # noqa: SLF001 - deliberate re-read
    t = fresh.load(SOURCE.stem)
    seg = next(s for s in t.segments if s.index == 2)
    assert seg.text == "hola mundo"
    assert seg.speaker.label == "dgac_official"
    assert seg.start == 3.0
    assert seg.end == 4.5


def test_recording_datetime_is_persisted(client) -> None:
    c, store = client
    res = c.post(
        f"/api/transcripts/{SOURCE.stem}/review/save",
        json={"recording_datetime": "2024-07-05T14:47:13-04:00"},
    )
    assert res.status_code == 200, res.text
    assert _load(store)["recording_datetime"] == "2024-07-05T14:47:13-04:00"


def test_inverted_timing_edit_is_rejected_not_persisted(client) -> None:
    """A start >= end edit must not corrupt the timeline; it is reported instead."""
    c, store = client
    before = _load(store)
    res = c.post(
        f"/api/transcripts/{SOURCE.stem}/review/save",
        json={"edited_starts": {"3": 99.0}, "edited_ends": {"3": 1.0}},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["partial"] is True
    assert any("must be < end" in s.get("reason", "") for s in body["skipped"]), body["skipped"]
    after = _load(store)
    assert (after["starts"][3], after["ends"][3]) == (
        before["starts"][3],
        before["ends"][3],
    )


def test_events_written_counts_only_applied_events(client) -> None:
    """`events_written` must reflect reality, not the raw payload size."""
    c, _store = client
    res = c.post(
        f"/api/transcripts/{SOURCE.stem}/review/save",
        json={"edited_texts": {"0": "a", "999999": "b"}},
    )
    assert res.status_code == 200, res.text
    # index 999999 does not exist, so exactly one event should be recorded.
    assert res.json()["events_written"] == 1


def test_reviewed_flag_and_note_still_work(client) -> None:
    """Guard the pre-existing behaviour that already worked."""
    c, store = client
    res = c.post(
        f"/api/transcripts/{SOURCE.stem}/review/save",
        json={"reviewed_indices": [0], "edited_correction_notes": {"0": "checked"}},
    )
    assert res.status_code == 200, res.text
    t = store.load(SOURCE.stem)
    seg = next(s for s in t.segments if s.index == 0)
    assert seg.reviewed is True
    assert seg.correction_note == "checked"


def test_saved_file_stays_schema_valid(client) -> None:
    """A review save must not produce a document the schema would reject."""
    from src.domain.transcript_fields import validate_transcript

    c, store = client
    c.post(
        f"/api/transcripts/{SOURCE.stem}/review/save",
        json={"edited_texts": {"0": "x"}, "edited_starts": {"0": 11.0}},
    )
    path = Path(store._dir) / f"{SOURCE.stem}.json"  # noqa: SLF001
    report = validate_transcript(json.loads(path.read_text(encoding="utf-8")))
    assert report.ok, report.errors
