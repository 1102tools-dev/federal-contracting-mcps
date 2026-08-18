# gsa-calc-mcp

<!-- mcp-name: io.github.1102tools/gsa-calc-mcp -->

MCP server for the GSA CALC+ Labor Ceiling Rates API. Query awarded GSA MAS schedule hourly rates for IGCE development, price reasonableness analysis, and market research.

No authentication required. MCP is an open standard: this server runs in any MCP client, not just Claude. Executed and verified on eleven platforms in August 2026 (see [Configuration](#configuration)).

*Tested and hardened through six audit rounds against the GSA CALC+ API. 352 regression tests (247 offline, 105 live-gated) covering 49 P1 bugs (19 crashes, 30 silent-wrong-data), 19 P2 validation gaps, 12 retroactive deep-audit findings, and the round-6 differential-count fixes (dead worksite filter, experience-range semantics, rate-card paging). See [testing.md](testing.md) for the full testing record.*

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

The GSA CALC+ API is public. 1,000 requests/hour rate limit.

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

MCP is an open standard, and this config was executed and verified in August 2026 on eleven platforms: Claude Desktop, Claude Code, Codex Desktop and CLI, Gemini via Antigravity, GitHub Copilot CLI, DeepSeek Harness, Grok Build, Cursor, opencode, and LibreChat. Most clients take the same JSON block below and differ only in where the config file lives; the [universal setup guide (PDF)](https://1102tools.com/downloads/1102tools-universal-setup.pdf) has the exact file path and format for every platform, including the Codex TOML form.

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
