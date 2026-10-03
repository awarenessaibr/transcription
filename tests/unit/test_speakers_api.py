"""Endpoint tests for the speaker resolution API.

The write path matters most: ``POST /api/speakers/map`` is the only endpoint here
that mutates a transcript, and it is the one that makes a diarization run
attributable. These tests drive the real router over a throwaway transcript store
and a synthetic registry, and assert that nothing is written unless asked.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.infrastructure.json_store import JSONTranscriptStore
from src.presentation.routers import speakers as speakers_router

NOTE = """---
note_type: speaker
speaker_id: SPK-antonela-latam-agent
display_name: "Antonela"
role: "Agent / Supervisor"
organization: "LATAM Airlines"
identification_confidence: partial
aliases:
  - "Antonela"
  - "Anto"
key_statements:
  - quote: "esta es la carta que usted pidio"
    transcript: "[[x]]"
---

# Antonela

## Key Statements

> ninguno de nuestros documentos tiene firma
"""

NOTE2 = """---
note_type: speaker
speaker_id: SPK-passenger-leandro
display_name: "Leandro Disconzi"
role: "Passenger"
identification_confidence: confirmed
aliases:
  - "Leandro"
---

# Leandro
"""

TRANSCRIPT = {
    "transcript_id": "aeropuerto_STG_6_run1",
    "audio_id": "aeropuerto_STG_6",
    "segments": [
        {"index": 0, "speaker": "SPEAKER_00", "start": 0.0, "end": 1.0, "text": "hola"},
        {
            "index": 1,
            "speaker": "SPEAKER_01",
            "start": 1.0,
            "end": 2.0,
            "text": "esta es la carta que usted pidio",
        },
    ],
    "participants": [],
}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    speakers = tmp_path / "speakers"
    speakers.mkdir()
    (speakers/"SPK-antonela-latam-agent.md").write_text(NOTE, encoding="utf-8")
    (speakers/"SPK-passenger-leandro.md").write_text(NOTE2, encoding="utf-8")
    index_path = tmp_path/"speaker_index.json"
    index_path.write_text(json.dumps({
        "answered": True,
        "mapped_speakers": {
            # cast is keyed on the *peer* transcript that covers the same audio
            "SPK-antonela-latam-agent": {
                "display_name": "Antonela", "organization": "LATAM Airlines",
                "identification_confidence": "partial",
                "md_file": str(speakers/"SPK-antonela-latam-agent.md"),
                "appearances": [{"transcript_id": "aeropuerto_STG_6", "segment_labels": ["airline_supervisor"]}],
            },
            "SPK-passenger-leandro": {
                "display_name": "Leandro Disconzi",
                "md_file": str(speakers/"SPK-passenger-leandro.md"),
                "appearances": [{"transcript_id": "aeropuerto_STG_6", "segment_labels": ["passenger"]}],
            },
        },
    }), encoding="utf-8")

    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    (tdir/"aeropuerto_STG_6_run1.json").write_text(json.dumps(TRANSCRIPT), encoding="utf-8")
    store = JSONTranscriptStore(str(tdir))

    monkeypatch.setattr(speakers_router.settings, "SPEAKERS_DIR", str(speakers), raising=False)
    monkeypatch.setattr(speakers_router.settings, "SPEAKER_INDEX_FILE", str(index_path), raising=False)
    monkeypatch.setattr(speakers_router.settings, "SPEAKER_MAP_FILE", str(tmp_path/"speaker_segment_map.json"), raising=False)
    speakers_router.init_speakers_router(store)

    app = FastAPI()
    app.include_router(speakers_router.router)
    with TestClient(app) as c:
        yield c, store, tmp_path
    speakers_router.init_speakers_router(None)


def _seg(store, tid="aeropuerto_STG_6_run1"):
    t = store.load(tid)
    return {s.index: s for s in t.segments}, t


# --------------------------------------------------------------------------
# read / resolve
# --------------------------------------------------------------------------
def test_index_and_files_still_work(client) -> None:
    c, _s, _t = client
    assert c.get("/api/speakers/index").status_code == 200
    files = c.get("/api/speakers/files").json()
    assert files["count"] == 2


def test_literal_routes_are_not_shadowed_by_speaker_id(client) -> None:
    """`/{speaker_id}` is declared last; /index must not be read as an id."""
    c, _s, _t = client
    assert c.get("/api/speakers/index").status_code == 200
    assert c.get("/api/speakers/candidates?transcript_id=x").status_code == 404  # not an id lookup
    assert c.get("/api/speakers/SPK-antonela-latam-agent").status_code == 200


def test_candidates_returns_the_recording_cast(client) -> None:
    c, _s, _t = client
    body = c.get("/api/speakers/candidates?transcript_id=aeropuerto_STG_6_run1").json()
    assert body["audio_id"] == "aeropuerto_STG_6"
    assert body["peer_transcripts"] == []
    ids = {p["speaker_id"] for p in body["known_cast"]}
    assert ids == {"SPK-antonela-latam-agent", "SPK-passenger-leandro"}
    assert body["registry_size"] == 2


def test_resolve_proposes_without_writing(client) -> None:
    c, store, _t = client
    body = c.post("/api/speakers/resolve", json={"transcript_id": "aeropuerto_STG_6_run1"}).json()
    proposals = {p["raw_label"]: p for p in body["proposals"]}
    # SPEAKER_01's text contains a verbatim registry quote
    assert proposals["SPEAKER_01"]["speaker_id"] == "SPK-antonela-latam-agent"
    assert "known_statement" in proposals["SPEAKER_01"]["signals"]
    # SPEAKER_00 is undetermined but narrowed to the cast
    assert proposals["SPEAKER_00"]["speaker_id"] == ""
    assert set(proposals["SPEAKER_00"]["candidates"]) == {
        "SPK-antonela-latam-agent", "SPK-passenger-leandro"
    }
    assert body["proposed_map"] == {"SPEAKER_01": "SPK-antonela-latam-agent"}
    # nothing written
    segs, _ = _seg(store)
    assert all(s.speaker_id == "" for s in segs.values())


def test_resolve_unknown_transcript_is_404(client) -> None:
    c, _s, _t = client
    assert c.post("/api/speakers/resolve", json={"transcript_id": "nope"}).status_code == 404


def test_resolve_rejects_a_traversing_id(client) -> None:
    c, _s, _t = client
    res = c.post("/api/speakers/resolve", json={"transcript_id": "../../etc/passwd"})
    assert res.status_code in (400, 404)


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------
def test_apply_map_persists_and_is_readable(client) -> None:
    c, store, _t = client
    res = c.post("/api/speakers/map", json={
        "transcript_id": "aeropuerto_STG_6_run1",
        "speaker_map": {"SPEAKER_00": "SPK-passenger-leandro",
                        "SPEAKER_01": "SPK-antonela-latam-agent"},
    })
    assert res.status_code == 200, res.text
    assert res.json()["applied_count"] == 2
    assert res.json()["saved"] is True

    segs, t = _seg(store)
    assert segs[0].speaker_id == "SPK-passenger-leandro"
    assert segs[1].speaker_id == "SPK-antonela-latam-agent"
    # raw labels preserved
    assert segs[0].speaker.label == "SPEAKER_00"
    # auditable
    assert t.corrections_applied[-1]["type"] == "speaker_mapping"

    mapping = c.get("/api/speakers/map/aeropuerto_STG_6_run1").json()
    assert mapping["speaker_map"] == {
        "SPEAKER_00": "SPK-passenger-leandro",
        "SPEAKER_01": "SPK-antonela-latam-agent",
    }
    assert mapping["unresolved_labels"] == []
    assert mapping["source"] == "segment.speaker_id"


def test_apply_map_dry_run_writes_nothing(client) -> None:
    c, store, _t = client
    res = c.post("/api/speakers/map", json={
        "transcript_id": "aeropuerto_STG_6_run1",
        "speaker_map": {"SPEAKER_00": "SPK-passenger-leandro"},
        "dry_run": True,
    }).json()
    assert res["saved"] is False
    assert res["applied_count"] == 1
    segs, _ = _seg(store)
    assert segs[0].speaker_id == "", "dry run must not persist"


def test_apply_map_rejects_an_empty_map(client) -> None:
    c, _s, _t = client
    res = c.post("/api/speakers/map", json={
        "transcript_id": "aeropuerto_STG_6_run1", "speaker_map": {}
    })
    assert res.status_code == 400


def test_apply_map_reports_unknown_speaker_ids(client) -> None:
    c, _s, _t = client
    body = c.post("/api/speakers/map", json={
        "transcript_id": "aeropuerto_STG_6_run1",
        "speaker_map": {"SPEAKER_00": "SPK-nope"},
    }).json()
    assert body["unknown_speaker_ids"] == ["SPK-nope"]


def test_map_get_falls_back_to_participant_labels(client) -> None:
    """The pre-existing corpus records mappings on participants, not segments."""
    c, store, _t = client
    t = store.load("aeropuerto_STG_6_run1")
    t.participants = [{"speaker_id": "SPK-passenger-leandro", "segment_labels": ["SPEAKER_00"]}]
    store.save(t)
    body = c.get("/api/speakers/map/aeropuerto_STG_6_run1").json()
    assert body["speaker_map"] == {"SPEAKER_00": "SPK-passenger-leandro"}
    assert body["source"] == "participants"


# --------------------------------------------------------------------------
# consumable artifact
# --------------------------------------------------------------------------
def test_segment_map_rebuild_writes_a_consumable_artifact(client) -> None:
    c, _s, tmp = client
    c.post("/api/speakers/map", json={
        "transcript_id": "aeropuerto_STG_6_run1",
        "speaker_map": {"SPEAKER_01": "SPK-antonela-latam-agent"},
    })
    res = c.post("/api/speakers/segment-map/rebuild").json()
    assert res["speaker_count"] == 1
    assert res["transcript_count"] == 1

    written = Path(res["written"])
    assert written.is_file(), "rebuild must write the artifact"
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["schema_version"]
    assert payload["speakers"]["SPK-antonela-latam-agent"]["segment_count"] == 1
    assert payload["transcripts"]["aeropuerto_STG_6_run1"]["speaker_map"] == {
        "SPEAKER_01": "SPK-antonela-latam-agent"
    }
    # the unmapped label is reported, not dropped
    assert payload["unresolved_segment_labels"]["SPEAKER_00"] == 1

    # and it is served back
    served = c.get("/api/speakers/segment-map").json()
    assert served["schema_version"] == payload["schema_version"]


def test_segment_map_served_on_demand_when_absent(client) -> None:
    c, _s, _t = client
    body = c.get("/api/speakers/segment-map").json()
    assert body["transcript_count"] == 1
    assert body["speaker_count"] == 0, "nothing mapped yet"
    assert body["unresolved_segment_labels"] == {"SPEAKER_00": 1, "SPEAKER_01": 1}


def test_rebuild_writes_the_index_to_the_configured_path(client) -> None:
    """Regression: the refresh must honour SPEAKER_INDEX_FILE.

    An earlier revision shelled out to scripts/generate_speaker_index_v3.py,
    which hardcodes data/speaker_index.json -- so a rebuild wrote into the
    repository no matter what the app was configured with.
    """
    c, _s, tmp = client
    configured = Path(speakers_router.settings.SPEAKER_INDEX_FILE)
    before = configured.read_text(encoding="utf-8")

    c.post("/api/speakers/map", json={
        "transcript_id": "aeropuerto_STG_6_run1",
        "speaker_map": {"SPEAKER_00": "SPK-passenger-leandro"},
    })
    assert c.post("/api/speakers/segment-map/rebuild").status_code == 200

    after = json.loads(configured.read_text(encoding="utf-8"))
    assert after["summary"]["total_transcripts_scanned"] == 1
    assert "SPK-passenger-leandro" in after["mapped_speakers"]
    assert after["summary"]["generated_utc"] != json.loads(before).get("generated_utc")
    # and the repo's own data dir was not involved
    assert str(configured).startswith(str(tmp))
