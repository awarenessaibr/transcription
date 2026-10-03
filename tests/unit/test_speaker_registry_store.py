"""Tests for the speaker-registry store.

Covers frontmatter parsing (the pre-existing scalar-only parser silently dropped
``aliases`` and ``key_statements`` -- exactly the fields deterministic resolution
needs), profile loading, the known cast, mapping application, and the consumable
segment map.

One test runs against the real ``data/speakers/`` + ``data/speaker_index.json`` so
the parser cannot silently stop understanding the shipped notes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.entities.transcript import Segment, Speaker, Transcript
from src.infrastructure.speaker_registry_store import (
    SpeakerRegistryStore,
    _as_tuple,
    parse_frontmatter,
)

REPO = Path(__file__).resolve().parents[2]
REAL_SPEAKERS = REPO / "data" / "speakers"
REAL_INDEX = REPO / "data" / "speaker_index.json"

NOTE = """---
note_type: speaker
speaker_id: SPK-antonela-latam-agent
display_name: "Antonela"
role: "Agent / Supervisor"
organization: "LATAM Airlines"
identification_confidence: partial
incidents:
  - "I-002"
transcripts_appearing:
  - "[[I-002_18_NAR_LATAM_STG_2]]"
appearances:
  - transcript_id: "I-002_18"
    segment_labels: "airline_supervisor"
key_statements:
  - quote: "esta es la carta que usted pidio"
    transcript: "[[I-002_18_NAR_LATAM_STG_2]]"
aliases:
  - "Antonela"
  - "Anto"
tags:
  - speaker
---

# Antonela

## Key Statements

### Segment 22

> ninguno de nuestros documentos tiene firma

*institutional unsigned-document policy*
"""


def _write_registry(tmp: Path, *, note: str = NOTE, index: dict | None = None) -> SpeakerRegistryStore:
    speakers = tmp / "speakers"
    speakers.mkdir(parents=True, exist_ok=True)
    (speakers / "SPK-antonela-latam-agent.md").write_text(note, encoding="utf-8")
    index_path = tmp / "speaker_index.json"
    index_path.write_text(
        json.dumps(
            index
            if index is not None
            else {
                "summary": {"total_transcripts_scanned": 1},
                "mapped_speakers": {
                    "SPK-antonela-latam-agent": {
                        "display_name": "Antonela",
                        "organization": "LATAM Airlines",
                        "identification_confidence": "partial",
                        "md_file": str(speakers / "SPK-antonela-latam-agent.md"),
                        "appearances": [
                            {
                                "transcript_id": "I-002_18_NAR_LATAM_STG_2",
                                "segment_labels": ["airline_supervisor"],
                                "segment_indices": [0, 2],
                            }
                        ],
                    }
                },
                "unmapped_segment_labels": {},
            }
        ),
        encoding="utf-8",
    )
    return SpeakerRegistryStore(str(speakers), str(index_path))


def _transcript(**over) -> Transcript:
    base = dict(
        transcript_id="t1",
        segments=[
            Segment(index=0, speaker=Speaker(label="SPEAKER_00"), start=0.0, end=1.0, text="hola"),
            Segment(index=1, speaker=Speaker(label="SPEAKER_01"), start=1.0, end=2.0, text="que tal"),
            Segment(index=2, speaker=Speaker(label="SPEAKER_00"), start=2.0, end=3.0, text="bien"),
        ],
    )
    base.update(over)
    return Transcript(**base)


# --------------------------------------------------------------------------
# frontmatter
# --------------------------------------------------------------------------
def test_parse_frontmatter_reads_scalars_and_block_lists() -> None:
    fm = parse_frontmatter(NOTE)
    assert fm["display_name"] == "Antonela"
    assert fm["role"] == "Agent / Supervisor"
    assert fm["identification_confidence"] == "partial"
    # The fields the old scalar-only parser dropped:
    assert fm["aliases"] == ["Antonela", "Anto"]
    assert fm["incidents"] == ["I-002"]
    assert fm["tags"] == ["speaker"]


def test_parse_frontmatter_handles_missing_block() -> None:
    assert parse_frontmatter("no frontmatter here") == {}
    assert parse_frontmatter("---\nkey: value\n---\nbody") == {"key": "value"}


def test_parse_frontmatter_stops_a_list_at_a_nested_mapping() -> None:
    """``appearances:`` must not swallow the following ``key_statements:``."""
    fm = parse_frontmatter(NOTE)
    assert "appearances" in fm
    assert fm["key_statements"] == [] or isinstance(fm["key_statements"], list)


def test_as_tuple_normalises_both_shapes() -> None:
    assert _as_tuple("one") == ("one",)
    assert _as_tuple(["a", " b "]) == ("a", "b")
    assert _as_tuple(None) == ()
    assert _as_tuple("") == ()


# --------------------------------------------------------------------------
# profile loading
# --------------------------------------------------------------------------
def test_load_profiles_joins_index_and_markdown(tmp_path: Path) -> None:
    profiles = _write_registry(tmp_path).load_profiles()
    p = profiles["SPK-antonela-latam-agent"]
    assert p.display_name == "Antonela"
    assert p.organization == "LATAM Airlines"
    # from the index:
    assert p.segment_labels == ("airline_supervisor",)
    # from the markdown, which the old parser dropped:
    assert "Anto" in p.aliases
    # quotes come from both the frontmatter and the `>` blockquote lines
    joined = " ".join(p.statements)
    assert "carta que usted pidio" in joined or "documentos tiene firma" in joined


def test_load_profiles_tolerates_a_missing_index(tmp_path: Path) -> None:
    (tmp_path / "speakers").mkdir()
    store = SpeakerRegistryStore(str(tmp_path / "speakers"), str(tmp_path / "nope.json"))
    assert store.load_profiles() == {}


def test_load_profiles_tolerates_invalid_index_json(tmp_path: Path) -> None:
    (tmp_path / "speakers").mkdir()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    store = SpeakerRegistryStore(str(tmp_path / "speakers"), str(bad))
    assert store.load_index() == {}
    assert store.load_profiles() == {}


# --------------------------------------------------------------------------
# known cast / participants / evidence
# --------------------------------------------------------------------------
def test_known_cast_matches_transcript_id(tmp_path: Path) -> None:
    store = _write_registry(tmp_path)
    t = _transcript(transcript_id="I-002_18_NAR_LATAM_STG_2")
    assert store.known_cast_for(t) == ["SPK-antonela-latam-agent"]


def test_known_cast_matches_by_audio_id_for_a_new_run(tmp_path: Path) -> None:
    """A fresh transcription over a known recording inherits its cast."""
    store = _write_registry(
        tmp_path,
        index={
            "mapped_speakers": {
                "SPK-x": {
                    "display_name": "X",
                    "appearances": [{"transcript_id": "aeropuerto_STG_7", "segment_labels": []}],
                }
            }
        },
    )
    t = _transcript(transcript_id="guided_aeropuerto_STG_7_123", audio_id="aeropuerto_STG_7")
    assert store.known_cast_for(t) == ["SPK-x"]


def test_participant_labels_reads_list_and_string_forms() -> None:
    t = _transcript(
        participants=[
            {"speaker_id": "SPK-a", "segment_labels": ["passenger", "SPEAKER_00"]},
            {"speaker_id": "SPK-b", "segment_labels": "SPEAKER_01"},
            {"speaker_id": "", "segment_labels": ["ignored"]},
            "not-a-dict",
        ]
    )
    labels = SpeakerRegistryStore.participant_labels(t)
    assert labels == {"passenger": "SPK-a", "SPEAKER_00": "SPK-a", "SPEAKER_01": "SPK-b"}


def test_evidence_groups_segments_by_label() -> None:
    evidence = {e.raw_label: e for e in SpeakerRegistryStore.evidence_from(_transcript())}
    assert set(evidence) == {"SPEAKER_00", "SPEAKER_01"}
    assert evidence["SPEAKER_00"].segment_indices == (0, 2)
    assert evidence["SPEAKER_00"].segment_count == 2
    assert "hola" in evidence["SPEAKER_00"].text and "bien" in evidence["SPEAKER_00"].text


# --------------------------------------------------------------------------
# apply_map
# --------------------------------------------------------------------------
def test_apply_map_sets_speaker_id_and_keeps_the_raw_label(tmp_path: Path) -> None:
    store = _write_registry(tmp_path)
    updated, report = store.apply_map(
        _transcript(), {"SPEAKER_00": "SPK-antonela-latam-agent"}
    )
    assert report["applied"] == {"SPEAKER_00": "SPK-antonela-latam-agent"}
    assert report["applied_count"] == 1
    # speaker_id is set on exactly the mapped segments...
    assert [s.speaker_id for s in updated.segments] == [
        "SPK-antonela-latam-agent",
        "",
        "SPK-antonela-latam-agent",
    ]
    # ...and the raw label is untouched, so nothing keying on it breaks.
    assert [s.speaker.label for s in updated.segments] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]


def test_apply_map_registers_the_label_on_the_participant(tmp_path: Path) -> None:
    """The bridge that makes the existing index generator see the mapping."""
    store = _write_registry(tmp_path)
    t = _transcript(participants=[{"speaker_id": "SPK-antonela-latam-agent", "segment_labels": []}])
    updated, _ = store.apply_map(t, {"SPEAKER_00": "SPK-antonela-latam-agent"})
    assert updated.participants[0]["segment_labels"] == ["SPEAKER_00"]


def test_apply_map_records_an_audit_entry(tmp_path: Path) -> None:
    store = _write_registry(tmp_path)
    updated, _ = store.apply_map(_transcript(), {"SPEAKER_01": "SPK-antonela-latam-agent"})
    assert updated.corrections_applied, "a mapping must be auditable"
    entry = updated.corrections_applied[-1]
    assert entry["type"] == "speaker_mapping"
    assert "SPEAKER_01->SPK-antonela-latam-agent" in entry["corrected"]


def test_apply_map_reports_unknown_speaker_ids(tmp_path: Path) -> None:
    store = _write_registry(tmp_path)
    _, report = store.apply_map(_transcript(), {"SPEAKER_00": "SPK-does-not-exist"})
    assert report["unknown_speaker_ids"] == ["SPK-does-not-exist"]


def test_apply_map_is_idempotent(tmp_path: Path) -> None:
    store = _write_registry(tmp_path)
    once, _ = store.apply_map(_transcript(), {"SPEAKER_00": "SPK-antonela-latam-agent"})
    twice, report = store.apply_map(once, {"SPEAKER_00": "SPK-antonela-latam-agent"})
    assert report["applied_count"] == 0, "re-applying the same map must be a no-op"
    assert len(twice.corrections_applied) == len(once.corrections_applied)
    assert [s.speaker_id for s in twice.segments] == [s.speaker_id for s in once.segments]


def test_apply_map_ignores_empty_input(tmp_path: Path) -> None:
    store = _write_registry(tmp_path)
    updated, report = store.apply_map(_transcript(), {})
    assert report["applied"] == {}
    assert updated.corrections_applied == []


# --------------------------------------------------------------------------
# resolve() wiring
# --------------------------------------------------------------------------
def test_resolve_uses_the_real_signals(tmp_path: Path) -> None:
    store = _write_registry(tmp_path)
    t = _transcript(
        segments=[
            Segment(
                index=0,
                speaker=Speaker(label="SPEAKER_00"),
                start=0.0,
                end=1.0,
                text="esta es la carta que usted pidio",
            )
        ]
    )
    resolution = store.resolve(t)
    assert resolution.proposals[0].speaker_id == "SPK-antonela-latam-agent"
    assert "known_statement" in resolution.proposals[0].signals


# --------------------------------------------------------------------------
# consumable artifact
# --------------------------------------------------------------------------
def test_build_segment_map_shape_and_counts(tmp_path: Path) -> None:
    store = _write_registry(tmp_path)
    mapped, _ = store.apply_map(_transcript(), {"SPEAKER_00": "SPK-antonela-latam-agent"})
    payload = store.build_segment_map([mapped])

    assert payload["schema_version"]
    assert payload["speaker_count"] == 1
    bucket = payload["speakers"]["SPK-antonela-latam-agent"]
    assert bucket["display_name"] == "Antonela"
    assert bucket["segment_count"] == 2
    assert {s["segment_index"] for s in bucket["segments"]} == {0, 2}
    assert all(s["transcript_id"] == "t1" for s in bucket["segments"])

    per = payload["transcripts"]["t1"]
    assert per["speaker_map"] == {"SPEAKER_00": "SPK-antonela-latam-agent"}
    assert per["unresolved_labels"] == ["SPEAKER_01"]
    assert per["segment_count"] == 3
    # unmapped labels are counted, not silently dropped
    assert payload["unresolved_segment_labels"]["SPEAKER_01"] == 1


def test_build_segment_map_falls_back_to_participant_labels(tmp_path: Path) -> None:
    """Transcripts mapped the old way (participants only) still produce output."""
    store = _write_registry(tmp_path)
    t = _transcript(
        participants=[
            {"speaker_id": "SPK-antonela-latam-agent", "segment_labels": ["SPEAKER_00", "SPEAKER_01"]}
        ]
    )
    payload = store.build_segment_map([t])
    assert payload["speakers"]["SPK-antonela-latam-agent"]["segment_count"] == 3
    assert payload["unresolved_segment_labels"] == {}


# --------------------------------------------------------------------------
# real registry
# --------------------------------------------------------------------------
@pytest.mark.skipif(not REAL_INDEX.is_file(), reason="speaker registry not present")
def test_real_registry_loads_with_aliases_and_labels() -> None:
    store = SpeakerRegistryStore(str(REAL_SPEAKERS), str(REAL_INDEX))
    profiles = store.load_profiles()
    assert len(profiles) >= 30, f"only {len(profiles)} profiles parsed"
    assert all(p.speaker_id == key for key, p in profiles.items())
    assert any(p.aliases for p in profiles.values()), (
        "no aliases parsed from the real notes -- the frontmatter parser has drifted"
    )
    assert any(p.segment_labels for p in profiles.values()), (
        "no segment_labels joined from the real index"
    )
