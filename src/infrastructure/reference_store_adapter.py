"""Filesystem-based reference transcript store.

Implements ReferenceStorePort. Reads/writes to:
  data/transcripts_by_audio/<canonical_name>/
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from src.domain.entities.reference import (
    AudioManifest,
    ManifestVersion,
    ReferenceSegment,
    ReferenceTranscript,
)

logger = logging.getLogger(__name__)


class ReferenceStoreAdapter:
    """Filesystem reference store. Implements ReferenceStorePort."""

    def __init__(self, base_dir: str = "data/transcripts_by_audio"):
        self._base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _audio_dir(self, canonical_name: str) -> str:
        return os.path.join(self._base_dir, canonical_name)

    # ── Manifest ──────────────────────────────────────────────────────────

    def load_manifest(self, canonical_name: str) -> AudioManifest | None:
        path = os.path.join(self._audio_dir(canonical_name), "manifest.json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        versions = [
            ManifestVersion(
                filename=v["filename"],
                type=v.get("type", "reference"),
                source=v.get("source", "unknown"),
                quality_score=v.get("quality_score"),
                segments=v.get("segments", 0),
                created_at=v.get("created_at", ""),
                model=v.get("model", ""),
                notes=v.get("notes", ""),
                reference_used=v.get("reference_used", ""),
            )
            for v in data.get("versions", [])
        ]
        return AudioManifest(
            audio_file=data.get("audio_file", ""),
            audio_path=data.get("audio_path", ""),
            canonical_name=data.get("canonical_name", canonical_name),
            participants=data.get("participants", []),
            language=data.get("language", "es"),
            location=data.get("location", ""),
            versions=versions,
        )

    def save_manifest(self, manifest: AudioManifest) -> str:
        audio_dir = self._audio_dir(manifest.canonical_name)
        os.makedirs(audio_dir, exist_ok=True)
        path = os.path.join(audio_dir, "manifest.json")
        data = {
            "audio_file": manifest.audio_file,
            "audio_path": manifest.audio_path,
            "canonical_name": manifest.canonical_name,
            "participants": manifest.participants,
            "language": manifest.language,
            "location": manifest.location,
            "versions": [
                {
                    "filename": v.filename,
                    "type": v.type,
                    "source": v.source,
                    "quality_score": v.quality_score,
                    "segments": v.segments,
                    "created_at": v.created_at,
                    "model": v.model,
                    "notes": v.notes,
                    "reference_used": v.reference_used,
                }
                for v in manifest.versions
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("[ref-store] saved manifest %s (%d versions)", path, len(manifest.versions))
        return path

    # ── References ────────────────────────────────────────────────────────

    def load_references(self, canonical_name: str) -> list[ReferenceTranscript]:
        manifest = self.load_manifest(canonical_name)
        if not manifest:
            # Fallback: look for any JSON files with content arrays
            return self._scan_for_references(canonical_name)

        refs: list[ReferenceTranscript] = []
        for version in manifest.versions:
            if version.type != "reference":
                continue
            ref = self._load_reference_file(canonical_name, version.filename)
            if ref:
                ref.quality_score = version.quality_score or 0.0
                ref.source = version.source
                refs.append(ref)

        # Sort by quality, highest first
        refs.sort(key=lambda r: r.quality_score, reverse=True)
        return refs

    def _load_reference_file(
        self, canonical_name: str, filename: str
    ) -> ReferenceTranscript | None:
        path = os.path.join(self._audio_dir(canonical_name), filename)
        if not os.path.exists(path):
            logger.warning("[ref-store] reference file not found: %s", path)
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return self._parse_reference(data, canonical_name)

    def _parse_reference(
        self, data: dict, canonical_name: str
    ) -> ReferenceTranscript:
        """Parse the rich reference transcript format.

        Accepts both ``content`` (canonical key) and ``segments`` (used by
        earlier-review exports such as LA8159 first_latam_case_version).
        """
        raw_segments = data.get("content")
        if not isinstance(raw_segments, list) or not raw_segments:
            raw_segments = data.get("segments") or []
        content = []
        for seg in raw_segments:
            content.append(
                ReferenceSegment(
                    id=str(seg.get("id", "")),
                    speaker=seg.get("speaker", "unknown"),
                    start=float(seg.get("start", 0)),
                    end=float(seg.get("end", 0)),
                    text=seg.get("text", ""),
                    language=seg.get("language", "es"),
                    confidence=float(seg.get("confidence", 0)),
                    duration=float(seg.get("duration", 0)),
                )
            )
        meta = data.get("metadata", {})
        return ReferenceTranscript(
            audio_id=data.get("audio_id", canonical_name),
            title=data.get("title", canonical_name),
            participants=data.get("participants", []),
            language=data.get("language", "es"),
            location=data.get("location", ""),
            recording_datetime=data.get("recording_datetime", ""),
            content=content,
            metadata=meta,
        )

    def _scan_for_references(self, canonical_name: str) -> list[ReferenceTranscript]:
        """Fallback: scan directory for JSON files with 'content' arrays."""
        audio_dir = self._audio_dir(canonical_name)
        if not os.path.isdir(audio_dir):
            return []

        refs: list[ReferenceTranscript] = []
        for fname in sorted(os.listdir(audio_dir)):
            if not fname.endswith(".json"):
                continue
            if fname in ("manifest.json", "metadata.json"):
                continue
            # Skip numbered legal analysis files (00001_*, etc.)
            if fname[:5].isdigit():
                continue

            path = os.path.join(audio_dir, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and (
                    (isinstance(data.get("content"), list) and data["content"])
                    or (isinstance(data.get("segments"), list) and data["segments"])
                ):
                    ref = self._parse_reference(data, canonical_name)
                    if ref.content:
                        ref.source = fname
                        refs.append(ref)
            except (json.JSONDecodeError, KeyError):
                continue

        logger.info(
            "[ref-store] scanned %s: found %d reference files (no manifest)",
            canonical_name,
            len(refs),
        )
        return refs

    # ── Guided Output ─────────────────────────────────────────────────────

    def save_guided_output(
        self, canonical_name: str, segments: list[dict], metadata: dict
    ) -> str:
        audio_dir = self._audio_dir(canonical_name)
        os.makedirs(audio_dir, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"guided_{timestamp}.json"
        path = os.path.join(audio_dir, filename)

        output = {
            "type": "guided_transcription",
            "canonical_name": canonical_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata,
            "content": segments,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info("[ref-store] saved guided output %s (%d segments)", path, len(segments))

        # Update manifest if it exists
        manifest = self.load_manifest(canonical_name)
        if manifest:
            manifest.versions.append(
                ManifestVersion(
                    filename=filename,
                    type="guided",
                    source="llm_reconciliation",
                    segments=len(segments),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    model=metadata.get("model", ""),
                    reference_used=metadata.get("reference_used", ""),
                )
            )
            self.save_manifest(manifest)

        return path

    # ── Listing ───────────────────────────────────────────────────────────

    def list_audio_names(self) -> list[str]:
        if not os.path.isdir(self._base_dir):
            return []
        return sorted(
            d
            for d in os.listdir(self._base_dir)
            if os.path.isdir(os.path.join(self._base_dir, d))
            and not d.startswith(".")
        )
