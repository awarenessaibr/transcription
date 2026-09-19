"""Unit tests for ``TranscriptAuditor``."""
from __future__ import annotations

from src.application.services.transcript_auditor import TranscriptAuditor
from src.domain.entities.anomaly import AnomalyKind
from src.domain.entities.transcript import Segment, Speaker, Transcript

from tests._fakes.fixture_loader import load_reference_as_transcript


def _seg(idx, speaker, start, end, text):
    return Segment(index=idx, speaker=Speaker(label=speaker), start=start, end=end, text=text)


def test_duplicate_ids_detected():
    t = Transcript(transcript_id="t", segments=[
        _seg(0, "A", 0.0, 1.0, "Hola."),
        _seg(1, "B", 1.0, 2.0, "Sí."),
        _seg(1, "A", 2.0, 3.0, "Otra."),
    ])
    audit = TranscriptAuditor().audit(t)
    assert any(a.kind == AnomalyKind.DUPLICATE_IDS for a in audit.anomalies)


def test_mid_word_boundary_detected():
    t = Transcript(transcript_id="t", segments=[
        _seg(0, "A", 0.0, 1.0, "Una de agresión"),
        _seg(1, "A", 1.0, 2.0, " ¿nadie te"),
    ])
    audit = TranscriptAuditor().audit(t)
    assert any(a.kind == AnomalyKind.MID_WORD_BOUNDARY for a in audit.anomalies)


def test_terminal_punct_blocks_mid_word():
    t = Transcript(transcript_id="t", segments=[
        _seg(0, "A", 0.0, 1.0, "Una de agresión."),
        _seg(1, "A", 1.0, 2.0, " ¿nadie te?"),
    ])
    audit = TranscriptAuditor().audit(t)
    assert not any(a.kind == AnomalyKind.MID_WORD_BOUNDARY for a in audit.anomalies)


def test_time_gap_detected():
    t = Transcript(transcript_id="t", segments=[
        _seg(0, "A", 0.0, 5.0, "Uno."),
        _seg(1, "A", 12.0, 13.0, "Dos."),
    ])
    audit = TranscriptAuditor(gap_threshold_s=4.0).audit(t)
    assert sum(1 for a in audit.anomalies if a.kind == AnomalyKind.TIME_GAP) == 1


def test_micro_segment_detected():
    t = Transcript(transcript_id="t", segments=[
        _seg(0, "A", 0.0, 0.3, " ¿Nadie te"),
        _seg(1, "A", 0.3, 5.0, "siguió."),
    ])
    audit = TranscriptAuditor(micro_segment_threshold_s=0.7).audit(t)
    assert any(a.kind == AnomalyKind.MICRO_SEGMENT for a in audit.anomalies)


def test_speaker_label_drift_within_transcript():
    t = Transcript(transcript_id="t", segments=[
        _seg(0, "Joaquin Barraza", 0.0, 1.0, "Sí."),
        _seg(1, "Joaquin Barraza", 1.0, 2.0, "Bueno."),
        _seg(2, "Joaquin Barraa", 2.0, 3.0, "Eh."),
    ])
    audit = TranscriptAuditor().audit(t)
    drifts = [a for a in audit.anomalies if a.kind == AnomalyKind.SPEAKER_LABEL_DRIFT]
    assert len(drifts) == 1
    assert drifts[0].detail_dict()["canonical"] == "Joaquin Barraza"


def test_non_monotonic_detected():
    t = Transcript(transcript_id="t", segments=[
        _seg(0, "A", 5.0, 6.0, "Hola."),
        _seg(1, "A", 1.0, 2.0, "Adiós."),
    ])
    audit = TranscriptAuditor().audit(t)
    assert any(a.kind == AnomalyKind.NON_MONOTONIC_TIMES for a in audit.anomalies)


def test_stg20_fixture_signature():
    t = load_reference_as_transcript("aeropuerto_STG_20.json")
    audit = TranscriptAuditor(gap_threshold_s=4.0).audit(t)
    counts = audit.kind_counts()
    assert counts.get("duplicate_ids", 0) >= 2
    assert counts.get("mid_word_boundary", 0) >= 1
    assert counts.get("time_gap", 0) >= 1


def test_cross_fixture_speaker_drift():
    t1 = load_reference_as_transcript("aeropuerto_STG_20.json")
    t2 = load_reference_as_transcript("aeropuerto_STG_20_segment_1.json")
    drifts = TranscriptAuditor().audit_speaker_corpus([t1, t2])
    assert any("Barraa" in a.detail_dict().get("drift", "") for a in drifts)
