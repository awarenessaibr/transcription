"""JSON-backed Project store. Implements ProjectStorePort."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict

from src.domain.entities.project import (
    ContextDocument,
    Project,
    ProjectAudio,
)

logger = logging.getLogger(__name__)


class ProjectStoreAdapter:
    """Filesystem JSON store: data/projects/<id>.json."""

    def __init__(self, base_dir: str = "data/projects"):
        self._base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _path(self, project_id: str) -> str:
        safe = project_id.replace("/", "_").replace("..", "_")
        return os.path.join(self._base_dir, f"{safe}.json")

    def save(self, project: Project) -> str:
        path = self._path(project.id)
        project.touch()
        data = asdict(project)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("[project-store] saved %s (%d audios, %d docs)",
                    path, len(project.audios), len(project.context_docs))
        return path

    def load(self, project_id: str) -> Project | None:
        path = self._path(project_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[project-store] failed to read %s: %s", path, exc)
            return None
        return self._deserialize(data)

    def delete(self, project_id: str) -> bool:
        path = self._path(project_id)
        if not os.path.exists(path):
            return False
        os.remove(path)
        logger.info("[project-store] deleted %s", path)
        return True

    def list_projects(self) -> list[Project]:
        if not os.path.isdir(self._base_dir):
            return []
        out: list[Project] = []
        for fname in sorted(os.listdir(self._base_dir)):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(self._base_dir, fname), encoding="utf-8") as f:
                    data = json.load(f)
                out.append(self._deserialize(data))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("[project-store] skipping %s: %s", fname, exc)
        return out

    @staticmethod
    def _deserialize(data: dict) -> Project:
        audios = [ProjectAudio(**a) for a in data.get("audios", [])]
        docs = [ContextDocument(**d) for d in data.get("context_docs", [])]
        return Project(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            language=data.get("language", "es"),
            location=data.get("location", ""),
            audios=audios,
            narrative_ids=list(data.get("narrative_ids", [])),
            context_docs=docs,
            qdrant_filter_tag=data.get("qdrant_filter_tag", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
