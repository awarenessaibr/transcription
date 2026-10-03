"""Guards for the Pinocchio templates' HTML-escaping discipline.

Segment text is attacker-influenced through several unauthenticated paths
(``POST /api/transcripts/import``, CSV import) and through adversarial audio
that Whisper transcribes verbatim. It is rendered with ``innerHTML`` in the
comparison view, so an unescaped interpolation is a stored-XSS sink -- and in a
file that keeps the operator's RunPod key in ``localStorage``, which turns it
into credential theft rather than a cosmetic bug.

Templates cannot be unit-tested for behaviour here, so these tests assert the
structural invariants that make the rendering safe, and syntax-check the inline
JavaScript (``node --check``) to catch a broken edit. See
docs/REDUCED_CORE_MANIFEST.md section 6.5.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
PINOCCHIO = ["pinocchio.html", "pinocchio-en.html"]

pytestmark = pytest.mark.skipif(
    not (TEMPLATES / "pinocchio.html").exists(), reason="templates not present"
)


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", PINOCCHIO)
def test_comparison_view_escapes_segment_text(name: str) -> None:
    """The comparison renderer must escape segment text before interpolating."""
    src = _read(name)
    assert "var textHtml = text ? escapeHtml(text) :" in src, (
        f"{name}: comparison renderer no longer escapes segment text"
    )
    assert """'<div class=\\"text\\">' + textHtml + '</div></div>';""" in src, (
        f"{name}: textHtml is not the value interpolated into the row"
    )
    # The raw form must be gone.
    assert """'<div class=\\"text\\">' + text + '</div></div>';""" not in src, (
        f"{name}: raw segment text is interpolated again (stored XSS)"
    )


@pytest.mark.parametrize("name", PINOCCHIO)
def test_backend_supplied_filename_is_escaped(name: str) -> None:
    """run.filename reaches innerHTML from a transcript the client can import."""
    src = _read(name)
    assert "escapeHtml(run.filename || " in src, (
        f"{name}: run.filename is interpolated into innerHTML unescaped"
    )
    assert "<td>' + (run.filename || " not in src, (
        f"{name}: unescaped run.filename sink is back"
    )


@pytest.mark.parametrize("name", PINOCCHIO)
def test_setstatus_escapes_its_message(name: str) -> None:
    """setStatus receives server-derived text, including exception messages."""
    src = _read(name)
    assert """'">' + escapeHtml(text) + '</span><span id="elapsed" style=""" in src, (
        f"{name}: setStatus interpolates its message unescaped"
    )


@pytest.mark.parametrize("name", PINOCCHIO)
def test_escape_html_handles_quotes(name: str) -> None:
    """Quote-safe escaping is required for attribute-context interpolation."""
    src = _read(name)
    m = re.search(r"function escapeHtml\(value\)\s*\{(.*?)\n\s*\}", src, re.S)
    assert m, f"{name}: escapeHtml not found"
    body = m.group(1)
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert entity in body, f"{name}: escapeHtml does not produce {entity}"


@pytest.mark.parametrize(
    "name",
    ["pinocchio.html", "pinocchio-en.html", "revision.html", "revision-en.html"],
)
def test_inline_javascript_parses(name: str) -> None:
    """A malformed template edit should fail here, not in the browser."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    src = _read(name)
    blocks = [
        m.group(1)
        for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.S | re.I)
    ]
    assert blocks, f"{name}: no inline script blocks found (regex drift?)"
    for i, block in enumerate(blocks):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(block)
            path = fh.name
        try:
            res = subprocess.run([node, "--check", path], capture_output=True, text=True)
        finally:
            Path(path).unlink(missing_ok=True)
        assert res.returncode == 0, (
            f"{name}: inline script block {i} has a syntax error:\n{res.stderr[:400]}"
        )
