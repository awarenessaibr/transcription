# Enrichment review — `BR.D11129.T1.Art.1`

**Article:** Art. 1 — Decreto nº 11.129/2022, Capítulo I, Art. 1º – Objeto e âmbito de aplicação
**Collection:** `la8159_law`
**Model:** `deepseek-flash`
**Generated:** 2026-09-19T06:20:44+00:00
**Source:** `BR/D11129_PNDH3.md`
**Fields reviewed:** `doc_type`

> The article's doc_type is unresolved ('unknown') while the snippet header clearly names a Decreto, so it can be confidently set to 'Decree'.

## 🧭 Proposed Field Populations

| Field | Proposed Value | Rationale |
| --- | --- | --- |
| `doc_type` | `Decree` | The document header names 'Decreto nº 11.129, de 11 de julho de 2022', and the vocabulary maps Decreto to the token 'Decree'. |

## 📋 Detailed Justification

### `doc_type`

- **Current:** `unknown`
- **Proposed:** `Decree`
- **Confidence:** `high`

> # Decreto nº 11.129, de 11 de julho de 2022

The vocabulary instructs that doc_type be read from the document header (title, law number or framework_code), not from the article's subject matter. The snippet's top-level heading is 'Decreto nº 11.129, de 11 de julho de 2022', and the article title repeats 'Decreto nº 11.129/2022', with framework_code D11129. Under the rule that 'Decreto' is 'Decree', the correct token is 'Decree'.

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

- **`doc_type`** — Read the instrument type from the document header (H1 title, law number, or framework_code), never from the article's subject matter; map Decreto/DTO/Decreto con Fuerza de Ley to 'Decree', Lei/Ley to 'Law', codified statutes to 'Code', etc. Only override an 'unknown' value when the header explicitly names the instrument; leave it untouched if no header is visible.

## ✅ Applied Updates

_Nothing has been written yet._
