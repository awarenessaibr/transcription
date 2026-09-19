import os
from pathlib import Path
from urllib.parse import urlparse

import torch
from dotenv import load_dotenv

_THIS_FILE = Path(__file__).resolve()
_transcription_ROOT = _THIS_FILE.parents[1]
_REPO_ROOT = _THIS_FILE.parents[2]
_DATA_ROOT = _transcription_ROOT / "data"
_SHARED_ENV = _REPO_ROOT / "_shared" / ".env"
_LOCAL_ENV = _transcription_ROOT / ".env"

# Only load dotenv in non-production environments.
# In RunPod Serverless, the container should rely on real env vars set in the endpoint.
ENV = os.getenv("ENV", "development").lower()
if ENV != "production":
    if _SHARED_ENV.exists():
        load_dotenv(_SHARED_ENV, override=False)
    if _LOCAL_ENV.exists():
        load_dotenv(_LOCAL_ENV, override=True)


class Settings:
    """Application settings loaded from environment variables."""

    @staticmethod
    def _normalize_qdrant_url(raw_url: str) -> str:
        value = (raw_url or "").strip()
        if not value:
            return ""

        parsed = urlparse(value if "://" in value else f"https://{value}")
        if parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return value

    @staticmethod
    def _normalize_qdrant_api_key(raw_key: str) -> str:
        key = (raw_key or "").strip()
        if not key:
            return ""

        if "|" not in key:
            return key

        parts = [p.strip() for p in key.split("|") if p.strip()]
        if not parts:
            return key

        # Some env pipelines accidentally concatenate values with pipes.
        return max(parts, key=len)

    HF_TOKEN: str = os.getenv("HF_TOKEN", "")
    HUGGINGFACE_HUB_TOKEN: str = os.getenv("HUGGINGFACE_HUB_TOKEN", "")
    PYANNOTE_AUTH_TOKEN: str = os.getenv("PYANNOTE_AUTH_TOKEN", "")
    USE_AUTH_TOKEN: str = os.getenv("use_auth_token", "")

    # Preferred order: explicit pyannote token, generic HF token, hub token, legacy key.
    RESOLVED_HF_TOKEN: str = (
        PYANNOTE_AUTH_TOKEN
        or HF_TOKEN
        or HUGGINGFACE_HUB_TOKEN
        or USE_AUTH_TOKEN
    )

    # AI-Native (Phase 2)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "deepseek-v4-pro")
    ANTHROPIC_BASE_URL: str = os.getenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_ANALYZER_MODEL: str = os.getenv("DEEPSEEK_ANALYZER_MODEL", "deepseek-v4-flash")
    DEEPSEEK_RECONCILER_MODEL: str = os.getenv("DEEPSEEK_RECONCILER_MODEL", "deepseek-v4-pro")
    QDRANT_URL: str = _normalize_qdrant_url(os.getenv("QDRANT_URL", "http://localhost:6333"))
    QDRANT_API_KEY: str = _normalize_qdrant_api_key(os.getenv("QDRANT_API_KEY", ""))

    # RunPod Serverless
    RUNPOD_API_KEY: str = os.getenv("RUNPOD_API_KEY", "")
    RUNPOD_ENDPOINT_ID: str = os.getenv("RUNPOD_ENDPOINT_ID", "")
    RUNPOD_API_URL: str = os.getenv("RUNPOD_API_URL", "https://api.runpod.ai/v2")

    AUDIO_DIR: str = os.getenv("AUDIO_DIR", str(_DATA_ROOT / "audio"))
    ORIGINALS_DIR: str = os.getenv("ORIGINALS_DIR", str(_DATA_ROOT / "originals"))
    TRANSCRIPT_DIR: str = os.getenv("TRANSCRIPT_DIR", str(_DATA_ROOT / "transcripts"))
    REFERENCE_DIR: str = os.getenv("REFERENCE_DIR", str(_DATA_ROOT / "transcripts_by_audio"))
    NARRATIVE_DIR: str = os.getenv("NARRATIVE_DIR", str(_DATA_ROOT / "transcripts_narrative"))
    PROJECTS_DIR: str = os.getenv("PROJECTS_DIR", str(_DATA_ROOT / "projects"))
    SPEAKERS_DIR: str = os.getenv("SPEAKERS_DIR", str(_DATA_ROOT / "speakers"))
    SPEAKER_INDEX_FILE: str = os.getenv("SPEAKER_INDEX_FILE", str(_DATA_ROOT / "speaker_index.json"))

    # Law corpus index (see src/infrastructure/qdrant_law_index.py)
    LAW_DIR: str = os.getenv("LAW_DIR", str(_DATA_ROOT / "law"))
    # Shared production collections (payload store + BM25 sparse search store).
    LAW_COLLECTION: str = os.getenv("LAW_COLLECTION", "la8159_law")
    LAW_BM25_COLLECTION: str = os.getenv("LAW_BM25_COLLECTION", "la8159_law_bm25")
    # Repo-owned dense collection for real semantic search.
    LAW_LOCAL_COLLECTION: str = os.getenv("LAW_LOCAL_COLLECTION", "transcription_law")
    LAW_EMBED_MODEL: str = os.getenv("LAW_EMBED_MODEL", "all-MiniLM-L6-v2")
    # Locale preferred when the same ELI exists in several languages.
    LAW_PREFERRED_LANGUAGE: str = os.getenv("LAW_PREFERRED_LANGUAGE", "en")

    # Hardware acceleration
    TORCH_DEVICE: str = "cuda" if torch.cuda.is_available() else "cpu"
    TORCH_FLOAT: str = "fp16" if TORCH_DEVICE == "cuda" else "fp32"

    # CORS — explicit allowed origins (override via env)
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000,http://localhost:8080").split(",")
        if o.strip()
    ]

    # Validate-and-refine
    ENABLE_ACOUSTIC_PROBES: bool = os.getenv("ENABLE_ACOUSTIC_PROBES", "true").lower() == "true"
    ACOUSTIC_PROBE_TARGET_SR: int = int(os.getenv("ACOUSTIC_PROBE_TARGET_SR", "16000"))
    REFINE_GAP_THRESHOLD_S: float = float(os.getenv("REFINE_GAP_THRESHOLD_S", "4.0"))
    REFINE_SNR_ESCALATION_DB: float = float(os.getenv("REFINE_SNR_ESCALATION_DB", "6.0"))
    REFINE_SILENCE_DROP_RATIO: float = float(os.getenv("REFINE_SILENCE_DROP_RATIO", "0.6"))
    REFINE_MAX_ACOUSTIC_WINDOWS: int = int(os.getenv("REFINE_MAX_ACOUSTIC_WINDOWS", "8"))

    # Startup warmup can consume a lot of RAM on local CPU boxes.
    PRELOAD_MODELS: bool = os.getenv("PRELOAD_MODELS", "false").lower() == "true"
    PRELOAD_WHISPER_MODEL: str = os.getenv("PRELOAD_WHISPER_MODEL", "large-v3")

    def __init__(self):
        # Create data directories at runtime, not import time
        os.makedirs(self.AUDIO_DIR, exist_ok=True)
        os.makedirs(self.ORIGINALS_DIR, exist_ok=True)
        os.makedirs(self.TRANSCRIPT_DIR, exist_ok=True)
        os.makedirs(self.REFERENCE_DIR, exist_ok=True)
        os.makedirs(self.PROJECTS_DIR, exist_ok=True)
        os.makedirs(self.SPEAKERS_DIR, exist_ok=True)
        os.makedirs(self.LAW_DIR, exist_ok=True)


settings = Settings()
