#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

<<<<<<< HEAD
PORT="${PORT:-${transcription_PORT:-8049}}"
=======
PORT="${PORT:-${transcription_PORT:-8040}}"
>>>>>>> ab0e50d (feat: implement region selection and comparison features)
VENV_BIN="$SCRIPT_DIR/.venv/bin"

require_py312() {
	if ! "$VENV_BIN/python" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)'; then
		echo "Error: .venv was created with $("$VENV_BIN/python" -V 2>&1), but this project requires Python 3.12.x."
		echo "Recreate the virtualenv with: rm -rf .venv && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt"
		exit 1
	fi
}

if [ ! -x "$VENV_BIN/python" ]; then
	python3.12 -m venv "$SCRIPT_DIR/.venv"
	"$VENV_BIN/pip" install -q -r requirements.txt
else
	require_py312
fi

echo "Starting SA-transcription Transcription API on :$PORT..."
exec "$VENV_BIN/uvicorn" src.main:app --host 0.0.0.0 --port "$PORT" --reload
