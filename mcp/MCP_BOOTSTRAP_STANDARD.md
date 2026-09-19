# MCP Bootstrap Standard

Use this standard when a project has an `mcp/` folder but no discovered MCP tools.

## Goal

Every project in the ecosystem should expose MCP tools using one of the approved patterns:

- `python-fastmcp-multi` (multiple domain servers under `src/mcp/servers/`)
- `node-mcp-single` (single JS server under `mcp/`)

## Minimum Required Artifacts

1. `mcp/README.md`
2. `mcp/MCP_ARCHITECTURE.md`
3. `mcp/mcpServers.example.json`
4. MCP server implementation file(s)
5. Readiness generator script
6. Readiness report with endpoint coverage

## Naming Rules

- Tool names are snake_case.
- Tool names must be prefixed by service name.
- Examples: `transcription_transcribe`, `legalpipeline_case_search`.

## Safety Rules

- Destructive operations must require `confirm=true`.
- API base URL and tokens must come from environment variables.
- No hardcoded secrets.

## Readiness Rules

- Report must show discovered endpoints, mapped endpoints, missing endpoints, and coverage.
- Expected state: `ready` and `0` missing in-scope endpoints.

## Agent Instruction Contract

When asking an agent to bootstrap MCP in a project with no tools, instruct it to:

1. Inventory backend endpoints and classify in-scope vs excluded.
2. Create MCP server(s) following one approved pattern.
3. Apply naming/safety rules from this standard.
4. Generate readiness artifacts and verify coverage.
5. Add `mcpServers.example.json` runnable entries.
6. Update local `mcp/README.md` with tool inventory.
7. Run syntax checks and provide a completion summary.

## Definition Of Done

A project is MCP-ready only when:

- The server starts without runtime errors.
- Tool names pass prefix + snake_case checks.
- Readiness report says `ready` and `missing=0` for in-scope endpoints.
- `mcpServers.example.json` can be used by clients without manual edits except URLs/tokens.
