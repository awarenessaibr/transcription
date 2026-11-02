"""Dependency-light DSP core for the Pinocchio Audio Lab.

This module is deliberately restricted to **numpy + scipy** for signal processing and the
stdlib :mod:`wave` module for I/O.  It deliberately does *not* import ``torch``/``torchaudio``
or ``pydub`` so that it stays fast to import, easy to unit-test, and usable from any process
that has the base scientific stack.

Design rules
------------
* Audio is always ``float32`` shaped ``(channels, frames)`` in ``[-1.0, 1.0]``.
* Every public function is pure: it returns new arrays and never mutates its inputs.
* Every numeric parameter is clamped to a sane range so a hostile or fat-fingered UI value
  cannot produce silence, NaN, or +7 dB of distortion (the failure modes of the legacy
  ``pydub_processor`` path).
* ``NaN``/``Inf`` are never allowed to escape: :func:`_sanitize` is applied at every boundary.

The operations mirror the semantics of the sibling ``audio/`` project (its ``torchaudio``
webapp), but with speech-appropriate defaults.
"""
from __future__ import annotations

import logging
import math
import wave
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal

logger = logging.getLogger(__name__)

__all__ = [
    "AudioLabError",
    "ChainResult",
    "PRESETS",
    "SilenceRegion",
    "load_audio",
    "save_wav",
    "resample",
    "to_mono",
    "to_channels",
    "apply_gain_db",
    "normalize",
    "highpass",
    "lowpass",
    "bandpass",
    "notch",
    "dc_remove",
    "fade",
    "reverse",
    "spectral_denoise",
    "dereverb",
    "detect_silence",
    "trim_silence",
    "measure",
    "integrated_loudness",
    "process_chain",
    "capabilities",
    "estimate_chain",
]


class AudioLabError(ValueError):
    """Raised for user-correctable input problems (bad path, bad op, bad param)."""


# ---------------------------------------------------------------------------
# Constants / clamps
# ---------------------------------------------------------------------------

#: Hard limits.  Values outside are clamped, not rejected, except where noted.
_MIN_SR = 4000
_MAX_SR = 192000
_MAX_CHANNELS = 8
_FLOAT_EPS = 1e-12

#: Speech-safe band-pass used by the ``voice_enhance`` preset.  Whisper transcribes the full
#: 0-8 kHz band; the legacy 300-3400 Hz "telephone" band-pass actively harms fricatives.
SPEECH_HIGHPASS_HZ = 60.0
SPEECH_LOWPASS_HZ = 8000.0

#: Named preprocessing chains surfaced in the UI.
PRESETS: dict[str, dict[str, Any]] = {
    "none": {"label": "No processing", "chain": []},
    "speech_clean": {
        "label": "Speech clean (safe default)",
        "chain": [
            {"op": "dc_remove"},
            {"op": "highpass", "cutoff_hz": 60.0, "q": 0.707},
            {"op": "lowpass", "cutoff_hz": 8000.0, "q": 0.707},
            {"op": "normalize", "target_dbfs": -3.0, "peak_ceiling_dbfs": -1.0},
        ],
    },
    "noisy_room": {
        "label": "Noisy room",
        "chain": [
            {"op": "dc_remove"},
            {"op": "highpass", "cutoff_hz": 80.0, "q": 0.707},
            {"op": "spectral_denoise", "strength": 0.55, "n_fft": 1024},
            {"op": "normalize", "target_dbfs": -3.0, "peak_ceiling_dbfs": -1.0},
        ],
    },
    "reverberant": {
        "label": "Reverberant room",
        "chain": [
            {"op": "dc_remove"},
            {"op": "highpass", "cutoff_hz": 80.0, "q": 0.707},
            {"op": "dereverb", "amount": 0.5, "decay_ms": 220.0},
            {"op": "normalize", "target_dbfs": -3.0, "peak_ceiling_dbfs": -1.0},
        ],
    },
    "asr_16k": {
        "label": "Whisper-ready 16 kHz mono",
        "chain": [
            {"op": "dc_remove"},
            {"op": "highpass", "cutoff_hz": 60.0, "q": 0.707},
            {"op": "lowpass", "cutoff_hz": 7800.0, "q": 0.707},
            {"op": "resample", "target_sr": 16000},
            {"op": "to_mono"},
            {"op": "normalize", "target_dbfs": -3.0, "peak_ceiling_dbfs": -1.0},
        ],
    },
}


def _sanitize(data: np.ndarray) -> np.ndarray:
    """Replace NaN/Inf and hard-clamp to the valid float range."""
    out = np.nan_to_num(
        np.asarray(data, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0
    )
    return np.clip(out, -1.5, 1.5, out=out)


def _clamp(value: float, low: float, high: float, name: str = "value") -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise AudioLabError(f"{name} must be a number, got {value!r}") from exc
    if math.isnan(v):
        raise AudioLabError(f"{name} must not be NaN")
    clamped = min(max(v, low), high)
    if clamped != v:
        logger.debug("[audio_dsp] clamped %s from %s to %s", name, v, clamped)
    return clamped


def _clamp_int(value: Any, low: int, high: int, name: str = "value") -> int:
    return int(round(_clamp(value, low, high, name)))


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _wav_dtype(sample_width: int) -> tuple[str, float]:
    """Return (numpy code, full-scale divisor) for a PCM sample width in bytes."""
    if sample_width == 1:
        return "u1", 128.0  # 8-bit WAV is unsigned
    if sample_width == 2:
        return "i2", float(2**15)
    if sample_width == 3:
        return "i4", float(2**23)  # widened below
    if sample_width == 4:
        return "i4", float(2**31)
    raise AudioLabError(f"unsupported WAV sample width: {sample_width * 8} bit")


def load_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """Load a PCM WAV file as ``float32 (channels, frames)`` in ``[-1, 1]``.

    Non-WAV containers must be converted first (the service already has
    ``AudioFileAdapter.convert_to_wav`` for that); this keeps the DSP core free of codec
    dependencies.
    """
    target = Path(path)
    if not target.exists():
        raise AudioLabError(f"audio file not found: {target}")

    try:
        with wave.open(str(target), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frames = handle.getnframes()
            raw = handle.readframes(frames)
            comptype = handle.getcomptype()
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioLabError(f"not a readable PCM WAV file: {target.name} ({exc})") from exc

    if comptype != "NONE":
        raise AudioLabError(f"compressed WAV (comptype={comptype}) is not supported")
    if channels < 1 or channels > _MAX_CHANNELS:
        raise AudioLabError(f"unsupported channel count: {channels}")
    if not (_MIN_SR <= sample_rate <= _MAX_SR):
        raise AudioLabError(f"unsupported sample rate: {sample_rate}")

    code, divisor = _wav_dtype(sample_width)
    if sample_width == 3:
        # 24-bit little-endian: widen to int32, then arithmetic-shift back to scale.
        buf = np.frombuffer(raw, dtype=np.uint8)
        usable = (buf.size // 3) * 3
        triplets = buf[:usable].reshape(-1, 3).astype(np.int32)
        values = triplets[:, 0] | (triplets[:, 1] << 8) | (triplets[:, 2] << 16)
        values = np.where(values & 0x800000, values - 0x1000000, values)
        flat = values.astype(np.float32)
    else:
        flat = np.frombuffer(raw, dtype=np.dtype(code)).astype(np.float32)

    if flat.size == 0:
        return np.zeros((channels, 0), dtype=np.float32), sample_rate

    if flat.size % channels:
        flat = flat[: flat.size - (flat.size % channels)]
    data = flat.reshape(-1, channels).T / divisor
    return _sanitize(data).astype(np.float32, copy=False), sample_rate


def save_wav(path: str | Path, data: np.ndarray, sample_rate: int, *, bit_depth: int = 16) -> Path:
    """Write ``data`` as a PCM WAV file, creating parent directories as needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = to_channels(_sanitize(np.asarray(data, dtype=np.float32)))
    channels, n = frames.shape
    sr = _clamp_int(sample_rate, _MIN_SR, _MAX_SR, "sample_rate")

    if bit_depth == 16:
        pcm = (np.clip(frames, -1.0, 1.0) * 32767.0).astype("<i2")
        width = 2
    elif bit_depth == 32:
        pcm = (np.clip(frames, -1.0, 1.0) * 2147483647.0).astype("<i4")
        width = 4
    else:
        raise AudioLabError(f"unsupported bit depth: {bit_depth}")

    interleaved = pcm.T.reshape(-1)
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(sr)
        handle.writeframes(interleaved.tobytes())
    if n == 0:
        logger.warning("[audio_dsp] wrote empty audio to %s", target)
    return target


# ---------------------------------------------------------------------------
# Shape / rate helpers
# ---------------------------------------------------------------------------


def to_channels(data: np.ndarray) -> np.ndarray:
    """Coerce to ``(channels, frames)`` float32, accepting 1-D input."""
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[None, :]
    elif arr.ndim != 2:
        raise AudioLabError(f"expected mono or 2-D audio, got shape {arr.shape}")
    if arr.shape[0] > _MAX_CHANNELS and arr.shape[1] <= _MAX_CHANNELS:
        arr = arr.T  # tolerate (frames, channels) from careless callers
    if arr.shape[0] < 1 or arr.shape[0] > _MAX_CHANNELS:
        raise AudioLabError(f"unsupported channel count: {arr.shape[0]}")
    return _sanitize(arr)


def to_mono(data: np.ndarray) -> np.ndarray:
    """Average channels down to a single channel."""
    arr = to_channels(data)
    if arr.shape[0] == 1:
        return arr
    return _sanitize(arr.mean(axis=0, keepdims=True))


def resample(data: np.ndarray, sample_rate: int, target_sr: int) -> tuple[np.ndarray, int]:
    """Polyphase resample with anti-aliasing.  No-op when the rates already match."""
    arr = to_channels(data)
    src = _clamp_int(sample_rate, _MIN_SR, _MAX_SR, "sample_rate")
    dst = _clamp_int(target_sr, _MIN_SR, _MAX_SR, "target_sr")
    if src == dst or arr.shape[1] == 0:
        return arr, src

    divisor = math.gcd(int(src), int(dst))
    up = int(dst) // divisor
    down = int(src) // divisor
    out = signal.resample_poly(arr, up, down, axis=-1)
    return _sanitize(out.astype(np.float32, copy=False)), int(dst)


# ---------------------------------------------------------------------------
# Biquad filters (RBJ audio-EQ-cookbook)
# ---------------------------------------------------------------------------


def _biquad(kind: str, sample_rate: int, f0: float, q: float, gain_db: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    nyquist = sample_rate / 2.0
    f0 = _clamp(f0, 1.0, nyquist * 0.999, "cutoff_hz")
    q = _clamp(q, 0.05, 20.0, "q")
    w0 = 2.0 * math.pi * f0 / sample_rate
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * q)
    a = 10.0 ** (_clamp(gain_db, -24.0, 24.0, "gain_db") / 40.0)
    sqrt_a = math.sqrt(a)

    if kind == "lowpass":
        b = [(1 - cos_w0) / 2, 1 - cos_w0, (1 - cos_w0) / 2]
        a_coef = [1 + alpha, -2 * cos_w0, 1 - alpha]
    elif kind == "highpass":
        b = [(1 + cos_w0) / 2, -(1 + cos_w0), (1 + cos_w0) / 2]
        a_coef = [1 + alpha, -2 * cos_w0, 1 - alpha]
    elif kind == "bandpass":
        b = [alpha, 0.0, -alpha]
        a_coef = [1 + alpha, -2 * cos_w0, 1 - alpha]
    elif kind == "notch":
        b = [1.0, -2 * cos_w0, 1.0]
        a_coef = [1 + alpha, -2 * cos_w0, 1 - alpha]
    elif kind == "highshelf":
        # Also used for BS.1770 K-weighting stage 1 (+4 dB shelf @ ~1.68 kHz).
        beta = 2.0 * sqrt_a * alpha
        b = [
            a * ((a + 1) + (a - 1) * cos_w0 + beta),
            -2 * a * ((a - 1) + (a + 1) * cos_w0),
            a * ((a + 1) + (a - 1) * cos_w0 - beta),
        ]
        a_coef = [(a + 1) - (a - 1) * cos_w0 + beta, 2 * ((a - 1) - (a + 1) * cos_w0), (a + 1) - (a - 1) * cos_w0 - beta]
    else:
        raise AudioLabError(f"unknown filter kind: {kind}")

    b_arr = np.asarray(b, dtype=np.float64) / a_coef[0]
    a_arr = np.asarray(a_coef, dtype=np.float64) / a_coef[0]
    return b_arr, a_arr


def _run_filter(data: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
    arr = to_channels(data)
    if arr.shape[1] == 0:
        return arr
    out = signal.lfilter(b, a, arr, axis=-1)
    return _sanitize(out.astype(np.float32, copy=False))


def _band_filter(data: np.ndarray, sample_rate: int, kind: str, cutoff_hz: float, q: float, gain_db: float = 0.0) -> np.ndarray:
    b, a = _biquad(kind, sample_rate, cutoff_hz, q, gain_db)
    return _run_filter(data, b, a)


def highpass(data: np.ndarray, sample_rate: int, cutoff_hz: float = SPEECH_HIGHPASS_HZ, q: float = 0.707) -> np.ndarray:
    """Second-order high-pass.  Removes DC, rumble and handling noise."""
    return _band_filter(data, sample_rate, "highpass", cutoff_hz, q)


def lowpass(data: np.ndarray, sample_rate: int, cutoff_hz: float = SPEECH_LOWPASS_HZ, q: float = 0.707) -> np.ndarray:
    """Second-order low-pass.  Keep the cutoff at/above 8 kHz for speech."""
    return _band_filter(data, sample_rate, "lowpass", cutoff_hz, q)


def bandpass(data: np.ndarray, sample_rate: int, center_hz: float, q: float = 0.707) -> np.ndarray:
    """Constant-skirt-gain band-pass."""
    return _band_filter(data, sample_rate, "bandpass", center_hz, q)


def notch(data: np.ndarray, sample_rate: int, center_hz: float, q: float = 10.0) -> np.ndarray:
    """Narrow band-stop, e.g. for 50/60 Hz mains hum or a whistle."""
    return _band_filter(data, sample_rate, "notch", center_hz, q)


def dc_remove(data: np.ndarray) -> np.ndarray:
    """Subtract the per-channel mean (fast, exact DC removal)."""
    arr = to_channels(data)
    if arr.shape[1] == 0:
        return arr
    return _sanitize(arr - arr.mean(axis=-1, keepdims=True))


def apply_gain_db(data: np.ndarray, gain_db: float) -> np.ndarray:
    """Scale by a decibel amount."""
    factor = 10.0 ** (_clamp(gain_db, -60.0, 60.0, "gain_db") / 20.0)
    return _sanitize(to_channels(data) * np.float32(factor))


def fade(data: np.ndarray, sample_rate: int, fade_in_s: float = 0.0, fade_out_s: float = 0.0) -> np.ndarray:
    """Linear fade in/out, in seconds.  Useful for click-free clip edges."""
    arr = to_channels(data).copy()
    n = arr.shape[1]
    if n == 0:
        return arr
    fade_in = int(_clamp(fade_in_s, 0.0, 60.0, "fade_in_s") * sample_rate)
    fade_out = int(_clamp(fade_out_s, 0.0, 60.0, "fade_out_s") * sample_rate)
    if fade_in > 0:
        ramp = np.linspace(0.0, 1.0, min(fade_in, n), dtype=np.float32)
        arr[:, : ramp.size] *= ramp
    if fade_out > 0:
        ramp = np.linspace(1.0, 0.0, min(fade_out, n), dtype=np.float32)
        arr[:, n - ramp.size :] *= ramp
    return _sanitize(arr)


def reverse(data: np.ndarray) -> np.ndarray:
    """Reverse along the time axis."""
    return _sanitize(to_channels(data)[:, ::-1])


# ---------------------------------------------------------------------------
# Level measurement and normalisation
# ---------------------------------------------------------------------------


def peak_dbfs(data: np.ndarray) -> float:
    arr = to_channels(data)
    if arr.size == 0:
        return -math.inf
    peak = float(np.abs(arr).max())
    return 20.0 * math.log10(peak) if peak > _FLOAT_EPS else -math.inf


def rms_dbfs(data: np.ndarray) -> float:
    arr = to_channels(data)
    if arr.size == 0:
        return -math.inf
    rms = float(np.sqrt(np.mean(np.square(arr, dtype=np.float64))))
    return 20.0 * math.log10(rms) if rms > _FLOAT_EPS else -math.inf


def normalize(
    data: np.ndarray,
    target_dbfs: float = -3.0,
    *,
    peak_ceiling_dbfs: float = -1.0,
    allow_attenuation: bool = True,
) -> np.ndarray:
    """Gain toward ``target_dbfs`` (RMS), never exceeding ``peak_ceiling_dbfs``.

    Unlike the legacy gain stage this can also *attenuate*, and it always reserves headroom:
    the applied gain is the smaller of (target - current RMS) and (ceiling - current peak).
    """
    arr = to_channels(data)
    if arr.size == 0:
        return arr
    target = _clamp(target_dbfs, -60.0, 0.0, "target_dbfs")
    ceiling = _clamp(peak_ceiling_dbfs, -30.0, 0.0, "peak_ceiling_dbfs")

    current_rms = rms_dbfs(arr)
    current_peak = peak_dbfs(arr)
    if not math.isfinite(current_rms) or not math.isfinite(current_peak):
        return arr  # digital silence: nothing meaningful to normalise

    gain = target - current_rms
    if not allow_attenuation:
        gain = max(gain, 0.0)
    gain = min(gain, ceiling - current_peak)
    gain = _clamp(gain, -60.0, 60.0, "gain")
    return apply_gain_db(arr, gain)


def integrated_loudness(data: np.ndarray, sample_rate: int) -> float:
    """ITU-R BS.1770-4 integrated loudness (LUFS) with absolute + relative gating.

    Returns ``-inf`` for digital silence.  This exists because the legacy pipeline labelled an
    RMS-dBFS measure as "LUFS"; that label is only truthful if we actually measure it.
    """
    arr = to_mono(data)
    if arr.shape[1] == 0 or not np.any(arr):
        return -math.inf
    sr = _clamp_int(sample_rate, _MIN_SR, _MAX_SR, "sample_rate")

    # K-weighting: high-shelf (+4 dB @ ~1.68 kHz, Q 0.707) then high-pass (38 Hz, Q 0.5).
    shelf_b, shelf_a = _biquad("highshelf", sr, 1681.974450955533, 0.7071752369554196, 3.999843853973347)
    hp_b, hp_a = _biquad("highpass", sr, 38.13547087602444, 0.5003270373238773)
    weighted = signal.lfilter(shelf_b, shelf_a, arr, axis=-1)
    weighted = signal.lfilter(hp_b, hp_a, weighted, axis=-1)

    block = max(1, int(round(0.400 * sr)))
    step = max(1, int(round(0.100 * sr)))
    n = weighted.shape[1]
    if n < block:
        block, step = n, max(1, n)
    if block <= 0:
        return -math.inf

    y = weighted[0].astype(np.float64)
    starts = range(0, max(1, n - block + 1), step)
    powers = np.array(
        [float(np.mean(np.square(y[s : s + block]))) for s in starts], dtype=np.float64
    )
    powers = powers[np.isfinite(powers) & (powers > 0)]
    if powers.size == 0:
        return -math.inf

    # Absolute gate at -70 LUFS.
    abs_gated = powers[powers > 10.0 ** ((-70.0 + 0.691) / 10.0)]
    if abs_gated.size == 0:
        return -math.inf
    # Relative gate at -10 LU below the absolute-gated mean.
    relative_threshold = float(np.mean(abs_gated)) * 10.0 ** (-10.0 / 10.0)
    gated = abs_gated[abs_gated > relative_threshold]
    if gated.size == 0:
        gated = abs_gated
    loudness = -0.691 + 10.0 * math.log10(float(np.mean(gated)))
    return float(loudness)


# ---------------------------------------------------------------------------
# STFT / overlap-add primitives
# ---------------------------------------------------------------------------


def _stft(x: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    window = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    pad = n_fft // 2
    padded = np.concatenate([np.zeros(pad, dtype=np.float32), x.astype(np.float32), np.zeros(pad + n_fft, dtype=np.float32)])
    frames: list[np.ndarray] = []
    for start in range(0, len(padded) - n_fft + 1, hop):
        frames.append(padded[start : start + n_fft] * window)
    if not frames:
        frames.append(np.zeros(n_fft, dtype=np.float32))
    return np.fft.rfft(np.stack(frames), axis=1)


def _istft(spec: np.ndarray, hop: int, length: int) -> np.ndarray:
    n_fft = (spec.shape[1] - 1) * 2
    window = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    frames = np.fft.irfft(spec, n=n_fft, axis=1).astype(np.float32) * window
    # sqrt-Hann / sqrt-Hann would be COLA-exact; plain Hann normalised by the window-sum is
    # equivalent in practice and avoids a square root per sample.
    out = np.zeros((n_fft // 2) + hop * (frames.shape[0]) + n_fft, dtype=np.float32)
    norm = np.zeros_like(out)
    for idx, frame in enumerate(frames):
        start = idx * hop
        out[start : start + n_fft] += frame
        norm[start : start + n_fft] += window * window
    norm = np.where(norm < 1e-8, 1.0, norm).astype(np.float32)
    out = out / norm
    return out[n_fft // 2 : n_fft // 2 + length]


def _frame_energies(x: np.ndarray, frame: int, hop: int) -> np.ndarray:
    if len(x) == 0:
        return np.zeros(0, dtype=np.float64)
    padded = np.concatenate([x, np.zeros(frame, dtype=np.float32)])
    count = max(1, 1 + (len(padded) - frame) // hop)
    idx = np.arange(count)[:, None] * hop + np.arange(frame)[None, :]
    return np.mean(np.square(padded[idx].astype(np.float64)), axis=1)


# ---------------------------------------------------------------------------
# Noise reduction / dereverb
# ---------------------------------------------------------------------------


def spectral_denoise(
    data: np.ndarray,
    sample_rate: int,
    *,
    strength: float = 0.6,
    n_fft: int = 1024,
    hop: int | None = None,
    noise_profile: np.ndarray | None = None,
    noise_floor_db: float = -45.0,
) -> np.ndarray:
    """Spectral-subtraction / Wiener-style denoiser.

    The noise magnitude spectrum is estimated from the quietest 10 % of frames unless an
    explicit ``noise_profile`` (noise-only audio) is supplied.  ``strength`` (0-1) maps to the
    over-subtraction factor; it is a *strength*, not decibels, matching the documented meaning
    of the UI's reduction control while remaining bounded and NaN-free.
    """
    arr = to_mono(data)
    if arr.shape[1] == 0:
        return arr
    # Validate the rate even though the STFT works in samples: a nonsense rate upstream means a
    # bug in the caller, and failing loudly here is cheaper than a silent garbage result.
    _clamp_int(sample_rate, _MIN_SR, _MAX_SR, "sample_rate")
    strength = _clamp(strength, 0.0, 1.0, "strength")
    if strength <= 0.0:
        return arr

    n_fft = _clamp_int(n_fft, 64, 8192, "n_fft")
    if n_fft % 2:
        n_fft += 1
    step = _clamp_int(hop or n_fft // 4, max(1, n_fft // 16), n_fft, "hop")

    spec = _stft(arr[0], n_fft, step)
    magnitude = np.abs(spec)
    if magnitude.size == 0:
        return arr

    if noise_profile is not None and np.asarray(noise_profile).size:
        prof = to_mono(np.asarray(noise_profile, dtype=np.float32))
        prof_spec = np.abs(_stft(prof[0], n_fft, step))
        noise_mag = prof_spec.mean(axis=0) if prof_spec.size else magnitude.min(axis=0)
    else:
        energies = np.mean(np.square(magnitude), axis=1)
        n_frames = energies.size
        take = max(1, min(n_frames, int(round(n_frames * 0.10))))
        quiet = np.argsort(energies)[:take]
        noise_mag = magnitude[quiet].mean(axis=0)

    noise_mag = np.maximum(noise_mag, _FLOAT_EPS)
    # Over-subtraction ramps with strength; the spectral floor keeps a natural residual.
    alpha = 1.0 + 3.0 * strength
    floor = 10.0 ** (noise_floor_db / 20.0) * noise_mag
    gain = 1.0 - alpha * (noise_mag[None, :] / np.maximum(magnitude, _FLOAT_EPS))
    gain = np.clip(gain, 0.0, 1.0)
    cleaned = spec * gain

    # Suppress residual energy that sits under the estimated floor.
    cleaned_mag = np.abs(cleaned)
    under = cleaned_mag < floor[None, :]
    cleaned = np.where(under, cleaned * 0.25, cleaned)

    out = _istft(cleaned, step, arr.shape[1])
    out = _sanitize(np.asarray(out, dtype=np.float32).reshape(-1))
    # Guard against gross level changes introduced by the spectral floor.
    before, after = rms_dbfs(arr), rms_dbfs(out)
    if math.isfinite(before) and math.isfinite(after) and abs(after - before) > 12.0:
        out = _sanitize(normalize(out, before, peak_ceiling_dbfs=-0.5).reshape(-1))
    return out[None, :]


def dereverb(
    data: np.ndarray,
    sample_rate: int,
    *,
    amount: float = 0.5,
    decay_ms: float = 200.0,
    n_fft: int = 1024,
    max_attenuation_db: float = 14.0,
) -> np.ndarray:
    """Late-reverberation suppression with a decay-tracking peak envelope.

    The envelope follows *recent peak* magnitude with an exponential decay.  For stationary
    speech it converges to the current magnitude, so the applied gain converges to unity; only
    where the signal has decayed sharply below its recent peak — i.e. reverb tails — does the
    gain drop.  This is far safer than a plain spectral subtraction, which over-attenuates
    steady speech (a -7 dB level loss at ``amount=0.5`` in an earlier revision of this module).
    """
    arr = to_mono(data)
    if arr.shape[1] == 0:
        return arr
    sr = _clamp_int(sample_rate, _MIN_SR, _MAX_SR, "sample_rate")
    amount = _clamp(amount, 0.0, 1.0, "amount")
    if amount <= 0.0:
        return arr

    n_fft = _clamp_int(n_fft, 128, 4096, "n_fft")
    if n_fft % 2:
        n_fft += 1
    step = max(1, n_fft // 4)
    decay_ms = _clamp(decay_ms, 20.0, 2000.0, "decay_ms")
    floor = 10.0 ** (-_clamp(max_attenuation_db, 0.0, 40.0, "max_attenuation_db") / 20.0)

    spec = _stft(arr[0], n_fft, step)
    magnitude = np.abs(spec)
    if magnitude.size == 0:
        return arr

    frame_seconds = step / sr
    decay = math.exp(-frame_seconds / max(decay_ms / 1000.0, 1e-3))
    envelope = np.empty_like(magnitude)
    running = magnitude[0].copy()
    for idx in range(magnitude.shape[0]):
        running = np.maximum(magnitude[idx], running * decay)
        envelope[idx] = running

    # Subtract only the *excess* over the present frame, so stationary speech is untouched.
    excess = np.maximum(envelope / np.maximum(magnitude, _FLOAT_EPS) - 1.0, 0.0)
    gain = np.clip(1.0 - amount * excess, floor, 1.0)
    out = _istft(spec * gain, step, arr.shape[1])
    return _sanitize(np.asarray(out, dtype=np.float32).reshape(-1))[None, :]


# ---------------------------------------------------------------------------
# Silence detection / trimming (timeline aware)
# ---------------------------------------------------------------------------


@dataclass
class SilenceRegion:
    """A detected silence interval in **original** timeline seconds."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def as_dict(self) -> dict[str, float]:
        return {"start": self.start, "end": self.end, "duration": round(self.duration, 4)}


def detect_silence(
    data: np.ndarray,
    sample_rate: int,
    *,
    threshold_db: float = -45.0,
    min_silence_ms: float = 250.0,
    frame_ms: float = 20.0,
) -> list[SilenceRegion]:
    """Return silence regions with start/end in original-timeline seconds."""
    arr = to_mono(data)
    sr = _clamp_int(sample_rate, _MIN_SR, _MAX_SR, "sample_rate")
    if arr.shape[1] == 0:
        return []
    threshold_db = _clamp(threshold_db, -90.0, 0.0, "threshold_db")
    min_silence_ms = _clamp(min_silence_ms, 0.0, 60000.0, "min_silence_ms")

    frame = max(1, int(round(sr * _clamp(frame_ms, 5.0, 100.0, "frame_ms") / 1000.0)))
    hop = max(1, frame // 2)
    energies = _frame_energies(arr[0], frame, hop)
    if energies.size == 0:
        return []

    threshold = 10.0 ** (threshold_db / 10.0)
    silent = energies < threshold

    regions: list[SilenceRegion] = []
    idx = 0
    while idx < silent.size:
        if not silent[idx]:
            idx += 1
            continue
        start_idx = idx
        while idx < silent.size and silent[idx]:
            idx += 1
        end_idx = idx
        start_s = start_idx * hop / sr
        end_s = min((end_idx * hop + frame) / sr, arr.shape[1] / sr)
        if (end_s - start_s) * 1000.0 >= min_silence_ms:
            regions.append(SilenceRegion(round(start_s, 4), round(end_s, 4)))
    return regions


def trim_silence(
    data: np.ndarray,
    sample_rate: int,
    *,
    threshold_db: float = -45.0,
    min_silence_ms: float = 250.0,
    pad_ms: float = 80.0,
    keep_regions: bool = True,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Remove detected silence, returning the result **and a timeline map**.

    The returned ``mapping`` contains ``kept`` (a list of ``[out_start, in_start, duration]``
    triples) so a transcript timestamp on the trimmed timeline can be projected back onto the
    original recording.  This is what the legacy destructive silence removal lacked.
    """
    arr = to_channels(data)
    sr = _clamp_int(sample_rate, _MIN_SR, _MAX_SR, "sample_rate")
    total = arr.shape[1] / sr if sr else 0.0
    regions = detect_silence(arr, sr, threshold_db=threshold_db, min_silence_ms=min_silence_ms)

    if not regions:
        return arr, {
            "applied": False,
            "original_duration": round(total, 4),
            "trimmed_duration": round(total, 4),
            "removed": [],
            "kept": [[0.0, 0.0, round(total, 4)]],
        }

    pad = _clamp(pad_ms, 0.0, 2000.0, "pad_ms") / 1000.0
    keep_windows: list[tuple[float, float]] = []
    cursor = 0.0
    for region in regions:
        start = max(0.0, region.start - pad)
        end = min(total, region.end + pad)
        if start > cursor:
            keep_windows.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total:
        keep_windows.append((cursor, total))
    keep_windows = [(s, e) for s, e in keep_windows if e - s > 1e-3]
    if not keep_windows:
        return arr, {
            "applied": False,
            "original_duration": round(total, 4),
            "trimmed_duration": round(total, 4),
            "removed": [r.as_dict() for r in regions],
            "kept": [[0.0, 0.0, round(total, 4)]],
            "note": "everything was classified as silence; original kept",
        }

    chunks = [arr[:, int(s * sr) : int(e * sr)] for s, e in keep_windows]
    out = np.concatenate(chunks, axis=1) if chunks else arr
    out = _sanitize(out.astype(np.float32, copy=False))

    mapping: dict[str, Any] = {
        "applied": True,
        "original_duration": round(total, 4),
        "trimmed_duration": round(out.shape[1] / sr, 4),
        "removed": [r.as_dict() for r in regions],
        "kept": [],
        "removed_total": round(sum(r.duration for r in regions), 4),
    }
    if keep_regions:
        offset = 0.0
        for (start, end) in keep_windows:
            mapping["kept"].append([round(offset, 4), round(start, 4), round(end - start, 4)])
            offset += end - start
    return out, mapping


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def measure(data: np.ndarray, sample_rate: int, *, with_loudness: bool = True) -> dict[str, Any]:
    """Compute a QC report suitable for display and for A/B comparison."""
    arr = to_channels(data)
    sr = _clamp_int(sample_rate, _MIN_SR, _MAX_SR, "sample_rate")
    channels, frames = arr.shape
    duration = frames / sr if sr else 0.0
    mono = arr.mean(axis=0)
    frame = max(1, int(round(0.020 * sr)))
    hop = max(1, frame // 2)
    energies = _frame_energies(mono.astype(np.float32), frame, hop)
    energies_db = 10.0 * np.log10(np.maximum(energies, 1e-12))

    noise_floor = float(np.percentile(energies_db, 10.0)) if energies_db.size else -math.inf
    speech_level = float(np.percentile(energies_db, 95.0)) if energies_db.size else -math.inf
    silence_ratio = (
        float(np.mean(energies_db < -50.0)) if energies_db.size else 0.0
    )
    # Literal digital silence (all-zero frames) is absence of signal, not a noise floor.
    # Including it would report a -120 dB floor and a ~107 dB "SNR".
    active = energies > 1e-10
    active_db = energies_db[active] if bool(np.any(active)) else energies_db
    if active_db.size:
        noise_floor = float(np.percentile(active_db, 10.0))
        speech_level = float(np.percentile(active_db, 95.0))
        snr_estimate: float | None = min(speech_level - noise_floor, 60.0)
    else:
        noise_floor = -math.inf
        snr_estimate = None

    report: dict[str, Any] = {
        "duration_sec": round(duration, 4),
        "sample_rate": sr,
        "channels": channels,
        "frames": frames,
        "peak_dbfs": _round_db(peak_dbfs(arr)),
        "rms_dbfs": _round_db(rms_dbfs(arr)),
        "crest_db": _round_db(peak_dbfs(arr) - rms_dbfs(arr)),
        "dc_offset": round(float(np.mean(mono)) if frames else 0.0, 6),
        "clipping_pct": round(float(np.mean(np.abs(arr) >= 0.999) * 100.0) if frames else 0.0, 4),
        "silence_ratio": round(silence_ratio, 4),
        "noise_floor_dbfs": _round_db(noise_floor),
        "noise_floor_db": _round_db(noise_floor),
        "snr_estimate_db": None if snr_estimate is None else round(snr_estimate, 2),
        "has_audio": bool(frames and float(np.abs(arr).max()) > _FLOAT_EPS),
    }

    if with_loudness and report["has_audio"]:
        try:
            report["loudness_lufs"] = _round_db(integrated_loudness(arr, sr))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[audio_dsp] loudness failed: %s", exc)
            report["loudness_lufs"] = None
    else:
        report["loudness_lufs"] = None

    # Spectral descriptors (mono, 1024-point, on up to 20 s in the middle).
    try:
        window = mono
        max_samples = sr * 20
        if window.size > max_samples:
            offset = (window.size - max_samples) // 2
            window = window[offset : offset + max_samples]
        freqs, psd = signal.welch(
            window.astype(np.float64) if window.size else np.zeros(1),
            fs=sr,
            nperseg=min(1024, max(64, window.size or 64)),
        )
        total = float(psd.sum()) or 1.0
        report["spectral_centroid_hz"] = round(float((freqs * psd).sum() / total), 2)
        cumulative = np.cumsum(psd)
        rolloff_idx = int(np.searchsorted(cumulative, 0.85 * total))
        report["rolloff85_hz"] = round(float(freqs[min(rolloff_idx, len(freqs) - 1)]), 2)
        if window.size:
            band = (freqs >= 3400) & (freqs <= 8000)
            report["energy_3k4_8k_pct"] = round(
                float(psd[band].sum() / total * 100.0), 3
            )
        else:
            report["energy_3k4_8k_pct"] = 0.0
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[audio_dsp] spectral descriptors failed: %s", exc)
        report["spectral_centroid_hz"] = None
        report["rolloff85_hz"] = None
        report["energy_3k4_8k_pct"] = None

    report["recommendations"] = recommend(report)
    return report


def _round_db(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), 2)


def recommend(report: dict[str, Any]) -> list[str]:
    """Turn a QC report into short, actionable advice for the operator."""
    tips: list[str] = []
    snr = report.get("snr_estimate_db")
    if snr is not None and snr < 12:
        tips.append(
            "Low estimated SNR — enable spectral denoise (strength 0.5-0.6) before transcription."
        )
    if (report.get("clipping_pct") or 0) > 0.05:
        tips.append("Clipping detected — check the source gain; denoise will not repair it.")
    if (report.get("dc_offset") or 0) and abs(report["dc_offset"]) > 0.01:
        tips.append("Non-trivial DC offset — enable DC removal.")
    if (report.get("rolloff85_hz") or 0) and report["rolloff85_hz"] < 3400:
        tips.append(
            "85 % of the energy sits below 3.4 kHz — the source may already be band-limited."
        )
    if (report.get("energy_3k4_8k_pct") or 0) < 0.5 and (report.get("duration_sec") or 0) > 1:
        tips.append(
            "Very little energy in 3.4-8 kHz: do NOT apply the legacy 300-3400 Hz 'voice enhance' "
            "band-pass; it removes the fricatives Whisper relies on."
        )
    lufs = report.get("loudness_lufs")
    if lufs is not None and lufs < -30:
        tips.append(f"Quiet source ({lufs} LUFS) — normalise before transcription.")
    sr = report.get("sample_rate")
    if report.get("channels") == 2:
        tips.append("Stereo source — downmixing to mono halves payload and matches Whisper's input.")
    if sr and sr != 16000:
        tips.append(f"Resample {sr} Hz to 16000 Hz for Whisper ('asr_16k' preset).")
    if not tips:
        tips.append("No obvious quality problems detected — the defaults are fine.")
    return tips


# ---------------------------------------------------------------------------
# Chain execution
# ---------------------------------------------------------------------------

_VALID_OPS = {
    "highpass",
    "lowpass",
    "bandpass",
    "notch",
    "dc_remove",
    "spectral_denoise",
    "dereverb",
    "normalize",
    "apply_gain",
    "resample",
    "to_mono",
    "trim_silence",
    "fade",
    "reverse",
    "channel",
}


@dataclass
class ChainResult:
    """Output of :func:`process_chain`."""

    data: np.ndarray
    sample_rate: int
    applied: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trim_map: dict[str, Any] | None = None

    @property
    def duration_sec(self) -> float:
        return self.data.shape[1] / self.sample_rate if self.sample_rate else 0.0


def process_chain(data: np.ndarray, sample_rate: int, chain: Sequence[dict[str, Any]] | None) -> ChainResult:
    """Apply an ordered list of operations.

    Each step is ``{"op": "<name>", ...params}``.  Unknown ops raise :class:`AudioLabError`
    (the UI is data-driven from :func:`capabilities`, so an unknown op means a client bug and
    should be loud rather than silently skipped — the opposite of the ``audio/`` service).
    """
    arr = to_channels(data)
    sr = _clamp_int(sample_rate, _MIN_SR, _MAX_SR, "sample_rate")
    result = ChainResult(data=arr, sample_rate=sr)
    if not chain:
        return result

    for raw_step in chain:
        if not isinstance(raw_step, dict):
            raise AudioLabError(f"chain step must be an object, got {type(raw_step).__name__}")
        op = str(raw_step.get("op") or raw_step.get("type") or "").strip().lower()
        if not op:
            raise AudioLabError("chain step is missing 'op'")
        if op not in _VALID_OPS:
            raise AudioLabError(f"unknown op {op!r}; valid ops: {', '.join(sorted(_VALID_OPS))}")

        before_frames = result.data.shape[1]
        try:
            if op == "highpass":
                result.data = highpass(
                    result.data,
                    result.sample_rate,
                    raw_step.get("cutoff_hz", raw_step.get("frequency_hz", SPEECH_HIGHPASS_HZ)),
                    raw_step.get("q", 0.707),
                )
            elif op == "lowpass":
                result.data = lowpass(
                    result.data,
                    result.sample_rate,
                    raw_step.get("cutoff_hz", raw_step.get("frequency_hz", SPEECH_LOWPASS_HZ)),
                    raw_step.get("q", 0.707),
                )
            elif op == "bandpass":
                result.data = bandpass(
                    result.data,
                    result.sample_rate,
                    raw_step.get("center_hz", raw_step.get("cutoff_hz", 1000.0)),
                    raw_step.get("q", 0.707),
                )
            elif op == "notch":
                result.data = notch(
                    result.data,
                    result.sample_rate,
                    raw_step.get("center_hz", raw_step.get("cutoff_hz", 50.0)),
                    raw_step.get("q", 10.0),
                )
            elif op == "dc_remove":
                result.data = dc_remove(result.data)
            elif op == "spectral_denoise":
                result.data = spectral_denoise(
                    result.data,
                    result.sample_rate,
                    strength=raw_step.get("strength", raw_step.get("reduction", 0.6)),
                    n_fft=raw_step.get("n_fft", 1024),
                    noise_floor_db=raw_step.get("noise_floor_db", -45.0),
                )
            elif op == "dereverb":
                result.data = dereverb(
                    result.data,
                    result.sample_rate,
                    amount=raw_step.get("amount", raw_step.get("mix", 0.5)),
                    decay_ms=raw_step.get("decay_ms", 200.0),
                )
            elif op == "normalize":
                result.data = normalize(
                    result.data,
                    raw_step.get("target_dbfs", -3.0),
                    peak_ceiling_dbfs=raw_step.get("peak_ceiling_dbfs", -1.0),
                    allow_attenuation=bool(raw_step.get("allow_attenuation", True)),
                )
            elif op == "apply_gain":
                result.data = apply_gain_db(result.data, raw_step.get("gain_db", 0.0))
            elif op == "resample":
                target = raw_step.get("target_sr", raw_step.get("sample_rate", 16000))
                result.data, result.sample_rate = resample(result.data, result.sample_rate, target)
            elif op == "to_mono":
                result.data = to_mono(result.data)
            elif op == "channel":
                idx = _clamp_int(raw_step.get("index", 0), 0, result.data.shape[0] - 1, "index")
                result.data = result.data[idx : idx + 1]
            elif op == "reverse":
                result.data = reverse(result.data)
            elif op == "fade":
                result.data = fade(
                    result.data,
                    result.sample_rate,
                    raw_step.get("fade_in_s", raw_step.get("in_s", 0.0)),
                    raw_step.get("fade_out_s", raw_step.get("out_s", 0.0)),
                )
            elif op == "trim_silence":
                trimmed, mapping = trim_silence(
                    result.data,
                    result.sample_rate,
                    threshold_db=raw_step.get("threshold_db", raw_step.get("silence_thresh", -45.0)),
                    min_silence_ms=raw_step.get("min_silence_ms", 250.0),
                    pad_ms=raw_step.get("pad_ms", 80.0),
                )
                result.data = trimmed
                result.trim_map = mapping
                if not mapping.get("applied") and mapping.get("note"):
                    result.warnings.append(mapping["note"])
        except AudioLabError:
            raise
        except Exception as exc:  # convert engine failures into a clear, client-safe error
            raise AudioLabError(f"op {op!r} failed: {exc}") from exc

        result.applied.append(
            {
                "op": op,
                "frames_before": int(before_frames),
                "frames_after": int(result.data.shape[1]),
                "sample_rate": int(result.sample_rate),
                "params": {k: v for k, v in raw_step.items() if k not in {"op", "type"}},
            }
        )

    if result.data.shape[1] == 0:
        result.warnings.append("processing produced zero-length audio")
    if not np.any(result.data):
        result.warnings.append("processing produced digital silence")
    return result


def capabilities() -> dict[str, Any]:
    """Machine-readable description of the ops and presets, consumed by the UI."""
    return {
        "presets": {
            key: {"label": value["label"], "chain": value["chain"]}
            for key, value in PRESETS.items()
        },
        "ops": {
            "dc_remove": {"label": "DC offset removal", "params": {}},
            "highpass": {
                "label": "High-pass",
                "params": {"cutoff_hz": {"default": SPEECH_HIGHPASS_HZ, "min": 20, "max": 2000, "unit": "Hz"}, "q": {"default": 0.707}},
            },
            "lowpass": {
                "label": "Low-pass",
                "params": {"cutoff_hz": {"default": SPEECH_LOWPASS_HZ, "min": 1000, "max": 20000, "unit": "Hz"}, "q": {"default": 0.707}},
            },
            "notch": {
                "label": "Notch",
                "params": {"center_hz": {"default": 50.0, "min": 10, "max": 20000, "unit": "Hz"}, "q": {"default": 10.0}},
            },
            "bandpass": {
                "label": "Band-pass",
                "params": {
                    "center_hz": {"default": 1000.0, "min": 20, "max": 20000, "unit": "Hz"},
                    "q": {"default": 0.707},
                },
            },
            "spectral_denoise": {
                "label": "Spectral denoise",
                "params": {
                    "strength": {"default": 0.6, "min": 0.0, "max": 1.0},
                    "n_fft": {"default": 1024, "min": 64, "max": 8192},
                    "noise_floor_db": {"default": -45.0, "min": -90, "max": -10, "unit": "dB"},
                },
            },
            "dereverb": {
                "label": "Dereverb",
                "params": {"amount": {"default": 0.5, "min": 0.0, "max": 1.0}, "decay_ms": {"default": 200.0, "min": 20, "max": 2000, "unit": "ms"}},
            },
            "normalize": {
                "label": "Normalize",
                "params": {
                    "target_dbfs": {"default": -3.0, "min": -40, "max": 0, "unit": "dBFS"},
                    "peak_ceiling_dbfs": {"default": -1.0, "min": -12, "max": 0, "unit": "dBFS"},
                },
            },
            "apply_gain": {"label": "Gain", "params": {"gain_db": {"default": 0.0, "min": -40, "max": 40, "unit": "dB"}}},
            "resample": {"label": "Resample", "params": {"target_sr": {"default": 16000, "min": 4000, "max": 192000, "unit": "Hz"}}},
            "to_mono": {"label": "Downmix to mono", "params": {}},
            "channel": {"label": "Select channel", "params": {"index": {"default": 0, "min": 0, "max": 7}}},
            "trim_silence": {
                "label": "Trim silence (timeline-aware)",
                "params": {
                    "threshold_db": {"default": -45.0, "min": -90, "max": 0, "unit": "dBFS"},
                    "min_silence_ms": {"default": 250.0, "min": 0, "max": 60000, "unit": "ms"},
                    "pad_ms": {"default": 80.0, "min": 0, "max": 2000, "unit": "ms"},
                },
            },
            "fade": {"label": "Fade", "params": {"fade_in_s": {"default": 0.0, "min": 0, "max": 60, "unit": "s"}, "fade_out_s": {"default": 0.0, "min": 0, "max": 60, "unit": "s"}}},
            "reverse": {"label": "Reverse", "params": {}},
        },
        "speech_safe_defaults": {
            "highpass_hz": SPEECH_HIGHPASS_HZ,
            "lowpass_hz": SPEECH_LOWPASS_HZ,
            "note": (
                "Keep the low-pass at or above 8 kHz for speech. The historical 300-3400 Hz "
                "'voice enhance' band-pass removes the 3.4-8 kHz fricatives Whisper relies on."
            ),
        },
    }


def estimate_chain(data: np.ndarray, sample_rate: int) -> list[dict[str, Any]]:
    """Suggest a starting chain from a QC report."""
    report = measure(data, sample_rate, with_loudness=True)
    chain: list[dict[str, Any]] = [{"op": "dc_remove"}]
    if report.get("snr_estimate_db") is not None and report["snr_estimate_db"] < 15:
        chain.append({"op": "spectral_denoise", "strength": 0.5, "n_fft": 1024})
    chain.append({"op": "highpass", "cutoff_hz": SPEECH_HIGHPASS_HZ, "q": 0.707})
    chain.append({"op": "lowpass", "cutoff_hz": SPEECH_LOWPASS_HZ, "q": 0.707})
    sr = report.get("sample_rate")
    if sr and sr != 16000:
        chain.append({"op": "resample", "target_sr": 16000})
    if report.get("channels", 1) > 1:
        chain.append({"op": "to_mono"})
    chain.append({"op": "normalize", "target_dbfs": -3.0, "peak_ceiling_dbfs": -1.0})
    return chain


def iter_ops() -> Iterable[str]:
    """Sorted op names."""
    return iter(sorted(_VALID_OPS))
