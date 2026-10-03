"""JSON transcript store adapter — implements TranscriptStorePort."""
from __future__ import annotations

import json
import logging
import os
import tempfile

from src.domain.entities.transcript import Segment, Speaker, Transcript

logger = logging.getLogger(__name__)


class JSONTranscriptStore:
    """Persist transcripts as JSON files. Implements TranscriptStorePort."""

    def __init__(self, transcript_dir: str):
        self._dir = transcript_dir
        os.makedirs(self._dir, exist_ok=True)

    def save(self, transcript: Transcript) -> str:
        path = os.path.join(self._dir, f"{transcript.transcript_id}.json")
        segments = [
            {
                "index": seg.index,
                "speaker": seg.speaker.label,
                "start": seg.start,
                "end": seg.end,
                "duration": seg.duration,
                "text": seg.text,
                "reviewed": getattr(seg, "reviewed", False),
                "correction_note": getattr(seg, "correction_note", ""),
                "backchannel_events": getattr(seg, "backchannel_events", ""),
                # Enrichment-owned provenance fields. Omitting either one
                # silently destroys it on the next save.
                "segment_datetime": getattr(seg, "segment_datetime", ""),
                "speaker_id": getattr(seg, "speaker_id", ""),
            }
            for seg in transcript.segments
        ]
        data = {
            "transcript_id": transcript.transcript_id,
            "source_file": transcript.source_file or "",
            "source_path": getattr(transcript, "source_path", "") or "",
            "language": transcript.language or "",
            "timestamp": transcript.timestamp or "",
            "provider": transcript.provider or "",
            "original_transcript_id": transcript.original_transcript_id,
            "metadata": transcript.metadata or {},
            "title": transcript.title or "",
            "subtitle": transcript.subtitle or "",
            "recording_datetime": transcript.recording_datetime or "",
            "location": transcript.location or "",
            "audio_id": transcript.audio_id or "",
            "case_id": transcript.case_id or "",
            "narrative_id": transcript.narrative_id or "",
            "chronological_order": transcript.chronological_order,
            "prior_stage": transcript.prior_stage or "",
            "next_stage": transcript.next_stage or "",
            "classification": transcript.classification or "",
            "participants": transcript.participants or [],
            "violations_cited": transcript.violations_cited or [],
            "tags": transcript.tags or [],
            "forensic_clusters": transcript.forensic_clusters or {},
            "key_evidentiary_findings": transcript.key_evidentiary_findings or [],
            "corrections_applied": transcript.corrections_applied or [],
            "segments": segments,
            "reviewed": bool(getattr(transcript, "reviewed", False)),
        }
        # Atomic write: dump to a temp file in the same directory, fsync, then
        # os.replace() (atomic on POSIX). A crash mid-write can therefore never
        # leave a truncated/corrupt transcript behind, and readers always see
        # either the old or the new complete file.
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{transcript.transcript_id}.", suffix=".tmp", dir=self._dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                logger.warning("[store] could not remove temp file %s", tmp_path)
            raise
        logger.info(f"[store] saved {path} segments={len(segments)}")
        return path

    def load(self, transcript_id: str) -> Transcript | None:
        path = os.path.join(self._dir, f"{transcript_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        # Backward compat: legacy files stored a flat list of segments. Normalise
        # to a dict first so every top-level lookup below is safe for both shapes
        # (previously the list branch set locals and then called raw.get(...),
        # raising AttributeError on exactly the files it was meant to support).
        doc = raw if isinstance(raw, dict) else {}
        items = raw if isinstance(raw, list) else (doc.get("segments", []) or [])
        meta = doc.get("metadata", {}) or {}
        source_file = doc.get("source_file", "") or ""
        language = doc.get("language", "es") or "es"
        timestamp = doc.get("timestamp", "") or ""
        provider = doc.get("provider", "") or ""
        original_transcript_id = doc.get("original_transcript_id") or None

        segments = []
        for i, item in enumerate(items):
            # Determine the segment index. Prefer an explicit 'index' field, then fall back to the legacy 'id' field,
            # and finally to the enumeration order. The legacy 'id' may be a string or a dotted identifier (e.g., "4.2");
            # in such cases we coerce it to an int when possible, otherwise use the enumeration order.
            raw_index = item.get("index")
            if raw_index is None:
                raw_index = item.get("id")
            try:
                # Some ids are strings like "0" or "12"; convert safely.
                index = int(float(raw_index)) if raw_index is not None else i
            except Exception:
                # If conversion fails (e.g., "4.2"), default to enumeration order.
                index = i
            segment = Segment(
                index=index,
                speaker=Speaker(label=item.get("speaker", "")),
                start=item.get("start", 0.0),
                end=item.get("end", 0.0),
                text=item.get("text", ""),
                reviewed=item.get("reviewed", False),
                correction_note=item.get("correction_note", ""),
                backchannel_events=item.get("backchannel_events", ""),
                segment_datetime=item.get("segment_datetime", ""),
                speaker_id=item.get("speaker_id", ""),
            )
            segments.append(segment)

        return Transcript(
            transcript_id=transcript_id,
            segments=segments,
            source_file=source_file,
            source_path=doc.get("source_path", "") or "",
            language=language,
            metadata=meta,
            timestamp=timestamp,
            provider=provider,
            original_transcript_id=original_transcript_id,
            title=doc.get("title", ""),
            subtitle=doc.get("subtitle", ""),
            recording_datetime=doc.get("recording_datetime", ""),
            location=doc.get("location", ""),
            audio_id=doc.get("audio_id", ""),
            case_id=doc.get("case_id", ""),
            narrative_id=doc.get("narrative_id", ""),
            chronological_order=doc.get("chronological_order"),
            prior_stage=doc.get("prior_stage", ""),
            next_stage=doc.get("next_stage", ""),
            classification=doc.get("classification", ""),
            participants=doc.get("participants", []),
            violations_cited=doc.get("violations_cited", []),
            tags=doc.get("tags", []),
            forensic_clusters=doc.get("forensic_clusters", {}),
            key_evidentiary_findings=doc.get("key_evidentiary_findings", []),
            corrections_applied=doc.get("corrections_applied", []),
            reviewed=bool(doc.get("reviewed", False)),
        )

    def list_ids(self) -> list[str]:
        return [
            f[:-5]
            for f in os.listdir(self._dir)
            if f.endswith(".json")
        ]
