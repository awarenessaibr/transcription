#!/usr/bin/env python3
"""
backfill_audio_metadata.py

Phase 1 of the transcript header repair: provenance + media metadata.

Source of truth is the original recordings in ``data/audio/*.m4a``, probed
directly with ffprobe.  Nothing is inferred from the values already stored in
the transcripts -- those are what we are trying to fix.

For every transcript in ``data/transcripts/*.json`` this script:

  * sets ``source_file``             -> real on-disk audio filename (one value kind)
  * adds ``source_path``             -> workspace-relative path to that file
  * sets ``provider``                -> "local" (overwrites the bogus "unknown")
  * sets ``recording_datetime`` and ``timestamp`` to the real device instant,
    taken from the file's own QuickTime header and converted to Chile time
  * rewrites ``metadata.file_info``       -> probed container facts, typed
  * rewrites ``metadata.audio_properties``-> probed duration/sample_rate/channels, typed
  * adds ``metadata.timestamps.QuickTime_Movie_Header_Created_verified``
  * sets ``metadata.saved_audio_file`` / ``processed_audio_file`` to the
    real recording filename
  * sets ``metadata.ontology_schema_version``
  * fills ``metadata.ontology_node_id`` with "" only where it is absent
  * reorders the top-level keys so ``source_path`` sits beside ``source_file``

Deliberately NOT done here:

  * ``QuickTime_Movie_Header_Created`` is left byte-for-byte untouched even
    though it is provably +3h wrong.  The probed value goes in the
    ``_verified`` sibling instead, so both survive.
  * ``metadata.ontology_node_id`` is never blanked when it already holds a
    real identifier -- existing values are preserved.
  * The recordings listed in ``TIME_OVERRIDES`` keep their stored time.  That
    is not a general escape hatch: it exists for one file whose own tag is
    provably a duplicate of a different recording's tag.

Timezone note: July 2024 in Chile is UTC-4 (DST runs Sep->Apr).  The QuickTime
``creation_time`` tag is true UTC, so the local wall clock is that instant
minus four hours.  Note that the stored ``QuickTime_Movie_Header_Created`` is
itself wrong by +3h -- it was written as though Chile were UTC-3 -- which is
why a ~7h disagreement appears when the two are compared naively.  It is two
separate errors, not one drift.

See docs/AUDIO_SOURCE_MAPPING.md for the evidence behind the mapping.

Usage:
    python3 scripts/backfill_audio_metadata.py --dry-run
    python3 scripts/backfill_audio_metadata.py
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = REPO / "data" / "transcripts"
AUDIO_DIR = REPO / "data" / "audio"

# Chile Standard Time in July 2024 (DST runs Sep->Apr, so July is UTC-4).
CHILE_OFFSET = "-04:00"
CHILE_TZ = timezone(timedelta(hours=-4))

ONTOLOGY_SCHEMA_VERSION = "2.5"

# Manual exceptions to the "trust the file" rule, keyed by transcript_id.
# Each one is a deliberate, documented decision -- see
# docs/AUDIO_SOURCE_MAPPING.md section 6 before changing or removing it.
#
#   I-002_11 (barraza counter, 20.m4a)
#       Its QuickTime ``creation_time`` is byte-identical to the one on
#       ``Terminal Internacional - T2.m4a``.  Two different recordings cannot
#       have been created at the same instant, so at least one tag was copied
#       by an export step; ``20.m4a`` is the weaker case (T2's metadata block
#       is already known to hold values copied from other files).  The
#       hand-entered 18:20:00 also sits a sensible 34 minutes after the T2
#       counter recording, so it is kept.
TIME_OVERRIDES = {
    "I-002_11_NAR-13_STG_20_barraza_counter": "2024-07-05T18:20:00" + CHILE_OFFSET,
}

# Alphabetical, matching the convention already used by the existing files.
METADATA_ORDER = [
    "audio_properties",
    "file_info",
    "ontology_node_id",
    "ontology_schema_version",
    "processed_audio_file",
    "saved_audio_file",
    "timestamps",
]

# Canonical top-level key order.  ``source_path`` belongs beside ``source_file``;
# previously it was appended after ``segments`` because dict insertion order
# put new keys last.
TOP_ORDER = [
    "transcript_id",
    "source_file",
    "source_path",
    "language",
    "timestamp",
    "provider",
    "original_transcript_id",
    "metadata",
    "title",
    "subtitle",
    "recording_datetime",
    "location",
    "audio_id",
    "case_id",
    "narrative_id",
    "chronological_order",
    "prior_stage",
    "next_stage",
    "classification",
    "participants",
    "violations_cited",
    "tags",
    "forensic_clusters",
    "key_evidentiary_findings",
    "corrections_applied",
    "segments",
    "reviewed",
]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def nfc(text: str) -> str:
    """macOS stores filenames decomposed (NFD); normalise for comparison."""
    return unicodedata.normalize("NFC", text)


def fmt_duration(seconds: float) -> str:
    """Seconds -> ``HH:MM:SS.mmm``."""
    total_ms = int(round(float(seconds) * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def split_brands(value: str | None) -> list[str]:
    """A compatible-brands string is a run of 4-character brand codes."""
    if not value:
        return []
    raw = value.rstrip()
    return [raw[i : i + 4].strip() for i in range(0, len(raw), 4) if raw[i : i + 4].strip()]


def naive(value: str | None) -> datetime | None:
    """Parse a stamp to a naive wall-clock datetime, discarding any zone."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if v.upper().endswith("Z"):
        v = v[:-1]
    v = re.sub(r"[+-]\d{2}:\d{2}$", "", v)
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def local_stamp(utc_tag: str | None) -> str | None:
    """Convert a UTC QuickTime tag to the Chile wall clock, second precision."""
    d = naive(utc_tag)
    if d is None:
        return None
    return d.replace(tzinfo=timezone.utc).astimezone(CHILE_TZ).strftime("%Y-%m-%dT%H:%M:%S") + CHILE_OFFSET


def describe_shift(old: str | None, new: str | None) -> str:
    """Human-readable wall-clock delta between two stamps, for reporting."""
    a, b = naive(old), naive(new)
    if a is None or b is None:
        return ""
    secs = round((b - a).total_seconds())
    if secs == 0:
        return ""
    sign = "+" if secs > 0 else "-"
    hours, rem = divmod(abs(secs), 3600)
    mins, sec = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    if sec or not parts:
        parts.append(f"{sec}s")
    return f"   (shift {sign}{''.join(parts)})"


def source_name_for(audio_id: str) -> str | None:
    """Map a transcript ``audio_id`` slug to the real recording filename."""
    aid = nfc(audio_id or "")

    m = re.fullmatch(r"aeropuerto_STG_(\d+)", aid, re.I)
    if m:
        n = m.group(1)
        stem = "Aeropuerto Arturo Merino Benítez" if n == "1" else f"Aeropuerto Arturo Merino Benítez {n}"
        return nfc(stem + ".m4a")

    if aid == "Terminal_Internacional_T2":
        return nfc("Terminal Internacional - T2.m4a")

    if re.fullmatch(r"latam_STG_\d+", aid, re.I):
        # on-disk names are exactly "latam_STG_N.m4a"
        return nfc(aid + ".m4a")

    m = re.fullmatch(r"carabineros_ppdartnel_(\d+)", aid, re.I)
    if m:
        n = m.group(1)
        stem = "Pedro Pablo Dartnell" if n == "1" else f"Pedro Pablo Dartnell {n}"
        return nfc(stem + ".m4a")

    return None


def probe(path: Path) -> dict:
    """Read authoritative media facts straight from the file."""
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration,size,format_name:format_tags:stream=sample_rate,channels",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"ffprobe failed on {path.name}: {proc.stderr.strip()[:200]}")

    data = json.loads(proc.stdout)
    fmt = data.get("format", {})
    tags = fmt.get("tags", {}) or {}
    stream = (data.get("streams") or [{}])[0]

    return {
        "dur": float(fmt.get("duration")),
        "size": int(fmt.get("size")),
        "created": tags.get("creation_time", ""),
        "major_brand": (tags.get("major_brand") or "M4A").strip(),
        "compatible_brands": split_brands(tags.get("compatible_brands")),
        "encoder": tags.get("encoder"),
        "voice_memo_uuid": tags.get("voice-memo-uuid"),
        "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
        "channels": int(stream["channels"]) if stream.get("channels") else None,
    }


def ordered(d: dict, order: list[str]) -> dict:
    """Reorder a dict by ``order``, keeping any unknown keys at the end."""
    out = {k: d[k] for k in order if k in d}
    for k, v in d.items():
        if k not in out:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    # 1. probe every recording once
    audio: dict[str, dict] = {}
    for path in sorted(AUDIO_DIR.glob("*.m4a")):
        audio[nfc(path.name)] = probe(path)
    print(f"probed {len(audio)} recordings in {AUDIO_DIR.relative_to(REPO.parent)}\n")

    used: set[str] = set()
    changed_files = 0
    problems: list[str] = []

    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        tid = data.get("transcript_id", f.stem)
        audio_id = data.get("audio_id", "")

        name = source_name_for(audio_id)
        if name is None or name not in audio:
            problems.append(f"{tid}: no recording resolved for audio_id={audio_id!r} -> {name!r}")
            continue
        used.add(name)
        rec = audio[name]

        notes: list[str] = []

        # --- top-level provenance ------------------------------------------ #
        if data.get("source_file") != name:
            notes.append(f"source_file: {data.get('source_file')!r} -> {name!r}")
        data["source_file"] = name
        data["source_path"] = f"transcription/data/audio/{name}"

        if data.get("provider") != "local":
            notes.append(f"provider: {data.get('provider')!r} -> 'local'")
            data["provider"] = "local"

        # --- timestamps: the device header is authoritative ---------------- #
        override = TIME_OVERRIDES.get(tid)
        local = override or local_stamp(rec["created"])
        for key in ("recording_datetime", "timestamp"):
            old = data.get(key)
            if local and old != local:
                why = "   [manual override, not the file tag]" if override else ""
                notes.append(f"{key}: {old!r} -> {local!r}{describe_shift(old, local)}{why}")
                data[key] = local

        # --- metadata ------------------------------------------------------ #
        md = dict(data.get("metadata") or {})

        file_info = {
            "file_name": name,
            "file_size": rec["size"],
            "file_size_kb": round(rec["size"] / 1024, 2),
            "content_type": "audio/mp4",
            "major_brand": rec["major_brand"],
        }
        if rec["compatible_brands"]:
            file_info["compatible_brands"] = rec["compatible_brands"]
        if rec["encoder"]:
            file_info["encoder"] = rec["encoder"]
        if rec["voice_memo_uuid"]:
            file_info["voice_memo_uuid"] = rec["voice_memo_uuid"]

        audio_props = {
            "duration": fmt_duration(rec["dur"]),
            "preferred_volume": (md.get("audio_properties") or {}).get("preferred_volume", "1"),
        }
        if rec["sample_rate"]:
            audio_props["sample_rate"] = rec["sample_rate"]
        if rec["channels"]:
            audio_props["channels"] = rec["channels"]

        # timestamps: keep whatever is there, add the probed sibling
        old_ts = dict(md.get("timestamps") or {})
        new_ts: dict = {}
        for k, v in old_ts.items():
            new_ts[k] = v
            if k == "QuickTime_Movie_Header_Created":
                new_ts["QuickTime_Movie_Header_Created_verified"] = rec["created"]
        if "QuickTime_Movie_Header_Created_verified" not in new_ts:
            new_ts["QuickTime_Movie_Header_Created_verified"] = rec["created"]

        md["file_info"] = file_info
        md["audio_properties"] = audio_props
        md["timestamps"] = new_ts

        # saved/processed audio point at the real recording
        for key in ("saved_audio_file", "processed_audio_file"):
            old = md.get(key)
            if old and old != name:
                notes.append(f"metadata.{key}: {old!r} -> {name!r}")
            md[key] = name

        # ontology: never blank a real identifier, only fill absent ones
        if md.get("ontology_node_id") is None:
            md["ontology_node_id"] = ""
        if md.get("ontology_schema_version") != ONTOLOGY_SCHEMA_VERSION:
            notes.append(
                "metadata.ontology_schema_version: "
                f"{md.get('ontology_schema_version')!r} -> {ONTOLOGY_SCHEMA_VERSION!r}"
            )
            md["ontology_schema_version"] = ONTOLOGY_SCHEMA_VERSION

        data["metadata"] = ordered(md, METADATA_ORDER)
        data = ordered(data, TOP_ORDER)

        # --- write ---------------------------------------------------------- #
        changed_files += 1
        print(f"{tid}")
        print(f"    audio: {name}  ({fmt_duration(rec['dur'])}, {rec['size']} B)")
        print(f"    uuid : {rec['voice_memo_uuid']}")
        for n in notes:
            print(f"    * {n}")

        if not args.dry_run:
            f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # -------------------------------------------------------------------- #
    print("\n" + "=" * 78)
    unused = sorted(set(audio) - used)
    print(f"recordings never referenced by a transcript ({len(unused)}):")
    for n in unused:
        print(f"    {n}  ({fmt_duration(audio[n]['dur'])})")

    if problems:
        print(f"\nPROBLEMS ({len(problems)}):")
        for p in problems:
            print("    " + p)
    else:
        print("\nno unresolved mappings")

    verb = "would update" if args.dry_run else "updated"
    print(f"\n{verb} {changed_files} transcripts")


if __name__ == "__main__":
    main()
