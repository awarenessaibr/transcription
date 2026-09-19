"""transcription MCP server: health and model/parameter metadata tools.

Launch with:
    python -m src.mcp.servers.meta_server
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import torch
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from whisper import available_models

from src.config import settings
from src.domain.entities.project import ContextDocument, Project, ProjectAudio
from src.domain.entities.reference import ManifestVersion
from src.infrastructure.narrative_store_adapter import NarrativeStoreAdapter
from src.infrastructure.project_store_adapter import ProjectStoreAdapter
from src.infrastructure.reference_store_adapter import ReferenceStoreAdapter

mcp = FastMCP("transcription-meta")

_project_store = ProjectStoreAdapter(settings.PROJECTS_DIR)
_ref_store = ReferenceStoreAdapter(settings.REFERENCE_DIR)
_narrative_store = NarrativeStoreAdapter(settings.NARRATIVE_DIR)


def _safe_canonical_name(canonical_name: str) -> str:
    value = (canonical_name or "").strip()
    if not value or "/" in value or ".." in value:
        raise ValueError("invalid canonical_name")
    return value


def _project_to_dict(project: Project) -> dict[str, Any]:
    data = asdict(project)
    summary: dict[str, list[dict[str, Any]]] = {}
    counts: list[dict[str, Any]] = []
    for canonical_name in project.canonical_names():
        manifest = _ref_store.load_manifest(canonical_name)
        versions: list[dict[str, Any]] = []
        if manifest is not None:
            for version in manifest.versions:
                if version.type != "reference":
                    continue
                versions.append(
                    {
                        "filename": version.filename,
                        "source": version.source,
                        "quality_score": version.quality_score,
                        "segments": version.segments,
                        "created_at": version.created_at,
                    }
                )
        summary[canonical_name] = versions
        counts.append(
            {
                "canonical_name": canonical_name,
                "has_manifest": manifest is not None,
                "n_references": len(versions),
                "n_versions": len(manifest.versions) if manifest else 0,
            }
        )

    data["references_summary"] = summary
    data["references_counts"] = counts
    return data


def _get_project_or_raise(project_id: str) -> Project:
    project = _project_store.load(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    return project


def _normalize_reference_filename(name: str) -> str:
    safe_name = (name or "reference.json").replace("/", "_")
    if not safe_name.endswith(".json"):
        safe_name += ".json"
    return safe_name


def _load_reference_content_or_raise(source_path: str) -> tuple[dict[str, Any], str]:
    if not source_path or not os.path.isfile(source_path):
        raise ValueError(f"source_path not found: {source_path}")
    try:
        with open(source_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"unreadable JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("content"), list):
        raise ValueError("reference must be a JSON object with a 'content' list")
    return data, os.path.basename(source_path)


def _upsert_reference_manifest(
    canonical_name: str,
    data: dict[str, Any],
    *,
    filename: str,
    source: str,
    quality_score: float,
    notes: str,
    replace_existing_filename: bool,
) -> None:
    manifest = _ref_store.load_manifest(canonical_name)
    if manifest is None:
        from src.domain.entities.reference import AudioManifest

        manifest = AudioManifest(
            audio_file=data.get("audio_file", ""),
            audio_path="",
            canonical_name=canonical_name,
            participants=data.get("participants", []),
            language=data.get("language", "es"),
            location=data.get("location", ""),
            versions=[],
        )

    if replace_existing_filename:
        manifest.versions = [v for v in manifest.versions if v.filename != filename]

    manifest.versions.append(
        ManifestVersion(
            filename=filename,
            type="reference",
            source=source,
            quality_score=quality_score,
            segments=len(data["content"]),
            created_at=datetime.now(timezone.utc).isoformat(),
            notes=notes,
        )
    )
    _ref_store.save_manifest(manifest)


@mcp.tool()
def transcription_health() -> dict[str, Any]:
    """Return basic service health metadata."""
    return {
        "status": "ok",
        "service": "transcription",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@mcp.tool()
def transcription_health_full() -> dict[str, Any]:
    """Return extended runtime health metadata."""
    return {
        "status": "ok",
        "service": "transcription",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "torch_device": settings.TORCH_DEVICE,
        "torch_float": settings.TORCH_FLOAT,
        "cuda_available": torch.cuda.is_available(),
    }


@mcp.tool()
def transcription_list_parameter_definitions() -> dict[str, Any]:
    """Return full transcription parameter metadata."""
    return {
        "general": {
            "language": "Input language locale (maps to Whisper language code). Ex: es-CL, en, pt-BR.",
            "model_size": "Whisper model variant. Larger = better quality, slower & more RAM.",
            "min_speakers": "Lower bound for expected speakers (diarization constraint).",
            "max_speakers": "Upper bound for expected speakers (diarization constraint).",
            "vad_threshold": "Voice activity probability threshold (lower = more segments, higher = stricter).",
        },
        "preprocessing": {
            "noise_reduce": "Apply spectral noise reduction (slow for long audio).",
            "reduction_db": "Approximate aggressiveness (0-40). Higher may introduce artifacts.",
            "voice_enhance": "Apply band-pass filtering + dynamic range compression.",
            "apply_gain": "Loudness normalization toward target_lufs.",
            "target_lufs": "Target loudness (LUFS). Typical podcast: -16 (stereo) / -19 (mono).",
            "remove_silence": "Remove detected silence segments before diarization.",
            "silence_thresh": "Silence threshold dBFS (e.g. -45). Higher (less negative) removes more.",
            "min_silence_len": "Minimum silence length (ms) to qualify for removal.",
        },
        "whisper_decoding": {
            "beam_size": "Beam search width (larger = better accuracy, slower).",
            "best_of": "Number of sampled candidates when not using temperature=0.",
            "whisper_temp": "Starting sampling temperature. 0 = deterministic.",
            "temperature_increment_on_fallback": "Temperature added on each fallback attempt.",
            "compression_ratio_threshold": "Abort & retry if gzip ratio exceeds this.",
            "logprob_threshold": "Abort & retry if avg log-prob below this.",
            "no_speech_threshold": "If no-speech probability exceeds this -> treat as silence.",
            "condition_on_previous_text": "Feed previous segment text as context.",
            "initial_prompt": "Optional priming text or domain vocabulary.",
            "length_penalty": "Adjust preference for longer/shorter outputs in beam search.",
            "patience": "Beam search termination patience.",
            "suppress_blank": "Suppress blank tokens.",
            "suppress_tokens": "Comma list of token IDs to suppress (-1 = library default).",
            "word_timestamps": "Enable per-word timestamps (slower).",
        },
        "control": {
            "keep_cache": "Keep models in memory after request for reuse (faster subsequent calls).",
        },
    }


@mcp.tool()
def transcription_list_whisper_models() -> dict[str, Any]:
    """Return locally available Whisper model names."""
    return {"available_models": available_models()}


# ── Project / Event Journey tools ────────────────────────────────────────


@mcp.tool()
def transcription_list_projects() -> dict[str, Any]:
    """List all transcription projects (event journeys) on disk."""
    projects = _project_store.list_projects()
    return {
        "count": len(projects),
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "language": p.language,
                "location": p.location,
                "n_audios": len(p.audios),
                "n_context_docs": len(p.context_docs),
                "n_narratives": len(p.narrative_ids),
                "qdrant_filter_tag": p.qdrant_filter_tag,
                "updated_at": p.updated_at,
            }
            for p in projects
        ],
    }


@mcp.tool()
def transcription_get_project(project_id: str) -> dict[str, Any]:
    """Return the full project record (audios, references, narratives, context docs)."""
    project = _project_store.load(project_id)
    if not project:
        return {"error": f"project {project_id} not found"}
    data = asdict(project)
    # Augment with reference manifest summaries
    summaries = []
    for cn in project.canonical_names():
        m = _ref_store.load_manifest(cn)
        summaries.append({
            "canonical_name": cn,
            "has_manifest": m is not None,
            "n_references": len([v for v in m.versions if v.type == "reference"]) if m else 0,
            "n_versions": len(m.versions) if m else 0,
        })
    data["references_summary"] = summaries
    return data


@mcp.tool()
def transcription_list_project_references(project_id: str) -> dict[str, Any]:
    """For each audio in a project, list its reference versions."""
    project = _project_store.load(project_id)
    if not project:
        return {"error": f"project {project_id} not found"}
    out = []
    for audio in project.audios:
        refs = _ref_store.load_references(audio.canonical_name)
        out.append({
            "canonical_name": audio.canonical_name,
            "audio_path": audio.audio_path,
            "n_references": len(refs),
            "references": [
                {
                    "title": r.title,
                    "source": r.source,
                    "quality_score": r.quality_score,
                    "n_segments": len(r.content),
                }
                for r in refs
            ],
        })
    return {"project_id": project_id, "audios": out}


@mcp.tool()
def transcription_read_project_context_doc(project_id: str, path: str, max_chars: int = 12000) -> dict[str, Any]:
    """Read a context document attached to a project (limited to attached paths).

    The agent must pass a ``path`` that is registered as one of the project's
    context_docs — this prevents arbitrary filesystem reads.
    """
    project = _project_store.load(project_id)
    if not project:
        return {"error": f"project {project_id} not found"}
    allowed = {d.path for d in project.context_docs}
    if path not in allowed:
        return {"error": "path not attached to this project", "attached": sorted(allowed)}
    if not os.path.isfile(path):
        return {"error": f"file missing on disk: {path}"}
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read(max_chars + 1)
    except OSError as exc:
        return {"error": f"read failed: {exc}"}
    truncated = len(text) > max_chars
    return {
        "path": path,
        "truncated": truncated,
        "content": text[:max_chars],
    }


@mcp.tool()
def transcription_list_project_narratives(project_id: str) -> dict[str, Any]:
    """List narratives linked to a project (resolves via narrative store)."""
    project = _project_store.load(project_id)
    if not project:
        return {"error": f"project {project_id} not found"}
    out = []
    for cn in project.canonical_names():
        for n in _narrative_store.load_narratives(cn):
            out.append({
                "audio_id": n.audio_id,
                "title": n.title,
                "timeline_time": n.timeline_time,
                "source_file": n.source_file,
                "preview": n.text[:300] + ("..." if len(n.text) > 300 else ""),
            })
    return {"project_id": project_id, "count": len(out), "narratives": out}


# API-aligned Project tools


@mcp.tool()
def transcription_list_projects_api() -> dict[str, Any]:
    """Return all projects, aligned with GET /api/projects."""
    projects = _project_store.list_projects()
    return {"projects": [_project_to_dict(project) for project in projects]}


@mcp.tool()
def transcription_get_project_api(project_id: str) -> dict[str, Any]:
    """Return one project, aligned with GET /api/projects/{project_id}."""
    return _project_to_dict(_get_project_or_raise(project_id))


@mcp.tool()
def transcription_create_project_api(
    name: str,
    project_id: str | None = None,
    description: str = "",
    language: str = "es",
    location: str = "",
    audios: list[dict[str, Any]] | None = None,
    narrative_ids: list[str] | None = None,
    context_docs: list[dict[str, Any]] | None = None,
    qdrant_filter_tag: str = "",
) -> dict[str, Any]:
    """Create a project, aligned with POST /api/projects."""
    pid = (project_id or "").strip() or f"proj_{uuid.uuid4().hex[:10]}"
    if _project_store.load(pid):
        raise ValueError(f"Project {pid} already exists")

    project = Project(
        id=pid,
        name=name,
        description=description,
        language=language,
        location=location,
        audios=[ProjectAudio(**item) for item in (audios or [])],
        narrative_ids=[str(item) for item in (narrative_ids or [])],
        context_docs=[ContextDocument(**item) for item in (context_docs or [])],
        qdrant_filter_tag=qdrant_filter_tag,
    )
    _project_store.save(project)
    return _project_to_dict(project)


@mcp.tool()
def transcription_update_project_api(
    project_id: str,
    name: str | None = None,
    description: str | None = None,
    language: str | None = None,
    location: str | None = None,
    qdrant_filter_tag: str | None = None,
) -> dict[str, Any]:
    """Patch a project, aligned with PATCH /api/projects/{project_id}."""
    project = _get_project_or_raise(project_id)

    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    if language is not None:
        project.language = language
    if location is not None:
        project.location = location
    if qdrant_filter_tag is not None:
        project.qdrant_filter_tag = qdrant_filter_tag

    _project_store.save(project)
    return _project_to_dict(project)


@mcp.tool()
def transcription_delete_project_api(project_id: str) -> dict[str, Any]:
    """Delete a project, aligned with DELETE /api/projects/{project_id}."""
    if not _project_store.delete(project_id):
        raise ValueError(f"Project {project_id} not found")
    return {"status": "deleted", "project_id": project_id}


@mcp.tool()
def transcription_add_project_audio_api(
    project_id: str,
    canonical_name: str,
    audio_path: str = "",
    title: str = "",
    recording_datetime: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Attach one audio to a project, aligned with POST /api/projects/{project_id}/audios."""
    project = _get_project_or_raise(project_id)
    if any(audio.canonical_name == canonical_name for audio in project.audios):
        raise ValueError(f"Audio {canonical_name} already linked to project")

    project.audios.append(
        ProjectAudio(
            canonical_name=canonical_name,
            audio_path=audio_path,
            title=title,
            recording_datetime=recording_datetime,
            notes=notes,
        )
    )
    _project_store.save(project)
    return _project_to_dict(project)


@mcp.tool()
def transcription_remove_project_audio_api(project_id: str, canonical_name: str) -> dict[str, Any]:
    """Remove one audio from a project, aligned with DELETE /api/projects/{project_id}/audios/{canonical_name}."""
    project = _get_project_or_raise(project_id)
    before = len(project.audios)
    project.audios = [audio for audio in project.audios if audio.canonical_name != canonical_name]
    if len(project.audios) == before:
        raise ValueError("audio not in project")
    _project_store.save(project)
    return _project_to_dict(project)


@mcp.tool()
def transcription_add_project_context_doc_api(
    project_id: str,
    path: str,
    title: str = "",
    kind: str = "report",
    notes: str = "",
) -> dict[str, Any]:
    """Attach one context document, aligned with POST /api/projects/{project_id}/context_docs."""
    project = _get_project_or_raise(project_id)
    if not os.path.exists(path):
        raise ValueError(f"Path does not exist: {path}")
    if any(doc.path == path for doc in project.context_docs):
        raise ValueError("document already attached")

    project.context_docs.append(ContextDocument(path=path, title=title, kind=kind, notes=notes))
    _project_store.save(project)
    return _project_to_dict(project)


@mcp.tool()
def transcription_remove_project_context_doc_api(project_id: str, path: str) -> dict[str, Any]:
    """Detach one context document, aligned with DELETE /api/projects/{project_id}/context_docs."""
    project = _get_project_or_raise(project_id)
    before = len(project.context_docs)
    project.context_docs = [doc for doc in project.context_docs if doc.path != path]
    if len(project.context_docs) == before:
        raise ValueError("document not attached")
    _project_store.save(project)
    return _project_to_dict(project)


@mcp.tool()
def transcription_add_project_narrative_api(project_id: str, narrative_id: str) -> dict[str, Any]:
    """Link one narrative id, aligned with POST /api/projects/{project_id}/narratives."""
    project = _get_project_or_raise(project_id)
    if narrative_id in project.narrative_ids:
        raise ValueError("narrative already linked")
    project.narrative_ids.append(narrative_id)
    _project_store.save(project)
    return _project_to_dict(project)


# API-aligned Reference tools


@mcp.tool()
def transcription_list_references_api() -> dict[str, Any]:
    """List canonical names, aligned with GET /api/references."""
    return {"canonical_names": _ref_store.list_audio_names()}


@mcp.tool()
def transcription_get_reference_manifest_api(canonical_name: str) -> dict[str, Any]:
    """Return reference manifest, aligned with GET /api/references/{canonical_name}/manifest."""
    canonical = _safe_canonical_name(canonical_name)
    manifest = _ref_store.load_manifest(canonical)
    if manifest is None:
        raise ValueError(f"No manifest for '{canonical}'")
    return asdict(manifest)


@mcp.tool()
def transcription_get_reference_api(canonical_name: str) -> dict[str, Any]:
    """Return references for one canonical audio, aligned with GET /api/references/{canonical_name}."""
    canonical = _safe_canonical_name(canonical_name)
    refs = _ref_store.load_references(canonical)
    manifest = _ref_store.load_manifest(canonical)
    versions_by_title: dict[str, str] = {}
    if manifest is not None:
        for version in manifest.versions:
            versions_by_title[os.path.splitext(version.filename)[0]] = version.filename

    return {
        "canonical_name": canonical,
        "count": len(refs),
        "references": [
            {
                "title": ref.title,
                "filename": versions_by_title.get(ref.title, ref.title + ".json"),
                "audio_id": ref.audio_id,
                "source": ref.source,
                "quality_score": ref.quality_score,
                "segments": len(ref.content),
                "n_segments": len(ref.content),
                "participants": ref.participants,
                "language": ref.language,
                "location": ref.location,
                "recording_datetime": ref.recording_datetime,
            }
            for ref in refs
        ],
    }


@mcp.tool()
def transcription_upload_reference_api(
    canonical_name: str,
    source_path: str,
    quality_score: float = 0.9,
    source: str = "manual_correction",
    notes: str = "",
    filename: str | None = None,
) -> dict[str, Any]:
    """Upload a JSON reference from disk, aligned with POST /api/references/{canonical_name}/upload."""
    canonical = _safe_canonical_name(canonical_name)
    data, base_name = _load_reference_content_or_raise(source_path)

    audio_dir = os.path.join(settings.REFERENCE_DIR, canonical)
    os.makedirs(audio_dir, exist_ok=True)
    safe_name = _normalize_reference_filename(filename or base_name)
    out_path = os.path.join(audio_dir, safe_name)
    shutil.copy2(source_path, out_path)

    _upsert_reference_manifest(
        canonical,
        data,
        filename=safe_name,
        source=source,
        quality_score=float(quality_score),
        notes=notes,
        replace_existing_filename=False,
    )
    return {
        "status": "ok",
        "path": out_path,
        "canonical_name": canonical,
        "filename": safe_name,
        "n_segments": len(data["content"]),
    }


@mcp.tool()
def transcription_link_reference_api(
    canonical_name: str,
    source_path: str,
    quality_score: float = 0.9,
    source: str = "linked",
    notes: str = "",
    copy: bool = False,
) -> dict[str, Any]:
    """Link or copy a JSON reference file, aligned with POST /api/references/{canonical_name}/link."""
    canonical = _safe_canonical_name(canonical_name)
    data, base_name = _load_reference_content_or_raise(source_path)

    audio_dir = os.path.join(settings.REFERENCE_DIR, canonical)
    os.makedirs(audio_dir, exist_ok=True)
    safe_name = _normalize_reference_filename(base_name)
    out_path = os.path.join(audio_dir, safe_name)

    if os.path.lexists(out_path):
        os.remove(out_path)
    if copy:
        shutil.copy2(source_path, out_path)
    else:
        os.symlink(os.path.abspath(source_path), out_path)

    _upsert_reference_manifest(
        canonical,
        data,
        filename=safe_name,
        source=source,
        quality_score=float(quality_score),
        notes=notes,
        replace_existing_filename=True,
    )
    return {
        "status": "ok",
        "path": out_path,
        "canonical_name": canonical,
        "filename": safe_name,
        "linked": not copy,
        "n_segments": len(data["content"]),
    }


@mcp.tool()
def transcription_get_reference_narratives_api(canonical_name: str) -> dict[str, Any]:
    """Return narratives for one canonical audio, aligned with GET /api/references/{canonical_name}/narratives."""
    canonical = _safe_canonical_name(canonical_name)
    narratives = _narrative_store.load_narratives(canonical)
    return {
        "canonical_name": canonical,
        "count": len(narratives),
        "narratives": [
            {
                "audio_id": item.audio_id,
                "title": item.title,
                "timeline_time": item.timeline_time,
                "source_file": item.source_file,
                "preview": (item.text[:300] + "...") if len(item.text) > 300 else item.text,
            }
            for item in narratives
        ],
    }


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for remote connectivity tests."""
    return JSONResponse({"status": "ok", "service": "transcription-meta"})


def main() -> None:
    """Entrypoint for MCP server with configurable transport."""
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8123"))

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
