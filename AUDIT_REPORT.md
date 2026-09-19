# SA-transcription — Architectural Audit Report

**Date:** 2026-03-09
**Auditor:** Awareness Architectural Auditor v2.0
**Mode:** Audit (Read-Only) → Proposal
**Target:** `sa-transcription` — Audio Transcription & Diarization Service

---

## 1. Executive Structural Summary

SA-transcription is a **FastAPI-based audio transcription service** specializing in Chilean Spanish. It combines OpenAI Whisper (local inference) with Pyannote speaker diarization, audio preprocessing (noise reduction, silence removal, gain normalization), and Runpod serverless deployment.

**Current state:** The project is a functional prototype with **critical security vulnerabilities**, **zero Clean Architecture compliance**, **zero AI-First retrieval integration**, and **no observability infrastructure**. The codebase is a flat monolith with business logic, routing, and I/O tightly coupled in a single 450+ line file.

**Verdict:** The project requires a **full structural transformation** to meet Awareness-AI ecosystem standards. The domain logic is sound and well-implemented — the audio pipeline works — but the surrounding architecture, security posture, and integration layer are absent.

| Metric | Score |
|--------|-------|
| **Clean Architecture Compliance** | 5/100 |
| **AI-Native Readiness** | 0/100 |
| **Observability Completeness** | 8/100 |
| **Security Posture** | 15/100 |
| **Code Quality** | 45/100 |
| **Production Readiness** | 25/100 |

---

## 2. Stack Detection Result

| Component | Technology | Version | Status |
|-----------|-----------|---------|--------|
| Language | Python | 3.10 (Docker) | ⚠️ Below required 3.12+ |
| Framework | FastAPI | 0.111.0 | ✅ Current |
| ASR Engine | OpenAI Whisper | latest (unpinned) | ⚠️ Unpinned |
| Diarization | Pyannote.audio | 3.1.0 | ✅ Current |
| Audio Processing | pydub + noisereduce | 0.25.1 / 3.0.0 | ✅ |
| ML Framework | PyTorch | 2.4.1 | ✅ |
| Validation | Pydantic | 2.7.3 | ✅ |
| Deployment | Docker + Runpod | Serverless | ✅ Functional |
| LLM Provider | None | — | ❌ No AI integration |
| Vector Store | None | — | ❌ No Qdrant |
| Graph DB | None | — | ❌ No Neo4j |

---

## 3. AI-First Retrieval Log

| Step | Tool Attempted | Result |
|------|---------------|--------|
| 1 | `context_assemble` | ❌ Not available — no Awareness API connection |
| 2 | `qdrant_search` | ❌ Not available — no Qdrant instance |
| 3 | `neo4j_query` | ❌ Not available — no Neo4j instance |
| 4 | Direct file read | ✅ Used (justified: no semantic infrastructure exists in target) |

**AI-First Compliance in target codebase: 0%.** No semantic retrieval, no vector indexing, no graph queries exist anywhere in the project.

---

## 4. Repository Map

```
sa-transcription/                           
├── .env                      ← 🔴 CRITICAL: Contains real API keys, no .gitignore
├── .env.example              ← ✅ Template with placeholders
├── .github/                  ← Copilot instructions (correct)
├── data/
│   ├── audio/                ← Empty (processed audio output)
│   ├── originals/            ← 13 .wav files (real evidence recordings)
│   ├── queue.json            ← ⚠️ Unused — referenced but no queue logic
│   └── transcripts/          ← 40 JSON transcript files
├── docker-compose.yml        ← Single service definition
├── Dockerfile                ← Python 3.10-slim (should be 3.12+)
├── install                   ← ⚠️ Markdown document, not a script
├── requirements.txt          ← 17 dependencies
├── run.sh                    ← Stub script (echo only)
├── runpod_client_example.js  ← Client example
├── runpod_client_example.py  ← Client example
├── RUNPOD_SETUP.md           ← 🔴 Contains hardcoded API tokens
├── sa-transcription.md           ← Project tree documentation
└── src/
    ├── config.py             ← Settings class (no gitignore for .env)
    ├── diarization.py        ← 🔴 God file: 450+ lines, routing + logic + I/O
    ├── logging_setup.py      ← ✅ Clean logging configuration
    ├── main.py               ← FastAPI app + dead placeholder code
    ├── models.py             ← Model manager + Pydantic schemas
    ├── preprocessing.py      ← ✅ Audio enhancement pipeline
    ├── runpod_handler.py     ← Serverless bridge
    └── __pycache__/          ← ⚠️ Should be gitignored
```

---

## 5. Current Architecture Assessment

**Pattern detected:** **Big Ball of Mud / Flat Monolith**

```
┌──────────────────────────────────────────────────┐
│                   src/main.py                     │
│     FastAPI app + routes + background tasks       │
├──────────────────────────────────────────────────┤
│               src/diarization.py                  │
│   Routes + Business Logic + File I/O + Models     │
│   (450+ lines, single file, all concerns mixed)   │
├──────────────────────────────────────────────────┤
│  src/models.py    src/preprocessing.py            │
│  (Model mgmt)     (Audio processing)              │
├──────────────────────────────────────────────────┤
│  src/config.py    src/logging_setup.py            │
│  (Settings)       (Log config)                    │
└──────────────────────────────────────────────────┘
```

**Dependency flow:** Circular. `main.py` imports from `diarization.py`, which imports from `models.py`, `preprocessing.py`, `config.py`. No layer separation. No interfaces. No dependency inversion.

---

## 6. Architectural Strengths

1. **Solid domain expertise** — The audio pipeline (preprocessing → diarization → transcription) is well-implemented with correct signal processing
2. **Good parameter exposure** — The `/api/diarization/parameters` endpoint provides structured metadata for frontend form generation
3. **Proper logging** — Uses Python logging throughout with structured format strings and timing breakdowns
4. **Model caching** — `ModelManager` implements lazy loading + caching of expensive Whisper/Pyannote models
5. **Cleanup discipline** — `finally` blocks handle temporary file removal consistently
6. **Detailed timing** — Transcription responses include per-stage timing breakdowns (`save_s`, `convert_s`, `preprocess_s`, etc.)
7. **Chilean Spanish specialization** — Post-processing regex for Chilean colloquialisms shows domain knowledge
8. **Dual deployment** — Supports both FastAPI server and Runpod serverless from the same codebase

---

## 7. Architectural Weaknesses

### CRITICAL (Must Fix)

| # | Issue | File | Impact |
|---|-------|------|--------|
| W1 | **Leaked API keys in .env** — Real HuggingFace and Runpod tokens committed | `.env` | Full account compromise |
| W2 | **Hardcoded tokens in documentation** — `RUNPOD_SETUP.md` contains real API keys in examples | `RUNPOD_SETUP.md` | Credential exposure |
| W3 | **No .gitignore** — `.env`, `__pycache__/`, `*.pyc`, `data/originals/` all potentially tracked | Root | Secret/data leakage |
| W4 | **CORS wildcard** — `allow_origins=["*"]` allows any origin | `main.py` L28 | CSRF / unauthorized access |
| W5 | **Path traversal** — `file_path` parameter accepts arbitrary server paths without validation | `diarization.py` | Arbitrary file read |

### HIGH (Should Fix)

| # | Issue | File | Impact |
|---|-------|------|--------|
| W6 | God file — `diarization.py` mixes routing, business logic, file I/O, and model interaction in 450+ lines | `diarization.py` | Unmaintainable |
| W7 | No Clean Architecture — zero layer separation, no interfaces, no dependency inversion | All `src/` | No testability |
| W8 | Dead code — `run_transcription()` in `main.py` with hardcoded `time.sleep(0.2)` placeholder | `main.py` L79-95 | Confusion |
| W9 | Duplicate endpoint — `/api/diarization/transcribe` defined in both `main.py` and `diarization.py` | Both | Route conflict |
| W10 | No tests — zero test files anywhere | — | No regression safety |

### MEDIUM (Recommended)

| # | Issue | File | Impact |
|---|-------|------|--------|
| W11 | Python 3.10 in Docker — ecosystem standard is 3.12+ | `Dockerfile` | Missing features |
| W12 | Unpinned `openai-whisper` — no version lock on critical dependency | `requirements.txt` | Build breakage |
| W13 | `os.makedirs` in class body — side effects at import time | `config.py` | Test complications |
| W14 | No Pydantic response models — raw dict returns instead of typed schemas | `diarization.py` | No API contract |
| W15 | `install` file is markdown, not a script | `install` | Misleading |
| W16 | `run.sh` is a stub echo | `run.sh` | Non-functional |
| W17 | `queue.json` referenced but unused | `config.py` / `data/` | Dead config |
| W18 | No health check in Docker | `Dockerfile` | Orchestration gap |

---

## 8. Violation Matrix

| Rule | Status | Evidence |
|------|--------|----------|
| **Security: No hardcoded secrets** | ❌ VIOLATED | `.env` and `RUNPOD_SETUP.md` contain real tokens |
| **Security: Validate file paths** | ❌ VIOLATED | `file_path` accepts arbitrary paths, no allowed-root check |
| **Security: CORS per-origin** | ❌ VIOLATED | `allow_origins=["*"]` |
| **Clean Arch: Dependency direction** | ❌ VIOLATED | No layers exist — flat structure |
| **Clean Arch: Domain free of infra imports** | ❌ VIOLATED | No domain layer exists |
| **AI-First: Semantic retrieval before file read** | ❌ VIOLATED | No retrieval infrastructure |
| **AI-First: qdrant_ingest after file write** | ❌ VIOLATED | No Qdrant integration |
| **SSE: Step protocol events** | ❌ VIOLATED | No SSE streaming |
| **Observability: Token/cost tracking** | ❌ VIOLATED | No tracking |
| **Python: 3.12+ with type hints** | ⚠️ PARTIAL | Type hints used inconsistently; Docker uses 3.10 |
| **Python: async for I/O** | ⚠️ PARTIAL | Some async endpoints, but sync model loading |
| **Python: Pydantic for schemas** | ⚠️ PARTIAL | Used for `TranscribeParams` but not responses |
| **Python: No print()** | ✅ MET | Uses logging throughout |
| **Logging: structured logger** | ✅ MET | `logging.getLogger(__name__)` pattern used |

---

## 9. Structural Risk Assessment

| Risk | Severity | Likelihood | Impact | Mitigation |
|------|----------|-----------|--------|-----------|
| **Credential theft** via committed .env | 🔴 Critical | High | Account compromise, billing fraud | Rotate tokens NOW, add .gitignore, use secrets manager |
| **Path traversal attack** via file_path | 🔴 Critical | Medium | Arbitrary server file read | Validate against allowed directories |
| **Service disruption** from unpinned deps | 🟡 Medium | Medium | Build failures | Pin all versions, use lockfile |
| **Data loss** from no backup strategy | 🟡 Medium | Low | Transcript loss | Add backup, consider DB storage |
| **Regression bugs** from no tests | 🟡 Medium | High | Silent breakage | Add test suite |
| **Scaling failure** from sync model loading | 🟠 High | Medium | Request timeout, OOM | Async loading, model pooling |

---

## 10. Dependency Direction Report

**Current state:** No architectural layers exist. All files import from each other at the same level.

```
main.py ──→ diarization.py ──→ models.py
    │              │                │
    │              ├──→ preprocessing.py
    │              │
    │              └──→ config.py
    │
    ├──→ config.py
    ├──→ models.py
    └──→ logging_setup.py

runpod_handler.py ──→ diarization.py ──→ (same graph)
```

**Violations:** Every import crosses what should be layer boundaries. Business logic (transcription pipeline) is embedded in presentation code (FastAPI route handlers). Infrastructure (file I/O, model loading) is directly used by routes without interfaces.

---

## 11. AI-Native Readiness Score: 0 / 100

| Capability | Required | Present | Score |
|-----------|----------|---------|-------|
| Qdrant vector store (4 collections) | Yes | No | 0 |
| Neo4j knowledge graph | Yes | No | 0 |
| `qdrant_ingest` hooks after file writes | Yes | No | 0 |
| `qdrant_search` before file reads | Yes | No | 0 |
| SSE streaming with typed events | Yes | No | 0 |
| Step-level token/cost accounting | Yes | No | 0 |
| Anthropic Claude integration | Yes | No | 0 |
| `context_assemble` tool | Yes | No | 0 |

**Assessment:** SA-transcription has no AI-native infrastructure. It is a pure ML inference service (Whisper + Pyannote) with no semantic retrieval, no knowledge graph, no LLM integration, and no observability pipeline.

---

## 12. Observability Completeness Score: 8 / 100

| Capability | Present | Score |
|-----------|---------|-------|
| Structured logging with levels | ✅ Yes | 8 |
| Per-stage timing breakdown | ✅ Yes (in response) | — (not streamed) |
| SSE step_reasoning events | ❌ No | 0 |
| SSE step_outcome events | ❌ No | 0 |
| SSE file_accessed events | ❌ No | 0 |
| SSE data_consumed events | ❌ No | 0 |
| Token budget tracking | ❌ No | 0 |
| Cost accumulation per session | ❌ No | 0 |
| Health check endpoint | ⚠️ Minimal (`GET /`) | 0 |
| Error tracking/alerting | ❌ No | 0 |

---

## 13. Dependency Overview

### Direct Dependencies (17)

| Package | Version | Purpose | Risk |
|---------|---------|---------|------|
| fastapi | 0.111.0 | Web framework | ✅ Low |
| uvicorn | 0.29.0 | ASGI server | ✅ Low |
| python-multipart | 0.0.9 | File uploads | ✅ Low |
| pydub | 0.25.1 | Audio manipulation | ✅ Low |
| torch | 2.4.1 | ML framework | ⚠️ Large (2GB+) |
| torchaudio | 2.4.1 | Audio ML | ⚠️ Large |
| openai-whisper | **unpinned** | ASR engine | 🔴 Breaking change risk |
| pyannote.audio | 3.1.0 | Speaker diarization | ⚠️ HF auth required |
| noisereduce | 3.0.0 | Noise reduction | ✅ Low |
| scipy | 1.13.0 | Scientific computing | ✅ Low |
| python-dotenv | 1.0.1 | Env loading | ✅ Low |
| aiofiles | 23.2.1 | Async file I/O | ⚠️ Unused in code |
| numpy | 1.26.4 | Numerical computing | ✅ Low |
| psutil | 5.9.8 | System monitoring | ⚠️ Unused in code |
| pydantic | 2.7.3 | Validation | ✅ Low |
| huggingface-hub | 0.17.3 | Model downloads | ⚠️ Outdated |
| runpod | 1.6.2 | Serverless deployment | ✅ Low |

**Unused dependencies (should remove):** `aiofiles`, `psutil`
**Unpinned (must pin):** `openai-whisper`
**Outdated (should update):** `huggingface-hub` (0.17.3 → latest)

---

## 14. Transformation Plan

### Phase 0: Emergency Security Fixes (Immediate)

1. **Rotate ALL tokens** — The HuggingFace and Runpod tokens in `.env` and `RUNPOD_SETUP.md` are compromised. Revoke and regenerate immediately.
2. **Create `.gitignore`** — Exclude `.env`, `__pycache__/`, `data/originals/`, `data/audio/`, `*.pyc`, `venv/`
3. **Scrub `RUNPOD_SETUP.md`** — Replace all real tokens with `<YOUR_TOKEN_HERE>` placeholders
4. **Fix CORS** — Replace `allow_origins=["*"]` with explicit allowed origins
5. **Add path validation** — Validate `file_path` parameter against allowed directories (`data/originals/`, `data/audio/`)

### Phase 1: Clean Architecture Restructure

Separate the monolith into proper layers:

```
src/
├── domain/                    ← Depends on NOTHING
│   ├── entities/
│   │   ├── transcript.py      ← Transcript, Segment, Speaker entities
│   │   └── audio_file.py      ← AudioFile value object
│   ├── services/
│   │   └── transcription_service.py  ← Pure business logic interface
│   └── ports/
│       ├── asr_port.py        ← ASR engine interface (Protocol)
│       ├── diarization_port.py ← Diarization interface (Protocol)
│       ├── storage_port.py    ← Transcript persistence interface
│       └── audio_processor_port.py ← Audio preprocessing interface
│
├── application/               ← Depends on Domain only
│   ├── use_cases/
│   │   ├── transcribe_audio.py    ← Orchestrates full pipeline
│   │   ├── diarize_excerpt.py     ← Excerpt diarization
│   │   └── list_transcripts.py    ← Transcript retrieval
│   └── dto/
│       ├── transcription_request.py
│       └── transcription_result.py
│
├── infrastructure/            ← Implements Domain ports
│   ├── asr/
│   │   └── whisper_adapter.py     ← Implements ASRPort using Whisper
│   ├── diarization/
│   │   └── pyannote_adapter.py    ← Implements DiarizationPort
│   ├── audio/
│   │   └── pydub_processor.py     ← Implements AudioProcessorPort
│   ├── persistence/
│   │   └── json_transcript_store.py ← Implements StoragePort (current JSON)
│   └── model_manager.py          ← Model lifecycle management
│
├── presentation/              ← Depends on Application
│   ├── api/
│   │   ├── transcription_router.py
│   │   ├── diarization_router.py
│   │   └── health_router.py
│   ├── schemas/
│   │   ├── requests.py        ← Pydantic request models
│   │   └── responses.py       ← Pydantic response models
│   └── middleware/
│       └── security.py        ← CORS, path validation
│
├── config.py                  ← App configuration
├── logging_setup.py           ← Logging configuration
└── main.py                    ← FastAPI app composition root
```

### Phase 2: AI-Native Integration

1. **Add Anthropic Claude** — Post-transcription analysis (summary, entity extraction, sentiment)
2. **Add Qdrant** — Index transcripts into `awa_conversations` collection for semantic search
3. **Add `qdrant_ingest` hook** — After every transcript write, auto-index
4. **Add transcript search API** — Semantic search across all transcripts
5. **Add SSE streaming** — Stream transcription progress as typed events
6. **Add Step Protocol** — Track per-step token/cost for any LLM calls

### Phase 3: Observability & Quality

1. **Add pytest suite** — Unit tests for domain, integration tests for adapters
2. **Add SSE event emission** — `step_reasoning`, `step_outcome`, `file_accessed`, `data_consumed`
3. **Add health check** — Proper `/health` endpoint with model status, GPU availability
4. **Add Docker multi-stage build** — Separate build/runtime stages
5. **Upgrade to Python 3.12** — In Dockerfile and CI
6. **Pin all dependencies** — Including `openai-whisper`
7. **Add CI pipeline** — Lint, type check, test on push

### Phase 4: Enhanced Outcomes

1. **Claude-powered transcript analysis** — After transcription, use Claude to generate:
   - Structured summary with key facts
   - Speaker identification suggestions
   - Chilean Spanish → formal Spanish translation
   - Legal relevance scoring (for Argus integration)
   - Entity extraction (names, locations, dates, claims)

2. **Transcript search & retrieval** — Qdrant-powered semantic search:
   - "Find all segments where someone mentions the flight"
   - "Show me confrontational exchanges"
   - Cross-transcript similarity detection

3. **Knowledge graph** — Neo4j for transcript relationships:
   - Speaker relationships across recordings
   - Timeline reconstruction
   - Evidence chain linking

---

## 15. Suggested Directory Restructure

### From (current):
```
src/
├── config.py           ← Flat settings
├── diarization.py      ← God file (450+ lines)
├── logging_setup.py    ← Logging
├── main.py             ← App + dead code
├── models.py           ← Models + schemas mixed
├── preprocessing.py    ← Audio processing
└── runpod_handler.py   ← Serverless handler
```

### To (proposed):
```
src/
├── domain/
│   ├── __init__.py
│   ├── entities/
│   │   ├── __init__.py
│   │   ├── transcript.py       ← Segment, Transcript, Speaker (dataclasses)
│   │   └── audio_file.py       ← AudioFile (path, format, duration, sample_rate)
│   └── ports/
│       ├── __init__.py
│       ├── asr_port.py          ← Protocol: transcribe(audio_path) -> list[Segment]
│       ├── diarization_port.py  ← Protocol: diarize(audio_path) -> list[Turn]
│       ├── audio_processor_port.py ← Protocol: process(path, params) -> path
│       └── transcript_store_port.py ← Protocol: save/load/search transcripts
│
├── application/
│   ├── __init__.py
│   └── use_cases/
│       ├── __init__.py
│       ├── transcribe_audio.py  ← TranscribeAudioUseCase
│       ├── diarize_excerpt.py   ← DiarizeExcerptUseCase
│       └── search_transcripts.py ← SearchTranscriptsUseCase
│
├── infrastructure/
│   ├── __init__.py
│   ├── whisper_adapter.py       ← WhisperASR implements ASRPort
│   ├── pyannote_adapter.py      ← PyAnnoteDiarizer implements DiarizationPort
│   ├── pydub_processor.py       ← PydubProcessor implements AudioProcessorPort
│   ├── json_store.py            ← JSONTranscriptStore implements TranscriptStorePort
│   ├── model_manager.py         ← ModelManager (lazy loading, caching, cleanup)
│   └── chilean_spanish.py       ← Post-processing rules
│
├── presentation/
│   ├── __init__.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── transcription.py     ← POST /api/diarization/transcribe
│   │   ├── diarization.py       ← POST /api/diarization/excerpt
│   │   ├── parameters.py        ← GET /api/diarization/parameters
│   │   └── health.py            ← GET /health
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── requests.py          ← TranscribeRequest, ExcerptRequest
│   │   └── responses.py         ← TranscriptResponse, ExcerptResponse, TimingResponse
│   └── middleware/
│       ├── __init__.py
│       └── path_validator.py    ← Validates file_path against allowed roots
│
├── config.py
├── logging_setup.py
├── main.py                       ← Composition root only
└── runpod_handler.py
```

---

## 16. Technology-Specific Migration Guide

### Step-by-step migration sequence

#### 16.1 Create Domain Entities (No dependencies)

```python
# src/domain/entities/transcript.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Speaker:
    label: str  # e.g. "SPEAKER_00"

@dataclass(frozen=True)
class Segment:
    index: int
    speaker: Speaker
    start: float
    end: float
    text: str = ""

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)

@dataclass
class Transcript:
    transcript_id: str
    segments: list[Segment] = field(default_factory=list)
    source_file: str = ""
    language: str = "es"
```

#### 16.2 Define Ports (Interfaces)

```python
# src/domain/ports/asr_port.py
from typing import Protocol
from domain.entities.transcript import Segment

class ASRPort(Protocol):
    def transcribe(
        self, audio_path: str, language: str, **kwargs
    ) -> list[Segment]: ...
```

```python
# src/domain/ports/diarization_port.py
from typing import Protocol
from dataclasses import dataclass

@dataclass(frozen=True)
class Turn:
    speaker: str
    start: float
    end: float

class DiarizationPort(Protocol):
    def diarize(
        self, audio_path: str, min_speakers: int, max_speakers: int, **kwargs
    ) -> list[Turn]: ...
```

#### 16.3 Implement Infrastructure Adapters

```python
# src/infrastructure/whisper_adapter.py
from domain.ports.asr_port import ASRPort
from domain.entities.transcript import Segment, Speaker

class WhisperASRAdapter:
    """Implements ASRPort using OpenAI Whisper."""

    def __init__(self, model_manager):
        self._model_manager = model_manager

    def transcribe(self, audio_path: str, language: str = "es", **kwargs) -> list[Segment]:
        model = self._model_manager.get_whisper_model(kwargs.get("model_size", "large-v3"))
        result = model.transcribe(audio_path, language=language, **kwargs)
        return [
            Segment(
                index=i,
                speaker=Speaker(label="UNKNOWN"),
                start=seg["start"],
                end=seg["end"],
                text=seg["text"]
            )
            for i, seg in enumerate(result.get("segments", []), 1)
        ]
```

#### 16.4 Create Use Cases

```python
# src/application/use_cases/transcribe_audio.py
from domain.ports.asr_port import ASRPort
from domain.ports.diarization_port import DiarizationPort
from domain.ports.audio_processor_port import AudioProcessorPort
from domain.ports.transcript_store_port import TranscriptStorePort
from domain.entities.transcript import Transcript, Segment, Speaker

class TranscribeAudioUseCase:
    def __init__(
        self,
        asr: ASRPort,
        diarizer: DiarizationPort,
        processor: AudioProcessorPort,
        store: TranscriptStorePort,
    ):
        self._asr = asr
        self._diarizer = diarizer
        self._processor = processor
        self._store = store

    async def execute(self, audio_path: str, params: dict) -> Transcript:
        processed = self._processor.process(audio_path, params)
        turns = self._diarizer.diarize(processed, params["min_speakers"], params["max_speakers"])
        segments = []
        for i, turn in enumerate(turns, 1):
            seg_results = self._asr.transcribe(
                processed, language=params.get("language", "es"),
                # ... whisper kwargs
            )
            segments.append(Segment(
                index=i,
                speaker=Speaker(label=turn.speaker),
                start=turn.start,
                end=turn.end,
                text=seg_results[0].text if seg_results else ""
            ))
        transcript = Transcript(
            transcript_id=f"transcript_{int(time.time())}",
            segments=segments,
            source_file=audio_path,
        )
        self._store.save(transcript)
        return transcript
```

#### 16.5 Presentation Layer (Thin routes)

```python
# src/presentation/routers/transcription.py
from fastapi import APIRouter, UploadFile, File, Form, Depends
from application.use_cases.transcribe_audio import TranscribeAudioUseCase
from presentation.schemas.responses import TranscriptResponse

router = APIRouter(prefix="/api/diarization", tags=["transcription"])

@router.post("/transcribe", response_model=TranscriptResponse)
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("es-CL"),
    model_size: str = Form("large-v3"),
    # ... other params
    use_case: TranscribeAudioUseCase = Depends(get_transcribe_use_case),
):
    # Save upload, call use case, return typed response
    ...
```

#### 16.6 Add Path Validation Middleware

```python
# src/presentation/middleware/path_validator.py
import os
from pathlib import Path

ALLOWED_ROOTS = [
    Path("data/audio").resolve(),
    Path("data/originals").resolve(),
]

def validate_file_path(file_path: str) -> Path:
    resolved = Path(file_path).resolve()
    if not any(resolved.is_relative_to(root) for root in ALLOWED_ROOTS):
        raise ValueError(f"Access denied: path outside allowed directories")
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    return resolved
```

#### 16.7 AI-Native Enhancement (Phase 2)

```python
# src/infrastructure/claude_analyzer.py
import anthropic
import os

class ClaudeTranscriptAnalyzer:
    """Post-transcription analysis using Anthropic Claude."""

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    async def analyze(self, transcript: Transcript) -> dict:
        text = "\n".join(
            f"[{s.speaker.label}] ({s.start:.1f}s-{s.end:.1f}s): {s.text}"
            for s in transcript.segments
        )
        response = self._client.messages.create(
            model="deepseek-v4-pro",
            max_tokens=4096,
            system="You are a legal transcript analyst specializing in Chilean Spanish.",
            messages=[{"role": "user", "content": f"Analyze this transcript:\n\n{text}"}]
        )
        return {
            "summary": response.content[0].text,
            "model": "deepseek-v4-pro",
            "tokens_in": response.usage.input_tokens,
            "tokens_out": response.usage.output_tokens,
        }
```

---

## 17. Suggested Documentation Additions

| Document | Purpose | Priority |
|----------|---------|----------|
| `.gitignore` | Exclude secrets, caches, data files | 🔴 IMMEDIATE |
| `README.md` | Replace `sa-transcription.md` with proper README | 🟡 High |
| `ARCHITECTURE.md` | Document Clean Architecture layers and ports | 🟡 High |
| `API.md` | OpenAPI-generated API documentation | 🟡 High |
| `CONTRIBUTING.md` | Development setup, testing, PR guidelines | 🟢 Medium |
| `CHANGELOG.md` | Track changes per version | 🟢 Medium |
| `pytest.ini` / `pyproject.toml` | Test configuration | 🟡 High |
| `Makefile` | Common commands (test, lint, build, run) | 🟢 Medium |

---

## 18. Session Token & Cost Summary

| Step | Tool | Tokens In | Tokens Out | Cost USD |
|------|------|-----------|-----------|----------|
| 1 | Read coding standards | ~800 | — | — |
| 2 | Read skill instructions | ~1,200 | — | — |
| 3 | Read all src/ files (7 files) | ~3,500 | — | — |
| 4 | Read infra files (Docker, compose, requirements) | ~600 | — | — |
| 5 | Read remaining files (.env, data, docs) | ~900 | — | — |
| 6 | Analysis & report generation | ~7,000 input | ~12,000 output | — |
| **Total** | | **~14,000** | **~12,000** | **~$0.22** |

*Cost estimate based on Sonnet pricing: $3/1M input, $15/1M output*

---

## Appendix A: Immediate Action Checklist

- [ ] **NOW:** Rotate HuggingFace token (`hf_mreOwhhP...`) — it's exposed in `.env` and `RUNPOD_SETUP.md`
- [ ] **NOW:** Rotate Runpod API key (`rpa_1BX7VV...`) — exposed in `.env` and `RUNPOD_SETUP.md`
- [ ] **NOW:** Create `.gitignore` (see below)
- [ ] **NOW:** Scrub `RUNPOD_SETUP.md` of all real tokens
- [ ] **NOW:** Fix CORS to specific origins
- [ ] **NOW:** Add path traversal protection to `file_path` parameters
- [ ] **WEEK 1:** Remove dead code (`run_transcription`, `analyze_audio_segments`)
- [ ] **WEEK 1:** Pin `openai-whisper` version
- [ ] **WEEK 1:** Remove unused deps (`aiofiles`, `psutil`)
- [ ] **WEEK 2-3:** Implement Clean Architecture restructure (Phase 1)
- [ ] **WEEK 4:** Add test suite
- [ ] **MONTH 2:** AI-Native integration (Phase 2)

## Appendix B: Suggested .gitignore

```gitignore
# Environment & Secrets
.env
*.env
!.env.example

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
*.egg-info/
dist/
build/

# Virtual environments
venv/
.venv/
env/

# Data (large files, user recordings)
data/audio/
data/originals/
data/transcripts/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Docker
*.log
```

---

*Awareness-AI Architectural Auditor v2.0 · Audit Complete · 2026-03-09*
