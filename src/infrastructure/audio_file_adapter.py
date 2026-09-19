"""Audio file operations adapter — implements AudioFilePort."""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from pydub import AudioSegment
import pydub.utils

logger = logging.getLogger(__name__)

# Ensure ffprobe is available in the environment
if not os.environ.get("PATH", ""):
    os.environ["PATH"] = "/usr/local/bin:/usr/bin:/bin"
elif "/usr/bin" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = "/usr/bin:" + os.environ["PATH"]

# Set explicit ffprobe/ffmpeg paths if available
ffprobe_path = shutil.which("ffprobe")
ffmpeg_path = shutil.which("ffmpeg")

if ffprobe_path:
    pydub.utils.which("ffprobe")
    # Monkey-patch pydub to use explicit paths
    original_which = pydub.utils.which

    def patched_which(name):
        if name == "ffprobe":
            return ffprobe_path
        elif name == "ffmpeg":
            return ffmpeg_path
        return original_which(name)

    pydub.utils.which = patched_which


class AudioFileAdapter:
    """File I/O for audio uploads/conversions. Implements AudioFilePort."""

    async def save_upload(self, filename: str, content: bytes, dest_dir: str) -> str:
        safe_name = Path(filename).name
        timestamp = int(time.time())
        base, ext = os.path.splitext(safe_name)
        out_path = os.path.join(dest_dir, f"{base}_{timestamp}{ext}")
        with open(out_path, "wb") as f:
            f.write(content)
        return out_path

    def convert_to_wav(self, audio_path: str) -> str:
        if audio_path.lower().endswith(".wav"):
            return audio_path
        audio = AudioSegment.from_file(audio_path)
        wav_path = audio_path + ".wav"
        audio.export(wav_path, format="wav")
        os.remove(audio_path)
        return wav_path

    def crop_audio(self, audio_path: str, start: float, end: float):
        from pyannote.audio import Audio as PyAudio
        from pyannote.core import Segment

        waveform, sample_rate = PyAudio().crop(audio_path, Segment(start, end))
        return waveform, sample_rate

    def get_duration(self, audio_path: str) -> float:
        audio = AudioSegment.from_file(audio_path)
        return audio.duration_seconds

    def extract_segment(
        self, audio_path: str, start_ms: int, end_ms: int, out_path: str
    ) -> str:
        full_audio = AudioSegment.from_wav(audio_path)
        segment = full_audio[start_ms:end_ms]
        segment.export(out_path, format="wav")
        return out_path
