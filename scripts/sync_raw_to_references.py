"""Sync the user's curated transcript source-of-truth into the reference store.

Layout assumptions
------------------
The reconciler reads priors from::

    data/transcripts_by_audio/<canonical_name>/manifest.json
    data/transcripts_by_audio/<canonical_name>/<file>.json   (often a symlink)

Symlinks under ``transcripts_by_audio/`` historically pointed at::

    data/LA8159_files/main_latam_case_version/<file>.json

The user's freshly curated transcripts now live at::

    /Users/leandrodisconzi/work/business/OliviaLegal/cases/INCIDENTS/
        INCIDENT_2024-07-05/transcripts/raw/<file>.json

This script makes ``main_latam_case_version/`` mirror ``raw/`` so the existing
relative symlinks under ``transcripts_by_audio/`` continue to resolve, while
quarantining files that exist in main but not in raw (the user said
"contamination must be avoided").

Behaviour
---------

* ``--dry-run`` (default): prints actions, mutates nothing.
* ``--apply``: actually performs the copy / quarantine / removal.
* Always:
    - creates ``main_latam_case_version.backup_<TS>/`` first when applying.
    - moves main-only files into ``main_latam_case_version/_quarantine_<TS>/``
      instead of deleting (reversible).
    - copies (does not symlink) raw → main so files remain self-contained.
* Reports:
    - which symlinks under ``transcripts_by_audio/`` are dangling after the swap
    - which raw files have no ``transcripts_by_audio/`` host directory
"""
from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys
import time
from pathlib import Path

DEFAULT_RAW = Path(
    "/Users/leandrodisconzi/work/business/OliviaLegal/cases/INCIDENTS/"
    "INCIDENT_2024-07-05/transcripts/raw"
)
DEFAULT_MAIN = Path("data/LA8159_files/main_latam_case_version")
DEFAULT_REFS = Path("data/transcripts_by_audio")


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _list_jsons(d: Path) -> list[str]:
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file() and p.suffix == ".json")


def _diff_dirs(raw: Path, main: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    raw_files = set(_list_jsons(raw))
    main_files = set(_list_jsons(main))
    common = sorted(raw_files & main_files)
    only_main = sorted(main_files - raw_files)
    only_raw = sorted(raw_files - main_files)
    differing = [f for f in common if not filecmp.cmp(raw / f, main / f, shallow=False)]
    return common, only_main, only_raw, differing


def _scan_dangling_symlinks(refs_dir: Path) -> list[Path]:
    out: list[Path] = []
    if not refs_dir.is_dir():
        return out
    for sub in refs_dir.iterdir():
        if not sub.is_dir():
            continue
        for f in sub.iterdir():
            if f.is_symlink() and not f.exists():
                out.append(f)
    return out


def _hosts_for(refs_dir: Path, raw_filename: str) -> list[Path]:
    """Find ``transcripts_by_audio/<canonical>/`` dirs whose symlinks resolve
    to ``raw_filename`` (basename match)."""
    hosts: list[Path] = []
    if not refs_dir.is_dir():
        return hosts
    for sub in refs_dir.iterdir():
        if not sub.is_dir():
            continue
        for f in sub.iterdir():
            if not f.is_symlink():
                continue
            try:
                target = (f.parent / os.readlink(f)).resolve(strict=False)
            except OSError:
                continue
            if target.name == raw_filename:
                hosts.append(sub)
                break
    return hosts


def _print_section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--main", type=Path, default=DEFAULT_MAIN)
    parser.add_argument("--refs", type=Path, default=DEFAULT_REFS)
    parser.add_argument("--apply", action="store_true",
                        help="Actually perform changes (otherwise dry-run).")
    args = parser.parse_args()

    raw = args.raw.resolve()
    main = args.main.resolve()
    refs = args.refs.resolve()

    if not raw.is_dir():
        print(f"[error] raw dir not found: {raw}", file=sys.stderr)
        return 2
    if not main.is_dir():
        print(f"[error] main dir not found: {main}", file=sys.stderr)
        return 2

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[mode] {mode}")
    print(f"[raw ] {raw}")
    print(f"[main] {main}")
    print(f"[refs] {refs}")

    common, only_main, only_raw, differing = _diff_dirs(raw, main)

    _print_section("Inventory")
    print(f"raw files          : {len(_list_jsons(raw))}")
    print(f"main files         : {len(_list_jsons(main))}")
    print(f"  common names     : {len(common)}")
    print(f"  differing content: {len(differing)}")
    print(f"  only in main     : {len(only_main)}")
    print(f"  only in raw      : {len(only_raw)}")

    if only_main:
        _print_section("Only-in-main (will be quarantined, not deleted)")
        for f in only_main:
            hosts = _hosts_for(refs, f)
            host_str = ", ".join(h.name for h in hosts) or "(no host dir)"
            print(f"  {f}    referenced by: {host_str}")

    if only_raw:
        _print_section("Only-in-raw (will be added to main)")
        for f in only_raw:
            hosts = _hosts_for(refs, f)
            host_str = ", ".join(h.name for h in hosts) or "(no host dir — needs manual mapping)"
            print(f"  {f}    host: {host_str}")

    if differing:
        _print_section(f"Content-changed ({len(differing)}) — will be overwritten in main")
        for f in differing[:10]:
            sz_main = (main / f).stat().st_size
            sz_raw = (raw / f).stat().st_size
            print(f"  {f}    main={sz_main}b  raw={sz_raw}b  (delta {sz_raw - sz_main:+d}b)")
        if len(differing) > 10:
            print(f"  ... and {len(differing) - 10} more")

    pre_dangling = _scan_dangling_symlinks(refs)
    if pre_dangling:
        _print_section("Pre-existing dangling symlinks (already broken)")
        for f in pre_dangling[:20]:
            print(f"  {f}")

    if not args.apply:
        _print_section("Dry-run summary — no changes made")
        print("Re-run with --apply to perform the sync.")
        return 0

    # ── APPLY ──────────────────────────────────────────────────────────
    ts = _ts()
    backup_dir = main.parent / f"{main.name}.backup_{ts}"
    quarantine_dir = main / f"_quarantine_{ts}"

    _print_section("APPLY: creating backup")
    print(f"copy {main} -> {backup_dir}")
    shutil.copytree(main, backup_dir, symlinks=True)

    if only_main:
        _print_section("APPLY: quarantine only-in-main")
        quarantine_dir.mkdir(exist_ok=True)
        for f in only_main:
            src = main / f
            dst = quarantine_dir / f
            print(f"  mv {src.name} -> {dst}")
            shutil.move(str(src), str(dst))

    _print_section("APPLY: overwrite changed + add new")
    for f in differing + only_raw:
        src = raw / f
        dst = main / f
        print(f"  cp {src} -> {dst}")
        shutil.copy2(src, dst)

    _print_section("APPLY: post-sync sanity check")
    post_dangling = _scan_dangling_symlinks(refs)
    if post_dangling:
        print(f"!! {len(post_dangling)} dangling symlinks after sync:")
        for f in post_dangling[:20]:
            print(f"  {f}")
    else:
        print("ok — no dangling symlinks.")

    # Files in raw not yet linked from any transcripts_by_audio host dir.
    unhosted: list[str] = []
    for f in only_raw:
        if not _hosts_for(refs, f):
            unhosted.append(f)
    if unhosted:
        print()
        print(f"!! {len(unhosted)} new raw files have no transcripts_by_audio host dir:")
        for f in unhosted:
            print(f"  {f}    (run scripts/bootstrap_la8159_references.py to wire)")
    print()
    print("Backup retained at:", backup_dir)
    print("Quarantine:", quarantine_dir if only_main else "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
