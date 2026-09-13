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

| Default setting | Value |
| --- | --- |
| Minimum upstream request-start interval | **0.6 seconds** (approximately 100 starts/minute while capacity remains) |
| Maximum upstream requests in flight | **2** |
| Rolling upstream attempt budget | **500 per 300 seconds (5 minutes)** |
| Hosted HTTP entrance limit | **120 requests per 60 seconds**, per incoming IP and Cloudflare location |
| Hosted active MCP HTTP requests | **4 total**, shared by this service's users |
| Hosted backend processing timeout | **55 seconds** |

The upstream budget and concurrency are shared by **all hosted users of this MCP**, even when their incoming IPs differ. Independently hosted/local installations have their own pacing histories; processes sharing a pacing directory and identity share its counter. The separate IP-based entrance limit can also be shared by users of a cloud AI client. HTTP requests include protocol traffic and are not equivalent to upstream data requests.

A 0.6-second minimum interval permits approximately 100 starts per minute, not two starts every 0.6 seconds. One tool can make multiple upstream requests. These are 1102tools safeguards, not an official agency quota or a guaranteed completion rate.

Failed and cancelled upstream attempts remain counted. Observed `Retry-After` extends the shared cooldown; the MCP does not automatically retry the failed upstream call.

`FEDERAL_API_PACING_DIR` selects the local coordination directory. `FEDERAL_API_MIN_INTERVAL_SECONDS` can slow requests; positive values below 0.6 are clamped to 0.6. Explicit zero disables pacing for offline or externally managed use. Hosted deployments use 0.6.

Local history survives process restarts while the pacing directory remains. Deleting the directory or replacing a hosted container can reset its filesystem history. Update local processes together rather than mixing old and new pacing implementations against one directory.

See the [complete pacing reference](../../docs/pacing.md) for all nine servers, local versus hosted behavior, shared IPs, retry intervals and state persistence.

## License

MIT
