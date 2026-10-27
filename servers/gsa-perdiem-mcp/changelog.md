# Changelog

Release evidence for October 10, 2026 is in the [release record](../../docs/releases/2026-10-10-content-audit.md).

## 1.2.8

Clearer error messages: when the government's API is down, slow or limiting requests, the message says so and how long to wait, and it no longer shows raw server text. It also no longer blames your search terms when the government's server fails. Limits are unchanged. Tools and answers are unchanged.

## 1.2.7

The PyPI page now links to this server's 1102tools page, and the MCP registry entry lists the hosted endpoint. Tools and answers are unchanged.

## 1.2.6

City lookups without a county are now answered from bundled Census place and GSA county data whenever that places the city in one rate area, so most need no key or network call. Big cities named like a rate area (Chicago, Houston, Dallas) match it directly. Other names still use GSA's city lookup. Small places GSA's lookup doesn't recognize, like Shields, IL (Lake County, Chicago rate area), now get their county's rate instead of an unresolved result.

## 1.2.5

Input mistakes, such as a misspelled state or month, again return a specific message saying how to fix the request under MCP SDK 2.3, instead of a generic error.

## 1.2.4

Fixes Doña Ana County (White Sands) worksite lookups, which a text-encoding error had broken, and matches `Doña Ana` and `Dona Ana` alike. The registry description now says a key is needed only for city-only API lookups and unbundled years; bundled city-plus-county lookups need none.

## 1.2.3

Setup docs, data status and missing-key guidance now say clearly that bundled city-plus-county lookups, estimates and comparisons need no key. The `estimate_travel_cost` description now says to add only monthly lodging totals and calculate M&IE once over the actual trip days.

## 1.2.2

Split-month trip results explain how to add monthly lodging and calculate M&IE once, instead of overstating M&IE. A county that conflicts with a city's known county is rejected, ZIP codes are fully validated, and comparison rows keep their GSA source.

## 1.2.1

A city now matches a composite rate area only as a whole part of its name, so "Milton, OH" no longer gets Hamilton's rate. Estimates explain one-month pricing and add notes for long stays (41 CFR 301-11.22); the 75% first/last-day rule is cited as 41 CFR 301-11.20. State lookups show seasonal rates by month, and ZIP lookups keep the county you supplied.

## 1.2.0

City lookups, estimates and comparisons without a county need `PERDIEM_API_KEY`; the shared `DEMO_KEY` fallback is gone, and missing-key requests return setup instructions. ZIP, state and M&IE lookups for bundled years still need no key. The key is sent in a header, never in the request URL.

## 1.1.1

Data status shows which fiscal years each M&IE file covers, since GSA names the file for its first year. The hosted service refuses to start without a key instead of falling back to `DEMO_KEY`.

## 1.1.0

ZIP, state and M&IE lookups for FY2021 onward come from GSA's published files bundled in the package, with no key or network call. Rate areas are never guessed: ZIPs and cities spanning several rate areas return `ambiguous` with every candidate, a new `county` argument picks one, and unknown cities are `unresolved`. `get_access_status` is replaced by `get_data_status`, and every result names its source.

## 1.0.11

With a registered key, requests are spaced 0.6 seconds apart instead of 4, capped at 950 upstream calls per rolling hour (`API_DATA_GOV_HOURLY_CAP`). Adds an optional response cache and an HTTP entry point for the hosted service.

## 1.0.10

Fixes request-pacing locks that could stay held after a cancelled or failed request. Pacing intervals are unchanged ([issue #10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10)).

## 1.0.9

HTTP debug logging no longer records request URLs that carry credentials. Tools and results are unchanged.

## 1.0.8

Adds `get_access_status`, which says whether a key is configured or the server is using the shared `DEMO_KEY`. Rate, authentication and network failures stay visible to the AI as clear tool errors.

## 1.0.7

Published under the MCP Registry name `com.1102tools/gsa-perdiem-mcp`. No tool changes.

## 1.0.6

API keys are redacted from upstream responses, error previews and tool errors, so they never appear in chat transcripts.

## 1.0.5

Fixes a deadlock when several requests ran at once in the same process. Pacing is unchanged.

## 1.0.4

Safety release: every request waits at least 4 seconds after the last one, shared with Regulations.gov when both use the same key, and `Retry-After` is honored without automatic retries.

## 1.0.3

Added optional pacing for personal-key traffic, superseded by 1.0.4.

## 1.0.2

No code changes; republished after the repository moved to the 1102tools-dev account.

## 1.0.1

Fixes 14 problems. Cities that GSA resolves to a county rate area (Washington to District of Columbia, Penasco to Taos) no longer carry a false warning. Alaska, Hawaii and the territories point to DoD (DTMO) rates instead of returning an empty answer, missing monthly data is no longer priced at $0, months must be spelled exactly, and fiscal years before FY2020 are rejected.

## 1.0.0

Requires MCP Python SDK 2 (`mcp>=2.0.0,<3`). No tool changes. Claude Desktop `.mcpb` bundles are discontinued; install with `uvx`, `pip`, or Docker.

## 0.2.5

Wider live testing across all 50 states, seasonal cities, fiscal years and ZIPs found no new bugs. No behavior changes.

## 0.2.1

Misspelled parameter names now return an error instead of being silently ignored.

## 0.2.0

Hardening release: fixes a path-traversal bug in city names, crashes on unusual GSA response shapes, fake $0 rates, and city matching across apostrophes and punctuation (such as "St Louis" and "Martha's Vineyard"). Adds input checks on every tool and a `match_type` on every lookup.

## 0.1.0

Initial release with 6 tools covering the GSA Per Diem Rates API.
