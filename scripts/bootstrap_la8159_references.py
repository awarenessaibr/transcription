#!/usr/bin/env python3
"""Bootstrap the reference store and a Project from the LA8159 case files.

Scans:
  - data/LA8159_files/main_latam_case_version/*.json   → register as references
  - data/LA8159_files/incidents_by_datetime/**/reports/general_reports/*.md
                                                       → register as context_docs
  - data/LA8159_files/incidents_by_datetime/**/*.md    → also context_docs

Outcomes:
  1. data/transcripts_by_audio/<canonical>/  is created and a relative symlink
     (or copy with --copy) is placed pointing at the source JSON.
  2. data/transcripts_by_audio/<canonical>/manifest.json is upserted with a
     "reference" version entry per LA8159 file.
  3. data/projects/la8159.json is upserted with all audios + context_docs.

Idempotent: re-running safely refreshes manifests without duplicating versions.

Usage:
    python3 scripts/bootstrap_la8159_references.py [--copy] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Make src importable when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.domain.entities.project import (  # noqa: E402
    ContextDocument,
    Project,
    ProjectAudio,
)
from src.domain.entities.reference import (  # noqa: E402
    AudioManifest,
    ManifestVersion,
)
from src.infrastructure.project_store_adapter import ProjectStoreAdapter  # noqa: E402
from src.infrastructure.reference_store_adapter import ReferenceStoreAdapter  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("bootstrap_la8159")

ROOT = Path(__file__).resolve().parents[1]
LA8159 = ROOT / "data" / "LA8159_files"
MAIN_CASE = LA8159 / "main_latam_case_version"
FIRST_REVIEW = LA8159 / "first_latam_case_version"
INCIDENTS = LA8159 / "incidents_by_datetime"
AUDIO_DIR = ROOT / "data" / "audio"
REFERENCE_DIR = ROOT / "data" / "transcripts_by_audio"
PROJECTS_DIR = ROOT / "data" / "projects"

PROJECT_ID = "la8159"
PROJECT_NAME = "LA8159 — LATAM airport incident"
PROJECT_DESCRIPTION = (
    "Forensic transcription project for the LA8159 LATAM Airlines / DGAC / PDI "
    "incident at Arturo Merino Benítez International Airport, July 2024. "
    "Bundles 30+ audio recordings, manually corrected reference transcripts, "
    "passenger narratives, and analytical reports."
)

# Quality tiers per source
MAIN_CASE_QUALITY = 0.95
FIRST_REVIEW_QUALITY = 0.70  # earlier draft, useful but lower confidence
MAIN_CASE_TAG = "la8159_main_case"
FIRST_REVIEW_TAG = "la8159_first_review"

# Outside LA8159 incident scope; exclude to prevent retrieval drift.
EXCLUDED_CANONICALS = {
    "guarulhos_airport_bd_marinho",
}


def canonical_name(filename: str) -> str:
    name = Path(filename).stem.lower()
    # Normalize to NFC so combining diacritics (common on macOS HFS+) collapse
    # into precomposed code points before the replacement table runs.
    name = unicodedata.normalize("NFC", name)
    repl = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "ü": "u", "ç": "c", "â": "a", "ê": "e", "ô": "o", "ã": "a", "õ": "o"}
    for old, new in repl.items():
        name = name.replace(old, new)
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    # Repair recurring accent-stripping artifact in the dataset:
    # "Beni_tez" (from raw "Bení tez") → "benitez".
    name = name.replace("beni_tez", "benitez")
    return name


def base_canonical(stem: str) -> str:
    """Group versioned files (segments / copies / numbered duplicates) under one canonical.

    Handles main_case suffixes (``_segment_N``, ``_merged``, ``_att``) and
    first_review duplicate markers (``_copy``, ``_<n>``, ``.<n>``) that appear
    AFTER a primary trailing number — so ``foo_15.json`` stays ``foo_15`` but
    ``foo_15.1.json``, ``foo_15_copy.json``, ``foo_15_2.json`` all collapse to
    ``foo_15``.
    """
    s = stem.lower()
    # Strip main_case variant suffixes
    s = re.sub(r"(_segment_\d+|_merged|_att)$", "", s)
    # Strip first_review duplicate markers AFTER a primary `_<number>`
    s = re.sub(r"(_\d+)((?:_copy|_\d+|\.\d+)+)$", r"\1", s)
    # Bare trailing `_copy` (no primary number guard)
    s = re.sub(r"_copy$", "", s)
    return canonical_name(s)


def link_or_copy(src: Path, dst: Path, copy: bool, dry_run: bool) -> None:
    if dry_run:
        logger.info("  [dry] %s %s → %s", "copy" if copy else "link", src.name, dst)
        return
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        shutil.copy2(src, dst)
    else:
        # Use a relative symlink so the tree is portable when copied
        rel = os.path.relpath(src, dst.parent)
        os.symlink(rel, dst)


def upsert_manifest_version(
    manifest: AudioManifest,
    version: ManifestVersion,
) -> None:
    """Replace any existing entry with the same filename."""
    manifest.versions = [v for v in manifest.versions if v.filename != version.filename]
    manifest.versions.append(version)


def collect_context_docs() -> list[ContextDocument]:
    docs: list[ContextDocument] = []
    if not INCIDENTS.exists():
        return docs
    for md_path in sorted(INCIDENTS.rglob("*.md")):
        rel = md_path.relative_to(ROOT)
        kind = "report"
        parts = md_path.parts
        if "reports" in parts:
            if "violations_reports" in parts:
                kind = "analysis"
            else:
                kind = "report"
        elif "narrative" in md_path.name.lower():
            kind = "narrative"
        else:
            kind = "report"
        docs.append(
            ContextDocument(
                path=str(rel),
                title=md_path.stem.replace("_", " "),
                kind=kind,
                notes=str(md_path.parent.relative_to(LA8159)) if md_path.parent.is_relative_to(LA8159) else "",
            )
        )
    return docs


def prune_excluded_reference_dirs(*, dry_run: bool) -> None:
    for canonical in sorted(EXCLUDED_CANONICALS):
        ref_dir = REFERENCE_DIR / canonical
        if not ref_dir.exists():
            continue
        if dry_run:
            logger.info("[dry] would remove excluded reference dir: %s", ref_dir)
            continue
        shutil.rmtree(ref_dir)
        logger.info("removed excluded reference dir: %s", ref_dir)


def ingest_reference_dir(
    src_dir: Path,
    *,
    quality: float,
    tag: str,
    notes: str,
    ref_store: ReferenceStoreAdapter,
    copy: bool,
    dry_run: bool,
) -> tuple[list[ProjectAudio], set[str]]:
    """Ingest every *.json under ``src_dir`` as a reference. Returns
    (project_audios_to_register, set_of_canonical_names_seen).
    """
    out_audios: list[ProjectAudio] = []
    seen: set[str] = set()
    if not src_dir.exists():
        logger.info("skip: %s does not exist", src_dir)
        return out_audios, seen

    json_files = sorted(p for p in src_dir.iterdir() if p.suffix == ".json")
    logger.info("Found %d json files in %s", len(json_files), src_dir.name)

    for src in json_files:
        try:
            with open(src, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("skip %s (%s)", src.name, exc)
            continue
        # Accept both `content` (main_case) and `segments` (first_review)
        seg_list = data.get("content")
        if not isinstance(seg_list, list) or not seg_list:
            seg_list = data.get("segments")
        if not isinstance(seg_list, list):
            logger.warning("skip %s (no content/segments list)", src.name)
            continue
        if not seg_list:
            logger.info("skip %s (empty content/segments)", src.name)
            continue

        target_canonical = base_canonical(src.stem)
        if target_canonical in EXCLUDED_CANONICALS:
            logger.info("skip %s (excluded canonical: %s)", src.name, target_canonical)
            continue
        dest_dir = REFERENCE_DIR / target_canonical
        dest_file = dest_dir / src.name
        link_or_copy(src, dest_file, copy, dry_run)

        if dry_run:
            logger.info("  [dry] would upsert %s in %s (qs=%s, src=%s)",
                        src.name, target_canonical, quality, tag)
        else:
            manifest = ref_store.load_manifest(target_canonical)
            if manifest is None:
                manifest = AudioManifest(
                    audio_file=str(data.get("audio_file") or ""),
                    audio_path="",
                    canonical_name=target_canonical,
                    participants=data.get("participants") or [],
                    language=data.get("language") or "es",
                    location=data.get("location") or "",
                    versions=[],
                )
            else:
                if not manifest.audio_file and data.get("audio_file"):
                    manifest.audio_file = data["audio_file"]
                if not manifest.location and data.get("location"):
                    manifest.location = data["location"]
            upsert_manifest_version(
                manifest,
                ManifestVersion(
                    filename=src.name,
                    type="reference",
                    source=tag,
                    quality_score=quality,
                    segments=len(seg_list),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    notes=notes,
                ),
            )
            ref_store.save_manifest(manifest)

        if target_canonical not in seen:
            seen.add(target_canonical)
            out_audios.append(
                ProjectAudio(
                    canonical_name=target_canonical,
                    audio_path="",
                    title=str(data.get("title") or src.stem),
                    recording_datetime=str(
                        data.get("recording_datetime") or data.get("recordingDateTime") or ""
                    ),
                    notes="",
                )
            )
    return out_audios, seen


def attach_audio_files(
    project_audios: list[ProjectAudio],
    ref_store: ReferenceStoreAdapter,
    *,
    dry_run: bool,
) -> tuple[int, list[ProjectAudio]]:
    """Walk data/audio/ and attach actual audio file paths to matching project audios.

    Returns (n_attached, extra_audios_to_register) — the latter for files that
    did not match any existing canonical and are added as new project entries.
    """
    if not AUDIO_DIR.exists():
        logger.info("skip: %s does not exist", AUDIO_DIR)
        return 0, []
    by_canonical: dict[str, ProjectAudio] = {a.canonical_name: a for a in project_audios}
    attached = 0
    extras: list[ProjectAudio] = []
    audio_exts = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".webm"}

    for audio in sorted(AUDIO_DIR.iterdir()):
        if audio.suffix.lower() not in audio_exts:
            continue
        canon = base_canonical(audio.stem)
        if canon in EXCLUDED_CANONICALS:
            logger.info("  audio %s skipped (excluded canonical: %s)", audio.name, canon)
            continue
        rel_path = str(audio.relative_to(ROOT))
        target = by_canonical.get(canon)
        if target is None:
            extras.append(
                ProjectAudio(
                    canonical_name=canon,
                    audio_path=rel_path,
                    title=audio.stem,
                    recording_datetime="",
                    notes="auto-discovered in data/audio (no reference yet)",
                )
            )
            logger.info("  audio %s \u2192 %s (new, no manifest yet)", audio.name, canon)
            continue
        if target.audio_path != rel_path:
            target.audio_path = rel_path
            attached += 1
            logger.info("  audio %s \u2192 %s (attached)", audio.name, canon)
        # Also propagate audio_path into the manifest if present
        if not dry_run:
            m = ref_store.load_manifest(canon)
            if m is not None and m.audio_path != rel_path:
                m.audio_path = rel_path
                if not m.audio_file:
                    m.audio_file = audio.name
                ref_store.save_manifest(m)
    return attached, extras


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copy", action="store_true", help="Copy files instead of symlinking")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not MAIN_CASE.exists():
        logger.error("Missing source folder: %s", MAIN_CASE)
        return 1

    ref_store = ReferenceStoreAdapter(str(REFERENCE_DIR))
    project_store = ProjectStoreAdapter(str(PROJECTS_DIR))

    prune_excluded_reference_dirs(dry_run=args.dry_run)

    # ── Pass 1: main_latam_case_version (high-quality manual transcripts)
    main_audios, main_seen = ingest_reference_dir(
        MAIN_CASE,
        quality=MAIN_CASE_QUALITY,
        tag=MAIN_CASE_TAG,
        notes="Imported from LA8159 main_latam_case_version",
        ref_store=ref_store,
        copy=args.copy,
        dry_run=args.dry_run,
    )

    # ── Pass 2: first_latam_case_version (earlier review draft)
    first_audios, first_seen = ingest_reference_dir(
        FIRST_REVIEW,
        quality=FIRST_REVIEW_QUALITY,
        tag=FIRST_REVIEW_TAG,
        notes=(
            "Imported from LA8159 first_latam_case_version (earlier review). "
            "Useful as secondary prior; review against main case for consolidation."
        ),
        ref_store=ref_store,
        copy=args.copy,
        dry_run=args.dry_run,
    )

    # Combine project audios (dedup by canonical_name)
    project_audios: list[ProjectAudio] = []
    seen_combined: set[str] = set()
    for a in main_audios + first_audios:
        if a.canonical_name in seen_combined:
            continue
        seen_combined.add(a.canonical_name)
        project_audios.append(a)

    # ── Pass 3: attach audio files from data/audio/
    n_attached, extra_audios = attach_audio_files(
        project_audios, ref_store, dry_run=args.dry_run
    )
    project_audios.extend(extra_audios)

    # ── Pass 4: project file (merge, never destroy manual edits)
    docs = collect_context_docs()
    project = project_store.load(PROJECT_ID) or Project(
        id=PROJECT_ID,
        name=PROJECT_NAME,
        description=PROJECT_DESCRIPTION,
        language="es",
        location="Arturo Merino Benítez International Airport, Santiago, Chile",
        qdrant_filter_tag=f"project:{PROJECT_ID}",
    )
    project.name = PROJECT_NAME
    project.description = PROJECT_DESCRIPTION
    project.qdrant_filter_tag = f"project:{PROJECT_ID}"

    # Merge audios: update audio_path on existing entries, append new ones
    existing_by_canon = {a.canonical_name: a for a in project.audios}
    for a in project_audios:
        prev = existing_by_canon.get(a.canonical_name)
        if prev is None:
            project.audios.append(a)
            existing_by_canon[a.canonical_name] = a
        else:
            if a.audio_path and prev.audio_path != a.audio_path:
                prev.audio_path = a.audio_path
            if a.recording_datetime and not prev.recording_datetime:
                prev.recording_datetime = a.recording_datetime
            if a.title and not prev.title:
                prev.title = a.title

    # Remove any excluded canonicals that may have existed from earlier runs.
    before_prune = len(project.audios)
    project.audios = [a for a in project.audios if a.canonical_name not in EXCLUDED_CANONICALS]
    if before_prune != len(project.audios):
        logger.info(
            "pruned %d excluded project audios",
            before_prune - len(project.audios),
        )

    # Merge context docs (dedup by path)
    existing_paths = {d.path for d in project.context_docs}
    for d in docs:
        if d.path not in existing_paths:
            project.context_docs.append(d)

    if args.dry_run:
        logger.info(
            "[dry] would write project %s with %d audios and %d context_docs",
            PROJECT_ID, len(project.audios), len(project.context_docs),
        )
    else:
        project_store.save(project)

    n_with_audio = sum(1 for a in project.audios if a.audio_path)
    logger.info(
        "DONE \u2014 main=%d, first_review=%d, audios attached=%d, "
        "extras from data/audio=%d, total project audios=%d (with audio_path: %d), context docs=%d",
        len(main_seen), len(first_seen), n_attached, len(extra_audios),
        len(project.audios), n_with_audio, len(docs),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
