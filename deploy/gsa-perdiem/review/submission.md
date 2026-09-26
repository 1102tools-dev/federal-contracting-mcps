# GSA Per Diem MCP publication

Publisher: James Prentiss Jenrette (individual). Brand: 1102tools.

Endpoint: https://gsa-perdiem.1102tools.com/mcp
Transport: Streamable HTTP (stateless, JSON responses).
Authentication: none. Users need no account or API key. City lookups call the GSA Per Diem API with a publisher key held as a Cloudflare Worker secret, sent in the `X-Api-Key` header and never exposed.
Support: https://gsa-perdiem.1102tools.com/support
Privacy: https://gsa-perdiem.1102tools.com/privacy
Terms: https://gsa-perdiem.1102tools.com/terms
Source: https://github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/gsa-perdiem-mcp
Category: Government / travel.

Status: prepared, **not ready to submit**. 1.2.0 is released and verified in production (tag `gsa-perdiem/v1.2.0`, commit `0691651`, 2026-09-26). Resolve every item under "Open before submission" first.

## Open before submission

1. **Third-party API eligibility (both portals).** OpenAI does not approve plugins that primarily act as unofficial pass-through connectors, and Anthropic's policy section 3(F) asks developers to verify control of the API endpoints their software connects to. 1102tools controls `gsa-perdiem.1102tools.com`, not `api.gsa.gov`. Do not attest ownership or control of GSA endpoints. Ask each platform how it applies these rules to a public government API before accepting the attestation. The statement below describes the service's own functionality.
2. **OpenAI demo recording URL.** Record the principal tools (ZIP, city with an ambiguous result, estimate, compare) on production 1.2.0.
3. **OpenAI domain verification.** The portal issues the `/.well-known/openai-apps-challenge` token; add it to `deploy/gsa-perdiem/src/public-docs.ts` and release.
4. **Production tool scan** in each portal after the final deployment.
5. **Capacity and origin testing** through each platform's connector: cold start, representative concurrency, p95 latency, 429/503 counts, and upstream budget use. The Worker rejects a cross-origin `Origin` header (403 for `https://claude.ai` and `https://chatgpt.com` in the audit); server-side connector calls send none. Add allowed origins only if a supported client needs them. Measured directly on 2026-09-26 (not through a platform connector): 40 requests at 10 concurrent returned all 200 with no tool errors, p95 0.32 s; the service's own Origin returns 200.
6. **Cloudflare retention.** The privacy notice states Cloudflare's documented 7-day maximum for Workers Logs. Confirm the account has no Logpush or other log export before accepting a privacy attestation.
7. **Portal access.** Recheck on the publishing account that the Claude directory portal is open to it (announced September 25 for paid Claude plans).

Independent functionality (for eligibility questions): ZIP, state, and M&IE answers come from GSA's published files for FY2021 onward bundled in the service, with no GSA call. The service identifies ZIP codes and cities that span more than one rate area and lists every candidate instead of guessing. It applies a labeled Census county tie-break, computes trip estimates with first- and last-day M&IE at 75% (41 CFR 301-11.101), compares destinations, and detects OCONUS locations instead of returning a CONUS rate. Only city lookups, and fiscal years that are not bundled, call the GSA API. The service uses a registered api.data.gov key under api.data.gov's terms.

## Listing copy

Name: GSA Per Diem by 1102tools

OpenAI short description (≤30): Federal per diem rates

One-liner (≤200): Federal travel per diem rates from GSA: lodging by month and M&IE by city, ZIP, or state, with county disambiguation and trip cost estimates for IGCEs.

Description (≤2,000):
Look up the official GSA per diem rates that cap federal travel lodging and meals-and-incidental-expense (M&IE) reimbursement in the continental United States. Search by city, ZIP code, or state, adding a county when a city or ZIP spans more than one rate area; see monthly lodging rates for seasonal locations; get the M&IE breakdown by meal; estimate a trip's per diem with first- and last-day M&IE at 75% (41 CFR 301-11.101); and compare destinations for an independent government cost estimate.

ZIP, state, and M&IE answers come from GSA's published per diem files (FY2021 onward) included in the service; city names are resolved to rate areas through the GSA Per Diem API. GSA sets rates by county or locality, so when a ZIP code or city spans more than one rate area the service lists every candidate instead of choosing one, and a county selects the applicable rate. Each result names the GSA file or API it came from.

Rates are reimbursement ceilings, not hotel prices. Alaska, Hawaii, U.S. territories, and foreign locations are set by DoD and the State Department and are not covered; the service says so rather than returning a CONUS rate. Read-only; no account needed. Independent service, not endorsed by GSA.

## Tools and annotation justifications

The server publishes no `instructions`. Tool descriptions describe behavior only.

| Tool | `readOnlyHint: true` | `destructiveHint: false` | `openWorldHint` |
|---|---|---|---|
| lookup_city_perdiem | Returns GSA rates; writes nothing. | Creates, changes, or deletes nothing, locally or at GSA. | `true`: sends city, state, and fiscal year to the GSA Per Diem API. |
| estimate_travel_cost | Computes an estimate from looked-up rates; stores nothing. | No side effects. | `true`: resolves the city through the GSA Per Diem API. |
| compare_locations | Returns rates for up to 25 locations; stores nothing. | No side effects. | `true`: one GSA city lookup per location. |
| lookup_zip_perdiem | Returns rates for a ZIP code. | No side effects. | `true`: bundled GSA file for FY2021+, GSA API for other fiscal years. |
| lookup_state_rates | Returns a state's rate areas. | No side effects. | `true`: bundled file for FY2021+, GSA API otherwise. |
| get_mie_breakdown | Returns M&IE meal tiers. | No side effects. | `true`: bundled file for FY2021+, GSA API otherwise. |
| get_data_status | Reports bundled data and credential presence. | No side effects. | `false`: reads only bundled metadata and local configuration. |

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

Source 1.2.0 (branch `claude/directory-audit-fixes`, 2026-09-26): offline suite 277 passed, 267 live-gated skipped (544 collected); release guards 57 passed; shared pacing and admission 100 passed; `scripts/check_hosted_contract.py gsa-perdiem` unchanged (7 tools); `scripts/validate_versions.py` passed.
`X-Api-Key` header authentication checked against `api.gsa.gov` on 2026-09-26: the header and the old `api_key` query parameter draw on the same quota, and an invalid key returns 403.
Live parity against the GSA API on 2026-09-26 with a registered key (1.1.x): every sampled ZIP (about 110 per fiscal year, FY2026 and FY2027) matched the bundled files; state lists for VA, MD, CA, MA, TX, CT, PA, and AZ matched; the city corpus resolved as expected.
Production 1.1.1 on 2026-09-26: `/health` ok at `001e536`; the updated `scripts/check_hosted_health.py` passed with a live GSA city lookup; all 79 monitor cities resolved as exact GSA API matches for FY2027.
Production 1.2.0 on 2026-09-26 (release run 36269423238, all jobs passed): `/health` ok, 7 tools, `0691651`; PyPI and the MCP Registry list 1.2.0; the health check passed with a GSA city lookup (Visalia, CA); every tool called on production returned the expected result (ZIP 01011 `ambiguous`, McLean `resolved`, Anchorage OCONUS); the new privacy notice is served. Before release, the exact image passed `verify_hosted_release.py` with upstream calls on a registered key.

## Remaining user steps

1. Resolve "Open before submission" above.
2. Test every tool on production in Claude (custom connector) and ChatGPT (Developer Mode).
3. OpenAI: create the plugin draft (verified individual publisher, no-auth MCP), enter the short description, listing copy, annotation justifications, test cases, starter prompts, demo URL, and the directory and composer icons from `review/assets/` (the same light and dark set ChatGPT made). No screenshots (no UI).
4. Claude: submit at claude.ai/directory/manage with the listing copy, the light and dark icons `review/assets/gsa-perdiem-directory-light.png` and `review/assets/gsa-perdiem-directory-dark.png`, the three starter prompts, and the support/privacy URLs.
5. Review and accept each portal's attestations yourself. A saved draft, submitted review, approval, and directory publication are separate states.
