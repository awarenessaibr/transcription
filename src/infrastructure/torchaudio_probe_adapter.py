"""Torchaudio-based ``AcousticProbePort`` adapter (in-process)."""
from __future__ import annotations

import math
from typing import Any

try:  # pragma: no cover — import guard
    import torch
    import torchaudio
    import torchaudio.functional as AF

    _TORCHAUDIO_AVAILABLE = True
except Exception as _exc:  # pragma: no cover
    _IMPORT_ERR = _exc
    _TORCHAUDIO_AVAILABLE = False


def _linear_to_db(x: float) -> float:
    if x <= 0:
        return -math.inf
    return 20.0 * math.log10(x)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return -math.inf
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


class TorchaudioProbeAdapter:
    """In-process ``AcousticProbePort`` using torchaudio.

    Lightweight numerical probes only — no ASR, no diarization.
    """

    def __init__(self, target_sample_rate: int = 16000):
        if not _TORCHAUDIO_AVAILABLE:  # pragma: no cover
            raise RuntimeError(
                f"torchaudio not available: {_IMPORT_ERR}"
            ) from _IMPORT_ERR
        self._target_sr = int(target_sample_rate)

    # ------------------------------------------------------------------ public
    def audio_info(self, path: str) -> dict[str, Any]:
        info = torchaudio.info(path)
        wav, sr = torchaudio.load(path)
        mono = wav.mean(dim=0) if wav.size(0) > 1 else wav.squeeze(0)
        peak = float(mono.abs().max().item()) if mono.numel() else 0.0
        rms = float(mono.pow(2).mean().sqrt().item()) if mono.numel() else 0.0
        clipping = (
            float((mono.abs() >= 0.999).float().mean().item()) if mono.numel() else 0.0
        )
        return {
            "sample_rate": int(info.sample_rate),
            "channels": int(info.num_channels),
            "duration": float(info.num_frames / info.sample_rate)
            if info.sample_rate
            else 0.0,
            "peak_db": _linear_to_db(peak),
            "rms_db": _linear_to_db(rms),
            "clipping_pct": clipping * 100.0,
        }

    def window_stats(self, path: str, start: float, end: float) -> dict[str, Any]:
        info = torchaudio.info(path)
        sr = int(info.sample_rate)
        total_frames = int(info.num_frames)
        start = max(0.0, float(start))
        end = max(start, float(end))
        end = min(end, total_frames / sr if sr else end)
        if (end - start) < 0.05:
            raise ValueError(
                f"window too short: {end - start:.3f}s (need >= 0.05s)"
            )

        frame_offset = int(start * sr)
        num_frames = max(1, int((end - start) * sr))
        wav, _ = torchaudio.load(
            path, frame_offset=frame_offset, num_frames=num_frames
        )
        mono = wav.mean(dim=0) if wav.size(0) > 1 else wav.squeeze(0)

        # Window framing: 25 ms hop with 10 ms stride.
        hop = max(1, int(0.010 * sr))
        win = max(hop, int(0.025 * sr))
        if mono.numel() < win:
            # Single-frame stats.
            rms = float(mono.pow(2).mean().sqrt().item()) if mono.numel() else 0.0
            peak = float(mono.abs().max().item()) if mono.numel() else 0.0
            return {
                "duration": float(end - start),
                "rms_db": _linear_to_db(rms),
                "peak_db": _linear_to_db(peak),
                "silence_ratio": 1.0 if rms <= 0 else 0.0,
                "voiced_ratio": 0.0,
                "snr_estimate": 0.0,
            }

        frames = mono.unfold(0, win, hop)  # (n_frames, win)
        frame_rms = frames.pow(2).mean(dim=1).sqrt()
        frame_rms_db = [
            _linear_to_db(float(v.item())) for v in frame_rms
        ]
        peak = float(mono.abs().max().item())
        rms = float(mono.pow(2).mean().sqrt().item())

        # Spectral flatness via STFT magnitudes per frame.
        try:
            spec = torch.stft(
                mono,
                n_fft=max(256, win),
                hop_length=hop,
                win_length=win,
                return_complex=True,
                center=False,
            ).abs()
            # spec: (freq, n_frames). Flatness = geo_mean / arith_mean per col.
            eps = 1e-12
            log_spec = torch.log(spec + eps)
            geo = torch.exp(log_spec.mean(dim=0))
            arith = spec.mean(dim=0) + eps
            flatness = (geo / arith).clamp(0.0, 1.0)
            voiced_ratio = float((flatness < 0.4).float().mean().item())
        except Exception:
            voiced_ratio = 0.0

        silence_ratio = float(
            sum(1 for v in frame_rms_db if v < -50.0) / max(1, len(frame_rms_db))
        )
        noise_floor = _percentile(frame_rms_db, 10.0)
        max_frame_rms_db = max(frame_rms_db) if frame_rms_db else -math.inf
        snr_estimate = (
            0.0
            if math.isinf(noise_floor) or math.isinf(max_frame_rms_db)
            else float(max_frame_rms_db - noise_floor)
        )

        return {
            "duration": float(end - start),
            "rms_db": _linear_to_db(rms),
            "peak_db": _linear_to_db(peak),
            "silence_ratio": silence_ratio,
            "voiced_ratio": voiced_ratio,
            "snr_estimate": snr_estimate,
        }

    def extract_window(
        self, src_path: str, start: float, end: float, dst_path: str
    ) -> str:
        info = torchaudio.info(src_path)
        sr = int(info.sample_rate)
        total_frames = int(info.num_frames)
        start = max(0.0, float(start))
        end = max(start, float(end))
        end = min(end, total_frames / sr if sr else end)
        if (end - start) < 0.05:
            raise ValueError(
                f"window too short: {end - start:.3f}s (need >= 0.05s)"
            )

        frame_offset = int(start * sr)
        num_frames = max(1, int((end - start) * sr))
        wav, _ = torchaudio.load(
            src_path, frame_offset=frame_offset, num_frames=num_frames
        )
        if wav.size(0) > 1:
            wav = wav.mean(dim=0, keepdim=True)
        if sr != self._target_sr:
            wav = AF.resample(wav, sr, self._target_sr)
        torchaudio.save(
            dst_path,
            wav,
            self._target_sr,
            format="wav",
            encoding="PCM_S",
            bits_per_sample=16,
        )
        return dst_path
