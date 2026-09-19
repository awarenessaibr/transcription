# transcription MCP Bootstrap

This directory provides a bootstrap MCP surface for this project using the
`python-fastmcp-multi` pattern.

## Servers

- `transcription-transcription` → `src/mcp/servers/transcription_server.py`
- `transcription-transcripts` → `src/mcp/servers/transcripts_server.py`
- `transcription-meta` → `src/mcp/servers/meta_server.py`

## Tool Inventory

### transcription-transcription

- `transcription_transcribe_audio`
- `transcription_transcribe_audio_async`
- `transcription_transcribe_audio_guided`
- `transcription_transcribe_audio_guided_async`
- `transcription_get_transcription_job`
- `transcription_diarize_excerpt`

### transcription-transcripts

- `transcription_list_transcripts`
- `transcription_get_transcript`
- `transcription_import_transcripts`
- `transcription_analyze_transcript`
- `transcription_search_transcripts`
- `transcription_index_transcript`
- `transcription_index_all_transcripts`
- `transcription_audit_transcript`
- `transcription_validate_and_refine_transcript`
- `transcription_patch_transcript_segments`

### transcription-meta

- `transcription_health`
- `transcription_health_full`
- `transcription_list_parameter_definitions`
- `transcription_list_whisper_models`
- `transcription_list_projects`
- `transcription_get_project`
- `transcription_list_project_references`
- `transcription_read_project_context_doc`
- `transcription_list_project_narratives`
- `transcription_list_projects_api`
- `transcription_get_project_api`
- `transcription_create_project_api`
- `transcription_update_project_api`
- `transcription_delete_project_api`
- `transcription_add_project_audio_api`
- `transcription_remove_project_audio_api`
- `transcription_add_project_context_doc_api`
- `transcription_remove_project_context_doc_api`
- `transcription_add_project_narrative_api`
- `transcription_list_references_api`
- `transcription_get_reference_api`
- `transcription_get_reference_manifest_api`
- `transcription_get_reference_narratives_api`
- `transcription_upload_reference_api`
- `transcription_link_reference_api`

## Generate Readiness Report

```bash
python mcp/generate_readiness_report.py
```

## Syntax Check

```bash
python -m py_compile src/mcp/servers/*.py mcp/generate_readiness_report.py
```

## Startup (Stdio)

```bash
python -m src.mcp.servers.meta_server
python -m src.mcp.servers.transcription_server
python -m src.mcp.servers.transcripts_server
```

Important:
- Start only one server per terminal session.
- Once started, do not type shell commands into that same terminal; stdio is reserved for MCP JSON-RPC messages.
- If you need to start another server, open a new terminal tab/window.
- Stop a running server with `Ctrl+C`.

Notes on warnings:
- `SyntaxWarning: invalid escape sequence` from packages like `pydub` or `pyannote` is non-fatal and does not prevent MCP startup.
- If needed, suppress these warnings with `PYTHONWARNINGS=ignore::SyntaxWarning`.
