"""Unit tests for the enrichment vocabulary and the saved review report.

The router tests exercise these helpers through ``/api/law/suggest``; this file
pins the vocabulary contract and the report layout directly, because both are
read by humans and by the corpus convention rather than by one caller.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.law_enrichment import (
    _ENRICHMENT_ALIASES,
    DOC_TYPE_GLOSSARY,
    DOC_TYPE_RULES,
    ENRICHMENT_FIELD_KINDS,
    ENRICHMENT_FIELDS,
    ENRICHMENT_GLOSSARY,
    ENRICHMENT_RULES,
    ENRICHMENT_VOCABULARY,
    REPORT_SUBDIR,
    TAXONOMY_FIELDS,
    fold_token,
    glossary_for,
    is_report_name,
    kind_for,
    list_reports,
    load_record,
    normalize_token,
    normalize_value,
    record_applied,
    render_report,
    report_paths,
    report_slug,
    rules_for,
    vocabulary_block,
    vocabulary_for,
    write_report,
)
from src.infrastructure.qdrant_law_index import DOC_TYPE_VALUES


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
def test_enrichment_fields_are_the_four_indexed_classifications() -> None:
    assert ENRICHMENT_FIELDS == ("norm_type", "scope", "direction", "sanctions")
    assert ENRICHMENT_FIELD_KINDS["direction"] == "scalar"
    assert ENRICHMENT_FIELD_KINDS["norm_type"] == "array"
    assert set(ENRICHMENT_FIELD_KINDS) == set(ENRICHMENT_FIELDS)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Duty", "duty"),
        ("  Regulamentar ", "regulamentar"),
        ("Administração Pública", "administracao_publica"),
        ("probidad-administrativa", "probidad_administrativa"),
        ("isenção", "isencao"),
        ("OBLIGATION", "obligation"),
    ],
)
def test_fold_token_removes_accents_case_and_separator_noise(raw: str, expected: str) -> None:
    assert fold_token(raw) == expected


def test_fold_token_is_idempotent_on_a_canonical_token() -> None:
    for tokens in ENRICHMENT_VOCABULARY.values():
        for token in tokens:
            assert fold_token(token) == token


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("norm_type", "duty", "duty"),
        ("norm_type", "dever", "duty"),
        ("norm_type", "Prohibition", "prohibition"),
        ("norm_type", "proibicao", "prohibition"),
        ("norm_type", "processual", "procedural"),
        ("scope", "regulamentar", "regulatory"),
        ("scope", "administrativo", "administrative"),
        ("direction", "obligation", "mandatory"),
        ("direction", "proibido", "prohibitive"),
        ("direction", "prohibido", "prohibitive"),
        ("direction", "vedado", "prohibitive"),
        ("sanctions", "multa", "financial_penalty"),
        ("sanctions", "fine", "financial_penalty"),
        ("sanctions", "responsabilidade_criminal", "criminal_liability"),
    ],
)
def test_normalize_token_maps_an_alias_onto_the_canonical_token(
    field: str, raw: str, expected: str
) -> None:
    token, known = normalize_token(field, raw)

    assert token == expected
    assert known is True


def test_every_alias_key_is_folded_and_every_value_is_canonical() -> None:
    # The table is consulted with a folded lookup, so an unfolded key can never
    # match — it is dead weight that reads as a real alias.
    for field, aliases in _ENRICHMENT_ALIASES.items():
        canonical = set(ENRICHMENT_VOCABULARY[field])
        for key, value in aliases.items():
            assert fold_token(key) == key, f"{field}: alias key {key!r} is not folded"
            assert value in canonical, f"{field}: alias {key!r} points outside the vocabulary"


def test_normalize_token_folds_and_flags_a_token_outside_the_vocabulary() -> None:
    token, known = normalize_token("norm_type", "Probidad Administrativa")

    # Kept — a missing concept is information — but flagged as unknown.
    assert token == "probidad_administrativa"
    assert known is False


def test_normalize_token_treats_a_blank_token_as_known_and_empty() -> None:
    assert normalize_token("norm_type", "   ") == ("", True)


def test_normalize_value_collapses_duplicates_after_normalisation() -> None:
    value, renames, unknown = normalize_value("norm_type", ["dever", "duty", " DUTY "])

    assert value == ["duty"]
    assert unknown == []


def test_normalize_value_wraps_a_bare_string_for_an_array_field() -> None:
    value, renames, unknown = normalize_value("sanctions", "multa")

    assert value == ["financial_penalty"]
    assert renames == [{"from": "multa", "to": "financial_penalty"}]
    assert unknown == []


def test_normalize_value_reports_every_token_it_rewrote() -> None:
    value, renames, unknown = normalize_value("scope", ["regulamentar", "probidad"])

    assert value == ["regulatory", "probidad"]
    assert renames == [{"from": "regulamentar", "to": "regulatory"}]
    assert unknown == ["probidad"]


def test_normalize_value_keeps_null_for_the_scalar_field() -> None:
    assert normalize_value("direction", None) == (None, [], [])


def test_normalize_value_passes_a_non_string_through_untouched() -> None:
    # Type rejection belongs to the payload validator, not to the vocabulary:
    # stringifying would turn 7 into a token that looks deliberate.
    assert normalize_value("norm_type", [7]) == ([7], [], [])


def test_vocabulary_block_covers_only_the_requested_fields() -> None:
    block = vocabulary_block(["direction"])

    assert "### `direction`" in block
    assert "### `norm_type`" not in block
    # The rules and the token list both reach the model.
    assert "Controlled vocabulary" in block
    assert "`prohibitive`" in block


def test_vocabulary_block_is_empty_when_nothing_is_in_scope() -> None:
    assert vocabulary_block([]) == ""
    assert vocabulary_block(["theme"]) == ""


def test_vocabulary_block_offers_doc_type_its_own_taxonomy() -> None:
    """``doc_type`` is not an enrichment field, so it carries its own rules.

    Without this block the model had no token to propose for ``doc_type`` and
    correctly declined the field — the field was in scope but unanswerable.
    """
    block = vocabulary_block(["doc_type"])

    assert "### `doc_type`" in block
    assert "Controlled vocabulary" in block
    for token in DOC_TYPE_VALUES:
        assert f"`{token}`" in block
    for rule in DOC_TYPE_RULES:
        assert rule in block
    # Every advertised token is glossed, so the list reads as a taxonomy.
    assert set(DOC_TYPE_GLOSSARY) == set(DOC_TYPE_VALUES)
    # The enrichment fields are not dragged in by association.
    assert "### `norm_type`" not in block


def test_vocabulary_block_omits_doc_type_unless_it_is_reviewed() -> None:
    assert "doc_type" not in vocabulary_block(["norm_type"])
    assert "doc_type" not in vocabulary_block([])


def test_vocabulary_block_combines_enrichment_and_doc_type() -> None:
    block = vocabulary_block(["sanctions", "doc_type", "title"])

    assert "### `sanctions`" in block
    assert "### `doc_type`" in block
    assert "### `scope`" not in block
    assert "### `title`" not in block


def test_vocabulary_block_accepts_any_iterable_of_the_same_fields() -> None:
    # The router passes a list; the helper must not consume a generator twice.
    assert vocabulary_block(iter(["direction"])) == vocabulary_block(["direction"])


def test_taxonomy_fields_are_the_enrichment_fields_plus_doc_type() -> None:
    assert (*ENRICHMENT_FIELDS, "doc_type") == TAXONOMY_FIELDS


def test_every_taxonomy_field_is_fully_described() -> None:
    # Rules, tokens and meanings for every field, so the prompt and the report
    # can share one loop without a per-field special case.
    for field in TAXONOMY_FIELDS:
        assert rules_for(field), field
        assert vocabulary_for(field), field
        assert set(glossary_for(field)) == set(vocabulary_for(field)), field
        assert kind_for(field) in {"array — one or more tokens", "single token or null"}


def test_rules_for_matches_the_table_the_prompt_offers() -> None:
    for field in ENRICHMENT_FIELDS:
        assert rules_for(field) == ENRICHMENT_RULES[field]
    assert rules_for("doc_type") == DOC_TYPE_RULES
    # A field without a taxonomy is empty rather than a KeyError: the report
    # renders metadata fields too, and it must not explode on them.
    assert rules_for("title") == ()
    assert vocabulary_for("title") == ()
    assert glossary_for("title") == {}


def test_enrichment_glossary_and_field_kinds_cover_the_same_fields() -> None:
    assert set(ENRICHMENT_GLOSSARY) == set(ENRICHMENT_FIELDS)
    for field, meanings in ENRICHMENT_GLOSSARY.items():
        assert set(meanings) == set(ENRICHMENT_VOCABULARY[field]), field


# ---------------------------------------------------------------------------
# Report names and paths
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("original_id", "expected"),
    [
        ("CL.DFL1_19653.T3.Art.52", "CL.DFL1_19653.T3.Art.52"),
        ("BR L1/C1 Art.1", "BR-L1-C1-Art.1"),
        ("../../etc/passwd", "etc-passwd"),
        ("", "article"),
    ],
)
def test_report_slug_stays_inside_the_report_directory(original_id: str, expected: str) -> None:
    slug = report_slug(original_id)

    assert slug == expected
    assert "/" not in slug
    assert ".." not in slug


def test_report_paths_live_under_the_mapping_directory(tmp_path: Path) -> None:
    json_path, md_path = report_paths(tmp_path, "BR.L1.C1.Art.1")

    assert json_path == tmp_path / "_mapping" / REPORT_SUBDIR / "BR.L1.C1.Art.1.json"
    assert md_path == json_path.with_suffix(".md")


@pytest.mark.parametrize(
    ("name", "accepted"),
    [
        ("BR.L1.C1.Art.1.md", True),
        ("notes-2026_01.md", True),
        ("notes.txt", False),
        ("../secrets.md", False),
        ("", False),
        ("sub/dir.md", False),
    ],
)
def test_is_report_name_rejects_anything_but_a_plain_markdown_file(name: str, accepted: bool) -> None:
    assert is_report_name(name) is accepted


# ---------------------------------------------------------------------------
# Rendering and round-trip
# ---------------------------------------------------------------------------
RECORD: dict[str, object] = {
    "original_id": "BR.L1.C1.Art.1",
    "collection": "transcription_law",
    "title": "Art. 1 — Alpha",
    "source_path": "BR/L1.md",
    "generated_at": "2026-01-01T00:00:00+00:00",
    "model": "stub-model",
    "fields_reviewed": ["norm_type", "scope", "direction", "sanctions", "theme"],
    "summary": "Nothing recorded yet.",
    "suggestions": [
        {
            "field": "norm_type",
            "current": [],
            "suggested": ["duty"],
            "rationale": "the article commands conduct",
            "justification": "The addressee shall observe the duty.",
            "evidence": "deverá observar",
            "confidence": "high",
            "normalized_from": [{"from": "dever", "to": "duty"}],
            "unknown_tokens": ["probidad"],
            "vocabulary": "proposal",
        }
    ],
    "dropped": 3,
    "current": {"norm_type": [], "scope": [], "direction": None, "sanctions": []},
    "decision_logic": {"norm_type": "A principle that commands is both."},
}


def test_render_report_has_the_four_fixed_sections_in_order() -> None:
    report = render_report(RECORD)
    headings = [
        "## 🧭 Proposed Field Populations",
        "## 📋 Detailed Justification",
        "## 🧩 Baseline for Other Articles",
        "## ✅ Applied Updates",
    ]

    positions = [report.index(heading) for heading in headings]

    assert positions == sorted(positions)


def test_render_report_tabulates_the_proposals() -> None:
    report = render_report(RECORD)

    assert "| Field | Proposed Value | Rationale |" in report
    assert "| `norm_type` | `duty` | the article commands conduct |" in report
    assert "**Vocabulary normalisation:** `dever` → `duty`" in report
    assert "**New tokens (not in the controlled vocabulary):** `probidad`" in report
    assert "> deverá observar" in report
    assert "_3 proposal(s) discarded by the validator before reaching this report._" in report


def test_render_report_marks_a_field_with_no_proposal_as_unchanged() -> None:
    report = render_report(RECORD)

    # ``sanctions`` was reviewed and had nothing to say.
    sanctions = report.split("### `sanctions`")[1].split("## ")[0]
    assert "**Proposed:** unchanged" in sanctions


def test_render_report_escapes_pipes_so_a_table_cannot_break() -> None:
    record = dict(RECORD)
    record["suggestions"] = [
        {
            "field": "theme",
            "current": "A",
            "suggested": "B | C",
            "rationale": "line one\nline two",
            "confidence": "low",
        }
    ]
    record["fields_reviewed"] = ["theme"]

    report = render_report(record)

    assert r"\|" in report
    assert "line one line two" in report


def test_render_report_says_so_when_nothing_is_proposed() -> None:
    report = render_report({**RECORD, "suggestions": [], "dropped": 0})

    assert "_Nothing to propose — the payload already agrees with the source._" in report
    assert "_Nothing has been written yet._" in report


def test_render_report_justifies_doc_type_like_any_other_field() -> None:
    """A ``doc_type`` proposal must reach the prose sections, not just the table.

    Sections 2 and 3 used to iterate the enrichment fields only, so a
    ``doc_type`` suggestion appeared in the summary table and then vanished —
    the justification the model wrote was captured in the JSON and discarded at
    render time.
    """
    record: dict[str, object] = {
        **RECORD,
        "fields_reviewed": ["doc_type", "theme"],
        "current": {"doc_type": "unknown"},
        "decision_logic": {"doc_type": "Read the instrument name from the header."},
        "suggestions": [
            {
                "field": "doc_type",
                "current": "unknown",
                "suggested": "Convention",
                "rationale": "the header names the Montreal Convention",
                "justification": "The instrument is the Montreal Convention, a treaty.",
                "evidence": "### Art. 5 — Convenio de Montreal",
                "confidence": "high",
            }
        ],
    }

    report = render_report(record)

    assert "| `doc_type` | `Convention` | the header names the Montreal Convention |" in report
    justification = report.split("## 📋 Detailed Justification")[1].split("## 🧩")[0]
    assert "### `doc_type`" in justification
    assert "**Proposed:** `Convention`" in justification
    assert "**Confidence:** `high`" in justification
    assert "The instrument is the Montreal Convention, a treaty." in justification
    baseline = report.split("## 🧩 Baseline for Other Articles")[1]
    assert "### `doc_type`" in baseline
    assert DOC_TYPE_RULES[0] in baseline
    assert "Read the instrument name from the header." in baseline
    assert "were not in scope" not in baseline


def test_render_report_keeps_a_declined_classification_field_in_the_baseline() -> None:
    record: dict[str, object] = {
        **RECORD,
        "fields_reviewed": ["doc_type"],
        "suggestions": [],
        "dropped": 0,
        "decision_logic": {},
    }

    report = render_report(record)

    # The rules stay: a baseline is what the reviewer should apply next time,
    # whether or not this article needed them.
    declared = report.split("### `doc_type`")[1].split("## ")[0]
    assert "**Proposed:** unchanged" in declared
    assert DOC_TYPE_RULES[0] in report


def test_render_report_justifies_a_proposed_metadata_field() -> None:
    """Metadata has no taxonomy, but a proposal's prose is never dropped."""
    record: dict[str, object] = {
        **RECORD,
        "fields_reviewed": ["title", "theme"],
        "decision_logic": {},
        "suggestions": [
            {
                "field": "title",
                "current": "Art. 1",
                "suggested": "Art. 1 — Duty to observe",
                "rationale": "the article titles itself",
                "justification": "The heading supplies the title verbatim.",
                "confidence": "medium",
            }
        ],
    }

    report = render_report(record)

    justification = report.split("## 📋 Detailed Justification")[1].split("## 🧩")[0]
    assert "### `title`" in justification
    assert "The heading supplies the title verbatim." in justification
    # `title` carries no reusable rules, so it stays out of the baseline — and
    # the fallback names the reason instead of claiming the field is absent.
    baseline = report.split("## 🧩 Baseline for Other Articles")[1]
    assert "### `title`" not in baseline
    assert "_The classification fields were not in scope for this review._" in baseline


def test_write_load_and_list_round_trip(tmp_path: Path) -> None:
    md_path = write_report(tmp_path, RECORD)

    assert md_path.read_text(encoding="utf-8") == render_report(RECORD)
    assert load_record(tmp_path, "BR.L1.C1.Art.1") == json.loads(json.dumps(RECORD, default=str))
    listing = list_reports(tmp_path)

    assert len(listing) == 1
    assert listing[0]["name"] == "BR.L1.C1.Art.1.md"
    assert listing[0]["suggestions"] == 1
    assert listing[0]["applied"] == 0


def test_list_reports_is_empty_before_anything_is_saved(tmp_path: Path) -> None:
    assert list_reports(tmp_path) == []
    assert load_record(tmp_path, "BR.L1.C1.Art.1") is None


def test_load_record_tolerates_a_corrupt_json_file(tmp_path: Path) -> None:
    json_path, _ = report_paths(tmp_path, "BR.L1.C1.Art.1")
    json_path.parent.mkdir(parents=True)
    json_path.write_text("{not json", encoding="utf-8")

    assert load_record(tmp_path, "BR.L1.C1.Art.1") is None
    # A corrupt source of truth must not make the listing raise.
    assert list_reports(tmp_path) == []


def test_record_applied_appends_the_rows_and_returns_the_markdown(tmp_path: Path) -> None:
    write_report(tmp_path, RECORD)

    md_path = record_applied(
        tmp_path,
        "BR.L1.C1.Art.1",
        [{"field": "norm_type", "from": [], "to": ["duty"]}],
        timestamp="2026-02-02T02:02:02+00:00",
    )

    assert md_path is not None
    stored = load_record(tmp_path, "BR.L1.C1.Art.1")
    assert stored is not None
    assert stored["applied"] == [{"at": "2026-02-02T02:02:02+00:00", "field": "norm_type", "from": [], "to": ["duty"]}]
    assert "| 2026-02-02T02:02:02+00:00 | `norm_type` | _(none)_ | `duty` |" in md_path.read_text(encoding="utf-8")


def test_record_applied_is_a_noop_without_a_report_or_rows(tmp_path: Path) -> None:
    assert record_applied(tmp_path, "BR.L1.C1.Art.1", [{"field": "theme", "from": "a", "to": "b"}]) is None

    write_report(tmp_path, RECORD)
    assert record_applied(tmp_path, "BR.L1.C1.Art.1", []) is None
