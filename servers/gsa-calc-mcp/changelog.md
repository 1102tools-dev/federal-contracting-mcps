# Changelog

Release evidence for October 10, 2026 is in the [release record](../../docs/releases/2026-10-10-content-audit.md).

## 1.0.19 — 2026-10-10

Vendor rate card guidance now requires every page for complete or role-specific answers, or explicit partial-result disclosure when pagination stops early.

## 1.0.18 — 2026-10-10

Suggestion counts now show GSA’s reported count uncertainty and remain approximate when its error bound is unknown.

## 1.0.17 — 2026-10-10

Exact searches for titles containing a colon now return that title's own rates. GSA's exact search cut such titles off at the colon and could return unrelated rows; when the full title can't be confirmed, the answer says so and suggests a recovery search instead of guessing.

## 1.0.16

Price checks now count exact-title matches separately from pooled matches, so a specific grade such as Registered Nurse I is not compared against Nurse II/III/IV or specialties. When grades or specialties differ, the statistics are kept but no high/low verdict is given, and the answer explains how to look up the exact title.

## 1.0.15 — 2026-10-10

Asking for a government-worksite filter again returns a clear message under MCP SDK 2.3 telling you to drop the worksite argument and check the site mix, instead of a generic error. Worksite filtering is still unavailable from GSA.

## 1.0.14

IGCE and price-check tool descriptions now say that GSA keyword searches match titles, vendor names and contract numbers, and how mixed populations are handled. A low ceiling-rate percentile is no longer described as evidence of performance risk or price reasonableness.

## 1.0.13

Capped suggestion totals are shown as "at least" counts. Price checks return `MIXED_SEARCH_FIELDS` without a verdict when a keyword also matched vendor or contract fields, and `UNVERIFIED_POPULATION` when the title list is missing, truncated or approximate. Missing averages or zero variance no longer produce made-up z-scores or dollar differences.

## 1.0.12

Vendor rate cards show worksite and contract end dates. With fewer than 20 rates, statistics are returned without a price verdict. Workflow tools gain SIN and clearance filters, matched labor titles, SIN category summaries, truncation flags and worksite counts. Negative lower bounds are clamped to zero and current-year prices are labeled.

## 1.0.11

Hosted service only: the answer cache size can be raised with `MCP_RESPONSE_CACHE_MB` and `MCP_RESPONSE_CACHE_ENTRIES`. The PyPI package is unchanged.

## 1.0.10

Hosted service only: repeat questions are answered from a bounded in-memory cache for 12 hours (GSA refreshes ceiling rates once a day overnight), so a repeat makes no GSA call and uses no budget. Errors are never cached. Off unless `MCP_RESPONSE_CACHE=1`, so the PyPI package is unchanged.

## 1.0.8

Faster request pacing: a shared budget of 500 requests per rolling hour, at least 0.6 seconds between starts, and two requests in flight, with clear retry guidance when the budget runs out. The hosted entrance limit rises from 60 to 120 per minute. Tools are unchanged.

## 1.0.7

The hosted service and the PyPI package now build from the same source.

## 1.0.6

Fixes request-pacing locks that could stay held after a cancelled or failed request. Pacing intervals are unchanged ([issue #10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10)).

## 1.0.5

Published under the MCP Registry name `com.1102tools/gsa-calc-mcp`. No tool changes.

## 1.0.4

Fixes a deadlock when several requests ran at once in the same process. Pacing is unchanged.

## 1.0.3

Safety release: every request waits at least 3 seconds after the last one, and `Retry-After` is honored without automatic retries. An unverified 1,000-requests-per-hour claim was removed.

## 1.0.2

No code changes; republished after the repository moved to the 1102tools-dev account.

## 1.0.1

Correctness fixes: passing `worksite` now returns an error because GSA silently ignores it; `experience_min` alone now means "at least" instead of "exactly"; `price_max` of zero or less is rejected; four retired SINs were removed from the built-in SIN list; and `vendor_rate_card` can page through large vendors (default 100 rows) and flags a partial card.

## 1.0.0

Requires MCP Python SDK 2 (`mcp>=2.0.0,<3`). No tool changes. Claude Desktop `.mcpb` bundles are discontinued; install with `uvx`, `pip`, or Docker.

## 0.2.6

Testing-only release: a large random-input test suite and live checks across all 8 tools found no new bugs.

## 0.2.2

Fixes found by live testing: control characters in search text, `filtered_browse` with no filters returning the whole dataset, `sin=True` silently becoming SIN 1, and `NaN`/`Inf` numbers are now rejected. Pages past the end are flagged, and requests past GSA's 10,000-row window get a clear error. Length limits added to free-text inputs.

## 0.2.1

Searches with apostrophes or SQL-like words (such as O'Reilly) are no longer wrongly blocked, and misspelled parameter names now return an error instead of being silently ignored.

## 0.2.0

Hardening release: fixes crashes on unusual GSA responses, URL-encodes filter values, validates education, worksite, SIN, ordering and range inputs, and rejects empty keyword searches that returned the whole dataset.

## 0.1.0

Initial release: 8 tools for the GSA CALC+ Labor Ceiling Rates API.
