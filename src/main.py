"""SA-transcription — Composition Root.

Wires domain ports → infrastructure adapters → use cases → routers.
This file is the ONLY place where all layers know about each other.
"""
import asyncio
import logging
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .composition import build_runtime
from .config import settings
from .llm.router import router as llm_router
from .logging_setup import setup_logging
from .presentation.routers.diarization import init_diarization_router
from .presentation.routers.diarization import router as diarization_router

# Presentation routers
from .presentation.routers.health import router as health_router
from .presentation.routers.law_registry import router as law_registry_router
from .presentation.routers.parameters import router as parameters_router
from .presentation.routers.pinocchio import router as pinocchio_router
from .presentation.routers.projects import init_projects_router
from .presentation.routers.projects import router as projects_router
from .presentation.routers.references import init_references_router
from .presentation.routers.references import router as references_router
from .presentation.routers.speakers import router as speakers_router
from .presentation.routers.transcription import init_transcription_router
from .presentation.routers.transcription import router as transcription_router
from .presentation.routers.transcripts import init_transcript_router
from .presentation.routers.transcripts import router as transcripts_router

# ── Setup ────────────────────────────────────────────────────────────────
setup_logging()
logger = logging.getLogger(__name__)

runtime = build_runtime()

# ── Router Injection ─────────────────────────────────────────────────────
init_diarization_router(runtime.excerpt_use_case, runtime.audio_file_adapter, settings.TRANSCRIPT_DIR)
init_transcription_router(
    runtime.transcribe_use_case,
    settings.ORIGINALS_DIR,
    guided_use_case=runtime.guided_transcribe_use_case,
    audio_file_adapter=runtime.audio_file_adapter,
    project_store=runtime.project_store_adapter,
)
init_transcript_router(
    runtime.analyze_use_case,
    runtime.search_use_case,
    runtime.store_adapter,
    runtime.qdrant_adapter,
    auditor=runtime.auditor,
    patcher=runtime.patcher,
    validate_refine_use_case=runtime.validate_refine_use_case,
    asr_adapter=runtime.asr_adapter,
    audio_file_adapter=runtime.audio_file_adapter,
)
init_projects_router(runtime.project_store_adapter, runtime.ref_store_adapter)
init_references_router(
    runtime.ref_store_adapter,
    runtime.narrative_store_adapter,
    settings.REFERENCE_DIR,
)


# ── FastAPI App ──────────────────────────────────────────────────────────
app = FastAPI(title="SA transcription Transcription API")

# CORS — explicit origins, not wildcard
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(parameters_router)
app.include_router(diarization_router)
app.include_router(transcription_router)
app.include_router(transcripts_router)
app.include_router(projects_router)
app.include_router(references_router)
app.include_router(pinocchio_router)
app.include_router(llm_router)
app.include_router(speakers_router)
app.include_router(law_registry_router)

# Serve frontend assets (shared LLM provider UI)
_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
_STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# Serve static data directories
app.mount("/audio", StaticFiles(directory=settings.AUDIO_DIR), name="audio")
app.mount("/originals", StaticFiles(directory=settings.ORIGINALS_DIR), name="originals")
app.mount("/transcripts", StaticFiles(directory=settings.TRANSCRIPT_DIR), name="transcripts")
app.mount("/speakers", StaticFiles(directory=settings.SPEAKERS_DIR), name="speakers")


@app.on_event("startup")
async def preload():
    """Kick off non-blocking background preload of heavy models."""
    log = logging.getLogger("startup")

    if not settings.PRELOAD_MODELS:
        log.info("Model preload disabled (PRELOAD_MODELS=false)")
        return

    t = time.time()
    whisper_model = (settings.PRELOAD_WHISPER_MODEL or "small").strip() or "small"

    async def _preload():
        try:
            await asyncio.to_thread(
                runtime.model_manager.get_diarization_pipeline,
                settings.RESOLVED_HF_TOKEN,
            )
            await asyncio.to_thread(runtime.model_manager.get_whisper_model, whisper_model)
            log.info("Preload done in %.2fs (whisper=%s)", time.time() - t, whisper_model)
        except Exception as e:
            log.warning(f"Preload skipped: {e}")

    asyncio.create_task(_preload())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8049)
