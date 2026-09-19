"""Unit tests for Chilean Spanish post-processing."""
from src.domain.chilean_spanish import post_process_chilean_spanish


class TestChileanSpanish:
    def test_pal_otro(self):
        assert "pa'l otro" in post_process_chilean_spanish("pal otro lado")

    def test_po(self):
        assert "po'" in post_process_chilean_spanish("ya po")

    def test_weon(self):
        assert "weón" in post_process_chilean_spanish("ese weon")

    def test_si_po(self):
        assert "sí poh" in post_process_chilean_spanish("si po")

    def test_vos(self):
        result = post_process_chilean_spanish("dijo vos")
        assert "vo'" in result

    def test_no_match_unchanged(self):
        text = "Hola, cómo estás?"
        assert post_process_chilean_spanish(text) == text

    def test_empty_string(self):
        assert post_process_chilean_spanish("") == ""

    def test_case_insensitive(self):
        assert "weón" in post_process_chilean_spanish("WEON")
