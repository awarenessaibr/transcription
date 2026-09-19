"""Controlled vocabulary and review reports for the law *enrichment* fields.

Four payload keys carry the structured classification of a provision —
``norm_type``, ``scope``, ``direction`` and ``sanctions`` — and they are the ones
a bare ingestion most often leaves empty (measured on this corpus: 1376 of 1421
articles have no ``direction``, 1236 no ``sanctions``, 97 no ``scope``). They are
also the keys the local collection indexes as keywords
(:data:`~src.infrastructure.qdrant_law_index.LOCAL_PAYLOAD_INDEX_FIELDS`), so
filling them in is what makes the corpus filterable rather than merely
searchable.

This module owns the three things that must not drift apart:

* **the vocabulary** — the canonical English tokens observed in the corpus, plus
  the Portuguese and Spanish twins and the looser phrasings a model tends to
  propose, folded onto them by :func:`normalize_token`. A token that is still
  unknown after folding is *not* discarded; it is returned lower-cased and
  flagged, so a genuinely new concept shows up in the report instead of silently
  disappearing from a suggestion;
* **the decision logic** — :data:`ENRICHMENT_RULES`, the reusable "baseline for
  other articles" the reviewer reads and the model is told to follow;
* **the report** — :func:`render_report` turns one review into the audit
  document that is saved next to the corpus, and :func:`record_applied` appends
  what was actually written back into that same document.

The report artifacts live in ``<law_dir>/_mapping/enrichment/`` — inside
``_mapping``, which :class:`~src.infrastructure.qdrant_law_index.LawCorpusParser`
already excludes from corpus discovery, so a report can never be re-ingested as
if it were a law document. Each report exists twice: a ``.json`` record that is
the source of truth and a ``.md`` rendering for humans.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.infrastructure.qdrant_law_index import (
    DOC_TYPE_VALUES,
    ENRICHMENT_ARRAY_FIELDS,
    ENRICHMENT_PAYLOAD_FIELDS,
    ENRICHMENT_SCALAR_FIELDS,
)

#: The reviewable enrichment fields, in report order.
ENRICHMENT_FIELDS: tuple[str, ...] = ENRICHMENT_PAYLOAD_FIELDS

#: Whether each enrichment field is a keyword array or a single token. Mirrors
#: the payload writer's split so the vocabulary, the prompt and the validator can
#: never disagree about a field's shape.
ENRICHMENT_FIELD_KINDS: dict[str, str] = {
    **dict.fromkeys(sorted(ENRICHMENT_ARRAY_FIELDS), "array"),
    **dict.fromkeys(sorted(ENRICHMENT_SCALAR_FIELDS), "scalar"),
}

#: Canonical English tokens for every field. Sentences in
#: :data:`ENRICHMENT_RULES` reference only these; anything else is a proposal.
ENRICHMENT_VOCABULARY: dict[str, tuple[str, ...]] = {
    "norm_type": (
        "constitutional_principle",
        "principle",
        "duty",
        "right",
        "prohibition",
        "power",
        "competence",
        "procedural",
        "definition",
        "penalty",
        "exemption",
        "liability",
        "ethics",
        "statute",
        "treaty_obligation",
        "constitutional_guarantee",
        "political_commitment",
        "soft_law_principle",
        "administrative_instruction",
        "default_rule",
        "due_process",
        "appeal",
        "limitation",
        "complaint",
    ),
    "scope": (
        "constitutional",
        "administrative",
        "regulatory",
        "contractual",
        "criminal",
        "civil",
        "public_administration",
        "municipal",
        "regional",
        "national",
        "state",
        "bilateral",
        "civil_society",
        "professional",
        "data_processing",
        "data_subject_rights",
        "public_policy",
        "accountability",
        "monitoring",
        "enforcement",
        "secrecy",
        "evidentiary",
        "jurisdictional",
        "procedural",
        "extracontractual",
    ),
    "direction": (
        "mandatory",
        "prohibitive",
        "permissive",
        "restrictive",
        "authority",
        "advisory",
    ),
    "sanctions": (
        "criminal_liability",
        "civil_liability",
        "administrative_liability",
        "disciplinary_sanction",
        "financial_penalty",
        "monetary_compensation",
        "suspension",
        "disqualification",
        "license_revocation",
        "service_remedy",
        "censure",
        "nullity",
        "imprisonment",
    ),
}

#: Folding table applied before an alias lookup, so ``Proibição``,
#: ``proibicao`` and ``proibição`` all resolve. Keys are already folded.
_ENRICHMENT_ALIASES: dict[str, dict[str, str]] = {
    "norm_type": {
        "dever": "duty",
        "obrigacao": "duty",
        "obligacion": "duty",
        "obligation": "duty",
        "deber": "duty",
        "proibicao": "prohibition",
        "prohibicion": "prohibition",
        "prohibition": "prohibition",
        "vedacao": "prohibition",
        "definicao": "definition",
        "definicion": "definition",
        "poder": "power",
        "power_to_act": "power",
        "faculdade": "power",
        "isencao": "exemption",
        "excecao": "exemption",
        "excepcion": "exemption",
        "processual": "procedural",
        "processual_penal": "procedural",
        "penalidade": "penalty",
        "sancion": "penalty",
        "sanction": "penalty",
        "direito": "right",
        "derecho": "right",
        "principio": "principle",
        "principio_constitucional": "constitutional_principle",
        "principio_de_soft_law": "soft_law_principle",
        "obrigacao_de_tratado": "treaty_obligation",
        "obrigacao_prevista_em_tratado": "treaty_obligation",
        "recomendacao": "soft_law_principle",
        "recomendacion": "soft_law_principle",
        "competencia": "competence",
        "institutional_competence": "competence",
    },
    "scope": {
        "regulamentar": "regulatory",
        "regulatorio": "regulatory",
        "administrativo": "administrative",
        "administrativa": "administrative",
        "contratual": "contractual",
        "constitucional": "constitutional",
        "estadual": "state",
        "estado": "state",
        "municipio": "municipal",
        "municipalidade": "municipal",
        "nacional": "national",
        "sociedade_civil": "civil_society",
        "politica": "public_policy",
        "politica_publica": "public_policy",
        "public_administration_state": "public_administration",
        "funcionarios_publicos": "public_administration",
        "data_protection": "data_processing",
        "privacy": "data_processing",
        "consumer": "civil",
    },
    "direction": {
        "obligation": "mandatory",
        "obrigatorio": "mandatory",
        "obrigatoria": "mandatory",
        "obligatorio": "mandatory",
        "obligatoria": "mandatory",
        "must": "mandatory",
        "dever": "mandatory",
        "deber": "mandatory",
        "prohibition": "prohibitive",
        "proibicao": "prohibitive",
        "proibido": "prohibitive",
        "proibida": "prohibitive",
        "prohibicion": "prohibitive",
        "prohibido": "prohibitive",
        "prohibited": "prohibitive",
        "vedado": "prohibitive",
        "vedada": "prohibitive",
        "forbidden": "prohibitive",
        "permission": "permissive",
        "permissao": "permissive",
        "permiso": "permissive",
        "right": "permissive",
        "derecho": "permissive",
        "discretion": "permissive",
        "recomendacao": "advisory",
        "recomendacion": "advisory",
        "recommendation": "advisory",
        "aspiration": "advisory",
        "restricao": "restrictive",
        "restriccion": "restrictive",
        "restriction": "restrictive",
    },
    "sanctions": {
        "responsabilidade_criminal": "criminal_liability",
        "responsabilidade_penal": "criminal_liability",
        "responsabilidad_penal": "criminal_liability",
        "responsabilidade_civil": "civil_liability",
        "responsabilidad_civil": "civil_liability",
        "responsabilidade_administrativa": "administrative_liability",
        "administrative_responsibility": "administrative_liability",
        "disciplinary_sanctions": "disciplinary_sanction",
        "sanction": "disciplinary_sanction",
        "sancao": "disciplinary_sanction",
        "penalidade_financeira": "financial_penalty",
        "penalty": "financial_penalty",
        "fine": "financial_penalty",
        "multa": "financial_penalty",
        "reparacao_do_servico": "service_remedy",
        "compensacion_monetaria": "monetary_compensation",
        "compensacao_monetaria": "monetary_compensation",
        "revogacao_de_licenca": "license_revocation",
        "censura": "censure",
        "suspensao": "suspension",
        "inabilitacao": "disqualification",
        "nulidade": "nullity",
        "prisao": "imprisonment",
    },
}

#: One-line meanings, used for the vocabulary section of a report. Keys match
#: :data:`ENRICHMENT_VOCABULARY`; a missing key simply prints the bare token.
ENRICHMENT_GLOSSARY: dict[str, dict[str, str]] = {
    "norm_type": {
        "constitutional_principle": "a constitutional principle the provision gives effect to",
        "principle": "states a general principle rather than a concrete command",
        "duty": "imposes an obligation on a named subject",
        "right": "confers an enforceable right",
        "prohibition": "forbids conduct",
        "power": "grants a faculty to act",
        "competence": "allocates jurisdiction to an organ",
        "procedural": "prescribes how a procedure runs",
        "definition": "defines a term or legal concept",
        "penalty": "attaches a consequence to a breach",
        "exemption": "carves an exception out of a general rule",
        "liability": "allocates responsibility for damage",
        "ethics": "sets a standard of conduct",
        "statute": "enacts a self-contained statutory regime",
        "treaty_obligation": "gives effect to an international commitment",
        "constitutional_guarantee": "guarantees a constitutional remedy",
        "political_commitment": "records a political commitment (non-binding)",
        "soft_law_principle": "states a non-binding principle or recommendation",
        "administrative_instruction": "instructs the administration internally",
        "default_rule": "supplies a rule where the parties were silent",
        "due_process": "guarantees procedural fairness",
        "appeal": "creates or regulates a review remedy",
        "limitation": "bounds a right or a period",
        "complaint": "channels a grievance into a procedure",
    },
    "scope": {
        "constitutional": "constitutional law",
        "administrative": "administrative law",
        "regulatory": "regulatory / rule-making law",
        "contractual": "contractual relations",
        "criminal": "criminal law",
        "civil": "civil law and private relations",
        "public_administration": "the public administration and its officials",
        "municipal": "municipal bodies",
        "regional": "regional / state-level bodies",
        "national": "the country as a whole",
        "state": "the state as an institution",
        "bilateral": "relations between two parties or two states",
        "civil_society": "civil society and the general public",
        "professional": "a regulated profession",
        "data_processing": "the processing of personal data",
        "data_subject_rights": "the rights of data subjects",
        "public_policy": "public policy and programmes",
        "accountability": "accountability and oversight duties",
        "monitoring": "monitoring and inspection",
        "enforcement": "enforcement and compliance",
        "secrecy": "secrecy and access restrictions",
        "evidentiary": "evidence and proof",
        "jurisdictional": "jurisdiction and competence",
        "procedural": "procedure",
        "extracontractual": "non-contractual (tort) liability",
    },
    "direction": {
        "mandatory": "obliges — “deberán”, “shall”, “must”, “é obrigatório”",
        "prohibitive": "forbids — “no podrán”, “é vedado”, “may not”",
        "permissive": "allows — “podrán”, “may”, “a su juicio”",
        "restrictive": "limits an existing right or a scope",
        "authority": "empowers an organ (parallel to norm_type=power)",
        "advisory": "non-binding guidance — “procurarán”, “recomienda”",
    },
    "sanctions": {
        "criminal_liability": "criminal responsibility",
        "civil_liability": "civil responsibility",
        "administrative_liability": "administrative responsibility",
        "disciplinary_sanction": "a disciplinary sanction on an official",
        "financial_penalty": "a fine or financial penalty",
        "monetary_compensation": "compensation to an injured party",
        "suspension": "suspension of an activity or of a licence",
        "disqualification": "disqualification from office or from contracting",
        "license_revocation": "revocation of a licence",
        "service_remedy": "an operational remedy (service reparation)",
        "censure": "a censure, formally recorded",
        "nullity": "the act is void or voidable",
        "imprisonment": "a custodial penalty",
    },
}

#: The reusable decision logic — what the report's "baseline for other
#: articles" section prints and what the model is told to apply.
ENRICHMENT_RULES: dict[str, tuple[str, ...]] = {
    "norm_type": (
        "Read what the article *does*, not what it is about: a statement of general "
        "policy is `principle`, a command addressed to a subject is `duty`.",
        "Take the main verb of the operative sentence. A provision that forbids is "
        "`prohibition`, one that confers is `right` or `power`, one that prescribes "
        "`step by step` conduct is `procedural`.",
        "An article can carry several facets — “the officials shall refrain…” is both "
        "`duty` and `prohibition`. Return every facet that is explicitly there.",
        "Use `definition` only for an article whose job is to fix the meaning of a term, "
        "and `penalty` only where the article itself attaches a consequence.",
        "Never infer a facet from the document title; base it on the article's own text.",
    ),
    "scope": (
        "Identify the addressees: `autoridades`, `funcionarios`, `Administración del "
        "Estado` are `public_administration`; a municipal organ is `municipal`; a "
        "regional government is `regional`.",
        "If the addressee is the state as a whole rather than a particular body, use "
        "`state`; if the provision is general and territorial, `national`.",
        "Legal *domain* and *addressee* are different axes — “data protection duties of "
        "public bodies” is `public_administration` plus `data_processing`. Both belong.",
        "Prefer a domain token (`administrative`, `regulatory`, `criminal`, "
        "`constitutional`) over a vague one; only add a second token when the text "
        "genuinely spans two domains.",
    ),
    "direction": (
        "Map the modality of the main verb — this field is a single token, not a list: "
        "`deberán`/`shall`/`é obrigatório` → `mandatory`; `no podrán`/`é vedado`/`may "
        "not` → `prohibitive`; `podrán`/`may` → `permissive`.",
        "`procurarán`, `se recomienda` and similar aspiration language is `advisory`, "
        "not `mandatory` — soft-law instruments must not be recorded as commands.",
        "A provision whose only purpose is to limit an existing right or an existing "
        "scope is `restrictive`, even when it is phrased permissively.",
        "An enabling provision — one that says an organ may exercise a power — is "
        "`authority`; reserve `permissive` for permissions granted to regulated "
        "subjects.",
        "Leave `direction` out entirely when the article contains no operative verb "
        "(a definition, a table of contents): an empty field is more accurate than a "
        "guess.",
    ),
    "sanctions": (
        "Record only consequences the article itself states — a sanction described only "
        "in another article belongs to that article.",
        "Match the consequence to a token: `acarreará responsabilidades` / "
        "`responsabilidad administrativa` → `administrative_liability`; "
        "`será sancionado con multa` → `financial_penalty`; `incurrirá en "
        "responsabilidad penal` → `criminal_liability`; a disciplinary hearing → "
        "`disciplinary_sanction`.",
        "`indemnizará` / `resarcirá` is `civil_liability` or `monetary_compensation`, "
        "not a penalty.",
        "An article can attach several consequences; return each one.",
        "Most articles attach none — an empty list is the correct answer, not a gap to "
        "fill. Never infer a sanction from the topic of the instrument.",
    ),
}

#: Directory (under ``_mapping``, which the corpus parser ignores) for reports.
REPORT_SUBDIR = "enrichment"

#: Decision logic for ``doc_type``. Unlike the enrichment fields this one is a
#: property of the *document* — the instrument the article belongs to — and not
#: of the article's text, so the rules are about reading the source header.
DOC_TYPE_RULES: tuple[str, ...] = (
    "`doc_type` names the instrument the article belongs to: read it from the "
    "document header (its title, its law number, or `framework_code`), never "
    "from the article's subject matter.",
    "Return exactly one token from the list below. `doc_type` is a single string, "
    "never a list.",
    "A codified instrument is `Code` even when an ordinary law enacted it: "
    "`Código Civil`, `Código Penal`, `Código Brasileiro de Aeronáutica`.",
    "`Ley`/`Lei` is `Law`; `Decreto`, `DTO` or `Decreto con Fuerza de Ley` is "
    "`Decree`; `Constitución`/`Constituição` is `Constitution`; an ICAO annex or "
    "document is `ICAO`; a regulator's `Resolución`/`Resolução` is `Resolution`.",
    "Only propose a value when the header actually names the instrument. If the "
    "snippet shows no header, leave the value alone — the ingester derives this "
    "field from `framework_code`, so a guess here contradicts it.",
    "`doc_type` is also read as `norm_type` by a downstream knowledge base, so an "
    "unresolved `unknown` is strictly better than a wrong instrument type.",
)

#: One-line meanings for :data:`DOC_TYPE_VALUES`, mirroring the shape of
#: :data:`ENRICHMENT_GLOSSARY`.
DOC_TYPE_GLOSSARY: dict[str, str] = {
    "Constitution": "a constitution (Constitucion_BCN, CF88)",
    "Code": "a codified statute (Código Civil, Código Penal, CBA)",
    "Law": "an ordinary statute (Lei / Ley)",
    "Decree": "an executive decree (Decreto, DTO, Decreto con Fuerza de Ley)",
    "Convention": "an international treaty or convention",
    "Declaration": "a non-binding joint declaration",
    "Guidelines": "non-binding guidelines or model articles",
    "Contract": "a private contractual instrument",
    "Resolution": "a regulator's resolution",
    "ICAO": "an ICAO annex or document",
    "Internal": "an internal agency instrument",
    "CDC": "the Brazilian Consumer Defence Code (legacy token)",
}

#: The fields that carry a controlled vocabulary and a reusable rule set, in
#: report order. ``doc_type`` is included even though it is not an enrichment
#: field: it is derived from ``framework_code`` rather than from the article's
#: text, so its taxonomy lives next to :func:`doc_type_for`.
TAXONOMY_FIELDS: tuple[str, ...] = (*ENRICHMENT_FIELDS, "doc_type")


def rules_for(field: str) -> tuple[str, ...]:
    """The decision rules for ``field`` — the same ones handed to the model."""
    if field == "doc_type":
        return DOC_TYPE_RULES
    return ENRICHMENT_RULES.get(field, ())


def vocabulary_for(field: str) -> tuple[str, ...]:
    """The controlled tokens for ``field``."""
    if field == "doc_type":
        return DOC_TYPE_VALUES
    return ENRICHMENT_VOCABULARY.get(field, ())


def glossary_for(field: str) -> Mapping[str, str]:
    """Token meanings for ``field``."""
    if field == "doc_type":
        return DOC_TYPE_GLOSSARY
    return ENRICHMENT_GLOSSARY.get(field, {})


def kind_for(field: str) -> str:
    """Human-readable cardinality of ``field``, for the prompt and the report."""
    return "array — one or more tokens" if ENRICHMENT_FIELD_KINDS.get(field) == "array" else "single token or null"


_REPORT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.md$")
_SLUG_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


# ---------------------------------------------------------------------------
# Vocabulary normalisation
# ---------------------------------------------------------------------------
def fold_token(token: str) -> str:
    """Accent-fold, lower-case and underscore-fold a token for lookup."""
    decomposed = unicodedata.normalize("NFKD", str(token or ""))
    ascii_only = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[\s\-]+", "_", ascii_only.strip().lower())


def normalize_token(field: str, token: str) -> tuple[str, bool]:
    """Map one proposed token onto the controlled vocabulary.

    Returns ``(token, known)``. The token is always lower-cased. ``known`` is
    ``False`` for a token that is neither canonical nor a known alias — the
    caller keeps it (a new concept is information, not noise) and the report
    lists it as a vocabulary proposal.
    """
    cleaned = str(token or "").strip()
    if not cleaned:
        return "", True
    aliases = _ENRICHMENT_ALIASES.get(field, {})
    canonical = set(ENRICHMENT_VOCABULARY.get(field, ()))
    folded = fold_token(cleaned)
    if folded in aliases:
        return aliases[folded], True
    for value in canonical:
        if fold_token(value) == folded:
            return value, True
    # Unknown: keep the folded form so the token still joins the corpus
    # convention (lower-case, underscore-separated).
    return folded, False


def normalize_value(field: str, value: Any) -> tuple[Any, list[dict[str, str]], list[str]]:
    """Normalise a proposed value for ``field``.

    Returns ``(value, renames, unknown)`` where ``renames`` records every token
    the vocabulary rewrote (``{"from", "to"}``) and ``unknown`` lists the tokens
    that stayed outside it.
    """
    renames: list[dict[str, str]] = []
    unknown: list[str] = []

    def one(raw: str) -> str:
        canonical, known = normalize_token(field, raw)
        if canonical and canonical != str(raw).strip():
            renames.append({"from": str(raw).strip(), "to": canonical})
        if canonical and not known:
            unknown.append(canonical)
        return canonical

    if ENRICHMENT_FIELD_KINDS.get(field) == "array":
        items = value if isinstance(value, list | tuple) else [value]
        out: list[Any] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, str):
                # Passing it through unchanged lets the payload validator
                # reject it; stringifying would invent a token out of a number.
                out.append(item)
                continue
            canonical = one(item)
            if canonical and canonical not in seen:
                seen.add(canonical)
                out.append(canonical)
        return out, renames, unknown
    if value is None:
        return None, renames, unknown
    canonical = one(value) if isinstance(value, str) else value
    return canonical, renames, unknown


def vocabulary_block(fields: Iterable[str]) -> str:
    """The taxonomy handed to the model and reprinted in the report.

    ``fields`` is the reviewed field list. Only the classification fields have
    rules and tokens — the plain metadata fields (``title``, ``theme``, …) are
    reviewed without a taxonomy, because nothing constrains their values.
    """
    requested = set(fields)
    lines: list[str] = []
    for field in TAXONOMY_FIELDS:
        if field not in requested:
            continue
        lines.append(f"\n### `{field}` ({kind_for(field)})")
        lines.extend(f"- {rule}" for rule in rules_for(field))
        lines.append("- Controlled vocabulary (prefer these exact tokens):")
        glossary = glossary_for(field)
        for token in vocabulary_for(field):
            meaning = glossary.get(token, "")
            lines.append(f"    - `{token}`" + (f" — {meaning}" if meaning else ""))
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
def report_slug(original_id: str) -> str:
    """Filesystem-safe, still-recognisable file name for one article's report."""
    slug = _SLUG_SAFE_RE.sub("-", str(original_id or "").strip()).strip("-.")
    return (slug or "article")[:150]


def report_paths(law_dir: str | Path, original_id: str) -> tuple[Path, Path]:
    """``(report.json, report.md)`` for one article."""
    base = Path(law_dir) / "_mapping" / REPORT_SUBDIR
    slug = report_slug(original_id)
    return base / f"{slug}.json", base / f"{slug}.md"


def is_report_name(name: str) -> bool:
    """Whether ``name`` is a plain report file name (no path traversal)."""
    return bool(_REPORT_NAME_RE.match(name or ""))


def _fmt_value(value: Any) -> str:
    """Render a payload value for the markdown tables."""
    if value is None or value == "" or value == []:
        return "_(none)_"
    if isinstance(value, list | tuple):
        return ", ".join(f"`{item}`" for item in value) if value else "_(none)_"
    return f"`{value}`"


def _table_cell(text: Any) -> str:
    """One-line, pipe-escaped table cell."""
    flat = re.sub(r"\s*\n+\s*", " ", str(text or "")).strip()
    return flat.replace("|", r"\|") or "—"


def render_report(record: Mapping[str, Any]) -> str:
    """Render one review record as the saved Markdown report.

    The layout is fixed — proposed populations, per-field justification, the
    reusable baseline, then what was applied — so two reports can be diffed and
    a reader always knows where to look.
    """
    suggestions: Sequence[Mapping[str, Any]] = [s for s in (record.get("suggestions") or []) if isinstance(s, Mapping)]
    by_field = {str(s.get("field")): s for s in suggestions}
    fields = [str(f) for f in (record.get("fields_reviewed") or [])]
    taxonomy_in_scope = [f for f in TAXONOMY_FIELDS if f in fields]
    # A classification field gets a subsection even when the model declined to
    # change it — that "declined" record is information. Any other reviewed
    # field gets one only when something was actually proposed, so a metadata
    # suggestion's justification can never be silently dropped.
    justified = list(taxonomy_in_scope)
    for item in suggestions:
        name = str(item.get("field"))
        if name not in justified:
            justified.append(name)
    current_values = record.get("current") if isinstance(record.get("current"), Mapping) else {}

    lines: list[str] = []
    lines.append(f"# Enrichment review — `{record.get('original_id', '?')}`")
    lines.append("")
    if record.get("title"):
        lines.append(f"**Article:** {_table_cell(record['title'])}")
    lines.append(f"**Collection:** `{record.get('collection', '?')}`")
    lines.append(f"**Model:** `{record.get('model') or 'n/a'}`")
    lines.append(f"**Generated:** {record.get('generated_at', '?')}")
    if record.get("source_path"):
        lines.append(f"**Source:** `{record['source_path']}`")
    lines.append(f"**Fields reviewed:** {', '.join(f'`{f}`' for f in fields) or '—'}")
    lines.append("")
    if record.get("summary"):
        lines.append(f"> {_table_cell(record['summary'])}")
        lines.append("")

    # -- 1. proposed populations -------------------------------------------
    lines.append("## 🧭 Proposed Field Populations")
    lines.append("")
    if not suggestions:
        lines.append("_Nothing to propose — the payload already agrees with the source._")
    else:
        lines.append("| Field | Proposed Value | Rationale |")
        lines.append("| --- | --- | --- |")
        for item in suggestions:
            lines.append(
                f"| `{_table_cell(item.get('field'))}` | {_table_cell(_fmt_value(item.get('suggested')))} "
                f"| {_table_cell(item.get('rationale'))} |"
            )
    lines.append("")
    if record.get("dropped"):
        lines.append(f"_{record['dropped']} proposal(s) discarded by the validator before reaching this report._")
        lines.append("")

    # -- 2. detailed justification ----------------------------------------
    lines.append("## 📋 Detailed Justification")
    lines.append("")
    if not suggestions:
        lines.append("_No field warranted a change._")
        lines.append("")
    for field in justified:
        item = by_field.get(field)
        lines.append(f"### `{field}`")
        lines.append("")
        if item is None:
            lines.append(f"- **Current:** {_fmt_value(current_values.get(field))}")
            lines.append("- **Proposed:** unchanged — the model found no element of the text that fixes a value for this field.")
            lines.append("")
            continue
        lines.append(f"- **Current:** {_fmt_value(item.get('current'))}")
        lines.append(f"- **Proposed:** {_fmt_value(item.get('suggested'))}")
        lines.append(f"- **Confidence:** `{item.get('confidence', 'medium')}`")
        if item.get("normalized_from"):
            renames = ", ".join(f"`{r['from']}` → `{r['to']}`" for r in item["normalized_from"])
            lines.append(f"- **Vocabulary normalisation:** {renames}")
        if item.get("unknown_tokens"):
            unknown = ", ".join(f"`{t}`" for t in item["unknown_tokens"])
            lines.append(f"- **New tokens (not in the controlled vocabulary):** {unknown} — needs a maintainer decision")
        if item.get("evidence"):
            lines.append("")
            lines.append(f"> {_table_cell(item['evidence'])}")
        lines.append("")
        lines.append(str(item.get("justification") or item.get("rationale") or "_No rationale given._").strip())
        lines.append("")

    # -- 3. reusable baseline ---------------------------------------------
    lines.append("## 🧩 Baseline for Other Articles")
    lines.append("")
    if not taxonomy_in_scope:
        lines.append("_The classification fields were not in scope for this review._")
        lines.append("")
    else:
        lines.append("The same decision logic applies to every article; only the evidence changes.")
        lines.append("")
        for field in taxonomy_in_scope:
            lines.append(f"### `{field}`")
            lines.append("")
            for rule in rules_for(field):
                lines.append(f"- {rule}")
            lines.append("")
        model_rules = record.get("decision_logic")
        if isinstance(model_rules, Mapping) and model_rules:
            lines.append("Additional heuristics proposed for this article:")
            lines.append("")
            for field in taxonomy_in_scope:
                extra = model_rules.get(field)
                if isinstance(extra, str) and extra.strip():
                    lines.append(f"- **`{field}`** — {_table_cell(extra)}")
                elif isinstance(extra, list):
                    lines.extend(f"- **`{field}`** — {_table_cell(entry)}" for entry in extra if str(entry).strip())
            lines.append("")

    # -- 4. what was applied ----------------------------------------------
    applied: Sequence[Mapping[str, Any]] = [a for a in (record.get("applied") or []) if isinstance(a, Mapping)]
    lines.append("## ✅ Applied Updates")
    lines.append("")
    if not applied:
        lines.append("_Nothing has been written yet._")
    else:
        lines.append("| Applied at | Field | From | To |")
        lines.append("| --- | --- | --- | --- |")
        for entry in applied:
            lines.append(
                f"| {_table_cell(entry.get('at'))} | `{_table_cell(entry.get('field'))}` "
                f"| {_table_cell(_fmt_value(entry.get('from')))} | {_table_cell(_fmt_value(entry.get('to')))} |"
            )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report(law_dir: str | Path, record: Mapping[str, Any]) -> Path:
    """Persist a review record as ``.json`` (source of truth) + ``.md``."""
    json_path, md_path = report_paths(law_dir, str(record.get("original_id") or ""))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_report(record), encoding="utf-8")
    return md_path


def load_record(law_dir: str | Path, original_id: str) -> dict[str, Any] | None:
    """Read one saved review record, or ``None`` when nothing was saved."""
    json_path, _ = report_paths(law_dir, original_id)
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def record_applied(
    law_dir: str | Path,
    original_id: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    timestamp: str | None = None,
) -> Path | None:
    """Append the fields actually written into the saved report.

    Returns the rewritten Markdown path, or ``None`` when the article has no
    saved report (nothing to amend) or ``rows`` is empty.
    """
    if not rows:
        return None
    record = load_record(law_dir, original_id)
    if record is None:
        return None
    stamp = timestamp or datetime.now(UTC).isoformat(timespec="seconds")
    applied = record.get("applied")
    if not isinstance(applied, list):
        applied = []
    for row in rows:
        applied.append(
            {
                "at": stamp,
                "field": str(row.get("field")),
                "from": row.get("from"),
                "to": row.get("to"),
            }
        )
    record["applied"] = applied
    record["applied_at"] = stamp
    return write_report(law_dir, record)


def list_reports(law_dir: str | Path) -> list[dict[str, Any]]:
    """Summarise every saved report, newest first."""
    base = Path(law_dir) / "_mapping" / REPORT_SUBDIR
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for json_path in sorted(base.glob("*.json")):
        record = load_record(law_dir, json_path.stem)
        if record is None:
            continue
        suggestions = record.get("suggestions") or []
        applied = record.get("applied") or []
        out.append(
            {
                "name": f"{json_path.stem}.md",
                "original_id": record.get("original_id"),
                "title": record.get("title") or "",
                "collection": record.get("collection") or "",
                "generated_at": record.get("generated_at") or "",
                "applied_at": record.get("applied_at") or "",
                "suggestions": len(suggestions) if isinstance(suggestions, list) else 0,
                "applied": len(applied) if isinstance(applied, list) else 0,
            }
        )
    out.sort(key=lambda item: str(item.get("applied_at") or item.get("generated_at") or ""), reverse=True)
    return out


__all__ = [
    "DOC_TYPE_GLOSSARY",
    "DOC_TYPE_RULES",
    "ENRICHMENT_FIELDS",
    "ENRICHMENT_FIELD_KINDS",
    "ENRICHMENT_GLOSSARY",
    "ENRICHMENT_RULES",
    "ENRICHMENT_VOCABULARY",
    "REPORT_SUBDIR",
    "TAXONOMY_FIELDS",
    "fold_token",
    "glossary_for",
    "is_report_name",
    "kind_for",
    "list_reports",
    "load_record",
    "normalize_token",
    "normalize_value",
    "record_applied",
    "render_report",
    "report_paths",
    "report_slug",
    "rules_for",
    "vocabulary_block",
    "vocabulary_for",
    "write_report",
]
