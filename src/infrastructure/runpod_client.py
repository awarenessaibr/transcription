"""RunPod Serverless Client — sends audio to the RunPod endpoint for transcription.

Supports both sync (runsync) and async (run + poll) modes.
Audio is sent as base64 to avoid needing files on the RunPod container.
"""
import base64
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# RunPod job status constants
_COMPLETED = "COMPLETED"
_FAILED = "FAILED"
_CANCELLED = "CANCELLED"
_TERMINAL = {_COMPLETED, _FAILED, _CANCELLED}


class RunPodClient:
    """Thin client for RunPod serverless transcription endpoint."""

    def __init__(self, api_key: str, endpoint_id: str, base_url: str = "https://api.runpod.ai/v2"):
        if not api_key:
            raise ValueError("RUNPOD_API_KEY is required")
        if not endpoint_id:
            raise ValueError("RUNPOD_ENDPOINT_ID is required")

        self._api_key = api_key
        self._endpoint_id = endpoint_id
        self._base = f"{base_url.rstrip('/')}/{endpoint_id}"
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    # ── Public API ───────────────────────────────────────────

    def transcribe_file(
        self,
        audio_path: str,
        *,
        language: str = "es",
        model_size: str = "large-v3",
        min_speakers: int = 1,
        max_speakers: int = 2,
        timeout_s: int = 300,
    ) -> dict:
        """Send an audio file to RunPod for full transcription.

        Uses runsync for files under 10 MB, async run+poll otherwise.
        Returns the result dict with 'segments', 'timings', 'params'.
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        audio_b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        file_size_mb = path.stat().st_size / (1024 * 1024)

        payload = {
            "input": {
                "task": "transcribe",
                "audio_base64": audio_b64,
                "filename": path.name,
                "language": language,
                "model_size": model_size,
                "min_speakers": min_speakers,
                "max_speakers": max_speakers,
            }
        }

        logger.info(
            "[runpod-client] sending %s (%.1f MB) lang=%s model=%s",
            path.name, file_size_mb, language, model_size,
        )

        # Small files → runsync (blocks until done, max 300s on RunPod)
        if file_size_mb < 10:
            return self._runsync(payload, timeout_s)

        # Larger files → async run + poll
        return self._run_and_poll(payload, timeout_s)

    def excerpt_file(
        self,
        audio_path: str,
        start: float,
        end: float,
        *,
        min_speakers: int = 1,
        max_speakers: int = 2,
        timeout_s: int = 120,
    ) -> dict:
        """Send an audio excerpt to RunPod for diarization."""
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        audio_b64 = base64.b64encode(path.read_bytes()).decode("utf-8")

        payload = {
            "input": {
                "task": "excerpt",
                "audio_base64": audio_b64,
                "filename": path.name,
                "start": start,
                "end": end,
                "min_speakers": min_speakers,
                "max_speakers": max_speakers,
            }
        }

        return self._runsync(payload, timeout_s)

    # ── Internal ─────────────────────────────────────────────

    def _runsync(self, payload: dict, timeout_s: int) -> dict:
        """Synchronous call — blocks until result or timeout."""
        resp = requests.post(
            f"{self._base}/runsync",
            headers=self._headers,
            json=payload,
            timeout=timeout_s + 30,  # HTTP timeout slightly above RunPod timeout
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == _COMPLETED:
            output = data.get("output", {})
            if "error" in output:
                raise RuntimeError(f"RunPod job error: {output['error']}")
            return output

        if data.get("status") == _FAILED:
            raise RuntimeError(f"RunPod job failed: {data}")

        # If runsync returns IN_QUEUE / IN_PROGRESS, fall through to polling
        job_id = data.get("id")
        if job_id:
            logger.info("[runpod-client] runsync returned %s, polling...", data.get("status"))
            return self._poll(job_id, timeout_s)

        raise RuntimeError(f"Unexpected runsync response: {data}")

    def _run_and_poll(self, payload: dict, timeout_s: int) -> dict:
        """Async run + poll for status."""
        resp = requests.post(
            f"{self._base}/run",
            headers=self._headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        job_id = data.get("id")
        if not job_id:
            raise RuntimeError(f"No job id returned: {data}")

        logger.info("[runpod-client] async job submitted: %s", job_id)
        return self._poll(job_id, timeout_s)

    def _poll(self, job_id: str, timeout_s: int) -> dict:
        """Poll job status until terminal state."""
        deadline = time.monotonic() + timeout_s
        interval = 2.0

        while time.monotonic() < deadline:
            resp = requests.get(
                f"{self._base}/status/{job_id}",
                headers=self._headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")

            if status == _COMPLETED:
                output = data.get("output", {})
                if "error" in output:
                    raise RuntimeError(f"RunPod job error: {output['error']}")
                return output

            if status in _TERMINAL:
                raise RuntimeError(f"RunPod job {status}: {data}")

            logger.debug("[runpod-client] job %s status=%s, waiting %.0fs...", job_id, status, interval)
            time.sleep(interval)
            interval = min(interval * 1.5, 15.0)  # backoff up to 15s

        raise TimeoutError(f"RunPod job {job_id} did not complete within {timeout_s}s")
