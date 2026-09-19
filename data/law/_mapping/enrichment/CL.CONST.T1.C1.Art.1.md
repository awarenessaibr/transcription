# Enrichment review — `CL.CONST.T1.C1.Art.1`

**Article:** Art. 1 — Constitución Política de Chile, Capítulo I, Artículo 1
**Collection:** `transcription_law`
**Model:** `deepseek-flash`
**Generated:** 2026-09-19T06:50:59+00:00
**Source:** `CL/Constitucion.md`
**Fields reviewed:** `norm_type`, `scope`, `direction`, `sanctions`, `title`, `theme`, `tags`, `doc_type`, `source_file`, `content`

> The article's metadata is largely correct; the only clear defect is the unresolved `doc_type` of "unknown", which the document header and EXPECTED both identify as a Constitution.

## 🧭 Proposed Field Populations

| Field | Proposed Value | Rationale |
| --- | --- | --- |
| `doc_type` | `Constitution` | The document header names the instrument "Constitución Política de Chile", so the controlled token `Constitution` applies. |

## 📋 Detailed Justification

### `norm_type`

- **Current:** `right`
- **Proposed:** unchanged — the model found no element of the text that fixes a value for this field.

### `scope`

- **Current:** `constitutional`
- **Proposed:** unchanged — the model found no element of the text that fixes a value for this field.

### `direction`

- **Current:** _(none)_
- **Proposed:** unchanged — the model found no element of the text that fixes a value for this field.

### `sanctions`

- **Current:** _(none)_
- **Proposed:** unchanged — the model found no element of the text that fixes a value for this field.

### `doc_type`

- **Current:** `unknown`
- **Proposed:** `Constitution`
- **Confidence:** `high`

> # Constitución Política de Chile

The vocabulary instructs that `doc_type` is read from the document header, its title, its law number or `framework_code`, never from the article's subject matter. The snippet's header reads "# Constitución Política de Chile" and the article title repeats "Constitución Política de Chile", and the framework_code is CONST. The offline ingester likewise computes `Constitution`, so replacing the unresolved `unknown` is a low-risk, high-confidence correction.

## 🧩 Baseline for Other Articles

The same decision logic applies to every article; only the evidence changes.

### `norm_type`

- Read what the article *does*, not what it is about: a statement of general policy is `principle`, a command addressed to a subject is `duty`.
- Take the main verb of the operative sentence. A provision that forbids is `prohibition`, one that confers is `right` or `power`, one that prescribes `step by step` conduct is `procedural`.
- An article can carry several facets — “the officials shall refrain…” is both `duty` and `prohibition`. Return every facet that is explicitly there.
- Use `definition` only for an article whose job is to fix the meaning of a term, and `penalty` only where the article itself attaches a consequence.
- Never infer a facet from the document title; base it on the article's own text.

### `scope`

- Identify the addressees: `autoridades`, `funcionarios`, `Administración del Estado` are `public_administration`; a municipal organ is `municipal`; a regional government is `regional`.
- If the addressee is the state as a whole rather than a particular body, use `state`; if the provision is general and territorial, `national`.
- Legal *domain* and *addressee* are different axes — “data protection duties of public bodies” is `public_administration` plus `data_processing`. Both belong.
- Prefer a domain token (`administrative`, `regulatory`, `criminal`, `constitutional`) over a vague one; only add a second token when the text genuinely spans two domains.

### `direction`

- Map the modality of the main verb — this field is a single token, not a list: `deberán`/`shall`/`é obrigatório` → `mandatory`; `no podrán`/`é vedado`/`may not` → `prohibitive`; `podrán`/`may` → `permissive`.
- `procurarán`, `se recomienda` and similar aspiration language is `advisory`, not `mandatory` — soft-law instruments must not be recorded as commands.
- A provision whose only purpose is to limit an existing right or an existing scope is `restrictive`, even when it is phrased permissively.
- An enabling provision — one that says an organ may exercise a power — is `authority`; reserve `permissive` for permissions granted to regulated subjects.
- Leave `direction` out entirely when the article contains no operative verb (a definition, a table of contents): an empty field is more accurate than a guess.

### `sanctions`

- Record only consequences the article itself states — a sanction described only in another article belongs to that article.
- Match the consequence to a token: `acarreará responsabilidades` / `responsabilidad administrativa` → `administrative_liability`; `será sancionado con multa` → `financial_penalty`; `incurrirá en responsabilidad penal` → `criminal_liability`; a disciplinary hearing → `disciplinary_sanction`.
- `indemnizará` / `resarcirá` is `civil_liability` or `monetary_compensation`, not a penalty.
- An article can attach several consequences; return each one.
- Most articles attach none — an empty list is the correct answer, not a gap to fill. Never infer a sanction from the topic of the instrument.

### `doc_type`

- `doc_type` names the instrument the article belongs to: read it from the document header (its title, its law number, or `framework_code`), never from the article's subject matter.
- Return exactly one token from the list below. `doc_type` is a single string, never a list.
- A codified instrument is `Code` even when an ordinary law enacted it: `Código Civil`, `Código Penal`, `Código Brasileiro de Aeronáutica`.
- `Ley`/`Lei` is `Law`; `Decreto`, `DTO` or `Decreto con Fuerza de Ley` is `Decree`; `Constitución`/`Constituição` is `Constitution`; an ICAO annex or document is `ICAO`; a regulator's `Resolución`/`Resolução` is `Resolution`.
- Only propose a value when the header actually names the instrument. If the snippet shows no header, leave the value alone — the ingester derives this field from `framework_code`, so a guess here contradicts it.
- `doc_type` is also read as `norm_type` by a downstream knowledge base, so an unresolved `unknown` is strictly better than a wrong instrument type.

Additional heuristics proposed for this article:

- **`norm_type`** — Keep the existing `right` token: the article confers rights ("Persons are born free and equal, in dignity and rights") and the ingester agrees; no change needed.
- **`scope`** — Keep `constitutional`: the provision is constitutional law and the ingester agrees; no second domain token is warranted by the text.
- **`direction`** — Leave null: the article states principles and duties without a single operative modal verb mapping cleanly to mandatory/prohibitive/permissive, and the ingester also leaves it null.
- **`sanctions`** — Leave empty: the article attaches no consequence to a breach, and the vocabulary warns against inferring sanctions from the instrument's topic.
- **`doc_type`** — Read the instrument type from the document header/title or framework_code; if the header names a Constitución/Constituição, set `Constitution`. Only replace an `unknown`/null value, and never infer doc_type from the article's subject matter.

## ✅ Applied Updates

_Nothing has been written yet._
