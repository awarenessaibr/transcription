"""Audio Lab router — speech-oriented audio manipulation for the Pinocchio UI.

This exposes the DSP in :mod:`src.infrastructure.audio_dsp` over HTTP so the
``File & Execution`` panel can inspect, clean and re-encode audio *before* it reaches
Whisper/pyannote.  It intentionally re-implements the useful subset of the sibling
``audio/`` project (torchaudio webapp on ``:8777``) **in-process**, because:

* the ``audio/`` service returns base64 WAV for every operation with no session/chaining
  support, and is single-worker with CPU-bound ``async`` handlers;
* this service already depends on ``torchaudio``/``numpy``/``scipy``, so there is no new
  runtime requirement;
* the ``audio/`` pipeline has speech-hostile defaults (a 300-3400 Hz "voice enhance"
  band-pass, a boost-only "LUFS" gain, a randomly-initialised default separation model).

Routes (all under ``/api/pinocchio/audio``):

``GET  /capabilities``  machine-readable op/preset catalogue driving the UI
``POST /analyze``       QC report: levels, SNR, clipping, silence, loudness, advice
``POST /silence-map``   silence regions with original-timeline mapping
``POST /suggest-chain`` a recommended processing chain for this specific file
``POST /process``       run a chain and return the rendered WAV (binary or JSON)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from src.infrastructure import audio_dsp
from src.presentation.middleware.path_validator import validate_file_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pinocchio/audio", tags=["audio-lab"])

#: Injected by the composition root.
_audio_files = None
_output_dir: str | None = None

#: Guard rails.
MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MB
MAX_DURATION_SEC = 4 * 3600  # 4 h
_SAFE_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".mp4", ".mov", ".webm"}


def init_audio_lab_router(audio_file_adapter, output_dir: str | None = None) -> None:
    """Wire the adapter used for container→WAV conversion."""
    global _audio_files, _output_dir
    _audio_files = audio_file_adapter
    _output_dir = output_dir


# ---------------------------------------------------------------------------
# Source preparation
# ---------------------------------------------------------------------------


class _Workdir:
    """Temp directory that cleans itself up, including converted intermediates."""

    def __init__(self) -> None:
        self.path = Path(tempfile.mkdtemp(prefix="pino-audiolab-"))

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *exc: object) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def _safe_name(name: str, default_suffix: str = ".wav") -> str:
    """Sanitise an uploaded filename.

    The suffix is preserved when it is plausibly usable, so that an undecodable container
    fails with a clear "could not decode .txt" message rather than being silently renamed to
    ``.wav`` and failing later with an opaque WAV parse error.
    """
    base = Path(name or "audio").name
    stem = Path(base).stem or "audio"
    raw_suffix = Path(base).suffix.lower()
    suffix_chars = "".join(ch for ch in raw_suffix[1:] if ch.isalnum())[:6]
    suffix = f".{suffix_chars}" if suffix_chars else default_suffix
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in stem)[:120] or "audio"
    return f"{cleaned}{suffix}"


def _materialise_source(
    workdir: Path,
    *,
    upload: UploadFile | None,
    audio_path: str | None,
) -> Path:
    """Copy the caller's audio into ``workdir`` and convert it to WAV if needed.

    The copy matters: :meth:`AudioFileAdapter.convert_to_wav` **deletes its input**, so
    converting a caller-supplied server-side path in place would destroy the original.
    """
    if (upload is None) == (audio_path is None):
        raise HTTPException(
            status_code=400, detail="Provide exactly one of 'file' (upload) or 'audio_path'."
        )

    if audio_path is not None:
        try:
            validate_file_path(audio_path)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        source = Path(audio_path)
        if not source.exists():
            raise HTTPException(status_code=404, detail=f"audio file not found: {source}")
        local = workdir / _safe_name(source.name)
        shutil.copy2(source, local)
    else:
        assert upload is not None
        content = upload.file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
            )
        if not content:
            raise HTTPException(status_code=400, detail="uploaded file is empty")
        local = workdir / _safe_name(upload.filename or "audio")
        local.write_bytes(content)

    if local.suffix.lower() == ".wav":
        return local
    if _audio_files is None:
        raise HTTPException(status_code=503, detail="audio conversion adapter unavailable")
    try:
        converted = Path(_audio_files.convert_to_wav(str(local)))
    except Exception as exc:
        logger.warning("[audio-lab] conversion failed for %s: %s", local.name, exc)
        raise HTTPException(
            status_code=400,
            detail=f"could not decode {local.suffix or 'file'} — is ffmpeg installed? ({exc})",
        ) from exc
    if not converted.exists():
        raise HTTPException(status_code=500, detail="audio conversion produced no output")
    return converted


def _load(data_source: Path) -> tuple[Any, int]:
    try:
        arr, sr = audio_dsp.load_audio(data_source)
    except audio_dsp.AudioLabError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return arr, sr


def _assert_reasonable(arr: Any, sr: int) -> None:
    duration = arr.shape[1] / sr if sr else 0.0
    if duration > MAX_DURATION_SEC:
        raise HTTPException(
            status_code=413,
            detail=f"audio is {duration / 3600:.1f} h; the limit is {MAX_DURATION_SEC / 3600:.0f} h",
        )


def _parse_chain(raw: str | None, preset: str | None) -> list[dict[str, Any]]:
    """Resolve the requested chain: an explicit JSON chain wins over a named preset."""
    if raw and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"'chain' is not valid JSON: {exc}") from exc
        if isinstance(parsed, dict) and "chain" in parsed:
            parsed = parsed["chain"]
        if not isinstance(parsed, list):
            raise HTTPException(status_code=400, detail="'chain' must be a JSON array of steps")
        return parsed
    key = (preset or "none").strip().lower()
    if key in ("", "none"):
        return []
    if key not in audio_dsp.PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown preset {preset!r}; choose one of {', '.join(audio_dsp.PRESETS)}",
        )
    return list(audio_dsp.PRESETS[key]["chain"])


def _run_chain(arr: Any, sr: int, chain: list[dict[str, Any]]) -> audio_dsp.ChainResult:
    try:
        return audio_dsp.process_chain(arr, sr, chain)
    except audio_dsp.AudioLabError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("[audio-lab] chain execution failed")
        raise HTTPException(status_code=500, detail=f"processing failed: {exc}") from exc


def _encoded_report(report: dict[str, Any]) -> str:
    """Header-safe (ASCII) encoding of a report dict."""
    return base64.urlsafe_b64encode(json.dumps(report).encode("utf-8")).decode("ascii")


def _decode_report(value: str) -> dict[str, Any]:  # pragma: no cover - used by clients/tests
    return json.loads(base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/capabilities")
async def audio_lab_capabilities() -> JSONResponse:
    """Ops, presets and speech-safe defaults — drives the UI controls."""
    caps = audio_dsp.capabilities()
    caps["limits"] = {
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "max_duration_sec": MAX_DURATION_SEC,
        "output_bit_depths": [16, 32],
        "accepted_containers": sorted(_SAFE_SUFFIXES),
    }
    return JSONResponse(caps)


@router.post("/analyze")
async def audio_lab_analyze(
    file: UploadFile | None = File(None, description="Audio/video file to inspect"),
    audio_path: str | None = Form(None, description="Server-side path to inspect"),
    with_loudness: bool = Form(True, description="Compute ITU-R BS.1770 integrated loudness"),
    with_silence: bool = Form(True, description="Include detected silence regions"),
    silence_threshold_db: float = Form(-45.0),
    min_silence_ms: float = Form(250.0),
) -> JSONResponse:
    """Quality-control report for one file, plus suggested processing."""
    with _Workdir() as workdir:
        source = _materialise_source(workdir, upload=file, audio_path=audio_path)
        arr, sr = _load(source)
        _assert_reasonable(arr, sr)

        try:
            report = audio_dsp.measure(arr, sr, with_loudness=with_loudness)
        except audio_dsp.AudioLabError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if with_silence:
            regions = audio_dsp.detect_silence(
                arr,
                sr,
                threshold_db=silence_threshold_db,
                min_silence_ms=min_silence_ms,
            )
            report["silence_regions"] = [region.as_dict() for region in regions]
            report["silence_region_count"] = len(regions)
        report["source"] = source.name
        try:
            report["suggested_chain"] = audio_dsp.estimate_chain(arr, sr)
        except Exception:  # pragma: no cover - defensive
            report["suggested_chain"] = []
        return JSONResponse(report)


@router.post("/silence-map")
async def audio_lab_silence_map(
    file: UploadFile | None = File(None),
    audio_path: str | None = Form(None),
    threshold_db: float = Form(-45.0),
    min_silence_ms: float = Form(250.0),
    pad_ms: float = Form(80.0),
    simulate_trim: bool = Form(True),
) -> JSONResponse:
    """Silence regions in **original-timeline** seconds, plus an optional trim map.

    The trim map is the fix for the legacy pipeline's destructive silence removal: with
    ``kept`` triples ``[out_start, in_start, duration]`` a timestamp on the trimmed
    timeline can be projected back onto the source recording.
    """
    with _Workdir() as workdir:
        source = _materialise_source(workdir, upload=file, audio_path=audio_path)
        arr, sr = _load(source)
        _assert_reasonable(arr, sr)

        regions = audio_dsp.detect_silence(
            arr, sr, threshold_db=threshold_db, min_silence_ms=min_silence_ms
        )
        payload: dict[str, Any] = {
            "sample_rate": sr,
            "duration_sec": round(arr.shape[1] / sr, 4) if sr else 0.0,
            "threshold_db": threshold_db,
            "min_silence_ms": min_silence_ms,
            "regions": [region.as_dict() for region in regions],
            "region_count": len(regions),
            "silence_total_sec": round(sum(r.duration for r in regions), 4),
        }
        if simulate_trim:
            _, mapping = audio_dsp.trim_silence(
                arr,
                sr,
                threshold_db=threshold_db,
                min_silence_ms=min_silence_ms,
                pad_ms=pad_ms,
            )
            payload["trim_map"] = mapping
        return JSONResponse(payload)


@router.post("/suggest-chain")
async def audio_lab_suggest_chain(
    file: UploadFile | None = File(None),
    audio_path: str | None = Form(None),
) -> JSONResponse:
    """Recommend a preprocessing chain for this specific recording."""
    with _Workdir() as workdir:
        source = _materialise_source(workdir, upload=file, audio_path=audio_path)
        arr, sr = _load(source)
        _assert_reasonable(arr, sr)
        report = audio_dsp.measure(arr, sr, with_loudness=False)
        try:
            chain = audio_dsp.estimate_chain(arr, sr)
        except Exception:  # pragma: no cover - defensive
            chain = audio_dsp.PRESETS["speech_clean"]["chain"]
        return JSONResponse(
            {"chain": chain, "report": report, "recommendations": report.get("recommendations", [])}
        )


@router.post("/process")
async def audio_lab_process(
    file: UploadFile | None = File(None, description="Audio/video to process"),
    audio_path: str | None = Form(None, description="Server-side path to process"),
    chain: str | None = Form(None, description="JSON array of steps; wins over 'preset'"),
    preset: str = Form("none", description="Named preset from /capabilities"),
    response_format: str = Form("binary", description="'binary' (audio/wav) or 'json'"),
    bit_depth: int = Form(16),
    trim: bool = Form(False, description="Append a timeline-aware silence trim"),
    trim_threshold_db: float = Form(-45.0),
    trim_min_silence_ms: float = Form(250.0),
    save: bool = Form(False, description="Persist the result under the audio directory"),
    output_name: str | None = Form(None),
    measure_before: bool = Form(True),
) -> Response:
    """Apply a chain and return the result.

    Returns ``audio/wav`` bytes by default.  The QC report travels in the
    ``X-Audio-Lab-Report`` header as URL-safe base64 JSON (HTTP headers are not a safe
    transport for arbitrary JSON), and is inlined when ``response_format=json``.
    """
    if bit_depth not in (16, 32):
        raise HTTPException(status_code=400, detail="bit_depth must be 16 or 32")
    fmt = (response_format or "binary").strip().lower()
    if fmt not in ("binary", "json"):
        raise HTTPException(status_code=400, detail="response_format must be 'binary' or 'json'")

    steps = _parse_chain(chain, preset)
    if trim:
        steps = steps + [
            {
                "op": "trim_silence",
                "threshold_db": trim_threshold_db,
                "min_silence_ms": trim_min_silence_ms,
            }
        ]
    if not steps:
        raise HTTPException(
            status_code=400,
            detail="nothing to do: supply a non-empty 'chain' or a 'preset' other than 'none'",
        )

    started = time.time()
    with _Workdir() as workdir:
        source = _materialise_source(workdir, upload=file, audio_path=audio_path)
        arr, sr = _load(source)
        _assert_reasonable(arr, sr)

        report: dict[str, Any] = {
            "source": source.name,
            "input": audio_dsp.measure(arr, sr, with_loudness=measure_before) if measure_before else None,
            "chain": steps,
        }
        result = _run_chain(arr, sr, steps)
        report["output"] = audio_dsp.measure(result.data, result.sample_rate, with_loudness=True)
        report["applied"] = result.applied
        report["warnings"] = result.warnings
        report["trim_map"] = result.trim_map
        report["sample_rate"] = result.sample_rate
        report["duration_sec"] = round(result.duration_sec, 4)

        if report["input"]:
            report["delta"] = {
                "rms_db": _delta(report["input"].get("rms_dbfs"), report["output"].get("rms_dbfs")),
                "peak_db": _delta(report["input"].get("peak_dbfs"), report["output"].get("peak_dbfs")),
                "snr_db": _delta(report["input"].get("snr_estimate_db"), report["output"].get("snr_estimate_db")),
                "loudness_lu": _delta(
                    report["input"].get("loudness_lufs"), report["output"].get("loudness_lufs")
                ),
                "duration_sec": round(
                    (report["output"].get("duration_sec") or 0) - (report["input"].get("duration_sec") or 0),
                    4,
                ),
            }

        stem = Path(output_name).stem if output_name else f"{Path(source.name).stem}_lab"
        stem = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in stem)[:120] or "audio_lab"
        filename = f"{stem}_{int(time.time())}.wav"

        saved_path: str | None = None
        if save:
            target_dir = Path(_output_dir or workdir)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename
            audio_dsp.save_wav(target, result.data, result.sample_rate, bit_depth=bit_depth)
            saved_path = str(target)
            report["saved_path"] = saved_path

        report["elapsed_sec"] = round(time.time() - started, 3)

        if fmt == "json":
            payload = dict(report)
            payload["audio_base64"] = base64.b64encode(
                _wav_bytes(result.data, result.sample_rate, bit_depth)
            ).decode("ascii")
            payload["filename"] = filename
            return JSONResponse(payload)

        headers = {
            "X-Audio-Lab-Report": _encoded_report(report),
            "X-Audio-Lab-Sample-Rate": str(result.sample_rate),
            "X-Audio-Lab-Channels": str(result.data.shape[0]),
            "X-Audio-Lab-Duration": f"{result.duration_sec:.4f}",
            "Content-Disposition": f'inline; filename="{filename}"',
            "Access-Control-Expose-Headers": (
                "X-Audio-Lab-Report, X-Audio-Lab-Sample-Rate, X-Audio-Lab-Channels, "
                "X-Audio-Lab-Duration, Content-Disposition"
            ),
        }
        return Response(
            content=_wav_bytes(result.data, result.sample_rate, bit_depth),
            media_type="audio/wav",
            headers=headers,
        )


def _delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round(float(after) - float(before), 3)


def _wav_bytes(data: Any, sample_rate: int, bit_depth: int) -> bytes:
    """Render to WAV in-memory (the DSP core is file-oriented, so use a temp file)."""
    with tempfile.TemporaryDirectory(prefix="pino-audiolab-out-") as tmp:
        target = os.path.join(tmp, "out.wav")
        audio_dsp.save_wav(target, data, sample_rate, bit_depth=bit_depth)
        with open(target, "rb") as handle:
            return handle.read()
