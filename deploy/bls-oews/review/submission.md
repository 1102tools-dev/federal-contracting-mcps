# BLS OEWS MCP publication

Publisher: James Prentiss Jenrette (individual). Brand: 1102tools.

Endpoint: https://bls-oews.1102tools.com/mcp
Transport: Streamable HTTP (stateless, JSON responses).
Authentication: none. Users need no account or API key, and the service holds none: every tool answers from the BLS OEWS release bundled in the image. No request reaches BLS or any other third party.
Support: https://bls-oews.1102tools.com/support
Privacy: https://bls-oews.1102tools.com/privacy
Terms: https://bls-oews.1102tools.com/terms
Source: https://github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/bls-oews-mcp
Category: Data & Analytics.

Status: deployed on 2026-09-26 (container application `a032779f-43ea-45f4-abd5-449099e866b9`, created with `scripts/first_deploy_hosted.sh bls-oews`). The `bls-oews/v1.1.0` release through CI and the items under "Open before submission" come first.

## Open before submission

1. **Icons.** Light and dark directory and composer icons made by ChatGPT, matching the other 1102tools icons, go in `review/assets/` and `docs/directory-icons/bls-oews.png`. BLS does not permit use of its logo, so the mark must be 1102tools' own.
2. **Production tool test** in Claude (custom connector) and ChatGPT (Developer Mode) with the review test cases below.
3. **OpenAI domain verification and demo recording**, as for the other services.
4. **Portal attestations.** API ownership: this service calls no API; it serves a copy of BLS's public flat files. Answer the portal's data-source question accordingly and do not attest control of BLS systems.

## Listing copy

Name: 1102tools for BLS OEWS (Claude slug `bls-oews-by-1102tools`)

One-liner (≤200): Look up federal market wage data

Description (≤2,000):
Look up the Bureau of Labor Statistics Occupational Employment and Wage Statistics (OEWS) estimates behind federal labor-rate analysis: employment, mean wages, and hourly and annual 10th to 90th percentile wages for every occupation, nationally, by state, and by metropolitan or nonmetropolitan area, plus national industry breakdowns. Compare an occupation across metros or several occupations in one place, see each estimate's relative standard error, and build independent government cost estimate (IGCE) wage benchmarks with burdened hourly ranges from multipliers you choose, through eight read-only tools. Answers come from the current OEWS release (May 2025 estimates, published by BLS on May 15, 2026), bundled in the service as a copy of BLS's published flat files; each result names the release, the BLS publication and retrieval dates, and the source file. OEWS wages are base wages without fringe, overhead, or profit, and burdened rates are estimates, not BLS figures. BLS.gov cannot vouch for the data or analyses derived from these data after the data have been retrieved from BLS.gov. This independent 1102tools integration is not a federal agency service and does not alter government records.

## Tools and annotation justifications

The server publishes no `instructions`. Every tool is `readOnlyHint: true`, `destructiveHint: false`, and `openWorldHint: false`: it reads the bundled database and reaches no outside system.

| Tool | What it returns |
|---|---|
| get_wage_data | Wage and employment estimates for one occupation (national, state, or metro; national industry) |
| compare_metros | One occupation across up to 50 metro areas |
| compare_occupations | Up to 50 occupations in one location |
| igce_wage_benchmark | Mean, median, 10th and 90th percentile wages with burdened hourly ranges |
| detect_latest_year | The bundled data year and release |
| get_data_status | The bundled release, its BLS source files with SHA-256 and publication dates, and the retrieval date |
| list_common_soc_codes | Common federal IT and professional services SOC codes |
| list_common_metros | Common metro area codes |

## Starter prompts

1. What is the median salary for software developers in the Washington, DC metro area?
2. Build IGCE wage benchmarks for a project management specialist in Virginia with a 2.0x burden.
3. Compare information security analyst wages in DC, Seattle, and Baltimore.

## Review test cases

Positive (expected tool call and result, May 2025 release):
1. "National mean wage for software developers (SOC 15-1252)?" → `get_wage_data` → $148,100 annual mean; hourly median $65.38.
2. "Software developer wages in the DC metro?" → `get_wage_data` (metro 47900) → Washington-Arlington-Alexandria, DC-VA-MD-WV, $153,100 annual mean.
3. "Compare software developer pay in DC, Seattle, and Baltimore." → `compare_metros` → $153,100, $174,920, $153,910.
4. "IGCE benchmarks for airline pilots." → `igce_wage_benchmark` (53-2011) → annual figures with the annual-only warning (BLS publishes no hourly wage).
5. "Which OEWS release is this?" → `get_data_status` or `detect_latest_year` → May 2025, published 2026-05-15.

Negative (expected explanation, no fabricated figure):
1. "Wages for SOC 99-9999?" → `no_data` with the reason that the code is not an OEWS occupation.
2. "OEWS wages for 2023?" → rejected with a pointer to bls.gov/oes/tables.htm (only the current release is bundled).
3. "What will software developers earn in 2026?" → rejected: 2026 estimates do not exist yet.

## Verification record

Source 1.1.0 (PR #24, merged 2026-09-26 at `8f87c41`): offline suite 275 passed with the network blocked, plus 1 live parity test (25/25 values and footnotes match the BLS v1 API); rounds 6 and 8 (157 tests written against the live API) run offline; release guards and hosted admission passed; `scripts/check_hosted_contract.py bls-oews` 8 tools; the linux/amd64 image passed `verify_hosted_release.py --no-upstream`.
First deploy 2026-09-26: `/health` ok, 8 tools; `get_wage_data` on production returned the DC metro software developer mean ($153,100) from `bundled_bls_oews_files`; `/support`, `/privacy`, `/terms` 200; a cross-origin `Origin` header is rejected with 403.
