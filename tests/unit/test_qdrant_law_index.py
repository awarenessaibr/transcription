"""Unit tests for the law corpus index (``src.infrastructure.qdrant_law_index``).

Everything here runs offline: the Qdrant client is replaced by a recording
stub, and the embedding model is monkeypatched, so no network or model download
is required.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from qdrant_client.http import models as qm

from src.infrastructure.qdrant_law_index import (
    _TAG_KEY_ALIASES,
    CANONICAL_DENSE_DIM,
    LOCAL_DENSE_DIM,
    LOCAL_PAYLOAD_INDEX_FIELDS,
    PAYLOAD_TARGET_LOCAL,
    RECORD_KIND_ARTICLE,
    RECORD_KIND_REFERENCE,
    SCHEMA_VERSION,
    VOLATILE_PAYLOAD_KEYS,
    CanonicalLawIngester,
    CorpusPlan,
    IngestStats,
    LawArticle,
    LawCorpusParser,
    LocalLawIngester,
    QdrantLawIndex,
    _fold_tag_label,
    article_number_for,
    default_law_dir,
    diff_payloads,
    doc_type_for,
    language_for_path,
    localized_point_id,
    normalize_content,
    normalize_qdrant_api_key,
    normalize_qdrant_url,
    parse_article_blocks,
    parse_article_tags,
    placeholder_dense_vector,
    point_id_for,
    sha256_short,
    split_eli,
    stable_point_id,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

BR_FILE = """\
# Lei 1

### Art. 1 — Alpha

**Theme:** Tema A
**ELI ID:** `BR.L1.C1.Art.1`
**Tags:** norm_type: duty · scope: regulatory

Alpha body.

---

### Art. 2 — Beta
**Theme:** Tema B
**ELI ID:** `BR.L1.C1.Art.2`
**Tags:** norm_type: procedural · scope: regulatory

Beta body.

---
"""

CL_FILE = """\
### Art. 224 — Gamma

**Tema:** Tema C
**ID ELI:** `CL.CL1.Art.224`
**Etiquetas:** norm_type: right

Gamma body.

---
"""

INT_BR_FILE = """\
### Art. 5 — X

**Tema:** Portuguese theme
**ELI ID:** `INT.TX.Art.5`
**Etiquetas:** norm_type: duty

Corpo em português.

---
"""

INT_EN_FILE = """\
### Art. 5 — X

**Theme:** English theme
**ELI ID:** `INT.TX.Art.5`
**Tags:** norm_type: duty

English body.

---
"""

CODE_FILE = """\
# Code of Ethics

We promise to behave.
"""

MAPPING_FILE = """\
### Art. 999 — Not a real article

**ELI ID:** `XX.YY.Art.999`

nope
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """A miniature law corpus covering every parsing branch."""
    root = tmp_path / "law"
    _write(root / "BR" / "L1.md", BR_FILE)
    _write(root / "CL" / "CL1.md", CL_FILE)
    _write(root / "INT" / "BR" / "TX.md", INT_BR_FILE)
    _write(root / "INT" / "EN" / "TX.md", INT_EN_FILE)
    _write(root / "CORP" / "CODE.md", CODE_FILE)
    _write(root / "_mapping" / "LAW_REGISTRY.md", MAPPING_FILE)
    return root


class StubQdrantClient:
    """Records every write; never talks to a server."""

    def __init__(self, records: list[qm.Record] | None = None) -> None:
        self.records = records or []
        self.payload_calls: list[dict[str, Any]] = []
        self.upserts: list[tuple[str, list[qm.PointStruct]]] = []
        self.created_collections: list[str] = []
        self.deleted_collections: list[str] = []
        self.payload_indexes: list[tuple[str, str]] = []
        self._existing: set[str] = set()

    # -- reads -------------------------------------------------------------
    def scroll(self, **kwargs: Any) -> tuple[list[qm.Record], None]:
        assert kwargs.get("with_vectors") is False, "scroll() must use with_vectors=False"
        return list(self.records), None

    def count(self, collection_name: str, exact: bool = True) -> SimpleNamespace:
        return SimpleNamespace(count=len(self.records))

    # -- writes ------------------------------------------------------------
    def set_payload(self, **kwargs: Any) -> None:
        self.payload_calls.append(kwargs)

    def upsert(self, collection_name: str, points: list[qm.PointStruct], wait: bool = True) -> None:
        self.upserts.append((collection_name, points))

    # -- collection lifecycle ---------------------------------------------
    def collection_exists(self, name: str) -> bool:
        return name in self._existing

    def create_collection(self, collection_name: str, vectors_config: Any = None) -> None:
        self._existing.add(collection_name)
        self.created_collections.append(collection_name)

    def create_payload_index(self, **kwargs: Any) -> None:
        self.payload_indexes.append((kwargs["collection_name"], kwargs["field_name"]))

    def delete_collection(self, name: str) -> None:
        self._existing.discard(name)
        self.deleted_collections.append(name)


def _article(original_id: str, **overrides: Any) -> LawArticle:
    defaults: dict[str, Any] = {
        "original_id": original_id,
        "title": "Art. 1 — Title",
        "theme": "Theme",
        "tags": "norm_type: duty",
        "content": "Body text.",
        "source_file": "L1.md",
        "source_path": "/tmp/law/BR/L1.md",
        "jurisdiction": split_eli(original_id)[0],
        "framework_code": split_eli(original_id)[1],
        "language": "pt",
        "doc_type": doc_type_for(split_eli(original_id)[1]),
    }
    defaults.update(overrides)
    return LawArticle(**defaults)


# ---------------------------------------------------------------------------
# Block parsing
# ---------------------------------------------------------------------------
def test_parse_article_blocks_handles_blank_and_inline_metadata() -> None:
    blocks = list(parse_article_blocks(BR_FILE))

    assert len(blocks) == 2
    title, metadata, body = blocks[0]
    assert title == "Art. 1 — Alpha"
    assert "**ELI ID:** `BR.L1.C1.Art.1`" in metadata
    assert body.strip() == "Alpha body.\n\n---"


def test_parse_article_blocks_inline_variant_keeps_body_clean() -> None:
    """Metadata immediately after the heading must not leak into the body."""
    _title, metadata, body = list(parse_article_blocks(BR_FILE))[1]

    assert "**Theme:** Tema B" in metadata
    assert body.lstrip().startswith("Beta body.")


def test_parse_article_blocks_ignores_non_heading_text() -> None:
    assert list(parse_article_blocks("# Just a title\n\nno articles here")) == []


def test_parse_article_blocks_level4_heading_is_not_a_block() -> None:
    text = "#### Not an article\n**ELI ID:** `X.Y.Art.1`\n"
    assert list(parse_article_blocks(text)) == []


# ---------------------------------------------------------------------------
# Tag classification
# ---------------------------------------------------------------------------
def test_parse_article_tags_reads_english_keys() -> None:
    tags = parse_article_tags("**Tags:** norm_type: duty · scope: regulatory\n")

    assert tags["norm_type"] == ["duty"]
    assert tags["scope"] == ["regulatory"]
    assert tags["tags"] == ["norm_type: duty", "scope: regulatory"]


def test_parse_article_tags_reads_portuguese_aliases() -> None:
    tags = parse_article_tags("**Etiquetas:** tipo_norma: dever · escopo: constitucional\n")

    assert tags["norm_type"] == ["dever"]
    assert tags["scope"] == ["constitucional"]


@pytest.mark.parametrize("key", ["âmbito", "ambito", "ÁMBITO", "Escopo", "escopo", "alcance"])
def test_parse_article_tags_folds_scope_aliases(key: str) -> None:
    assert parse_article_tags(f"**Etiquetas:** {key}: penal\n")["scope"] == ["penal"]


def test_parse_article_tags_splits_multi_valued_tokens() -> None:
    tags = parse_article_tags("**Tags:** norm_type: duty, penalty · sanctions: fine\n")

    assert tags["norm_type"] == ["duty", "penalty"]
    assert tags["sanctions"] == ["fine"]


def test_parse_article_tags_splits_comma_separated_tokens() -> None:
    tags = parse_article_tags("**Tags:** norm_type: duty, scope: state\n")

    assert tags["norm_type"] == ["duty"]
    assert tags["scope"] == ["state"]


def test_parse_article_tags_reads_inline_pipe_style() -> None:
    block = "**Norm type:** procedure | **Direction:** mandatory | **Scope:** administrative\n"
    tags = parse_article_tags(block)

    assert tags["norm_type"] == ["procedure"]
    assert tags["direction"] == "mandatory"
    assert tags["scope"] == ["administrative"]
    # Regression: a ``**Tags:**``-only parser leaves this empty, which the
    # earlier proposal did even though its own contract required tags.
    assert tags["tags"] == ["norm_type: procedure", "direction: mandatory", "scope: administrative"]


def test_parse_article_tags_ignores_unrelated_metadata_fields() -> None:
    tags = parse_article_tags("**Theme:** Tema A\n**ELI ID:** `BR.L1.C1.Art.1`\n")

    assert tags == {"norm_type": [], "scope": [], "direction": None, "sanctions": [], "tags": []}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("eli", "expected"),
    [
        ("BR.CBA.T7.C1.Art.224", ("BR", "CBA")),
        ("CL.CONST.T1.Art.5", ("CL", "CONST")),
        ("INT.DOC4444.C15.Art.1", ("INT", "DOC4444")),
        ("BROKEN", ("BROKEN", "")),
    ],
)
def test_split_eli(eli: str, expected: tuple[str, str]) -> None:
    assert split_eli(eli) == expected


@pytest.mark.parametrize(
    ("eli", "expected"),
    [
        ("BR.CBA.T7.C1.Art.224", "224"),
        ("BR.CBA.T3.C1.Art.74", "74"),
        ("CL.CONST.T1.C3.P7.Art.19.7", "19.7"),
        ("INT.DOC4444.C15.S1.P2.Art.15.1.2", "15.1.2"),
        # No ``Art.`` token at all -> last segment, never the jurisdiction.
        # Naive splitting returns "BR" for these, which is how the earlier
        # proposal collided 25 articles onto a single id.
        ("BR.ABEAR_COC.SA.I", "I"),
        ("BR.D1171.Anexo.C1.S1.I", "I"),
        ("BROKEN", "BROKEN"),
    ],
)
def test_article_number_for(eli: str, expected: str) -> None:
    assert article_number_for(eli) == expected


@pytest.mark.parametrize(
    ("framework", "expected"),
    [
        ("ABEAR_PAC", "Internal"),
        ("ABEARPIAP", "Internal"),
        ("AN14", "ICAO"),
        ("AN9", "ICAO"),
        ("DOC4444", "ICAO"),
        ("R400", "Resolution"),
        ("R123", "Resolution"),
        ("CDC", "CDC"),
        ("L12813", "unknown"),
        ("D7724", "unknown"),
        ("CBA", "unknown"),
        ("", "unknown"),
    ],
)
def test_doc_type_for(framework: str, expected: str) -> None:
    assert doc_type_for(framework) == expected


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("data/law/BR/L1.md", "pt"),
        ("data/law/CL/L1.md", "es"),
        ("data/law/CORP/CODE.md", "en"),
        ("data/law/INT/BR/TX.md", "pt"),
        ("data/law/INT/EN/TX.md", "en"),
        ("data/law/INT/ES/TX.md", "es"),
    ],
)
def test_language_for_path(rel: str, expected: str) -> None:
    root = Path("data/law")
    assert language_for_path(Path(rel), root) == expected


def test_normalize_content_keeps_separator_by_default() -> None:
    raw = "\n\nBody text.\n\n---\n"
    assert normalize_content(raw) == "Body text.\n\n---"
    assert normalize_content(raw, keep_separator=False) == "Body text."


def test_normalize_content_is_idempotent() -> None:
    once = normalize_content("Body.\n\n---", keep_separator=False)
    assert normalize_content(once, keep_separator=False) == once


def test_sha256_short_is_stable() -> None:
    assert sha256_short("abc", 8) == sha256_short("abc", 8)
    assert len(sha256_short("abc", 8)) == 8


# ---------------------------------------------------------------------------
# Point IDs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("eli", "expected"),
    [
        # Verified against the live production collection (la8159_law).
        ("BR.CBA.T7.C1.Art.224", "0151cad0-fe68-5505-b3ca-47cd9c47af81"),
        ("INT.DOC4444.C15.S1.P2.Art.15.1.2", "e3ad7a74-e305-57cf-a57d-5175c1d9a3b6"),
        ("CL.CONST.T1.C3.P7.Art.19.7", "0077f180-961b-5c77-a350-5066b30b56cf"),
    ],
)
def test_stable_point_id_matches_production(eli: str, expected: str) -> None:
    assert stable_point_id(eli) == expected
    assert stable_point_id(eli) == str(uuid.uuid5(uuid.NAMESPACE_DNS, eli))


def test_localized_point_id_is_language_qualified() -> None:
    eli = "INT.TX.Art.5"
    assert localized_point_id(eli, "pt") != localized_point_id(eli, "en")
    assert localized_point_id(eli, "pt") != stable_point_id(eli)
    assert localized_point_id(eli, "pt") == localized_point_id(eli, "pt")


def test_placeholder_dense_vector_is_deterministic_and_normalized() -> None:
    vector = placeholder_dense_vector("BR.L1.C1.Art.1", CANONICAL_DENSE_DIM)

    assert len(vector) == CANONICAL_DENSE_DIM
    assert vector == placeholder_dense_vector("BR.L1.C1.Art.1", CANONICAL_DENSE_DIM)
    assert vector != placeholder_dense_vector("BR.L1.C1.Art.2", CANONICAL_DENSE_DIM)
    assert sum(v * v for v in vector) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# payload shape
# ---------------------------------------------------------------------------
def test_to_payload_matches_production_schema() -> None:
    article = _article("BR.L1.C1.Art.1")
    payload = article.to_payload(article.point_id, ingestion_time="2026-01-01T00:00:00")

    assert set(payload["original_data"]) == {
        "id",
        "title",
        "source_file",
        "theme",
        "tags",
        "content",
        "original_id",
    }
    assert payload["original_data"]["id"] == article.point_id
    assert payload["metadata"] == {
        "data_type": "law",
        "doc_type": "unknown",
        "ingestion_time": "2026-01-01T00:00:00",
    }
    assert payload["doc_type"] == payload["metadata"]["doc_type"]
    assert payload["text"] == payload["content"] == article.content
    assert payload["original_id"] == "BR.L1.C1.Art.1"
    # framework fields are BM25-only, extras are local-only
    assert "framework_code" not in payload
    assert "language" not in payload


def test_to_payload_optional_fields() -> None:
    article = _article("INT.TX.Art.5", language="en", framework_code="TX", jurisdiction="INT")
    payload = article.to_payload(
        article.point_id,
        include_framework_fields=True,
        include_extra=True,
        ingestion_time="t",
    )

    assert payload["framework_code"] == "TX"
    assert payload["jurisdiction"] == "INT"
    assert payload["language"] == "en"
    assert payload["sha256_short"] == article.sha256_short


def test_embed_text_includes_title_theme_and_body() -> None:
    article = _article("BR.L1.C1.Art.1", title="Art. 1 — T", theme="Th", content="Body.")
    text = article.embed_text()

    assert text.startswith("Art. 1 — T — Th")
    assert text.endswith("Body.")


def test_canonical_payload_change_is_additive_only() -> None:
    """Sibling projects read this shape; existing keys must keep their meaning."""
    article = _article("BR.L1.C1.Art.1")
    payload = article.to_payload(
        article.point_id,
        include_framework_fields=True,
        include_extra=True,
        ingestion_time="t",
    )

    assert set(payload["original_data"]) == {
        "id",
        "title",
        "source_file",
        "theme",
        "tags",
        "content",
        "original_id",
    }
    assert payload["tags"] == "norm_type: duty"  # still a display string
    assert payload["metadata"]["ingestion_time"] == "t"
    assert payload["doc_type"] == "unknown"  # NOT re-purposed as a record kind

    assert payload["eli_id"] == payload["original_id"] == "BR.L1.C1.Art.1"
    assert payload["article_number"] == "1"
    assert payload["record_kind"] == RECORD_KIND_ARTICLE
    assert payload["schema_version"] == SCHEMA_VERSION


def test_canonical_stamp_stays_naive_utc() -> None:
    """``metadata.ingestion_time`` must not gain a ``Z`` mid-migration."""
    article = _article("BR.L1.C1.Art.1")
    ingestion_time = article.to_payload(article.point_id)["metadata"]["ingestion_time"]

    assert not ingestion_time.endswith("Z")
    assert "+" not in ingestion_time


def test_local_payload_is_schema_v1() -> None:
    article = _article(
        "BR.L1.C1.Art.1",
        norm_type=("duty",),
        scope=("regulatory",),
        direction="mandatory",
        sanctions=("fine",),
        tag_tokens=("norm_type: duty",),
    )
    payload = article.to_payload(article.point_id, target=PAYLOAD_TARGET_LOCAL, ingestion_time="t")

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["original_id"] == payload["eli_id"] == "BR.L1.C1.Art.1"
    assert payload["article_number"] == "1"
    assert payload["record_kind"] == RECORD_KIND_ARTICLE
    assert payload["norm_type"] == ["duty"]
    assert payload["scope"] == ["regulatory"]
    assert payload["direction"] == "mandatory"
    assert payload["sanctions"] == ["fine"]
    assert payload["tags"] == ["norm_type: duty"]  # a list, not a display string
    assert payload["content"] == payload["text"] == article.content
    assert payload["source_sha256"] == article.sha256_full
    assert len(payload["source_sha256"]) == 64
    assert payload["ingested_at"] == payload["updated_at"] == "t"
    assert payload["doc_type"] == "unknown"  # unchanged by decision
    assert payload["data_type"] == "law"
    # local drops the canonical-only duplication
    assert "original_data" not in payload
    assert "metadata" not in payload
    assert "sha256_short" not in payload


def test_local_payload_default_stamp_carries_z() -> None:
    article = _article("BR.L1.C1.Art.1")
    payload = article.to_payload(article.point_id, target=PAYLOAD_TARGET_LOCAL)

    assert payload["ingested_at"].endswith("Z")
    assert payload["updated_at"] == payload["ingested_at"]


def test_reference_only_article_is_marked() -> None:
    article = _article("BR.L1.C1.Art.1", reference_only=True)
    payload = article.to_payload(article.point_id, target=PAYLOAD_TARGET_LOCAL, ingestion_time="t")

    assert payload["record_kind"] == RECORD_KIND_REFERENCE
    assert payload["reference_only"] is True


def test_payload_target_must_be_known() -> None:
    article = _article("BR.L1.C1.Art.1")

    with pytest.raises(ValueError, match="unknown payload target"):
        article.to_payload(article.point_id, target="staging")


def test_eli_id_and_article_number_default_from_original_id() -> None:
    article = _article("INT.DOC4444.C15.S1.P2.Art.15.1.2")

    assert article.eli_id == "INT.DOC4444.C15.S1.P2.Art.15.1.2"
    assert article.article_number == "15.1.2"


def test_local_ingest_writes_schema_v1_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    client = StubQdrantClient()
    ingester = LocalLawIngester(client, collection="transcription_law")
    monkeypatch.setattr(ingester, "_embed", lambda texts: [[0.1] * LOCAL_DENSE_DIM for _ in texts])

    ingester.ingest([_article("BR.L1.C1.Art.1")])

    payload = client.upserts[0][1][0].payload
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["ingested_at"].endswith("Z")
    assert "original_data" not in payload


# ---------------------------------------------------------------------------
# Payload diffing (migration planning)
# ---------------------------------------------------------------------------
def test_diff_payloads_reports_added_removed_and_changed() -> None:
    live = {"original_id": "BR.L1.C1.Art.1", "tags": "norm_type: duty", "original_data": {"id": "x"}}
    wanted = {"original_id": "BR.L1.C1.Art.1", "tags": ["norm_type: duty"], "eli_id": "BR.L1.C1.Art.1"}

    diff = diff_payloads(live, wanted)

    assert diff.added == ("eli_id",)
    assert diff.removed == ("original_data",)
    assert diff.changed == ("tags",)
    assert diff.unchanged == ("original_id",)


def test_diff_payloads_reports_a_new_timestamp_key_as_added() -> None:
    """A brand-new volatile key is real structure, so it must still show up."""
    diff = diff_payloads({"original_id": "X"}, {"original_id": "X", "ingested_at": "2026-01-01T00:00:00Z"})

    assert diff.added == ("ingested_at",)
    assert diff.changed == ()


def test_diff_payloads_ignores_a_shifted_timestamp_value() -> None:
    live = {"original_id": "X", "ingested_at": "2026-01-01T00:00:00Z"}
    wanted = {"original_id": "X", "ingested_at": "2026-06-01T00:00:00Z"}

    diff = diff_payloads(live, wanted)

    assert diff.changed == ()
    assert diff.added == ()
    assert diff.removed == ()


def test_diff_payloads_ignores_metadata_ingestion_time() -> None:
    live = {"metadata": {"data_type": "law", "ingestion_time": "2026-01-01T00:00:00"}}
    wanted = {"metadata": {"data_type": "law", "ingestion_time": "2026-06-01T00:00:00"}}

    diff = diff_payloads(live, wanted)

    assert diff.changed == ()


def test_diff_payloads_still_sees_other_metadata_changes() -> None:
    live = {"metadata": {"data_type": "law", "doc_type": "unknown"}}
    wanted = {"metadata": {"data_type": "law", "doc_type": "CDC"}}

    diff = diff_payloads(live, wanted)

    assert diff.changed == ("metadata",)


def test_diff_payloads_byte_delta_is_signed() -> None:
    shrinks = diff_payloads({"a": "x" * 50, "b": 1}, {"a": "x" * 10})
    grows = diff_payloads({"a": "x" * 10}, {"a": "x" * 50, "b": 1})

    assert shrinks.byte_delta < 0
    assert grows.byte_delta > 0
    assert shrinks.byte_delta == -grows.byte_delta
    assert shrinks.live_bytes > shrinks.wanted_bytes


def test_payload_diff_as_dict_is_json_ready() -> None:
    diff = diff_payloads({"a": 1}, {"a": 2, "b": 3})

    assert diff.as_dict() == {
        "added": ["b"],
        "removed": [],
        "changed": ["a"],
        "unchanged": [],
        "byte_delta": diff.byte_delta,
        "live_bytes": diff.live_bytes,
        "wanted_bytes": diff.wanted_bytes,
    }
    assert diff.touched == ("a", "b")


def test_payload_diff_of_identical_payloads_is_empty() -> None:
    payload = {"a": 1, "b": [1, 2]}

    diff = diff_payloads(payload, payload)

    assert diff.touched == ()
    assert diff.byte_delta == 0


def test_point_id_for_matches_the_stable_recipe_by_default() -> None:
    article = _article("BR.L1.C1.Art.1")

    assert point_id_for(article) == stable_point_id("BR.L1.C1.Art.1")


def test_point_id_for_honours_multi_language() -> None:
    article = _article("BR.L1.C1.Art.1")

    assert point_id_for(article, multi_language=True) == localized_point_id("BR.L1.C1.Art.1", article.language)


def test_volatile_payload_keys_are_not_schema_v1_fields() -> None:
    """Volatile keys are stamps, not schema — they must stay out of the index list."""
    assert set(VOLATILE_PAYLOAD_KEYS) == {"ingested_at", "updated_at"}
    assert not set(VOLATILE_PAYLOAD_KEYS) & set(LOCAL_PAYLOAD_INDEX_FIELDS)


# ---------------------------------------------------------------------------
# Corpus planning
# ---------------------------------------------------------------------------
def test_build_plan_covers_every_file_and_language(corpus: Path) -> None:
    plan = LawCorpusParser().build_plan(corpus)

    # 2 (BR) + 1 (CL) + 1 (INT, one variant chosen) ; _mapping/ excluded
    assert sorted(a.original_id for a in plan.articles) == [
        "BR.L1.C1.Art.1",
        "BR.L1.C1.Art.2",
        "CL.CL1.Art.224",
        "INT.TX.Art.5",
    ]
    assert plan.blocks_total == 5
    assert plan.blocks_without_eli == 0
    assert {f.rel_path for f in plan.files} == {
        "BR/L1.md",
        "CL/CL1.md",
        "INT/BR/TX.md",
        "INT/EN/TX.md",
        "CORP/CODE.md",
    }
    assert dict(plan.languages) == {"pt": 2, "es": 1, "en": 1}


def test_mapping_directory_is_excluded(corpus: Path) -> None:
    plan = LawCorpusParser().build_plan(corpus)

    assert "XX.YY.Art.999" not in plan.by_original_id
    assert all("_mapping" not in f.rel_path for f in plan.files)


def test_collision_prefers_english_by_default(corpus: Path) -> None:
    plan = LawCorpusParser().build_plan(corpus)

    assert plan.collisions["INT.TX.Art.5"] == ["INT/BR/TX.md", "INT/EN/TX.md"]
    chosen = plan.by_original_id["INT.TX.Art.5"]
    assert chosen.theme == "English theme"
    assert chosen.language == "en"
    assert plan.skipped_variants == [("INT.TX.Art.5", "INT/BR/TX.md")]


def test_collision_prefer_language_is_configurable(corpus: Path) -> None:
    plan = LawCorpusParser(preferred_language="pt").build_plan(corpus)

    chosen = plan.by_original_id["INT.TX.Art.5"]
    assert chosen.theme == "Portuguese theme"
    assert chosen.language == "pt"
    assert plan.skipped_variants == [("INT.TX.Art.5", "INT/EN/TX.md")]


def test_keep_all_languages_marks_variants(corpus: Path) -> None:
    parser = LawCorpusParser(keep_all_languages=True)
    plan = parser.build_plan(corpus)

    assert len(plan.articles) == 5
    assert plan.skipped_variants == []
    assert plan.collisions["INT.TX.Art.5"] == ["INT/BR/TX.md", "INT/EN/TX.md"]


def test_reference_only_files_are_reported_not_indexed(corpus: Path) -> None:
    plan = LawCorpusParser().build_plan(corpus)

    assert plan.reference_only_files == ["CORP/CODE.md"]
    report = next(f for f in plan.files if f.rel_path == "CORP/CODE.md")
    assert report.reference_only is True
    assert report.reference_note and "institutional" in report.reference_note


def test_reference_only_detects_document_without_eli_labels(corpus: Path) -> None:
    _write(corpus / "INT" / "EN" / "VCCR.md", "### Preamble\n\nThe States Parties...\n")
    plan = LawCorpusParser().build_plan(corpus)

    report = next(f for f in plan.files if f.rel_path == "INT/EN/VCCR.md")
    assert report.reference_only is True
    assert report.reference_note == "no ELI labels found"
    assert report.blocks_without_eli == 1


def test_reference_only_detects_document_without_article_blocks(corpus: Path) -> None:
    _write(corpus / "INT" / "EN" / "VCCR.md", "# Vienna Convention on Consular Relations\n\nText.\n")
    plan = LawCorpusParser().build_plan(corpus)

    report = next(f for f in plan.files if f.rel_path == "INT/EN/VCCR.md")
    assert report.reference_only is True
    assert report.reference_note == "no article blocks found"


def test_legacy_id_eli_label_and_portuguese_metadata(corpus: Path) -> None:
    """``ID ELI:`` / ``Tema:`` / ``Etiquetas:`` must be understood."""
    article = LawCorpusParser().build_plan(corpus).by_original_id["CL.CL1.Art.224"]

    assert article.theme == "Tema C"
    assert article.tags == "norm_type: right"
    assert article.language == "es"
    assert article.jurisdiction == "CL"


def test_separator_policy_is_forwarded(corpus: Path) -> None:
    keep = LawCorpusParser().build_plan(corpus).by_original_id["BR.L1.C1.Art.1"]
    strip = LawCorpusParser(keep_separator=False).build_plan(corpus).by_original_id["BR.L1.C1.Art.1"]

    assert keep.content.endswith("---")
    assert strip.content == "Alpha body."


def test_plan_as_dict_is_json_serializable(corpus: Path) -> None:
    import json

    plan = LawCorpusParser().build_plan(corpus)
    payload = json.loads(json.dumps(plan.as_dict()))

    assert payload["unique_elis"] == len(plan.articles)
    assert payload["language_breakdown"] == {"pt": 2, "es": 1, "en": 1}


# ---------------------------------------------------------------------------
# Canonical ingestion (non-destructive)
# ---------------------------------------------------------------------------
def test_canonical_ingest_refreshes_existing_payload_without_vectors() -> None:
    existing_id = stable_point_id("BR.L1.C1.Art.1")
    client = StubQdrantClient(
        [
            qm.Record(id=existing_id, payload={"original_id": "BR.L1.C1.Art.1"}),
            qm.Record(id=existing_id, payload={"original_id": "BR.L1.C1.Art.2"}),
        ]
    )
    ingester = CanonicalLawIngester(client, collection="law", bm25_collection="law_bm25")
    articles = [_article("BR.L1.C1.Art.1"), _article("BR.L1.C1.Art.2")]

    stats = ingester.ingest(articles, refresh_bm25=False)

    assert (stats.updated, stats.created, stats.skipped) == (2, 0, 0)
    assert len(client.payload_calls) == 2
    assert all(call["points"] for call in client.payload_calls)
    # payload refresh must never carry a vector
    assert all("vector" not in call for call in client.payload_calls)
    assert [c for c, _ in client.upserts] == []


def test_canonical_ingest_reuses_existing_point_ids() -> None:
    """A point written by the legacy JS ingester keeps its own ID."""
    legacy_id = "11111111-2222-3333-4444-555555555555"
    client = StubQdrantClient(
        [qm.Record(id=legacy_id, payload={"original_id": "BR.L1.C1.Art.1"})]
    )
    ingester = CanonicalLawIngester(client, collection="law")

    ingester.ingest([_article("BR.L1.C1.Art.1")], refresh_bm25=False)

    assert client.payload_calls[0]["points"] == [legacy_id]
    assert legacy_id != stable_point_id("BR.L1.C1.Art.1")


def test_canonical_ingest_skips_unknown_articles_by_default() -> None:
    client = StubQdrantClient()
    ingester = CanonicalLawIngester(client, collection="law", bm25_collection="law_bm25")

    stats = ingester.ingest([_article("BR.L1.C1.Art.1")])

    assert (stats.created, stats.updated, stats.skipped) == (0, 0, 1)
    assert stats.failed == 1
    assert client.payload_calls == []
    assert client.upserts == []


def test_canonical_ingest_creates_new_articles_when_allowed() -> None:
    client = StubQdrantClient()
    ingester = CanonicalLawIngester(client, collection="law", bm25_collection="law_bm25")

    stats = ingester.ingest([_article("BR.L1.C1.Art.1")], allow_new=True)

    assert (stats.created, stats.skipped, stats.failed) == (1, 0, 0)
    assert len(client.upserts) == 2  # dense + bm25
    dense_points = client.upserts[0][1]
    assert dense_points[0].id == stable_point_id("BR.L1.C1.Art.1")
    assert len(dense_points[0].vector) == CANONICAL_DENSE_DIM


def test_canonical_ingest_writes_bm25_sparse_vectors() -> None:
    point_id = stable_point_id("BR.L1.C1.Art.1")
    client = StubQdrantClient([qm.Record(id=point_id, payload={"original_id": "BR.L1.C1.Art.1"})])
    ingester = CanonicalLawIngester(client, collection="law", bm25_collection="law_bm25")

    ingester.ingest([_article("BR.L1.C1.Art.1")])

    collection, points = client.upserts[0]
    assert collection == "law_bm25"
    assert set(points[0].vector) == {"text"}
    assert points[0].payload["framework_code"] == "L1"
    assert points[0].payload["jurisdiction"] == "BR"


def test_canonical_ingest_dry_run_writes_nothing() -> None:
    point_id = stable_point_id("BR.L1.C1.Art.1")
    client = StubQdrantClient([qm.Record(id=point_id, payload={"original_id": "BR.L1.C1.Art.1"})])
    ingester = CanonicalLawIngester(client, collection="law", bm25_collection="law_bm25")

    stats = ingester.ingest([_article("BR.L1.C1.Art.1")], dry_run=True)

    assert client.payload_calls == []
    assert client.upserts == []
    assert stats.notes and "dry-run" in stats.notes[-1]


def test_canonical_dry_run_preview_respects_refresh_payloads() -> None:
    """The preview must not claim a payload rewrite that ``refresh_payloads`` forbids."""
    point_id = stable_point_id("BR.L1.C1.Art.1")
    client = StubQdrantClient([qm.Record(id=point_id, payload={"original_id": "BR.L1.C1.Art.1"})])
    ingester = CanonicalLawIngester(client, collection="law", bm25_collection="law_bm25")

    full = ingester.ingest([_article("BR.L1.C1.Art.1")], dry_run=True)
    incremental = ingester.ingest([_article("BR.L1.C1.Art.1")], dry_run=True, refresh_payloads=False)

    assert "would refresh payload for 1 point(s)" in full.notes[-1]
    assert "would refresh payload for 0 point(s)" in incremental.notes[-1]
    # BM25 sparse vectors are derived data, so they are regenerated either way.
    assert "would upsert 1 BM25 point(s)" in incremental.notes[-1]
    assert client.payload_calls == []
    assert client.upserts == []


def test_facade_incremental_dry_run_does_not_claim_payload_rewrites(corpus: Path) -> None:
    """``only_missing`` implies ``refresh_payloads=False`` end to end."""
    plan = QdrantLawIndex(client=StubQdrantClient([]), law_dir=corpus).build_plan()
    client = StubQdrantClient(
        [
            qm.Record(id=stable_point_id(article.original_id), payload={"original_id": article.original_id})
            for article in plan.articles
        ]
    )
    index = QdrantLawIndex(client=client, law_dir=corpus)

    results = index.ingest(plan, targets=["canonical"], dry_run=True, only_missing=True)

    note = results["canonical"].notes[-1]
    assert "would refresh payload for 0 point(s)" in note
    assert client.payload_calls == []
    assert client.upserts == []


def test_facade_forced_dry_run_reports_payload_rewrites(corpus: Path) -> None:
    """A non-incremental preview still reports the payload refresh it would perform."""
    plan = QdrantLawIndex(client=StubQdrantClient([]), law_dir=corpus).build_plan()
    client = StubQdrantClient(
        [
            qm.Record(id=stable_point_id(article.original_id), payload={"original_id": article.original_id})
            for article in plan.articles
        ]
    )
    index = QdrantLawIndex(client=client, law_dir=corpus)

    results = index.ingest(plan, targets=["canonical"], dry_run=True, only_missing=False)

    assert f"would refresh payload for {len(plan.articles)} point(s)" in results["canonical"].notes[-1]
    assert client.payload_calls == []


def test_existing_index_maps_original_id_to_point_id() -> None:
    client = StubQdrantClient(
        [
            qm.Record(id="a", payload={"original_id": "BR.L1.C1.Art.1"}),
            qm.Record(id="b", payload={"original_id": "BR.L1.C1.Art.2"}),
            qm.Record(id="c", payload={}),
        ]
    )
    index = CanonicalLawIngester(client, collection="law").existing_index()

    assert index == {"BR.L1.C1.Art.1": "a", "BR.L1.C1.Art.2": "b"}


def test_article_count_uses_exact_count() -> None:
    client = StubQdrantClient([qm.Record(id="a", payload={"original_id": "x"})])
    assert CanonicalLawIngester(client, collection="law").article_count() == 1


# ---------------------------------------------------------------------------
# Local ingestion
# ---------------------------------------------------------------------------
def test_local_ingest_dry_run_writes_nothing() -> None:
    client = StubQdrantClient()
    ingester = LocalLawIngester(client, collection="transcription_law")

    stats = ingester.ingest([_article("BR.L1.C1.Art.1")], dry_run=True)

    assert client.created_collections == []
    assert client.upserts == []
    assert "dry-run" in stats.notes[0]


def test_local_ingest_embeds_and_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = StubQdrantClient()
    ingester = LocalLawIngester(client, collection="transcription_law")
    monkeypatch.setattr(ingester, "_embed", lambda texts: [[0.1] * LOCAL_DENSE_DIM for _ in texts])

    stats = ingester.ingest([_article("BR.L1.C1.Art.1")])

    assert stats.created == 1
    assert client.created_collections == ["transcription_law"]
    collection, points = client.upserts[0]
    assert collection == "transcription_law"
    assert points[0].id == stable_point_id("BR.L1.C1.Art.1")
    assert len(points[0].vector) == LOCAL_DENSE_DIM
    assert points[0].payload["language"] == "pt"


def test_local_ingest_multi_language_uses_qualified_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    client = StubQdrantClient()
    ingester = LocalLawIngester(client, collection="transcription_law")
    monkeypatch.setattr(ingester, "_embed", lambda texts: [[0.1] * LOCAL_DENSE_DIM for _ in texts])
    article = _article("INT.TX.Art.5", language="en")

    ingester.ingest([article], multi_language=True)

    assert client.upserts[0][1][0].id == localized_point_id("INT.TX.Art.5", "en")


def test_local_ingest_recreate_drops_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    client = StubQdrantClient()
    ingester = LocalLawIngester(client, collection="transcription_law")
    monkeypatch.setattr(ingester, "_embed", lambda texts: [[0.0] * LOCAL_DENSE_DIM for _ in texts])
    client.create_collection("transcription_law")

    ingester.ingest([_article("BR.L1.C1.Art.1")], recreate=True)

    assert client.deleted_collections == ["transcription_law"]
    assert client.created_collections == ["transcription_law", "transcription_law"]


def test_local_ingest_records_embedding_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    client = StubQdrantClient()
    ingester = LocalLawIngester(client, collection="transcription_law")

    def boom(_texts: Any) -> list[list[float]]:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ingester, "_embed", boom)

    stats = ingester.ingest([_article("BR.L1.C1.Art.1")])

    assert stats.created == 0
    assert stats.failed == 1
    assert stats.failures[0]["reason"] == "embed_failed"
    assert client.upserts == []


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def test_ingest_stats_upserted_and_failure_cap() -> None:
    stats = IngestStats(target="canonical", created=2, updated=3)

    assert stats.upserted == 5
    for index in range(30):
        stats.add_failure("boom", index=index)
    assert stats.failed == 30
    assert len(stats.failures) == 20  # capped to keep reports small
    assert stats.as_dict()["upserted"] == 5


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://x.cloud.qdrant.io:6333/", "https://x.cloud.qdrant.io:6333"),
        ("https://x.cloud.qdrant.io:6333", "https://x.cloud.qdrant.io:6333"),
        ("http://localhost:6333", "http://localhost:6333"),
        ("x.cloud.qdrant.io:6333", "https://x.cloud.qdrant.io:6333"),
        ("", ""),
    ],
)
def test_normalize_qdrant_url(raw: str, expected: str) -> None:
    assert normalize_qdrant_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("short|the-real-long-key", "the-real-long-key"),
        ("a|b|c", "a"),
        ("plain-key", "plain-key"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_qdrant_api_key(raw: str, expected: str) -> None:
    assert normalize_qdrant_api_key(raw) == expected


def test_empty_plan_reports_zero_articles() -> None:
    plan = CorpusPlan()
    assert plan.as_dict()["unique_elis"] == 0
    assert plan.languages == {}


# ---------------------------------------------------------------------------
# Registry artifacts
# ---------------------------------------------------------------------------
def test_write_registry_is_backward_compatible_with_js_schema(corpus: Path) -> None:
    import json

    from src.infrastructure.qdrant_law_index import (
        LawRegistryValidator,
        ValidationReport,
        write_registry,
    )

    plan = LawCorpusParser().build_plan(corpus)
    report = ValidationReport(
        collection="la8159_law",
        points=4,
        unique_original_ids=4,
        articles_parsed=4,
        unique_elis_local=4,
        content_exact=3,
        content_normalized=1,
        source_files_in_collection=["L1.md"],
    )

    json_path, md_path = write_registry(plan, report, output_dir=corpus / "_mapping")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    # legacy top-level shape
    assert set(payload) >= {"summary", "files", "qdrant_only_articles"}
    assert set(payload["summary"]) >= {
        "generated_at",
        "data_law_md_files",
        "data_law_articles_unique",
        "data_law_reference_only_files",
        "qdrant_points",
        "qdrant_articles_with_local_file",
        "data_law_articles_not_in_qdrant",
        "alias_only_same_article_already_ingested",
        "genuinely_missing_articles",
        "qdrant_articles_without_local_file",
        "language_breakdown",
    }
    assert set(payload["files"][0]) >= {
        "file",
        "language",
        "title",
        "reference_only",
        "reference_note",
        "articles_local",
        "articles_in_qdrant",
        "articles_missing",
        "alias_only_not_separately_ingested",
        "missing_eli",
        "alias_eli",
        "in_qdrant_eli",
        "source_basename_present_in_qdrant",
    }
    assert payload["summary"]["data_law_md_files"] == 5
    assert payload["summary"]["data_law_articles_unique"] == 4
    assert payload["summary"]["qdrant_points"] == 4
    assert payload["summary"]["generated_at"]

    assert payload["summary"]["alias_only_same_article_already_ingested"] == 1

    # richer detail block
    assert payload["detail"]["collection"] == "la8159_law"
    assert payload["detail"]["colliding_elis"] == 1

    assert "Registro" not in md_path.read_text(encoding="utf-8")
    assert "Per-file coverage" in md_path.read_text(encoding="utf-8")
    assert isinstance(LawRegistryValidator, type)


def test_write_registry_flags_missing_and_alias_articles(corpus: Path) -> None:
    import json

    from src.infrastructure.qdrant_law_index import ValidationReport, write_registry

    plan = LawCorpusParser().build_plan(corpus)
    report = ValidationReport(
        collection="law",
        missing_in_collection=["BR.L1.C1.Art.2"],
        extra_in_collection=["XX.OTHER.Art.9"],
        extra_details=[{"eli_id": "XX.OTHER.Art.9", "source_file": "other.md", "title": "Other"}],
    )

    json_path, _ = write_registry(plan, report, output_dir=corpus / "_mapping")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    l1 = next(f for f in payload["files"] if f["file"] == "BR/L1.md")
    assert l1["articles_local"] == 2
    assert l1["articles_missing"] == 1
    assert l1["missing_eli"] == ["BR.L1.C1.Art.2"]
    assert l1["in_qdrant_eli"] == ["BR.L1.C1.Art.1"]
    assert l1["source_basename_present_in_qdrant"] is False

    tx = next(f for f in payload["files"] if f["file"] == "INT/EN/TX.md")
    assert tx["alias_only_not_separately_ingested"] == 0  # the EN variant is the chosen one
    assert tx["articles_in_qdrant"] == 1

    br = next(f for f in payload["files"] if f["file"] == "INT/BR/TX.md")
    assert br["articles_local"] == 1
    assert br["alias_eli"] == ["INT.TX.Art.5"]
    assert br["alias_only_not_separately_ingested"] == 1
    assert br["articles_in_qdrant"] == 1

    assert payload["summary"]["genuinely_missing_articles"] == 1
    assert payload["summary"]["qdrant_articles_without_local_file"] == 1
    assert payload["qdrant_only_articles"][0]["eli_id"] == "XX.OTHER.Art.9"


def test_write_registry_given_a_corpus_root_writes_into_mapping(corpus: Path) -> None:
    """A corpus root must resolve to ``_mapping`` so artifacts never land in the corpus.

    Writing them to the root made the generated ``LAW_REGISTRY.md`` show up as a
    corpus file, and the refresh endpoint disagreed with the read endpoints
    (which resolve through ``registry_paths``).
    """
    from src.infrastructure.qdrant_law_index import ValidationReport, write_registry

    plan = LawCorpusParser().build_plan(corpus)
    report = ValidationReport(collection="law")

    json_path, md_path = write_registry(plan, report, output_dir=corpus)

    assert json_path.parent == corpus / "_mapping"
    assert md_path.parent == corpus / "_mapping"
    assert json_path.is_file()
    assert md_path.is_file()
    assert not (corpus / "law_registry.json").exists()
    assert not (corpus / "LAW_REGISTRY.md").exists()


def test_parser_ignores_a_stray_registry_at_the_corpus_root(corpus: Path) -> None:
    """A generated registry dropped at the corpus root is not law content."""
    (corpus / "LAW_REGISTRY.md").write_text("# Law Corpus Registry\n\nGenerated: now\n", encoding="utf-8")
    (corpus / "law_registry.json").write_text("{}\n", encoding="utf-8")

    parser = LawCorpusParser()
    files = parser.iter_files(corpus)
    plan = parser.build_plan(corpus)

    assert all(path.name not in {"LAW_REGISTRY.md", "law_registry.json"} for path in files)
    assert not any(report.rel_path == "LAW_REGISTRY.md" for report in plan.files)
    assert all(article.original_id != "LAW_REGISTRY" for article in plan.articles)


# ---------------------------------------------------------------------------
# Point identity over the real corpus
#
# These tests run against ``data/law`` when it is present. That directory is
# untracked in git, so they skip cleanly in a fresh clone rather than failing.
#
# They exist because an external proposal asserted that "the current random UUID
# creates a new point every run" and replaced the scheme with
# ``article|{framework_code}|{article_number}``. Both halves of that were wrong,
# and both are now executable claims.
# ---------------------------------------------------------------------------
CORPUS_LAW_DIR = default_law_dir()

requires_corpus = pytest.mark.skipif(
    not CORPUS_LAW_DIR.is_dir(),
    reason=f"law corpus not present ({CORPUS_LAW_DIR}) — it is untracked in git",
)


@requires_corpus
def test_every_corpus_point_id_is_unique_and_deterministic() -> None:
    plan = LawCorpusParser().build_plan(CORPUS_LAW_DIR)
    articles = plan.articles
    assert len(articles) > 1000, f"suspiciously small corpus: {len(articles)} articles"

    point_ids = [stable_point_id(article.original_id) for article in articles]
    assert len(set(point_ids)) == len(point_ids), "point IDs must be injective over the corpus"

    for article in articles:
        # Independently recomputed, not read back off the article.
        assert stable_point_id(article.original_id) == str(uuid.uuid5(uuid.NAMESPACE_DNS, article.original_id))
        assert article.point_id == stable_point_id(article.original_id)


@requires_corpus
def test_existing_index_lookups_agree_with_recomputed_ids() -> None:
    """Re-ingest resolves points through the payload field, not by re-deriving ids."""
    plan = LawCorpusParser().build_plan(CORPUS_LAW_DIR)
    records = [
        qm.Record(id=uuid.uuid5(uuid.NAMESPACE_DNS, article.original_id), payload={"original_id": article.original_id})
        for article in plan.articles
    ]
    ingester = CanonicalLawIngester(StubQdrantClient(records))

    assert ingester.existing_index() == {
        article.original_id: str(uuid.uuid5(uuid.NAMESPACE_DNS, article.original_id)) for article in plan.articles
    }


@requires_corpus
def test_the_proposed_identity_recipe_collides_and_must_not_be_used() -> None:
    """``article|{framework_code}|{article_number}`` is not injective.

    Measured on the real corpus: 1119 articles collapse to ~868 ids, and none of
    the surviving ids match the live collection. This is a regression guard, not
    a wish — if it ever starts passing, someone has changed ``article_number``
    or ``framework_code`` and needs to re-check identity.
    """
    plan = LawCorpusParser().build_plan(CORPUS_LAW_DIR)
    articles = plan.articles

    proposed = [f"article|{article.framework_code}|{article.article_number}" for article in articles]
    assert len(set(proposed)) < len(proposed)

    # And the field itself is still populated for every article.
    assert all(article.article_number for article in articles)
    assert all(article.eli_id == article.original_id for article in articles)


@requires_corpus
def test_corpus_articles_carry_classification_and_relative_paths() -> None:
    plan = LawCorpusParser().build_plan(CORPUS_LAW_DIR)
    articles = plan.articles

    assert all(not Path(article.source_path).is_absolute() for article in articles)
    assert all(article.jurisdiction == split_eli(article.original_id)[0] for article in articles)

    classified = sum(1 for article in articles if article.norm_type or article.scope)
    assert classified / len(articles) > 0.9, f"classification coverage regressed: {classified}/{len(articles)}"


@requires_corpus
def test_portuguese_tag_keys_are_not_silently_dropped() -> None:
    """``tipo_norma`` / ``âmbito`` must land in ``norm_type`` / ``scope``.

    An English-only alias table leaves these blocks with no classification at
    all, which is invisible in the payload — the keys are simply absent.

    This scans **every** block, not ``plan.articles``: the plan de-duplicates
    locale variants and keeps the English one, so the Portuguese blocks would
    otherwise never be inspected.
    """
    parser = LawCorpusParser()
    articles = [
        article
        for path in parser.iter_files(CORPUS_LAW_DIR)
        for article in parser.parse_file(path, root=CORPUS_LAW_DIR)[0]
    ]
    assert len(articles) > 1000

    def is_portuguese(article: LawArticle) -> bool:
        return any(token.startswith(("tipo_norma", "âmbito", "escopo")) for token in article.tag_tokens)

    portuguese = [article for article in articles if is_portuguese(article)]
    assert portuguese, "expected Portuguese tag keys in the corpus"
    assert all(article.norm_type or article.scope for article in portuguese)


@requires_corpus
def test_every_corpus_tag_key_is_recognised() -> None:
    """The alias table must cover the corpus vocabulary completely.

    A key that is not in the table is dropped without a trace, so this is the
    check that keeps the bilingual table honest as the corpus grows.
    """
    parser = LawCorpusParser()
    unknown: set[str] = set()
    for path in parser.iter_files(CORPUS_LAW_DIR):
        text = path.read_text(encoding="utf-8")
        for _title, metadata, _body in parse_article_blocks(text):
            for token in parse_article_tags(metadata)["tags"]:
                key, separator, _value = token.partition(":")
                if separator and _fold_tag_label(key) not in _TAG_KEY_ALIASES:
                    unknown.add(_fold_tag_label(key))

    assert unknown == set()
