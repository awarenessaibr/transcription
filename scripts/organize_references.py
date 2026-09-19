#!/usr/bin/env python3.10
"""Organize existing transcripts into the reference-guided structure.

Scans data/transcripts_by_audio/ for existing reference files without
manifests, and creates manifest.json files for each audio folder.

Also maps audio files in data/audio/ to reference folders and reports
coverage.

Usage:
    python3.10 scripts/organize_references.py [--create-missing] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)

AUDIO_DIR = "data/audio"
REFERENCE_DIR = "data/transcripts_by_audio"
TRANSCRIPT_DIR = "data/transcripts"
NARRATIVE_DIR = "data/transcripts_narrative"
SUPPORTED_EXT = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".webm"}


def canonical_name(filename: str) -> str:
    """Derive canonical name from an audio filename.

    'Aeropuerto Arturo Merino Benítez 7.m4a' → 'aeropuerto_arturo_merino_benitez_7'
    'aeropuerto_STG_7.m4a' → 'aeropuerto_stg_7'
    """
    name = os.path.splitext(filename)[0]
    name = name.lower()
    # Normalize accented characters
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ñ": "n", "ü": "u",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    # Replace spaces and hyphens with underscores, collapse multiples
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def scan_audio_files() -> dict[str, str]:
    """Map canonical names to audio file paths."""
    mapping: dict[str, str] = {}
    if not os.path.isdir(AUDIO_DIR):
        return mapping
    for f in sorted(os.listdir(AUDIO_DIR)):
        ext = os.path.splitext(f)[1].lower()
        if ext in SUPPORTED_EXT:
            cname = canonical_name(f)
            mapping[cname] = os.path.join(AUDIO_DIR, f)
    return mapping


def scan_narratives() -> dict[str, list[str]]:
    """Map canonical names to narrative file paths."""
    narr: dict[str, list[str]] = {}
    if not os.path.isdir(NARRATIVE_DIR):
        return narr
    for f in sorted(os.listdir(NARRATIVE_DIR)):
        if not f.endswith(".txt"):
            continue
        # Parse: incident_narrative_<audio_id>_<ISO-datetime>.txt
        stem = os.path.splitext(f)[0]
        stem = stem.removeprefix("incident_narrative_")
        # Strip ISO datetime suffix
        m = re.search(r"_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d+Z)\s*$", stem)
        if m:
            audio_id = stem[:m.start()].strip()
        else:
            audio_id = stem
        cname = canonical_name(audio_id + ".tmp")  # add dummy ext for canonical_name()
        cname = cname.removesuffix("_tmp")
        narr.setdefault(cname, []).append(f)
    return narr


def scan_existing_references() -> dict[str, list[str]]:
    """Map canonical names to their reference folder contents."""
    refs: dict[str, list[str]] = {}
    if not os.path.isdir(REFERENCE_DIR):
        return refs
    for d in sorted(os.listdir(REFERENCE_DIR)):
        dpath = os.path.join(REFERENCE_DIR, d)
        if not os.path.isdir(dpath):
            continue
        files = [f for f in os.listdir(dpath) if f.endswith(".json")]
        refs[d] = sorted(files)
    return refs


def analyze_reference_file(path: str) -> dict | None:
    """Analyze a JSON file to determine if it's a valid reference transcript."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    if "content" not in data or not isinstance(data.get("content"), list):
        return None

    content = data["content"]
    if not content:
        return None

    # Check if content items look like transcript segments
    first = content[0]
    if not isinstance(first, dict) or "text" not in first:
        return None

    speakers = set()
    for seg in content:
        if "speaker" in seg:
            speakers.add(seg["speaker"])

    return {
        "segments": len(content),
        "speakers": list(speakers),
        "participants": data.get("participants", []),
        "language": data.get("language", ""),
        "location": data.get("location", ""),
        "recording_datetime": data.get("recording_datetime", ""),
        "has_confidence": any("confidence" in s for s in content),
        "has_timing": any("start" in s and "end" in s for s in content),
        "title": data.get("title", ""),
        "audio_id": data.get("audio_id", ""),
    }


def build_manifest(
    canonical: str,
    audio_path: str | None,
    ref_files: list[str],
) -> dict:
    """Build a manifest.json for an audio folder."""
    versions = []
    participants_set: set[str] = set()
    language = "es"
    location = ""

    for fname in ref_files:
        if fname == "manifest.json":
            continue
        if fname.startswith("metadata"):
            continue
        # Skip numbered legal analysis files
        if fname[:5].isdigit():
            continue

        fpath = os.path.join(REFERENCE_DIR, canonical, fname)
        info = analyze_reference_file(fpath)
        if not info:
            continue

        # Determine version type
        if "guided" in fname.lower():
            vtype = "guided"
            source = "llm_reconciliation"
        elif "whisper" in fname.lower() or "raw" in fname.lower():
            vtype = "whisper_raw"
            source = "pipeline"
        elif "segment" in fname.lower():
            vtype = "reference"
            source = "segment_extraction"
        elif "corruption" in fname.lower():
            vtype = "reference"
            source = "corruption_note"
        else:
            vtype = "reference"
            source = "manual_correction"

        versions.append({
            "filename": fname,
            "type": vtype,
            "source": source,
            "quality_score": 0.9 if source == "manual_correction" else 0.7,
            "segments": info["segments"],
            "created_at": info.get("recording_datetime", ""),
            "model": "",
            "notes": f"{len(info['speakers'])} speakers: {', '.join(info['speakers'][:5])}",
            "reference_used": "",
        })

        participants_set.update(info.get("participants", []))
        if info.get("language"):
            language = info["language"]
        if info.get("location"):
            location = info["location"]

    audio_file = os.path.basename(audio_path) if audio_path else ""
    return {
        "audio_file": audio_file,
        "audio_path": audio_path or "",
        "canonical_name": canonical,
        "participants": sorted(participants_set),
        "language": language,
        "location": location,
        "versions": versions,
    }


def create_empty_folder(canonical: str, audio_path: str, dry_run: bool) -> None:
    """Create an empty reference folder with a manifest for an unmapped audio."""
    folder = os.path.join(REFERENCE_DIR, canonical)
    if dry_run:
        logger.info("  [DRY RUN] Would create: %s/", folder)
        return

    os.makedirs(folder, exist_ok=True)
    manifest = {
        "audio_file": os.path.basename(audio_path),
        "audio_path": audio_path,
        "canonical_name": canonical,
        "participants": [],
        "language": "es",
        "location": "",
        "versions": [],
    }
    manifest_path = os.path.join(folder, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    logger.info("  Created: %s/manifest.json", folder)


def main():
    parser = argparse.ArgumentParser(description="Organize reference transcripts")
    parser.add_argument(
        "--create-missing",
        action="store_true",
        help="Create empty reference folders for audio files without them",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    args = parser.parse_args()

    audio_map = scan_audio_files()
    ref_map = scan_existing_references()
    narr_map = scan_narratives()

    logger.info("=" * 60)
    logger.info("Audio files: %d", len(audio_map))
    logger.info("Reference folders: %d", len(ref_map))
    logger.info("Narrative files: %d (covering %d audio IDs)", sum(len(v) for v in narr_map.values()), len(narr_map))
    logger.info("=" * 60)

    # ── Report: Audio files → reference folders ──────────────────────────
    logger.info("\n── AUDIO → REFERENCE MAPPING ──")
    mapped = 0
    unmapped = []

    for cname, apath in sorted(audio_map.items()):
        narr_count = len(narr_map.get(cname, []))
        narr_tag = f" 📝{narr_count}" if narr_count else ""
        if cname in ref_map:
            files = ref_map[cname]
            has_manifest = "manifest.json" in files
            ref_count = len([f for f in files if f != "manifest.json"])
            status = "✓" if has_manifest else "~"
            logger.info("  %s %s → %s/ (%d refs, manifest=%s%s)",
                        status, os.path.basename(apath), cname, ref_count, has_manifest, narr_tag)
            mapped += 1
        else:
            logger.info("  ✗ %s → (no reference folder%s)", os.path.basename(apath), narr_tag)
            unmapped.append((cname, apath))

    logger.info("\nMapped: %d/%d | Unmapped: %d", mapped, len(audio_map), len(unmapped))

    # ── Report: Orphan reference folders (no matching audio) ─────────────
    orphans = [d for d in ref_map if d not in audio_map]
    if orphans:
        logger.info("\n── ORPHAN REFERENCE FOLDERS (no matching audio) ──")
        for o in orphans:
            logger.info("  ? %s/ (%d files)", o, len(ref_map[o]))

    # ── Report: Narrative coverage ───────────────────────────────────────
    narr_only = [n for n in narr_map if n not in audio_map]
    if narr_map:
        logger.info("\n── NARRATIVE COVERAGE ──")
        for cname in sorted(narr_map.keys()):
            files = narr_map[cname]
            has_audio = "✓" if cname in audio_map else "✗"
            has_refs = "✓" if cname in ref_map else "✗"
            logger.info("  %s audio | %s refs | %s: %d narrative(s)",
                        has_audio, has_refs, cname, len(files))
        if narr_only:
            logger.info("  ── Narratives without matching audio: %s", ", ".join(narr_only))

    # ── Build manifests for folders that don't have one ──────────────────
    logger.info("\n── MANIFEST GENERATION ──")
    for cname, files in ref_map.items():
        if "manifest.json" in files:
            logger.info("  SKIP %s (manifest exists)", cname)
            continue
        if not files:
            logger.info("  SKIP %s (empty folder)", cname)
            continue

        audio_path = audio_map.get(cname)
        manifest = build_manifest(cname, audio_path, files)

        if not manifest["versions"]:
            logger.info("  SKIP %s (no valid reference files)", cname)
            continue

        manifest_path = os.path.join(REFERENCE_DIR, cname, "manifest.json")
        if args.dry_run:
            logger.info("  [DRY RUN] Would create: %s (%d versions)",
                        manifest_path, len(manifest["versions"]))
        else:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            logger.info("  CREATED: %s (%d versions)",
                        manifest_path, len(manifest["versions"]))

    # ── Create missing folders ───────────────────────────────────────────
    if args.create_missing and unmapped:
        logger.info("\n── CREATING MISSING REFERENCE FOLDERS ──")
        for cname, apath in unmapped:
            create_empty_folder(cname, apath, dry_run=args.dry_run)

    logger.info("\n" + "=" * 60)
    logger.info("DONE")


if __name__ == "__main__":
    main()
