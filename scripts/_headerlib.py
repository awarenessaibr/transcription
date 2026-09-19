#!/usr/bin/env python3
"""
_headerlib.py

Shared plumbing for the transcript *header* normalisation scripts.

The header pass is split into one script per concern (chain/lineage,
violations, records, vocabulary, speakers).  Every one of them needs the same
three things, so they live here instead of being copy-pasted five times:

  * the canonical top-level key order (imported, not re-declared -- a second
    copy of ``TOP_ORDER`` would let a reorder masquerade as a data change),
  * a loader that keeps file order stable and normalises NFD/NFC, and
  * a writer that reproduces the exact serialisation the rest of the corpus
    already uses, so ``git diff`` stays meaningful.

The serialisation contract is load-bearing.  All 27 transcripts round-trip
byte-identically through ``dumps(indent=2, ensure_ascii=False) + "\\n"``.
Changing it rewrites every line of every file and buries the real edits.

Usage:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _headerlib import TRANSCRIPTS_DIR, TOP_ORDER, load_docs, save_docs
"""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The transcript corpus and the application live under ``transcription/``; the
# violation registry and case workspace sit one level above it.
WORKSPACE = REPO.parent
TRANSCRIPTS_DIR = REPO / "data" / "transcripts"

# One definition, in the script that established the order.  Importing it keeps
# the two in lockstep; a divergence would silently reorder keys.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from backfill_audio_metadata import TOP_ORDER  # noqa: E402  (path set above)

__all__ = [
    "REPO",
    "WORKSPACE",
    "TRANSCRIPTS_DIR",
    "TOP_ORDER",
    "nfc",
    "ordered",
    "load_docs",
    "save_docs",
    "dumps",
]


def nfc(text: str) -> str:
    """macOS stores filenames decomposed (NFD), the JSON holds NFC."""
    return unicodedata.normalize("NFC", text)


def ordered(d: dict, order: list[str] | None = None) -> dict:
    """Return ``d`` with keys in canonical order; unknown keys keep their place.

    Anything not named in ``order`` is appended in its existing order, so a new
    field is never silently dropped by a save.
    """
    order = order or TOP_ORDER
    out = {k: d[k] for k in order if k in d}
    for k, v in d.items():
        if k not in out:
            out[k] = v
    return out


def dumps(data: dict) -> str:
    """The corpus-wide serialisation: 2-space indent, literal UTF-8, trailing NL."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def load_docs() -> dict[str, dict]:
    """Load every transcript, keyed by filename stem, in stable sorted order.

    ``filename -> data`` is also stored on each doc as a transient
    ``"_stem"``-free lookup: callers that need the stem should iterate
    ``load_docs().items()``.
    """
    docs: dict[str, dict] = {}
    for path in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        docs[nfc(path.stem)] = json.loads(path.read_text(encoding="utf-8"))
    return docs


def save_docs(docs: dict[str, dict], *, dry_run: bool = False) -> int:
    """Write each doc back in canonical key order.  Returns the count written."""
    if dry_run:
        return len(docs)
    written = 0
    for stem, data in docs.items():
        path = TRANSCRIPTS_DIR / f"{stem}.json"
        path.write_text(dumps(ordered(data)), encoding="utf-8")
        written += 1
    return written
