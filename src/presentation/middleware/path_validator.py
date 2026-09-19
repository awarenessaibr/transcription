"""Path validation middleware — prevents path traversal attacks."""
from __future__ import annotations

import os
from pathlib import Path

# Resolved allowed roots — set once at import time from env or defaults.
_ALLOWED_ROOTS: list[Path] | None = None


def _get_allowed_roots() -> list[Path]:
    global _ALLOWED_ROOTS
    if _ALLOWED_ROOTS is None:
        roots = [
            Path(os.getenv("AUDIO_DIR", "data/audio")).resolve(),
            Path(os.getenv("ORIGINALS_DIR", "data/originals")).resolve(),
            Path(os.getenv("TRANSCRIPT_DIR", "data/transcripts")).resolve(),
        ]

        # Auto-discover _shared/media relative to the repository root.
        _this = Path(__file__).resolve()
        for parent in _this.parents:
            shared_media = parent / "_shared" / "media"
            if shared_media.is_dir():
                roots.append(shared_media.resolve())
                break

        # Agent-MCP session scratch directory — sliced audio lands here.
        # Directory may not exist yet at import time; add root unconditionally.
        roots.append(Path("/tmp/agent-mcp/sessions").resolve())

        # Allow adding extra dirs via env (colon-separated).
        extra = os.getenv("transcription_EXTRA_ALLOWED_DIRS", "")
        if extra:
            for d in extra.split(":"):
                d = d.strip()
                if d:
                    p = Path(d).resolve()
                    if p.is_dir():
                        roots.append(p)
        _ALLOWED_ROOTS = roots
    return _ALLOWED_ROOTS


def validate_file_path(file_path: str) -> Path:
    """Validate that file_path is within allowed directories.

    Raises ValueError if the path escapes allowed roots.
    Raises FileNotFoundError if the file does not exist.
    """
    resolved = Path(file_path).resolve()
    allowed = _get_allowed_roots()

    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
        raise ValueError(
            f"Access denied: path '{file_path}' is outside allowed directories "
            f"(allowed: {[str(r) for r in allowed]})"
        )
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    return resolved
