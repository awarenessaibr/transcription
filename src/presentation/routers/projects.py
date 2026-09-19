"""HTTP router for project / event-journey CRUD."""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.domain.entities.project import ContextDocument, Project, ProjectAudio

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])

_project_store = None
_ref_store = None


def init_projects_router(project_store, ref_store) -> None:
    global _project_store, _ref_store
    _project_store = project_store
    _ref_store = ref_store


# ── Schemas ──────────────────────────────────────────────────────────────


class ProjectAudioIn(BaseModel):
    canonical_name: str
    audio_path: str = ""
    title: str = ""
    recording_datetime: str = ""
    notes: str = ""


class ContextDocumentIn(BaseModel):
    path: str
    title: str = ""
    kind: str = "report"
    notes: str = ""


class ProjectCreate(BaseModel):
    id: str | None = Field(default=None, description="Optional id; auto-generated if omitted.")
    name: str
    description: str = ""
    language: str = "es"
    location: str = ""
    audios: list[ProjectAudioIn] = Field(default_factory=list)
    narrative_ids: list[str] = Field(default_factory=list)
    context_docs: list[ContextDocumentIn] = Field(default_factory=list)
    qdrant_filter_tag: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    language: str | None = None
    location: str | None = None
    qdrant_filter_tag: str | None = None


def _ensure_store():
    if _project_store is None:
        raise HTTPException(status_code=503, detail="Project store not configured")


def _to_dict(project: Project) -> dict:
    data = asdict(project)
    if _ref_store is not None:
        summary: dict[str, list[dict]] = {}
        counts: list[dict] = []
        for cn in project.canonical_names():
            m = _ref_store.load_manifest(cn)
            versions = []
            if m is not None:
                for v in m.versions:
                    if v.type != "reference":
                        continue
                    versions.append({
                        "filename": v.filename,
                        "source": v.source,
                        "quality_score": v.quality_score,
                        "segments": v.segments,
                        "created_at": v.created_at,
                    })
            summary[cn] = versions
            counts.append({
                "canonical_name": cn,
                "has_manifest": m is not None,
                "n_references": len(versions),
                "n_versions": len(m.versions) if m else 0,
            })
        # Dict keyed by canonical_name (UI-friendly) plus a flat counts array
        # for backward compatibility with anything iterating it.
        data["references_summary"] = summary
        data["references_counts"] = counts
    return data


# ── CRUD ─────────────────────────────────────────────────────────────────


@router.get("")
def list_projects():
    _ensure_store()
    return {"projects": [_to_dict(p) for p in _project_store.list_projects()]}


@router.get("/{project_id}")
def get_project(project_id: str):
    _ensure_store()
    p = _project_store.load(project_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return _to_dict(p)


@router.post("")
def create_project(payload: ProjectCreate):
    _ensure_store()
    pid = payload.id or f"proj_{uuid.uuid4().hex[:10]}"
    if _project_store.load(pid):
        raise HTTPException(status_code=409, detail=f"Project {pid} already exists")
    project = Project(
        id=pid,
        name=payload.name,
        description=payload.description,
        language=payload.language,
        location=payload.location,
        audios=[ProjectAudio(**a.model_dump()) for a in payload.audios],
        narrative_ids=list(payload.narrative_ids),
        context_docs=[ContextDocument(**d.model_dump()) for d in payload.context_docs],
        qdrant_filter_tag=payload.qdrant_filter_tag,
    )
    _project_store.save(project)
    return _to_dict(project)


@router.patch("/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate):
    _ensure_store()
    project = _project_store.load(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(project, k, v)
    _project_store.save(project)
    return _to_dict(project)


@router.delete("/{project_id}")
def delete_project(project_id: str):
    _ensure_store()
    if not _project_store.delete(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return {"status": "deleted", "project_id": project_id}


# ── Sub-resource: audios ────────────────────────────────────────────────


@router.post("/{project_id}/audios")
def add_audio(project_id: str, payload: ProjectAudioIn):
    _ensure_store()
    project = _project_store.load(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    if any(a.canonical_name == payload.canonical_name for a in project.audios):
        raise HTTPException(
            status_code=409,
            detail=f"Audio {payload.canonical_name} already linked to project",
        )
    project.audios.append(ProjectAudio(**payload.model_dump()))
    _project_store.save(project)
    return _to_dict(project)


@router.delete("/{project_id}/audios/{canonical_name}")
def remove_audio(project_id: str, canonical_name: str):
    _ensure_store()
    project = _project_store.load(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    before = len(project.audios)
    project.audios = [a for a in project.audios if a.canonical_name != canonical_name]
    if len(project.audios) == before:
        raise HTTPException(status_code=404, detail="audio not in project")
    _project_store.save(project)
    return _to_dict(project)


# ── Sub-resource: context_docs ──────────────────────────────────────────


@router.post("/{project_id}/context_docs")
def add_context_doc(project_id: str, payload: ContextDocumentIn):
    _ensure_store()
    project = _project_store.load(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    if not os.path.exists(payload.path):
        raise HTTPException(status_code=400, detail=f"Path does not exist: {payload.path}")
    if any(d.path == payload.path for d in project.context_docs):
        raise HTTPException(status_code=409, detail="document already attached")
    project.context_docs.append(ContextDocument(**payload.model_dump()))
    _project_store.save(project)
    return _to_dict(project)


@router.delete("/{project_id}/context_docs")
def remove_context_doc(project_id: str, path: str):
    _ensure_store()
    project = _project_store.load(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    before = len(project.context_docs)
    project.context_docs = [d for d in project.context_docs if d.path != path]
    if len(project.context_docs) == before:
        raise HTTPException(status_code=404, detail="document not attached")
    _project_store.save(project)
    return _to_dict(project)


# ── Sub-resource: narratives ────────────────────────────────────────────


class NarrativeRefIn(BaseModel):
    narrative_id: str


@router.post("/{project_id}/narratives")
def add_narrative(project_id: str, payload: NarrativeRefIn):
    _ensure_store()
    project = _project_store.load(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    if payload.narrative_id in project.narrative_ids:
        raise HTTPException(status_code=409, detail="narrative already linked")
    project.narrative_ids.append(payload.narrative_id)
    _project_store.save(project)
    return _to_dict(project)
