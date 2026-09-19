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
            prop = min(params.get("reduction_db", 25) / 40, 1.0)
            logger.debug(f"[enhance] noise window start={start_idx} prop={prop:.3f}")
            reduced = nr.reduce_noise(
                y=samples,
                y_noise=noise_clip if noise_clip.size > 0 else None,
                sr=sr,
                prop_decrease=prop,
                stationary=False,
            )
            reduced_int16 = (np.clip(reduced, -1, 1) * 32767).astype(np.int16).tobytes()
            audio = AudioSegment(data=reduced_int16, sample_width=2, frame_rate=sr, channels=1)

        if params.get("voice_enhance"):
            logger.info("[enhance] voice enhancement ON")
            audio = audio.low_pass_filter(3400).high_pass_filter(300)
            try:
                audio = compress_dynamic_range(
                    audio, threshold=-50.0, ratio=4.0, attack=5, release=200
                )
            except Exception as e:
                logger.warning(f"[enhance] compression skipped: {e}")

        if params.get("apply_gain"):
            target_lufs = params.get("target_lufs", -16.0)
            if audio.dBFS != float("-inf"):
                gain_needed = max(target_lufs - audio.dBFS, 0)
                logger.info(
                    f"[enhance] gain apply {gain_needed:.2f} dB (current {audio.dBFS:.2f})"
                )
                audio = audio.apply_gain(gain_needed)

        logger.info(
            f"[enhance] done duration={len(audio)/1000:.2f}s "
            f"elapsed={time.time()-start:.2f}s"
        )
        return audio

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
