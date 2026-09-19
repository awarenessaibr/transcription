# Nested schema normalisation (Task C)

Transcripts rewritten: **0** of 27.

Canonical shapes:

| field | canonical keys |
|---|---|
| `key_evidentiary_findings[]` | `id, finding, strength, segments, cross_reference` |
| `forensic_clusters.<name>` | `summary, reasoning, provisions_engaged, violation_linkage, segments` (present keys only) |
| `corrections_applied[]` | `segment, original, corrected, reason, type` (`type` optional) |

`strength` vocabulary: `High`, `Medium`, `Low`.

## `strength` remapping

| original value | findings | mapped to |
|---|---|---|
| _(none)_ | 0 | — |

## Discarded keys

| key | occurrences | justification |
|---|---|---|
| _(none)_ | 0 | — |

## `corrections_applied` coercions

| original shape | entries | result |
|---|---|---|
| bare string | 0 | `reason` = prose, `type` = `process_note`, `segment`/`original`/`corrected` = `""` |
| `{note, type}` | 0 | `reason` = note, `type` preserved |

## Rewritten transcripts

- _(none)_
