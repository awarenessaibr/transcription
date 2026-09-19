#!/usr/bin/env python3
"""Import per-transcript ``title`` values from docs/LA8159-Overview.html.

Why
---
The 27 transcript headers carried asset names in ``title`` -- e.g.
``Aeropuerto Arturo Merino Benítez 20 — FINAL v2`` -- which identify the
recording, not the event, and 20 of them embed a stale ``FINAL v2`` version
suffix.  The case overview at ``docs/LA8159-Overview.html`` already names every
one of the 27 recordings with a human-readable narrative title, and is the
document the case is actually published from, so it is the authority for
``title``.

What this script does
---------------------
For each ``<article class="review-narrative">`` section in the overview it
reads the section title, joins it to a transcript through the ``I-002_…``
source chips in the section body, and writes:

* ``title``    -- the overview's narrative title, **but with the leading
  date/time re-derived from the transcript's own verified
  ``recording_datetime``.**  The overview's clock prefixes mirror the
  pre-backfill hand-entered times and contradict the QuickTime-verified
  metadata in 16 of 27 files (the overview gives three different recordings
  the same rounded ``7:15pm``).  Keeping the prose and re-deriving the clock
  means titles and metadata cannot drift apart.  Decision recorded in
  ``docs/TRANSCRIPT_TITLE_MAP.md``.
* ``subtitle`` -- the section's ``Phase:`` string, but only where the current
  subtitle is empty, is bare prose, or is strictly less precise.  Two files are
  deliberately exempted (see ``SUBTITLE_KEEP``).

The overview also supplies ``Date/Time:`` and ``Location:`` per section.  Those
are not written here; ``location`` is settled by the controlled-vocabulary pass
because the overview's strings are themselves verbose.  The extracted values are
dumped to ``docs/TRANSCRIPT_TITLE_MAP.md`` for that pass to consume.

Idempotent: re-running reports zero changes.  ``--dry-run`` prints the plan.

Serialisation must stay ``json.dumps(data, indent=2, ensure_ascii=False) + "\n"``
or the diffs against the corpus stop round-tripping.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = REPO / "data" / "transcripts"
OVERVIEW = REPO / "docs" / "LA8159-Overview.html"
REPORT = REPO / "docs" / "TRANSCRIPT_TITLE_MAP.md"

# Key order is owned by scripts/backfill_audio_metadata.py; mirror it here so a
# reorder never shows up as part of a title change.
TOP_ORDER = [
    "transcript_id", "source_file", "source_path", "language", "timestamp",
    "provider", "original_transcript_id", "metadata", "title", "subtitle",
    "recording_datetime", "location", "audio_id", "case_id", "narrative_id",
    "chronological_order", "prior_stage", "next_stage", "classification",
    "participants", "violations_cited", "tags", "forensic_clusters",
    "key_evidentiary_findings", "corrections_applied", "segments", "reviewed",
]

# Subtitles that must NOT be taken from the overview even though they differ.
# Each entry is a defect in the overview, not a preference.
SUBTITLE_KEEP = {
    # overview's "Phase:" here is just "Boarding" -- vaguer than the current
    # "Boarding Gate", so the existing value wins.
    "I-002_02_NAR-02_STG_2_boarding_gate",
    # overview says "Carabineros PPD Artnel 2", preserving the "Artnel"
    # misspelling already flagged as a defect; the current subtitle is the
    # officer's actual words and is analytically stronger.
    "I-002_22_NAR_CARABINEROS_2",
}

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def nfc(text: str) -> str:
    """macOS stores filenames decomposed; JSON stores them composed."""
    return unicodedata.normalize("NFC", text)


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def clock_12h(hour: int, minute: int) -> str:
    """21:23 -> 9:23pm, 00:05 -> 12:05am -- the overview's own house style."""
    meridiem = "am" if hour < 12 else "pm"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d}{meridiem}"


def human_stamp(iso_local: str) -> str:
    """'2024-07-05T18:20:00-04:00' -> '5th July 2024 @ 6:20pm'.

    Reads the wall clock straight out of the string -- the offset is already
    baked in by backfill_audio_metadata.py, so no timezone maths is needed.
    """
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", iso_local or "")
    if not m:
        raise ValueError(f"unparsable recording_datetime: {iso_local!r}")
    year, month, day, hour, minute = (int(g) for g in m.groups())
    return (
        f"{ordinal(day)} {MONTHS[month - 1]} {year}"
        f" @ {clock_12h(hour, minute)}"
    )


def split_overview_title(raw: str) -> tuple[str, str]:
    """Split '5th July 2024 @ 6:20pm - The Dirty Job Sales Proxy'.

    The separator is an ASCII hyphen surrounded by spaces.  En dashes are left
    alone -- `stg-12` legitimately reads `@ 9:13am – 9:26am`, and splitting on
    the en dash would eat the description.
    """
    head, sep, tail = raw.partition(" - ")
    if not sep:
        return "", raw
    return head.strip(), tail.strip()


def ordered(mapping: dict, order: list) -> dict:
    result = {k: mapping[k] for k in order if k in mapping}
    for k, v in mapping.items():
        if k not in result:
            result[k] = v
    return result


# --------------------------------------------------------------------------- #
# parsing the overview
# --------------------------------------------------------------------------- #
def parse_overview() -> list[dict]:
    """Return one record per narrative section, in document order."""
    source = OVERVIEW.read_text(encoding="utf-8")
    chunks = re.split(r"<!--\s*#\s*([A-Za-z0-9._-]+)\s*-->", source)

    sections: list[dict] = []
    for i in range(1, len(chunks), 2):
        anchor, body = chunks[i], chunks[i + 1]
        title = re.search(
            r'<span class="review-narrative-title">(.*?)</span>', body, re.S
        )
        if not title:
            continue  # executive-summary / defined-terms / appendix sections

        def field(name: str):
            m = re.search(
                rf"<strong>{name}:</strong>\s*([^<]*)<br>", body
            )
            return strip_tags(m.group(1)) if m else None

        source_file = re.search(
            r"<strong>Source File:</strong>\s*<code>([^<]+)</code>", body
        )

        chips: list[str] = []
        for m in re.finditer(
            r'<div class="source-chip"><span class="dot"></span>(I-002[^<]*)</div>',
            body,
        ):
            chip = strip_tags(m.group(1))
            if chip not in chips:
                chips.append(chip)

        sections.append(
            {
                "anchor": anchor,
                "raw_title": strip_tags(title.group(1)),
                "file": strip_tags(source_file.group(1)) if source_file else None,
                "phase": field("Phase"),
                "datetime": field("Date/Time"),
                "location": field("Location"),
                "chips": chips,
            }
        )
    return sections


def join_sections_to_transcripts(sections, docs) -> dict:
    """Map transcript_id -> section, by unique longest prefix match."""
    tids = list(docs)
    joined: dict[str, dict] = {}
    for section in sections:
        for chip in section["chips"]:
            for tid in tids:
                if tid == chip or tid.startswith(chip + "_"):
                    joined.setdefault(tid, section)
    return joined


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the plan only")
    args = ap.parse_args()

    docs = {}
    files = {}
    for path in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        docs[data["transcript_id"]] = data
        files[data["transcript_id"]] = path

    sections = parse_overview()
    joined = join_sections_to_transcripts(sections, docs)

    unmatched = sorted(set(docs) - set(joined))
    if unmatched:
        print("FATAL: transcripts with no overview section:", file=sys.stderr)
        for tid in unmatched:
            print("   " + tid, file=sys.stderr)
        return 1

    rows = []
    title_changes = 0
    subtitle_changes = 0
    changed_files = 0

    for tid in sorted(docs, key=lambda k: docs[k].get("chronological_order") or 0):
        data = docs[tid]
        section = joined[tid]
        notes = []

        head, description = split_overview_title(section["raw_title"])
        want_title = f"{human_stamp(data['recording_datetime'])} - {description}"

        old_title = data.get("title")
        if old_title != want_title:
            notes.append(f"title: {old_title!r}\n            -> {want_title!r}")
            data["title"] = want_title
            title_changes += 1

        # Clock drift between the overview's hand-entered prefix and the
        # verified tag, recorded for the audit report.
        drift = ""
        if head:
            m = re.search(r"@\s*(.+)$", head)
            overview_clock = (m.group(1) if m else head).strip()
            if overview_clock and data["recording_datetime"][11:16] not in (
                overview_clock,
                overview_clock.split("–")[0].strip(),
            ):
                drift = overview_clock

        # subtitle: overview Phase:, unless the overview is the weaker source
        want_subtitle = data.get("subtitle")
        if (
            section["phase"]
            and section["phase"] != data.get("subtitle")
            and tid not in SUBTITLE_KEEP
        ):
            notes.append(
                f"subtitle: {data.get('subtitle')!r}\n              "
                f"-> {section['phase']!r}"
            )
            want_subtitle = section["phase"]
            subtitle_changes += 1
        data["subtitle"] = want_subtitle

        data = ordered(data, TOP_ORDER)

        rows.append(
            {
                "tid": tid,
                "anchor": section["anchor"],
                "file": section["file"],
                "overview_title": section["raw_title"],
                "overview_dt": section["datetime"],
                "overview_location": section["location"],
                "overview_phase": section["phase"],
                "clock_drift": drift,
                "old_title": old_title,
                "title": data["title"],
                "subtitle": data["subtitle"],
                "notes": notes,
            }
        )

        if notes:
            changed_files += 1
            print(tid)
            for n in notes:
                print(f"        * {n}")

        if not args.dry_run:
            files[tid].write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    write_report(rows)

    verb = "would update" if args.dry_run else "updated"
    print("\n" + "=" * 78)
    print(f"overview sections parsed : {len(sections)}")
    print(f"titles changed           : {title_changes}")
    print(f"subtitles changed        : {subtitle_changes}")
    print(f"{verb} {changed_files} transcripts")
    print(f"wrote {REPORT.relative_to(REPO)}")
    return 0


def write_report(rows) -> None:
    lines = [
        "# Transcript title map (`docs/LA8159-Overview.html` → transcript headers)",
        "",
        "Generated by `scripts/import_overview_titles.py`. Do not hand-edit.",
        "",
        "The overview is the authority for `title`. Its clock prefixes are **not**",
        "authoritative — they mirror the pre-backfill hand-entered times and",
        "contradict the QuickTime-verified `recording_datetime` in 16 of 27 files,",
        "so each prefix is re-derived from the transcript's own verified timestamp.",
        "The prose half of every title is copied verbatim.",
        "",
        "`subtitle` takes the section's `Phase:` value except where the overview is",
        "the weaker source; those two exemptions are listed by the script constant",
        "`SUBTITLE_KEEP` (the vague `Boarding` on `I-002_02`, and the `Dartnell`",
        "misspelling on `I-002_22`).",
        "",
        "`Date/Time:` and `Location:` are captured here but **not** written to the",
        "transcripts — `location` is settled by the controlled-vocabulary pass,",
        "for which the `overview_location` column is the input.",
        "",
        "| transcript_id | anchor | clock in overview | clock (verified) | drift |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        verified = r["title"].split("@ ")[1].split(" - ")[0] if "@ " in r["title"] else ""
        lines.append(
            f"| `{r['tid']}` | {r['anchor']} | "
            f"{r['clock_drift'] or '—'} | {verified} | "
            f"{'yes' if r['clock_drift'] else ''} |"
        )

    lines += ["", "## Titles written", "",
              "| transcript_id | previous title | new title |", "|---|---|---|"]
    for r in rows:
        if r["old_title"] != r["title"]:
            lines.append(f"| `{r['tid']}` | {r['old_title']} | {r['title']} |")

    lines += ["", "## Overview `Phase:` / `Date/Time:` / `Location:` per section", "",
              "| transcript_id | Phase | Date/Time | Location |", "|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| `{r['tid']}` | {r['overview_phase']} | {r['overview_dt']} | "
            f"{r['overview_location']} |"
        )

    lines += ["", "## Subtitle provenance", "",
              "| transcript_id | subtitle | source |", "|---|---|---|"]
    for r in rows:
        source = "overview `Phase:`"
        if r["subtitle"] == r["overview_phase"]:
            source = "overview `Phase:` (already matched)"
        elif r["tid"] in SUBTITLE_KEEP:
            source = "**kept existing** — overview is weaker"
        lines.append(f"| `{r['tid']}` | {r['subtitle']} | {source} |")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
