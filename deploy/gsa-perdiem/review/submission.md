# GSA Per Diem MCP publication

Publisher: James Prentiss Jenrette (individual). Brand: 1102tools.

Endpoint: https://gsa-perdiem.1102tools.com/mcp
Transport: Streamable HTTP (stateless, JSON responses).
Authentication: none. Users need no account or API key. City lookups call the GSA Per Diem API with a publisher key held as a Cloudflare Worker secret and never exposed.
Support: https://gsa-perdiem.1102tools.com/support
Privacy: https://gsa-perdiem.1102tools.com/privacy
Terms: https://gsa-perdiem.1102tools.com/terms
Source: https://github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/gsa-perdiem-mcp
Category: Government / travel.

Status: prepared, not submitted. Requires package 1.1.0 deployed to the endpoint above (health `release_sha` equal to the release commit) before any portal scan.

## Listing copy

Name: GSA Per Diem by 1102tools

One-liner (≤200): Federal travel per diem rates from GSA: lodging by month and M&IE by city, ZIP, county, or state, with trip cost estimates for IGCEs.

Description (≤2,000):
Look up the official GSA per diem rates that cap federal travel lodging and meals-and-incidental-expense (M&IE) reimbursement in the continental United States. Search by city, ZIP code, county, or state; see monthly lodging rates for seasonal locations; get the M&IE breakdown by meal; estimate a trip's per diem with first- and last-day M&IE at 75% (41 CFR 301-11.101); and compare destinations for an independent government cost estimate.

ZIP, state, and M&IE answers come from GSA's published per diem files (FY2021 onward) included in the service; city names are resolved to rate areas through the GSA Per Diem API. GSA sets rates by county or locality, so when a ZIP code or city spans more than one rate area the service lists every candidate instead of choosing one, and a county selects the applicable rate. Each result names the GSA file or API it came from.

Rates are reimbursement ceilings, not hotel prices. Alaska, Hawaii, U.S. territories, and foreign locations are set by DoD and the State Department and are not covered; the service says so rather than returning a CONUS rate. Read-only; no account needed. Independent service, not endorsed by GSA.

## Tools and annotations

Every tool is read-only (`readOnlyHint: true`) and non-destructive (`destructiveHint: false`); none modifies data anywhere.

| Tool | openWorldHint | Reason |
|---|---|---|
| lookup_city_perdiem | true | Resolves city names through the GSA Per Diem API. |
| estimate_travel_cost | true | Uses the city lookup. |
| compare_locations | true | Uses the city lookup for each location. |
| lookup_zip_perdiem | true | Bundled GSA file for FY2021+; calls the GSA API for other fiscal years. |
| lookup_state_rates | true | Same as ZIP. |
| get_mie_breakdown | true | Same as ZIP. |
| get_data_status | false | Reports bundled data and configuration; no external access. |

The server publishes no `instructions`. Tool descriptions describe behavior only.

## Starter prompts

1. What is the federal per diem for Arlington, Virginia in November?
2. Estimate per diem for a 3-night trip to Chester, Massachusetts in March.
3. Compare per diem for Denver, Austin, and San Diego for FY2027.

## Review test cases

Positive (expected tool call and result):
1. "Per diem for ZIP 22201 in FY2027?" → `lookup_zip_perdiem` → District of Columbia rate area, M&IE $92, monthly lodging.
2. "Estimate per diem for 3 nights in McLean, VA in November." → `estimate_travel_cost` → District of Columbia rate area, FY2027 November lodging, M&IE with 75% first/last day.
3. "List all non-standard per diem areas in Virginia." → `lookup_state_rates` → 10 areas plus the $113/$68 standard rate (FY2027).
4. "Show the M&IE breakdown for FY2027." → `get_mie_breakdown` → tiers $68-$92 with breakfast/lunch/dinner/incidentals.
5. "Per diem for ZIP 01011?" → `lookup_zip_perdiem` → `ambiguous` with Northampton ($80 M&IE) and Springfield ($74); follow-up "It's in Hampden County" → Springfield.

Negative (expected refusal or explanation, no fabricated rate):
1. "What's the per diem in Anchorage, Alaska?" → OCONUS: explains DoD/DTMO sets Alaska rates; no CONUS rate returned.
2. "Book me a hotel in Boston at the per diem rate." → No booking capability; tools only return rates.
3. "Per diem for Xyzzyville, Virginia?" → `unresolved`: GSA does not recognize the city; asks for county or ZIP rather than asserting the standard rate.

## Verification record

Offline suite: 274 passed (541 collected; live-gated tests skipped). Release guards: 37 passed.
Live parity against the GSA API on 2026-09-26 with a registered key: every sampled ZIP (about 110 per fiscal year, FY2026 and FY2027) matched the bundled files exactly; state lists for VA, MD, CA, MA, TX, CT, PA, and AZ matched; the city corpus resolved as expected.
Local hosted entry point (`gsa_perdiem_mcp.http`, `PERDIEM_HOSTED=1`) passed `scripts/verify_hosted_release.py gsa-perdiem` including the live city check.
Production checks: pending deployment.

## Remaining user steps

1. Approve the PR, then push tag `gsa-perdiem/v1.1.0` (scoped release; other services are not redeployed).
2. Confirm the workflow's production verification passed and `/health` reports the tag commit.
3. Test every tool on production in Claude (custom connector) and ChatGPT (Developer Mode).
4. OpenAI: create the plugin draft (verified individual publisher, no-auth MCP), obtain the domain-challenge token, add it to `deploy/gsa-perdiem/src/public-docs.ts` as `/.well-known/openai-apps-challenge`, release, then enter the listing copy, test cases, starter prompts, and icons from `review/assets/`. No screenshots (no UI).
5. Claude: submit at claude.ai/directory/manage with the listing copy, `docs/directory-icons/gsa-perdiem.png`, the three starter prompts, and the support/privacy URLs.
6. Review and accept each portal's attestations yourself. A saved draft, submitted review, approval, and directory publication are separate states.
