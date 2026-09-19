# Enrichment review — `CL.DFL1_19653.T3.Art.52`

**Article:** Art. 52 - Principio de probidad administrativa
**Collection:** `transcription_law`
**Model:** `deepseek-flash`
**Generated:** 2026-09-19T06:03:08+00:00
**Source:** `CL/DFL1_19653_L18575.md`
**Fields reviewed:** `norm_type`, `scope`, `direction`, `sanctions`, `title`, `theme`, `tags`, `doc_type`, `source_file`

> The article's metadata is largely correct; the only concrete gap is the empty `sanctions` list, which should record the administrative liability the article itself attaches to a breach of the probity principle.

## 🧭 Proposed Field Populations

| Field | Proposed Value | Rationale |
| --- | --- | --- |
| `sanctions` | `administrative_liability` | The article itself states that breach of the probity principle entails the responsibilities and sanctions set by the Constitution, the laws and paragraph 4 of the Title, which maps to administrative liability. |

## 📋 Detailed Justification

### `norm_type`

- **Current:** `principle`, `duty`
- **Proposed:** unchanged — the model found no element of the text that fixes a value for this field.

### `scope`

- **Current:** `public_administration`, `administrative`
- **Proposed:** unchanged — the model found no element of the text that fixes a value for this field.

### `direction`

- **Current:** `mandatory`
- **Proposed:** unchanged — the model found no element of the text that fixes a value for this field.

### `sanctions`

- **Current:** _(none)_
- **Proposed:** `administrative_liability`
- **Confidence:** `medium`

> Su inobservancia acarreará las responsabilidades y sanciones que determinen la Constitución, las leyes y el párrafo 4° de este Título, en su caso.

Article 52, third paragraph, expressly provides that inobservance of the probity principle 'acarreará las responsabilidades y sanciones que determinen la Constitución, las leyes y el párrafo 4° de este Título'. The vocabulary rule maps 'acarreará responsabilidades' to `administrative_liability`. Because the consequence is attached by this very article, it is not a sanction described only elsewhere. The reference to paragraph 4 does not make the consequence purely disciplinary, so the broader administrative liability token is the safest fit.

### `doc_type`

- **Current:** `unknown`
- **Proposed:** unchanged — the model found no element of the text that fixes a value for this field.

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

- **`norm_type`** — Keep existing tokens when the article states a general principle and imposes a duty on named subjects; do not add facets not explicitly present.
- **`scope`** — Keep existing tokens when the addressees are the public administration and its officials and the domain is administrative law.
- **`direction`** — Keep 'mandatory' where the operative verb is 'deberán'.
- **`sanctions`** — Scan the article's own text for consequence language ('acarreará', 'será sancionado', 'incurrirá en'); map 'acarreará responsabilidades' to administrative_liability; do not infer sanctions from the instrument's topic or from other articles.
- **`doc_type`** — Leave as 'unknown' because the snippet does not supply a controlled doc_type token.

## ✅ Applied Updates

| Applied at | Field | From | To |
| --- | --- | --- | --- |
| 2026-09-19T05:53:15+00:00 | `direction` | _(none)_ | `mandatory` |
| 2026-09-19T05:53:15+00:00 | `scope` | _(none)_ | `public_administration`, `administrative` |
| 2026-09-19T05:59:05+00:00 | `norm_type` | _(none)_ | `principle`, `duty` |
