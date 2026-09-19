# Enrichment review — `BR.CBA.T7.C1.Art.224`

**Article:** Art. 224 — CBA Title VII, Chapter I, Article 224 – Combined Transport
**Collection:** `la8159_law`
**Model:** `deepseek-flash`
**Generated:** 2026-09-19T06:20:46+00:00
**Source:** `BR/L7565_CBA.md`
**Fields reviewed:** `doc_type`

> The article's doc_type is unresolved ('unknown') while the header and framework_code (CBA) identify the instrument as the Brazilian Aeronautical Code, so a single high-confidence update to 'Code' is warranted.

## 🧭 Proposed Field Populations

| Field | Proposed Value | Rationale |
| --- | --- | --- |
| `doc_type` | `Code` | The document header and framework_code 'CBA' name the Código Brasileiro de Aeronáutica, a codified statute, which the vocabulary maps to 'Code'. |

## 📋 Detailed Justification

### `doc_type`

- **Current:** `unknown`
- **Proposed:** `Code`
- **Confidence:** `high`

> **ELI ID:** `BR.CBA.T7.C1.Art.224`

The vocabulary instructs that doc_type be read from the document header, its law number or framework_code, never from the article's subject matter. The title 'CBA Title VII, Chapter I, Article 224' and the ELI ID 'BR.CBA.T7.C1.Art.224' both derive from the Código Brasileiro de Aeronáutica, and the vocabulary expressly lists CBA as an example of a codified instrument that is 'Code'. Since the current value is the unresolved placeholder 'unknown', replacing it with the controlled token 'Code' is a low-risk, high-confidence correction.

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

- **`doc_type`** — Read the instrument from the document header, law number or framework_code (here 'CBA' / ELI ID BR.CBA...), not from the article's subject matter; map a codified statute such as the Código Brasileiro de Aeronáutica to the controlled token 'Code'. Only fill the field when the header actually names the instrument and the current value is empty, null or 'unknown'; otherwise leave it untouched.

## ✅ Applied Updates

_Nothing has been written yet._
