# GSA Per Diem Rates MCP: Testing

588 regression tests: 321 run offline on every release, and 267 call the live GSA Per Diem API when you turn them on.

## What is tested

All 7 tools, called through the MCP pipeline the way Claude or ChatGPT calls them (`mcp.call_tool`), not by calling the Python functions directly.

- **Right rates, not just valid answers.** Bundled ZIP, state, M&IE and seasonal monthly rates are checked against GSA's published files, and live parity tests compare the bundled data with the GSA API.
- **Rate areas are never guessed.** ZIPs and cities that span more than one rate area come back `ambiguous` with every candidate; a supplied `county` picks one. Unknown cities are `unresolved` instead of defaulting to the standard rate. Composite GSA names such as "Boston / Cambridge" and independent cities are covered.
- **Trip estimates.** Lodging plus M&IE with 75% on the first and last travel days, recomputed against FTR 301-11, including seasonal months and guidance for trips that cross months or fiscal years.
- **Keys and data sources.** Bundled lookups need no key or network call; city-only and unbundled-year lookups ask for a key with setup instructions. Credentials are redacted from errors and logs.
- **OCONUS handoff.** Alaska, Hawaii and the territories point to DoD (DTMO) rates and foreign locations to the State Department, instead of returning an empty or CONUS answer.
- **Input checks.** Cities, states, ZIPs, months, fiscal years and malformed values get a specific message saying how to fix the request.
- **Bundled data integrity.** The snapshot builder fails on schema drift, on any disagreement between GSA's rate and ZIP files, and on unfamiliar locality wording.
- **Hosted service.** Key handling, data status, shared request pacing and concurrency.

Realistic contractor travel questions (worksite ZIPs, seasonal rates, multi-site budgets, historical years, fiscal-year crossings) were also checked against GSA's published files before release. Those results are in the [October 10, 2026 release record](../../docs/releases/2026-10-10-content-audit.md).

## How to run the tests

From `servers/gsa-perdiem-mcp`:

```sh
uv run pytest                                                   # offline suite (no key needed)
MCP_LIVE_TESTS=1 PERDIEM_API_KEY=your-key uv run pytest         # add live tests
MCP_LIVE_TESTS=1 PERDIEM_API_KEY=your-key uv run pytest -m live_smoke   # small one-call-per-test live set
```

The offline suite ignores any `PERDIEM_API_KEY` in your shell, so it runs the same as CI. Live tests are paced automatically. See [tests/README.md](tests/README.md) for what each test file covers.

## Known limits

- **CONUS only.** Non-foreign OCONUS rates (Alaska, Hawaii, territories) are set by DoD (DTMO); foreign rates by the State Department. The tools say so instead of returning a rate.
- **Bundled years.** FY2021 onward is bundled. FY2020 and fiscal years not yet bundled use the GSA API and need a key locally. The GSA rates endpoints serve nothing before FY2020.
- **City-only lookups need a key locally.** Without a county, a city name is resolved through the GSA API. Supplying the county for a bundled year completes the lookup without a key.
- **Ceilings, not prices.** Rates are reimbursement ceilings under 41 CFR 301-11, not hotel prices. Lodging taxes, airfare and other transportation are outside the estimates. For contractor travel, contract terms, reasonable actual costs and agency exceptions decide what is allowable.
- **Split trips.** Each estimate assumes its own departure and return. For trips crossing months or fiscal years, add monthly lodging totals and calculate M&IE once over the actual travel days.
- **Multi-row API answers.** When the GSA API returns several rate areas for a city, the server prefers the county that mentions the query and lists the rest as `other_candidates`; GSA does not document that ordering.
- **Fiscal year rollover.** October 1 behavior is tested in principle but has not been checked live across a real fiscal-year change.
- **Rate limits.** A free api.data.gov key allows 1,000 requests per hour. The server spaces keyed requests (0.6 seconds by default, set with `FEDERAL_API_MIN_INTERVAL_SECONDS`), caps itself at 950 upstream calls per rolling hour, shares the api.data.gov pacing bucket with Regulations.gov when both use the same key, and honors `Retry-After` without automatic retries.

## History

Earlier audit rounds, fixes and release checks, including the Round 6 to Round 10 audits referenced in test file names, are in this file's git history and in [changelog.md](changelog.md).
