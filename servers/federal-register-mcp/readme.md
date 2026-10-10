# federal-register-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 8](https://img.shields.io/badge/tools-8-007a59)](#what-it-does) [![regression tests: 295](https://img.shields.io/badge/regression%20tests-295-007a59)](testing.md)

<!-- mcp-name: com.1102tools/federal-register-mcp -->

Free, open-source MCP server for the Federal Register API. Proposed rules, final rules, notices, executive orders, comment periods, and regulatory tracking since 1994.

No API key required, locally or hosted. See [Local or hosted](#local-or-hosted).

*Tested and hardened through nine audit rounds and integration testing against the live Federal Register API. 295 collected regression tests (190 offline, 105 live-gated) covering the `list_agencies` pydantic crash that hit every call, payload bombs, silent-wrong-data docket matches, the pre-2011 archive lockout, and open-comment results that missed the soonest deadlines, FAR Council agency mapping, presidential filters, parent-agency public inspection, and page limits. See [testing.md](testing.md) for the full testing record.*

The targeted SDK 2.3 correction in candidate 1.0.16 restores actionable input-validation messages for ordinary CFR and paging recovery. All 60 previously failing guidance assertions now pass without weakening their messages; unexpected faults remain masked under SDK 2.3. Both frozen SDK 2.0 and installed candidate SDK 2.3 suites measured 190 passed / 105 optional live skips / 295 collected. Actual candidate console originals and valid followups passed; publication and live 1.0.16 acceptance remain pending. See [the SDK correction record](testing.md#targeted-sdk-23-guidance-correction-2026-10-10-candidate-1016).

The October 10, 2026 content research round 3 found zero new defects in 54 ordinary and power-user calls across all eight tools. All 54 public answers matched primary-source comparisons, and all 54 answers from a fresh official PyPI 1.0.14 CLI installation matched the public service. The current offline suite passed 181 tests with 105 live-gated skips; no new full live-suite run is claimed. See [the round 3 record](testing.md#content-research-round-3-2026-10-10-published-1014) for coverage and source limits.

The October 10, 2026 content research round 4 found zero new defects in 63 valid public questions across all eight tools. A fresh official PyPI 1.0.14 stdio CLI matched all 63 answers in substance (62 exactly; one source page-view timestamp differed). Current verification passed 181 offline tests with 105 live skips, distinct from the new content corpus. See [the round 4 record](testing.md#content-research-round-4-2026-10-10-published-1014) for source comparisons, corrected audit selections and coverage limits.

## Local or hosted

| Local (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|
| [Local setup](#installation) | [Install](https://claude.ai/directory/federal-register-by-1102tools) | Coming soon |

- **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. You get your own full rate limits, and it relies only on the government service. You don't have to set it up by hand: give your AI this page's link and ask it to set it up or walk you through it.
- **Hosted** is the convenient option: one click, no keys, and it works in Claude or ChatGPT anywhere.

[Compare local and hosted](../../#local-or-hosted) · [Matching prompts](https://1102tools.com/#federal-register)

The October 10, 2026 content research round 5 found zero new content defects in 71 ordinary questions across all eight tools. A fresh official PyPI 1.0.14 stdio CLI matched all 71 public answers in substance (69 exactly; two dynamic page-view differences). Complete EPA/NRC/FCC/VA comment scans and deadline-to-document followups passed. Frozen tests passed 181 with 105 skips; the separate MCP 2.3 published-package lane retained 60 legacy validation/error-expectation failures (121 passed, 105 skipped). See [the round 5 record](testing.md#content-research-round-5-2026-10-10-published-1014) for primary evidence, source bounds and execution distinctions.

The October 10, 2026 content research round 6 completed 71 genuinely new questions across all eight tools, plus one prior control excluded from new coverage. Actual fresh official PyPI 1.0.15 and public acceptance completed 72 CLI and 72 public calls, all exactly equal. The P3 comment-source scope/recovery correction is published and accepted: zero indexed results now guide docket/detail verification, recovering the Coast Guard October 29 DATES deadline while preserving August 24 metadata. All eight runtime modules and catalogs match release source 881bad8f; both official artifact size/hash checks pass. The actual published SDK 2.3 suite measured 124 passed/60 failed/105 skipped out of 289; the same 60 legacy negatives remain separate from passing ordinary content. The retained frozen candidate result is 184 passed/105 skipped, not a new published run. See [the actual published record](testing.md#actual-published-round-6-acceptance-2026-10-10-1015).

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

### Open-comment completeness

`open_comment_periods` sorts the documents it scans by deadline. `complete` says whether every matching document was scanned; `truncated` also flags a result shortened by `limit`. An incomplete scan can omit a deadline earlier than one returned. Narrow with agencies or keywords, or use `search_documents` with `comment_date_gte`/`comment_date_lte` to verify a deadline window. FAR Council answers preserve the underlying scan metadata and flag lower-bound totals.
