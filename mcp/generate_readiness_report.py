"""Generate MCP readiness report for transcription bootstrap servers."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTERS_DIR = ROOT / "src" / "presentation" / "routers"
SERVERS_DIR = ROOT / "src" / "mcp" / "servers"
REPORT_PATH = ROOT / "mcp" / "MCP_READINESS_REPORT.md"

TOOL_ROUTE_MAP: dict[str, str] = {
    "transcription_health": "GET /health",
    "transcription_health_full": "GET /",
    "transcription_list_parameter_definitions": "GET /api/diarization/parameters",
    "transcription_list_whisper_models": "GET /api/diarization/models/whisper",
    "transcription_transcribe_audio": "POST /api/diarization/transcribe",
    "transcription_transcribe_audio_async": "POST /api/diarization/transcribe/async",
    "transcription_diarize_excerpt": "POST /api/diarization/excerpt",
    "transcription_list_transcripts": "GET /api/transcripts",
    "transcription_get_transcript": "GET /api/transcripts/{transcript_id}",
    "transcription_import_transcripts": "POST /api/transcripts/import",
    "transcription_analyze_transcript": "POST /api/transcripts/analyze",
    "transcription_search_transcripts": "POST /api/transcripts/search",
    "transcription_audit_transcript": "POST /api/transcripts/{transcript_id}/audit",
    "transcription_validate_and_refine_transcript": "POST /api/transcripts/{transcript_id}/refine",
    "transcription_patch_transcript_segments": "POST /api/transcripts/{transcript_id}/patch",
    "transcription_index_transcript": "POST /api/transcripts/{transcript_id}/index",
    "transcription_index_all_transcripts": "POST /api/transcripts/index-all",
    "transcription_get_transcription_job": "GET /api/transcripts/status/{job_id}",
    "transcription_transcribe_audio_guided": "POST /api/diarization/transcribe/guided",
    "transcription_transcribe_audio_guided_async": "POST /api/diarization/transcribe/guided/async",
    "transcription_list_projects": "GET /api/projects",
    "transcription_get_project": "GET /api/projects/{project_id}",
    "transcription_create_project_api": "POST /api/projects",
    "transcription_update_project_api": "PATCH /api/projects/{project_id}",
    "transcription_delete_project_api": "DELETE /api/projects/{project_id}",
    "transcription_add_project_audio_api": "POST /api/projects/{project_id}/audios",
    "transcription_remove_project_audio_api": "DELETE /api/projects/{project_id}/audios/{canonical_name}",
    "transcription_add_project_context_doc_api": "POST /api/projects/{project_id}/context_docs",
    "transcription_remove_project_context_doc_api": "DELETE /api/projects/{project_id}/context_docs",
    "transcription_add_project_narrative_api": "POST /api/projects/{project_id}/narratives",
    "transcription_list_references_api": "GET /api/references",
    "transcription_get_reference_api": "GET /api/references/{canonical_name}",
    "transcription_get_reference_manifest_api": "GET /api/references/{canonical_name}/manifest",
    "transcription_get_reference_narratives_api": "GET /api/references/{canonical_name}/narratives",
    "transcription_upload_reference_api": "POST /api/references/{canonical_name}/upload",
    "transcription_link_reference_api": "POST /api/references/{canonical_name}/link",
}


def _normalize_path(prefix: str, path: str) -> str:
    if not prefix:
        return path or "/"
    if not path:
        return prefix
    if path == "/":
        return prefix or "/"
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def discover_endpoints() -> list[str]:
    endpoints: list[str] = []
    route_pattern = re.compile(r"@router\.(get|post|put|delete|patch)\(\"([^\"]*)\"\)")
    prefix_pattern = re.compile(r"APIRouter\((?:[^\)]*?)prefix\s*=\s*\"([^\"]+)\"")

    for file_path in sorted(ROUTERS_DIR.glob("*.py")):
        content = file_path.read_text(encoding="utf-8")
        prefix_match = prefix_pattern.search(content)
        prefix = prefix_match.group(1) if prefix_match else ""

        for method, path in route_pattern.findall(content):
            full_path = _normalize_path(prefix, path)
            endpoints.append(f"{method.upper()} {full_path}")

    return sorted(set(endpoints))


def discover_tools() -> list[str]:
    tools: list[str] = []
    tool_pattern = re.compile(r"@mcp\.tool\(\)\s*\n(?:async\s+)?def\s+([a-zA-Z0-9_]+)\(")
    for file_path in sorted(SERVERS_DIR.glob("*_server.py")):
        content = file_path.read_text(encoding="utf-8")
        tools.extend(tool_pattern.findall(content))
    return sorted(set(tools))


def is_snake_case(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z0-9_]*", name))


def main() -> None:
    endpoints = discover_endpoints()
    tools = discover_tools()

    mapped_endpoints = {route for route in TOOL_ROUTE_MAP.values() if route in endpoints}
    missing = sorted(set(endpoints) - mapped_endpoints)

    bad_prefix = sorted([name for name in tools if not name.startswith("transcription_")])
    bad_case = sorted([name for name in tools if not is_snake_case(name)])

    coverage = 0.0
    if endpoints:
        coverage = (len(mapped_endpoints) / len(endpoints)) * 100

    ready = not missing and not bad_prefix and not bad_case

    lines: list[str] = []
    lines.append("# MCP Readiness Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- state: {'ready' if ready else 'not-ready'}")
    lines.append(f"- discovered_endpoints: {len(endpoints)}")
    lines.append(f"- mapped_endpoints: {len(mapped_endpoints)}")
    lines.append(f"- missing_endpoints: {len(missing)}")
    lines.append(f"- coverage_percent: {coverage:.1f}")
    lines.append("")

    lines.append("## Naming Checks")
    lines.append("")
    lines.append(f"- tools_discovered: {len(tools)}")
    lines.append(f"- prefix_violations: {len(bad_prefix)}")
    lines.append(f"- snake_case_violations: {len(bad_case)}")
    lines.append("")

    if bad_prefix:
        lines.append("### Prefix Violations")
        lines.append("")
        for item in bad_prefix:
            lines.append(f"- {item}")
        lines.append("")

    if bad_case:
        lines.append("### Snake Case Violations")
        lines.append("")
        for item in bad_case:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## Endpoint Coverage")
    lines.append("")
    for endpoint in endpoints:
        matched_tool = next((tool for tool, route in TOOL_ROUTE_MAP.items() if route == endpoint), None)
        if matched_tool:
            lines.append(f"- mapped: {endpoint} -> {matched_tool}")
        else:
            lines.append(f"- missing: {endpoint}")
    lines.append("")

    if missing:
        lines.append("## Missing Endpoints")
        lines.append("")
        for endpoint in missing:
            lines.append(f"- {endpoint}")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")
    print(f"State: {'ready' if ready else 'not-ready'}")


if __name__ == "__main__":
    main()
