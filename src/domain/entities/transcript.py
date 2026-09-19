"""Domain entities — depend on NOTHING external."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Speaker:
    """Identified speaker label from diarization."""
    label: str


@dataclass(frozen=True)
class Segment:
    """A single transcribed audio segment."""

    index: int
    speaker: Speaker
    start: float
    end: float

    text: str = ""
    reviewed: bool = False

    # NEW FIELDS
    correction_note: str = ""
    backchannel_events: str = ""

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


@dataclass(frozen=True)
class DiarizationTurn:
    """A raw diarization turn (before transcription)."""

    speaker: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


@dataclass
class Transcript:
    """Complete transcription result."""

    transcript_id: str
    segments: list[Segment] = field(default_factory=list)

    source_file: str = ""
    source_path: str = ""
    language: str = "es"
    metadata: dict = field(default_factory=dict)
    timestamp: str = ""
    provider: str = ""
    original_transcript_id: str | None = None

    # metadata fields used by frontend
    title: str = ""
    subtitle: str = ""
    recording_datetime: str = ""
    location: str = ""
    audio_id: str = ""
    case_id: str = ""
    narrative_id: str = ""

    chronological_order: int | None = None

    prior_stage: str = ""
    next_stage: str = ""
    classification: str = ""

    participants: list = field(default_factory=list)
    violations_cited: list = field(default_factory=list)
    tags: list = field(default_factory=list)

    forensic_clusters: dict = field(default_factory=dict)
    key_evidentiary_findings: list = field(default_factory=list)
    corrections_applied: list = field(default_factory=list)

    # Set once a human has signed off on this transcript.  Distinct from the
    # segment-level ``Segment.reviewed``, which tracks per-segment review.
    reviewed: bool = False


@dataclass(frozen=True)
class AudioFile:
    """Value object representing an audio file on disk."""

    path: str
    format: str = "wav"

    @property
    def exists(self) -> bool:
        import os
        return os.path.exists(self.path)