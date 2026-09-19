#!/usr/bin/env python3
"""
generate_speaker_index_v3.py

Phase 3: Rebuild speaker_index.json cleanly.
- Source: data/transcripts/ ONLY (not transcripts-named/)
- Groups by canonical speaker_id
- Uses participants[].segment_labels to match segments to speakers
- Reads display_name, organization, role from speaker MD files
- Output: concise — one entry per SPK-..., with full cross-transcript summary
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = REPO / "data" / "transcripts"
SPEAKERS_DIR = REPO / "data" / "speakers"
OUTPUT = REPO / "data" / "speaker_index.json"

ID_MERGES: dict[str, str] = {
    "SPK-dgac-nicolas": "SPK-dgac-don-nicolas",
}


def read_frontmatter(md_path: Path) -> dict:
    """Extract YAML frontmatter from a speaker MD file."""
    text = md_path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    fm: dict = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith(" ") and not line.startswith("-"):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm


def main() -> None:
    # ── Collect from transcripts ──────────────────────────────────────────────
    # {spk_id: {transcripts: {tid: {labels: set, seg_indices: list}}, participants: [...]}}
    speaker_map: dict[str, dict] = {}

    total_segments = 0
    total_transcripts = 0

    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        if f.name.endswith(".bak"):
            continue

        data = json.loads(f.read_text(encoding="utf-8"))
        tid = data.get("transcript_id", f.stem)
        total_transcripts += 1

        participants = data.get("participants", [])

        # Build label→spk_id lookup using segment_labels (primary) and descriptive fields (fallback)
        label_to_spk: dict[str, str] = {}
        for p in participants:
            raw_id = p.get("speaker_id", "")
            if not raw_id:
                continue
            spk_id = ID_MERGES.get(raw_id, raw_id)
            # Primary: segment_labels are the exact labels used in segment.speaker fields
            for seg_label in p.get("segment_labels", []):
                label_to_spk[seg_label.strip().lower()] = spk_id
            # Fallback: descriptive fields
            for field in ("speaker_label", "role", "canonical_name"):
                val = (p.get(field) or "").strip().lower()
                if val:
                    label_to_spk.setdefault(val, spk_id)

        # From participants: register in speaker_map
        for p in participants:
            raw_id = p.get("speaker_id", "")
            if not raw_id:
                continue
            spk_id = ID_MERGES.get(raw_id, raw_id)
            if spk_id not in speaker_map:
                speaker_map[spk_id] = {"transcripts": {}, "participants": []}
            speaker_map[spk_id]["participants"].append({**p, "_transcript_id": tid})
            if tid not in speaker_map[spk_id]["transcripts"]:
                speaker_map[spk_id]["transcripts"][tid] = {"labels": set(), "seg_indices": []}

        # From segments: match each segment's label to a speaker_id
        segments = data.get("segments", [])
        total_segments += len(segments)

        for i, seg in enumerate(segments):
            idx = seg.get("index", i)
            label = (seg.get("speaker") or "").strip()
            label_lower = label.lower()

            spk_id = label_to_spk.get(label_lower)

            if spk_id:
                spk_id = ID_MERGES.get(spk_id, spk_id)
                if spk_id not in speaker_map:
                    speaker_map[spk_id] = {"transcripts": {}, "participants": []}
                if tid not in speaker_map[spk_id]["transcripts"]:
                    speaker_map[spk_id]["transcripts"][tid] = {"labels": set(), "seg_indices": []}
                speaker_map[spk_id]["transcripts"][tid]["labels"].add(label)
                speaker_map[spk_id]["transcripts"][tid]["seg_indices"].append(idx)

    # ── Collect unmapped segment speakers ─────────────────────────────────────
    unmapped: list[dict] = []
    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        if f.name.endswith(".bak"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        tid = data.get("transcript_id", f.stem)
        segments = data.get("segments", [])
        participants = data.get("participants", [])

        # Rebuild covered set for this transcript
        covered_labels: set[str] = set()
        for p in participants:
            if not p.get("speaker_id"):
                continue
            for seg_label in p.get("segment_labels", []):
                covered_labels.add(seg_label.strip().lower())
            for field in ("speaker_label", "role", "canonical_name"):
                val = (p.get(field) or "").strip().lower()
                if val:
                    covered_labels.add(val)

        for i, seg in enumerate(segments):
            idx = seg.get("index", i)
            label = (seg.get("speaker") or "").strip()
            if label.lower() not in covered_labels:
                unmapped.append({"transcript_id": tid, "segment_index": idx, "speaker": label})

    # ── Build output ──────────────────────────────────────────────────────────
    mapped_out: dict[str, dict] = {}

    for spk_id, info in sorted(speaker_map.items()):
        # Load MD file for canonical metadata
        md_path = SPEAKERS_DIR / f"{spk_id}.md"
        fm = read_frontmatter(md_path) if md_path.exists() else {}

        appearances = []
        for tid, tinfo in sorted(info["transcripts"].items()):
            entry: dict = {"transcript_id": tid}
            labels = sorted(tinfo["labels"])
            if labels:
                entry["segment_labels"] = labels
            if tinfo["seg_indices"]:
                entry["segment_indices"] = sorted(set(tinfo["seg_indices"]))
            appearances.append(entry)

        # Collect canonical name from participants
        canon_names = list({
            p.get("canonical_name", "")
            for p in info["participants"]
            if p.get("canonical_name")
        })

        mapped_out[spk_id] = {
            "display_name": fm.get("display_name") or (canon_names[0] if canon_names else spk_id),
            "organization": fm.get("organization") or "Unknown",
            "identification_confidence": fm.get("identification_confidence") or "unknown",
            "md_file": f"data/speakers/{spk_id}.md" if md_path.exists() else None,
            "appearances": appearances,
        }

    # Summarize unmapped by label
    unmapped_summary: dict[str, list] = {}
    for u in unmapped:
        key = f"{u['speaker']} [{u['transcript_id']}]"
        unmapped_summary.setdefault(u["speaker"], [])
        if u["transcript_id"] not in unmapped_summary[u["speaker"]]:
            unmapped_summary[u["speaker"]].append(u["transcript_id"])

    output = {
        "summary": {
            "generated_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "source": "data/transcripts/",
            "total_transcripts_scanned": total_transcripts,
            "total_segments_scanned": total_segments,
            "total_mapped_speaker_ids": len(mapped_out),
            "total_unmapped_segment_instances": len(unmapped),
        },
        "mapped_speakers": mapped_out,
        "unmapped_segment_labels": unmapped_summary,
    }

    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=" * 60)
    print("SPEAKER INDEX REBUILT")
    print("=" * 60)
    print(f"Transcripts scanned  : {total_transcripts}")
    print(f"Segments scanned     : {total_segments}")
    print(f"Mapped speaker IDs   : {len(mapped_out)}")
    print(f"Unmapped seg labels  : {len(unmapped_summary)} unique labels, {len(unmapped)} instances")
    if unmapped_summary:
        print("\nUnmapped labels:")
        for label, tids in sorted(unmapped_summary.items()):
            print(f"  {label!r} in: {tids}")
    print(f"\nOutput: {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
