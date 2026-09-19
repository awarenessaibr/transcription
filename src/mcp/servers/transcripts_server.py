"""transcription MCP server: transcript intelligence and indexing tools.

Launch with:
    python -m src.mcp.servers.transcripts_server
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.composition import build_runtime
from src.domain.entities.transcript import Segment, Speaker, Transcript

logger = logging.getLogger(__name__)

_RUNTIME = build_runtime()
_ANALYZE_USE_CASE = _RUNTIME.analyze_use_case
_SEARCH_USE_CASE = _RUNTIME.search_use_case
_STORE = _RUNTIME.store_adapter
_INDEX = _RUNTIME.qdrant_adapter
_AUDITOR = _RUNTIME.auditor
_PATCHER = _RUNTIME.patcher
_VALIDATE_REFINE_USE_CASE = _RUNTIME.validate_refine_use_case

mcp = FastMCP("transcription-transcripts")

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename_stem(name: str) -> str:
    """Turn user-facing filename into a safe transcript_id stem."""
    if not name:
        return ""
    base = os.path.basename(str(name)).strip()
    stem, _ext = os.path.splitext(base)
    cleaned = _SAFE_NAME_RE.sub("_", stem).strip("._-")
    return cleaned[:180]


def _serialize_transcript(transcript: Transcript) -> dict[str, Any]:
    return {
        "transcript_id": transcript.transcript_id,
        "source_file": transcript.source_file,
        "language": transcript.language,
        "timestamp": transcript.timestamp,
        "provider": transcript.provider,
        "original_transcript_id": transcript.original_transcript_id,
        "metadata": transcript.metadata or {},
        "title": transcript.title or "",
        "subtitle": transcript.subtitle or "",
        "recording_datetime": transcript.recording_datetime or "",
        "location": transcript.location or "",
        "audio_id": transcript.audio_id or "",
        "case_id": transcript.case_id or "",
        "narrative_id": transcript.narrative_id or "",
        "chronological_order": transcript.chronological_order,
        "prior_stage": transcript.prior_stage or "",
        "next_stage": transcript.next_stage or "",
        "classification": transcript.classification or "",
        "participants": transcript.participants or [],
        "violations_cited": transcript.violations_cited or [],
        "tags": transcript.tags or [],
        "forensic_clusters": transcript.forensic_clusters or {},
        "key_evidentiary_findings": transcript.key_evidentiary_findings or [],
        "corrections_applied": transcript.corrections_applied or [],
        "segments": [
            {
                "index": s.index,
                "speaker": s.speaker.label,
                "start": s.start,
                "end": s.end,
                "duration": s.duration,
                "text": s.text,
            }
            for s in transcript.segments
        ],
    }


@mcp.tool()
def transcription_list_transcripts() -> dict[str, Any]:
    """Return all transcript ids, newest first by id sort."""
    return {"transcripts": sorted(_STORE.list_ids(), reverse=True)}


@mcp.tool()
def transcription_get_transcript(transcript_id: str) -> dict[str, Any]:
    """Load one transcript by id."""
    transcript = _STORE.load(transcript_id)
    if transcript is None:
        raise ValueError(f"Transcript not found: {transcript_id}")
    return _serialize_transcript(transcript)


@mcp.tool()
def transcription_import_transcripts(
    runs: list[dict[str, Any]],
    overwrite: bool = False,
    rename_by_filename: bool = True,
) -> dict[str, Any]:
    """Import one or more transcript runs into JSON transcript storage."""
    if not runs:
        raise ValueError("No runs provided for import")

    existing_ids = set(_STORE.list_ids())
    imported_ids: list[str] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for idx, run in enumerate(runs):
        try:
            segments_payload = run.get("segments") or []
            segments: list[Segment] = []
            for seg_idx, seg in enumerate(segments_payload):
                start = float(seg.get("start") or 0.0)
                if start < 0:
                    start = 0.0

                end_raw = seg.get("end") if seg.get("end") is not None else start
                end = float(end_raw)
                if end < start:
                    end = start

                speaker_label = (seg.get("speaker") or f"SPEAKER_{seg_idx:02d}").strip() or f"SPEAKER_{seg_idx:02d}"
                segment_index = seg.get("index") if seg.get("index") is not None else seg_idx

                segments.append(
                    Segment(
                        index=int(segment_index),
                        speaker=Speaker(label=speaker_label),
                        start=start,
                        end=end,
                        text=str(seg.get("text") or ""),
                    )
                )

            if not segments:
                skipped.append({"index": idx, "reason": "empty_segments"})
                continue

            incoming_id = str(run.get("transcript_id") or "").strip()
            source_file = str(run.get("source_file") or run.get("filename") or "").strip()
            filename_stem = _sanitize_filename_stem(str(run.get("filename") or run.get("source_file") or ""))

            if rename_by_filename and filename_stem:
                desired_id = filename_stem
            elif incoming_id:
                desired_id = incoming_id
            elif filename_stem:
                desired_id = filename_stem
            else:
                desired_id = f"imported_{int(time.time() * 1000)}_{idx + 1}"

            transcript_id = desired_id
            if not overwrite and transcript_id in existing_ids:
                nonce = 1
                while transcript_id in existing_ids:
                    nonce += 1
                    transcript_id = f"{desired_id}_{nonce}"

            if not overwrite and transcript_id in existing_ids:
                skipped.append(
                    {
                        "index": idx,
                        "transcript_id": transcript_id,
                        "reason": "already_exists",
                    }
                )
                continue

            transcript = Transcript(
                transcript_id=transcript_id,
                segments=segments,
                source_file=source_file,
                language=(str(run.get("language") or "es") or "es"),
                metadata=(run.get("metadata") or {}),
                timestamp=str(run.get("timestamp") or ""),
                provider=str(run.get("provider") or ""),
                original_transcript_id=(incoming_id if incoming_id and incoming_id != transcript_id else ""),
                title=str(run.get("title") or ""),
                subtitle=str(run.get("subtitle") or ""),
                recording_datetime=str(run.get("recording_datetime") or ""),
                location=str(run.get("location") or ""),
                audio_id=str(run.get("audio_id") or ""),
                case_id=str(run.get("case_id") or ""),
                narrative_id=str(run.get("narrative_id") or ""),
                chronological_order=run.get("chronological_order"),
                prior_stage=str(run.get("prior_stage") or ""),
                next_stage=str(run.get("next_stage") or ""),
                classification=str(run.get("classification") or ""),
                participants=run.get("participants", []),
                violations_cited=run.get("violations_cited", []),
                tags=run.get("tags", []),
                forensic_clusters=run.get("forensic_clusters", {}),
                key_evidentiary_findings=run.get("key_evidentiary_findings", []),
                corrections_applied=run.get("corrections_applied", []),
            )
            _STORE.save(transcript)
            existing_ids.add(transcript_id)
            imported_ids.append(transcript_id)
        except Exception as exc:
            errors.append(
                {
                    "index": idx,
                    "transcript_id": run.get("transcript_id"),
                    "error": str(exc),
                }
            )

    return {
        "total_runs": len(runs),
        "imported": len(imported_ids),
        "imported_ids": imported_ids,
        "skipped": skipped,
        "errors": errors,
    }


@mcp.tool()
async def transcription_analyze_transcript(transcript_id: str, instructions: str = "") -> dict[str, Any]:
    """Run configured LLM analyzer for one transcript."""
    if _ANALYZE_USE_CASE is None:
        raise ValueError("Transcript analysis not configured. Set DEEPSEEK_API_KEY or ANTHROPIC_API_KEY.")
    result = await _ANALYZE_USE_CASE.execute(transcript_id, instructions=instructions)
    return result.model_dump()


@mcp.tool()
async def transcription_search_transcripts(query: str, limit: int = 5) -> dict[str, Any]:
    """Semantic search across all indexed transcript segments."""
    if _SEARCH_USE_CASE is None:
        raise ValueError("Transcript search not configured. Set QDRANT_URL.")
    result = await _SEARCH_USE_CASE.execute(query, limit=limit)
    return result.model_dump()


@mcp.tool()
async def transcription_index_transcript(transcript_id: str) -> dict[str, Any]:
    """Re-index a single transcript into Qdrant."""
    if _INDEX is None:
        raise ValueError("Vector indexing not configured. Set QDRANT_URL.")
    transcript = _STORE.load(transcript_id)
    if transcript is None:
        raise ValueError(f"Transcript not found: {transcript_id}")
    count = await _INDEX.index(transcript)
    return {"transcript_id": transcript_id, "segments_indexed": count}


@mcp.tool()
async def transcription_index_all_transcripts() -> dict[str, Any]:
    """Re-index all stored transcripts into Qdrant."""
    if _INDEX is None:
        raise ValueError("Vector indexing not configured. Set QDRANT_URL.")

    ids = _STORE.list_ids()
    total = 0
    errors: list[dict[str, Any]] = []

    for transcript_id in ids:
        transcript = _STORE.load(transcript_id)
        if transcript is None:
            continue
        try:
            count = await _INDEX.index(transcript)
            total += count
        except Exception as exc:
            errors.append({"transcript_id": transcript_id, "error": str(exc)})

    return {
        "transcripts_processed": len(ids),
        "segments_indexed": total,
        "errors": errors,
    }


# ── Validate-and-refine tools ──────────────────────────────────────────


@mcp.tool()
def transcription_audit_transcript(transcript_id: str) -> dict[str, Any]:
    """Run structural audit on a stored transcript. No audio, no LLM."""
    transcript = _STORE.load(transcript_id)
    if transcript is None:
        raise ValueError(f"Transcript not found: {transcript_id}")
    report = _AUDITOR.audit(transcript)
    return {
        "transcript_id": report.transcript_id,
        "counts_by_kind": report.kind_counts(),
        "counts_by_severity": report.severity_counts(),
        "anomalies": [
            {
                "kind": a.kind.value,
                "severity": a.severity.value,
                "segment_indices": list(a.segment_indices),
                "start": a.start,
                "end": a.end,
                "hint": a.hint,
                "detail": a.detail_dict(),
            }
            for a in report.anomalies
        ],
    }


@mcp.tool()
async def transcription_validate_and_refine_transcript(
    transcript_id: str,
    canonical_name: str | None = None,
    use_acoustic_probes: bool = True,
    apply_patches: bool = True,
    save_as_new_id: bool = True,
    max_acoustic_windows: int = 8,
) -> dict[str, Any]:
    """Audit + auto-fix deterministic anomalies + reconcile flagged windows
    + (optionally) probe audio and re-diarize/re-ASR low-SNR clips."""
    if _VALIDATE_REFINE_USE_CASE is None:
        raise ValueError("Validate-refine use case not configured.")
    result = await _VALIDATE_REFINE_USE_CASE.execute(
        transcript_id,
        canonical_name=canonical_name,
        use_acoustic_probes=use_acoustic_probes,
        apply_patches=apply_patches,
        save_as_new_id=save_as_new_id,
        max_acoustic_windows=max_acoustic_windows,
    )
    return result.model_dump()


@mcp.tool()
def transcription_patch_transcript_segments(
    transcript_id: str,
    patches: list[dict[str, Any]],
    save_as_new_id: bool = True,
) -> dict[str, Any]:
    """Apply agent-supplied patches. Each patch dict must include 'op' and
    'segment_indices'; other fields per Patch dataclass."""
    from src.domain.entities.patch import Patch, PatchOp

    transcript = _STORE.load(transcript_id)
    if transcript is None:
        raise ValueError(f"Transcript not found: {transcript_id}")

    parsed: list[Patch] = []
    for raw in patches:
        op_value = raw.get("op")
        if not op_value:
            raise ValueError("patch missing 'op'")
        try:
            op = PatchOp(op_value)
        except ValueError as exc:
            raise ValueError(f"unknown patch op: {op_value}") from exc
        parsed.append(
            Patch(
                op=op,
                segment_indices=tuple(int(i) for i in raw.get("segment_indices", [])),
                new_text=raw.get("new_text"),
                new_speaker=raw.get("new_speaker"),
                new_start=(
                    float(raw["new_start"]) if raw.get("new_start") is not None else None
                ),
                new_end=(
                    float(raw["new_end"]) if raw.get("new_end") is not None else None
                ),
                insert_after_index=(
                    int(raw["insert_after_index"])
                    if raw.get("insert_after_index") is not None
                    else None
                ),
                note=str(raw.get("note", "")),
            )
        )

    patched, applied = _PATCHER.apply(transcript, parsed)
    if save_as_new_id:
        new_id = f"{transcript_id}_patched_{int(time.time())}"
        from dataclasses import replace as _replace
        patched = _replace(
            patched,
            transcript_id=new_id,
            original_transcript_id=transcript_id,
        )
    _STORE.save(patched)

    return {
        "transcript_id_in": transcript_id,
        "transcript_id_out": patched.transcript_id,
        "transcript": _serialize_transcript(patched),
        "patches_applied": [
            {
                "op": p.op.value,
                "segment_indices": list(p.segment_indices),
                "new_text": p.new_text,
                "new_speaker": p.new_speaker,
                "new_start": p.new_start,
                "new_end": p.new_end,
                "insert_after_index": p.insert_after_index,
                "note": p.note,
            }
            for p in applied
        ],
    }


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for remote connectivity tests."""
    return JSONResponse({"status": "ok", "service": "transcription-transcripts"})


def main() -> None:
    """Entrypoint for MCP server with configurable transport."""
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8122"))

    if transport == "stdio":
        mcp.run()
        return

    if transport not in {"sse", "streamable-http"}:
        raise ValueError(f"Unsupported MCP_TRANSPORT '{transport}'. Use: stdio, sse, streamable-http")

    if hasattr(mcp, "settings"):
        if hasattr(mcp.settings, "host"):
            mcp.settings.host = host
        if hasattr(mcp.settings, "port"):
            mcp.settings.port = port

    try:
        mcp.run(transport=transport, host=host, port=port)
    except TypeError:
        mcp.run(transport=transport)


if __name__ == "__main__":
    main()
