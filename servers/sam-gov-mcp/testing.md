# SAM.gov MCP: Testing

1,158 regression tests for the local 20-tool package: 784 run offline on every release, and 374 call the live SAM.gov APIs when you turn them on with your own key.

## What is tested

All 20 local tools, called through the MCP pipeline the way Claude or ChatGPT calls them (`mcp.call_tool`), not by calling the Python functions directly.

- **Input checks.** UEI and CAGE formats, NAICS, PSC, set-aside and business-type codes, country codes, date formats per API (MM/dd/yyyy for Contract Awards, yyyy-MM-dd for Subawards), the one-year Opportunities date span, page limits, and empty or misspelled parameters. Unknown parameters are rejected instead of silently ignored. Bad input gets a specific message saying how to fix it.
- **Right answers, not just valid ones.** Live tests check that filters actually filter (state, NAICS, set-aside, classification, agency, and more), that exact PIID, CAGE, solicitation number and FAIN lookups round-trip, and that paging returns the records it claims to.
- **SAM.gov API quirks.** Parameter casings the API silently ignores (for example `PIID` vs `piid` on Subawards), `exclusionName` vs `entityName`, `offset` meaning a page number on Opportunities and Contract Awards, the 400,000-record paging ceiling on Contract Awards, past-the-end pages that return a stray record or hang, and error bodies sent with HTTP 200.
- **Reps and certs.** Summary mode returns the entity's real FAR and DFARS answers, checked against documented and live response shapes.
- **SBA certifications.** 8(a), HUBZone and other SBA certification codes go through `sbaBusinessTypeCode`, so searches don't silently return zero.
- **Response shapes.** Null, string and single-record responses from SAM.gov are normalized instead of crashing.
- **Your key.** Missing, expired and rate-limited keys return clear guidance, and the key value never appears in tool output or errors.
- **Request pacing.** Shared pacing and `Retry-After` handling across processes.

The hosted 4-tool edition was also checked in October 2026 with several hundred realistic contracting questions and followups, each compared against SAM.gov's official contract opportunities file. Those results are in the [October 10, 2026 release record](../../docs/releases/2026-10-10-content-audit.md). The hosted edition's own tests live with its deployment code, separate from this package.

## How to run the tests

From `servers/sam-gov-mcp`:

```sh
uv run pytest                                                        # offline suite, no key needed
SAM_LIVE_TESTS=1 SAM_API_KEY=your-key uv run pytest                  # add live tests
SAM_LIVE_TESTS=1 SAM_API_KEY=your-key uv run pytest -m live_smoke    # small live anchor set (~10 calls)
```

Live tests are paced 2-4 seconds apart, but a full live pass needs hundreds of calls. A personal key with no SAM role gets about 10 requests a day, so a full pass realistically needs a federal or system-account key. `SAM_TEST_UEI` sets the UEI used by one live lookup test. See [tests/README.md](tests/README.md) for what each test file covers, and [tests/live_audit/README.md](tests/live_audit/README.md) for the separate paced probe harness.

## Known limits

- **Your key's daily limit applies.** From 10 a day (non-federal, no SAM role) to 10,000 a day (federal system account). Keys expire every 90 days.
- **Public REST APIs only.** OASIS+ and login-required transactional endpoints are not covered. Behavior on the 10,000-a-day system-account plan has not been observed.
- **Contract Awards paging stops at 400,000 records** (offset x limit), so only the first 400,000 records of any result can be paged.
- **Contract Awards history reaches back to FY1970**, but volumes thin out before 1980.
- **A UEI can return more than one registration record.**
- **Hosted edition is not a full archive.** It serves notices that remain active in SAM.gov's public file, including some from earlier fiscal years. Archived notices and attachment contents are not included; results link to the notice on sam.gov.
- **Hosted keyword search is literal.** A keyword hit is not the same as a good fit; read the full notice.
- **Source data can be incomplete or contradictory.** Some notices have blank descriptions, missing work locations, unclear time zones on deadlines, or deadlines that differ between the data field and the notice text. The server reports what SAM.gov publishes and does not fill gaps.
- **Notice amounts are not obligations.** Estimated values and award amounts in notices are not verified spending; use USAspending for that.

## History

Earlier audit rounds and fixes are in this file's git history and in [changelog.md](changelog.md). The Round 10 paced live campaign referenced in the tests is in this file's git history.
