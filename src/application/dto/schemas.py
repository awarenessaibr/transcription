"""Application-layer DTOs — Pydantic models for use-case I/O."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PreprocessingParams(BaseModel):
    noise_reduce: bool = True
    reduction_db: int = 25
    voice_enhance: bool = True
    apply_gain: bool = True
    target_lufs: float = -16.0
    remove_silence: bool = True
    silence_thresh: int = -45
    min_silence_len: int = 250


class WhisperDecodingParams(BaseModel):
    beam_size: int = 5
    best_of: int = 5
    whisper_temp: float = 0.0
    temperature_increment_on_fallback: float = 0.2
    compression_ratio_threshold: float = 2.4
    logprob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    condition_on_previous_text: bool = False
    initial_prompt: str | None = None
    length_penalty: float = 1.0
    patience: float | None = None
    suppress_blank: bool = True
    suppress_tokens: str = "-1"
    word_timestamps: bool = False


class TranscribeRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    language: str = "es-CL"
    model_size: str = "large-v3"
    min_speakers: int = 1
    max_speakers: int = 2
    vad_threshold: float = 0.25
    preprocessing: PreprocessingParams = Field(default_factory=PreprocessingParams)
    decoding: WhisperDecodingParams = Field(default_factory=WhisperDecodingParams)
    keep_cache: bool = True


class ExcerptRequest(BaseModel):
    file_path: str = Field(..., description="Server-side file path")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    min_speakers: int = Field(1, description="Minimum expected speakers")
    max_speakers: int = Field(2, description="Maximum expected speakers")
    num_speakers: int | None = Field(None, description="Exact number of speakers")


class SegmentResult(BaseModel):
    index: int
    speaker: str
    start: float
    end: float
    duration: float
    text: str = ""


class TimingResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    save_s: float = 0.0
    convert_s: float = 0.0
    preprocess_s: float = 0.0
    diarization_s: float = 0.0
    model_load_s: float = 0.0
    transcription_s: float = 0.0
    total_s: float = 0.0


class TranscribeResult(BaseModel):
    transcript_id: str
    segments: list[SegmentResult]
    timings: TimingResult
    params: dict


class ExcerptResult(BaseModel):
    start: float
    end: float
    segments: list[SegmentResult]


# ── AI-Native (Phase 2) ─────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    transcript_id: str = Field(..., description="ID of transcript to analyze")
    instructions: str = Field("", description="Additional analysis instructions")


class AnalyzeResult(BaseModel):
    transcript_id: str
    analysis: dict
    meta: dict = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str = Field(..., description="Semantic search query", min_length=1)
    limit: int = Field(5, description="Max results", ge=1, le=50)


class SearchHit(BaseModel):
    transcript_id: str
    segment_index: int
    speaker: str
    start: float
    end: float
    text: str
    source_file: str = ""
    score: float


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit]


# ── Validate-and-refine ─────────────────────────────────────────────────


class AnomalyDTO(BaseModel):
    kind: str
    severity: str
    segment_indices: list[int]
    start: float
    end: float
    hint: str
    detail: dict[str, str] = Field(default_factory=dict)


class AuditReportDTO(BaseModel):
    transcript_id: str
    anomalies: list[AnomalyDTO]
    counts_by_kind: dict[str, int] = Field(default_factory=dict)
    counts_by_severity: dict[str, int] = Field(default_factory=dict)


class PatchDTO(BaseModel):
    op: str
    segment_indices: list[int] = Field(default_factory=list)
    new_text: str | None = None
    new_speaker: str | None = None
    new_start: float | None = None
    new_end: float | None = None
    insert_after_index: int | None = None
    note: str = ""


class ValidateAndRefineResult(BaseModel):
    transcript_id_in: str
    transcript_id_out: str
    audit_before: AuditReportDTO
    audit_after: AuditReportDTO
    patches_applied: list[PatchDTO] = Field(default_factory=list)
    acoustic_probes_run: int = 0
    reconciler_calls: int = 0
    audio_available: bool = True
    notes: list[str] = Field(default_factory=list)
