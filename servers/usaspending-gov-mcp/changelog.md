# Changelog

Release evidence for October 10, 2026 is in the [release record](../../docs/releases/2026-10-10-content-audit.md).

## 1.0.25

The award search and spending tools can now filter grants, loans, and other assistance by assistance listing (CFDA) number, for example 93.778 for Medicaid. Undotted numbers like 93778 are accepted, and using the filter with contracts or IDVs returns a clear message. Seven tools gain the filter; the tool count is unchanged.

## 1.0.24

PSC autocomplete now directs partial families such as D3 to the hierarchy tool instead of suggesting unsupported prefix matches.

## 1.0.23

Input mistakes (for example, a bad recipient UEI, an unsupported page, or a missing date window) again return a specific message saying how to fix the request under MCP SDK 2.3, instead of a generic error. Unexpected failures stay masked. Tools and answers are unchanged.

## 1.0.22

Award-date answers now explain that a default date window matches awards active during it, not proof of an action inside the window, and point you to transaction search for actual dated activity. Four tool descriptions are corrected to match.

## 1.0.21

NAICS lookups now count genuinely retired codes separately from current codes left out only by your result limit, and suggest raising the limit to see the rest.

## 1.0.20

When you ask for a federal-account fiscal year the source does not have yet, the answer keeps USAspending's explanation of available years and suggests dropping the year and checking the returned `fy`.

## 1.0.19

Republishes the 1.0.18 content corrections under a new version after the 1.0.18 release stopped on a test timing issue. No tool changes from 1.0.18.

## 1.0.18

Federal-account program lists now say they span all reported years, carry no dollar amounts and ignore a requested fiscal year, and the tool fetches the full list (up to 2,000 records) with a completeness flag. Descriptions now note that agency budgetary resources have no mandatory/discretionary split and that account listings default to the latest available fiscal year.

## 1.0.17

Grouped subcontract (FFATA) totals are labeled as cumulative reported subawards for matching primes, not period rankings, with guidance for getting dated reports.

## 1.0.16

Annual new-award counts for a recipient now follow federal fiscal years. Recipient descriptions now say profiles and trends use the recipient hash, while subsidiaries use the parent UEI or DUNS.

## 1.0.15

Corrects the descriptions of IDV File C funding and submission periods to match what the source actually covers. No tool name or schema changes.

## 1.0.14

The 90-day DoD procurement delay note now also covers USACE, geographic and transaction searches, state summaries and new-award timelines. File C rollups and IDV summaries explain partial coverage, submission periods are labeled as a reporting calendar, and fiscal timeline buckets are labeled.

## 1.0.13

Agency and state queries default to the last completed fiscal year and say so. PIID lookups check exact contracts and IDVs and label ambiguous or fuzzy matches. Searches accept `date_type` (including new awards only), spending tools accept funding agency, competition and pricing filters, recent DoD results warn about the 90-day delay, and grouped subaward paging is fixed.

## 1.0.12

Hosted service only: the answer cache size can be raised with `MCP_RESPONSE_CACHE_MB` and `MCP_RESPONSE_CACHE_ENTRIES`. The PyPI package is unchanged.

## 1.0.11

Hosted service only: cached answers are tied to USAspending's last load date (checked at most every 15 minutes). Searches, totals, counts and details are kept 24 hours or until the next nightly load; if the date can't be read, the 1.0.10 times apply. The PyPI package is unchanged.

## 1.0.10

Hosted service only: repeat questions are answered from a bounded in-memory cache (reference lists, autocompletes and the state list 24 hours; award, IDV, recipient, agency and federal-account details 6 hours; searches, totals and counts 1 hour; the last-updated date 15 minutes). Errors are never cached. Off unless `MCP_RESPONSE_CACHE=1`, so the PyPI package is unchanged.

## 1.0.7

The hosted service and the PyPI package now build from the same source.

## 1.0.6

Fixes request-pacing locks that could stay held after a cancelled or failed request. Pacing intervals are unchanged ([issue #10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10)).

## 1.0.5

Published under the MCP Registry name `com.1102tools/usaspending-gov-mcp`. No tool changes.

## 1.0.4

Fixes concurrent requests in the same process. Adds an opt-in `acquisition-agent` tool profile with a stable 20-tool subset; the full 55 tools remain the default.

## 1.0.3

Safety release: every request waits at least 3 seconds after the last one, and `Retry-After` is honored without automatic retries.

## 1.0.2

No code changes; republished after the repository moved to the 1102tools-dev account.

## 1.0.1

Fixes 22 problems found by a live audit. `get_recipient_children` now works (it takes a UEI or DUNS); UEI filters on transaction search, newer assistance award codes, lowercase set-aside/competition/pricing codes and unfiltered category searches no longer return silently wrong data; `get_award_detail` rejects IDs that would change the request path. Adds `def_codes` filters and `hide_edge_cases` on `get_idv_activity`, removes sort options the API ignores, and documents that recipient name searches can include joint ventures and that an empty IDV child list can be a reporting gap.

## 1.0.0

Requires MCP Python SDK 2 (`mcp>=2.0.0,<3`). No tool changes. Claude Desktop `.mcpb` bundles are discontinued; install with `uvx`, `pip`, or Docker.

## 0.3.1

Fixes two federal-account tools: object classes now use the request method the API requires, and the fiscal-year snapshot takes the numeric `account_id`. Adds broader mock tests for the v0.3 tools.

## 0.3.0

Expands from 17 to 55 tools: subawards, recipient profiles and subsidiaries, agency depth, award funding rollups, transaction and geography search, IDV depth, autocomplete helpers, reference data and Treasury federal accounts. Fixes `list_states`, which would have failed on every call.

## 0.2.10

Adds property-based tests for every input check. No tool changes.

## 0.2.9

Adds a deeper live test set. No tool changes.

## 0.2.8

Fixes PSC filter-tree drill-downs, which failed on every non-empty path, and lets NAICS, PSC and other code lists accept numbers as well as text.

## 0.2.7

Adds 415 tests covering every input field on every tool. No tool changes.

## 0.2.3

`search_awards()` with no filters now returns an error instead of 25 unfiltered recent contracts, and empty or non-JSON responses from USAspending return a clear error.

## 0.2.2

Fixes nine silent wrong-data paths and four validation gaps: control characters, negative amounts, empty code lists and blank award IDs are now rejected before the request.

## 0.2.1

Misspelled parameter names now return an error instead of being silently ignored.

## 0.2.0

Hardening release: no-filter guards, bounded limits and pages, date validation, a two-character minimum for PSC/NAICS autocomplete, retired NAICS codes hidden by default (`exclude_retired=True`), and HTML error pages trimmed to their message.

## 0.1.2

Initial release with 17 tools covering award search, award detail, PIID lookup, PSC/NAICS autocomplete and agency reference data.
