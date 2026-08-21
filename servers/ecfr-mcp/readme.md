# ecfr-mcp

<!-- mcp-name: io.github.1102tools/ecfr-mcp -->

MCP server for the eCFR (Electronic Code of Federal Regulations) API. Read FAR, DFARS, and all agency FAR supplement text with no authentication required.

MCP is an open standard: this server runs in any MCP client, not just Claude. Executed and verified on eleven platforms in August 2026 (see [Configuration](#configuration)).

*Tested and hardened through six rounds of integration testing against the live eCFR API. 295 regression tests (182 offline, 113 live-gated) covering 2 P0 catastrophic bugs, 26 P1 silent-wrong-data bugs, 32 P2 validation gaps, and the round-6 audit fixes (Title 48 chapter whitelist, table extraction, appendix access). See [testing.md](testing.md) for the full testing record.*

## What it does

Exposes the eCFR API as 13 MCP tools covering regulatory text, structure, search, version history, and common acquisition workflows:

**Core endpoints**
- `get_latest_date` - Get the most recent available date for a CFR title (call before other tools)
- `get_cfr_content` - Get parsed regulatory text for a section, subpart, or part
- `get_cfr_structure` - Hierarchical table of contents
- `get_version_history` - Amendment history for a section or part
- `get_ancestry` - Breadcrumb hierarchy path
- `search_cfr` - Full-text search with hierarchy filters
- `list_agencies` - All agencies with their CFR references
- `get_corrections` - Editorial corrections for a title

**Workflow convenience**
- `lookup_far_clause` - One-call FAR/DFARS clause text lookup (auto-resolves date)
- `compare_versions` - Side-by-side text comparison at two dates
- `list_sections_in_part` - All sections in a FAR/DFARS part
- `find_far_definition` - Search FAR 2.101 for a term definition
- `find_recent_changes` - Sections modified since a given date

## No authentication required

The eCFR API is fully public. No API key, no registration, no auth headers. Just install and use.

## Installation

### Via uvx (recommended)

```bash
uvx ecfr-mcp
```

### Via pip

```bash
pip install ecfr-mcp
```

### From source

```bash
git clone https://github.com/1102tools-dev/federal-contracting-mcps.git
cd federal-contracting-mcps/servers/ecfr-mcp
pip install -e .
```

## Configuration

MCP is an open standard, and this config was executed and verified in August 2026 on eleven platforms: Claude Desktop, Claude Code, Codex Desktop and CLI, Gemini via Antigravity, GitHub Copilot CLI, DeepSeek Harness, Grok Build, Cursor, opencode, and LibreChat. Most clients take the same JSON block below and differ only in where the config file lives; the [universal setup guide (PDF)](https://1102tools.com/downloads/1102tools-universal-setup.pdf) has the exact file path and format for every platform, including the Codex TOML form.

```json
{
  "mcpServers": {
    "ecfr": {
      "command": "uvx",
      "args": ["--refresh-package", "ecfr-mcp", "--from", "ecfr-mcp", "ecfr-mcp"]
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

Restart the client. The `ecfr` server appears with 13 tools.

## Example prompts

- "Pull the current text of FAR 15.305 (Proposal Evaluation) and summarize what it requires."
- "List all sections in FAR Part 19 (Small Business Programs)."
- "Look up the FAR definition of 'commercial product' in 2.101."
- "What FAR sections were amended in the last 6 months?"
- "Compare FAR 52.212-4 between 2024-01-01 and 2025-01-01 and show me what changed."
- "Get the current text of DFARS 252.227-7014 (Rights in Noncommercial Computer Software)."
- "Search Title 48 for 'organizational conflict of interest' and show me the relevant sections."
- "Which agency owns Chapter 8 in Title 48? Get their FAR supplement structure."

## Design notes

- **XML parsed server-side.** The eCFR content endpoint returns raw XML. This server parses it into clean text (headings, paragraphs, citations) before returning to the model, saving significant context tokens.
- **Automatic date resolution.** eCFR lags 1-2 business days behind the Federal Register. Using today's date on versioner endpoints causes 404 errors. All content tools auto-resolve to the latest available date unless you specify one.
- **Search defaults to current text.** Without `date=current`, eCFR search returns ALL historical versions including superseded. Default `current_only=True` prevents duplicate results.
- **Structure endpoint limitation.** The eCFR structure endpoint does not support section-level filtering (returns 400). `list_sections_in_part` works around this by fetching the part structure and walking the tree.
- **FAR 2.101 optimization.** The definitions section is ~109KB of XML. `find_far_definition` parses the full section server-side and returns only matching paragraphs with context.

## CFR Title 48 quick reference

| Chapter | Regulation | Parts |
|---|---|---|
| 1 | FAR | 1-99 |
| 2 | DFARS | 200-299 |
| 3 | HHSAR | 300-399 |
| 4 | AGAR | 400-499 |
| 5 | GSAR | 500-599 |
| 6 | DOSAR | 600-699 |
| 7 | AIDAR | 700-799 |
| 8 | VAAR | 800-899 |
| 9 | DEAR | 900-999 |
| 18 | NFS | 1800-1899 |

## Data source

All data from [ecfr.gov](https://www.ecfr.gov), the continuously updated online Code of Federal Regulations maintained by the Office of the Federal Register. Updated daily, typically 1-2 business days after Federal Register publication. Not an official legal edition; for official citations reference the annual CFR from GPO.

## Part of

[federal-contracting-mcps](https://github.com/1102tools-dev/federal-contracting-mcps): monorepo of 8 MCP servers for federal contracting data. Companion to [federal-contracting-skills](https://github.com/1102tools-dev/federal-contracting-skills).

## Request pacing

Every upstream request uses a provisional 3-second cross-process anti-burst
interval by default. eCFR does not publish a numeric limit, so this is a
1102tools safeguard rather than a provider requirement. Override with
`FEDERAL_API_MIN_INTERVAL_SECONDS`, use `0` to deliberately disable it, and
use `FEDERAL_API_PACING_DIR` to relocate local pacing state.

## License

MIT
