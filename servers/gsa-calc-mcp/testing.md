# GSA CALC+ MCP: Testing

443 regression tests: 322 run offline on every release, and 121 call the live GSA CALC+ API when you turn them on.

## What is tested

All 8 tools, called through the MCP pipeline the way Claude or ChatGPT calls them (`mcp.call_tool`), not by calling the Python functions directly. That matters: the bug where `filtered_browse` with no filters returned all 265,000 records only showed up through the pipeline.

- **Input checks.** Control characters, overlong text, `NaN`/`Inf` numbers, negative or reversed price and experience ranges, unknown education codes, `sin=True` coerced to `1`, misspelled parameter names, and pages past GSA's 10,000-row window. Bad input gets a specific message saying how to fix it.
- **Filters really filter.** Live tests compare filtered totals with GSA's own counts, so a filter GSA silently ignores fails the test. This is how the dead `worksite` filter and the `experience_min` exact-match bug were caught.
- **Right answers, not just valid ones.** Live tests compare tool output with direct GSA CALC+ calls: keyword and exact searches, suggestions, IGCE benchmarks, price checks, vendor rate cards (including paging), and SIN analysis.
- **Comparable rates only.** Price checks withhold a high/low verdict when a keyword pools vendor or contract matches (`MIXED_SEARCH_FIELDS`), when the title list can't be confirmed (`UNVERIFIED_POPULATION`), when grades or specialties differ (`MIXED_LABOR_TITLES`), or when there are fewer than 20 rates.
- **Exact titles.** Titles containing a colon (GSA's exact search cuts them off at the colon) return the real title's rates, not unrelated ones.
- **Odd GSA responses.** Missing or oddly shaped totals, statistics and buckets are handled without crashing; HTML error pages are never passed through.
- **Hosted service.** Tool catalog, request guards, response cache, hourly budget, and shared request pacing.

Realistic pricing questions (IGCE benchmarks, price checks, vendor rate cards, exact-title lookups, SIN and contract follow-ups) were also checked against the official API before release. Those results are in the [October 10, 2026 release record](../../docs/releases/2026-10-10-content-audit.md).

## How to run the tests

From `servers/gsa-calc-mcp`:

```sh
uv run pytest                                      # offline suite
GSA_CALC_LIVE_TESTS=1 uv run pytest                # add live tests (no API key needed)
GSA_CALC_LIVE_TESTS=1 uv run pytest -m live_smoke  # small one-call-per-test live set
```

Live tests are paced automatically. See [tests/README.md](tests/README.md) for what each test file covers.

## Known limits

- **Ceiling rates, not prices paid.** CALC+ rates are the most a contractor can charge under its GSA MAS contract; task order prices should be lower.
- **Keyword searches pool fields.** GSA's keyword search matches labor titles, vendor names and contract numbers together. For title-only rates, find the exact title with `suggest_contains`, then use `exact_search` on `labor_category`.
- **No worksite filter.** GSA ignores worksite filtering, so passing `worksite` returns an error. Remove it and check each rate's worksite field instead.
- **`exact_search` has no SIN or clearance filter.**
- **Approximate GSA statistics.** Percentiles are GSA estimates and can differ by a few dollars an hour between identical calls. Suggestion lists are capped at 100, and their counts can be off by up to five records or marked as lower bounds.
- **10,000-row window.** Results past row 10,000 can't be reached; narrow with filters.
- **Small samples.** With fewer than 20 rates, statistics are returned without a price verdict.
- **Vendor names.** Rate cards match GSA's legal vendor name. Large cards are paged, and rows tied on the sort field can shift across page boundaries.
- **Current rates only.** Historical award data is not exposed.
- **Rate limits.** GSA does not publish a numeric limit for CALC+. The server shares a budget of 500 requests per rolling hour, starts requests at least 0.6 seconds apart with two in flight, and honors `Retry-After` without automatic retries.

## History

Earlier audit rounds and fixes are in this file's git history and in [changelog.md](changelog.md). Pacing test results are in [keyless throughput evidence](../../docs/keyless-throughput.md).
