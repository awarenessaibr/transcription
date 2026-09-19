"""Unit tests for ``TranscriptPatcher``."""
from __future__ import annotations

from src.application.services.transcript_patcher import TranscriptPatcher
from src.domain.entities.patch import Patch, PatchOp
from src.domain.entities.transcript import Segment, Speaker, Transcript


def _seg(idx, speaker, start, end, text):
    return Segment(index=idx, speaker=Speaker(label=speaker), start=start, end=end, text=text)


def _t(*segs):
    return Transcript(transcript_id="t", segments=list(segs))


def test_replace_text():
    t = _t(_seg(0, "A", 0, 1, "uno"), _seg(1, "A", 1, 2, "dos"))
    out, _ = TranscriptPatcher().apply(t, [Patch(op=PatchOp.REPLACE_TEXT, segment_indices=(1,), new_text="DOS")])
    assert out.segments[1].text == "DOS"


def test_merge_contiguous():
    t = _t(_seg(0, "A", 0, 1, "una"), _seg(1, "A", 1, 2, "frase"), _seg(2, "A", 2, 3, "completa"))
    out, _ = TranscriptPatcher().apply(t, [Patch(op=PatchOp.MERGE, segment_indices=(0, 1, 2))])
    assert len(out.segments) == 1
    assert out.segments[0].text == "una frase completa"
    assert out.segments[0].start == 0
    assert out.segments[0].end == 3


def test_merge_non_contiguous_skipped():
    t = _t(_seg(0, "A", 0, 1, "x"), _seg(1, "B", 1, 2, "y"), _seg(2, "A", 2, 3, "z"))
    out, applied = TranscriptPatcher().apply(t, [Patch(op=PatchOp.MERGE, segment_indices=(0, 2))])
    assert len(out.segments) == 3
    assert applied[0].note.startswith("skipped")


def test_split():
    t = _t(_seg(0, "A", 0.0, 4.0, "hola amigos buenas tardes"))
    out, _ = TranscriptPatcher().apply(t, [Patch(op=PatchOp.SPLIT, segment_indices=(0,), new_start=2.0)])
    assert len(out.segments) == 2
    assert out.segments[0].end == 2.0
    assert out.segments[1].start == 2.0


def test_relabel():
    t = _t(_seg(0, "A", 0, 1, "x"), _seg(1, "B", 1, 2, "y"))
    out, _ = TranscriptPatcher().apply(t, [Patch(op=PatchOp.RELABEL, segment_indices=(1,), new_speaker="A")])
    assert out.segments[1].speaker.label == "A"


def test_retime():
    t = _t(_seg(0, "A", 0.0, 1.0, "x"))
    out, _ = TranscriptPatcher().apply(t, [Patch(op=PatchOp.RETIME, segment_indices=(0,), new_start=0.5, new_end=2.5)])
    assert out.segments[0].start == 0.5
    assert out.segments[0].end == 2.5


def test_delete():
    t = _t(_seg(0, "A", 0, 1, "x"), _seg(1, "B", 1, 2, "y"))
    out, _ = TranscriptPatcher().apply(t, [Patch(op=PatchOp.DELETE, segment_indices=(0,))])
    assert len(out.segments) == 1
    assert out.segments[0].index == 0


def test_insert():
    t = _t(_seg(0, "A", 0, 1, "x"))
    out, _ = TranscriptPatcher().apply(t, [Patch(
        op=PatchOp.INSERT, insert_after_index=0,
        new_text="new", new_speaker="C", new_start=1.0, new_end=2.0,
    )])
    assert len(out.segments) == 2
    assert out.segments[1].text == "new"


def test_reindex_dedupes_duplicates():
    t = _t(_seg(7, "A", 0, 1, "x"), _seg(7, "A", 1, 2, "y"), _seg(9, "B", 2, 3, "z"))
    out = TranscriptPatcher().reindex(t)
    assert [s.index for s in out.segments] == [0, 1, 2]
