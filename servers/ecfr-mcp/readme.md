# ecfr-mcp

<!-- mcp-name: com.1102tools/ecfr-mcp -->

MCP server for the eCFR (Electronic Code of Federal Regulations) API. Read FAR, DFARS, and all agency FAR supplement text with no authentication required.

Connect through the published ChatGPT plugin below, or use the installation and configuration instructions for another compatible MCP client.

*Tested and hardened through six rounds of integration testing against the live eCFR API. 295 regression tests (182 offline, 113 live-gated) covering 2 P0 catastrophic bugs, 26 P1 silent-wrong-data bugs, 32 P2 validation gaps, and the round-6 audit fixes (Title 48 chapter whitelist, table extraction, appendix access). See [testing.md](testing.md) for the full testing record.*

## Available in ChatGPT

[Install eCFR in ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9ef0341b04819192935fd4e5cd9b34)

This MCP is also available as a published plugin in the ChatGPT directory. Open the listing to install and connect it; no user API key or local Python setup is required. Then try a [matching prompt](https://1102tools.com/#ecfr). Prompts that combine sources require every listed MCP to be connected.

The installation and configuration sections below cover direct setup in other compatible MCP clients.

## What it does

Exposes the eCFR API as 13 MCP tools covering regulatory text, structure, search, version history, and common acquisition workflows:

**Core endpoints**
- `get_latest_date` - Get the most recent available date for a CFR title (call before other tools)
- `get_cfr_content` - Get parsed regulatory text for a section, subpart, or part
- `get_cfr_structure` - Hierarchical table of contents
- `get_version_history` - Amendment history for a section or part
- `get_ancestry` - Breadcrumb hierarchy path
- `search_cfr` - Full-text search with hierarchy filters
- `list_agencies` - All agencies with their CFR references
- `get_corrections` - Editorial corrections for a title

**Workflow convenience**
- `lookup_far_clause` - One-call FAR/DFARS clause text lookup (auto-resolves date)
- `compare_versions` - Side-by-side text comparison at two dates
- `list_sections_in_part` - All sections in a FAR/DFARS part
- `find_far_definition` - Search FAR 2.101 for a term definition
- `find_recent_changes` - Sections modified since a given date

## No authentication required

The eCFR API is fully public. No API key, no registration, no auth headers. Just install and use.

## Installation

### Via uvx (recommended)

```bash
uvx ecfr-mcp
```

### Via pip

```bash
pip install ecfr-mcp
```

### From source

```bash
git clone https://github.com/1102tools-dev/federal-contracting-mcps.git
cd federal-contracting-mcps/servers/ecfr-mcp
pip install -e .
```

## Configuration

Use the configuration below as the server definition and adapt its placement to your compatible MCP client. For practical requests using this source, see the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

```json
{
  "mcpServers": {
    "ecfr": {
      "command": "uvx",
      "args": ["--refresh-package", "ecfr-mcp", "--from", "ecfr-mcp", "ecfr-mcp"]
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

Restart the client. The `ecfr` server appears with 13 tools.

## Example prompts

- "Pull the current text of FAR 15.305 (Proposal Evaluation) and summarize what it requires."
- "List all sections in FAR Part 19 (Small Business Programs)."
- "Look up the FAR definition of 'commercial product' in 2.101."
- "What FAR sections were amended in the last 6 months?"
- "Compare FAR 52.212-4 between 2024-01-01 and 2025-01-01 and show me what changed."
- "Get the current text of DFARS 252.227-7014 (Rights in Noncommercial Computer Software)."
- "Search Title 48 for 'organizational conflict of interest' and show me the relevant sections."
- "Which agency owns Chapter 8 in Title 48? Get their FAR supplement structure."

## Design notes

- **XML parsed server-side.** The eCFR content endpoint returns raw XML. This server parses it into clean text (headings, paragraphs, citations) before returning to the model, saving significant context tokens.
- **Automatic date resolution.** eCFR lags 1-2 business days behind the Federal Register. Using today's date on versioner endpoints causes 404 errors. All content tools auto-resolve to the latest available date unless you specify one.
- **Search defaults to current text.** Without `date=current`, eCFR search returns ALL historical versions including superseded. Default `current_only=True` prevents duplicate results.
- **Structure endpoint limitation.** The eCFR structure endpoint does not support section-level filtering (returns 400). `list_sections_in_part` works around this by fetching the part structure and walking the tree.
- **FAR 2.101 optimization.** The definitions section is ~109KB of XML. `find_far_definition` parses the full section server-side and returns only matching paragraphs with context.

## CFR Title 48 quick reference

| Chapter | Regulation | Parts |
|---|---|---|
| 1 | FAR | 1-99 |
| 2 | DFARS | 200-299 |
| 3 | HHSAR | 300-399 |
| 4 | AGAR | 400-499 |
| 5 | GSAR | 500-599 |
| 6 | DOSAR | 600-699 |
| 7 | AIDAR | 700-799 |
| 8 | VAAR | 800-899 |
| 9 | DEAR | 900-999 |
| 18 | NFS | 1800-1899 |

## Data source

All data from [ecfr.gov](https://www.ecfr.gov), the continuously updated online Code of Federal Regulations maintained by the Office of the Federal Register. Updated daily, typically 1-2 business days after Federal Register publication. Not an official legal edition; for official citations reference the annual CFR from GPO.

## Part of

[federal-contracting-mcps](https://github.com/1102tools-dev/federal-contracting-mcps): monorepo of 9 MCP servers for federal contracting data. Pair these sources with the [MCP prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

## Request pacing and cache

| Default setting | Value |
| --- | --- |
| Minimum JSON request-start interval | **0.6 seconds** (approximately 100 starts/minute while capacity remains) |
| Maximum upstream requests in flight | **2 across JSON and XML combined** |
| Rolling upstream attempt budget | **500 per 300 seconds (5 minutes), shared by JSON and XML** |
| Hosted HTTP entrance limit | **120 requests per 60 seconds**, per incoming IP and Cloudflare location |
| Hosted processing slots | **16 total**, shared by this service's users |
| Hosted FIFO waiting slots | **32 additional**, for **48 accepted requests total** |
| Hosted total request deadline | **55 seconds**, including upload, queue wait and processing |
| Uncached XML | **1 fetch at a time; 3 seconds after previous XML completion** |
| XML cache | **300 seconds; 128 entries; 32 MiB total; 2 MiB per entry** |

Waiting requests enter processing in arrival order as slots become available. Client disconnects, cancellations and deadlines release their slots. A full 16 + 32 admission queue returns HTTP 429 with `Retry-After: 5`; an expired deadline returns HTTP 504 if no response has started. Slots count HTTP requests, not people, and accepting a request does not guarantee completion before its deadline.

The upstream budget and concurrency are shared by **all hosted users of this MCP**, even when their incoming IPs differ. Independently hosted/local installations have their own pacing histories; processes sharing a pacing directory and identity share its counter. The separate IP-based entrance limit can also be shared by users of a cloud AI client. HTTP requests include protocol traffic and are not equivalent to upstream data requests.

An XML cache hit makes **zero additional XML downloads** and skips the XML pacing wait. A tool may still need JSON calls, for example to resolve the latest date. XML misses also consume the shared rolling budget and an upstream concurrency slot.

The cache key includes the date, path and filters. Concurrent duplicate misses reuse one download. Only valid XML within the size limit is cached; errors and larger responses are not. Entries expire after 300 seconds and can be evicted earlier for capacity. Upstream corrections may take up to five minutes to appear in a cached result. Restarting the process clears the cache. These are 1102tools safeguards, not published agency quotas or guaranteed response times.

Failed and cancelled upstream attempts remain counted. Observed `Retry-After` extends the shared cooldown; the MCP does not automatically retry the failed upstream call.

`FEDERAL_API_PACING_DIR` selects the local coordination directory. `FEDERAL_API_MIN_INTERVAL_SECONDS` can slow requests; positive values below 0.6 are clamped to 0.6. Explicit zero disables pacing for offline or externally managed use. Hosted deployments use 0.6. Uncached XML retains its three-second completion gap for positive settings.

Local history survives process restarts while the pacing directory remains. Deleting the directory or replacing a hosted container can reset its filesystem history. Update local processes together rather than mixing old and new pacing implementations against one directory.

See the [complete pacing reference](../../docs/pacing.md) for all nine servers, local versus hosted behavior, shared IPs, retry intervals and state persistence.

## License

MIT
