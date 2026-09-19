"""Qdrant law corpus index — parse ``data/law/**/*.md`` and ingest into Qdrant.

The law corpus under ``data/law`` is authored in Markdown. Every *article* is a
level-3 heading block::

    ### Art. 224 — CBA Title VII, Chapter I, Article 224 – Combined Transport

    **Theme:** Liability and Exemptions
    **ELI ID:** `BR.CBA.T7.C1.Art.224`
    **Tags:** norm_type: procedural · scope: regulatory

    Art. 224. Em caso de transporte combinado, ...

    ---

This module turns those blocks into canonical article records and writes them to
two kinds of Qdrant target:

``canonical``
    The shared production collections ``la8159_law`` (768-dim dense payload store)
    and ``la8159_law_bm25`` (server-side BM25 sparse vectors). These are consumed
    by sibling projects, so ingestion is **non-destructive**:

    * existing points are found by the ``original_id`` payload field and their
      point ID is *reused* (no duplicates, no orphans);
    * payloads are refreshed with ``set_payload``, which preserves the original
      768-dim dense vectors (the model that produced them is not available here);
    * BM25 sparse vectors are *derived* data, so they are safely re-generated.

``local``
    A repo-owned dense collection (default ``transcription_law``, 384-dim
    ``all-MiniLM-L6-v2``) for real semantic search from this repository.

Design notes
------------
* Articles are keyed by **ELI label**, not by heading prefix. The corpus uses
  many heading styles (``Art.``, ``Artigo``, ``Article``, ``Anexo``, ``Item``,
  ``Seção``, ``§``, roman numerals …) but exactly one ELI per article, and
  ``discovery/case-server/pipeline/build_law_registry.js`` validates the corpus
  the same way.
* ``INT/BR/<file>.md`` and ``INT/EN/<file>.md`` are the same instruments in
  Portuguese and English, so they share ELI labels. The collision policy decides
  which variant is indexed (default: the English one, matching production).
* Files with no ELI label (whole-code dumps, corporate codes of conduct) are
  *reference-only* per ``discovery/ref_docs/law-ingestion-guide.md`` and skipped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
import unicodedata
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

logger = logging.getLogger(__name__)

#: ``(phase, done, total)`` progress callback. Invoked from whichever thread is
#: performing the ingestion, so implementations must be thread-safe.
ProgressCallback = Callable[[str, int, int], None]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Namespace for deterministic article point IDs.
#:
#: Verified against production: 834 / 1119 points in ``la8159_law`` follow
#: ``uuid5(NAMESPACE_DNS, original_id)``. The other 285 were written by
#: ``discovery/case-server/pipeline/ingest_new_law.js`` using a private
#: namespace. New points therefore use this namespace by default while existing
#: points are always *reused by id*, so the collection never gains duplicates.
LAW_ID_NAMESPACE: uuid.UUID = uuid.NAMESPACE_DNS

CANONICAL_COLLECTION = "la8159_law"
CANONICAL_BM25_COLLECTION = "la8159_law_bm25"
LOCAL_COLLECTION = "transcription_law"

#: Dense dimension of ``la8159_law``. The model that produced those vectors is
#: not available in this repo, so newly created points get a deterministic
#: *placeholder* vector that must never be used for semantic search.
CANONICAL_DENSE_DIM = 768

#: Dense dimension and model for the repo-owned semantic collection.
LOCAL_DENSE_DIM = 384
LOCAL_EMBED_MODEL = "all-MiniLM-L6-v2"

BM25_VECTOR_NAME = "text"
BM25_MODEL = "qdrant/bm25"
BM25_MAX_CHARS = 12_000

DATA_TYPE = "law"

#: Payload schema version. Local (``transcription_law``) payloads carry this at
#: the root so a reader can tell the schema-v1 shape apart from the canonical
#: one during the transition window. See ``.dev/law_ingest_payload_review.md``.
SCHEMA_VERSION = "1"

#: ``record_kind`` values. This is deliberately a **new** key rather than a
#: re-use of ``doc_type``: ``discovery/case-server/pipeline/legal_kb.js`` maps
#: ``pl.doc_type -> norm_type``, so changing ``doc_type`` to
#: ``"law_article"`` would silently break norm-type classification downstream.
RECORD_KIND_ARTICLE = "article"
RECORD_KIND_REFERENCE = "reference"

#: ``to_payload`` targets. ``canonical`` emits the production shape
#: (``la8159_law``); ``local`` emits schema v1 (``transcription_law``).
PAYLOAD_TARGET_CANONICAL = "canonical"
PAYLOAD_TARGET_LOCAL = "local"

#: Keyword payload indexes maintained on the local collection. The schema-v1
#: additions are all filterable single-token fields (``norm_type``/``scope``/
#: ``sanctions`` are keyword *arrays*, which Qdrant indexes natively), so a
#: query can ask for "constitutional duties in BR" without a full scan.
LOCAL_PAYLOAD_INDEX_FIELDS: tuple[str, ...] = (
    "original_id",
    "eli_id",
    "jurisdiction",
    "framework_code",
    "language",
    "doc_type",
    "record_kind",
    "article_number",
    "norm_type",
    "scope",
    "direction",
    "sanctions",
    "schema_version",
)

#: Locale directory (``data/law/<X>/…``) -> ISO language code.
_LOCALE_LANGUAGE = {
    "BR": "pt",
    "CL": "es",
    "CORP": "en",
}

#: Nested locale directory (``data/law/INT/<X>/…``) -> ISO language code.
_INT_LOCALE_LANGUAGE = {
    "BR": "pt",
    "EN": "en",
    "ES": "es",
}

#: Preferred locale when the same ELI appears in several languages. The live
#: ``la8159_law`` collection holds the English variant for the ``INT/BR`` ×
#: ``INT/EN`` overlap.
_DEFAULT_PREFERRED_LANGUAGE = "en"

#: Generated registry artifacts. They describe the corpus, so ingesting them
#: back into it would be self-referential; a stray copy left at the corpus root
#: must be ignored rather than counted as a law document.
_CORPUS_EXCLUDED_FILES: frozenset[str] = frozenset({"law_registry.json", "LAW_REGISTRY.md"})

_DOC_TYPE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^ABEAR", re.IGNORECASE), "Internal"),
    (re.compile(r"^(?:AN\d|DOC\d)", re.IGNORECASE), "ICAO"),
    (re.compile(r"^R\d{3}$", re.IGNORECASE), "Resolution"),
    (re.compile(r"^CDC$", re.IGNORECASE), "CDC"),
)

# ---------------------------------------------------------------------------
# Markdown parsing regexes
# ---------------------------------------------------------------------------

#: Level-3 heading (exactly three hashes) that starts an article block.
_HEADING_SPLIT_RE = re.compile(r"(?m)^###(?!#)[ \t]+")

#: ``**ELI ID:** `BR.CBA.T7.C1.Art.224` `` (also accepts the legacy ``ID ELI:``
#: label and unbolded labels).
_ELI_RE = re.compile(
    r"(?:ELI[ \t]*ID|ID[ \t]*ELI)[ \t]*:?[ \t]*\**[ \t]*`(?P<eli>[^`\n]+)`",
    re.IGNORECASE,
)

#: ``**Theme:** …`` / ``**Tema:** …``
_THEME_RE = re.compile(r"^[ \t]*\*\*(?:Theme|Tema)\s*:\*\*[ \t]*(?P<value>.*)$", re.IGNORECASE | re.MULTILINE)

#: ``**Tags:** …`` / ``**Etiquetas:** …``
_TAGS_RE = re.compile(r"^[ \t]*\*\*(?:Tags|Etiquetas)\s*:\*\*[ \t]*(?P<value>.*)$", re.IGNORECASE | re.MULTILINE)

#: A line belonging to the leading metadata block: blank, ``**Field:** …`` or a
#: horizontal rule.
_METADATA_LINE_RE = re.compile(r"^(?:\s*|\s*\*\*[^*\n]{1,60}:\*\*.*|\s*-{3,}\s*)$")

#: Trailing Markdown horizontal rule used as an article separator.
_TRAILING_RULE_RE = re.compile(r"(?:[ \t]*\n[ \t]*-{3,}[ \t]*)+\s*$")

#: Whole-document heading that marks a reference-only (non article-level) file.
_REFERENCE_ONLY_TITLE_RE = re.compile(
    r"^#\s+(?:CIVIL CODE|C[ÓO]DIGO|CODE OF CONDUCT|CODE OF ETHICS|.*Code of Conduct|.*Code of Ethics)",
    re.IGNORECASE | re.MULTILINE,
)

#: Document title (first level-1 heading).
_H1_RE = re.compile(r"^#(?!#)[ \t]+(?P<title>.+?)[ \t]*$", re.MULTILINE)

# ---------------------------------------------------------------------------
# Tag classification
# ---------------------------------------------------------------------------

#: ``**Label:** value`` anywhere in a block. Handles both the single-line
#: ``**Tags:** norm_type: duty · scope: state`` style and the inline
#: pipe-separated ``**Norm type:** procedure | **Scope:** administrative`` style.
#: The value stops at ``|`` or end-of-line, so the next inline field is not
#: swallowed.
_TAG_FIELD_RE = re.compile(r"\*\*(?P<label>[^*\n:]{1,40}?)\s*:\*\*[ \t]*(?P<value>[^|\n]*)", re.IGNORECASE)

#: Token separator inside a ``**Tags:**`` line. The corpus uses ``·`` (1266
#: occurrences), but a few files separate tokens with ``,``. A comma only splits
#: when what follows it is label-shaped (``scope: …``), so a genuinely
#: multi-valued token such as ``norm_type: duty, penalty`` stays intact.
_TAG_TOKEN_SPLIT_RE = re.compile(r"\s*·\s*|,\s*(?=[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ _-]{0,39}\s*:)", re.IGNORECASE)

#: Separator for a multi-valued classification field (``sanctions: a, b``).
_TAG_MULTI_VALUE_RE = re.compile(r"[,;]")

#: Keys observed inside ``**Tags:**`` / ``**Etiquetas:**`` lines, accent-folded and
#: lowercased. The corpus is bilingual: ``tipo_norma`` (230 blocks) and ``âmbito``
#: (198 blocks) carry the same information as ``norm_type`` / ``scope``, and
#: dropping them would silently lose the classification of ~20% of the corpus.
_TAG_KEY_ALIASES: dict[str, str] = {
    "norm_type": "norm_type",
    "norma": "norm_type",
    "tipo": "norm_type",
    "tipo_norma": "norm_type",
    "tipo_de_norma": "norm_type",
    "scope": "scope",
    "escopo": "scope",
    "ambito": "scope",
    "alcance": "scope",
    "direction": "direction",
    "direcao": "direction",
    "direccion": "direction",
    "sentido": "direction",
    "sanctions": "sanctions",
    "sanction": "sanctions",
    "sancao": "sanctions",
    "sancoes": "sanctions",
    "sanciones": "sanctions",
}

#: Structured fields that can legitimately hold several values. ``direction`` is
#: deliberately absent: it is single-valued in the corpus.
_TAG_LIST_FIELDS: frozenset[str] = frozenset({"norm_type", "scope", "sanctions"})

#: Keys of the value returned by :func:`parse_article_tags`.
TAG_FIELDS: tuple[str, ...] = ("norm_type", "scope", "direction", "sanctions", "tags")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def sha256_short(text: str, length: int = 16) -> str:
    """Return a truncated SHA-256 hex digest of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def stable_point_id(original_id: str) -> str:
    """Deterministic Qdrant point ID for an article ELI."""
    return str(uuid.uuid5(LAW_ID_NAMESPACE, original_id))


def localized_point_id(original_id: str, language: str) -> str:
    """Point ID for a *language-qualified* article (multi-language indexing)."""
    return str(uuid.uuid5(LAW_ID_NAMESPACE, f"{original_id}|{language}"))


def placeholder_dense_vector(seed: str, dim: int = CANONICAL_DENSE_DIM) -> list[float]:
    """Deterministic unit vector for collections whose embedding model is gone.

    ``la8159_law`` is a *payload* store: callers look articles up by ELI/payload
    filter, not by dense similarity. This keeps the schema valid without
    inventing semantics. **Never** use these vectors for semantic search.
    """
    state = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:8], "big")
    values: list[float] = []
    mask = (1 << 64) - 1
    for _ in range(dim):
        state = (state * 6364136223846793005 + 1442695040888963407) & mask
        values.append(((state >> 33) / (1 << 31)) - 1.0)
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def language_for_path(path: Path, root: Path | None = None) -> str:
    """Infer the ISO language code from the file's locale directory."""
    try:
        rel = path.relative_to(root) if root is not None else path
    except ValueError:
        rel = path
    parts = rel.parts
    if len(parts) >= 3 and parts[0].upper() == "INT":
        return _INT_LOCALE_LANGUAGE.get(parts[1].upper(), "en")
    if parts:
        return _LOCALE_LANGUAGE.get(parts[0].upper(), "pt")
    return "pt"


def doc_type_for(framework_code: str) -> str:
    """Deterministic document type for a framework code.

    The legacy ``la8159_law`` payloads carry an inconsistent ``doc_type``
    (e.g. ``DOC4444`` is split between ``ICAO`` and ``Internal``). This function
    replaces that with an explicit, reproducible mapping; the validator reports
    how many points would change.
    """
    for pattern, value in _DOC_TYPE_RULES:
        if pattern.match(framework_code or ""):
            return value
    return "unknown"


def split_eli(eli: str) -> tuple[str, str]:
    """``"BR.CBA.T7.C1.Art.224"`` -> ``("BR", "CBA")``."""
    parts = eli.split(".")
    jurisdiction = parts[0] if parts and parts[0] else ""
    framework_code = parts[1] if len(parts) > 1 else ""
    return jurisdiction, framework_code


def article_number_for(eli: str) -> str:
    """Extract the article number from an ELI.

    ``"BR.CBA.T3.C1.Art.74"`` -> ``"74"`` and
    ``"INT.DOC4444.C15.S1.P2.Art.15.1.2"`` -> ``"15.1.2"``: everything after the
    **final** ``Art.`` token, with sub-numbers preserved.

    Naively taking the first segment after ``Art.`` (or splitting the whole ELI)
    is wrong: 69 corpus ELIs carry no ``Art.`` token at all
    (``BR.ABEAR_COC.SA.I``, ``BR.D1171.Anexo.C1.S1.II``…) and would yield the
    *jurisdiction* instead of the article number. Those fall back to the last ELI
    segment.

    This is a convenience field for lookups — it is **not** part of point
    identity. ``(framework_code, article_number)`` collides for 301 of the 1119
    corpus articles, so point IDs stay ``uuid5(NAMESPACE_DNS, eli)``.
    """
    _head, separator, tail = eli.rpartition(".Art.")
    if separator and tail:
        return tail.strip()
    parts = [part for part in eli.split(".") if part]
    return parts[-1] if parts else ""


def normalize_content(content: str, *, keep_separator: bool = True) -> str:
    """Normalise an article body.

    The trailing ``---`` in the source Markdown is an authoring separator that
    the production collection mostly keeps (752 of 1119 live payloads end with
    it), so it is **preserved by default** to keep payloads byte-identical to
    the authored corpus. Measured parity against ``la8159_law``:

    ``keep_separator=True``  788 / 1119 exact
    ``keep_separator=False`` 339 / 1119 exact

    Pass ``keep_separator=False`` for cleaner BM25 tokens / embedding text.

    Neither flag reaches parity, and the 331 misses with the default are *four*
    distinct causes, only one of which this function owns:

    * **280** differ only in trailing whitespace / the ``---`` separator: the
      projection *adds* a separator the live payload does not carry.
    * **45** differ because the live ``text`` retains metadata labels
      (``**Norm type:** …``, ``**Hierarchy:** …``) that :func:`parse_article_blocks`
      classifies as metadata and therefore excludes from the body. The stale
      payloads were written by an older rule that only stripped the ``ELI ID``
      line; the current convention is body-only.
    * **5** differ substantively because a *body-opening* paragraph is absorbed
      into the metadata block and dropped from the body (``**Agente Público:** …``
      in the four ABEAR files, ``**Dirección General de Aeronáutica Civil:** …``
      in ``CL.DAN17``). This is the only genuine parser defect of the four.
    * **1** (``INT.AN9.C6.S45.Art.6.45``) carries a stray editorial token in the
      live payload and is not a parser issue at all.

    See ``.dev/law_ingest_payload_review.md`` § "What the migration diff found".
    """
    text = content.strip()
    if not keep_separator:
        text = _TRAILING_RULE_RE.sub("", text).strip()
    return text


def _iso_now() -> str:
    """Naive UTC timestamp — the canonical ``metadata.ingestion_time`` format.

    Kept byte-stable on purpose: canonical payloads are shared with sibling
    projects, so their timestamps must not change format.
    """
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def _iso_utc_now() -> str:
    """ISO-8601 UTC with an explicit ``Z`` — the schema-v1 lifecycle stamp."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LawArticle:
    """A single indexable law article extracted from the Markdown corpus."""

    original_id: str
    title: str
    theme: str
    tags: str
    content: str
    source_file: str
    source_path: str
    jurisdiction: str
    framework_code: str
    language: str
    doc_type: str
    # --- schema v1 additions (see .dev/law_ingest_payload_review.md) ---
    #: ELI, dual-written with ``original_id`` during the transition. Both are
    #: identity and both are immutable; ``eli_id`` exists so the field can be
    #: renamed on the sibling readers' schedule rather than ours.
    eli_id: str = ""
    #: Article number derived from the ELI (``Art.15.1.2`` -> ``"15.1.2"``). A
    #: convenience scalar — **not** part of point identity.
    article_number: str = ""
    #: Structured classification parsed from the bilingual tag block.
    norm_type: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()
    direction: str | None = None
    sanctions: tuple[str, ...] = ()
    #: Raw ``·``-separated tag tokens, kept for display and round-tripping.
    tag_tokens: tuple[str, ...] = ()
    #: ``True`` for files that carry no indexable article body.
    reference_only: bool = False

    def __post_init__(self) -> None:
        # ``eli_id`` mirrors ``original_id``; keeping the default empty means
        # every existing construction site keeps working unchanged.
        if not self.eli_id:
            object.__setattr__(self, "eli_id", self.original_id)
        if not self.article_number:
            object.__setattr__(self, "article_number", article_number_for(self.original_id))

    @property
    def sha256_short(self) -> str:
        """16-char display digest of the article body (the canonical payload key)."""
        return sha256_short(self.content)

    @property
    def sha256_full(self) -> str:
        """Full 64-hex digest of the article body, for cache-drift comparisons."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    @property
    def record_kind(self) -> str:
        return RECORD_KIND_REFERENCE if self.reference_only else RECORD_KIND_ARTICLE

    @property
    def point_id(self) -> str:
        return stable_point_id(self.original_id)

    def embed_text(self) -> str:
        """Text used for semantic embedding (local collection only)."""
        header = " — ".join(part for part in (self.title, self.theme, self.tags) if part)
        return f"{header}\n\n{self.content}".strip()

    def local_payload(self, *, ingestion_time: str | None = None) -> dict[str, Any]:
        """Schema v1 payload for the repo-owned ``transcription_law`` collection.

        Differences from the canonical shape, all deliberate:

        * ``original_id`` **and** ``eli_id`` are both written (transition window).
        * ``tags`` is a ``list`` of structured tokens instead of a display string,
          alongside the parsed ``norm_type``/``scope``/``direction``/``sanctions``.
        * No ``original_data``: it duplicates ~36% of the payload and has no
          reader. The canonical copy is untouched.
        * ``content`` stays an alias of ``text``, and ``doc_type`` keeps its
          canonical values because a sibling reader consumes them as ``norm_type``.
        * ``source_sha256`` is the full digest; ``sha256_short`` was its
          16-character display form.
        """
        stamp = ingestion_time or _iso_utc_now()
        return {
            "eli_id": self.eli_id,
            "original_id": self.original_id,
            "article_number": self.article_number,
            "framework_code": self.framework_code,
            "jurisdiction": self.jurisdiction,
            "title": self.title,
            "theme": self.theme,
            "norm_type": list(self.norm_type),
            "scope": list(self.scope),
            "direction": self.direction,
            "sanctions": list(self.sanctions),
            "tags": list(self.tag_tokens),
            "content": self.content,
            "text": self.content,
            "source_file": self.source_file,
            "source_path": self.source_path,
            "source_sha256": self.sha256_full,
            "language": self.language,
            "doc_type": self.doc_type,
            "record_kind": self.record_kind,
            "reference_only": self.reference_only,
            "data_type": DATA_TYPE,
            "schema_version": SCHEMA_VERSION,
            "ingested_at": stamp,
            "updated_at": stamp,
        }

    def to_payload(
        self,
        point_id: str,
        *,
        target: str = PAYLOAD_TARGET_CANONICAL,
        include_framework_fields: bool = False,
        ingestion_time: str | None = None,
        include_extra: bool = False,
    ) -> dict[str, Any]:
        """Build the payload for ``target``.

        ``target="local"`` emits schema v1 (see :meth:`local_payload`).
        ``target="canonical"`` emits the production ``la8159_law`` shape — the
        flat + ``original_data`` + ``metadata`` structure documented in
        ``discovery/ref_docs/law-ingestion-guide.md`` — which is shared with
        sibling projects and is therefore **additive only**: every existing key
        keeps its current value and meaning, and only ``eli_id``,
        ``record_kind``, ``article_number`` and ``schema_version`` are added.
        """
        if target == PAYLOAD_TARGET_LOCAL:
            return self.local_payload(ingestion_time=ingestion_time)
        if target != PAYLOAD_TARGET_CANONICAL:
            raise ValueError(f"unknown payload target: {target!r}")

        original_data = {
            "id": point_id,
            "title": self.title,
            "source_file": self.source_file,
            "theme": self.theme,
            "tags": self.tags,
            "content": self.content,
            "original_id": self.original_id,
        }
        payload: dict[str, Any] = {
            "original_id": self.original_id,
            "eli_id": self.eli_id,
            "title": self.title,
            "text": self.content,
            "content": self.content,
            "theme": self.theme,
            "tags": self.tags,
            "source_file": self.source_file,
            "doc_type": self.doc_type,
            "article_number": self.article_number,
            "record_kind": self.record_kind,
            "schema_version": SCHEMA_VERSION,
            "original_data": original_data,
            "metadata": {
                "data_type": DATA_TYPE,
                "doc_type": self.doc_type,
                "ingestion_time": ingestion_time or _iso_now(),
            },
        }
        if include_framework_fields:
            payload["framework_code"] = self.framework_code
            payload["jurisdiction"] = self.jurisdiction
        if include_extra:
            payload["language"] = self.language
            payload["sha256_short"] = self.sha256_short
            payload["source_path"] = self.source_path
        return payload


# ---------------------------------------------------------------------------
# Payload editing
# ---------------------------------------------------------------------------

#: Payload keys a human is allowed to edit from the registry UI.
EDITABLE_PAYLOAD_FIELDS: frozenset[str] = frozenset(
    {"title", "theme", "tags", "content", "text", "source_file", "doc_type"},
)

#: Payload keys this module owns. A caller can read them but never set them
#: directly, so a user-supplied mapping cannot smuggle in a vector, a point id
#: or a derived field (``sha256_short`` must stay a truthful digest).
_IMMUTABLE_PAYLOAD_FIELDS: frozenset[str] = frozenset(
    {
        "original_id",
        "eli_id",
        "original_data",
        "metadata",
        "framework_code",
        "jurisdiction",
        "language",
        "sha256_short",
        "source_sha256",
        "source_path",
        "article_number",
        "record_kind",
        "reference_only",
        "norm_type",
        "scope",
        "direction",
        "sanctions",
        "data_type",
        "schema_version",
        "ingested_at",
        "updated_at",
    },
)

#: ``original_data`` is a nested mirror of these flat payload fields. Downstream
#: consumers read the nested copy, so every edit has to be written to both.
_ORIGINAL_DATA_MIRROR: tuple[str, ...] = ("title", "theme", "tags", "content", "source_file")


class PayloadEditError(ValueError):
    """Raised when a requested payload edit is rejected."""


def build_payload_patch(
    fields: Mapping[str, Any],
    *,
    existing: Mapping[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build a schema-consistent payload patch from user-supplied ``fields``.

    The patch is deliberately *surgical* — it is handed straight to
    ``set_payload``, which merges it into the live point and leaves the dense
    vector untouched. Guarantees:

    * only :data:`EDITABLE_PAYLOAD_FIELDS` are accepted; unknown or immutable
      keys raise :class:`PayloadEditError` rather than silently corrupting a
      point shared with sibling projects;
    * ``content`` and ``text`` are aliases: editing either rewrites the other,
      and re-derives the body digest (``sha256_short`` on canonical,
      ``source_sha256`` on the schema-v1 local shape);
    * ``content`` may not be emptied;
    * ``tags`` is a display ``str`` on canonical and a ``list`` on local; a list
      is only accepted for a local-schema payload so the shared canonical shape
      cannot drift;
    * on canonical, ``original_data`` — the nested mirror other services read —
      is kept in step with the flat keys, and ``metadata.updated_at`` records the
      edit without clobbering ``metadata.ingestion_time``;
    * on local, the edit stamps the top-level ``updated_at`` instead, leaving
      ``ingested_at`` intact.
    """
    if not fields:
        raise PayloadEditError("no fields supplied")

    rejected = sorted(set(fields) - EDITABLE_PAYLOAD_FIELDS)
    if rejected:
        hint = ""
        if any(key in _IMMUTABLE_PAYLOAD_FIELDS for key in rejected):
            hint = " (immutable: derived or owned by the ingester)"
        raise PayloadEditError(f"field(s) not editable: {', '.join(rejected)}{hint}")

    existing_map: Mapping[str, Any] = existing if isinstance(existing, Mapping) else {}
    local_schema = "schema_version" in existing_map

    patch: dict[str, Any] = {}
    for key, value in fields.items():
        if key == "tags" and isinstance(value, list):
            if not local_schema:
                raise PayloadEditError("field 'tags' must be a string on the canonical schema")
            if not all(isinstance(item, str) for item in value):
                raise PayloadEditError("field 'tags' must be a list of strings")
            patch[key] = list(value)
            continue
        if not isinstance(value, str):
            raise PayloadEditError(f"field {key!r} must be a string, got {type(value).__name__}")
        patch[key] = value

    # ``content`` and ``text`` are aliases; ``content`` wins when both are given.
    if "content" in patch:
        if not patch["content"].strip():
            raise PayloadEditError("content may not be empty")
        patch["text"] = patch["content"]
    elif "text" in patch:
        if not patch["text"].strip():
            raise PayloadEditError("content may not be empty")
        patch["content"] = patch["text"]

    # Keep the BM25 source text and the digest in step with the body. The digest
    # key differs per schema: canonical carries the 16-char ``sha256_short``,
    # schema v1 carries the full ``source_sha256``.
    if "content" in patch:
        digest = hashlib.sha256(patch["content"].encode("utf-8")).hexdigest()
        if local_schema:
            patch["source_sha256"] = digest
        else:
            patch["sha256_short"] = sha256_short(patch["content"])

    if local_schema:
        # Schema v1 has no ``original_data`` mirror and no ``metadata`` block.
        patch["updated_at"] = timestamp or _iso_utc_now()
        return patch

    # Mirror the flat edits into ``original_data`` without dropping its sibling
    # keys (``id``, ``original_id``).
    mirror_source = existing_map.get("original_data")
    mirrored = dict(mirror_source) if isinstance(mirror_source, Mapping) else {}
    for key in _ORIGINAL_DATA_MIRROR:
        if key in patch:
            mirrored[key] = patch[key]
    if mirrored:
        patch["original_data"] = mirrored

    # Merge metadata so the ingestion timestamp survives an edit.
    live_metadata = existing_map.get("metadata")
    metadata = dict(live_metadata) if isinstance(live_metadata, Mapping) else {}
    metadata["updated_at"] = timestamp or _iso_now()
    patch["metadata"] = metadata

    return patch


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _is_metadata_line(line: str) -> bool:
    return bool(_METADATA_LINE_RE.match(line))


def parse_article_blocks(text: str) -> Iterator[tuple[str, str, str]]:
    """Yield ``(title, metadata_text, body_text)`` for every level-3 block."""
    for chunk in _HEADING_SPLIT_RE.split(text)[1:]:
        lines = chunk.split("\n")
        title = lines[0].strip()
        index = 1
        # Skip the leading metadata block (blank lines / ``**Field:** …`` / ``---``).
        while index < len(lines) and _is_metadata_line(lines[index]):
            index += 1
        yield title, "\n".join(lines[1:index]), "\n".join(lines[index:])


def _fold_tag_label(label: str) -> str:
    """Accent-fold + lowercase a field label so ``âmbito`` and ``ambito`` agree."""
    decomposed = unicodedata.normalize("NFKD", label)
    ascii_only = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[\s-]+", "_", ascii_only.strip().lower())


def _split_tag_values(raw: str) -> list[str]:
    """Split a comma/semicolon-joined classification value, preserving order."""
    values: dict[str, None] = {}
    for part in _TAG_MULTI_VALUE_RE.split(raw):
        token = part.strip()
        if token:
            values.setdefault(token, None)
    return list(values)


def _assign_tag_value(out: dict[str, Any], field_name: str, raw: str) -> None:
    values = _split_tag_values(raw)
    if not values:
        return
    if field_name in _TAG_LIST_FIELDS:
        bucket: list[str] = out[field_name]
        for value in values:
            if value not in bucket:
                bucket.append(value)
    else:
        out[field_name] = values[0]


def parse_article_tags(block: str) -> dict[str, Any]:
    """Extract the structured classification out of an article's metadata block.

    The corpus writes the same information three ways and in two languages::

        **Tags:** norm_type: duty · scope: criminal · sanctions: financial_penalty
        **Etiquetas:** tipo_norma: dever · escopo: constitucional
        **Norm type:** procedure | **Direction:** mandatory | **Scope:** administrative

    All of them resolve to the same fields, so a query can filter on
    ``norm_type``/``scope`` instead of substring-matching a display string.

    Returns ``{norm_type, scope, direction, sanctions, tags}``. ``norm_type``,
    ``scope`` and ``sanctions`` are lists because the corpus carries genuinely
    multi-valued tokens (``norm_type: duty, penalty``); ``direction`` is a scalar
    or ``None``; ``tags`` keeps the raw tokens for display and round-tripping —
    including tokens reconstructed from the inline style, which has no
    ``**Tags:**`` line of its own.

    English-only key matching loses roughly a fifth of the corpus:
    ``tipo_norma`` (230 blocks) and ``âmbito`` (198 blocks) fold into
    ``norm_type`` and ``scope`` here.
    """
    out: dict[str, Any] = {"norm_type": [], "scope": [], "direction": None, "sanctions": [], "tags": []}
    raw_tokens: list[str] = out["tags"]

    def remember(token: str) -> None:
        if token and token not in raw_tokens:
            raw_tokens.append(token)

    tags_match = _TAGS_RE.search(block)
    if tags_match:
        for token in (raw.strip() for raw in _TAG_TOKEN_SPLIT_RE.split(tags_match.group("value"))):
            if not token:
                continue
            remember(token)
            key, separator, value = token.partition(":")
            if not separator:
                continue
            field_name = _TAG_KEY_ALIASES.get(_fold_tag_label(key))
            if field_name:
                _assign_tag_value(out, field_name, value)

    for field_match in _TAG_FIELD_RE.finditer(block):
        field_name = _TAG_KEY_ALIASES.get(_fold_tag_label(field_match.group("label")))
        if field_name:
            value = field_match.group("value")
            _assign_tag_value(out, field_name, value)
            remember(f"{field_name}: {value.strip()}")

    return out


def _flatten_tags(raw: Any) -> str:
    """``tags`` is a ``str`` on canonical and a ``list`` on the schema-v1 local shape."""
    if isinstance(raw, list):
        return " · ".join(str(item) for item in raw)
    return raw if isinstance(raw, str) else ""


@dataclass(slots=True)
class FileReport:
    """Per-file result of parsing the corpus."""

    rel_path: str
    language: str
    reference_only: bool
    articles_local: int
    title: str = ""
    elis: list[str] = field(default_factory=list)
    blocks_without_eli: int = 0
    reference_note: str | None = None

    @property
    def unique_elis(self) -> list[str]:
        """Unique ELIs in file order (a file may repeat an article)."""
        return list(dict.fromkeys(self.elis))

    def as_dict(self) -> dict[str, Any]:
        return {
            "file": self.rel_path,
            "language": self.language,
            "title": self.title,
            "reference_only": self.reference_only,
            "reference_note": self.reference_note,
            "articles_local": self.articles_local,
            "blocks_without_eli": self.blocks_without_eli,
            "eli": list(self.elis),
        }


@dataclass(slots=True)
class CorpusPlan:
    """A parsed, de-duplicated corpus ready for ingestion."""

    articles: list[LawArticle] = field(default_factory=list)
    files: list[FileReport] = field(default_factory=list)
    collisions: dict[str, list[str]] = field(default_factory=dict)
    blocks_total: int = 0
    blocks_without_eli: int = 0
    reference_only_files: list[str] = field(default_factory=list)
    skipped_variants: list[tuple[str, str]] = field(default_factory=list)

    @property
    def by_original_id(self) -> dict[str, LawArticle]:
        return {a.original_id: a for a in self.articles}

    @property
    def languages(self) -> Counter[str]:
        return Counter(a.language for a in self.articles)

    def as_dict(self) -> dict[str, Any]:
        return {
            "files": len(self.files),
            "reference_only_files": self.reference_only_files,
            "blocks_total": self.blocks_total,
            "blocks_without_eli": self.blocks_without_eli,
            "articles_with_eli": len(self.articles),
            "unique_elis": len(self.by_original_id),
            "collisions": {k: v for k, v in self.collisions.items()},
            "language_breakdown": dict(self.languages),
        }


class LawCorpusParser:
    """Parse ``data/law/**/*.md`` into :class:`LawArticle` records."""

    def __init__(
        self,
        *,
        preferred_language: str = _DEFAULT_PREFERRED_LANGUAGE,
        keep_all_languages: bool = False,
        keep_separator: bool = True,
        exclude_dirs: Iterable[str] = ("_mapping",),
        exclude_files: Iterable[str] = _CORPUS_EXCLUDED_FILES,
    ) -> None:
        self.preferred_language = preferred_language
        self.keep_all_languages = keep_all_languages
        self.keep_separator = keep_separator
        self.exclude_dirs = set(exclude_dirs)
        self.exclude_files = set(exclude_files)

    # -- file discovery ----------------------------------------------------
    def iter_files(self, root: Path) -> list[Path]:
        return sorted(
            p
            for p in root.rglob("*.md")
            if not (self.exclude_dirs & set(p.parts)) and p.name not in self.exclude_files
        )

    # -- single file -------------------------------------------------------
    def parse_file(self, path: Path, *, root: Path | None = None) -> tuple[list[LawArticle], FileReport]:
        text = path.read_text(encoding="utf-8")
        language = language_for_path(path, root)
        try:
            rel_path = str(path.relative_to(root)) if root is not None else path.name
        except ValueError:
            rel_path = path.name

        articles: list[LawArticle] = []
        without_eli = 0
        for title, meta, body in parse_article_blocks(text):
            match = _ELI_RE.search(meta)
            if not match:
                without_eli += 1
                continue
            eli = match.group("eli").strip()
            theme_match = _THEME_RE.search(meta)
            tags_match = _TAGS_RE.search(meta)
            parsed_tags = parse_article_tags(meta)
            jurisdiction, framework_code = split_eli(eli)
            articles.append(
                LawArticle(
                    original_id=eli,
                    title=title,
                    theme=theme_match.group("value").strip() if theme_match else "",
                    tags=tags_match.group("value").strip() if tags_match else "",
                    content=normalize_content(body, keep_separator=self.keep_separator),
                    source_file=path.name,
                    # Project-relative so a payload is portable across machines.
                    source_path=rel_path,
                    jurisdiction=jurisdiction,
                    framework_code=framework_code,
                    language=language,
                    doc_type=doc_type_for(framework_code),
                    article_number=article_number_for(eli),
                    norm_type=tuple(parsed_tags["norm_type"]),
                    scope=tuple(parsed_tags["scope"]),
                    direction=parsed_tags["direction"],
                    sanctions=tuple(parsed_tags["sanctions"]),
                    tag_tokens=tuple(parsed_tags["tags"]),
                )
            )

        reference_only = not articles
        note: str | None = None
        if reference_only:
            if _REFERENCE_ONLY_TITLE_RE.search(text):
                note = "whole-code / institutional document (no article ELIs)"
            elif without_eli:
                note = "no ELI labels found"
            else:
                note = "no article blocks found"

        title_match = _H1_RE.search(text)
        unique_elis = list(dict.fromkeys(a.original_id for a in articles))
        report = FileReport(
            rel_path=rel_path,
            language=language,
            reference_only=reference_only,
            articles_local=len(unique_elis),
            title=title_match.group("title").strip() if title_match else "",
            elis=[a.original_id for a in articles],
            blocks_without_eli=without_eli,
            reference_note=note,
        )
        return articles, report

    # -- whole corpus ------------------------------------------------------
    def build_plan(self, root: Path) -> CorpusPlan:
        plan = CorpusPlan()
        grouped: dict[str, list[LawArticle]] = defaultdict(list)

        for path in self.iter_files(root):
            articles, report = self.parse_file(path, root=root)
            plan.files.append(report)
            plan.blocks_total += report.articles_local + report.blocks_without_eli
            plan.blocks_without_eli += report.blocks_without_eli
            if report.reference_only:
                plan.reference_only_files.append(report.rel_path)
            for article in articles:
                grouped[article.original_id].append(article)

        def rel(article: LawArticle) -> str:
            path = Path(article.source_path)
            if not path.is_absolute():
                # ``parse_file`` stores a project-relative path, which is
                # already what a report wants.
                return str(path)
            try:
                return str(path.relative_to(root))
            except ValueError:
                return article.source_file

        for eli, variants in grouped.items():
            if len(variants) == 1:
                plan.articles.append(variants[0])
                continue
            # Same ELI in several locales (the INT/BR × INT/EN pairs share a
            # basename, so report the corpus-relative path to disambiguate).
            plan.collisions[eli] = [rel(v) for v in variants]
            if self.keep_all_languages:
                plan.articles.extend(variants)
                continue
            chosen = self._pick_variant(variants)
            plan.articles.append(chosen)
            for variant in variants:
                if variant is not chosen:
                    plan.skipped_variants.append((eli, rel(variant)))

        plan.articles.sort(key=lambda a: a.original_id)
        return plan

    def _pick_variant(self, variants: Sequence[LawArticle]) -> LawArticle:
        for variant in variants:
            if variant.language == self.preferred_language:
                return variant
        return variants[0]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class IngestStats:
    """Accounting for one ingestion run against one collection."""

    target: str = ""
    scanned: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    embedded: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def upserted(self) -> int:
        return self.created + self.updated

    def add_failure(self, reason: str, **context: Any) -> None:
        self.failed += 1
        if len(self.failures) < 20:
            self.failures.append({"reason": reason, **context})

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "scanned": self.scanned,
            "created": self.created,
            "updated": self.updated,
            "upserted": self.upserted,
            "skipped": self.skipped,
            "failed": self.failed,
            "embedded": self.embedded,
            "notes": list(self.notes),
            "failures": list(self.failures),
        }


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------
def normalize_qdrant_url(raw_url: str | None) -> str:
    value = (raw_url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else value


def normalize_qdrant_api_key(raw_key: str | None) -> str:
    key = (raw_key or "").strip()
    if not key or "|" not in key:
        return key
    parts = [p.strip() for p in key.split("|") if p.strip()]
    return max(parts, key=len) if parts else key


def build_qdrant_client(url: str | None, api_key: str | None) -> QdrantClient:
    """Create a client that tolerates minor client/server version skew."""
    return QdrantClient(
        url=normalize_qdrant_url(url) or None,
        api_key=normalize_qdrant_api_key(api_key) or None,
        timeout=60,
        check_compatibility=False,
    )


def _scroll_all(
    client: QdrantClient,
    collection: str,
    *,
    with_payload: bool = True,
    page: int = 500,
) -> list[qm.Record]:
    records: list[qm.Record] = []
    offset: Any = None
    while True:
        batch, offset = client.scroll(
            collection_name=collection,
            limit=page,
            offset=offset,
            with_payload=with_payload,
            with_vectors=False,  # NOTE: plural — `with_vector=` raises in client >= 1.13
        )
        records.extend(batch)
        if offset is None:
            break
    return records


def _payload_filter(key: str, value: str) -> qm.Filter:
    return qm.Filter(must=[qm.FieldCondition(key=key, match=qm.MatchValue(value=value))])


# ---------------------------------------------------------------------------
# Payload diffing (migration planning)
# ---------------------------------------------------------------------------
#: Payload keys whose value is a write timestamp, so it differs on every run.
#: Excluded from *value* comparison so a migration diff stays stable across
#: runs; presence/absence of the key is still reported.
VOLATILE_PAYLOAD_KEYS: frozenset[str] = frozenset({"ingested_at", "updated_at"})

#: Nested volatile keys, per parent key.
_NESTED_VOLATILE_KEYS: dict[str, tuple[str, ...]] = {"metadata": ("ingestion_time",)}


def payload_bytes(payload: Mapping[str, Any]) -> int:
    """Serialised size of a payload, used as the byte-delta proxy.

    Qdrant stores payloads as JSON, so the compact JSON encoding of the dict is
    a stable stand-in for the stored size (it ignores pre-existing compression).
    """
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))


def _strip_volatile(payload: Mapping[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in payload.items() if key not in VOLATILE_PAYLOAD_KEYS}
    for key, nested in _NESTED_VOLATILE_KEYS.items():
        value = out.get(key)
        if isinstance(value, dict):
            out[key] = {k: v for k, v in value.items() if k not in nested}
    return out


@dataclass(frozen=True, slots=True)
class PayloadDiff:
    """Field-level difference between a live payload and its projected form."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    live_bytes: int = 0
    wanted_bytes: int = 0

    @property
    def byte_delta(self) -> int:
        """``wanted - live`` serialised bytes; negative means the rewrite shrinks."""
        return self.wanted_bytes - self.live_bytes

    @property
    def touched(self) -> tuple[str, ...]:
        return tuple(sorted({*self.added, *self.removed, *self.changed}))

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
            "unchanged": list(self.unchanged),
            "byte_delta": self.byte_delta,
            "live_bytes": self.live_bytes,
            "wanted_bytes": self.wanted_bytes,
        }


def diff_payloads(live: Mapping[str, Any], wanted: Mapping[str, Any]) -> PayloadDiff:
    """Compare a live payload with the payload the current writer would emit.

    Only the *keys* and their values are compared — this never writes.

    Added/removed are computed from the **raw** key sets, so a brand-new
    timestamp key (``ingested_at``) is correctly reported as added. Value
    comparison then ignores volatile keys, so a timestamp that merely moves
    forward does not register as a change.
    """
    added = tuple(sorted(set(wanted) - set(live)))
    removed = tuple(sorted(set(live) - set(wanted)))
    left, right = _strip_volatile(live), _strip_volatile(wanted)
    shared = set(left) & set(right)
    changed = tuple(sorted(key for key in shared if left[key] != right[key]))
    unchanged = tuple(sorted(key for key in shared if left[key] == right[key]))
    return PayloadDiff(
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
        live_bytes=payload_bytes(live),
        wanted_bytes=payload_bytes(wanted),
    )


def point_id_for(article: LawArticle, *, multi_language: bool = False) -> str:
    """The point ID the ingest paths would use for ``article``."""
    if multi_language:
        return localized_point_id(article.original_id, article.language)
    return stable_point_id(article.original_id)


# ---------------------------------------------------------------------------
# Canonical ingestion (non-destructive)
# ---------------------------------------------------------------------------
class CanonicalLawIngester:
    """Refresh the shared ``la8159_law`` / ``la8159_law_bm25`` collections.

    Existing points are never re-created: their payload is updated in place, so
    the original 768-dim dense vectors survive. BM25 sparse vectors are derived
    from the article text and are therefore regenerated freely.
    """

    def __init__(
        self,
        client: QdrantClient,
        *,
        collection: str = CANONICAL_COLLECTION,
        bm25_collection: str = CANONICAL_BM25_COLLECTION,
        dense_dim: int = CANONICAL_DENSE_DIM,
        batch_size: int = 128,
        sleep_between_batches: float = 0.0,
    ) -> None:
        self.client = client
        self.collection = collection
        self.bm25_collection = bm25_collection
        self.dense_dim = dense_dim
        self.batch_size = max(1, batch_size)
        self.sleep_between_batches = sleep_between_batches

    # -- inspection --------------------------------------------------------
    def article_count(self) -> int:
        return self.client.count(collection_name=self.collection, exact=True).count

    def existing_index(self) -> dict[str, str]:
        """Map ``original_id`` -> existing point ID for the whole collection."""
        index: dict[str, str] = {}
        for record in _scroll_all(self.client, self.collection):
            original_id = (record.payload or {}).get("original_id")
            if original_id:
                index[str(original_id)] = str(record.id)
        return index

    # -- writing -----------------------------------------------------------
    def ingest(
        self,
        articles: Sequence[LawArticle],
        *,
        existing: dict[str, str] | None = None,
        dry_run: bool = False,
        allow_new: bool = False,
        refresh_payloads: bool = True,
        refresh_bm25: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> IngestStats:
        stats = IngestStats(target="canonical")
        stats.scanned = len(articles)
        if existing is None:
            existing = self.existing_index()

        timestamp = _iso_now()
        to_create: list[tuple[LawArticle, str]] = []
        to_refresh: list[tuple[LawArticle, str]] = []

        for article in articles:
            point_id = existing.get(article.original_id)
            if point_id:
                to_refresh.append((article, point_id))
            elif allow_new:
                to_create.append((article, stable_point_id(article.original_id)))
            else:
                stats.skipped += 1
                stats.add_failure("article_not_in_collection", original_id=article.original_id)

        stats.notes.append(f"existing_points={len(existing)}")
        if not allow_new and stats.skipped:
            stats.notes.append(
                f"{stats.skipped} article(s) absent from {self.collection}; "
                "pass allow_new=True to create them with placeholder dense vectors"
            )

        touched = len(to_refresh) + len(to_create)
        if dry_run:
            # ``refresh_payloads`` is False in incremental mode, so the preview
            # must not claim a payload rewrite that a real run would not do.
            payload_targets = len(to_refresh) if refresh_payloads else 0
            stats.notes.append(
                f"dry-run: would refresh payload for {payload_targets} point(s), "
                f"would create {len(to_create)} point(s), would upsert "
                f"{touched if refresh_bm25 else 0} BM25 point(s)"
            )
            return stats

        # 1) refresh payloads in place (dense vectors untouched)
        if refresh_payloads:
            done = 0
            for batch in _chunks(to_refresh, self.batch_size):
                try:
                    self._set_payloads(batch, timestamp)
                    stats.updated += len(batch)
                except Exception as exc:  # noqa: BLE001
                    for article, _pid in batch:
                        stats.add_failure("set_payload_failed", original_id=article.original_id, error=str(exc))
                done += len(batch)
                if on_progress:
                    on_progress("payloads", done, len(to_refresh))
                if self.sleep_between_batches:
                    time.sleep(self.sleep_between_batches)

        # 2) create genuinely new points (placeholder dense vector)
        done = 0
        for batch in _chunks(to_create, self.batch_size):
            try:
                self._create_points(batch, timestamp)
                stats.created += len(batch)
            except Exception as exc:  # noqa: BLE001
                for article, _pid in batch:
                    stats.add_failure("create_failed", original_id=article.original_id, error=str(exc))
            done += len(batch)
            if on_progress:
                on_progress("creating", done, len(to_create))
            if self.sleep_between_batches:
                time.sleep(self.sleep_between_batches)

        # 3) BM25 sparse vectors (derived data — always safe to regenerate)
        if refresh_bm25:
            done = 0
            bm25_total = len(to_refresh) + len(to_create)
            for batch in _chunks([*to_refresh, *to_create], self.batch_size):
                try:
                    self._upsert_bm25(batch, timestamp)
                except Exception as exc:  # noqa: BLE001
                    for article, _pid in batch:
                        stats.add_failure("bm25_upsert_failed", original_id=article.original_id, error=str(exc))
                done += len(batch)
                if on_progress:
                    on_progress("bm25", done, bm25_total)
                if self.sleep_between_batches:
                    time.sleep(self.sleep_between_batches)

        return stats

    def _set_payloads(self, batch: Sequence[tuple[LawArticle, str]], timestamp: str) -> None:
        for article, point_id in batch:
            payload = article.to_payload(point_id, ingestion_time=timestamp)
            self.client.set_payload(
                collection_name=self.collection,
                payload=payload,
                points=[point_id],
                wait=False,
            )

    def _create_points(self, batch: Sequence[tuple[LawArticle, str]], timestamp: str) -> None:
        points = [
            qm.PointStruct(
                id=point_id,
                vector=placeholder_dense_vector(article.original_id, self.dense_dim),
                payload=article.to_payload(point_id, ingestion_time=timestamp),
            )
            for article, point_id in batch
        ]
        self.client.upsert(collection_name=self.collection, points=points, wait=True)

    def _upsert_bm25(self, batch: Sequence[tuple[LawArticle, str]], timestamp: str) -> None:
        points = []
        for article, point_id in batch:
            document = qm.Document(text=article.content[:BM25_MAX_CHARS], model=BM25_MODEL)
            points.append(
                qm.PointStruct(
                    id=point_id,
                    vector={BM25_VECTOR_NAME: document},
                    payload=article.to_payload(
                        point_id,
                        include_framework_fields=True,
                        ingestion_time=timestamp,
                    ),
                )
            )
        self.client.upsert(collection_name=self.bm25_collection, points=points, wait=True)

    # -- surgical payload edit --------------------------------------------
    def update_payload(
        self,
        original_id: str,
        fields: Mapping[str, Any],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Apply an edited payload to an existing point (vector untouched).

        Points are located by ``original_id``; a missing article is an error
        rather than an implicit create, so the UI can never materialise a point
        with a placeholder vector by accident. ``set_payload`` is used, which
        merges the patch and preserves the 768-dim dense vector.
        """
        record = None
        records, _ = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=_payload_filter("original_id", original_id),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if records:
            record = records[0]
        if record is None:
            raise PayloadEditError(f"article not indexed in {self.collection}: {original_id}")

        current = dict(record.payload or {})
        patch = build_payload_patch(fields, existing=current)
        if dry_run:
            return {
                "collection": self.collection,
                "original_id": original_id,
                "point_id": str(record.id),
                "applied": False,
                "patch": patch,
                "payload": {**current, **patch},
            }

        self.client.set_payload(
            collection_name=self.collection,
            payload=patch,
            points=[record.id],
            wait=True,
        )
        return {
            "collection": self.collection,
            "original_id": original_id,
            "point_id": str(record.id),
            "applied": True,
            "patch": patch,
            "payload": {**current, **patch},
        }


# ---------------------------------------------------------------------------
# Local semantic ingestion
# ---------------------------------------------------------------------------
class LocalLawIngester:
    """Ingest the corpus into the repo-owned dense collection."""

    def __init__(
        self,
        client: QdrantClient,
        *,
        collection: str = LOCAL_COLLECTION,
        embed_model: str = LOCAL_EMBED_MODEL,
        vector_name: str | None = None,
        batch_size: int = 64,
    ) -> None:
        self.client = client
        self.collection = collection
        self.embed_model = embed_model
        self.vector_name = vector_name
        self.batch_size = max(1, batch_size)
        self._encoder = None  # lazy: importing sentence-transformers is slow

    # -- collection lifecycle ---------------------------------------------
    def collection_exists(self) -> bool:
        try:
            return self.client.collection_exists(self.collection)
        except AttributeError:  # pragma: no cover - older clients
            return self.collection in {c.name for c in self.client.get_collections().collections}

    def ensure_collection(self, *, recreate: bool = False) -> None:
        if recreate and self.collection_exists():
            logger.warning("[law] deleting collection %s (recreate=True)", self.collection)
            self.client.delete_collection(self.collection)
        if not self.collection_exists():
            vectors_config: Any = qm.VectorParams(size=LOCAL_DENSE_DIM, distance=qm.Distance.COSINE)
            if self.vector_name:
                vectors_config = {self.vector_name: vectors_config}
            self.client.create_collection(collection_name=self.collection, vectors_config=vectors_config)
            logger.info("[law] created local collection %s (dim=%d)", self.collection, LOCAL_DENSE_DIM)

        for field_name in LOCAL_PAYLOAD_INDEX_FIELDS:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema=qm.PayloadSchemaType.KEYWORD,
                    wait=True,
                )
            except Exception as exc:  # noqa: BLE001 — index may already exist
                logger.debug("[law] payload index %s.%s: %s", self.collection, field_name, exc)

    # -- embedding ---------------------------------------------------------
    def _get_encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer

            logger.info("[law] loading embedding model %s", self.embed_model)
            self._encoder = SentenceTransformer(self.embed_model)
        return self._encoder

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        encoder = self._get_encoder()
        vectors = encoder.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vec.tolist() for vec in vectors]

    def existing_ids(self) -> set[str]:
        """``original_id`` values already embedded in the local collection."""
        if not self.collection_exists():
            return set()
        ids: set[str] = set()
        for record in _scroll_all(self.client, self.collection):
            value = (record.payload or {}).get("original_id")
            if value:
                ids.add(str(value))
        return ids

    # -- writing -----------------------------------------------------------
    def ingest(
        self,
        articles: Sequence[LawArticle],
        *,
        dry_run: bool = False,
        recreate: bool = False,
        multi_language: bool = False,
        only_missing: bool = False,
        on_progress: ProgressCallback | None = None,
    ) -> IngestStats:
        stats = IngestStats(target="local")
        stats.scanned = len(articles)

        if only_missing and not recreate:
            known = self.existing_ids()
            pending = [a for a in articles if a.original_id not in known]
            stats.skipped = len(articles) - len(pending)
            stats.notes.append(f"incremental: {len(pending)} of {len(articles)} article(s) not yet indexed")
            articles = pending

        if not articles:
            stats.notes.append("nothing to do")
            return stats

        if dry_run:
            stats.notes.append(
                f"dry-run: would embed {len(articles)} article(s) into {self.collection} "
                f"with {self.embed_model} (dim={LOCAL_DENSE_DIM})"
            )
            return stats

        self.ensure_collection(recreate=recreate)
        # Schema v1 lifecycle stamps carry an explicit ``Z``; the canonical
        # ``metadata.ingestion_time`` format stays untouched.
        timestamp = _iso_utc_now()

        done = 0
        total = len(articles)
        for batch in _chunks(list(articles), self.batch_size):
            texts = [a.embed_text() for a in batch]
            try:
                vectors = self._embed(texts)
            except Exception as exc:  # noqa: BLE001
                for article in batch:
                    stats.add_failure("embed_failed", original_id=article.original_id, error=str(exc))
                done += len(batch)
                if on_progress:
                    on_progress("embedding", done, total)
                continue
            stats.embedded += len(batch)

            points = []
            for article, vector in zip(batch, vectors, strict=True):
                point_id = (
                    localized_point_id(article.original_id, article.language)
                    if multi_language
                    else stable_point_id(article.original_id)
                )
                payload = article.to_payload(
                    point_id,
                    target=PAYLOAD_TARGET_LOCAL,
                    ingestion_time=timestamp,
                )
                points.append(
                    qm.PointStruct(
                        id=point_id,
                        vector={self.vector_name: vector} if self.vector_name else vector,
                        payload=payload,
                    )
                )
            try:
                self.client.upsert(collection_name=self.collection, points=points, wait=True)
                stats.created += len(points)
            except Exception as exc:  # noqa: BLE001
                for article in batch:
                    stats.add_failure("upsert_failed", original_id=article.original_id, error=str(exc))
            done += len(batch)
            if on_progress:
                on_progress("embedding", done, total)
        return stats


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SearchHit:
    """A search result from either collection."""

    score: float
    original_id: str
    title: str
    theme: str
    tags: str
    content: str
    source_file: str
    jurisdiction: str
    framework_code: str
    language: str
    doc_type: str
    article_number: str = ""
    record_kind: str = ""
    norm_type: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, score: float, payload: dict[str, Any]) -> SearchHit:
        def as_list(key: str) -> tuple[str, ...]:
            value = payload.get(key) or []
            if isinstance(value, str):
                return (value,)
            return tuple(str(item) for item in value)

        return cls(
            score=score,
            # ``eli_id`` is the schema-v1 name for the same value; read either so
            # a hit normalises regardless of which collection served it.
            original_id=payload.get("original_id") or payload.get("eli_id") or "",
            title=payload.get("title", ""),
            theme=payload.get("theme", ""),
            tags=_flatten_tags(payload.get("tags")),
            content=payload.get("content") or payload.get("text", ""),
            source_file=payload.get("source_file", ""),
            jurisdiction=payload.get("jurisdiction", ""),
            framework_code=payload.get("framework_code", ""),
            language=payload.get("language", ""),
            doc_type=payload.get("doc_type", ""),
            article_number=str(payload.get("article_number") or ""),
            record_kind=str(payload.get("record_kind") or ""),
            norm_type=as_list("norm_type"),
            scope=as_list("scope"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "original_id": self.original_id,
            "title": self.title,
            "theme": self.theme,
            "tags": self.tags,
            "source_file": self.source_file,
            "jurisdiction": self.jurisdiction,
            "framework_code": self.framework_code,
            "language": self.language,
            "doc_type": self.doc_type,
            "content": self.content,
            "article_number": self.article_number,
            "record_kind": self.record_kind,
            "norm_type": list(self.norm_type),
            "scope": list(self.scope),
        }


class LawSearchService:
    """Query the law corpus — dense (local) or BM25 (canonical)."""

    def __init__(
        self,
        client: QdrantClient,
        *,
        local_collection: str = LOCAL_COLLECTION,
        canonical_collection: str = CANONICAL_COLLECTION,
        bm25_collection: str = CANONICAL_BM25_COLLECTION,
        embed_model: str = LOCAL_EMBED_MODEL,
    ) -> None:
        self.client = client
        self.local_collection = local_collection
        self.canonical_collection = canonical_collection
        self.bm25_collection = bm25_collection
        self._local = LocalLawIngester(client, collection=local_collection, embed_model=embed_model)

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        target: str = "local",
        jurisdiction: str | None = None,
    ) -> list[SearchHit]:
        if target == "local":
            return self.search_local(query, limit=limit, jurisdiction=jurisdiction)
        if target in {"canonical", "bm25"}:
            return self.search_bm25(query, limit=limit, jurisdiction=jurisdiction)
        raise ValueError(f"unknown search target: {target!r} (use 'local' or 'canonical')")

    def _filter(self, jurisdiction: str | None) -> qm.Filter | None:
        if not jurisdiction:
            return None
        return qm.Filter(must=[qm.FieldCondition(key="jurisdiction", match=qm.MatchValue(value=jurisdiction))])

    def search_local(self, query: str, *, limit: int = 10, jurisdiction: str | None = None) -> list[SearchHit]:
        vector = self._local._embed([query])[0]
        response = self.client.query_points(
            collection_name=self.local_collection,
            query=vector,
            limit=limit,
            query_filter=self._filter(jurisdiction),
            with_payload=True,
        )
        return [SearchHit.from_payload(pt.score, pt.payload or {}) for pt in response.points]

    def search_bm25(self, query: str, *, limit: int = 10, jurisdiction: str | None = None) -> list[SearchHit]:
        response = self.client.query_points(
            collection_name=self.bm25_collection,
            query=qm.Document(text=query, model=BM25_MODEL),
            using=BM25_VECTOR_NAME,
            limit=limit,
            query_filter=self._filter(jurisdiction),
            with_payload=True,
        )
        return [SearchHit.from_payload(pt.score, pt.payload or {}) for pt in response.points]

    def get_article(self, original_id: str, *, collection: str | None = None) -> dict[str, Any] | None:
        """Exact payload lookup by ELI (``MatchValue``; no full-text index needed)."""
        collection = collection or self.canonical_collection
        records, _ = self.client.scroll(
            collection_name=collection,
            scroll_filter=_payload_filter("original_id", original_id),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            return None
        return {"id": str(records[0].id), **(records[0].payload or {})}


# ---------------------------------------------------------------------------
# Validation / registry
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ValidationReport:
    """Coverage + parity report for one collection."""

    collection: str
    points: int = 0
    unique_original_ids: int = 0
    duplicate_original_ids: dict[str, int] = field(default_factory=dict)
    articles_parsed: int = 0
    unique_elis_local: int = 0
    missing_in_collection: list[str] = field(default_factory=list)
    extra_in_collection: list[str] = field(default_factory=list)
    #: ``{eli_id, source_file, title}`` for live points with no local article.
    extra_details: list[dict[str, Any]] = field(default_factory=list)
    #: ``source_file`` basenames referenced by the live collection.
    source_files_in_collection: list[str] = field(default_factory=list)
    content_exact: int = 0
    #: Matches once whitespace and a trailing ``---`` separator are ignored.
    content_normalized: int = 0
    #: ELIs whose live body genuinely differs from the authored source.
    content_drift: list[str] = field(default_factory=list)
    title_drift: list[str] = field(default_factory=list)
    theme_drift: int = 0
    tags_drift: int = 0
    doc_type_drift: int = 0
    has_source_file: int = 0
    source_missing: int = 0

    @property
    def ok(self) -> bool:
        return (
            not self.missing_in_collection
            and not self.extra_in_collection
            and not self.duplicate_original_ids
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "ok": self.ok,
            "points": self.points,
            "unique_original_ids": self.unique_original_ids,
            "duplicate_original_ids": self.duplicate_original_ids,
            "articles_parsed": self.articles_parsed,
            "unique_elis_local": self.unique_elis_local,
            "missing_in_collection": len(self.missing_in_collection),
            "extra_in_collection": len(self.extra_in_collection),
            "missing_sample": self.missing_in_collection[:20],
            "extra_sample": self.extra_in_collection[:20],
            "extra_details": self.extra_details[:50],
            "source_files_in_collection": len(self.source_files_in_collection),
            "content_exact": self.content_exact,
            "content_normalized": self.content_normalized,
            "content_drift": len(self.content_drift),
            "content_drift_sample": self.content_drift[:20],
            "title_drift": len(self.title_drift),
            "title_drift_sample": self.title_drift[:20],
            "theme_drift": self.theme_drift,
            "tags_drift": self.tags_drift,
            "doc_type_drift": self.doc_type_drift,
            "has_source_file": self.has_source_file,
            "source_missing": self.source_missing,
        }


def _normalize_for_compare(text: str) -> str:
    """Collapse whitespace and drop a trailing rule so that a cosmetic
    separator difference is not reported as an actual content divergence."""
    collapsed = re.sub(r"[ \t\n\r]+", " ", text or "").strip()
    return re.sub(r"(?: -{3,})+$", "", collapsed).strip()


class LawRegistryValidator:
    """Compare the local corpus against a live Qdrant collection."""

    def __init__(self, client: QdrantClient, *, preferred_language: str = _DEFAULT_PREFERRED_LANGUAGE) -> None:
        self.client = client
        self.preferred_language = preferred_language

    def validate(
        self,
        plan: CorpusPlan,
        *,
        collection: str = CANONICAL_COLLECTION,
        compare_payloads: bool = True,
    ) -> ValidationReport:
        report = ValidationReport(collection=collection, articles_parsed=len(plan.articles))
        by_id: dict[str, list[LawArticle]] = defaultdict(list)
        for article in plan.articles:
            by_id[article.original_id].append(article)
        report.unique_elis_local = len(by_id)

        records = _scroll_all(self.client, collection)
        report.points = len(records)

        live: dict[str, dict[str, Any]] = {}
        counts: Counter[str] = Counter()
        source_files: set[str] = set()
        for record in records:
            payload = record.payload or {}
            original_id = payload.get("original_id")
            if payload.get("source_file"):
                source_files.add(str(payload["source_file"]))
            if not original_id:
                continue
            counts[str(original_id)] += 1
            live.setdefault(str(original_id), payload)
        report.unique_original_ids = len(live)
        report.duplicate_original_ids = {k: v for k, v in counts.items() if v > 1}
        report.source_files_in_collection = sorted(source_files)

        local_ids = set(by_id)
        live_ids = set(live)
        report.missing_in_collection = sorted(local_ids - live_ids)
        report.extra_in_collection = sorted(live_ids - local_ids)
        report.extra_details = [
            {
                "eli_id": eli,
                "source_file": live[eli].get("source_file"),
                "title": (live[eli].get("title") or "")[:120],
            }
            for eli in report.extra_in_collection
        ]

        if not compare_payloads:
            return report

        for eli, payload in live.items():
            variants = by_id.get(eli)
            if not variants:
                continue
            if payload.get("source_file"):
                report.has_source_file += 1
            else:
                report.source_missing += 1

            live_raw = payload.get("content") or payload.get("text") or ""
            live_content = _normalize_for_compare(live_raw)
            exact = any(article.content == live_raw for article in variants)
            normalized = any(_normalize_for_compare(article.content) == live_content for article in variants)
            if exact:
                report.content_exact += 1
            elif normalized:
                report.content_normalized += 1
            else:
                report.content_drift.append(eli)

            if not any(article.title == (payload.get("title") or "") for article in variants):
                report.title_drift.append(eli)
            if not any(article.theme == (payload.get("theme") or "") for article in variants):
                report.theme_drift += 1
            if not any(article.tags == (payload.get("tags") or "") for article in variants):
                report.tags_drift += 1
            if not any(article.doc_type == (payload.get("doc_type") or "") for article in variants):
                report.doc_type_drift += 1
        return report


# ---------------------------------------------------------------------------
# Index status
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class LawIndexStatus:
    """Live coverage snapshot used to label the registry UI's index actions."""

    law_dir: str = ""
    articles_parsed: int = 0
    unique_elis: int = 0
    reference_only_files: int = 0
    collisions: int = 0
    canonical_collection: str = CANONICAL_COLLECTION
    canonical_points: int = 0
    canonical_missing: list[str] = field(default_factory=list)
    canonical_extra: list[str] = field(default_factory=list)
    local_collection: str = LOCAL_COLLECTION
    local_exists: bool = False
    local_points: int = 0
    local_missing: list[str] = field(default_factory=list)
    local_extra: list[str] = field(default_factory=list)

    def as_dict(self, sample: int = 50) -> dict[str, Any]:
        return {
            "law_dir": self.law_dir,
            "articles_parsed": self.articles_parsed,
            "unique_elis": self.unique_elis,
            "reference_only_files": self.reference_only_files,
            "collisions": self.collisions,
            "canonical": {
                "collection": self.canonical_collection,
                "points": self.canonical_points,
                "missing": len(self.canonical_missing),
                "extra": len(self.canonical_extra),
                "missing_sample": self.canonical_missing[:sample],
                "up_to_date": not self.canonical_missing and not self.canonical_extra,
            },
            "local": {
                "collection": self.local_collection,
                "exists": self.local_exists,
                "points": self.local_points,
                "missing": len(self.local_missing),
                "extra": len(self.local_extra),
                "missing_sample": self.local_missing[:sample],
                "up_to_date": self.local_exists and not self.local_missing and not self.local_extra,
            },
        }


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------
class QdrantLawIndex:
    """End-to-end facade: parse → ingest (canonical/local) → validate → search."""

    def __init__(
        self,
        *,
        url: str | None = None,
        api_key: str | None = None,
        client: QdrantClient | None = None,
        law_dir: str | Path | None = None,
        canonical_collection: str = CANONICAL_COLLECTION,
        bm25_collection: str = CANONICAL_BM25_COLLECTION,
        local_collection: str = LOCAL_COLLECTION,
        embed_model: str = LOCAL_EMBED_MODEL,
        batch_size: int = 128,
        preferred_language: str = _DEFAULT_PREFERRED_LANGUAGE,
        keep_all_languages: bool = False,
        keep_separator: bool = True,
    ) -> None:
        self.client = client or build_qdrant_client(url, api_key)
        self.law_dir = Path(law_dir) if law_dir else default_law_dir()
        self.parser = LawCorpusParser(
            preferred_language=preferred_language,
            keep_all_languages=keep_all_languages,
            keep_separator=keep_separator,
        )
        self.canonical = CanonicalLawIngester(
            self.client,
            collection=canonical_collection,
            bm25_collection=bm25_collection,
            batch_size=batch_size,
        )
        self.local = LocalLawIngester(
            self.client,
            collection=local_collection,
            embed_model=embed_model,
            batch_size=min(batch_size, 64),
        )
        self.search_service = LawSearchService(
            self.client,
            local_collection=local_collection,
            canonical_collection=canonical_collection,
            bm25_collection=bm25_collection,
            embed_model=embed_model,
        )
        self.validator = LawRegistryValidator(self.client, preferred_language=preferred_language)

    # -- convenience -------------------------------------------------------
    @classmethod
    def from_settings(cls, **overrides: Any) -> QdrantLawIndex:
        """Build from :class:`src.config.Settings` (env-driven)."""
        from src.config import Settings

        settings = Settings()
        params: dict[str, Any] = {
            "url": settings.QDRANT_URL,
            "api_key": settings.QDRANT_API_KEY,
            "law_dir": settings.LAW_DIR,
            "canonical_collection": settings.LAW_COLLECTION,
            "bm25_collection": settings.LAW_BM25_COLLECTION,
            "local_collection": settings.LAW_LOCAL_COLLECTION,
            "embed_model": settings.LAW_EMBED_MODEL,
        }
        params.update(overrides)
        return cls(**params)

    def build_plan(self, root: str | Path | None = None) -> CorpusPlan:
        return self.parser.build_plan(Path(root) if root else self.law_dir)

    def ingest(
        self,
        plan: CorpusPlan | None = None,
        *,
        targets: Sequence[str] = ("canonical", "local"),
        dry_run: bool = False,
        allow_new: bool = False,
        refresh_payloads: bool = True,
        refresh_bm25: bool = True,
        recreate_local: bool = False,
        multi_language: bool = False,
        only_missing: bool = False,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, IngestStats]:
        """Ingest the corpus into the requested targets.

        ``only_missing`` switches every target to *incremental* mode: articles
        already present are skipped, which is what the registry UI's
        "index not yet indexed" action needs.

        ``on_progress`` receives ``(phase, done, total)`` and is called from the
        ingesting thread, so a background job can report granular progress.
        """
        plan = plan or self.build_plan()
        results: dict[str, IngestStats] = {}
        progress = on_progress or (lambda *_args: None)

        def _target_progress(target: str) -> ProgressCallback:
            def _cb(phase: str, done: int, total: int) -> None:
                progress(f"{target}:{phase}", done, total)

            return _cb

        if "canonical" in targets:
            existing = self.canonical.existing_index()
            results["canonical"] = self.canonical.ingest(
                plan.articles,
                existing=existing,
                dry_run=dry_run,
                allow_new=allow_new,
                # Incremental mode must not rewrite payloads that are already
                # there; BM25 is derived data, so it is safe to regenerate.
                refresh_payloads=refresh_payloads and not only_missing,
                refresh_bm25=refresh_bm25,
                on_progress=_target_progress("canonical"),
            )
        if "local" in targets:
            results["local"] = self.local.ingest(
                plan.articles,
                dry_run=dry_run,
                recreate=recreate_local,
                multi_language=multi_language,
                only_missing=only_missing,
                on_progress=_target_progress("local"),
            )
        return results

    def status(self, plan: CorpusPlan | None = None) -> LawIndexStatus:
        """Compare the corpus against both collections without writing anything."""
        plan = plan or self.build_plan()
        status = LawIndexStatus(
            law_dir=str(self.law_dir),
            articles_parsed=len(plan.articles),
            unique_elis=len(plan.by_original_id),
            reference_only_files=len(plan.reference_only_files),
            collisions=len(plan.collisions),
            canonical_collection=self.canonical.collection,
            local_collection=self.local.collection,
        )

        corpus_ids = set(plan.by_original_id)

        with suppress(Exception):
            status.canonical_points = self.canonical.article_count()
            canonical_ids = set(self.canonical.existing_index())
            status.canonical_missing = sorted(corpus_ids - canonical_ids)
            status.canonical_extra = sorted(canonical_ids - corpus_ids)

        status.local_exists = self.local.collection_exists()
        if status.local_exists:
            local_ids = self.local.existing_ids()
            status.local_points = len(local_ids)
            status.local_missing = sorted(corpus_ids - local_ids)
            status.local_extra = sorted(local_ids - corpus_ids)

        return status

    def update_payload(
        self,
        original_id: str,
        fields: Mapping[str, Any],
        *,
        collection: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Edit one indexed article's payload (dense vector preserved)."""
        collection = collection or self.canonical.collection
        if collection != self.canonical.collection:
            return self._update_payload_generic(collection, original_id, fields, dry_run=dry_run)
        return self.canonical.update_payload(original_id, fields, dry_run=dry_run)

    def _update_payload_generic(
        self,
        collection: str,
        original_id: str,
        fields: Mapping[str, Any],
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        """Same edit semantics for non-canonical collections (e.g. the local one)."""
        records, _ = self.client.scroll(
            collection_name=collection,
            scroll_filter=_payload_filter("original_id", original_id),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            raise PayloadEditError(f"article not indexed in {collection}: {original_id}")
        current = dict(records[0].payload or {})
        patch = build_payload_patch(fields, existing=current)
        if not dry_run:
            self.client.set_payload(
                collection_name=collection,
                payload=patch,
                points=[records[0].id],
                wait=True,
            )
        return {
            "collection": collection,
            "original_id": original_id,
            "point_id": str(records[0].id),
            "applied": not dry_run,
            "patch": patch,
            "payload": {**current, **patch},
        }

    def validate(
        self,
        plan: CorpusPlan | None = None,
        *,
        collection: str | None = None,
        compare_payloads: bool = True,
    ) -> ValidationReport:
        plan = plan or self.build_plan()
        return self.validator.validate(
            plan,
            collection=collection or self.canonical.collection,
            compare_payloads=compare_payloads,
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        target: str = "local",
        jurisdiction: str | None = None,
    ) -> list[SearchHit]:
        return self.search_service.search(query, limit=limit, target=target, jurisdiction=jurisdiction)

    def get_article(self, original_id: str, *, collection: str | None = None) -> dict[str, Any] | None:
        return self.search_service.get_article(original_id, collection=collection)

    def close(self) -> None:
        with suppress(Exception):
            self.client.close()


def default_law_dir() -> Path:
    """``<repo>/data/law`` resolved relative to this module."""
    return Path(__file__).resolve().parents[2] / "data" / "law"


def registry_paths(output_dir: str | Path | None = None) -> tuple[Path, Path]:
    """``(law_registry.json, LAW_REGISTRY.md)`` for a corpus root or mapping dir."""
    if output_dir is None:
        base = default_law_dir() / "_mapping"
    else:
        base = Path(output_dir)
        if base.name != "_mapping" and (base / "_mapping").is_dir():
            base = base / "_mapping"
    return base / "law_registry.json", base / "LAW_REGISTRY.md"


def write_registry(
    plan: CorpusPlan,
    report: ValidationReport,
    *,
    output_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    """Write ``law_registry.json`` + ``LAW_REGISTRY.md`` next to the corpus.

    The JSON is a **superset** of the schema produced by
    ``discovery/case-server/pipeline/build_law_registry.js``: the legacy
    ``summary`` / ``files`` / ``qdrant_only_articles`` keys and their field names
    are preserved so existing consumers keep working, with the additional
    parity/reconciliation detail nested under ``detail``.

    The destination is resolved through :func:`registry_paths`, so passing a
    corpus root writes into its ``_mapping`` subdirectory and can never drop
    artifacts into the corpus itself (which would then be parsed as input).
    """
    json_path, md_path = registry_paths(output_dir)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    missing = set(report.missing_in_collection)
    extra = set(report.extra_in_collection)
    live_source_basenames = set(report.source_files_in_collection)

    # ELIs dropped because another locale was preferred, grouped by source file.
    alias_by_file: dict[str, list[str]] = defaultdict(list)
    for eli, rel_path in plan.skipped_variants:
        alias_by_file[rel_path].append(eli)

    files: list[dict[str, Any]] = []
    for file_report in plan.files:
        elis = file_report.unique_elis
        missing_eli = [e for e in elis if e in missing]
        in_qdrant_eli = [e for e in elis if e not in missing]
        alias_eli = alias_by_file.get(file_report.rel_path, [])
        files.append(
            {
                "file": file_report.rel_path,
                "language": file_report.language,
                "title": file_report.title,
                "reference_only": file_report.reference_only,
                "reference_note": file_report.reference_note,
                "articles_local": len(elis),
                "articles_in_qdrant": len(in_qdrant_eli),
                "articles_missing": len(missing_eli),
                "alias_only_not_separately_ingested": len(alias_eli),
                "missing_eli": missing_eli,
                "alias_eli": alias_eli,
                "in_qdrant_eli": in_qdrant_eli,
                "source_basename_present_in_qdrant": Path(file_report.rel_path).name
                in live_source_basenames,
                # -- extra detail (not part of the legacy JS schema) --
                "blocks_without_eli": file_report.blocks_without_eli,
            }
        )

    language_breakdown: Counter[str] = Counter(f["language"] for f in files)
    generated_at = _iso_now()

    summary: dict[str, Any] = {
        # legacy JS-compatible keys
        "generated_at": generated_at,
        "data_law_md_files": len(files),
        "data_law_articles_unique": len(plan.by_original_id),
        "data_law_reference_only_files": len(plan.reference_only_files),
        "qdrant_points": report.points,
        "qdrant_articles_with_local_file": report.unique_original_ids - len(extra),
        "data_law_articles_not_in_qdrant": len(report.missing_in_collection),
        "alias_only_same_article_already_ingested": len(plan.skipped_variants),
        "genuinely_missing_articles": len(report.missing_in_collection),
        "qdrant_articles_without_local_file": len(report.extra_in_collection),
        "language_breakdown": dict(language_breakdown),
    }
    detail = {
        "collection": report.collection,
        "validation_ok": report.ok,
        "article_blocks_total": plan.blocks_total,
        "article_blocks_without_eli": plan.blocks_without_eli,
        "articles_with_eli": len(plan.articles),
        "colliding_elis": len(plan.collisions),
        "duplicate_original_ids": report.duplicate_original_ids,
        "articles_language_breakdown": dict(plan.languages),
        "content_exact": report.content_exact,
        "content_normalized": report.content_normalized,
        "content_drift": len(report.content_drift),
        "content_drift_eli": report.content_drift,
        "title_drift": len(report.title_drift),
        "theme_drift": report.theme_drift,
        "tags_drift": report.tags_drift,
        "doc_type_drift": report.doc_type_drift,
        "missing_eli": report.missing_in_collection,
        "extra_eli": report.extra_in_collection,
    }

    payload = {
        "summary": summary,
        "files": files,
        "qdrant_only_articles": report.extra_details,
        "detail": detail,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# Law Corpus Registry — `data/law/` ↔ Qdrant `{report.collection}`",
        "",
        f"Generated: {generated_at}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| data/law .md files | {summary['data_law_md_files']} |",
        f"| Article blocks (with ELI) | {detail['articles_with_eli']} |",
        f"| Unique article ELIs | {summary['data_law_articles_unique']} |",
        f"| Reference-only files (no ELI) | {summary['data_law_reference_only_files']} |",
        f"| Qdrant points | {summary['qdrant_points']} |",
        f"| Qdrant unique original_ids | {report.unique_original_ids} |",
        f"| Qdrant duplicate original_ids | {len(report.duplicate_original_ids)} |",
        f"| Articles missing in Qdrant | {summary['genuinely_missing_articles']} |",
        f"| Qdrant articles with no local ELI | {summary['qdrant_articles_without_local_file']} |",
        f"| Same article already ingested (alias) | {summary['alias_only_same_article_already_ingested']} |",
        f"| Content exact match | {report.content_exact} |",
        f"| Content whitespace/separator-normalised | {report.content_normalized} |",
        f"| Content drift (legacy revision) | {len(report.content_drift)} |",
        f"| Title drift | {len(report.title_drift)} |",
        f"| Theme drift / Tags drift | {report.theme_drift} / {report.tags_drift} |",
        f"| doc_type drift (derived mapping) | {report.doc_type_drift} |",
        f"| Files by language | {summary['language_breakdown']} |",
        f"| Articles by language | {detail['articles_language_breakdown']} |",
        f"| Colliding ELIs (multi-locale) | {detail['colliding_elis']} |",
        f"| Validation OK | {report.ok} |",
        "",
        "## Per-file coverage",
        "",
        "| File | Lang | Ref-only | Local | In Qdrant | Alias | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in files:
        lines.append(
            f"| `{entry['file']}` | {entry['language']} | "
            f"{'yes' if entry['reference_only'] else ''} | "
            f"{entry['articles_local']} | {entry['articles_in_qdrant']} | "
            f"{entry['alias_only_not_separately_ingested'] or ''} | "
            f"{entry['reference_note'] or ''} |"
        )
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


__all__ = [
    "BM25_MAX_CHARS",
    "BM25_MODEL",
    "BM25_VECTOR_NAME",
    "CANONICAL_BM25_COLLECTION",
    "CANONICAL_COLLECTION",
    "CANONICAL_DENSE_DIM",
    "EDITABLE_PAYLOAD_FIELDS",
    "LOCAL_COLLECTION",
    "LOCAL_DENSE_DIM",
    "LOCAL_EMBED_MODEL",
    "LOCAL_PAYLOAD_INDEX_FIELDS",
    "PAYLOAD_TARGET_CANONICAL",
    "PAYLOAD_TARGET_LOCAL",
    "RECORD_KIND_ARTICLE",
    "RECORD_KIND_REFERENCE",
    "SCHEMA_VERSION",
    "TAG_FIELDS",
    "VOLATILE_PAYLOAD_KEYS",
    "CanonicalLawIngester",
    "CorpusPlan",
    "FileReport",
    "IngestStats",
    "LawArticle",
    "LawCorpusParser",
    "LawIndexStatus",
    "LawRegistryValidator",
    "LawSearchService",
    "LocalLawIngester",
    "PayloadDiff",
    "PayloadEditError",
    "QdrantLawIndex",
    "SearchHit",
    "ValidationReport",
    "article_number_for",
    "build_payload_patch",
    "build_qdrant_client",
    "default_law_dir",
    "diff_payloads",
    "doc_type_for",
    "language_for_path",
    "localized_point_id",
    "normalize_content",
    "parse_article_tags",
    "payload_bytes",
    "placeholder_dense_vector",
    "point_id_for",
    "registry_paths",
    "sha256_short",
    "split_eli",
    "stable_point_id",
    "write_registry",
]
