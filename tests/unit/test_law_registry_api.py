"""Unit tests for the payload-editing helpers and the ``/api/law`` router.

These drive the registry UI's review-and-edit path. Everything runs offline: the
Qdrant client is a recording stub and no embedding model is loaded.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.infrastructure.qdrant_law_index import (
    CANONICAL_COLLECTION,
    EDITABLE_PAYLOAD_FIELDS,
    LOCAL_COLLECTION,
    IngestStats,
    LawIndexStatus,
    PayloadEditError,
    ValidationReport,
    build_payload_patch,
    registry_paths,
)
from tests.unit.test_qdrant_law_index import StubQdrantClient

# ---------------------------------------------------------------------------
# build_payload_patch
# ---------------------------------------------------------------------------
LIVE_PAYLOAD: dict[str, Any] = {
    "original_id": "BR.L1.C1.Art.1",
    "title": "Art. 1 — Alpha",
    "theme": "Tema A",
    "tags": "norm_type: duty",
    "content": "Alpha body.",
    "text": "Alpha body.",
    "source_file": "BR/L1.md",
    "doc_type": "Internal",
    "original_data": {
        "id": "0151cad0-fe68-5505-b3ca-47cd9c47af81",
        "original_id": "BR.L1.C1.Art.1",
        "title": "Art. 1 — Alpha",
        "theme": "Tema A",
        "tags": "norm_type: duty",
        "content": "Alpha body.",
        "source_file": "BR/L1.md",
    },
    "metadata": {
        "data_type": "law",
        "doc_type": "Internal",
        "ingestion_time": "2026-01-01T00:00:00+00:00",
    },
}


def test_editable_fields_exclude_derived_and_owned_keys() -> None:
    # ``text`` is the BM25 source alias of ``content``: both are writable, and
    # ``build_payload_patch`` keeps them in step. The four enrichment fields are
    # writable too, but only on a schema-v1 payload — see
    # ``test_patch_rejects_enrichment_fields_on_a_canonical_payload``.
    assert {
        "title",
        "theme",
        "tags",
        "content",
        "text",
        "source_file",
        "doc_type",
        "norm_type",
        "scope",
        "direction",
        "sanctions",
    } == EDITABLE_PAYLOAD_FIELDS
    owned = (
        "original_id",
        "eli_id",
        "original_data",
        "metadata",
        "sha256_short",
        "source_sha256",
        "framework_code",
        "jurisdiction",
        "article_number",
        "record_kind",
        "schema_version",
    )
    for key in owned:
        assert key not in EDITABLE_PAYLOAD_FIELDS


def test_patch_accepts_every_editable_field() -> None:
    # The enrichment fields only exist on a schema-v1 payload, so the whole
    # editable set is exercised against the local shape. Arrays take a list of
    # tokens; every other field takes a string.
    proposal: dict[str, Any] = dict.fromkeys(EDITABLE_PAYLOAD_FIELDS, "x")
    for array_field in ("norm_type", "scope", "sanctions"):
        proposal[array_field] = ["x"]

    patch = build_payload_patch(proposal, existing=LOCAL_PAYLOAD)

    assert set(patch) >= EDITABLE_PAYLOAD_FIELDS


def test_patch_rejects_immutable_fields_with_a_hint() -> None:
    with pytest.raises(PayloadEditError) as excinfo:
        build_payload_patch({"original_id": "X.Y.Art.1"}, existing=LIVE_PAYLOAD)
    assert "immutable" in str(excinfo.value)


def test_patch_rejects_unknown_fields() -> None:
    with pytest.raises(PayloadEditError, match="not editable"):
        build_payload_patch({"vector": [0.0, 0.0]}, existing=LIVE_PAYLOAD)


def test_patch_rejects_non_string_values() -> None:
    with pytest.raises(PayloadEditError, match="must be a string"):
        build_payload_patch({"tags": ["a", "b"]}, existing=LIVE_PAYLOAD)


def test_patch_rejects_empty_content() -> None:
    with pytest.raises(PayloadEditError, match="may not be empty"):
        build_payload_patch({"content": "   "}, existing=LIVE_PAYLOAD)


def test_patch_rejects_empty_request() -> None:
    with pytest.raises(PayloadEditError, match="no fields"):
        build_payload_patch({}, existing=LIVE_PAYLOAD)


def test_patch_editing_content_syncs_text_and_digest() -> None:
    patch = build_payload_patch({"content": "Beta body."}, existing=LIVE_PAYLOAD)

    assert patch["text"] == "Beta body."
    assert patch["sha256_short"]  # re-derived from the new body
    assert patch["original_data"]["content"] == "Beta body."


def test_patch_mirrors_flat_edits_into_original_data_without_dropping_id() -> None:
    patch = build_payload_patch({"title": "New title", "tags": "scope: x"}, existing=LIVE_PAYLOAD)

    mirror = patch["original_data"]
    assert mirror["title"] == "New title"
    assert mirror["tags"] == "scope: x"
    # Sibling keys the ingester owns must survive.
    assert mirror["id"] == "0151cad0-fe68-5505-b3ca-47cd9c47af81"
    assert mirror["original_id"] == "BR.L1.C1.Art.1"
    assert mirror["theme"] == "Tema A"


def test_patch_preserves_ingestion_time_and_stamps_updated_at() -> None:
    patch = build_payload_patch({"theme": "T2"}, existing=LIVE_PAYLOAD)

    assert patch["metadata"]["ingestion_time"] == "2026-01-01T00:00:00+00:00"
    assert "updated_at" in patch["metadata"]


def test_patch_uses_the_supplied_timestamp() -> None:
    patch = build_payload_patch({"theme": "T2"}, existing=LIVE_PAYLOAD, timestamp="2026-05-05T05:05:05+00:00")

    assert patch["metadata"]["updated_at"] == "2026-05-05T05:05:05+00:00"


def test_patch_without_existing_payload_still_builds_metadata() -> None:
    patch = build_payload_patch({"title": "Only a title"})

    assert patch["title"] == "Only a title"
    assert "updated_at" in patch["metadata"]
    # The nested mirror is built from the flat edits even with no existing payload.
    assert patch["original_data"] == {"title": "Only a title"}


def test_patch_without_existing_payload_omits_the_mirror_when_no_mirrored_key_is_edited() -> None:
    patch = build_payload_patch({"doc_type": "ICAO"})

    assert patch["doc_type"] == "ICAO"
    assert "original_data" not in patch


def test_patch_does_not_leak_other_metadata_keys() -> None:
    patch = build_payload_patch({"title": "T"}, existing=LIVE_PAYLOAD)

    assert patch["metadata"]["data_type"] == "law"
    assert patch["metadata"]["doc_type"] == "Internal"


# ---------------------------------------------------------------------------
# build_payload_patch — schema v1 (transcription_law)
# ---------------------------------------------------------------------------
LOCAL_PAYLOAD: dict[str, Any] = {
    "eli_id": "BR.L1.C1.Art.1",
    "original_id": "BR.L1.C1.Art.1",
    "article_number": "1",
    "framework_code": "L1",
    "jurisdiction": "BR",
    "title": "Art. 1 — Alpha",
    "theme": "Tema A",
    "norm_type": ["duty"],
    "scope": ["regulatory"],
    "direction": None,
    "sanctions": [],
    "tags": ["norm_type: duty", "scope: regulatory"],
    "content": "Alpha body.",
    "text": "Alpha body.",
    "source_file": "BR/L1.md",
    "source_path": "BR/L1.md",
    "source_sha256": "0" * 64,
    "language": "pt",
    "doc_type": "unknown",
    "record_kind": "article",
    "reference_only": False,
    "data_type": "law",
    "schema_version": "1",
    "ingested_at": "2026-01-01T00:00:00.000000Z",
    "updated_at": "2026-01-01T00:00:00.000000Z",
}


def test_local_schema_patch_accepts_a_list_of_tags() -> None:
    patch = build_payload_patch({"tags": ["scope: state", "norm_type: duty"]}, existing=LOCAL_PAYLOAD)

    assert patch["tags"] == ["scope: state", "norm_type: duty"]
    # Schema v1 has neither a nested mirror nor a metadata block.
    assert "metadata" not in patch
    assert "original_data" not in patch


def test_local_schema_patch_stamps_updated_at_but_not_ingested_at() -> None:
    patch = build_payload_patch({"title": "T"}, existing=LOCAL_PAYLOAD, timestamp="2026-05-05T05:05:05.000000Z")

    assert patch["updated_at"] == "2026-05-05T05:05:05.000000Z"
    assert "ingested_at" not in patch


def test_local_schema_patch_rederives_the_full_digest_from_text() -> None:
    patch = build_payload_patch({"text": "Beta body."}, existing=LOCAL_PAYLOAD)

    assert patch["content"] == "Beta body."
    assert patch["text"] == "Beta body."
    assert patch["source_sha256"] == hashlib.sha256(b"Beta body.").hexdigest()
    assert "sha256_short" not in patch


def test_local_schema_patch_rejects_a_non_string_tag_item() -> None:
    with pytest.raises(PayloadEditError, match="list of strings"):
        build_payload_patch({"tags": ["ok", 1]}, existing=LOCAL_PAYLOAD)


# ---------------------------------------------------------------------------
# build_payload_patch — the four enrichment fields
# ---------------------------------------------------------------------------
def test_enrichment_arrays_are_trimmed_and_de_duplicated() -> None:
    patch = build_payload_patch(
        {"norm_type": ["Duty", " duty ", "", "prohibition"]},
        existing=LOCAL_PAYLOAD,
    )

    # First spelling wins, so the corpus keeps the casing the editor typed.
    assert patch["norm_type"] == ["Duty", "prohibition"]


def test_enrichment_arrays_reject_a_bare_string() -> None:
    # A scalar is ambiguous: ``"duty"`` could mean one token or a comma-joined
    # list. The review path wraps a scalar, so the writer stays strict.
    with pytest.raises(PayloadEditError, match="list of strings"):
        build_payload_patch({"sanctions": "financial_penalty"}, existing=LOCAL_PAYLOAD)


def test_enrichment_arrays_reject_a_non_string_token() -> None:
    with pytest.raises(PayloadEditError, match="got int"):
        build_payload_patch({"scope": ["regulatory", 7]}, existing=LOCAL_PAYLOAD)


def test_direction_is_lower_cased_and_underscore_folded() -> None:
    patch = build_payload_patch({"direction": "Forbidden  Task"}, existing=LOCAL_PAYLOAD)

    assert patch["direction"] == "forbidden_task"


def test_direction_can_be_cleared_with_null() -> None:
    patch = build_payload_patch({"direction": None}, existing=LOCAL_PAYLOAD)

    assert patch["direction"] is None


def test_direction_cannot_be_emptied_with_a_blank_string() -> None:
    with pytest.raises(PayloadEditError, match="may not be emptied"):
        build_payload_patch({"direction": "   "}, existing=LOCAL_PAYLOAD)


def test_direction_rejects_a_list() -> None:
    with pytest.raises(PayloadEditError, match="must be a string"):
        build_payload_patch({"direction": ["mandatory"]}, existing=LOCAL_PAYLOAD)


@pytest.mark.parametrize("key", ["norm_type", "scope", "direction", "sanctions"])
def test_patch_rejects_enrichment_fields_on_a_canonical_payload(key: str) -> None:
    # The shared canonical payload has no enrichment keys at all, so accepting
    # an edit there would add a key its consumers do not expect.
    with pytest.raises(PayloadEditError, match="schema-v1 enrichment field"):
        build_payload_patch({key: ["x"] if key != "direction" else "x"}, existing=LIVE_PAYLOAD)


def test_enrichment_edit_stamps_updated_at_and_leaves_ingested_at_alone() -> None:
    patch = build_payload_patch(
        {"direction": "mandatory"}, existing=LOCAL_PAYLOAD, timestamp="2026-06-06T06:06:06.000000Z"
    )

    assert patch["updated_at"] == "2026-06-06T06:06:06.000000Z"
    assert "ingested_at" not in patch


def test_canonical_patch_still_requires_a_string_tags_value() -> None:
    with pytest.raises(PayloadEditError, match="canonical schema"):
        build_payload_patch({"tags": ["scope: state"]}, existing=LIVE_PAYLOAD)


# ---------------------------------------------------------------------------
# registry_paths / LawIndexStatus
# ---------------------------------------------------------------------------
def test_registry_paths_defaults_to_the_repo_mapping_dir() -> None:
    json_path, md_path = registry_paths()

    assert json_path.name == "law_registry.json"
    assert md_path.name == "LAW_REGISTRY.md"
    assert json_path.parent.name == "_mapping"


def test_registry_paths_accepts_a_corpus_root_or_the_mapping_dir(tmp_path: Path) -> None:
    (tmp_path / "_mapping").mkdir()

    assert registry_paths(tmp_path) == registry_paths(tmp_path / "_mapping")


def test_registry_paths_accepts_a_missing_corpus_root(tmp_path: Path) -> None:
    json_path, _ = registry_paths(tmp_path)

    assert json_path == tmp_path / "law_registry.json"


def test_law_index_status_reports_pending_counts() -> None:
    status = LawIndexStatus(
        articles_parsed=10,
        unique_elis=9,
        canonical_missing=["A", "B"],
        local_exists=True,
        local_missing=["C"],
        canonical_points=7,
        local_points=8,
    )

    payload = status.as_dict()

    assert payload["canonical"]["missing"] == 2
    assert payload["canonical"]["extra"] == 0
    assert payload["canonical"]["up_to_date"] is False
    assert payload["local"]["up_to_date"] is False
    assert payload["local"]["missing_sample"] == ["C"]
    assert payload["articles_parsed"] == 10


def test_law_index_status_is_up_to_date_when_nothing_is_pending() -> None:
    payload = LawIndexStatus(local_exists=True).as_dict()

    assert payload["canonical"]["up_to_date"] is True
    assert payload["local"]["up_to_date"] is True


def test_law_index_status_absent_local_collection_is_not_up_to_date() -> None:
    payload = LawIndexStatus(local_exists=False).as_dict()

    assert payload["local"]["exists"] is False
    assert payload["local"]["up_to_date"] is False


def test_status_samples_are_capped() -> None:
    payload = LawIndexStatus(canonical_missing=[f"E{i}" for i in range(200)]).as_dict(sample=5)

    assert payload["canonical"]["missing"] == 200
    assert len(payload["canonical"]["missing_sample"]) == 5


# ---------------------------------------------------------------------------
# Local incremental ingestion
# ---------------------------------------------------------------------------
def test_local_ingest_only_missing_skips_indexed_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure.qdrant_law_index import LOCAL_DENSE_DIM, LocalLawIngester
    from tests.unit.test_qdrant_law_index import _article

    client = StubQdrantClient([SimpleNamespace(payload={"original_id": "BR.L1.C1.Art.1"})])
    ingester = LocalLawIngester(client, collection=LOCAL_COLLECTION)
    monkeypatch.setattr(ingester, "_embed", lambda texts: [[0.1] * LOCAL_DENSE_DIM for _ in texts])
    client.create_collection(LOCAL_COLLECTION)

    stats = ingester.ingest(
        [_article("BR.L1.C1.Art.1"), _article("BR.L1.C1.Art.2")],
        only_missing=True,
    )

    assert stats.scanned == 2
    assert stats.skipped == 1
    assert stats.created == 1
    collection, points = client.upserts[0]
    assert collection == LOCAL_COLLECTION
    assert len(points) == 1
    assert "incremental" in stats.notes[0]


def test_local_ingest_only_missing_is_a_noop_when_nothing_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure.qdrant_law_index import LOCAL_DENSE_DIM, LocalLawIngester
    from tests.unit.test_qdrant_law_index import _article

    client = StubQdrantClient([SimpleNamespace(payload={"original_id": "BR.L1.C1.Art.1"})])
    ingester = LocalLawIngester(client, collection=LOCAL_COLLECTION)
    monkeypatch.setattr(ingester, "_embed", lambda texts: [[0.1] * LOCAL_DENSE_DIM for _ in texts])
    client.create_collection(LOCAL_COLLECTION)

    stats = ingester.ingest([_article("BR.L1.C1.Art.1")], only_missing=True)

    assert stats.created == 0
    assert client.upserts == []
    assert stats.notes[-1] == "nothing to do"


def test_local_ingest_only_missing_embeds_everything_into_a_missing_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.qdrant_law_index import LOCAL_DENSE_DIM, LocalLawIngester
    from tests.unit.test_qdrant_law_index import _article

    client = StubQdrantClient()
    ingester = LocalLawIngester(client, collection=LOCAL_COLLECTION)
    monkeypatch.setattr(ingester, "_embed", lambda texts: [[0.1] * LOCAL_DENSE_DIM for _ in texts])

    stats = ingester.ingest([_article("BR.L1.C1.Art.1")], only_missing=True)

    assert stats.created == 1


def test_local_ingest_reports_progress_per_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure.qdrant_law_index import LOCAL_DENSE_DIM, LocalLawIngester
    from tests.unit.test_qdrant_law_index import _article

    client = StubQdrantClient()
    ingester = LocalLawIngester(client, collection=LOCAL_COLLECTION, batch_size=2)
    monkeypatch.setattr(ingester, "_embed", lambda texts: [[0.1] * LOCAL_DENSE_DIM for _ in texts])

    seen: list[tuple[str, int, int]] = []
    ingester.ingest(
        [_article(f"BR.L1.C1.Art.{i}") for i in range(5)],
        on_progress=lambda phase, done, total: seen.append((phase, done, total)),
    )

    assert seen == [("embedding", 2, 5), ("embedding", 4, 5), ("embedding", 5, 5)]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
class _StubIndex:
    """Minimal stand-in for ``QdrantLawIndex`` used by the router tests."""

    def __init__(self, articles: dict[str, Any] | None = None) -> None:
        self._articles = articles or {}
        self.canonical = SimpleNamespace(collection=CANONICAL_COLLECTION)
        self.local = SimpleNamespace(collection=LOCAL_COLLECTION)
        self.ingest_calls: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.payloads: dict[str, dict[str, Any]] = {}

    def status(self) -> LawIndexStatus:
        return LawIndexStatus(
            articles_parsed=len(self._articles),
            unique_elis=len(self._articles),
            canonical_points=len(self.payloads),
            local_exists=True,
            local_points=len(self.payloads),
        )

    def build_plan(self) -> Any:
        return SimpleNamespace(
            articles=list(self._articles.values()),
            by_original_id=dict(self._articles),
            files=[],
            reference_only_files=[],
            collisions=[],
        )

    def validate(self, plan: Any, **kwargs: Any) -> ValidationReport:
        return ValidationReport(collection=CANONICAL_COLLECTION)

    def get_article(self, original_id: str, *, collection: str | None = None) -> dict[str, Any] | None:
        payload = self.payloads.get(original_id)
        return {"id": "0000", **payload} if payload else None

    def update_payload(
        self,
        original_id: str,
        fields: dict[str, Any],
        *,
        collection: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        self.updates.append({"original_id": original_id, "fields": fields, "collection": collection})
        existing = self.payloads.get(original_id)
        if existing is None:
            raise PayloadEditError(f"article not indexed: {original_id}")
        patch = build_payload_patch(fields, existing=existing)
        if not dry_run:
            self.payloads[original_id] = {**existing, **patch}
        return {
            "collection": collection or CANONICAL_COLLECTION,
            "original_id": original_id,
            "patch": patch,
            "applied": not dry_run,
        }

    def ingest(self, plan: Any, **kwargs: Any) -> dict[str, IngestStats]:
        self.ingest_calls.append(kwargs)
        on_progress = kwargs.get("on_progress")
        if on_progress:
            on_progress("local:embedding", 1, 1)
        stats = IngestStats(target="local")
        stats.created = 3
        return {"local": stats}

    def search(self, query: str, **kwargs: Any) -> list[Any]:
        return []


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A FastAPI app exposing only the law router, backed by ``_StubIndex``.

    ``LAW_DIR`` is redirected to a temp corpus so registry endpoints never read
    or write the real ``data/law`` tree.
    """
    from src.config import settings
    from src.presentation.routers import law_registry

    monkeypatch.setattr(settings, "LAW_DIR", str(tmp_path / "law"), raising=False)
    (tmp_path / "law" / "_mapping").mkdir(parents=True)
    (tmp_path / "law" / "BR").mkdir(parents=True)
    (tmp_path / "law" / "BR" / "L1.md").write_text("# Lei 1\n\n### Art. 1\n\nBody.\n", encoding="utf-8")

    from tests.unit.test_qdrant_law_index import _article

    articles = {"BR.L1.C1.Art.1": _article("BR.L1.C1.Art.1")}
    index = _StubIndex(articles)
    index.payloads["BR.L1.C1.Art.1"] = dict(LIVE_PAYLOAD)
    law_registry.init_law_registry_router(index)

    app = FastAPI()
    app.state.law_root = tmp_path / "law"
    app.include_router(law_registry.router)
    with TestClient(app) as test_client:
        test_client.index = index  # type: ignore[attr-defined]
        yield test_client

    law_registry.init_law_registry_router(None)


def _wait_for_job(client: Any, job_id: str, timeout: float = 5.0) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(f"/api/law/index/{job_id}").json()
        if payload["state"] not in {"queued", "running"}:
            return payload
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


def test_status_endpoint_exposes_coverage_and_editable_fields(client: Any) -> None:
    payload = client.get("/api/law/status").json()

    assert payload["local"]["collection"] == LOCAL_COLLECTION
    assert payload["canonical"]["collection"] == CANONICAL_COLLECTION
    assert payload["editable_fields"] == sorted(EDITABLE_PAYLOAD_FIELDS)
    assert payload["registry"]["json_exists"] is False


def test_article_endpoint_returns_live_and_expected_payloads(client: Any) -> None:
    payload = client.get("/api/law/article", params={"original_id": "BR.L1.C1.Art.1"}).json()

    assert payload["indexed"] is True
    assert payload["live"]["title"] == "Art. 1 — Alpha"
    assert payload["expected"] is not None
    assert payload["diff"]["content"] == "exact" or payload["diff"]["content"] in {"drift", "whitespace"}
    assert isinstance(payload["diff"]["_only_live"], list)


def test_article_endpoint_404s_for_an_unknown_eli(client: Any) -> None:
    response = client.get("/api/law/article", params={"original_id": "NOPE.Art.1"})

    assert response.status_code == 404


def test_article_endpoint_reports_unindexed_corpus_articles(client: Any) -> None:
    from tests.unit.test_qdrant_law_index import _article

    client.index._articles["BR.L1.C1.Art.9"] = _article("BR.L1.C1.Art.9")

    payload = client.get("/api/law/article", params={"original_id": "BR.L1.C1.Art.9"}).json()

    assert payload["indexed"] is False
    assert payload["live"] is None
    assert payload["expected"] is not None


def test_patch_payload_applies_an_edit(client: Any) -> None:
    response = client.patch(
        "/api/law/payload",
        json={"original_id": "BR.L1.C1.Art.1", "fields": {"title": "Edited"}},
    )

    assert response.status_code == 200
    assert client.index.payloads["BR.L1.C1.Art.1"]["title"] == "Edited"
    assert response.json()["patch"]["original_data"]["title"] == "Edited"


def test_patch_payload_rejects_immutable_fields(client: Any) -> None:
    response = client.patch(
        "/api/law/payload",
        json={"original_id": "BR.L1.C1.Art.1", "fields": {"original_id": "HACKED"}},
    )

    assert response.status_code == 400
    assert "immutable" in response.json()["detail"]


def test_patch_payload_rejects_an_empty_field_set(client: Any) -> None:
    response = client.patch("/api/law/payload", json={"original_id": "BR.L1.C1.Art.1", "fields": {}})

    assert response.status_code == 400


def test_patch_payload_reports_a_missing_point(client: Any) -> None:
    response = client.patch(
        "/api/law/payload",
        json={"original_id": "BR.L1.C1.Art.404", "fields": {"title": "x"}},
    )

    assert response.status_code == 400
    assert "not indexed" in response.json()["detail"]


def test_index_endpoint_runs_an_incremental_job(client: Any) -> None:
    response = client.post("/api/law/index", json={"mode": "incremental", "target": "local"})

    assert response.status_code == 202
    job = _wait_for_job(client, response.json()["id"])

    assert job["state"] == "done"
    assert job["result"]["targets"]["local"]["created"] == 3
    assert client.index.ingest_calls[0]["only_missing"] is True


def test_index_endpoint_force_mode_disables_only_missing(client: Any) -> None:
    job_id = client.post("/api/law/index", json={"mode": "force", "target": "local"}).json()["id"]
    _wait_for_job(client, job_id)

    assert client.index.ingest_calls[0]["only_missing"] is False


def test_index_endpoint_requires_confirmation_for_canonical_writes(client: Any) -> None:
    response = client.post("/api/law/index", json={"mode": "incremental", "target": "canonical"})

    assert response.status_code == 400
    assert "confirm" in response.json()["detail"]


def test_index_endpoint_allows_a_canonical_dry_run_without_confirmation(client: Any) -> None:
    response = client.post(
        "/api/law/index",
        json={"mode": "incremental", "target": "canonical", "dry_run": True},
    )

    assert response.status_code == 202
    _wait_for_job(client, response.json()["id"])


def test_index_endpoint_accepts_a_confirmed_canonical_write(client: Any) -> None:
    response = client.post(
        "/api/law/index",
        json={"mode": "incremental", "target": "canonical", "confirm": True},
    )

    assert response.status_code == 202
    job = _wait_for_job(client, response.json()["id"])
    assert job["request"]["targets"] == ["canonical"]


def test_index_endpoint_rejects_recreate_with_incremental_mode(client: Any) -> None:
    response = client.post(
        "/api/law/index",
        json={"mode": "incremental", "target": "local", "recreate_local": True},
    )

    assert response.status_code == 400


def test_index_endpoint_rejects_an_unknown_mode(client: Any) -> None:
    response = client.post("/api/law/index", json={"mode": "sideways", "target": "local"})

    assert response.status_code == 422


def test_unknown_job_id_returns_404(client: Any) -> None:
    assert client.get("/api/law/index/deadbeef").status_code == 404


def test_source_endpoint_rejects_traversal(client: Any) -> None:
    response = client.get("/api/law/source", params={"path": "../../../etc/passwd"})

    assert response.status_code == 400


def test_source_endpoint_rejects_non_markdown(client: Any) -> None:
    response = client.get("/api/law/source", params={"path": "BR/L1.txt"})

    assert response.status_code == 400


def test_source_endpoint_serves_a_corpus_file(client: Any) -> None:
    response = client.get("/api/law/source", params={"path": "BR/L1.md"})

    assert response.status_code == 200
    assert "Lei 1" in response.text


def test_registry_endpoint_generates_on_demand_when_absent(client: Any) -> None:
    payload = client.get("/api/law/registry").json()

    assert payload["summary"]["note"].startswith("generated on demand")


def test_registry_endpoint_returns_the_file_once_present(client: Any) -> None:
    json_path, md_path = registry_paths(client.app.state.law_root)
    json_path.write_text(json.dumps({"summary": {"generated_at": "x"}, "files": [{"file": "BR/L1.md"}]}), "utf-8")

    payload = client.get("/api/law/registry").json()

    assert payload["files"][0]["file"] == "BR/L1.md"
    assert md_path.parent == json_path.parent


def test_registry_markdown_endpoint_404s_when_absent(client: Any) -> None:
    assert client.get("/api/law/registry/markdown").status_code == 404


def test_search_endpoint_returns_hits(client: Any) -> None:
    payload = client.get("/api/law/search", params={"q": "duty"}).json()

    assert payload["hits"] == []
    assert payload["target"] == "local"


# ---------------------------------------------------------------------------
# POST /api/law/suggest — LLM-assisted payload review
# ---------------------------------------------------------------------------
def _stub_llm(monkeypatch: pytest.MonkeyPatch, result: Any) -> dict[str, Any]:
    """Replace the LLM seam; ``result`` may be a dict or an exception instance."""
    from src.presentation.routers import law_registry

    calls: dict[str, Any] = {}

    def _fake(system: str, user: str, **kwargs: Any) -> dict[str, Any]:
        calls["system"] = system
        calls["user"] = json.loads(user)
        calls["kwargs"] = kwargs
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(law_registry, "call_llm_json", _fake)
    return calls


def test_suggest_keeps_only_editable_effective_suggestions(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_llm(
        monkeypatch,
        {
            "suggestions": [
                {"field": "title", "suggested": "Art. 1 — Renamed", "rationale": "clearer", "confidence": "high"},
                {"field": "norm_type", "suggested": ["duty"], "rationale": "canonical payload cannot hold it"},
                {"field": "theme", "suggested": "Tema A", "rationale": "no-op"},
                {"field": "tags", "suggested": ["norm_type: duty"], "rationale": "wrong type"},
                {"field": "content", "suggested": "Rewritten body.", "rationale": "not requested"},
            ],
            "_model": "stub-model",
            "_usage": {"total_tokens": 12},
        },
    )

    payload = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"}).json()

    assert [s["field"] for s in payload["suggestions"]] == ["title"]
    assert payload["suggestions"][0]["current"] == "Art. 1 — Alpha"
    assert payload["suggestions"][0]["suggested"] == "Art. 1 — Renamed"
    assert payload["suggestions"][0]["confidence"] == "high"
    assert payload["dropped"] == 4
    assert payload["model"] == "stub-model"
    assert payload["usage"] == {"total_tokens": 12}


def test_suggest_review_fields_exclude_immutable_and_unrequested_content(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_llm(monkeypatch, {"suggestions": []})

    payload = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"}).json()

    fields = payload["fields_reviewed"]
    assert "content" not in fields
    assert "text" not in fields
    assert fields == ["title", "theme", "tags", "doc_type", "source_file"]
    assert set(fields) <= EDITABLE_PAYLOAD_FIELDS
    # The model is told its own allow-list.
    assert calls["user"]["allowed_fields"] == fields


def test_suggest_include_content_opts_the_body_back_in(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_llm(
        monkeypatch,
        {"suggestions": [{"field": "content", "suggested": "Alpha body, extended.", "confidence": "low"}]},
    )

    payload = client.post(
        "/api/law/suggest",
        json={"original_id": "BR.L1.C1.Art.1", "include_content": True},
    ).json()

    assert "content" in payload["fields_reviewed"]
    assert [s["field"] for s in payload["suggestions"]] == ["content"]


def test_suggest_explicit_field_list_is_validated(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_llm(monkeypatch, {"suggestions": []})

    response = client.post(
        "/api/law/suggest",
        json={"original_id": "BR.L1.C1.Art.1", "fields": ["title", "jurisdiction"]},
    )

    assert response.status_code == 400
    assert "jurisdiction" in response.json()["detail"]


def test_suggest_explicit_content_without_the_flag_is_rejected(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_llm(monkeypatch, {"suggestions": []})

    response = client.post(
        "/api/law/suggest",
        json={"original_id": "BR.L1.C1.Art.1", "fields": ["content"]},
    )

    assert response.status_code == 400


def test_suggest_writes_nothing(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_llm(monkeypatch, {"suggestions": [{"field": "title", "suggested": "Art. 1 — Renamed"}]})

    client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"})

    assert client.index.updates == []
    assert client.index.payloads["BR.L1.C1.Art.1"]["title"] == "Art. 1 — Alpha"


def test_suggest_reply_can_be_applied_through_the_patch_endpoint(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_llm(monkeypatch, {"suggestions": [{"field": "title", "suggested": "Art. 1 — Renamed"}]})

    suggestion = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"}).json()["suggestions"][0]
    patch = client.patch(
        "/api/law/payload",
        json={
            "original_id": "BR.L1.C1.Art.1",
            "collection": CANONICAL_COLLECTION,
            "fields": {suggestion["field"]: suggestion["suggested"]},
        },
    )

    assert patch.status_code == 200
    assert client.index.payloads["BR.L1.C1.Art.1"]["title"] == "Art. 1 — Renamed"


def test_suggest_reports_an_unknown_article_as_404(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_llm(monkeypatch, {"suggestions": []})

    response = client.post("/api/law/suggest", json={"original_id": "BR.L9.C9.Art.9"})

    assert response.status_code == 404


def test_suggest_maps_llm_failures_to_502(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure.llm import LLMError

    _stub_llm(monkeypatch, LLMError("No LLM provider is configured"))

    response = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"})

    assert response.status_code == 502
    assert "No LLM provider is configured" in response.json()["detail"]


def test_suggest_passes_provider_and_model_through(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_llm(monkeypatch, {"suggestions": []})

    client.post(
        "/api/law/suggest",
        json={"original_id": "BR.L1.C1.Art.1", "provider": "deepseek", "model": "deepseek-flash"},
    )

    assert calls["kwargs"] == {"provider": "deepseek", "model": "deepseek-flash"}


def test_suggest_snippets_the_corpus_markdown(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.presentation.routers import law_registry
    from tests.unit.test_qdrant_law_index import _article

    calls = _stub_llm(monkeypatch, {"suggestions": []})
    article = _article("BR.L1.C1.Art.1", source_path="BR/L1.md", content="Body.")

    snippet = law_registry._source_snippet(article, {})

    assert "Lei 1" in snippet
    client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"})
    assert calls["user"]["SNIPPET"]


def test_source_snippet_falls_back_to_the_live_content(client: Any) -> None:
    from src.presentation.routers import law_registry
    from tests.unit.test_qdrant_law_index import _article

    article = _article("BR.L1.C1.Art.1", source_path="BR/missing.md", content="")

    assert law_registry._source_snippet(article, {"content": "Live only."}) == "Live only."


def test_suggest_honours_an_explicit_narrow_field_list(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_llm(monkeypatch, {"suggestions": []})

    payload = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1", "fields": ["theme"]}).json()

    assert payload["fields_reviewed"] == ["theme"]
    # The live value is still sent as context even though only one field is reviewed.
    assert calls["user"]["CURRENT"]["theme"] == "Tema A"


# ---------------------------------------------------------------------------
# /suggest — enrichment review and the saved report
# ---------------------------------------------------------------------------
SCHEMA_V1_LIVE: dict[str, Any] = {**LOCAL_PAYLOAD}


def _use_schema_v1_payload(client: Any) -> dict[str, Any]:
    """Point the stub index at a schema-v1 (local) payload."""
    client.index.payloads["BR.L1.C1.Art.1"] = dict(SCHEMA_V1_LIVE)
    return client.index.payloads["BR.L1.C1.Art.1"]


def _report_dir(client: Any) -> Path:
    return Path(client.app.state.law_root) / "_mapping" / "enrichment"


def test_suggest_on_canonical_leaves_enrichment_out_and_says_why(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_llm(monkeypatch, {"suggestions": []})

    payload = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"}).json()

    assert payload["mode"] == "metadata"
    assert payload["enrichment_fields"] == []
    assert not set(payload["fields_reviewed"]) & {"norm_type", "scope", "direction", "sanctions"}
    # The enrichment taxonomy is withheld here — but ``doc_type`` is reviewed on
    # canonical payloads as well (it is a canonical key), so its own taxonomy is
    # offered and the model can still propose an instrument type.
    vocabulary = calls["user"]["vocabulary"]
    assert "### `doc_type`" in vocabulary
    assert not any(
        f"### `{name}`" in vocabulary for name in ("norm_type", "scope", "direction", "sanctions")
    )
    assert any("schema" in note for note in payload["notes"])


def test_suggest_on_schema_v1_reviews_the_enrichment_fields_with_the_taxonomy(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_schema_v1_payload(client)
    calls = _stub_llm(monkeypatch, {"suggestions": []})

    payload = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"}).json()

    assert payload["mode"] == "enrichment"
    assert payload["enrichment_fields"] == ["norm_type", "scope", "direction", "sanctions"]
    # The taxonomy is handed over, not just the field names.
    assert "### `norm_type`" in calls["user"]["vocabulary"]
    assert "`prohibitive`" in calls["user"]["vocabulary"]


def test_suggest_normalises_enrichment_tokens_onto_the_vocabulary(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_schema_v1_payload(client)
    _stub_llm(
        monkeypatch,
        {
            "suggestions": [
                {"field": "norm_type", "suggested": ["dever", "Prohibition"], "rationale": "r", "confidence": "high"},
                {"field": "direction", "suggested": "Obligation", "rationale": "r", "confidence": "high"},
            ]
        },
    )

    payload = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"}).json()
    by_field = {s["field"]: s for s in payload["suggestions"]}

    assert by_field["norm_type"]["suggested"] == ["duty", "prohibition"]
    assert by_field["norm_type"]["normalized_from"] == [
        {"from": "dever", "to": "duty"},
        {"from": "Prohibition", "to": "prohibition"},
    ]
    assert by_field["norm_type"]["vocabulary"] == "controlled"
    # ``direction`` is stored as null, so any string the model proposes is a change.
    assert by_field["direction"]["suggested"] == "mandatory"
    assert by_field["direction"]["normalized_from"] == [{"from": "Obligation", "to": "mandatory"}]


def test_suggest_keeps_a_token_outside_the_vocabulary_as_a_proposal(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_schema_v1_payload(client)
    _stub_llm(
        monkeypatch,
        {"suggestions": [{"field": "norm_type", "suggested": ["Probidad"], "rationale": "r"}]},
    )

    suggestion = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"}).json()["suggestions"][0]

    # The token is folded into the corpus convention and flagged, not dropped.
    assert suggestion["suggested"] == ["probidad"]
    assert suggestion["unknown_tokens"] == ["probidad"]
    assert suggestion["vocabulary"] == "proposal"


def test_suggest_reports_the_fields_that_saw_no_element_of_text(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_schema_v1_payload(client)
    _stub_llm(monkeypatch, {"suggestions": [{"field": "sanctions", "suggested": [], "rationale": "none"}]})

    payload = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"}).json()

    assert payload["suggestions"] == []
    assert payload["dropped"] == 1
    assert "### `sanctions`" in payload["report"]


def test_suggest_saves_the_report_and_returns_its_markdown(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_schema_v1_payload(client)
    _stub_llm(
        monkeypatch,
        {
            "summary": "Nothing recorded yet.",
            "suggestions": [
                {
                    "field": "direction",
                    "suggested": "mandatory",
                    "rationale": "the operative verb is 'deverá'",
                    "justification": "The addressee shall observe the duty.",
                    "evidence": "deverá observar",
                    "confidence": "high",
                }
            ],
            "decision_logic": {"direction": "Read the main verb."},
            "_model": "stub-model",
        },
    )

    payload = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"}).json()

    assert payload["saved"] is True
    assert payload["report_name"] == "BR.L1.C1.Art.1.md"
    assert payload["report"].startswith("# Enrichment review — `BR.L1.C1.Art.1`")
    for heading in (
        "## 🧭 Proposed Field Populations",
        "## 📋 Detailed Justification",
        "## 🧩 Baseline for Other Articles",
        "## ✅ Applied Updates",
    ):
        assert heading in payload["report"]
    assert "the operative verb is 'deverá'" in payload["report"]
    assert "deverá observar" in payload["report"]

    written = _report_dir(client) / payload["report_name"]
    assert written.read_text(encoding="utf-8") == payload["report"]
    # The JSON sibling is the machine-readable source of truth.
    assert json.loads((_report_dir(client) / "BR.L1.C1.Art.1.json").read_text(encoding="utf-8"))["model"] == "stub-model"


def test_suggest_can_skip_saving_the_report(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_schema_v1_payload(client)
    _stub_llm(monkeypatch, {"suggestions": [{"field": "direction", "suggested": "mandatory"}]})

    payload = client.post(
        "/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1", "save_report": False}
    ).json()

    assert payload["saved"] is False
    assert payload["report_name"] is None
    assert payload["report"]  # the review is still returned to the caller
    assert not list(_report_dir(client).glob("*.md"))


def test_suggest_still_writes_a_report_when_an_earlier_review_exists(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_schema_v1_payload(client)
    _stub_llm(monkeypatch, {"suggestions": [{"field": "direction", "suggested": "mandatory"}]})
    article = {"original_id": "BR.L1.C1.Art.1", "collection": LOCAL_COLLECTION, "fields": {"direction": "mandatory"}}

    client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"})
    assert client.patch("/api/law/payload", json=article).status_code == 200
    payload = client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"}).json()

    # A re-review must not forget what was already applied.
    assert "`direction`" in payload["report"].split("## ✅ Applied Updates")[1]
    assert "| `direction` | _(none)_ | `mandatory` |" in payload["report"]


def test_reports_endpoints_list_and_serve_the_saved_reports(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_schema_v1_payload(client)
    _stub_llm(monkeypatch, {"suggestions": [{"field": "direction", "suggested": "mandatory", "rationale": "r"}]})
    client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"})

    listing = client.get("/api/law/reports").json()["reports"]
    assert [entry["name"] for entry in listing] == ["BR.L1.C1.Art.1.md"]
    assert listing[0]["original_id"] == "BR.L1.C1.Art.1"
    assert listing[0]["suggestions"] == 1
    assert listing[0]["applied"] == 0

    response = client.get("/api/law/reports/BR.L1.C1.Art.1.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# Enrichment review")


def test_report_endpoint_rejects_a_non_markdown_name_and_an_unknown_report(client: Any) -> None:
    assert client.get("/api/law/reports/notes.txt").status_code == 400
    assert client.get("/api/law/reports/BR.L1.C1.Art.9.md").status_code == 404


def test_patch_on_an_enrichment_field_appends_to_the_saved_report(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_schema_v1_payload(client)
    _stub_llm(monkeypatch, {"suggestions": [{"field": "direction", "suggested": "mandatory", "rationale": "r"}]})
    client.post("/api/law/suggest", json={"original_id": "BR.L1.C1.Art.1"})

    response = client.patch(
        "/api/law/payload",
        json={
            "original_id": "BR.L1.C1.Art.1",
            "collection": LOCAL_COLLECTION,
            "fields": {"direction": "mandatory"},
        },
    )

    assert response.status_code == 200
    assert response.json()["report_name"] == "BR.L1.C1.Art.1.md"
    trail = (_report_dir(client) / "BR.L1.C1.Art.1.md").read_text(encoding="utf-8")
    assert "| `direction` | _(none)_ | `mandatory` |" in trail
    assert client.index.payloads["BR.L1.C1.Art.1"]["direction"] == "mandatory"


def test_patch_on_a_metadata_field_does_not_touch_the_report(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_llm(monkeypatch, {"suggestions": []})

    response = client.patch(
        "/api/law/payload",
        json={
            "original_id": "BR.L1.C1.Art.1",
            "collection": CANONICAL_COLLECTION,
            "fields": {"title": "Art. 1 — Renamed"},
        },
    )

    assert response.status_code == 200
    assert "report_name" not in response.json()


def test_article_endpoint_reports_the_editor_shape_per_schema(client: Any) -> None:
    canonical = client.get("/api/law/article", params={"original_id": "BR.L1.C1.Art.1"}).json()
    assert "norm_type" not in canonical["field_kinds"]
    assert canonical["field_kinds"]["theme"] == "string"

    _use_schema_v1_payload(client)
    local = client.get("/api/law/article", params={"original_id": "BR.L1.C1.Art.1"}).json()

    assert local["field_kinds"]["norm_type"] == "list"
    assert local["field_kinds"]["sanctions"] == "list"
    assert local["field_kinds"]["direction"] == "scalar_nullable"
    assert local["field_kinds"]["tags"] == "list"
    assert local["enrichment_fields"] == ["norm_type", "scope", "direction", "sanctions"]


def test_llm_json_parser_tolerates_fences_and_prose() -> None:
    from src.infrastructure.llm import LLMError, parse_json_reply

    assert parse_json_reply('```json\n{"suggestions": []}\n```') == {"suggestions": []}
    assert parse_json_reply('Here you go: {"a": 1} — enjoy') == {"a": 1}

    with pytest.raises(LLMError):
        parse_json_reply("no json at all")


# ---------------------------------------------------------------------------
# Reasoning budget
#
# Measured against the configured endpoint: a reasoning model spent the entire
# completion budget on reasoning_content and returned empty content with
# finish_reason="length" — at both 4096 and 8192 max_tokens — so ``/suggest``
# failed with "the model returned an empty reply". Sending
# ``reasoning_effort="none"`` zeroes the reasoning block there.
# ---------------------------------------------------------------------------
def _chat_response(status: int, payload: dict[str, Any]) -> Any:
    return SimpleNamespace(status_code=status, text=json.dumps(payload), json=lambda: payload)


def _patch_llm_plumbing(monkeypatch: pytest.MonkeyPatch, post: Any) -> None:
    from src.infrastructure import llm

    monkeypatch.setattr(llm, "_post_chat", post)
    monkeypatch.setattr(llm, "_chat_url", lambda provider: "https://example.test/v1/chat/completions")
    monkeypatch.setattr(llm, "resolve_provider", lambda explicit=None: "deepseek")
    monkeypatch.setattr(llm, "resolve_model", lambda provider, explicit=None: "test-model")
    monkeypatch.setattr(llm, "provider_kind", lambda provider: "openai")
    monkeypatch.setattr(llm.creds, "get_api_key", lambda provider: "test-key")


def test_call_llm_json_asks_the_provider_not_to_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure import llm

    sent: list[dict[str, Any]] = []

    def post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        sent.append(dict(body))
        return _chat_response(200, {
            "model": "test-model",
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}],
            "usage": {"completion_tokens": 12},
        })

    _patch_llm_plumbing(monkeypatch, post)
    assert llm.call_llm_json("system", "user")["ok"] is True
    assert sent[0]["reasoning_effort"] == "none"
    assert len(sent) == 1


def test_call_llm_json_retries_without_reasoning_effort_when_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure import llm

    sent: list[dict[str, Any]] = []
    replies = [
        _chat_response(400, {"error": {"message": "unknown parameter: reasoning_effort"}}),
        _chat_response(200, {
            "model": "test-model",
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}],
            "usage": {},
        }),
    ]

    def post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        sent.append(dict(body))
        return replies.pop(0)

    _patch_llm_plumbing(monkeypatch, post)
    assert llm.call_llm_json("system", "user")["ok"] is True
    assert sent[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in sent[1]
    assert len(sent) == 2


def test_call_llm_json_does_not_retry_a_400_that_names_something_else(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure import llm

    sent: list[dict[str, Any]] = []

    def post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        sent.append(dict(body))
        return _chat_response(400, {"error": {"message": "model not found"}})

    _patch_llm_plumbing(monkeypatch, post)
    with pytest.raises(llm.LLMError) as err:
        llm.call_llm_json("system", "user")
    assert "model not found" in str(err.value)
    # A blind retry would double the traffic of every genuine 400.
    assert len(sent) == 1


def test_empty_content_says_the_reasoning_ate_the_budget() -> None:
    from src.infrastructure.llm import LLMError, _message_text

    upstream = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": "", "reasoning_content": "x" * 500},
            }
        ]
    }
    with pytest.raises(LLMError) as err:
        _message_text(upstream)
    message = str(err.value)
    assert "reasoning" in message
    assert "500" in message
    assert "length" in message

    with pytest.raises(LLMError) as silent:
        _message_text({"choices": [{"finish_reason": "stop", "message": {"content": ""}}]})
    assert "empty reply" in str(silent.value)

    assert _message_text({"choices": [{"message": {"content": "  hello  "}}]}) == "  hello  "
    assert _message_text(
        {"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}
    ) == "ab"


# ---------------------------------------------------------------------------
# Auto-detection skips a provider with no models
#
# Reported live: with the "auto-detect" provider the review failed with "No model
# chosen for provider 'ollama'". A local Ollama daemon answers without an API key
# and sorts first in the registry, so it won auto-detection while having zero
# models pulled — every auto-detected call failed.
# ---------------------------------------------------------------------------
def _patch_registry(monkeypatch: pytest.MonkeyPatch, configured: dict[str, list[str]]) -> None:
    from src.infrastructure import llm

    monkeypatch.setattr(llm.creds, "is_configured", lambda provider: provider in configured)
    monkeypatch.setattr(
        llm, "get_models", lambda provider: [{"id": f"{provider}-model"}] if configured.get(provider) else []
    )


def test_auto_detect_skips_a_configured_provider_with_no_models(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure import llm

    _patch_registry(monkeypatch, {"ollama": [], "deepseek": ["deepseek-flash"]})
    assert llm.configured_providers()[:2] == ["ollama", "deepseek"]
    assert llm.serviceable_providers() == ["deepseek"]
    assert llm.resolve_provider() == "deepseek"


def test_auto_detect_still_returns_a_modelless_provider_when_it_is_all_there_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure import llm

    _patch_registry(monkeypatch, {"ollama": []})
    assert llm.serviceable_providers() == []
    assert llm.resolve_provider() == "ollama"
    with pytest.raises(llm.LLMError, match="No model chosen"):
        llm.resolve_model("ollama")
