# Enrichment review — `INT.MC99.C2.Art.5`

**Article:** Art. 5 — Montreal Convention 1999, Chapter II - Documentation and Duties of the Parties Relating to the Carriage of Passengers, Baggage and Cargo, Article 5 — Contents of Air Waybill or Cargo Receipt
**Collection:** `la8159_law`
**Model:** `deepseek-flash`
**Generated:** 2026-09-19T06:20:29+00:00
**Source:** `INT/EN/MC99_1999.md`
**Fields reviewed:** `doc_type`, `title`, `theme`, `tags`, `source_file`

> The article's metadata is largely complete and consistent; the only clear defect is the unresolved doc_type, which the header identifies as an international convention.

## 🧭 Proposed Field Populations

| Field | Proposed Value | Rationale |
| --- | --- | --- |
| `doc_type` | `Convention` | The document header names the instrument as the 'Montreal Convention 1999', an international treaty, so the controlled token 'Convention' applies. |

## 📋 Detailed Justification

### `doc_type`

- **Current:** `unknown`
- **Proposed:** `Convention`
- **Confidence:** `high`

> ### Art. 5 — Montreal Convention 1999, Chapter II - Documentation and Duties of the Parties Relating to the Carriage of Passengers, Baggage and Cargo, Article 5 — Contents of Air Waybill or Cargo Receipt

The snippet's article heading explicitly reads 'Montreal Convention 1999', identifying the instrument as an international treaty. Under the vocabulary rules, an international treaty or convention maps to the token 'Convention'. The current value 'unknown' is unresolved and is strictly worse than the correct instrument type, which the header directly licenses.

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

- **`doc_type`** — Read the instrument name from the document header/title; map 'Convention' for international treaties. Only replace 'unknown' when the header explicitly names the instrument; otherwise leave it alone since the ingester derives it from framework_code.

## ✅ Applied Updates

_Nothing has been written yet._
