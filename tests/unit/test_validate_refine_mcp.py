"""Smoke tests for the validate/refine MCP tool surface.

These tests bypass the FastMCP wire layer and call the underlying tool
functions directly through ``mcp._tool_manager``.  They confirm that the
``audit_transcript`` and ``patch_transcript_segments`` tools are registered
and route to the wired use cases / services produced by ``build_runtime``.

The store is monkey-patched onto a ``tmp_path`` JSON store per-test so the
tests never write into ``data/transcripts/``.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

# Ensure the runtime does not try to load torchaudio for these smoke tests.
os.environ.setdefault("ENABLE_ACOUSTIC_PROBES", "false")

from src.infrastructure.json_store import JSONTranscriptStore
from src.mcp.servers import transcripts_server as srv


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """Swap the module-level _STORE for a JSONTranscriptStore rooted at tmp_path."""
    store = JSONTranscriptStore(str(tmp_path))
    monkeypatch.setattr(srv, "_STORE", store)
    monkeypatch.setattr(srv._RUNTIME, "store_adapter", store)
    return store


def _call_tool(name: str, **kwargs):
    tool = srv.mcp._tool_manager.get_tool(name)
    assert tool is not None, f"tool {name} is not registered"
    result = tool.fn(**kwargs)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return result


def _seed_transcript(store: JSONTranscriptStore) -> str:
    """Write a minimal Transcript JSON via the store and return its id."""
    payload = {
        "transcript_id": "mcp_smoke",
        "segments": [
            {"index": 0, "speaker": "A", "start": 0.0, "end": 1.0, "text": "Hola"},
            {"index": 1, "speaker": "A", "start": 1.0, "end": 2.0, "text": " mundo."},
        ],
        "metadata": {},
        "source_file": "",
        "original_transcript_id": "mcp_smoke",
    }
    target = Path(store._dir) / "mcp_smoke.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return "mcp_smoke"


def test_tools_are_registered():
    names = {t.name for t in srv.mcp._tool_manager.list_tools()}
    assert {"audit_transcript", "patch_transcript_segments", "validate_and_refine_transcript"} <= names


def test_audit_transcript_smoke(tmp_store):
    tid = _seed_transcript(tmp_store)
    out = _call_tool("audit_transcript", transcript_id=tid)
    assert isinstance(out, dict)
    assert out.get("transcript_id") == tid
    assert "anomalies" in out
    assert "counts_by_kind" in out


def test_patch_transcript_segments_smoke(tmp_store):
    tid = _seed_transcript(tmp_store)
    patches = [{"op": "replace_text", "segment_indices": [1], "new_text": "MUNDO"}]
    out = _call_tool(
        "patch_transcript_segments",
        transcript_id=tid,
        patches=patches,
        save_as_new_id=True,
    )
    assert isinstance(out, dict)
    assert out.get("transcript_id_in") == tid
    assert "_patched_" in out.get("transcript_id_out", "")
    assert out.get("patches_applied"), "expected at least one applied patch"
