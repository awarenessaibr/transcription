# Transcript Header Review — I-002 Corpus

**Target:** `transcription/data/transcripts/*.json` — 27 canonical transcripts
**Scope:** every top-level key **except** `segments[]` (the "header"), plus the nested blocks it contains (`metadata`, `participants[]`, `forensic_clusters{}`, `key_evidentiary_findings[]`, `corrections_applied[]`)
**Method:** direct programmatic measurement of all 27 files (JSON parse + field/type/emptiness censuses + cross-file set comparisons). The corpus was not modified for this report; the repairs described in the banner were applied afterwards by the scripts under `scripts/`.
**Date:** 2026-09-13 (repaired 2026-09-13)
**Classification:** Attorney Work Product — Privileged and Confidential

> **Status of repairs.** This report describes the corpus as first measured.
> **Every defect class below has since been addressed** (2026-09-13), except the ones
> explicitly marked *still open*. Fixed:
>
> | Area | Was | Now | Where |
> |---|---|---|---|
> | Pro provenance + `metadata` | 7/27, `2.3.1` | 27/27, `2.5` | `docs/AUDIO_SOURCE_MAPPING.md` |
> | Temporal agreement | 3 axes disagreed | 27/27 `-04:00` from media | same |
> | `violations_cited` | 91 strings, 29 codes | 35 registry IDs, 0 non-conforming | `docs/VIOLATIONS_CROSSWALK.md` |
> | Findings/clusters/corrections | 6/3/3 shapes, 7 `strength` values | 1 shape each, `High`/`Medium`/`Low` | `docs/SCHEMA_NORMALIZATION.md` |
> | `tags`, `location`, `audio_id` | mixed case, 16 variants | kebab-case, 14 variants | `docs/VOCABULARY_NORMALIZATION.md` |
> | `speaker_id` | 48 values, 8 null | 43 values, 0 null | `docs/SPEAKER_ID_CONSOLIDATION.md` |
> | `title` | 4 conventions, `FINAL v2`×20 | imported from the overview doc | `scripts/import_overview_titles.py` |
> | `reviewed`, chain, lineage | 18 absent, 3 breaks, self-refs | explicit, 0 breaks, `null` | `scripts/fix_header_lineage.py` |
> | `speaker_index.json`, `speaker_patch.json`, `data/speakers/*.md` | keyed by 46 raw ids | rebuilt on 43 canonical ids | `docs/SPEAKER_ID_CONSOLIDATION.md` |
>
> **Still open:** violations anchoring (H1), finding `segments` coverage (H4),
> the `tags` 97-value spread (H10), 9 participants missing `segment_labels`,
> `classification` having no per-file meaning (H16), and 915 `speaker_patch.json`
> suggestions awaiting human review.
> Corrected sections are marked inline.

---

## 1. Executive summary

The header block is **structurally stable but semantically loose**.

* **Structure is excellent.** All 27 files carry the same header keys in a consistent shape — 24 inspected here, plus out-of-scope `segments`. The provenance backfill added `source_path`, and 9 files also carried `reviewed`, so at first measurement the files held 26 or 27 top-level keys; the lineage repair then added `original_transcript_id` and `reviewed` everywhere, and the corpus is now a **single uniform 27-key shape across all 27 files**. `chronological_order` is 1–27 with no duplicates, `case_id` is uniformly `I-002`, `classification` is byte-identical in all 27, and `recording_datetime` is strictly monotonic with the chronological spine. As a machine-readable envelope, the header works.
* **Completeness is poor and bimodal.** Content-bearing fields are populated in roughly a third of the corpus: `violations_cited[]` is non-empty in **14/27**, `forensic_clusters{}` in **11/27**, `corrections_applied[]` in **6/27**. There is no partial-credit middle: files are either rich or empty. *(`metadata` was the extreme case — non-empty in only 13/27 — and is now complete in 27/27; `reviewed` now exists on 27/27 with 18 explicitly `false`.)* Annotation **density** was deliberately not changed: the empty fields are a transcription-coverage fact, not a schema defect.
* **Consistency is the real defect — and it is now normalized.** The same information was encoded in different shapes, duplicated across fields, or expressed in inconsistent vocabularies:
  * `violations_cited[]` mixed **three incompatible kinds of value** (registry codes, statutory article references, prose assertions) — 101 citations, 91 distinct strings, only 29 distinct real codes. **Now: 35 distinct registry IDs, 0 non-conforming.**
  * `forensic_clusters{}.<key>` had **three different value schemas**, and one file mixed two of them internally. **Now: one 5-key schema.**
  * `corrections_applied[]` had **three different record shapes** (4-key object, 2-key object, bare string). **Now: one 5-key schema.**
  * `key_evidentiary_findings[]` had **six different record shapes**, and `strength` was drawn from **7 values**, two of which were literal star strings. **Now: one schema, `High`/`Medium`/`Low`.**
  * `speaker_id` had **48 values, one per transcript-role pair, plus 8 nulls**. **Now: 43 canonical values, 0 nulls.**
  * `timestamp`, `recording_datetime`, and `metadata.timestamps.QuickTime_Movie_Header_Created` all described the same moment but disagreed — the stored header was **+3 h** wrong in all 9 files that had it, and `recording_datetime` had drifted in 15 of 27. **Now fixed** (§4.2) by deriving all three from the media file itself.
* **Provenance was thin** *(now fixed — §4.1, §4.12)*. `source_file` was populated in **7/27**, `provider` in **4/27** (with `local` and `unknown` used as the same field's vocabulary). One `source_file` pointed at a *transcript* JSON rather than audio.
* **Ordering had 3 concrete breaks** isolating the two near-empty fragment files (`05B`, `07`) from the prior/next chain. **Now: 0 breaks.**

The header is usable today as an index, and after the 2026-09-13 normalization pass it is
usable as a reliable evidentiary index for everything except **segment anchoring** (H1, H4),
which needs new content rather than new rules. The dominant fixes were therefore
**normalization** (violations, tags, strength, cluster/finding/correction schemas, speaker_ids)
and **backfill** (metadata, provenance, `reviewed`, titles), not restructuring.

---

## 2. Corpus at a glance

| Metric | Value |
|---|---|
| Transcript files | **27** |
| Total segments (`segments[]` length) | **3,207** |
| Total participant records | **87** (1–10 per file) |
| Distinct `speaker_id` values | **48** |
| Total `violations_cited` entries | **101** (91 distinct strings) |
| Total `tags[]` entries | **202** (97 distinct) |
| Total forensic clusters | **62** (2–10 per file) |
| Total `key_evidentiary_findings` | **153** |
| Total `corrections_applied` records | **47** |
| `case_id` values | `I-002` ×27 |
| `classification` values | 1 distinct string ×27 |
| `language` values | `es` ×24, `pt` ×2, `en` ×1 |
| `chronological_order` | 1–27, all unique |
| Time span | `2024-07-05T12:57:11-04:00` → `2024-07-06T10:13:54-04:00` (crosses midnight; corrected post-fix) |

---

## 3. Header field inventory

All 27 files contain exactly these **24 header keys** (100% presence):

`transcript_id`, `source_file`, `language`, `timestamp`, `provider`, `original_transcript_id`, `metadata`, `title`, `subtitle`, `recording_datetime`, `location`, `audio_id`, `case_id`, `narrative_id`, `chronological_order`, `prior_stage`, `next_stage`, `classification`, `participants`, `violations_cited`, `tags`, `forensic_clusters`, `key_evidentiary_findings`, `corrections_applied`

One **25th** key is conditional: `reviewed` — present on **9/27** only.

A **26th** key, `source_path`, was added to all 27 by the provenance backfill
(§4.1), making the current file shape **26 keys**, or **27** where `reviewed` is
also present. (`segments`, the 25th pre-existing key, is out of scope for this
review and is not counted above.)

| Field | Type | Present | Non-empty | Notes |
|---|---|---|---|---|
| `transcript_id` | str | 27/27 | 27/27 | = filename stem; unique |
| `source_file` | str | 27/27 | **7/27** | heterogeneous value kinds |
| `language` | str | 27/27 | 27/27 | not a closed enum (see §4.1) |
| `timestamp` | str | 27/27 | **26/27** | 5 carry `Z`, 21 naive, 1 empty |
| `provider` | str | 27/27 | **4/27** | `local`, `unknown` |
| `original_transcript_id` | str | 27/27 | **22/27** | 22 are self-references |
| `metadata` | obj | 27/27 | **13/27** | 14 are `{}` |
| `title` | str | 27/27 | 27/27 | unique; 20 embed `FINAL v2` |
| `subtitle` | str | 27/27 | **26/27** | mixed register |
| `recording_datetime` | str | 27/27 | 27/27 | strictly monotonic with order |
| `location` | str | 27/27 | 27/27 | 16 distinct variants |
| `audio_id` | str | 27/27 | 27/27 | unique; 5 off-pattern |
| `case_id` | str | 27/27 | 27/27 | constant |
| `narrative_id` | str | 27/27 | 27/27 | = filename-derived; unique |
| `chronological_order` | int | 27/27 | 27/27 | 1–27, unique |
| `prior_stage` | str | 27/27 | **26/27** | blank only at order 1 (correct) |
| `next_stage` | str | 27/27 | **26/27** | blank only at order 27 (correct) |
| `classification` | str | 27/27 | 27/27 | constant ×27 |
| `participants` | arr | 27/27 | 27/27 | 5-key schema, stable |
| `violations_cited` | arr | 27/27 | **14/27** | 3 value kinds |
| `tags` | arr | 27/27 | 27/27 | no controlled vocabulary |
| `forensic_clusters` | obj | 27/27 | **11/27** | 3 value schemas |
| `key_evidentiary_findings` | arr | 27/27 | **23/27** | 6 record shapes |
| `corrections_applied` | arr | 27/27 | **6/27** | 3 record shapes |
| `reviewed` | bool | **9/27** | 9/27 | always `true`; never `false` |

---

## 4. Field-level findings

### 4.1 Identity & provenance

> **FIXED 2026-09-13.** `source_file`, `source_path`, `provider` are now populated 27/27; `original_transcript_id` is `null` 27/27. See `docs/AUDIO_SOURCE_MAPPING.md`.

> **Status: provenance part FIXED 2026-09-13** (`source_file`, `source_path`,
> `provider`). Identity fields (`transcript_id`, `narrative_id`, `audio_id`,
> `original_transcript_id`, `classification`, `language`) are **unchanged** and
> the observations below still apply to them.

**`transcript_id` / `narrative_id`** — 27/27, both unique, both derived mechanically from the filename. `narrative_id` has no independent authority. The `NAR-NN` prefix is **not unique** on its own (`NAR-06` ×2, `NAR-18` ×2, `NAR-19` ×3); uniqueness comes only from the `NAR-NN_STG-N` composite. One `narrative_id` is off-pattern: `NAR-STG_8_pdi_identity_control` (no numeric NAR component) — consistent with its off-pattern filename `I-002_06_NAR-STG_8_pdi_identity_control.json`.

**`original_transcript_id`** — the field name implies a link to a prior version, but in **22/27** files it is a verbatim **self-reference** (`original_transcript_id == transcript_id`). It is empty in 5 (`05B`, `10A`, `10B`, `11`, `13`). No provenance value is carried anywhere in the corpus.

**`source_file`** — was populated in 7/27, and the 7 values were **not the same kind of thing**:

| File | `source_file` value | Kind |
|---|---|---|
| `01` | `transcription/data/audio/Aeropuerto Arturo Merino Benítez.m4a` | repo-relative path to original audio |
| `05B` | `Aeropuerto Arturo Merino Benítez 11_1788416958.m4a.wav` | processed/unix-timestamped WAV |
| `10A` | `Aeropuerto Arturo Merino Benítez 19_1788417813.m4a.wav` | processed WAV |
| `10B` | `Aeropuerto Arturo Merino Benítez 18_1788417663.m4a.wav` | processed WAV |
| `10` | `Terminal_Internacional_T2.m4a` | bare original filename |
| `12` | `Aeropuerto Arturo Merino Benítez 22.m4a` | bare original filename |
| `14` | `aeropuerto_STG_23.json` | **wrong layer** — a transcript JSON, not audio |

**`provider`** — was populated in 4/27: `local` ×1 (`01`), `unknown` ×3 (`10`, `12`, `14`). Using `unknown` as a value is equivalent to leaving it blank but makes the field look populated; the 23 genuinely blank files and the 3 `unknown` files were semantically identical.

**Repaired.** Every transcript's recording was identified against `data/audio/`
by exact duration **and** byte-size match (27/27, zero conflicts, and 27 distinct
`voice-memo-uuid`s). As a result:

| Field | Now |
|---|---|
| `source_file` | the real on-disk filename, e.g. `Aeropuerto Arturo Merino Benítez 6.m4a` — was empty in 20, wrong in 4 |
| `source_path` | **new key**: `transcription/data/audio/<file>` |
| `provider` | `local`, on all 27 (the three `unknown` values were overwritten) |
| `audio_id` | **left as-is** — still uses slugs, so the slug-vs-filename conflict below persists |

**`audio_id`** — 27/27, all unique, but 5 are off-pattern against the dominant `*_STG_N` convention:
* `24` → `aeropuerto_stg_12` (**lowercase** `stg`, unique casing deviation)
* `10` → `Terminal_Internacional_T2` (no STG component)
* `21`/`22`/`23` → `carabineros_ppdartnel_1|2|3` (**`artnel`**, while location and subtitle say **Dartnell**)

**Cross-field naming conflict** *(still open)*. `audio_id` uses **slug** names (`aeropuerto_STG_15`) while `metadata.file_info.file_name` uses **human** names (`Aeropuerto Arturo Merino Benítez 15.m4a`), and `source_file` used a third form. Example — file `08`:

```
audio_id                 = aeropuerto_STG_15
metadata.file_info.file_name = Aeropuerto Arturo Merino Benítez 15.m4a
```

**`classification`** — one identical string in all 27: `Attorney Work Product — Privileged and Confidential`. It carries no per-file information (it does not distinguish reviewed from unreviewed, nor draft from final), yet it is asserted 27 times.

**`language`** — 27/27 present, but:
* **24 `es`, 2 `pt`, 1 `en`**. The `en` outlier is `I-002_10B_NAR-18_STG_18_counter_fragment.json`, which is a 3-segment fragment.
* The header carries **one language per file**, while several files are demonstrably bilingual (e.g. `17` contains a `SPEAKER_01` "Passenger / LATAM Staff (contextual)"; `24` contains a `SPEAKER_00 (English speaker)`). A single `language` string cannot represent these.
* `pt` files (`01`, `05B`) are flagged `Portuguese` in `tags[]` (English name) — the two fields use different vocabularies for the same concept.

### 4.2 Temporal fields

> **FIXED 2026-09-13.** All 27 `recording_datetime` and `timestamp` values are the media file's own `creation_time` in Chile local time (`-04:00`) and agree with each other. See §4.1 and `docs/AUDIO_SOURCE_MAPPING.md`.

> **Status: FIXED 2026-09-13** by `scripts/backfill_audio_metadata.py`. All three
> fields now derive from the recording's own QuickTime tag, converted to Chile
> time (`-04:00`). See `docs/AUDIO_SOURCE_MAPPING.md` §5. The findings below are
> the pre-fix state, retained as evidence of what was wrong.

Three fields carried time, and they disagreed.

**`recording_datetime` — the strongest field in the header, but only relatively.**
27/27 populated, ISO-8601, and **strictly monotonic with `chronological_order`**
across the whole corpus, including the midnight rollover. It was the de facto
authoritative timestamp. However, comparison against the files' genuine
QuickTime `creation_time` showed it was **accurate to under a minute in only 12
of 27** transcripts: 15 had drifted, three of them by more than an hour
(`STG_26/27/28/29` by ~+2 h, `10B` by −1 h, `22`/`23` by +21 min). Headers can
agree with each other and still all be wrong; only the media was ground truth.

**`timestamp` — a near-duplicate that was sometimes missing and sometimes drifted.**
* Empty in `13` (`I-002_13…`).
* Identical to `recording_datetime` in 24/27.
* Differs only in the **seconds** where it differed — and those were the files
  that were *more* correct:
  * `02`: `13:08:31` vs `13:08:00`
  * `03`: `13:33:02` vs `13:33:00`
* **Timezone style was inconsistent across the corpus**: 5 files ended in `Z`
  (`20`–`24`), 21 were timezone-naive, 1 was empty. Two files with the same
  wall-clock semantics could therefore sort differently as strings. The `Z` on
  those five was a mislabel, not a statement of fact: the digits were local
  time. `20.m4a` proves it — its `Z` value sits exactly 4 h 00 m 18 s from its
  own QuickTime tag.

**`metadata.timestamps.QuickTime_Movie_Header_Created` — the stored value was
itself wrong, by exactly +3 h, in all 9 files that had it.**

| File | Stored QuickTime header | True header (from the file) | Stored − true | `recording_datetime` (before) | vs true tag |
|---|---|---|---|---|---|
| `01` | `2024-07-05T19:57:11.000Z` | `2024-07-05T16:57:11Z` | +3:00:00 | `2024-07-05T12:56:00` | −4:01:11 |
| `02` | `2024-07-05T20:08:31.000Z` | `2024-07-05T17:08:31Z` | +3:00:00 | `2024-07-05T13:08:00` | −4:00:31 |
| `03` | `2024-07-05T20:30:02.000Z` | `2024-07-05T17:30:02Z` | +3:00:00 | `2024-07-05T13:33:00` | −3:57:02 |
| `04` | `2024-07-05T21:48:13.000Z` | `2024-07-05T18:47:13Z` | +3:00:00 | `2024-07-05T14:48:00` | −3:59:13 |
| `05` | `2024-07-05T22:17:51.000Z` | `2024-07-05T19:17:51Z` | +3:00:00 | `2024-07-05T15:17:00` | −4:00:51 |
| `08` | `2024-07-05T23:26:32.000Z` | `2024-07-05T20:26:32Z` | +3:00:00 | `2024-07-05T16:26:00` | −4:00:32 |

So the apparent "~7 h" gap was **two independent errors stacked**: a bad +3 h
conversion baked into the stored tag, plus a genuine ~4 h UTC-vs-Chile-local
difference in `recording_datetime`. The correct offset for July 2024 is **UTC−4**
(Chile Standard Time; DST runs September→April), so the ~4 h gap is the expected
one and `recording_datetime`'s *digits* were right — it was the missing offset
and the occasional drift that were wrong.

**Resolution.** Rather than pick a winner between two untrustworthy header
values, every transcript now takes its time from the file itself:
`recording_datetime` and `timestamp` are both set to the QuickTime
`creation_time` converted to Chile local time and written as
`YYYY-MM-DDTHH:MM:SS-04:00`. They are now identical in all 27. The wrong stored
`QuickTime_Movie_Header_Created` was **preserved byte-for-byte** (it is evidence
of the faulty conversion) and the true value recorded alongside it in the new
key `QuickTime_Movie_Header_Created_verified`.

**Also in the `metadata.timestamps` block:** 3 files (`10`, `12`, `14`) carry a
QuickTime key with an **empty-string value** (`""`) rather than omitting it —
present-but-null, indistinguishable from absent at a glance. All pre-existing
`timestamps` keys were preserved verbatim; the backfill only adds
`QuickTime_Movie_Header_Created_verified`. `File_Modified_Date` appears in 2
files with a **2025** date (`2025-07-06T15:53:46.000Z`), i.e. processing time,
not recording time — left as-is, but it should not be read as provenance.

### 4.3 Location

> **FIXED 2026-09-13.** `location` is now 14 canonical values on a facility + ` — <place>` pattern; `Artnel` no longer appears in any file. See `docs/VOCABULARY_NORMALIZATION.md`.

27/27 present, but **16 distinct strings** for a corpus that has only ~4 real places. The variation is granularity and punctuation, not substance:

| Occurrences | Value |
|---|---|
| 6 | `Arturo Merino Benítez International Airport, Santiago, Chile` |
| 4 | `Arturo Merino Benítez International Airport (SCL)` |
| 3 | `Carabineros Dartnell sub‑station, Arturo Merino Benítez International Airport, Santiago, Chile` |
| 2 | `Arturo Merino Benítez International Airport (SCL), Santiago, Chile — DGAC Office` |
| 1 each | 12 further variants adding suffixes (`— Boarding Gate Area`, `— Aboard Aircraft / Jetbridge`, `— PDI processing area`, `— LATAM Counter`, `— Terminal 2 (T2), LATAM Check-In Counter, airside`, …) |

Defects:
* The base airport is written **3 ways** (`… , Santiago, Chile` / `… (SCL)` / `… (SCL), Santiago, Chile`), so 27 files cannot be grouped by location with a string equality.
* The Carabineros row uses a **non-breaking hyphen** `sub‑station` (U+2011), which will not match a normal `-` in filters or searches.
* Venue precision is applied inconsistently — some stage files get a venue suffix, others at the same venue do not.

### 4.4 Ordering (`chronological_order`, `prior_stage`, `next_stage`)

> **FIXED 2026-09-13.** The 3 broken links were repaired and `05B`/`07` are reconnected; a re-check reports 0 chain issues.

`chronological_order` is exemplary: **1–27, all unique, no gaps**. `prior_stage` is blank only at order 1 and `next_stage` only at order 27 — the intended boundary convention is respected.

However, the prior/next links **do not form an unbroken chain**. Three links disagree with the chronological spine:

| Defect | File | Field | Value | Should be |
|---|---|---|---|---|
| D1 | `05` (`I-002_05_NAR-07…`, order 5) | `next_stage` | `I-002_06_NAR-STG_8…` | `I-002_05B_NAR-11_STG_11_waiting_area` |
| D2 | `06` (`I-002_06_NAR-STG_8…`, order 7) | `prior_stage` | `I-002_05_NAR-07…` | `I-002_05B_NAR-11_STG_11_waiting_area` |
| D3 | `08` (`I-002_08_NAR-09…`, order 9) | `prior_stage` | `I-002_06_NAR-STG_8…` | `I-002_07_NAR-06_STG_13_post_PDI_corridor` |

Effect: **two files are orphaned from the chain** — `05B` (`NAR-11_STG_11_waiting_area`, order 6) and `07` (`NAR-06_STG_13_post_PDI_corridor`, order 8). Both are inserted at a chronological position but neither is referenced by its predecessor nor points back to it. Notably, **both are also empty for `forensic_clusters` and `key_evidentiary_findings`** — the orphans are the same files that carry no analytic content. A traversal of the prior/next chain will silently skip them.

### 4.5 Descriptive fields (`title`, `subtitle`)

> **FIXED 2026-09-13.** `title` and `subtitle` were replaced from `transcription/docs/LA8159-Overview.html`. See `scripts/import_overview_titles.py`.

**`title`** — 27/27, unique, but four different conventions are in use:

| Convention | Files | Example |
|---|---|---|
| `<Venue> <N> — FINAL v2` | 20 | `Aeropuerto Arturo Merino Benítez 6 — FINAL v2` |
| Descriptive, no version marker | 5 (`05B`, `06`, `10A`, `10B`, `12`) | `Aeropuerto Arturo Merino Benítez 11 — Waiting Area / Information Request` |
| Different prefix entirely | 1 (`01`) | `01 - Aeropuerto Arturo Merino Benítez` (leading number, hyphen not em-dash) |
| Different naming | 2 (`10`, `24`) | `Terminal Internacional T2 — FINAL v2`; `STG-12 — Day 2 Counter Interaction (…)` |

Two further problems:
* **`FINAL v2`** appears in 20 titles but there is **no `version` field** in the header — the version is embedded in prose and cannot be queried.
* The Carabineros titles (`21`–`23`) say **`Carabineros PPD Artnel N`** while their own `subtitle` and `location` say **Dartnell** — an internal spelling contradiction inside a single file.

**`subtitle`** — 26/27 (empty in `08`), and the field has **no consistent register**: it ranges from a 2-word label (`Boarding Gate`) to a full evidentiary assertion containing quoted speech and a specific clock time (`Document Delivery — Supervisora Antonela delivers the falsified 'carta de desembarque' at 22:59`). As a result `subtitle` sometimes duplicates what belongs in a finding, and its length varies by ~10×.

### 4.6 `participants[]`

> **RESOLVED 2026-09-13 (Task E).** `speaker_id` is now **43 canonical values over 85 records,
> with 0 nulls**, and `canonical_name` no longer embeds the transcript identity. The two
> non-person rows were removed. Script: `scripts/fix_speaker_ids.py`; audit trail:
> `docs/SPEAKER_ID_CONSOLIDATION.md`. The pre-fix analysis is retained below for the record.

**Schema is nearly stable**: of 85 participant records, **76 carry all 5 keys**
(`canonical_name`, `role`, `segment_labels`, `speaker_id`, `speaker_label`) and **9 carry 4** —
the 8 minted ids plus the surviving `SPK-pdi-female` row in `06` lack `segment_labels`.
An earlier revision of this report claimed 5 keys on every record; that was never true of the
8 records that had no `speaker_id` at all. `add_participant_segment_labels.py` can close the gap.

**Volume:** 85 records, 1–10 per file. **6 files have exactly one participant**, and in every case that participant is the passenger alone: `05B`, `10B`, `13`, `15`, `16`, `19`. Those files also have 1–2 findings and no clusters — they are the thin fragments.

**`speaker_id` was null/absent in 8 records** (spread over 3 files) — **now minted**
(`SPK-unknown-stg-<N>-speaker-<NN>`, a form that cannot be re-suffixed):

| File | Participants with no `speaker_id` |
|---|---|
| `06` | `SPEAKER_02`, `SPEAKER_03`, `SPEAKER_04`, `SPEAKER_05` |
| `17` | `SPEAKER_00`, `SPEAKER_01`, `SPEAKER_02` |
| `24` | `SPEAKER_00` |

A null `speaker_id` broke any join keyed on speaker, and there was no compensating identifier.

**Identifier fragmentation — FIXED.** The pre-fix space was 46 raw `speaker_id` values for a much
smaller cast. Two mechanisms caused it, and **both are now removed**:

1. *Stage/narrative scoping baked into the ID.* The same role recurring across stages got a new ID, e.g. a PDI officer as `SPK-pdi-female-nar-stg-8-pdi-identity-control` (which was then **reused in `CARABINEROS_1` and `CARABINEROS_2`** — a stage-scoped ID leaking across unrelated stages), and the DGAC official "Don Nicolás" appearing as three different identifiers across files.
2. *Stage/narrative scoping baked into the display name.* `canonical_name` values such as `Latam Pilot Ruiz (NAR-01_STG_1_pre_boarding)`, `PDI (NAR-07_STG_7_post_removal_investigation)` and `DGAC - Don Nicolas (NAR-14_…)` embedded the transcript identity into the person's name, so the "canonical" name was not canonical. The `(NAR-…)` suffix is now stripped from **40** names, and where a canonical id still carried several names, the majority name won so that one id maps to exactly one name (4 such corrections, including `Piloto (RUIZ)` / `Ruiz` → `Latam Pilot Ruiz`).

The consolidation is **35 canonical + 8 minted = 43 values**, and it records *why* each
collision was merged: **identity** merges join a named person (`SPK-pilot-ruiz` 3→1,
`SPK-dgac-don-nicolas` 3→1, `SPK-dgac-edgardo-ortiz` 2→1, `SPK-female-carabinero-2` 3→1),
while **role** merges join a generic label that had been suffixed per stage (`SPK-dgac` 2→1,
`SPK-pdi` 3→1, `SPK-computer-officer` 2→1).

Legitimate reuse does occur — `SPK-passenger-leandro` appears in **27/27**, `SPK-joaquin-barraza-latam-security` in 4, `SPK-stewardess-accuser` in 2, `SPK-antonela-latam-agent` in 2 — which proves person-level IDs exist and work; the fragmented ones were avoidable.

**Two non-person rows were removed from `06`:** `SPK-review-important-nar-stg-8-…`
(`canonical_name: "Review-Important"`, `role: "Unknown speaker"` — a mis-parsed diarization
label) and a duplicate `SPK-pdi-female` row (`"PDI - Female"` / `Possible PDI Officer`; the
`"PDI Female"` / `PDI Female Officer` row was kept). `speaker_index.json` had already recorded
only one appearance, so index and transcript disagreed before the fix.

**Unresolved identity** is still encoded inconsistently at the *name* level: `canonical_name: "Unknown"`
in 6 records, and in `17`/`24` the raw ASR label (`SPEAKER_00`, `SPEAKER_00 (English speaker)`).
Consolidation gave these ids a stable join key but deliberately did not invent a display name —
`SPEAKER_00` is not machine-distinguishable from a real name.

`segment_labels[]` is present on 76 of 85 records; its values were not reconciled against the `segment_labels` used in `segments[]` in this pass; it is the correct place for per-transcript speaker labels, so any consolidation of `speaker_id` must preserve it — Task E did.

### 4.7 `violations_cited[]` — the largest single defect

> **FIXED 2026-09-13.** Now 35 distinct registry IDs over 85 entries, 0 non-conforming. Unmappable strings were dropped, not relocated. See `docs/VIOLATIONS_CROSSWALK.md`.

101 citations across 14/27 files (13 files empty). The list holds **three incompatible kinds of value**:

| Kind | Count | Share | Examples |
|---|---|---|---|
| Registry code | **32** (29 distinct) | 32% | `CL-008`, `INT-017`, `BR-012` |
| Statutory article reference | **45** | 45% | `CACH Art. 131`, `CPCL Art. 197 — Falsificación en instrumento privado`, `LPDC Art. 23 bis (a)-(e)`, `Ley 20.609 (Ley Zamudio)`, `ICAO Annex 9 Std. 3.42` |
| Free prose / pseudo-tag | **24** | 24% | `PATTERN-OF-FAILURE`, `TOTAL-SERVICE-BLOCK`, `WRONGFUL-USE-OF-INTERNAL-CHANNEL`, `Abuso de autoridad — forcible removal without valid cause`, `Lifetime travel ban without due process`, `Stigmatisation and discrimination via 'disruptivo' label` |

**Distribution is extremely skewed** — from 0 to 17 entries:

`17` → `04`; `13` → `17`; `12` → `10`; `10` → `24`; `9` → `23`; `8` → `21`,`22`; `6` → `18`,`20`; `5` → `12`; `3` → `07`; `2` → `01`; `1` → `03`,`08`; **`0` → 13 files**

**Duplication of a single legal concept.** The same instrument is re-entered with different suffixes, so a set-comparison treats one norm as five violations:

* `CACH Art. 131` appears as: `CACH Art. 131` · `CACH Art. 131 — Duty to inform passenger of rights` · `CACH Art. 131 — Duty to inform passengers of their rights` · `CACH Art. 131 — failure to inform passenger of rights` · `CACH Art. 131 — no rights information provided`
* `CPCL Art. 197` — 4 distinct strings; `CHIPENCOD Art. 211` — 3; `LPDC Art. 23 bis` — 5; `LPDC Art. 3(b)` — 4.
* By contrast `CHIPENCOD Art. 211` and `CPCL Art. 211 (CHIPENCOD)` are used for the same provision with the framework code in two different positions.

**Registry validation (performed against the registry that is on disk).** The registry at `discovery/_files_which_will_be_used_in_pipeline/violations/*.json` contains **81 codes**. Of the 29 distinct clean codes cited, **all 29 resolve — 0 unresolved** — but **52 of 81 registry codes are never cited by any transcript**. So the field is simultaneously over-fragmented (91 strings for 29 concepts) and under-citing (only 36% of the registry is used).

**No evidentiary anchoring.** Citations carry no `segment`, no `confidence`, and no `trust_tier`. Unlike `key_evidentiary_findings[]` (which at least sometimes carries `segments`) and unlike `forensic_clusters` (which always carries `segments`), a `violations_cited` entry cannot be traced back to the transcript it is asserted against. This is the single most important missing capability in the header.

**Cross-layer contamination.** Several strings are *claims about the case*, not *citations of law* (`PATTERN-OF-FAILURE`, `TOTAL-SERVICE-BLOCK`, `EVIDENCE-PRESERVATION-DUTY`, `Procedural weaponization — airline accusation compels automatic police action with zero discretion`). Stored in `violations_cited`, they will be mistaken for legal norms by any consumer of the field.

### 4.8 `tags[]`

> **FIXED 2026-09-13 (casing only).** All 202 tags are lowercase kebab-case, 0 non-conforming. The 97 distinct values are inherent to the corpus and were left alone. See `docs/VOCABULARY_NORMALIZATION.md`.

27/27 non-empty (3–14 per file), **202 instances, 97 distinct** — i.e. a **long tail**: only 9 tags appear 3+ times, and **~70 tags appear exactly once**.

Universal/near-universal tags: `transcript` (27), `evidence` (27), `narrative` (26 — missing only in `I-002_06_NAR-STG_8_pdi_identity_control.json`).

There is **no controlled vocabulary**, and the inconsistency is visible on several axes:

* **Case**: lowercase kebab (`ley-20831`, `tokyo-convention`) vs Title-Case (`Portuguese`, `Chilean-Aviation-Law`) vs ALL-CAPS (`PPD`, `PDI`, `DGAC`).
* **Language**: English concepts (`boarding-denial`, `false-accusation-allegation`) vs Spanish (`categoria-3`, `passa-diario`, `no-existe`, `atados-de-mano`, `pasajero-disruptivo`) — with no language marking; and `Portuguese` (tag) vs `pt` (the `language` field) for the same idea.
* **Granularity**: entities (`latam`, `barraza`), concepts (`systemic-pattern`), document types (`falsified-document`, `document-invalidity`), and stage labels (`day-2`, `pre-boarding`) are all mixed in one namespace.
* **Type**: tags duplicate information already held in dedicated fields — stage tags duplicate `narrative_id`/`chronological_order`; `false-aggression-allegation` duplicates content in `key_evidentiary_findings`; and the 4 pseudo-tags that should logically live here (`PATTERN-OF-FAILURE`, `TOTAL-SERVICE-BLOCK`, `WRONGFUL-USE-OF-INTERNAL-CHANNEL`, `EVIDENCE-PRESERVATION-DUTY`) are instead in `violations_cited` (§4.7).

### 4.9 `forensic_clusters{}`

> **FIXED 2026-09-13.** One schema: `{summary, reasoning, provisions_engaged, violation_linkage, segments}`. See `docs/SCHEMA_NORMALIZATION.md`.

**Coverage: 11/27 non-empty; 16 empty.** 62 clusters total, 2–10 per file. Key naming is consistent (`cluster_A_…`, `cluster_B_…`, …, up to `cluster_J_…`), which makes the block easy to traverse.

The **value schema is not consistent — three variants exist**:

| Value keys | Occurrences | Files |
|---|---|---|
| `{segments, summary}` | 48 | `01`,`02`,`03`,`04`,`05`,`06`,`09`,`12`,`14` |
| `{provisions_engaged, reasoning, segments, summary, violation_linkage}` | 13 | `08`, `10` |
| `{provisions_engaged, reasoning, segments, summary}` | 1 | `08` |

File `08` (`I-002_08_NAR-09_STG_15_luggage_recovery.json`) **mixes both schemes inside one file**.

Two consequences:
* A consumer reading `provisions_engaged` / `violation_linkage` gets a value in `08` and `10` and nothing anywhere else.
* This is a **third place** where violation/provision information is encoded (after `violations_cited[]` and `key_evidentiary_findings[]`), with no cross-reference between them. Whether `violation_linkage` values are registry codes or prose was not normalized, so a legal-concept census of the corpus is currently impossible.

### 4.10 `key_evidentiary_findings[]`

> **PARTLY FIXED 2026-09-13.** Schema unified to `{id, finding, strength, segments, cross_reference}` and `strength` reduced to `High`/`Medium`/`Low`; `segments` is still optional, so the 101 unanchored findings remain open (H4).

**153 findings; 23/27 non-empty; 4 empty** — and those 4 (`05B`, `07`, `10A`, `10B`) are the same files that are empty for `forensic_clusters`.

**Six different record shapes** occur:

| Keys present | Occurrences (approx.) |
|---|---|
| `{id, finding, strength}` | — |
| `{id, finding, segments, strength}` | — |
| `{id, finding, strength, cross_reference}` | — |
| `{id, finding, segments, strength, cross_reference}` | 67 carry `cross_reference` |
| `{id, finding, note, segments, strength}` | 6 carry `note` |
| `{id, finding, note, strength, cross_reference, segments}` | — |

Field census across all 153 findings: `id` 153, `finding` 153, `strength` 153, `cross_reference` 67, `segments` **52**, `note` 6.

* **101 of 153 findings (66%) have no `segments`** — i.e. most findings cannot be traced back to a segment. This is the opposite of `forensic_clusters`, which always carries `segments`. The corpus's most important analytic layer is the least anchored.
* `id` is present on all 153 and unique within the corpus (`S6-1`, `T2-1`, … — stage-derived prefixes), so findings are addressable even when unanchored.
* `cross_reference` (67 findings) has no documented semantics and no counterpart field; it is presumably a cross-file reference but its target format is unverified.
* **`strength` uses 7 unconverted values**: `High` (83), `Medium` (31), `Critical` (26), `Low` (2), `Remarkable` (1), `★★★★★★` (3), `★★★★★` (7). Two values are literal Unicode star strings. There is no ordinal mapping, so `Critical` vs `★★★★★★` vs `High` cannot be compared, sorted, or filtered.

### 4.11 `corrections_applied[]`

> **FIXED 2026-09-13.** One schema: `{segment, original, corrected, reason, type}`; 9 legacy records coerced. See `docs/SCHEMA_NORMALIZATION.md`.

**47 records; only 6/27 files non-empty** (`02` 9, `03` 10, `04` 1, `08` 19, `12` 5, `14` 3); 21 files empty. **Three record shapes**:

| Shape | Records | Files |
|---|---|---|
| `{segment, original, corrected, reason}` | 38 | `02`, `03`, `08` |
| `{type, note}` | 3 | `14` |
| bare `string` | 6 | `04` (1), `12` (5) |

Problems:
* The two keyed shapes do not share a key. `{segment, original, corrected, reason}` is directly actionable; `{type, note}` is not (no segment, no original text).
* The **bare strings carry no provenance at all** — there is no segment, no original, no reason, so the correction cannot be audited or applied.
* Coverage tracks "who did the transcription", not "which transcripts needed corrections" — `08` alone holds 19 of 47 records. Files with rich analytic content (`10`, `14` except 3, `17`, `24`) have none, which may be genuine or may be an unreviewed gap.

### 4.12 `metadata` block

> **Status: FIXED 2026-09-13** by `scripts/backfill_audio_metadata.py`. `metadata`
> is now populated and complete in **27/27** files. See
> `docs/AUDIO_SOURCE_MAPPING.md` §4. The findings below are the pre-fix state.

> **Correction to an earlier draft of this report.** `ontology_node_id`,
> `ontology_schema_version`, `saved_audio_file` and `processed_audio_file` are
> sub-keys **inside `metadata`**, not top-level fields, and each was present in
> only **3** files — not universally present and null as first stated here.

`metadata` was a non-empty object in only **13/27** files; **14 files had
`metadata: {}`**.

| Sub-key | Coverage (before) | Notes |
|---|---|---|
| `file_info` | **10/27** | keys: `file_name` (10), `file_size` (9), `file_size_kb` (9), `major_brand` (9), `content_type` (9) — one file (`11`) has `file_name` only |
| `timestamps` | **9/27** | keys: `QuickTime_Movie_Header_Created` (9), `QuickTime_Movie_Header_Preview/Poster/Selection/Current_Time` (4), `File_Modified_Date` (2) |
| `audio_properties` | **9/27** | `duration`, `track_id`, `preferred_volume` (9 each) — durations range `00:00:59.733` to `00:39:54.186` |
| `ontology_node_id` | **3/27** | `TRNS_a51eca2c`, `TRNS_7962d91d`, `TRNS_d5bf2f2c` (files `02`, `03`, `05`) |
| `ontology_schema_version` | **3/27** | `2.3.1` in all three |
| `processed_audio_file` | **3/27** | `05B`, `10A`, `10B` — all pointed at `.m4a_processed.wav` artefacts |
| `saved_audio_file` | **3/27** | `05B`, `10A`, `10B` |

Defects found:
* Coverage was triple-partitioned: 9 files had the media trio, 3 different files
  had the ontology pair, 3 different files again had the process pair. **No file
  had all sub-blocks**, so no file was a complete media record.
* `QuickTime_Movie_Header_Created` is an **empty string** in 3 of its 9 files
  (`10`, `12`, `14`) — present-but-null. Preserved as-is.
* `File_Modified_Date` values are **2025** (`2025-07-06T15:53:46.000Z`), i.e.
  processing artefacts recorded alongside recording timestamps with no field to
  distinguish them. Preserved as-is; do not read them as provenance.
* `ontology_schema_version` was **`2.3.1`** in all three instances — a stale
  schema. It is now **`2.5`** on all 27.
* There is no `duration`-vs-segment-count check performed here, but note that
  files with the richest `metadata` were not the longest recordings (`04` is
  39:54 but `14` is 375 segments with a 2025-modified header) — provenance and
  content were evidently produced by different passes.
* **Two stored `file_size` values were provably wrong rather than merely missing.**
  `I-002_14_NAR-16_STG_23_DGAC_don_nicolas` said `"21699915 bytes"` while the real
  `Aeropuerto Arturo Merino Benítez 23.m4a` is **21701500** bytes — a **1,585-byte
  deficit**, the only numeric mismatch in the corpus. `I-002_12_NAR-15_STG_22_DGAC_office`
  had `file_size: ""` (empty string) despite carrying a correct `file_name`.
  Both are now the probed integer.

**What the backfill wrote** (all 27 files, every sub-key):

| Sub-key | Now |
|---|---|
| `audio_properties` | `duration` (normalized `HH:MM:SS.mmm`), `preferred_volume`, `sample_rate` (int), `channels` |
| `file_info` | `file_name`, `file_size` (int), `file_size_kb`, `content_type`, `major_brand`, plus `compatible_brands` / `encoder` / `voice_memo_uuid` when the file carries them |
| `timestamps` | all pre-existing keys preserved verbatim + new `QuickTime_Movie_Header_Created_verified` |
| `ontology_node_id` | `""` for 24 files; the 3 real IDs above **preserved, not blanked** |
| `ontology_schema_version` | `"2.5"` everywhere |
| `saved_audio_file` | real on-disk recording filename |
| `processed_audio_file` | real on-disk recording filename (replaces the `.wav` artefacts) |

Sub-keys are stored in alphabetical order to match the pre-existing convention.
Two type migrations were applied: `audio_properties.track_id` was **mislabelled**
— it held a sample rate (`"48000"`/`"44100"`/`""`), not a track id — and was
replaced by `sample_rate` (int); and `file_info.file_size` went from the string
`"68673430 bytes"` to the int `68673430`.

### 4.13 `reviewed`

> **FIXED 2026-09-13.** Present on 27/27 — `true` in 9, explicit `false` in the other 18, so absent no longer means unknown.

* Present on **9/27**, always with value `true` (`06`, `09`, `12`, `15`, `16`, `21`, `22`, `23`, `24`).
* **Absent on 18/27.** No file has `reviewed: false`.
* Consequence: **"absent" is ambiguous** — it could mean "not reviewed", "not applicable", or "the flag is optional". Because `true` is the only value ever written, the flag currently conveys nothing beyond "this file passed through a pass that writes `reviewed: true`".
* The flag sits at the top level, separate from segment-level review state; there is no summary of how many segments were reviewed, so a file marked `reviewed: true` gives no indication of the review's depth.

---

## 5. Per-file completeness matrix

Rows in `chronological_order`. `md.t/r/a` = `metadata.timestamps` / `metadata.audio_properties` / `metadata.file_info` present (letter) or absent (`·`). `src/prov` = `source_file` / `provider` populated.

| # | File | Lang | Segs | md t/r/a | src/prov | rev | viol | tags | clusters | findings | corr | parts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `I-002_01_NAR-01_STG_1_pre_boarding.json` | pt | 9 | TAF | S P | — | 2 | 8 | 2 | 3 | 0 | 2 |
| 2 | `I-002_02_NAR-02_STG_2_boarding_gate.json` | es | 60 | TAF | · · | — | 0 | 6 | 6 | 7 | 9 | 5 |
| 3 | `I-002_03_NAR-05_STG_5_aircraft_removal.json` | es | 28 | TAF | · · | — | 1 | 7 | 6 | 7 | 10 | 2 |
| 4 | `I-002_04_NAR-06_STG_6_jetbridge_standoff.json` | es | 418 | TAF | · · | — | 17 | 9 | 5 | 9 | 1 | 7 |
| 5 | `I-002_05_NAR-07_STG_7_post_removal_investigation.json` | es | 183 | TAF | · · | — | 0 | 9 | 6 | 8 | 0 | 5 |
| 6 | `I-002_05B_NAR-11_STG_11_waiting_area.json` | pt | 4 | · · · | S · | — | 0 | 5 | 0 | 0 | 0 | 1 |
| 7 | `I-002_06_NAR-STG_8_pdi_identity_control.json` | es | 127 | · · · | · · | ✓ | 0 | 6 | 4 | 5 | 0 | 10 |
| 8 | `I-002_07_NAR-06_STG_13_post_PDI_corridor.json` | es | 211 | · · · | · · | — | 3 | 8 | 0 | 0 | 0 | 2 |
| 9 | `I-002_08_NAR-09_STG_15_luggage_recovery.json` | es | 93 | TAF | · · | — | 1 | 5 | 6 | 8 | 19 | 2 |
| 10 | `I-002_09_NAR-10_STG_16_counter_confrontation.json` | es | 147 | · · · | · · | ✓ | 0 | 8 | 4 | 6 | 0 | 3 |
| 11 | `I-002_10A_NAR-19_STG_19_counter_escalation.json` | es | 19 | · · · | S · | — | 0 | 5 | 0 | 0 | 0 | 2 |
| 12 | `I-002_10_NAR-14_Terminal_Internacional_T2_counter.json` | es | 183 | TAF | S P | — | 12 | 9 | 8 | 12 | 0 | 5 |
| 13 | `I-002_10B_NAR-18_STG_18_counter_fragment.json` | **en** | 3 | · · · | S · | — | 0 | 5 | 0 | 0 | 0 | 1 |
| 14 | `I-002_11_NAR-13_STG_20_barraza_counter.json` | es | 75 | · · F | · · | — | 0 | 7 | 0 | 2 | 0 | 2 |
| 15 | `I-002_12_NAR-15_STG_22_DGAC_office.json` | es | 134 | TAF | S P | ✓ | 5 | 12 | 5 | 8 | 5 | 4 |
| 16 | `I-002_13_NAR-18_STG_26_self_narration.json` | es | 23 | · · · | · · | — | 0 | 4 | 0 | 1 | 0 | 1 |
| 17 | `I-002_14_NAR-16_STG_23_DGAC_don_nicolas.json` | es | 375 | TAF | S P | — | 0 | 14 | 10 | 14 | 3 | 5 |
| 18 | `I-002_15_NAR-19_STG_27_self_narration.json` | es | 4 | · · · | · · | ✓ | 0 | 4 | 0 | 1 | 0 | 1 |
| 19 | `I-002_16_NAR-20_STG_28.json` | es | 25 | · · · | · · | ✓ | 0 | 3 | 0 | 1 | 0 | 1 |
| 20 | `I-002_17_NAR-21_STG_29.json` | es | 115 | · · · | · · | — | 13 | 8 | 0 | 7 | 0 | 5 |
| 21 | `I-002_18_NAR_LATAM_STG_2.json` | es | 33 | · · · | · · | — | 6 | 8 | 0 | 4 | 0 | 2 |
| 22 | `I-002_19_NAR_LATAM_STG_3.json` | es | 17 | · · · | · · | — | 0 | 4 | 0 | 1 | 0 | 1 |
| 23 | `I-002_20_NAR_LATAM_STG_4.json` | es | 142 | · · · | · · | — | 6 | 9 | 0 | 6 | 0 | 3 |
| 24 | `I-002_21_NAR_CARABINEROS_1.json` | es | 163 | · · · | · · | ✓ | 8 | 9 | 0 | 10 | 0 | 4 |
| 25 | `I-002_22_NAR_CARABINEROS_2.json` | es | 227 | · · · | · · | ✓ | 8 | 10 | 0 | 12 | 0 | 3 |
| 26 | `I-002_23_NAR_CARABINEROS_3.json` | es | 113 | · · · | · · | ✓ | 9 | 10 | 0 | 9 | 0 | 3 |
| 27 | `I-002_24_NAR-19_STG_12.json` | es | 276 | · · · | · · | ✓ | 10 | 10 | 0 | 12 | 0 | 5 |

Observations from the matrix:
* The **media metadata** block (rows 1–5, 9, 12, 15, 17) and the **analytic** block (rows 20–27) are almost disjoint populations. Files that have media metadata tend to have clusters and corrections; files that carry heavy citation load tend to have no metadata at all.
* The **"empty shell" files** — rows 6, 11, 13, 16, 18, 19, 22 — are 0-cluster files with 0–1 findings and 1–2 participants. They are the fragment / self-narration records.
* The **four findings-less files** (`05B`, `07`, `10A`, `10B`) coincide exactly with the four cluster-less files.
* `reviewed: true` clusters on the Carabineros block (rows 24–26) and a few others, never on the metadata-rich early files.

---

## 6. Defect register (ranked by impact on downstream use)

| ID | Defect | Evidence | Impact |
|---|---|---|---|
| **H1** | Unanchored violations: no `violations_cited` entry carries `segment`, `confidence`, or `trust_tier` | 101/101 citations lack anchoring | Violations cannot be verified against the transcript; the field is assertion-only |
| **H2** | `violations_cited[]` mixes codes, article references and prose | 32 / 45 / 24 split; 91 strings for 29 concepts | Set operations, counts and registry joins are wrong — **FIXED 2026-09-13** (35 distinct registry IDs, 0 non-conforming) |
| **H3** | Three-way time disagreement | stored QuickTime header **+3 h** wrong in all 9 files that had it; the remaining gap to `recording_datetime` was ~4 h; 15 of 27 `recording_datetime` values had drifted (up to ~+2 h); `timestamp` empty in 1 and seconds-drifted in 2; 5 files end in `Z` (mislabel), 21 naive | No single trustworthy time axis; sorting/merging across files is unreliable — **FIXED 2026-09-13** |
| **H4** | `key_evidentiary_findings[]` largely unanchored + uncontrolled `strength` | 101/153 findings lack `segments`; was 7 `strength` values incl. `★★★★★★` | 66% of the key analytic output is untraceable and unsortable — `strength` **FIXED** (`High`/`Medium`/`Low`); anchoring still open |
| **H5** | Three different schemas for `forensic_clusters` values (one file mixes two) | was 48 / 13 / 1 | Legal-provision content in clusters was unreadable in 9 of 11 files — **FIXED 2026-09-13** (one 5-key schema) |
| **H6** | Bimodal completeness: analytic fields empty in ~40–75% of files | clusters 16 empty, corrections 21, violations 13, `metadata` 14 (`{}`), `reviewed` absent 18 | Corpus-level aggregates silently under-count (`metadata` part **FIXED**) |
| **H7** | `reviewed` semantics undefined; 18 files lack it; `false` never occurs | was 9× `true`, 18 absent | Cannot distinguish "not reviewed" from "not applicable" — **FIXED 2026-09-13** (explicit `false` in the other 18) |
| **H8** | Broken `prior_stage`/`next_stage` chain | was 3 wrong links; `05B` and `07` orphaned — and both are analytic-empty | Any chain traversal silently drops two files — **FIXED 2026-09-13** (0 issues) |
| **H9** | `speaker_id` fragmentation and 8 null IDs | was 48 distinct IDs; stage-scoped slugs; `SPEAKER_00–05`; `canonical_name: "Unknown"` and raw ASR labels | Person-level aggregation and per-speaker attribution are unreliable — **FIXED 2026-09-13** (43 values, 0 null, suffix-free) |
| **H10** | `tags[]` has no controlled vocabulary | 97 distinct / 202 instances; ~70 singletons; casing, language and granularity mixed | Tags unusable as a query facet; duplicates content held elsewhere — casing **FIXED 2026-09-13** (0 non-kebab values); the 97-value spread is inherent to the corpus |
| **H11** | Provenance thrift: `source_file` was 7/27, `provider` 4/27, `original_transcript_id` redundant self-ref 22/27 | one `source_file` even pointed at a transcript JSON (`aeropuerto_STG_23.json`) | No reliable link back to the source media — **FIXED 2026-09-13** (`source_file`/`source_path`/`provider` `local` ×27; `original_transcript_id` now `null` ×27) |
| **H12** | `corrections_applied` has 3 shapes; 6 records are bare strings | was 38 / 3 / 6 | Corrections cannot be audited or replayed uniformly — **FIXED 2026-09-13** (one 5-key schema, 9 coercions) |
| **H13** | `metadata` sub-blocks partition the corpus; ontology stuck at `2.3.1` | media trio 9, ontology 3 (`2.3.1`), process pair 3; 14 files `{}`; 3 empty-string timestamps | No file had a complete media/ontology record — **FIXED 2026-09-13** (27/27; `2.3.1` → `2.5`) |
| **H14** | Free-text descriptors: `location` 16 variants for ~4 places; `title` 4 conventions with `FINAL v2` in 20; `subtitle` mixed register | see §4.3/§4.5 | Grouping, filtering and title-based lookup fail — `location` (`14` variants) and `title` **FIXED 2026-09-13** |
| **H15** | Internal contradictions inside single files | Carabineros titles said **Artnel** while subtitle/location say **Dartnell**; `audio_id` `aeropuerto_stg_12` casing; non-breaking hyphen in `sub‑station` | Text search misses — **FIXED 2026-09-13** (0 files contain `Artnel`; `audio_id` `STG` upper-cased; hyphens normalised) |
| **H16** | `classification` identical ×27 | 1 distinct string | Field carries no information; suggests missing per-file status |

---

## 7. Cross-layer notes

1. **The planned enrichment sources are no longer on disk.** `discovery/TRANSCRIPT_HEADER_REVIEW_TASK.md` specifies `_intelligence/law_dossier_registry.json`, `events.json`, `timeline.json`, `event_graph.json` under `discovery/documents_scanned/sessions/<uuid>/workspace/_intelligence/`. That session workspace has been pruned — only `_server_boot/workspace` remains and **no `_intelligence` directory exists anywhere in the repo**. The report above therefore uses only the **canonical transcripts** plus the one registry that survives.
2. **A usable code registry does survive** at `discovery/_files_which_will_be_used_in_pipeline/violations/*.json` (**81 codes**). Cross-check result: **all 29 distinct cited codes resolve; 0 unresolved; 52 registry codes never cited.**
3. **The registry's own titles are defective** and must not be imported into headers: three titles begin with a stray `: "` (`CL-016`, `CL-035`, `CL-037`) and `CL-001`'s title embeds a `[[SPK-stewardess-accuser]]` wikilink. Any code→title copy needs cleaning first.
4. **Legal concepts are encoded in four places** with no cross-links: `violations_cited[]`, `forensic_clusters[].provisions_engaged` / `violation_linkage`, `key_evidentiary_findings[].finding`, and `corrections_applied`. Until these are reconciled, a corpus-wide "which norms are engaged" answer is not derivable.
5. **`speaker_index.json`** (`transcription/data/speaker_index.json`) is the natural place to source `speaker_id` consolidation, `display_name`, `organization`, `identification_confidence`, and `md_file`; the participants defects in §4.6 were exactly its input, and both the index and `data/speakers/*.md` have since been rebuilt against the canonical ids (`docs/SPEAKER_ID_CONSOLIDATION.md`). One profile, `SPK-carabinero-dartnell-female-1.md`, is retained without an index entry by explicit decision — it is unreconciled vault material whose id never existed in the corpus. See that document before citing it.

---

## 8. Recommendations

### 8.1 Normalization (highest value — no new data required)

1. ~~**`violations_cited[]` → bare registry codes only.**~~ — **DONE 2026-09-13**: 35 distinct registry IDs, 0 non-conforming values. The resolution route and every dropped citation are recorded in `docs/VIOLATIONS_CROSSWALK.md`.
2. ~~**Move non-code, non-legal strings out.**~~ — **DONE** with #1 (`PATTERN-OF-FAILURE`, `TOTAL-SERVICE-BLOCK`, the 8 unmappable strings) — dropped rather than relocated, since each was redundant with a registry code that is cited anyway.
3. ~~**Standardize `strength`** to a closed ordinal set and map `Remarkable`/`★★★★★`/`★★★★★★`~~ — **DONE 2026-09-13**: `High` / `Medium` / `Low`, stars removed. `Critical`→`High`, `Remarkable`→`High`, `★★★★★★`→`High`, `★★★★★`→`Medium`. See `docs/SCHEMA_NORMALIZATION.md`.
4. ~~**One cluster schema.**~~ — **DONE 2026-09-13**: `{summary, reasoning, provisions_engaged, violation_linkage, segments}`.
5. ~~**One finding schema.**~~ — **DONE 2026-09-13**: `{id, finding, strength, segments, cross_reference}`; `segments` is still optional (anchoring remains open — see H4).
6. ~~**One correction schema.**~~ — **DONE 2026-09-13**: `{segment, original, corrected, reason, type}`; the 6 bare strings and 3 `{type, note}` objects were coerced (9 total).
7. **`reviewed`:** ~~make it explicit on all 27~~ — **DONE 2026-09-13** (`true` 9, explicit `false` 18). A sibling `review_scope` / `segments_reviewed` count was not added.
8. **`provider`:** ~~either populate it properly for all 27 or remove the key~~ — **DONE** (`local` ×27). Note `unknown` should never be a value.
9. ~~**`original_transcript_id`:** if there is no prior version, set `null` for all 27~~ — **DONE 2026-09-13** (`null` ×27).
10. **`metadata`:** normalize to one sub-object set `{timestamps, audio_properties, file_info, ontology_node_id, ontology_schema_version, saved_audio_file, processed_audio_file}` — **DONE**, in alphabetical order. Still open: replace the 3 empty-string timestamp values with `null`. The target schema version was set to **`2.5`** per instruction (not `2.4`).

### 8.2 Backfill (requires the media / index sources)

11. ~~**`source_file`** from the audio inventory; assert a **single value kind**~~ — **DONE** for all 27: bare on-disk filename in `source_file`, repo-relative path in the new `source_path`, `local` in `provider`. The mapping was established by exact duration **and** byte-size match; see `docs/AUDIO_SOURCE_MAPPING.md`.
12. ~~**Resolve the ~7 h offset**~~ — **DONE**. It was two stacked errors: a **+3 h** bad conversion in the stored QuickTime header, plus a genuine ~4 h UTC-vs-Chile-local gap. All 27 `recording_datetime` and `timestamp` values are now the media file's own `creation_time` in Chile local time (`-04:00`), identical to each other. The wrong stored header value was preserved verbatim as evidence and the true value added as `QuickTime_Movie_Header_Created_verified`. Not normalized to UTC, as this recommendation originally suggested.
13. **`metadata.timestamps` / `audio_properties` / `file_info`** — **DONE** to 27/27 from the audio files (duration, byte size, sample rate, channels, brands, encoder, voice-memo UUID). Still open: the 3 empty-string `QuickTime_Movie_Header_Created` values were preserved, not nulled.
13b. **Still open from this group:** the 9 recordings in `data/audio/` that match no transcript were left untranscribed by decision, and `Terminal Internacional - T2.m4a` plus `Aeropuerto Arturo Merino Benítez 20.m4a` share one identical `creation_time` tag, so their two transcripts now carry the same timestamp.
14. ~~**`location`** to a small closed vocabulary~~ — **DONE 2026-09-13**: 14 values, built on the canonical facility name plus a ` — <place>` suffix (see `docs/VOCABULARY_NORMALIZATION.md`). A separate `location_detail` key was not added; the separator is an em dash, not a plain hyphen.
15. ~~**`speaker_id`** consolidation from `speaker_index.json`~~ — **DONE 2026-09-13**: consolidated in the transcripts from the participant records themselves, which were more complete than the index (the index had already lost the duplicate `SPK-pdi-female` row). `speaker_index.json`, `speaker_patch.json` and `data/speakers/*.md` were then regenerated against the canonical ids — the index now holds 43 canonical keys with 85 appearances, the patch holds no non-canonical suggestions, and the profile set is 43 canonical files plus the one retained orphan (`SPK-carabinero-dartnell-female-1.md`, kept by decision as unreconciled vault material). See `docs/SPEAKER_ID_CONSOLIDATION.md`.
16. **`violations_cited[]`** — extend the 13 empty files from segment-level citations once anchoring exists, so coverage is driven by content, not by who transcribed the file.
17. ~~**`tags[]`** — define a controlled vocabulary (recommend lowercase kebab-case, English keys, with a separate `tags_es[]` or a `lang` suffix for Spanish-language tags).~~ — **DONE 2026-09-13** for the casing/separator half (lowercase kebab-case, 0 non-conforming values; see `docs/VOCABULARY_NORMALIZATION.md`). The English/Spanish split was not adopted: `tags` remains a single bilingual list.

### 8.3 Proposed canonical header (target shape)

> **Legend:** `ACHIEVED` blocks match the files as they stand now. `TARGET`
> blocks are still aspirational — the corpus has not been migrated to them.

```jsonc
{
  "transcript_id": "I-002_04_NAR-06_STG_6_jetbridge_standoff",
  "source_file": "Aeropuerto Arturo Merino Benítez 6.m4a",   // ACHIEVED: bare on-disk name
  "source_path": "transcription/data/audio/Aeropuerto Arturo Merino Benítez 6.m4a",  // ACHIEVED
  "language": "es",                        // primary language, closed enum
  "timestamp": "2024-07-05T14:47:13-04:00",  // ACHIEVED: == recording_datetime, Chile local
  "provider": "local",                     // ACHIEVED ×27
  "original_transcript_id": null,          // TARGET: null when no prior version
  "metadata": {                            // ACHIEVED: all 27
    "audio_properties": {
      "duration": "00:39:54.186",
      "preferred_volume": "1",
      "sample_rate": 44100,                 // replaces the mislabelled track_id
      "channels": 1
    },
    "file_info": {
      "file_name": "Aeropuerto Arturo Merino Benítez 6.m4a",
      "file_size": 68673430,                // int, not "68673430 bytes"
      "file_size_kb": 67063.9,
      "content_type": "audio/mp4",
      "major_brand": "M4A",
      "compatible_brands": ["M4A", "isom", "mp42"],
      "encoder": "com.apple.VoiceMemos (iPhone Version 18.5 (Build 22F76))",
      "voice_memo_uuid": "981D09D7-144C-4857-A1BE-FE6D70B3332E"
    },
    "ontology_node_id": "",                // "" when absent; real IDs preserved
    "ontology_schema_version": "2.5",
    "processed_audio_file": "Aeropuerto Arturo Merino Benítez 6.m4a",
    "saved_audio_file": "Aeropuerto Arturo Merino Benítez 6.m4a",
    "timestamps": {
      "QuickTime_Movie_Header_Created": "2024-07-05T21:48:13.000Z",  // preserved, WRONG (+3 h)
      "QuickTime_Movie_Header_Created_verified": "2024-07-05T18:47:13.000000Z"
    }
  },
  "title": "…",
  "subtitle": "…",
  "recording_datetime": "2024-07-05T14:47:13-04:00",  // ACHIEVED: from the media file
  "location": "SCL — aircraft/jetbridge",  // TARGET: closed vocabulary
  "audio_id": "aeropuerto_STG_6",          // TARGET: align with source_file
  "case_id": "I-002",
  "narrative_id": "NAR-06_STG_6_jetbridge_standoff",
  "chronological_order": 4,
  "prior_stage": "I-002_03_NAR-05_STG_5_aircraft_removal",
  "next_stage": "I-002_05_NAR-07_STG_7_post_removal_investigation",
  "classification": "attorney-work-product",  // TARGET: per-file status
  "tags": ["latam", "forced-removal", "systemic-pattern"],   // TARGET: controlled vocab

  "participants": [                       // TARGET
    { "speaker_id": "SPK-passenger-leandro", "display_name": "Leandro Disconzi",
      "organization": null, "identification_confidence": "confirmed",
      "canonical_name": "Leandro Disconzi",   // no stage names
      "role": "Passenger", "speaker_label": "Passenger (Leandro Disconzi)",
      "segment_labels": ["…"] }
  ],

  "violations_cited": [                     // TARGET: bare registry codes ONLY
    { "code": "CL-002", "trust_tier": "A", "segments": [12, 13, 88] }
  ],

  "forensic_clusters": {                    // TARGET: one schema
    "cluster_A_escalating_allegations": {
      "summary": "…", "segments": [1, 2, 3],
      "provisions_engaged": ["CL-013"],
      "reasoning": "…", "violation_linkage": ["CL-013"]
    }
  },

  "key_evidentiary_findings": [             // TARGET: segments REQUIRED
    { "id": "S6-1", "finding": "…", "strength": "high", "segments": [4, 5] }
  ],

  "corrections_applied": [                  // TARGET: one schema
    { "segment": 7, "original": "…", "corrected": "…", "reason": "…" }
  ],

  "reviewed": true                          // TARGET: explicit on all 27
}
```

**Note on time zone choice.** The report originally recommended normalizing all
timestamps to UTC with an explicit `Z`. The applied fix instead keeps them as
**Chile local time with an explicit `-04:00` offset** — unambiguous for machine
use, and directly readable as the wall-clock time on the original recordings,
which matters for an evidentiary corpus. Offset-bearing local time and UTC sort
identically as strings within one zone; the caveat is that these timestamps are
not comparable by naive string sort against any future UTC-form timestamps.

---

## 9. Appendix — measured counts

| Quantity | As measured | After repair (2026-09-13) |
|---|---|---|
| Transcripts | 27 | 27 |
| Segments | 3,207 | 3,207 |
| Top-level header keys | 24 universal (`reviewed` on 9 only) | **27 on all 27 files** |
| `source_file` / `provider` populated | 7 / 4 | **27 / 27** (`local`) |
| `original_transcript_id` | self 22, empty 5 | **`null` ×27** |
| `metadata` non-empty | 13 (14 × `{}`) | **27/27** |
| `metadata` sub-key coverage | file_info 10, timestamps 9, audio_properties 9, ontology_node_id 3, ontology_schema_version 3, saved/processed_audio_file 3 | **all 7 sub-keys on 27/27** (`2.5`) |
| `participants` records | 87 over 48 distinct `speaker_id` (8 null) | **85 over 43 canonical ids (0 null)** |
| … records missing `segment_labels` | 0 claimed | **9** (the 8 minted + `SPK-pdi-female` in `06`) |
| `violations_cited` entries | 101 in 14 files (13 empty) | **85 in 14 files (13 empty)** |
| … codes / articles / prose | 32 / 45 / 24 | **85 / 0 / 0** |
| … distinct codes | 29 cited vs 81 in registry (52 never cited, 0 unresolved) | **35 cited vs 81, 0 unresolved** |
| `tags` entries | 202, 97 distinct | 202, 97 distinct, **0 non-kebab-case** |
| `forensic_clusters` | 62 in 11 files (16 empty); schemas 48 / 13 / 1 | 62 in 11 files; **1 schema** |
| `key_evidentiary_findings` | 153 in 23 files (4 empty); 101 lack `segments`; 7 `strength` values | 153 in 23 files; **101 still lack `segments`**; **`strength` ∈ {High, Medium, Low}** |
| `corrections_applied` | 47 in 6 files (21 empty); shapes 38 / 3 / 6 | 47 in 6 files; **1 schema** |
| `location` distinct | 16 | **14** |
| `title` distinct | 27 (20 contain `FINAL v2`) | 27, **imported from `docs/LA8159-Overview.html`** |
| `reviewed` | 9 × `true`, 18 absent | **9 × `true`, 18 × `false`** |
| QuickTime-vs-`recording_datetime` offset | stored header **+3 h 00 m** in all 9 that had one (3 held `""`); `recording_datetime` drifted in 15/27 | **0** — all 27 derive from the media file, `-04:00` |
| `chronological_order` duplicates | 0 | 0 |
| Broken prior/next links | 3 (orphans: `05B`, `07`) | **0** |

*End of report.*
