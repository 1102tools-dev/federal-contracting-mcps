# regulationsgov-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 9](https://img.shields.io/badge/tools-9-007a59)](#what-it-does) [![regression tests: 236](https://img.shields.io/badge/regression%20tests-236-007a59)](testing.md) [![hosted edition: coming soon](https://img.shields.io/badge/hosted%20edition-coming%20soon-b0770f)](#available-in-claude-and-chatgpt)


<!-- mcp-name: com.1102tools/regulations-gov-mcp -->

Free, open-source MCP server for the Regulations.gov API. Federal rulemaking dockets, proposed rules, final rules, public comments, and comment period tracking.

Requires a free api.data.gov key. Use the installation and configuration instructions below to connect this MCP directly.

*Tested and hardened through four rounds of integration testing against the live Regulations.gov API, plus a round-7 independent re-audit with live verification. 240 collected regression tests (121 offline, 119 live-gated) covering 1 P0 catastrophic bug, 10 P1 silent-wrong-data bugs (including `agency_id=""` returning all 1,951,938 records), 7 P2 validation gaps, 12 round-7 findings, and the 1.1.0 hosted-directory fixes (compact results, publisher-key fail-closed). See [testing.md](testing.md) for the full testing record.*

## Available in Claude and ChatGPT

| MCP | Claude | ChatGPT |
|---|---|---|
| Regulations.gov | Coming soon | Coming soon |

A hosted edition is running at `https://regulations-gov.1102tools.com/mcp` and is planned for the Claude and ChatGPT directories. It needs no user API key and no local setup. Locally, a free personal key is recommended; a shared fallback works at low volume. Until the listings are live, use the installation and configuration instructions below, then try a [matching prompt](https://1102tools.com/#regulationsgov).

## What it does

Exposes the Regulations.gov API plus a credential-readiness check as 9 MCP tools:

**Core**
- `search_documents` - Search proposed rules, final rules, notices with flexible filters
- `get_document_detail` - Full document details with optional attachments
- `search_comments` - Search public comments (by docket, document, or keyword)
- `get_comment_detail` - Full comment text and submitter info
- `search_dockets` - Search rulemaking and nonrulemaking dockets
- `get_docket_detail` - Docket metadata, abstract, and RIN

**Workflow**
- `open_comment_periods` - Currently open comment periods across procurement agencies
- `far_case_history` - Summary of a FAR/DFARS rulemaking case with its documents, paged

## API key (required)

This server calls `api.regulations.gov`, which requires an api.data.gov key:
1,000 requests per hour, yours alone. Without `REGULATIONS_GOV_API_KEY` the
server still starts and lists its tools, but data tools return setup
instructions instead of calling Regulations.gov.

**Get a free key (takes 30 seconds):**

1. Go to [open.gsa.gov/api/regulationsgov/#getting-started](https://open.gsa.gov/api/regulationsgov/#getting-started) (or directly at [api.data.gov/signup](https://api.data.gov/signup/))
2. Enter your name and email: no approval, no wait
3. Copy the key from the confirmation page
4. Paste it into your client config as `REGULATIONS_GOV_API_KEY` (see below)

The same api.data.gov key works for every api.data.gov-backed API
(Regulations.gov, GSA Per Diem, NASA, FEC, FCC, etc.), so if you already
have one for another 1102tools MCP you can reuse it.

## Installation

```bash
uvx regulationsgov-mcp
```

## Configuration

Use the configuration below as the server definition and adapt its placement to your compatible MCP client. For practical requests using this source, see the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

**With your key:**
```json
{
  "mcpServers": {
    "regulationsgov": {
      "command": "uvx",
      "args": ["--refresh-package", "regulationsgov-mcp", "--from", "regulationsgov-mcp", "regulationsgov-mcp"],
      "env": {
        "REGULATIONS_GOV_API_KEY": "paste-your-api-data-gov-key-here"
      }
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

Restart the client and the tools appear.

## Example prompts

- "What FAR cases have open comment periods right now?"
- "Show me the full docket history for FAR-2023-0008."
- "Find all proposed rules from DARS posted in the last 6 months."
- "How many public comments were submitted on FAR Case 2023-008?"
- "Search for rulemaking dockets related to cybersecurity at DoD."
- "Find all SBA rules about size standards from the last year."

## Important: case-sensitive filter values

Regulations.gov filter values are CASE-SENSITIVE. Use exact casing:
- Document types: `Proposed Rule`, `Rule`, `Notice` (not lowercase)
- Docket types: `Rulemaking`, `Nonrulemaking`
- Lowercase values silently return 0 results with no error

## Companion tools

- `federal-register-mcp`: what was published in the Federal Register
- `regulationsgov-mcp`: the docket structure, public comments, and comment period status
- `ecfr-mcp`: what the regulation currently says after amendments

Together these three cover the full regulatory pipeline from proposal through public comment to codified rule.

## Request pacing

| Default setting | Value |
| --- | --- |
| Wait after each upstream request completes | **4 seconds** |
| Maximum upstream requests in flight per pacing identity | **1** |
| Rolling attempt counter in this pacer | **None**; provider quotas still apply |

The next request starts after the previous request's duration **plus 4 seconds**. This is a completion delay, not a 4-second start interval. Local processes sharing the same pacing directory and identity share this gate; a separate local counter does not create additional provider quota.

See the [complete pacing reference](../../docs/pacing.md) for all nine servers, shared credentials/IPs, configuration and hosting differences.

Every request and pagination subrequest uses a provisional 4-second
cross-process anti-burst interval by default. Regulations.gov and Per Diem
share a local `api.data.gov` bucket when they use the same key. This does not
increase provider quota or coordinate the key on another computer. Override
with `FEDERAL_API_MIN_INTERVAL_SECONDS`, use `0` to deliberately disable it,
and use `FEDERAL_API_PACING_DIR` to relocate local pacing state.

## License

MIT
