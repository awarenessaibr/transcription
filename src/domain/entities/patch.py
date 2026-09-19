"""Patch entities for transcript refinement — pure domain."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PatchOp(str, Enum):
    REPLACE_TEXT = "replace_text"
    MERGE = "merge"
    SPLIT = "split"
    RELABEL = "relabel"
    RETIME = "retime"
    DELETE = "delete"
    INSERT = "insert"


@dataclass(frozen=True)
class Patch:
    """A single transcript edit operation.

    ``segment_indices`` references the ``Segment.index`` field of the input
    transcript (NOT positions after prior patches).
    """

    op: PatchOp
    segment_indices: tuple[int, ...] = ()
    new_text: str | None = None
    new_speaker: str | None = None
    new_start: float | None = None
    new_end: float | None = None
    insert_after_index: int | None = None
    note: str = ""
