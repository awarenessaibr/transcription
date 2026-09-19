"""HTTP router for reference transcripts and narratives.

Lets clients (UI, agents, MCP) inspect, link, and upload reference transcripts
and narratives that feed the reference-guided transcription pipeline.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile

from src.domain.entities.reference import ManifestVersion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/references", tags=["references"])

_ref_store = None
_narrative_store = None
_reference_dir = ""


def init_references_router(ref_store, narrative_store, reference_dir: str) -> None:
    global _ref_store, _narrative_store, _reference_dir
    _ref_store = ref_store
    _narrative_store = narrative_store
    _reference_dir = reference_dir


def _ensure():
    if _ref_store is None:
        raise HTTPException(status_code=503, detail="Reference store not configured")


def _safe_canonical(canonical_name: str) -> str:
    if not canonical_name or "/" in canonical_name or ".." in canonical_name:
        raise HTTPException(status_code=400, detail="invalid canonical_name")
    return canonical_name


# ── Listing ──────────────────────────────────────────────────────────────


@router.get("")
def list_audio_names():
    _ensure()
    return {"canonical_names": _ref_store.list_audio_names()}


@router.get("/{canonical_name}/manifest")
def get_manifest(canonical_name: str):
    _ensure()
    canonical_name = _safe_canonical(canonical_name)
    manifest = _ref_store.load_manifest(canonical_name)
    if not manifest:
        raise HTTPException(
            status_code=404, detail=f"No manifest for '{canonical_name}'"
        )
    return asdict(manifest)


@router.get("/{canonical_name}")
def get_references(canonical_name: str):
    _ensure()
    canonical_name = _safe_canonical(canonical_name)
    refs = _ref_store.load_references(canonical_name)
    manifest = _ref_store.load_manifest(canonical_name)
    versions_by_title = {}
    if manifest is not None:
        for v in manifest.versions:
            versions_by_title[os.path.splitext(v.filename)[0]] = v.filename
    return {
        "canonical_name": canonical_name,
        "count": len(refs),
        "references": [
            {
                "title": r.title,
                "filename": versions_by_title.get(r.title, r.title + ".json"),
                "audio_id": r.audio_id,
                "source": r.source,
                "quality_score": r.quality_score,
                "segments": len(r.content),
                "n_segments": len(r.content),
                "participants": r.participants,
                "language": r.language,
                "location": r.location,
                "recording_datetime": r.recording_datetime,
            }
            for r in refs
        ],
    }


# ── Upload / link a reference ───────────────────────────────────────────


@router.post("/{canonical_name}/upload")
async def upload_reference(
    canonical_name: str,
    file: UploadFile = File(..., description="Reference transcript JSON file"),
    quality_score: float = Form(0.9),
    source: str = Form("manual_correction"),
    notes: str = Form(""),
):
    """Upload a reference transcript JSON file and register it in the manifest."""
    _ensure()
    canonical_name = _safe_canonical(canonical_name)
    audio_dir = os.path.join(_reference_dir, canonical_name)
    os.makedirs(audio_dir, exist_ok=True)

    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("content"), list):
        raise HTTPException(
            status_code=400,
            detail="reference must be a JSON object with a 'content' list",
        )

    safe_name = (file.filename or "reference.json").replace("/", "_")
    if not safe_name.endswith(".json"):
        safe_name += ".json"
    out_path = os.path.join(audio_dir, safe_name)
    with open(out_path, "wb") as f:
        f.write(raw)

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
    manifest.versions.append(
        ManifestVersion(
            filename=safe_name,
            type="reference",
            source=source,
            quality_score=quality_score,
            segments=len(data["content"]),
            created_at=datetime.now(timezone.utc).isoformat(),
            notes=notes,
        )
    )
    _ref_store.save_manifest(manifest)
    return {
        "status": "ok",
        "path": out_path,
        "canonical_name": canonical_name,
        "filename": safe_name,
        "n_segments": len(data["content"]),
    }


@router.post("/{canonical_name}/link")
def link_reference(
    canonical_name: str,
    payload: dict = Body(..., example={
        "source_path": "data/LA8159_files/main_latam_case_version/aeropuerto_STG_7.json",
        "quality_score": 0.95,
        "source": "la8159_main_case",
        "copy": False,
    }),
):
    """Register an existing JSON file (already on disk) as a reference.

    By default a relative symlink is created; pass ``copy: true`` to copy bytes.
    """
    _ensure()
    canonical_name = _safe_canonical(canonical_name)
    src_path = payload.get("source_path", "")
    if not src_path or not os.path.isfile(src_path):
        raise HTTPException(status_code=400, detail=f"source_path not found: {src_path}")
    quality_score = float(payload.get("quality_score", 0.9))
    source = str(payload.get("source", "linked"))
    notes = str(payload.get("notes", ""))
    do_copy = bool(payload.get("copy", False))

    try:
        with open(src_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"unreadable JSON: {exc}") from exc
    if not isinstance(data.get("content"), list):
        raise HTTPException(status_code=400, detail="JSON missing 'content' list")

    audio_dir = os.path.join(_reference_dir, canonical_name)
    os.makedirs(audio_dir, exist_ok=True)
    base = os.path.basename(src_path)
    safe_name = base if base.endswith(".json") else base + ".json"
    out_path = os.path.join(audio_dir, safe_name)

    if os.path.lexists(out_path):
        os.remove(out_path)
    if do_copy:
        shutil.copy2(src_path, out_path)
    else:
        os.symlink(os.path.abspath(src_path), out_path)

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
    # Replace any prior entry with the same filename
    manifest.versions = [v for v in manifest.versions if v.filename != safe_name]
    manifest.versions.append(
        ManifestVersion(
            filename=safe_name,
            type="reference",
            source=source,
            quality_score=quality_score,
            segments=len(data["content"]),
            created_at=datetime.now(timezone.utc).isoformat(),
            notes=notes,
        )
    )
    _ref_store.save_manifest(manifest)
    return {
        "status": "ok",
        "path": out_path,
        "canonical_name": canonical_name,
        "filename": safe_name,
        "linked": not do_copy,
        "n_segments": len(data["content"]),
    }


# ── Narratives ──────────────────────────────────────────────────────────


@router.get("/{canonical_name}/narratives")
def get_narratives(canonical_name: str):
    _ensure()
    canonical_name = _safe_canonical(canonical_name)
    if _narrative_store is None:
        return {"canonical_name": canonical_name, "narratives": []}
    narrs = _narrative_store.load_narratives(canonical_name)
    return {
        "canonical_name": canonical_name,
        "count": len(narrs),
        "narratives": [
            {
                "audio_id": n.audio_id,
                "title": n.title,
                "timeline_time": n.timeline_time,
                "source_file": n.source_file,
                "preview": (n.text[:300] + "...") if len(n.text) > 300 else n.text,
            }
            for n in narrs
        ],
    }
