# gsa-perdiem-mcp

<!-- mcp-name: com.1102tools/gsa-perdiem-mcp -->

MCP server for the GSA Per Diem Rates API. Federal travel lodging and M&IE rates for IGCEs and travel cost estimation.

Works without configuration using DEMO_KEY. Optional free API key for higher rate limits. Standalone MCP use is an advanced, self-supported path; packaged agents are the maintained beginner path.

*Tested and hardened through seven rounds of integration testing against the live GSA Per Diem API, including a round-7 independent re-audit with live verification. 437 regression tests covering 1 P0 path-traversal bug, 23 P1 silent-wrong-data bugs, 21 P2 validation gaps, and 14 round-7 findings fixed. See [testing.md](testing.md) for the full testing record.*

## What it does

Exposes the GSA Per Diem API as 6 MCP tools:

**Core lookups**
- `lookup_city_perdiem` - Rates by city/state (auto-selects best NSA match)
- `lookup_zip_perdiem` - Rates by ZIP code
- `lookup_state_rates` - All NSA rates for a state
- `get_mie_breakdown` - M&IE tier table (meal components)

**Workflow**
- `estimate_travel_cost` - Calculate trip per diem (lodging + M&IE with first/last day at 75%)
- `compare_locations` - Compare rates across multiple cities

## Get your own API key (strongly recommended)

This server hits `api.gsa.gov`, which uses api.data.gov for rate limiting.

- **Without a key**: falls back to the shared `DEMO_KEY` which is capped at
  **~10 requests per hour across everyone using it**. A couple real prompts
  will blow through that limit and you'll start seeing 429 errors.
- **With a personal key**: 1,000 requests per hour, yours alone.

**Get a free key (takes 30 seconds):**

1. Go to [api.data.gov/signup](https://api.data.gov/signup/)
2. Enter your name and email: no approval, no wait
3. Copy the key from the confirmation page
4. Paste it into your client config as `PERDIEM_API_KEY` (see below)

The same key works for every api.data.gov-backed API (GSA Per Diem, NASA,
FEC, FCC, etc.).

## Installation

```bash
uvx gsa-perdiem-mcp
```

## Configuration

MCP is an open standard, and compatible clients can run this server. The maintained [1102tools Agent Setup Guide](https://1102tools.com/downloads/1102tools-agent-setup-guide.pdf) covers packaged agents in Codex and Claude Code, not standalone server configuration. Use the block below as the server definition and adapt its placement to your client.

**Recommended (with your own key):**
```json
{
  "mcpServers": {
    "gsa-perdiem": {
      "command": "uvx",
      "args": ["--refresh-package", "gsa-perdiem-mcp", "--from", "gsa-perdiem-mcp", "gsa-perdiem-mcp"],
      "env": {
        "PERDIEM_API_KEY": "paste-your-api-data-gov-key-here",
        "FEDERAL_API_MIN_INTERVAL_SECONDS": "4"
      }
    }
  }
}
```

The server defaults `FEDERAL_API_MIN_INTERVAL_SECONDS` to `4` for personal-key
and DEMO_KEY requests. The explicit value above documents the intended policy
and can be changed when you have a documented reason. Per Diem and
Regulations.gov processes using the same `api.data.gov` key share the gate.

**Without a key** (works for a handful of calls per hour, then 429s until the hour rolls over):
```json
{
  "mcpServers": {
    "gsa-perdiem": {
      "command": "uvx",
      "args": ["--refresh-package", "gsa-perdiem-mcp", "--from", "gsa-perdiem-mcp", "gsa-perdiem-mcp"]
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

Restart the client and the tools appear.

## Example prompts

- "What's the per diem rate for Washington DC in FY2026?"
- "Estimate travel costs for 4 nights in Boston in March."
- "Compare per diem rates for DC, New York, and San Francisco."
- "What are all the NSA per diem locations in Virginia?"
- "Show me the M&IE meal breakdown for the $92 tier."
- "Build a travel estimate: 3 trips to Seattle (4 nights each) and 2 trips to DC (3 nights each)."

## Important: maximum reimbursement, not actual prices

Per diem rates are federal reimbursement ceilings per 41 CFR 301-11. They are not actual hotel prices. CONUS only. Non-foreign OCONUS rates (Alaska, Hawaii, territories) are set by DoD (DTMO); foreign rates by the State Department. Lodging taxes generally not included. First/last travel day M&IE at 75%.

## Companion tools

Use alongside `bls-oews-mcp` (wage data) and `gsa-calc-mcp` (ceiling rates) for complete IGCE development. Per diem covers the travel component; BLS and CALC+ cover labor.

## Request pacing

Every request, including DEMO_KEY traffic, uses a provisional 4-second
cross-process anti-burst interval by default. Per Diem and Regulations.gov
share a local `api.data.gov` bucket when they use the same key. This does not
increase provider quota or coordinate the key on another computer. Override
with `FEDERAL_API_MIN_INTERVAL_SECONDS`, use `0` to deliberately disable it,
and use `FEDERAL_API_PACING_DIR` to relocate local pacing state.

## License

MIT
