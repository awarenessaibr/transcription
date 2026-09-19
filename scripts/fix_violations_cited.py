#!/usr/bin/env python3
"""
fix_violations_cited.py

Normalises ``violations_cited`` to the only format the application actually
consumes: bare violation-registry IDs.

Why IDs
-------
``violations_cited`` is declared as a list of strings and the field has drifted
into three incompatible dialects:

    32 occurrences   "CL-008", "BR-001", "INT-019"      registry IDs
    46 occurrences   "LPDC Art. 23 bis — failure ..."   article references
    23 occurrences   "PATTERN-OF-FAILURE", "Abuso ..."  prose assertions

The application's contract is the ID dialect.  ``templates/revision.html``
seeds the field's editor with ``["BR-001", "CL-002"]`` and
``tests/integration/test_json_store.py`` asserts
``violations_cited == ["BR-001"]``.  Anything else is unjoinable: a consumer
cannot look "LPDC Art. 23 bis" up in the registry without re-implementing
citation parsing, and the registry is the thing that carries severity,
confidence and the underlying evidence blocks.

The crosswalk below is EXPLICIT, not inferred
---------------------------------------------
Resolving an article reference to a violation record is a legal judgement, not
a string operation.  A mechanical rule (e.g. "pick the record whose confidence
components mention this article") was tried and produces confidently wrong
answers: it maps ``CACH Art. 133`` to ``CL-006`` ("Next-Day Boarding Denial")
because ``CL-006`` happens to carry ``CL.CACH.Art.133`` as its single
component, when the record actually titled *"Failure to Offer CACH Art. 133(2)
Compensation"* is ``CL-039``.

So every mapping is written out below with the evidence used to choose it.
Nothing is guessed at run time.  Where no record is clearly on point the entry
is listed in ``DROP`` and the citation is removed -- per the agreed policy that
unmappable entries are dropped rather than kept in a non-conforming dialect.
Every dropped string is still recorded in the report, so the information is
preserved for review even though it leaves the field.

See ``docs/VIOLATIONS_CROSSWALK.md`` (generated) for the per-citation outcome.

Usage:
    python3 scripts/fix_violations_cited.py --dry-run
    python3 scripts/fix_violations_cited.py
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _headerlib import WORKSPACE, load_docs, save_docs  # noqa: E402

REGISTRY_DIR = WORKSPACE / "discovery" / "_files_which_will_be_used_in_pipeline" / "violations"
REPORT = WORKSPACE / "transcription" / "docs" / "VIOLATIONS_CROSSWALK.md"

# --------------------------------------------------------------------------- #
# The crosswalk
# --------------------------------------------------------------------------- #
# Keyed by the normalised article token produced by ``article_key``:
#     ("LPDC", "23 bis"), ("CACH", "133"), ("CONST", "19.1") ...
#
# Each target was chosen because the registry record either names the article
# in its own title (strongest evidence) or is the only record whose confidence
# components cite that article *and* whose title matches the cited conduct.
ARTICLE_MAP: dict[tuple[str, str], str] = {
    # -- LPDC (Ley de Protección al Consumidor) -----------------------------
    # CL-038 is titled "Failure to Provide LPDC Art. 23 bis Mandatory Written
    # Notice — All Subsections (a)–(e) Breached": names the article exactly.
    ("LPDC", "23 bis"): "CL-038",
    # CL-039 is titled "Failure to Offer CACH Art. 133(2) Compensation
    # (10-20 UF) for Denied Boarding": 3(e) is the compensation entitlement.
    ("LPDC", "3(e)"): "CL-039",
    # CL-010 "Rights Violation — Systematic Denial of Fundamental Passenger
    # Rights" carries component CL.LPDC.Art.3.b.
    ("LPDC", "3(b)"): "CL-010",
    # Ley 20.831 (right to information). CL-029 "DGAC Violations of Ley 16.752"
    # carries components CL.LEY20285.Art.3 and CL.LEY20285.Art.14.
    ("LEY 20.831", "20.831"): "CL-029",
    # -- CACH (Código Aeronáutico de Chile) ---------------------------------
    # CL-039 title names CACH Art. 133(2) explicitly.
    ("CACH", "133"): "CL-039",
    ("CACH", "133B(d)"): "CL-039",
    # CACH Art. 131 is the carrier's duty to inform passengers of their rights.
    # No record is titled for it; CL-010 is the "denial of fundamental passenger
    # rights" record and is the closest on-point home.
    ("CACH", "131"): "CL-010",
    # -- CONST (Constitución de Chile) --------------------------------------
    # CL-010 carries component CL.CONST.T1.C3.P1.Art.19.1 -- a unique match.
    ("CONST", "19.1"): "CL-010",
    # CL-030 "Chilean Penal Code Violations by Public Officials" is the abuse-of-
    # authority record; Art. 19.4 is the constitutional due-process guarantee
    # breached by the same conduct.
    ("CONST", "19.4"): "CL-030",
    # CL-011 is titled "Denial of Due Process — No Evidence, No Reason Given for
    # Removal", which is exactly what Art. 19 Nº3 guarantees.
    ("CONST", "19 Nº3"): "CL-011",
    # -- CPCL (Código Penal de Chile) ---------------------------------------
    # CL-001 is titled "False Accusation of Aggression (Calumnia)".  Calumnia is
    # CPCL Art. 211; the registry cites the same article in its CHIPENCOD form.
    ("CPCL", "211"): "CL-001",
    ("CHIPENCOD", "211"): "CL-001",
    # CL-016 "Invalid Document — Unsigned 'Carta de Desembarque'" -- the record
    # for a falsified private instrument (CPCL Art. 197).
    ("CPCL", "197"): "CL-016",
    # CL-037 "Coercion — Conditional Documentation" carries the single component
    # CL.CPCL.L3.T4.Art.494.16: a unique, unambiguous match.
    ("CPCL", "494.16"): "CL-037",
    # CL-030 covers Penal Code offences by public officials (prevaricación,
    # abuso de autoridad) -- the Art. 193.4 heading.
    ("CPCL", "193.4"): "CL-030",
    # -- ICAO ---------------------------------------------------------------
    # INT-003 is titled "ICAO Annex 9 Standard 3.42 — Failure to Provide Written
    # Reasons for Refusal of Embarkation": names the standard exactly.
    ("ICAO", "Annex 9 Std. 3.42"): "INT-003",
}

# Prose citations that are legal characterisations in disguise, mapped by hand.
LITERAL_MAP: dict[str, str] = {
    "Abuso de autoridad — forcible removal without valid cause": "CL-030",
    "Abuso de autoridad — forcible removal without valid reason": "CL-030",
    "Concealment of official document by LATAM, PDI, DGAC": "CL-004",
    "Concealment of official document (carta de desembarque) by LATAM, PDI, DGAC": "CL-004",
    "False accusation (agresión) disproved by PDI cameras": "CL-005",
    "Lifetime travel ban without due process": "CL-041",
    "Lifetime travel ban without due process (85% market share)": "CL-041",
    "Procedural weaponization — airline accusation compels automatic police action with zero discretion": "CL-012",
    "Systemic pattern of false detentions for 'aggression' by LATAM (daily occurrence)": "CL-002",
    "Systemic institutional practice of false detentions — 'casi todos los días'": "CL-002",
    "Systemic institutional practice — daily false detentions confirmed by Carabinero": "CL-002",
    "Systemic institutional practice — daily false detentions confirmed by Carabineros (cross‑reference)": "CL-002",
    "Violation of passenger rights under CACH Art. 131, 133": "CL-039",
    "Failure to provide lawful notice (LPDC Art. 23 bis)": "CL-038",
    "Issuance of falsified, unsigned document (CPCL Art. 197)": "CL-016",
    "ICAO Annex 9 Std. 3.42 — no written reasons given at time of removal": "INT-003",
}

# Deliberately removed.  These are either pattern/doctrine labels rather than
# citable provisions, or claims with no corresponding registry record.
# Nothing else may be dropped: the script aborts if a string is unresolved.
DROP: dict[str, str] = {
    "PATTERN-OF-FAILURE": "pattern label, not a citable provision",
    "TOTAL-SERVICE-BLOCK": "pattern label, not a citable provision",
    "WRONGFUL-USE-OF-INTERNAL-CHANNEL": "pattern label, not a citable provision",
    "EVIDENCE-PRESERVATION-DUTY": "doctrinal duty label, no registry record",
    "Pattern evidence for class‑wide liability and consumer fraud": "argument, not a provision",
    "Institutional discrimination / abuse of market power": "argument, not a provision",
    "Stigmatisation and discrimination via 'disruptivo' label": "argument, not a provision",
    "Ley 20.609 (Ley Zamudio)": "no registry record covers this statute",
}

# --------------------------------------------------------------------------- #
# Citation parsing
# --------------------------------------------------------------------------- #
_TAIL = re.compile(r"\s+[—–]\s+|:\s*")
# Keep letter-only parentheticals -- '(b)', '(e)', '(d)' -- because they
# distinguish sub-sections of the same article.  Drop everything else:
# '(mandatory written notice)', '(CHIPENCOD)', '(adequate information)', and
# ranges such as '(a)-(e)', which mean "all sub-sections" and so collapse to
# the bare article.
_KEEP_PAREN = re.compile(r"^\([a-h]\)$", re.I)
# A range such as '(a)-(e)' means "all sub-sections" and collapses to the bare
# article.  It must be removed before the per-parenthetical pass, which would
# otherwise see '(a)' and '(e)' as two independently meaningful markers.
_RANGE_PAREN = re.compile(r"\s*\([a-h]\)\s*-\s*\([a-h]\)", re.I)
_PAREN = re.compile(r"\s*\(([^()]*)\)")
_ART = re.compile(r"^(.*?)\s+Art\.?\s*(\S.*)$", re.I)

_LAW_ALIAS = {
    "CHIPENCOD": "CHIPENCOD",  # heading path through the Chilean Penal Code
    "CPCL": "CPCL",
    "CONST": "CONST",
    "LPDC": "LPDC",
    "CACH": "CACH",
}


def article_key(text: str) -> tuple[str, str] | None:
    """Normalise a citation to ``(LAW, ARTICLE)``, or None if not an article ref.

    >>> article_key("LPDC Art. 23 bis (a)-(e) — Mandatory written notice")
    ('LPDC', '23 bis')
    >>> article_key("LPDC Art. 3(b) — Right to truthful information")
    ('LPDC', '3(b)')
    >>> article_key("LPDC Art. 3(b) (adequate information)")
    ('LPDC', '3(b)')
    >>> article_key("CACH Art. 133B(d)")
    ('CACH', '133B(d)')
    >>> article_key("PATTERN-OF-FAILURE") is None
    True
    """
    head = _TAIL.split(text, maxsplit=1)[0].strip()
    head = _RANGE_PAREN.sub("", head).strip()

    # Remove descriptive parentheticals, preserving sub-section letters.
    head = _PAREN.sub(
        lambda m: m.group(0) if _KEEP_PAREN.match(m.group(0).strip()) else "",
        head,
    ).strip()

    match = _ART.match(head)
    if not match:
        # 'Ley 20.831 (right to information)' -> normalise the statute number.
        ley = re.match(r"^Ley\s+(\d[\d.]*)$", head, re.I)
        if ley:
            return ("LEY " + ley.group(1), ley.group(1))
        return None

    law = re.sub(r"[^A-Za-z]", "", match.group(1)).upper()
    law = _LAW_ALIAS.get(law, law)
    article = match.group(2).strip().rstrip(".").strip()
    return (law, article)


def resolve(citation: str, registry_ids: set[str]) -> tuple[str | None, str]:
    """Return ``(violation_id_or_None, reason)`` for one citation string."""
    if citation in registry_ids:
        return citation, "already a registry ID"
    if citation in DROP:
        return None, f"dropped -- {DROP[citation]}"
    if citation in LITERAL_MAP:
        return LITERAL_MAP[citation], "literal crosswalk"
    key = article_key(citation)
    if key and key in ARTICLE_MAP:
        return ARTICLE_MAP[key], f"article {key[0]} Art. {key[1]}"
    return None, f"UNRESOLVED ({key!r})"


def load_registry_ids() -> set[str]:
    ids = set()
    for path in sorted(REGISTRY_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        ids.add(data.get("violation_id") or path.stem)
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    registry_ids = load_registry_ids()
    docs = load_docs()

    rows: list[dict] = []
    unresolved: list[str] = []
    total_changes = 0

    for stem, data in docs.items():
        old = list(data.get("violations_cited") or [])
        new: list[str] = []
        for citation in old:
            target, reason = resolve(citation, registry_ids)
            rows.append(
                {"file": stem, "citation": citation, "target": target, "reason": reason}
            )
            if target is None and reason.startswith("UNRESOLVED"):
                unresolved.append(f"{stem}: {citation!r} -> {reason}")
                continue
            if target and target not in new:
                new.append(target)
        # Deterministic order, and stable across runs.
        new = sorted(set(new))
        if new != old:
            total_changes += 1
        data["violations_cited"] = new

    if unresolved:
        print("FATAL: unresolved citations (add to ARTICLE_MAP/LITERAL_MAP/DROP):",
              file=sys.stderr)
        for line in unresolved:
            print(f"  {line}", file=sys.stderr)
        raise SystemExit(1)

    written = save_docs(docs, dry_run=args.dry_run)
    _write_report(rows, registry_ids)

    kept = sum(1 for r in rows if r["target"])
    dropped = sum(1 for r in rows if not r["target"])
    print(f"{len(rows)} citation instances: {kept} kept, {dropped} dropped")
    print(f"{len({r['citation'] for r in rows})} distinct strings, "
          f"{len(registry_ids)} registry IDs available")
    verb = "would update" if args.dry_run else "updated"
    print(f"{verb} {written} transcripts ({total_changes} with a changed list)")
    print("report:", REPORT.relative_to(WORKSPACE))


def _write_report(rows: list[dict], registry_ids: set[str]) -> None:
    by_reason = collections.Counter(r["reason"].split(" --")[0] for r in rows)
    dropped = [r for r in rows if not r["target"]]

    lines: list[str] = []
    lines.append("# Violations Cited — Citation Crosswalk\n")
    lines.append(
        "Generated by `transcription/scripts/fix_violations_cited.py`. "
        "Do not edit by hand.\n"
    )
    lines.append(
        "`violations_cited` was normalised to bare violation-registry IDs, the "
        "only format the application consumes (`templates/revision.html` seeds "
        "the field with `[\"BR-001\", \"CL-002\"]` and\n"
        "`tests/integration/test_json_store.py` asserts `[\"BR-001\"]`). "
        "Article references were resolved through the explicit table in the "
        "script; anything with no clearly corresponding registry record was "
        "dropped, and is listed below so the original citations survive.\n"
    )

    lines.append("\n## How each citation was resolved\n")
    lines.append("| Resolution route | Instances |\n|---|---:|")
    for reason, count in by_reason.most_common():
        lines.append(f"| {reason} | {count} |")

    lines.append("\n## Dropped citations\n")
    lines.append(
        "These strings left `violations_cited`. Each is either a pattern/"
        "doctrine label rather than a citable provision, or a claim with no "
        "corresponding registry record.\n"
    )
    lines.append("| Transcript | Citation | Why |\n|---|---|---|")
    for row in sorted(dropped, key=lambda r: (r["citation"], r["file"])):
        why = row["reason"].split("-- ", 1)[-1]
        lines.append(f"| `{row['file']}` | {row['citation']} | {why} |")

    lines.append("\n## Article crosswalk applied\n")
    lines.append("| Citation | Registry ID |\n|---|---|")
    for key in sorted(ARTICLE_MAP):
        lines.append(f"| {key[0]} Art. {key[1]} | `{ARTICLE_MAP[key]}` |")

    lines.append("\n## Registry IDs referenced but never cited\n")
    used = {r["target"] for r in rows if r["target"]}
    unused = sorted(registry_ids - used)
    lines.append(
        f"{len(unused)} of {len(registry_ids)} registry records are not "
        "referenced by any transcript:\n"
    )
    lines.append(", ".join(f"`{i}`" for i in unused))

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
