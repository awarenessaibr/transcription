"""Filesystem-based incident narrative store.

Implements NarrativeStorePort. Reads .txt narratives from:
  data/transcripts_narrative/

Filename pattern:
  incident_narrative_<audio_id>_<ISO-datetime>.txt

Maps narrative audio_ids to canonical audio names using the same
normalization as organize_references.py.
"""
from __future__ import annotations

import logging
import os
import re

from src.domain.entities.reference import IncidentNarrative

logger = logging.getLogger(__name__)

# Maps narrative audio identifiers that don't follow the standard
# naming to their canonical audio names. These are cross-references:
# narratives recorded at different locations about the same events.
_ALIAS_MAP: dict[str, list[str]] = {
    # latam_STG_2/3 are LATAM-side recordings related to aeropuerto_stg events
    "latam_stg_2": ["aeropuerto_stg_2"],
    "latam_stg_3": ["aeropuerto_stg_3"],
    # carabineros PPDartnell recording maps to Pedro Pablo Dartnell audio
    "carabineros_ppdartnel_1": ["pedro_pablo_dartnell"],
}


def _normalize(name: str) -> str:
    """Normalize an identifier to canonical form."""
    name = name.lower()
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ñ": "n", "ü": "u",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def _parse_narrative_filename(filename: str) -> tuple[str, str]:
    """Extract audio_id and timeline_time from a narrative filename.

    Returns (audio_id, timeline_time) where audio_id is the identifier
    before the ISO datetime suffix.
    """
    # Strip extension and prefix
    stem = os.path.splitext(filename)[0]
    stem = stem.removeprefix("incident_narrative_")

    # Match ISO datetime suffix: _YYYY-MM-DDTHH-MM-SS.000Z
    m = re.search(r"_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d+Z)\s*$", stem)
    if m:
        timeline_time = m.group(1)
        audio_id = stem[: m.start()]
    else:
        timeline_time = ""
        audio_id = stem

    return audio_id.strip(), timeline_time


def _parse_narrative_header(text: str) -> dict[str, str]:
    """Parse the header block at the top of a narrative file."""
    header: dict[str, str] = {}
    for line in text.split("\n")[:6]:
        line = line.strip()
        if line.startswith("Title:"):
            header["title"] = line.removeprefix("Title:").strip()
        elif line.startswith("Timeline Time:"):
            header["timeline_time"] = line.removeprefix("Timeline Time:").strip()
        elif line.startswith("Saved:"):
            header["saved"] = line.removeprefix("Saved:").strip()
    return header


class NarrativeStoreAdapter:
    """Filesystem narrative store. Implements NarrativeStorePort."""

    def __init__(self, narrative_dir: str = "data/transcripts_narrative"):
        self._dir = narrative_dir
        self._index: dict[str, list[str]] | None = None  # canonical → [filepaths]

    def _build_index(self) -> dict[str, list[str]]:
        """Build mapping from canonical names to narrative file paths."""
        index: dict[str, list[str]] = {}
        if not os.path.isdir(self._dir):
            return index

        for fname in sorted(os.listdir(self._dir)):
            if not fname.endswith(".txt"):
                continue
            audio_id, _ = _parse_narrative_filename(fname)
            canonical = _normalize(audio_id)
            fpath = os.path.join(self._dir, fname)

            # Direct mapping
            index.setdefault(canonical, []).append(fpath)

            # Alias mappings (cross-references)
            for alias_target in _ALIAS_MAP.get(canonical, []):
                index.setdefault(alias_target, []).append(fpath)

        return index

    def _get_index(self) -> dict[str, list[str]]:
        if self._index is None:
            self._index = self._build_index()
        return self._index

    def load_narratives(self, canonical_name: str) -> list[IncidentNarrative]:
        """Load all narratives matching a canonical audio name."""
        index = self._get_index()
        paths = index.get(canonical_name, [])
        if not paths:
            return []

        narratives: list[IncidentNarrative] = []
        for path in paths:
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                header = _parse_narrative_header(text)
                narratives.append(
                    IncidentNarrative(
                        audio_id=canonical_name,
                        title=header.get("title", ""),
                        timeline_time=header.get("timeline_time", ""),
                        text=text,
                        source_file=os.path.basename(path),
                    )
                )
            except (OSError, UnicodeDecodeError) as e:
                logger.warning("[narrative] failed to read %s: %s", path, e)

        logger.info(
            "[narrative] loaded %d narratives for '%s'",
            len(narratives),
            canonical_name,
        )
        return narratives

    def list_all(self) -> list[str]:
        """List all canonical names that have narratives."""
        return sorted(self._get_index().keys())
