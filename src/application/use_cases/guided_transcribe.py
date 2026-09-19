"""Use case: Reference-guided audio transcription.

Orchestrates: load references → build initial_prompt → Whisper ASR →
diarization → merge → LLM reconciliation → persist → index.
"""
from __future__ import annotations

import logging
import time

from src.domain.entities.reference import ReferenceTranscript
from src.domain.entities.transcript import Segment, Speaker, Transcript
from src.domain.ports.interfaces import (
    ASRPort,
    AudioFilePort,
    AudioProcessorPort,
    DiarizationPort,
    NarrativeStorePort,
    ReferenceStorePort,
    TranscriptIndexPort,
    TranscriptReconcilerPort,
    TranscriptStorePort,
)

logger = logging.getLogger(__name__)

# Max characters from reference text to use as Whisper initial_prompt
_INITIAL_PROMPT_MAX_CHARS = 1500

# Default number of top-quality references to send to the reconciler
_DEFAULT_TOP_N_REFERENCES = 3


class ReferenceGuidedTranscribeUseCase:
    """Transcribe audio using existing corrected transcripts as priors."""

    def __init__(
        self,
        asr: ASRPort,
        diarizer: DiarizationPort,
        processor: AudioProcessorPort,
        store: TranscriptStorePort,
        audio_files: AudioFilePort,
        ref_store: ReferenceStorePort,
        reconciler: TranscriptReconcilerPort,
        narrative_store: NarrativeStorePort | None = None,
        index: TranscriptIndexPort | None = None,
    ):
        self._asr = asr
        self._diarizer = diarizer
        self._processor = processor
        self._store = store
        self._audio_files = audio_files
        self._ref_store = ref_store
        self._reconciler = reconciler
        self._narrative_store = narrative_store
        self._index = index

    async def execute(
        self,
        audio_path: str,
        canonical_name: str,
        params: dict,
    ) -> dict:
        """Run full reference-guided transcription pipeline.

        Args:
            audio_path: Path to audio file on disk.
            canonical_name: Key for reference store lookup (e.g. "aeropuerto_stg_7").
            params: Whisper/diarization/preprocessing parameters.

        Returns:
            Dict with transcript_id, segments, speaker_map, timings, reconciliation metadata.
        """
        t_global = time.time()
        language = params.get("language", "es")
        model_size = params.get("model_size", "large-v3")

        # ── Step 1: Load references ───────────────────────────────────────
        t_step = time.time()
        references = self._ref_store.load_references(canonical_name)
        ref_load_elapsed = time.time() - t_step

        best_ref = references[0] if references else None
        logger.info(
            "[guided] loaded %d references for '%s' (best: %s, quality=%.2f) in %.2fs",
            len(references),
            canonical_name,
            best_ref.title if best_ref else "none",
            best_ref.quality_score if best_ref else 0,
            ref_load_elapsed,
        )

        # ── Step 1b: Load narratives ──────────────────────────────────────
        narratives = []
        if self._narrative_store:
            narratives = self._narrative_store.load_narratives(canonical_name)
            logger.info(
                "[guided] loaded %d narratives for '%s'",
                len(narratives),
                canonical_name,
            )
        best_narrative = narratives[0] if narratives else None

        # ── Step 2: Build initial_prompt from reference ───────────────────
        initial_prompt = self._build_initial_prompt(best_ref, language)
        if initial_prompt:
            logger.info("[guided] initial_prompt: %d chars", len(initial_prompt))

        # ── Step 3: Convert + preprocess audio ────────────────────────────
        t_step = time.time()
        wav_path = self._audio_files.convert_to_wav(audio_path)
        processed_path = self._processor.process(wav_path, {
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

        # ── Step 4: Whisper ASR (full file, not segmented) ────────────────
        t_step = time.time()
        asr_result = self._asr.transcribe(
            processed_path,
            language=language,
            model_size=model_size,
            temperature=params.get("whisper_temp", 0.0),
            beam_size=params.get("beam_size", 5),
            best_of=params.get("best_of", 5),
            initial_prompt=initial_prompt,
            condition_on_previous_text=params.get("condition_on_previous_text", True),
            word_timestamps=params.get("word_timestamps", False),
        )
        raw_text = asr_result.get("text", "") if isinstance(asr_result, dict) else asr_result
        asr_elapsed = time.time() - t_step
        logger.info("[guided] ASR complete: %d chars in %.2fs", len(raw_text), asr_elapsed)

        # ── Step 5: Diarization ───────────────────────────────────────────
        t_step = time.time()
        turns = self._diarizer.diarize(
            processed_path,
            min_speakers=params.get("min_speakers", 1),
            max_speakers=params.get("max_speakers", len(best_ref.participants) if best_ref else 4),
            vad_threshold=params.get("vad_threshold", 0.25),
        )
        diar_elapsed = time.time() - t_step
        logger.info("[guided] diarization: %d turns in %.2fs", len(turns), diar_elapsed)

        # ── Step 6: Build raw segments (merged ASR + diarization) ─────────
        raw_segments = self._build_raw_segments(raw_text, turns)
        logger.info("[guided] merged %d raw segments", len(raw_segments))

        # ── Step 7: LLM Reconciliation ────────────────────────────────────
        reconciliation: dict = {}
        top_n = int(params.get("top_n_references", _DEFAULT_TOP_N_REFERENCES))
        priors = references[:top_n] if references else []
        if best_ref and self._reconciler:
            t_step = time.time()
            reconciliation = await self._reconciler.reconcile(
                raw_segments,
                best_ref,
                narrative=best_narrative,
                language=language,
                references=priors,
            )
            reconcile_elapsed = time.time() - t_step
            reconciled_segments = reconciliation.get("segments", raw_segments)
            speaker_map = reconciliation.get("speaker_map", {})
            reconciliation_meta = reconciliation.get("_meta", {})
            logger.info(
                "[guided] reconciled %d segments using %d priors (map=%s) in %.2fs",
                len(reconciled_segments),
                len(priors),
                speaker_map,
                reconcile_elapsed,
            )
        else:
            reconciled_segments = raw_segments
            speaker_map = {}
            reconciliation_meta = {}
            reconcile_elapsed = 0.0
            logger.info("[guided] no reference available — skipping reconciliation")

        # ── Step 8: Persist transcript ────────────────────────────────────
        transcript_id = f"guided_{canonical_name}_{int(time.time())}"
        domain_segments = [
            Segment(
                index=i,
                speaker=Speaker(label=seg.get("speaker", "unknown")),
                start=seg.get("start", 0),
                end=seg.get("end", 0),
                text=seg.get("text", ""),
            )
            for i, seg in enumerate(reconciled_segments, 1)
        ]
        transcript = Transcript(
            transcript_id=transcript_id,
            segments=domain_segments,
            source_file=audio_path,
            language=language,
        )
        self._store.save(transcript)

        # Save guided output to reference store
        self._ref_store.save_guided_output(
            canonical_name,
            reconciled_segments,
            metadata={
                "model": model_size,
                "llm_model": reconciliation_meta.get("model", ""),
                "reference_used": best_ref.title if best_ref else "",
                "speaker_map": speaker_map,
                "language": language,
            },
        )

        # ── Step 9: Index into Qdrant ─────────────────────────────────────
        if self._index is not None:
            try:
                n = await self._index.index(transcript)
                logger.info("[guided] indexed %d segments for %s", n, transcript_id)
            except Exception as e:
                logger.warning("[guided] indexing failed: %s", e)

        total_elapsed = time.time() - t_global
        logger.info(
            "[guided] DONE '%s': %.2fs total (%d segments, %d references, %d narratives)",
            canonical_name,
            total_elapsed,
            len(reconciled_segments),
            len(references),
            len(narratives),
        )

        return {
            "transcript_id": transcript_id,
            "canonical_name": canonical_name,
            "project_id": params.get("project_id", ""),
            "segments": reconciled_segments,
            "speaker_map": speaker_map,
            "participants": reconciliation.get("participants", []) if best_ref else [],
            "reconciliation_notes": reconciliation.get("reconciliation_notes", "") if best_ref else "",
            "references_used": len(references),
            "priors_sent_to_reconciler": len(priors),
            "narratives_used": len(narratives),
            "timings": {
                "ref_load_s": round(ref_load_elapsed, 2),
                "preprocess_s": round(preprocess_elapsed, 2),
                "asr_s": round(asr_elapsed, 2),
                "diarization_s": round(diar_elapsed, 2),
                "reconciliation_s": round(reconcile_elapsed, 2),
                "total_s": round(total_elapsed, 2),
            },
            "reconciliation_meta": reconciliation_meta,
        }

    # ── Private helpers ───────────────────────────────────────────────────

    def _build_initial_prompt(
        self, reference: ReferenceTranscript | None, language: str
    ) -> str | None:
        """Build Whisper initial_prompt from the best reference transcript.

        This biases Whisper's decoder toward expected vocabulary without
        constraining it. Includes: participant names, location, and the
        first portion of the reference text.
        """
        if not reference:
            return None

        parts: list[str] = []

        # Speaker names/roles as vocabulary hints
        if reference.participants:
            parts.append("Participants: " + ", ".join(reference.participants))

        # Location context
        if reference.location:
            parts.append(reference.location)

        # First portion of reference text for vocabulary priming
        text_excerpt = reference.full_text[:_INITIAL_PROMPT_MAX_CHARS]
        if text_excerpt:
            parts.append(text_excerpt)

        prompt = ". ".join(parts)
        return prompt if prompt else None

    def _build_raw_segments(
        self, raw_text: str, turns: list
    ) -> list[dict]:
        """Merge Whisper text with diarization turns.

        Simple approach: treat each diarization turn as a segment, and
        assign the proportional part of the Whisper text to it based on
        duration. This is a baseline — the LLM reconciliation will refine.
        """
        if not turns:
            return [{"speaker": "SPEAKER_00", "start": 0, "end": 0, "text": raw_text}]

        # For now, each diarization turn gets a placeholder
        # The full text is distributed across turns by position
        total_duration = sum(t.duration for t in turns) or 1
        segments = []

        # Split text roughly by duration proportion
        text_chars = list(raw_text)
        total_chars = len(text_chars)
        char_pos = 0

        for i, turn in enumerate(turns):
            proportion = turn.duration / total_duration
            char_count = int(proportion * total_chars)
            if i == len(turns) - 1:
                # Last segment gets remaining characters
                seg_text = "".join(text_chars[char_pos:]).strip()
            else:
                seg_text = "".join(text_chars[char_pos : char_pos + char_count]).strip()
            char_pos += char_count

            segments.append({
                "id": str(i),
                "speaker": turn.speaker,
                "start": round(turn.start, 3),
                "end": round(turn.end, 3),
                "text": seg_text,
            })

        return segments
