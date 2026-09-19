"""Use case: validate and refine a stored transcript.

Pipeline:
1. Load + audit
2. Deterministic patches (no LLM, no audio) — reindex, label drift, micro-merge
3. Reconciler patches (text-only) for mid-word boundaries / time gaps
4. Acoustic escalation (opt-in) — silence drop, low-SNR re-process+re-diarize
5. Audit-after + persist
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from collections import Counter
from dataclasses import replace as dc_replace
from typing import Any

from src.application.dto.schemas import (
    AnomalyDTO,
    AuditReportDTO,
    PatchDTO,
    ValidateAndRefineResult,
)
from src.application.services.transcript_auditor import TranscriptAuditor
from src.application.services.transcript_patcher import TranscriptPatcher
from src.domain.entities.anomaly import Anomaly, AnomalyKind, AuditReport
from src.domain.entities.patch import Patch, PatchOp
from src.domain.entities.transcript import Segment, Speaker, Transcript
from src.domain.ports.interfaces import (
    AcousticProbePort,
    ASRPort,
    AudioFilePort,
    AudioProcessorPort,
    DiarizationPort,
    NarrativeStorePort,
    ReferenceStorePort,
    TranscriptReconcilerPort,
    TranscriptStorePort,
)

logger = logging.getLogger(__name__)


class ValidateAndRefineTranscriptUseCase:
    """Audit + refine a stored transcript, escalating to acoustic probes when asked."""

    def __init__(
        self,
        store: TranscriptStorePort,
        ref_store: ReferenceStorePort,
        narrative_store: NarrativeStorePort,
        reconciler: TranscriptReconcilerPort | None,
        auditor: TranscriptAuditor,
        patcher: TranscriptPatcher,
        processor: AudioProcessorPort,
        diarizer: DiarizationPort,
        asr: ASRPort,
        audio_files: AudioFilePort,
        probe: AcousticProbePort | None,
    ) -> None:
        self._store = store
        self._ref_store = ref_store
        self._narrative_store = narrative_store
        self._reconciler = reconciler
        self._auditor = auditor
        self._patcher = patcher
        self._processor = processor
        self._diarizer = diarizer
        self._asr = asr
        self._audio_files = audio_files
        self._probe = probe

    async def execute(
        self,
        transcript_id: str,
        *,
        canonical_name: str | None = None,
        use_acoustic_probes: bool = True,
        apply_patches: bool = True,
        save_as_new_id: bool = True,
        max_acoustic_windows: int = 8,
        gap_threshold_s: float = 4.0,
        snr_escalation_threshold_db: float = 6.0,
        silence_drop_ratio: float = 0.6,
    ) -> ValidateAndRefineResult:
        transcript = self._store.load(transcript_id)
        if transcript is None:
            raise ValueError(f"Transcript not found: {transcript_id}")

        notes: list[str] = []
        audio_path = (
            transcript.metadata.get("source_audio_path")
            if transcript.metadata
            else None
        ) or transcript.source_file or ""
        audio_available = bool(audio_path) and os.path.exists(audio_path)
        if not audio_available:
            notes.append(f"audio_unavailable:{audio_path or 'none'}")

        # 1. Audit before
        audit_before = self._auditor.audit(transcript)

        # 2. Deterministic patches
        working = transcript
        applied_total: list[Patch] = []

        if any(a.kind == AnomalyKind.DUPLICATE_IDS for a in audit_before.anomalies):
            working = self._patcher.reindex(working)
            applied_total.append(
                Patch(
                    op=PatchOp.RELABEL,  # repurposed marker; note describes action
                    note="reindex segments to resolve duplicate ids",
                )
            )

        # Re-audit after reindex so subsequent patches use stable indices.
        audit = self._auditor.audit(working)

        deterministic_patches = self._build_deterministic_patches(working, audit)
        if deterministic_patches:
            working, applied = self._patcher.apply(working, deterministic_patches)
            applied_total.extend(applied)

        # 3. Reconciler patches (text only)
        reconciler_calls = 0
        if (
            self._reconciler is not None
            and canonical_name
            and audio_available  # narrative/refs typically keyed by canonical name
        ):
            audit = self._auditor.audit(working)
            text_anomalies = [
                a
                for a in audit.anomalies
                if a.kind in (AnomalyKind.MID_WORD_BOUNDARY, AnomalyKind.TIME_GAP)
                and (a.kind != AnomalyKind.TIME_GAP or (a.end - a.start) >= gap_threshold_s)
            ]
            windows = self._merge_windows(text_anomalies)
            cap = max(0, max_acoustic_windows // 2)
            for w_start, w_end in windows[:cap]:
                try:
                    working, n = await self._reconcile_window(
                        working, canonical_name, w_start, w_end
                    )
                    reconciler_calls += 1
                    if n:
                        applied_total.append(
                            Patch(
                                op=PatchOp.REPLACE_TEXT,
                                new_start=w_start,
                                new_end=w_end,
                                note=f"reconciler patched {n} segments in [{w_start:.2f},{w_end:.2f}]",
                            )
                        )
                except Exception as exc:
                    logger.warning(
                        "[refine] reconciler window [%.2f,%.2f] failed: %s",
                        w_start,
                        w_end,
                        exc,
                    )
                    notes.append(
                        f"reconciler_window_error:{w_start:.2f}-{w_end:.2f}:{exc}"
                    )

        # 4. Acoustic escalation
        acoustic_probes_run = 0
        if use_acoustic_probes and self._probe is not None and audio_available:
            audit = self._auditor.audit(working)
            remaining = [
                a
                for a in audit.anomalies
                if a.kind in (AnomalyKind.MID_WORD_BOUNDARY, AnomalyKind.TIME_GAP)
            ]
            for anomaly in remaining[:max_acoustic_windows]:
                try:
                    stats = self._probe.window_stats(audio_path, anomaly.start, anomaly.end)
                except Exception as exc:
                    notes.append(f"probe_error:{anomaly.start:.2f}-{anomaly.end:.2f}:{exc}")
                    continue
                acoustic_probes_run += 1
                if stats.get("silence_ratio", 0.0) > silence_drop_ratio:
                    patch = self._silence_merge_patch(working, anomaly)
                    if patch is not None:
                        working, applied = self._patcher.apply(working, [patch])
                        applied_total.extend(applied)
                    continue
                if stats.get("snr_estimate", 99.0) < snr_escalation_threshold_db:
                    try:
                        working, applied = await self._low_snr_escalation(
                            working,
                            audio_path,
                            anomaly,
                            canonical_name,
                        )
                        applied_total.extend(applied)
                    except Exception as exc:
                        notes.append(
                            f"escalation_error:{anomaly.start:.2f}-{anomaly.end:.2f}:{exc}"
                        )
                else:
                    notes.append(
                        f"within_tolerance:{anomaly.start:.2f}-{anomaly.end:.2f}"
                    )

        # 5. Audit after + persist
        audit_after = self._auditor.audit(working)

        out_id = transcript_id
        if apply_patches:
            if save_as_new_id:
                out_id = f"{transcript_id}_refined_{int(time.time())}"
                meta = dict(working.metadata or {})
                meta["refined_from"] = transcript_id
                meta["refinement"] = {
                    "audit_before_counts": audit_before.kind_counts(),
                    "audit_after_counts": audit_after.kind_counts(),
                    "patches_applied": len(applied_total),
                    "acoustic_probes_run": acoustic_probes_run,
                    "reconciler_calls": reconciler_calls,
                }
                working = dc_replace(
                    working,
                    transcript_id=out_id,
                    metadata=meta,
                    original_transcript_id=transcript_id,
                )
            else:
                meta = dict(working.metadata or {})
                meta["refinement"] = {
                    "audit_before_counts": audit_before.kind_counts(),
                    "audit_after_counts": audit_after.kind_counts(),
                    "patches_applied": len(applied_total),
                    "acoustic_probes_run": acoustic_probes_run,
                    "reconciler_calls": reconciler_calls,
                }
                working = dc_replace(working, metadata=meta)
            self._store.save(working)

        return ValidateAndRefineResult(
            transcript_id_in=transcript_id,
            transcript_id_out=out_id,
            audit_before=_audit_to_dto(audit_before),
            audit_after=_audit_to_dto(audit_after),
            patches_applied=[_patch_to_dto(p) for p in applied_total],
            acoustic_probes_run=acoustic_probes_run,
            reconciler_calls=reconciler_calls,
            audio_available=audio_available,
            notes=notes,
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _build_deterministic_patches(
        transcript: Transcript, audit: AuditReport
    ) -> list[Patch]:
        patches: list[Patch] = []

        # Speaker label drift — RELABEL each rare label to its canonical.
        for anomaly in audit.anomalies:
            if anomaly.kind != AnomalyKind.SPEAKER_LABEL_DRIFT:
                continue
            detail = anomaly.detail_dict()
            canonical = detail.get("canonical")
            if not canonical:
                continue
            patches.append(
                Patch(
                    op=PatchOp.RELABEL,
                    segment_indices=anomaly.segment_indices,
                    new_speaker=canonical,
                    note=f"canonicalize speaker '{detail.get('drift', '')}' -> '{canonical}'",
                )
            )

        # Micro-segment — merge with previous same-speaker neighbor when adjacent.
        by_index = {s.index: s for s in transcript.segments}
        positions = {s.index: i for i, s in enumerate(transcript.segments)}
        used: set[int] = set()
        for anomaly in audit.anomalies:
            if anomaly.kind != AnomalyKind.MICRO_SEGMENT:
                continue
            idx = anomaly.segment_indices[0]
            if idx in used:
                continue
            seg = by_index.get(idx)
            if seg is None:
                continue
            pos = positions[idx]
            if pos == 0:
                continue
            prev = transcript.segments[pos - 1]
            if prev.speaker.label != seg.speaker.label:
                continue
            if (seg.start - prev.end) > 1.5:
                continue
            patches.append(
                Patch(
                    op=PatchOp.MERGE,
                    segment_indices=(prev.index, seg.index),
                    note=f"merge micro-segment {seg.index} into {prev.index}",
                )
            )
            used.add(prev.index)
            used.add(seg.index)

        return patches

    @staticmethod
    def _merge_windows(
        anomalies: list[Anomaly], pad: float = 1.0
    ) -> list[tuple[float, float]]:
        if not anomalies:
            return []
        intervals = sorted(
            (max(0.0, a.start - pad), a.end + pad) for a in anomalies
        )
        merged: list[tuple[float, float]] = [intervals[0]]
        for s, e in intervals[1:]:
            ls, le = merged[-1]
            if s <= le:
                merged[-1] = (ls, max(le, e))
            else:
                merged.append((s, e))
        return merged

    async def _reconcile_window(
        self,
        transcript: Transcript,
        canonical_name: str,
        w_start: float,
        w_end: float,
    ) -> tuple[Transcript, int]:
        in_window = [
            s for s in transcript.segments if s.end >= w_start and s.start <= w_end
        ]
        if not in_window:
            return transcript, 0

        raw_segments = [
            {
                "speaker": s.speaker.label,
                "start": s.start,
                "end": s.end,
                "text": s.text,
            }
            for s in in_window
        ]
        references = self._ref_store.load_references(canonical_name) or []
        if not references:
            return transcript, 0
        narratives = (
            self._narrative_store.load_narratives(canonical_name)
            if self._narrative_store
            else []
        )
        result = await self._reconciler.reconcile(
            raw_segments,
            references[0],
            narrative=narratives[0] if narratives else None,
            language=transcript.language or "es",
            references=references,
        )
        new_segs = result.get("segments") or []
        if not new_segs:
            return transcript, 0

        # Build patches: DELETE all in-window indices, INSERT new segs after the
        # segment immediately preceding the window (or at start).
        positions = [
            i for i, s in enumerate(transcript.segments)
            if s.end >= w_start and s.start <= w_end
        ]
        anchor_pos = positions[0] - 1
        anchor_index = (
            transcript.segments[anchor_pos].index if anchor_pos >= 0 else -1
        )
        patches: list[Patch] = [
            Patch(
                op=PatchOp.DELETE,
                segment_indices=tuple(s.index for s in in_window),
                note="reconciler: drop in-window originals",
            )
        ]
        # INSERTs go in reverse so each new seg lands right after the anchor
        # in correct chronological order. We use new (unique) anchor index = -1
        # for "start" and re-anchor by re-running insert_after_index= the most
        # recently inserted segment's *original transcript* anchor — but our
        # patcher uses input indices. Simpler: serialize all inserts referencing
        # the same anchor (which the patcher handles by inserting just after
        # that anchor each time), so we pass them in *reverse* chronological
        # order so reading in order gives forward order.
        for ns in reversed(new_segs):
            patches.append(
                Patch(
                    op=PatchOp.INSERT,
                    insert_after_index=anchor_index,
                    new_text=str(ns.get("text", "")),
                    new_speaker=str(ns.get("speaker", "unknown")),
                    new_start=float(ns.get("start", w_start)),
                    new_end=float(ns.get("end", w_end)),
                    note="reconciler: insert reconciled segment",
                )
            )
        new_transcript, _ = self._patcher.apply(transcript, patches)
        return new_transcript, len(new_segs)

    def _silence_merge_patch(
        self, transcript: Transcript, anomaly: Anomaly
    ) -> Patch | None:
        if anomaly.kind != AnomalyKind.TIME_GAP:
            return None
        if len(anomaly.segment_indices) != 2:
            return None
        a, b = anomaly.segment_indices
        # Only merge if same speaker (or close fuzzy).
        by_index = {s.index: s for s in transcript.segments}
        sa, sb = by_index.get(a), by_index.get(b)
        if not (sa and sb):
            return None
        if sa.speaker.label != sb.speaker.label:
            return None
        return Patch(
            op=PatchOp.MERGE,
            segment_indices=(a, b),
            note=f"silence merge across {anomaly.start:.2f}s-{anomaly.end:.2f}s gap",
        )

    async def _low_snr_escalation(
        self,
        transcript: Transcript,
        audio_path: str,
        anomaly: Anomaly,
        canonical_name: str | None,
    ) -> tuple[Transcript, list[Patch]]:
        # Extract clip → process → diarize → ASR per turn → splice.
        with tempfile.TemporaryDirectory() as tmp:
            raw_clip = os.path.join(tmp, "clip.wav")
            self._probe.extract_window(audio_path, anomaly.start, anomaly.end, raw_clip)
            processed = self._processor.process(
                raw_clip,
                {
                    "noise_reduce": True,
                    "voice_enhance": True,
                    "apply_gain": True,
                },
            )
            turns = self._diarizer.diarize(
                processed, min_speakers=2, max_speakers=2
            )
            initial_prompt: str | None = None
            if canonical_name and self._narrative_store:
                narratives = self._narrative_store.load_narratives(canonical_name)
                if narratives:
                    initial_prompt = (narratives[0].text or "")[:200] or None

            new_segments: list[dict[str, Any]] = []
            for turn in turns:
                turn_path = os.path.join(
                    tmp, f"turn_{int(turn.start * 1000)}.wav"
                )
                self._probe.extract_window(
                    processed,
                    max(0.0, turn.start),
                    turn.end,
                    turn_path,
                )
                asr_result = self._asr.transcribe(
                    turn_path,
                    language=transcript.language or "es",
                    initial_prompt=initial_prompt,
                )
                text = asr_result.get("text", "") if isinstance(asr_result, dict) else asr_result
                new_segments.append(
                    {
                        "speaker": turn.speaker,
                        "start": anomaly.start + turn.start,
                        "end": anomaly.start + turn.end,
                        "text": text,
                    }
                )

        if not new_segments:
            return transcript, []

        in_window = [
            s
            for s in transcript.segments
            if s.end >= anomaly.start and s.start <= anomaly.end
        ]
        positions = [
            i
            for i, s in enumerate(transcript.segments)
            if s.end >= anomaly.start and s.start <= anomaly.end
        ]
        anchor_pos = positions[0] - 1 if positions else -1
        anchor_index = (
            transcript.segments[anchor_pos].index if anchor_pos >= 0 else -1
        )
        patches: list[Patch] = []
        if in_window:
            patches.append(
                Patch(
                    op=PatchOp.DELETE,
                    segment_indices=tuple(s.index for s in in_window),
                    note="acoustic escalation: drop low-SNR originals",
                )
            )
        for ns in reversed(new_segments):
            patches.append(
                Patch(
                    op=PatchOp.INSERT,
                    insert_after_index=anchor_index,
                    new_text=str(ns["text"]),
                    new_speaker=str(ns["speaker"]),
                    new_start=float(ns["start"]),
                    new_end=float(ns["end"]),
                    note="acoustic escalation: insert re-asr segment",
                )
            )
        new_transcript, applied = self._patcher.apply(transcript, patches)
        return new_transcript, applied


# ──────────────────────────────────────────────────────────── DTO converters

def _audit_to_dto(report: AuditReport) -> AuditReportDTO:
    return AuditReportDTO(
        transcript_id=report.transcript_id,
        anomalies=[
            AnomalyDTO(
                kind=a.kind.value,
                severity=a.severity.value,
                segment_indices=list(a.segment_indices),
                start=a.start,
                end=a.end,
                hint=a.hint,
                detail=a.detail_dict(),
            )
            for a in report.anomalies
        ],
        counts_by_kind=dict(Counter({k: v for k, v in report.counts_by_kind})),
        counts_by_severity=dict(
            Counter({k: v for k, v in report.counts_by_severity})
        ),
    )


def _patch_to_dto(p: Patch) -> PatchDTO:
    return PatchDTO(
        op=p.op.value,
        segment_indices=list(p.segment_indices),
        new_text=p.new_text,
        new_speaker=p.new_speaker,
        new_start=p.new_start,
        new_end=p.new_end,
        insert_after_index=p.insert_after_index,
        note=p.note,
    )
