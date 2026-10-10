# Changelog

## 1.1.0

Fixes from the 2026-10-10 bug hunt. All 13 tools keep their names.

**Text parsing** (`get_cfr_content`, `lookup_far_clause`, `compare_versions`)

- eCFR's XML is now read with a real XML parser instead of regular
  expressions. Every text node in eCFR's response comes out once, in order;
  a test checks this on ten saved eCFR responses, and an offline sweep
  checked all of Title 48 plus 13 CFR 121 and 124-127, 2 CFR 200 and others
  (18,044 sections).
- Subpart, part and appendix requests return one object per section under
  `sections`, each with its own section number and heading. Before, they
  came back as one run of paragraphs with no section numbers.
- Indented and list paragraphs (`FP-1`, `FP-2`, `FP-DASH`, `P-2`, `LI` and
  similar) are their own paragraphs. Before, they were dropped or fused into
  neighbors (2 CFR 200 Appendix VIII came back empty; 52.212-3 had a
  5,714-character run-on paragraph).
- Clause text is no longer repeated in `extracts`, which roughly halves
  clause answers (52.219-9 is 58,910 characters, not 116,283).
- Worked examples (`examples`), notes such as drafting notes (`notes`) and
  table captions are kept, numbered, and marked in place in `paragraphs`
  (for example `[See example 1: Example 1 to paragraph (b).]`).
- Footnote marks read `[fn 9]`, so 13 CFR 121.201's NAICS 531110 standard
  reads `$34.0 [fn 9]`, not `$34.09`. Line breaks in table cells become
  spaces, and whitespace is collapsed.
- Images (formulas, forms) appear as `[Image: <link>]` with a warning.
- eCFR's "Link to an amendment published at ..." notices are returned as
  `pending_amendments`, with a warning that the text may be about to change.
- `hierarchy_metadata` paths carry the real date instead of
  `_SUBSTITUTE_DATE_`, plus a full `url`.
- Answers over about 60,000 characters come in pages, split between
  paragraphs, table rows and sections. New optional `page` parameter on
  `get_cfr_content` and `lookup_far_clause`; each page says which page it is
  and how many there are.
- `compare_versions` now returns `changes` (paragraphs added, removed or
  changed, plus heading, table and pending-amendment-link changes) and
  `identical`. When both texts together are too long, it keeps the changes
  and leaves out the full texts, and says so.

**Definitions** (`find_far_definition`)

- Rewritten. 2.101 is indexed by defined term, and each matching definition
  comes back whole (the defining paragraph and every paragraph under it),
  first, as `kind: "definition"`. Before, a fixed window cut 45 of the 253
  definitions while reporting `truncated: false`.
- Names match the way people type them: case, hyphens, spacing, plurals, a
  trailing "means", and the acronym 2.101 puts in a name ("service-disabled
  veteran-owned small business concern", "SDVOSB concern", "COTS",
  "commercial services", "contract means", "SAT").
- Other paragraphs that use the term match on whole words only (so
  "allowable cost" no longer returns "Unallowable cost") and come after the
  definition as `kind: "mention"`, each naming the definition it sits in.
- When 2.101 doesn't define a term, the rest of the FAR is searched for
  `"<term>" means` and the definitions found are returned in
  `defined_elsewhere` (for example 19.001 and 52.219-14 for "similarly
  situated entity"), with `did_you_mean` suggestions from 2.101.

**Current text only** (`search_cfr`, `find_recent_changes`)

- `search_cfr` with `current_only=True` (the default) now checks every hit
  against the section's version history. eCFR's own "current" index still
  lists many superseded and removed versions (52.212-5 came back three
  times; a CAS waiver search returned only the repealed "$15 million" text;
  every section of CAS 404, 407, 408, 409 and 411 showed as current). Older
  copies are dropped; hits whose text has since been replaced or removed are
  dropped and listed under `current_check` (`superseded` with the current
  version's date, `removed` with the removal date).
- `find_recent_changes` is rebuilt on the version history, so removals show
  up (`change: "removed"`), each change says amended, removed or re-issued,
  and `summary` counts them. New optional `page`; `total_pages` says how
  many pages there are. The chapter filter is applied on our side, because
  eCFR's version history ignores it.

**No silent caps or empty answers**

- `get_version_history` reads every page eCFR has (Part 52: all 2,264
  versions, not the first 1,000), with new optional `since_date`,
  `until_date`, `per_page` and `page`, plus `total_count`/`total_pages`. A
  section that isn't in the title is an error instead of an empty list that
  read as "never amended". The `substantive` description now says what
  eCFR's flag really means.
- `get_corrections` returns the newest corrections first (it kept the 50
  oldest, 2005-2009), with new optional `section` and `part` filters.
- `search_cfr` refuses an agency slug eCFR doesn't know ("va", "gsa") and
  suggests the right one, instead of silently finding nothing.
- `list_sections_in_part` includes appendices (all 12 in 2 CFR 200), lists
  subparts, returns just identifier and heading by default (FAR 52: 58,200
  characters, was 142,748; `detail=True` for the old fields), takes an
  optional `subpart`, reports the part's real chapter, and no longer needs
  `chapter` (an explicit wrong chapter is an error).
- `get_cfr_structure` takes an optional `depth`; a tree too large to send
  (chapter 1 is ~1 MB) is cut to the deepest level that fits, with a note.
  `appendix` works (eCFR's structure endpoint has no appendix filter, so the
  appendix is found in the tree; it always failed with HTTP 400 before), a
  Title 48 `subchapter` without `chapter` is an error instead of silently
  meaning the FAR, and the answer says which date it describes.

## 1.0.13

- Hosted service only: the machine running the service can give the answer cache
  more room with `MCP_RESPONSE_CACHE_MB` (size in MiB) and
  `MCP_RESPONSE_CACHE_ENTRIES`. Unset, the sizes are unchanged, so the small
  Cloudflare backup containers keep the defaults.
  `MCP_XML_CACHE_MB` does the same for the XML text cache (default 40 MiB).
- Off unless `MCP_RESPONSE_CACHE=1`, so the PyPI package behaves exactly as
  before. Tools, schemas, pacing, budgets and cache times are unchanged.

## 1.0.12

- Hosted service only: answers are filed under eCFR's update state, a short
  fingerprint of every title's up-to-date, amended and issue dates read from
  `/api/versioner/v1/titles.json` at most every 15 minutes, outside the cache.
  Searches, recent changes, version history, corrections and the last week of
  dated text filed under that state are kept 24 hours; eCFR's next daily update
  changes the state and retires them. Older dated text stays 24 hours. If the
  state can't be read, answers use the 1.0.11 times and it is read again after
  a minute.
- Off unless `MCP_RESPONSE_CACHE=1`, so the PyPI package behaves exactly as
  before. Tools, schemas, pacing and budgets are unchanged.

## 1.0.11

- Hosted service only: answer repeat questions from a bounded in-memory copy of
  eCFR's answers. Text, structure and ancestry for a past date are kept 24
  hours (the past doesn't change); for dates in the last week, which is what
  "current" resolves to, 6 hours. The latest-date lookup is kept 15 minutes,
  the agency list 24 hours, and searches, recent changes, version history and
  corrections 1 hour. A repeat makes no eCFR call and uses no pacing slot or
  budget; identical questions asked at the same time share one call. Errors
  and refusals are never kept. 24 MiB for JSON plus 40 MiB for XML.
  `/health` reports cache counts.
- Off unless `MCP_RESPONSE_CACHE=1`. The PyPI package behaves exactly as
  before, including its existing 5-minute XML cache. Tools, schemas, pacing
  and budgets are unchanged.

## 1.0.9

- Separate fast JSON pacing from controlled XML retrieval. Use a shared
  500-attempt rolling five-minute budget, 0.6-second starts and two in-flight
  slots; uncached XML retains a three-second completion gap.
- Add a bounded five-minute XML cache and coalesce concurrent duplicate misses.
  Errors are never cached. New dates and different filters have separate keys.
- Raise this service's hosted HTTP entrance limit from 60 to 120 per minute.
  Published tools, schemas, authentication and endpoint URLs are unchanged.
- Add cache and cross-process pacing regression tests.

## 1.0.8

Unifies the hosted HTTP wrapper and existing published tool annotations with the
canonical package source. Releases can now build PyPI packages and Cloudflare
images from the same commit, with contract and live version checks.

## 1.0.7

Fixes shared request pacing locks that could remain held when background
executor threads changed. Lock acquisition now uses non-blocking attempts with
async polling, and release stays on the same event-loop thread. This also avoids
abandoned lock acquisitions when a waiting request is cancelled. Pacing intervals
and provider cooldowns are unchanged. Regression coverage includes repeated calls,
upstream errors, cancellation, state-write failures, and cross-process contention.
See [issue #10](https://github.com/1102tools-dev/federal-contracting-mcps/issues/10).

## 1.0.6

Publishes the package under the domain-verified
`com.1102tools/ecfr-mcp` MCP Registry identity and updates project links
to the `1102tools-dev` GitHub repository. No tool behavior changed.

## 1.0.5

Serializes concurrent same-process requests by API identity before acquiring
the existing cross-process file lock. This preserves configured pacing while
preventing same-process lock contention from deadlocking concurrent calls.

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
