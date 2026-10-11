# USAspending.gov MCP: Testing

2,322 regression tests: 1,943 run by default on every release, and 379 call the live USAspending API when you turn them on.

## What is tested

All 55 tools, called through the MCP pipeline the way Claude or ChatGPT calls them (`mcp.call_tool`), not by calling the Python functions directly. That matters: testing through the pipeline surfaced more than 28 integration issues the earlier unit tests missed.

- **Input checks.** Dates (`YYYY-MM-DD`, reversed ranges), page and limit bounds, amount ranges, empty or whitespace-only code lists, control characters, misspelled parameter names, agency codes, recipient hashes, UEIs and award IDs. Bad input gets a specific message saying how to fix it, before any call to USAspending.
- **Filters that actually filter.** Searches with no real filter are refused instead of returning unfiltered data. Live tests flip one parameter at a time (sort order, agency, NAICS, set-aside, pricing, competition) and check that the answer changes.
- **Right answers, not just valid ones.** Monthly totals add up to the fiscal-year total, page 2 continues where page 1 stopped, and award type groups include the newer assistance codes.
- **Scope notes in answers.** Answers say when a date window matches awards rather than actions, when subcontract totals are cumulative, when federal-account program lists cover all years without dollars, when File C funding coverage is partial, and when recent DoD or USACE data may still be missing.
- **Recipients and vehicles.** Parent and child recipients stay separate, PIID lookups label exact, ambiguous and fuzzy matches, and IDV child orders are reachable in all three modes.
- **Shape and safety.** Unexpected or HTML error responses are never passed through as data, and IDs that would change the request path are rejected.
- **Hosted service.** Tool catalog, tool profiles, request guards, response cache timing, and shared request pacing.

Realistic contracting questions across all 55 tools (award histories, fiscal-year totals, subcontract reports, agency roles, vehicles and federal accounts) were also checked against the official API before release. Those results are in the [October 10, 2026 release record](../../docs/releases/2026-10-10-content-audit.md).

## How to run the tests

From `servers/usaspending-gov-mcp`:

```sh
PYTHONPATH=src uv run --python 3.12 python -m pytest -q                                          # default suite
USASPENDING_LIVE_TESTS=1 PYTHONPATH=src uv run --python 3.12 python -m pytest -q                 # add live tests (no API key needed)
USASPENDING_LIVE_TESTS=1 PYTHONPATH=src uv run --python 3.12 python -m pytest -q -m live_smoke   # small live set, about 10 calls
```

Live tests are paced 1-2 seconds apart automatically. A few tests in the default suite also read the public API. See [tests/README.md](tests/README.md) for what each test file covers.

## Known limits

- **Search history starts October 1, 2007.** USAspending rejects search dates before 2007-10-01.
- **Award date windows match awards, not actions.** A default date window matches awards active during it. For actual activity in a window, page through `spending_by_transaction` and deduplicate award identifiers.
- **Subcontract (FFATA) totals are cumulative.** `spending_by_subaward_grouped` totals are not trimmed to the requested period, and reported amounts can repeat cumulative values, so their sum is not net new subcontract spending.
- **Federal-account program lists are all-year.** They carry no dollar amounts and do not apply a fiscal year; use `get_federal_account_fy_snapshot` for single-year figures. Object-class totals are cumulative across all reported years.
- **Available fiscal years lag.** A year the source has not published yet (for example, right after October rollover) is rejected by the source; the answer explains the available years. Current-year data may be partial.
- **Reporting delays.** DoD and USACE procurement data has a 90-day reporting delay. Submission periods are a reporting calendar, not proof an agency submitted complete data.
- **No parent-vehicle filter by action date.** USAspending cannot filter IDV order obligations by fiscal action date and ordering agency. Vehicle values do not establish a legal ceiling or remaining capacity.
- **Empty IDV children can be a reporting gap.** `get_idv_children` can return zero orders for an active vehicle.
- **Recipient name matching is broad.** A parent-company search can return joint ventures whose names do not match the query; check names before presenting a definitive list.
- **Large responses.** A `limit=100` search can reach about 90K characters, and a DoD sub-agency request with `limit=3` returns about 113 KB because it includes every contracting-office child. Page in batches of 25-30 where possible.
- **Slow endpoints.** Agency overview endpoints can take 20+ seconds against the 30-second client timeout, and large aggregation questions can occasionally time out; asking again usually succeeds.
- **Rate limits.** USAspending does not publish numeric limits. The server paces its own requests and honors `Retry-After` without automatic retries.
- **Pending upstream change.** USAspending plans to replace the `subawards` flag with `spending_level`; the server does not expose `spending_level` yet.

## History

Earlier audit rounds and fixes are in this file's git history and in [changelog.md](changelog.md). The Round 11 paced live campaign referenced in `tests/test_audit_r11.py` is in this file's git history.
