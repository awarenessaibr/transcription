#!/usr/bin/env python3
"""Task D -- normalise the controlled vocabularies (tags, location, audio_id).

``tags``
    202 entries / 97 distinct.  Eight carried non-kebab casing; the rest are
    already ``lower-kebab``.  Every tag is run through ``kebab()`` so the rule
    is mechanical rather than a hand-maintained list, and duplicates created by
    the collapse are removed while preserving first-seen order (the leading
    ``evidence``/``transcript``/``narrative`` trio is meaningful).

``location``
    16 variants for one facility.  Each value is parsed into a canonical
    facility plus an optional ``— <place>`` suffix:

        Arturo Merino Benítez International Airport (SCL), Santiago, Chile
        Arturo Merino Benítez International Airport (SCL), Santiago, Chile — <place>
        Carabineros Dartnell Sub-Station, Arturo Merino Benítez International Airport (SCL), Santiago, Chile

    The place suffix is preserved verbatim (per the agreed conservative scope);
    only the facility prefix, hyphen variants and whitespace are corrected.

``audio_id``
    One casing defect: ``aeropuerto_stg_12`` -> ``aeropuerto_STG_12``.

``classification`` is identical across all 27 transcripts (the privilege
marking) and is deliberately left untouched.

Usage::

    python3 scripts/fix_vocabularies.py --dry-run
    python3 scripts/fix_vocabularies.py
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _headerlib import TRANSCRIPTS_DIR, WORKSPACE, load_docs, nfc, save_docs  # noqa: E402

REPORT = WORKSPACE / "transcription" / "docs" / "VOCABULARY_NORMALIZATION.md"

# -- canonical location vocabulary ------------------------------------------
FACILITY = "Arturo Merino Ben\u00edtez International Airport (SCL), Santiago, Chile"
SUBSTATION = (
    "Carabineros Dartnell Sub-Station, "
    "Arturo Merino Ben\u00edtez International Airport (SCL), Santiago, Chile"
)

# Recognised facility spellings.  Anything else aborts the run rather than
# being silently rewritten, so a new facility must be declared here first.
_FACILITY_HEADS = (
    "Arturo Merino Ben\u00edtez International Airport",
    "Carabineros Dartnell",
)

_PLACE_SEP = " \u2014 "  # space, em dash, space
# Hyphen-like characters that must not leak into machine-readable fields.
_HYPHENS = {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "--"}


def kebab(tag: str) -> str:
    """Normalise a tag to ``lower-kebab``.

    >>> kebab("Chilean-Aviation-Law")
    'chilean-aviation-law'
    >>> kebab("DGAC")
    'dgac'
    >>> kebab("post-PDI")
    'post-pdi'
    >>> kebab("PDI-identity-control")
    'pdi-identity-control'
    >>> kebab("Bo  arding")
    'bo-arding'
    >>> kebab("  Leading and trailing  ")
    'leading-and-trailing'
    """
    text = nfc(tag).strip()
    for bad, good in _HYPHENS.items():
        text = text.replace(bad, good)
    text = re.sub(r"[\s_]+", "-", text).lower()
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def normalise_location(value: str) -> str:
    """Reduce a location string to canonical facility (+ place) form.

    >>> normalise_location("Arturo Merino Benítez International Airport, Santiago, Chile")
    'Arturo Merino Benítez International Airport (SCL), Santiago, Chile'
    >>> normalise_location("Arturo Merino Benítez International Airport (SCL) — Boarding Gate")
    'Arturo Merino Benítez International Airport (SCL), Santiago, Chile — Boarding Gate'
    >>> normalise_location("Carabineros Dartnell sub‑station, Arturo Merino Benítez International Airport, Santiago, Chile")
    'Carabineros Dartnell Sub-Station, Arturo Merino Benítez International Airport (SCL), Santiago, Chile'
    """
    text = nfc(value).strip()
    if not text.startswith(_FACILITY_HEADS):
        raise SystemExit(
            f"FATAL: unrecognised facility in location {value!r} -- add it to "
            "_FACILITY_HEADS so the canonical form stays explicit"
        )

    if text.startswith("Carabineros Dartnell"):
        return SUBSTATION

    facility, sep, place = text.partition(_PLACE_SEP)
    if not sep:
        return FACILITY

    place = nfc(place).strip()
    for bad, good in _HYPHENS.items():
        place = place.replace(bad, good)
    place = re.sub(r"\s{2,}", " ", place)
    return f"{FACILITY}{_PLACE_SEP}{place}"


def normalise_audio_id(value: str) -> str:
    """Force the stage component of an audio id to upper case.

    ``\\b`` cannot be used here: ``_`` is a word character, so there is no word
    boundary inside ``aeropuerto_stg_12``.  Alphanumeric lookarounds express the
    intent directly -- ``stg`` must be a standalone underscore/dash-delimited
    component.

    >>> normalise_audio_id("aeropuerto_stg_12")
    'aeropuerto_STG_12'
    >>> normalise_audio_id("latam_stg_3")
    'latam_STG_3'
    >>> normalise_audio_id("aeropuerto_STG_1")
    'aeropuerto_STG_1'
    >>> normalise_audio_id("Terminal_Internacional_T2")
    'Terminal_Internacional_T2'
    """
    return re.sub(r"(?i)(?<![A-Za-z0-9])stg(?![A-Za-z0-9])", "STG", nfc(value))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    if not TRANSCRIPTS_DIR.is_dir():
        raise SystemExit(f"FATAL: transcripts dir not found: {TRANSCRIPTS_DIR}")

    docs = load_docs()
    ledger: dict = {
        "tag_changes": Counter(),
        "tag_deduped": Counter(),
        "loc_changes": Counter(),
        "audio_id": [],
        "touched": [],
    }

    for stem, data in docs.items():
        changed = False

        tags = data.get("tags")
        if isinstance(tags, list):
            new_tags: list[str] = []
            for raw in tags:
                fixed = kebab(raw)
                if fixed != raw:
                    ledger["tag_changes"][raw] += 1
                    changed = True
                if fixed in new_tags:
                    ledger["tag_deduped"][fixed] += 1
                    changed = True
                    continue
                new_tags.append(fixed)
            data["tags"] = new_tags

        loc = data.get("location")
        if isinstance(loc, str) and loc:
            fixed = normalise_location(loc)
            if fixed != loc:
                ledger["loc_changes"][loc] += 1
                changed = True
            data["location"] = fixed

        aid = data.get("audio_id")
        if isinstance(aid, str) and aid:
            fixed = normalise_audio_id(aid)
            if fixed != aid:
                ledger["audio_id"].append((stem, aid, fixed))
                changed = True
            data["audio_id"] = fixed

        if changed:
            ledger["touched"].append(stem)

    save_docs(docs, dry_run=args.dry_run)
    _write_report(ledger, dry_run=args.dry_run)

    verb = "would rewrite" if args.dry_run else "rewrote"
    print(f"{verb} {len(ledger['touched'])} transcripts")
    print(f"  tag values normalised: {sum(ledger['tag_changes'].values())} "
          f"({len(ledger['tag_changes'])} distinct)")
    print(f"  tags deduplicated:     {sum(ledger['tag_deduped'].values())}")
    print(f"  location values fixed: {sum(ledger['loc_changes'].values())} "
          f"({len(ledger['loc_changes'])} distinct)")
    print(f"  audio_id fixed:        {len(ledger['audio_id'])}")
    print("report:", REPORT.relative_to(WORKSPACE))
    return 0


def _write_report(ledger: dict, dry_run: bool) -> None:
    """Emit the audit trail for every vocabulary rewrite."""
    lines = [
        "# Controlled vocabulary normalisation (Task D)",
        "",
        f"Transcripts rewritten: **{len(ledger['touched'])}** of 27."
        + ("  _(dry run -- not written)_" if dry_run else ""),
        "",
        "## Canonical vocabularies",
        "",
        "**Facility**",
        "",
        f"```\n{FACILITY}\n```",
        "",
        "**Facility with place**",
        "",
        f"```\n{FACILITY} — <place>\n```",
        "",
        "**Police sub-station** (a distinct facility inside SCL)",
        "",
        f"```\n{SUBSTATION}\n```",
        "",
        "Place suffixes are preserved verbatim; only the facility prefix, hyphen",
        "variants and whitespace are corrected. `classification` is identical across",
        "all 27 transcripts and is left untouched.",
        "",
        "## Tag normalisation (`lower-kebab`)",
        "",
        "| original | occurrences | normalised |",
        "|---|---|---|",
    ]
    if ledger["tag_changes"]:
        for raw, count in ledger["tag_changes"].most_common():
            lines.append(f"| `{raw}` | {count} | `{kebab(raw)}` |")
    else:
        lines.append("| _(none)_ | 0 | — |")

    lines += ["", "Tags removed as duplicates after normalisation:", ""]
    if ledger["tag_deduped"]:
        for tag, count in ledger["tag_deduped"].most_common():
            lines.append(f"- `{tag}` x{count}")
    else:
        lines.append("- _(none)_")

    lines += [
        "",
        "## Location normalisation",
        "",
        "| original | occurrences | canonical |",
        "|---|---|---|",
    ]
    if ledger["loc_changes"]:
        for raw, count in ledger["loc_changes"].most_common():
            lines.append(f"| `{raw}` | {count} | `{normalise_location(raw)}` |")
    else:
        lines.append("| _(none)_ | 0 | — |")

    lines += [
        "",
        "## `audio_id` casing",
        "",
        "| transcript | before | after |",
        "|---|---|---|",
    ]
    if ledger["audio_id"]:
        for stem, before, after in ledger["audio_id"]:
            lines.append(f"| `{stem}` | `{before}` | `{after}` |")
    else:
        lines.append("| _(none)_ | — | — |")

    lines += ["", "## Rewritten transcripts", ""]
    lines += [f"- `{stem}`" for stem in ledger["touched"]] or ["- _(none)_"]
    lines.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
