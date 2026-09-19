#!/usr/bin/env bash
# transcription - start API + MCP servers
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-${transcription_PORT:-8049}}"
APP_URL="${APP_URL:-http://${HOST}:${PORT}/pinocchio}"

MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"

VENV_DIR="$SCRIPT_DIR/.venv"
if [[ -x "$VENV_DIR/bin/python" ]] && ! "$VENV_DIR/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' >/dev/null 2>&1; then
    VENV_DIR="$SCRIPT_DIR/.venv-py312"
fi
PYTHON_BIN="$VENV_DIR/bin/python"
UVICORN_BIN="$VENV_DIR/bin/uvicorn"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
REQUIREMENTS_STAMP="$VENV_DIR/.requirements-stamp"

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

mkdir -p "$(dirname "$(get_log_file "transcription" "api")")"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Creating transcription Python environment"
    python3.12 -m venv "$VENV_DIR"
fi
if [[ -f "$REQUIREMENTS_FILE" && ( ! -f "$REQUIREMENTS_STAMP" || "$REQUIREMENTS_FILE" -nt "$REQUIREMENTS_STAMP" ) ]]; then
    echo "Installing transcription Python dependencies"
    "$PYTHON_BIN" -m pip install -q --upgrade pip
    "$PYTHON_BIN" -m pip install -q -r "$REQUIREMENTS_FILE"
    touch "$REQUIREMENTS_STAMP"
fi
if [[ ! -x "$UVICORN_BIN" ]]; then
    echo "transcription Python environment is missing uvicorn" >&2
    exit 1
fi

"$SCRIPT_DIR/stop.sh" --quiet || true

echo "Updating speaker indices and MD files..."
"$PYTHON_BIN" "$SCRIPT_DIR/scripts/generate_speaker_index_v3.py" > /dev/null || true
"$PYTHON_BIN" "$SCRIPT_DIR/scripts/generate_speaker_md_files.py" > /dev/null || true

echo "Starting transcription API on ${HOST}:${PORT}"
start_logging "transcription" "api" env PYTHONUNBUFFERED=1 "$UVICORN_BIN" src.main:app --host "$HOST" --port "$PORT"

echo "Starting transcription MCP servers (${MCP_TRANSPORT})"
start_logging "transcription" "mcp-transcription" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8121 \
    "$PYTHON_BIN" -m src.mcp.servers.transcription_server
start_logging "transcription" "mcp-transcripts" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8122 \
    "$PYTHON_BIN" -m src.mcp.servers.transcripts_server
start_logging "transcription" "mcp-meta" env PYTHONUNBUFFERED=1 MCP_TRANSPORT="$MCP_TRANSPORT" MCP_HOST="$MCP_HOST" MCP_PORT=8123 \
    "$PYTHON_BIN" -m src.mcp.servers.meta_server

echo "Waiting for API health endpoint"
for _ in $(seq 1 120); do
    if curl -sf "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

for port in 8121 8122 8123; do
    if ! wait_for_port "$port" 120; then
        echo "transcription MCP server failed to listen on port $port" >&2
        exit 1
    fi
done

if [[ -n "${OPEN_APP:-}" ]]; then
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$APP_URL" >/dev/null 2>&1 || true
    elif command -v open >/dev/null 2>&1; then
        open "$APP_URL" >/dev/null 2>&1 || true
    fi
fi

echo ""
echo "transcription is running"
echo "  URL  : $APP_URL"
echo "  Logs : .dev-logs/transcription/"
echo "  Stop : ./stop.sh"