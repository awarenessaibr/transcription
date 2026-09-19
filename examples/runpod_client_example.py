"""
Example: Call Runpod Serverless Endpoint for Audio Transcription & Diarization
"""
import requests
import base64
import os
from pathlib import Path

# Configuration — set via environment or replace inline
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "YOUR_RUNPOD_API_KEY")
ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "5j22h5dqpbj6kh")
RUNPOD_ENDPOINT = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {RUNPOD_API_KEY}"
}


def call_excerpt_by_path(file_path: str, start: float, end: float, min_speakers: int = 1, max_speakers: int = 2):
    """
    Call diarization excerpt using a server-side file path.
    Note: file_path must exist on the Runpod container filesystem.
    """
    data = {
        "input": {
            "task": "excerpt",
            "file_path": file_path,
            "start": start,
            "end": end,
            "min_speakers": min_speakers,
            "max_speakers": max_speakers
        }
    }
    
    response = requests.post(f"{RUNPOD_ENDPOINT}/runsync", headers=headers, json=data)
    return response.json()


def call_excerpt_with_upload(audio_file_path: str, start: float, end: float, min_speakers: int = 1, max_speakers: int = 2):
    """
    Call diarization excerpt by uploading audio as base64.
    """
    # Read and encode audio file
    with open(audio_file_path, "rb") as f:
        audio_data = f.read()
    
    audio_base64 = base64.b64encode(audio_data).decode("utf-8")
    filename = Path(audio_file_path).name
    
    data = {
        "input": {
            "task": "excerpt",
            "audio_base64": audio_base64,
            "filename": filename,
            "start": start,
            "end": end,
            "min_speakers": min_speakers,
            "max_speakers": max_speakers
        }
    }
    
    response = requests.post(f"{RUNPOD_ENDPOINT}/runsync", headers=headers, json=data)
    return response.json()


def call_transcribe_with_upload(audio_file_path: str, language: str = "es", model_size: str = "large-v3",
                                 min_speakers: int = 1, max_speakers: int = 2):
    """
    Full transcription: upload audio, get diarized + transcribed segments back.
    """
    with open(audio_file_path, "rb") as f:
        audio_data = f.read()

    audio_base64 = base64.b64encode(audio_data).decode("utf-8")
    filename = Path(audio_file_path).name

    data = {
        "input": {
            "task": "transcribe",
            "audio_base64": audio_base64,
            "filename": filename,
            "language": language,
            "model_size": model_size,
            "min_speakers": min_speakers,
            "max_speakers": max_speakers
        }
    }

    response = requests.post(f"{RUNPOD_ENDPOINT}/runsync", headers=headers, json=data)
    return response.json()


# Examples
if __name__ == "__main__":
    print("Example 1: Excerpt diarization using server-side path")
    result = call_excerpt_by_path(
        file_path="/workspace/data/originals/yourfile.wav",
        start=15.0,
        end=30.0,
        min_speakers=1,
        max_speakers=2
    )
    print(result)
    
    print("\n" + "="*60 + "\n")
    
    print("Example 2: Excerpt diarization with file upload")
    result = call_excerpt_with_upload(
        audio_file_path="./local_audio.mp3",
        start=0.0,
        end=15.0,
        min_speakers=1,
        max_speakers=3
    )
    print(result)

    print("\n" + "="*60 + "\n")

    print("Example 3: Full transcription with file upload")
    result = call_transcribe_with_upload(
        audio_file_path="./local_audio.mp3",
        language="es",
        model_size="large-v3",
        min_speakers=1,
        max_speakers=2
    )
    print(result)
