# Speaker ID consolidation (Task E)
Transcripts rewritten: **27** of 27.

`speaker_id` space: **46 raw -> 43 canonical** (plus 1 removed).

The enrichment pass appended a per-file disambiguator (`-nar-<stage>`) to
both `speaker_id` and `canonical_name`. Those suffixes are now removed, so a
canonical id no longer encodes the transcript it came from.

## Merge groups

`basis` is **identity** where the raw ids are the same named person, and
**role** where a generic role label was suffixed per stage.

| canonical id | basis | merged from |
|---|---|---|
| `SPK-background` | role | `SPK-background-nar-10-stg-16-counter-confrontation` |
| `SPK-carabinero-constancia` | role | `SPK-carabinero-constancia-nar-carabineros-1` |
| `SPK-carabinero-speaker-00` | role | `SPK-carabinero-speaker-00-nar-carabineros-3` |
| `SPK-computer-officer` | role | `SPK-computer-officer-nar-carabineros-1`, `SPK-computer-officer-nar-carabineros-2` |
| `SPK-dgac` | role | `SPK-dgac-nar-06-stg-6-jetbridge-standoff`, `SPK-dgac-nar-07-stg-7-post-removal-investigation` |
| `SPK-dgac-don-nicolas` | identity | `SPK-dgac-don-nicolas-nar-14-terminal-internacional-t2-counter`, `SPK-dgac-don-nicolas-nar-16-stg-23-dgac-don-nicolas` |
| `SPK-dgac-edgardo-ortiz` | identity | `SPK-dgac-edgardo-ortiz-nar-16-stg-23-dgac-don-nicolas` |
| `SPK-dgac-official-1` | role | `SPK-dgac-official-1-nar-15-stg-22-dgac-office` |
| `SPK-dgac-official-2` | role | `SPK-dgac-official-2-nar-15-stg-22-dgac-office` |
| `SPK-dgac-official-3` | role | `SPK-dgac-official-3-nar-16-stg-23-dgac-don-nicolas` |
| `SPK-female-carabinero-2` | identity | `SPK-female-carabinero-2-nar-carabineros-1`, `SPK-female-carabinero-2-nar-carabineros-2`, `SPK-female-carabinero-2-nar-carabineros-3` |
| `SPK-latam-boss` | role | `SPK-latam-boss-nar-07-stg-7-post-removal-investigation` |
| `SPK-latam-gate-staff` | role | `SPK-latam-gate-staff-nar-02-stg-2-boarding-gate` |
| `SPK-latam-gate-staff-2` | role | `SPK-latam-gate-staff-2-nar-02-stg-2-boarding-gate` |
| `SPK-latam-gate-staff-acuser` | role | `SPK-latam-gate-staff-acuser-nar-02-stg-2-boarding-gate` |
| `SPK-latam-luggage-supervisor-dominika` | role | `SPK-latam-luggage-supervisor-dominika-nar-09-stg-15-luggage-recovery` |
| `SPK-latam-official` | role | `SPK-latam-official-nar-19-stg-12` |
| `SPK-latam-staff` | role | `SPK-latam-staff-nar-19-stg-12` |
| `SPK-latam-staff-acuser` | role | `SPK-latam-staff-acuser-nar-07-stg-7-post-removal-investigation` |
| `SPK-latam-staff-counter` | role | `SPK-latam-staff-counter-nar-14-terminal-internacional-t2-counter` |
| `SPK-latam-staff-counter-2` | role | `SPK-latam-staff-counter-2-nar-14-terminal-internacional-t2-counter` |
| `SPK-latam-staff-counter-female` | role | `SPK-latam-staff-counter-female-nar-14-terminal-internacional-t2-counter` |
| `SPK-latam-staff-random` | role | `SPK-latam-staff-random-nar-16-stg-23-dgac-don-nicolas` |
| `SPK-latam-staff-speaker-01` | role | `SPK-latam-staff-speaker-01-nar-latam-stg-4` |
| `SPK-latam-supervisora` | role | `SPK-latam-supervisora-nar-19-stg-12` |
| `SPK-pasajeros-del-vuelo` | role | `SPK-pasajeros-del-vuelo-nar-06-stg-6-jetbridge-standoff` |
| `SPK-pdi` | role | `SPK-pdi-nar-06-stg-6-jetbridge-standoff`, `SPK-pdi-nar-07-stg-7-post-removal-investigation`, `SPK-pdi-nar-stg-8-pdi-identity-control` |
| `SPK-pdi-2` | role | `SPK-pdi-2-nar-stg-8-pdi-identity-control` |
| `SPK-pdi-female` | role | `SPK-pdi-female-nar-stg-8-pdi-identity-control` |
| `SPK-pilot-ruiz` | identity | `SPK-latam-pilot-ruiz-nar-01-stg-1-pre-boarding`, `SPK-piloto-ruiz-nar-02-stg-2-boarding-gate` |

## Removed participants

| transcript | speaker_id | justification |
|---|---|---|
| _(none)_ | — | — |

## Minted ids for the previously-null `speaker_id` values

Minted ids deliberately omit the `-nar-` prefix so a re-run cannot strip them.

| transcript | speaker label | new id |
|---|---|---|
| `I-002_06_NAR-STG_8_pdi_identity_control` | `SPEAKER_02` | `SPK-unknown-stg-8-speaker-02` |
| `I-002_06_NAR-STG_8_pdi_identity_control` | `SPEAKER_03` | `SPK-unknown-stg-8-speaker-03` |
| `I-002_06_NAR-STG_8_pdi_identity_control` | `SPEAKER_04` | `SPK-unknown-stg-8-speaker-04` |
| `I-002_06_NAR-STG_8_pdi_identity_control` | `SPEAKER_05` | `SPK-unknown-stg-8-speaker-05` |
| `I-002_17_NAR-21_STG_29` | `SPEAKER_00` | `SPK-unknown-stg-29-speaker-00` |
| `I-002_17_NAR-21_STG_29` | `SPEAKER_01` | `SPK-unknown-stg-29-speaker-01` |
| `I-002_17_NAR-21_STG_29` | `SPEAKER_02` | `SPK-unknown-stg-29-speaker-02` |
| `I-002_24_NAR-19_STG_12` | `SPEAKER_00` | `SPK-unknown-stg-12-speaker-00` |

## Duplicate participants removed

| transcript:speaker_id | occurrences dropped |
|---|---|
| _(none)_ | — |

## `canonical_name` changes

The `(NAR-…)` suffix was stripped from 0 names. Where a canonical id still
carried several names, the majority name won (ties broken by transcript
order) so one id maps to one name:

| transcript | canonical id | before | after |
|---|---|---|---|
| _(none)_ | — | — | — |

## Canonical vocabulary

| canonical id | display name | participants | transcripts |
|---|---|---|---|
| `SPK-antonela-latam-agent` | Antonela | 2 | 2 |
| `SPK-background` | background | 1 | 1 |
| `SPK-carabinero-constancia` | Carabinero (Constancia) | 1 | 1 |
| `SPK-carabinero-speaker-00` | Carabinero (SPEAKER_00) | 1 | 1 |
| `SPK-computer-officer` | Computer Officer | 2 | 2 |
| `SPK-dgac` | DGAC | 2 | 2 |
| `SPK-dgac-don-nicolas` | DGAC - Don Nicolas | 3 | 3 |
| `SPK-dgac-edgardo-ortiz` | Edgardo Ortiz | 2 | 2 |
| `SPK-dgac-official-1` | DGAC Official 1 | 1 | 1 |
| `SPK-dgac-official-2` | DGAC Official 2 | 1 | 1 |
| `SPK-dgac-official-3` | DGAC Official 3 | 1 | 1 |
| `SPK-diego-latam-supervisor` | Diego | 1 | 1 |
| `SPK-female-carabinero-2` | Female Carabinero #2 | 3 | 3 |
| `SPK-joaquin-barraza-latam-security` | Joaquín Barraza | 4 | 4 |
| `SPK-latam-boss` | Latam BOSS | 1 | 1 |
| `SPK-latam-gate-staff` | Latam Gate Staff | 1 | 1 |
| `SPK-latam-gate-staff-2` | Latam Gate Staff 2 | 1 | 1 |
| `SPK-latam-gate-staff-acuser` | Latam Gate Staff (Acuser) | 1 | 1 |
| `SPK-latam-luggage-supervisor-dominika` | Latam Luggage Supervisor (Dominika) | 1 | 1 |
| `SPK-latam-official` | LATAM Official | 1 | 1 |
| `SPK-latam-staff` | LATAM Staff | 1 | 1 |
| `SPK-latam-staff-acuser` | Latam Staff (ACUSER) | 1 | 1 |
| `SPK-latam-staff-counter` | Latam Staff Counter | 1 | 1 |
| `SPK-latam-staff-counter-2` | Latam Staff Counter 2 | 1 | 1 |
| `SPK-latam-staff-counter-female` | Latam Staff Counter Female | 1 | 1 |
| `SPK-latam-staff-random` | LATAM Staff (random) | 1 | 1 |
| `SPK-latam-staff-speaker-01` | LATAM Staff (SPEAKER_01) | 1 | 1 |
| `SPK-latam-supervisora` | LATAM Supervisora | 1 | 1 |
| `SPK-pasajeros-del-vuelo` | Pasajeros del vuelo | 1 | 1 |
| `SPK-passenger-leandro` | Leandro Disconzi | 27 | 27 |
| `SPK-pdi` | PDI | 3 | 3 |
| `SPK-pdi-2` | PDI 2 | 1 | 1 |
| `SPK-pdi-female` | PDI Female | 1 | 1 |
| `SPK-pilot-ruiz` | Latam Pilot Ruiz | 3 | 3 |
| `SPK-stewardess-accuser` | Unknown | 2 | 2 |
| `SPK-unknown-stg-12-speaker-00` | SPEAKER_00 (English speaker) | 1 | 1 |
| `SPK-unknown-stg-29-speaker-00` | SPEAKER_00 | 1 | 1 |
| `SPK-unknown-stg-29-speaker-01` | SPEAKER_01 | 1 | 1 |
| `SPK-unknown-stg-29-speaker-02` | SPEAKER_02 | 1 | 1 |
| `SPK-unknown-stg-8-speaker-02` | Unknown | 1 | 1 |
| `SPK-unknown-stg-8-speaker-03` | Unknown | 1 | 1 |
| `SPK-unknown-stg-8-speaker-04` | Unknown | 1 | 1 |
| `SPK-unknown-stg-8-speaker-05` | Unknown | 1 | 1 |

## Downstream artifacts — regenerated 2026-09-13

All three artifacts were keyed by the pre-consolidation ids. They were rebuilt
from the repaired transcripts, so the reported keys now agree on every id.

| artifact | before | after |
|---|---|---|
| `data/speaker_index.json` | 47 keys, raw ids | **43 keys, all canonical, 85 appearances** |
| `data/speaker_patch.json` | 1474 entries, 9 stale + 2 malformed suggestions | **1474 entries, 0 non-canonical suggestions** |
| `data/speakers/*.md` | 48 files named after raw ids | **43 canonical files + 1 retained orphan, 39 archived** |

### `data/speakers/*.md`

Profiles were classified by provenance before anything was moved:

* **8 hand-curated** (`ingested_utc` / `source_path`, non-empty `key_statements`) —
  7 already carried a canonical filename and were kept as the merge base.
* **40 auto-generated** (`generated_utc`, `key_statements: []`) — 39 were named
  after retired ids and carried nothing hand-written, so archiving them lost no
  content. Their appearances are recomputed from the transcripts on every run.

`scripts/consolidate_speaker_md_files.py` performs the retirement. It moves
files to `data/speakers/.archive/` (git-tracked, never overwritten — collisions
get a `.2` suffix) and refuses to touch a file that carries `key_statements`
unless `--allow-curated` is passed.

Retired: 39 files.

#### `SPK-carabinero-dartnell-female-1.md` — retained deliberately

The one curated profile whose speaker appears in no transcript. It is the only
remaining file with no entry in `speaker_index.json`.

**Decision (2026-09-13): keep as-is.** The profile is hand-curated, carries a
real `key_statements` entry, and its `_provenance` traces it to
`vault-2026-05-20` / `00-case-hub/synthesis/06-SPEAKER-MAP.md` — a vault-era
numbering that is independent of the transcript corpus. Retaining an inert,
curated artifact costs nothing; deleting it would discard sourced content that
may become relevant if the underlying recordings are ever transcribed.

Two facts the next reader should have, because the file itself does not state
them:

1. **The id never existed in the corpus.** `SPK-carabinero-dartnell-female-1`
   appears in neither the 46 raw ids nor `CANONICAL` in `fix_speaker_ids.py`. The
   vault numbered this witness "#1"; the transcripts use
   `SPK-female-carabinero-2` (`#2`) for the female Carabinero they do contain.
   Whether the two are the same person is **not established** and was not
   assumed — that asymmetry in numbering is exactly why no alias was minted.
2. **Its `transcripts_appearing` wikilinks do resolve, but not to this id.**
   `I-002_21/22/23_NAR_CARABINEROS_*` are real transcripts; their participants
   are `SPK-female-carabinero-2`, `SPK-carabinero-constancia`,
   `SPK-carabinero-speaker-00` and `SPK-computer-officer`. So the file's
   `key_statements` quote currently points at transcripts that attribute the
   utterance to a different id. Treat the profile as **unreconciled vault
   material**, not as corroborated corpus evidence.

Revisit if: the recordings behind those three transcripts are re-transcribed
with a distinct "#1" diarization label, or the vault mapping is superseded.
Otherwise leave it. Archiving is a one-liner if that changes:
`python3 scripts/consolidate_speaker_md_files.py --allow-curated`.

### `data/speaker_patch.json`

The patch's `suggested_speaker_id` values come from a hand-authored rule table,
so regenerating alone would have reproduced the old ids. `generate_speaker_patch.py`
now canonicalises every suggestion at emit time and maps two scoped ids that
never existed in any transcript:

| authored suggestion | resolved to | basis |
|---|---|---|
| `SPK-dgac-official-2-angry-one-nar-15-stg-22-dgac-office` | `SPK-dgac-official-2` | the `dgac_official 2` label (space) is a typo of `dgac_official_2`, owned by that participant in `I-002_12`; "angry one" is a free-text descriptor |
| `SPK-dgac-of-nar-15-stg-22-dgac-office` | `NEEDS_HUMAN_REVIEW` | the generic `dgac_official` label in `I-002_12` is contested — participant `SPK-dgac-edgardo-ortiz` already declares it, and no canonical "unattributed DGAC official" bucket exists |

Consequence: 89 entries moved from `confidence: auto` to `review`, leaving
**507 auto / 967 review / 915 needing human review** (was 596 / 878). A
suggestion that cannot be mapped to a canonical id has no business claiming to
be safe to apply.

### Bug found while regenerating

`generate_speaker_md_files.py` emitted `organization: "Unknown"` for all 35
profiles it created. `build_md` used
`index_entry.get("organization") or infer_org(spk_id)`, and the index reports
`"Unknown"` whenever the speaker has no profile yet — a **truthy** placeholder,
so `infer_org` never ran and the placeholder was written to disk. The next run
read it back, making it permanent. `identification_confidence: "unknown"` had
the same problem, which also poisoned the `identification/unknown` tag.

Fixed with `pick_index_value()`, which treats placeholder values as absent
(5 doctests). After regenerating the affected files the organizations are:

| organization | speakers |
|---|---|
| LATAM Airlines | 19 |
| DGAC (Dirección General de Aeronáutica Civil) | 6 |
| Carabineros de Chile | 4 |
| PDI (Policía de Investigaciones de Chile) | 3 |
| Unknown (genuinely unidentified) | 8 |
| ambient / fellow passengers / self (Leandro Disconzi) | 1 each |

Two curated profiles carried non-canonical organization strings and were
normalised to the vocabulary above: `SPK-dgac-don-nicolas` (`DGAC (Chile)` →
`DGAC (Dirección General de Aeronáutica Civil)`) and `SPK-passenger-leandro`
(`passenger-self` → `self (Leandro Disconzi)`).

### Regeneration order

The generators read each other's output, so order matters and two passes are
needed to converge — the index reads display names from the profiles, and the
profiles read appearances from the index:

```
python3 scripts/consolidate_speaker_md_files.py
python3 scripts/generate_speaker_index_v3.py
python3 scripts/generate_speaker_md_files.py
python3 scripts/generate_speaker_index_v3.py   # picks up inferred org / conf
python3 scripts/generate_speaker_md_files.py   # 0 created, 0 updated = converged
python3 scripts/generate_speaker_patch.py
```

Verified after convergence: 43 index keys, canonical id set identical to the
transcript participant set in **both** directions, 85 appearances matching 85
participant records, every key carrying a `md_file`, and a settled run reporting
`0 created / 0 updated / 43 unchanged`.
