"""Regression tests for the review-save pipeline fixes.

Covers:
* ``JSONTranscriptStore.save`` atomicity (F8)
* ``TranscriptPatcher.apply_with_report`` skipped-patch reporting (F4)
* reviewed-flag / index-space ordering used by ``POST /review/save`` (F3)
"""
from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import replace as dc_replace

from src.application.services.transcript_patcher import TranscriptPatcher
from src.domain.entities.patch import Patch, PatchOp
from src.domain.entities.transcript import Segment, Speaker, Transcript
from src.infrastructure.json_store import JSONTranscriptStore


def _seg(i: int, text: str, speaker: str = "A") -> Segment:
    return Segment(
        index=i,
        speaker=Speaker(label=speaker),
        start=float(i),
        end=float(i) + 1.0,
        text=text,
    )


def _transcript(tid: str = "T-1", texts=("A", "B", "C", "D")) -> Transcript:
    return Transcript(
        transcript_id=tid,
        segments=[_seg(i, t) for i, t in enumerate(texts)],
        source_file="sample.wav",
    )


# --------------------------------------------------------------- F8 atomic write
def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    store = JSONTranscriptStore(str(tmp_path))
    transcript = _transcript()

    path = store.save(transcript)

    assert os.path.isfile(path)
    # No stray temp files left behind in the transcript directory.
    assert [p for p in os.listdir(tmp_path) if p.endswith(".tmp")] == []
    # File is always complete, parseable JSON.
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data["segments"]) == 4


def test_save_round_trips_segments_and_review_metadata(tmp_path):
    store = JSONTranscriptStore(str(tmp_path))
    transcript = _transcript()
    transcript = dc_replace(
        transcript,
        segments=[
            dc_replace(s, reviewed=True, correction_note="n", backchannel_events="bc")
            for s in transcript.segments
        ],
    )

    store.save(transcript)
    loaded = store.load("T-1")

    assert [s.reviewed for s in loaded.segments] == [True] * 4
    assert loaded.segments[0].correction_note == "n"
    assert loaded.segments[0].backchannel_events == "bc"


def test_save_overwrites_previous_version_in_place(tmp_path):
    store = JSONTranscriptStore(str(tmp_path))
    store.save(_transcript(texts=("A", "B")))
    store.save(_transcript(texts=("A", "B", "C")))

    loaded = store.load("T-1")
    assert [s.text for s in loaded.segments] == ["A", "B", "C"]
    assert len(os.listdir(tmp_path)) == 1


# ------------------------------------------------- F4 skipped-patch reporting
def test_apply_with_report_reports_skipped_patches():
    patcher = TranscriptPatcher()
    base = _transcript()

    good = Patch(op=PatchOp.REPLACE_TEXT, segment_indices=(1,), new_text="B2")
    bad = Patch(op=PatchOp.REPLACE_TEXT, segment_indices=(99,), new_text="nope")

    patched, applied, skipped = patcher.apply_with_report(base, [good, bad])

    assert len(applied) == 2  # legacy semantics: one entry per requested patch
    assert len(skipped) == 1
    assert skipped[0][0] is bad
    assert skipped[0][1]  # a human-readable reason is present
    assert [s.text for s in patched.segments] == ["A", "B2", "C", "D"]


def test_apply_with_report_skips_delete_on_missing_segment():
    patcher = TranscriptPatcher()
    base = _transcript()

    bad = Patch(op=PatchOp.DELETE, segment_indices=(42,))
    patched, _applied, skipped = patcher.apply_with_report(base, [bad])

    assert len(skipped) == 1
    assert len(patched.segments) == 4  # nothing was removed


def test_apply_legacy_signature_still_returns_two_tuple():
    patcher = TranscriptPatcher()
    base = _transcript()
    good = Patch(op=PatchOp.REPLACE_TEXT, segment_indices=(0,), new_text="Z")

    result = patcher.apply(base, [good])

    assert isinstance(result, tuple) and len(result) == 2
    patched, applied = result
    assert patched.segments[0].text == "Z"
    assert applied == [good]


def test_apply_with_report_clean_run_reports_nothing_skipped():
    patcher = TranscriptPatcher()
    base = _transcript()
    patches = [
        Patch(op=PatchOp.REPLACE_TEXT, segment_indices=(0,), new_text="A2"),
        Patch(op=PatchOp.RELABEL, segment_indices=(2,), new_speaker="B"),
    ]

    _patched, applied, skipped = patcher.apply_with_report(base, patches)

    assert skipped == []
    assert len(applied) == 2


def _insert_after(index: int, text: str = "NEW") -> Patch:
    """A fully-specified INSERT patch (timing fields are mandatory)."""
    base = float(max(index, 0))
    return Patch(
        op=PatchOp.INSERT,
        insert_after_index=index,
        new_text=text,
        new_speaker="A",
        new_start=base + 10.0,
        new_end=base + 11.0,
    )


# --------------------------------------------- F3 index-space ordering on save
def _save_pipeline(
    base: Transcript,
    patches: list[Patch],
    reviewed_indices: list[int],
) -> tuple[Transcript, list[Patch], list[tuple[Patch, str]]]:
    """Mirror of the ordering used by ``POST /review/save``.

    Reviewed flags are applied in the ORIGINAL index space *before* patching,
    because patch ops locate segments by original ``Segment.index``.
    """
    reviewed_set = set(reviewed_indices)
    staged = dc_replace(
        base,
        segments=[dc_replace(s, reviewed=s.index in reviewed_set) for s in base.segments],
    )
    return TranscriptPatcher().apply_with_report(staged, patches)


def test_reviewed_flag_rides_along_with_its_segment_across_insert():
    """An insert before the flagged segment must not move the flag to a new row."""
    base = _transcript()  # segments 0..3 with text A B C D

    patched, _applied, skipped = _save_pipeline(base, [_insert_after(1)], reviewed_indices=[2])
    assert skipped == [], f"insert should have applied, got {skipped}"

    texts = [s.text for s in patched.segments]
    assert texts == ["A", "B", "NEW", "C", "D"]
    # The reviewed flag must still be on the original segment "C" (now position 3),
    # never on the freshly inserted "NEW" row.
    flagged = [s.text for s in patched.segments if s.reviewed]
    assert flagged == ["C"]
    assert patched.segments[2].reviewed is False


def test_reviewed_flag_survives_delete_before_it():
    base = _transcript()
    delete = Patch(op=PatchOp.DELETE, segment_indices=(0,))

    patched, _applied, _skipped = _save_pipeline(base, [delete], reviewed_indices=[3])

    assert [s.text for s in patched.segments] == ["B", "C", "D"]
    flagged = [s.text for s in patched.segments if s.reviewed]
    assert flagged == ["D"]


def test_wrong_ordering_would_flag_the_wrong_segment():
    """Documents the bug F3 fixed: applying reviewed flags post-patch is wrong."""
    base = _transcript()
    insert = _insert_after(1)

    # Correct ordering: flags applied first, in the original index space.
    correct, _a, skipped = _save_pipeline(base, [insert], reviewed_indices=[2])
    assert skipped == []
    assert [s.text for s in correct.segments if s.reviewed] == ["C"]

    # Buggy ordering: patch first, then flag by the same numeric index.
    patched, _applied = TranscriptPatcher().apply(base, [insert])
    assert len(patched.segments) == 5  # insert really happened
    buggy = dc_replace(
        patched,
        segments=[dc_replace(s, reviewed=s.index == 2) for s in patched.segments],
    )
    assert [s.text for s in buggy.segments if s.reviewed] == ["NEW"]


def test_reviewed_flags_and_patches_are_independent_when_no_structural_change():
    base = _transcript()
    patch = Patch(op=PatchOp.REPLACE_TEXT, segment_indices=(1,), new_text="B2")

    patched, _applied, _skipped = _save_pipeline(base, [patch], reviewed_indices=[0, 3])

    assert [s.text for s in patched.segments] == ["A", "B2", "C", "D"]
    assert [s.reviewed for s in patched.segments] == [True, False, False, True]


def test_patched_transcript_is_frozen_dataclass_immutable_copy():
    """The pipeline must never mutate the caller's transcript in place."""
    base = _transcript()
    before = dataclasses.asdict(base)

    _save_pipeline(base, [Patch(op=PatchOp.DELETE, segment_indices=(0,))], reviewed_indices=[0])

    assert dataclasses.asdict(base) == before
