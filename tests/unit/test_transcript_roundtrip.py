"""Round-trip tests against the REAL transcript corpus.

These exist because the canonical store silently destroyed data: `Segment` did
not declare `segment_datetime` or `speaker_id`, so every load -> save cycle
dropped them, and 349 wall-clock timestamps were lost before anyone noticed
(see docs/REDUCED_CORE_MANIFEST.md section 6.3).

The tests are deliberately written against ``data/transcripts/*.json`` rather
than a synthetic fixture: the synthetic fixture used elsewhere in this suite
(`tests/fixtures/aeropuerto_STG_20.json`) has a schema that exists in no real
transcript, which is exactly why the loss went undetected.

No test here ever writes into ``data/`` -- each case copies one real file into
``tmp_path`` and round-trips it there.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.domain.entities.transcript import Segment, Speaker, Transcript
from src.domain.transcript_fields import (
    PARTICIPANT_FIELDS,
    SEGMENT_FIELDS,
    TRANSCRIPT_FIELDS,
    validate_transcript,
)
from src.infrastructure.json_store import JSONTranscriptStore

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "data" / "transcripts"

# Fields a segment may carry. Every one of these must survive a round-trip.
# (Named distinctly from the imported SEGMENT_FIELDS schema dict.)
ROUNDTRIP_SEGMENT_FIELDS = (
    "index",
    "speaker",
    "start",
    "end",
    "text",
    "reviewed",
    "correction_note",
    "backchannel_events",
    "segment_datetime",
    "speaker_id",
)

# Fields whose value is recomputed rather than preserved verbatim.
RECOMPUTED = {"duration"}


def _real_transcripts() -> list[Path]:
    if not CORPUS.is_dir():
        return []
    return sorted(p for p in CORPUS.glob("*.json") if p.is_file())


_CORPUS = _real_transcripts()

pytestmark = pytest.mark.skipif(
    not _CORPUS, reason="real transcript corpus not present"
)


def _roundtrip(tmp_path: Path, source: Path):
    """Load a real transcript through the store, save it, return (before, after)."""
    import_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    import_dir.mkdir()
    out_dir.mkdir()
    shutil.copy2(source, import_dir / source.name)

    store = JSONTranscriptStore(str(import_dir))
    transcript = store.load(source.stem)
    assert transcript is not None, f"could not load {source.name}"

    out_store = JSONTranscriptStore(str(out_dir))
    out_path = out_store.save(transcript)

    before = json.loads(source.read_text(encoding="utf-8"))
    after = json.loads(Path(out_path).read_text(encoding="utf-8"))
    return before, after


def _ids() -> list[str]:
    return [p.stem for p in _CORPUS]


@pytest.mark.parametrize("stem", _ids())
def test_no_top_level_key_is_lost(stem: str, tmp_path: Path) -> None:
    """A round-trip must not drop any top-level key the corpus carries."""
    source = CORPUS / f"{stem}.json"
    before, after = _roundtrip(tmp_path, source)
    lost = set(before) - set(after)
    assert not lost, f"{stem}: round-trip lost top-level keys {sorted(lost)}"


@pytest.mark.parametrize("stem", _ids())
def test_segment_count_is_preserved(stem: str, tmp_path: Path) -> None:
    """Segment count must be identical -- no truncation, no duplication."""
    source = CORPUS / f"{stem}.json"
    before, after = _roundtrip(tmp_path, source)
    assert len(after.get("segments", [])) == len(before.get("segments", [])), (
        f"{stem}: segment count changed "
        f"{len(before.get('segments', []))} -> {len(after.get('segments', []))}"
    )


@pytest.mark.parametrize("stem", _ids())
def test_every_present_segment_field_survives(stem: str, tmp_path: Path) -> None:
    """A value that was PRESENT must survive; an absent field may gain its default.

    The distinction matters for a forensic record: normalising an absent
    optional field to its declared default is fine (and makes the schema
    explicit), but replacing a present value with a default is data loss --
    which is precisely what happened to 349 ``segment_datetime`` values.
    """
    source = CORPUS / f"{stem}.json"
    before, after = _roundtrip(tmp_path, source)
    b_segs = before.get("segments", [])
    a_segs = after.get("segments", [])
    assert len(a_segs) == len(b_segs)

    problems: list[str] = []
    for field in ROUNDTRIP_SEGMENT_FIELDS:
        if field in RECOMPUTED:
            continue
        for i, (b, a) in enumerate(zip(b_segs, a_segs, strict=False)):
            if field in b:
                # Present before -> must be identical after.
                if b[field] != a.get(field):
                    problems.append(
                        f"segment {i} field {field!r} changed "
                        f"{b[field]!r} -> {a.get(field)!r}"
                    )
            elif a.get(field) not in (None, "", False):
                # Absent before -> may only gain an empty default, never a value.
                problems.append(
                    f"segment {i} field {field!r} was absent but gained "
                    f"{a.get(field)!r}"
                )
    assert not problems, f"{stem}: " + "; ".join(problems[:5])


@pytest.mark.parametrize("stem", _ids())
def test_no_enrichment_value_is_emptied(stem: str, tmp_path: Path) -> None:
    """Explicit regression guard for the realised loss: no non-empty value becomes empty."""
    source = CORPUS / f"{stem}.json"
    before, after = _roundtrip(tmp_path, source)
    b_segs = before.get("segments", [])
    a_segs = after.get("segments", [])
    assert len(a_segs) == len(b_segs)

    emptied: list[str] = []
    for i, (b, a) in enumerate(zip(b_segs, a_segs, strict=False)):
        for field in ("segment_datetime", "speaker_id", "text", "correction_note", "backchannel_events"):
            if b.get(field) not in (None, "") and a.get(field) in (None, ""):
                emptied.append(f"segment {i} {field}: {b.get(field)!r} -> {a.get(field)!r}")
    assert not emptied, f"{stem}: emptied {emptied[:5]}"


@pytest.mark.parametrize("stem", _ids())
def test_duration_stays_consistent_with_endpoints(stem: str, tmp_path: Path) -> None:
    """``duration`` is recomputed from end-start, so allow rounding only."""
    source = CORPUS / f"{stem}.json"
    before, after = _roundtrip(tmp_path, source)
    for i, (b, a) in enumerate(zip(before.get("segments", []), after.get("segments", []), strict=False)):
        if "duration" not in b:
            continue
        assert a["duration"] == pytest.approx(b["duration"], abs=1e-3), (
            f"{stem}: segment {i} duration drifted {b['duration']} -> {a['duration']}"
        )


def test_corpus_provenance_fields_actually_exist() -> None:
    """Guard against the corpus losing the fields this suite is protecting.

    If enrichment stops writing these, the round-trip tests above would pass
    vacuously, so assert the corpus still carries them somewhere.
    """
    with_datetime = 0
    with_speaker_id = 0
    for path in _CORPUS:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for seg in doc.get("segments", []):
            if "segment_datetime" in seg:
                with_datetime += 1
            if "speaker_id" in seg:
                with_speaker_id += 1
    assert with_datetime > 0, (
        "no segment in the corpus carries segment_datetime -- either the corpus "
        "was damaged or enrichment stopped writing it; the round-trip guard is blind"
    )
    assert with_speaker_id > 0, (
        "no segment in the corpus carries speaker_id -- see above"
    )


def test_legacy_flat_list_file_loads_without_crashing(tmp_path: Path) -> None:
    """The legacy list-format branch used to raise AttributeError.

    It set locals from the list and then called ``raw.get(...)`` for every
    top-level field, so exactly the files it was meant to support crashed.
    """
    legacy = [
        {
            "index": 0,
            "speaker": "passenger",
            "start": 0.0,
            "end": 1.5,
            "text": "hola",
        }
    ]
    d = tmp_path / "legacy"
    d.mkdir()
    (d / "old.json").write_text(json.dumps(legacy), encoding="utf-8")

    transcript = JSONTranscriptStore(str(d)).load("old")
    assert transcript is not None
    assert len(transcript.segments) == 1
    assert transcript.segments[0].text == "hola"


def test_list_ids_strips_only_the_extension(tmp_path: Path) -> None:
    """``f.replace(".json", "")`` mangled names containing '.json' twice."""
    d = tmp_path / "ids"
    d.mkdir()
    (d / "a.json.b.json").write_text("{}", encoding="utf-8")
    (d / "plain.json").write_text("{}", encoding="utf-8")
    ids = JSONTranscriptStore(str(d)).list_ids()
    assert "a.json.b" in ids, ids
    assert "plain" in ids, ids


# ---------------------------------------------------------------------------
# Schema drift guards
#
# These are the *preventive* half of the safety net. The round-trip tests above
# only prove that declared fields survive; these prove that everything the
# corpus actually contains IS declared. Had they existed, both
# `segment_datetime` and segment-level `speaker_id` would have been caught the
# moment an enrichment script started writing them.
# ---------------------------------------------------------------------------
def _corpus_docs() -> list[tuple[str, dict]]:
    out = []
    for path in _CORPUS:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            out.append((path.stem, raw))
    return out


def test_every_corpus_segment_key_is_declared() -> None:
    """Any segment key in the real corpus must exist in SEGMENT_FIELDS."""
    seen: dict[str, list[str]] = {}
    for stem, doc in _corpus_docs():
        for seg in doc.get("segments", []):
            for key in seg:
                seen.setdefault(key, [])
                if len(seen[key]) < 3:
                    seen[key].append(stem)
    undeclared = {k: v for k, v in seen.items() if k not in SEGMENT_FIELDS and k not in RECOMPUTED}
    assert not undeclared, (
        "segment keys present in the corpus but not declared in SEGMENT_FIELDS "
        f"(they will be silently dropped by the store): {undeclared}"
    )


def test_every_corpus_top_level_key_is_declared() -> None:
    """Any top-level key in the real corpus must exist in TRANSCRIPT_FIELDS."""
    seen: dict[str, list[str]] = {}
    for stem, doc in _corpus_docs():
        for key in doc:
            seen.setdefault(key, [])
            if len(seen[key]) < 3:
                seen[key].append(stem)
    undeclared = {k: v for k, v in seen.items() if k not in TRANSCRIPT_FIELDS}
    assert not undeclared, (
        f"top-level keys present in the corpus but not declared in TRANSCRIPT_FIELDS: {undeclared}"
    )


def test_every_corpus_participant_key_is_declared() -> None:
    """Any participant key in the real corpus must exist in PARTICIPANT_FIELDS."""
    seen: dict[str, list[str]] = {}
    for stem, doc in _corpus_docs():
        for part in doc.get("participants", []):
            if not isinstance(part, dict):
                continue
            for key in part:
                seen.setdefault(key, [])
                if len(seen[key]) < 3:
                    seen[key].append(stem)
    undeclared = {k: v for k, v in seen.items() if k not in PARTICIPANT_FIELDS}
    assert not undeclared, (
        f"participant keys present in the corpus but not declared in PARTICIPANT_FIELDS: {undeclared}"
    )


@pytest.mark.parametrize("stem", _ids())
def test_real_corpus_validates_cleanly(stem: str) -> None:
    """Every real transcript must pass the declared schema with no warnings."""
    doc = json.loads((CORPUS / f"{stem}.json").read_text(encoding="utf-8"))
    report = validate_transcript(doc)
    assert report.ok, f"{stem}: schema errors {report.errors[:5]}"
    assert not report.warnings, f"{stem}: schema warnings {report.warnings[:5]}"


def test_validator_rejects_a_segment_missing_required_fields() -> None:
    """The gate must not be vacuous: a malformed segment is an error."""
    report = validate_transcript(
        {"transcript_id": "x", "segments": [{"index": 0, "start": 0.0}]}
    )
    assert not report.ok
    assert any("speaker" in e for e in report.errors), report.errors


def test_store_refuses_to_save_an_invalid_transcript(tmp_path: Path) -> None:
    """save() must raise rather than persist a schema-violating document.

    Dataclasses do not enforce their annotations, so a non-numeric ``index``
    reaches the store intact -- exactly the shape of value an untyped caller or
    a hand-edited payload produces. The gate must reject it.
    """
    store = JSONTranscriptStore(str(tmp_path / "s"))
    bad = Transcript(
        transcript_id="bad",
        segments=[Segment(index="not-an-int", speaker=Speaker(label="x"), start=0.0, end=1.0)],
    )
    with pytest.raises(ValueError, match="refusing to save"):
        store.save(bad)


def test_store_saves_a_valid_transcript(tmp_path: Path) -> None:
    """Control case: a well-formed transcript still saves."""
    store = JSONTranscriptStore(str(tmp_path / "s"))
    good = Transcript(
        transcript_id="good",
        segments=[
            Segment(
                index=0,
                speaker=Speaker(label="passenger"),
                start=0.0,
                end=1.0,
                text="hola",
                segment_datetime="2024-07-05T12:00:00.000",
                speaker_id="SPK-passenger-leandro",
            )
        ],
    )
    path = store.save(good)
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    assert saved["segments"][0]["segment_datetime"] == "2024-07-05T12:00:00.000"
    assert saved["segments"][0]["speaker_id"] == "SPK-passenger-leandro"
