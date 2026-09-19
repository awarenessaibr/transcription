"""Domain entity for a transcription project / event journey.

A Project groups a related set of audio recordings, their reference
transcripts, narratives, and context documents into a single unit so an
agent or pipeline can operate against a coherent body of work (e.g. the
LA8159 LATAM case: 30+ airport audios + reports + narratives).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ContextDocument:
    """A free-form context/report document attached to a project."""

    path: str
    title: str = ""
    kind: str = "report"  # report | narrative | analysis | email | other
    notes: str = ""


@dataclass
class ProjectAudio:
    """One audio entry inside a project."""

    canonical_name: str
    audio_path: str = ""
    title: str = ""
    recording_datetime: str = ""
    notes: str = ""


@dataclass
class Project:
    """A grouped event/case with audios, references, narratives and context docs."""

    id: str
    name: str
    description: str = ""
    language: str = "es"
    location: str = ""
    audios: list[ProjectAudio] = field(default_factory=list)
    narrative_ids: list[str] = field(default_factory=list)
    context_docs: list[ContextDocument] = field(default_factory=list)
    qdrant_filter_tag: str = ""  # e.g. "project:la8159"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def canonical_names(self) -> list[str]:
        return [a.canonical_name for a in self.audios]

    def touch(self) -> None:
        self.updated_at = _now_iso()
