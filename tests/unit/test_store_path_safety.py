"""Path-safety tests for the transcript store and the import endpoint.

``transcript_id`` was interpolated straight into a filename:

    path = os.path.join(self._dir, f"{transcript_id}.json")

so ``POST /api/transcripts/import`` with
``{"transcript_id": "./../../escaped_root"}`` wrote a JSON file two levels above
the transcript directory -- with attacker-controlled contents and metadata --
and ``load()`` had the same join. See
docs/REDUCED_CORE_MANIFEST.md section 6.11.

The router-level test is the important one: it exercises the path that was
actually reachable over HTTP.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.entities.transcript import Segment, Speaker, Transcript
from src.infrastructure.json_store import (
    JSONTranscriptStore,
    validate_transcript_id,
)

TRAVERSAL_IDS = [
    "./../../escaped_root",
    "../escaped",
    "../../etc/passwd",
    "a/b",
    "a\\b",
    ".hidden",          # would write a dotfile
    "..",
    "",
    "   ",
    "x\x00y",
    "a..b",
]


@pytest.mark.parametrize("bad", TRAVERSAL_IDS)
def test_validate_transcript_id_rejects_traversal(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_transcript_id(bad)


@pytest.mark.parametrize(
    "bad", [None, 42, b"bytes", ["list"]]
)
def test_validate_transcript_id_rejects_non_strings(bad) -> None:
    with pytest.raises(ValueError):
        validate_transcript_id(bad)


@pytest.mark.parametrize(
    "good",
    [
        "I-002_04_NAR-06_STG_6_jetbridge_standoff",
        "I-001_01_Guarulhos_incident_Ofensive_Agressive_Behaviour",
        "plain",
        "with.dots",
        "a" * 128,
    ],
)
def test_validate_transcript_id_accepts_real_ids(good: str) -> None:
    assert validate_transcript_id(good) == good


def test_real_corpus_ids_all_validate() -> None:
    """The guard must not reject any id the corpus actually uses."""
    import glob

    root = Path(__file__).resolve().parents[2]
    ids = [
        json.loads(Path(p).read_text(encoding="utf-8"))["transcript_id"]
        for p in glob.glob(str(root / "data" / "transcripts" / "*.json"))
    ]
    assert ids, "corpus not present"
    for tid in ids:
        assert validate_transcript_id(tid) == tid


def test_store_save_refuses_a_traversal_id(tmp_path: Path) -> None:
    store = JSONTranscriptStore(str(tmp_path / "store"))
    bad = Transcript(
        transcript_id="./../../escaped",
        segments=[Segment(index=0, speaker=Speaker(label="x"), start=0.0, end=1.0)],
    )
    with pytest.raises(ValueError):
        store.save(bad)
    # Nothing may appear outside the store directory.
    assert not list((tmp_path).glob("escaped*")), list(tmp_path.iterdir())


def test_store_load_refuses_a_traversal_id(tmp_path: Path) -> None:
    store = JSONTranscriptStore(str(tmp_path / "store"))
    with pytest.raises(ValueError):
        store.load("../../etc/passwd")


def test_import_endpoint_cannot_write_outside_the_store(tmp_path: Path) -> None:
    """The reachable HTTP path: a traversal id must not create a file."""
    from src.presentation.routers import transcripts as transcripts_router

    store_dir = tmp_path / "transcripts"
    store = JSONTranscriptStore(str(store_dir))
    transcripts_router.init_transcript_router(
        analyze_use_case=None,
        search_use_case=None,
        store=store,
        index=None,
        auditor=None,
        patcher=None,
    )
    app = FastAPI()
    app.include_router(transcripts_router.router)

    payload = {
        "overwrite": True,
        "rename_by_filename": False,
        "runs": [
            {
                "transcript_id": "./../../escaped_root",
                "source_file": "x.wav",
                "metadata": {"attacker": "controlled"},
                "segments": [
                    {"index": 0, "speaker": "s", "start": 0.0, "end": 1.0, "text": "boom"}
                ],
            }
        ],
    }
    with TestClient(app) as c:
        res = c.post("/api/transcripts/import", json=payload)
    transcripts_router.init_transcript_router(None, None, None, None)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 0, body
    assert body["errors"], body

    # The decisive assertion: nothing was written above the store root.
    escaped = sorted(p for p in tmp_path.rglob("*") if p.is_file() and p.suffix == ".json")
    assert escaped == [], f"files escaped the store: {escaped}"


def test_import_endpoint_still_imports_a_legitimate_id(tmp_path: Path) -> None:
    """Control case: normal ids continue to work."""
    from src.presentation.routers import transcripts as transcripts_router

    store_dir = tmp_path / "transcripts"
    store = JSONTranscriptStore(str(store_dir))
    transcripts_router.init_transcript_router(
        analyze_use_case=None,
        search_use_case=None,
        store=store,
        index=None,
        auditor=None,
        patcher=None,
    )
    app = FastAPI()
    app.include_router(transcripts_router.router)

    payload = {
        "overwrite": True,
        "rename_by_filename": False,
        "runs": [
            {
                "transcript_id": "I-999_01_test_case",
                "source_file": "x.wav",
                "segments": [
                    {"index": 0, "speaker": "s", "start": 0.0, "end": 1.0, "text": "hi"}
                ],
            }
        ],
    }
    with TestClient(app) as c:
        res = c.post("/api/transcripts/import", json=payload)
    transcripts_router.init_transcript_router(None, None, None, None)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 1, body
    assert (store_dir / "I-999_01_test_case.json").exists()
