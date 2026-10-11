# Federal Register MCP: Testing

295 regression tests: 190 run offline on every release, and 105 call the live Federal Register API when you turn them on.

## What is tested

All 8 tools, called through the MCP pipeline the way Claude or ChatGPT calls them (`mcp.call_tool`), not by calling the Python functions directly. That matters: an early `list_agencies` crash only showed up through the pipeline.

- **Input checks.** Document numbers (including pre-2011 forms such as `E9-12940`), `YYYY-MM-DD` dates, reversed date ranges, empty or whitespace-only filters, overlong terms, and page limits. Bad input gets a specific message saying how to fix it.
- **Right answers, not just valid ones.** Live tests compare tool output with direct Federal Register API calls: search filters (agency, type, docket, RIN, CFR title/part), document and batch lookups, facet counts, public inspection, open comment periods, and FAR/DFARS case history.
- **Open comment periods.** Results are sorted by deadline, and each answer says whether every matching document was scanned (`complete`) or the list was shortened (`truncated`).
- **FAR case history.** Combines docket and quoted-text matches and labels where each match came from.
- **Shape and size.** Large responses are trimmed by default; HTML error pages are never passed through.
- **Hosted service.** Tool catalog, request guards, response cache timing, and shared request pacing.

Realistic contracting questions (FAR Council co-filings, comment deadlines, case histories, agency queues) were also checked against the official API before release. Those results are in the [October 10, 2026 release record](../../docs/releases/2026-10-10-content-audit.md).

## How to run the tests

From `servers/federal-register-mcp`:

```sh
uv run pytest                                  # offline suite
FR_LIVE_TESTS=1 uv run pytest                  # add live tests (no API key needed)
FR_LIVE_TESTS=1 uv run pytest -m live_smoke    # small one-call-per-test live set
```

Live tests are paced automatically. See [tests/README.md](tests/README.md) for what each test file covers.

## Known limits

- **Archive starts in 1994.** Earlier publication filters are rejected. Older issues are in [GovInfo's digitized archive](https://www.govinfo.gov/features/digitized-federal-register-final).
- **Open-comment scan.** `open_comment_periods` scans up to 500 documents. When `complete` is false, an unscanned document could close sooner; narrow by agency or keyword, or use `search_documents` with `comment_date_gte`/`comment_date_lte`.
- **Indexed deadlines can lag.** A reopening notice can list a later deadline in its DATES section than the indexed close date. Check the document before relying on a deadline.
- **Page limit.** Pages above 50 are rejected because the API cannot reach them.
- **Rate limits.** The Federal Register does not publish numeric limits. The server paces its own requests and honors `Retry-After` without automatic retries.
- **Agency reorganizations.** Older documents can appear under an agency's former name; the server passes through the API's agency mapping.
- **Public inspection changes during the day.** Results reflect the queue at the time of the call.
- **Dates are not legal conclusions.** Effective dates and comment deadlines come from the published documents; they do not establish whether a rule applies to a given contract.

## History

Earlier audit rounds and fixes are in this file's git history and in [changelog.md](changelog.md).
