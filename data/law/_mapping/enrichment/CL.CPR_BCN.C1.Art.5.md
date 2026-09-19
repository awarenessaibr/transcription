# Enrichment review — `CL.CPR_BCN.C1.Art.5`

**Article:** Art. 5 - Soberanía y deber estatal de respetar y promover derechos
**Collection:** `la8159_law`
**Model:** `deepseek-flash`
**Generated:** 2026-09-19T06:20:51+00:00
**Source:** `CL/Constitucion_BCN.md`
**Fields reviewed:** `doc_type`

> The article's doc_type is unresolved ('unknown') while the snippet header clearly identifies the instrument as the Constitución Política de la República de Chile, so it should be set to 'Constitution'.

## 🧭 Proposed Field Populations

| Field | Proposed Value | Rationale |
| --- | --- | --- |
| `doc_type` | `Constitution` | The document header names the instrument as the 'Constitución Política de la República de Chile', which maps to the controlled token 'Constitution'. |

## 📋 Detailed Justification

### `doc_type`

- **Current:** `unknown`
- **Proposed:** `Constitution`
- **Confidence:** `high`

> # Constitución Política de la República de Chile (BCN official text)

The vocabulary instructs that doc_type be read from the document header, its title, law number or framework_code, not from the article's subject matter. The snippet's top-level heading is 'Constitución Política de la República de Chile (BCN official text)', and the ELI ID 'CL.CPR_BCN.C1.Art.5' confirms the CPR_BCN framework. A 'Constitución' is expressly mapped to the token 'Constitution'.

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

- **`doc_type`** — Read the instrument type from the document header/title or framework_code, never from the article's subject matter; map 'Constitución'/'Constituição' to the controlled token 'Constitution'; only replace 'unknown' when the header explicitly names the instrument.

## ✅ Applied Updates

_Nothing has been written yet._
