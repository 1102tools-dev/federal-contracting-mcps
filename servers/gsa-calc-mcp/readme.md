# gsa-calc-mcp

<!-- mcp-name: com.1102tools/gsa-calc-mcp -->

MCP server for the GSA CALC+ Labor Ceiling Rates API. Query awarded GSA MAS schedule hourly rates for IGCE development, price reasonableness analysis, and market research.

No authentication required. Connect through the published ChatGPT plugin below, or use the installation and configuration instructions for another compatible MCP client.

*Tested and hardened through six audit rounds against the GSA CALC+ API. 352 regression tests (247 offline, 105 live-gated) covering 49 P1 bugs (19 crashes, 30 silent-wrong-data), 19 P2 validation gaps, 12 retroactive deep-audit findings, and the round-6 differential-count fixes (dead worksite filter, experience-range semantics, rate-card paging). See [testing.md](testing.md) for the full testing record.*

## Available in ChatGPT

[Install GSA CALC+ in ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9eeeebfa8c81918945df0945276cb1)

This MCP is also available as a published plugin in the ChatGPT directory. Open the listing to install and connect it; no user API key or local Python setup is required. Then try a [matching prompt](https://1102tools.com/#gsa-calc). Prompts that combine sources require every listed MCP to be connected.

The installation and configuration sections below cover direct setup in other compatible MCP clients.

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

## Request pacing

The default safeguard allows up to 500 upstream request attempts per rolling
hour, with starts spaced at least 0.6 seconds apart and at most two
requests in flight. This is a 1102tools policy tested against GSA CALC+,
not a published provider quota or a guaranteed tool-call rate. All eight
current tools make at most one upstream request. Upstream latency can reduce
throughput.

Local processes sharing `FEDERAL_API_PACING_DIR` share the budget. The hosted
service has an additional persistent budget of 500 tool requests per rolling
hour, shared by its users. Every current CALC+ tool makes at most one upstream
request; failed or invalid hosted tool requests still consume an admission.
Protocol-only requests do not consume this hourly budget. The hosted counter
and observed provider cooldowns live in Durable Object SQLite storage, so they
survive container sleep and replacement.

The separate HTTP entrance limit is 120 requests per minute per IP and
Cloudflare location, including protocol requests. Other MCP services have
separate budgets. `X-1102tools-Hourly-Remaining` reports the hosted admission
balance; it is not an agency quota header.

Exhausting the hourly safety budget returns an error with a retry time instead
of holding a connection open. Provider cooldowns longer than 30 seconds also
return promptly with the remaining wait. Attempts remain counted on failure or
cancellation, and `Retry-After` extends
a shared cooldown. Set `FEDERAL_API_MIN_INTERVAL_SECONDS` above `0.6` to slow
requests; positive values below `0.6` are clamped. Explicit `0` disables pacing
for offline tests or externally managed clients. Hosted deployments use `0.6`.
Local pacing history does not survive deletion of its directory. Hosted
Python pacing history is ephemeral, with the durable admission budget and
provider cooldown above preserving the outer safeguards across restarts. Do
not run old and new local pacing implementations against the same directory
concurrently.

## License

MIT
