"""Unit tests for path validation middleware."""
from __future__ import annotations

import os

import pytest

# Reset the cached roots before importing
import src.presentation.middleware.path_validator as pv


class TestPathValidator:
    def setup_method(self):
        """Reset cached roots so each test can set its own env."""
        pv._ALLOWED_ROOTS = None

    def test_valid_path_within_allowed_root(self, tmp_path):
        allowed_dir = tmp_path / "data" / "originals"
        allowed_dir.mkdir(parents=True)
        test_file = allowed_dir / "test.wav"
        test_file.write_text("fake")

        os.environ["ORIGINALS_DIR"] = str(allowed_dir)
        os.environ["AUDIO_DIR"] = str(tmp_path / "data" / "audio")
        os.environ["TRANSCRIPT_DIR"] = str(tmp_path / "data" / "transcripts")
        pv._ALLOWED_ROOTS = None

        result = pv.validate_file_path(str(test_file))
        assert result == test_file.resolve()

    def test_path_traversal_rejected(self, tmp_path):
        allowed_dir = tmp_path / "data" / "originals"
        allowed_dir.mkdir(parents=True)

        os.environ["ORIGINALS_DIR"] = str(allowed_dir)
        os.environ["AUDIO_DIR"] = str(tmp_path / "data" / "audio")
        os.environ["TRANSCRIPT_DIR"] = str(tmp_path / "data" / "transcripts")
        pv._ALLOWED_ROOTS = None

        with pytest.raises(ValueError, match="outside"):
            pv.validate_file_path(str(allowed_dir / ".." / ".." / "etc" / "passwd"))

    def test_nonexistent_file_raises(self, tmp_path):
        allowed_dir = tmp_path / "data" / "originals"
        allowed_dir.mkdir(parents=True)

        os.environ["ORIGINALS_DIR"] = str(allowed_dir)
        os.environ["AUDIO_DIR"] = str(tmp_path / "data" / "audio")
        os.environ["TRANSCRIPT_DIR"] = str(tmp_path / "data" / "transcripts")
        pv._ALLOWED_ROOTS = None

        with pytest.raises(FileNotFoundError):
            pv.validate_file_path(str(allowed_dir / "nonexistent.wav"))
