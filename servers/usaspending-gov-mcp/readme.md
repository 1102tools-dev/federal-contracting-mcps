# usaspending-gov-mcp

<!-- mcp-name: com.1102tools/usaspending-gov-mcp -->

MCP server for the USASpending.gov federal contract, award, subaward, recipient, agency, and federal account API.

No API key required. Connect through the published ChatGPT plugin below, or use the installation and configuration instructions for another compatible MCP client.

*Tested and hardened through ten rounds of integration testing against the live USASpending.gov API. 2,151 regression tests (1,783 offline, 368 live-gated); round 10 fixed 25 verified findings across both tool families, including filters that could never match and a tool that had never once succeeded. See [testing.md](testing.md) for the full testing record.*

## Available in ChatGPT

[Install USASpending in ChatGPT](https://chatgpt.com/plugins/plugin_asdk_app_6a9ee668cc248191a0bdb9911b546799)

This MCP is also available as a published plugin in the ChatGPT directory. Open the listing to install and connect it; no user API key or local Python setup is required. Then try a [matching prompt](https://1102tools.com/#competitor-intelligence). Prompts that combine sources require every listed MCP to be connected.

The installation and configuration sections below cover direct setup in other compatible MCP clients.

## What it does

Exposes the USASpending.gov REST API as 55 MCP tools covering:

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
- `spending_by_subaward_grouped` - Subaward search with full filter set

**Recipients**
- `search_recipients` - Search recipients by keyword
- `get_recipient_profile` - Full recipient record
- `get_recipient_children` - Subsidiaries of a parent recipient
- `autocomplete_recipient` - Find recipient hashes by partial name
- `list_states` - All states with FIPS codes

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

- **No authentication required.** USASpending.gov is a free, public API.
- **Award type groups cannot be mixed.** The `award_type` parameter takes one of: `contracts`, `idvs`, `grants`, `loans`, `direct_payments`, `other`. Use separate calls for separate categories.
- **Actionable error messages.** Common API errors (422 mixed award types, 400 sort field missing, 400 empty keywords) are translated into guidance for the calling LLM.
- **Sort field auto-handling.** The USASpending API requires the sort field to appear in the fields array; this server adds it automatically.
- **Sensible defaults.** Search limits default to 25 (API max 100). Default fields cover the most common columns for each award category.
- **Flat filter parameters.** Most common filters are surfaced as named parameters (`keywords`, `awarding_agency`, `naics_codes`, etc.) rather than a nested filter dict, for better LLM tool discovery.

## Data source

All data is sourced from [USASpending.gov](https://www.usaspending.gov), which aggregates FPDS-NG contract data, FAADC assistance data, and agency DATA Act submissions. Data freshness varies by agency: non-DoD contract data is typically available within 5 business days, DoD and USACE procurement data has a 90-day reporting delay in FPDS, and financial assistance data is available within 2 days of submission.

## Request pacing

| Default setting | Value |
| --- | --- |
| Minimum upstream request-start interval | **0.6 seconds** (approximately 100 starts/minute while capacity remains) |
| Maximum upstream requests in flight | **4** |
| Rolling upstream attempt budget | **500 per 300 seconds (5 minutes)** |
| Hosted HTTP entrance limit | **120 requests per 60 seconds**, per incoming IP and Cloudflare location |
| Hosted active MCP HTTP requests | **4 total**, shared by this service's users |
| Hosted backend processing timeout | **55 seconds** |

The upstream budget and concurrency are shared by **all hosted users of this MCP**, even when their incoming IPs differ. Independently hosted/local installations have their own pacing histories; processes sharing a pacing directory and identity share its counter. The separate IP-based entrance limit can also be shared by users of a cloud AI client. HTTP requests include protocol traffic and are not equivalent to upstream data requests.

A 0.6-second minimum interval permits approximately 100 starts per minute, not four starts every 0.6 seconds. Slow requests can overlap within the four-request cap. One tool can make multiple upstream requests. These are 1102tools safeguards, not an official USAspending quota or a guaranteed completion rate.

Failed and cancelled upstream attempts remain counted. Observed `Retry-After` extends the shared cooldown; the MCP does not automatically retry the failed upstream call.

`FEDERAL_API_PACING_DIR` selects the local coordination directory. `FEDERAL_API_MIN_INTERVAL_SECONDS` can slow requests; positive values below 0.6 are clamped to 0.6. Explicit zero disables pacing for offline or externally managed use. Hosted deployments use 0.6.

Local history survives process restarts while the pacing directory remains. Deleting the directory or replacing a hosted container can reset its filesystem history. Update local processes together rather than mixing old and new pacing implementations against one directory.

See the [complete pacing reference](../../docs/pacing.md) for all nine servers, local versus hosted behavior, shared IPs, retry intervals and state persistence.

## License

MIT
