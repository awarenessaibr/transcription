# Enrichment review — `INT.UNGCP.Principle.11`

**Article:** Principle 11 — Principles for good business practices (excerpt in scope)
**Collection:** `la8159_law`
**Model:** `deepseek-flash`
**Generated:** 2026-09-19T06:20:49+00:00
**Source:** `INT/EN/UNGCP.md`
**Fields reviewed:** `doc_type`

> The article's doc_type is currently 'unknown' but the snippet identifies the instrument as the UN Guidelines for Consumer Protection (UNGCP), a non-binding soft-law instrument, so it should be classified as 'Guidelines'.

## 🧭 Proposed Field Populations

| Field | Proposed Value | Rationale |
| --- | --- | --- |
| `doc_type` | `Guidelines` | The snippet's header identifies the instrument as the UN Guidelines for Consumer Protection, a non-binding soft-law instrument matching the 'Guidelines' token. |

## 📋 Detailed Justification

### `doc_type`

- **Current:** `unknown`
- **Proposed:** `Guidelines`
- **Confidence:** `high`

> official UN General Assembly resolution PDF for A/RES/70/186 (stored as scoped excerpts used by INT_SOFTLAW)

The document header names the instrument as the 'Principles' of the UN Guidelines for Consumer Protection (UNGCP), an official UN General Assembly resolution (A/RES/70/186). The vocabulary rule states that non-binding guidelines or model articles are classified as 'Guidelines'. The snippet's tags ('norm_type: soft_law_principle') confirm the non-binding, soft-law character of the instrument.

## 🧩 Baseline for Other Articles

The same decision logic applies to every article; only the evidence changes.

### `doc_type`

- `doc_type` names the instrument the article belongs to: read it from the document header (its title, its law number, or `framework_code`), never from the article's subject matter.
- Return exactly one token from the list below. `doc_type` is a single string, never a list.
- A codified instrument is `Code` even when an ordinary law enacted it: `Código Civil`, `Código Penal`, `Código Brasileiro de Aeronáutica`.
- `Ley`/`Lei` is `Law`; `Decreto`, `DTO` or `Decreto con Fuerza de Ley` is `Decree`; `Constitución`/`Constituição` is `Constitution`; an ICAO annex or document is `ICAO`; a regulator's `Resolución`/`Resolução` is `Resolution`.
- Only propose a value when the header actually names the instrument. If the snippet shows no header, leave the value alone — the ingester derives this field from `framework_code`, so a guess here contradicts it.
- `doc_type` is also read as `norm_type` by a downstream knowledge base, so an unresolved `unknown` is strictly better than a wrong instrument type.

Additional heuristics proposed for this article:

- **`doc_type`** — Read the instrument type from the document header (title, law number, or framework_code), never from the article's subject matter. Match against the controlled vocabulary; non-binding guidelines or model articles map to 'Guidelines'. Only propose a value when the header actually names the instrument; otherwise leave 'unknown' in place.

## ✅ Applied Updates

_Nothing has been written yet._
