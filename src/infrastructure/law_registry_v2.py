"""Four-sub-report law registry (schema v2).

Replaces the single binary ``validation_ok`` flag with four independent,
independently-gated questions about ``data/law/**/*.md`` and the Qdrant
collection it is projected into:

=========================  ==============================================================
sub-report                 question
=========================  ==============================================================
``coverage_report``        is every local ELI in Qdrant, and every point backed by a file?
``identity_report``        when two files claim one ELI, is that legitimate and resolved?
``provenance_report``      does each point record the corpus-relative file it came from?
``fidelity_report``        does the ingested text match the canonical local text?
=========================  ==============================================================

The shape is fixed by ``data/law/schemas/law_registry.v2.schema.json``.

Two deliberate departures from the source specification
(``.dev/ongoing/04.1.md``), because its *rules* and its *worked example* disagree
and the rules are the correct half:

1. **A same-language collision fails the identity gate; it is not a locale
   pair.** Rule A.1.2 says "if an ELI appears in multiple files with the same
   language, this is an error. Stop and report the collision. Do not guess",
   yet the spec's example registry reports ``unintentional_duplicate: 0``. The
   corpus has four such collisions, so ``canonical_source`` is left ``null`` for
   them and the gate fails. Implementing the example instead would have
   certified a corpus that silently drops BCN amendment notes.
2. **``skipped`` is a real gate state.** Without a reachable Qdrant, coverage,
   provenance and fidelity cannot be computed. The schema already carries a
   ``skipped`` status, so they are reported as skipped rather than zeroed — a
   zeroed ``missing_total`` reads as "checked and clean". ``identity`` needs no
   infrastructure and is always computed, so ``--offline`` still produces a
   meaningful verdict.

Determinism: every list is sorted, and ``generated_at`` is the only field that
changes between two runs over unchanged inputs.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .qdrant_law_index import (
    CANONICAL_COLLECTION,
    CorpusPlan,
    LawArticle,
    LawCorpusParser,
    default_law_dir,
)

__all__ = [
    "CANONICAL_LANGUAGE_PRECEDENCE",
    "SCHEMA_VERSION_V2",
    "build_v2_registry",
    "collect_variants",
    "index_live_payloads",
    "normalize_for_fidelity",
    "sha256_hex",
]

SCHEMA_VERSION_V2 = "2.0.0"

#: Canonical-locale precedence from the specification's rule A.1.3. Note that
#: every one of the corpus's multi-locale collisions is an ``en``/``pt`` pair,
#: for which this order and the parser's ``preferred_language="en"`` agree, so
#: adopting it changes no current canonical choice. It differs from the parser
#: only for a hypothetical ``es``/``en`` pair.
CANONICAL_LANGUAGE_PRECEDENCE: tuple[str, ...] = ("es", "en", "pt")

#: A BCN amendment marker is an authoring annotation, not article text. The
#: specification removes it from the *normalised* comparison only (rule A.3), so
#: a body differing solely by these notes reports ``normalized``, not ``drift``.
_BCN_NOTE_RE = re.compile(r"(?m)^[ \t]*>[ \t]*\*\*BCN amendment note:.*$")

#: The trailing ``---`` authoring rule. ``normalize_content`` keeps it by
#: default, so parity comparisons have to tolerate it.
_TRAILING_RULE_RE = re.compile(r"(?:[ \t]*-{3,})+[ \t]*$")

_WHITESPACE_RE = re.compile(r"[ \t\n\r]+")


# ---------------------------------------------------------------------------
# Hashing / normalisation
# ---------------------------------------------------------------------------
def sha256_hex(text: str) -> str:
    """Full 64-hex SHA-256 of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_for_fidelity(text: str) -> str:
    """Specification rule A.3.

    NFC → line-ending unification → BCN-marker blockquote removal → whitespace
    collapse → trailing-rule removal.
    """
    normalised = unicodedata.normalize("NFC", text or "")
    normalised = normalised.replace("\r\n", "\n").replace("\r", "\n")
    normalised = _BCN_NOTE_RE.sub("", normalised)
    normalised = _WHITESPACE_RE.sub(" ", normalised).strip()
    return _TRAILING_RULE_RE.sub("", normalised).strip()


# ---------------------------------------------------------------------------
# Corpus-side collection
# ---------------------------------------------------------------------------
def collect_variants(
    root: Path | str,
    *,
    parser: LawCorpusParser | None = None,
) -> dict[str, list[LawArticle]]:
    """``eli -> [every article carrying that ELI]``, across the whole corpus.

    :meth:`LawCorpusParser.build_plan` keeps only the *chosen* variant per
    colliding ELI, so a caller that needs to see every claimant has to group the
    parse output itself. Read-only.
    """
    root = Path(root)
    parser = parser or LawCorpusParser()
    grouped: dict[str, list[LawArticle]] = defaultdict(list)
    for path in parser.iter_files(root):
        articles, _ = parser.parse_file(path, root=root)
        for article in articles:
            grouped[article.original_id].append(article)
    return dict(grouped)


def index_live_payloads(
    records: Iterable[Any],
) -> tuple[dict[str, dict[str, Any]], int]:
    """``(eli -> payload, point_count)`` from scrolled Qdrant records.

    Accepts either ``qm.Record`` objects or bare payload mappings, so the report
    can be built in a test without a Qdrant client. Points without an
    ``original_id`` are counted but not indexed — a point with no identity cannot
    be attributed to a local file, and dropping it silently would understate
    ``qdrant_points_total``.
    """
    live: dict[str, dict[str, Any]] = {}
    total = 0
    for record in records:
        total += 1
        payload = getattr(record, "payload", None)
        if payload is None:
            payload = record if isinstance(record, Mapping) else None
        if not isinstance(payload, Mapping):
            continue
        original_id = payload.get("original_id")
        if not original_id:
            continue
        # First point wins for a duplicated id. Duplicates are a coverage
        # concern of their own; the v1 report already tracks them.
        live.setdefault(str(original_id), dict(payload))
    return live, total


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
def _canonical_variant(variants: Sequence[LawArticle]) -> LawArticle | None:
    """Canonical variant per rule A.1, or ``None`` when the choice is not safe.

    ``None`` means "two claimants share a language": rule A.1.2 forbids guessing,
    and a guess is exactly what makes the loss invisible.
    """
    languages = [v.language for v in variants]
    if len(set(languages)) < len(languages):
        return None
    for language in CANONICAL_LANGUAGE_PRECEDENCE:
        for variant in variants:
            if variant.language == language:
                return variant
    # A language outside the precedence list: fall back to the first claimant in
    # a deterministic order rather than to file-iteration order.
    return sorted(variants, key=lambda v: (v.source_path, v.language))[0]


def _collision_kind(variants: Sequence[LawArticle]) -> str:
    return "unintentional_duplicate" if _canonical_variant(variants) is None else "intentional_multilocale"


def build_identity_report(
    plan: CorpusPlan,
    variants_by_eli: Mapping[str, Sequence[LawArticle]],
    *,
    chosen_by_eli: Mapping[str, LawArticle] | None = None,
) -> dict[str, Any]:
    """One entry per colliding ELI, with its language set and canonical choice."""
    collisions: list[dict[str, Any]] = []
    counts = {"intentional_multilocale": 0, "unintentional_duplicate": 0}

    for eli in sorted(plan.collisions):
        variants = list(variants_by_eli.get(eli) or [])
        if len(variants) < 2:  # pragma: no cover - defensive
            continue
        variants.sort(key=lambda v: (v.language, v.source_path))
        canonical = _canonical_variant(variants)
        kind = _collision_kind(variants)
        counts[kind] += 1

        languages = sorted({v.language for v in variants})
        if canonical is None:
            note = (
                f"no canonical source: {len(variants)} claimants share a language "
                f"({', '.join(languages)}); rule A.1.2 forbids guessing"
            )
        else:
            note = f"canonical locale {canonical.language} of {{{', '.join(languages)}}}"
            chosen = (chosen_by_eli or {}).get(eli)
            if chosen is not None and chosen.source_path != canonical.source_path:
                note += f"; ingester would pick {chosen.source_path}"

        collisions.append(
            {
                "eli": eli,
                "kind": kind,
                "sources": sorted(v.source_path for v in variants),
                "canonical_source": canonical.source_path if canonical else None,
                "resolution_note": note,
            }
        )

    return {
        "gate": "pass" if counts["unintentional_duplicate"] == 0 and all(
            c["canonical_source"] for c in collisions
        ) else "fail",
        "totals": {
            "collisions_total": len(collisions),
            "intentional_multilocale": counts["intentional_multilocale"],
            "unintentional_duplicate": counts["unintentional_duplicate"],
        },
        "collisions": collisions,
    }


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------
def build_coverage_report(
    plan: CorpusPlan,
    live: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Per-file local-vs-Qdrant coverage.

    ``reference_only`` files carry no ELIs by construction, so they are excluded
    from the missing/extra counts; their ``blocks_without_eli`` is reported for
    transparency only.
    """
    files: list[dict[str, Any]] = []
    missing_all: set[str] = set()
    reference_only_blocks = 0

    for report in sorted(plan.files, key=lambda f: f.rel_path):
        elis = sorted(report.unique_elis)
        if report.reference_only:
            reference_only_blocks += report.blocks_without_eli
            files.append(
                {
                    "file": report.rel_path,
                    "language": report.language,
                    "reference_only": True,
                    "reference_note": report.reference_note,
                    "articles_local": 0,
                    "articles_ingested": 0,
                    "missing_eli": [],
                    "extra_eli": [],
                    "blocks_without_eli": report.blocks_without_eli,
                }
            )
            continue

        missing = sorted(eli for eli in elis if eli not in live)
        missing_all.update(missing)
        files.append(
            {
                "file": report.rel_path,
                "language": report.language,
                "reference_only": False,
                "reference_note": report.reference_note,
                "articles_local": len(elis),
                "articles_ingested": len(elis) - len(missing),
                "missing_eli": missing,
                "extra_eli": [],
                "blocks_without_eli": report.blocks_without_eli,
            }
        )

    local_ids = set(plan.by_original_id)
    extras = sorted(set(live) - local_ids)
    totals = {
        "missing_total": len(missing_all),
        "extra_total": len(extras),
        "reference_only_blocks": reference_only_blocks,
    }
    return {
        "gate": "pass" if totals["missing_total"] == 0 and totals["extra_total"] == 0 else "fail",
        "files": files,
        "totals": totals,
    }


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
def build_provenance_report(
    live: Mapping[str, Mapping[str, Any]],
    expected_path_by_eli: Mapping[str, str],
    *,
    accepted_paths_by_eli: Mapping[str, set[str]] | None = None,
    sample: int | None = None,
) -> dict[str, Any]:
    """Does each point name the corpus-relative file it was ingested from?

    The specification's anti-pattern #2 is the driver: the canonical payload
    writes ``source_file`` (a **basename**) unless ``include_extra`` is set, and
    a basename collides across ``CL/``, ``BR/`` and ``INT/``. A point with no
    ``source_path`` at all counts as ``missing_source_field``, not as a match.

    For an unresolved same-language collision there is no single expected path,
    so any *claimant* counts as a valid source — the ambiguity is reported by the
    identity report, which is where it can be adjudicated. Flagging it here too
    would report one cause as two failures.
    """
    points: list[dict[str, Any]] = []
    matched = mismatched = missing_field = 0

    for eli in sorted(live):
        expected = expected_path_by_eli.get(eli)
        if expected is None:
            accepted: set[str] = set()
        elif accepted_paths_by_eli is not None:
            accepted = set(accepted_paths_by_eli.get(eli) or {expected})
        else:
            accepted = {expected}
        raw = live[eli].get("source_path")
        in_payload = str(raw) if isinstance(raw, str) and raw else None
        if in_payload is None:
            missing_field += 1
            is_match = False
        else:
            is_match = in_payload in accepted
            if is_match:
                matched += 1
            else:
                mismatched += 1
        points.append(
            {
                "eli": eli,
                "qdrant_original_id": str(live[eli].get("original_id") or eli),
                "source_path_in_payload": in_payload,
                "source_path_expected": expected,
                "match": is_match,
            }
        )

    totals = {
        "points_total": len(points),
        "matched": matched,
        "mismatched": mismatched,
        "missing_source_field": missing_field,
    }
    return {
        "gate": "pass" if mismatched == 0 and missing_field == 0 else "fail",
        "points": points[:sample] if sample is not None else points,
        "totals": totals,
    }


# ---------------------------------------------------------------------------
# Fidelity
# ---------------------------------------------------------------------------
def build_fidelity_report(
    live: Mapping[str, Mapping[str, Any]],
    variants_by_eli: Mapping[str, Sequence[LawArticle]],
    canonical_by_eli: Mapping[str, LawArticle | None],
    *,
    sample: int | None = None,
) -> dict[str, Any]:
    """Byte-level comparison of ingested text against the canonical local text.

    Where no canonical source exists (an unresolved same-language collision) the
    item is compared against the lexicographically first claimant and the
    ambiguity is recorded in ``drift_note``. Comparing against the claimant the
    payload itself names would be circular — it would guarantee a match.
    """
    items: list[dict[str, Any]] = []
    counts = {"exact": 0, "normalized": 0, "drift": 0, "unreadable": 0}

    for eli in sorted(live):
        expected = canonical_by_eli.get(eli)
        if expected is None:
            claimants = list(variants_by_eli.get(eli) or [])
            if not claimants:
                counts["unreadable"] += 1
                payload_text = str(live[eli].get("content") or live[eli].get("text") or "")
                items.append(
                    {
                        "eli": eli,
                        "status": "unreadable",
                        "local_sha256": sha256_hex(""),
                        "qdrant_sha256": sha256_hex(payload_text),
                        "local_chars": 0,
                        "qdrant_chars": len(payload_text),
                        "drift_note": "no local article carries this ELI",
                    }
                )
                continue
            expected = sorted(claimants, key=lambda v: (v.source_path, v.language))[0]
            ambiguous = True
        else:
            ambiguous = False

        payload_text = str(live[eli].get("content") or live[eli].get("text") or "")
        note: str | None = None
        if expected.content == payload_text:
            status = "exact"
        elif normalize_for_fidelity(expected.content) == normalize_for_fidelity(payload_text):
            status = "normalized"
            note = "differs only in whitespace, separator or BCN amendment markers"
        else:
            status = "drift"
            note = f"local {len(expected.content)} chars vs qdrant {len(payload_text)} chars"
        if ambiguous:
            note = (
                f"no canonical source: {len(variants_by_eli.get(eli) or [])} same-language "
                f"claimants; compared against {expected.source_path}"
            )
        counts[status] += 1

        items.append(
            {
                "eli": eli,
                "status": status,
                "local_sha256": sha256_hex(expected.content),
                "qdrant_sha256": sha256_hex(payload_text),
                "local_chars": len(expected.content),
                "qdrant_chars": len(payload_text),
                "drift_note": note,
            }
        )

    return {
        "gate": "pass" if counts["drift"] == 0 and counts["unreadable"] == 0 else "fail",
        "items": items[:sample] if sample is not None else items,
        "totals": counts,
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _skipped(sub_report: dict[str, Any]) -> dict[str, Any]:
    """Mark a sub-report skipped and blank the parts we could not measure."""
    return {**sub_report, "gate": "skipped"}


def _overall(gates: Mapping[str, str]) -> str:
    values = {v for k, v in gates.items() if k != "overall"}
    if "fail" in values:
        return "fail"
    if "skipped" in values:
        return "skipped"
    return "pass"


def build_v2_registry(
    plan: CorpusPlan,
    *,
    collection: str = CANONICAL_COLLECTION,
    root: Path | str | None = None,
    live_records: Iterable[Any] | None = None,
    variants_by_eli: Mapping[str, Sequence[LawArticle]] | None = None,
    sample: int | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the v2 registry document.

    ``live_records=None`` (offline) still computes the identity report — it is a
    property of the corpus alone — and marks the other three ``skipped``.
    """
    root = Path(root) if root is not None else default_law_dir()
    if variants_by_eli is None:
        variants_by_eli = collect_variants(root)

    chosen_by_eli = plan.by_original_id
    identity = build_identity_report(plan, variants_by_eli, chosen_by_eli=chosen_by_eli)
    canonical_by_eli: dict[str, LawArticle | None] = {
        eli: _canonical_variant(list(vs)) for eli, vs in variants_by_eli.items()
    }

    expected_path_by_eli: dict[str, str] = {}
    accepted_paths_by_eli: dict[str, set[str]] = {}
    for eli, claimants in variants_by_eli.items():
        paths = sorted(v.source_path for v in claimants)
        if not paths:  # pragma: no cover - defensive
            continue
        canonical = canonical_by_eli.get(eli)
        expected_path_by_eli[eli] = canonical.source_path if canonical else paths[0]
        accepted_paths_by_eli[eli] = {canonical.source_path} if canonical else set(paths)

    if live_records is None:
        coverage = _skipped(
            {
                "gate": "skipped",
                "files": [],
                "totals": {"missing_total": 0, "extra_total": 0, "reference_only_blocks": 0},
            }
        )
        provenance = _skipped(
            {
                "gate": "skipped",
                "points": [],
                "totals": {"points_total": 0, "matched": 0, "mismatched": 0, "missing_source_field": 0},
            }
        )
        fidelity = _skipped(
            {
                "gate": "skipped",
                "items": [],
                "totals": {"exact": 0, "normalized": 0, "drift": 0, "unreadable": 0},
            }
        )
        points_total = 0
        elis_in_qdrant = 0
    else:
        live, points_total = index_live_payloads(live_records)
        coverage = build_coverage_report(plan, live)
        provenance = build_provenance_report(
            live,
            expected_path_by_eli,
            accepted_paths_by_eli=accepted_paths_by_eli,
            sample=sample,
        )
        fidelity = build_fidelity_report(live, variants_by_eli, canonical_by_eli, sample=sample)
        elis_in_qdrant = len(live)

    languages = plan.languages
    gates = {
        "coverage": coverage["gate"],
        "identity": identity["gate"],
        "provenance": provenance["gate"],
        "fidelity": fidelity["gate"],
    }
    return {
        "schema_version": SCHEMA_VERSION_V2,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "collection": collection,
        "summary": {
            "md_files_total": len(plan.files),
            "reference_only_files": len(plan.reference_only_files),
            "elis_local_total": len(plan.by_original_id),
            "elis_in_qdrant_total": elis_in_qdrant,
            "qdrant_points_total": points_total,
            "language_breakdown": {
                "pt": languages.get("pt", 0),
                "es": languages.get("es", 0),
                "en": languages.get("en", 0),
            },
        },
        "coverage_report": coverage,
        "identity_report": identity,
        "provenance_report": provenance,
        "fidelity_report": fidelity,
        "gates": {**gates, "overall": _overall(gates)},
    }
