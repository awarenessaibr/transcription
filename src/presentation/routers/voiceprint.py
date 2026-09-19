"""Voiceprint identification router — real endpoint for /api/voiceprint_from_file.

Replaces the 501 stub in pinocchio.py with proper speaker identification
using pyannote/embedding and cosine-distance matching.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import tempfile

import numpy as np
import torch
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["voiceprint"])

# Injected by main.py
_model_manager = None
_audio_files = None


def init_voiceprint_router(model_manager, audio_files):
    global _model_manager, _audio_files
    _model_manager = model_manager
    _audio_files = audio_files


def _b64_to_embedding(b64_str: str, expected_dim: int = 512) -> np.ndarray:
    """Decode a base64-encoded voiceprint back to numpy embedding."""
    raw = base64.b64decode(b64_str)
    # If the voiceprint was stored as base64 of numpy array bytes
    try:
        arr = np.frombuffer(raw, dtype=np.float32)
    except ValueError:
        # Could be base64 of a JSON list of floats
        arr = np.array(json.loads(raw), dtype=np.float32)
    if arr.ndim != 1:
        arr = arr.ravel()
    if arr.shape[0] != expected_dim:
        # Allow resizing if needed (shouldn't normally happen)
        if arr.shape[0] > expected_dim:
            arr = arr[:expected_dim]
        else:
            padded = np.zeros(expected_dim, dtype=np.float32)
            padded[: arr.shape[0]] = arr
            arr = padded
    return arr


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D arrays."""
    dot = float(np.dot(a, b))
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@router.post("/voiceprint_from_file")
@router.post("/pinocchio/voiceprint_from_file", include_in_schema=False)
async def voiceprint_from_file(
    file: UploadFile = File(..., description="Audio file to identify speakers in"),
    voiceprints: str = Form(
        ...,
        description="JSON array of {label, voiceprint} objects. voiceprint is base64-encoded embedding.",
    ),
    api_key: str | None = Form(None, description="Pyannote API key override"),
    confidence: float | None = Form(None, description="Minimum confidence threshold (0-1)"),
):
    """
    Identify speakers in an audio file against a library of stored voiceprints.

    Expects a multipart upload with:
      - `file`: audio file (wav, mp3, m4a, etc.)
      - `voiceprints`: JSON string of [{"label": "Alice", "voiceprint": "<base64>"}, ...]
      - `api_key` (optional): HF / Pyannote token override
      - `confidence` (optional): minimum cosine similarity to report (default: 0.5)
    """
    if _model_manager is None:
        raise HTTPException(status_code=503, detail="Voiceprint service not initialised")

    # Parse voiceprints
    try:
        voiceprints_data = json.loads(voiceprints)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid voiceprints JSON: {e}") from e

    if isinstance(voiceprints_data, dict) and "voiceprints" in voiceprints_data:
        voiceprints_data = voiceprints_data["voiceprints"]

    if not isinstance(voiceprints_data, list) or len(voiceprints_data) == 0:
        raise HTTPException(
            status_code=400,
            detail="voiceprints must be a non-empty array of {label, voiceprint} objects",
        )

    labels = []
    ref_embeddings = []
    for vp in voiceprints_data:
        label = vp.get("label")
        vp_b64 = vp.get("voiceprint")
        if not label or not vp_b64:
            continue
        try:
            emb = _b64_to_embedding(vp_b64)
        except Exception as e:
            logger.warning("Failed to decode voiceprint for label %s: %s", label, e)
            continue
        labels.append(str(label))
        ref_embeddings.append(emb)

    if not ref_embeddings:
        raise HTTPException(status_code=400, detail="No valid voiceprints found in payload")

    ref_matrix = np.stack(ref_embeddings, axis=0)

    min_confidence = confidence if confidence is not None else 0.5

    # Save uploaded file to temp
    temp_path = None
    try:
        original_filename = file.filename or "audio_upload"
        _, ext = os.path.splitext(original_filename)
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext or ".wav") as f:
            content = await file.read()
            f.write(content)
            temp_path = f.name

        # Convert to WAV if needed
        if _audio_files is not None:
            temp_path = _audio_files.convert_to_wav(temp_path)
        source_path = temp_path

        # Load embedding model
        token = api_key or None
        embedding_model = _model_manager.get_embedding_model(token)

        # Run embedding on the audio file (returns (batch, dim) per frame)
        embedding_output = embedding_model(source_path)

        # For each frame embedding, compute closest match
        device = embedding_output.device if hasattr(embedding_output, "device") else "cpu"
        if isinstance(embedding_output, torch.Tensor):
            frame_embeddings = embedding_output.cpu().numpy()
        else:
            frame_embeddings = np.asarray(embedding_output)

        if frame_embeddings.ndim == 1:
            frame_embeddings = frame_embeddings.reshape(1, -1)

        num_frames = frame_embeddings.shape[0]

        # Get diarization for turn boundaries
        diarization_pipeline = _model_manager.get_diarization_pipeline(token)
        try:
            diarization = diarization_pipeline(source_path)
        except Exception as e:
            logger.warning("Diarization failed, using whole-file as single turn: %s", e)
            # Fallback: treat whole audio as one turn
            turns = []
        else:
            # pyannote >= 4 returns a DiarizeOutput wrapper; 3.x returns the Annotation directly.
            if hasattr(diarization, "exclusive_speaker_diarization"):
                diarization = diarization.exclusive_speaker_diarization
            turns = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                turns.append({
                    "start": float(turn.start),
                    "end": float(turn.end),
                    "speaker": str(speaker),
                })

        if not turns:
            # Whole file as single turn
            turns = [{"start": 0.0, "end": float(num_frames), "speaker": "UNKNOWN"}]

        # Map frames to time (pyannote/embedding typically outputs 10ms or 16ms frames)
        # We'll estimate frame duration from the diarization total
        total_duration = max(t["end"] for t in turns) if turns else float(num_frames)
        frame_duration_s = total_duration / max(num_frames, 1)

        # For each turn, compute mean embedding and match against voiceprints
        results = []
        for turn in turns:
            turn_start_s = turn["start"]
            turn_end_s = turn["end"]
            start_frame = max(0, int(turn_start_s / frame_duration_s))
            end_frame = min(num_frames, int(turn_end_s / frame_duration_s) + 1)

            if end_frame <= start_frame:
                continue

            turn_embeddings = frame_embeddings[start_frame:end_frame, :]
            mean_embedding = turn_embeddings.mean(axis=0)

            similarities = [
                cosine_similarity(mean_embedding, ref_embeddings[i])
                for i in range(len(labels))
            ]
            best_idx = int(np.argmax(similarities))
            best_score = float(similarities[best_idx])

            if best_score < min_confidence:
                continue

            results.append({
                "start": turn_start_s,
                "end": turn_end_s,
                "speaker": turn["speaker"],
                "match_label": labels[best_idx],
                "confidence": best_score,
                "all_scores": {
                    labels[i]: float(similarities[i])
                    for i in range(len(labels))
                },
            })

        return {
            "turns": results,
            "voiceprints_used": len(labels),
            "min_confidence": min_confidence,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("[error] voiceprint identification failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        if temp_path and os.path.exists(temp_path):
            import contextlib
            with contextlib.suppress(Exception):
                os.remove(temp_path)