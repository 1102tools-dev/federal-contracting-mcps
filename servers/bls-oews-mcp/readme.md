# bls-oews-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 8](https://img.shields.io/badge/tools-8-007a59)](#what-it-does) [![regression tests: 276](https://img.shields.io/badge/regression%20tests-276-007a59)](testing.md) [![Claude directory: listed](https://img.shields.io/badge/Claude%20directory-listed-172f2a)](https://claude.ai/directory/bls-oews-by-1102tools)


<!-- mcp-name: com.1102tools/bls-oews-mcp -->

Free, open-source MCP server for BLS Occupational Employment and Wage Statistics (OEWS) market wages. For IGCE development, price analysis, and labor market research.

No API key and no daily limit. The package bundles the current OEWS release (May 2025 estimates, published by BLS on May 15, 2026) as a read-only database built from BLS's published flat files, so every answer is local and each result cites the BLS release, publication date, retrieval date, and source file. Use the installation and configuration instructions below to connect this MCP directly.

*Tested and hardened through a 5-round retroactive live audit with a real BLS API key after the initial smoke test reported zero bugs, then round 7's full-source re-audit. 276 collected regression tests (275 offline, 1 live parity check against the BLS API), covering the 1 P0 usability-breaking bug (SOC format), 10 P1 silent-wrong-data bugs, 12 P1 response-shape crash paths, and 7 P2 validation gaps fixed in that audit. See [TESTING.md](TESTING.md) for the full testing record.*

## Available in Claude and ChatGPT

| MCP | Claude | ChatGPT |
|---|---|---|
| BLS OEWS | [Install](https://claude.ai/directory/bls-oews-by-1102tools) | Coming soon |

This MCP is published in the Claude directory. Open the listing to install and connect it; no user API key or local Python setup is required. A ChatGPT directory listing is coming soon. Then try a [matching prompt](https://1102tools.com/#bls-oews). Prompts that combine sources require every listed MCP to be connected.

The installation and configuration sections below cover direct setup in other compatible MCP clients. The local server needs no key either.

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

The `igce_wage_benchmark` tool applies the multiplier automatically.

## Data year

OEWS publishes about a year in arrears. The server answers from the bundled release, 2025 (May 2025 estimates, published May 15, 2026); other years raise a clear error pointing to the historical tables at [bls.gov/oes/tables.htm](https://www.bls.gov/oes/tables.htm). Omit the year argument in normal use, and call `detect_latest_year` or `get_data_status` to see the bundled release.

## Companion tools

Use alongside `gsa-calc-mcp` (GSA CALC+ ceiling rates) for complete pricing analysis. BLS provides what the market pays; CALC+ provides what GSA contractors charge. Together they form the IGCE pricing toolkit.

## Request pacing

None. Every tool answers from the bundled database, so the server makes no upstream requests and has no BLS quota. See the [pacing reference](../../docs/pacing.md) for the other servers.

## License

MIT
