# Changelog

## 1.0.4

Suite-wide API safety release. Every upstream request, including XML content
and JSON metadata calls, now passes through a 3-second default cross-process
gate. Provider `Retry-After` is honored without automatic retries. Version
reporting now derives consistently from installed package metadata, and the
release workflow runs the complete offline suite before publishing.

## 1.0.3

No code changes. Republish to verify the Trusted Publisher pipeline after the repo moved to the 1102tools-dev account.

## 1.0.2

Round 6: an external re-audit probed the constants against the live API, the
XML parser against real section archetypes, and the exposed parameters
against documented API behavior. Ten findings, all fixed here.

### Fixed

**Nine live Title 48 chapters were unreachable through chapter filters.**
`TITLE_48_CHAPTERS` was missing chapters 17, 19, 21, 30 (the entire DHS
HSAR), 34 (Dept. of Education), 52 (Navy), 54 (DLA), 57 (USADF), and 61
(Civilian Board of Contract Appeals), all live and non-reserved in eCFR. The
chapter validator rejected them with a confident but false "not a valid
Title 48 chapter" error across every chapter-taking tool. The map now
matches the eCFR agencies endpoint, chapter 16's label is corrected to
FEHBAR (there is no "OPMAR"), and a live-gated regression test diffs the
map's keys against agencies.json so it cannot silently drift again.

**Table content was silently discarded.** The parser extracted only
paragraph, heading, citation, and extract tags, so a table-based section
like FAR 1.106 (a 562-cell OMB control number table) came back as a single
stray paragraph with no signal that anything was missing. Tables now parse
into a `tables` field (rows of cell strings, both HTML-style and GPO-style
markup) with a `table_note`, and any table that resists row parsing is
reported in a `warning` instead of vanishing.

**Dropped heading and editorial-note text.** `<HD1>`-`<HD3>` blocks (which
carry text like "(End of clause)" and Alternate markers) and `<FP>` flush
paragraphs now flow into `paragraphs` in document order; `<EDNOTE>` bodies
land in a new `editorial_notes` field.

**`summary_only` agency listings lost the biggest FAR supplements.** CFR
references that live on child agencies (DFARS chapter 2 sits on a DoD child,
HSAR chapter 30 on a DHS child, plus chapters 34, 52, 54, and 61) were
stripped along with the `children` key, so the summary could not answer
"which chapter is DFARS". Child references now merge into the parent row.

**Trailing paragraph cites 404'd.** `section='15.305(a)(2)'`, a common LLM
shape, now resolves to section `15.305` on every section-taking tool. The
404 guidance also explains paragraph cites and the 2017-01-03 history floor.

**`compare_versions` accepted dates before eCFR history begins.**
Point-in-time coverage starts 2017-01-03; earlier dates always 404'd with
misleading guidance. They are now rejected up front with the floor named.

**Stale `USER_AGENT`.** The header was pinned at `ecfr-mcp/1.0.0`. It now
derives from the installed package version so it cannot go stale again.

**Live test gate documented wrong.** testing.md said `ECFR_LIVE_TESTS=1`;
the gate only read `MCP_LIVE_TESTS`, so the documented command silently ran
zero live tests. Both variables now work and the docs name the real one.

### Added

**`appendix` parameter** on `get_cfr_content`, `get_cfr_structure`, and
`get_ancestry`. DFARS appendices (Appendix A, F, H, and I to Chapter 2) were
live in the API but unreachable through any tool parameter.

**`order` and `agency_slugs` on `search_cfr`.** The API supports both; the
docstring previously claimed only relevance ordering existed. Verified
orderings: relevance, newest_first, oldest_first, hierarchy, citations.
`find_recent_changes` now returns newest first instead of applying
relevance scoring to a wildcard query.

**Docstring corrections** in `search_cfr`: the per_page text described a
100-item soft cap that never existed (actual bound 1 to 5000).

## 1.0.1

### Fixed

**Most CFR sections were unreachable.** The CFR identifier parameters
(`section`, `part`, `subpart`, `chapter`, `subchapter`, `part_number`,
`section_id`) were declared as `Any`, so the emitted JSON Schema carried no
type constraint. A conformant client was free to send `4.130` as a JSON
number, Python received the float `4.13`, and the validator refused it. Only
identifiers ending in a letter, such as `4.88a`, survived, which in most CFR
titles is a small minority of sections.

The quiet part was worse than the error: `4.130` and `4.13` are different
sections, and a float round-trip collapses one into the other. The validator
rejecting the request is the only thing that kept this from returning the
wrong regulatory text without any signal.

Those parameters are now typed `str | int`, so the schema constrains them to
string or integer and decimal identifiers arrive intact. A regression test
asserts every identifier parameter carries a type constraint, and a second
test checks that `4.130` and `4.13` still resolve to different sections.

Reported by @zackunseasoned in #6, who also narrowed the scope by testing the
sibling servers and confirming the issue is eCFR-only: JSON numbers cannot
carry leading zeros, so codes like `01` are always serialized as strings.
Fix contributed in #8, extended here to `list_sections_in_part`, which the
original patch did not cover.

## 1.0.0

First stable release. The suite is feature-complete for its intended scope and
moves to baseline maintenance from here.

### Breaking

Requires **v2 of the MCP Python SDK** (`mcp>=2.0.0`). Version 2 renamed the
high-level server class from `FastMCP` to `MCPServer` and removed the
`mcp.server.fastmcp` module. No tool name, parameter, or response shape changed.
Installs pinned to `mcp` 1.x should stay on the 0.x line of this package.
The requirement is now bounded (`mcp>=2.0.0,<3`) so a future major release of
the SDK produces a clean resolver error instead of an import-time crash.

**Claude Desktop `.mcpb` bundles are discontinued.** Bundles could not be
signed in a way Claude Desktop recognizes, so every install surfaced an
untrusted-developer warning, and because the bundle shipped without a lockfile
it re-resolved its dependencies on every launch, which is what made it the
install path most exposed to the failure above. Install via `uvx`, `pip`, or
Docker instead; the per-server readme has the client config block. Existing
bundle installs keep working until removed, but will not receive updates.

Earlier releases declared `mcp>=1.0.0` with no upper bound. When `mcp` 2.0.0
published, fresh installs of the 0.x line resolved to it and failed at import
with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. Requiring
`mcp>=2.0.0` closes that gap.

### Changed

- Package version, `__version__`, `USER_AGENT`, and the MCPB manifest version
  are now synchronized. The USER_AGENT currency test derives its expected value
  from package metadata rather than a hardcoded literal, which is why the string
  had drifted a patch behind the package.
- Declares Python 3.10 through 3.14. Classifiers normalized across all eight
  servers.

### Verified

240 regression tests (134 offline, 106 live-gated), all passing
against `mcp` 2.0.0 on Python 3.14, with pass counts identical to the pre-migration
baseline on `mcp` 1.x. Server confirmed to boot over stdio and enumerate all
13 tools.

## 0.2.5

Round 6: Hypothesis-driven property test suite + extensive live audit.
138 new test functions (~25,000 random probes via Hypothesis + 100+ live
calls across all 13 tools). Two real bugs found and fixed.

### P3 bug: _safe_int crashed on inf/nan floats

Same bug pattern as sam-gov-mcp 0.3.7. `_safe_int(float('inf'))` raised
`OverflowError` instead of returning the default. Fix: added OverflowError
to the except clause.

### P3 bug: _validate_title_number crashed on inf

`int(float('inf'))` raises OverflowError, which the validator's except
clause did not catch. Now caught alongside TypeError/ValueError.

### Round 6 coverage

Bucket | Functions | Notes
---|---|---
A. Shape helpers (_safe_dict/_as_list/_safe_int/_strip_or_none) | 4 | 500 probes each
B. _clamp / _clamp_str_len | 2 | sys.maxsize bounds
C. _clean_error_body fuzz | 1 | 500 probes
D. _validate_date_ymd | 2 + 9 specific | calendar edges
E. _validate_title_number | 1 + 16 specific | 1-50 range, inf/nan rejection (P3 bug fix)
F. _coerce_cfr_str | 1 | 500 probes
G. _validate_chapter | 1 | 500 probes
H. _validate_query_safe | 1 + 1 specific | null byte rejection
I. Async concurrency | 2 | 50 concurrent + 50 sequential
J. Encoding edge cases | 5 specific | unicode, emoji
K. Live tests (~100 calls) | 100+ | 18 CFR titles, 10 FAR clauses, 5 DFARS clauses (chapter 2), 20 FAR parts, 10 search queries, 8 FAR definitions, 3 ancestry, 3 version history, compare versions, corrections, recent changes, CFR content, concurrent calls, validation rejection live

### Test counts after round 6

- `tests/test_validation.py`: 102 (89 offline + 13 live-gated)
- `tests/test_round_6.py`: 138 (40 offline Hypothesis + 98 live)
- **Total: 240 regression tests (134 offline, 106 live-gated)**
- **Density: 18.5 tests per tool** (13 tools)

## 0.2.1

Cross-MCP fix discovered during the sam-gov-mcp 0.3.1 live audit.

- FastMCP tools generate pydantic argument models with the default
  `extra='ignore'` config. Unknown parameter names were silently
  dropped: a typo like `search_cfr(keyword='audit')` (real param is
  `query`) would succeed with the typo discarded, leaving the tool
  to call the API without the intended filter. Now every tool has
  `extra='forbid'` applied after registration, so typos raise
  "Extra inputs are not permitted" before any HTTP call.
- USER_AGENT bumped to `ecfr-mcp/0.2.1`.
- Added regression test covering the new behavior.

## 0.2.0

Hardening pass. Deep audit surfaced 72 issues across five rounds (2 P0, 26 P1,
32 P2, 12 P3). All fixed.

### Crash fixes (P0)
- `search_cfr` was silently ignoring every filter: query, title, chapter,
  part, subpart, section, current_only, date filters, per_page, page. The
  tool built the query string into the URL path and then passed `params={}`
  to httpx, which strips the existing query string. Every call returned a
  random default 20-result set of all-CFR content. Fixed by passing params
  as a proper dict.
- `find_recent_changes` delegates to `search_cfr` and inherited the same
  P0. `since_date` is now actually applied.

### Crash fixes (P1)
- `_resolve_date` crashed on reserved titles (up_to_date_as_of is null).
  Returns a clear "title is reserved" error instead of building a URL
  containing the literal string "None".
- `_resolve_date` crashed on API response shape variance: titles as a
  non-list, individual entries as None or non-dict, missing `number` field,
  `number` as a string instead of int. All handled defensively now.
- `_walk_structure` crashed on `children: None`, dict children, or null/
  non-dict child entries. Defensive for each.
- `_parse_xml_to_text` crashed on non-string input (bytes, None, int).
  Handled.
- `_get_json` leaked raw `JSONDecodeError` when the API returned HTML
  (maintenance page, 404 HTML), empty body, truncated body, or binary.
  Now raises a descriptive RuntimeError with content-type and body preview.
- `_format_error` crashed on bytes body (`.lower()`). Now safely coerces.

### Silent wrong-data fixes (P1)
- `get_cfr_content` with `section=""` or whitespace previously returned
  the entire 23.2 MB title XML. Now requires at least one of section/
  subpart/part/chapter.
- `lookup_far_clause` with empty `section_id` had the same 23 MB bomb.
  Now rejects empty.
- `find_far_definition` with empty term matched every paragraph (437 KB).
  With term="the" matched 358 paragraphs (327 KB). Now requires
  minimum 3 chars and paginates with `max_matches` (default 20, cap 100).
- `get_cfr_content` with unknown `chapter` (e.g. "0", "27") silently
  returned the full title. Chapter is now validated against
  TITLE_48_CHAPTERS when title=48.
- `list_agencies` returned ~100 KB. Added `summary_only` mode (default
  True) that strips deep `children` trees and non-essential fields,
  dropping payload to ~30 KB.
- `get_corrections` returned all 283 corrections (109 KB). Added `limit`
  (default 50, max 1000) and `since_year` filters.
- `_parse_xml_to_text` didn't HTML-unescape the heading or citations.
  `&amp;`, `&lt;`, `&gt;`, numeric entities now correctly decoded
  alongside paragraphs.
- Regex matching was case-sensitive; mixed-case `<head>`, `<p>`, `<cita>`
  tags were silently dropped. Now case-insensitive. Attribute-bearing
  tags like `<HEAD class="x">` now also match.
- `_parse_xml_to_text` did not strip HTML comments (content leaked through).
  Now stripped before paragraph extraction. CDATA content preserved.

### Validation (P2)
- `date` now validated as YYYY-MM-DD with real calendar check on every
  tool that takes one: `get_cfr_content`, `get_cfr_structure`,
  `get_ancestry`, `compare_versions`, `list_sections_in_part`,
  `find_far_definition`, `find_recent_changes`, search date filters.
  Rejects `""`, whitespace, `2026/04/16`, `April 16, 2026`, ISO 8601
  timestamps, and `"current"` with actionable messages.
- `part`, `subpart`, `section` accept `int` or `str` on every tool.
  Previous pydantic str-only rejection of `part=15` was a frequent
  LLM-calls-tool pain point. Handoff-known issue for get_ancestry and
  get_cfr_structure, extended to version_history and list_sections_in_part.
- Common user mistakes like `section="FAR 15.305"`, `"48 CFR 15.305"`,
  `" 15.305 "`, `"DFARS 252.204-7012"` are now normalized to the bare
  identifier rather than hitting the API as a 404.
- `title_number` / `title` validated as int 1-50.
- `search_cfr.query` rejects empty, whitespace, null byte, and strings
  over 500 chars.
- `search_cfr.per_page` and `.page` now bounds-checked (>= 1).
- `get_corrections.limit` bounds-checked (1-1000).
- `find_far_definition.term` requires minimum 3 characters.
- `find_far_definition.max_matches` bounds-checked (1-100).
- `compare_versions` now rejects identical dates with a "nothing to
  compare" error instead of silently returning two identical blocks.
- Null byte / newline / tab rejected in all coerced identifier strings.
- Strings over 120 chars rejected in identifier fields (catches
  pathological LLM inputs).
- `get_cfr_content` requires at least one scope filter (no more
  accidental whole-title fetches).

### Polish (P3)
- `_get_client` now re-creates the client if it was closed, protecting
  against multi-event-loop test harnesses.
- `_clean_error_body` helper strips HTML title/h1 from upstream HTML
  error pages instead of including raw HTML in error messages.
- XML decl and other processing instructions stripped before parsing.
- `USER_AGENT` bumped to 0.2.0.
- Error messages on 429/5xx now include retry guidance.

### Release automation
- Added `.github/workflows/publish.yml` for PyPI publishing via GitHub
  Trusted Publisher on tag `v*.*.*`.
- Added `[dependency-groups].dev` with pytest + pytest-asyncio.

### Testing
- New `tests/test_validation.py` with 101 tests. 88 offline tests cover
  every validator, response-shape defense, and XML parser edge case,
  plus the full HTTP-layer mocked error paths. 13 live tests (guarded
  by `MCP_LIVE_TESTS=1`) verify P0 regression: search filters now reach
  the API, int parts are accepted, reserved titles return clear errors,
  and list_agencies summary is under 50 KB.
- The older `stress_test.py` / `stress_test_r2.py` / `stress_test_r3.py`
  are kept for regression reference but not run by CI. They called tools
  as raw coroutines and bypassed pydantic, which is why the round 1
  smoke test said "0 bugs found".

## 0.1.0
Initial release.

- 13 MCP tools covering the eCFR API (admin, versioner, search endpoints)
- Core: get_latest_date, get_cfr_content, get_cfr_structure, get_version_history, get_ancestry, search_cfr, list_agencies, get_corrections
- Workflows: lookup_far_clause, compare_versions, list_sections_in_part, find_far_definition, find_recent_changes
- Server-side XML parsing (Claude never sees raw XML, only clean text with headings, paragraphs, and citations)
- Automatic date resolution (prevents 404s from eCFR's 1-2 day lag)
- Search defaults to current-only (prevents historical version duplicates)
- Actionable error translation for 400/404/406 responses
- No authentication required
