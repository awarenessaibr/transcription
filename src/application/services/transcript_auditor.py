"""Pure structural auditor for ``Transcript`` objects.

Detects structural anomalies (duplicate ids, mid-word boundaries, time gaps,
micro-segments, speaker label drift, non-monotonic times). No I/O, no LLM.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from src.domain.entities.anomaly import Anomaly, AnomalyKind, AuditReport, Severity
from src.domain.entities.transcript import Segment, Transcript

_TERMINAL_PUNCT = ".!?…"
_OPENING_INVERTED = "¿¡"


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _ends_with_terminal(text: str) -> bool:
    s = text.rstrip()
    if not s:
        return False
    return s[-1] in _TERMINAL_PUNCT


def _starts_lowercase_continuation(text: str) -> bool:
    s = text.lstrip()
    if not s:
        return False
    first = s[0]
    if first in _OPENING_INVERTED:
        # Check the first alphabetical char after the inverted punctuation.
        rest = s[1:].lstrip()
        if not rest:
            return False
        return rest[0].islower()
    return first.islower()


class TranscriptAuditor:
    """Detect structural anomalies in a transcript. Pure — no I/O."""

    def __init__(
        self,
        gap_threshold_s: float = 4.0,
        micro_segment_threshold_s: float = 0.7,
        label_min_occurrences: int = 2,
        label_fuzzy_max_distance: int = 2,
    ) -> None:
        self._gap_threshold_s = gap_threshold_s
        self._micro_segment_threshold_s = micro_segment_threshold_s
        self._label_min_occurrences = label_min_occurrences
        self._label_fuzzy_max_distance = label_fuzzy_max_distance

    # ------------------------------------------------------------------ public
    def audit(self, transcript: Transcript) -> AuditReport:
        anomalies: list[Anomaly] = []
        anomalies.extend(self._duplicate_ids(transcript.segments))
        anomalies.extend(self._non_monotonic(transcript.segments))
        anomalies.extend(self._mid_word_boundaries(transcript.segments))
        anomalies.extend(self._time_gaps(transcript.segments))
        anomalies.extend(self._micro_segments(transcript.segments))
        anomalies.extend(self._speaker_label_drift(transcript.segments))

        kind_counts: Counter[str] = Counter(a.kind.value for a in anomalies)
        sev_counts: Counter[str] = Counter(a.severity.value for a in anomalies)

        return AuditReport(
            transcript_id=transcript.transcript_id,
            anomalies=tuple(anomalies),
            counts_by_kind=tuple(sorted(kind_counts.items())),
            counts_by_severity=tuple(sorted(sev_counts.items())),
        )

    def audit_speaker_corpus(
        self, transcripts: list[Transcript]
    ) -> list[Anomaly]:
        """Cross-fixture speaker label drift detection."""
        all_segments: list[Segment] = []
        for t in transcripts:
            all_segments.extend(t.segments)
        return list(self._speaker_label_drift(all_segments))

    # ------------------------------------------------------------------ rules
    def _duplicate_ids(self, segments: list[Segment]) -> list[Anomaly]:
        groups: dict[int, list[Segment]] = defaultdict(list)
        for seg in segments:
            groups[seg.index].append(seg)
        out: list[Anomaly] = []
        for idx, group in groups.items():
            if len(group) < 2:
                continue
            start = min(s.start for s in group)
            end = max(s.end for s in group)
            out.append(
                Anomaly(
                    kind=AnomalyKind.DUPLICATE_IDS,
                    severity=Severity.HIGH,
                    segment_indices=tuple(s.index for s in group),
                    start=start,
                    end=end,
                    hint=f"index {idx} appears {len(group)} times",
                )
            )
        return out

    def _non_monotonic(self, segments: list[Segment]) -> list[Anomaly]:
        out: list[Anomaly] = []
        for i in range(len(segments) - 1):
            a, b = segments[i], segments[i + 1]
            if b.start < a.start:
                out.append(
                    Anomaly(
                        kind=AnomalyKind.NON_MONOTONIC_TIMES,
                        severity=Severity.HIGH,
                        segment_indices=(a.index, b.index),
                        start=min(a.start, b.start),
                        end=max(a.end, b.end),
                        hint=f"start regression: {a.start:.2f} -> {b.start:.2f}",
                    )
                )
        return out

    def _mid_word_boundaries(self, segments: list[Segment]) -> list[Anomaly]:
        out: list[Anomaly] = []
        for i in range(len(segments) - 1):
            a, b = segments[i], segments[i + 1]
            if a.speaker.label != b.speaker.label:
                # Allow fuzzy match — same person, drifted label.
                if (
                    _levenshtein(a.speaker.label, b.speaker.label)
                    > self._label_fuzzy_max_distance
                ):
                    continue
            if _ends_with_terminal(a.text):
                continue
            if not _starts_lowercase_continuation(b.text):
                continue
            out.append(
                Anomaly(
                    kind=AnomalyKind.MID_WORD_BOUNDARY,
                    severity=Severity.HIGH,
                    segment_indices=(a.index, b.index),
                    start=a.start,
                    end=b.end,
                    hint=(
                        f"segment {a.index} ends without terminal punct; "
                        f"segment {b.index} continues lowercase"
                    ),
                )
            )
        return out

    def _time_gaps(self, segments: list[Segment]) -> list[Anomaly]:
        out: list[Anomaly] = []
        for i in range(len(segments) - 1):
            a, b = segments[i], segments[i + 1]
            gap = b.start - a.end
            if gap >= self._gap_threshold_s:
                out.append(
                    Anomaly(
                        kind=AnomalyKind.TIME_GAP,
                        severity=Severity.MEDIUM,
                        segment_indices=(a.index, b.index),
                        start=a.end,
                        end=b.start,
                        hint=f"silence gap of {gap:.2f}s between segments {a.index} and {b.index}",
                    )
                )
        return out

    def _micro_segments(self, segments: list[Segment]) -> list[Anomaly]:
        out: list[Anomaly] = []
        for seg in segments:
            if seg.duration < self._micro_segment_threshold_s and not _ends_with_terminal(seg.text):
                out.append(
                    Anomaly(
                        kind=AnomalyKind.MICRO_SEGMENT,
                        severity=Severity.LOW,
                        segment_indices=(seg.index,),
                        start=seg.start,
                        end=seg.end,
                        hint=f"micro-segment {seg.duration:.2f}s without terminal punct",
                    )
                )
        return out

    def _speaker_label_drift(self, segments: list[Segment]) -> list[Anomaly]:
        if not segments:
            return []
        counts: Counter[str] = Counter(seg.speaker.label for seg in segments)
        rare = [lbl for lbl, c in counts.items() if c < self._label_min_occurrences]
        common = [lbl for lbl, c in counts.items() if c >= self._label_min_occurrences]

        # First-pass: rare-vs-common Levenshtein on full labels.
        used: set[str] = set()
        out: list[Anomaly] = []
        for r in rare:
            best: str | None = None
            best_d = self._label_fuzzy_max_distance + 1
            for c in common:
                d = _levenshtein(r, c)
                if d <= self._label_fuzzy_max_distance and d < best_d:
                    best = c
                    best_d = d
            if best is not None and r not in used:
                used.add(r)
                out.append(self._build_drift_anomaly(segments, r, best))

        # Second-pass: drift between two common labels whose name-prefix
        # (text before " (") is fuzzy-equal — catches "Joaquin Barraa (...)"
        # vs "Joaquin Barraza (...)" where role suffixes differ in prose.
        def _name_prefix(label: str) -> str:
            return label.split(" (", 1)[0].strip()

        for a, b in self._common_label_pairs(common):
            if a in used or b in used:
                continue
            na, nb = _name_prefix(a), _name_prefix(b)
            if na == nb:
                continue
            if _levenshtein(na, nb) > self._label_fuzzy_max_distance:
                continue
            # The lower-count label is treated as the drift form.
            if counts[a] >= counts[b]:
                canonical, drift = a, b
            else:
                canonical, drift = b, a
            used.add(drift)
            out.append(self._build_drift_anomaly(segments, drift, canonical))

        return out

    @staticmethod
    def _common_label_pairs(common: list[str]):
        for i in range(len(common)):
            for j in range(i + 1, len(common)):
                yield common[i], common[j]

    def _build_drift_anomaly(
        self, segments: list[Segment], drift: str, canonical: str
    ) -> Anomaly:
        related = [s for s in segments if s.speaker.label == drift]
        start = min(s.start for s in related)
        end = max(s.end for s in related)
        return Anomaly(
            kind=AnomalyKind.SPEAKER_LABEL_DRIFT,
            severity=Severity.MEDIUM,
            segment_indices=tuple(s.index for s in related),
            start=start,
            end=end,
            hint=f"label '{drift}' is likely a drifted form of '{canonical}'",
            detail=(("canonical", canonical), ("drift", drift)),
        )
