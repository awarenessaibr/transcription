"""Tests for the reference-guided pipeline's parameter forwarding.

Selecting a Project in the Pinocchio UI routes the request to ``/api/diarization/transcribe/guided``
(or ``/guided/async``).  Those routes used to declare only a handful of form fields, so every
preprocessing flag and most decoding controls were silently replaced by defaults — and the
async variant dropped *all* of them.  These tests pin the fix at both layers.
"""
from __future__ import annotations

import inspect

import pytest

from src.application.use_cases.guided_transcribe import ReferenceGuidedTranscribeUseCase
from src.presentation.routers import transcription as router_module

# --------------------------------------------------------------------------- fakes


class _Recorder:
    def __init__(self, result=None):
        self.calls: list[tuple] = []
        self.kwargs: list[dict] = []
        self._result = result

    def record(self, *args, **kwargs):
        self.calls.append(args)
        self.kwargs.append(kwargs)
        return self._result


class _FakeASR:
    def __init__(self):
        self.kwargs: list[dict] = []

    def transcribe(self, path, **kwargs):
        self.kwargs.append(kwargs)
        return {"text": "hola que tal", "language": "es"}


class _FakeDiarizer:
    def __init__(self):
        self.kwargs: list[dict] = []

    def diarize(self, path, **kwargs):
        self.kwargs.append(kwargs)
        return []


class _FakeProcessor:
    def __init__(self):
        self.params: list[dict] = []

    def process(self, path, params):
        self.params.append(dict(params))
        return path


class _FakeAudioFiles:
    def convert_to_wav(self, path):
        return path


class _FakeRefStore:
    def __init__(self, references=()):
        self._references = list(references)
        self.guided_outputs: list[tuple] = []

    def load_references(self, canonical_name):
        return list(self._references)

    def save_guided_output(self, canonical_name, segments, metadata=None):
        self.guided_outputs.append((canonical_name, segments, metadata))
        return "ref-id"


class _FakeStore:
    def __init__(self):
        self.saved = []

    def save(self, transcript):
        self.saved.append(transcript)
        return transcript.transcript_id


@pytest.fixture()
def harness():
    asr = _FakeASR()
    diarizer = _FakeDiarizer()
    processor = _FakeProcessor()
    ref_store = _FakeRefStore()
    store = _FakeStore()
    use_case = ReferenceGuidedTranscribeUseCase(
        asr=asr,
        diarizer=diarizer,
        processor=processor,
        store=store,
        audio_files=_FakeAudioFiles(),
        ref_store=ref_store,
        reconciler=None,
    )
    return use_case, asr, diarizer, processor, ref_store, store


async def _run(harness, params: dict):
    use_case, asr, diarizer, processor, ref_store, store = harness
    result = await use_case.execute(audio_path="/tmp/a.wav", canonical_name="aud_1", params=params)
    return result


# --------------------------------------------------------------------------- preprocessing


class TestPreprocessingForwarding:
    @pytest.mark.asyncio
    async def test_preprocessing_flags_reach_the_processor(self, harness):
        await _run(
            harness,
            {
                "noise_reduce": False,
                "reduction_db": 7,
                "voice_enhance": False,
                "enhance_highpass_hz": 80.0,
                "enhance_lowpass_hz": 7500.0,
                "apply_gain": False,
                "target_lufs": -20.0,
                "allow_attenuation": False,
                "remove_silence": False,
                "silence_thresh": -50,
                "min_silence_len": 400,
            },
        )
        _, _, _, processor, _, _ = harness
        assert processor.params == [
            {
                "noise_reduce": False,
                "reduction_db": 7,
                "voice_enhance": False,
                "enhance_highpass_hz": 80.0,
                "enhance_lowpass_hz": 7500.0,
                "apply_gain": False,
                "target_lufs": -20.0,
                "allow_attenuation": False,
                "remove_silence": False,
                "silence_thresh": -50,
                "min_silence_len": 400,
            }
        ]

    @pytest.mark.asyncio
    async def test_absent_preprocessing_flags_fall_back_to_defaults(self, harness):
        await _run(harness, {})
        _, _, _, processor, _, _ = harness
        params = processor.params[0]
        assert params["noise_reduce"] is True
        assert params["reduction_db"] == 25
        assert params["enhance_highpass_hz"] is None
        assert params["enhance_lowpass_hz"] is None


# --------------------------------------------------------------------------- decoding


class TestDecodingForwarding:
    @pytest.mark.asyncio
    async def test_core_decoding_controls_are_forwarded(self, harness):
        await _run(
            harness,
            {
                "language": "es",
                "model_size": "large-v3-turbo",
                "whisper_temp": 0.2,
                "beam_size": 3,
                "best_of": 2,
                "condition_on_previous_text": False,
                "word_timestamps": True,
            },
        )
        _, asr, _, _, _, _ = harness
        kwargs = asr.kwargs[0]
        assert kwargs["language"] == "es"
        assert kwargs["model_size"] == "large-v3-turbo"
        assert kwargs["temperature"] == 0.2
        assert kwargs["beam_size"] == 3
        assert kwargs["best_of"] == 2
        assert kwargs["word_timestamps"] is True

    @pytest.mark.asyncio
    async def test_optional_decoding_controls_are_forwarded_when_supplied(self, harness):
        """These were undeclared on the router, so tuning them in the UI did nothing."""
        await _run(
            harness,
            {
                "compression_ratio_threshold": 2.0,
                "logprob_threshold": -0.8,
                "no_speech_threshold": 0.4,
                "length_penalty": 1.4,
                "patience": 1.5,
                "suppress_blank": False,
                "suppress_tokens": "-1,50364",
            },
        )
        _, asr, _, _, _, _ = harness
        kwargs = asr.kwargs[0]
        assert kwargs["compression_ratio_threshold"] == 2.0
        assert kwargs["logprob_threshold"] == -0.8
        assert kwargs["no_speech_threshold"] == 0.4
        assert kwargs["length_penalty"] == 1.4
        assert kwargs["patience"] == 1.5
        assert kwargs["suppress_blank"] is False
        assert kwargs["suppress_tokens"] == "-1,50364"

    @pytest.mark.asyncio
    async def test_optional_controls_are_omitted_when_absent(self, harness):
        """The adapter's own defaults must stay authoritative when the caller is silent."""
        await _run(harness, {})
        _, asr, _, _, _, _ = harness
        kwargs = asr.kwargs[0]
        for key in (
            "compression_ratio_threshold",
            "logprob_threshold",
            "no_speech_threshold",
            "length_penalty",
            "patience",
            "suppress_blank",
            "suppress_tokens",
        ):
            assert key not in kwargs, key

    @pytest.mark.asyncio
    async def test_caller_prompt_is_used_when_no_reference_exists(self, harness):
        """The router used to drop the operator's initial_prompt entirely."""
        await _run(harness, {"initial_prompt": "LATAM, carabineros, abuse"})
        _, asr, _, _, _, _ = harness
        assert asr.kwargs[0]["initial_prompt"] == "LATAM, carabineros, abuse"


# --------------------------------------------------------------------------- diarization


class TestDiarizationForwarding:
    @pytest.mark.asyncio
    async def test_speaker_bounds_reach_the_diarizer(self, harness):
        await _run(harness, {"min_speakers": 2, "max_speakers": 6, "vad_threshold": 0.4})
        _, _, diarizer, _, _, _ = harness
        assert diarizer.kwargs[0]["min_speakers"] == 2
        assert diarizer.kwargs[0]["max_speakers"] == 6
        assert diarizer.kwargs[0]["vad_threshold"] == 0.4


# --------------------------------------------------------------------------- routing contract


class TestRouterDeclaresTheParameters:
    """A form field the route does not declare is silently discarded by FastAPI."""

    PREPROCESSING = (
        "noise_reduce",
        "reduction_db",
        "voice_enhance",
        "enhance_highpass_hz",
        "enhance_lowpass_hz",
        "apply_gain",
        "allow_attenuation",
        "target_lufs",
        "remove_silence",
        "silence_thresh",
        "min_silence_len",
    )
    DECODING = (
        "beam_size",
        "best_of",
        "whisper_temp",
        "condition_on_previous_text",
        "word_timestamps",
        "compression_ratio_threshold",
        "logprob_threshold",
        "no_speech_threshold",
        "length_penalty",
        "patience",
        "suppress_blank",
        "suppress_tokens",
    )

    @pytest.mark.parametrize(
        "endpoint",
        [
            router_module.diarization_transcribe,
            router_module.diarization_transcribe_async,
            router_module.diarization_transcribe_guided,
            router_module.diarization_transcribe_guided_async,
        ],
        ids=lambda fn: fn.__name__,
    )
    def test_every_transcribe_route_declares_preprocessing_and_decoding(self, endpoint):
        declared = set(inspect.signature(endpoint).parameters)
        missing = [name for name in self.PREPROCESSING + self.DECODING if name not in declared]
        assert not missing, f"{endpoint.__name__} silently drops: {missing}"

    def test_guided_route_accepts_project_and_reference_fields(self):
        declared = set(inspect.signature(router_module.diarization_transcribe_guided).parameters)
        assert {"project_id", "canonical_name", "top_n_references", "initial_prompt"} <= declared

    def test_async_guided_route_reports_a_status_url(self):
        source = inspect.getsource(router_module.diarization_transcribe_guided_async)
        assert "status_url" in source and "job_id" in source
