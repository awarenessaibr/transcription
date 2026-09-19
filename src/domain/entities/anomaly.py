"""Audit anomaly entities — pure domain, no I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AnomalyKind(str, Enum):
    DUPLICATE_IDS = "duplicate_ids"
    MID_WORD_BOUNDARY = "mid_word_boundary"
    TIME_GAP = "time_gap"
    MICRO_SEGMENT = "micro_segment"
    SPEAKER_LABEL_DRIFT = "speaker_label_drift"
    NON_MONOTONIC_TIMES = "non_monotonic_times"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class Anomaly:
    """A structural anomaly found by ``TranscriptAuditor``.

    ``segment_indices`` refers to the position-based ``Segment.index`` field.
    ``detail`` is a small free-form dict with kind-specific data.
    """

    kind: AnomalyKind
    severity: Severity
    segment_indices: tuple[int, ...]
    start: float
    end: float
    hint: str
    detail: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def detail_dict(self) -> dict[str, str]:
        return dict(self.detail)


@dataclass(frozen=True)
class AuditReport:
    """Result of a structural audit over a single transcript."""

    transcript_id: str
    anomalies: tuple[Anomaly, ...]
    counts_by_kind: tuple[tuple[str, int], ...]
    counts_by_severity: tuple[tuple[str, int], ...]

    def kind_counts(self) -> dict[str, int]:
        return dict(self.counts_by_kind)

    def severity_counts(self) -> dict[str, int]:
        return dict(self.counts_by_severity)
