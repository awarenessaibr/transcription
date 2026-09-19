#!/usr/bin/env python3
"""
fix_header_lineage.py

Repairs three header defects that share a root cause: fields describing *where
a transcript sits in the case* were hand-maintained and drifted.

H8 -- broken ``prior_stage``/``next_stage`` links
    The corpus is a doubly-linked chain: every transcript names the stage
    before and after it.  Three links were wrong, which orphaned two
    transcripts (``I-002_05B_`` and ``I-002_07_``) from the chain even though
    both are ordinary members of it:

        I-002_05_.next   -> I-002_06_     should be I-002_05B_
        I-002_06_.prior  -> I-002_05_     should be I-002_05B_
        I-002_08_.prior  -> I-002_06_     should be I-002_07_

    ``I-002_07_`` matters: it carries 211 segments and 3 cited violations, so
    leaving it unreachable loses real evidence.  ``I-002_05B_`` is small
    (4 segments) but sits legitimately between ``_05_`` and ``_06_``.

    ``chronological_order`` is deliberately NOT touched.  It was already
    consistent with the repaired chain (05, 05B, 06, 07, 08 -> 5, 6, 7, 8, 9)
    and the author's narrative order takes precedence over the device clock;
    three recordings are genuinely out of clock order on purpose (see
    docs/AUDIO_SOURCE_MAPPING.md section 5.3).

H11 -- ``original_transcript_id`` self-references
    22 of 27 files pointed at themselves.  Per the field's own definition --
    "ID of the transcript this one was derived from (patch/refine)" -- a
    self-reference is meaningless: nothing was derived from anything.  All 27
    are set to ``null``, which is the honest value for an underived transcript
    and leaves room for real lineage later.

H7 -- ``reviewed`` was present in only 9 files
    The flag means "a human has reviewed this transcript".  9 files said
    ``true``; the other 18 omitted the key entirely, which is indistinguishable
    from "not reviewed" only by accident.  All 27 now carry an explicit
    ``true``/``false``.  This is a declaration of existing intent, not a
    promotion: no absent flag is turned into ``true``.

Usage:
    python3 scripts/fix_header_lineage.py --dry-run
    python3 scripts/fix_header_lineage.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _headerlib import load_docs, save_docs  # noqa: E402

# (filename stem, field, expected current value, corrected value)
#
# ``expected`` is asserted before writing so a re-run is a no-op and a drifted
# corpus aborts instead of being silently "fixed" into a different shape.
CHAIN_FIXES: list[tuple[str, str, str, str]] = [
    (
        "I-002_05_NAR-07_STG_7_post_removal_investigation",
        "next_stage",
        "I-002_06_NAR-STG_8_pdi_identity_control",
        "I-002_05B_NAR-11_STG_11_waiting_area",
    ),
    (
        "I-002_06_NAR-STG_8_pdi_identity_control",
        "prior_stage",
        "I-002_05_NAR-07_STG_7_post_removal_investigation",
        "I-002_05B_NAR-11_STG_11_waiting_area",
    ),
    (
        "I-002_08_NAR-09_STG_15_luggage_recovery",
        "prior_stage",
        "I-002_06_NAR-STG_8_pdi_identity_control",
        "I-002_07_NAR-06_STG_13_post_PDI_corridor",
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    docs = load_docs()
    changes: list[str] = []
    fatal: list[str] = []

    # --- H8: chain links ---------------------------------------------------
    for stem, field, expected, corrected in CHAIN_FIXES:
        data = docs.get(stem)
        if data is None:
            fatal.append(f"missing transcript: {stem}")
            continue
        actual = data.get(field)
        if actual == corrected:
            continue  # already applied
        if actual != expected:
            fatal.append(
                f"{stem}.{field}: expected {expected!r} to be replaced, found {actual!r}"
            )
            continue
        data[field] = corrected
        changes.append(f"H8  {stem}.{field}: {expected} -> {corrected}")

    # --- H11: drop self-referential lineage --------------------------------
    for stem, data in docs.items():
        old = data.get("original_transcript_id")
        if old is None:
            continue
        if old == data.get("transcript_id"):
            changes.append(f"H11 {stem}.original_transcript_id: {old} -> None (self-reference)")
        else:
            changes.append(f"H11 {stem}.original_transcript_id: {old} -> None")
        data["original_transcript_id"] = None

    # --- H7: explicit reviewed flag on every transcript --------------------
    promoted = 0
    for stem, data in docs.items():
        old = data.get("reviewed")
        if isinstance(old, bool):
            continue
        data["reviewed"] = False
        promoted += 1
        changes.append(f"H7  {stem}.reviewed: {old!r} -> False (was absent)")

    if fatal:
        print("FATAL: refusing to write:", file=sys.stderr)
        for line in fatal:
            print(f"  {line}", file=sys.stderr)
        raise SystemExit(1)

    for line in changes:
        print(f"  {line}")

    written = save_docs(docs, dry_run=args.dry_run)
    verb = "would update" if args.dry_run else "updated"
    print(
        f"\n{verb} {written} transcripts "
        f"({len(CHAIN_FIXES)} chain links checked, "
        f"{promoted} reviewed flags materialised)"
    )
    print("OK" if not changes else f"{len(changes)} change(s)")


if __name__ == "__main__":
    main()
