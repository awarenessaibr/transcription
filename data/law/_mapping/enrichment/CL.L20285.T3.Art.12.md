# Enrichment review — `CL.L20285.T3.Art.12`

**Article:** Art. 12 — Ley 20.285, Título III, Artículo 12° – Denegación de acceso
**Collection:** `la8159_law`
**Model:** `deepseek-flash`
**Generated:** 2026-09-19T06:20:41+00:00
**Source:** `CL/L20285_Transparencia.md`
**Fields reviewed:** `doc_type`

> The article's doc_type is currently 'unknown' but the header and framework code clearly identify it as an ordinary Chilean statute (Ley 20.285), so it should be set to 'Law'.

## 🧭 Proposed Field Populations

| Field | Proposed Value | Rationale |
| --- | --- | --- |
| `doc_type` | `Law` | The document header names 'Ley 20.285' and the framework code L20285, which is an ordinary statute, matching the controlled token 'Law'. |

## 📋 Detailed Justification

### `doc_type`

- **Current:** `unknown`
- **Proposed:** `Law`
- **Confidence:** `high`

> ### Art. 12 — Ley 20.285, Título III, Artículo 12° – Denegación de acceso

The vocabulary rule states that 'Ley'/'Lei' maps to the token 'Law', and doc_type must be read from the document header or framework_code rather than the article's subject matter. The title 'Art. 12 — Ley 20.285' and the ELI ID 'CL.L20285.T3.Art.12' both identify the instrument as Ley 20.285, an ordinary Chilean statute. Therefore 'Law' is the correct instrument type.

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

- **`doc_type`** — Read the instrument type from the document header/title or framework_code, not from the article's subject matter. Map 'Ley'/'Lei' to 'Law', 'Decreto'/'DTO'/'Decreto con Fuerza de Ley' to 'Decree', 'Constitución' to 'Constitution', codified instruments to 'Code', etc. Only replace 'unknown' when the header explicitly names the instrument; otherwise leave it alone.

## ✅ Applied Updates

_Nothing has been written yet._
