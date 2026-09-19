"""Domain entities for reference-guided transcription."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReferenceSegment:
    """A single segment from a reference transcript."""

    id: str
    speaker: str
    start: float
    end: float
    text: str
    language: str = "es"
    confidence: float = 0.0
    duration: float = 0.0


@dataclass
class ReferenceTranscript:
    """A previously-corrected transcript used as prior knowledge.

    This is the rich format with named speakers, per-segment confidence,
    and metadata — as opposed to the raw Whisper output format.
    """

    audio_id: str
    title: str = ""
    participants: list[str] = field(default_factory=list)
    language: str = "es"
    location: str = ""
    recording_datetime: str = ""
    content: list[ReferenceSegment] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    quality_score: float = 0.0
    source: str = ""

    @property
    def full_text(self) -> str:
        """Concatenated text of all segments."""
        return " ".join(seg.text for seg in self.content if seg.text)

    @property
    def speaker_set(self) -> set[str]:
        """All unique speaker labels in this reference."""
        return {seg.speaker for seg in self.content}


@dataclass
class ManifestVersion:
    """One version entry in the audio manifest."""

    filename: str
    type: str  # "reference", "whisper_raw", "guided"
    source: str  # "manual_correction", "pipeline", "llm_reconciliation"
    quality_score: float | None = None
    segments: int = 0
    created_at: str = ""
    model: str = ""
    notes: str = ""
    reference_used: str = ""


@dataclass
class IncidentNarrative:
    """A first-person narrative account of events during an audio recording.

    These are timestamped chronological narratives written by the passenger,
    providing context about what was happening at each moment in the audio.
    Contains named individuals, exact quotes, and situational context that
    helps the reconciler map speakers and correct transcription errors.
    """

    audio_id: str
    title: str = ""
    timeline_time: str = ""
    text: str = ""
    source_file: str = ""


@dataclass
class AudioManifest:
    """Master index for all transcript versions of one audio file."""

    audio_file: str
    audio_path: str
    canonical_name: str
    participants: list[str] = field(default_factory=list)
    language: str = "es"
    location: str = ""
    versions: list[ManifestVersion] = field(default_factory=list)
    narratives: list[str] = field(default_factory=list)  # narrative filenames

    def best_reference(self) -> ManifestVersion | None:
        """Return the highest-quality reference version."""
        refs = [v for v in self.versions if v.type == "reference"]
        if not refs:
            return None
        return max(refs, key=lambda v: v.quality_score or 0.0)

    def latest_guided(self) -> ManifestVersion | None:
        """Return the most recent guided output."""
        guided = [v for v in self.versions if v.type == "guided"]
        if not guided:
            return None
        return max(guided, key=lambda v: v.created_at)
