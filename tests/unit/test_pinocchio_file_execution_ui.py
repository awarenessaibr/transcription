"""Structural guards for the Pinocchio `File & Execution` surface and the Audio Lab panel.

Templates cannot be behaviour-tested here, so these assert the invariants that make the
configuration path correct:

* every UI control that is meant to reach the server uses the server's **exact** form-field
  name (FastAPI discards undeclared multipart fields with a 200 OK, so a typo is silent);
* the guided-async `job_id` response is handled rather than rendered as an empty transcript;
* the Critical Configuration card and the Settings modal no longer disagree;
* the Audio Lab is present, wired to the right endpoints, and defaults to a speech-safe
  band-pass.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
PINOCCHIO = TEMPLATES / "pinocchio-en.html"

pytestmark = pytest.mark.skipif(not PINOCCHIO.exists(), reason="template not present")


@pytest.fixture(scope="module")
def src() -> str:
    return PINOCCHIO.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Configuration field names
# ---------------------------------------------------------------------------

#: UI key -> the Form field the backend actually declares.  A mismatch here means the value is
#: silently thrown away by FastAPI.
SERVER_FIELD_NAMES = {
    "temperature_increment_on_fallback": "temperature_increment_on_fallback",
    "compression_ratio_threshold": "compression_ratio_threshold",
    "logprob_threshold": "logprob_threshold",
    "enhance_highpass_hz": "enhance_highpass_hz",
    "enhance_lowpass_hz": "enhance_lowpass_hz",
    "allow_attenuation": "allow_attenuation",
    "suppress_blank": "suppress_blank",
    "suppress_tokens": "suppress_tokens",
    "keep_cache": "keep_cache",
    "skip_diarization": "skip_diarization",
}

#: The wrong names that used to be sent.  They match no Form declaration anywhere.
BOGUS_FIELD_NAMES = ("temp_inc", "comp_ratio", "logprob")


class TestBuildConfigFieldNames:
    def test_correct_names_are_sent(self, src):
        block = _build_config_block(src)
        for name in SERVER_FIELD_NAMES:
            assert re.search(rf"\b{name}\s*:", block), f"buildConfig does not send {name}"

    @pytest.mark.parametrize("bogus", BOGUS_FIELD_NAMES)
    def test_bogus_names_are_not_sent_as_top_level_keys(self, src, bogus):
        block = _build_config_block(src)
        assert not re.search(rf"^\s*{bogus}\s*:", block, re.M), (
            f"buildConfig still sends the undeclared field '{bogus}'"
        )

    def test_legacy_aliases_still_apply_from_saved_suggestions(self, src):
        """Saved suggestion payloads use the old short names; they must keep working."""
        mapping = _suggestion_mapping_block(src)
        for alias in BOGUS_FIELD_NAMES:
            assert re.search(rf"\b{alias}\s*:\s*\[", mapping), (
                f"the '{alias}' alias was dropped from applySuggestionObject"
            )

    def test_band_pass_edges_are_sent_explicitly(self, src):
        block = _build_config_block(src)
        assert "cfg_enhance_highpass" in block
        assert "cfg_enhance_lowpass" in block


class TestSettingsModalControls:
    @pytest.mark.parametrize(
        "element_id",
        [
            "cfg_enhance_highpass",
            "cfg_enhance_lowpass",
            "cfg_allow_attenuation",
            "cfg_suppress_blank",
            "cfg_suppress_tokens",
            "cfg_keep_cache",
            "cfg_skip_diarization",
        ],
    )
    def test_control_exists(self, src, element_id):
        assert f'id="{element_id}"' in src, f"{element_id} missing from the Settings modal"

    def test_speech_safe_band_defaults(self, src):
        assert 'id="cfg_enhance_highpass" type="number" value="60"' in src
        assert 'id="cfg_enhance_lowpass" type="number" value="8000"' in src

    def test_reduction_control_is_labelled_as_a_strength_not_decibels(self, src):
        assert "Reduction Strength (0–40, not dB)" in src


class TestCriticalAndModalAgree:
    def test_reverse_sync_exists(self, src):
        assert "function syncCriticalFromCfg()" in src
        assert "const CFG_TO_CRITICAL" in src

    def test_all_eight_shadowed_fields_are_synced(self, src):
        block = re.search(r"const CFG_TO_CRITICAL = \{(.*?)\};", src, re.S)
        assert block, "CFG_TO_CRITICAL not found"
        for field in (
            "cfg_language",
            "cfg_model_size",
            "cfg_min_speakers",
            "cfg_max_speakers",
            "cfg_vad_threshold",
            "cfg_remove_silence",
            "cfg_noise_reduce",
            "cfg_word_timestamps",
        ):
            assert field in block.group(1), f"{field} is still shadowed by the critical panel"

    def test_save_and_load_both_sync(self, src):
        save = re.search(r"if \(saveCfgBtn\) saveCfgBtn\.onclick = function \(\) \{(.*?)\n      \};", src, re.S)
        load = re.search(r"if \(loadCfgBtn\) loadCfgBtn\.onclick = function \(\) \{(.*?)\n      \};", src, re.S)
        assert save and "syncCriticalFromCfg()" in save.group(1), "Save Config does not sync"
        assert load and "syncCriticalFromCfg()" in load.group(1), "Load Config does not sync"


class TestWordTimestampExport:
    def test_word_timestamps_are_enabled_by_default(self, src):
        assert '<select id="criticalWordTimestamps">\n                <option selected>true</option>' in src
        assert '<select id="cfg_word_timestamps">\n                <option selected>true</option>' in src

    def test_export_zip_contains_word_timestamp_json_and_csv(self, src):
        assert "exportBase + '_word_timestamps.json'" in src
        assert "exportBase + '_word_timestamps.csv'" in src
        assert "segment_index,speaker,word,start,end,probability" in src
        assert "word_timestamp_count: 0" in src


# ---------------------------------------------------------------------------
# Async jobs
# ---------------------------------------------------------------------------


class TestAsyncJobHandling:
    def test_job_detection_helper_exists(self, src):
        assert "function isAsyncJobResponse(data)" in src

    def test_poller_uses_the_status_endpoint(self, src):
        assert "/api/transcripts/status/" in src
        assert "async function awaitTranscriptionJob(" in src

    def test_transcribe_local_awaits_jobs(self, src):
        block = re.search(r"async function transcribeLocal\(file, config\) \{(.*?)\n        \}", src, re.S)
        assert block, "transcribeLocal not found"
        assert "isAsyncJobResponse(data)" in block.group(1), (
            "transcribeLocal still treats a job_id response as a finished transcript"
        )
        assert "awaitTranscriptionJob(" in block.group(1)

    def test_progress_updates_from_job_payload(self, src):
        assert "function applyJobProgress(job)" in src
        assert "job.stage" in src and "job.progress" in src


# ---------------------------------------------------------------------------
# Audio Lab panel
# ---------------------------------------------------------------------------


class TestAudioLabPanel:
    def test_endpoints_are_used(self, src):
        for endpoint in ("/capabilities", "/analyze", "/process", "/suggest-chain"):
            assert endpoint in src, f"the Audio Lab never calls {endpoint}"
        assert "/api/pinocchio/audio" in src

    @pytest.mark.parametrize(
        "element_id",
        [
            "audioLabSection",
            "audioLabContent",
            "audioLabStatus",
            "labPreset",
            "labHighpass",
            "labLowpass",
            "labDenoise",
            "labDereverb",
            "labNormalize",
            "labPeakCeiling",
            "labResample",
            "labMono",
            "labTrim",
            "labAnalyzeBtn",
            "labSuggestBtn",
            "labProcessBtn",
            "labApplyBtn",
            "labDownloadBtn",
            "labTranscribeBtn",
            "labRevertBtn",
            "labReportChips",
            "labReportPre",
        ],
    )
    def test_control_exists(self, src, element_id):
        assert f'id="{element_id}"' in src, f"{element_id} missing from the Audio Lab panel"

    def test_panel_lives_inside_the_execution_column(self, src):
        """It must sit between File & Execution and the Speakers card in the left column."""
        exec_idx = src.index('<h3>File &amp; Execution</h3>')
        lab_idx = src.index('id="audioLabSection"')
        speakers_idx = src.index('id="speakerResolveSection"')
        assert exec_idx < lab_idx < speakers_idx

    def test_defaults_are_speech_safe(self, src):
        assert 'id="labHighpass" type="number" value="60"' in src
        assert 'id="labLowpass" type="number" value="8000"' in src

    def test_reports_the_historical_band_pass_problem(self, src):
        assert "300–3400 Hz" in src or "300-3400 Hz" in src

    def test_chain_builder_matches_the_server_op_names(self, src):
        block = re.search(r"function buildChain\(\) \{(.*?)\n      \}", src, re.S)
        assert block, "buildChain not found"
        body = block.group(1)
        for op in (
            "dc_remove",
            "highpass",
            "lowpass",
            "spectral_denoise",
            "dereverb",
            "resample",
            "to_mono",
            "normalize",
            "trim_silence",
        ):
            assert f"op: '{op}'" in body, f"buildChain never emits {op}"

    def test_honours_the_server_supplied_preset_catalogue(self, src):
        assert "state.capabilities.presets" in src
        assert "applyPreset(" in src

    def test_uses_the_session_bridge_instead_of_poking_globals(self, src):
        assert "window.__pinocchioBridge" in src
        assert "getCurrentFile" in src and "setCurrentFile" in src

    def test_download_and_apply_are_guarded(self, src):
        block = re.search(r"function updateButtons\(\) \{(.*?)\n      \}", src, re.S)
        assert block, "updateButtons not found"
        assert "hasProcessed" in block.group(1)

    def test_report_text_is_escaped_before_rendering(self, src):
        """Every interpolation of report text must go through escapeHtml."""
        assert "function escapeHtml(value)" in src
        assert "escapeHtml(tip)" in src


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_config_block(src: str) -> str:
    block = re.search(r"function buildConfig\(\) \{(.*?)\n        \}", src, re.S)
    assert block, "buildConfig() not found"
    return block.group(1)


def _suggestion_mapping_block(src: str) -> str:
    block = re.search(r"var mapping = \{(.*?)\n          \};", src, re.S)
    assert block, "applySuggestionObject mapping not found"
    return block.group(1)
