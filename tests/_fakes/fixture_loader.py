"""Helpers for loading reference-format fixtures into ``Transcript`` objects."""
from __future__ import annotations

import json
from pathlib import Path

from src.domain.entities.transcript import Segment, Speaker, Transcript

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_reference_as_transcript(filename: str, transcript_id: str | None = None) -> Transcript:
    """Load a reference-format JSON file and convert to a ``Transcript``.

    The reference format uses ``content`` with string ids; we map ``id``→int
    while preserving duplicates so the auditor can detect them.
    """
    path = FIXTURE_DIR / filename
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("content") or raw.get("segments") or []
    segments: list[Segment] = []
    for pos, item in enumerate(items):
        try:
            idx = int(str(item.get("id", pos)))
        except (TypeError, ValueError):
            idx = pos
        segments.append(
            Segment(
                index=idx,
                speaker=Speaker(label=str(item.get("speaker", "unknown"))),
                start=float(item.get("start", 0.0)),
                end=float(item.get("end", 0.0)),
                text=str(item.get("text", "")),
            )
        )
    return Transcript(
        transcript_id=transcript_id or raw.get("audio_id") or path.stem,
        segments=segments,
        source_file=str(raw.get("audio_path", "")),
        language=str(raw.get("language", "es")),
        metadata={"location": raw.get("location", "")},
    )
