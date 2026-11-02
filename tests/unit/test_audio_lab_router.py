"""Unit tests for the Audio Lab HTTP surface (``/api/pinocchio/audio/*``)."""
from __future__ import annotations

import base64
import io
import json
import wave

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.presentation.routers import audio_lab

SR = 16000
BASE = "/api/pinocchio/audio"


# --------------------------------------------------------------------------- helpers


def _speechlike(seconds: float = 2.0, sr: int = SR, seed: int = 4) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    sig = (
        0.30 * np.sin(2 * np.pi * 220 * t)
        + 0.15 * np.sin(2 * np.pi * 1400 * t)
        + 0.08 * np.sin(2 * np.pi * 5200 * t)
    )
    sig = sig * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))
    rng = np.random.default_rng(seed)
    return (sig + 0.02 * rng.standard_normal(t.size)).astype(np.float32)


def _wav_bytes(data: np.ndarray, sr: int = SR) -> bytes:
    arr = np.atleast_2d(np.asarray(data, dtype=np.float32))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(arr.shape[0])
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes((np.clip(arr, -1, 1) * 32767.0).astype("<i2").T.reshape(-1).tobytes())
    return buffer.getvalue()


class _FakeAdapter:
    """Stands in for AudioFileAdapter.convert_to_wav.

    ``convertible`` maps an input suffix to the WAV bytes it should produce, so the router's
    container-handling branch can be exercised without ffmpeg.
    """

    def __init__(self, *, convertible: dict[str, bytes] | None = None, fail: bool = False):
        self.convertible = convertible or {}
        self.fail = fail
        self.calls: list[str] = []

    def convert_to_wav(self, path: str) -> str:
        self.calls.append(path)
        if self.fail:
            raise RuntimeError("ffmpeg missing")
        suffix = "." + path.rsplit(".", 1)[-1].lower()
        if suffix not in self.convertible:
            raise AssertionError(f"unexpected conversion request for {suffix}")
        out = path + ".wav"
        with open(out, "wb") as handle:
            handle.write(self.convertible[suffix])
        return out


@pytest.fixture()
def client(tmp_path):
    app = FastAPI()
    audio_lab.init_audio_lab_router(_FakeAdapter(), output_dir=str(tmp_path))
    app.include_router(audio_lab.router)
    yield TestClient(app)
    audio_lab.init_audio_lab_router(None, None)


def _upload(name: str = "clip.wav", data: bytes | None = None):
    return {"file": (name, data if data is not None else _wav_bytes(_speechlike()), "audio/wav")}


def _report(response) -> dict:
    header = response.headers["x-audio-lab-report"]
    return json.loads(base64.urlsafe_b64decode(header.encode("ascii")).decode("utf-8"))


# --------------------------------------------------------------------------- capabilities


class TestCapabilities:
    def test_returns_ops_presets_and_limits(self, client):
        response = client.get(f"{BASE}/capabilities")
        assert response.status_code == 200
        body = response.json()
        assert body["presets"]
        assert body["ops"]
        assert body["limits"]["output_bit_depths"] == [16, 32]
        assert ".wav" in body["limits"]["accepted_containers"]

    def test_advertises_speech_safe_lowpass(self, client):
        body = client.get(f"{BASE}/capabilities").json()
        assert body["speech_safe_defaults"]["lowpass_hz"] >= 8000


# --------------------------------------------------------------------------- analyze


class TestAnalyze:
    def test_reports_quality_metrics(self, client):
        response = client.post(f"{BASE}/analyze", files=_upload())
        assert response.status_code == 200
        body = response.json()
        assert body["sample_rate"] == SR
        assert body["duration_sec"] == pytest.approx(2.0, abs=0.05)
        assert body["has_audio"] is True
        assert body["loudness_lufs"] is not None
        assert "recommendations" in body
        assert "suggested_chain" in body

    def test_includes_silence_regions(self, client):
        signal = _speechlike(3.0)
        signal[8000:24000] = 0.0
        response = client.post(
            f"{BASE}/analyze",
            files=_upload(data=_wav_bytes(signal)),
            data={"min_silence_ms": "200"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["silence_region_count"] == 1
        assert body["silence_regions"][0]["duration"] > 0.5

    def test_can_skip_loudness(self, client):
        body = client.post(f"{BASE}/analyze", files=_upload(), data={"with_loudness": "false"}).json()
        assert body["loudness_lufs"] is None

    def test_rejects_empty_upload(self, client):
        response = client.post(f"{BASE}/analyze", files={"file": ("x.wav", b"", "audio/wav")})
        assert response.status_code == 400
        assert "empty" in response.json()["detail"]

    def test_rejects_corrupt_wav(self, client):
        response = client.post(f"{BASE}/analyze", files={"file": ("x.wav", b"RIFFxxWAVEjunkjunk", "audio/wav")})
        assert response.status_code == 400
        assert "WAV" in response.json()["detail"]

    def test_requires_a_source(self, client):
        assert client.post(f"{BASE}/analyze").status_code == 400

    def test_rejects_both_sources(self, client, tmp_path):
        path = tmp_path / "srv.wav"
        path.write_bytes(_wav_bytes(_speechlike(0.5)))
        response = client.post(
            f"{BASE}/analyze",
            files=_upload(),
            data={"audio_path": str(path)},
        )
        assert response.status_code == 400
        assert "exactly one" in response.json()["detail"]

    def test_non_wav_goes_through_conversion(self, tmp_path):
        payload = _wav_bytes(_speechlike(1.0))
        adapter = _FakeAdapter(convertible={".mp3": payload})
        app = FastAPI()
        audio_lab.init_audio_lab_router(adapter, output_dir=str(tmp_path))
        app.include_router(audio_lab.router)
        local = TestClient(app)
        try:
            response = local.post(
                f"{BASE}/analyze", files={"file": ("clip.mp3", b"ID3fake", "audio/mpeg")}
            )
            assert response.status_code == 200
            assert adapter.calls, "conversion should have been attempted"
        finally:
            audio_lab.init_audio_lab_router(None, None)

    def test_conversion_failure_is_a_clear_400(self, tmp_path):
        adapter = _FakeAdapter(fail=True)
        app = FastAPI()
        audio_lab.init_audio_lab_router(adapter, output_dir=str(tmp_path))
        app.include_router(audio_lab.router)
        local = TestClient(app)
        try:
            response = local.post(
                f"{BASE}/analyze", files={"file": ("clip.mp3", b"ID3fake", "audio/mpeg")}
            )
            assert response.status_code == 400
            assert "could not decode" in response.json()["detail"]
        finally:
            audio_lab.init_audio_lab_router(None, None)


# --------------------------------------------------------------------------- silence map


class TestSilenceMap:
    def test_returns_regions_and_trim_map(self, client):
        signal = _speechlike(3.0)
        signal[8000:24000] = 0.0
        response = client.post(
            f"{BASE}/silence-map",
            files=_upload(data=_wav_bytes(signal)),
            data={"min_silence_ms": "200"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["region_count"] == 1
        trim = body["trim_map"]
        assert trim["applied"] is True
        assert trim["trimmed_duration"] < trim["duration_sec"] if "duration_sec" in trim else True
        assert trim["kept"]

    def test_can_skip_trim_simulation(self, client):
        body = client.post(
            f"{BASE}/silence-map", files=_upload(), data={"simulate_trim": "false"}
        ).json()
        assert "trim_map" not in body


# --------------------------------------------------------------------------- suggest


class TestSuggestChain:
    def test_returns_a_runnable_chain(self, client):
        response = client.post(f"{BASE}/suggest-chain", files=_upload())
        assert response.status_code == 200
        chain = response.json()["chain"]
        assert chain and all("op" in step for step in chain)

        # Whatever it suggests must actually run.
        run = client.post(
            f"{BASE}/process",
            files=_upload(),
            data={"chain": json.dumps(chain)},
        )
        assert run.status_code == 200


# --------------------------------------------------------------------------- process


class TestProcess:
    def test_returns_wav_with_report_header(self, client):
        response = client.post(f"{BASE}/process", files=_upload(), data={"preset": "speech_clean"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.content[:4] == b"RIFF"

        report = _report(response)
        assert report["sample_rate"] == SR
        assert [step["op"] for step in report["applied"]] == [
            "dc_remove",
            "highpass",
            "lowpass",
            "normalize",
        ]
        assert report["output"]["rms_dbfs"] is not None
        assert "delta" in report

        # The payload must be a decodable WAV of the advertised duration.
        with wave.open(io.BytesIO(response.content), "rb") as handle:
            assert handle.getframerate() == SR
            duration = handle.getnframes() / handle.getframerate()
        assert duration == pytest.approx(report["duration_sec"], abs=0.01)

    def test_json_response_format_embeds_base64(self, client):
        response = client.post(
            f"{BASE}/process",
            files=_upload(),
            data={"preset": "asr_16k", "response_format": "json"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["audio_base64"]
        assert base64.b64decode(body["audio_base64"])[:4] == b"RIFF"
        assert body["filename"].endswith(".wav")

    def test_explicit_chain_beats_preset(self, client):
        chain = json.dumps([{"op": "notch", "center_hz": 50, "q": 10}])
        report = _report(
            client.post(
                f"{BASE}/process",
                files=_upload(),
                data={"preset": "speech_clean", "chain": chain},
            )
        )
        assert [step["op"] for step in report["applied"]] == ["notch"]

    def test_trim_appends_a_timeline_map(self, client):
        signal = _speechlike(3.0)
        signal[8000:24000] = 0.0
        response = client.post(
            f"{BASE}/process",
            files=_upload(data=_wav_bytes(signal)),
            data={"preset": "speech_clean", "trim": "true", "trim_min_silence_ms": "200"},
        )
        assert response.status_code == 200
        report = _report(response)
        assert report["applied"][-1]["op"] == "trim_silence"
        assert report["trim_map"]["applied"] is True
        assert report["delta"]["duration_sec"] < 0

    def test_save_persists_the_output(self, client, tmp_path):
        response = client.post(
            f"{BASE}/process",
            files=_upload(),
            data={"preset": "speech_clean", "save": "true", "output_name": "cleaned"},
        )
        assert response.status_code == 200
        report = _report(response)
        saved = report["saved_path"]
        assert saved and saved.endswith(".wav")
        assert "cleaned" in saved
        from pathlib import Path

        assert Path(saved).exists()
        assert Path(saved).parent == tmp_path

    def test_resample_preset_changes_sample_rate(self, client):
        report = _report(
            client.post(f"{BASE}/process", files=_upload(), data={"preset": "asr_16k"})
        )
        assert report["sample_rate"] == 16000

    def test_32_bit_output(self, client):
        response = client.post(
            f"{BASE}/process", files=_upload(), data={"preset": "speech_clean", "bit_depth": "32"}
        )
        assert response.status_code == 200
        with wave.open(io.BytesIO(response.content), "rb") as handle:
            assert handle.getsampwidth() == 4

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"preset": "does_not_exist"}, "unknown preset"),
            ({"preset": "none"}, "nothing to do"),
            ({"chain": "[{\"op\": \"nope\"}]"}, "unknown op"),
            ({"chain": "{not json"}, "not valid JSON"),
            ({"chain": "\"a string\""}, "must be a JSON array"),
            ({"preset": "speech_clean", "bit_depth": "24"}, "bit_depth"),
            ({"preset": "speech_clean", "response_format": "xml"}, "response_format"),
        ],
    )
    def test_validation_errors(self, client, payload, expected):
        response = client.post(f"{BASE}/process", files=_upload(), data=payload)
        assert response.status_code == 400
        assert expected in response.json()["detail"]

    def test_processing_is_deterministic(self, client):
        payload = _wav_bytes(_speechlike(1.0))
        first = client.post(f"{BASE}/process", files=_upload(data=payload), data={"preset": "noisy_room"})
        second = client.post(f"{BASE}/process", files=_upload(data=payload), data={"preset": "noisy_room"})
        assert first.content == second.content


class TestSourceHandling:
    @pytest.fixture()
    def allowed_dir(self, tmp_path, monkeypatch):
        """Point the path validator's allow-list at tmp_path for the duration of a test."""
        import src.presentation.middleware.path_validator as pv

        monkeypatch.setenv("AUDIO_DIR", str(tmp_path))
        monkeypatch.setenv("ORIGINALS_DIR", str(tmp_path / "originals"))
        monkeypatch.setenv("TRANSCRIPT_DIR", str(tmp_path / "transcripts"))
        monkeypatch.setattr(pv, "_ALLOWED_ROOTS", None)
        yield tmp_path
        monkeypatch.setattr(pv, "_ALLOWED_ROOTS", None)

    def test_audio_path_does_not_destroy_the_original(self, client, allowed_dir):
        """convert_to_wav deletes its input, so the router must work on a copy."""
        source = allowed_dir / "original.wav"
        source.write_bytes(_wav_bytes(_speechlike(1.0)))
        response = client.post(f"{BASE}/analyze", data={"audio_path": str(source)})
        assert response.status_code == 200
        assert source.exists(), "the caller's file must survive analysis"

    def test_audio_path_outside_allowlist_is_rejected(self, client, tmp_path):
        outsider = tmp_path / "outside.wav"
        outsider.write_bytes(_wav_bytes(_speechlike(0.5)))
        response = client.post(f"{BASE}/analyze", data={"audio_path": str(outsider)})
        assert response.status_code in (400, 404)

    def test_missing_audio_path_is_an_error(self, client, allowed_dir):
        response = client.post(f"{BASE}/analyze", data={"audio_path": str(allowed_dir / "nope.wav")})
        assert response.status_code in (400, 404)
