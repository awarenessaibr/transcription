# Audio Source Mapping — `data/audio/` → `data/transcripts/`

Authoritative record of which original recording backs each transcript, the
evidence used to establish it, and the provenance/time defects that were
corrected (or are still open).

Status: **verified and applied** on 2026-09-13 by
`transcription/scripts/backfill_audio_metadata.py`.

---

## 1. Why this document exists

Before the backfill, transcript provenance was unreliable. Measured across all
27 transcripts:

- `source_file` was **empty in 20 of 27**, and in 4 more held a non-audio value
  (e.g. `"aeropuerto_STG_23.json"`, `"…11_1788416958.m4a.wav"`).
- `provider` was `""` in 23, `"unknown"` in 3, `"local"` in 1.
- `metadata` was `{}` in **14 of 27**; `file_info` was present in only 10 and
  `audio_properties` in only 9.
- Where `metadata.file_info.file_name` existed it mixed two conventions:
  synthetic slugs (`aeropuerto_STG_5.m4a`, `Terminal_Internacional_T2.m4a`) and
  real on-disk names (`Aeropuerto Arturo Merino Benítez 15.m4a`).
- Time fields disagreed with each other by up to ~7 h.

The original `.m4a` recordings were treated as ground truth, because they carry
their own non-forgeable provenance (`voice-memo-uuid`, `encoder`, embedded
`creation_time`) that the transcripts do not.

---

## 2. Evidence method

Every claim below rests on **two independent exact matches** between a probed
audio file and a stored transcript value:

1. **Duration equality** — `ffprobe format.duration` vs stored
   `metadata.audio_properties.duration`, matched to the millisecond.
2. **Byte-size equality** — actual file size vs stored
   `metadata.file_info.file_size`.

Command used:

```bash
ffprobe -v error \
  -show_entries "format=duration,size,format_name:format_tags:stream=sample_rate,channels" \
  -of json "<file>.m4a"
```

Two checks are stronger than one because the `STG_*` slugs in
`transcript_id` are not authoritative and, in at least two cases, are
internally inconsistent (see §6). A duration match alone can be coincidental;
a duration **and** size match to the exact second and byte cannot.

**Result: 27 of 27 transcripts resolved, with zero conflicts.** Each transcript
also received a distinct `voice-memo-uuid`, which independently confirms that no
two transcripts point at the same recording.

### macOS filename caveat (important for any future tooling)

APFS returns filenames in decomposed Unicode (NFD); the JSON stores them
composed (NFC). A naive dict lookup keyed on the raw `os.listdir()` value
raises `KeyError: 'Aeropuerto Arturo Merino Benítez 28.m4a'`. All joins must
apply `unicodedata.normalize("NFC", ...)` to both sides.

---

## 3. Confirmed mapping (27 rows)

| # | transcript_id | transcript file | recording (data/audio/) | duration | bytes | Hz | voice-memo-uuid |
|---|---|---|---|---|---|---|---|
| 1 | `I-002_01_NAR-01_STG_1_pre_boarding` | `I-002_01_NAR-01_STG_1_pre_boarding.json` | `Aeropuerto Arturo Merino Benítez.m4a` | 00:00:59.733 | 509547 | 48000 | `F943D3A2-0136-4BED-A26B-8D58ABDD09B8` |
| 2 | `I-002_02_NAR-02_STG_2_boarding_gate` | `I-002_02_NAR-02_STG_2_boarding_gate.json` | `Aeropuerto Arturo Merino Benítez 2.m4a` | 00:04:42.688 | 2423926 | 48000 | `A8ADD501-CDDA-430E-AA16-D84438FFE463` |
| 3 | `I-002_03_NAR-05_STG_5_aircraft_removal` | `I-002_03_NAR-05_STG_5_aircraft_removal.json` | `Aeropuerto Arturo Merino Benítez 5.m4a` | 00:03:05.899 | 1597387 | 48000 | `B7E39EC4-2EA0-4255-9574-F836CEF3693D` |
| 4 | `I-002_04_NAR-06_STG_6_jetbridge_standoff` | `I-002_04_NAR-06_STG_6_jetbridge_standoff.json` | `Aeropuerto Arturo Merino Benítez 6.m4a` | 00:39:54.186 | 68673430 | 44100 | `981D09D7-144C-4857-A1BE-FE6D70B3332E` |
| 5 | `I-002_05B_NAR-11_STG_11_waiting_area` | `I-002_05B_NAR-11_STG_11_waiting_area.json` | `Aeropuerto Arturo Merino Benítez 11.m4a` | 00:00:25.088 | 217097 | 48000 | `EF49D012-E4E5-4546-B97C-0846CE3AD1C5` |
| 6 | `I-002_05_NAR-07_STG_7_post_removal_investigation` | `I-002_05_NAR-07_STG_7_post_removal_investigation.json` | `Aeropuerto Arturo Merino Benítez 7.m4a` | 00:21:11.176 | 36431637 | 44100 | `B5761175-D765-4001-A631-79DFEEDFBB08` |
| 7 | `I-002_06_NAR-STG_8_pdi_identity_control` | `I-002_06_NAR-STG_8_pdi_identity_control.json` | `Aeropuerto Arturo Merino Benítez 8.m4a` | 00:09:09.120 | 4667317 | 48000 | `CC153946-63E8-4163-8EFF-EB42C0362778` |
| 8 | `I-002_07_NAR-06_STG_13_post_PDI_corridor` | `I-002_07_NAR-06_STG_13_post_PDI_corridor.json` | `Aeropuerto Arturo Merino Benítez 13.m4a` | 00:15:21.493 | 7787439 | 48000 | `4BC83451-4563-43CE-B38E-4CD793B8C493` |
| 9 | `I-002_08_NAR-09_STG_15_luggage_recovery` | `I-002_08_NAR-09_STG_15_luggage_recovery.json` | `Aeropuerto Arturo Merino Benítez 15.m4a` | 00:09:57.589 | 5079387 | 48000 | `AD9639DA-4464-40DB-8F38-77AF3B1298A7` |
| 10 | `I-002_09_NAR-10_STG_16_counter_confrontation` | `I-002_09_NAR-10_STG_16_counter_confrontation.json` | `Aeropuerto Arturo Merino Benítez 16.m4a` | 00:05:00.437 | 2575731 | 48000 | `A650A927-FCDB-442D-AFE6-AEB0B0BDC4E6` |
| 11 | `I-002_10A_NAR-19_STG_19_counter_escalation` | `I-002_10A_NAR-19_STG_19_counter_escalation.json` | `Aeropuerto Arturo Merino Benítez 19.m4a` | 00:01:59.232 | 1015482 | 48000 | `B496841D-1EA6-4634-821C-75A7654F13BD` |
| 12 | `I-002_10B_NAR-18_STG_18_counter_fragment` | `I-002_10B_NAR-18_STG_18_counter_fragment.json` | `Aeropuerto Arturo Merino Benítez 18.m4a` | 00:00:36.160 | 308420 | 48000 | `793522D6-A533-4F34-AEAF-5C5AE4C61B4B` |
| 13 | `I-002_10_NAR-14_Terminal_Internacional_T2_counter` | `I-002_10_NAR-14_Terminal_Internacional_T2_counter.json` | `Terminal Internacional - T2.m4a` | 00:16:52.344 | 28882488 | 44100 | `18C9A812-0B86-4698-AF56-8129106F603F` |
| 14 | `I-002_11_NAR-13_STG_20_barraza_counter` | `I-002_11_NAR-13_STG_20_barraza_counter.json` | `Aeropuerto Arturo Merino Benítez 20.m4a` | 00:05:17.909 | 2696008 | 48000 | `7E7B9C57-13B0-4B48-BD25-78CFAEE7B639` |
| 15 | `I-002_12_NAR-15_STG_22_DGAC_office` | `I-002_12_NAR-15_STG_22_DGAC_office.json` | `Aeropuerto Arturo Merino Benítez 22.m4a` | 00:09:44.363 | 5021164 | 48000 | `FF61D3CC-36CE-43EC-9E20-B660EDF8B13B` |
| 16 | `I-002_13_NAR-18_STG_26_self_narration` | `I-002_13_NAR-18_STG_26_self_narration.json` | `Aeropuerto Arturo Merino Benítez 26.m4a` | 00:03:58.724 | 6829173 | 44100 | `612AB516-4F69-4BCE-B5D8-48291D3EA20C` |
| 17 | `I-002_14_NAR-16_STG_23_DGAC_don_nicolas` | `I-002_14_NAR-16_STG_23_DGAC_don_nicolas.json` | `Aeropuerto Arturo Merino Benítez 23.m4a` | 00:42:43.989 | 21701500 | 48000 | `3EDCE5D6-F5B1-4D57-B7FF-737E719CA262` |
| 18 | `I-002_15_NAR-19_STG_27_self_narration` | `I-002_15_NAR-19_STG_27_self_narration.json` | `Aeropuerto Arturo Merino Benítez 27.m4a` | 00:00:23.872 | 203401 | 48000 | `3676F583-E2AF-48B3-A35E-3F64C5FBBEB9` |
| 19 | `I-002_16_NAR-20_STG_28` | `I-002_16_NAR-20_STG_28.json` | `Aeropuerto Arturo Merino Benítez 28.m4a` | 00:02:17.601 | 3924899 | 44100 | `44368F57-A92A-4D9D-B829-F0568BC066FD` |
| 20 | `I-002_17_NAR-21_STG_29` | `I-002_17_NAR-21_STG_29.json` | `Aeropuerto Arturo Merino Benítez 29.m4a` | 00:10:36.437 | 5396702 | 48000 | `F45CB84A-1695-4F2D-A72B-810E185D41C3` |
| 21 | `I-002_18_NAR_LATAM_STG_2` | `I-002_18_NAR_LATAM_STG_2.json` | `latam_STG_2.m4a` | 00:02:05.525 | 1047689 | 48000 | `B79069BA-FDA9-4B1B-86FD-E7801820AE9C` |
| 22 | `I-002_19_NAR_LATAM_STG_3` | `I-002_19_NAR_LATAM_STG_3.json` | `latam_STG_3.m4a` | 00:02:39.010 | 4529452 | 44100 | `C8D210DE-D6C8-437A-8592-00A18B06841F` |
| 23 | `I-002_20_NAR_LATAM_STG_4` | `I-002_20_NAR_LATAM_STG_4.json` | `latam_STG_4.m4a` | 00:06:09.024 | 3148162 | 48000 | `06731C2B-FB4C-44FE-9F3E-B381BD06C4DE` |
| 24 | `I-002_21_NAR_CARABINEROS_1` | `I-002_21_NAR_CARABINEROS_1.json` | `Pedro Pablo Dartnell.m4a` | 00:12:28.395 | 6372873 | 48000 | `3B2DBBD7-4A8B-4C88-8732-62E84BF59F67` |
| 25 | `I-002_22_NAR_CARABINEROS_2` | `I-002_22_NAR_CARABINEROS_2.json` | `Pedro Pablo Dartnell 2.m4a` | 00:14:03.349 | 7198313 | 48000 | `8EAB382C-011F-4C6D-87FB-CCFF0DDD4E55` |
| 26 | `I-002_23_NAR_CARABINEROS_3` | `I-002_23_NAR_CARABINEROS_3.json` | `Pedro Pablo Dartnell 3.m4a` | 00:05:14.368 | 2705309 | 48000 | `D7794A43-23FE-4B65-992C-881CF08147EA` |
| 27 | `I-002_24_NAR-19_STG_12` | `I-002_24_NAR-19_STG_12.json` | `Aeropuerto Arturo Merino Benítez 12.m4a` | 00:13:17.845 | 6694419 | 48000 | `88C414BB-C34C-4BA2-A424-C4283C7648DE` |

All recordings are **mono** (`channels: 1`). The on-disk files were copied with
filesystem mtime 2026-08-25 (birth 2026-08-22), which are copy artifacts and
carry no information about recording date.

Note the two intentional out-of-order pairs, both confirmed by stored
`saved_audio_file` hints and by duration/size:

- `I-002_10A_…STG_19` → `19.m4a`, while `I-002_10B_…STG_18` → `18.m4a`
  (the `A`/`B` suffix order is inverted relative to the `STG_` number).
- `I-002_24_…STG_12` → `12.m4a` — the transcript is last in sequence order but
  its recording is the 12th.

---

## 4. Fields written by the backfill

### Top level

| key | value | note |
|---|---|---|
| `source_file` | bare on-disk filename, NFC | e.g. `Aeropuerto Arturo Merino Benítez 6.m4a` |
| `source_path` | repo-relative path | **new key** — `transcription/data/audio/<file>` |
| `provider` | `local` | set on all 27 (overwrites `"unknown"`) |
| `recording_datetime` | the device instant in Chile time | **corrected from the QuickTime tag**, `-04:00` |
| `timestamp` | identical to `recording_datetime` | the two now agree in all 27 |

`source_path` is stored directly after `source_file` (position 3). On the first
pass it had been appended after `segments`, because assigning a new key to a
dict puts it last.

### `metadata`

```jsonc
{
  "audio_properties": {
    "duration": "00:39:54.186",   // now uniformly HH:MM:SS.mmm
    "preferred_volume": "1",      // preserved if present, else "1"
    "sample_rate": 44100,          // int; replaces the mislabelled "track_id"
    "channels": 1
  },
  "file_info": {
    "file_name": "Aeropuerto Arturo Merino Benítez 6.m4a",
    "file_size": 68673430,         // int bytes (was the string "68673430 bytes")
    "file_size_kb": 67063.9,
    "content_type": "audio/mp4",  // constant
    "major_brand": "M4A",         // probed, defaults to "M4A" if ffprobe omits it
    "compatible_brands": ["M4A", "isom", "mp42"],   // omitted when absent
    "encoder": "com.apple.VoiceMemos (iPhone Version 18.5 (Build 22F76))",   // omitted when absent
    "voice_memo_uuid": "981D09D7-144C-4857-A1BE-FE6D70B3332E"
  },
  "ontology_node_id": "",          // "" where absent; real IDs preserved (see below)
  "ontology_schema_version": "2.5",
  "processed_audio_file": "Aeropuerto Arturo Merino Benítez 6.m4a",
  "saved_audio_file": "Aeropuerto Arturo Merino Benítez 6.m4a",
  "timestamps": {
    "QuickTime_Movie_Header_Created": "2024-07-05T21:48:13.000Z",           // preserved, WRONG (see §5)
    "QuickTime_Movie_Header_Created_verified": "2024-07-05T18:47:13.000000Z" // new, true value
  }
}
```

**`ontology_node_id` is never blanked.** Three transcripts already held a real
identifier, and those were preserved rather than overwritten with `""`:

| transcript | `ontology_node_id` |
|---|---|
| `I-002_02_NAR-02_STG_2_boarding_gate` | `TRNS_a51eca2c` |
| `I-002_03_NAR-05_STG_5_aircraft_removal` | `TRNS_7962d91d` |
| `I-002_05_NAR-07_STG_7_post_removal_investigation` | `TRNS_d5bf2f2c` |

The other 24 got `""`. `ontology_schema_version` was bumped to `2.5` on all 27
(three files previously said `2.3.1`).

**`processed_audio_file` values were replaced.** The three files that had one
pointed at `.m4a_processed.wav` artifacts from an older pipeline, e.g.
`"Aeropuerto Arturo Merino Benítez 11_1788416958.m4a_processed.wav"`. Those were
overwritten with the real recording filename per instruction. The old strings are
recoverable from git if that pipeline is ever revisited.

The `metadata` sub-objects are stored in alphabetical key order
(`audio_properties`, `file_info`, `ontology_node_id`, `ontology_schema_version`,
`processed_audio_file`, `saved_audio_file`, `timestamps`) to match the
pre-existing convention.

### Migrations performed

- `audio_properties.track_id` (`"48000"`, `"44100"`, or `""`) → removed;
  replaced by `audio_properties.sample_rate` (int). The old key was mislabelled:
  it held a sample rate, not a track identifier.
- `file_info.file_size` `"68673430 bytes"` → `68673430` (int).
- durations normalized to `HH:MM:SS.mmm` on a single form.
- slug-style and `.wav`-derived `source_file` values replaced with the real
  recording name.

---

## 5. The timezone finding

The ~7 h disagreement between the stored time fields is **two independent
errors**, not one:

**(a) The stored `QuickTime_Movie_Header_Created` is wrong by exactly +3 h.**
In all 9 transcripts that had it, the stored value equals the real file
`creation_time` **plus 3 h 00 m**. This is a bad timezone conversion —
treating Chile as UTC-3 in July 2024. July is Chile Standard Time
(**UTC-4**); DST in Chile runs September→April.

Example (`6.m4a`): stored `2024-07-05T21:48:13.000Z`, real
`2024-07-05T18:47:13.000000Z`.

Per instruction, the **stored value was preserved byte-for-byte** and the true
value recorded in the new sibling key `QuickTime_Movie_Header_Created_verified`.
Nothing was silently overwritten.

**(b) The real file `creation_time` is ~4 h after the stored `recording_datetime`
— and that part is correct.** `recording_datetime` had been written as Chile
local wall-clock with no offset, and the QuickTime tag is true UTC. UTC-4 for
July 2024 is the right gap. So the defect was **drifting values and a missing
offset**, not a systematically shifted instant.

A related trap: five transcripts (`20`, `21`, `22`, `23`, `24`) originally ended
in `Z`, which made their digits look like UTC. They were not — the digits were
local time with the wrong designator. For `20.m4a` the gap to its own tag is
exactly 4 h 00 m 18 s, which settles it. Appending `-04:00` to those was the
correct fix, not a mistake.

### 5.1 Diagnosis (state before the correction)

`recording_datetime + 4 h` should equal the verified QuickTime `creation_time`.
It does to within ~1 minute for 12 transcripts but not for the other 15:

| transcript_id | recording_datetime (before) | QuickTime verified (real, UTC) | delta vs rec+4h |
|---|---|---|---|
| `I-002_01_NAR-01_STG_1_pre_boarding` | `2024-07-05T12:56:00-04:00` | `2024-07-05T16:57:11Z` | +0:01:11 |
| `I-002_02_NAR-02_STG_2_boarding_gate` | `2024-07-05T13:08:00-04:00` | `2024-07-05T17:08:31Z` | +0:00:31 |
| `I-002_03_NAR-05_STG_5_aircraft_removal` | `2024-07-05T13:33:00-04:00` | `2024-07-05T17:30:02Z` | −0:02:58 |
| `I-002_04_NAR-06_STG_6_jetbridge_standoff` | `2024-07-05T14:48:00-04:00` | `2024-07-05T18:47:13Z` | −0:00:47 |
| `I-002_05B_NAR-11_STG_11_waiting_area` | `2024-07-05T15:40:00-04:00` | `2024-07-05T19:44:20Z` | **+0:04:20** |
| `I-002_05_NAR-07_STG_7_post_removal_investigation` | `2024-07-05T15:17:00-04:00` | `2024-07-05T19:16:51Z` | −0:00:09 |
| `I-002_06_NAR-STG_8_pdi_identity_control` | `2024-07-05T15:50:23-04:00` | `2024-07-05T19:19:01Z` | **−0:31:22** |
| `I-002_07_NAR-06_STG_13_post_PDI_corridor` | `2024-07-05T16:01:00-04:00` | `2024-07-05T19:50:40Z` | **−0:10:20** |
| `I-002_08_NAR-09_STG_15_luggage_recovery` | `2024-07-05T16:26:00-04:00` | `2024-07-05T20:26:32Z` | +0:00:32 |
| `I-002_09_NAR-10_STG_16_counter_confrontation` | `2024-07-05T16:47:00-04:00` | `2024-07-05T20:47:09Z` | +0:00:09 |
| `I-002_10A_NAR-19_STG_19_counter_escalation` | `2024-07-05T17:03:00-04:00` | `2024-07-05T21:03:58Z` | +0:00:58 |
| `I-002_10B_NAR-18_STG_18_counter_fragment` | `2024-07-05T17:58:00-04:00` | `2024-07-05T20:57:15Z` | **−1:00:45** |
| `I-002_10_NAR-14_Terminal_Internacional_T2_counter` | `2024-07-05T17:46:00-04:00` | `2024-07-05T21:46:00Z` | 0:00:00 (suspicious, see §6) |
| `I-002_11_NAR-13_STG_20_barraza_counter` | `2024-07-05T18:20:00-04:00` | `2024-07-05T21:46:00Z` | **−0:34:00** |
| `I-002_12_NAR-15_STG_22_DGAC_office` | `2024-07-05T18:49:00-04:00` | `2024-07-05T22:49:39Z` | +0:00:39 |
| `I-002_13_NAR-18_STG_26_self_narration` | `2024-07-05T19:00:00-04:00` | `2024-07-06T01:23:55Z` | **+2:23:55** |
| `I-002_14_NAR-16_STG_23_DGAC_don_nicolas` | `2024-07-05T19:11:00-04:00` | `2024-07-05T23:11:54Z` | +0:00:54 |
| `I-002_15_NAR-19_STG_27_self_narration` | `2024-07-05T19:15:00-04:00` | `2024-07-06T01:26:45Z` | **+2:11:45** |
| `I-002_16_NAR-20_STG_28` | `2024-07-05T19:30:00-04:00` | `2024-07-06T01:39:55Z` | **+2:09:55** |
| `I-002_17_NAR-21_STG_29` | `2024-07-05T19:45:00-04:00` | `2024-07-06T01:51:11Z` | **+2:06:11** |
| `I-002_18_NAR_LATAM_STG_2` | `2024-07-05T22:59:00-04:00` | `2024-07-06T02:59:11Z` | +0:00:11 |
| `I-002_19_NAR_LATAM_STG_3` | `2024-07-05T23:10:00-04:00` | `2024-07-06T03:05:43Z` | −0:04:17 |
| `I-002_20_NAR_LATAM_STG_4` | `2024-07-05T23:20:00-04:00` | `2024-07-06T03:20:18Z` | +0:00:18 |
| `I-002_21_NAR_CARABINEROS_1` | `2024-07-06T07:03:00-04:00` | `2024-07-06T11:03:26Z` | +0:00:26 |
| `I-002_22_NAR_CARABINEROS_2` | `2024-07-06T07:05:00-04:00` | `2024-07-06T11:26:08Z` | **+0:21:08** |
| `I-002_23_NAR_CARABINEROS_3` | `2024-07-06T07:20:00-04:00` | `2024-07-06T11:41:15Z` | **+0:21:15** |

**Interpretation.** 12 transcripts land within ~1 minute, which validates the
`-04:00` model. The other 15 carry `recording_datetime` values that were
hand-adjusted — rounded to the minute and sometimes moved by minutes or hours.
The four consecutive `STG_26/27/28/29` transcripts are all off by a consistent
**~+2:06 to +2:24**, suggesting a different clock. `10B` (−1:00:45), `11`
(−0:34) and `22`/`23` (+0:21) are smaller versions of the same problem.

### 5.2 Resolution applied

Per decision, **26 of 27** transcripts take their `recording_datetime` and
`timestamp` from the file's own QuickTime tag, converted to Chile time. One rule
covers the corpus, so the sub-minute rounding in the 12 "good" files is gone
too, and the `02`/`03` divergence between `recording_datetime` and `timestamp`
(they differed by a few seconds) is resolved — those two were the only files
where `timestamp` already held the tag-derived instant, which shows `timestamp`
was always intended to be the device time.

The single exception is `I-002_11_NAR-13_STG_20_barraza_counter`, whose file tag
is provably a duplicate of another recording's (§6). It keeps its original
`2024-07-05T18:20:00-04:00`; the exception is encoded as a `TIME_OVERRIDES`
entry in the backfill script so it persists across runs.

Notable shifts:

| transcript | before | after | shift |
|---|---|---|---|
| `I-002_13_NAR-18_STG_26_self_narration` | `2024-07-05T19:00:00-04:00` | `2024-07-05T21:23:55-04:00` | +2h23m55s |
| `I-002_15_NAR-19_STG_27_self_narration` | `2024-07-05T19:15:00-04:00` | `2024-07-05T21:26:45-04:00` | +2h11m45s |
| `I-002_16_NAR-20_STG_28` | `2024-07-05T19:30:00-04:00` | `2024-07-05T21:39:55-04:00` | +2h9m55s |
| `I-002_17_NAR-21_STG_29` | `2024-07-05T19:45:00-04:00` | `2024-07-05T21:51:11-04:00` | +2h6m11s |
| `I-002_24_NAR-19_STG_12` | `2024-07-06T09:13:00-04:00` | `2024-07-06T10:13:54-04:00` | +1h0m54s |
| `I-002_10B_NAR-18_STG_18_counter_fragment` | `2024-07-05T17:58:00-04:00` | `2024-07-05T16:57:15-04:00` | −1h0m45s |
| ~~`I-002_11_NAR-13_STG_20_barraza_counter`~~ | `2024-07-05T18:20:00-04:00` | `2024-07-05T18:20:00-04:00` | **0 — reverted** (file tag rejected, §6) |
| `I-002_06_NAR-STG_8_pdi_identity_control` | `2024-07-05T15:50:23-04:00` | `2024-07-05T15:19:01-04:00` | −31m22s |
| `I-002_22_NAR_CARABINEROS_2` | `2024-07-06T07:05:00-04:00` | `2024-07-06T07:26:08-04:00` | +21m8s |
| `I-002_23_NAR_CARABINEROS_3` | `2024-07-06T07:20:00-04:00` | `2024-07-06T07:41:15-04:00` | +21m15s |
| `I-002_07_NAR-06_STG_13_post_PDI_corridor` | `2024-07-05T16:01:00-04:00` | `2024-07-05T15:50:40-04:00` | −10m20s |
| `I-002_05B_NAR-11_STG_11_waiting_area` | `2024-07-05T15:40:00-04:00` | `2024-07-05T15:44:20-04:00` | +4m20s |
| `I-002_19_NAR_LATAM_STG_3` | `2024-07-05T23:10:00-04:00` | `2024-07-05T23:05:43-04:00` | −4m17s |
| `I-002_03_NAR-05_STG_5_aircraft_removal` | `2024-07-05T13:33:00-04:00` | `2024-07-05T13:30:02-04:00` | −2m58s |
| `I-002_01_NAR-01_STG_1_pre_boarding` | `2024-07-05T12:56:00-04:00` | `2024-07-05T12:57:11-04:00` | +1m11s |

The remaining 12 shifted by 9–58 s only. `I-002_10_NAR-14_Terminal_Internacional_T2_counter`
is the sole no-op, because its stored value already matched its tag exactly
(see §6 for why that is not reassuring).

The relative chronological order of the 27 transcripts was preserved — the
shifts are small relative to the gaps between recordings.

**One collision, resolved against the file.** Transcript `11` (`STG_20`,
`20.m4a`) shares its file tag with transcript `10` (T2) — see §6. `10` keeps the
file value; `11` was **reverted** to its original `18:20:00-04:00`. That revert
lives in the script as a documented `TIME_OVERRIDES` entry, so re-running the
backfill does not re-apply the shared tag.

---

## 6. Value defects found in the pre-existing data

Both were corrected by the backfill (values replaced from the files):

| transcript | field | stored (wrong) | real (from file) | delta |
|---|---|---|---|---|
| `I-002_10_NAR-14_Terminal_Internacional_T2_counter` | `duration` | `00:42:44.000` | `00:16:52.344` | **−1551.656 s** |
| `I-002_14_NAR-16_STG_23_DGAC_don_nicolas` | `file_size` | `21699915` | `21701500` | −1585 B |

The `Terminal…T2` duration was **2564 s**, which happens to equal `23.m4a`'s
duration (2563.989 s) — the value was copied from the wrong recording. Its
`file_size` matched correctly (28882488), which is what allowed the mapping to
be confirmed despite the bad duration. So the mapping was right; only the
duration value was wrong.

**Unresolved oddity — a duplicated `creation_time`.**
`Terminal Internacional - T2.m4a` and `Aeropuerto Arturo Merino Benítez 20.m4a`
both report the **identical** tag:

```
creation_time = 2024-07-05T21:46:00.000000Z
```

to the second, and it is a whole minute — the only whole-minute value in the
entire corpus (every other file carries real second/subsecond values). Two
different recordings cannot genuinely have been created at the same instant.
At most one of those tags is native; the other was very likely copied or
rewritten by an export/transcode step. `T2`'s metadata block is already known
to be partly copied from other files (its duration came from `23.m4a`), which
does not help its case.

**Decision: the tag is treated as T2's, and rejected for `20.m4a`.** `T2`
(`I-002_10`) carries `2024-07-05T17:46:00-04:00` because its file really does
say so, and its mapping is confirmed independently by duration and byte size.
`20.m4a` (`I-002_11`, barraza counter) does **not** get the shared tag: its
QuickTime `creation_time` is byte-identical to T2's, which cannot be genuine for
two different recordings, and `T2` is the file whose metadata block is already
known to hold values copied from other recordings (its `duration` came from
`23.m4a`). So the copy is attributed to `20.m4a`, and transcript `11` keeps its
original hand-entered `2024-07-05T18:20:00-04:00` — a plausible 34-minute gap
after the T2 counter incident.

The revert is not silent: `scripts/backfill_audio_metadata.py` carries it as an
explicit `TIME_OVERRIDES` entry with the reasoning inline, so the exception
survives every future run and cannot be mistaken for staleness.

```
  * recording_datetime: '2024-07-05T17:46:00-04:00' -> '2024-07-05T18:20:00-04:00'   (shift +34m)   [manual override, not the file tag]
  * timestamp:          '2024-07-05T17:46:00-04:00' -> '2024-07-05T18:20:00-04:00'   (shift +34m)   [manual override, not the file tag]
```

Caveat: the value is now *unverifiable from the corpus*. It is an assertion of
plausibility, not an observation. Only the original device can settle which file
owns the `21:46:00Z` instant; until then transcript `11` is the only file in the
corpus whose `recording_datetime` deliberately disagrees with its own audio
header, and `metadata.timestamps.QuickTime_Movie_Header_Created_verified` still
records the rejected `21:46:00Z` value for audit.

---

## 7. Recordings not referenced by any transcript (9)

These 9 files exist in `data/audio/` but match no transcript by duration+size.
They are **not** lost evidence — they are simply outside the transcribed corpus.

**Decision: out of scope for now.** They are deliberately left untranscribed, and
the backfill does not touch them.

| recording | duration |
|---|---|
| `Aeropuerto Arturo Merino Benítez 17.m4a` | 00:02:00.939 |
| `Aeropuerto Arturo Merino Benítez 24.m4a` | 00:01:31.881 |
| `Aeropuerto Arturo Merino Benítez 25.m4a` | 00:00:31.296 |
| `Aeropuerto Arturo Merino Benítez 3.m4a` | 00:00:53.525 |
| `Aeropuerto Arturo Merino Benítez 4.m4a` | 00:04:20.245 |
| `Aeropuerto Arturo Merino Benítez 9.m4a` | 00:01:55.093 |
| `GRU-Airport 3.m4a` | 00:00:01.045 |
| `GRU-Airport 4.m4a` | 00:00:03.221 |
| `GRU-Terminal 2.m4a` | 00:10:11.093 |

The three `GRU-*` recordings are a different airport and belong to a different
event (recorded 2024-04-05). The six airport-sequence leftovers would increase
coverage — notably `4.m4a` (4:20) and `17.m4a` (2:00) are long enough to contain
real dialogue — but they are out of scope by decision.

---

## 8. Resolved and remaining questions

### Resolved

| # | question | outcome |
|---|---|---|
| 1 | Which `recording_datetime` values to trust? | 26 derive from the device QuickTime tag; `I-002_11` is a documented exception (§6). |
| 2 | Scope: only the wrong ones, or all? | All 27, one uniform rule. |
| 3 | Preserve the wrong stored QuickTime value? | Yes — kept verbatim, true value in `..._verified`. |
| 4 | `provider: "unknown"` (files 10, 12, 14) | Set to `"local"`; all 27 are now `"local"`. |
| 5 | `saved_audio_file` / `processed_audio_file` | Set to the real recording filename on all 27. |
| 6 | `ontology_schema_version` | `"2.5"` on all 27 (was `2.3.1` on three). |
| 7 | `ontology_node_id` | `""` where absent; three real IDs preserved. |
| 8 | The 9 unreferenced recordings | Out of scope for now. |
| 9 | The duplicate T2 / `20.m4a` tag | T2 keeps the file value; `20.m4a` reverts to `18:20:00` via `TIME_OVERRIDES` (§6). |

### Still open

1. **`Terminal Internacional - T2.m4a` and `20.m4a` share one `creation_time`**
   (§6). The shared tag is now used only for `10` (T2); `11` was reverted to
   `18:20:00-04:00`. The two incidents no longer collide, but the underlying
   question stands: **two headers claim the same instant**, and only a check
   against the original device can say which recording actually owns it.
2. **`I-002_11` (barraza counter) is now the corpus's only unverified time.**
   It was reverted because `18:20:00` is the plausible reading — 34 minutes after
   the T2 counter — but plausibility is not evidence. Its
   `QuickTime_Movie_Header_Created_verified` still says `21:46:00Z`, so a future
   audit will see the disagreement; that is intended, not a leftover bug.
3. **The `STG_26/27/28/29` group moved by ~+2 h.** The shift is now applied, but
   
   *why* the source values were ~2 h early is unexplained. If the originals were
   hand-entered from a paper log, the paper log may contain the same error, and
   anything derived from it — not just `recording_datetime` — would inherit it.
4. **`T2`'s `file_size` is correct but its duration was not.** Two fields from
   the same metadata block disagreed in trustworthiness. Worth spot-checking the
   other 26 for a similar silent copy.
5. **Narrative dependencies on the old times.** `chronological_order`,
   `prior_stage` / `next_stage`, and any prose that cites a clock time were left
   untouched. The shifts are small relative to the gaps between recordings, so
   the ordering survives — but hand-written times inside `segments` prose will
   now disagree with `recording_datetime` by up to ~2 h in the affected files.
6. **`segments[].start` / `.end` offsets are relative to the recording**, so
   they are unaffected by this change. Worth confirming on one `STG_26`
   transcript if you want certainty.

---

## 9. Reproducing

```bash
cd transcription
python3 scripts/backfill_audio_metadata.py --dry-run   # review
python3 scripts/backfill_audio_metadata.py             # apply
```

The script is idempotent: re-running it produces no diff, because every field it
writes already holds either the file-derived value or an explicit
`TIME_OVERRIDES` value. It does still rewrite all 27 files, so its progress
output always says *"would update 27 transcripts"* — that line is **not** a
change signal. Judge idempotency by the diff (`git diff --stat`), or by the
per-field change counters, never by that summary line.
It writes JSON with `json.dumps(data, indent=2, ensure_ascii=False) + "\n"`,
which was verified to round-trip all 27 files byte-for-byte.

Pre-change snapshots are in git (`git show HEAD:transcription/data/transcripts/<file>`).
The backfill itself touched only these top-level keys — `source_file`,
`source_path`, `provider`, `recording_datetime`, `timestamp`, `metadata` — and
left the payload keys (`segments`, `participants`, `speaker_map`, `findings`,
`violations`, `forensic_clusters`, `corrections`, `classification`, `tags`,
`case_id`, …) **value-identical**. Two things do change beyond values:

- **Key order.** `source_path` is inserted as the third top-level key, and
  `metadata`'s sub-keys are sorted into a fixed order. Order carries no meaning
  here, but it does mean the file is not a pure value diff.
- **`metadata.timestamps` grows one key.** `QuickTime_Movie_Header_Created_verified`
  is added. All pre-existing `timestamps` entries were preserved verbatim,
  including `QuickTime_Movie_Header_Created` even where it is provably +3 h
  wrong.

Everything else was confirmed by a strict before/after key-and-value diff against
a snapshot of the 27 files taken immediately before the run: **0 unexpected
changes**, and `stored QuickTime_Movie_Header_Created unchanged: 27/27`.

> **Note on `data/transcripts/bak/`** — that directory holds 27 files dated
> 2024-09-12 21:29 that **predate both backfill passes** and still use the older
> filename convention. Do not treat it as the pre-backfill snapshot; use git.

### Verifying the result

```bash
cd transcription
python3 scripts/backfill_audio_metadata.py --dry-run   # expect no diff
```

A correct post-repair run leaves the corpus byte-identical. Confirm with
`git diff --stat transcription/data/transcripts` (expect no output) rather than
the script's own "would update N" line, which always reports all 27 files.

Then confirm the invariants:

| check | expected |
|---|---|
| `metadata.ontology_node_id` key present | 27/27 |
| `metadata.ontology_schema_version == "2.5"` | 27/27 |
| `metadata.processed_audio_file == source_file` | 27/27 |
| `metadata.saved_audio_file == source_file` | 27/27 |
| `provider == "local"` | 27/27 |
| `recording_datetime == local(QuickTime_verified)` | 26/27 |
| `recording_datetime == TIME_OVERRIDES[id]` | 1/27 (`I-002_11`, §6) |
| `metadata.timestamps.QuickTime_Movie_Header_Created_verified` present | 27/27 |
| `timestamp == recording_datetime` | 27/27 |
| real `TRNS_*` ontology ids preserved | 3 (`02`, `03`, `05`) |

Cumulative diff against the pre-backfill commit:

```
27 files changed, 863 insertions(+), 234 deletions(-)
```
