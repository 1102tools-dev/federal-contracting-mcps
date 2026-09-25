# bls-oews-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 8](https://img.shields.io/badge/tools-8-007a59)](#what-it-does) [![regression tests: 258](https://img.shields.io/badge/regression%20tests-258-007a59)](testing.md) [![hosted edition: coming soon](https://img.shields.io/badge/hosted%20edition-coming%20soon-b0770f)](#available-in-claude-and-chatgpt)


<!-- mcp-name: com.1102tools/bls-oews-mcp -->

Free, open-source MCP server for the BLS Occupational Employment and Wage Statistics (OEWS) API. Market wage data for IGCE development, price analysis, and labor market research.

Optional free API key for higher rate limits. Works without a key at reduced limits. Use the installation and configuration instructions below to connect this MCP directly.

*Tested and hardened through a 5-round retroactive live audit with a real BLS API key after the initial smoke test reported zero bugs. 258 collected regression tests (94 offline, 164 live-gated), covering the 1 P0 usability-breaking bug (SOC format), 10 P1 silent-wrong-data bugs, 12 P1 response-shape crash paths, and 7 P2 validation gaps fixed in that audit. See [TESTING.md](TESTING.md) for the full testing record.*

## Available in Claude and ChatGPT

| MCP | Claude | ChatGPT |
|---|---|---|
| BLS OEWS | Coming soon | Coming soon |

A hosted edition is coming soon to the Claude and ChatGPT directories. It is planned to need no user API key and no local setup. This server also works locally without a key at reduced limits. Until the listings are live, use the installation and configuration instructions below, then try a [matching prompt](https://1102tools.com/#bls-oews).

## What it does

Exposes the BLS OEWS API plus a credential-readiness check as 8 MCP tools:

**Core**
- `get_wage_data` - Wage statistics for an occupation by SOC code (national, state, or metro)
- `compare_metros` - Compare wages for one occupation across multiple metro areas
- `compare_occupations` - Compare wages across multiple occupations in one location

**Workflow**
- `igce_wage_benchmark` - Wage benchmarks with burdened rate estimates for IGCE development
- `detect_latest_year` - Check if newer OEWS data has been released

**Reference**
- `list_common_soc_codes` - SOC code mappings for federal IT/professional services
- `list_common_metros` - Metro area MSA codes

## Authentication (optional)

Without a key, the server uses BLS v1 API (25 queries/day). With a key, it uses v2 (500 queries/day). Register free at [data.bls.gov/registrationEngine](https://data.bls.gov/registrationEngine/).

## Installation

```bash
uvx bls-oews-mcp
```

## Configuration

Use the configuration below as the server definition and adapt its placement to your compatible MCP client. For practical requests using this source, see the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

Without key:
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

With key (recommended):
```json
{
  "mcpServers": {
    "bls-oews": {
      "command": "uvx",
      "args": ["--refresh-package", "bls-oews-mcp", "--from", "bls-oews-mcp", "bls-oews-mcp"],
      "env": {
        "BLS_API_KEY": "your-api-key-here",
        "FEDERAL_API_MIN_INTERVAL_SECONDS": "3"
      }
    }
  }
}
```

The server defaults `FEDERAL_API_MIN_INTERVAL_SECONDS` to `3` for keyed and
keyless requests. The explicit value above documents the intended policy and
can be changed when you have a documented reason. Multiple local processes
using the same key share the gate.

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

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

OEWS publishes about a year in arrears, and the BLS API serves ONLY the latest survey year. The server defaults to 2025 (May 2025 estimates, released April 2026), which is currently the only year that returns data: older years are withdrawn and raise a clear error here. Omit the year argument in normal use, and call `detect_latest_year` to confirm the newest release.

## Companion tools

Use alongside `gsa-calc-mcp` (GSA CALC+ ceiling rates) for complete pricing analysis. BLS provides what the market pays; CALC+ provides what GSA contractors charge. Together they form the IGCE pricing toolkit.

## Request pacing

| Default setting | Value |
| --- | --- |
| Wait after each upstream request completes | **3 seconds** |
| Maximum upstream requests in flight per pacing identity | **1** |
| Rolling attempt counter in this pacer | **None**; provider quotas still apply |

The next request starts after the previous request's duration **plus 3 seconds**. This is a completion delay, not a 3-second start interval. Local processes sharing the same pacing directory and identity share this gate; a separate local counter does not create additional provider quota.

See the [complete pacing reference](../../docs/pacing.md) for all nine servers, shared credentials/IPs, configuration and hosting differences.

Every upstream request uses a provisional 3-second cross-process anti-burst
interval by default. This protects keyed and keyless traffic launched by
multiple local clients; it does not increase BLS daily quota or coordinate the
same key on another computer. Override with
`FEDERAL_API_MIN_INTERVAL_SECONDS`, use `0` to deliberately disable it, and
use `FEDERAL_API_PACING_DIR` to relocate local pacing state.

## License

MIT
