# ecfr-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 13](https://img.shields.io/badge/tools-13-007a59)](#what-it-does) [![regression tests: 449](https://img.shields.io/badge/regression%20tests-449-007a59)](testing.md)

<!-- mcp-name: com.1102tools/ecfr-mcp -->

Free, open-source MCP server for the eCFR (Electronic Code of Federal Regulations) API. Read FAR, DFARS, and all agency FAR supplement text with no authentication required.

No API key required, locally or hosted. See [Local or hosted](#local-or-hosted).

*Tested and hardened through eight rounds of testing against the live eCFR API. 449 collected regression tests (331 offline, 118 live-gated), including a check that every piece of text in ten saved eCFR responses comes out exactly once and in order. Round 8 (1.1.0, October 2026) fixed 18 P2 and about 20 P3 findings from a six-agent bug hunt plus an everyday-questions pass. The 1.1.4 release carries three P2 corrections in definition matching, historical-read followups and scoped editorial corrections. See [testing.md](testing.md) for the full testing record.*

## Local or hosted

| Local (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|
| [Local setup](#installation) | [Install](https://claude.ai/directory/ecfr-by-1102tools) | [Install](https://chatgpt.com/plugins/plugin_asdk_app_6a9ef0341b04819192935fd4e5cd9b34) |

- **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. You get your own full rate limits, and it relies only on the government service. You don't have to set it up by hand: give your AI this page's link and ask it to set it up or walk you through it.
- **Hosted** is the convenient option: one click, no keys, and it works in Claude or ChatGPT anywhere.

[Compare local and hosted](../../#local-or-hosted) · [Matching prompts](https://1102tools.com/#ecfr)

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

Use the configuration below as the server definition and adapt its placement to your compatible MCP client. For practical requests using this source, see the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

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

[federal-contracting-mcps](https://github.com/1102tools-dev/federal-contracting-mcps): monorepo of 9 MCP servers for federal contracting data. Pair these sources with the [MCP prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

## License

MIT
