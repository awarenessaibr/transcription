#!/usr/bin/env python3
"""
collect_observations.py

Read every JSON transcript under a directory and emit a single consolidated
file containing all segments whose analyst-observation fields
(`correction_note` and/or `backchannel_events`) are non-empty.

Usage:
    python scripts/collect_observations.py \
        --input  data/transcripts \
        --output data/refiner/observations.json \
        --fields correction_note backchannel_events \
        --mode   any

Modes:
    any  -> segment is kept if ANY configured field is non-empty  (default)
    all  -> segment is kept only if ALL configured fields are non-empty

The script never writes back into source files.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


DEFAULT_FIELDS = ("correction_note", "backchannel_events")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def iter_json_files(root: Path) -> Iterable[Path]:
    """Yield every .json file under root, sorted for deterministic output."""
    for p in sorted(root.rglob("*.json")):
        if p.is_file():
            yield p


def safe_load(path: Path) -> Any | None:
    """Load JSON, returning None (and warning to stderr) on parse failure."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"[WARN] could not parse {path}: {exc}", file=sys.stderr)
        return None


def is_non_empty(value: Any) -> bool:
    """Treat None, '', whitespace-only strings, and empty lists as empty."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def find_segments_container(doc: dict) -> tuple[str, list] | None:
    """
    Return (path_label, segments_list) for the first recognised container.

    Recognised:
        - doc["segments"]                  -> original transcript
        - doc["refiner"]["segments"]       -> hypothetical refiner variant
    """
    if isinstance(doc.get("segments"), list):
        return ("segments", doc["segments"])
    refiner = doc.get("refiner")
    if isinstance(refiner, dict) and isinstance(refiner.get("segments"), list):
        return ("refiner.segments", refiner["segments"])
    return None


# --------------------------------------------------------------------------- #
# Observation extraction
# --------------------------------------------------------------------------- #

@dataclass
class Observation:
    source_file: str
    transcript_id: str | None
    case_id: str | None
    narrative_id: str | None
    chronological_order: int | None
    segment_index: int | None
    segment_datetime: str | None
    speaker: str | None
    speaker_id: str | None
    start: float | None
    end: float | None
    text: str | None
    fields: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "source_file": self.source_file,
            "transcript_id": self.transcript_id,
            "case_id": self.case_id,
            "narrative_id": self.narrative_id,
            "chronological_order": self.chronological_order,
            "segment_index": self.segment_index,
            "segment_datetime": self.segment_datetime,
            "speaker": self.speaker,
            "speaker_id": self.speaker_id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "observations": self.fields,
        }


def matches(segment: dict, fields: list[str], mode: str) -> bool:
    checks = [is_non_empty(segment.get(f)) for f in fields]
    if mode == "any":
        return any(checks)
    if mode == "all":
        return all(checks)
    raise ValueError(f"unknown mode: {mode!r}")


def extract_from_document(
    doc: dict,
    source_path: Path,
    fields: list[str],
    mode: str,
) -> list[Observation]:
    container = find_segments_container(doc)
    if container is None:
        print(f"[SKIP] no recognised segments container in {source_path}",
              file=sys.stderr)
        return []

    _label, segments = container
    out: list[Observation] = []

    for seg in segments:
        if not isinstance(seg, dict):
            continue
        if not matches(seg, fields, mode):
            continue

        obs_fields = {
            f: seg.get(f) for f in fields if is_non_empty(seg.get(f))
        }

        out.append(Observation(
            source_file=str(source_path),
            transcript_id=doc.get("transcript_id"),
            case_id=doc.get("case_id"),
            narrative_id=doc.get("narrative_id"),
            chronological_order=doc.get("chronological_order"),
            segment_index=seg.get("index"),
            segment_datetime=seg.get("segment_datetime"),
            speaker=seg.get("speaker"),
            speaker_id=seg.get("speaker_id"),
            start=seg.get("start"),
            end=seg.get("end"),
            text=seg.get("text"),
            fields=obs_fields,
        ))
    return out


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def build_index(observations: list[Observation]) -> dict:
    """Group observations by transcript, then by field, for quick lookup."""
    by_transcript: dict[str, list[dict]] = {}
    by_field: dict[str, list[dict]] = {}

    for obs in observations:
        d = obs.as_dict()
        key = obs.transcript_id or obs.source_file
        by_transcript.setdefault(key, []).append(d)
        for fname in obs.fields:
            by_field.setdefault(fname, []).append({
                "transcript_id": obs.transcript_id,
                "segment_index": obs.segment_index,
                "text": obs.text,
                "value": obs.fields[fname],
                "source_file": obs.source_file,
            })

    return {"by_transcript": by_transcript, "by_field": by_field}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True,
                        help="Directory containing transcript JSON files")
    parser.add_argument("--output", required=True,
                        help="Path to write the consolidated observations file")
    parser.add_argument("--fields", nargs="+", default=list(DEFAULT_FIELDS),
                        help="Observation fields to scan "
                             f"(default: {list(DEFAULT_FIELDS)})")
    parser.add_argument("--mode", choices=("any", "all"), default="any",
                        help="Keep segment if ANY or ALL fields are non-empty")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print the output JSON")
    args = parser.parse_args(argv)

    root = Path(args.input)
    if not root.is_dir():
        print(f"[ERROR] input is not a directory: {root}", file=sys.stderr)
        return 2

    all_obs: list[Observation] = []
    files_scanned = 0

    for path in iter_json_files(root):
        doc = safe_load(path)
        if doc is None:
            continue
        files_scanned += 1
        all_obs.extend(
            extract_from_document(doc, path, args.fields, args.mode)
        )

    payload = {
        "generated_from": str(root.resolve()),
        "fields_scanned": list(args.fields),
        "match_mode": args.mode,
        "files_scanned": files_scanned,
        "observations_count": len(all_obs),
        "observations": [o.as_dict() for o in all_obs],
        "index": build_index(all_obs),
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        if args.pretty:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        else:
            json.dump(payload, fh, ensure_ascii=False)

    print(f"[OK] scanned {files_scanned} files, "
          f"wrote {len(all_obs)} observations to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())