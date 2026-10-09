# federal-register-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 8](https://img.shields.io/badge/tools-8-007a59)](#what-it-does) [![regression tests: 243](https://img.shields.io/badge/regression%20tests-243-007a59)](testing.md)

<!-- mcp-name: com.1102tools/federal-register-mcp -->

Free, open-source MCP server for the Federal Register API. Proposed rules, final rules, notices, executive orders, comment periods, and regulatory tracking since 1994.

No API key required, locally or hosted. See [Local or hosted](#local-or-hosted).

*Tested and hardened through six rounds of integration testing against the live Federal Register API. 243 collected regression tests (143 offline, 100 live-gated) covering the `list_agencies` pydantic crash that hit every call, payload bombs, silent-wrong-data docket matches, the pre-2011 archive lockout, and open-comment results that missed the soonest deadlines. See [testing.md](testing.md) for the full testing record.*

## Local or hosted

| Local (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|
| [Local setup](#installation) | [Install](https://claude.ai/directory/federal-register-by-1102tools) | Coming soon |

- **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. You get your own full rate limits, and it relies only on the government service. You don't have to set it up by hand: give your AI this page's link and ask it to set it up or walk you through it.
- **Hosted** is the convenient option: one click, no keys, and it works in Claude or ChatGPT anywhere.

[Compare local and hosted](../../#local-or-hosted) · [Matching prompts](https://1102tools.com/#federal-register)

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

## License

MIT
