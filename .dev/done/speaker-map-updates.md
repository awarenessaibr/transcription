I reviewed the current transcript files against the earlier `unmapped_speakers` array. Important: that earlier list is partly stale. In several transcripts, the old labels (`SPEAKER_00`, `Pasajero 2`, `PDI-Felipe`, etc.) no longer exist. They were replaced by normalized generic labels such as `airline_staff`, `dgac_official`, `pdi_official`, `multi_party_audio`, `background_audio`, `unresolved_speaker`, `other_passenger`, etc.

Below are the **exact current segments that still need speaker mapping**, grouped by current transcript file. Where the old unmapped label still exists under a different name, I note the equivalent.

## 1. Exact remaining unmapped segments by file

### `I-002_02_NAR-02_STG_2_boarding_gate`
Old: `json_aeropuerto_arturo_merino_benitez_2`, segment `NEW_SPEAKER`

- **Index 17** — current speaker: `unresolved_speaker`  
  Text: `"Estamos bien en la hora del embarque,"`  
  Likely mapping: LATAM Gate Staff / `SPK-latam-gate-staff-nar-02...` or `SPK-latam-gate-staff-2...`

Other current generic unmapped labels in this file:
- `airline_staff` — indices: `1, 3, 5, 8, 10, 12, 14, 16, 18, 20, 22, 25, 26, 28, 34, 36, 38, 40, 42, 45, 46, 48, 49, 51, 53, 55, 57, 59`
- `unresolved_speaker` — index: `17`

---

### `I-002_04_NAR-06_STG_6_jetbridge_standoff`
Old: `json_aeropuerto_arturo_merino_benitez_6`

None of the old exact labels remain:  
`Pasajera 3`, `Pasajero 5`, `SPEAKER_00`, `DGAC - Edgardo Ortiz`, `Pasajero 4`, `NEW_SPEAKER`, `Pasajero 2`, `Pasajera 2`, `SPEAKER_02`, `witness questioning narrative changes`, `DGAC & PDI`, `Pasajera 6`, `Pasajera 1`, `DGAC - Officer`.

They are now represented by:
- `other_passenger`
- `dgac_official`
- `pdi_official`
- `multi_party_audio`
- `background_audio`
- `unresolved_speaker`

The main still-unmapped generic labels are `multi_party_audio`, `background_audio`, and `unresolved_speaker`. These occur at many indices and need a manual pass.

---

### `I-002_05_NAR-07_STG_7_post_removal_investigation`
Old: `json_aeropuerto_arturo_merino_benitez_7`

None of the old exact labels remain:  
`New Person / Latam BOSS?`, `PDI & DGAC Oficials?`, `PDI-Felipe?`, `PDI/DGAC?`, `DGAC - Of`, `Another person? Acuser?`, `PDI/DGAC/LATAM_BOSS/ACCUSER - TIPS`, `PDI Instructing LATAM BOSS`, `Latam Staff Accuser`, `PDI/Latam BOSS`, `Latam BOSS or Staff (ACUSER)`, `DGAC/PDI`, `Pdi/Latam`, `PDI-Felipe`.

Current file uses normalized labels: `dgac_official`, `pdi_official`, `airline_staff`, `multi_party_audio`, `unresolved_speaker`, etc. These need mapping.

---

### `I-002_06_NAR-STG_8_pdi_identity_control`
Old: `json_aeropuerto_arturo_merino_benitez_8`

Old exact labels not present in current segments:  
`SPEAKER_02`, `SPEAKER_03`, `SPEAKER_04`, `SPEAKER_05`, `PDI-Female`.

Current generic unmapped labels:
- `multi_party_audio`
- `background_audio`
- `unresolved_speaker`

These need a separate index extraction if you want every occurrence.

---

### `I-002_08_NAR-09_STG_15_luggage_recovery`
Old: `json_aeropuerto_arturo_merino_benitez_15`, segment `SPEAKER_00`

No `SPEAKER_00` label remains. The equivalent unresolved/silence segments are:

- **Indices:** `22, 29, 34, 39, 41, 44, 48, 60, 62, 80, 86`
- Current speaker: `unresolved_speaker`
- Most are `[silencio]` or empty; index 39 has note about laughing.

---

### `I-002_13_NAR-18_STG_26_self_narration`
Old: `json_aeropuerto_arturo_merino_benitez_26`, segment `Latam Supervisor`

Current equivalent label: `airline_supervisor`

Exact segments:
- **Index 1** — `airline_supervisor` — `"Yo Creo que ya hablaron con usted, señor."`
- **Index 4** — `airline_supervisor` — `"sí, pero lo que pasa es que no. Usted para poder viajar tendría que firmar otra carta. Pero no puede.."`
- **Index 6** — `airline_supervisor` — `"para poder viajar, pero en este caso no puede tiene que esperar para comprar otro ticket.."`
- **Index 8** — `airline_supervisor` — `"si si, lo entiendo."`
- **Index 10** — `airline_supervisor` — `"no es necesario."`
- **Index 12** — `airline_supervisor` — `"Por que lo viran las cameras."`
- **Index 14** — `airline_supervisor` — `"sí, que lo sacaron del avión, me dicen."`
- **Index 17** — `airline_supervisor` — `"Posso llamar la seguridad denovo para que hable con ellos, ¿bueno?"`
- **Index 19** — `airline_supervisor` — `"Ya! ya lo voy a llamar, bueno?"`
- **Index 21** — `airline_supervisor` — `"si"`

Likely mapping: Diego / `SPK-diego-latam-supervisor` or a separate LATAM supervisor key.

---

### `I-002_15_NAR-19_STG_27_self_narration`
Old: `json_aeropuerto_arturo_merino_benitez_27`, segment `latam supervisor (Diego)`

Current equivalent label: `airline_supervisor`

Exact segments:
- **Index 0** — `airline_supervisor` — `"esta ... un documento de que queria ustedes"`
- **Index 2** — `airline_supervisor` — `"Ya."`

Likely mapping: `SPK-diego-latam-supervisor`.

---

### `I-002_16_NAR-20_STG_28`
Old: `json_aeropuerto_arturo_merino_benitez_28`

Old labels:
- `Latam Supervisor (Diego)`
- `other passengers`
- `leandro Disconzi (passenger)`

Current equivalents:
- `Latam Supervisor (Diego)` → `airline_supervisor`  
  Exact indices: `0, 1, 3, 5, 8, 10, 11, 16, 18, 20`
- `other passengers` → `other_passenger`  
  Exact index: `23`
- `leandro Disconzi (passenger)` → `passenger`  
  All `passenger` segments. Already mapped to Leandro.

Also unresolved:
- `unresolved_speaker` — indices `13, 14` (`[silencio]`)

---

### `I-002_17_NAR-21_STG_29`
Old: `json_aeropuerto_arturo_merino_benitez_29`, segments `SPEAKER_02`, `SPEAKER_00`, `SPEAKER_01`

No segments currently use `SPEAKER_00`, `SPEAKER_01`, or `SPEAKER_02`. They appear only as participant placeholders. The actual current unmapped segment labels are:

- `NEW_SPEAKER` — index `9`
- `airline_staff_antonella` — indices `7, 10, 19`
- `airline_staff_3` — indices `12, 22`
- `airline_staff_4` — indices `18, 20, 21`
- `airline_staff_5` — indices `52, 71`

These need mapping.

---

### `I-002_19_NAR_LATAM_STG_3`
Old: segment `unknown_role`

Current equivalent label: `airline_staff_antonella`

Exact segments:
- **Index 6** — `airline_staff_antonella` — `"Usted esta agravando la situacion...todo se vas a ver la area legal"`
- **Index 8** — `airline_staff_antonella` — `"?? ..ninguna pregunta suya. Esta es su carta."`

Likely mapping: `SPK-antonela-latam-agent`.

---

### `I-002_24_NAR-19_STG_12`
Old: `json_aeropuerto_arturo_merino_benitez_12`, participant/segment `SPEAKER_00` (English speaker)

No segment uses `SPEAKER_00` directly. Equivalent current segments:
- **Index 276** — `unresolved_speaker` — `"Thank"`
- **Index 277** — `unresolved_speaker` — `"you."`

Likely mapping: `SPEAKER_00 (English speaker)` or a LATAM/airport staff key.

---

## 2. Old unmapped entries that are no longer present in the current files

These old labels were not found as segment speakers in the provided current transcripts:

- `json_aeropuerto_arturo_merino_benitez_6` — all old passenger/DGAC/PDI labels are gone; replaced by generic labels.
- `json_aeropuerto_arturo_merino_benitez_7` — all old PDI/DGAC/LATAM BOSS/ACCUSER labels are gone; replaced by generic labels.
- `json_aeropuerto_arturo_merino_benitez_8` — `SPEAKER_02/03/04/05`, `PDI-Female` are not segment speakers anymore.
- `json_aeropuerto_arturo_merino_benitez_22` — `SPEAKER_01`, `SPEAKER_02` are not segment speakers in `I-002_12`.
- `json_aeropuerto_arturo_merino_benitez_23` — `SPEAKER_00` is not a segment speaker in `I-002_14`.
- `csv_aeropuerto_arturo_merino_benitez_13` — this file was **not provided** in the current batch, so I cannot locate its exact segment indices.

---

## 3. Bottom line for finishing the mapping

To finish cleanly, you need to resolve these **current generic labels**:

| File | Current unmapped/generic labels to resolve |
|---|---|
| `I-002_02` | `airline_staff`, `unresolved_speaker` |
| `I-002_04` | `multi_party_audio`, `background_audio`, `unresolved_speaker`, `other_passenger` |
| `I-002_05` | `multi_party_audio`, `unresolved_speaker`, `airline_staff`, `dgac_official`, `pdi_official` |
| `I-002_06` | `multi_party_audio`, `background_audio`, `unresolved_speaker` |
| `I-002_08` | `unresolved_speaker` at `22,29,34,39,41,44,48,60,62,80,86` |
| `I-002_13` | `airline_supervisor` at `1,4,6,8,10,12,14,17,19,21` |
| `I-002_15` | `airline_supervisor` at `0,2` |
| `I-002_16` | `airline_supervisor` at `0,1,3,5,8,10,11,16,18,20`; `other_passenger` at `23`; `unresolved_speaker` at `13,14` |
| `I-002_17` | `NEW_SPEAKER` at `9`; `airline_staff_antonella` at `7,10,19`; `airline_staff_3` at `12,22`; `airline_staff_4` at `18,20,21`; `airline_staff_5` at `52,71` |
| `I-002_19` | `airline_staff_antonella` at `6,8` |
| `I-002_24` | `unresolved_speaker` at `276,277` |



Here is the comprehensive index list of every segment whose `speaker` value is **not** already mapped to a canonical `SPK-...` key in `mapped_speakers`. I've organized it by transcript file, with the exact segment index, the current generic speaker label, a short text snippet, and a suggested canonical key. Files with no unmapped segments are omitted.

## `I-002_02_NAR-02_STG_2_boarding_gate`

| Index | Current label | Text snippet | Suggested key |
|---|---|---|---|
| 1 | airline_staff | ¿para embarcar? | SPK-latam-gate-staff-nar-02-stg-2-boarding-gate |
| 3 | airline_staff | es su presentación | SPK-latam-gate-staff-acuser |
| 5 | airline_staff | en uns minutos si | SPK-latam-gate-staff-acuser |
| 8 | airline_staff | de llegar acá | SPK-latam-gate-staff-acuser |
| 10 | airline_staff | aham | SPK-latam-gate-staff-acuser |
| 12 | airline_staff | ah, ok. | SPK-latam-gate-staff-acuser |
| 14 | airline_staff | si | SPK-latam-gate-staff-acuser |
| 16 | airline_staff | No | SPK-latam-gate-staff-acuser |
| 17 | unresolved_speaker | Estamos bien en la hora del embarque, | SPK-latam-gate-staff-2-nar-02-stg-2-boarding-gate |
| 18 | airline_staff | nosotros comenzamos el embarco 40 minutos antes | SPK-latam-gate-staff-acuser |
| 20 | airline_staff | La hora de apresentacion | SPK-latam-gate-staff-acuser |
| 22 | airline_staff | Esa es la hora de presentación. | SPK-latam-gate-staff-acuser |
| 25 | airline_staff | No, esa es la hora de presentación. | SPK-latam-gate-staff-acuser |
| 26 | airline_staff | la hora del embarque es otra. | SPK-latam-gate-staff-acuser |
| 28 | airline_staff | Ahí nos sale la hora del embarque... | SPK-latam-gate-staff-acuser |
| 34 | airline_staff | Mira, en este minuto nosotros vamos a empezar el embarco | SPK-latam-gate-staff-acuser |
| 36 | airline_staff | exacto | SPK-latam-gate-staff-acuser |
| 38 | airline_staff | Eso sale cuando usted compra el pasaje... | SPK-latam-gate-staff-acuser |
| 40 | airline_staff | Por que esa es la hora de presentación. | SPK-latam-gate-staff-acuser |
| 42 | airline_staff | presentación. Esa es la hora de presentación | SPK-latam-gate-staff-acuser |
| 45 | airline_staff | aham | SPK-latam-gate-staff-acuser |
| 46 | airline_staff | Ae si, | SPK-latam-gate-staff-acuser |
| 48 | airline_staff | laughs | SPK-latam-gate-staff-acuser |
| 49 | airline_staff | Claro, Es el | SPK-latam-gate-staff-acuser |
| 51 | airline_staff | ya, ahora ya van a embarcar. | SPK-latam-gate-staff-acuser |
| 53 | airline_staff | tienen otro tiempo | SPK-latam-gate-staff-2-nar-02-stg-2-boarding-gate |
| 55 | airline_staff | Ellos tienen otro tiempos al que les sale acá... | SPK-latam-gate-staff-2-nar-02-stg-2-boarding-gate |
| 57 | airline_staff | Claro! A veces tienen que esperar... | SPK-latam-gate-staff-2-nar-02-stg-2-boarding-gate |
| 59 | airline_staff | Ah no po, no esta correcto. | SPK-latam-gate-staff-2-nar-02-stg-2-boarding-gate |

Also: `airline_staff` at indices 5, 8, 10, 12, 14, 16, 18, 20, 22, 25, 26, 28, 34, 36, 38, 40, 42, 45, 46, 48, 49, 51 — all need review to split between **Acuser** and **Staff 2**.

## `I-002_03_NAR-05_STG_5_aircraft_removal`

| Index | Current label | Text snippet | Suggested key |
|---|---|---|---|
| 1 | airline_cabin_crew | Tiene que salir del avión, tiene que bajar | SPK-stewardess-accuser |
| 5 | airline_cabin_crew | Por qué fue agresivo y | SPK-stewardess-accuser |
| 8 | airline_cabin_crew | Tiene que salir. Estaba mi compañero... | SPK-stewardess-accuser |
| 10 | airline_cabin_crew | Oye, el pasajero no se quiere mover... | SPK-stewardess-accuser |
| 11 | airline_cabin_crew | Ya activamos seguridad. Igual va a tener que bajar | SPK-stewardess-accuser |
| 13 | airline_cabin_crew | Usted empezó desde un comienzo... | SPK-stewardess-accuser |
| 15 | airline_cabin_crew | Pero... | SPK-stewardess-accuser |
| 17 | airline_cabin_crew | Usted no tiene el derecho de tocar a mi compañero... | SPK-stewardess-accuser |
| 19 | airline_cabin_crew | No fue así. | SPK-stewardess-accuser |
| 21 | airline_cabin_crew | Tiene que bajar. | SPK-stewardess-accuser |
| 23 | airline_cabin_crew | Podemos pedir las cámaras del aeropuerto. | SPK-stewardess-accuser |
| 25 | airline_cabin_crew | Vai ter que bajar. | SPK-stewardess-accuser |
| 27 | airline_cabin_crew | el pasajero no quiere bajar... | SPK-stewardess-accuser |

## `I-002_04_NAR-06_STG_6_jetbridge_standoff`

This file is the largest. Unmapped labels: `airline_cabin_crew`, `airline_security_official`, `airline_pilot`, `dgac_official`, `pdi_official`, `other_passenger`, `multi_party_audio`, `background_audio`, `unresolved_speaker`.

**`airline_cabin_crew`** → `SPK-stewardess-accuser` (indices: 0, 2, 4, 6, 8, 10, 15, 20, 22, 23, 24, 26, 28)

**`airline_security_official`** → `SPK-joaquin-barraza-latam-security` (indices: 33, 35, 37, 39, 41, 48, 50, 52, 54, 55, 57, 60, 64, 67, 70, 123, 125, 131, 133)

**`airline_pilot`** → `SPK-pilot-ruiz` (indices: 68, 69, 71, 73)

**`dgac_official`** → varies; most are DGAC Officer — need split between DGAC Officer 1 (main), DGAC Officer 2, and Don Nicolas/Edgardo. Indices: 75, 76, 78, 79, 80, 83, 84, 86, 88, 90, 92, 93, 95, 99, 101, 103, 105, 107, 109, 116, 120, 135, 137, 140, 142, 149, 150, 151, 154, 156, 159, 164, 165, 176, 177, 180, 182, 183, 184, 188, 192, 193, 196, 198, 200, 202, 204, 206, 207, 209, 211, 213, 223, 226, 228, 230, 232, 233, 234, 239, 241, 243, 244, 246, 249, 252, 257, 265, 270, 274, 277, 282, 283, 284, 285, 287, 289, 292, 294, 297, 299, 301, 302, 303, 305, 306, 308, 311, 313, 315, 316, 318, 320, 323, 327, 332, 340, 342, 344, 347, 348, 349, 351, 352, 353, 354, 356.

**`pdi_official`** → `SPK-pdi-nar-06-stg-6-jetbridge-standoff` or a specific PDI officer. Indices: 257, 349, 353, 361, 363, 365, 367, 369, 371, 373, 377, 382, 384, 387, 389, 391, 393, 395, 398, 400, 403, 405, 408, 410, 412, 414, 416, 417.

**`other_passenger`** → `SPK-pasajeros-del-vuelo-nar-06-stg-6-jetbridge-standoff`. Indices: 134, 143, 163, 166, 167, 168, 170, 171, 173, 175, 178, 179, 181, 185, 187, 189, 191, 194, 248, 249, 251, 252, 253.

**`multi_party_audio`** → needs manual split. Indices: 260, 263, 265, 270, 274, 277, 283, 284, 285, 287, 289, 292, 294, 295, 296, 297, 301, 302, 303, 305, 306, 308, 311, 313, 315, 316, 318, 320, 323, 327, 329, 332, 335, 336, 340, 342, 344, 347, 348, 349, 351, 352, 353, 354, 356.

**`background_audio`** → background. Indices: 282, 309.

**`unresolved_speaker`** → unknown. Indices: 30, 31, 172, 174.

**`passenger`** — already mapped to `SPK-passenger-leandro`.

## `I-002_05_NAR-07_STG_7_post_removal_investigation`

Unmapped labels: `dgac_official`, `pdi_official`, `airline_staff`, `multi_party_audio`, `unresolved_speaker`.

**`dgac_official`** → `SPK-dgac-nar-07-stg-7-post-removal-investigation`. Indices: 4, 5, 7, 8, 9, 10, 12, 13, 16, 18, 19, 29, 32, 33, 34, 36, 71, 74, 75, 76, 77, 78, 79, 81, 82.

**`pdi_official`** → `SPK-pdi-nar-07-stg-7-post-removal-investigation`. Indices: 39, 40, 51, 52, 53, 54, 55, 57, 58, 61, 62, 64, 68, 73, 94, 96, 98, 100, 101, 102, 103, 105, 115, 118, 119, 121, 122, 123, 124, 125, 126, 129, 131, 132, 133, 134, 136, 137, 139, 141, 142, 143, 144, 145, 146, 148, 149, 152, 155, 156, 157, 159, 161, 163, 165, 167, 169, 171, 173, 176, 179, 180, 182.

**`airline_staff`** → likely `SPK-latam-staff-acuser-nar-07...` or `SPK-latam-boss-nar-07...`. Indices: 38, 45, 56, 59, 60, 63, 65, 66, 69.

**`multi_party_audio`** → needs split. Indices: 30, 37, 41, 42, 43, 44, 46, 47, 48, 49, 50, 58, 62, 69, 70, 71, 72, 82.

**`unresolved_speaker`** → unknown. Index: 70.

## `I-002_06_NAR-STG_8_pdi_identity_control`

Unmapped labels: `multi_party_audio`, `background_audio`, `unresolved_speaker`, `airline_security_official`, `dgac_official`, `pdi_official`, `pdi_official` (multiple), `passenger` (mapped).

**`airline_security_official`** → likely `SPK-joaquin-barraza-latam-security`. Index: 0.

**`dgac_official`** → DGAC. Index: 3.

**`pdi_official`** → PDI. Indices: 1, 2, 5, 13, 14, 17, 18, 38, 40, 42, 43, 45, 46, 62, 63, 64, 76, 77, 79, 89, 90, 92, 93, 101, 102.

**`multi_party_audio`** → needs split. Indices: 6, 21, 22, 23, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 39, 41, 44, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 78, 80, 81, 82, 83, 84, 85, 91, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126.

**`background_audio`** → background. Indices: 86, 87, 88, 99, 100.

**`unresolved_speaker`** → unknown. Indices: 7, 8, 9, 10, 11, 12, 82, 126.

## `I-002_08_NAR-09_STG_15_luggage_recovery`

Unmapped labels: `unresolved_speaker` mostly.

**`unresolved_speaker`** → likely Dominika or passenger. Indices: 22, 29, 34, 39, 41, 44, 48, 60, 62, 80, 86.

Note: this file uses `airline_luggage_staff` label (which should map to `SPK-latam-luggage-supervisor-dominika...`).

## `I-002_09_NAR-10_STG_16_counter_confrontation`

Unmapped labels: `background_audio`.

**`background_audio`** → `SPK-background-nar-10-stg-16-counter-confrontation`. Indices: 1, 2.

## `I-002_10_NAR-14_Terminal_Internacional_T2_counter`

Unmapped labels: `dgac_official`, `airline_staff`, `airline_staff 2`, `passenger` (mapped).

**`dgac_official`** → `SPK-dgac-don-nicolas`. Indices: 0, 1, 3, 5, 7, 9, 10, 12, 16, 18, 20, 22, 24, 26.

**`airline_staff`** → LATAM Counter Staff. Indices: 37, 39, 44, 45, 51, 52, 53, 55, 58, 60, 62, 65, 67, 68, 70, 71, 75, 77, 78, 80, 81, 83, 84, 86, 88, 92, 94, 96, 97, 100, 101, 104, 106, 108, 110, 112, 114, 118, 120, 121, 123, 124, 125, 129, 131, 132, 133, 134, 135, 137, 140, 142, 144, 146, 149, 150, 151, 153, 155, 157, 158, 159, 161, 163, 165, 168, 169, 170, 172, 173, 180.

**`airline_staff 2`** → LATAM Counter Staff (Male 2). Indices: 101, 148.

## `I-002_10A_NAR-19_STG_19_counter_escalation`

Unmapped labels: `dgac_official` — mostly `SPK-dgac-don-nicolas`. Indices: 0, 7, 11, 12, 14, 15, 16, 18.

## `I-002_11_NAR-13_STG_20_barraza_counter`

Unmapped labels: `airline_staff`, `airline_security_official`.

**`airline_staff`** → likely LATAM counter staff. Indices: 0, 2, 4, 10, 13.

**`airline_security_official`** → `SPK-joaquin-barraza-latam-security`. Indices: 1, 16, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 42, 44, 46, 49, 51, 55, 62, 64, 66, 68, 70, 72, 74.

## `I-002_12_NAR-15_STG_22_DGAC_office`

Unmapped labels: `dgac_official`, `dgac_official 2`, `dgac_official 3`, `dgac_EDGARDO`, `passenger`.

**`dgac_official`** → `SPK-dgac-official-1-nar-15-stg-22-dgac-office`. Indices: 0, 3, 6, 8, 9, 10, 12, 13, 15, 17, 18, 20, 22, 24, 26, 29, 31, 32, 33, 34, 36, 38, 39, 41, 43, 47, 48, 50, 52, 54, 55, 57, 58, 60, 61, 62, 66, 68, 70, 72, 73, 75, 76, 78, 80, 82, 84, 86, 87, 88, 90, 91, 92, 93, 94, 96, 97, 98, 99, 101, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 117, 118, 119, 120, 121, 122, 123, 124, 125, 127, 128, 129, 130, 131, 132, 133.

**`dgac_official 2`** → `SPK-dgac-official-2-angry-one-nar-15-stg-22-dgac-office`. Index: 121.

**`dgac_official 3`** → unknown DGAC Official 3. Indices: 137, 138, 210, 213.

**`dgac_EDGARDO`** → `SPK-dgac-edgardo-ortiz`. Indices: 136, 167, 169, 211, 220, 221, 222, 223, 227, 230, 232, 235, 238, 239, 242, 243, 245, 247.

**`dgac_official_don_nicolas`** → `SPK-dgac-don-nicolas`. Indices: 248, 250, 252, 254, 256, 257, 259, 261, 262, 264, 266, 267, 270, 273, 275, 276, 278, 281, 283, 284, 286, 287, 289, 291, 293, 294, 296, 298, 301, 305, 307, 309.

## `I-002_13_NAR-18_STG_26_self_narration`

`airline_supervisor` at indices: 1, 4, 6, 8, 10, 12, 14, 17, 19, 21. Likely Diego / `SPK-diego-latam-supervisor`.

## `I-002_14_NAR-16_STG_23_DGAC_don_nicolas`

Unmapped labels: `dgac_edgardo_ortiz`, `DGAC_higher_official_Nicolas`, `dgac_official`, `dgac_official 2`, `dgac_official 3`, `dgac_EDGARDO`, `dgac_official_don_nicolas`, `latam_staff_random`, `passenger`.

**`dgac_edgardo_ortiz`** → `SPK-dgac-edgardo-ortiz`. Indices: 0, 2, 5, 9, 10, 12, 17, 19, 21, 22, 24, 26, 27, 29, 30, 31, 35, 36, 38, 39, 41, 42, 44.

**`DGAC_higher_official_Nicolas`** → `SPK-dgac-don-nicolas`. Indices: 45, 47, 48, 49, 51, 57, 63, 65, 67, 69, 71, 72, 73, 74, 75.

**`dgac_official`** → DGAC Officer 1. Indices: 59, 61, 62, 77, 79, 80, 81, 87, 95, 96, 97, 99, 101, 103, 105, 106, 108, 109, 111, 113, 114, 115, 117, 119, 121, 122, 123, 124, 125, 127, 129, 130, 131, 133, 134, 135, 139, 143, 144, 151, 153, 154, 155, 156, 157, 159, 160, 162, 163, 164, 165, 167, 168, 169, 170, 171, 174, 175, 177, 179, 180, 181, 182, 183, 184, 185, 187, 189, 192, 193, 194, 195, 196, 197, 199, 201, 202.

**`dgac_official 2`** → `SPK-dgac-official-2-angry-one-nar-15-stg-22-dgac-office`. Index: 121.

**`dgac_official 3`** → DGAC Official 3. Indices: 137, 138, 210, 213.

**`dgac_EDGARDO`** → `SPK-dgac-edgardo-ortiz`. Indices: 136, 167, 169, 211, 220, 221, 222, 223, 227, 230, 232, 235, 238, 239, 242, 243, 245, 247.

**`dgac_official_don_nicolas`** → `SPK-dgac-don-nicolas`. Indices: 248, 250, 252, 254, 256, 257, 259, 261, 262, 264, 266, 267, 270, 273, 275, 276, 278, 281, 283, 284, 286, 287, 289, 291, 293, 294, 296, 298, 301, 305, 307, 309.

**`latam_staff_random`** → unknown LATAM staff. Indices: 314, 318, 321, 325, 328, 333, 335, 337, 338, 340, 343, 348, 350, 352, 354, 357, 359, 366, 367, 370, 371, 374.

## `I-002_16_NAR-20_STG_28`

`airline_supervisor` at indices: 0, 1, 3, 5, 8, 10, 11, 16, 18, 20. Likely `SPK-diego-latam-supervisor` or a different LATAM supervisor.

`other_passenger` at index: 23.

`unresolved_speaker` at indices: 13, 14.

## `I-002_17_NAR-21_STG_29`

**`NEW_SPEAKER`** at index: 9.

**`airline_staff_antonella`** → `SPK-antonela-latam-agent`. Indices: 7, 10, 19.

**`airline_staff_3`** → unknown LATAM Staff 3. Indices: 12, 22.

**`airline_staff_4`** → unknown LATAM Staff 4. Indices: 18, 20, 21.

**`airline_staff_5`** → unknown LATAM Staff 5. Indices: 52, 71.

## `I-002_19_NAR_LATAM_STG_3`

`airline_staff_antonella` → `SPK-antonela-latam-agent`. Indices: 6, 8.

## `I-002_20_NAR_LATAM_STG_4`

**`airline_supervisor_antonella`** → `SPK-antonela-latam-agent`. Indices: 3, 10, 16, 17, 22, 25, 29, 30, 33, 35, 37, 42, 47, 49, 50, 52, 54, 57, 59, 61, 62, 75, 78, 80, 82, 84, 85, 88, 90, 99, 102, 104, 106, 108, 110, 114, 116, 118, 121, 123, 125, 127, 129, 131, 133, 135, 137, 139, 140.

**`airline_staff_5`** → unknown LATAM Staff 5. Indices: 4, 43, 46.

**`airline_staff`** → LATAM Staff. Indices: 6, 8.

## `I-002_21_NAR_CARABINEROS_1`

**`carabinero_official`** → `SPK-female-carabinero-2-nar-carabineros-1` or `SPK-carabinero-constancia-nar-carabineros-1`. Indices: 0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 37, 38, 40, 52, 53, 73, 75, 99, 122, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 141, 143, 145, 148, 150, 155, 156, 157, 159, 160, 161.

Note: this file also uses `passenger` (mapped).

## `I-002_22_NAR_CARABINEROS_2`

**`carabinero_official`** → `SPK-female-carabinero-2-nar-carabineros-2` or `SPK-computer-officer`. Indices: 0, 1, 3, 4, 6, 8, 10, 12, 13, 14, 23, 34, 36, 37, 42, 47, 49, 51, 54, 57, 59, 61, 62, 67, 68, 70, 72, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 99, 100, 101, 102, 103, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 190, 191, 192, 193, 194, 195, 196, 197, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220, 221, 222, 223, 224, 225.

Note: this file is mostly `carabinero_official` — need to distinguish between the female speaker and computer officer.

## `I-002_23_NAR_CARABINEROS_3`

**`carabinero_official`** → `SPK-female-carabinero-2-nar-carabineros-3` or `SPK-carabinero-speaker-00-nar-carabineros-3`. Indices: 0, 1, 14, 16, 22, 28, 32, 34, 39, 41, 44, 46, 48, 50, 62, 63, 64, 65, 66, 67, 68, 70, 73, 77, 81, 83, 85, 86, 87, 88, 89, 90, 92, 95, 97, 99, 101, 103, 107, 111, 112.

## `I-002_24_NAR-19_STG_12`

Unmapped labels: `airline_supervisor`, `airline_staff`, `unresolved_speaker`.

**`airline_supervisor`** → `SPK-latam-supervisora-nar-19-stg-12`. Indices: 4, 5, 6, 9, 11, 13, 15, 17, 19, 21, 24, 26, 28, 30, 32, 35, 39, 41, 44, 47, 49, 52, 54, 56, 58, 65, 68, 70, 82, 103, 105, 113, 114, 121, 126, 127, 129, 131, 137, 140, 142, 145, 147, 242, 244, 246, 249, 253, 264, 265.

**`airline_staff`** → `SPK-latam-staff-nar-19-stg-12` or `SPK-latam-official-nar-19-stg-12`. Indices: 50, 65, 66, 68, 70, 78, 80, 82, 90, 92, 94, 96, 98, 102, 107, 109, 110, 112, 114, 154, 171, 172, 174, 181, 183, 187, 205, 206, 208, 209, 211, 214, 216, 218, 219, 220, 223, 225, 227, 232, 234, 235, 238, 239, 241, 243, 245, 247, 252, 269, 271, 272, 273, 274, 275.

**`unresolved_speaker`** → `SPEAKER_00 (English speaker)`. Indices: 276, 277.

**`SPEAKER_00`** — see unresolved_speaker above.

## Summary counts

| File | Unmapped segment count |
|---|---|
| I-002_02 | ~32 |
| I-002_03 | 13 |
| I-002_04 | ~320+ |
| I-002_05 | ~120 |
| I-002_06 | ~150 |
| I-002_08 | 11 |
| I-002_09 | 2 |
| I-002_10 | ~80 |
| I-002_10A | 8 |
| I-002_11 | ~33 |
| I-002_12 | ~150 |
| I-002_13 | 10 |
| I-002_14 | ~200 |
| I-002_16 | 13 |
| I-002_17 | 11 |
| I-002_19 | 2 |
| I-002_20 | ~53 |
| I-002_21 | ~55 |
| I-002_22 | ~225 |
| I-002_23 | 42 |
| I-002_24 | ~60 |

## Recommendation for final mapping

1. **For `dgac_official` in files 04/05/06/12/14** — split into `DGAC Officer 1`, `DGAC Officer 2`, `DGAC Officer 3`, `Don Nicolas`, and `Edgardo Ortiz`.
2. **For `pdi_official` in files 04/05/06** — split into the specific PDI officer if distinguishable; otherwise map to the file-specific PDI group key.
3. **For `airline_staff` / `airline_supervisor`** — determine which LATAM person (Diego, Antonela, Acuser, BOSS, Counter staff, etc.) based on context.
4. **For `multi_party_audio`** — split manually; these are mixed-speaker segments. Usually assign to the dominant identifiable person.
5. **For `carabinero_official`** — split between `Female Carabinero #2` and the `Computer Officer` / `Carabinero (Constancia)` / `Carabinero (SPEAKER_00)`.
6. **For `other_passenger`** — map to `SPK-pasajeros-del-vuelo-nar-06-stg-6-jetbridge-standoff` where applicable, or to individual passengers if distinguishable.

