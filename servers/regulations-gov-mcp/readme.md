# regulationsgov-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 9](https://img.shields.io/badge/tools-9-007a59)](#what-it-does) [![regression tests: 295](https://img.shields.io/badge/regression%20tests-295-007a59)](testing.md)

<!-- mcp-name: com.1102tools/regulations-gov-mcp -->

Free, open-source MCP server for the Regulations.gov API. Federal rulemaking dockets, proposed rules, final rules, public comments, and comment period tracking.

Hosted: no key. Local: a free api.data.gov key. See [Local or hosted](#local-or-hosted).

*Tested and hardened through four rounds of integration testing against the live Regulations.gov API, plus a round-7 independent re-audit with live verification. 298 collected regression tests (179 offline, 119 live-gated) covering 1 P0 catastrophic bug, 10 P1 silent-wrong-data bugs (including `agency_id=""` returning all 1,951,938 records), 7 P2 validation gaps, 12 round-7 findings, the 1.1.0 hosted-directory fixes (compact results, publisher-key fail-closed), and the 2.0.3 content fixes (Eastern deadlines, posted-count labels, organization lookup, lifecycle subtypes, pagination limits, and comment text), plus 2.0.4 workflow recovery and truthful partial organization results, and 2.0.5 source-attributed deadline verification links. The 2026-10-10 offline run passed 179 tests; 119 live-gated tests were skipped because DEMO_KEY returned HTTP 429. See [testing.md](testing.md) for the full testing record.*

## Local or hosted

| Local (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|
| [Local setup](#installation) | [Install](https://claude.ai/directory/regulations-gov-by-1102tools) | Coming soon |

- **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. You get your own full rate limits, and it relies only on the government service. It needs a free api.data.gov key. You don't have to set it up by hand: give your AI this page's link and ask it to set it up or walk you through it.
- **Hosted** is the convenient option: one click, no keys, and it works in Claude or ChatGPT anywhere.

[Compare local and hosted](../../#local-or-hosted) · [Matching prompts](https://1102tools.com/#regulationsgov)

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

## License

MIT


The published 2.0.5 Round 3 replay completed 115 actual public questions across
all nine tools and recovered the conditional OSHA deadline from the linked
notice. A fresh install with MCP SDK 2.3.0 exposed hidden repair guidance;
published 2.0.6 preserves anticipated filter/date guidance across SDK
versions. Both SDK 2.0.0 and 2.3.0 suites pass 179 tests and skip 119 optional
live checks (298 collected). See [testing.md](testing.md) for separate actual
console, captured-provider, public, and primary-source evidence.
