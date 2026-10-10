# gsa-calc-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 8](https://img.shields.io/badge/tools-8-007a59)](#what-it-does) [![regression tests: 438](https://img.shields.io/badge/regression%20tests-438-007a59)](testing.md)

<!-- mcp-name: com.1102tools/gsa-calc-mcp -->

Free, open-source MCP server for the GSA CALC+ Labor Ceiling Rates API. Query awarded GSA MAS schedule hourly rates for IGCE development, price reasonableness analysis, and market research.

No API key required, locally or hosted. See [Local or hosted](#local-or-hosted).

*Tested and hardened through ten audit rounds and the 1.0.14 workflow audit and discovery-description correction against the GSA CALC+ API. 438 collected regression tests (317 offline, 121 live-gated) covering 49 P1 bugs (19 crashes, 30 silent-wrong-data), 19 P2 validation gaps, 12 retroactive deep-audit findings, and the round-6 differential-count fixes (dead worksite filter, experience-range semantics, rate-card paging). The content fixes cover vendor worksites, low-sample price checks, comparison filters, title summaries and truncation. The 1.0.15 recovery correction preserves actionable unsupported-worksite guidance in fresh MCP 2.3 clients. The 1.0.16 correction exposes exact-title scope and withholds grade-specific high/low verdicts when pooled titles differ. See [testing.md](testing.md) for the full testing record and the [test suite map](tests/README.md) for counts by file.*

## Local or hosted

| Local (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|
| [Local setup](#installation) | [Install](https://claude.ai/directory/gsa-calc-by-1102tools) | [Install](https://chatgpt.com/plugins/plugin_asdk_app_6a9eeeebfa8c81918945df0945276cb1) |

- **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. You get your own full rate limits, and it relies only on the government service. You don't have to set it up by hand: give your AI this page's link and ask it to set it up or walk you through it.
- **Hosted** is the convenient option: one click, no keys, and it works in Claude or ChatGPT anywhere.

[Compare local and hosted](../../#local-or-hosted) · [Matching prompts](https://1102tools.com/#gsa-calc)

## What it does

Exposes the GSA CALC+ API as 8 MCP tools:

**Core search**
- `keyword_search` - Wildcard search across labor categories, vendors, and contract numbers
- `exact_search` - Exact field match (use suggest_contains to discover values first)
- `suggest_contains` - Autocomplete/discovery for field values (2-char minimum)
- `filtered_browse` - Browse with filters only (no keyword)

**Workflow tools**
- `igce_benchmark` - Rate statistics for IGCE development (min/max/avg/median/percentiles)
- `price_reasonableness_check` - Evaluate a proposed rate against market distribution
- `vendor_rate_card` - All rates for a vendor (auto-discovers exact name)
- `sin_analysis` - Rate distribution for a GSA SIN

## No authentication required

The GSA CALC+ API is public. GSA does not publish a numeric limit for this endpoint. The MCP applies a provisional 3-second cross-process anti-burst interval by default.

## Installation

```bash
uvx gsa-calc-mcp
```

Or from source:

```bash
git clone https://github.com/1102tools-dev/federal-contracting-mcps.git
cd federal-contracting-mcps/servers/gsa-calc-mcp
pip install -e .
```

## Configuration

Use the configuration below as the server definition and adapt its placement to your compatible MCP client. For practical requests using this source, see the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

```json
{
  "mcpServers": {
    "gsa-calc": {
      "command": "uvx",
      "args": ["--refresh-package", "gsa-calc-mcp", "--from", "gsa-calc-mcp", "gsa-calc-mcp"]
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

Restart the client and the tools appear.

## Example prompts

- "What are the GSA ceiling rates for Senior Software Developer with a BA and 10+ years experience?"
- "Is $195/hr reasonable for a Cybersecurity Analyst? Check against CALC+ rates."
- "Pull the full rate card for Booz Allen Hamilton from GSA CALC+."
- "What does the IT Professional Services SIN (54151S) rate distribution look like?"
- "Build IGCE benchmarks for these 5 labor categories: Program Manager, Systems Engineer, Software Developer, Help Desk Specialist, Network Administrator."
- "Find all small business ceiling rates for project management between $100-$200/hr."

## Important: ceiling rates, not prices paid

CALC+ data represents the maximum hourly rate a contractor can charge under their GSA MAS contract. Actual task order rates should be lower per FAR 8.405-2(d). These rates are:

- Fully burdened (includes fringe, overhead, G&A, profit)
- Worldwide (no geographic adjustment)
- Master contract-level (not task order-specific)
- From vendor Price Proposal Tables (self-reported by contractors)

Always note sample size and remind users these are ceiling rates when presenting analysis.

## License

MIT

IGCE and price checks use GSA's keyword search across labor titles, vendor names
and contract numbers. Check `population_scope`: a vendor-name match can pool
unrelated labor categories. Price checks return `MIXED_SEARCH_FIELDS` without a
verdict when off-title matches are found, and `UNVERIFIED_POPULATION` when the
title list cannot establish the full population. For title-only rates, discover
an exact title with `suggest_contains`, then call `exact_search` on
`labor_category`. Suggestion totals marked
`total_matching_records_is_lower_bound` mean **at least** that many records.
