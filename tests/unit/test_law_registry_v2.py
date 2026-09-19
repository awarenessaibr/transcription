"""Unit tests for the four-sub-report law registry (schema v2).

Everything here runs offline: ``index_live_payloads`` accepts bare mappings, so
a "live collection" is just a list of dicts. No Qdrant client is constructed.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure.law_registry_v2 import (
    CANONICAL_LANGUAGE_PRECEDENCE,
    SCHEMA_VERSION_V2,
    _canonical_variant,
    _collision_kind,
    _overall,
    build_coverage_report,
    build_fidelity_report,
    build_identity_report,
    build_provenance_report,
    build_v2_registry,
    index_live_payloads,
    normalize_for_fidelity,
    sha256_hex,
)
from src.infrastructure.qdrant_law_index import CorpusPlan, FileReport, LawArticle

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "data/law/schemas/law_registry.v2.schema.json"


def make_article(
    *,
    eli: str,
    language: str,
    content: str,
    source_path: str,
    reference_only: bool = False,
) -> LawArticle:
    """A ``LawArticle`` with only the fields the v2 reports read."""
    return LawArticle(
        original_id=eli,
        title=f"Title of {eli}",
        theme="Aviation",
        tags="aviation · safety",
        content=content,
        source_file=Path(source_path).name,
        source_path=source_path,
        jurisdiction="BR",
        framework_code="LA8159",
        language=language,
        doc_type="statute",
        reference_only=reference_only,
    )


def make_plan(*, files: list[FileReport] | None = None, articles: list[LawArticle] | None = None,
              collisions: dict[str, list[str]] | None = None) -> CorpusPlan:
    return CorpusPlan(
        articles=articles or [],
        files=files or [],
        collisions=collisions or {},
    )


# ---------------------------------------------------------------------------
# normalize_for_fidelity
# ---------------------------------------------------------------------------
def test_normalize_collapses_whitespace_and_unifies_line_endings() -> None:
    assert normalize_for_fidelity("a\r\n\r\nb") == "a b"
    assert normalize_for_fidelity("a\rb") == "a b"
    assert normalize_for_fidelity("  a\t\t b  ") == "a b"


def test_normalize_applies_nfc_so_decomposed_accents_compare_equal() -> None:
    decomposed = "Constituic\u0327a\u0303o"  # c + cedilla, a + tilde
    composed = "Constitui\u00e7\u00e3o"
    assert decomposed != composed
    assert normalize_for_fidelity(decomposed) == normalize_for_fidelity(composed)
    assert normalize_for_fidelity(composed) == composed


def test_normalize_removes_bcn_amendment_note_blocks() -> None:
    text = "Art. 1. Texto.\n\n> **BCN amendment note:** Ley 20.555 reformó este artículo.\n\nArt. 2."
    result = normalize_for_fidelity(text)
    assert "BCN amendment note" not in result
    assert "Ley 20.555" not in result
    assert result == "Art. 1. Texto. Art. 2."


def test_normalize_strips_only_a_trailing_authoring_rule() -> None:
    assert normalize_for_fidelity("Art. 1.\n\n---\n") == "Art. 1."
    # A rule in the middle is content, not a separator.
    assert normalize_for_fidelity("Art. 1.\n\n---\n\nArt. 2.") == "Art. 1. --- Art. 2."


def test_normalize_handles_empty_text() -> None:
    assert normalize_for_fidelity("") == ""
    assert normalize_for_fidelity("   \n\n  ") == ""


# ---------------------------------------------------------------------------
# sha256_hex
# ---------------------------------------------------------------------------
def test_sha256_hex_matches_known_digest_and_shape() -> None:
    digest = sha256_hex("abc")
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert len(digest) == 64 and digest == digest.lower()


def test_sha256_hex_is_encoding_sensitive() -> None:
    # Accents must be hashed as UTF-8 bytes, not latin-1.
    assert sha256_hex("ação") != sha256_hex("acao")


# ---------------------------------------------------------------------------
# index_live_payloads
# ---------------------------------------------------------------------------
def test_index_live_payloads_accepts_records_and_bare_mappings() -> None:
    live, total = index_live_payloads(
        [
            SimpleNamespace(payload={"original_id": "A.1", "text": "x"}),
            {"original_id": "A.2", "text": "y"},
        ]
    )
    assert total == 2
    assert sorted(live) == ["A.1", "A.2"]
    assert live["A.1"]["text"] == "x"


def test_index_live_payloads_counts_but_does_not_index_anonymous_points() -> None:
    live, total = index_live_payloads(
        [{"original_id": "A.1"}, {"text": "no identity"}, "not-a-mapping"]
    )
    assert total == 3, "points without an id must still be counted"
    assert list(live) == ["A.1"]


def test_index_live_payloads_keeps_the_first_point_for_a_duplicated_id() -> None:
    live, total = index_live_payloads(
        [{"original_id": "A.1", "text": "first"}, {"original_id": "A.1", "text": "second"}]
    )
    assert total == 2
    assert live["A.1"]["text"] == "first"


# ---------------------------------------------------------------------------
# _canonical_variant / _collision_kind
# ---------------------------------------------------------------------------
def test_canonical_variant_returns_none_for_a_same_language_collision() -> None:
    variants = [
        make_article(eli="X.1", language="es", content="a", source_path="CL/one.md"),
        make_article(eli="X.1", language="es", content="b", source_path="CL/two.md"),
    ]
    assert _canonical_variant(variants) is None
    assert _collision_kind(variants) == "unintentional_duplicate"


@pytest.mark.parametrize(
    ("languages", "expected"),
    [(["pt"], "pt"), (["en", "pt"], "en"), (["es", "pt"], "es"),
     (["es", "en", "pt"], "es"), (["en", "es"], "es")],
)
def test_canonical_variant_follows_es_en_pt_precedence(languages: list[str], expected: str) -> None:
    variants = [
        make_article(eli="X.1", language=lang, content=f"body {lang}", source_path=f"INT/{lang}/f.md")
        for lang in languages
    ]
    assert _canonical_variant(variants).language == expected
    assert _collision_kind(variants) == "intentional_multilocale"


def test_canonical_variant_handles_a_lone_variant() -> None:
    only = make_article(eli="X.1", language="pt", content="a", source_path="CL/one.md")
    assert _canonical_variant([only]) is only


def test_canonical_language_precedence_is_documented_order() -> None:
    assert CANONICAL_LANGUAGE_PRECEDENCE == ("es", "en", "pt")


# ---------------------------------------------------------------------------
# build_identity_report
# ---------------------------------------------------------------------------
def test_identity_passes_for_a_multilocale_pair_and_names_the_canonical() -> None:
    variants = {
        "INT.VCLT.Art.26": [
            make_article(eli="INT.VCLT.Art.26", language="en", content="EN", source_path="INT/EN/VCLT_1969.md"),
            make_article(eli="INT.VCLT.Art.26", language="pt", content="PT", source_path="INT/BR/VCLT_1969.md"),
        ]
    }
    plan = make_plan(collisions={"INT.VCLT.Art.26": ["INT/EN/VCLT_1969.md", "INT/BR/VCLT_1969.md"]})
    report = build_identity_report(plan, variants)

    assert report["gate"] == "pass"
    assert report["totals"] == {
        "collisions_total": 1,
        "intentional_multilocale": 1,
        "unintentional_duplicate": 0,
    }
    collision = report["collisions"][0]
    assert collision["canonical_source"] == "INT/EN/VCLT_1969.md"
    assert collision["sources"] == ["INT/BR/VCLT_1969.md", "INT/EN/VCLT_1969.md"]


def test_identity_fails_when_two_claimants_share_a_language() -> None:
    variants = {
        "CL.CPCL.C1.Art.269_ter": [
            make_article(eli="CL.CPCL.C1.Art.269_ter", language="es", content="short",
                         source_path="CL/CL.CPCL.C1.Art.269_ter.md"),
            make_article(eli="CL.CPCL.C1.Art.269_ter", language="es", content="long",
                         source_path="CL/CodigoPenal.md"),
            make_article(eli="CL.CPCL.C1.Art.269_ter", language="es", content="medium",
                         source_path="CL/CodigoPenal_269bis_269ter.md"),
        ]
    }
    plan = make_plan(collisions={"CL.CPCL.C1.Art.269_ter": ["a", "b", "c"]})
    report = build_identity_report(plan, variants)

    assert report["gate"] == "fail"
    assert report["totals"]["unintentional_duplicate"] == 1
    collision = report["collisions"][0]
    assert collision["canonical_source"] is None, "rule A.1.2 forbids guessing a canonical"
    assert "3 claimants share a language" in collision["resolution_note"]


def test_identity_records_when_the_ingester_would_pick_a_different_variant() -> None:
    variants = {
        "X.1": [
            make_article(eli="X.1", language="en", content="EN", source_path="INT/EN/f.md"),
            make_article(eli="X.1", language="pt", content="PT", source_path="INT/BR/f.md"),
        ]
    }
    plan = make_plan(collisions={"X.1": ["a", "b"]})
    # Pretend the parser was configured for Portuguese.
    chosen = {"X.1": variants["X.1"][1]}
    report = build_identity_report(plan, variants, chosen_by_eli=chosen)

    assert report["collisions"][0]["canonical_source"] == "INT/EN/f.md"
    assert "ingester would pick INT/BR/f.md" in report["collisions"][0]["resolution_note"]


def test_identity_ignores_a_collision_with_fewer_than_two_variants() -> None:
    plan = make_plan(collisions={"X.1": ["a"]})
    report = build_identity_report(plan, {"X.1": [make_article(
        eli="X.1", language="es", content="a", source_path="CL/a.md")]})
    assert report["totals"]["collisions_total"] == 0
    assert report["gate"] == "pass"


# ---------------------------------------------------------------------------
# build_coverage_report
# ---------------------------------------------------------------------------
def _coverage_fixture() -> tuple[CorpusPlan, dict[str, dict[str, str]]]:
    plan = make_plan(
        # ``plan.articles`` is what makes an ELI "local": without it every live
        # point is reported as extra, which is the correct behaviour and the
        # reason this fixture must populate it.
        articles=[
            make_article(eli="X.1", language="es", content="body 1", source_path="CL/a.md"),
            make_article(eli="X.2", language="es", content="body 2", source_path="CL/a.md"),
        ],
        files=[
            FileReport(rel_path="CL/a.md", language="es", reference_only=False,
                       articles_local=2, elis=["X.1", "X.2"]),
            FileReport(rel_path="CL/ref.md", language="es", reference_only=True,
                       articles_local=0, elis=[], blocks_without_eli=7,
                       reference_note="index only"),
        ],
    )
    live = {"X.1": {"original_id": "X.1"}}
    return plan, live


def test_coverage_reports_missing_per_file_and_in_totals() -> None:
    plan, live = _coverage_fixture()
    report = build_coverage_report(plan, live)

    assert report["gate"] == "fail"
    assert report["totals"]["missing_total"] == 1
    assert report["totals"]["extra_total"] == 0
    file_entry = next(f for f in report["files"] if f["file"] == "CL/a.md")
    assert file_entry["missing_eli"] == ["X.2"]
    assert file_entry["articles_local"] == 2
    assert file_entry["articles_ingested"] == 1


def test_coverage_reports_every_live_point_with_no_local_article_as_extra() -> None:
    plan, _ = _coverage_fixture()
    report = build_coverage_report(plan, {"X.999": {"original_id": "X.999"}})
    assert report["totals"]["extra_total"] == 1, "X.999 has no local article"
    assert report["totals"]["missing_total"] == 2, "X.1 and X.2 are no longer in Qdrant"
    assert report["gate"] == "fail"


def test_coverage_excludes_reference_only_files_from_missing_but_reports_their_blocks() -> None:
    plan, live = _coverage_fixture()
    report = build_coverage_report(plan, live)

    assert report["totals"]["reference_only_blocks"] == 7
    ref = next(f for f in report["files"] if f["file"] == "CL/ref.md")
    assert ref["reference_only"] is True
    assert ref["missing_eli"] == []
    assert ref["blocks_without_eli"] == 7


def test_coverage_flags_an_eli_that_exists_only_in_qdrant() -> None:
    plan, live = _coverage_fixture()
    live["X.999"] = {"original_id": "X.999"}
    report = build_coverage_report(plan, live)

    assert report["totals"]["extra_total"] == 1
    assert report["gate"] == "fail"


def test_coverage_passes_when_local_and_qdrant_agree() -> None:
    plan, live = _coverage_fixture()
    live["X.2"] = {"original_id": "X.2"}
    report = build_coverage_report(plan, live)
    assert report["gate"] == "pass"
    assert report["totals"] == {"missing_total": 0, "extra_total": 0, "reference_only_blocks": 7}


# ---------------------------------------------------------------------------
# build_provenance_report
# ---------------------------------------------------------------------------
def test_provenance_counts_a_missing_field_as_missing_not_as_a_match() -> None:
    live = {"X.1": {"original_id": "X.1", "source_file": "a.md"}}
    report = build_provenance_report(live, {"X.1": "CL/a.md"})

    assert report["gate"] == "fail"
    assert report["totals"] == {
        "points_total": 1,
        "matched": 0,
        "mismatched": 0,
        "missing_source_field": 1,
    }
    assert report["points"][0]["source_path_in_payload"] is None
    assert report["points"][0]["match"] is False


def test_provenance_a_basename_is_not_accepted_in_place_of_a_relative_path() -> None:
    """Anti-pattern #2: ``source_file`` is a basename and must not satisfy the gate."""
    live = {"X.1": {"original_id": "X.1", "source_path": "ACHR_1969.md"}}
    report = build_provenance_report(live, {"X.1": "INT/EN/ACHR_1969.md"})

    assert report["totals"]["mismatched"] == 1
    assert report["totals"]["matched"] == 0


def test_provenance_matches_the_canonical_relative_path() -> None:
    live = {"X.1": {"original_id": "X.1", "source_path": "INT/EN/ACHR_1969.md"}}
    report = build_provenance_report(live, {"X.1": "INT/EN/ACHR_1969.md"})

    assert report["gate"] == "pass"
    assert report["totals"]["matched"] == 1
    assert report["points"][0]["match"] is True


def test_provenance_accepts_any_claimant_when_no_canonical_exists() -> None:
    """An unresolved collision has no single expected path; both claimants are valid."""
    live = {
        "X.1": {"original_id": "X.1", "source_path": "CL/one.md"},
        "X.2": {"original_id": "X.2", "source_path": "CL/two.md"},
    }
    accepted = {"X.1": {"CL/one.md", "CL/two.md"}, "X.2": {"CL/one.md", "CL/two.md"}}
    report = build_provenance_report(
        live, {"X.1": "CL/one.md", "X.2": "CL/one.md"}, accepted_paths_by_eli=accepted
    )
    assert report["gate"] == "pass"
    assert report["totals"]["matched"] == 2


def test_provenance_caps_the_points_array_without_changing_the_totals() -> None:
    live = {f"X.{i}": {"original_id": f"X.{i}", "source_path": "CL/a.md"} for i in range(10)}
    expected = {eli: "CL/a.md" for eli in live}
    report = build_provenance_report(live, expected, sample=3)

    assert len(report["points"]) == 3
    assert report["totals"]["points_total"] == 10
    assert report["totals"]["matched"] == 10


def test_provenance_ignores_points_with_no_corpus_eli() -> None:
    report = build_provenance_report({"X.999": {"original_id": "X.999"}}, {"X.1": "CL/a.md"})
    # No expected path -> blank accepted set -> the named path cannot match.
    assert report["totals"]["points_total"] == 1


# ---------------------------------------------------------------------------
# build_fidelity_report
# ---------------------------------------------------------------------------
def _fidelity(live_text: str, local_text: str, *, language: str = "en") -> dict:
    article = make_article(eli="X.1", language=language, content=local_text, source_path="CL/a.md")
    live = {"X.1": {"original_id": "X.1", "text": live_text}}
    return build_fidelity_report(live, {"X.1": [article]}, {"X.1": article})


def test_fidelity_exact_when_bytes_are_identical() -> None:
    report = _fidelity("Art. 1.\n", "Art. 1.\n")
    assert report["gate"] == "pass"
    assert report["totals"]["exact"] == 1
    assert report["items"][0]["drift_note"] is None


def test_fidelity_normalized_when_only_whitespace_differs() -> None:
    report = _fidelity("Art.  1.\r\n", "Art. 1.")
    assert report["gate"] == "pass", "a whitespace-only difference is not drift"
    assert report["totals"]["normalized"] == 1
    assert "whitespace" in report["items"][0]["drift_note"]


def test_fidelity_normalized_when_only_an_added_bcn_marker_differs() -> None:
    report = _fidelity(
        "Art. 1.\n\n> **BCN amendment note:** reform\n",
        "Art. 1.",
    )
    assert report["totals"]["normalized"] == 1
    assert report["gate"] == "pass"


def test_fidelity_drift_fails_the_gate_and_records_both_lengths() -> None:
    report = _fidelity("Art. 1. Extra wording.", "Art. 1.")

    assert report["gate"] == "fail"
    assert report["totals"]["drift"] == 1
    item = report["items"][0]
    assert item["status"] == "drift"
    assert item["local_chars"] == len("Art. 1.")
    assert item["qdrant_chars"] == len("Art. 1. Extra wording.")
    assert "vs qdrant" in item["drift_note"]


def test_fidelity_unreadable_when_no_local_article_carries_the_eli() -> None:
    live = {"ORPHAN.1": {"original_id": "ORPHAN.1", "text": "body"}}
    report = build_fidelity_report(live, {}, {})

    assert report["gate"] == "fail"
    assert report["totals"]["unreadable"] == 1
    assert report["items"][0]["local_chars"] == 0
    assert "no local article" in report["items"][0]["drift_note"]


def test_fidelity_ambiguous_collision_compares_against_the_first_claimant_by_path() -> None:
    """Comparing against the claimant the payload names would be circular."""
    first = make_article(eli="X.1", language="es", content="FIRST", source_path="CL/a_first.md")
    second = make_article(eli="X.1", language="es", content="SECOND", source_path="CL/b_second.md")
    live = {"X.1": {"original_id": "X.1", "text": "SECOND"}}
    report = build_fidelity_report(live, {"X.1": [first, second]}, {"X.1": None})

    item = report["items"][0]
    assert item["status"] == "drift", "compared against the first claimant, not the named one"
    assert item["local_sha256"] == sha256_hex("FIRST")
    assert "no canonical source" in item["drift_note"]
    assert "CL/a_first.md" in item["drift_note"]


def test_fidelity_prefers_content_over_text_when_both_are_present() -> None:
    report = _fidelity("", "Art. 1.")
    assert report["totals"]["exact"] == 0
    live = {"X.1": {"original_id": "X.1", "content": "Art. 1.", "text": "STALE"}}
    article = make_article(eli="X.1", language="en", content="Art. 1.", source_path="CL/a.md")
    report = build_fidelity_report(live, {"X.1": [article]}, {"X.1": article})
    assert report["totals"]["exact"] == 1


def test_fidelity_omits_eli_absent_from_both_sides() -> None:
    report = build_fidelity_report({}, {}, {})
    assert report["gate"] == "pass"
    assert report["items"] == []
    assert report["totals"] == {"exact": 0, "normalized": 0, "drift": 0, "unreadable": 0}


# ---------------------------------------------------------------------------
# _overall
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("gates", "expected"),
    [
        ({"coverage": "pass", "identity": "pass", "provenance": "pass", "fidelity": "pass"}, "pass"),
        ({"coverage": "pass", "identity": "pass", "provenance": "pass", "fidelity": "skipped"}, "skipped"),
        ({"coverage": "skipped", "identity": "fail", "provenance": "skipped", "fidelity": "skipped"}, "fail"),
        ({"coverage": "fail", "identity": "pass", "provenance": "fail", "fidelity": "skipped"}, "fail"),
    ],
)
def test_overall_precedence_is_fail_then_skipped_then_pass(gates: dict[str, str], expected: str) -> None:
    assert _overall(gates) == expected


def test_overall_ignores_its_own_key_so_it_cannot_self_reference() -> None:
    gates = {"coverage": "pass", "identity": "pass", "provenance": "pass", "fidelity": "pass",
             "overall": "fail"}
    assert _overall(gates) == "pass"


# ---------------------------------------------------------------------------
# build_v2_registry
# ---------------------------------------------------------------------------
def _registry_fixture() -> tuple[CorpusPlan, dict[str, list[LawArticle]]]:
    en = make_article(eli="INT.VCLT.Art.26", language="en", content="EN body",
                      source_path="INT/EN/VCLT_1969.md")
    pt = make_article(eli="INT.VCLT.Art.26", language="pt", content="PT body",
                      source_path="INT/BR/VCLT_1969.md")
    solo = make_article(eli="BR.CC.Art.1", language="pt", content="BR body",
                        source_path="BR/CC.md")
    files = [
        FileReport(rel_path="INT/EN/VCLT_1969.md", language="en", reference_only=False,
                   articles_local=1, elis=["INT.VCLT.Art.26"]),
        FileReport(rel_path="BR/CC.md", language="pt", reference_only=False,
                   articles_local=1, elis=["BR.CC.Art.1"]),
    ]
    plan = make_plan(
        files=files,
        articles=[en, solo],
        collisions={"INT.VCLT.Art.26": ["INT/EN/VCLT_1969.md", "INT/BR/VCLT_1969.md"]},
    )
    return plan, {"INT.VCLT.Art.26": [pt, en], "BR.CC.Art.1": [solo]}


def test_offline_registry_skips_three_reports_but_still_computes_identity(tmp_path: Path) -> None:
    plan, variants = _registry_fixture()
    document = build_v2_registry(plan, root=tmp_path, variants_by_eli=variants)

    assert document["schema_version"] == SCHEMA_VERSION_V2
    assert document["collection"] == "la8159_law"
    assert document["gates"] == {
        "coverage": "skipped",
        "identity": "pass",
        "provenance": "skipped",
        "fidelity": "skipped",
        "overall": "skipped",
    }
    assert document["identity_report"]["totals"]["collisions_total"] == 1
    # A skipped report must not read as "checked and clean".
    assert document["coverage_report"]["totals"]["missing_total"] == 0
    assert document["coverage_report"]["gate"] == "skipped"
    assert document["summary"]["elis_in_qdrant_total"] == 0


def test_registry_summary_counts_the_corpus_not_the_writes(tmp_path: Path) -> None:
    plan, variants = _registry_fixture()
    document = build_v2_registry(plan, root=tmp_path, variants_by_eli=variants)

    assert document["summary"]["elis_local_total"] == 2
    # All three locales are always present, so a locale that genuinely hits zero
    # is distinguishable from one that was never counted.
    assert document["summary"]["language_breakdown"] == {"pt": 1, "es": 0, "en": 1}


def test_registry_online_run_gates_all_four_and_records_provenance(tmp_path: Path) -> None:
    plan, variants = _registry_fixture()
    live_records = [
        {"original_id": "INT.VCLT.Art.26", "content": "EN body",
         "source_path": "INT/EN/VCLT_1969.md"},
        # missing entirely -> coverage fail
    ]
    document = build_v2_registry(
        plan, root=tmp_path, variants_by_eli=variants, live_records=live_records
    )

    assert document["gates"]["coverage"] == "fail", "BR.CC.Art.1 was never written"
    assert document["coverage_report"]["totals"]["missing_total"] == 1
    assert document["gates"]["provenance"] == "pass"
    assert document["provenance_report"]["totals"]["matched"] == 1
    assert document["gates"]["fidelity"] == "pass"
    assert document["fidelity_report"]["totals"]["exact"] == 1
    assert document["gates"]["overall"] == "fail"


def test_registry_counts_points_without_an_eli_in_the_total(tmp_path: Path) -> None:
    plan, variants = _registry_fixture()
    live_records = [
        {"original_id": "BR.CC.Art.1", "content": "BR body", "source_path": "BR/CC.md"},
        {"original_id": "INT.VCLT.Art.26", "content": "EN body",
         "source_path": "INT/EN/VCLT_1969.md"},
        {"content": "anonymous point", "source_path": "unknown.md"},
    ]
    document = build_v2_registry(
        plan, root=tmp_path, variants_by_eli=variants, live_records=live_records
    )
    assert document["summary"]["qdrant_points_total"] == 3
    assert document["summary"]["elis_in_qdrant_total"] == 2


def test_registry_is_deterministic_when_the_timestamp_is_pinned(tmp_path: Path) -> None:
    plan, variants = _registry_fixture()
    live_records = [
        {"original_id": "BR.CC.Art.1", "content": "BR body", "source_path": "BR/CC.md"},
        {"original_id": "INT.VCLT.Art.26", "content": "EN body",
         "source_path": "INT/EN/VCLT_1969.md"},
    ]
    kwargs = dict(root=tmp_path, variants_by_eli=variants, live_records=live_records,
                  generated_at="2026-01-01T00:00:00+00:00")
    first = build_v2_registry(plan, **kwargs)
    second = build_v2_registry(plan, **kwargs)

    assert first["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_registry_gates_serialise_as_sorted_lists_of_sources(tmp_path: Path) -> None:
    plan, variants = _registry_fixture()
    document = build_v2_registry(plan, root=tmp_path, variants_by_eli=variants)
    collision = document["identity_report"]["collisions"][0]
    assert collision["sources"] == sorted(collision["sources"])


# ---------------------------------------------------------------------------
# JSON Schema conformance
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not SCHEMA_PATH.is_file(), reason="schema file not present"
)
def test_a_real_document_validates_against_the_published_schema(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")

    plan, variants = _registry_fixture()
    live_records = [
        {"original_id": "BR.CC.Art.1", "content": "BR body", "source_path": "BR/CC.md"},
        {"original_id": "INT.VCLT.Art.26", "content": "EN body",
         "source_path": "INT/EN/VCLT_1969.md"},
    ]
    document = build_v2_registry(
        plan, root=tmp_path, variants_by_eli=variants, live_records=live_records
    )

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    assert not errors, "\n".join(f"{list(e.absolute_path)}: {e.message}" for e in errors)


def test_the_schema_requires_every_top_level_report() -> None:
    if not SCHEMA_PATH.is_file():
        pytest.skip("schema file not present")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(schema["required"]) == {
        "schema_version",
        "generated_at",
        "collection",
        "summary",
        "coverage_report",
        "identity_report",
        "provenance_report",
        "fidelity_report",
        "gates",
    }
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION_V2
