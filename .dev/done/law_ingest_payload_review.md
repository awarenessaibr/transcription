# Law ingest payload — schema v1 review

**Status:** decisions recorded, Phase 1 in progress
**Scope:** `transcription_law` (repo-owned) only. `la8159_law` / `la8159_law_bm25`
are **out of scope** and sign-off gated.
**Input:** `.dev/law_ingest_payload_implementation-needed.md` (external proposal)
**Evidence base:** measured against the live collection (1119 points), the real corpus
(100 files / 1119 articles / 4 reference-only files), and the sibling project
`discovery/` that shares the canonical collections.

---

## Correction to the proposal's premise

The proposal states:

> The current random UUID (`b7de404c-7c40-...`) creates a new point every run.

This is false, and it is load-bearing for the proposal's ID change. Measured on
`la8159_law`:

```
uuid5(NAMESPACE_DNS, original_id)                834   <- this repo
uuid5(6f1e6a9d-2a0a-4c0c-9e1e-a1b2c3d4e5f6, …)   285   <- discovery/case-server
neither                                            0
uuid version nibble distribution: {'5': 1119}
```

All 1119 point IDs are deterministic UUIDv5. The other 285 come from
`discovery/case-server/pipeline/ingest_new_law.js`, whose own header reads:

```js
const NS = '6f1e6a9d-2a0a-4c0c-9e1e-a1b2c3d4e5f6'; // namespace for v5 ids
// Deterministic UUIDv5 point ids derived from original_id → idempotent upserts.
```

`b7de404c-7c40-5773-ad96-e7d462fc8591` *is* `uuid5(NAMESPACE_DNS, "BR.CBA.T3.C1.Art.74")`.
Re-ingest is already idempotent because `existing_index()` resolves points by the
`original_id` **payload field**, not by recomputing an ID.

The proposal's replacement recipe is also not injective on this corpus:

```
article|{framework_code}|{article_number}   1119 ELIs → 868 distinct IDs
                                            50 colliding IDs covering 301 ELIs
```

| Cause | Impact | Example |
|---|---|---|
| `eli.rsplit(".Art.", 1)[-1].split(".")[0]` on an ELI with no `.Art.` returns the **jurisdiction** | 69 ELIs get `article_number="BR"` | `BR.ABEAR_COC.SA.I` → `'BR'`; `BR.D1171.Anexo.C1.S1.I` → `'BR'` (25 collide) |
| `(framework_code, article_number)` is not unique — tier/chapter/section/paragraph segments are load-bearing | 50 pairs repeat | `('AN9','9')` ×28: `Art.9.1`, `Art.9.1.1`, `Art.9.10`… |

Switching recipes would also orphan every point: proposed ID == live ID for
**0 / 1119** articles.

**Outcome:** `article_number` is retained as a *helpful scalar field* (the proposal's
stated motivation — "so a lookup by article number doesn't have to reverse-engineer
the ELI tail"), but point identity stays `uuid5(NAMESPACE_DNS, eli)`. A guard test
(Phase 1.3) makes both of these facts executable so the recipe cannot regress.

The proposal also conflates three distinct schemas. Its "already present" annotations
are true of `la8159_law_bm25` or `transcription_law`, not of `la8159_law`, which has
exactly 10 payload keys:

```
original_id · title · theme · tags · text · content · source_file · doc_type
· original_data · metadata
```

---

## Decisions

### 1. Scope

**Decision: `transcription_law` only. Canonical migration is a separate, sign-off-gated proposal.**

Evidence: canonical is read by `legal_kb.js` and `ingest_new_law.js`. Its shape is
documented in `discovery/ref_docs/law-ingestion-guide.md §9` as "verified against live
payloads" (§9 lists `original_id`, `text`, `content`, `doc_type`, `original_data`,
`metadata`). Any change there is a cross-repo contract change and needs the sibling
maintainer in the loop. The new schema should prove itself against real queries in
`transcription_law` before we ask anyone to migrate.

Cost: two collections on different schemas for the transition window. Mitigated by a
collection-level `schema_version` sentinel point so readers can discover which is which.

---

### 2. `doc_type`

**Decision: keep as-is; add `record_kind`.**

Evidence — the sharpest finding in the audit:

```js
// discovery/case-server/pipeline/legal_kb.js:159
norm_type: pl.doc_type || null,
```

`doc_type` is *consumed* as `norm_type` by a live reader. Setting it to
`"law_article"` makes every KB article's `norm_type` read as `"law_article"` — a
silent, invisible break (no error, no warning, just wrong classification downstream).
Real `doc_type` distribution today: `unknown` 654, `Resolution` 178, `ICAO` 141,
`Internal` 112, `CDC` 33, `IN` 1. `record_kind: "article" | "reference"` is a new key
that nobody consumes and nobody can break.

Cost: 24 B/point. Zero risk.

---

### 3. `original_id` / `eli_id`

**Decision: dual-write both keys through the transition. Both equal. Both identity
(read-only). Deprecate `original_id` only after both JS filter sites migrate.**

Evidence — both sibling readers filter on this key with exact match:

```js
legal_kb.js:170       filter: { must: [{ key: 'original_id', match: { value: eliId } }] }
ingest_new_law.js:217 filter: { must: [{ key: 'original_id', match: { value: oid } }] }
```

A hard rename returns *zero results*, not an error. That's the worst kind of break —
silent, and only discovered when someone notices a lookup stopped working.
`legal_kb.js:144` already tolerates `pl.original_id || pl.eli_id` on the read path, so
dual-write makes this a no-op for consumers.

Cost: 24 B/point. Deprecation decision deferred to Phase 6.

---

### 4. `original_data`

**Decision: drop in local; keep in canonical until the sibling guide is updated and
sign-off obtained.**

Evidence: the audit found no reader anywhere in this repo, and measured
**~1006 B/point — roughly 36% of the 2818 B average payload** (`original_data` is a
verbatim copy of `title`/`source_file`/`theme`/`tags`/`content`/`original_id` plus the
point ID). The measured cost is real. But `discovery/ref_docs/law-ingestion-guide.md §9`
documents it as part of the live shape, and the sibling ingest path may use it as a
fallback. Prove the drop against real local queries first; propose the canonical drop
as a separate change.

Cost: ~1.1 MB on `transcription_law` if we kept it; zero on canonical.

---

### 5. `tags`

**Decision: target-aware.** Canonical stays `str`. Local becomes `list`. The editor
renders both (`str` → textarea, `list` → chip-editor).

Evidence: `EDITABLE_PAYLOAD_FIELDS` currently enforces `isinstance(value, str)`, and 45
Style-B blocks would emit `tags=[]` under the proposal's parser because that branch
never appends to `out["tags"]`. Two distinct shapes are already in the corpus. The
honest answer isn't "pick one" — it's "the local schema is new, the canonical schema is
load-bearing."

Cost: `build_payload_patch` gains one branch. The editor gains one branch. No test churn
on canonical.

---

### 6. `content` / `text`

**Decision: alias. Both keys present, both equal, both writable; `build_payload_patch`
re-derives one from the other.**

Evidence: `content` is the *editable* field in the current UI; `text` is what BM25
indexes. They are byte-identical (1119/1119 confirmed), so the redundancy is real — but
dropping `content` in one change touches:

- `build_payload_patch`'s re-derivation logic
- the diff badges in `law-registry.html`
- the `_ORIGINAL_DATA_MIRROR` (which carries `content`)
- the 128 existing tests

An alias costs ~700 B/point (~780 KB on local) but is one line of re-derivation and zero
test churn. Drop `content` in Phase 6 alongside the UI migration, once `original_data` is
already gone and the editor is already list-aware.

---

## Summary

| # | Decision | Delta on local | Risk if wrong |
|---|---|---|---|
| 1 | Local only | — | Low (canonical untouched) |
| 2 | Keep `doc_type`, add `record_kind` | +24 B | None (additive) |
| 3 | Dual-write `original_id` + `eli_id` | +24 B | Low (no-op for readers) |
| 4 | Drop `original_data` (local only) | −1006 B | Medium (documented in sibling) — gated by Phase 5 dry-run review |
| 5 | Target-aware `tags` | shape change | Low (editor handles both) |
| 6 | `content` alias | +700 B | None (transition state) |

Net on local (**measured**: mean **−804.9 B/point**, range −12375 … −84) vs today — the
estimate above was low because `original_data` carries a full copy of the body, not just
the metadata. Net on canonical (**measured**: mean **+89.8 B/point**, range −700 … +133) if
we dual-write identity keys and `record_kind` — the 4 new keys cost +48 B, and the rest is
value churn described in "What the migration diff found" below.

---

## Phase 1 — the reviewable slice

Offline only: **no Qdrant writes, no UI changes, no migration.**

> **Status: all five items landed.** `ruff` clean; `tests/unit/test_qdrant_law_index.py` +
> `tests/unit/test_law_registry_api.py` = **177 passed** (was 128); full `tests/unit` =
> 266 passed, with only the 3 pre-existing `test_validate_refine_mcp.py` failures. Item 5 ran
> against both live collections and wrote nothing — see "What the migration diff found".

1. `parse_article_tags` with the bilingual key-alias table and comma-joined
   multi-value normalisation.
2. `article_number_for(eli)` — last segment after the final `Art.`, sub-numbers
   preserved; falls back to the last segment when there is no `Art.` token.
3. **Collision guard test** — run the ID recipe over all 1119 corpus ELIs, assert 1119
   distinct IDs, assert each equals `uuid5(NAMESPACE_DNS, eli)`, assert `existing_index()`
   lookups match. This is the test that would have caught the proposal's premise being
   wrong.
4. Extend `LawArticle` with the new fields; `to_payload(target=...)` emits schema v1 for
   local and the additive set for canonical.
5. `scripts/ingest_law_corpus.py migrate --target local --dry-run` emits per-point field
   diffs, no writes.

### Phase 1 sub-decisions (made because the proposal left them open)

These are called out so they can be reviewed independently of the six decisions above.

| Item | Decision | Why |
|---|---|---|
| `norm_type` / `scope` typing | `list[str]` (possibly empty), not `str \| None` | The corpus genuinely carries multi-value tokens (`norm_type: duty, penalty`, `tipo_norma: dever · escopo: constitucional`). Comma-joining "normalisation" is only lossless as a list. Qdrant keyword indexes accept arrays, so filtering is unaffected. |
| `direction` typing | `str \| None` | Single-valued by nature; only ever sourced from Style B (`**Direction:**`). |
| `sanctions` typing | `list[str]` | As the proposal specified. |
| Bilingual keys | Accent-folded alias table: `norm_type ← tipo_norma`, `scope ← escopo \| âmbito`, `direction ← direção`, `sanctions ← sanções` | Measured vocabulary: `norm_type` 1063, `scope` 1036, `tipo_norma` 230, `âmbito` 198, `sanctions` 158, `escopo` 32, `sanções` 15. Without folding, 230 blocks silently lose their classification. |
| Label regexes | Reuse the module's existing compiled bilingual regexes (`Theme|Tema`, `Tags|Etiquetas`) instead of the proposal's English-only inline ones | The proposal's patterns miss `**Etiquetas:**` (63 blocks) and `**Tema:**` (281 blocks). |
| `tags` raw tokens | New `LawArticle.tag_tokens: list[str]`, keeping `tags: str` as-is | Canonical writes the `str`, local writes the list. Both representations are needed by decision 5. |
| `ingested_at` / `updated_at` | New `_iso_utc_now()` (with `Z`), used only by the new fields | `_iso_now()` stays untouched so canonical `metadata.ingestion_time` is byte-stable, per decision 1's "+48 B and nothing else". |

### Measured impact of the parser change

Block-level counts over the real corpus: 100 files, **1621 article blocks**, of which
**1408 carry an ELI**. The "proposal" column is a faithful re-implementation of the
proposal's parser (English keys only, `**Tags:**` line only); the "Phase 1" column is
the shipped `parse_article_tags`.

| metric | proposal parser | Phase 1 | delta | source of the delta |
|---|---|---|---|---|
| `norm_type` populated | 1063 | **1338** | +275 | `tipo_norma` (230) + Style B inline `**Norm type:**` (45) |
| `scope` populated | 1036 | **1311** | +275 | `escopo` (32) + `âmbito` (198) + Style B inline `**Scope:**` (45) |
| `direction` populated | 0 | **45** | +45 | `direction` was absent from the proposal's table entirely |
| `sanctions` populated | 0 | **173** | +173 | `sanctions` was absent from the proposal's table entirely |
| `tags` non-empty | 1293 | **1338** | +45 | Style B blocks, which the proposal never inspects |
| blocks with **no** classification | 558 | **283** | −275 | remaining 283 are genuinely untagged |
| unrecognised tag keys | 7 observed | **0** | −7 | `aliases known` covers every observed key |

Observed key vocabulary (accent-folded): `norm_type` 1063, `scope` 1036, `tipo_norma` 230,
`ambito` 198, `sanctions` 158, `escopo` 32, `sancoes` 15.

`UNKNOWN keys: {}` — the alias table resolves 100 % of the corpus vocabulary, so no key is
dropped silently.

Effect on `plan.articles` (after locale-variant de-duplication, `preferred_language="en"`):

| metric | value |
|---|---|
| `plan.articles` | 1119 |
| classified | 1049 (**93.7 %**) |
| tags empty | 70 |
| `source_path` project-relative | yes |

The 230 Portuguese-keyed blocks do **not** all survive into `plan.articles`: `build_plan`
de-duplicates locale variants and keeps the English one, so 1408 blocks collapse to 1119
articles. The English variants of those same articles are the ones that use `norm_type:`,
which is why the ratio rises from 84.1 % (941/1119) to 93.7 % rather than by the full 275.
Corpus tests that assert per-block tag properties must therefore iterate parsed blocks, not
`plan.articles` — `test_portuguese_tag_keys_are_not_silently_dropped` does exactly that.

Reproduce with a block-level scan; `scripts/ingest_law_corpus.py plan --tag-coverage` reports
the `plan.articles` row only.

---

## What the migration diff found

`scripts/ingest_law_corpus.py migrate --target {local,canonical} --dry-run` (Phase 1 item 5)
compares each live payload against what the current writers would emit, matched on
`original_id`. It **writes nothing**. Both collections were reconciled live: 1119 points,
1119 distinct ELIs, **0 would-create, 0 orphans**, all 1119 point IDs reused as-is.

### `--target local` (`transcription_law`)

| field | added | removed | changed |
|---|---|---|---|
| `eli_id`, `article_number`, `norm_type`, `scope`, `direction`, `sanctions`, `source_sha256`, `record_kind`, `reference_only`, `data_type`, `schema_version`, `ingested_at`, `updated_at` | 1119 each | — | — |
| `original_data`, `metadata`, `sha256_short` | — | 1119 each | — |
| `tags` | — | — | 1119 |
| `source_path` | — | — | 1119 |

13 added, 3 removed, 2 changed, on 12 keys kept = **25 keys**, matching `local_payload()`
exactly. Mean **−804.9 B/point**. `tags` is `str → list` and `source_path` goes relative →
the two intended shape changes, and nothing else moves: no `content`/`text` churn, because
this collection was built by *this* repo's parser.

### `--target canonical` (`la8159_law`) — the sign-off gated one

| field | added | removed | changed |
|---|---|---|---|
| `eli_id`, `article_number`, `record_kind`, `schema_version` | 1119 each | — | — |
| `doc_type` + `metadata` | — | — | 26 |
| `content`, `text`, `original_data` | — | — | **331** |

Key-wise it is **additive only** (4 added, 0 removed) — decision 3 holds. Two findings:

**1. 285 point IDs differ from `stable_point_id(eli)`.** They were built by
`discovery/case-server/pipeline/ingest_new_law.js` under a *second* namespace
(`6f1e6a9d-…`), not `NAMESPACE_DNS`. The tool therefore **reuses the live ID** and never
recomputes one — recomputing would have reported 285 phantom "would create" points. This is
the trap from the audit, now handled in code rather than in a comment.

**2. A refresh would change article *text* on 331 points.** A first pass attributed the 331
to just two causes (280 separator + 51 "content loss") and concluded that a canonical refresh
would destroy body text on 51 articles. **That was wrong.** Per-case diagnosis of all 51
splits them into four buckets, of which only the third is a parser defect:

| count | live-only prefix pattern | cause | would a refresh lose body text? |
|---|---|---|---|
| 280 | (none — tail only) | projection *adds* the `---` separator the live payload lacks | no |
| 26 | `**Norm type:** …` | stale payload: metadata retained in `text` | no |
| 18 | `**Hierarchy:** …` + `**Norm type:** …` | stale payload: metadata retained in `text` | no |
| 1 | `**Added by:** …` + `**Norm type:** …` | hybrid of the above two | no |
| 4 | `**Agente Público:** …` | **body-open paragraph absorbed into metadata** | **yes** |
| 1 | `**Dirección General de Aeronáutica Civil:** …, **DGAC:**` | **body-open paragraph absorbed into metadata** | **yes** |
| 1 | plain prose | stray editorial token in the live payload, not a parser issue | no |

280 + 45 + 5 + 1 = **331**. So:

* **45 articles** are *stale payloads*, not parser bugs. An older writer stripped only the
  `ELI ID` line and left `**Hierarchy:**` / `**Norm type:**` inside `text`; the current
  convention is body-only (the 788 exact matches confirm it). A refresh would **remove one or
  two metadata lines** from those payloads — hygiene, but still real churn in BM25 and
  embeddings on 45 shared production points.
* **5 articles** are a genuine defect, caused by `_METADATA_LINE_RE` being a *generic*
  `**label:**` predicate: a body-opening bold-labelled paragraph is absorbed into the
  metadata block and dropped from `content`. Proven example, `BR.ABEAR_PAC.Art.3` (source
  `ABEAR_PoliticaAnticorrupcao.md`, paragraph present at line 47):

  ```
  corpus block body (what the current parser yields)
    "i. Membros de qualquer Poder da União, …"

  live la8159_law payload
    "**Agente Público:** Indivíduo que, por força da lei, … não taxativa:
     i. Membros de qualquer Poder da União, …"
  ```

  A refresh would **newly strip that paragraph** from those 5 payloads. Nothing else in the
  331 loses body text.
* It is **already baked into** `transcription_law` — that is exactly why the local diff shows
  zero `content` churn: both sides came from this parser. The 5 leaked paragraphs are
  therefore already missing from local too.
* The 331 reconciles the existing `normalize_content` docstring, which reported
  `keep_separator=True` → 788/1119 exact: `1119 − 331 = 788`. The docstring attributed all
  331 misses to the separator; it now records the four-way split.

The repo's own validator already tracks this as `content_drift 51`, and the notes labelled
those 51 "legacy revisions". **That label is wrong**: they are a writer-convention change
(45), a parser defect (5), and one data anomaly (1) — not corpus revisions.

### What the fix actually is (and the fix that does *not* work)

Naively, the metadata block should end at the first blank line. **That heuristic is broken** —
it was implemented and measured: corpus articles drop **1119 → 1085** (34 lost, because the
blocks whose metadata carries an internal blank line then lose their `ELI ID` and are
discarded by `build_plan`), empty `tags` rise 70 → 115, and `classified` falls 1049 → 1015.

The safe discriminator is a **label whitelist**, and the vocabulary is empirically *closed*.
Across 2187 blocks there are 503 distinct bold labels, but only 12 occur more than once:

```
ELI ID 1357 · Tags 1230 · Theme 1058 · Tema 281 · Etiquetas 63
ID ELI 51 · Norm type 45 · Hierarchy 42          <- the metadata vocabulary
Agente Público 4 · Article N 3 · NOTA 3          <- body paragraphs (the leak)
```

A whitelist-restricted `_is_metadata_line` was prototyped in memory (no repo edit) and
measured: **articles stay 1119, ELIs stay 1119, `classified` stays 1049**, and it recovers
exactly the 5 body-leak articles plus `CL.DAN17.Art.11`. Parity moves
`788 exact / 280 normalized / 51 drift` → `789 / 284 / 46`. It correctly leaves the 45 stale
payloads alone, because `Hierarchy` / `Norm type` *are* metadata.

**Recommendation:** land the whitelist-based `_is_metadata_line` as its own reviewed change
before any canonical refresh, so the 5 leaked paragraphs are restored rather than lost. It
is deliberately **not** bundled into Phase 1. Separately decide what to do about the 45 stale
payloads, whose `text` legitimately changes.

### Also measured: `doc_type` disagrees with live on 26 points

`doc_type_for()` is path-derived and disagrees with the stored values in **both** directions:
`ICAO → unknown` (3), `CDC → unknown`, `Resolution → unknown`, `IN → unknown`,
`unknown → ICAO` (8), `Internal → ICAO` (11), `Internal → unknown` (1). The path-derived
values look *more* correct (`BR.D7724_LAI_Regulamento.md` is Brazilian, not `ICAO`), but a
sibling reads this field as `norm_type` (`discovery/…/legal_kb.js:159`), so a canonical
refresh would silently re-type 26 production articles. Either accept it explicitly or pin
`doc_type` during the canonical refresh — do not let it ride along in an "additive only"
change.

---

## Not in Phase 1 (deferred, explicitly)

- **The whitelist-based `_is_metadata_line` fix** (§ "What the fix actually is"), which
  restores the 5 leaked body paragraphs. Its own reviewed change, to land before any
  canonical refresh.
- A decision on the 45 stale payloads whose `text` legitimately changes on refresh.
- Reference-only point emission (Phase 4) — needs an explicit `framework_code` mapping
  table for the 4 files; the proposal's `"CC"` has no derivation.
- Payload indexes on `transcription_law` (Phase 3).
- Any `la8159_law` write (sign-off gated).
- `law-registry.html` changes: the `NESTED = ['original_data','metadata']` handling, the
  list-aware tag editor, and diff badges for `tags`/`content` when the target is local.
