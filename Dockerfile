# ── Stage 1: Build ──────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y gcc python3-dev git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade "pip<24" "setuptools<70" wheel \
    && pip install --prefix=/install --ignore-installed -r requirements.txt

# ── Stage 2: Runtime ────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /workspace

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY . .

# Default: RunPod serverless handler
# For local/docker-compose, override: uvicorn src.main:app --host 0.0.0.0 --port 8000
CMD ["python", "-u", "-m", "src.runpod_handler"]
