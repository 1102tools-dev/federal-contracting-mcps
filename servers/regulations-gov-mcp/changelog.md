# Changelog

Release evidence for October 10, 2026 is in the [release record](../../docs/releases/2026-10-10-content-audit.md).

## 2.0.10

Clearer error messages: when the government's API is down, slow or limiting requests, the message says so and how long to wait, and it no longer shows raw server text. It also no longer blames your search terms when the government's server fails. Limits are unchanged. Tools and answers are unchanged.

## 2.0.9

The PyPI page now links to this server in the ChatGPT directory. Tools and answers are unchanged.

## 2.0.8

The PyPI page now links to this server's 1102tools page, and the MCP registry entry lists the hosted endpoint. Tools and answers are unchanged.

## 2.0.7

Hosted cache counts on `/health` now cover real users only; 1102tools' own health checks and release checks are counted separately under `monitor`.

## 2.0.6

Input mistakes (for example, asking to include closed comment periods, or a calendar date where a docket search needs a timestamp) again return a specific message saying how to fix the request under MCP SDK 2.3, instead of a generic error.

## 2.0.5

Comment dates are labeled as Regulations.gov metadata, not a confirmed deadline, and come with links to the Federal Register notice and docket so you can check the DATES section, extensions and conditional deadlines. Raw dates and Eastern-time formatting are kept.

## 2.0.4

FAR case history and open comment periods keep the recovery guidance from searches (empty results, pages past the end, the 40-page limit). A failed organization lookup now leaves the organization unknown instead of implying an individual commented. Hosted build tooling was updated to clear development dependency advisories.

## 2.0.3

Fixes from a 40-question content test:

- **Comment deadlines in Eastern time.** Regulations.gov stores 11:59 PM Eastern as a UTC time that reads one day late (`2026-10-23T03:59:59Z` is Oct 22). Search and detail records now carry `commentDeadlineEastern` and `commentEndDateUtc` in place of `commentEndDate`; `open_comment_periods` and `far_case_history` rows carry `comment_deadline` and `comment_end_date_utc` in place of `comment_end_date`.
- **Comment counts say what they count.** `search_comments` adds `posted_comments` and a `count_note`: comments posted publicly, not comments received. `far_case_history` page 1 adds the docket's `posted_comments`.
- **Withdrawals no longer read as new proposed rules.** Workflow rows keep `subtype` and `fr_doc_num`.
- **Who commented.** `search_comments(include_organization=True)` (page_size up to 25) adds each row's organization.
- **40-page limit.** Searches flag `truncated`, `records_beyond_page_limit` and a `page_limit_note` instead of reporting the last page at page 40.
- `open_comment_periods` takes `document_type`; facets the query already filtered on are left out; comment text comes back as plain text; descriptions explain sort order.

## 2.0.2

Hosted service only: the answer cache size can be raised with `MCP_RESPONSE_CACHE_MB` and `MCP_RESPONSE_CACHE_ENTRIES`. The PyPI package is unchanged.

## 2.0.1

Hosted service only: docket, document and comment details are cached for 6 hours (was 15 minutes); searches and open comment periods stay at 15 minutes. The API key is removed from answers before they are cached. Errors are never cached. Turned on by `MCP_RESPONSE_CACHE=1`; the PyPI package is unchanged.

## 2.0.0

**Breaking: a key is required.** The shared `DEMO_KEY` fallback is gone; without `REGULATIONS_GOV_API_KEY`, data tools return setup instructions. `open_comment_periods` and `far_case_history` now return one page at a time (`page_size` 5-100, `page_number` 1-40) with docket-wide counts. The key is sent in a header, never in the request URL.

## 1.1.0

Smaller results: searches return the top 10 facet counts instead of about 300 agencies, and `page_size` is 5-100 (was 5-250). The hosted service refuses to start without its key instead of using `DEMO_KEY`. A 403 is reported as a key problem only when api.data.gov says so. Date-window guidance now points to the right filter for each search.

## 1.0.11

The server no longer sends instructions at startup. Without a key, data results carry a note on the `DEMO_KEY` limit and where to get a free key.

## 1.0.10

With a registered key, requests are spaced 0.6 seconds apart instead of 4 (`DEMO_KEY` keeps 4 seconds), capped at 950 per rolling hour (`API_DATA_GOV_HOURLY_CAP`). Adds the hosted HTTP entry point and an opt-in response cache. Tools are unchanged.

## 1.0.9

Fixes request-pacing locks that could stay held after a cancelled or failed request. Pacing intervals are unchanged ([issue #10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10)).

## 1.0.8

HTTP debug logging no longer records request URLs that carry the key.

## 1.0.7

Adds `get_access_status`, which reports whether a key is configured without calling Regulations.gov. Rate, authentication and network errors now reach the AI as readable tool errors.

## 1.0.6

Published under the MCP Registry name `com.1102tools/regulations-gov-mcp`. No tool changes.

## 1.0.5

API keys are removed from upstream error bodies, malformed-response previews, network errors and every error the AI sees.

## 1.0.4

Fixes a deadlock when several requests ran at once in the same process. Pacing is unchanged.

## 1.0.3

Safety release: every request waits at least 4 seconds after the last one, Regulations.gov and Per Diem share one `api.data.gov` budget when they use the same key, and `Retry-After` is honored without automatic retries.

## 1.0.2

No code changes; republished after the repository moved to the 1102tools-dev account.

## 1.0.1

Correctness fixes: `open_comment_periods` returns the soonest-closing documents first with the true total (it had been dropping them); pages up to 40 are allowed; multi-agency filters and multi-field sorts work; `far_case_history` flags truncated dockets; empty `docket_id` or `comment_on_id` and document IDs passed as `comment_on_id` are rejected; `within_comment_period=False` gets a clear error. The `DEMO_KEY` limit is stated as 10 per hour.

## 1.0.0

Requires MCP Python SDK 2 (`mcp>=2.0.0,<3`). No tool changes. Claude Desktop `.mcpb` bundles are discontinued; install with `uvx`, `pip`, or Docker.

## 0.2.0

Hardening release: misspelled parameters, an empty `agency_id` (which returned all 1,951,938 documents), control characters, reversed or malformed dates, path characters in IDs and unknown sort fields are now rejected with clear errors. Firewall blocks are no longer reported as key problems, and pages past the end are flagged.

## 0.1.0

Initial release: 8 tools for the Regulations.gov API.
