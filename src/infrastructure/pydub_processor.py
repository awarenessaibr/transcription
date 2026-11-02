"""Pydub audio processor adapter — implements AudioProcessorPort."""
from __future__ import annotations

import logging
import os
import time

import noisereduce as nr
import numpy as np
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range
from pydub.silence import detect_nonsilent

logger = logging.getLogger(__name__)

#: Default band-pass edges for ``voice_enhance``.
#:
#: These were 300 / 3400 Hz — a *telephone* band — until this revision.  Whisper transcribes
#: the full 0-8 kHz band and leans on 3.4-8 kHz for fricatives (s, f, z, th), so the old
#: defaults measurably cost accuracy on the exact material this service targets.  Callers can
#: restore the legacy band by passing ``enhance_highpass_hz=300`` / ``enhance_lowpass_hz=3400``.
DEFAULT_VOICE_HIGHPASS_HZ = 60.0
DEFAULT_VOICE_LOWPASS_HZ = 8000.0

#: Range for the noise-reduction strength control.  This is a 0-40 *scale*, not decibels: it
#: maps linearly onto noisereduce's ``prop_decrease``.
MIN_REDUCTION_STRENGTH = 0.0
MAX_REDUCTION_STRENGTH = 40.0


class PydubProcessorAdapter:
    """Audio preprocessing using pydub + noisereduce. Implements AudioProcessorPort."""

    def process(self, audio_path: str, params: dict) -> str:
        t0 = time.time()
        logger.info(f"[process] load {audio_path}")
        audio = AudioSegment.from_file(audio_path)

        audio = self._enhance(audio, params)

        if params.get("remove_silence"):
            audio = self._remove_silence(
                audio,
                silence_thresh=params.get("silence_thresh", -45),
                min_silence_len=params.get("min_silence_len", 250),
            )

        base, ext = os.path.splitext(audio_path)
        processed_path = f"{base}_processed{ext}"
        audio.export(processed_path, format="wav", bitrate="192k")
        logger.info(
            f"[process] wrote {processed_path} duration={len(audio)/1000:.2f}s "
            f"total_elapsed={time.time()-t0:.2f}s"
        )
        return processed_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _enhance(audio: AudioSegment, params: dict) -> AudioSegment:
        start = time.time()
        logger.info(
            f"[enhance] start duration={len(audio)/1000:.2f}s "
            f"sr={audio.frame_rate} ch={audio.channels}"
        )

        if params.get("noise_reduce"):
            logger.info("[enhance] noise reduction ON")
            if audio.dBFS == float("-inf"):
                # noisereduce divides by its own smoothed spectrum and emits NaN for digital
                # silence, so skip the whole stage rather than cleaning up after it.
                logger.info("[enhance] noise reduction skipped: digital silence")
            else:
                raw = np.array(audio.get_array_of_samples())
                if audio.channels > 1:
                    raw = raw.reshape((-1, audio.channels)).mean(axis=1)
                max_int = float(2 ** (8 * audio.sample_width - 1))
                samples = (raw / max_int).astype(np.float32)
                sr = audio.frame_rate
                seg_len = int(0.5 * sr)
                if samples.size > seg_len:
                    step = max(seg_len // 4, 1)
                    rms = [
                        (i, np.sqrt(np.mean(samples[i : i + seg_len] ** 2)))
                        for i in range(0, samples.size - seg_len, step)
                    ]
                    start_idx = min(rms, key=lambda x: x[1])[0] if rms else 0
                else:
                    start_idx = 0
                noise_clip = samples[start_idx : start_idx + seg_len]
                # ``reduction_db`` is a *strength fraction*, not decibels: it maps the 0-40
                # scale onto prop_decrease 0-1.  Clamp and coerce defensively, because a
                # negative value pushes the mask above 1 and amplifies noise instead of
                # suppressing it (measured +7.6 dB of distortion at reduction_db=-100).
                strength = PydubProcessorAdapter._clamp_strength(
                    params.get("reduction_db", 25), default=25.0
                )
                prop = strength / MAX_REDUCTION_STRENGTH
                logger.debug(f"[enhance] noise window start={start_idx} prop={prop:.3f}")
                reduced = nr.reduce_noise(
                    y=samples,
                    y_noise=noise_clip if noise_clip.size > 0 else None,
                    sr=sr,
                    prop_decrease=prop,
                    stationary=False,
                )
                # Belt and braces: never let a NaN from the denoiser reach the int16 cast.
                reduced = np.nan_to_num(
                    np.asarray(reduced, dtype=np.float32), nan=0.0, posinf=1.0, neginf=-1.0
                )
                reduced_int16 = (np.clip(reduced, -1, 1) * 32767).astype(np.int16).tobytes()
                audio = AudioSegment(data=reduced_int16, sample_width=2, frame_rate=sr, channels=1)

        if params.get("voice_enhance"):
            # Band-pass edges are configurable and now default to speech-safe values.  The
            # historical 300-3400 Hz band was a telephone band that tilts 3.4-8 kHz down by
            # 6-8 dB (pydub uses single-pole RC filters), removing fricative energy Whisper
            # relies on.
            high_pass_hz = PydubProcessorAdapter._clamp_hz(
                params.get("enhance_highpass_hz"), DEFAULT_VOICE_HIGHPASS_HZ, 20, 2000
            )
            low_pass_hz = PydubProcessorAdapter._clamp_hz(
                params.get("enhance_lowpass_hz"), DEFAULT_VOICE_LOWPASS_HZ, 1000, 20000
            )
            if low_pass_hz <= high_pass_hz:
                logger.warning(
                    "[enhance] low-pass %s Hz <= high-pass %s Hz; using the speech-safe %s-%s Hz band",
                    low_pass_hz,
                    high_pass_hz,
                    DEFAULT_VOICE_HIGHPASS_HZ,
                    DEFAULT_VOICE_LOWPASS_HZ,
                )
                high_pass_hz, low_pass_hz = DEFAULT_VOICE_HIGHPASS_HZ, DEFAULT_VOICE_LOWPASS_HZ
            logger.info("[enhance] voice enhancement ON band=%s-%s Hz", high_pass_hz, low_pass_hz)
            audio = audio.low_pass_filter(low_pass_hz).high_pass_filter(high_pass_hz)
            try:
                audio = compress_dynamic_range(
                    audio, threshold=-50.0, ratio=4.0, attack=5, release=200
                )
            except Exception as e:
                logger.warning(f"[enhance] compression skipped: {e}")

        if params.get("apply_gain"):
            audio = PydubProcessorAdapter._normalize_loudness(
                audio,
                target_lufs=params.get("target_lufs", -16.0),
                allow_attenuation=bool(params.get("allow_attenuation", True)),
            )

        logger.info(
            f"[enhance] done duration={len(audio)/1000:.2f}s "
            f"elapsed={time.time()-start:.2f}s"
        )
        return audio

    @staticmethod
    def _clamp_hz(value, default: float, low: float, high: float) -> float:
        try:
            hz = float(value)
        except (TypeError, ValueError):
            return float(default)
        if hz != hz:  # NaN
            return float(default)
        return min(max(hz, low), high)

    @staticmethod
    def _clamp_strength(value, default: float = 25.0) -> float:
        """Coerce the 0-40 noise-reduction strength, tolerating junk input."""
        try:
            strength = float(value)
        except (TypeError, ValueError):
            return float(default)
        if strength != strength:  # NaN
            return float(default)
        return min(max(strength, MIN_REDUCTION_STRENGTH), MAX_REDUCTION_STRENGTH)

    @staticmethod
    def _normalize_loudness(
        audio: AudioSegment, *, target_lufs: float, allow_attenuation: bool = True
    ) -> AudioSegment:
        """Peak-guarded gain toward ``target_lufs``.

        Two legacy defects are fixed here:

        * the old gain was ``max(target - dBFS, 0)``, i.e. **boost-only**, so an already-hot
          recording was never brought down to the target;
        * nothing reserved headroom, so a quiet input lifted to the target could clip.

        ``audio.dBFS`` remains an RMS approximation of loudness (a true BS.1770 measurement
        lives in :mod:`src.infrastructure.audio_dsp`); the parameter keeps its historical name
        for API compatibility.
        """
        if audio.dBFS == float("-inf"):
            logger.debug("[enhance] gain skipped: digital silence")
            return audio
        try:
            target = float(target_lufs)
        except (TypeError, ValueError):
            target = -16.0

        gain_needed = target - audio.dBFS
        if not allow_attenuation:
            gain_needed = max(gain_needed, 0.0)

        # Reserve 1 dB of headroom, but only constrain *boosts*.  Attenuation already lowers
        # the peak, and forcing a ceiling onto an input that is already hot would silently
        # change levels even when the operator asked for boost-only.
        peak_dbfs = audio.max_dBFS
        if gain_needed > 0 and peak_dbfs != float("-inf"):
            gain_needed = min(gain_needed, -1.0 - peak_dbfs)
        gain_needed = min(max(gain_needed, -40.0), 40.0)

        if abs(gain_needed) < 0.05:
            logger.info("[enhance] gain %.2f dB is within tolerance; leaving level as is", gain_needed)
            return audio
        logger.info(
            "[enhance] gain %+.2f dB (current %.2f dBFS rms, %.2f dBFS peak, target %.2f)",
            gain_needed,
            audio.dBFS,
            peak_dbfs,
            target,
        )
        return audio.apply_gain(gain_needed)

    @staticmethod
    def _remove_silence(
        audio: AudioSegment, silence_thresh: float, min_silence_len: int
    ) -> AudioSegment:
        logger.info(
            f"[silence] removing silence silence_thresh={silence_thresh}dB "
            f"min_len={min_silence_len}ms"
        )
        ranges = detect_nonsilent(
            audio, min_silence_len=min_silence_len, silence_thresh=silence_thresh
        )
        if not ranges:
            logger.info("[silence] no non-silent ranges detected (keeping original)")
            return audio
        combined = AudioSegment.empty()
        pad = 80
        for start_ms, end_ms in ranges:
            combined += audio[max(0, start_ms - pad) : min(len(audio), end_ms + pad)]
        logger.info(
            f"[silence] kept {len(ranges)} segments -> "
            f"new_duration={len(combined)/1000:.2f}s"
        )
        return combined
