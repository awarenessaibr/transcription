#!/usr/bin/env python3
"""
consolidate_speaker_md_files.py

Retire speaker profile files whose ``speaker_id`` is no longer in use.

Why this is needed
------------------
`fix_speaker_ids.py` collapsed 46 raw ``speaker_id`` values into 35 canonical
ones and minted 8 more. The transcripts were rewritten, but
``data/speakers/*.md`` was still keyed by the **old** ids, so:

* ~40 profile files are named after ids that no longer appear in any transcript;
* profile files for the new canonical ids (e.g. ``SPK-dgac``, ``SPK-pdi``) do
  not exist yet.

`generate_speaker_md_files.py` only archives a hard-coded ``ORPHANED_FILES``
list, so it will not clean up an arbitrary set of stale profiles. This script
does that one job, and refuses to touch anything that carries hand-written
content unless explicitly allowed.

Safety rules
------------
1. A file is *stale* when its stem is not a ``speaker_id`` present in any
   ``data/transcripts/*.json`` participant record.
2. A stale file is *curated* when its frontmatter ``key_statements`` is anything
   other than ``[]`` / empty. Curated files are reported and skipped unless
   ``--allow-curated`` is given.
3. Files are **moved** to ``data/speakers/.archive/``, never deleted. That
   directory is git-tracked, so every retirement is recoverable.
4. An existing archive entry is never overwritten — a ``.2``/``.3`` suffix is
   added instead.
5. ``--dry-run`` reports the plan without moving anything.

Typical use
-----------
    python3 scripts/consolidate_speaker_md_files.py --dry-run
    python3 scripts/consolidate_speaker_md_files.py
    python3 scripts/generate_speaker_index_v3.py
    python3 scripts/generate_speaker_md_files.py
    python3 scripts/generate_speaker_patch.py
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = REPO / "data" / "transcripts"
SPEAKERS_DIR = REPO / "data" / "speakers"
ARCHIVE_DIR = SPEAKERS_DIR / ".archive"

_FM = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_KEY_STATEMENTS = re.compile(r"^key_statements:(?P<inline>.*)$", re.MULTILINE)


def active_speaker_ids() -> set[str]:
    """Every non-empty ``speaker_id`` used by a transcript participant."""
    ids: set[str] = set()
    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        if f.name.endswith(".bak"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        for p in data.get("participants", []):
            sid = (p.get("speaker_id") or "").strip()
            if sid:
                ids.add(sid)
    return ids


def has_key_statements(text: str) -> bool:
    """True when the frontmatter carries at least one recorded key statement."""
    m = _FM.match(text)
    if not m:
        return False
    km = _KEY_STATEMENTS.search(m.group(1))
    if not km:
        return False
    inline = km.group("inline").strip()
    # `key_statements:` with nothing after it means the list continues on the
    # following (indented) lines — so anything other than a bare `[]` counts.
    return inline not in ("[]",)


def unique_destination(name: str) -> Path:
    """``foo.md`` → ``.archive/foo.md``, or ``foo.2.md`` if already archived."""
    dst = ARCHIVE_DIR / name
    if not dst.exists():
        return dst
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while True:
        candidate = ARCHIVE_DIR / f"{stem}.{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[3])
    parser.add_argument("--dry-run", action="store_true",
                        help="Report the plan without moving files")
    parser.add_argument("--allow-curated", action="store_true",
                        help="Also archive stale files that carry key_statements")
    args = parser.parse_args()

    ARCHIVE_DIR.mkdir(exist_ok=True)
    active = active_speaker_ids()

    archived: list[tuple[str, int]] = []
    curated: list[str] = []
    kept = 0

    for md in sorted(SPEAKERS_DIR.glob("*.md")):
        if md.stem in active:
            kept += 1
            continue

        text = md.read_text(encoding="utf-8")
        if has_key_statements(text) and not args.allow_curated:
            curated.append(md.stem)
            print(f"[keep]    {md.name} — stale id but carries key_statements")
            continue

        dst = unique_destination(md.name)
        size = md.stat().st_size
        if not args.dry_run:
            shutil.move(str(md), str(dst))
        print(f"[archive] {md.name} → .archive/{dst.name}")
        archived.append((md.name, size))

    print("\n" + "=" * 62)
    print(f"Active speaker ids   : {len(active)}")
    print(f"Profiles kept        : {kept}")
    print(f"Profiles archived    : {len(archived)}")
    print(f"Curated, left alone  : {len(curated)}")
    if curated:
        print("\nStale ids that still hold hand-written content:")
        for stem in curated:
            print(f"  {stem}")
        print("Re-run with --allow-curated once their content is re-homed.")
    print(f"Live profile files   : {len(list(SPEAKERS_DIR.glob('*.md')))}")
    if args.dry_run:
        print("\n(dry-run: nothing was moved)")


if __name__ == "__main__":
    main()
