# federal-register-mcp

<!-- mcp-name: io.github.1102tools/federal-register-mcp -->

MCP server for the Federal Register API. Proposed rules, final rules, notices, executive orders, comment periods, and regulatory tracking since 1994.

No authentication required. MCP is an open standard: this server runs in any MCP client, not just Claude. Executed and verified on eleven platforms in August 2026 (see [Configuration](#configuration)).

*Tested and hardened through six rounds of integration testing against the live Federal Register API. 228 regression tests (132 offline, 96 live-gated) covering the `list_agencies` pydantic crash that hit every call, payload bombs, silent-wrong-data docket matches, the pre-2011 archive lockout, and open-comment results that missed the soonest deadlines. See [testing.md](testing.md) for the full testing record.*

## What it does

Exposes the Federal Register API as 8 MCP tools:

**Core**
- `search_documents` - Search with flexible filters (agency, type, term, docket, dates, RIN, CFR title/part)
- `get_document` - Full details for a single document by number
- `get_documents_batch` - Fetch up to 20 documents in one call
- `get_facet_counts` - Document counts by type, agency, topic, or time bucket (daily through yearly)
- `get_public_inspection` - Pre-publication documents with client-side filtering
- `list_agencies` - All ~470 agencies with slugs

**Workflow**
- `open_comment_periods` - Currently open comment periods (sorted by deadline)
- `far_case_history` - Full rulemaking history for a FAR/DFARS case

## No authentication required

The Federal Register API is fully public. No key, no registration.

## Installation

```bash
uvx federal-register-mcp
```

## Configuration

MCP is an open standard, and this config was executed and verified in August 2026 on eleven platforms: Claude Desktop, Claude Code, Codex Desktop and CLI, Gemini via Antigravity, GitHub Copilot CLI, DeepSeek Harness, Grok Build, Cursor, opencode, and LibreChat. Most clients take the same JSON block below and differ only in where the config file lives; the [universal setup guide (PDF)](https://1102tools.com/downloads/1102tools-universal-setup.pdf) has the exact file path and format for every platform, including the Codex TOML form.

```json
{
  "mcpServers": {
    "federal-register": {
      "command": "uvx",
      "args": ["--refresh-package", "federal-register-mcp", "--from", "federal-register-mcp", "federal-register-mcp"]
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

Restart the client and the tools appear.

## Example prompts

- "What FAR cases have open comment periods right now?"
- "Show me the full rulemaking history for FAR Case 2023-008."
- "Find all proposed rules from DoD published in the last 6 months."
- "What significant rules has GSA published this fiscal year?"
- "Are there any pre-publication documents related to procurement today?"
- "How many proposed rules vs final rules has the SBA published since January?"
- "Find executive orders related to federal acquisition from the last year."

## Companion tools

- `ecfr-mcp`: what the regulation currently says (the book)
- `federal-register-mcp`: what is changing (the newspaper)

Together they cover the full regulatory pipeline. Use `far_case_history` to trace a rulemaking from proposal through final rule, then `ecfr-mcp` to read the codified result.

## License

MIT
