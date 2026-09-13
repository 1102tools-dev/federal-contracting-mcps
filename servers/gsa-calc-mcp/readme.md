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

| Default setting | Value |
| --- | --- |
| Minimum upstream request-start interval | **0.6 seconds** (approximately 100 starts/minute while capacity remains) |
| Maximum upstream requests in flight | **2** |
| Rolling upstream attempt budget | **500 per 3,600 seconds (1 hour)** |
| Hosted HTTP entrance limit | **120 requests per 60 seconds**, per incoming IP and Cloudflare location |
| Hosted processing slots | **16 total**, shared by this service's users |
| Hosted FIFO waiting slots | **32 additional**, for **48 accepted requests total** |
| Hosted total request deadline | **55 seconds**, including upload, queue wait and processing |
| Persistent hosted admission budget | **500 tool requests per rolling hour**, shared by all users |

Waiting requests enter processing in arrival order as slots become available. Client disconnects, cancellations and deadlines release their slots. A full 16 + 32 admission queue returns HTTP 429 with `Retry-After: 5`; an expired deadline returns HTTP 504 if no response has started. Slots count HTTP requests, not people, and accepting a request does not guarantee completion before its deadline.

The upstream budget and concurrency are shared by **all hosted users of this MCP**, even when their incoming IPs differ. Independently hosted/local installations have their own pacing histories; processes sharing a pacing directory and identity share its counter. The separate IP-based entrance limit can also be shared by users of a cloud AI client. HTTP requests include protocol traffic and are not equivalent to upstream data requests.

The 0.6-second start interval supports short batches at approximately 100 starts per minute; the 500-attempt hourly budget prevents sustained 500-per-five-minute use. All eight current CALC+ tools make at most one upstream request. These are 1102tools safeguards, not a published provider quota.

The hosted hourly admission counter and observed provider cooldowns persist in Durable Object SQLite storage across container sleep/replacement. Failed or invalid hosted tool requests consume an admission; protocol-only requests do not. `X-1102tools-Hourly-Remaining` reports that balance, not an agency allowance. Exhausting the budget or encountering a provider cooldown longer than 30 seconds returns an MCP tool error with a retry interval rather than holding the connection open. HTTP 200 alone does not mean a tool succeeded.

Failed and cancelled upstream attempts remain counted. Observed `Retry-After` extends the shared cooldown; the MCP does not automatically retry the failed upstream call.

`FEDERAL_API_PACING_DIR` selects the local coordination directory. `FEDERAL_API_MIN_INTERVAL_SECONDS` can slow requests; positive values below 0.6 are clamped to 0.6. Explicit zero disables pacing for offline or externally managed use. Hosted deployments use 0.6.

Local history survives process restarts while the pacing directory remains. Deleting the directory or replacing a hosted container can reset its filesystem history. The persistent hosted admission budget and provider cooldown above remain in place across container replacement. Update local processes together rather than mixing old and new pacing implementations against one directory.

See the [complete pacing reference](../../docs/pacing.md) for all nine servers, local versus hosted behavior, shared IPs, retry intervals and state persistence.

## License

MIT
