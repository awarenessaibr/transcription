"""Use case: Full audio transcription with diarization."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Callable

from src.application.dto.schemas import (
    SegmentResult,
    TimingResult,
    TranscribeResult,
)
from src.domain.chilean_spanish import post_process_chilean_spanish
from src.domain.entities.transcript import Segment, Speaker, Transcript
from src.domain.entities.transcript import DiarizationTurn
from src.domain.ports.interfaces import (
    ASRPort,
    AudioFilePort,
    AudioProcessorPort,
    DiarizationPort,
    TranscriptIndexPort,
    TranscriptStorePort,
)

logger = logging.getLogger(__name__)

_SAFE_TRANSCRIPT_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")

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

# Type alias for the progress callback signature.
ProgressCallback = Callable[[str, int, str, dict | None], None] | None


def _transcript_id_from_saved_audio(saved_audio_path: str) -> str:
    """Build a filesystem-safe transcript id from a backend-saved audio path."""
    stem = Path(saved_audio_path).stem
    cleaned = _SAFE_TRANSCRIPT_ID_RE.sub("_", stem).strip("._-")
    return cleaned or f"transcript_{int(time.time())}"


def _merge_short_turns(
    turns: list[DiarizationTurn],
    *,
    min_turn_duration_s: float,
    merge_gap_s: float,
    max_segments: int,
) -> list[DiarizationTurn]:
    """Normalize diarization output to avoid micro-segment explosion.

    On CPU runs, many tiny turns can make Whisper calls extremely slow due to
    per-segment invocation overhead. This merge pass keeps timeline continuity
    while reducing pathological segmentation.
    """
    if not turns:
        return turns

    min_turn_duration_s = max(0.05, float(min_turn_duration_s))
    merge_gap_s = max(0.0, float(merge_gap_s))
    max_segments = max(1, int(max_segments))

    sorted_turns = sorted(turns, key=lambda t: (t.start, t.end))

    merged: list[DiarizationTurn] = []
    current = sorted_turns[0]

    for nxt in sorted_turns[1:]:
        if nxt.speaker == current.speaker and (nxt.start - current.end) <= merge_gap_s:
            current = DiarizationTurn(
                speaker=current.speaker,
                start=current.start,
                end=max(current.end, nxt.end),
            )
            continue
        merged.append(current)
        current = nxt
    merged.append(current)

    if not merged:
        return merged

    total_duration = max(0.0, merged[-1].end - merged[0].start)
    if len(merged) <= max_segments and total_duration <= 0:
        return merged

    adaptive_floor = total_duration / max_segments if total_duration > 0 else min_turn_duration_s
    effective_min = max(min_turn_duration_s, adaptive_floor)

    filtered = [t for t in merged if t.duration >= effective_min]
    if not filtered:
        longest = max(merged, key=lambda t: t.duration)
        filtered = [longest]

    if len(filtered) <= max_segments:
        return filtered

    trimmed = sorted(filtered, key=lambda t: t.duration, reverse=True)[:max_segments]
    return sorted(trimmed, key=lambda t: (t.start, t.end))


def _parse_suppress_tokens(raw: str) -> list[int]:
    """Parse the suppress_tokens parameter string into a list of integers."""
    if raw.strip() == "-1":
        return [-1]
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        return [-1]


class TranscribeAudioUseCase:
    """Orchestrates: save -> preprocess -> diarize -> transcribe -> persist."""

    def __init__(
        self,
        asr: ASRPort,
        diarizer: DiarizationPort,
        processor: AudioProcessorPort,
        store: TranscriptStorePort,
        audio_files: AudioFilePort,
        index: TranscriptIndexPort | None = None,
    ):
        self._asr = asr
        self._diarizer = diarizer
        self._processor = processor
        self._store = store
        self._audio_files = audio_files
        self._index = index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        filename: str,
        content: bytes,
        dest_dir: str,
        params: dict,
    ) -> TranscribeResult:
        t_global = time.time()

        # -- extract cli params --------------------------------------------------
        language = params.get("language", "es")
        model_size = params.get("model_size", "large-v3")
        min_speakers = params.get("min_speakers", 1)
        max_speakers = params.get("max_speakers", 2)
        vad_threshold = params.get("vad_threshold", 0.25)
        keep_cache = params.get("keep_cache", True)
        keep_audio_artifacts = params.get("keep_audio_artifacts", True)
        diarization_timeout_s = float(params.get("diarization_timeout_s", 500.0))
        min_turn_duration_s = float(params.get("min_turn_duration_s", 0.0))
        merge_gap_s = float(params.get("merge_gap_s", 0.0))
        max_diarization_segments = int(params.get("max_diarization_segments", 1000))
        skip_diarization = bool(params.get("skip_diarization", False))
        progress_callback = params.get("progress_callback")
        suppress_tokens_raw = params.get("suppress_tokens", "-1")
        parsed_suppress_tokens = _parse_suppress_tokens(suppress_tokens_raw)
        whisper_lang = LANGUAGE_MAP.get(language)

        # -- progress helper ----------------------------------------------------
        current_progress = 0

        async def emit_progress(
            stage: str, progress: int, message: str, extra: dict | None = None
        ):
            nonlocal current_progress
            current_progress = max(current_progress, int(progress))
            if callable(progress_callback):
                try:
                    progress_callback(stage, int(progress), message, extra)
                except Exception:
                    logger.debug("[progress] callback failed", exc_info=True)
            await asyncio.sleep(0)

        audio_path = None
        processed_path = None

        try:
            await emit_progress("upload", 4, "Upload recebido")

            # ---- stage 1: save & convert --------------------------------------
            audio_path, save_elapsed, convert_elapsed, transcript_source_file = (
                await self._save_and_convert(filename, content, dest_dir, emit_progress)
            )

            transcript_id = _transcript_id_from_saved_audio(audio_path)

            # ---- stage 2: preprocess -------------------------------------------
            processed_path, preprocess_elapsed = await self._preprocess_audio(
                audio_path, params, emit_progress
            )

            # ---- stage 3: diarization ------------------------------------------
            turns, diarization_elapsed, diarization_fallback, diarization_fallback_reason, raw_turn_count = (
                await self._run_diarization(
                    processed_path,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                    vad_threshold=vad_threshold,
                    diarization_timeout_s=diarization_timeout_s,
                    min_turn_duration_s=min_turn_duration_s,
                    merge_gap_s=merge_gap_s,
                    max_diarization_segments=max_diarization_segments,
                    skip_diarization=skip_diarization,
                    emit_progress=emit_progress,
                )
            )

            # ---- stage 4: transcribe segments ----------------------------------
            segments, transcription_elapsed_total = await self._transcribe_segments(
                processed_path=processed_path,
                turns=turns,
                whisper_lang=whisper_lang,
                model_size=model_size,
                params=params,
                parsed_suppress_tokens=parsed_suppress_tokens,
                emit_progress=emit_progress,
            )

            # ---- stage 5: persist ----------------------------------------------
            transcript = self._build_and_persist_transcript(
                transcript_id=transcript_id,
                segments=segments,
                transcript_source_file=transcript_source_file or filename,
                language=language,
                processed_path=processed_path,
            )
            await emit_progress("transcription", 95, "Transcrição consolidada")

            # ---- stage 6: index ------------------------------------------------
            await self._index_transcript(transcript)

            # ---- summary -------------------------------------------------------
            total_elapsed = time.time() - t_global
            logger.info(
                "[summary] file='%s' total=%.2fs save=%.2f convert=%.2f "
                "preprocess=%.2f diar=%.2f transcribe=%.2f segments=%d",
                filename, total_elapsed, save_elapsed, convert_elapsed,
                preprocess_elapsed, diarization_elapsed,
                transcription_elapsed_total, len(segments),
            )
            await emit_progress(
                "transcription", 100, "Concluído", {"transcript_id": transcript_id}
            )

            model_load_elapsed = 0.0  # tracked inside adapter

            return TranscribeResult(
                transcript_id=transcript_id,
                segments=segments,
                timings=TimingResult(
                    save_s=round(save_elapsed, 2),
                    convert_s=round(convert_elapsed, 2),
                    preprocess_s=round(preprocess_elapsed, 2),
                    diarization_s=round(diarization_elapsed, 2),
                    model_load_s=round(model_load_elapsed, 2),
                    transcription_s=round(transcription_elapsed_total, 2),
                    total_s=round(total_elapsed, 2),
                ),
                params={
                    "model_size": model_size,
                    "language": language,
                    "diarization_fallback": diarization_fallback,
                    "diarization_fallback_reason": diarization_fallback_reason,
                    "beam_size": params.get("beam_size", 9),
                    "best_of": params.get("best_of", 8),
                    "temperature": params.get("whisper_temp", 0.0),
                    "vad_threshold": vad_threshold,
                    "diarization_timeout_s": diarization_timeout_s,
                    "min_turn_duration_s": min_turn_duration_s,
                    "merge_gap_s": merge_gap_s,
                    "max_diarization_segments": max_diarization_segments,
                    "noise_reduce": params.get("noise_reduce", True),
                    "reduction_db": params.get("reduction_db", 25),
                    "voice_enhance": params.get("voice_enhance", True),
                    "apply_gain": params.get("apply_gain", True),
                    "target_lufs": params.get("target_lufs", -16.0),
                    "remove_silence": params.get("remove_silence", True),
                    "silence_thresh": params.get("silence_thresh", -45),
                    "min_silence_len": params.get("min_silence_len", 250),
                    "word_timestamps": params.get("word_timestamps", False),
                    "keep_audio_artifacts": keep_audio_artifacts,
                    "saved_audio_file": transcript_source_file,
                    "processed_audio_file": os.path.basename(processed_path) if processed_path else "",
                },
            )

        except Exception as e:
            await emit_progress(
                "transcription", max(current_progress, 1), f"Erro: {e}", {"error": str(e)}
            )
            raise

        finally:
            self._cleanup_artifacts(
                audio_path=audio_path,
                processed_path=processed_path,
                keep_audio_artifacts=keep_audio_artifacts,
                keep_cache=keep_cache,
            )

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    async def _save_and_convert(
        self,
        filename: str,
        content: bytes,
        dest_dir: str,
        emit_progress: Callable,
    ) -> tuple[str, float, float, str]:
        """Save uploaded bytes and convert to WAV.

        Returns (audio_path, save_elapsed, convert_elapsed, transcript_source_file).
        """
        # 1. Save upload
        t_step = time.time()
        audio_path = await self._audio_files.save_upload(filename, content, dest_dir)
        save_elapsed = time.time() - t_step
        logger.info(
            "[save] stored %s size=%dB elapsed=%.2fs", audio_path, len(content), save_elapsed
        )
        await emit_progress("upload", 10, "Arquivo salvo", {"bytes": len(content)})

        # 2. Convert to WAV
        t_step = time.time()
        audio_path = self._audio_files.convert_to_wav(audio_path)
        convert_elapsed = time.time() - t_step
        transcript_source_file = os.path.basename(audio_path)
        await emit_progress("preprocess", 18, "Convertendo para WAV")

        return audio_path, save_elapsed, convert_elapsed, transcript_source_file

    async def _preprocess_audio(
        self,
        audio_path: str,
        params: dict,
        emit_progress: Callable,
    ) -> tuple[str, float]:
        """Run audio preprocessing and return (processed_path, preprocess_elapsed)."""
        t_step = time.time()
        processed_path = self._processor.process(audio_path, {
            "noise_reduce": params.get("noise_reduce", True),
            "reduction_db": params.get("reduction_db", 25),
            "voice_enhance": params.get("voice_enhance", True),
            "apply_gain": params.get("apply_gain", True),
            "target_lufs": params.get("target_lufs", -16.0),
            "remove_silence": params.get("remove_silence", True),
            "silence_thresh": params.get("silence_thresh", -45),
            "min_silence_len": params.get("min_silence_len", 250),
        })
        preprocess_elapsed = time.time() - t_step
        logger.info("[prep] processed=%s elapsed=%.2fs", processed_path, preprocess_elapsed)
        await emit_progress("preprocess", 42, "Pré-processamento concluído")
        return processed_path, preprocess_elapsed

    async def _run_diarization(
        self,
        processed_path: str,
        *,
        min_speakers: int,
        max_speakers: int,
        vad_threshold: float,
        diarization_timeout_s: float,
        min_turn_duration_s: float,
        merge_gap_s: float,
        max_diarization_segments: int,
        skip_diarization: bool = False,
        emit_progress: Callable,
    ) -> tuple[list[DiarizationTurn], float, bool, str | None, int]:
        """Run speaker diarization with fallback handling.

        When ``skip_diarization`` is True the whole clip is treated as a single
        speaker turn (no pyannote call), so the pipeline returns one segment.

        Returns (turns, diarization_elapsed, fallback, fallback_reason, raw_turn_count).
        """
        t_step = time.time()
        diarization_fallback = False
        diarization_fallback_reason = None
        await emit_progress("diarization", 50, "Iniciando diarização")

        def _single_speaker_fallback() -> list[DiarizationTurn]:
            duration_s = float(self._audio_files.get_duration(processed_path))
            return [
                DiarizationTurn(speaker="SPEAKER_00", start=0.0, end=duration_s)
            ]

        if skip_diarization:
            turns = _single_speaker_fallback()
            diarization_fallback = True
            diarization_fallback_reason = "skipped_by_request"
            logger.info("[diarization] skipped by request; single-speaker mode")
            raw_turn_count = len(turns)
            diarization_elapsed = time.time() - t_step
            await emit_progress(
                "diarization", 65,
                "Diarização ignorada (1 segmento)",
                {
                    "segments": len(turns),
                    "raw_segments": raw_turn_count,
                    "fallback": diarization_fallback,
                    "fallback_reason": diarization_fallback_reason,
                },
            )
            return (
                turns, diarization_elapsed, diarization_fallback,
                diarization_fallback_reason, raw_turn_count,
            )

        try:
            turns = await asyncio.wait_for(
                asyncio.to_thread(
                    self._diarizer.diarize,
                    processed_path,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                    vad_threshold=vad_threshold,
                ),
                timeout=diarization_timeout_s,
            )
        except asyncio.TimeoutError:
            turns = _single_speaker_fallback()
            diarization_fallback = True
            diarization_fallback_reason = "pyannote_timeout"
            logger.warning(
                "[diarization] timeout after %.1fs; fallback to single-speaker mode",
                diarization_timeout_s,
            )
        except ValueError as e:
            if "Pyannote auth token missing" not in str(e):
                raise
            turns = _single_speaker_fallback()
            diarization_fallback = True
            diarization_fallback_reason = "pyannote_token_missing"
            logger.warning("[diarization] pyannote token missing; fallback to single-speaker mode")
        except Exception as e:
            turns = _single_speaker_fallback()
            diarization_fallback = True
            diarization_fallback_reason = "pyannote_runtime_unavailable"
            logger.warning("[diarization] unavailable (%s); fallback to single-speaker mode", e)

        if not turns:
            turns = _single_speaker_fallback()
            diarization_fallback = True
            diarization_fallback_reason = "pyannote_empty_turns"
            logger.warning("[diarization] no speaker turns returned; fallback to single-speaker mode")

        raw_turn_count = len(turns)
        if (
            min_turn_duration_s > 0
            or merge_gap_s > 0
            or max_diarization_segments < raw_turn_count
        ):
            turns = _merge_short_turns(
                turns,
                min_turn_duration_s=min_turn_duration_s,
                merge_gap_s=merge_gap_s,
                max_segments=max_diarization_segments,
            )

        diarization_elapsed = time.time() - t_step
        logger.info(
            "[diarization] segments=%d raw=%d elapsed=%.2fs",
            len(turns), raw_turn_count, diarization_elapsed,
        )
        await emit_progress(
            "diarization", 65,
            f"Diarização concluída com {len(turns)} segmentos",
            {
                "segments": len(turns),
                "raw_segments": raw_turn_count,
                "fallback": diarization_fallback,
                "fallback_reason": diarization_fallback_reason,
            },
        )

        return (
            turns, diarization_elapsed, diarization_fallback,
            diarization_fallback_reason, raw_turn_count,
        )

    async def _transcribe_segments(
        self,
        *,
        processed_path: str,
        turns: list[DiarizationTurn],
        whisper_lang: str | None,
        model_size: str,
        params: dict,
        parsed_suppress_tokens: list[int],
        emit_progress: Callable,
    ) -> tuple[list[SegmentResult], float]:
        """Transcribe each diarized segment via ASR.

        Returns (segments, transcription_elapsed_total).
        """
        segments: list[SegmentResult] = []
        transcription_elapsed_total = 0.0
        total_turns = max(1, len(turns))

        is_spanish_request = whisper_lang in ("es", "es-CL")
        detected_language: str | None = None

        for idx, turn in enumerate(turns, 1):
            progress_before = 66 + int(((idx - 1) / total_turns) * 27)
            await emit_progress(
                "transcription", progress_before,
                f"Transcrevendo segmento {idx}/{total_turns}",
                {"segment_index": idx, "segment_total": total_turns},
            )

            seg_start_ms = int(turn.start * 1000)
            seg_end_ms = int(turn.end * 1000)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as seg_file:
                seg_path = self._audio_files.extract_segment(
                    processed_path, seg_start_ms, seg_end_ms, seg_file.name
                )

            t_seg = time.time()
            asr_result = self._asr.transcribe(
                seg_path,
                language=whisper_lang,
                model_size=model_size,
                temperature=params.get("whisper_temp", 0.0),
                beam_size=params.get("beam_size", 5),
                best_of=params.get("best_of", 5),
                compression_ratio_threshold=params.get("compression_ratio_threshold", 2.4),
                logprob_threshold=params.get("logprob_threshold", -1.0),
                no_speech_threshold=params.get("no_speech_threshold", 0.6),
                condition_on_previous_text=params.get("condition_on_previous_text", False),
                initial_prompt=params.get("initial_prompt"),
                length_penalty=params.get("length_penalty", 1.0),
                patience=params.get("patience"),
                suppress_blank=params.get("suppress_blank", True),
                suppress_tokens=parsed_suppress_tokens,
                word_timestamps=params.get("word_timestamps", False),
            )
            raw_text = asr_result.get("text", "") if isinstance(asr_result, dict) else asr_result
            if idx == 1 and isinstance(asr_result, dict):
                detected_language = asr_result.get("language")
            seg_elapsed = time.time() - t_seg
            transcription_elapsed_total += seg_elapsed

            # Clean up temp segment file
            if os.path.exists(seg_path):
                os.remove(seg_path)

            resolved_lang = detected_language or whisper_lang
            is_spanish = resolved_lang in ("es", "es-CL") or is_spanish_request
            text = post_process_chilean_spanish(raw_text) if is_spanish else raw_text
            logger.info(
                "[segment %d] speaker=%s %.2f-%.2fs chars=%d elapsed=%.2fs",
                idx, turn.speaker, turn.start, turn.end, len(text), seg_elapsed,
            )

            progress_after = 66 + int((idx / total_turns) * 27)
            await emit_progress(
                "transcription", progress_after,
                f"Segmento {idx}/{total_turns} concluído",
                {"segment_index": idx, "segment_total": total_turns, "speaker": turn.speaker},
            )

            segments.append(SegmentResult(
                index=idx,
                speaker=turn.speaker,
                start=turn.start,
                end=turn.end,
                duration=turn.duration,
                text=text,
            ))

        return segments, transcription_elapsed_total

    def _build_and_persist_transcript(
        self,
        transcript_id: str,
        segments: list[SegmentResult],
        transcript_source_file: str,
        language: str,
        processed_path: str | None,
    ) -> Transcript:
        """Build domain entities, save to store, and return the Transcript."""
        domain_segments = [
            Segment(
                index=s.index,
                speaker=Speaker(label=s.speaker),
                start=s.start,
                end=s.end,
                text=s.text,
            )
            for s in segments
        ]
        transcript = Transcript(
            transcript_id=transcript_id,
            segments=domain_segments,
            source_file=transcript_source_file,
            language=language,
            metadata={
                "saved_audio_file": transcript_source_file,
                "processed_audio_file": os.path.basename(processed_path) if processed_path else "",
            },
        )
        self._store.save(transcript)
        return transcript

    async def _index_transcript(self, transcript: Transcript) -> None:
        """Auto-index transcript into vector store (if configured)."""
        if self._index is None:
            return
        try:
            n = await self._index.index(transcript)
            logger.info("[qdrant] auto-indexed %d segments for %s", n, transcript.transcript_id)
        except Exception as e:
            logger.warning("[qdrant] auto-index failed: %s", e)

    def _cleanup_artifacts(
        self,
        *,
        audio_path: str | None,
        processed_path: str | None,
        keep_audio_artifacts: bool,
        keep_cache: bool,
    ) -> None:
        """Remove temporary audio files and optionally clear ASR cache."""
        if keep_audio_artifacts:
            return
        import contextlib

        if processed_path and os.path.exists(processed_path):
            with contextlib.suppress(Exception):
                os.remove(processed_path)
        if audio_path and os.path.exists(audio_path):
            with contextlib.suppress(Exception):
                os.remove(audio_path)
        if not keep_cache and hasattr(self._asr, "clear_cache"):
            self._asr.clear_cache()
