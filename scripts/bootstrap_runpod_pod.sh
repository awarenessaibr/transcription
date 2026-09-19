#!/usr/bin/env bash
set -euo pipefail

REPO_DIR_DEFAULT="/workspace/sa-transcription"
APP_PORT_DEFAULT="8888"
PYTHON_BIN_DEFAULT="python3"

REPO_DIR="${REPO_DIR:-$REPO_DIR_DEFAULT}"
APP_PORT="${APP_PORT:-$APP_PORT_DEFAULT}"
PYTHON_BIN="${PYTHON_BIN:-$PYTHON_BIN_DEFAULT}"
START_MODE="${START_MODE:-foreground}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
  printf '\n[%s] %s\n' "bootstrap" "$1"
}

die() {
  printf '\n[bootstrap] ERROR: %s\n' "$1" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

apt_install_if_missing() {
  local packages=()
  for pkg in "$@"; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
      packages+=("$pkg")
    fi
  done

  if [ "${#packages[@]}" -gt 0 ]; then
    log "Installing system packages: ${packages[*]}"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
  fi
}

require_env_value() {
  local key="$1"
  local value="${!key:-}"
  if [ -z "$value" ] || [[ "$value" == your_* ]] || [[ "$value" == *"<YOUR"* ]]; then
    die "Environment variable $key is required. Export it before running this script or edit $REPO_DIR/.env afterward."
  fi
}

write_env_file() {
  local env_file="$REPO_DIR/.env"
  if [ -f "$env_file" ]; then
    log "Preserving existing .env at $env_file"
    return
  fi

  [ -f "$REPO_DIR/.env.example" ] || die ".env.example not found in $REPO_DIR"

  log "Creating .env from .env.example"
  cp "$REPO_DIR/.env.example" "$env_file"

  python3 - "$env_file" <<'PY'
from pathlib import Path
import os

env_path = Path(__import__("sys").argv[1])
content = env_path.read_text()
replacements = {
    "HUGGINGFACE_HUB_TOKEN=your_new_hf_token_here": f"HUGGINGFACE_HUB_TOKEN={os.environ.get('HUGGINGFACE_HUB_TOKEN', '')}",
    "PYANNOTE_AUTH_TOKEN=your_new_hf_token_here": f"PYANNOTE_AUTH_TOKEN={os.environ.get('PYANNOTE_AUTH_TOKEN', '')}",
    "use_auth_token=your_new_hf_token_here": f"use_auth_token={os.environ.get('PYANNOTE_AUTH_TOKEN', '')}",
    "ANTHROPIC_API_KEY=your_anthropic_api_key_here": f"ANTHROPIC_API_KEY={os.environ.get('ANTHROPIC_API_KEY', '""').strip()}",
    "QDRANT_URL=http://localhost:6333": f"QDRANT_URL={os.environ.get('QDRANT_URL', 'http://localhost:6333')}",
    "QDRANT_API_KEY=": f"QDRANT_API_KEY={os.environ.get('QDRANT_API_KEY', '')}",
    "CORS_ORIGINS=http://localhost:3000,http://localhost:8000": f"CORS_ORIGINS={os.environ.get('CORS_ORIGINS', 'http://localhost:3000,http://localhost:8000')}",
}

for old, new in replacements.items():
    content = content.replace(old, new)

env_path.write_text(content)
PY
}

ensure_repo_location() {
  if [ "$PROJECT_ROOT" = "$REPO_DIR" ]; then
    return
  fi

  if [ ! -d "$REPO_DIR" ]; then
    log "Copying repository to $REPO_DIR"
    mkdir -p "$(dirname "$REPO_DIR")"
    cp -R "$PROJECT_ROOT" "$REPO_DIR"
    return
  fi

  if [ ! -f "$REPO_DIR/pyproject.toml" ]; then
    die "$REPO_DIR exists but does not look like the sa-transcription repository"
  fi
}

check_python_version() {
  local version
  version="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [ "$version" != "3.12" ] && [ "$version" != "3.13" ]; then
    die "This repo expects Python 3.12+. Found $version from $PYTHON_BIN"
  fi
}

install_python_deps() {
  log "Creating virtualenv"
  "$PYTHON_BIN" -m venv "$REPO_DIR/venv"

  log "Installing Python dependencies"
  source "$REPO_DIR/venv/bin/activate"
  python -m pip install --upgrade pip setuptools wheel
  pip install -r "$REPO_DIR/requirements.txt"
}

prepare_runtime() {
  log "Preparing runtime directories"
  mkdir -p "$REPO_DIR/data/audio" "$REPO_DIR/data/originals" "$REPO_DIR/data/transcripts"
}

print_summary() {
  local pod_ip
  pod_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"

  printf '\n'
  printf '============================================================\n'
  printf 'SA-transcription Pod bootstrap complete\n'
  printf '============================================================\n'
  printf 'Repo: %s\n' "$REPO_DIR"
  printf 'Port: %s\n' "$APP_PORT"
  printf 'Python: %s\n' "$PYTHON_BIN"
  printf 'Start mode: %s\n' "$START_MODE"
  if [ -n "$pod_ip" ]; then
    printf 'Health: http://%s:%s/health\n' "$pod_ip" "$APP_PORT"
  fi
  printf '\n'
  printf 'Run manually later with:\n'
  printf '  cd %s && source venv/bin/activate && uvicorn src.main:app --host 0.0.0.0 --port %s\n' "$REPO_DIR" "$APP_PORT"
  printf '\n'
}

start_app() {
  source "$REPO_DIR/venv/bin/activate"
  cd "$REPO_DIR"

  if [ "$START_MODE" = "background" ]; then
    log "Starting API in background on port $APP_PORT"
    nohup uvicorn src.main:app --host 0.0.0.0 --port "$APP_PORT" > "$REPO_DIR/pod-api.log" 2>&1 &
    printf '%s\n' $! > "$REPO_DIR/pod-api.pid"
    sleep 3
    return
  fi

  log "Starting API in foreground on port $APP_PORT"
  exec uvicorn src.main:app --host 0.0.0.0 --port "$APP_PORT"
}

main() {
  [ "$(id -u)" -eq 0 ] || die "Run this script as root on the Pod so it can install ffmpeg if needed"

  require_env_value PYANNOTE_AUTH_TOKEN
  require_env_value HUGGINGFACE_HUB_TOKEN

  export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:$APP_PORT,http://127.0.0.1:$APP_PORT}"

  ensure_repo_location
  apt_install_if_missing ffmpeg git

  command_exists "$PYTHON_BIN" || die "$PYTHON_BIN not found"
  check_python_version

  write_env_file
  install_python_deps
  prepare_runtime
  print_summary
  start_app
}

main "$@"