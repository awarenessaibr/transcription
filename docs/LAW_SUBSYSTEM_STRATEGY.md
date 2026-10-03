# Law Subsystem Strategy

**Date:** 2026-10-03
**Status:** proposal — no code changed by this document
**Context:** decision 5 of §12 in [REDUCED_CORE_MANIFEST.md](REDUCED_CORE_MANIFEST.md): *"Law subsystem needs to be defined the best strategy."*

---

## 1. What the subsystem is

| Component | Lines | Role |
|---|---:|---|
| `src/infrastructure/qdrant_law_index.py` | 3,288 | Parse `data/law/**/*.md`, build payloads, ingest, search, validate, write the registry |
| `src/presentation/routers/law_registry.py` | 1,113 | 15 endpoints + the `/law-registry` UI |
| `src/infrastructure/law_enrichment.py` | 849 | LLM-assisted payload review, report artifacts |
| `src/infrastructure/law_registry_v2.py` | 570 | Second-generation registry with gate reports |
| `src/infrastructure/run_law_ingest.py` | 29 | Unimportable stray script |
| **Total** | **5,849** | **+ 2 scripts, 15 endpoints, 1 UI, 3 Qdrant collections** |

Corpus: 114 Markdown files, 2,608 articles. Decoupling is **proven**: none of `transcripts.py`, `transcription.py`, `diarization.py` or `projects.py` imports any of it (verified by import analysis), so all 5,849 lines can move without touching the two active frontends.

---

## 2. The core problem: two purposes are conflated

The subsystem serves two unrelated needs, which is why it grew to 17% of the codebase:

**(a) Citation resolution — small, and required by the evidence.**
Transcripts carry `violations_cited` codes (`CL-038`, `INT-003`, …). Resolving a code to a citable provision needs a validated `code → provision` map — roughly the 81 records `docs/VIOLATIONS_CROSSWALK.md` refers to. That is a **data artifact of a few hundred KB**, not a service.

**(b) Corpus search — large, and optional.**
Semantic/lexical search across 2,608 articles is what the 3,288-line module and three Qdrant collections exist for. It is a research tool. Neither active frontend uses it.

Conflating them produced the situation where the *required* half is broken (28 of 35 citation codes resolve to nothing anywhere in this repository or its siblings) while the *optional* half absorbs the engineering effort.

---

## 3. The decisive finding: we do not own `la8159_law`

A sibling project has **already written the ownership contract, in executable form**:

`violation-refiner/violation_pack/shared_corpora.py`
> *"Read-only access to the two shared Qdrant collections **owned by `transcription`**. Both collections are **written only by `transcription/`**. This project may read them and must never write to them. … the declarations here are the executable version of the table in `docs/data_source_of_truth.md` §4 … asserted by `verify_contract()`."*

The declared collections, with owners and dimensions:

| Collection | Owner (per contract) | Dim | Embedder |
|---|---|---|---|
| `transcription_law` | **transcription** | 384 | `all-MiniLM-L6-v2` |
| `reviewed_transcripts` | **transcription** | 384 | `all-MiniLM-L6-v2` |
| `transcription_transcripts` | transcription (deliberately **not** in contract) | 384 | — |

**`la8159_law` is not in the contract, and no project claims ownership of it.** Yet this repository:
- writes to it with `set_payload` (`qdrant_law_index.py:1595/1608`),
- re-derives and upserts its BM25 sparse vectors,
- can `delete_orphans` on it plus `la8159_law_bm25` from the CLI with only a warning,
- treats its 768-dim vectors as an opaque "shared production payload store" (README),
- and the v2 provenance gate fails on it **for every point** — `missing_source_field: 1119/1119` — because the canonical writer never emits `source_path`.

That last failure is not a bug to fix piecemeal; it is the symptom of writing to a collection whose schema, writer and owner are elsewhere. **The gate cannot pass because we are not the writer of record.**

Cross-check: `la8159_law` is read by at least two sibling repos (`seeking/mcp/servers/console_server.py`, `seeking/scripts/search_console_source.py`), and `violation-refiner` reads `transcription_law`/`reviewed_transcripts` — i.e. the ecosystem already treats this repo as the owner of the **384-dim** collections and something else as the owner of `la8159_law`.

---

## 4. Measured blockers

| # | Blocker | Evidence |
|---|---|---|
| B1 | All five registry gates fail | `law_registry.v2.json`: `coverage/identity/provenance/fidelity/overall = fail` |
| B2 | Provenance can never pass | writer omits `source_path`; gate requires it; `missing_source_field: 1119/1119` |
| B3 | The committed artifact is stale | says 107 files / 1,146 ELIs; re-deriving gives **114 / 2,608**; 6 → 17 collisions |
| B4 | The artifact violates its own schema | 8 `jsonschema` violations (`source_path_expected: None is not of type string`) |
| B5 | Two registry implementations | API serves **v1** (`law_registry.json`); `law_registry_v2` has **no API consumer** — an unfinished migration |
| B6 | Language inference is wrong | all 21 `INT/*.md` files classify as `pt` (`language_for_path` checks `len(parts) >= 3`, corpus is flat, `INT` missing from the map) |
| B7 | Corpus duplicates itself | each article exists both standalone and inside its parent law file → 6 collisions now, 17 on re-derive |
| B8 | Citations are unverifiable | 35 distinct codes; only 7 resolve in `seeking/scripts/validation_gates/norms.json`; **28 dangle**; the field has no closed value set |
| B9 | Gate state is never surfaced | no reference to `gate`/`coverage`/`fidelity` in the router or the UI |
| B10 | Writing to an unowned collection | see §3; `delete_orphans` is reachable from the CLI against shared collections |

---

## 5. Options

| Option | Effort | Benefit | Risk |
|---|---|---|---|
| **A. Delete the law subsystem** | Low | −5,849 lines, −15 endpoints | Loses 2,608 curated articles; `violations_cited` becomes permanently unverifiable; 28/35 codes already dangle |
| **B. Leave in place, fix defects** | Medium | Keeps everything | Keeps a 3,288-line god module in the critical path, 15 unauthenticated endpoints, a permanent cross-project write hazard, and the conflation of §2 |
| **C. Extract to an in-repo package behind an interface** | Medium | Removes it from the transcription critical path while keeping it; boundary can later become a repo at near-zero cost | Still same repo/CI |
| **D. Extract to its own repository/service** | High | Cleanest separation; single owner of the shared collections | New repo + packaging + client + cross-repo versioning for a single operator; premature until a second consumer exists |

---

## 6. Recommendation

**Split by purpose, then extract — and align with the contract that already exists rather than inventing one.**

### Phase L1 — Citation registry as data (small, do first)
This is the part the evidence actually needs, and it is independent of every search concern.

1. **Vendor the citation registry** into the repo (the ~81 records) as a data file, with the source declared in `config.py`. `docs/VIOLATIONS_CROSSWALK.md` currently references a registry that is not present, and `scripts/fix_violations_cited.py` points at `discovery/_files_which_will_be_used_in_pipeline/violations`, which does not exist — which is why that script now aborts.
2. **Enforce the code space**: declare `violations_cited` with a closed value set. `FieldSpec` already supports `allowed_values`; the field is presently a free-form `LIST` seeded from a JSON textarea.
3. **Gate it in CI**: fail if any cited code does not resolve.

Acceptance: 35/35 codes resolve; an unknown code fails validation. This is a day's work and it closes the largest integrity gap in the evidence itself.

### Phase L2 — Stop writing to collections we do not own
1. Make `la8159_law` / `la8159_law_bm25` **read-only** from this repo: no `set_payload`, no BM25 upsert, no orphan pruning.
2. Own explicitly what the ecosystem already assigns us: `transcription_law` (384-d, semantic search) and `reviewed_transcripts` (derived from `review/index`).
3. Delete or gate the destructive CLI paths (`--prune-orphans`, `--recreate-local` on a shared target) behind an explicit `--confirm-production`.
4. Add a test asserting the contract in `violation-refiner/docs/data_source_of_truth.md` §4 still holds, so drift fails loudly rather than silently.

Acceptance: `grep` shows zero write calls against `la8159_law*`; the ownership contract is asserted in this repo's suite.

> Note the synergy: `reviewed_transcripts` is defined as exactly the reviewed segments of the 27 `I-002_*` transcripts. Commit `211c241` on this branch made `/review/save` actually persist review edits, so that derived corpus is now trustworthy for the first time.

### Phase L3 — One registry, passing gates
1. **Pick v2 as the source of truth** (it has the gates and the schema) and wire the API + UI to it; delete the v1 path. Or, if the search use case is deferred, delete the v2 artifact and the module and keep v1 with the language fix. **Do not keep both.**
2. Fix `language_for_path` (add `INT` → `en`; raise on unknown locale dirs instead of guessing `pt`; support `multi`).
3. Resolve B7 at the corpus level: designate one authoritative source per ELI (per-article file vs parent-law file) and delete the duplicate form, or record precedence so the collision is intentional rather than reported as a failure.
4. Surface gate state in `/api/law/status` and the UI.
5. Delete the unused `data/law/pdf/**` (32 files, 4.5 MB incl. 7 duplicate `Ley-19496` downloads) — `iter_files` globs `*.md` only, so the pipeline never reads them.

Acceptance: `overall: "pass"` with 0 collisions, 0 missing/extra, provenance matching whatever writer we actually control; the UI shows gate state.

### Phase L4 — Extract behind a boundary (then, only if useful, to a repo)
Move the search half into `src/lawindex/` (or a sibling package) exposing a narrow interface, with its own entrypoints, and delete `run_law_ingest.py`. This is **Option C**, adopting **Option D** only when a second consumer of the search service appears — which, per §3, is exactly how `transcription_law` already acquired one.

Acceptance: nothing under `src/presentation/routers/transcripts*.py`, `transcription.py`, `diarization.py` or `projects.py` imports the package; the transcription suite passes with it removed.

---

## 7. Decisions needed

1. **Is the corpus search (384-d `transcription_law`) still wanted?** If no, Phases L3–L4 collapse to "delete the search half, keep L1". That is the single biggest fork here — and it is the one that determines whether 3,288 lines stay.
2. **Who owns `la8159_law`?** It is unowned in every contract I could find while three projects touch it. Either another repo adopts it explicitly or this repo drops it (L2). Silence is not an option: a `delete_orphans` from this repo's CLI can currently mutate a collection that two other projects read.
3. **v1 or v2 as the registry of record?** (L3.1)
4. **`reviewed_transcripts`:** keep publishing it (the sibling contract depends on it), and confirm the "27 `I-002_*` transcripts" scope now that the corpus is 29 including the two `I-001` Guarulhos files.
