# transcription MCP Architecture

This folder follows the canonical MCP architecture standard at:
`/Users/leandrodisconzi/2026/garage-main/mcp/MCP_ARCHITECTURE.md`.

## Pattern

- Pattern: `python-fastmcp-multi`
- Servers live under `src/mcp/servers/`
- Transport: stdio
- Runtime style: direct invocation via existing project composition/use cases

## Servers

- `src/mcp/servers/transcription_server.py` (`transcription-transcription`)
- `src/mcp/servers/transcripts_server.py` (`transcription-transcripts`)
- `src/mcp/servers/meta_server.py` (`transcription-meta`)

## Naming Rules

- Tool names are snake_case
- Tool names are prefixed with `transcription_`

## Safety Rules

- No hardcoded secrets
- Runtime config provided through environment variables in MCP client config
- No destructive delete/reset operations are exposed in this bootstrap set

## Coverage Strategy

- Endpoint discovery source: `src/presentation/routers/*.py`
- MCP tool discovery source: `src/mcp/servers/*.py`
- Mapping source of truth: `mcp/generate_readiness_report.py`

## Validation

- Syntax check:
  - `python -m py_compile src/mcp/servers/*.py mcp/generate_readiness_report.py`
- Readiness generation:
  - `python mcp/generate_readiness_report.py`
- Startup check:
  - `python -m src.mcp.servers.meta_server`
  - `python -m src.mcp.servers.transcription_server`
  - `python -m src.mcp.servers.transcripts_server`
