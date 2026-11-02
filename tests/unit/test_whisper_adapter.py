from __future__ import annotations

from src.infrastructure.whisper_adapter import WhisperASRAdapter


class FakeModel:
    def __init__(self):
        self.kwargs = None

    def transcribe(self, _audio_path, **kwargs):
        self.kwargs = kwargs
        return {
            "text": "hello",
            "language": "en",
            "segments": [{
                "start": 0.0,
                "end": 0.6,
                "text": " hello",
                "words": [
                    {"word": " hello", "start": 0.1, "end": 0.5, "probability": 0.97}
                ]
            }],
        }


class FakeModelManager:
    def __init__(self):
        self.model = FakeModel()

    def get_whisper_model(self, _model_size):
        return self.model


def test_adapter_preserves_word_level_timestamps():
    manager = FakeModelManager()
    adapter = WhisperASRAdapter(manager)

    result = adapter.transcribe("audio.wav", language="en", word_timestamps=True)

    assert manager.model.kwargs["word_timestamps"] is True
    assert result["words"] == [
        {"word": " hello", "start": 0.1, "end": 0.5, "probability": 0.97}
    ]
    assert result["segments"] == [{"start": 0.0, "end": 0.6, "text": "hello"}]


def test_adapter_leaves_words_empty_when_timestamps_are_disabled():
    manager = FakeModelManager()
    adapter = WhisperASRAdapter(manager)

    result = adapter.transcribe("audio.wav", language="en", word_timestamps=False)

    assert manager.model.kwargs["word_timestamps"] is False
    assert result["words"] == []
