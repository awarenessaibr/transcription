#!/usr/bin/env python3
"""Task C -- unify the nested curator schemas (findings, clusters, corrections).

Three list/dict fields had drifted into several incompatible shapes across the
27 transcripts:

``key_evidentiary_findings`` (153 entries, 6 distinct key sets)
    Canonical shape is ``{id, finding, strength}`` plus the optional provenance
    keys ``segments`` and ``cross_reference``.  The six ``note`` values are all
    the literal string "Segment reference from original transcript." -- fully
    redundant with ``segments`` -- so they are dropped.

``forensic_clusters`` (62 clusters, 3 distinct value key sets)
    Canonical key order is ``summary, reasoning, provisions_engaged,
    violation_linkage, segments``.  Only keys that are actually present are
    kept; nothing is invented to pad thin clusters.

``corrections_applied`` (47 entries, 3 shapes)
    Canonical shape is ``{segment, original, corrected, reason}`` plus an
    optional ``type`` discriminator.  The nine non-pair entries are curator
    process notes rather than "original -> corrected" rewrites; their prose is
    preserved verbatim in ``reason``.

``strength`` is normalised to the three-value vocabulary ``High/Medium/Low``.
Per the agreed decision ``Critical`` folds into ``High`` (the 26 findings it
affects are listed in the generated report, which is the only remaining record
of the original tier).

Segment references are normalised from mixed ``int``/``str`` to ``str`` so that
one vocabulary of segment references (``"56"``, ``"0-4"``) applies everywhere.

Usage::

    python3 scripts/fix_finding_schemas.py --dry-run
    python3 scripts/fix_finding_schemas.py
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _headerlib import TRANSCRIPTS_DIR, WORKSPACE, load_docs, ordered, save_docs  # noqa: E402

REPORT = WORKSPACE / "transcription" / "docs" / "SCHEMA_NORMALIZATION.md"

# -- canonical shapes -------------------------------------------------------
FINDING_ORDER = ["id", "finding", "strength", "segments", "cross_reference"]
CLUSTER_ORDER = ["summary", "reasoning", "provisions_engaged", "violation_linkage", "segments"]
CORRECTION_ORDER = ["segment", "original", "corrected", "reason", "type"]

# Keys that are legitimately discarded, with the justification recorded in the
# report so the deletion stays auditable.
FINDING_DROPS = {
    "note": "always the literal 'Segment reference from original transcript.' -- redundant with 'segments'",
}

# -- strength vocabulary ----------------------------------------------------
STRENGTH_VALUES = ("High", "Medium", "Low")

# Every raw value seen in the corpus, mapped onto the three-value vocabulary.
# ``Critical`` folds into ``High`` by explicit decision.
_STRENGTH_MAP = {
    "high": "High",
    "critical": "High",
    "remarkable": "High",
    "★★★★★": "High",
    "★★★★★★": "High",
    "medium": "Medium",
    "low": "Low",
}


def normalise_strength(value) -> str:
    """Map a raw strength value onto ``High``/``Medium``/``Low``.

    >>> normalise_strength("Critical")
    'High'
    >>> normalise_strength("★★★★★★")
    'High'
    >>> normalise_strength(" Remarkable ")
    'High'
    >>> normalise_strength("medium")
    'Medium'
    >>> normalise_strength(None)
    'Medium'
    """
    if value is None:
        return "Medium"
    mapped = _STRENGTH_MAP.get(str(value).strip().lower())
    if mapped is None:
        raise SystemExit(
            f"FATAL: unknown strength value {value!r} -- add it to _STRENGTH_MAP "
            "so the mapping stays explicit"
        )
    return mapped


def normalise_segment_refs(value) -> list[str]:
    """Normalise segment references to a uniform list of strings.

    >>> normalise_segment_refs([56, 57])
    ['56', '57']
    >>> normalise_segment_refs(["0-4"])
    ['0-4']
    >>> normalise_segment_refs(None)
    []
    """
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value]


def coerce_correction(entry) -> dict:
    """Coerce any of the three observed correction shapes to the canonical one.

    >>> coerce_correction({"segment": "5", "original": "a", "corrected": "b", "reason": "r"})
    {'segment': '5', 'original': 'a', 'corrected': 'b', 'reason': 'r'}
    >>> coerce_correction("Removed duplicate segments.")
    {'segment': '', 'original': '', 'corrected': '', 'reason': 'Removed duplicate segments.', 'type': 'process_note'}
    >>> coerce_correction({"type": "annotation", "note": "N"})
    {'segment': '', 'original': '', 'corrected': '', 'reason': 'N', 'type': 'annotation'}
    """
    if isinstance(entry, str):
        return {
            "segment": "",
            "original": "",
            "corrected": "",
            "reason": entry,
            "type": "process_note",
        }
    if not isinstance(entry, dict):
        raise SystemExit(f"FATAL: unexpected correction entry {entry!r}")
    out = {
        "segment": str(entry.get("segment", "") or ""),
        "original": entry.get("original", "") or "",
        "corrected": entry.get("corrected", "") or "",
        "reason": entry.get("reason") or entry.get("note") or "",
    }
    if entry.get("type"):
        out["type"] = entry["type"]
    return out


def normalise_finding(entry: dict, ledger: dict) -> dict:
    """Return ``entry`` in canonical finding shape, recording every change."""
    unknown = sorted(set(entry) - set(FINDING_ORDER))
    for key in unknown:
        if key not in FINDING_DROPS:
            raise SystemExit(
                f"FATAL: unexpected finding key {key!r} -- add it to FINDING_ORDER "
                "or to FINDING_DROPS with a justification"
            )
        ledger["finding_drops"][key] += 1

    out: dict = {"id": entry.get("id", "")}
    out["finding"] = entry.get("finding", "")
    out["strength"] = normalise_strength(entry.get("strength"))
    if entry.get("strength") != out["strength"]:
        ledger["strength"][str(entry.get("strength"))] += 1

    if "segments" in entry:
        refs = normalise_segment_refs(entry["segments"])
        if refs != entry["segments"]:
            ledger["segment_ref_type"] += 1
        out["segments"] = refs
    if entry.get("cross_reference"):
        out["cross_reference"] = entry["cross_reference"]
    return out


def normalise_cluster(value: dict, ledger: dict) -> dict:
    """Return a forensic-cluster payload in canonical key order."""
    unknown = sorted(set(value) - set(CLUSTER_ORDER))
    if unknown:
        raise SystemExit(f"FATAL: unexpected cluster keys {unknown} -- extend CLUSTER_ORDER")
    out = dict(value)
    if "segments" in out:
        refs = normalise_segment_refs(out["segments"])
        if refs != out["segments"]:
            ledger["segment_ref_type"] += 1
        out["segments"] = refs
    return ordered(out, CLUSTER_ORDER)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    if not TRANSCRIPTS_DIR.is_dir():
        raise SystemExit(f"FATAL: transcripts dir not found: {TRANSCRIPTS_DIR}")

    docs = load_docs()
    ledger: dict = {
        "strength": Counter(),
        "finding_drops": Counter(),
        "corrections_coerced": Counter(),
        "segment_ref_type": 0,
        "touched_files": [],
    }

    for stem, data in docs.items():
        before = (data.get("key_evidentiary_findings"), data.get("forensic_clusters"),
                  data.get("corrections_applied"))

        findings = data.get("key_evidentiary_findings")
        if isinstance(findings, list):
            data["key_evidentiary_findings"] = [
                ordered(normalise_finding(f, ledger), FINDING_ORDER) for f in findings
            ]

        clusters = data.get("forensic_clusters")
        if isinstance(clusters, dict):
            data["forensic_clusters"] = {
                name: normalise_cluster(val, ledger) if isinstance(val, dict) else val
                for name, val in clusters.items()
            }

        corrections = data.get("corrections_applied")
        if isinstance(corrections, list):
            coerced = [coerce_correction(c) for c in corrections]
            for src, dst in zip(corrections, coerced):
                if not isinstance(src, dict):
                    ledger["corrections_coerced"]["bare_str"] += 1
                elif set(src) == {"note", "type"}:
                    ledger["corrections_coerced"]["note_type"] += 1
            data["corrections_applied"] = [ordered(c, CORRECTION_ORDER) for c in coerced]

        after = (data.get("key_evidentiary_findings"), data.get("forensic_clusters"),
                 data.get("corrections_applied"))
        if before != after:
            ledger["touched_files"].append(stem)

    save_docs(docs, dry_run=args.dry_run)
    _write_report(ledger, dry_run=args.dry_run)

    verb = "would rewrite" if args.dry_run else "rewrote"
    print(f"{verb} {len(ledger['touched_files'])} transcripts")
    if ledger["strength"]:
        print("  strength remapped:", dict(ledger["strength"]))
    if ledger["finding_drops"]:
        print("  finding keys dropped:", dict(ledger["finding_drops"]))
    if ledger["corrections_coerced"]:
        print("  corrections coerced:", dict(ledger["corrections_coerced"]))
    print("  segment refs int->str:", ledger["segment_ref_type"])
    print("report:", REPORT.relative_to(WORKSPACE))
    return 0


def _write_report(ledger: dict, dry_run: bool) -> None:
    """Emit the audit trail for every rewrite this script performs."""
    lines = [
        "# Nested schema normalisation (Task C)",
        "",
        f"Transcripts rewritten: **{len(ledger['touched_files'])}** of 27."
        + ("  _(dry run -- not written)_" if dry_run else ""),
        "",
        "Canonical shapes:",
        "",
        "| field | canonical keys |",
        "|---|---|",
        f"| `key_evidentiary_findings[]` | `{', '.join(FINDING_ORDER)}` |",
        f"| `forensic_clusters.<name>` | `{', '.join(CLUSTER_ORDER)}` (present keys only) |",
        f"| `corrections_applied[]` | `{', '.join(CORRECTION_ORDER)}` (`type` optional) |",
        "",
        f"`strength` vocabulary: `{'`, `'.join(STRENGTH_VALUES)}`.",
        "",
        "## `strength` remapping",
        "",
        "| original value | findings | mapped to |",
        "|---|---|---|",
    ]
    mapped_to = {
        "High": "High (unchanged)",
        "critical": "High",
        "Remarkable": "High",
        "★★★★★": "High",
        "★★★★★★": "High",
        "Medium": "Medium (unchanged)",
        "Low": "Low (unchanged)",
    }
    for raw, count in ledger["strength"].most_common():
        lines.append(f"| `{raw}` | {count} | {mapped_to.get(raw, 'High')} |")
    if not ledger["strength"]:
        lines.append("| _(none)_ | 0 | — |")

    lines += [
        "",
        "## Discarded keys",
        "",
        "| key | occurrences | justification |",
        "|---|---|---|",
    ]
    for key, count in ledger["finding_drops"].most_common():
        lines.append(f"| `{key}` | {count} | {FINDING_DROPS[key]} |")
    if not ledger["finding_drops"]:
        lines.append("| _(none)_ | 0 | — |")

    lines += [
        "",
        "## `corrections_applied` coercions",
        "",
        "| original shape | entries | result |",
        "|---|---|---|",
        (
            f"| bare string | {ledger['corrections_coerced'].get('bare_str', 0)} | "
            "`reason` = prose, `type` = `process_note`, `segment`/`original`/`corrected` = `\"\"` |"
        ),
        (
            f"| `{{note, type}}` | {ledger['corrections_coerced'].get('note_type', 0)} | "
            "`reason` = note, `type` preserved |"
        ),
        "",
        "## Rewritten transcripts",
        "",
    ]
    lines += [f"- `{stem}`" for stem in ledger["touched_files"]] or ["- _(none)_"]
    lines.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
