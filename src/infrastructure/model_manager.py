"""Model lifecycle management — lazy loading, caching, cleanup."""
from __future__ import annotations

import gc
import logging
import os

import torch
import whisper

logger = logging.getLogger(__name__)

# NOTE: this module used to monkeypatch ``torch.load`` process-wide to force
# ``weights_only=False``, and set a ``TORCH_FORCE_WEIGHTS_ONLY`` env var that
# PyTorch does not read. That defeated safe unpickling for *every* checkpoint
# loaded anywhere in the process -- including models fetched from a hub -- and
# silently overrode callers that had explicitly asked for ``weights_only=True``.
#
# The supported way to load a checkpoint that legitimately contains non-tensor
# classes is ``torch.serialization.add_safe_globals``, applied below to the
# Pyannote classes the diarization pipeline needs. If a checkpoint ever fails to
# load, the error names the offending class: add it to the allowlist rather than
# disabling the safety check for the whole process.

# Register the Pyannote classes that appear in the diarization checkpoints.
try:
    import inspect

    import pyannote.audio.core.task

    # Get all classes from pyannote.audio.core.task
    pyannote_classes = []
    for _name, obj in inspect.getmembers(pyannote.audio.core.task):
        if inspect.isclass(obj) and obj.__module__.startswith('pyannote'):
            pyannote_classes.append(obj)

    # Add torch version class
    pyannote_classes.append(torch.torch_version.TorchVersion)

    torch.serialization.add_safe_globals(pyannote_classes)
    logger.debug(f"Registered {len(pyannote_classes)} Pyannote classes as safe globals")
except Exception as e:
    logger.warning(f"Could not register Pyannote safe globals: {e}")

try:
    import huggingface_hub
    from huggingface_hub import file_download as hf_file_download
except Exception:  # pragma: no cover - optional runtime dependency edge
    huggingface_hub = None
    hf_file_download = None


def _patch_hf_hub_download_compat() -> None:
    """Map deprecated use_auth_token kwarg to token for pyannote compatibility."""
    if huggingface_hub is None:
        return

    original = huggingface_hub.hf_hub_download
    if getattr(original, "_transcription_compat_patch", False):
        return

    def _hf_hub_download_compat(*args, **kwargs):
        if "use_auth_token" in kwargs:
            legacy_token = kwargs.pop("use_auth_token")
            kwargs.setdefault("token", legacy_token)
        return original(*args, **kwargs)

    _hf_hub_download_compat._transcription_compat_patch = True  # type: ignore[attr-defined]
    huggingface_hub.hf_hub_download = _hf_hub_download_compat
    if hf_file_download is not None and hasattr(hf_file_download, "hf_hub_download"):
        hf_file_download.hf_hub_download = _hf_hub_download_compat


_patch_hf_hub_download_compat()

from pyannote.audio import Pipeline
from whisper import available_models


class ModelManager:
    """Manages heavy ML model instances (Whisper + Pyannote)."""

    def __init__(self):
        self._whisper_models: dict[str, whisper.Whisper] = {}
        self._diarization_pipeline: Pipeline | None = None

    def get_whisper_model(self, model_size: str = "large-v3") -> whisper.Whisper:
        if model_size not in available_models():
            logger.warning(
                f"Model '{model_size}' not available. Falling back to 'large'. "
                f"Available: {available_models()}"
            )
            model_size = "large"
        if model_size not in self._whisper_models:
            logger.info(f"Loading Whisper model '{model_size}'")
            # Check for explicit CPU force flag (for unsupported GPU architectures)
            force_cpu = os.getenv("FORCE_CPU", "").lower() in ("true", "1", "yes")
            device = torch.device("cpu" if force_cpu else ("cuda" if torch.cuda.is_available() else "cpu"))
            try:
                self._whisper_models[model_size] = whisper.load_model(model_size, device=device)
            except RuntimeError as e:
                # Handle Blackwell GPU (sm_120) and other unsupported CUDA architectures
                if "no kernel image is available" in str(e) or "sm_120" in str(e):
                    logger.warning(
                        f"GPU kernel incompatibility detected: {str(e)[:100]}. "
                        f"Falling back to CPU for Whisper inference."
                    )
                    device = torch.device("cpu")
                    self._whisper_models[model_size] = whisper.load_model(model_size, device=device)
                else:
                    raise
        return self._whisper_models[model_size]

    def get_diarization_pipeline(self, token: str | None = None) -> Pipeline:
        if self._diarization_pipeline is None:
            logger.info("Loading Pyannote diarization pipeline")
            token = (
                token
                or os.getenv("PYANNOTE_AUTH_TOKEN")
                or os.getenv("HF_TOKEN")
                or os.getenv("HUGGINGFACE_HUB_TOKEN")
                or os.getenv("use_auth_token")
            )
            if not token:
                raise ValueError("Pyannote auth token missing.")

            # Pass the token explicitly to Pipeline.from_pretrained so the HF auth
            # token is used in serverless environments where .env is not present.
            os.environ["HF_TOKEN"] = token
            
            # Check for explicit CPU force flag (for unsupported GPU architectures)
            force_cpu = os.getenv("FORCE_CPU", "").lower() in ("true", "1", "yes")
            if force_cpu:
                os.environ["CUDA_VISIBLE_DEVICES"] = ""

            try:
                self._diarization_pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    token=token,
                )
                if self._diarization_pipeline is None:
                    raise RuntimeError(
                        "Pipeline.from_pretrained returned None — "
                        "check that your HF token has access to pyannote/speaker-diarization-3.1"
                    )
            except RuntimeError as e:
                # Handle Blackwell GPU and other unsupported CUDA architectures
                if "no kernel image is available" in str(e) or "sm_120" in str(e):
                    logger.warning(
                        f"GPU kernel incompatibility detected in Pyannote: {str(e)[:100]}. "
                        f"Falling back to CPU for diarization."
                    )
                    # Force CPU by setting device before loading
                    os.environ["CUDA_VISIBLE_DEVICES"] = ""
                    self._diarization_pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1",
                        token=token,
                    )
                    if self._diarization_pipeline is None:
                        raise RuntimeError(
                            "Pipeline.from_pretrained returned None on CPU fallback — "
                            "check that your HF token has access to pyannote/speaker-diarization-3.1"
                        )
                else:
                    raise
            
            try:
                if (
                    hasattr(self._diarization_pipeline, "segmentation")
                    and hasattr(self._diarization_pipeline.segmentation, "threshold")
                ):
                    self._diarization_pipeline.segmentation.threshold = 0.25
            except Exception:
                pass
        return self._diarization_pipeline

    def clear_cache(self):
        self._whisper_models = {}
        self._diarization_pipeline = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
