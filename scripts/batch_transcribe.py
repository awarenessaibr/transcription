#!/usr/bin/env python3
"""Batch transcription of audio files using Whisper (local) or RunPod (serverless).

Transcribes all .m4a/.wav/.mp3 files in data/audio/ and saves
structured JSON transcripts to data/transcripts/.

Usage:
    # Local GPU:
    python scripts/batch_transcribe.py [--model small] [--file "specific file.m4a"]

    # RunPod serverless:
    python scripts/batch_transcribe.py --serverless [--model large-v3] [--file "specific file.m4a"]
"""
import argparse
import json
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)

AUDIO_DIR = "data/audio"
TRANSCRIPT_DIR = "data/transcripts"
SUPPORTED_EXT = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".webm"}


def transcribe_file(model, audio_path: str, language: str = "es") -> list[dict]:
    """Transcribe a single audio file and return segments."""
    result = model.transcribe(
        audio_path,
        language=language,
        temperature=0.0,
        beam_size=5,
        best_of=5,
        condition_on_previous_text=False,
        verbose=False,
        word_timestamps=False,
    )

    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "speaker": "SPEAKER_00",
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "text": seg["text"].strip(),
        })

    return segments


def get_transcript_id(filename: str) -> str:
    """Generate a deterministic transcript ID from filename."""
    # Use filename without extension as ID, sanitized
    name = os.path.splitext(filename)[0]
    return name.replace(" ", "_").replace(".", "_")


def main():
    parser = argparse.ArgumentParser(description="Batch transcribe audio files")
    parser.add_argument("--model", default="small", help="Whisper model size (tiny/base/small/medium/large-v3)")
    parser.add_argument("--language", default="es", help="Language code")
    parser.add_argument("--file", default=None, help="Transcribe a specific file only")
    parser.add_argument("--skip-existing", action="store_true", help="Skip files with existing transcripts")
    parser.add_argument("--serverless", action="store_true", help="Use RunPod serverless endpoint instead of local GPU")
    parser.add_argument("--min-speakers", type=int, default=1, help="Minimum speakers for diarization")
    parser.add_argument("--max-speakers", type=int, default=2, help="Maximum speakers for diarization")
    args = parser.parse_args()

    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)

    # Collect files
    if args.file:
        files = [args.file]
    else:
        files = sorted([
            f for f in os.listdir(AUDIO_DIR)
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXT
        ])

    if not files:
        logger.error("No audio files found in %s", AUDIO_DIR)
        sys.exit(1)

    logger.info("Found %d audio files to transcribe", len(files))

    if args.serverless:
        _run_serverless(files, args)
    else:
        _run_local(files, args)


def _run_serverless(files: list[str], args):
    """Transcribe via RunPod serverless endpoint."""
    # Import here to avoid requiring runpod deps for local mode
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.infrastructure.runpod_client import RunPodClient

    api_key = os.environ.get("RUNPOD_API_KEY")
    endpoint_id = os.environ.get("RUNPOD_ENDPOINT_ID")

    if not api_key or not endpoint_id:
        logger.error("RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID must be set for --serverless mode")
        sys.exit(1)

    client = RunPodClient(api_key=api_key, endpoint_id=endpoint_id)
    model_size = args.model if args.model != "small" else "large-v3"  # default to large-v3 for serverless

    logger.info("Mode: SERVERLESS (endpoint=%s, model=%s)", endpoint_id, model_size)

    results = []
    for i, filename in enumerate(files, 1):
        audio_path = os.path.join(AUDIO_DIR, filename)
        if not os.path.isfile(audio_path):
            logger.warning("File not found: %s", audio_path)
            continue

        tid = get_transcript_id(filename)
        out_path = os.path.join(TRANSCRIPT_DIR, f"{tid}.json")

        if args.skip_existing and os.path.exists(out_path):
            logger.info("[%d/%d] SKIP (exists) %s", i, len(files), filename)
            continue

        size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        logger.info("[%d/%d] Sending to RunPod: %s (%.1f MB)", i, len(files), filename, size_mb)

        t1 = time.time()
        try:
            result = client.transcribe_file(
                audio_path,
                language=args.language,
                model_size=model_size,
                min_speakers=args.min_speakers,
                max_speakers=args.max_speakers,
                timeout_s=600,
            )
            elapsed = time.time() - t1
            segments = result.get("segments", [])

            # Save transcript
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)

            total_text = " ".join(s.get("text", "") for s in segments)
            timings = result.get("timings", {})
            logger.info(
                "  -> %d segments, %d chars, %.1fs elapsed (remote: diar=%.1fs asr=%.1fs) -> %s",
                len(segments), len(total_text), elapsed,
                timings.get("diarization_s", 0), timings.get("transcription_s", 0),
                out_path,
            )
            results.append({
                "file": filename,
                "transcript_id": tid,
                "segments": len(segments),
                "chars": len(total_text),
                "time_s": round(elapsed, 1),
                "remote_total_s": timings.get("total_s", 0),
            })

        except Exception as e:
            logger.error("  -> FAILED: %s", e)
            results.append({"file": filename, "error": str(e)})

    _print_summary(results, files)


def _run_local(files: list[str], args):
    """Transcribe locally using Whisper on GPU/CPU."""
    import torch
    import whisper

    # Load model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Mode: LOCAL (model=%s, device=%s)", args.model, device)
    t0 = time.time()
    model = whisper.load_model(args.model, device=device)
    logger.info("Model loaded in %.1fs", time.time() - t0)

    # Transcribe
    results = []
    for i, filename in enumerate(files, 1):
        audio_path = os.path.join(AUDIO_DIR, filename)
        if not os.path.isfile(audio_path):
            logger.warning("File not found: %s", audio_path)
            continue

        tid = get_transcript_id(filename)
        out_path = os.path.join(TRANSCRIPT_DIR, f"{tid}.json")

        if args.skip_existing and os.path.exists(out_path):
            logger.info("[%d/%d] SKIP (exists) %s", i, len(files), filename)
            continue

        size_kb = os.path.getsize(audio_path) / 1024
        logger.info("[%d/%d] Transcribing: %s (%.0fKB)", i, len(files), filename, size_kb)

        t1 = time.time()
        try:
            segments = transcribe_file(model, audio_path, language=args.language)
            elapsed = time.time() - t1

            # Save transcript
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)

            total_text = " ".join(s["text"] for s in segments)
            logger.info(
                "  -> %d segments, %d chars, %.1fs elapsed -> %s",
                len(segments), len(total_text), elapsed, out_path,
            )
            results.append({
                "file": filename,
                "transcript_id": tid,
                "segments": len(segments),
                "chars": len(total_text),
                "time_s": round(elapsed, 1),
            })

        except Exception as e:
            logger.error("  -> FAILED: %s", e)
            results.append({"file": filename, "error": str(e)})

    _print_summary(results, files)


def _print_summary(results: list[dict], files: list[str]):
    """Print final summary of batch run."""
    logger.info("=" * 60)
    ok = [r for r in results if "error" not in r]
    logger.info("DONE: %d/%d files transcribed", len(ok), len(files))
    for r in results:
        if "error" in r:
            logger.info("  FAIL: %s — %s", r["file"], r["error"])
        else:
            extra = f" (remote {r['remote_total_s']}s)" if "remote_total_s" in r else ""
            logger.info("  OK: %s — %d segs, %d chars (%.1fs%s)", r["file"], r["segments"], r["chars"], r["time_s"], extra)


if __name__ == "__main__":
    main()
