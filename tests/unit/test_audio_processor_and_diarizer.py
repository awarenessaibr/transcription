"""Regression tests for speaker-count bounds and the legacy audio processor.

Two defects are pinned here:

1. ``PyAnnoteDiarizerAdapter.diarize`` used to assign ``pipeline.min_speakers`` /
   ``pipeline.max_speakers`` as *instance attributes*.  pyannote's
   ``SpeakerDiarization.apply()`` reads only its own kwargs, so the Min/Max Speakers controls
   in the Pinocchio UI had no effect and diarization always ran with min=1, max=inf.
2. ``PydubProcessorAdapter`` divided ``reduction_db`` by 40 without clamping (negative values
   amplified noise), cast NaN from ``noisereduce`` to int16, used a boost-only "LUFS" gain with
   no headroom, and hard-coded a 300-3400 Hz telephone band-pass for "voice enhance".
"""
from __future__ import annotations

import numpy as np
import pytest
from pydub import AudioSegment

from src.infrastructure.pyannote_adapter import PyAnnoteDiarizerAdapter
from src.infrastructure.pydub_processor import (
    DEFAULT_VOICE_HIGHPASS_HZ as DEFAULT_HIGHPASS,
)
from src.infrastructure.pydub_processor import (
    DEFAULT_VOICE_LOWPASS_HZ as DEFAULT_LOWPASS,
)
from src.infrastructure.pydub_processor import PydubProcessorAdapter

SR = 16000


# --------------------------------------------------------------------------- fakes


class _FakeTurn:
    def __init__(self, start: float, end: float):
        self.start = start
        self.end = end


class _FakeAnnotation:
    """Minimal stand-in for a pyannote Annotation."""

    def __init__(self, turns):
        self._turns = turns

    def itertracks(self, yield_label: bool = False):
        for index, (start, end) in enumerate(self._turns):
            yield _FakeTurn(start, end), None, f"SPEAKER_{index:02d}"


class _FakePipeline:
    """Records how it was called; mimics pyannote >= 4's DiarizeOutput wrapper."""

    def __init__(self):
        self.calls: list[dict] = []
        self.instance_attrs: list[str] = []
        self.segmentation = type("Seg", (), {"threshold": 0.5})()

    def __call__(self, *_args, **kwargs):
        self.calls.append(kwargs)
        return type("Diari", (), {"exclusive_speaker_diarization": _FakeAnnotation([(0.0, 1.0)])})()

    def __setattr__(self, name, value):
        if name in {"instance_attrs", "calls", "segmentation"}:
            object.__setattr__(self, name, value)
        else:
            # pyannote's Pipeline.__setattr__ parks unknown names on the instance; they are
            # never read by apply().  Record the attempt so the test can assert we don't do it.
            self.instance_attrs.append(name)
            object.__setattr__(self, name, value)


class _FakeModelManager:
    def __init__(self, pipeline):
        self._pipeline = pipeline

    def get_diarization_pipeline(self, _token=None):
        return self._pipeline


# --------------------------------------------------------------------------- adapter


class TestSpeakerBoundsAreForwarded:
    def _adapter(self):
        pipeline = _FakePipeline()
        return PyAnnoteDiarizerAdapter(_FakeModelManager(pipeline)), pipeline

    def test_min_and_max_are_passed_as_call_kwargs(self):
        adapter, pipeline = self._adapter()
        adapter.diarize("audio.wav", min_speakers=2, max_speakers=5)
        assert pipeline.calls == [{"min_speakers": 2, "max_speakers": 5}]

    def test_bounds_are_not_set_as_instance_attributes(self):
        adapter, pipeline = self._adapter()
        adapter.diarize("audio.wav", min_speakers=2, max_speakers=5)
        assert "min_speakers" not in pipeline.instance_attrs
        assert "max_speakers" not in pipeline.instance_attrs

    def test_vad_threshold_is_not_written_to_the_segmentation_model(self):
        """The powerset segmentation model ignores it; pretending otherwise was misleading."""
        adapter, pipeline = self._adapter()
        adapter.diarize("audio.wav", vad_threshold=0.9)
        assert pipeline.segmentation.threshold == 0.5

    def test_num_speakers_wins_over_bounds(self):
        adapter, pipeline = self._adapter()
        adapter.diarize("audio.wav", min_speakers=1, max_speakers=6, num_speakers=3)
        assert pipeline.calls == [{"num_speakers": 3}]

    def test_inverted_bounds_are_normalised(self):
        adapter, pipeline = self._adapter()
        adapter.diarize("audio.wav", min_speakers=5, max_speakers=2)
        assert pipeline.calls == [{"min_speakers": 2, "max_speakers": 5}]

    def test_zero_and_negative_bounds_are_clamped(self):
        adapter, pipeline = self._adapter()
        adapter.diarize("audio.wav", min_speakers=0, max_speakers=0)
        assert pipeline.calls == [{"min_speakers": 1, "max_speakers": 1}]

    def test_returns_turns(self):
        adapter, _ = self._adapter()
        turns = adapter.diarize("audio.wav")
        assert len(turns) == 1
        assert turns[0].speaker == "SPEAKER_00"

    def test_waveform_path_uses_the_same_helper(self):
        adapter, pipeline = self._adapter()
        adapter.diarize_waveform(np.zeros((1, 16000), dtype=np.float32), SR, min_speakers=2, max_speakers=4)
        assert pipeline.calls == [{"min_speakers": 2, "max_speakers": 4}]

    def test_unavailable_pipeline_raises(self):
        adapter = PyAnnoteDiarizerAdapter(_FakeModelManager(None))
        with pytest.raises(RuntimeError, match="not available"):
            adapter.diarize("audio.wav")


# --------------------------------------------------------------------------- processor


def _segment(seconds: float = 1.0, sr: int = SR, amp: int = 6000, freq: float = 300.0) -> AudioSegment:
    t = np.arange(int(sr * seconds)) / sr  # seconds, not sample index
    samples = (amp * np.sin(2 * np.pi * freq * t)).astype(np.int16)
    return AudioSegment(data=samples.tobytes(), sample_width=2, frame_rate=sr, channels=1)


class TestProcessorSafety:
    def test_negative_reduction_does_not_amplify(self):
        """reduction_db is a 0-40 strength fraction; negatives used to push the mask above 1."""
        audio = _segment(1.0, amp=3000)
        baseline = PydubProcessorAdapter._enhance(
            audio, {"noise_reduce": True, "reduction_db": 0}
        )
        hostile = PydubProcessorAdapter._enhance(
            audio, {"noise_reduce": True, "reduction_db": -100}
        )
        assert hostile.dBFS <= baseline.dBFS + 0.5, "a negative strength must not boost the signal"

    def test_extreme_reduction_stays_bounded(self):
        audio = _segment(0.5, amp=3000)
        for value in (-1000, -1, 0, 40, 41, 1000, "junk"):
            out = PydubProcessorAdapter._enhance(audio, {"noise_reduce": True, "reduction_db": value})
            assert out.dBFS != float("nan")

    def test_digital_silence_survives_noise_reduction(self):
        silence = AudioSegment(
            data=np.zeros(SR, dtype=np.int16).tobytes(),
            sample_width=2,
            frame_rate=SR,
            channels=1,
        )
        out = PydubProcessorAdapter._enhance(silence, {"noise_reduce": True, "reduction_db": 25})
        samples = np.array(out.get_array_of_samples())
        assert not np.isnan(samples.astype(np.float64)).any()
        assert np.abs(samples).max() == 0


class TestProcessorGain:
    def test_quiet_audio_is_boosted(self):
        quiet = _segment(1.0, amp=100)
        out = PydubProcessorAdapter._normalize_loudness(quiet, target_lufs=-16.0)
        assert out.dBFS > quiet.dBFS + 6.0

    def test_hot_audio_is_attenuated(self):
        """The legacy gain was boost-only, so a hot recording was never brought down."""
        hot = _segment(1.0, amp=30000)
        out = PydubProcessorAdapter._normalize_loudness(hot, target_lufs=-30.0)
        assert out.dBFS < hot.dBFS - 3.0

    def test_boost_only_mode_preserves_legacy_behaviour(self):
        hot = _segment(1.0, amp=30000)
        out = PydubProcessorAdapter._normalize_loudness(
            hot, target_lufs=-30.0, allow_attenuation=False
        )
        assert abs(out.dBFS - hot.dBFS) < 0.1

    def test_boost_never_clips(self):
        quiet = _segment(1.0, amp=400)
        out = PydubProcessorAdapter._normalize_loudness(quiet, target_lufs=0.0)
        assert out.max_dBFS <= -0.9, "the peak ceiling must reserve headroom"

    def test_silence_is_left_alone(self):
        silence = AudioSegment(
            data=np.zeros(SR, dtype=np.int16).tobytes(),
            sample_width=2,
            frame_rate=SR,
            channels=1,
        )
        out = PydubProcessorAdapter._normalize_loudness(silence, target_lufs=-16.0)
        assert out.dBFS == float("-inf")


class TestProcessorBandPass:
    def test_defaults_are_speech_safe(self):
        """The legacy 300-3400 Hz default tilted the 3.4-8 kHz fricative band down by 6-8 dB."""
        assert PydubProcessorAdapter._clamp_hz(None, DEFAULT_HIGHPASS, 20, 2000) == DEFAULT_HIGHPASS
        assert PydubProcessorAdapter._clamp_hz(None, DEFAULT_LOWPASS, 1000, 20000) == DEFAULT_LOWPASS
        assert DEFAULT_HIGHPASS == 60.0
        assert DEFAULT_LOWPASS == 8000.0

    def test_legacy_band_can_still_be_requested(self):
        assert PydubProcessorAdapter._clamp_hz(300, DEFAULT_HIGHPASS, 20, 2000) == 300
        assert PydubProcessorAdapter._clamp_hz(3400, DEFAULT_LOWPASS, 1000, 20000) == 3400

    def test_explicit_edges_are_honoured(self):
        assert PydubProcessorAdapter._clamp_hz(80, DEFAULT_HIGHPASS, 20, 2000) == 80
        assert PydubProcessorAdapter._clamp_hz(7000, DEFAULT_LOWPASS, 1000, 20000) == 7000

    def test_edges_are_clamped_to_sane_ranges(self):
        assert PydubProcessorAdapter._clamp_hz(-5, DEFAULT_HIGHPASS, 20, 2000) == 20
        assert PydubProcessorAdapter._clamp_hz(99999, DEFAULT_LOWPASS, 1000, 20000) == 20000

    def test_non_numeric_edges_fall_back_to_default(self):
        assert PydubProcessorAdapter._clamp_hz("junk", DEFAULT_HIGHPASS, 20, 2000) == DEFAULT_HIGHPASS
        assert PydubProcessorAdapter._clamp_hz(float("nan"), DEFAULT_LOWPASS, 1000, 20000) == DEFAULT_LOWPASS

    def test_reduction_strength_is_clamped_and_junk_tolerant(self):
        clamp = PydubProcessorAdapter._clamp_strength
        assert clamp(25) == 25.0
        assert clamp(-100) == 0.0
        assert clamp(999) == 40.0
        assert clamp("junk") == 25.0
        assert clamp(None) == 25.0
        assert clamp(float("nan")) == 25.0

    def test_speech_safe_band_preserves_high_frequencies_better(self):
        """pydub's filters are single-pole RC, so expect a tilt difference, not a brick wall.

        The 4:1 compressor inside ``voice_enhance`` also flattens level differences, which is
        why the threshold here is modest rather than the raw filter response.
        """
        high = _segment(0.5, amp=12000, freq=7500.0)
        legacy = PydubProcessorAdapter._enhance(
            high, {"voice_enhance": True, "enhance_highpass_hz": 300, "enhance_lowpass_hz": 3400}
        )
        safe = PydubProcessorAdapter._enhance(
            high, {"voice_enhance": True, "enhance_highpass_hz": 60, "enhance_lowpass_hz": 8000}
        )
        assert safe.dBFS > legacy.dBFS + 1.0

    def test_inverted_band_falls_back_to_speech_safe(self):
        tone = _segment(0.3, amp=8000)
        out = PydubProcessorAdapter._enhance(
            tone, {"voice_enhance": True, "enhance_highpass_hz": 9000, "enhance_lowpass_hz": 100}
        )
        assert out.dBFS != float("nan")
        assert out.dBFS > -40.0


class TestProcessorPipeline:
    def test_process_writes_a_wav(self, tmp_path):
        import wave

        source = tmp_path / "in.wav"
        _segment(1.0).export(source, format="wav")
        processor = PydubProcessorAdapter()
        out = processor.process(
            str(source),
            {
                "noise_reduce": False,
                "voice_enhance": False,
                "apply_gain": False,
                "remove_silence": False,
            },
        )
        assert out.endswith("_processed.wav")
        with wave.open(out, "rb") as handle:
            assert handle.getnframes() > 0

    def test_absent_params_are_a_pass_through(self, tmp_path):
        source = tmp_path / "in.wav"
        original = _segment(1.0)
        original.export(source, format="wav")
        out = PydubProcessorAdapter().process(str(source), {})
        assert AudioSegment.from_wav(out).dBFS == pytest.approx(original.dBFS, abs=0.5)
