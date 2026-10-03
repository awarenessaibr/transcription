# Reduced-Core Manifest — branch `cleanup/reduced-core`

**Created:** 2026-10-03
**Branch:** `cleanup/reduced-core` (baseline commit `58f42d3`)
**Criterion:** *what do the two active frontends actually require?*
**Reference frontends:** `templates/revision-en.html`, `templates/pinocchio-en.html`

This manifest derives the keep/remove decision from measured consumption, not judgement. Every "KEEP" below traces to a specific `fetch()` in one of the two templates; every "remove" traces to the absence of one. Evidence lines are given throughout.

---

## 1. Method

1. Extracted every API call, asset reference and navigation link from the two templates (line numbers cited).
2. Resolved the alias indirection (`/api/pinocchio/*` → 307 → canonical routes).
3. Mapped each required call to its registered route and router file.
4. Computed the transitive module closure of those routers.
5. Tested the law subsystem for coupling to the target frontends — it is **fully decoupled** (§5).
6. Cross-checked against sibling repositories for external HTTP consumers — **none** (§9).

---

## 2. The two target frontends

| | `pinocchio-en.html` | `revision-en.html` |
|---|---|---|
| Lines | 7,360 | 3,148 |
| Role | Capture → diarize → transcribe → analyse; project/audio management; LLM provider panel; waveform regions; voiceprints | Curation & review: segment grid, inline edit, segment-level re-transcription, per-segment audio, exports |
| Endpoints called | 20 distinct | 11 distinct (9 shared) |
| Assets | `/static/js/llm-providers.js` (:2932), `/audio/{file}` (:3473) | — |
| Esp. features | RunPod health from the browser (:5850), 7 Qdrant collection dropdowns (:3402), config-suggestion via LLM (:5152), AI analysis panel (:5085, :5131) | segment-audio extract/upload/regenerate (:1774, :1828, :1846), `buildPatchesFromDisplay()` → `/review/save` (:2618), ZIP/CSV export |

Both share the transcripts review surface, which is why `revision-en` is largely a subset of `pinocchio-en`.

---

## 3. Required endpoint set — 37 of 93

### 3.1 Endpoints required by the two UIs

| Method | Endpoint | Called from |
|---|---|---|
| GET | `/api/transcripts` | pinocchio-en:6359 |
| GET, PUT | `/api/transcripts/{id}` | revision-en:1926, :2494; pinocchio-en:6686 |
| GET | `/api/transcripts/status/{id}` | async job polling |
| GET | `/api/transcripts/stream/{id}` | async job SSE |
| POST | `/api/transcripts/{id}/audit` | pinocchio-en:6387 |
| POST | `/api/transcripts/{id}/refine` | pinocchio-en:6416 |
| POST | `/api/transcripts/{id}/review/save` | revision-en:2618; pinocchio-en:7051 |
| POST | `/api/transcripts/{id}/review/index` | revision-en:2591; pinocchio-en:7077 |
| POST | `/api/transcripts/{id}/retranscribe_segments` | revision-en:2831; pinocchio-en:7118 |
| GET | `/api/transcripts/{id}/segment_audio/{i}?start=&end=` | revision-en:1774 |
| POST | `/api/transcripts/{id}/segment_audio/{i}` | revision-en:1828 |
| POST | `/api/transcripts/{id}/segment_audio/{i}/regenerate` | revision-en:1846 |
| POST | `/api/transcripts/batch_ingest` | revision-en:3127 |
| GET | `/api/transcripts/csv/list` | revision-en:1977; pinocchio-en:6518 |
| POST | `/api/transcripts/csv/import` | revision-en:2672; pinocchio-en:6654 |
| GET | `/api/transcripts/review/list` | revision-en:1963; pinocchio-en:6502, :6690 |
| GET | `/api/transcripts/audio/list` | pinocchio-en:3359 |
| POST | `/api/diarization/transcribe` | via alias (revision-en:2887) |
| POST | `/api/diarization/transcribe/async` | pinocchio-en:2960 |
| POST | `/api/diarization/transcribe/guided` | pinocchio-en:3024 |
| POST | `/api/diarization/transcribe/guided/async` | pinocchio-en:3023 |
| POST | `/api/diarization/excerpt` | pinocchio-en:3886 |
| GET | `/api/projects` | pinocchio-en:6201 |
| GET | `/api/projects/{id}` | pinocchio-en:6234 |
| GET | `/health` | `start.sh` health loop, monitoring |
| POST | `/v1/llm/chat/completions` | `llm-providers.js:349` → pinocchio-en:5152, :5085, :5131 |
| GET | `/v1/llm/providers` | `llm-providers.js` |
| POST | `/v1/llm/providers/{p}/key` | `llm-providers.js:492` |
| DELETE | `/v1/llm/providers/{p}/key` | `llm-providers.js:522` |
| POST | `/v1/llm/providers/{p}/verify` | `llm-providers.js:541` |
| GET | `/revision-en` | `pinocchio.py:88` |
| GET | `/pinocchio-en` | `pinocchio.py:79` |
| GET | `/pinocchio` | footer link pinocchio-en:5501 |
| GET | `/revision` | es counterpart of the review UI |
| GET | `/` | **required but currently returns health JSON** — see §6.1 |

**Note on `/v1/llm/chat/completions`:** it is a genuine, used feature (LLM-assisted config suggestion and analysis), *and* it carries the critical SSRF/key-exfiltration defect. **Keep the route, remove `base_url` from `ChatRequest`** — do not delete it.

**Note on static mounts:** `/static` (llm-providers.js) and `/audio` (waveform playback) are required. `/transcripts`, `/originals`, `/speakers` are **not** referenced by these two templates.

### 3.2 Removals per router

| Router | Endpoints now | Keep | Remove/defer |
|---|---:|---:|---:|
| `pinocchio.py` | 16 | 5 (HTML routes) | **11** — 8 API aliases + 3 other-UI HTML routes |
| `law_registry.py` | 15 | 0 | **15** (lifts out with the law subsystem) |
| `transcripts.py` | 26 | 18 | **8** |
| `projects.py` | 10 | 2 | **8** |
| `references.py` | 6 | 0 | **6** |
| `speakers.py` | 3 | 0 | **3** |
| `parameters.py` | 2 | 0 | **2** (model list is hardcoded: pinocchio-en:1819) |
| `voiceprint.py` | 2 | 0 | **2** (never mounted) |
| `diarization.py` | 2 | 1 | **1** (`/excerpt_by_path`) |
| `transcription.py` | 4 | 4 | 0 |
| `health.py` | 2 | 2 | 0 |
| `llm/router.py` | 5 | 5 | 0 |
| **total** | **93** | **37** | **56 (−60%)** |

Exact removals from `transcripts.py` (7 paths / 8 endpoint-methods):

```
POST   /api/transcripts/import                 superseded by csv/import + batch_ingest
POST   /api/transcripts/analyze                not called by either UI
POST   /api/transcripts/search                 not called by either UI
POST   /api/transcripts/{id}/index             single-transcript indexing; review/index is used instead
POST   /api/transcripts/index-all              not called
POST   /api/transcripts/{id}/patch             revision-en sends patches through /review/save
GET    /api/transcripts/pinocchio/review/{id}  not called by either UI (verify against curadoria.html)
POST   /api/transcripts/pinocchio/review/{id}
```

---

## 4. Required code closure

The two UIs need **4 API routers** (`transcripts`, `transcription`, `diarization`, `projects`), the `llm` router, `health`, and `pinocchio` for HTML serving — plus the standard plumbing (`main`, `composition`, `config`, `logging_setup`, `path_validator`).

| Layer | Keep | Lines |
|---|---|---:|
| `domain/` | entities (transcript, project, patch, anomaly, reference), ports, chilean_spanish | 641 |
| `application/` | transcribe_audio, guided_transcribe, validate_and_refine, diarize_excerpt, auditor, patcher, dto | 2,348 |
| `infrastructure/` | whisper, pyannote, model_manager, pydub, torchaudio_probe, audio_file, json_store, qdrant_index, project_store, narrative_store, base/claude/deepseek analyzer+reconciler, llm | 5,600 |
| `presentation/` | transcripts, transcription, diarization, projects, pinocchio, health, path_validator | ~2,700 |
| `llm/` | router, providers, credentials | 941 |
| plumbing | main, composition, config, logging_setup | 499 |
| **core target** | | **~9,900** |

Plus **`transcript_fields.py` (448 lines) — revived, not removed.** It is the schema contract that would have prevented the 349 lost timestamps, and it currently has zero importers. Wiring it in is Phase-1 item 1.1.

### Not required by the two UIs (defer / lift)

| Item | Lines | Disposition |
|---|---:|---|
| `qdrant_law_index.py` | 3,288 | **Lift** into the law subsystem |
| `law_registry` router | 1,113 | **Lift** |
| `law_enrichment.py` | 849 | **Lift** |
| `law_registry_v2.py` | 570 | **Lift** (also an unfinished migration — no consumer) |
| `run_law_ingest.py` | 29 | **Delete** (unimportable, unguarded production writes) |
| MCP servers ×3 | 1,778 | **Preserve** — consumed by the Olivia agent workspace on 8121-8123 |
| `voiceprint.py` | 240 | **Delete** (never mounted; its own docstring is false) |
| `runpod_handler.py` + `runpod_client.py` | 469 | **Defer** if serverless is not in active use — the browser calls RunPod directly (pinocchio-en:5850) |
| `references` router + adapter | 529 | **Defer** (only a hint string references it, pinocchio-en:6183) |
| `speakers` router | 82 | **Defer** (own UI) |
| `parameters` router | 55 | **Defer** (model list hardcoded) |
| `analyze_transcript` + `search_transcripts` | 86 | **Defer** |

---

## 5. The law subsystem is fully decoupled from both frontends — proven

Verified by import analysis: **none** of `transcripts.py`, `transcription.py`, `diarization.py`, `projects.py` imports `qdrant_law_index`, `law_enrichment` or `law_registry_v2`. The only references anywhere in `src/` are:

```
src/config.py                          (law env vars only — trivially separable)
src/presentation/routers/law_registry.py
src/infrastructure/law_enrichment.py
src/infrastructure/law_registry_v2.py
src/infrastructure/run_law_ingest.py
```

So the entire law subsystem — **5,849 lines plus 15 endpoints** — can be lifted behind its own interface with **zero impact on the two target frontends**. This is the cleanest seam in the repository and should be the first structural move.

---

## 6. Fix-first: things these two UIs depend on that are broken

These are not cleanup items — they are defects that directly break the target frontends. They should land **before or with** the reduction, each with a regression test.

| # | Defect | Impact on these UIs | Evidence |
|---|---|---|---|
| 6.1 | **`GET /` returns health JSON, not the UI** | Every back-link in both templates (`href="/"`, labelled "Main"/"Evidence Archive") returns JSON. Cause: `health.py:11` registers before `pinocchio.py:44`, and Starlette matches first-registered | revision-en:1092, :1094, :1100; pinocchio-en:1712, :1716, :5494 |
| 6.2 | **`/review/save` silently discards `edited_texts` / `edited_speakers` / `edited_starts` / `edited_ends`** | This *is* revision-en's core review workflow (pinocchio-en:7051, :6607-6639 → revision-en:2618). Reviewers' edits vanish with a success message | `transcripts.py:1150-1166` vs `:1217-1218` |
| 6.3 | **Canonical store destroys `segment_datetime` + segment `speaker_id`** | Any review save in either UI drops these fields. **349 values already lost** | `json_store.py:23-36`; `transcript.py:14-27` |
| 6.4 | **No authentication on any of these 37 endpoints** | Both UIs are fully open, including privileged transcript and audio access | no `Depends`/security scheme in `src/` |
| 6.5 | **Stored XSS in segment text** | `pinocchio-en.html` renders transcript text via `innerHTML` unescaped — in the same file that stores the **RunPod API key in `localStorage`** (pinocchio-en:1771): XSS → key theft | pinocchio-en:3650-3655 |
| 6.6 | **`torch.load` monkeypatched process-wide** | Every transcription path in both UIs loads models through `ModelManager` | `model_manager.py:10, 32-39` |
| 6.7 | **`min_speakers`/`max_speakers` ignored by pyannote** | pinocchio-en exposes these controls; they do nothing | `pyannote_adapter.py:34-36` |
| 6.8 | **Auditor merges `SPEAKER_00`/`SPEAKER_01`** | Affects `/refine` and `/audit` in both UIs | `transcript_auditor.py:231-245`; reproduced |
| 6.9 | **`/refine` can empty a transcript and report success** | pinocchio-en:6416 | `validate_and_refine_transcript.py:408`; reproduced |
| 6.10 | **Segment-audio cache is unbounded and attacker-controlled** | revision-en:1774, :1828, :1846 write permanent files per distinct `start`/`end` | `transcripts.py:1410-1450` |
| 6.11 | **`transcript_id` not validated → path-traversal write** | `/import` and store `save`/`load` | `json_store.py:22`; `TestClient` proof |

---

## 7. Broken things *inside* the two frontends

Found while extracting dependencies — the templates reference things that do not exist:

| Reference | Line | Reality |
|---|---|---|
| `fetch('/v1/qdrant/collections')` | pinocchio-en:3402 | **No such endpoint.** `loadCollections()` populates **7 dropdowns** (ingest, structured, query, chat, workflow, step, enhanced) — an entire dead panel targeting a different backend |
| `POST /api/pinocchio/voiceprint_from_file` | pinocchio-en:4670 | Returns **501** — the real `voiceprint.py` router is never mounted |
| `href="/agente"` | pinocchio-en:5495 | **No such route** |
| `href="/"` ("Main", "Evidence Archive") | revision-en:1092/1094/1100; pinocchio-en:1712/1716/5494 | Returns health JSON (see 6.1) |
| `/api/diarization/transcribe_advanced`, `/api/pinocchio/transcribe_advanced` | pinocchio-en:2963-2973 | Legacy names; the JS rewrites them to `/transcribe`. Dead branch — keep only if old `localStorage` configs must still work |
| `https://api.runpod.ai/v2/…/health` with `Authorization: Bearer <key>` | pinocchio-en:5850 | Direct browser→RunPod; key lives in `localStorage` (pinocchio-en:1771). A credential-handling decision, not a bug per se |

**Decision needed:** the Qdrant collection panel (7 dropdowns + `loadCollections`) is a substantial dead feature. Either delete it, or point `loadCollections` at a real endpoint (`/api/law/status` or a new `/api/qdrant/collections`).

---

## 8. The alias collapse

Both templates call `/api/pinocchio/*`; those 8 routes are pure 307 shims (`pinocchio.py:98-154`):

```
POST /api/pinocchio/transcribe              → /api/diarization/transcribe
POST /api/pinocchio/transcribe/async        → /api/diarization/transcribe/async
POST /api/pinocchio/transcribe/guided       → /api/diarization/transcribe/guided
POST /api/pinocchio/transcribe/guided/async → /api/diarization/transcribe/guided/async
POST /api/pinocchio/transcribe/pyannote     → /api/diarization/transcribe
GET  /api/pinocchio/transcripts             → /api/transcripts
GET  /api/pinocchio/transcripts/{id}        → /api/transcripts/{id}
POST /api/pinocchio/voiceprint_from_file    → 501 stub
```

**Plan:** repoint the templates to the canonical routes → verify both UIs → delete the 8 aliases. `pinocchio.py` then keeps only its 5 HTML routes (it becomes a small template server).

---

## 9. No external HTTP consumers (checked)

Verified that no sibling project's **code** calls this API: the only references to port 8049 in `mcp-ecosystem/` outside this repo are inside archived LLM conversation logs under `seeking/searches/**`, not source.

**The MCP servers are a different matter and must be preserved:** a documented workspace integration ("Olivia") consumes `mcp-transcription` / `mcp-diarization` / `mcp-translate` on ports 8121-8123. MCP is a separate, live consumption surface — trimming it must be checked against that workspace's actual tool list, not inferred from the HTTP surface.

---

## 10. Reduction ledger

| Metric | Now | Target | Δ |
|---|---:|---:|---:|
| HTTP endpoints | 93 | **37** | −60% |
| `src/` lines | 18,995 | **~9,900** core (+448 revived schema) | **−48%** |
| API router modules | 11 | **6** | −45% |
| Modules >1,000 lines | 3 (`qdrant_law_index` 3288, `transcripts` 1545, `law_registry` 1113) | **0 in core** (law lifts out; `transcripts.py` splits) | −100% |
| Templates | 29,284 | **~10,500** (one per view + i18n) | −64% |
| `scripts/` | 8,516 | ~3,500 | −59% |
| Capability lost for these 2 UIs | — | **none** | — |

Preserved elsewhere, not deleted: law subsystem 5,849 lines; MCP servers 1,778 lines.

---

## 11. Execution order (commit sequence on this branch)

Each step leaves the suite green and is independently revertable.

| # | Commit | Content | Gate |
|---|---|---|---|
| 0 | `fix: make / serve the UI` | Resolve the `/` route collision; fix or repoint the broken back-links (§6.1, §7) | Both UIs' nav works |
| 1 | `test: real-transcript round-trip + schema activation` | Wire `transcript_fields.validate_transcript` into store save/load; add round-trip tests over real `data/transcripts/*.json` | Suite green; round-trip byte-stable |
| 2 | `fix: stop losing segment_datetime / speaker_id` | Add fields to `Segment`, `load()`, `save()` | 349 values restorable; no loss on re-save |
| 3 | `fix: persist review edits` | Apply `edited_*` maps + `recording_datetime` in `/review/save` | Edit survives reload (test) |
| 4 | `security: auth + drop base_url + validate transcript_id + escape segment text` | §6.4–6.6, §6.11 | 401 without token; no foreign-host Authorization; traversal rejected |
| 5 | `refactor: repoint templates to canonical routes, delete 8 aliases` | §8 | Both UIs work; `pinocchio.py` shrinks to HTML routes |
| 6 | `refactor: lift the law subsystem behind its own package` | §5 — 5,849 lines + 15 endpoints | Two UIs unaffected; law tests still green |
| 7 | `chore: remove dead endpoints and code` | §3.2 removals, `voiceprint.py`, `run_law_ingest.py`, dead Qdrant panel | 93 → 37 endpoints; suite green |
| 8 | `refactor: split transcripts.py and transcription.py` | Extract `_jobs.py` / `_matching.py`; factor the duplicated transcribe form block | No file >600 lines |
| 9 | `refactor: collapse es/en template duplication` | i18n dictionary + one escaper | ~14,000 lines removed; both languages render |
| 10 | `chore: scripts + docs consolidation` | Move one-offs, dedupe docs, delete stale reports | `git status` clean after dry runs |

**Hard constraint:** before commit 7, confirm `data/transcripts/bak/` is preserved and the 349 timestamps in §“recover” are restored. The `bak/` files are currently the only copy.

---

## 12. Decisions — resolved 2026-10-03

| # | Decision | Outcome | Status |
|---|---|---|---|
| 1 | Qdrant collections panel (`pinocchio-en:3402`, 7 dropdowns) | **Delete.** It was fully orphaned: it called `/v1/qdrant/collections` (no such route), populated eight elements absent from the document, and was never invoked | ✅ `d1a7d0d` (−82) |
| 2 | RunPod: serverless path still used? | **Keep the frontend calls; delete server-side redundancy.** Deleted `runpod_client.py` (our server calling RunPod, duplicating the browser) + the script's `--serverless` path. **Kept `runpod_handler.py`**: the browser calls `api.runpod.ai/v2/<id>` (`pinocchio-en:5771`, `:5845`) and `runpod_handler.py` is the handler *inside* that endpoint — deleting it would break the feature we were told to preserve | ✅ `8d546a9` (−275 net) |
| 3 | `curadoria.html` | **Delete.** It called no endpoint the two surviving UIs do not also call, so nothing was orphaned | ✅ `2e5cf4a` (−2,895) |
| 4 | MCP scope | **Leave as-is** — not yet defined what the Olivia workspace needs. No MCP changes on this branch | ⏸ deferred |
| 5 | Law subsystem destination | **Split by purpose, then extract** (Phase L1–L4). Decisive input: `violation-refiner/violation_pack/shared_corpora.py` already declares `transcription_law` and `reviewed_transcripts` as owned by `transcription` — and **no project claims `la8159_law`**, which this repo nonetheless writes to. Full proposal: [LAW_SUBSYSTEM_STRATEGY.md](LAW_SUBSYSTEM_STRATEGY.md) | 📋 proposal |
| 6 | Spanish twins | **Retire them; keep the `-en` pair.** The `-en` files are now canonical; `/pinocchio`, `/revision` etc. remain as aliases so old links work | ✅ `2e5cf4a` (−10,059) |

**Net effect of decisions 1, 2, 3 and 6 — measured from git, not estimated:**

| Item | Lines |
|---|---:|
| Templates deleted (`pinocchio.html` 6,958 · `revision.html` 3,101 · `curadoria.html` 2,895) | **12,954** |
| Dead UI code deleted (Qdrant panel) | 82 |
| Python net (`runpod_client.py` 193 + `batch_transcribe.py` 84, less 2 inserted) | 275 |
| Router + test churn added back (73 inserted, 62 rewritten) | −11 |
| **Total across the three commits** | **−13,300 net** (13,375 deleted, 75 inserted) |

…with **no capability lost** for the two active frontends.

### Still open from decision 5

1. **Is corpus search (384-d `transcription_law`) still wanted?** If not, Phases L3–L4 collapse to "delete the search half, keep L1" — the fork that determines whether 3,288 lines stay.
2. **Who owns `la8159_law`?** Unowned in every contract found, while three projects touch it, and this repo's CLI can `delete_orphans` on it.
