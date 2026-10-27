# Changelog

Release evidence for October 10, 2026 is in the [release record](../../docs/releases/2026-10-10-content-audit.md).

## 1.1.14

Clearer error messages: when the government's API is down, slow or limiting requests, the message says so and how long to wait, and it no longer shows raw server text. Regulation-text requests now stop waiting after 40 seconds instead of 60, so a slow eCFR site gets that clear message. Limits are unchanged. Tools and answers are unchanged.

## 1.1.13

`get_cfr_content` no longer calls itself the primary workhorse for reading regulatory text. Its description now just says what it returns. Tools and answers are unchanged.

## 1.1.12

The PyPI page now links to this server's 1102tools page, and the MCP registry entry lists the hosted endpoint. Tools and answers are unchanged.

## 1.1.11

Hosted cache counts on `/health` no longer include the latest-date check before each lookup. That check now reuses the titles list eCFR's update-state read already fetches, so a new question counts as one lookup and asks eCFR one request fewer. Answers are unchanged.

## 1.1.10

Hosted cache counts on `/health` now cover real users only; 1102tools' own health checks and release checks are counted separately under `monitor`.

## 1.1.9

Common COTS names and unique definition-name prefixes return complete FAR 2.101 definitions; unsuccessful lookups describe search results without claiming a term is undefined.

## 1.1.8

Scientific notation split across superscripts in regulation tables is kept: the 40 CFR 141.61 dioxin limit now reads `3 × 10^−8 mg/l` instead of a footnote. Genuine footnotes and ordinal text are unchanged.

## 1.1.7

FAR 2.101 numbered subtype definitions (individual surety, corporate surety, cosurety) now return their complete defining text instead of reporting the term absent. A Surety lookup still returns the whole parent definition with all three types.

## 1.1.6

When a section or snapshot is missing, the answer again explains how to recover under fresh MCP SDK installs, so legacy-section questions can move on to history, available dated text and removal comparisons. Tool contracts are unchanged.

## 1.1.5

Version history is sorted oldest-first before paging, even when eCFR returns records out of order. Comparisons can use available text from before 2017 (such as a December 2016 Section 508 snapshot), and an unavailable older snapshot gets recovery guidance instead of a false "section added or removed."

## 1.1.4

Internal pacing tests were made reliable; the two-in-flight limit and the 500-request rolling five-minute budget are unchanged. No content behavior changed (1.1.3 never published).

## 1.1.3

Natural names such as "contracting officer representative" find the full FAR 2.101 definition. Comparison followups keep the requested CFR title, and combined chapter/part/section filters on editorial corrections match the same reference, so a Part 52 query no longer pulls in other FAR parts.

## 1.1.2

Input and lookup errors (such as an unavailable date or the wrong title) keep their recovery guidance in fresh MCP SDK 2.3.0 installs, matching the hosted service.

## 1.1.1

`compare_versions` rejects dates past the title's latest snapshot instead of falsely reporting a section removed, and a citation naming a different title (for example `2 CFR 200` with the default Title 48) explains how to select the right one. `changes_only=True` also leaves out full texts when a section was added or removed.

## 1.1.0

Fixes from the October 10, 2026 bug hunt; all 13 tools keep their names. Regulation text is read with a real XML parser, so every paragraph, list item, table, example, note, footnote mark (`[fn 9]`), image link and pending-amendment notice comes through once and in order, subpart and part reads return one entry per section, and long answers come in pages under 64,000 characters. `find_far_definition` returns whole definitions by name (plurals, acronyms, trailing "means") and looks elsewhere in the FAR and DFARS when 2.101 has none. `search_cfr` drops superseded and removed text from current results and explains why under `current_check`; `find_recent_changes` shows removals; version history, corrections, section lists and structure no longer cut off silently. Copied citations (`§ 15.305`, `48 C.F.R.`, `FAR Part 22`, supplement prefixes, paragraph cites) work everywhere, and `lookup_far_clause` works out the chapter from the clause number.

## 1.0.13

Hosted service only: the answer cache and XML cache sizes can be raised with `MCP_RESPONSE_CACHE_MB`, `MCP_RESPONSE_CACHE_ENTRIES` and `MCP_XML_CACHE_MB` (default 40 MiB). The PyPI package is unchanged.

## 1.0.12

Hosted service only: cached answers are tied to eCFR's update state (checked at most every 15 minutes). Searches, recent changes, version history, corrections and the last week of dated text are kept 24 hours or until eCFR's next daily update; older dated text stays 24 hours. The PyPI package is unchanged.

## 1.0.11

Hosted service only: repeat questions are answered from a bounded in-memory cache (past-date text 24 hours, last-week text 6 hours, latest date 15 minutes, agency list 24 hours, searches, recent changes, version history and corrections 1 hour). Errors are never cached. Off unless `MCP_RESPONSE_CACHE=1`, so the PyPI package and its 5-minute XML cache are unchanged.

## 1.0.9

Faster request pacing: a shared budget of 500 requests per rolling five minutes, at least 0.6 seconds between starts and two in flight, while uncached XML keeps a three-second gap. Adds a five-minute XML cache and raises the hosted entrance limit from 60 to 120 per minute.

## 1.0.8

The hosted service and the PyPI package now build from the same source.

## 1.0.7

Fixes request-pacing locks that could stay held after a cancelled or failed request. Pacing intervals are unchanged ([issue #10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10)).

## 1.0.6

Published under the MCP Registry name `com.1102tools/ecfr-mcp`. No tool changes.

## 1.0.5

Fixes a deadlock when several requests ran at once in the same process. Pacing is unchanged.

## 1.0.4

Safety release: every request waits at least 3 seconds after the last one, and `Retry-After` is honored without automatic retries.

## 1.0.3

No code changes; republished after the repository moved to the 1102tools-dev account.

## 1.0.2

Nine live Title 48 chapters (including HSAR chapter 30) were wrongly rejected and now work, tables and headings such as "(End of clause)" are no longer dropped from section text, and agency summaries show which chapter is DFARS. Adds an `appendix` parameter (for DFARS appendices) and `order` and `agency_slugs` on `search_cfr`; paragraph cites such as `15.305(a)(2)` resolve to the section. The live-test switch now accepts both `ECFR_LIVE_TESTS=1` and `MCP_LIVE_TESTS=1`.

## 1.0.1

Section numbers such as `4.130` are no longer turned into `4.13`: identifier parameters are typed string-or-integer so decimal section numbers arrive intact (reported in #6, fixed in #8).

## 1.0.0

First stable release, built on v2 of the MCP Python SDK (`mcp>=2.0.0,<3`). No tool name, parameter or response changed. Claude Desktop `.mcpb` bundles are discontinued; install with `uvx`, `pip` or Docker.

## 0.2.5

Fixes two crashes on infinite or non-number inputs found by property-based testing.

## 0.2.1

A misspelled parameter name (for example `keyword` instead of `query`) now returns an error instead of being silently ignored.

## 0.2.0

Hardening release. `search_cfr` and `find_recent_changes` had been ignoring every filter and now apply them. Empty inputs no longer return a whole 23 MB title, dates and identifiers are validated with clear messages, and common citation forms such as `FAR 15.305` are accepted.

## 0.1.0

Initial release: 13 tools covering eCFR text, structure, search and version history, with server-side XML parsing, automatic date resolution and current-only search by default. No authentication required.
