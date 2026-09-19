"""Unit tests for ``ValidateAndRefineTranscriptUseCase``."""
from __future__ import annotations

import asyncio
from dataclasses import replace as dc_replace
from typing import Any

from src.application.services.transcript_auditor import TranscriptAuditor
from src.application.services.transcript_patcher import TranscriptPatcher
from src.application.use_cases.validate_and_refine_transcript import (
    ValidateAndRefineTranscriptUseCase,
)
from src.domain.entities.transcript import DiarizationTurn, Segment, Speaker, Transcript

from tests._fakes.fake_acoustic_probe import FakeAcousticProbe
from tests._fakes.fixture_loader import load_reference_as_transcript


class FakeStore:
    def __init__(self, transcripts):
        self._t = dict(transcripts)
        self.saved: list[Transcript] = []

    def save(self, transcript):
        self._t[transcript.transcript_id] = transcript
        self.saved.append(transcript)
        return f"/fake/{transcript.transcript_id}.json"

    def load(self, tid):
        return self._t.get(tid)

    def list_ids(self):
        return list(self._t.keys())


class FakeRefStore:
    def __init__(self, refs=None):
        self._refs = refs or []

    def load_manifest(self, _n): return None
    def save_manifest(self, _m): return ""
    def load_references(self, _n): return list(self._refs)
    def save_guided_output(self, *_a, **_k): return ""
    def list_audio_names(self): return []


class FakeNarrativeStore:
    def __init__(self, narratives=None):
        self._n = narratives or []
    def load_narratives(self, _n): return list(self._n)
    def list_all(self): return []


class FakeProcessor:
    def __init__(self):
        self.calls = []
    def process(self, p, params):
        self.calls.append((p, params))
        return p


class FakeDiarizer:
    def __init__(self, turns):
        self.turns = turns
    def diarize(self, *_a, **_k): return list(self.turns)
    def diarize_waveform(self, *_a, **_k): return list(self.turns)


class FakeASR:
    def __init__(self, text="transcribed"):
        self._text = text
        self.calls = 0
    def transcribe(self, *_a, **_k):
        self.calls += 1
        return self._text


class FakeAudioFiles:
    async def save_upload(self, *_a, **_k): return ""
    def convert_to_wav(self, p): return p
    def crop_audio(self, *_a, **_k): return (None, 16000)
    def get_duration(self, _p): return 60.0
    def extract_segment(self, *_a, **_k): return ""


def _seg(idx, sp, s, e, t):
    return Segment(index=idx, speaker=Speaker(label=sp), start=s, end=e, text=t)


def _make_uc(transcript, *, probe=None, reconciler=None, refs=None, turns=None):
    store = FakeStore({transcript.transcript_id: transcript})
    return ValidateAndRefineTranscriptUseCase(
        store=store,
        ref_store=FakeRefStore(refs=refs or []),
        narrative_store=FakeNarrativeStore(),
        reconciler=reconciler,
        auditor=TranscriptAuditor(gap_threshold_s=4.0),
        patcher=TranscriptPatcher(),
        processor=FakeProcessor(),
        diarizer=FakeDiarizer(turns or []),
        asr=FakeASR(),
        audio_files=FakeAudioFiles(),
        probe=probe,
    ), store


def _stg20():
    t = load_reference_as_transcript("aeropuerto_STG_20.json", transcript_id="stg20")
    return dc_replace(t, source_file="")


def test_deterministic_only():
    uc, store = _make_uc(_stg20())
    result = asyncio.run(uc.execute("stg20", use_acoustic_probes=False, save_as_new_id=True))
    assert result.audit_after.counts_by_kind.get("duplicate_ids", 0) == 0
    assert any(s.transcript_id == result.transcript_id_out for s in store.saved)


def test_audio_missing():
    probe = FakeAcousticProbe()
    uc, _ = _make_uc(_stg20(), probe=probe)
    result = asyncio.run(uc.execute("stg20", use_acoustic_probes=True))
    assert result.audio_available is False
    assert result.acoustic_probes_run == 0
    assert probe.calls_window_stats == []


def test_save_as_new_id():
    uc, store = _make_uc(_stg20())
    result = asyncio.run(uc.execute("stg20", save_as_new_id=True))
    assert "_refined_" in result.transcript_id_out
    final = store.load(result.transcript_id_out)
    assert final is not None
    assert final.original_transcript_id == "stg20"
    assert store.load("stg20") is not None


def test_max_acoustic_windows_caps_probes(tmp_path):
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"RIFF")
    segs = [_seg(i, "A", float(i * 10), float(i * 10 + 1), f"x{i}") for i in range(20)]
    t = Transcript(transcript_id="many", segments=segs, source_file=str(audio))
    probe = FakeAcousticProbe(
        info={str(audio): {"sample_rate": 16000, "channels": 1, "duration": 200.0,
                            "peak_db": -3.0, "rms_db": -20.0, "clipping_pct": 0.0}},
        windows={str(audio): {"duration": 1.0, "rms_db": -20.0, "peak_db": -3.0,
                              "silence_ratio": 0.1, "voiced_ratio": 0.8, "snr_estimate": 30.0}},
    )
    uc, _ = _make_uc(t, probe=probe)
    result = asyncio.run(uc.execute("many", use_acoustic_probes=True, max_acoustic_windows=3))
    assert result.acoustic_probes_run <= 3
    assert len(probe.calls_window_stats) <= 3


def test_acoustic_silence_drop(tmp_path):
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"RIFF")
    t = Transcript(
        transcript_id="silence",
        segments=[_seg(0, "A", 0.0, 5.0, "Uno."), _seg(1, "A", 12.0, 13.0, "Dos.")],
        source_file=str(audio),
    )
    probe = FakeAcousticProbe(
        info={str(audio): {"sample_rate": 16000, "channels": 1, "duration": 60.0,
                            "peak_db": -3.0, "rms_db": -20.0, "clipping_pct": 0.0}},
        windows={str(audio): {"duration": 7.0, "rms_db": -55.0, "peak_db": -40.0,
                              "silence_ratio": 0.85, "voiced_ratio": 0.0, "snr_estimate": 1.0}},
    )
    uc, _ = _make_uc(t, probe=probe)
    result = asyncio.run(uc.execute("silence", use_acoustic_probes=True))
    assert result.audit_after.counts_by_kind.get("time_gap", 0) == 0


def test_acoustic_low_snr_escalation(tmp_path):
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"RIFF")
    t = Transcript(
        transcript_id="lowsnr",
        segments=[_seg(0, "A", 0.0, 5.0, "Uno"), _seg(1, "A", 5.5, 9.0, " sin terminar")],
        source_file=str(audio),
    )
    probe = FakeAcousticProbe(
        info={str(audio): {"sample_rate": 16000, "channels": 1, "duration": 60.0,
                            "peak_db": -3.0, "rms_db": -20.0, "clipping_pct": 0.0}},
        windows={str(audio): {"duration": 6.0, "rms_db": -25.0, "peak_db": -10.0,
                              "silence_ratio": 0.1, "voiced_ratio": 0.7, "snr_estimate": 3.0}},
    )
    turns = [DiarizationTurn(speaker="SPEAKER_00", start=0.0, end=3.0),
             DiarizationTurn(speaker="SPEAKER_01", start=3.0, end=6.0)]
    # Add a fake extract that returns the dst path so the probe can be reused for clip extraction.
    probe._extracts[str(audio)] = ""  # not strictly used; FakeAcousticProbe returns dst by default
    uc, _ = _make_uc(t, probe=probe, turns=turns)
    result = asyncio.run(uc.execute("lowsnr", use_acoustic_probes=True))
    assert result.acoustic_probes_run >= 1
