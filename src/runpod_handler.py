"""
Runpod Serverless Handler
Bridges Runpod's event format to the Clean Architecture use cases.

Supports two tasks:
  - "excerpt"    → diarize a time-range of an audio file
  - "transcribe" → full diarization + ASR transcription of an entire audio file
"""
import base64
import contextlib
import logging
import os
import tempfile
import time
from pathlib import Path

import runpod

from .config import settings
from .composition import build_runtime
from .domain.chilean_spanish import post_process_chilean_spanish

logger = logging.getLogger(__name__)

# Wire infrastructure from shared composition root
_runtime = build_runtime()
_model_manager = _runtime.model_manager
_diarizer = _runtime.diarizer_adapter
_audio_files = _runtime.audio_file_adapter
_processor = _runtime.processor_adapter
_asr = _runtime.asr_adapter
_excerpt_use_case = _runtime.excerpt_use_case

# Validate critical environment variables on startup
def _validate_runtime_config():
    """Check that required credentials are available."""
    if not settings.RESOLVED_HF_TOKEN:
        raise RuntimeError(
            "No HuggingFace token found. Set PYANNOTE_AUTH_TOKEN, HF_TOKEN, "
            "HUGGINGFACE_HUB_TOKEN, or use_auth_token in RunPod endpoint config."
        )
    if not settings.DEEPSEEK_API_KEY and not settings.ANTHROPIC_API_KEY:
        logger.warning(
            "[runpod] No AI provider configured. Set DEEPSEEK_API_KEY or ANTHROPIC_API_KEY "
            "for transcript analysis features."
        )
    if not settings.QDRANT_URL:
        logger.warning("[runpod] Qdrant not configured. Vector search disabled.")
    logger.info("[runpod] Runtime config validated. Ready to accept jobs.")

_validate_runtime_config()

# ── Language map ─────────────────────────────────────────────
LANGUAGE_MAP = {
    "auto": None,
    "es-CL": "es",
    "es": "es",
    "en-US": "en",
    "en": "en",
    "pt": "pt",
    "pt-BR": "pt",
    "it": "it",
    "fr": "fr",
    "de": "de",
    "ja": "ja",
    "ko": "ko",
    "zh": "zh",
    "ru": "ru",
    "ar": "ar",
    "hi": "hi",
    "nl": "nl",
    "sv": "sv",
    "pl": "pl",
}


def _resolve_audio(job_input: dict) -> tuple[str, str | None]:
    """Return (file_path, temp_path_or_None) from either file_path or base64."""
    file_path = job_input.get("file_path")
    audio_base64 = job_input.get("audio_base64")

    if audio_base64:
        filename = job_input.get("filename", "audio.mp3")
        audio_data = base64.b64decode(audio_base64)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix)
        tmp.write(audio_data)
        tmp.close()
        logger.info("[runpod] decoded base64 audio -> %s", tmp.name)
        return tmp.name, tmp.name

    return file_path, None


def _cleanup(path: str | None):
    if path and os.path.exists(path):
        with contextlib.suppress(Exception):
            os.remove(path)


# ── Excerpt handler ──────────────────────────────────────────
def _handle_excerpt(job_input: dict, file_path: str) -> dict:
    start = float(job_input.get("start", 0))
    end = float(job_input.get("end", 30))
    min_speakers = int(job_input.get("min_speakers", 1))
    max_speakers = int(job_input.get("max_speakers", 2))
    num_speakers = job_input.get("num_speakers")

    result = _excerpt_use_case.execute(
        file_path=file_path,
        start=start,
        end=end,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        num_speakers=num_speakers,
    )
    return result.model_dump()


# ── Full transcription handler ───────────────────────────────
def _handle_transcribe(job_input: dict, file_path: str) -> dict:
    """Full pipeline: convert → preprocess → diarize → ASR per segment."""
    t0 = time.time()
    language = job_input.get("language", "es")
    model_size = job_input.get("model_size", "large-v3")
    min_speakers = int(job_input.get("min_speakers", 1))
    max_speakers = int(job_input.get("max_speakers", 2))
    vad_threshold = float(job_input.get("vad_threshold", 0.25))
    whisper_lang = LANGUAGE_MAP.get(language, None)

    processed_path = None
    wav_path = None

    try:
        # 1. Convert to WAV
        wav_path = _audio_files.convert_to_wav(file_path)

        # 2. Preprocess (noise reduce, gain, etc.)
        processed_path = _processor.process(wav_path, {
            "noise_reduce": job_input.get("noise_reduce", True),
            "reduction_db": job_input.get("reduction_db", 25),
            "voice_enhance": job_input.get("voice_enhance", True),
            "apply_gain": job_input.get("apply_gain", True),
            "target_lufs": job_input.get("target_lufs", -16.0),
            "remove_silence": job_input.get("remove_silence", True),
            "silence_thresh": job_input.get("silence_thresh", -45),
            "min_silence_len": job_input.get("min_silence_len", 250),
        })

        # 3. Diarize
        t_diar = time.time()
        turns = _diarizer.diarize(
            processed_path,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            vad_threshold=vad_threshold,
        )
        diar_s = time.time() - t_diar
        logger.info("[runpod] diarized %d segments in %.1fs", len(turns), diar_s)

        # 4. Transcribe each segment
        segments = []
        t_asr = time.time()
        for idx, turn in enumerate(turns, 1):
            seg_start_ms = int(turn.start * 1000)
            seg_end_ms = int(turn.end * 1000)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as sf:
                seg_path = _audio_files.extract_segment(
                    processed_path, seg_start_ms, seg_end_ms, sf.name
                )

            asr_result = _asr.transcribe(
                seg_path,
                language=whisper_lang,
                model_size=model_size,
                temperature=float(job_input.get("whisper_temp", 0.0)),
                beam_size=int(job_input.get("beam_size", 5)),
                best_of=int(job_input.get("best_of", 5)),
                condition_on_previous_text=job_input.get("condition_on_previous_text", False),
            )
            _cleanup(seg_path)
            raw_text = asr_result.get("text", "") if isinstance(asr_result, dict) else asr_result

            resolved_lang = asr_result.get("language") if isinstance(asr_result, dict) else None
            is_spanish = resolved_lang in ("es", "es-CL") or whisper_lang in ("es", "es-CL")
            text = post_process_chilean_spanish(raw_text) if is_spanish else raw_text
            segments.append({
                "index": idx,
                "speaker": turn.speaker,
                "start": round(turn.start, 3),
                "end": round(turn.end, 3),
                "duration": round(turn.duration, 3),
                "text": text,
            })

        asr_s = time.time() - t_asr
        total_s = time.time() - t0
        logger.info("[runpod] ASR done: %d segments in %.1fs (total %.1fs)", len(segments), asr_s, total_s)

        return {
            "segments": segments,
            "timings": {
                "diarization_s": round(diar_s, 2),
                "transcription_s": round(asr_s, 2),
                "total_s": round(total_s, 2),
            },
            "params": {
                "model_size": model_size,
                "language": language,
                "min_speakers": min_speakers,
                "max_speakers": max_speakers,
            },
        }

    finally:
        _cleanup(processed_path)
        if wav_path and wav_path != file_path:
            _cleanup(wav_path)


# ── Main router ──────────────────────────────────────────────
async def handler(event):
    """
    Runpod serverless handler.

    Expected input format:
    {
        "input": {
            "task": "excerpt" | "transcribe",
            "file_path": "/path/to/file.mp3",
            "audio_base64": "base64_encoded_audio_data",
            "filename": "audio.mp3",

            // excerpt-specific:
            "start": 15.0, "end": 30.0,

            // shared:
            "min_speakers": 1, "max_speakers": 2, "num_speakers": null,
            "language": "es", "model_size": "large-v3"
        }
    }
    """
    temp_path = None
    try:
        job_input = event.get("input", {})
        task = job_input.get("task", "transcribe")

        file_path, temp_path = _resolve_audio(job_input)
        if not file_path:
            return {"error": "Must provide either 'file_path' or 'audio_base64'"}

        if task == "excerpt":
            return _handle_excerpt(job_input, file_path)
        elif task == "transcribe":
            return _handle_transcribe(job_input, file_path)
        else:
            return {"error": f"Unknown task: {task}. Use 'excerpt' or 'transcribe'."}

    except Exception as e:
        logger.exception("[runpod] handler error")
        return {"error": str(e)}
    finally:
        _cleanup(temp_path)


# Start Runpod serverless handler
if __name__ == "__main__":
    logger.info("[runpod] preloading models...")
    try:
        _model_manager.get_diarization_pipeline(settings.PYANNOTE_AUTH_TOKEN)
        _model_manager.get_whisper_model("small")
        logger.info("[runpod] models preloaded")
    except Exception as e:
        logger.warning(f"[runpod] preload failed: {e}")

    runpod.serverless.start({"handler": handler})
