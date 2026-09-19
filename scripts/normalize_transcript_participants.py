#!/usr/bin/env python3
"""
normalize_transcript_participants.py

Phase 2: Update transcript participant headers.
- Applies ID merges (SPK-dgac-nicolas → SPK-dgac-don-nicolas)
- Ensures segment speakers that match a participant label get the speaker_id in the segment payload
  (note: segments themselves don't have speaker_id fields, but participants must be complete)
- Reports any participants still missing speaker_id
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = REPO / "data" / "transcripts"

ID_MERGES: dict[str, str] = {
    "SPK-dgac-nicolas": "SPK-dgac-don-nicolas",
}


def main() -> None:
    updated_files = 0
    total_participants_fixed = 0

    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        if f.name.endswith(".bak"):
            continue

        data = json.loads(f.read_text(encoding="utf-8"))
        changed = False

        # Apply ID merges to participants
        for p in data.get("participants", []):
            raw_id = p.get("speaker_id", "")
            merged = ID_MERGES.get(raw_id)
            if merged:
                p["speaker_id"] = merged
                changed = True
                total_participants_fixed += 1
                print(f"  [merge] {f.name}: participant {p.get('speaker_label')!r}: {raw_id} → {merged}")

        if changed:
            # Write backup first
            bak = f.with_suffix(".json.bak")
            if not bak.exists():
                bak.write_bytes(f.read_bytes())
            f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            updated_files += 1

    # Report participants still missing speaker_id
    print("\n=== Participants with NO speaker_id (need manual assignment) ===")
    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        if f.name.endswith(".bak"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        tid = data.get("transcript_id", f.stem)
        for p in data.get("participants", []):
            if not p.get("speaker_id"):
                print(f"  {tid} | {p.get('speaker_label')!r} | {p.get('canonical_name')!r}")

    print(f"\nFiles updated: {updated_files}")
    print(f"IDs merged: {total_participants_fixed}")


if __name__ == "__main__":
    main()
