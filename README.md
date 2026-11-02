# SA-transcription — Chilean Spanish Audio Transcription & Diarization

High-accuracy transcription service combining **OpenAI Whisper** ASR with **Pyannote** speaker diarization, optimised for Chilean Spanish. Designed for legal and evidentiary audio analysis within the [Awareness-AI](https://github.com/awareness-ai) ecosystem.

## Features

- **Speaker diarization** — Identifies who speaks when using Pyannote 3.1
- **Whisper ASR** — Full Whisper model support (tiny → large-v3) with all decoding parameters
- **Chilean Spanish post-processing** — Regex rules for colloquial expressions ("po", "weón", "cachai", etc.)
- **Audio preprocessing** — Noise reduction, voice enhancement (band-pass 300-3400 Hz), loudness normalisation (LUFS), silence removal
- **AI transcript analysis** — Anthropic Claude integration for summaries, entity extraction, sentiment (optional)
- **Semantic search** — Qdrant vector store with sentence-transformers for transcript search (optional)
- **Clean Architecture** — Domain / Application / Infrastructure / Presentation layers with Protocol-based ports
- **Dual deployment** — FastAPI server or Runpod serverless handler

## Quick Start

### Prerequisites

- Python 3.12+
- FFmpeg (`brew install ffmpeg` / `apt install ffmpeg`)
- CUDA GPU (recommended for large-v3; CPU fallback supported)
- [HuggingFace token](https://huggingface.co/settings/tokens) with access to `pyannote/speaker-diarization-3.1`

### Local Development

```bash
# Clone and setup
git clone <repo-url> && cd sa-transcription
cp .env.example .env
# Edit .env with your HuggingFace/Pyannote tokens

# Install
python3.12 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip setuptools
uv pip install -r requirements.txt

# Run
make run
# or: uvicorn src.main:app --host 0.0.0.0 --port 8039 --reload
```

### Docker

```bash
docker compose up --build
```

The API will be available at `http://localhost:8049`.

For RunPod pod template details, see [docs/RUNPOD_POD_TEMPLATE.md](docs/RUNPOD_POD_TEMPLATE.md).

## API Endpoints

### Health & System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | System info (GPU status, device) |
| `GET` | `/health` | Health check |

### Transcription & Diarization (`/api/diarization`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/diarization/parameters` | Available parameters metadata |
| `GET` | `/api/diarization/models/whisper` | Available Whisper models |
| `POST` | `/api/diarization/transcribe` | Full transcription with diarization |
| `POST` | `/api/alignment/narration` | Align source text lines to Whisper timestamps and return CSV |
| `POST` | `/api/diarization/transcribe/async` | Async transcription (returns job ID) |
| `POST` | `/api/diarization/transcribe/guided` | Reference-guided transcription |
| `POST` | `/api/diarization/transcribe/guided/async` | Async reference-guided transcription |
| `POST` | `/api/diarization/excerpt` | Diarize a time range (upload or path) |
| `POST` | `/api/diarization/excerpt_by_path` | Diarize excerpt by server path (JSON) |

The narration aligner UI is available at `/aligner`. Upload an audio file and source text
(plain lines, `Página N` markers, or CSV with a `text` column) to preview and download
`start_ms,end_ms,page,text` timestamps. Low-confidence rows are marked for review. The
alignment request uses Whisper's timed segments without saving or indexing a transcript; the
returned timestamps stay on the source audio timeline.

### Transcripts (`/api/transcripts`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/transcripts` | List all transcript IDs |
| `GET` | `/api/transcripts/{transcript_id}` | Retrieve full transcript |
| `POST` | `/api/transcripts/import` | Import transcripts from directory |
| `POST` | `/api/transcripts/analyze` | AI analysis via LLM (optional) |
| `POST` | `/api/transcripts/search` | Semantic search across transcripts (optional) |
| `POST` | `/api/transcripts/{transcript_id}/index` | Re-index single transcript into Qdrant |
| `POST` | `/api/transcripts/index-all` | Bulk re-index all transcripts |
| `POST` | `/api/transcripts/{transcript_id}/audit` | Audit transcript for quality issues |
| `POST` | `/api/transcripts/{transcript_id}/refine` | Refine transcript via reconciliation |
| `POST` | `/api/transcripts/{transcript_id}/patch` | Apply patches to a transcript |
| `GET` | `/api/transcripts/status/{job_id}` | Async job status |
| `GET` | `/api/transcripts/stream/{job_id}` | SSE progress stream for async jobs |

### Projects (`/api/projects`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects` | List all projects |
| `GET` | `/api/projects/{project_id}` | Get project details |
| `POST` | `/api/projects` | Create a new project |
| `PATCH` | `/api/projects/{project_id}` | Update project metadata |
| `DELETE` | `/api/projects/{project_id}` | Delete a project |
| `POST` | `/api/projects/{project_id}/audios` | Add an audio file to a project |
| `DELETE` | `/api/projects/{project_id}/audios/{canonical_name}` | Remove an audio file |
| `POST` | `/api/projects/{project_id}/context_docs` | Add context documents |
| `DELETE` | `/api/projects/{project_id}/context_docs` | Remove context documents |
| `POST` | `/api/projects/{project_id}/narratives` | Add incident narratives |

### References (`/api/references`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/references` | List all canonical audio names |
| `GET` | `/api/references/{canonical_name}/manifest` | Get reference manifest |
| `GET` | `/api/references/{canonical_name}` | Get all references for an audio |
| `POST` | `/api/references/{canonical_name}/upload` | Upload reference transcript |
| `POST` | `/api/references/{canonical_name}/link` | Link existing transcript as reference |
| `GET` | `/api/references/{canonical_name}/narratives` | Get narratives for an audio |

### Transcribe Example

```bash
curl -X POST http://localhost:8049/api/diarization/transcribe \
  -F "audio=@recording.wav" \
  -F "language=es-CL" \
  -F "model_size=large-v3" \
  -F "min_speakers=1" \
  -F "max_speakers=3"
```

## Architecture

```
src/
├── domain/              ← Entities, Ports (depends on nothing)
├── application/         ← Use cases, DTOs (depends on Domain)
├── infrastructure/      ← Adapters: Whisper, Pyannote, Pydub, JSON (implements Ports)
├── presentation/        ← FastAPI routers, middleware (depends on Application)
├── config.py            ← Environment settings
├── main.py              ← Composition root (DI wiring)
└── runpod_handler.py    ← Serverless bridge
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design document.

## Configuration

All settings are loaded from environment variables. See [.env.example](.env.example) for the full list.

| Variable | Description | Default |
|----------|-------------|---------|
| `TRANSCRIPTION_API_KEY` | Enables API-key auth on every route except `/health`, `/static/*` and the HTML shells. **Unset means the API is unauthenticated** — only safe because the server binds to loopback by default. | — |
| `HOST` | Bind address for the API (`127.0.0.1` by default; set `0.0.0.0` to expose on the network) | `127.0.0.1` |
| `PORT` | Bind port for the API | `8049` |
| `PYANNOTE_AUTH_TOKEN` | HuggingFace token for Pyannote | — |
| `HF_TOKEN` | Canonical Hugging Face token env var | — |
| `HUGGINGFACE_HUB_TOKEN` | HuggingFace hub token | — |
| `AUDIO_DIR` | Processed audio output directory | `data/audio` |
| `ORIGINALS_DIR` | Original uploads directory | `data/originals` |
| `TRANSCRIPT_DIR` | JSON transcript storage | `data/transcripts` |
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:3000,http://localhost:8049` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `ANTHROPIC_API_KEY` | Anthropic-compatible API key (enables AI analysis) | — |
| `ANTHROPIC_BASE_URL` | Anthropic-compatible base URL | `https://api.deepseek.com/anthropic` |
| `ANTHROPIC_MODEL` | Anthropic-compatible model for analysis | `deepseek-flash` |
| `QDRANT_URL` | Qdrant server URL (enables semantic search) | `http://localhost:6333` |
| `QDRANT_API_KEY` | Qdrant API key (if secured) | — |

Pyannote token resolution order is:
`PYANNOTE_AUTH_TOKEN` → `HF_TOKEN` → `HUGGINGFACE_HUB_TOKEN` → `use_auth_token`.

## Testing

```bash
make test          # Run all tests
make test-unit     # Domain + application only
make lint          # Ruff linter
make typecheck     # Mypy type checking
```

## MCP Server (Transcription)

transcription now includes MCP servers that expose service capabilities as MCP tools
over stdio.

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run locally

The recommended way to start the environment is using the included start script:

```bash
./start.sh
```

**Startup Sequence:**
When you run `./start.sh`, it automatically handles the full startup lifecycle:
1. **Cleanup**: Stops any currently running background services (via `./stop.sh`).
2. **Speaker Re-sync**: Scans `data/transcripts/` to dynamically regenerate the `speaker_index.json` mappings and updates the individual markdown files in `data/speakers/`.
3. **Web API**: Launches the main Uvicorn API on port 8049 (used for the Pinocchio UI).
4. **MCP Servers**: Launches the 3 MCP servers (`mcp-transcription`, `mcp-transcripts`, `mcp-meta`) in the background using streamable HTTP (ports 8121, 8122, 8123).
5. **Health Checks**: Waits for the API and MCP ports to become healthy before returning control.

Upon success, it prints the URL to access the UI (e.g., `http://0.0.0.0:8049/pinocchio`).

To gracefully shut down all services, run:
```bash
./stop.sh
```

> [!NOTE]
> All logs are preserved in the `.dev-logs/` directory for debugging.

### Word timestamps and segment export

Pinocchio enables word timestamps by default (the setting can still be changed in the
configuration). When enabled, the transcription response and saved transcript include a
`words` array per segment. The **Export Segments ZIP** also contains
`<transcript_id>_word_timestamps.json` and `<transcript_id>_word_timestamps.csv`, with each
word's text, speaker, segment index, start, and end in seconds on the original audio timeline.
To preserve that timebase, silence trimming is skipped for runs with word timestamps enabled.
Existing transcripts without word data need to be transcribed again to generate it.

## Git Guidance

Large generated data (under `data/`, `data/transcripts/`, etc.) should not be committed. These paths are in `.gitignore`. To remove an accidentally tracked file:

```
git rm --cached path/to/generated_file
git commit -m "chore: remove generated file from repo"
```

### Tools exposed (transcription server)

- `transcribe_audio`
- `transcribe_audio_async`
- `get_transcription_job`
- `diarize_excerpt`

### Tools exposed (transcripts server)

- `list_transcripts`
- `get_transcript`
- `import_transcripts`
- `analyze_transcript`
- `search_transcripts`
- `index_transcript`
- `index_all_transcripts`

### Tools exposed (meta server)

- `health`
- `health_full`
- `list_parameter_definitions`
- `list_whisper_models`

### MCP client config example

```json
{
  "mcpServers": {
    "transcription-transcription": {
      "command": "python",
      "args": [
        "-m",
        "src.mcp.servers.transcription_server"
      ],
      "env": {
        "PYANNOTE_AUTH_TOKEN": "<your_token>",
        "HF_TOKEN": "<your_token>",
        "ORIGINALS_DIR": "data/originals",
        "TRANSCRIPT_DIR": "data/transcripts",
        "QDRANT_URL": "http://localhost:6333"
      }
    },
    "transcription-transcripts": {
      "command": "python",
      "args": [
        "-m",
        "src.mcp.servers.transcripts_server"
      ],
      "env": {
        "TRANSCRIPT_DIR": "data/transcripts",
        "ANTHROPIC_API_KEY": "<optional>",
        "DEEPSEEK_API_KEY": "<optional>",
        "QDRANT_URL": "http://localhost:6333"
      }
    },
    "transcription-meta": {
      "command": "python",
      "args": [
        "-m",
        "src.mcp.servers.meta_server"
      ],
      "env": {}
    }
  }
}
```

Full ready-to-use config file is available at `docs/mcp-servers.example.json`.

Input mode for `transcribe_audio` and `diarize_excerpt`:
- Use `file_path` for server-side files
- Or use `audio_base64` + optional `filename`

Both MCP servers and FastAPI now share the same dependency container in
`src/composition.py`, keeping service wiring consistent across interfaces.

## Security

- **No wildcard CORS** — explicit origins only
- **Path traversal prevention** — all file paths validated against allowed roots
- **No secrets in code** — all tokens via environment variables
- **`.gitignore` protection** — `.env`, data files, and caches excludedd

> **Token rotation required:** If you previously had tokens committed to git history, rotate them immediately on [HuggingFace](https://huggingface.co/settings/tokens) and [Runpod](https://www.runpod.io/console/user/settings).

## License

Private — Awareness-AI ecosystem. 
