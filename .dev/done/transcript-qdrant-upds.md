
1.2 Changes to the transcript JSON — none required
The JSON is already self-describing. speaker (role token) + participants[].speaker_id (canonical, when known) + reviewed + segment_datetime + correction_note + backchannel_events + top-level prior_stage/next_stage — everything the ingester needs is there.

Two optional cosmetic choices, not needed for correctness:

Denormalise speaker_id onto each segment in the JSON, so a reader doesn't have to build the role→id map. This is a preference; the ingester can build the map trivially and I'd leave the JSON alone.

segment_id at segment level ("seg-5"). Currently derived from index in code. Leave it derived — a single canonical field is better than two that can drift.

1.3 Changes to the transcript Qdrant payload / ingester — this is the work
Add four fields, and change one namespace decision.

Add speaker_id (nullable)
Resolved from participants[] by matching the segment's role token. Where the participant has no speaker_id (the anonymous cases — airline_staff, dgac_official, pdi_official, unresolved_speaker, other_passenger, multi_party_audio, background_audio), write null.

This is what makes same_speaker correlation a Qdrant filter rather than a full-scan heuristic.

Add reviewed
Boolean, from segments[i].reviewed. Enables reviewed=true filters — so downstream consumers can distinguish "this is human-signed-off evidence" from "this is raw ASR."

Add segment_id
The qualified <source_id>.<local_id> form that the models use everywhere else — e.g. STG-5.seg-23. Currently a caller has to reconstruct it from transcript_id + segment_index and remember the exact naming convention. Store it.

Add prior_stage / next_stage
From the JSON top-level. Two scalars. Gives you the linked-list ordering of the incident without needing a second query.

Change the point-ID namespace
Today the ingester namespaces under bundle_id (or violation id). That produces one point per (segment, violation) — a segment cited by CL-014 and CL-021 lands twice. The reviewed dump uses one point per segment, which is correct. Namespace under the transcript:

python
_stable_point_id("segment", src.source_id(), str(idx))
upsert_segment(segment, violation_id) (existing Protocol method) then becomes a per-violation convenience wrapper that simply doesn't touch the id — it delegates to the same point. violations_cited is a list on the payload; a segment becomes "cited by" a violation via filter, not via a duplicated point.

Drop bundle_id; keep case_id
The dump uses case_id (I-002) plus narrative_id. That's the incident-scoped identity. bundle_id was a per-run tag that meant different things at different times. Remove it.

1.4 Resulting payload — the whole shape
jsonc
{
  "transcript_id":        "I-002_01_NAR-01_STG_1_pre_boarding",
  "segment_id":           "I-002_01_NAR-01_STG_1_pre_boarding.seg-5",   // new
  "segment_index":        5,
  "speaker":              "airline_pilot",
  "speaker_id":           null,                                          // new
  "start":                39.3,
  "end":                  44.7,
  "text":                 "Cara, voce tem 45 minutos para decolar, vai dar mais ou menos no horario.",
  "local_time":           "2024-07-05T12:56:39.300000",
  "reviewed":             true,                                          // new
  "correction_note":      "",
  "backchannel_events":   "",

  // denormalised transcript context
  "case_id":              "I-002",
  "narrative_id":         "NAR-01_STG_1_pre_boarding",
  "title":                "01 - Aeropuerto Arturo Merino Benítez",
  "location":             "…",
  "language":             "pt",
  "source_file":          "transcription/data/audio/Aeropuerto Arturo Merino Benítez.m4a",
  "recording_datetime":   "2024-07-05T12:56:00",
  "chronological_order":  1,
  "prior_stage":          null,                                          // new
  "next_stage":           "I-002_02_NAR-02_STG_2_boarding_gate",         // new

  "tags":                 ["transcript","narrative","evidence",...],
  "violations_cited":     ["CL-014","CL-021"],
  "participants":         [ {…}, {…} ],

  "forensic_cluster_ids": ["cluster_A_casual_inquiry"],
  "key_finding_ids":      []
}
