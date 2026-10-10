# sam-gov-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 20](https://img.shields.io/badge/tools-20-007a59)](#what-it-does) [![regression tests: 1,158](https://img.shields.io/badge/regression%20tests-1%2C158-007a59)](testing.md)

<!-- mcp-name: com.1102tools/sam-gov-mcp -->

Free, open-source MCP server for SAM.gov entity registration, exclusion/debarment, contract opportunity, contract award, federal hierarchy, and FFATA subaward data.

Two editions: **hosted**, with 4 keyless tools for contract opportunities, and **local**, the full 20 tools with a free SAM.gov key. See [Local or hosted](#local-or-hosted).

*Tested and hardened through ten audit rounds including a ~230-call paced live campaign. 1,158 collected regression tests (784 offline, 374 live-gated). v0.4 added 278 tests for Federal Hierarchy + FFATA Subaward endpoints (123 live), catching three silently-ignored Subaward API parameter casings during live audit. Birthplace of the `extra='forbid'` cross-fix applied across the suite. See [testing.md](testing.md) for the full testing record.*

The October 10, 2026 round-3 content audit verified published hosted mirror 1.0.3 with 110 realistic questions and followups plus data status. All 110 fresh official CSV comparisons and 345 returned-row checks passed. A fresh PyPI installation of the unchanged local 1.0.13 completed actual CLI initialization, its 20-tool catalog and access guidance; 19 keyed data workflows remained unexecuted without `SAM_API_KEY`. Optional live-test skips are not source passes. See [the round-3 record](testing.md#october-10-2026-round-3--published-opportunities-mirror-103) for scope and evidence.

Round 4 checked another 114 realistic hosted questions and followups plus status, with 114 source comparisons and 348 returned-row checks. A fresh official conditional HTTP 304 confirmed the retained CSV bytes. Local 1.0.14 restores anticipated date/code repair guidance hidden by MCP SDK 2.3; candidate suites pass 784 and skip 374 under both SDK 2.0 and 2.3. The mirror remains 1.0.3. Local keyed data workflows remain unexecuted without `SAM_API_KEY`; [the round-4 record](testing.md#october-10-2026-round-4--content-audit-and-local-1014-candidate) distinguishes candidate from final publication.

<a id="two-editions-hosted-or-full"></a>

## Local or hosted

SAM.gov comes in two editions. Hosted is the only one with no key.

| | Local (full edition) | Hosted |
|---|---|---|
| Install | On your computer. Give your AI this page's link and ask it to set it up, or start at [Installation](#installation) | One click from the Claude directory (ChatGPT coming soon) |
| API key | Free SAM.gov key, which expires every 90 days | None |
| Tools | 20 | 4 |
| Covers | Opportunities plus entity registrations, SBA certifications, exclusions, reps and certs, integrity records, contract award records, the federal hierarchy, and subawards | Contract opportunities, award notices, and justifications |
| Data | Live SAM.gov APIs, within your key's daily limit | SAM.gov's public contract opportunities file, refreshed daily |
| Works in | Claude or ChatGPT desktop apps and other AI apps, on a desktop or laptop | Claude or ChatGPT on web, desktop, and phone |

| Local (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|
| [Local setup](#installation) | [Install](https://claude.ai/directory/sam-gov-by-1102tools) | Coming soon |

[Compare local and hosted](../../#local-or-hosted) · [Matching prompts](https://1102tools.com/#catching-opportunities)

### Hosted edition: 4 tools, no key

The hosted edition is for finding and reading contract opportunities. It serves the contract opportunities file that SAM.gov publishes for public download, so it needs no API key and no local setup.

| Tool | What it does |
|---|---|
| `search_opportunities` | Search notices by keyword (titles and full descriptions), NAICS, PSC, set-aside, notice type, agency, state, and posted or response dates. Award notices and justifications are notice types. |
| `get_opportunity` | The full notice: description, contacts, award details, and the sam.gov link |
| `summarize_opportunities` | Counts by agency, NAICS, set-aside, or notice type |
| `get_data_status` | The date of the file behind every answer, and how many notices it holds |

Older notices can appear when they remain active, including notices posted in earlier fiscal years. This is not a complete historical archive; archived notices and attachments are not included (results link to the notice on sam.gov). Pair it with the [USAspending MCP](../usaspending-gov-mcp) for broader award history.

### Local full edition: when you need more

Use the full edition when you need to look up a company: registrations, UEI and CAGE codes, SBA certification dates, exclusions, reps and certs, integrity records (FAPIIS), or SAM.gov's contract award records, federal hierarchy, and subawards.

The full edition is local only. Give your AI this page's link and ask it to set it up, or start at [Installation](#installation). It needs your own free SAM.gov key, and that key's daily limit applies; see [Authentication](#authentication).

## What it does

Exposes seven SAM.gov REST APIs plus a credential-readiness check as 20 MCP tools:

**Entity Management (v3)**
- `lookup_entity_by_uei` - Single UEI lookup with configurable response sections
- `lookup_entity_by_cage` - CAGE code lookup
- `search_entities` - Flexible entity search (NAICS, PSC, business type, state, name, etc.)
- `get_entity_reps_and_certs` - FAR/DFARS reps and certs (must be requested explicitly)
- `get_entity_integrity_info` - FAPIIS proceedings data

**Exclusions (v4)**
- `check_exclusion_by_uei` - Single-UEI debarment check
- `search_exclusions` - Broader exclusion search by name, classification, program, agency, date

**Contract Opportunities (v2)**
- `search_opportunities` - Search contract opportunities with full working filter set
- `get_opportunity_description` - Fetch the HTML description by notice ID

**Contract Awards (v1) -- FPDS replacement**
- `search_contract_awards` - Search contract award records (vendor, agency, NAICS, dates, dollars, set-aside, etc.)
- `lookup_award_by_piid` - Look up all modifications for a single PIID
- `search_deleted_awards` - Search deleted award records for audit trails

**Federal Hierarchy (v1)**
- `search_federal_organizations` - Search the FH for departments, agencies, sub-agencies, offices (filter by FH org id, name, type, status, agency code, CGAC)
- `get_organization_hierarchy` - Walk the children of a federal organization

**Acquisition Subaward Reporting (FFATA subcontracts)**
- `search_acquisition_subawards` - Search FFATA subcontract reports (prime/sub relationships, agency, dates, status)

**Assistance Subaward Reporting (FFATA grant subawards)**
- `search_assistance_subawards` - Search FFATA grant subaward reports (FAIN, prime award key, agency, dates)

**PSC Lookup**
- `lookup_psc_code` - Resolve a PSC code to its full record
- `search_psc_free_text` - Free-text PSC discovery

**Composite workflow**
- `vendor_responsibility_check` - One-shot FAR 9.104-1 check (entity + exclusions in a single tool call)

## Authentication

Requires a SAM.gov API key set via the `SAM_API_KEY` environment variable.

Get a free personal API key by signing in and following the Public API Key instructions at [SAM.gov Help](https://sam.gov/help).

| Account Type | Daily Limit |
|---|---|
| Non-federal, no SAM role | 10/day |
| Non-federal with SAM role | 1,000/day |
| Federal personal | 1,000/day |
| Federal system account | 10,000/day |

**Important: SAM.gov API keys expire every 90 days.** Use SAM.gov Help to verify or regenerate the key and update your env var. This server returns a clear actionable error on 401/403 with regeneration instructions.

## Installation

### Via uvx (recommended)

```bash
uvx sam-gov-mcp
```

### Via pip

```bash
pip install sam-gov-mcp
```

### From source

```bash
git clone https://github.com/1102tools-dev/federal-contracting-mcps.git
cd federal-contracting-mcps/servers/sam-gov-mcp
pip install -e .
```

## Configuration

Use the configuration below as the server definition and adapt its placement to your compatible MCP client. For practical requests using this source, see the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

```json
{
  "mcpServers": {
    "sam-gov": {
      "command": "uvx",
      "args": ["--refresh-package", "sam-gov-mcp", "--from", "sam-gov-mcp", "sam-gov-mcp"],
      "env": {
        "SAM_API_KEY": "SAM-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
      }
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

Restart the client and the tools appear.

## Example prompts

Once configured, these examples illustrate the server's advanced standalone use. The maintained [MCP-oriented request library](https://github.com/1102tools-dev/federal-contracting-prompts) contains the broader collection:

- "Run a vendor responsibility check on [UEI] for registration status and exclusions, then pull FAPIIS integrity records separately; the one-pass check does not include those."
- "Pull [COMPANY]'s registration status, socioeconomic categories, and any exclusions. If SAM returns multiple registrations for one UEI, say so and list them before picking one."
- "Get [COMPANY]'s FAR 52.212-3 and DFARS 252.204-7016 answers from their reps and certs (summary mode), and flag anything a contracting officer would want to read in full text."
- "How far back does [COMPANY]'s federal award history actually go? Check contract awards decade by decade, FY1970 forward; volumes thin out before 1980, so read single-digit years as archival traces, not gaps."
- "Find active 8(a)-certified firms (SBA-certified, not self-designated) in [STATE] under NAICS [NAICS]."
- "Search sources sought notices from the last 30 days under NAICS [NAICS], response deadlines sorted soonest first."
- "Show me SDVOSB set-aside solicitations for IT services posted this quarter."
- "Get the full description of notice ID [paste ID] and summarize the SOW."
- "Search exclusions for [NAME]: give me classification (Firm, Individual, Vessel), excluding agency, and whether each record is active."
- "Search contract awards for [COMPANY] in fiscal year 2026, then look up all modifications for the biggest PIID you find."
- "Show me deleted contract award records for Department of Defense this fiscal year."
- "Find the Federal Hierarchy ID for the Department of the Treasury and walk one level of children."
- "Show me FFATA subcontracts on prime PIID [PIID], and total the subaward amounts."
- "Pull all subawards reported under grant FAIN [FAIN]."
- "List the agency-level orgs in CGAC 075 (HHS)."

## Design notes

- **Authentication via env var only.** `SAM_API_KEY` is read from the environment on every call. The key never enters the model's conversation context.
- **90-day expiration awareness.** 401/403 errors are translated into an actionable regeneration message with the current SAM.gov Help link.
- **API quirks baked in as safety rails.**
  - Entity Management hard cap of size=10 is enforced client-side with a clear error
  - Exclusions uses `size` not `limit` (different from other SAM endpoints)
  - Country codes are validated as 3-character ISO alpha-3 (2-char codes return 0 silently)
  - No `Accept: application/json` header is set (Exclusions returns 406 if present)
  - Bracket/tilde/exclamation characters are preserved in query strings for multi-value params
- **Post-filtering for broken parameters.** The Opportunities API silently ignores `deptname` and `subtier` filters. `search_opportunities` exposes an `agency_keyword` parameter that post-filters results by matching `fullParentPathName` substring.
- **includeSections defaults.** Entity lookups default to `entityRegistration,coreData`. Always include `entityRegistration` alongside any other section or the response has no identification. `repsAndCerts` and `integrityInformation` require explicit tool calls (`get_entity_reps_and_certs`, `get_entity_integrity_info`) because even `includeSections=All` doesn't include them.
- **Contract Awards response normalization.** The Contract Awards API returns different JSON wrapper shapes for populated vs. empty results. All tools normalize this to a consistent `{"awardSummary": [...], "totalRecords": int}` shape. Error responses are plain text (not JSON), detected and raised as actionable errors.
- **Contract Awards pagination.** Uses `limit`/`offset` (NOT `page`/`size` like Entity Management). Max limit is 100. Dates must be MM/dd/yyyy format with bracket ranges `[MM/dd/yyyy,MM/dd/yyyy]`.
- **Composite workflow.** `vendor_responsibility_check` collapses a typical FAR 9.104-1 check (entity registration + exclusion lookup) into one tool call, returning a structured flags list for downstream reasoning.
- **Federal Hierarchy quirks baked in.**
  - Lowercase `totalrecords` and `orglist` keys (rest of SAM.gov uses camelCase); normalizer preserves both
  - Default response is ACTIVE-only; passing `status=ACTIVE` is a no-op vs. the unfiltered call. Pass `INACTIVE` to expand to retired orgs
  - Real `fhorgtype` values look like `Department/Ind. Agency`, but the API also accepts shorthand (DEPARTMENT, AGENCY) with case-insensitive matching
- **Subaward Reporting quirks baked in.**
  - Dates use ISO `yyyy-MM-dd` (NOT `MM/dd/yyyy` like Contract Awards). Mixing them raises a clear pre-network validation error
  - Pagination uses `pageNumber`/`pageSize` (NOT `page`/`size` or `limit`/`offset`)
  - Live audit (April 2026) found three documented parameter casings are silently ignored: `PIID` is dropped (use lowercase `piid`), `referencedIdvPIID` is dropped (use `referencedIDVPIID`), and `referencedIDVAgencyID` is dropped (use `referencedIDVAgencyId`). Wire-level names are now correct in the server

## Part of

[federal-contracting-mcps](https://github.com/1102tools-dev/federal-contracting-mcps): monorepo of 9 MCP servers for federal contracting data. Pair these sources with the [MCP prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

## License

MIT
