# federal-register-mcp

<!-- mcp-name: com.1102tools/federal-register-mcp -->

MCP server for the Federal Register API. Proposed rules, final rules, notices, executive orders, comment periods, and regulatory tracking since 1994.

No authentication required. Use the installation and configuration instructions below to connect this MCP directly.

*Tested and hardened through six rounds of integration testing against the live Federal Register API. 228 regression tests (132 offline, 96 live-gated) covering the `list_agencies` pydantic crash that hit every call, payload bombs, silent-wrong-data docket matches, the pre-2011 archive lockout, and open-comment results that missed the soonest deadlines. See [testing.md](testing.md) for the full testing record.*

## What it does

Exposes the Federal Register API as 8 MCP tools:

**Core**
- `search_documents` - Search with flexible filters (agency, type, term, docket, dates, RIN, CFR title/part)
- `get_document` - Full details for a single document by number
- `get_documents_batch` - Fetch up to 20 documents in one call
- `get_facet_counts` - Document counts by type, agency, topic, or time bucket (daily through yearly)
- `get_public_inspection` - Pre-publication documents with client-side filtering
- `list_agencies` - All ~470 agencies with slugs

**Workflow**
- `open_comment_periods` - Currently open comment periods (sorted by deadline)
- `far_case_history` - Full rulemaking history for a FAR/DFARS case

## No authentication required

The Federal Register API is fully public. No key, no registration.

## Installation

```bash
uvx federal-register-mcp
```

## Configuration

Use the configuration below as the server definition and adapt its placement to your compatible MCP client. For practical requests using this source, see the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

```json
{
  "mcpServers": {
    "federal-register": {
      "command": "uvx",
      "args": ["--refresh-package", "federal-register-mcp", "--from", "federal-register-mcp", "federal-register-mcp"]
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

Restart the client and the tools appear.

## Example prompts

- "What FAR cases have open comment periods right now?"
- "Show me the full rulemaking history for FAR Case 2023-008."
- "Find all proposed rules from DoD published in the last 6 months."
- "What significant rules has GSA published this fiscal year?"
- "Are there any pre-publication documents related to procurement today?"
- "How many proposed rules vs final rules has the SBA published since January?"
- "Find executive orders related to federal acquisition from the last year."

## Companion tools

- `ecfr-mcp`: what the regulation currently says (the book)
- `federal-register-mcp`: what is changing (the newspaper)

Together they cover the full regulatory pipeline. Use `far_case_history` to trace a rulemaking from proposal through final rule, then `ecfr-mcp` to read the codified result.

## Request pacing

The default safeguard allows up to 500 upstream request attempts per rolling
five minutes, with starts spaced at least 0.6 seconds apart and at most two
requests in flight. This is a 1102tools policy tested against Federal Register,
not a published provider quota or a guaranteed tool-call rate. A tool may make
more than one upstream request, and upstream latency can reduce throughput.

Local processes sharing `FEDERAL_API_PACING_DIR` share the budget. The hosted
service has its own budget shared by its users. Its separate HTTP entrance
limit is 120 requests per minute per IP and Cloudflare location, including
protocol requests that do not call the upstream API. Other MCP services have
separate budgets.

Attempts remain counted on failure or cancellation, and `Retry-After` extends
a shared cooldown. Set `FEDERAL_API_MIN_INTERVAL_SECONDS` above `0.6` to slow
requests; positive values below `0.6` are clamped. Explicit `0` disables pacing
for offline tests or externally managed clients. Hosted deployments use `0.6`.
State is local to the pacing directory and does not survive its deletion or a
hosted container replacement. Do not run old and new pacing implementations
against the same directory concurrently.

## License

MIT
