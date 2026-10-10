# bls-oews-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 8](https://img.shields.io/badge/tools-8-007a59)](#what-it-does) [![regression tests: 298](https://img.shields.io/badge/regression%20tests-298-007a59)](testing.md)

<!-- mcp-name: com.1102tools/bls-oews-mcp -->

Free, open-source MCP server for BLS Occupational Employment and Wage Statistics (OEWS) market wages. For IGCE development, price analysis, and labor market research.

No API key and no daily limit. The package bundles the current OEWS release (May 2025 estimates, published by BLS on May 15, 2026) as a read-only database built from BLS's published flat files, so every answer is local and each result cites the BLS release, publication date, retrieval date, and source file. See [Local or hosted](#local-or-hosted).

Version **1.1.4** preserves BLS publication footnotes when a requested wage measure has no numeric value. Teacher hourly and performer annual comparisons explain the alternate published measure and suggest a useful annual or hourly followup. Topcoded wages retain BLS's published lower bound; the server does not invent an exact wage or annualize hourly-only occupations.

The current suite has **298 collected tests: 297 passed and one optional live BLS API parity test skipped** in both frozen and fresh dependency environments. After publishing 1.1.4, a fresh official PyPI installation and the public service each completed a separate 46-question corpus covering all eight tools, source values, IGCE arithmetic and useful followups. Twenty sampled current BLS API cells and footnotes matched the bundled source. The native Worker passed 31 tests; Python/Worker parity covered 227 cases with zero unexpected differences. See [testing.md](testing.md) for the historical audits, fixes and release checks.

The next content audit, round 3, found **zero new defects** across 58 new ordinary and power-user questions. The actual published CLI and public service each completed all 58 questions and followups; 431 measure/benchmark objects matched the bundled source and IGCE arithmetic, and 28 fresh official BLS API cells and footnotes matched. The flat-file footnote refresh returned HTTP 403 and is recorded as unavailable, separate from those successful API checks.

The fourth content round found **zero new P0, P1, P2 or P3 defects** in 66 new practical questions across all eight tools. A fresh official PyPI 1.1.4 CLI and the public service each completed the separate 66-call corpus with identical answers. All 418 wage/benchmark objects matched the bundled source; 31 selected fresh BLS API cells and footnotes matched independently. The audit covered environmental/civil work, social services, EMS/therapy, transportation, maintenance, communications and education, including successful annual-only/hourly-only followups. Flat-file footnote access remained unavailable (HTTP 403); no new package release was needed.

The fifth content round found **zero new P0–P3 defects** in 65 new practical questions across all eight tools. Actual fresh official PyPI 1.1.4 CLI and public answers matched for all 65 questions; 450 wage/benchmark objects and 33 fresh official API cells/footnotes reconciled. New veterinary, utility, manufacturing, trades, science and language-service tasks include local benchmarks and four caller-composed staffing budgets. Flight attendant annual-only and dancer hourly-only alternatives remain explicit. Both full dependency lanes measured 297 passed / one optional skip / 298 collected; direct BLS HTML/flat-footnote 403s are retained source limitations. See the Round 5 record in [testing.md](testing.md).

The sixth content round found **zero new P0–P3 defects** in 71 new questions across all eight tools. Fresh official PyPI 1.1.4 CLI and public answers match; 503 wage/benchmark objects and 40 selected fresh BLS API cells/footnotes reconcile. New trades, aircraft maintenance, metalworking, science technicians, childcare and performing-arts tasks include local benchmarks and four caller-composed budgets. One initial BLS API 503 was recovered by a bounded retry; direct HTML/flat-footnote 403s remain explicit. Both full Python lanes measured 297 passed / one optional skip / 298 collected. See the Round 6 record in [testing.md](testing.md).

## Local or hosted

| Local (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|
| [Local setup](#installation) | [Install](https://claude.ai/directory/bls-oews-by-1102tools) | [Install](https://chatgpt.com/plugins/plugin_asdk_app_6ab872bf5360819186af0917c923e57e) |

- **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. Answers come from the bundled BLS database, with no government API calls or request limits. You don't have to set it up by hand: give your AI this page's link and ask it to set it up or walk you through it.
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
