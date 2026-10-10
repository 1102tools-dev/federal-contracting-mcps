# bls-oews-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 8](https://img.shields.io/badge/tools-8-007a59)](#what-it-does) [![regression tests: 298](https://img.shields.io/badge/regression%20tests-298-007a59)](testing.md)

<!-- mcp-name: com.1102tools/bls-oews-mcp -->

Free, open-source MCP server for BLS Occupational Employment and Wage Statistics (OEWS) market wages. For IGCE development, price analysis, and labor market research.

No API key and no daily limit. The package bundles the current OEWS release (May 2025 estimates, published by BLS on May 15, 2026) as a read-only database built from BLS's published flat files, so every answer is local and each result cites the BLS release, publication date, retrieval date, and source file. See [Local or hosted](#local-or-hosted).

*Tested and hardened through a 5-round retroactive live audit with a real BLS API key after the initial smoke test reported zero bugs, then round 7's full-source re-audit and round 9's source-backed content corrections. 295 collected regression tests (294 offline, 1 live parity check against the BLS API), covering the 1 P0 usability-breaking bug (SOC format), 10 P1 silent-wrong-data bugs, 12 P1 response-shape crash paths, and 7 P2 validation gaps fixed in that audit. See [testing.md](testing.md) for the full testing record.*

## Local or hosted

| Local (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|
| [Local setup](#installation) | [Install](https://claude.ai/directory/bls-oews-by-1102tools) | [Install](https://chatgpt.com/plugins/plugin_asdk_app_6ab872bf5360819186af0917c923e57e) |

- **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. You get your own full rate limits, and it relies only on the government service. You don't have to set it up by hand: give your AI this page's link and ask it to set it up or walk you through it.
- **Hosted** is the convenient option: one click, no keys, and it works in Claude or ChatGPT anywhere.

[Compare local and hosted](../../#local-or-hosted) · [Matching prompts](https://1102tools.com/#bls-oews)

## What it does

Answers OEWS questions from the bundled release through 8 MCP tools:

**Core**
- `get_wage_data` - Wage statistics for an occupation by SOC code (national, state, or metro)
- `compare_metros` - Compare wages for one occupation across multiple metro areas
- `compare_occupations` - Compare wages across multiple occupations in one location

**Workflow**
- `igce_wage_benchmark` - Wage benchmarks with burdened rate estimates for IGCE development
- `detect_latest_year` - Report the bundled OEWS data year and release

**Reference**
- `list_common_soc_codes` - SOC code mappings for federal IT/professional services
- `list_common_metros` - Metro area MSA codes
- `get_data_status` - The bundled release, its BLS source files with SHA-256 and publication dates, and the retrieval date

## Data source

The bundled database is built by [`scripts/build_oews_db.py`](scripts/build_oews_db.py) from the BLS OEWS flat files at [download.bls.gov/pub/time.series/oe/](https://download.bls.gov/pub/time.series/oe/): national, state, metropolitan and nonmetropolitan area, and national industry estimates for every occupation and all 17 OEWS datatypes, including the relative standard errors. [`data/manifest.json`](src/bls_oews_mcp/data/manifest.json) records each source file's URL, size, SHA-256, and BLS publication date. A weekly check reports when BLS publishes a new release, which ships as a new package version.

BLS.gov cannot vouch for the data or analyses derived from these data after the data have been retrieved from BLS.gov.

## Installation

```bash
uvx bls-oews-mcp
```

## Configuration

Use the configuration below as the server definition and adapt its placement to your compatible MCP client. For practical requests using this source, see the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

```json
{
  "mcpServers": {
    "bls-oews": {
      "command": "uvx",
      "args": ["--refresh-package", "bls-oews-mcp", "--from", "bls-oews-mcp", "bls-oews-mcp"]
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes and new OEWS releases arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

On first use the server decompresses the bundled database (about 50 MB) into your user cache directory; set `BLS_OEWS_DATA_DIR` to put it elsewhere.

Restart the client and the tools appear.

## Example prompts

- "What's the national median salary for Software Developers (SOC 151252)?"
- "Compare Systems Analyst wages in DC, Seattle, and Baltimore."
- "Build IGCE wage benchmarks for Program Manager, Software Developer, and Help Desk at the DC metro area with a 2.0x burden factor."
- "Is $195/hr reasonable for a Senior Software Developer? Show me the BLS market data."
- "What do Information Security Analysts earn in Virginia vs nationally?"

## Important: base wages, not burdened rates

BLS OEWS data represents employer-reported base wages (no fringe, overhead, G&A, or profit). To estimate fully burdened hourly rates for an IGCE, apply a burden multiplier:

- 1.5x-1.7x: lean contractor
- 1.8x-2.2x: mid-range professional services
- 2.0x-2.5x: large contractor with clearance overhead
- 2.5x-3.0x: high-overhead (SCIF, deployed)

The `igce_wage_benchmark` tool applies the multiplier automatically. OEWS wages are estimates for the release's May reference month, so escalate them to the period of performance; the tool's `wage_period` and `_escalation_note` say which month.

## Data year

OEWS publishes about a year in arrears. The server answers from the bundled release, 2025 (May 2025 estimates, published May 15, 2026); other years raise a clear error pointing to the historical tables at [bls.gov/oes/tables.htm](https://www.bls.gov/oes/tables.htm). Omit the year argument in normal use, and call `detect_latest_year` or `get_data_status` to see the bundled release.

## Companion tools

Use alongside `gsa-calc-mcp` (GSA CALC+ ceiling rates) for complete pricing analysis. BLS provides what the market pays; CALC+ provides what GSA contractors charge. Together they form the IGCE pricing toolkit.

## License

MIT
