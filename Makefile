.PHONY: run dev test test-unit lint typecheck clean docker-build docker-up

# ── Run ──────────────────────────────────────────────────────
run:
	PYTHONWARNINGS="ignore:invalid escape sequence:SyntaxWarning" uvicorn src.main:app --host 0.0.0.0 --port 8049

dev:
	PYTHONWARNINGS="ignore:invalid escape sequence:SyntaxWarning" uvicorn src.main:app --host 0.0.0.0 --port 8049 --reload

run-mcp-transcription:
	python -m src.mcp.servers.transcription_server

run-mcp-transcripts:
	python -m src.mcp.servers.transcripts_server

run-mcp-meta:
	python -m src.mcp.servers.meta_server

# ── Testing ──────────────────────────────────────────────────
test:
	python -m pytest tests/ -v

test-unit:
	python -m pytest tests/unit/ -v

test-integration:
	python -m pytest tests/integration/ -v

test-refine:
	python -m pytest tests/unit/test_transcript_auditor.py \
	       tests/unit/test_transcript_patcher.py \
	       tests/unit/test_validate_and_refine_transcript.py \
	       tests/unit/test_validate_refine_mcp.py -v

# ── Quality ──────────────────────────────────────────────────
lint:
	ruff check src/ tests/

lint-fix:
	ruff check --fix src/ tests/

typecheck:
	mypy src/ --ignore-missing-imports

# ── Docker ───────────────────────────────────────────────────
docker-build:
	docker build -t sa-transcription .

docker-up:
	docker compose up --build

# ── Cleanup ──────────────────────────────────────────────────
clean:
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true
