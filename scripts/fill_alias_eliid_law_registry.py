#!/usr/bin/env python3
"""
Fill alias_eli in data/law/_mapping/law_registry.json from alias_map.json.

Usage:
    python scripts/fill_alias_eliid_law_registry.py
    python scripts/fill_alias_eliid_law_registry.py --write
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_DIR = REPO_ROOT / "data" / "law" / "_mapping"
ALIAS_MAP_PATH = MAPPING_DIR / "alias_map.json"
REGISTRY_PATH = MAPPING_DIR / "law_registry.json"


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description="Fill alias_eli in law_registry.json using alias_map.json."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write changes in place. Without this, runs as dry-run.",
    )
    args = parser.parse_args()

    alias_map = load_json(ALIAS_MAP_PATH)["aliases"]
    registry = load_json(REGISTRY_PATH)

    # target ELI -> alias citation ELI(s)
    target_to_aliases: dict[str, list[str]] = {}
    for alias, target in alias_map.items():
        target_to_aliases.setdefault(target, []).append(alias)

    changed = 0

    for entry in registry.get("files", []):
        local_elis = set(entry.get("missing_eli", [])) | set(
            entry.get("in_qdrant_eli", [])
        )
        existing = set(entry.get("alias_eli", []))
        new_aliases = set(existing)

        for target, aliases in target_to_aliases.items():
            if target in local_elis:
                new_aliases.update(aliases)

        if new_aliases != existing:
            entry["alias_eli"] = sorted(new_aliases)
            changed += 1
            print(f"{entry['file']}: {len(new_aliases)} alias_eli")

    if args.write:
        if REGISTRY_PATH.exists():
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            backup = REGISTRY_PATH.with_suffix(
                REGISTRY_PATH.suffix + f".bak.{stamp}"
            )
            shutil.copy2(REGISTRY_PATH, backup)
            print(f"Backup written: {backup}")

        dump_json(REGISTRY_PATH, registry)
        print(f"Updated {REGISTRY_PATH} ({changed} entries changed)")
    else:
        print(f"Dry-run: {changed} entries would change. Use --write to save.")


if __name__ == "__main__":
    main()