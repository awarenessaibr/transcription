# SA-transcription Architecture

## Clean Architecture (Onion)

Dependencies flow inward only. Domain depends on nothing.

```
┌──────────────────────────────────────────────────────┐
│  PRESENTATION  (routers, middleware, schemas)         │
│    FastAPI routers with form parameters               │
│    Path validation middleware                         │
│    Depends on: Application                            │
├──────────────────────────────────────────────────────┤
│  INFRASTRUCTURE  (adapters, model manager)            │
│    WhisperASRAdapter      → implements ASRPort        │
│    PyAnnoteDiarizerAdapter → implements DiarizationPort│
│    PydubProcessorAdapter  → implements AudioProcessorPort│
│    JSONTranscriptStore    → implements TranscriptStorePort│
│    AudioFileAdapter       → implements AudioFilePort  │
│    ClaudeAnalyzerAdapter  → implements TranscriptAnalyzerPort│
│    QdrantTranscriptIndex  → implements TranscriptIndexPort│
│    ModelManager           → lazy model lifecycle      │
│    Depends on: Application (via Domain ports)         │
├──────────────────────────────────────────────────────┤
│  APPLICATION  (use cases, DTOs)                       │
│    TranscribeAudioUseCase — full pipeline orchestrator │
│    DiarizeExcerptUseCase  — excerpt diarization       │
│    AnalyzeTranscriptUseCase — Claude analysis         │
│    SearchTranscriptsUseCase — Qdrant semantic search  │
│    Depends on: Domain                                 │
├──────────────────────────────────────────────────────┤
│  DOMAIN  (entities, ports, services)                  │
│    Transcript, Segment, Speaker, DiarizationTurn      │
│    Protocol ports (structural subtyping)              │
│    Chilean Spanish post-processing                    │
│    Depends on: NOTHING                                │
└──────────────────────────────────────────────────────┘
```

## Directory Map

```
src/
├── domain/
│   ├── entities/
│   │   └── transcript.py       ← Speaker, Segment, DiarizationTurn, Transcript, AudioFile
│   ├── ports/
│   │   └── interfaces.py       ← ASRPort, DiarizationPort, AudioProcessorPort,
│   │                              TranscriptStorePort, AudioFilePort (all Protocol)
│   └── chilean_spanish.py      ← Pure post-processing function
│
├── application/
│   ├── dto/
│   │   └── schemas.py          ← Pydantic request/response models
│   └── use_cases/
│       ├── transcribe_audio.py ← Full pipeline: upload → preprocess → diarize → transcribe → persist
│       └── diarize_excerpt.py  ← Crop + diarize (no transcription)
│
├── infrastructure/
│   ├── model_manager.py        ← Lazy-load + cache Whisper & Pyannote models
│   ├── whisper_adapter.py      ← ASRPort implementation via OpenAI Whisper
│   ├── pyannote_adapter.py     ← DiarizationPort implementation via Pyannote 3.1
│   ├── pydub_processor.py      ← AudioProcessorPort: noise reduction, gain, silence
│   ├── json_store.py           ← TranscriptStorePort: JSON file persistence
│   ├── audio_file_adapter.py   ← AudioFilePort: upload, convert, crop, extract
│   ├── claude_analyzer.py      ← TranscriptAnalyzerPort: Anthropic Claude analysis
│   ├── qdrant_index.py         ← TranscriptIndexPort: transcript vector search
│
├── presentation/
│   ├── routers/
│   │   ├── health.py           ← GET /, GET /health
│   │   ├── parameters.py       ← GET /api/diarization/parameters, /models/whisper
│   │   ├── diarization.py      ← POST excerpt, excerpt_by_path
│   │   ├── transcription.py    ← POST transcribe
│   │   └── transcripts.py      ← Transcript CRUD, analyze, search, SSE streaming
│   ├── middleware/
│   │   └── path_validator.py   ← Path traversal prevention
│   └── schemas/                ← (reserved for response-only schemas)
│
├── config.py                   ← Settings from env vars
├── logging_setup.py            ← Logging configuration
├── main.py                     ← Composition root — wires all layers
└── runpod_handler.py           ← Runpod serverless bridge
```

## Ports & Adapters

The Domain layer defines 5 ports as Python `Protocol` classes (structural subtyping — no inheritance required):

| Port | Methods | Adapter |
|------|---------|---------|
| `ASRPort` | `transcribe(path, lang)` → `str` | `WhisperASRAdapter` |
| `DiarizationPort` | `diarize(path, ...)` → `list[DiarizationTurn]` | `PyAnnoteDiarizerAdapter` |
| | `diarize_waveform(waveform, sr, ...)` | |
| `AudioProcessorPort` | `process(path, params)` → `str` | `PydubProcessorAdapter` |
| `TranscriptStorePort` | `save(transcript)` → `str` | `JSONTranscriptStore` |
| | `load(id)` → `Transcript \| None` | |
| | `list_ids()` → `list[str]` | |
| `AudioFilePort` | `save_upload()`, `convert_to_wav()`, `crop_audio()`, `get_duration()`, `extract_segment()` | `AudioFileAdapter` |
| `TranscriptAnalyzerPort` | `analyze(transcript, instructions)` → `dict` | `ClaudeAnalyzerAdapter` |
| `TranscriptIndexPort` | `index(transcript)` → `int`, `search(query, limit)` → `list[dict]`, `delete(id)` | `QdrantTranscriptIndex` |

## Composition Root

`src/main.py` is the **only** file that knows about all layers. It:

1. Creates infrastructure adapters (passing config/tokens)
2. Creates use cases (injecting adapters via constructor)
3. Injects use cases into routers via `init_*_router()` functions
4. Assembles the FastAPI app with middleware and mounts

No other file cross-references layers.

## Transcription Pipeline

```
Upload audio → Save to disk → Convert to WAV → Preprocess
    ↓                                              ↓
    │                                    noise reduction
    │                                    band-pass filter
    │                                    loudness normalisation
    │                                    silence removal
    ↓
Diarize (Pyannote 3.1) → Speaker turns [{speaker, start, end}]
    ↓
For each turn:
    Extract segment → Whisper transcribe → Chilean Spanish cleanup
    ↓
Assemble Transcript → Save JSON → Return result with timings
```

## Model Management

`ModelManager` provides lazy loading with caching:

- **Whisper models**: Loaded on first use per model size, cached in memory
- **Pyannote pipeline**: Loaded once with HuggingFace auth, cached
- **GPU detection**: Automatic CUDA/CPU selection via PyTorch
- **Cache clearing**: `clear_cache()` with garbage collection for memory recovery

## Security Boundaries

- **Path validation**: All user-supplied file paths checked against allowed roots (`AUDIO_DIR`, `ORIGINALS_DIR`, `TRANSCRIPT_DIR`) — prevents path traversal
- **CORS**: Explicit origin list from `CORS_ORIGINS` env var — no wildcards
- **Secrets**: All tokens via environment variables, never in code
- **Docker**: Non-root process, health check enabled

## AI-Native Features (Optional)

When configured via environment variables, the platform gains:

- **Transcript Analysis** — Anthropic Claude analyzes transcripts for summaries, key facts, entities, speaker profiles, and sentiment. Enabled when `ANTHROPIC_API_KEY` is set.
- **Semantic Search** — Qdrant vector store with `all-MiniLM-L6-v2` sentence-transformer embeddings (384-dim). Transcripts are auto-indexed after transcription. Enabled when `QDRANT_URL` is set.
- **Graceful Degradation** — All AI features are optional. When env vars are not set, the corresponding adapters are `None` and endpoints return `503 Service Unavailable` with a clear message. Core transcription is never affected.
