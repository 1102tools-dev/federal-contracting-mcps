# federal-register-mcp

<!-- mcp-name: io.github.1102tools/federal-register-mcp -->

MCP server for the Federal Register API. Proposed rules, final rules, notices, executive orders, comment periods, and regulatory tracking since 1994.

No authentication required.

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

## Claude Desktop configuration

```json
{
  "mcpServers": {
    "federal-register": {
      "command": "uvx",
      "args": ["federal-register-mcp"]
    }
  }
}
```

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
