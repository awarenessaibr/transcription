# Speaker Registry & Diarization Resolution

**Date:** 2026-10-03
**Status:** stages 1–3 implemented; stage 4 (acoustic) designed, not built
**Scope:** `templates/speakers-registry.html`, `data/speakers/*.md`, the resolution
API, and the consumable speaker+segment map.

---

## 1. Review — `templates/speakers-registry.html`

2,742 lines. A **read-only viewer** over the curated registry. Three fetches
(`/api/speakers/files`, `/api/speakers/index`, and the `/speakers/*.md` static
mount) plus a relative-path fallback so the page also works from a directory of
markdown files.

### What it gets right

* **Escaping is complete and consistently applied.** Its `escapeHtml` handles all
  five entities (`& < > " '`) and all nine `innerHTML` sites showed zero
  unescaped concatenations under an automated scan. This is the template the
  others should copy — `pinocchio.html`/`pinocchio-en.html` shipped a stored XSS
  in exactly this pattern (fixed separately on this branch).
* **No dead references.** Every path it calls exists; it has no dependency on the
  retired law registry (0 references), so the law removal did not break it.
* **Read-only by construction** — it issues no writes, so it cannot corrupt the
  registry it displays.

### The gap that motivated this work

1. **It never surfaces the unresolved segments.** `GET /api/speakers/index`
   returns `unmapped_segment_labels` and a summary with
   `total_unmapped_segment_instances: 424` — but the template greps to **zero**
   hits for "unmapped"/"unresolved". The single most actionable number in the
   data (10.5% of segments carry a label that resolves to nobody) is invisible.
2. **It is display-only.** It cannot resolve a fresh diarization, apply a
   mapping, or regenerate the index. Those are exactly the operations that make
   the registry useful at capture time.
3. **The `SPEAKER_nn` bridge did not exist anywhere.** Diarization emits opaque
   labels; the registry holds curated identities; nothing connected them for a
   *new* run. The mapping for the existing 29 transcripts existed only
   implicitly, hand-written into `participants[].segment_labels`.

### Data model observed

| Source | Contributes |
|---|---|
| `data/speakers/*.md` frontmatter | `display_name`, `role`, `organization`, `identification_confidence`, `aliases[]`, `key_statements[].quote`, `classification` |
| `data/speaker_index.json` | `mapped_speakers[SPK].appearances[]` → `transcript_id`, `segment_labels[]`, `segment_indices[]`; `summary`; `unmapped_segment_labels` |
| `data/speaker_patch.json` | 1,474 suggested label→id patches (507 auto / 967 review) |

**Identification is hand-curated, not acoustic** — `identification_confidence`
is `confirmed`/`partial` and the notes record a human mapping source. There is no
voiceprint data in the registry at all.

---

## 2. The resolution design

`src/application/services/speaker_resolver.py` is **pure** (no I/O, no model) and
**never writes**. It proposes `raw label → SPK-...` with the signals that justify
each proposal, because attribution in an evidentiary record must be reviewable.

| Signal | Confidence | What it means |
|---|---:|---|
| `participant_segment_label` | 1.00 | The transcript already records this label — a human already decided |
| `single_known_speaker` | 0.90 | The recording is known to contain exactly one speaker |
| `known_statement` | 0.85 | A verbatim registry quote appears in this label's text |
| `label_matches_alias` | 0.70 | The raw label is one of the speaker's names, or a curated label |
| `mentioned_by_other_speaker` | 0.30 | *Advisory only*: this label's text names someone. Presence, not identity |

`proposals_to_map()` collapses proposals to a mapping, excluding advisory signals
and honouring a confidence floor.

### Two flaws found by simulating a fresh run against the real corpus

Both were invisible until the resolver was pointed at real data:

1. **Generic labels matched the registry globally.** `SPEAKER_00` is local to one
   recording, yet a stale profile carrying `SPEAKER_00` in its `segment_labels`
   matched *every* fresh run (observed: `SPEAKER_00 → SPK-unknown-stg-12-speaker-00`
   at 0.7). Generic labels (`speaker[_-]?\d+`) are now excluded from label
   matching entirely.
2. **A fresh run over a known recording could not find its cast**, because the
   index keys appearances by `transcript_id`. `known_cast_for(peer_transcript_ids=…)`
   plus `audio_peers()` (shared `audio_id`) fixes exactly the case this feature
   exists for.

### Honest limit, measured

With more than one candidate the resolver **refuses to pick**, and reports
candidates instead. Its contribution there is narrowing. On the real corpus:

* `I-002_06` (11 opaque labels) goes from "unknown out of 40 registry profiles" to
  **each label narrowed to the 8 people actually in that recording**.
* Where a verbatim quote or an alias label exists, it determines outright. Across
  the 29 transcripts it produces **99 determining proposals** and leaves **11**
  labels unresolved.

Narrowing is not attribution, and the API labels it as such: `determining: false`,
`confidence: 0.0`, `signals: ["known_cast_candidate"]`.

---

## 3. What was built

### API (`src/presentation/routers/speakers.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/speakers/candidates?transcript_id=` | The known cast for a recording + its peer transcripts |
| POST | `/api/speakers/resolve` | Proposals + `proposed_map` + display names. Writes nothing |
| POST | `/api/speakers/map` | Apply a confirmed mapping (`dry_run` supported) |
| GET | `/api/speakers/map/{transcript_id}` | Mapping as stored on the transcript |
| POST | `/api/speakers/segment-map/rebuild` | Regenerate the artifact + refresh the index |
| GET | `/api/speakers/segment-map` | The artifact, built on demand when absent |

`POST /map` is conservative by design:

* sets `segment.speaker_id` and **leaves `segment.speaker` untouched**, so nothing
  keyed on the raw/curated label breaks;
* registers the raw label on the owning participant's `segment_labels` — the
  bridge the existing `generate_speaker_index_v3.py` and the registry UI already
  read, so both light up with no changes to them;
* appends an auditable `corrections_applied` entry.

### Consumable artifact — `data/speaker_segment_map.json`

Schema-versioned, written atomically, gitignored (it is generated). Real output
over the corpus: **27 speakers across 29 transcripts**, with
`SPK-passenger-leandro` at 1,669 segments spanning 27 transcripts, and the 13
unresolved label formats quantified (376 segment instances).

```json
{
  "schema_version": "1.0.0",
  "speakers":    { "SPK-x": { "display_name": "...", "segment_count": 1669,
                              "segments": [ { "transcript_id": "...", "segment_index": 0,
                                              "speaker_label": "...", "start": 0.0,
                                              "end": 1.0, "segment_datetime": "..." } ] } },
  "transcripts": { "<tid>": { "speaker_map": { "SPEAKER_00": "SPK-x" },
                              "unresolved_labels": [...], "segment_count": 418 } },
  "unresolved_segment_labels": { "Passenger (Leandro Disconzi)": 210, "...": 94 }
}
```

### UI (`templates/pinocchio-en.html`)

A **Speakers** card and modal: resolve the loaded transcript, see one row per
label with the proposed identity preselected, the signals, confidence, segment
count and mere mentions; adjust any dropdown; apply. Applying writes the result
into the existing `speakerLabels` map and re-renders, so the segment table shows
names immediately. A rebuild button regenerates the artifact.

Nothing is applied without a click.

---

## 4. Stage 4 — acoustic resolution (designed, not built)

Text and cast signals cannot separate two people who both say unremarkable
things. Only voice can. The pieces exist but are **mutually inconsistent**:

| Piece | Contract |
|---|---|
| `templates/pinocchio-en.html:4591` | POSTs `file`+`start`+`end`+`label`, expects **`{label, voiceprint}`** (an embedding back) |
| `src/presentation/routers/voiceprint.py` | Implements **matching against a supplied library**; returns `{turns[], voiceprints_used}` |
| `src/presentation/routers/pinocchio.py:157` | Serves a **501 stub** — the live route |
| `scripts/identify_speakers.py` | Targets a **different service** (`/api/transcription/identify_from_file`) |

So the feature has four contracts and no working path. Two concrete blockers:

1. **`voiceprint.py` is never mounted** (`main.py` has no `init_voiceprint_router`
   call), so `/api/voiceprint_from_file` 404s while its own docstring claims it
   "replaces the 501 stub".
2. **It would crash if mounted**: it calls `ModelManager.get_embedding_model()`,
   and `ModelManager` only defines `get_whisper_model` and
   `get_diarization_pipeline`.

Proposed stage 4, in order:

1. Add `ModelManager.get_embedding_model()` (pyannote/embedding, 512-dim) with the
   same lazy-cache-and-return discipline as the other two.
2. Split the endpoint into the two operations the four contracts conflate:
   * `POST /api/speakers/voiceprint/extract` → `{label, voiceprint}` for a span
     (what the UI already expects);
   * `POST /api/speakers/voiceprint/match` → `{turns[{label, match_label, confidence}]}`
     against a library (what `voiceprint.py` already implements).
3. Mount it, and store voiceprints against **registry identities** (not free-text
   labels), so an acoustic match produces a `speaker_id` the resolver can consume
   as a new `voiceprint_match` signal alongside the existing five.
4. Keep it advisory: an acoustic match above a threshold is a *proposal*.

Until then, the honest position is the one the resolver takes: narrow the field,
determine what content can determine, and leave the rest for a human.

---

## 5. Follow-ups

* `speakers-registry.html` still does not show `unmapped_segment_labels`. The
  artifact and `/api/speakers/map/{id}` now expose the same information, so the
  template can be updated to surface it.
* `data/speaker_index.json` is tracked but generated (and was written into the
  repo by a test during this work — fixed; the refresh is now in-process at the
  configured path). It should be gitignored like the new artifact.
* The 376 unmapped segment instances are the real remaining data gap; the API
  makes them enumerable so they can be driven to zero.
