"""Shared dependency wiring for FastAPI and MCP servers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .application.use_cases.diarize_excerpt import DiarizeExcerptUseCase
from .application.use_cases.guided_transcribe import ReferenceGuidedTranscribeUseCase
from .application.use_cases.transcribe_audio import TranscribeAudioUseCase
from .config import settings
from .infrastructure.audio_file_adapter import AudioFileAdapter
from .infrastructure.json_store import JSONTranscriptStore
from .infrastructure.model_manager import ModelManager
from .infrastructure.narrative_store_adapter import NarrativeStoreAdapter
from .infrastructure.project_store_adapter import ProjectStoreAdapter
from .infrastructure.pyannote_adapter import PyAnnoteDiarizerAdapter
from .infrastructure.pydub_processor import PydubProcessorAdapter
from .infrastructure.reference_store_adapter import ReferenceStoreAdapter
from .infrastructure.whisper_adapter import WhisperASRAdapter

logger = logging.getLogger(__name__)


@dataclass
class transcriptionRuntime:
    """Fully wired runtime dependencies and use cases."""

    model_manager: ModelManager
    asr_adapter: WhisperASRAdapter
    diarizer_adapter: PyAnnoteDiarizerAdapter
    processor_adapter: PydubProcessorAdapter
    store_adapter: JSONTranscriptStore
    audio_file_adapter: AudioFileAdapter
    ref_store_adapter: ReferenceStoreAdapter
    narrative_store_adapter: NarrativeStoreAdapter
    project_store_adapter: ProjectStoreAdapter

    qdrant_adapter: Any = None
    reconciler_adapter: Any = None
    analyze_use_case: Any = None
    search_use_case: Any = None

    transcribe_use_case: TranscribeAudioUseCase | None = None
    excerpt_use_case: DiarizeExcerptUseCase | None = None
    guided_transcribe_use_case: ReferenceGuidedTranscribeUseCase | None = None

    auditor: Any = None
    patcher: Any = None
    probe_adapter: Any = None
    validate_refine_use_case: Any = None


def build_runtime() -> transcriptionRuntime:
    """Build full runtime dependency graph from environment settings."""
    model_manager = ModelManager()
    asr_adapter = WhisperASRAdapter(model_manager)
    diarizer_adapter = PyAnnoteDiarizerAdapter(model_manager, settings.RESOLVED_HF_TOKEN)
    processor_adapter = PydubProcessorAdapter()
    store_adapter = JSONTranscriptStore(settings.TRANSCRIPT_DIR)
    audio_file_adapter = AudioFileAdapter()
    ref_store_adapter = ReferenceStoreAdapter(settings.REFERENCE_DIR)
    narrative_store_adapter = NarrativeStoreAdapter(settings.NARRATIVE_DIR)
    project_store_adapter = ProjectStoreAdapter(settings.PROJECTS_DIR)

    runtime = transcriptionRuntime(
        model_manager=model_manager,
        asr_adapter=asr_adapter,
        diarizer_adapter=diarizer_adapter,
        processor_adapter=processor_adapter,
        store_adapter=store_adapter,
        audio_file_adapter=audio_file_adapter,
        ref_store_adapter=ref_store_adapter,
        narrative_store_adapter=narrative_store_adapter,
        project_store_adapter=project_store_adapter,
    )

    if settings.ANTHROPIC_API_KEY:
        from .application.use_cases.analyze_transcript import AnalyzeTranscriptUseCase
        from .infrastructure.claude_analyzer import ClaudeAnalyzerAdapter
        from .infrastructure.claude_reconciler import ClaudeReconcilerAdapter

        claude_adapter = ClaudeAnalyzerAdapter(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.ANTHROPIC_MODEL,
            base_url=settings.ANTHROPIC_BASE_URL,
        )
        runtime.analyze_use_case = AnalyzeTranscriptUseCase(
            analyzer=claude_adapter,
            store=store_adapter,
        )
        logger.info("[ai] Claude analyzer configured (model=%s)", settings.ANTHROPIC_MODEL)

        if settings.DEEPSEEK_API_KEY:
            from .infrastructure.deepseek_reconciler import DeepSeekReconcilerAdapter

            runtime.reconciler_adapter = DeepSeekReconcilerAdapter(
                api_key=settings.DEEPSEEK_API_KEY,
                model=settings.DEEPSEEK_RECONCILER_MODEL,
            )
            logger.info(
                "[ai] DeepSeek reconciler configured (model=%s)",
                settings.DEEPSEEK_RECONCILER_MODEL,
            )
        else:
            runtime.reconciler_adapter = ClaudeReconcilerAdapter(
                api_key=settings.ANTHROPIC_API_KEY,
                model=settings.ANTHROPIC_MODEL,
                base_url=settings.ANTHROPIC_BASE_URL,
            )
            logger.info("[ai] Claude reconciler configured (model=%s)", settings.ANTHROPIC_MODEL)
    elif settings.DEEPSEEK_API_KEY:
        from .application.use_cases.analyze_transcript import AnalyzeTranscriptUseCase
        from .infrastructure.deepseek_analyzer import DeepSeekAnalyzerAdapter
        from .infrastructure.deepseek_reconciler import DeepSeekReconcilerAdapter

        deepseek_analyzer = DeepSeekAnalyzerAdapter(
            api_key=settings.DEEPSEEK_API_KEY,
            model=settings.DEEPSEEK_ANALYZER_MODEL,
        )
        runtime.analyze_use_case = AnalyzeTranscriptUseCase(
            analyzer=deepseek_analyzer,
            store=store_adapter,
        )
        runtime.reconciler_adapter = DeepSeekReconcilerAdapter(
            api_key=settings.DEEPSEEK_API_KEY,
            model=settings.DEEPSEEK_RECONCILER_MODEL,
        )
        logger.info("[ai] DeepSeek analyzer + reconciler configured (no Anthropic key)")
    else:
        logger.info("[ai] Transcript analysis disabled — set ANTHROPIC_API_KEY or DEEPSEEK_API_KEY")

    if settings.QDRANT_URL:
        try:
            from .application.use_cases.search_transcripts import SearchTranscriptsUseCase
            from .infrastructure.qdrant_index import QdrantTranscriptIndex

            runtime.qdrant_adapter = QdrantTranscriptIndex(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
            )
            # Suppress version compatibility warning - minor version differences are compatible
            if hasattr(runtime.qdrant_adapter, 'client') and hasattr(runtime.qdrant_adapter.client, '_check_compatibility'):
                runtime.qdrant_adapter.client._check_compatibility = False
            runtime.search_use_case = SearchTranscriptsUseCase(index=runtime.qdrant_adapter)
            logger.info("[ai] Qdrant index configured (url=%s)", settings.QDRANT_URL)
        except Exception as exc:
            logger.warning("[ai] Qdrant index disabled — connection failed: %s", exc)
            runtime.qdrant_adapter = None
            runtime.search_use_case = None

    runtime.transcribe_use_case = TranscribeAudioUseCase(
        asr=asr_adapter,
        diarizer=diarizer_adapter,
        processor=processor_adapter,
        store=store_adapter,
        audio_files=audio_file_adapter,
        index=runtime.qdrant_adapter,
    )
    runtime.excerpt_use_case = DiarizeExcerptUseCase(
        diarizer=diarizer_adapter,
        audio_files=audio_file_adapter,
    )
    runtime.guided_transcribe_use_case = ReferenceGuidedTranscribeUseCase(
        asr=asr_adapter,
        diarizer=diarizer_adapter,
        processor=processor_adapter,
        store=store_adapter,
        audio_files=audio_file_adapter,
        ref_store=ref_store_adapter,
        reconciler=runtime.reconciler_adapter,
        narrative_store=narrative_store_adapter,
        index=runtime.qdrant_adapter,
    )

    # Validate-and-refine wiring
    from .application.services.transcript_auditor import TranscriptAuditor
    from .application.services.transcript_patcher import TranscriptPatcher
    from .application.use_cases.validate_and_refine_transcript import (
        ValidateAndRefineTranscriptUseCase,
    )

    runtime.auditor = TranscriptAuditor(
        gap_threshold_s=settings.REFINE_GAP_THRESHOLD_S,
    )
    runtime.patcher = TranscriptPatcher()

    if settings.ENABLE_ACOUSTIC_PROBES:
        try:
            from .infrastructure.torchaudio_probe_adapter import TorchaudioProbeAdapter

            runtime.probe_adapter = TorchaudioProbeAdapter(
                target_sample_rate=settings.ACOUSTIC_PROBE_TARGET_SR,
            )
            logger.info("[refine] acoustic probes enabled (torchaudio)")
        except Exception as exc:
            logger.warning(
                "[refine] acoustic probes disabled — torchaudio import failed: %s",
                exc,
            )
            runtime.probe_adapter = None
    else:
        runtime.probe_adapter = None
        logger.info("[refine] acoustic probes disabled by ENABLE_ACOUSTIC_PROBES=false")

    runtime.validate_refine_use_case = ValidateAndRefineTranscriptUseCase(
        store=store_adapter,
        ref_store=ref_store_adapter,
        narrative_store=narrative_store_adapter,
        reconciler=runtime.reconciler_adapter,
        auditor=runtime.auditor,
        patcher=runtime.patcher,
        processor=processor_adapter,
        diarizer=diarizer_adapter,
        asr=asr_adapter,
        audio_files=audio_file_adapter,
        probe=runtime.probe_adapter,
    )
    return runtime