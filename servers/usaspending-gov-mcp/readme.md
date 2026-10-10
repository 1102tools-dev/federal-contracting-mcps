# usaspending-gov-mcp

[![price: free](https://img.shields.io/badge/price-free-007a59)](https://1102tools.com/#why) [![license: MIT](https://img.shields.io/badge/license-MIT-007a59)](license) [![tools: 55](https://img.shields.io/badge/tools-55-007a59)](#what-it-does) [![regression tests: 2,322](https://img.shields.io/badge/regression%20tests-2%2C322-007a59)](testing.md)

<!-- mcp-name: com.1102tools/usaspending-gov-mcp -->

Free, open-source MCP server for the USAspending.gov federal contract, award, subaward, recipient, agency, and federal account API.

No API key required, locally or hosted. See [Local or hosted](#local-or-hosted).

*Candidate 1.0.23 source collects 2,322 regression cases. Both the frozen MCP SDK 2.0.0 lane and actually installed candidate-wheel MCP 2.3.0 lane measure 1,943 passed and 379 skipped. All 855 retained SDK 2.3 failures are resolved with specific visible expected-input guidance or strict unexpected-fault causal/masking assertions. Publication remains pending; the actual published 1.0.22 record below is preserved.*

*Published 1.0.22 has 2,318 collected regression cases. The measured frozen Python 3.12 / MCP SDK 2.0.0 source lane passed 1,939 and skipped 379 live-gated cases. Its separately installed official PyPI package with MCP 2.3.0 measured 1,084 passed, 855 retained legacy negative-expectation failures and 379 skipped. Actual published console/public acceptance passed 153 questions across all 55 tools, including 138 new Round 6 questions and 15 reference/control reads. See [testing.md](testing.md) for separate lane provenance.*

Version 1.0.22 clarifies award-date scope: an omitted date type matches the
interval from first signing through latest action, so it does not prove an
action occurred inside the requested window. For actual activity use
`spending_by_transaction`, read every page and deduplicate award identifiers;
`get_transactions` gives a discovered award's action dates. Explicit
`date_type="action_date"` bounds the latest action. The new Round 6 audit covers
all 55 tools with 138 new entity/filter questions and 15 separate prior controls.
Originals and recovery pass on the actual installed published package and public
service at release source `d7154fd26f985cee55ff0db3617d4ce587844446`.

Published 1.0.21 completed all 143 new Round 5 questions plus 10 separately
counted prior vehicle checks on a fresh official PyPI installation and the
public deployment. All 55 tool definitions matched. Its five-step NAICS
workflow correctly separates actual retired codes from current matches
omitted by the result limit and recovers the highway construction code.
Four workflow steps are included in the 153-call replay; one genuine
retired-inclusive control is additional.

The separate actual latest MCP SDK 2.3.0 full regression run measured
1,081 passed, 855 failed and 379 skipped. The 855 retained exception/message
expectations are the same failures as published 1.0.20 and are not credited
as passing. See [the final publication record](testing.md#round-17-final-published-verification-1021-2026-10-10)
for exact content, source and regression provenance.

Federal-account program lists contain codes/names across all reported years,
without dollar amounts or a fiscal-year filter. The tool retrieves source pages
internally (up to 2,000 records) and reports completeness and any requested FY
that was not applied. Use the numeric account ID with the fiscal-year snapshot
for single-year account resources. Agency program totals apply to the whole
agency. Account listings default to the source’s latest available FY; check
`fy`, especially after October rollover. Agency budgetary resources do not
provide a mandatory/discretionary split. Published 1.0.21 preserves the source available-year explanation and guides
omission of an unavailable year plus checking the returned `fy`.

## Local or hosted

| Local (desktop) | Claude (hosted) | ChatGPT (hosted) |
|---|---|---|
| [Local setup](#installation) | [Install](https://claude.ai/directory/usaspending-by-1102tools) | [Install](https://chatgpt.com/plugins/plugin_asdk_app_6a9ee668cc248191a0bdb9911b546799) |

- **Local** runs it on your computer, inside the Claude or ChatGPT desktop app or another AI app. You get your own full rate limits, and it relies only on the government service. You don't have to set it up by hand: give your AI this page's link and ask it to set it up or walk you through it.
- **Hosted** is the convenient option: one click, no keys, and it works in Claude or ChatGPT anywhere.

[Compare local and hosted](../../#local-or-hosted) · [Matching prompts](https://1102tools.com/#competitor-intelligence)

## What it does

Exposes the USAspending.gov REST API as 55 MCP tools covering:

**Search and aggregation**
- `search_awards` - Primary search for contracts, IDVs, grants, loans, direct payments
- `get_award_count` - Dimensional counts across award categories
- `spending_over_time` - Time series aggregation (fiscal year, quarter, month)
- `spending_by_category` - Top N breakdowns by agency, vendor, NAICS, PSC, state, etc.
- `spending_by_transaction` - Modification-level transaction search
- `spending_by_geography` - State, county, or congressional district breakdown
- `new_awards_over_time` - Pipeline trend for a recipient

**Award detail**
- `get_award_detail` - Full record for a single award
- `get_transactions` - Full modification history for an award
- `get_award_funding` - File C funding data (Treasury account, object class, program activity)
- `get_award_funding_rollup` - Single-line funding summary
- `get_award_subaward_count`, `get_award_federal_account_count`, `get_award_transaction_count`
- `get_idv_children` - Task/delivery orders under an IDV
- `awards_last_updated` - Data freshness check

**Subawards (FFATA)**
- `search_subawards` - Subawards under a single prime
- `spending_by_subaward_grouped` - Matching prime awards with cumulative reported subaward totals

**Recipients**
- `search_recipients` - Search recipients by keyword
- `get_recipient_profile` - Full recipient record
- `get_recipient_children` - Subsidiaries of a parent recipient
- `autocomplete_recipient` - Find recipient names by partial name
- `list_states` - All states with FIPS codes

For a recipient workflow, take a name from `autocomplete_recipient` to
`search_recipients`. Use the returned `id` hash for profiles and new-award
trends. To retrieve subsidiaries, pass the parent (`-P`) row’s `uei` (or
legacy `duns`) to `get_recipient_children`; that tool accepts UEI/DUNS.

**Agency depth**
- `list_toptier_agencies`, `get_agency_overview`, `get_agency_awards`
- `get_agency_budgetary_resources` - Budget resources by FY
- `get_agency_sub_agencies` - Subordinate orgs with obligations
- `get_agency_federal_accounts` - Funding sources (TAS)
- `get_agency_object_classes` - Spending categories (OMB)
- `get_agency_program_activities` - Program-level breakdown
- `get_agency_obligations_by_award_category` - Contract vs grant mix

**IDV depth**
- `get_idv_amounts` - Top-line IDV rollup
- `get_idv_funding`, `get_idv_funding_rollup` - File C for IDV
- `get_idv_activity` - Child orders under an IDV

**Federal accounts (Treasury)**
- `list_federal_accounts` - Search TAS
- `get_federal_account_detail`, `get_federal_account_object_classes`,
  `get_federal_account_program_activities`, `get_federal_account_fy_snapshot`

**Autocomplete**
- `autocomplete_psc`, `autocomplete_naics`
- `autocomplete_awarding_agency`, `autocomplete_funding_agency`
- `autocomplete_cfda` (grants), `autocomplete_glossary`, `autocomplete_recipient`

**Reference data**
- `get_naics_details`, `get_psc_filter_tree`
- `get_award_types_reference` - All award type codes (A=BPA Call etc.)
- `get_def_codes_reference` - Disaster Emergency Fund codes (COVID, IIJA, IRA)
- `get_glossary` - Acquisition/spending vocabulary
- `get_submission_periods` - Agency reporting period coverage
- `get_state_profile` - State-level spending profile

**Workflow convenience**
- `lookup_piid` - Auto-detects contract vs IDV and returns the matching award

## Installation

### Via pip

```bash
pip install usaspending-gov-mcp
```

### Via uvx (recommended, no venv needed)

```bash
uvx --from usaspending-gov-mcp usaspending-mcp
```

The `--from` is required for this server and only this server. The PyPI package
is `usaspending-gov-mcp` but the console script it installs is `usaspending-mcp`,
so a bare `uvx usaspending-gov-mcp` fails with "An executable named
usaspending-gov-mcp is not provided by package usaspending-gov-mcp".

Do **not** run `uvx usaspending-mcp` either. `usaspending-mcp` is an unrelated
third-party package on PyPI, not this project.

### From source

```bash
git clone https://github.com/1102tools-dev/federal-contracting-mcps.git
cd federal-contracting-mcps/servers/usaspending-gov-mcp
pip install -e .
```

## Configuration

Use the configuration below as the server definition and adapt its placement to your compatible MCP client. For practical requests using this source, see the [prompt library](https://github.com/1102tools-dev/federal-contracting-prompts).

```json
{
  "mcpServers": {
    "usaspending": {
      "command": "uvx",
      "args": ["--refresh-package", "usaspending-gov-mcp", "--from", "usaspending-gov-mcp", "usaspending-mcp"]
    }
  }
}
```

The `--refresh-package` flag tells uv to check PyPI for a newer release each time your client launches the server, so fixes arrive automatically; without it, uv keeps serving whatever version it first cached. It adds a moment of network time at startup, so raise your platform's MCP startup timeout if it enforces a short one.

If you installed via `pip install -e .` or a regular `pip install`:

```json
{
  "mcpServers": {
    "usaspending": {
      "command": "python",
      "args": ["-m", "usaspending_gov_mcp.server"]
    }
  }
}
```

Restart the client and the tools appear.

### Tool profiles

Standalone use defaults to `USASPENDING_TOOL_PROFILE=full`, which exposes all
55 tools. Packaged acquisition agents set
`USASPENDING_TOOL_PROFILE=acquisition-agent` to expose a stable 20-tool subset
covering core award search, spending, agency, recipient, NAICS, PSC,
transaction, and subaward operations. An unknown profile stops startup with a
clear error instead of silently changing the catalog.

## Example prompts

Once configured, try:

- "Show me the top 10 NAVSEA contracts awarded in FY2025 by dollar value."
- "Find all software development contracts at NASA with sole-source justifications in the last year."
- "How much has Leidos received in federal awards since 2020? Group by fiscal year."
- "What are the top 15 recipients of HUBZone set-aside contracts at DoD?"
- "Pull the full modification history for PIID N00024-24-C-0085."
- "Compare FFP vs T&M award counts for IT services at Air Force in FY2024."

## Design notes

- **No authentication required.** USAspending.gov is a free, public API.
- **Fiscal time groups.** Fiscal years run October through September; quarter 1 is October–December and month 1 is October. `new_awards_over_time` combines the source’s fiscal-quarter counts for annual fiscal-year results. A date window that covers only part of a fiscal year returns counts for that requested portion, not the entire year. Quarter and month results retain the source counts.
- **FFATA period scope.** `spending_by_subaward_grouped` ranks cumulative reported subaward totals for matching primes. Its date filters do not trim those totals to subaward actions inside the requested period. For period-specific reports, pass a returned `award_generated_internal_id` to `search_subawards`, read every page and filter the records by `action_date`. Reported amounts can repeat cumulative values; their sum is not net new subcontract spending.
- **Award type groups cannot be mixed.** The `award_type` parameter takes one of: `contracts`, `idvs`, `grants`, `loans`, `direct_payments`, `other`. Use separate calls for separate categories.
- **Actionable error messages.** Common API errors (422 mixed award types, 400 sort field missing, 400 empty keywords) are translated into guidance for the calling LLM.
- **Sort field auto-handling.** The USAspending API requires the sort field to appear in the fields array; this server adds it automatically.
- **Sensible defaults.** Search limits default to 25 (API max 100). Default fields cover the most common columns for each award category.
- **Flat filter parameters.** Most common filters are surfaced as named parameters (`keywords`, `awarding_agency`, `naics_codes`, etc.) rather than a nested filter dict, for better LLM tool discovery.

## Data source

All data is sourced from [USAspending.gov](https://www.usaspending.gov), which aggregates FPDS-NG contract data, FAADC assistance data, and agency DATA Act submissions. Data freshness varies by agency: non-DoD contract data is typically available within 5 business days, DoD and USACE procurement data has a 90-day reporting delay in FPDS, and financial assistance data is available within 2 days of submission.

## License

MIT


## Regression tests

Run `PYTHONPATH=src uv run --python 3.12 python -m pytest -q` from this
package directory. For candidate 1.0.23, both measured Python 3.12.13 / frozen
SDK 2.0.0 and installed candidate-wheel SDK 2.3.0 lanes pass 1,943 cases and skip
379 live cases. Actual published 1.0.22 measured 1,084 passed / 855 failed / 379
skipped; that prior execution remains separate. Set
`USASPENDING_LIVE_TESTS=1` to enable public API checks. Counts below include
parametrized and live-gated cases collected for candidate 1.0.23 (publication pending).

| Test file | Cases | Coverage |
|---|---:|---|
| [test_v0_3_features.py](tests/test_v0_3_features.py) | 1,244 | Tool shapes, filters and expanded API surface |
| [test_density_r5.py](tests/test_density_r5.py) | 415 | Boundary and semantic regression density |
| [test_live_audit_r6.py](tests/test_live_audit_r6.py) | 157 | Live endpoint audit |
| [test_live_audit_r7.py](tests/test_live_audit_r7.py) | 104 | Live parameter and pagination audit |
| [test_content_fixes_1013.py](tests/test_content_fixes_1013.py) | 75 | October content fixes; 71 offline, 4 live |
| [test_round_8.py](tests/test_round_8.py) | 69 | Property and validation checks |
| [test_entity_family_fixes.py](tests/test_entity_family_fixes.py) | 63 | Agency, recipient and award semantics |
| [test_validation.py](tests/test_validation.py) | 62 | Input validation |
| [test_search_family_fixes.py](tests/test_search_family_fixes.py) | 37 | Search and aggregation semantics |
| [test_response_cache_hosted.py](tests/test_response_cache_hosted.py) | 10 | Hosted cache behavior |
| [test_audit_r11.py](tests/test_audit_r11.py) | 9 | Paced audit anchors |
| [test_throughput.py](tests/test_throughput.py) | 9 | Request throughput and pacing |
| [test_tool_profiles.py](tests/test_tool_profiles.py) | 3 | Tool profile selection |
| [test_http.py](tests/test_http.py) | 2 | HTTP handling |
| [test_content_e2e_1014.py](tests/test_content_e2e_1014.py) | 36 | Full end-to-end audit guidance regressions |
| [test_published_scope_1015.py](tests/test_published_scope_1015.py) | 2 | Published tool-selection scope guidance |
| [test_new_awards_fiscal_year_1016.py](tests/test_new_awards_fiscal_year_1016.py) | 6 | Captured annual fiscal-year correction and unchanged quarter/month samples |
| [test_subaward_period_scope_1017.py](tests/test_subaward_period_scope_1017.py) | 3 | Cumulative FFATA scope and complete dated-report recovery |
| [test_federal_account_program_scope_1018.py](tests/test_federal_account_program_scope_1018.py) | 3 | Captured all-year program scope, complete list and single-year financial recovery |
| [test_federal_account_available_fy_1020.py](tests/test_federal_account_available_fy_1020.py) | 3 | Current-FY source availability, supported recovery and unchanged 503 control |
| [test_naics_current_retired_1021.py](tests/test_naics_current_retired_1021.py) | 3 | Actual retired rows versus active rows omitted by the requested limit |
| [test_award_date_overlap_r6.py](tests/test_award_date_overlap_r6.py) | 3 | Award interval overlap versus complete dated-transaction recovery |
| [test_sdk23_expected_guidance.py](tests/test_sdk23_expected_guidance.py) | 4 | Visible ordinary recovery hints, no pre-validation source requests, preserved source outputs and unexpected-fault masking |
| **Total** | **2,322** | **1,943 passes on each tested SDK; 379 live-gated skips** |
