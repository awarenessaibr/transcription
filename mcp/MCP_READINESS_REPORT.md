# MCP Readiness Report

## Summary

- state: not-ready
- discovered_endpoints: 49
- mapped_endpoints: 36
- missing_endpoints: 13
- coverage_percent: 73.5

## Naming Checks

- tools_discovered: 41
- prefix_violations: 0
- snake_case_violations: 0

## Endpoint Coverage

- mapped: DELETE /api/projects/{project_id} -> transcription_delete_project_api
- mapped: DELETE /api/projects/{project_id}/audios/{canonical_name} -> transcription_remove_project_audio_api
- mapped: DELETE /api/projects/{project_id}/context_docs -> transcription_remove_project_context_doc_api
- mapped: GET / -> transcription_health_full
- mapped: GET /api/diarization/models/whisper -> transcription_list_whisper_models
- mapped: GET /api/diarization/parameters -> transcription_list_parameter_definitions
- mapped: GET /api/projects -> transcription_list_projects
- mapped: GET /api/projects/{project_id} -> transcription_get_project
- mapped: GET /api/references -> transcription_list_references_api
- mapped: GET /api/references/{canonical_name} -> transcription_get_reference_api
- mapped: GET /api/references/{canonical_name}/manifest -> transcription_get_reference_manifest_api
- mapped: GET /api/references/{canonical_name}/narratives -> transcription_get_reference_narratives_api
- mapped: GET /api/transcripts -> transcription_list_transcripts
- missing: GET /api/transcripts/audio/list
- missing: GET /api/transcripts/csv/list
- missing: GET /api/transcripts/pinocchio/review/{transcript_id}
- missing: GET /api/transcripts/review/list
- mapped: GET /api/transcripts/status/{job_id} -> transcription_get_transcription_job
- missing: GET /api/transcripts/stream/{job_id}
- mapped: GET /api/transcripts/{transcript_id} -> transcription_get_transcript
- mapped: GET /health -> transcription_health
- mapped: PATCH /api/projects/{project_id} -> transcription_update_project_api
- mapped: POST /api/diarization/excerpt -> transcription_diarize_excerpt
- missing: POST /api/diarization/excerpt_by_path
- mapped: POST /api/diarization/transcribe -> transcription_transcribe_audio
- mapped: POST /api/diarization/transcribe/async -> transcription_transcribe_audio_async
- mapped: POST /api/diarization/transcribe/guided -> transcription_transcribe_audio_guided
- mapped: POST /api/diarization/transcribe/guided/async -> transcription_transcribe_audio_guided_async
- mapped: POST /api/projects -> transcription_create_project_api
- mapped: POST /api/projects/{project_id}/audios -> transcription_add_project_audio_api
- mapped: POST /api/projects/{project_id}/context_docs -> transcription_add_project_context_doc_api
- mapped: POST /api/projects/{project_id}/narratives -> transcription_add_project_narrative_api
- mapped: POST /api/references/{canonical_name}/link -> transcription_link_reference_api
- mapped: POST /api/references/{canonical_name}/upload -> transcription_upload_reference_api
- mapped: POST /api/transcripts/analyze -> transcription_analyze_transcript
- missing: POST /api/transcripts/csv/import
- mapped: POST /api/transcripts/import -> transcription_import_transcripts
- mapped: POST /api/transcripts/index-all -> transcription_index_all_transcripts
- missing: POST /api/transcripts/pinocchio/review/{transcript_id}
- mapped: POST /api/transcripts/search -> transcription_search_transcripts
- mapped: POST /api/transcripts/{transcript_id}/audit -> transcription_audit_transcript
- mapped: POST /api/transcripts/{transcript_id}/index -> transcription_index_transcript
- mapped: POST /api/transcripts/{transcript_id}/patch -> transcription_patch_transcript_segments
- mapped: POST /api/transcripts/{transcript_id}/refine -> transcription_validate_and_refine_transcript
- missing: POST /api/transcripts/{transcript_id}/retranscribe_segments
- missing: POST /api/transcripts/{transcript_id}/review/index
- missing: POST /api/transcripts/{transcript_id}/review/save
- missing: POST /api/voiceprint_from_file
- missing: PUT /api/transcripts/{transcript_id}

## Missing Endpoints

- GET /api/transcripts/audio/list
- GET /api/transcripts/csv/list
- GET /api/transcripts/pinocchio/review/{transcript_id}
- GET /api/transcripts/review/list
- GET /api/transcripts/stream/{job_id}
- POST /api/diarization/excerpt_by_path
- POST /api/transcripts/csv/import
- POST /api/transcripts/pinocchio/review/{transcript_id}
- POST /api/transcripts/{transcript_id}/retranscribe_segments
- POST /api/transcripts/{transcript_id}/review/index
- POST /api/transcripts/{transcript_id}/review/save
- POST /api/voiceprint_from_file
- PUT /api/transcripts/{transcript_id}
