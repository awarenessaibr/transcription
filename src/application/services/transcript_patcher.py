"""Pure transcript patcher: applies ``Patch`` ops, validates, reindexes."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace as dc_replace

from src.domain.entities.patch import Patch, PatchOp
from src.domain.entities.transcript import Segment, Speaker, Transcript


class TranscriptPatcher:
    """Apply a sequence of patches to a transcript, in order, then reindex."""

    def reindex(self, transcript: Transcript) -> Transcript:
        """Renumber segments by position. Resolves duplicate-index anomalies."""
        reindexed = [dc_replace(seg, index=i) for i, seg in enumerate(transcript.segments)]
        return dc_replace(transcript, segments=reindexed)

    def apply(
        self, transcript: Transcript, patches: Sequence[Patch]
    ) -> tuple[Transcript, list[Patch]]:
        new_transcript, applied, _skipped = self.apply_with_report(transcript, patches)
        return new_transcript, applied

    def apply_with_report(
        self, transcript: Transcript, patches: Sequence[Patch]
    ) -> tuple[Transcript, list[Patch], list[tuple[Patch, str]]]:
        """Apply patches and also report the ones that were skipped and why.

        ``applied`` keeps the legacy semantics: it lists every patch in request
        order, with failed ones annotated in their ``note`` field. ``skipped``
        is the new structured view ``[(patch, reason), ...]`` so callers can
        surface a partial-failure warning instead of silently dropping edits.
        """
        segments: list[Segment] = list(transcript.segments)
        applied: list[Patch] = []
        skipped: list[tuple[Patch, str]] = []
        for patch in patches:
            try:
                segments = self._apply_one(segments, patch)
            except _PatchError as exc:
                skipped.append((patch, str(exc)))
                applied.append(self._note(patch, f"skipped: {exc}"))
                continue
            applied.append(patch)
        # Reindex by position.
        reindexed = [dc_replace(seg, index=i) for i, seg in enumerate(segments)]
        new_transcript = dc_replace(transcript, segments=reindexed)
        return new_transcript, applied, skipped

    # ------------------------------------------------------------------ ops
    def _apply_one(self, segments: list[Segment], patch: Patch) -> list[Segment]:
        if patch.op == PatchOp.REPLACE_TEXT:
            return self._replace_text(segments, patch)
        if patch.op == PatchOp.MERGE:
            return self._merge(segments, patch)
        if patch.op == PatchOp.SPLIT:
            return self._split(segments, patch)
        if patch.op == PatchOp.RELABEL:
            return self._relabel(segments, patch)
        if patch.op == PatchOp.RETIME:
            return self._retime(segments, patch)
        if patch.op == PatchOp.DELETE:
            return self._delete(segments, patch)
        if patch.op == PatchOp.INSERT:
            return self._insert(segments, patch)
        raise _PatchError(f"unknown op: {patch.op}")

    def _replace_text(self, segments: list[Segment], patch: Patch) -> list[Segment]:
        if len(patch.segment_indices) != 1:
            raise _PatchError("REPLACE_TEXT requires exactly one segment_index")
        if patch.new_text is None:
            raise _PatchError("REPLACE_TEXT requires new_text")
        idx = patch.segment_indices[0]
        pos = self._locate(segments, idx)
        segments[pos] = dc_replace(segments[pos], text=patch.new_text)
        return segments

    def _merge(self, segments: list[Segment], patch: Patch) -> list[Segment]:
        if len(patch.segment_indices) < 2:
            raise _PatchError("MERGE requires >= 2 segment_indices")
        positions = sorted(self._locate(segments, i) for i in patch.segment_indices)
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise _PatchError("MERGE requires contiguous segments")
        targets = [segments[p] for p in positions]
        merged_text = " ".join(s.text.strip() for s in targets if s.text.strip())
        speaker_label = patch.new_speaker or targets[0].speaker.label
        merged = dc_replace(
            targets[0],
            speaker=Speaker(label=speaker_label),
            start=min(s.start for s in targets),
            end=max(s.end for s in targets),
            text=merged_text,
        )
        return segments[: positions[0]] + [merged] + segments[positions[-1] + 1 :]

    def _split(self, segments: list[Segment], patch: Patch) -> list[Segment]:
        if len(patch.segment_indices) != 1:
            raise _PatchError("SPLIT requires exactly one segment_index")
        if patch.new_start is None:
            raise _PatchError("SPLIT requires new_start (split point)")
        idx = patch.segment_indices[0]
        pos = self._locate(segments, idx)
        target = segments[pos]
        if not (target.start < patch.new_start < target.end):
            raise _PatchError("SPLIT new_start must lie strictly inside segment")
        # Heuristic word-boundary split.
        text = target.text
        frac = (patch.new_start - target.start) / (target.end - target.start)
        cut = self._word_split_index(text, frac)
        first_text = text[:cut].rstrip()
        second_text = patch.new_text if patch.new_text is not None else text[cut:].lstrip()
        first = dc_replace(target, end=patch.new_start, text=first_text)
        second = Segment(
            index=target.index,
            speaker=target.speaker,
            start=patch.new_start,
            end=target.end,
            text=second_text,
        )
        return segments[:pos] + [first, second] + segments[pos + 1 :]

    def _relabel(self, segments: list[Segment], patch: Patch) -> list[Segment]:
        if not patch.segment_indices:
            raise _PatchError("RELABEL requires >= 1 segment_index")
        if not patch.new_speaker:
            raise _PatchError("RELABEL requires new_speaker")
        targets = {self._locate(segments, i) for i in patch.segment_indices}
        speaker = Speaker(label=patch.new_speaker)
        return [
            dc_replace(seg, speaker=speaker) if i in targets else seg
            for i, seg in enumerate(segments)
        ]

    def _retime(self, segments: list[Segment], patch: Patch) -> list[Segment]:
        if len(patch.segment_indices) != 1:
            raise _PatchError("RETIME requires exactly one segment_index")
        if patch.new_start is None and patch.new_end is None:
            raise _PatchError("RETIME requires new_start and/or new_end")
        idx = patch.segment_indices[0]
        pos = self._locate(segments, idx)
        seg = segments[pos]
        new_start = patch.new_start if patch.new_start is not None else seg.start
        new_end = patch.new_end if patch.new_end is not None else seg.end
        if new_start >= new_end:
            raise _PatchError("RETIME requires new_start < new_end")
        segments[pos] = dc_replace(seg, start=new_start, end=new_end)
        return segments

    def _delete(self, segments: list[Segment], patch: Patch) -> list[Segment]:
        if not patch.segment_indices:
            raise _PatchError("DELETE requires >= 1 segment_index")
        targets = {self._locate(segments, i) for i in patch.segment_indices}
        return [seg for i, seg in enumerate(segments) if i not in targets]

    def _insert(self, segments: list[Segment], patch: Patch) -> list[Segment]:
        if patch.insert_after_index is None:
            raise _PatchError("INSERT requires insert_after_index (-1 for start)")
        if (
            patch.new_text is None
            or patch.new_speaker is None
            or patch.new_start is None
            or patch.new_end is None
        ):
            raise _PatchError("INSERT requires new_text, new_speaker, new_start, new_end")
        if patch.new_start >= patch.new_end:
            raise _PatchError("INSERT requires new_start < new_end")
        new_seg = Segment(
            index=-1,  # reindexed at the end
            speaker=Speaker(label=patch.new_speaker),
            start=patch.new_start,
            end=patch.new_end,
            text=patch.new_text,
        )
        if patch.insert_after_index == -1:
            return [new_seg] + segments
        pos = self._locate(segments, patch.insert_after_index)
        return segments[: pos + 1] + [new_seg] + segments[pos + 1 :]

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _locate(segments: list[Segment], target_index: int) -> int:
        for pos, seg in enumerate(segments):
            if seg.index == target_index:
                return pos
        raise _PatchError(f"segment index {target_index} not found")

    @staticmethod
    def _word_split_index(text: str, frac: float) -> int:
        if not text:
            return 0
        frac = max(0.0, min(1.0, frac))
        approx = int(len(text) * frac)
        # Snap to nearest whitespace.
        left = text.rfind(" ", 0, approx)
        right = text.find(" ", approx)
        if left == -1 and right == -1:
            return approx
        if left == -1:
            return right
        if right == -1:
            return left
        return left if (approx - left) <= (right - approx) else right

    @staticmethod
    def _note(patch: Patch, note: str) -> Patch:
        return Patch(
            op=patch.op,
            segment_indices=patch.segment_indices,
            new_text=patch.new_text,
            new_speaker=patch.new_speaker,
            new_start=patch.new_start,
            new_end=patch.new_end,
            insert_after_index=patch.insert_after_index,
            note=note,
        )


class _PatchError(ValueError):
    pass
