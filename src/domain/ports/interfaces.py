"""Domain ports — abstract interfaces for infrastructure adapters.

These are Protocol classes (structural subtyping). Infrastructure adapters
implement these without inheriting from them. Domain depends on NOTHING external.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.domain.entities.project import Project
from src.domain.entities.reference import AudioManifest, IncidentNarrative, ReferenceTranscript
from src.domain.entities.transcript import DiarizationTurn, Transcript


# ---------------------------------------------------------------------------
# ASR (Automatic Speech Recognition)
# ---------------------------------------------------------------------------
@runtime_checkable
class ASRPort(Protocol):
    """Transcribe an audio file segment into text."""

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        **kwargs,
    ) -> dict: ...


# ---------------------------------------------------------------------------
# Speaker Diarization
# ---------------------------------------------------------------------------
@runtime_checkable
class DiarizationPort(Protocol):
    """Identify speaker turns in an audio file."""

    def diarize(
        self,
        audio_path: str,
        *,
        min_speakers: int = 1,
        max_speakers: int = 2,
        num_speakers: int | None = None,
        vad_threshold: float = 0.25,
    ) -> list[DiarizationTurn]: ...

    def diarize_waveform(
        self,
        waveform,
        sample_rate: int,
        *,
        min_speakers: int = 1,
        max_speakers: int = 2,
        num_speakers: int | None = None,
    ) -> list[DiarizationTurn]: ...


# ---------------------------------------------------------------------------
# Audio Preprocessing
# ---------------------------------------------------------------------------
@runtime_checkable
class AudioProcessorPort(Protocol):
    """Apply audio treatments (noise reduction, gain, silence removal)."""

    def process(self, audio_path: str, params: dict) -> str:
        """Return path to the processed audio file."""
        ...


# ---------------------------------------------------------------------------
# Transcript Persistence
# ---------------------------------------------------------------------------
@runtime_checkable
class TranscriptStorePort(Protocol):
    """Save and retrieve transcripts."""

    def save(self, transcript: Transcript) -> str:
        """Persist and return the storage path."""
        ...

    def load(self, transcript_id: str) -> Transcript | None: ...

    def list_ids(self) -> list[str]: ...


# ---------------------------------------------------------------------------
# Audio File Operations
# ---------------------------------------------------------------------------
@runtime_checkable
class AudioFilePort(Protocol):
    """Save uploaded audio and convert to WAV."""

    async def save_upload(self, filename: str, content: bytes, dest_dir: str) -> str:
        """Save uploaded bytes, return path."""
        ...

    def convert_to_wav(self, audio_path: str) -> str:
        """Convert to WAV if needed, return WAV path."""
        ...

    def crop_audio(self, audio_path: str, start: float, end: float):
        """Return (waveform, sample_rate) for the requested range."""
        ...

    def get_duration(self, audio_path: str) -> float: ...

    def extract_segment(self, audio_path: str, start_ms: int, end_ms: int, out_path: str) -> str: ...


# ---------------------------------------------------------------------------
# Transcript Analysis (LLM-powered)
# ---------------------------------------------------------------------------
@runtime_checkable
class TranscriptAnalyzerPort(Protocol):
    """Analyze a transcript using an LLM."""

    async def analyze(
        self,
        transcript: Transcript,
        *,
        instructions: str = "",
    ) -> dict:
        """Return analysis dict with summary, entities, tokens, cost, etc."""
        ...


# ---------------------------------------------------------------------------
# Transcript Search (Vector / Semantic)
# ---------------------------------------------------------------------------
@runtime_checkable
class TranscriptIndexPort(Protocol):
    """Index and search transcripts semantically."""

    async def index(self, transcript: Transcript) -> int:
        """Index a transcript. Return number of vectors upserted."""
        ...

    async def search(self, query: str, *, limit: int = 5) -> list[dict]:
        """Return matching segments: [{transcript_id, index, speaker, text, score}]."""
        ...

    async def delete(self, transcript_id: str) -> None:
        """Remove all vectors for a transcript."""
        ...


# ---------------------------------------------------------------------------
# Reference Transcript Store
# ---------------------------------------------------------------------------
@runtime_checkable
class ReferenceStorePort(Protocol):
    """Load and manage reference transcripts per audio file."""

    def load_manifest(self, canonical_name: str) -> AudioManifest | None:
        """Load the manifest for an audio file. None if not found."""
        ...

    def save_manifest(self, manifest: AudioManifest) -> str:
        """Persist the manifest. Return the file path."""
        ...

    def load_references(self, canonical_name: str) -> list[ReferenceTranscript]:
        """Load all reference transcripts for an audio, sorted by quality."""
        ...

    def save_guided_output(
        self, canonical_name: str, segments: list[dict], metadata: dict
    ) -> str:
        """Save a guided transcription result. Return the file path."""
        ...

    def list_audio_names(self) -> list[str]:
        """List all canonical audio names that have reference folders."""
        ...


# ---------------------------------------------------------------------------
# Incident Narrative Store
# ---------------------------------------------------------------------------
@runtime_checkable
class NarrativeStorePort(Protocol):
    """Load incident narratives per audio file."""

    def load_narratives(self, canonical_name: str) -> list[IncidentNarrative]:
        """Load all narratives matching an audio file."""
        ...

    def list_all(self) -> list[str]:
        """List all canonical names that have narratives."""
        ...


# ---------------------------------------------------------------------------
# Transcript Reconciliation (LLM-powered)
# ---------------------------------------------------------------------------
@runtime_checkable
class TranscriptReconcilerPort(Protocol):
    """Reconcile raw transcription with reference transcripts using an LLM."""

    async def reconcile(
        self,
        raw_segments: list[dict],
        reference: ReferenceTranscript,
        *,
        narrative: IncidentNarrative | None = None,
        language: str = "es",
        references: list[ReferenceTranscript] | None = None,
    ) -> dict:
        """Return reconciled segments + metadata (tokens, cost, speaker_map).

        ``reference`` is the primary (highest-quality) reference. ``references``
        is an optional ranked list of additional priors; when provided, the
        reconciler should weight earlier entries more heavily but use the full
        set as cross-checks. Implementations remain backward-compatible when
        ``references`` is omitted.
        """
        ...


# ---------------------------------------------------------------------------
# Project Store
# ---------------------------------------------------------------------------
@runtime_checkable
class ProjectStorePort(Protocol):
    """Persist and load Project (event journey) records."""

    def save(self, project: Project) -> str: ...

    def load(self, project_id: str) -> Project | None: ...

    def delete(self, project_id: str) -> bool: ...

    def list_projects(self) -> list[Project]: ...


# ---------------------------------------------------------------------------
# Acoustic Probe (lightweight numerical audio measurements)
# ---------------------------------------------------------------------------
@runtime_checkable
class AcousticProbePort(Protocol):
    """Acoustic measurement and clip extraction.

    Lightweight numerical probes only — no ASR, no diarization. Implementations
    may use torchaudio, soundfile, etc.
    """

    def audio_info(self, path: str) -> dict:
        """Return ``{sample_rate, channels, duration, peak_db, rms_db, clipping_pct}``."""
        ...

    def window_stats(self, path: str, start: float, end: float) -> dict:
        """Return per-window stats.

        Keys: ``duration``, ``rms_db``, ``peak_db``, ``silence_ratio``,
        ``voiced_ratio``, ``snr_estimate``.
        """
        ...

    def extract_window(
        self, src_path: str, start: float, end: float, dst_path: str
    ) -> str:
        """Write ``[start, end]`` of ``src_path`` as 16 kHz mono WAV to ``dst_path``."""
        ...

