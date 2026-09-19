#!/usr/bin/env python3
"""Task E -- consolidate ``participants[].speaker_id`` onto canonical IDs.

The enrichment pass appended a per-file disambiguator to both ``speaker_id`` and
``canonical_name``, producing 48 distinct IDs for 35 actual speakers/roles and
``canonical_name`` values such as ``'PDI 2 (NAR-STG_8_pdi_identity_control)'``.

Two tables drive the rewrite, both explicit so that drift is caught rather than
silently rewritten:

``CANONICAL``
    raw id -> canonical id.  Two kinds of merge are recorded separately in the
    report:

    * **identity** -- a named person appearing under several IDs
      (``SPK-pilot-ruiz`` / ``SPK-piloto-ruiz-nar-02-...`` /
      ``SPK-latam-pilot-ruiz-nar-01-...``).
    * **role** -- a generic role label that was suffixed per stage
      (``SPK-dgac-nar-06-...`` / ``SPK-dgac-nar-07-...``).

``MINTED``
    ``(stem, speaker_label)`` -> new deterministic id, for the 8 participants
    whose ``speaker_id`` was null.  The minted ids deliberately do **not** end in
    a stage suffix, so re-running the script cannot strip them again.

Also applied:

* the ``(NAR-…)`` suffix is stripped from ``canonical_name``;
* participants are deduplicated by canonical id within a file, keeping the first
  occurrence (``I-002_06`` listed ``SPK-pdi-female`` twice);
* one junk participant is removed -- ``SPK-review-important-nar-stg-8-...``,
  whose name is ``'Review-Important'`` and role is ``'Unknown speaker'``;
* where a canonical id still carries several different display names, the
  majority name wins (ties broken by transcript order) so one id maps to one
  name.  Every such change is listed in the report.

Usage::

    python3 scripts/fix_speaker_ids.py --dry-run
    python3 scripts/fix_speaker_ids.py
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _headerlib import TRANSCRIPTS_DIR, WORKSPACE, load_docs, nfc, save_docs  # noqa: E402

REPORT = WORKSPACE / "transcription" / "docs" / "SPEAKER_ID_CONSOLIDATION.md"

# -- raw id -> canonical id -------------------------------------------------
# "identity" = the same named person; "role" = a generic role merged per stage.
CANONICAL: dict[str, str] = {
    "SPK-antonela-latam-agent": "SPK-antonela-latam-agent",
    "SPK-background-nar-10-stg-16-counter-confrontation": "SPK-background",
    "SPK-carabinero-constancia-nar-carabineros-1": "SPK-carabinero-constancia",
    "SPK-carabinero-speaker-00-nar-carabineros-3": "SPK-carabinero-speaker-00",
    "SPK-computer-officer-nar-carabineros-1": "SPK-computer-officer",
    "SPK-computer-officer-nar-carabineros-2": "SPK-computer-officer",
    "SPK-dgac-don-nicolas": "SPK-dgac-don-nicolas",
    "SPK-dgac-don-nicolas-nar-14-terminal-internacional-t2-counter": "SPK-dgac-don-nicolas",
    "SPK-dgac-don-nicolas-nar-16-stg-23-dgac-don-nicolas": "SPK-dgac-don-nicolas",
    "SPK-dgac-edgardo-ortiz": "SPK-dgac-edgardo-ortiz",
    "SPK-dgac-edgardo-ortiz-nar-16-stg-23-dgac-don-nicolas": "SPK-dgac-edgardo-ortiz",
    "SPK-dgac-nar-06-stg-6-jetbridge-standoff": "SPK-dgac",
    "SPK-dgac-nar-07-stg-7-post-removal-investigation": "SPK-dgac",
    "SPK-dgac-official-1-nar-15-stg-22-dgac-office": "SPK-dgac-official-1",
    "SPK-dgac-official-2-nar-15-stg-22-dgac-office": "SPK-dgac-official-2",
    "SPK-dgac-official-3-nar-16-stg-23-dgac-don-nicolas": "SPK-dgac-official-3",
    "SPK-diego-latam-supervisor": "SPK-diego-latam-supervisor",
    "SPK-female-carabinero-2-nar-carabineros-1": "SPK-female-carabinero-2",
    "SPK-female-carabinero-2-nar-carabineros-2": "SPK-female-carabinero-2",
    "SPK-female-carabinero-2-nar-carabineros-3": "SPK-female-carabinero-2",
    "SPK-joaquin-barraza-latam-security": "SPK-joaquin-barraza-latam-security",
    "SPK-latam-boss-nar-07-stg-7-post-removal-investigation": "SPK-latam-boss",
    "SPK-latam-gate-staff-2-nar-02-stg-2-boarding-gate": "SPK-latam-gate-staff-2",
    "SPK-latam-gate-staff-acuser-nar-02-stg-2-boarding-gate": "SPK-latam-gate-staff-acuser",
    "SPK-latam-gate-staff-nar-02-stg-2-boarding-gate": "SPK-latam-gate-staff",
    "SPK-latam-luggage-supervisor-dominika-nar-09-stg-15-luggage-recovery": "SPK-latam-luggage-supervisor-dominika",
    "SPK-latam-official-nar-19-stg-12": "SPK-latam-official",
    "SPK-latam-pilot-ruiz-nar-01-stg-1-pre-boarding": "SPK-pilot-ruiz",
    "SPK-latam-staff-acuser-nar-07-stg-7-post-removal-investigation": "SPK-latam-staff-acuser",
    "SPK-latam-staff-counter-2-nar-14-terminal-internacional-t2-counter": "SPK-latam-staff-counter-2",
    "SPK-latam-staff-counter-female-nar-14-terminal-internacional-t2-counter": "SPK-latam-staff-counter-female",
    "SPK-latam-staff-counter-nar-14-terminal-internacional-t2-counter": "SPK-latam-staff-counter",
    "SPK-latam-staff-nar-19-stg-12": "SPK-latam-staff",
    "SPK-latam-staff-random-nar-16-stg-23-dgac-don-nicolas": "SPK-latam-staff-random",
    "SPK-latam-staff-speaker-01-nar-latam-stg-4": "SPK-latam-staff-speaker-01",
    "SPK-latam-supervisora-nar-19-stg-12": "SPK-latam-supervisora",
    "SPK-pasajeros-del-vuelo-nar-06-stg-6-jetbridge-standoff": "SPK-pasajeros-del-vuelo",
    "SPK-passenger-leandro": "SPK-passenger-leandro",
    "SPK-pdi-2-nar-stg-8-pdi-identity-control": "SPK-pdi-2",
    "SPK-pdi-female-nar-stg-8-pdi-identity-control": "SPK-pdi-female",
    "SPK-pdi-nar-06-stg-6-jetbridge-standoff": "SPK-pdi",
    "SPK-pdi-nar-07-stg-7-post-removal-investigation": "SPK-pdi",
    "SPK-pdi-nar-stg-8-pdi-identity-control": "SPK-pdi",
    "SPK-pilot-ruiz": "SPK-pilot-ruiz",
    "SPK-piloto-ruiz-nar-02-stg-2-boarding-gate": "SPK-pilot-ruiz",
    "SPK-stewardess-accuser": "SPK-stewardess-accuser",
}

# Merges that join a *named person*, as opposed to a generic role label.
IDENTITY_MERGES = {
    "SPK-pilot-ruiz",
    "SPK-dgac-don-nicolas",
    "SPK-dgac-edgardo-ortiz",
    "SPK-female-carabinero-2",
}

# Junk participants: a mis-parsed diarization label, not a person.
REMOVED: dict[str, str] = {
    "SPK-review-important-nar-stg-8-pdi-identity-control": (
        "canonical_name 'Review-Important', role 'Unknown speaker' -- a diarization "
        "label that was never a participant"
    ),
}

# The same junk row, addressed by (stem, speaker_label) instead of by id.  Needed
# because a first pass may already have blanked its ``speaker_id``, and because
# it keeps the script idempotent once the row has been dropped.
REMOVED_LABELS: dict[tuple[str, str], str] = {
    ("I-002_06_NAR-STG_8_pdi_identity_control", "Review-Important"): (
        "canonical_name 'Review-Important', role 'Unknown speaker' -- a diarization "
        "label that was never a participant"
    ),
}

# -- null ids -> deterministic new ids --------------------------------------
MINTED: dict[tuple[str, str], str] = {
    ("I-002_06_NAR-STG_8_pdi_identity_control", "SPEAKER_02"): "SPK-unknown-stg-8-speaker-02",
    ("I-002_06_NAR-STG_8_pdi_identity_control", "SPEAKER_03"): "SPK-unknown-stg-8-speaker-03",
    ("I-002_06_NAR-STG_8_pdi_identity_control", "SPEAKER_04"): "SPK-unknown-stg-8-speaker-04",
    ("I-002_06_NAR-STG_8_pdi_identity_control", "SPEAKER_05"): "SPK-unknown-stg-8-speaker-05",
    ("I-002_17_NAR-21_STG_29", "SPEAKER_00"): "SPK-unknown-stg-29-speaker-00",
    ("I-002_17_NAR-21_STG_29", "SPEAKER_01"): "SPK-unknown-stg-29-speaker-01",
    ("I-002_17_NAR-21_STG_29", "SPEAKER_02"): "SPK-unknown-stg-29-speaker-02",
    ("I-002_24_NAR-19_STG_12", "SPEAKER_00"): "SPK-unknown-stg-12-speaker-00",
}

CANONICAL_VALUES = frozenset(CANONICAL.values()) | frozenset(MINTED.values())

# Lookup for the removal justification, keyed the way the ledger records it.
_REASONS: dict[str, str] = dict(REMOVED)
_REASONS.update({f"{stem}:{label}": why for (stem, label), why in REMOVED_LABELS.items()})

# The per-file disambiguator appended to canonical_name, e.g. '(NAR-14_…)'.
_NAME_SUFFIX = re.compile(r"\s*\(NAR[^)]*\)\s*$")


def strip_name_suffix(name: str) -> str:
    """Remove the per-file ``(NAR-…)`` disambiguator from a display name.

    >>> strip_name_suffix("PDI 2 (NAR-STG_8_pdi_identity_control)")
    'PDI 2'
    >>> strip_name_suffix("Carabinero (SPEAKER_00) (NAR_CARABINEROS_3)")
    'Carabinero (SPEAKER_00)'
    >>> strip_name_suffix("Ruiz")
    'Ruiz'
    >>> strip_name_suffix("SPEAKER_00 (English speaker)")
    'SPEAKER_00 (English speaker)'
    """
    return _NAME_SUFFIX.sub("", nfc(name)).strip()


def resolve_speaker_id(stem: str, label: str, sid, ledger: dict) -> str | None:
    """Map one participant's ``speaker_id`` onto its canonical value.

    Returns None when the participant should be dropped.

    >>> ledger = {"minted": Counter(), "removed": Counter()}
    >>> resolve_speaker_id("X", "SPEAKER_00", "SPK-piloto-ruiz-nar-02-stg-2-boarding-gate", ledger)
    'SPK-pilot-ruiz'
    >>> resolve_speaker_id("X", "SPEAKER_00", "SPK-pilot-ruiz", ledger)
    'SPK-pilot-ruiz'
    >>> resolve_speaker_id("I-002_17_NAR-21_STG_29", "SPEAKER_01", None, ledger)
    'SPK-unknown-stg-29-speaker-01'
    >>> resolve_speaker_id("X", "y", "SPK-review-important-nar-stg-8-pdi-identity-control", ledger) is None
    True
    >>> resolve_speaker_id("I-002_06_NAR-STG_8_pdi_identity_control", "Review-Important", None, ledger) is None
    True
    """
    if (stem, label) in REMOVED_LABELS:
        ledger["removed"][f"{stem}:{label}"] += 1
        return None

    if sid in REMOVED:
        ledger["removed"][f"{stem}:{sid}"] += 1
        return None

    if sid is None:
        minted = MINTED.get((stem, label))
        if minted is None:
            raise SystemExit(
                f"FATAL: {stem}: null speaker_id for label {label!r} has no entry "
                "in MINTED -- add one so the id stays deterministic"
            )
        ledger["minted"][minted] += 1
        return minted

    if sid in CANONICAL:
        return CANONICAL[sid]
    if sid in CANONICAL_VALUES:
        return sid  # already canonical; keeps the script idempotent

    raise SystemExit(
        f"FATAL: {stem}: unknown speaker_id {sid!r} -- add it to CANONICAL "
        "(or to REMOVED with a justification)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    if not TRANSCRIPTS_DIR.is_dir():
        raise SystemExit(f"FATAL: transcripts dir not found: {TRANSCRIPTS_DIR}")

    docs = load_docs()
    ledger: dict = {
        "minted": Counter(),
        "removed": Counter(),
        "renamed": Counter(),
        "deduped": Counter(),
        "name_suffix": Counter(),
        "names_unified": [],
        "touched": [],
    }

    # Pass 1 -- resolve ids, strip the name suffix, drop removed rows, dedupe.
    for stem, data in docs.items():
        participants = data.get("participants")
        if not isinstance(participants, list):
            continue
        seen: set = set()
        kept = []
        for person in participants:
            sid = resolve_speaker_id(
                stem, person.get("speaker_label", ""), person.get("speaker_id"), ledger
            )
            if sid is None:
                continue  # junk row, or a duplicate of one already kept
            if sid in seen:
                ledger["deduped"][f"{stem}:{sid}"] += 1
                continue
            seen.add(sid)
            person["speaker_id"] = sid

            name = person.get("canonical_name")
            if isinstance(name, str) and name:
                clean = strip_name_suffix(name)
                if clean != name:
                    ledger["name_suffix"][name] += 1
                person["canonical_name"] = clean
            kept.append(person)
        data["participants"] = kept

    # Pass 2 -- one display name per canonical id, by majority.
    names: dict[str, Counter] = defaultdict(Counter)
    order: dict[str, dict[str, int]] = defaultdict(dict)
    for rank, (stem, data) in enumerate(sorted(docs.items())):
        for person in data.get("participants") or []:
            sid = person.get("speaker_id")
            name = person.get("canonical_name")
            if not sid or not name:
                continue
            names[sid][name] += 1
            order[sid].setdefault(name, rank)

    chosen = {
        sid: max(counts.items(), key=lambda kv: (kv[1], -order[sid][kv[0]]))[0]
        for sid, counts in names.items()
    }

    # Pass 3 -- apply the chosen names.
    for stem, data in docs.items():
        for person in data.get("participants") or []:
            sid = person.get("speaker_id")
            if not sid or sid not in chosen:
                continue
            if person.get("canonical_name") != chosen[sid]:
                ledger["names_unified"].append(
                    (stem, sid, person.get("canonical_name"), chosen[sid])
                )
                person["canonical_name"] = chosen[sid]

    for stem, data in docs.items():
        if data.get("participants"):
            ledger["touched"].append(stem)

    ledger["renamed"] = Counter(
        raw for raw, canonical in CANONICAL.items() if raw != canonical
    )

    save_docs(docs, dry_run=args.dry_run)
    _write_report(docs, chosen, ledger, dry_run=args.dry_run)

    verb = "would rewrite" if args.dry_run else "rewrote"
    print(f"{verb} {len(ledger['touched'])} transcripts")
    print(f"  speaker ids consolidated: {len(CANONICAL)} -> {len(CANONICAL_VALUES)} canonical"
          f" (raw ids remapped: {len(ledger['renamed'])})")
    print(f"  participants removed:     {sum(ledger['removed'].values())}")
    print(f"  participants deduped:     {sum(ledger['deduped'].values())}")
    print(f"  null ids minted:          {sum(ledger['minted'].values())}")
    print(f"  names de-suffixed:        {sum(ledger['name_suffix'].values())}")
    print(f"  names unified:            {len(ledger['names_unified'])}")
    print("report:", REPORT.relative_to(WORKSPACE))
    return 0


def _write_report(docs: dict, chosen: dict, ledger: dict, dry_run: bool) -> None:
    """Emit the audit trail for the consolidation."""
    merges: dict[str, list[str]] = defaultdict(list)
    for raw, canonical in CANONICAL.items():
        if raw != canonical:
            merges[canonical].append(raw)

    lines = [
        "# Speaker ID consolidation (Task E)",
        f"Transcripts rewritten: **{len(ledger['touched'])}** of 27."
        + ("  _(dry run -- not written)_" if dry_run else ""),
        "",
        f"`speaker_id` space: **{len(CANONICAL)} raw -> "
        f"{len(CANONICAL_VALUES)} canonical** (plus {len(REMOVED)} removed).",
        "",
        "The enrichment pass appended a per-file disambiguator (`-nar-<stage>`) to",
        "both `speaker_id` and `canonical_name`. Those suffixes are now removed, so a",
        "canonical id no longer encodes the transcript it came from.",
        "",
        "## Merge groups",
        "",
        "`basis` is **identity** where the raw ids are the same named person, and",
        "**role** where a generic role label was suffixed per stage.",
        "",
        "| canonical id | basis | merged from |",
        "|---|---|---|",
    ]
    for canonical in sorted(merges):
        basis = "identity" if canonical in IDENTITY_MERGES else "role"
        sources = ", ".join(f"`{s}`" for s in sorted(merges[canonical]))
        lines.append(f"| `{canonical}` | {basis} | {sources} |")

    lines += [
        "",
        "## Removed participants",
        "",
        "| transcript | speaker_id | justification |",
        "|---|---|---|",
    ]
    if ledger["removed"]:
        for key, count in ledger["removed"].most_common():
            stem, _, target = key.partition(":")
            reason = _REASONS.get(key) or REMOVED.get(target, "")
            lines.append(f"| `{stem}` | `{target}` x{count} | {reason} |")
    else:
        lines.append("| _(none)_ | — | — |")

    lines += [
        "",
        "## Minted ids for the previously-null `speaker_id` values",
        "",
        "Minted ids deliberately omit the `-nar-` prefix so a re-run cannot strip them.",
        "",
        "| transcript | speaker label | new id |",
        "|---|---|---|",
    ]
    for (stem, label), sid in sorted(MINTED.items()):
        lines.append(f"| `{stem}` | `{label}` | `{sid}` |")

    lines += [
        "",
        "## Duplicate participants removed",
        "",
        "| transcript:speaker_id | occurrences dropped |",
        "|---|---|",
    ]
    if ledger["deduped"]:
        for key, count in ledger["deduped"].most_common():
            lines.append(f"| `{key}` | {count} |")
    else:
        lines.append("| _(none)_ | — |")

    lines += [
        "",
        "## `canonical_name` changes",
        "",
        "The `(NAR-…)` suffix was stripped from "
        f"{sum(ledger['name_suffix'].values())} names. Where a canonical id still",
        "carried several names, the majority name won (ties broken by transcript",
        "order) so one id maps to one name:",
        "",
        "| transcript | canonical id | before | after |",
        "|---|---|---|---|",
    ]
    if ledger["names_unified"]:
        for stem, sid, before, after in ledger["names_unified"]:
            lines.append(f"| `{stem}` | `{sid}` | `{before}` | `{after}` |")
    else:
        lines.append("| _(none)_ | — | — | — |")

    lines += [
        "",
        "## Canonical vocabulary",
        "",
        "| canonical id | display name | participants | transcripts |",
        "|---|---|---|---|",
    ]
    for sid in sorted(chosen):
        occurrences = [
            stem for stem, data in sorted(docs.items())
            if any(p.get("speaker_id") == sid for p in data.get("participants") or [])
        ]
        count = sum(
            1 for data in docs.values()
            for p in data.get("participants") or []
            if p.get("speaker_id") == sid
        )
        lines.append(f"| `{sid}` | {chosen[sid]} | {count} | {len(occurrences)} |")

    lines += [
        "",
        "## Follow-ups outside the transcript corpus",
        "",
        "These artifacts are still keyed by the pre-consolidation ids:",
        "",
        "- `data/speaker_index.json` -- 47 keys in `mapped_speakers`",
        "- `data/speaker_patch.json` -- 1474 `suggested_speaker_id` values",
        "- `data/speakers/*.md` -- 48 profile files named after the raw ids",
        "",
        "They were left untouched because merging them is not mechanical: several",
        "profiles would have to be combined into one file, which is an authoring task",
        "rather than a rename.",
        "",
    ]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
