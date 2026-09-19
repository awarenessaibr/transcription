#!/usr/bin/env bash
# transcription - stop API + MCP servers
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-${transcription_PORT:-8049}}"
QUIET="${1:-}"

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

# ── Colors ──
R='\033[0;31m' G='\033[0;32m' A='\033[0;33m' C='\033[0;36m' W='\033[1;37m' N='\033[0m'
info()  { printf "${C}▸${N} %s\n" "$*"; }
ok()    { printf "${G}✓${N} %s\n" "$*"; }
warn()  { printf "${A}⚠${N} %s\n" "$*"; }
fail()  { printf "${R}✗${N} %s\n" "$*"; exit 1; }

# ── Stop services ──
info "Stopping transcription services..."

stop_by_pid_file "transcription" "api"
stop_by_pid_file "transcription" "mcp-transcription"
stop_by_pid_file "transcription" "mcp-transcripts"
stop_by_pid_file "transcription" "mcp-meta"

# Belt-and-braces: kill anything on our ports
kill_port "transcription" "api" "$PORT"
kill_port "transcription" "mcp-transcription" 8121
kill_port "transcription" "mcp-transcripts" 8122
kill_port "transcription" "mcp-meta" 8123

pkill -f "src.mcp.servers.transcription_server" 2>/dev/null || true
pkill -f "src.mcp.servers.transcripts_server" 2>/dev/null || true
pkill -f "src.mcp.servers.meta_server" 2>/dev/null || true

[[ "$QUIET" == "--quiet" ]] || ok "transcription stopped — logs preserved in .dev-logs/"