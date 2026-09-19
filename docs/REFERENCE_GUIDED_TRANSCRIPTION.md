# Reference-Guided Transcription Architecture

## Problem

Audio files have been transcribed multiple times, manually corrected, and are
scattered across different formats and locations. Each version has different
strengths — one may have correct speaker names, another may have better timing,
a third may have manually verified Chilean Spanish corrections.

Re-transcribing from scratch wastes all that prior work. A new Whisper run
produces generic `SPEAKER_00` labels, hallucinates on quiet segments, and
loses domain-specific vocabulary (legal terms, proper names, Chilean slang).

## Solution: Reference-Guided Pipeline

Use existing corrected transcripts as **priors** to the transcription pipeline:

```
┌─────────────────────────────────────────────────────────────┐
│                   REFERENCE STORE                           │
│  data/transcripts_by_audio/<audio_name>/                    │
│    ├── manifest.json         ← versions index + metadata    │
│    ├── reference_v1.json     ← prior corrected transcript   │
│    ├── reference_v2.json     ← another version              │
│    └── whisper_raw.json      ← latest raw Whisper output    │
└─────────────┬───────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│                   NARRATIVE STORE                            │
│  data/transcripts_narrative/                                │
│    └── incident_narrative_<audio_id>_<datetime>.txt          │
│        • Passenger-written chronological account            │
│        • Named individuals, [MM:SS] timestamps              │
│        • Situational context, exact Spanish quotes           │
└─────────────┬───────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│              REFERENCE-GUIDED TRANSCRIBE USE CASE           │
│                                                             │
│  1a. Load references from store                             │
│  1b. Load narratives from narrative store                   │
│  2.  Build Whisper initial_prompt from best reference       │
│  3.  Run Whisper (ASR) → raw segments                       │
│  4.  Run diarization → speaker turns                        │
│  5.  Merge ASR segments with speaker turns                  │
│  6.  LLM reconciliation: Claude merges raw + ref + narrative│
│  7.  Persist result + update manifest                       │
│  8.  Index into Qdrant                                      │
└─────────────────────────────────────────────────────────────┘
```

## Data Organization

### Directory structure per audio file

```
data/transcripts_by_audio/
└── aeropuerto_stg_7/
    ├── manifest.json              ← master index for this audio
    ├── reference_corrected.json   ← best manually-corrected version
    ├── reference_v2.json          ← another version
    ├── whisper_raw_20260718.json  ← raw Whisper output (timestamped)
    ├── guided_20260718.json      ← LLM-reconciled output
    └── metadata.json              ← audio metadata, participants, etc.
```

### manifest.json schema

```json
{
  "audio_file": "aeropuerto_STG_7.m4a",
  "audio_path": "data/audio/aeropuerto_STG_7.m4a",
  "canonical_name": "aeropuerto_stg_7",
  "participants": ["passenger", "airline_staff", "police_officer"],
  "language": "multi",
  "location": "Arturo Merino Benítez International Airport",
  "versions": [
    {
      "filename": "reference_corrected.json",
      "type": "reference",
      "source": "manual_correction",
      "quality_score": 0.95,
      "segments": 187,
      "created_at": "2026-02-13T14:26:21Z",
      "notes": "Manually corrected with named speakers"
    },
    {
      "filename": "whisper_raw_20260718.json",
      "type": "whisper_raw",
      "source": "pipeline",
      "model": "large-v3",
      "quality_score": null,
      "segments": 210,
      "created_at": "2026-07-18T10:30:00Z"
    },
    {
      "filename": "guided_20260718.json",
      "type": "guided",
      "source": "llm_reconciliation",
      "model": "claude-sonnet-4-5",
      "quality_score": null,
      "segments": 190,
      "created_at": "2026-07-18T10:35:00Z",
      "reference_used": "reference_corrected.json"
    }
  ]
}
```

### Reference transcript schema (rich format)

Existing references already follow this format (from `aeropuerto_STG_7.json`):

```json
{
  "node_id": "TRNS_d5bf2f2c",
  "title": "aeropuerto_STG_7",
  "audio_id": "aeropuerto_STG_7",
  "recording_datetime": "2024-07-05T15:16:00Z",
  "location": "Arturo Merino Benítez International Airport",
  "language": "multi",
  "participants": ["airline_staff", "passenger", "police_officer", "unknown_role"],
  "metadata": {
    "audio_duration": 1271.17,
    "source_file": "aeropuerto_STG_7.m4a",
    "confidence_score": 0.9
  },
  "content": [
    {
      "id": "0",
      "speaker": "passenger",
      "start": 0.03,
      "end": 20.69,
      "duration": 20.66,
      "text": "Yo estoy acá simplemente para manejar...",
      "language": "multi",
      "confidence": 0.9,
      "local_time": "2024-07-05T15:16:00.030000Z"
    }
  ]
}
```

## Narrative Layer

Passenger-written incident narratives provide a third context source alongside
references and raw ASR output. These are chronological accounts of events with
timestamps, named individuals, and exact quotes.

### Narrative file format

```
Title: <incident title>
Timeline Time: <ISO datetime>
Saved: <ISO datetime>

### Incident Overview
<paragraph describing the incident>

### Detailed Chronology
[MM:SS] <event description with names and quotes>
[MM:SS] <next event>
...
```

### Storage

Narratives live in `data/transcripts_narrative/` with the naming convention:
```
incident_narrative_<audio_id>_<ISO-datetime>.txt
```

### Alias mapping

Some narratives reference the same audio under different names:
- `latam_stg_2` → `aeropuerto_stg_2` (airline perspective of airport incident)
- `latam_stg_3` → `aeropuerto_stg_3`
- `carabineros_ppdartnel_1` → `pedro_pablo_dartnell` (police station name)

The `NarrativeStoreAdapter` resolves these aliases automatically.

### How narratives improve reconciliation

Claude receives the narrative as a third input alongside RAW + REFERENCE:
1. **Speaker identification** — narratives name individuals explicitly
2. **Context disambiguation** — clarifies ambiguous audio (shouting, crosstalk)
3. **Vocabulary grounding** — provides correct spellings of names, places, roles
4. **Timeline anchoring** — `[MM:SS]` timestamps cross-reference audio positions

Narrative text is truncated at 4,000 characters (at paragraph boundary) to
stay within token budget.

## Pipeline Steps Detail

### Step 1a: Load References

```python
references = reference_store.load_references("aeropuerto_stg_7")
# Returns: list of ReferenceTranscript with quality_score
# Sorted by quality: manual corrections first, then guided, then raw
```

### Step 2: Build Whisper initial_prompt

Whisper's `initial_prompt` parameter biases the decoder toward expected
vocabulary without constraining it. We extract key terms from the best
reference:

```python
best_ref = references[0]  # highest quality
prompt_parts = []

# Speaker names and roles
for p in best_ref.participants:
    prompt_parts.append(p)

# Key vocabulary from first ~500 tokens of transcript text
full_text = " ".join(seg.text for seg in best_ref.content[:30])
prompt_parts.append(full_text[:1500])

initial_prompt = ". ".join(prompt_parts)
```

This gives Whisper vocabulary hints: proper names, Chilean Spanish terms,
domain jargon — without forcing the decoder to reproduce the reference.

### Step 3-4: Whisper ASR + Diarization

Standard pipeline: Whisper produces text segments, pyannote produces speaker
turns. These run independently.

### Step 5: Merge Segments with Speaker Turns

Map each Whisper text segment to the overlapping diarization turn to assign
speakers. Standard merge by temporal overlap.

### Step 6: LLM Reconciliation (Claude)

This is the core innovation. Claude receives three inputs:
- The new raw transcription (with generic speaker labels)
- The best reference transcript (with named speakers, corrections)
- The incident narrative (if available — passenger's chronological account)

```
SYSTEM: You are a transcript reconciliation specialist for Chilean Spanish
audio recordings. You receive a NEW raw transcription, a REFERENCE
(previously corrected) transcript of the same audio, and optionally a
NARRATIVE (passenger's chronological account of events).

Your task:
1. Map generic speakers (SPEAKER_00, SPEAKER_01) to named roles from the
   reference (passenger, airline_staff, police_officer) based on what they say
2. Correct obvious Whisper errors using the reference as ground truth
3. Preserve any NEW content in the raw transcription not in the reference
4. Keep the raw timing (start/end) — the reference timing may differ
5. Flag segments where raw and reference significantly disagree
6. Maintain Chilean Spanish as-is — do not "correct" dialect to standard Spanish
7. Use the NARRATIVE for context — it provides named individuals, situational
   details, and timestamps that help disambiguate unclear audio

Output: JSON array of reconciled segments matching the reference schema.
```

### Step 7: Persist + Update Manifest

Save the reconciled output and update `manifest.json` with the new version.

### Step 8: Qdrant Index

Auto-index the reconciled transcript for semantic search.

## Clean Architecture Mapping

```
Domain Layer:
  ├── entities/reference.py              ← ReferenceTranscript, Manifest,
  │                                        IncidentNarrative
  └── ports/interfaces.py               ← ReferenceStorePort, NarrativeStorePort,
                                           TranscriptReconcilerPort

Application Layer:
  └── use_cases/guided_transcribe.py     ← ReferenceGuidedTranscribeUseCase

Infrastructure Layer:
  ├── reference_store_adapter.py         ← Filesystem-based reference store
  ├── narrative_store_adapter.py         ← Filesystem-based narrative store
  │                                        (alias resolution, header parsing)
  └── claude_reconciler.py              ← Claude-powered 3-input reconciliation
```

## Key Design Decisions

1. **References are read-only inputs** — the pipeline never modifies existing
   reference files. New outputs are always new files.

2. **Quality scoring is manual** — the `quality_score` in the manifest is set
   by the user, not computed. Automated quality metrics may come later.

3. **initial_prompt is vocabulary bias, not constraint** — Whisper uses it to
   prime its decoder but will still transcribe what it hears. This is the right
   balance between guidance and accuracy.

4. **Reconciliation is segment-level** — Claude processes segments in batches
   (not the entire transcript at once) to stay within token budgets.

5. **Speaker mapping is LLM-driven** — diarization produces SPEAKER_00/01,
   and the LLM maps these to named roles by comparing what each speaker says
   against the reference's speaker attributions.

6. **Runs on RunPod GPU** — the architecture separates ASR (GPU-intensive)
   from reconciliation (API call). RunPod handles Whisper + pyannote;
   Claude reconciliation can run anywhere.
