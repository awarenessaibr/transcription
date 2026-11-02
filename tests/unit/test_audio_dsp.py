"""Unit tests for the Audio Lab DSP core (``src.infrastructure.audio_dsp``).

These tests are intentionally dependency-light: the module under test must stay importable
without torch/torchaudio/pydub, which is one of its design constraints.
"""
from __future__ import annotations

import math
import wave

import numpy as np
import pytest

from src.infrastructure import audio_dsp as dsp

SR = 16000


# --------------------------------------------------------------------------- helpers


def _tone(seconds: float = 2.0, freq: float = 240.0, amp: float = 0.3, sr: int = SR) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _speechlike(seconds: float = 2.0, sr: int = SR, seed: int = 7) -> np.ndarray:
    """A broadband, amplitude-modulated signal with energy up to ~6 kHz."""
    t = np.arange(int(sr * seconds)) / sr
    sig = (
        0.30 * np.sin(2 * np.pi * 220 * t)
        + 0.15 * np.sin(2 * np.pi * 1200 * t)
        + 0.08 * np.sin(2 * np.pi * 5200 * t)
    )
    sig = sig * (0.55 + 0.45 * np.sin(2 * np.pi * 3 * t))
    rng = np.random.default_rng(seed)
    return (sig + 0.01 * rng.standard_normal(t.size)).astype(np.float32)


def _write_wav(path, data: np.ndarray, sr: int = SR, width: int = 2) -> str:
    arr = np.atleast_2d(np.asarray(data, dtype=np.float32))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(arr.shape[0])
        handle.setsampwidth(width)
        handle.setframerate(sr)
        if width == 2:
            pcm = (np.clip(arr, -1, 1) * 32767.0).astype("<i2")
        else:
            pcm = (np.clip(arr, -1, 1) * 2147483647.0).astype("<i4")
        handle.writeframes(pcm.T.reshape(-1).tobytes())
    return str(path)


# --------------------------------------------------------------------------- I/O


class TestIo:
    def test_roundtrip_mono_16bit(self, tmp_path):
        original = _tone(1.0)
        path = _write_wav(tmp_path / "a.wav", original)
        loaded, sr = dsp.load_audio(path)
        assert sr == SR
        assert loaded.shape == (1, original.size)
        assert np.max(np.abs(loaded[0] - original)) < 1e-3

    def test_roundtrip_stereo_32bit(self, tmp_path):
        original = np.stack([_tone(0.5), _tone(0.5, freq=400.0)])
        path = tmp_path / "b.wav"
        dsp.save_wav(path, original, SR, bit_depth=32)
        loaded, sr = dsp.load_audio(path)
        assert loaded.shape == (2, original.shape[1])
        assert sr == SR

    def test_loads_24bit_pcm(self, tmp_path):
        path = _write_wav(tmp_path / "c24.wav", _tone(0.25), width=4)
        loaded, sr = dsp.load_audio(path)
        assert loaded.shape[1] == 4000 and sr == SR

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(dsp.AudioLabError, match="not found"):
            dsp.load_audio(tmp_path / "nope.wav")

    def test_corrupt_file_raises_audio_lab_error(self, tmp_path):
        bad = tmp_path / "bad.wav"
        bad.write_bytes(b"RIFFxxxxWAVEjunkjunkjunk")
        with pytest.raises(dsp.AudioLabError):
            dsp.load_audio(bad)

    def test_rejects_unsupported_bit_depth(self, tmp_path):
        with pytest.raises(dsp.AudioLabError, match="bit depth"):
            dsp.save_wav(tmp_path / "x.wav", _tone(0.1), SR, bit_depth=8)


class TestShapes:
    def test_to_channels_accepts_1d(self):
        assert dsp.to_channels(np.zeros(10, dtype=np.float32)).shape == (1, 10)

    def test_to_mono_averages(self):
        stereo = np.stack([np.ones(10, dtype=np.float32), np.zeros(10, dtype=np.float32)])
        mono = dsp.to_mono(stereo)
        assert mono.shape == (1, 10)
        assert np.allclose(mono, 0.5)

    def test_rejects_3d(self):
        with pytest.raises(dsp.AudioLabError):
            dsp.to_channels(np.zeros((1, 2, 3), dtype=np.float32))

    def test_sanitize_removes_nan(self):
        arr = np.array([[np.nan, np.inf, -np.inf, 5.0]], dtype=np.float32)
        out = dsp.to_channels(arr)
        assert np.isfinite(out).all()
        assert out[0, 3] <= 1.5


class TestResample:
    def test_changes_rate_and_preserves_duration(self):
        data = _tone(1.0, freq=440.0)
        out, sr = dsp.resample(data, SR, 8000)
        assert sr == 8000
        assert abs(out.shape[1] / sr - 1.0) < 0.01

    def test_noop_when_rates_match(self):
        data = _tone(0.2)
        out, sr = dsp.resample(data, SR, SR)
        assert sr == SR
        assert out.shape == (1, data.size)

    def test_roundtrip_preserves_dominant_frequency(self):
        data = _tone(1.0, freq=1000.0)
        down, sr_d = dsp.resample(data, SR, 8000)
        back, sr_u = dsp.resample(down, sr_d, SR)
        assert sr_u == SR
        spectrum = np.abs(np.fft.rfft(back[0]))
        peak_hz = np.fft.rfftfreq(back.shape[1], 1 / SR)[int(np.argmax(spectrum))]
        assert abs(peak_hz - 1000.0) < 40.0


# --------------------------------------------------------------------------- filters


class TestFilters:
    def test_highpass_attenuates_dc_and_keeps_speech(self):
        dc = np.full(4000, 0.5, dtype=np.float32)
        out = dsp.highpass(dc, SR, 60.0)
        assert abs(float(out.mean())) < 0.05

        speech = _tone(0.5, freq=1000.0, amp=0.4)
        kept = dsp.highpass(speech, SR, 60.0)
        assert dsp.rms_dbfs(kept) > dsp.rms_dbfs(speech) - 1.0

    def test_speech_safe_lowpass_preserves_the_fricative_band(self):
        """The whole point of the 8 kHz default: keep 3.4-8 kHz that the legacy band deletes."""
        tone = _tone(0.5, freq=6000.0, amp=0.4)
        safe = dsp.lowpass(tone, SR, dsp.SPEECH_LOWPASS_HZ)
        legacy = dsp.lowpass(tone, SR, 3400.0)
        assert dsp.rms_dbfs(safe) > dsp.rms_dbfs(tone) - 1.0, "8 kHz low-pass must not touch 6 kHz"
        assert dsp.rms_dbfs(legacy) < dsp.rms_dbfs(tone) - 15.0, "3.4 kHz low-pass must delete 6 kHz"

    def test_lowpass_removes_near_nyquist_content(self):
        tone = _tone(0.5, freq=7600.0, amp=0.4)
        out = dsp.lowpass(tone, SR, 5000.0)
        assert dsp.rms_dbfs(out) < dsp.rms_dbfs(tone) - 6.0

    def test_dc_remove_is_exact(self):
        arr = (_tone(0.2) + 0.3).astype(np.float32)[None, :]
        out = dsp.dc_remove(arr)
        assert abs(float(out.mean())) < 1e-6

    def test_notch_suppresses_mains_hum(self):
        hum = _tone(1.0, freq=50.0, amp=0.4)
        out = dsp.notch(hum, SR, 50.0, q=10.0)
        assert dsp.rms_dbfs(out) < dsp.rms_dbfs(hum) - 6.0

    def test_clamps_absurd_cutoffs(self):
        data = _tone(0.2)
        assert np.isfinite(dsp.highpass(data, SR, -500.0)).all()
        assert np.isfinite(dsp.lowpass(data, SR, 10**9)).all()

    def test_bandpass_is_finite(self):
        assert np.isfinite(dsp.bandpass(_tone(0.2), SR, 1000.0)).all()


# --------------------------------------------------------------------------- level


class TestLevel:
    def test_peak_and_rms_of_known_tone(self):
        data = _tone(1.0, amp=0.5)
        assert abs(dsp.peak_dbfs(data) - (-6.02)) < 0.1
        assert abs(dsp.rms_dbfs(data) - (-9.03)) < 0.1

    def test_silence_is_negative_infinity(self):
        silence = np.zeros((1, 1000), dtype=np.float32)
        assert dsp.peak_dbfs(silence) == -math.inf
        assert dsp.rms_dbfs(silence) == -math.inf

    def test_normalize_boosts_quiet_audio(self):
        quiet = (_tone(1.0, amp=0.001))[None, :]
        out = dsp.normalize(quiet, -3.0)
        assert -4.5 < dsp.rms_dbfs(out) < -1.0

    def test_normalize_can_attenuate(self):
        """The legacy gain stage was boost-only; this one must be able to come down."""
        loud = (_tone(1.0, amp=0.9))[None, :]
        out = dsp.normalize(loud, -20.0)
        assert dsp.rms_dbfs(out) < dsp.rms_dbfs(loud) - 10.0

    def test_normalize_respects_peak_ceiling(self):
        for amp in (1e-4, 0.05, 0.5, 0.99):
            out = dsp.normalize((_tone(1.0, amp=amp))[None, :], -1.0, peak_ceiling_dbfs=-1.0)
            assert dsp.peak_dbfs(out) <= -0.9

    def test_normalize_boost_only_mode(self):
        loud = (_tone(1.0, amp=0.9))[None, :]
        out = dsp.normalize(loud, -20.0, allow_attenuation=False)
        assert abs(dsp.rms_dbfs(out) - dsp.rms_dbfs(loud)) < 0.1

    def test_normalize_leaves_silence_alone(self):
        silence = np.zeros((1, 1000), dtype=np.float32)
        assert not np.any(dsp.normalize(silence, -3.0))

    def test_gain_db_clamped(self):
        data = _tone(0.5, amp=0.1)
        assert abs(dsp.rms_dbfs(dsp.apply_gain_db(data, 1e6)) - dsp.rms_dbfs(dsp.apply_gain_db(data, 60))) < 1e-6
        assert abs(dsp.rms_dbfs(dsp.apply_gain_db(data, -1e6)) - dsp.rms_dbfs(dsp.apply_gain_db(data, -60))) < 1e-6

    def test_integrated_loudness_matches_bs1770_reference(self):
        """A 1 kHz full-scale sine is -3.01 dBFS RMS; BS.1770 puts it near -3.0 LUFS."""
        lufs = dsp.integrated_loudness((_tone(3.0, freq=1000.0, amp=1.0))[None, :], SR)
        assert abs(lufs - (-3.01)) < 1.0

    def test_loudness_of_silence_is_neg_inf(self):
        assert dsp.integrated_loudness(np.zeros((1, 16000), dtype=np.float32), SR) == -math.inf


# --------------------------------------------------------------------------- spectral


class TestSpectral:
    def test_stft_istft_roundtrip(self):
        signal = _speechlike(1.0)
        for n_fft, hop in ((512, 128), (1024, 256), (2048, 512)):
            spec = dsp._stft(signal, n_fft, hop)
            restored = dsp._istft(spec, hop, signal.size)
            n = min(signal.size, restored.size)
            assert np.max(np.abs(signal[:n] - restored[:n])) < 1e-4

    def test_denoise_never_produces_nan(self):
        rng = np.random.default_rng(3)
        for signal in (
            np.zeros((1, 16000), dtype=np.float32),
            (_tone(1.0))[None, :],
            (rng.standard_normal(16000) * 0.1).astype(np.float32)[None, :],
            _speechlike(1.0)[None, :],
        ):
            out = dsp.spectral_denoise(signal, SR, strength=0.8)
            assert np.isfinite(out).all()

    def test_denoise_strength_zero_is_identity(self):
        signal = _speechlike(1.0)[None, :]
        assert np.allclose(dsp.spectral_denoise(signal, SR, strength=0.0), signal)

    def test_denoise_reduces_noise_floor(self):
        rng = np.random.default_rng(11)
        clean = _speechlike(2.0)
        noise = (0.05 * rng.standard_normal(clean.size)).astype(np.float32)
        noisy = (clean + noise)[None, :]
        out = dsp.spectral_denoise(noisy, SR, strength=0.6)
        before = dsp.measure(noisy, SR, with_loudness=False)["snr_estimate_db"]
        after = dsp.measure(out, SR, with_loudness=False)["snr_estimate_db"]
        assert after >= before - 1.0  # never makes SNR dramatically worse
        assert abs(dsp.rms_dbfs(out) - dsp.rms_dbfs(noisy)) < 12.0

    def test_denoise_clamps_strength(self):
        signal = _speechlike(0.5)[None, :]
        assert np.isfinite(dsp.spectral_denoise(signal, SR, strength=99.0)).all()
        assert np.isfinite(dsp.spectral_denoise(signal, SR, strength=-5.0)).all()

    def test_dereverb_zero_is_identity(self):
        signal = _speechlike(1.0)[None, :]
        assert np.allclose(dsp.dereverb(signal, SR, amount=0.0), signal)

    def test_dereverb_targets_decay_tails_not_steady_speech(self):
        """A conservative dereverb must leave stationary speech alone.

        An earlier revision attenuated steady speech by ~7 dB; this test pins the fix.
        """
        steady = (_tone(2.0, freq=300.0))[None, :]
        tail = steady.copy()
        decay = np.exp(-np.arange(steady.shape[1] - SR) / (0.08 * SR)).astype(np.float32)
        tail[0, SR:] *= decay

        out_tail = dsp.dereverb(tail, SR, amount=1.0)
        out_steady = dsp.dereverb(steady, SR, amount=1.0)

        tail_delta = dsp.rms_dbfs(out_tail[0, SR:]) - dsp.rms_dbfs(tail[0, SR:])
        steady_delta = dsp.rms_dbfs(out_steady) - dsp.rms_dbfs(steady)
        assert tail_delta < -0.5, "dereverb should suppress the decay tail"
        assert abs(steady_delta) < 0.3, "dereverb must not reshape steady speech"

    def test_dereverb_amount_monotonic(self):
        steady = _tone(2.0, freq=300.0)[None, :]
        tail = steady.copy()
        decay = np.exp(-np.arange(steady.shape[1] - SR) / (0.08 * SR)).astype(np.float32)
        tail[0, SR:] *= decay
        deltas = [
            dsp.rms_dbfs(dsp.dereverb(tail, SR, amount=a)[0, SR:]) - dsp.rms_dbfs(tail[0, SR:])
            for a in (0.25, 0.5, 1.0)
        ]
        assert deltas == sorted(deltas, reverse=True)


# --------------------------------------------------------------------------- silence


class TestSilence:
    def test_detects_inserted_gap(self):
        signal = _speechlike(3.0)[None, :]
        signal[0, 8000:20000] = 0.0  # 0.75 s of silence at 16 kHz
        regions = dsp.detect_silence(signal, SR, threshold_db=-45.0, min_silence_ms=200.0)
        assert len(regions) == 1
        assert abs(regions[0].start - 0.5) < 0.1
        assert abs(regions[0].end - 1.25) < 0.1

    def test_min_silence_filters_short_gaps(self):
        signal = _speechlike(2.0)[None, :]
        signal[0, 8000:8300] = 0.0  # ~19 ms
        assert dsp.detect_silence(signal, SR, min_silence_ms=250.0) == []

    def test_empty_audio_has_no_regions(self):
        assert dsp.detect_silence(np.zeros((1, 0), dtype=np.float32), SR) == []

    def test_trim_produces_timeline_map(self):
        signal = _speechlike(3.0)[None, :]
        signal[0, 8000:24000] = 0.0
        trimmed, mapping = dsp.trim_silence(signal, SR, threshold_db=-45.0, min_silence_ms=200.0)
        assert mapping["applied"] is True
        assert mapping["trimmed_duration"] < mapping["original_duration"]
        assert len(mapping["kept"]) >= 2
        # The map must be monotonic in output time and consistent with the trimmed length.
        offset = 0.0
        for out_start, in_start, duration in mapping["kept"]:
            assert abs(out_start - offset) < 1e-6
            assert in_start >= 0
            offset += duration
        assert abs(offset - mapping["trimmed_duration"]) < 0.05
        assert abs(trimmed.shape[1] / SR - mapping["trimmed_duration"]) < 0.05

    def test_trim_of_all_silence_keeps_original(self):
        silence = np.zeros((1, SR), dtype=np.float32)
        out, mapping = dsp.trim_silence(silence, SR, min_silence_ms=100.0)
        assert mapping["applied"] is False
        assert out.shape == silence.shape
        assert "note" in mapping

    def test_trim_of_audio_without_silence_is_noop(self):
        signal = _speechlike(1.0)[None, :]
        out, mapping = dsp.trim_silence(signal, SR, min_silence_ms=500.0)
        assert mapping["applied"] is False
        assert out.shape == signal.shape


# --------------------------------------------------------------------------- measure


class TestMeasure:
    def test_reports_core_fields(self):
        report = dsp.measure(_speechlike(2.0)[None, :], SR)
        for key in (
            "duration_sec",
            "sample_rate",
            "channels",
            "peak_dbfs",
            "rms_dbfs",
            "crest_db",
            "clipping_pct",
            "silence_ratio",
            "noise_floor_dbfs",
            "snr_estimate_db",
            "loudness_lufs",
            "spectral_centroid_hz",
            "rolloff85_hz",
            "energy_3k4_8k_pct",
            "has_audio",
            "recommendations",
        ):
            assert key in report, key
        assert report["duration_sec"] == pytest.approx(2.0, abs=0.01)
        assert report["sample_rate"] == SR

    def test_digital_silence_does_not_report_absurd_snr(self):
        silence = np.zeros((1, SR), dtype=np.float32)
        report = dsp.measure(silence, SR)
        assert report["has_audio"] is False
        assert report["loudness_lufs"] is None

    def test_silence_gap_does_not_inflate_snr(self):
        signal = _speechlike(2.0)[None, :].copy()
        signal[0, 4000:12000] = 0.0
        report = dsp.measure(signal, SR)
        assert report["snr_estimate_db"] is not None
        assert report["snr_estimate_db"] < 60.0

    def test_clipping_detected(self):
        hot = np.clip(_tone(1.0, amp=2.0), -1.0, 1.0)[None, :]
        assert dsp.measure(hot, SR)["clipping_pct"] > 1.0

    def test_recommends_resampling_for_non_16k(self):
        tips = dsp.measure(_speechlike(2.0, sr=44100)[None, :], 44100)["recommendations"]
        assert any("16000" in tip for tip in tips)

    def test_recommends_denoise_for_noisy_audio(self):
        rng = np.random.default_rng(5)
        clean = _speechlike(4.0)
        noisy = (clean + 0.15 * rng.standard_normal(clean.size)).astype(np.float32)[None, :]
        tips = dsp.measure(noisy, SR)["recommendations"]
        assert any("denoise" in tip.lower() for tip in tips)


# --------------------------------------------------------------------------- chain


class TestProcessChain:
    def test_empty_chain_is_identity(self):
        data = _speechlike(0.5)[None, :]
        result = dsp.process_chain(data, SR, None)
        assert np.allclose(result.data, data)
        assert result.applied == []
        assert result.duration_sec == pytest.approx(0.5, abs=0.01)

    def test_all_presets_run_clean(self):
        data = np.stack([_speechlike(1.0), _speechlike(1.0, seed=9)])
        for name, preset in dsp.PRESETS.items():
            result = dsp.process_chain(data, SR, preset["chain"])
            assert np.isfinite(result.data).all(), name
            assert result.data.shape[1] > 0, name
            assert result.duration_sec > 0.5, name

    def test_presets_use_speech_safe_lowpass(self):
        """Guards against a regression back to the 300-3400 Hz telephone band."""
        for name, preset in dsp.PRESETS.items():
            for step in preset["chain"]:
                if step["op"] == "lowpass":
                    assert step["cutoff_hz"] >= 7800.0, f"{name} low-passes at {step['cutoff_hz']}"

    def test_unknown_op_raises(self):
        with pytest.raises(dsp.AudioLabError, match="unknown op"):
            dsp.process_chain(_tone(0.1)[None, :], SR, [{"op": "explode"}])

    def test_missing_op_raises(self):
        with pytest.raises(dsp.AudioLabError, match="missing 'op'"):
            dsp.process_chain(_tone(0.1)[None, :], SR, [{"cutoff_hz": 100}])

    def test_non_dict_step_raises(self):
        with pytest.raises(dsp.AudioLabError, match="must be an object"):
            dsp.process_chain(_tone(0.1)[None, :], SR, ["highpass"])

    def test_bad_param_raises_audio_lab_error(self):
        with pytest.raises(dsp.AudioLabError, match="must be a number"):
            dsp.process_chain(_tone(0.1)[None, :], SR, [{"op": "channel", "index": "abc"}])

    def test_op_engine_failure_is_wrapped_with_op_name(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise RuntimeError("scipy exploded")

        monkeypatch.setattr(dsp, "highpass", boom)
        with pytest.raises(dsp.AudioLabError, match="op 'highpass' failed"):
            dsp.process_chain(_tone(0.1)[None, :], SR, [{"op": "highpass"}])

    def test_applied_trace_records_frame_deltas(self):
        data = _speechlike(2.0)[None, :].copy()
        data[0, 8000:16000] = 0.0
        result = dsp.process_chain(
            data,
            SR,
            [
                {"op": "resample", "target_sr": 8000},
                {"op": "trim_silence", "threshold_db": -45, "min_silence_ms": 200},
            ],
        )
        ops = [step["op"] for step in result.applied]
        assert ops == ["resample", "trim_silence"]
        assert result.sample_rate == 8000
        assert result.applied[0]["frames_after"] < result.applied[0]["frames_before"]
        assert result.trim_map is not None

    def test_trim_of_silence_only_warns(self):
        result = dsp.process_chain(
            np.zeros((1, SR), dtype=np.float32),
            SR,
            [{"op": "trim_silence", "min_silence_ms": 100}],
        )
        assert result.warnings

    def test_aliases_are_accepted(self):
        result = dsp.process_chain(
            _speechlike(0.5)[None, :],
            SR,
            [{"type": "highpass", "frequency_hz": 100}, {"op": "spectral_denoise", "reduction": 0.4}],
        )
        assert [s["op"] for s in result.applied] == ["highpass", "spectral_denoise"]

    def test_chain_clamps_hostile_values(self):
        result = dsp.process_chain(
            _speechlike(0.5)[None, :],
            SR,
            [
                {"op": "highpass", "cutoff_hz": -10_000},
                {"op": "apply_gain", "gain_db": 1e9},
                {"op": "normalize", "target_dbfs": 500},
            ],
        )
        assert np.isfinite(result.data).all()


class TestCapabilities:
    def test_lists_every_valid_op(self):
        caps = dsp.capabilities()
        assert set(caps["ops"]) == set(dsp.iter_ops())
        for name, spec in caps["ops"].items():
            assert "label" in spec, name
            assert "params" in spec, name

    def test_documents_speech_safe_defaults(self):
        caps = dsp.capabilities()
        assert caps["speech_safe_defaults"]["highpass_hz"] == dsp.SPEECH_HIGHPASS_HZ
        assert caps["speech_safe_defaults"]["lowpass_hz"] == dsp.SPEECH_LOWPASS_HZ
        assert "3.4-8 kHz" in caps["speech_safe_defaults"]["note"]

    def test_presets_are_serialisable(self):
        for name, preset in dsp.capabilities()["presets"].items():
            assert isinstance(preset["chain"], list), name
            assert preset["label"], name

    def test_estimate_chain_reacts_to_input(self):
        noisy = dsp.estimate_chain(_speechlike(2.0)[None, :], SR)
        stereo_44k = dsp.estimate_chain(np.stack([_speechlike(2.0, sr=44100)] * 2), 44100)
        assert any(step["op"] == "resample" for step in stereo_44k)
        assert any(step["op"] == "to_mono" for step in stereo_44k)
        assert any(step["op"] == "normalize" for step in noisy)
