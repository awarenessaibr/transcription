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
            "reduction_db": (
                "Noise-reduction strength on a 0-40 scale. NOT decibels: 40 maps to a full "
                "prop_decrease of 1.0. Values are clamped to 0-40; negative values used to "
                "amplify noise instead of suppressing it."
            ),
            "voice_enhance": "Apply band-pass filtering + dynamic range compression.",
            "enhance_highpass_hz": (
                "Low edge of the voice-enhance band-pass. Defaults to the legacy 300 Hz when unset; "
                "60 Hz is the speech-safe choice."
            ),
            "enhance_lowpass_hz": (
                "High edge of the voice-enhance band-pass. Defaults to the legacy 3400 Hz when "
                "unset. Keep at or above 8000 Hz for speech: 3.4-8 kHz carries the fricatives "
                "Whisper relies on, and the 300-3400 Hz 'telephone' band actively hurts accuracy."
            ),
            "apply_gain": "Loudness normalization toward target_lufs.",
            "allow_attenuation": (
                "Let normalization reduce gain as well as boost it. When false the legacy "
                "boost-only behaviour is used."
            ),
            "target_lufs": (
                "Target loudness. The in-pipeline processor uses RMS dBFS as an approximation, not "
                "a true ITU-R BS.1770 measurement; use /api/pinocchio/audio/analyze for real LUFS."
            ),
            "remove_silence": (
                "Remove detected silence segments before diarization. Destructive: timestamps then "
                "refer to the trimmed timeline. See /api/pinocchio/audio/silence-map for a "
                "timeline-preserving alternative."
            ),
            "silence_thresh": "Silence threshold dBFS (e.g. -45). Higher (less negative) removes more.",
            "min_silence_len": "Minimum silence length (ms) to qualify for removal.",
        },
        "audio_lab": {
            "preset": "Named preprocessing chain (see /api/pinocchio/audio/capabilities).",
            "chain": "Explicit JSON array of DSP steps; takes precedence over 'preset'.",
            "trim": "Append a timeline-aware silence trim that returns a kept-region map.",
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
