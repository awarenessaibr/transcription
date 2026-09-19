# RunPod Pod Template for transcription-transcription

This document describes the recommended RunPod pod template for the `transcription-transcription` service, optimized for the RunPod serverless GPU deployment used by this repository.

## Template metadata

- Name: `transcription-serverless`
- Visibility: Public template
- Availability: Available to all users on the team
- Type: RunPod serverless GPU endpoint
- Compute type: GPU
- Recommended GPUs: `NVIDIA RTX A6000` (48GB), or `NVIDIA RTX A5000` / `A4500` for lower cost
- GPU count: `1`

## Container image

- Image: `docker.io/leandrodisconzi/transcription-transcription:serverless`
- Validation: public Docker Hub image; verify with `docker pull docker.io/leandrodisconzi/transcription-transcription:serverless`

## Startup command

- `python -u src/runpod_handler.py`

## Storage

- Container disk: `20 GiB`
  - Temporary runtime disk for model caches, temporary audio, and job scratch space.

- Volume disk: `40 GiB`
  - Persistent storage mounted to `/workspace` for repo files, uploads, generated transcripts, and workspace state.
  - This storage is erased when the Pod is stopped or terminated.

- Volume mount path: `/workspace`
  - The repo and runtime data should live under `/workspace` to match the Dockerfile and entrypoint expectations.

## Recommended environment variables

Sensitive values should be stored as RunPod secrets and injected via environment variables.

### Required secrets

- `PYANNOTE_AUTH_TOKEN`
  - Hugging Face token for `pyannote/speaker-diarization-3.1`
  - This is the primary token used by the service.

- `HUGGINGFACE_HUB_TOKEN`
  - Optional alias for Hugging Face API access.
  - Recommended to set if the service downloads models from Hugging Face.

### Optional token aliases

- `HF_TOKEN`
- `use_auth_token`

These aliases are supported by the code and can be set to the same secret value as `PYANNOTE_AUTH_TOKEN`.

### Optional service secrets

- `ANTHROPIC_API_KEY`
  - Required only if you enable AI analysis routes via Anthropic-compatible providers.

- `DEEPSEEK_API_KEY`
  - Required only if using DeepSeek analysis or reconciliation.

- `QDRANT_API_KEY`
  - Required only if using Qdrant semantic search with an authenticated Qdrant instance.

### Non-sensitive runtime configuration

- `PRELOAD_MODELS=false`
  - Set to `true` only when you want startup model warm-up to reduce first-request latency.

- `AUDIO_DIR=/workspace/data/audio`
- `ORIGINALS_DIR=/workspace/data/originals`
- `TRANSCRIPT_DIR=/workspace/data/transcripts`
- `REFERENCE_DIR=/workspace/data/transcripts_by_audio`
- `PROJECTS_DIR=/workspace/data/projects`

- `CORS_ORIGINS=http://localhost:3000,http://localhost:8049`
  - Adjust to your frontend domain(s) as needed.

### Notes

- `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` are deployment-time values used by setup scripts, not required by the runtime service inside the Pod.
- If you need larger model cache or temporary workspace capacity, increase container disk to `30 GiB` or `40 GiB`.

## Example RunPod setup

The repository already includes `setup_runpod_endpoint.sh`, which updates a RunPod endpoint using the configured container image and environment secrets.

Example deployment values:

- `imageName`: `leandrodisconzi/transcription-transcription:serverless`
- `dockerArgs`: `python -u src/runpod_handler.py`
- `containerDiskInGb`: `20`
- `gpuTypeId`: `NVIDIA RTX A6000`
- `gpuCount`: `1`
- `ports`: `8049/http`

### Example GraphQL mutation payload

```json
{
  "query": "mutation {\n      updateEndpointTemplate(\n        input: {\n          endpointId: \"<YOUR_ENDPOINT_ID>\",\n          imageName: \"leandrodisconzi/transcription-transcription:serverless\",\n          dockerArgs: \"python -u src/runpod_handler.py\",\n          containerDiskInGb: 20,\n          ports: \"8049/http\",\n          env: [\n            { key: \"PYANNOTE_AUTH_TOKEN\", value: \"{{PYANNOTE_AUTH_TOKEN}}\" },\n            { key: \"HF_TOKEN\", value: \"{{PYANNOTE_AUTH_TOKEN}}\" },\n            { key: \"HUGGINGFACE_HUB_TOKEN\", value: \"{{HUGGINGFACE_HUB_TOKEN}}\" },\n            { key: \"use_auth_token\", value: \"{{PYANNOTE_AUTH_TOKEN}}\" }\n          ],\n          gpuTypeId: \"NVIDIA RTX A6000\",\n          gpuCount: 1\n        }
      ) { id name imageName }
    }"
}
```

## Usage guidance

- Use this template for GPU-backed transcription jobs only.
- If the service is expected to run as a permanent API, consider a separate dedicated GPU instance or serverless endpoint with the same image and secrets.
- For temporary or burst workloads, the `40 GiB` `/workspace` volume is a safe default for audio and transcript state.

## Troubleshooting

- If the deployed pod cannot authenticate to Hugging Face, verify the secret values for `PYANNOTE_AUTH_TOKEN` and `HUGGINGFACE_HUB_TOKEN`.
- If the container fails to start, confirm the image tag is published and `docker pull` succeeds.
- If file writes fail, increase `containerDiskInGb` and/or `workspace` volume size.
