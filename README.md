# SA-transcription — Chilean Spanish Audio Transcription & Diarization

High-accuracy transcription service combining **OpenAI Whisper** ASR with **Pyannote** speaker diarization, optimised for Chilean Spanish. Designed for legal and evidentiary audio analysis within the [Awareness-AI](https://github.com/awareness-ai) ecosystem.

## Features

- **Speaker diarization** — Identifies who speaks when using Pyannote 3.1
- **Whisper ASR** — Full Whisper model support (tiny → large-v3) with all decoding parameters
- **Chilean Spanish post-processing** — Regex rules for colloquial expressions ("po", "weón", "cachai", etc.)
- **Audio preprocessing** — Noise reduction, voice enhancement (band-pass 300-3400 Hz), loudness normalisation (LUFS), silence removal
- **AI transcript analysis** — Anthropic Claude integration for summaries, entity extraction, sentiment (optional)
- **Semantic search** — Qdrant vector store with sentence-transformers for transcript search (optional)
- **Law corpus index** — `data/law/**/*.md` → Qdrant with payload/BM25 parity validation and a regenerateable registry (see [Law Corpus Index](#law-corpus-index))
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
| `POST` | `/api/diarization/transcribe/async` | Async transcription (returns job ID) |
| `POST` | `/api/diarization/transcribe/guided` | Reference-guided transcription |
| `POST` | `/api/diarization/transcribe/guided/async` | Async reference-guided transcription |
| `POST` | `/api/diarization/excerpt` | Diarize a time range (upload or path) |
| `POST` | `/api/diarization/excerpt_by_path` | Diarize excerpt by server path (JSON) |

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

## Law Corpus Index (`data/law/`) {#law-corpus-index}

The `data/law/**/*.md` corpus (100 files / 1119 article ELIs) is parsed into Qdrant by
`src/infrastructure/qdrant_law_index.py` and driven by `scripts/ingest_law_corpus.py`.

| Collection | Dim | Vector | Role |
|---|---|---|---|
| `transcription_law` | 384 | dense, `all-MiniLM-L6-v2` | **Repo-owned semantic search.** Safe to drop/rebuild (`--recreate-local`). |
| `la8159_law` | 768 | dense (opaque) | **Shared production payload store.** Read for payloads; treated as *not* a similarity index. |
| `la8159_law_bm25` | — | sparse `text`, `qdrant/bm25` | Shared lexical search over the same articles. |

> ⚠️ **Dense semantic search must use `transcription_law`.** The 768-dim vectors in
> `la8159_law` are not produced by any known local model, so similarity on that
> collection is meaningless. Point IDs are `uuid5(NAMESPACE_DNS, original_id)`, so
> existing points are always reused and never duplicated.

```bash
# read-only: parse the corpus and print an inventory
.venv-py312/bin/python scripts/ingest_law_corpus.py plan

# build/refresh the repo-owned semantic index (default target = local)
.venv-py312/bin/python scripts/ingest_law_corpus.py ingest

# coverage + payload-parity report, and regenerate the registry artifacts
.venv-py312/bin/python scripts/ingest_law_corpus.py validate --write-registry

# semantic search / lexical search
.venv-py312/bin/python scripts/ingest_law_corpus.py search "prazo para recurso administrativo"
.venv-py312/bin/python scripts/ingest_law_corpus.py search "prazo recurso" --target canonical

# preview a refresh of the SHARED production collections (writes nothing)
.venv-py312/bin/python scripts/ingest_law_corpus.py ingest --target canonical --dry-run
```

**Targets.** `--target local` (the default), `canonical`, or `both`. Writing to
`canonical` refreshes payloads via `set_payload` (no `vector` key, so the 768-dim
vectors are preserved) and re-derives the BM25 sparse vectors. `--allow-new` is
off by default because creating a missing article would require a placeholder
dense vector.

**Corpus conventions** — each article is a `### <Title>` block whose first
backticked `` `ELI ID` `` (or `` `ID ELI` ``) line becomes `original_id`; optional
`Theme`/`Tags` lines and a trailing `---` separator are preserved. Multi-locale
articles (`INT/BR` pt vs `INT/EN` en) collide on `original_id`; the English
variant wins by default (`--prefer-language`, `--multi-language` to keep all).

**Registry.** `validate --write-registry` writes `data/law/_mapping/law_registry.json`
and `LAW_REGISTRY.md`. The JSON is a **superset** of the schema emitted by
`discovery/case-server/pipeline/build_law_registry.js`, so existing JS consumers
keep working; parity details live under the extra `detail` key.

Registry artifacts are **excluded from parsing** (`_CORPUS_EXCLUDED_FILES`), so a
generated `LAW_REGISTRY.md` can never be re-ingested as law content.
`write_registry` resolves its destination through `registry_paths()`, which maps a
corpus root to its `_mapping` subdirectory — the writer and the read endpoints can
therefore never disagree about where the registry lives.

### Law registry API (`/api/law`)

Served by `src/presentation/routers/law_registry.py`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/status` | Corpus/coverage summary, `editable_fields`, registry artifact paths. Slow (~2–6 s): it parses the whole corpus. |
| `GET` | `/registry` | `law_registry.json` (generated on demand when absent). |
| `GET` | `/registry/markdown` | `LAW_REGISTRY.md`. |
| `POST` | `/registry/refresh` | Re-validate and rewrite both artifacts. |
| `GET` | `/source?path=` | Read one corpus file (traversal-safe, `.md`/`.markdown` only). |
| `GET` | `/article?original_id=&collection=` | Live payload, expected payload, and per-field `diff`; `indexed` is per selected collection. |
| `GET` | `/search?q=&target=&limit=&jurisdiction=` | Dense search on `local`, lexical on `canonical`. |
| `PATCH` | `/payload` | Edit a point's payload (see below). |
| `POST` | `/index` | Start an ingestion job → `202` with a job id. |
| `GET` | `/index/{job_id}` | Job state, per-phase `progress`, stats, notes, failures. |
| `GET` | `/index` | Known jobs and the active one. |
| `POST` | `/index/{job_id}/cancel` | Request cancellation. |

`POST /index` body: `mode` (`incremental` \| `force`), `target` (`local` \|
`canonical` \| `both`), `dry_run`, `allow_new`, `recreate_local`,
`multi_language`, `confirm`.

- `mode=incremental` maps to `only_missing`: articles already present are skipped,
  and **canonical payloads are not rewritten** (`refresh_payloads and not only_missing`).
  BM25 sparse vectors are derived data, so they are still regenerated.
- `mode=force` re-ingests everything.
- `target` defaults to `local`. Writing to `canonical` requires `confirm: true`
  unless `dry_run: true`.
- `recreate_local` with `incremental` → `400`. A second concurrent job → `409`.

### Editing payloads from the UI

`/law-registry` renders the registry, lets you open any article's live payload next
to the corpus-derived expectation, and edit it in place. The Index button offers
*index not yet indexed* (incremental) and *full forced ingestion*, with dry-run,
recreate, and target controls.

**Editable:** `title`, `theme`, `tags`, `content`, `source_file`, `doc_type`.
**Immutable:** `original_id`, `original_data`, `metadata`, `framework_code`,
`jurisdiction`, `language`, `sha256_short`, `source_path`.

Editing `content` also rewrites `text` and re-derives `sha256_short`; flat edits are
mirrored into `original_data`, and `metadata.updated_at` is set while
`ingestion_time` is preserved. Dense vectors and point IDs are **never** modified —
only `set_payload` is used — and an edit to an ELI that is not indexed fails rather
than creating a point with a placeholder vector. The UI defaults writes to
`transcription_law` (repo-owned) and requires an explicit confirm dialog before
touching the shared production collections.

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
| `ANTHROPIC_MODEL` | Anthropic-compatible model for analysis | `deepseek-v4-pro` |
| `QDRANT_URL` | Qdrant server URL (enables semantic search) | `http://localhost:6333` |
| `QDRANT_API_KEY` | Qdrant API key (if secured) | — |
| `LAW_DIR` | Law corpus root (`.md` articles) | `data/law` |
| `LAW_COLLECTION` | Shared canonical payload collection | `la8159_law` |
| `LAW_BM25_COLLECTION` | Shared BM25 sparse collection | `la8159_law_bm25` |
| `LAW_LOCAL_COLLECTION` | Repo-owned dense search collection | `transcription_law` |
| `LAW_EMBED_MODEL` | Sentence-transformers model for the law index | `all-MiniLM-L6-v2` |
| `LAW_PREFERRED_LANGUAGE` | Locale winner on `original_id` collisions | `en` |

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
