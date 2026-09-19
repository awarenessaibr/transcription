"""Parameter metadata router — serves form definitions for frontend."""
from __future__ import annotations

from fastapi import APIRouter
from whisper import available_models

router = APIRouter(prefix="/api/diarization", tags=["parameters"])


@router.get("/parameters")
def list_parameter_definitions():
    """Structured metadata for front-end form generation."""
    return {
        "general": {
            "language": "Input language locale (maps to Whisper language code). Ex: es-CL, en, pt-BR.",
            "model_size": "Whisper model variant. Larger = better quality, slower & more RAM.",
            "min_speakers": "Lower bound for expected speakers (diarization constraint).",
            "max_speakers": "Upper bound for expected speakers (diarization constraint).",
            "vad_threshold": "Voice activity probability threshold (lower = more segments, higher = stricter).",
        },
        "preprocessing": {
            "noise_reduce": "Apply spectral noise reduction (slow for long audio).",
            "reduction_db": "Approximate aggressiveness (0–40). Higher may introduce artifacts.",
            "voice_enhance": "Apply band-pass filtering + dynamic range compression.",
            "apply_gain": "Loudness normalization toward target_lufs.",
            "target_lufs": "Target loudness (LUFS). Typical podcast: -16 (stereo) / -19 (mono).",
            "remove_silence": "Remove detected silence segments before diarization.",
            "silence_thresh": "Silence threshold dBFS (e.g. -45). Higher (less negative) removes more.",
            "min_silence_len": "Minimum silence length (ms) to qualify for removal.",
        },
        "whisper_decoding": {
            "beam_size": "Beam search width (larger = better accuracy, slower).",
            "best_of": "Number of sampled candidates when not using temperature=0.",
            "whisper_temp": "Starting sampling temperature. 0 = deterministic.",
            "temperature_increment_on_fallback": "Temperature added on each fallback attempt.",
            "compression_ratio_threshold": "Abort & retry if gzip ratio exceeds this.",
            "logprob_threshold": "Abort & retry if avg log-prob below this.",
            "no_speech_threshold": "If no-speech probability exceeds this → treat as silence.",
            "condition_on_previous_text": "Feed previous segment text as context.",
            "initial_prompt": "Optional priming text or domain vocabulary.",
            "length_penalty": "Adjust preference for longer/shorter outputs in beam search.",
            "patience": "Beam search termination patience.",
            "suppress_blank": "Suppress blank tokens.",
            "suppress_tokens": "Comma list of token IDs to suppress (-1 = library default).",
            "word_timestamps": "Enable per-word timestamps (slower).",
        },
        "control": {
            "keep_cache": "Keep models in memory after request for reuse (faster subsequent calls).",
        },
    }


@router.get("/models/whisper")
def list_whisper_models():
    return {"available_models": available_models()}
