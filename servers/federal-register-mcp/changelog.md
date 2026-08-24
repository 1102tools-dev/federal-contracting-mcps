# Changelog

## 1.0.5

Publishes the package under the domain-verified
`com.1102tools/federal-register-mcp` MCP Registry identity and updates
project links to the `1102tools-dev` GitHub repository. No tool behavior
changed.

## 1.0.4

Serializes concurrent same-process requests by API identity before acquiring
the existing cross-process file lock. This preserves configured pacing while
preventing same-process lock contention from deadlocking concurrent calls.

## 1.0.3

Suite-wide API safety release. Every Federal Register request now passes
through a 3-second default cross-process anti-burst gate. Provider
`Retry-After` is honored without automatic retries. Version reporting now
derives consistently from installed package metadata, and publication is
blocked unless offline tests and wheel inspection pass.

## 1.0.2

No code changes. Republish to verify the Trusted Publisher pipeline after the repo moved to the 1102tools-dev account.

## 1.0.1

Round 6 audit: a fresh live audit against the production API (contract diff
via the API's own OpenAPI spec plus ~60 live probes) surfaced 12 verified
findings. All fixed. The recurring theme: earlier rounds hardened inputs
against junk but never tested legacy-real inputs, and treated payload size
as the only output risk while result correctness went unchecked.

### Fixed

- **`get_document` / `get_documents_batch` rejected the entire pre-2011
  archive.** The document-number pattern only accepted modern
  'YYYY-NNNNN' numbers, but the API serves legacy families going back to
  1994: 'E9-12940' (2005-2011 electronic era), 'X94-70302' and 'Z9-10645'
  (special series), and 2-digit-year forms like '94-16174'. All verified
  retrievable upstream while the tools refused them. The pattern is now a
  loose URL-safe shape check covering every live-verified family; the
  API's own 404 decides genuinely unknown numbers.
- **`open_comment_periods` missed the soonest-closing deadlines.** It
  fetched only the `limit` most recently PUBLISHED documents and sorted
  that page, so documents closing today (published months ago) never
  appeared while the docstring promised "soonest closing deadline first".
  With 985 open periods live, a default call returned nothing closing
  before Sep 8 while dockets closed Aug 16-17. Now scans up to 500
  matching documents oldest-published first, sorts by close date, and
  returns the first `limit`.
- **`open_comment_periods` reported the page size as `total_open`.**
  `total_open: 5` while the API count was 985. Now reports the API's true
  count plus separate `scanned` and `returned` fields.
- **`open_comment_periods` excluded RULE-type documents.** Interim and
  direct final rules accept comments too (41 open live at audit time,
  including FAA ADs). RULE added to the type filter.
- **`far_case_history` returned a partial set whenever the docket search
  partially matched.** The quoted-term fallback only fired on zero docket
  hits, so 'FAC 2025-06' returned 1 of its 4 documents (the FAC intro and
  companion documents carry only internal docket numbers). Now always runs
  both searches and merges the results deduped by document number.
- **`far_case_history` silently truncated at 100 documents** ('FAR Case'
  matched 1625, returned 100, no flag). Now returns `truncated` plus
  `docket_matches` / `term_matches` API counts.
- **`get_documents_batch` with one document collapsed to the bare document
  object** (no count/results wrapper), breaking callers that iterate
  `results`. Single-document responses are now wrapped as
  `{"count": 1, "results": [doc]}`.
- **`get_facet_counts` accepted any string in `doc_types` and lowercase or
  misspelled values silently returned `{}`**, indistinguishable from "zero
  documents published" (`["rule"]` returned `{}` while `["RULE"]` showed
  153 in the same window). Now typed with the same PRORULE/RULE/NOTICE/
  PRESDOCU literal as `search_documents`.
- **Pre-1994 guard was asymmetric.** `pub_date_lte="1990-01-01"` silently
  returned an empty set while the gte side raised an actionable error.
  Both sides now raise, in `search_documents` and `get_facet_counts`.
- **`get_public_inspection` parent-agency filters silently returned
  nothing.** PI documents list only the filing sub-agency, and matching
  was slug-only, so `agency_filter="defense-department"` returned 0 while
  a Defense sub-agency filing sat in the queue. Matching now covers slug,
  name, and raw name (with hyphens-as-spaces fallback) and the docstring
  warns about parent slugs.

### Added

- **CFR location filters.** `cfr_title` + `cfr_part` on both
  `search_documents` and `get_facet_counts`, mapping to
  `conditions[cfr][title]` / `conditions[cfr][part]` (part accepts ranges
  like '1-99'; part requires title, enforced with an actionable error).
  48 CFR part 52 alone covers 1086 documents that were previously
  unreachable by filter.
- **Time-bucket facets.** `get_facet_counts` now accepts daily, weekly,
  monthly, quarterly, and yearly facets alongside type, agency, and topic.

### Changed

- `far_case_history` response: `total_documents` is now the merged returned
  count; new `docket_matches`, `term_matches`, and `truncated` fields.
- `open_comment_periods` response: `total_open` is now the API's true
  count; new `scanned`, `scan_cap`, and `returned` fields.
- Docstrings corrected: docket matching described as token-based (not
  substring; 'FAR Case 20' matches nothing while 'FAR Case 2023' matches
  all 2023 cases), legacy document-number formats documented.

### Verified

Every fix carries a live repro in the round 6 regression file
(`tests/test_round_6.py`, offline mocks plus live-gated confirmations).
Post-fix live confirmation: 'E9-12940' fetches, 'FAC 2025-06' returns all
4 documents, `open_comment_periods` surfaces deadlines closing within days
with a truthful government-wide total.

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

182 regression tests (91 offline, 91 live-gated), all passing
against `mcp` 2.0.0 on Python 3.14, with pass counts identical to the pre-migration
baseline on `mcp` 1.x. Server confirmed to boot over stdio and enumerate all
8 tools.

## 0.2.2

Full live-audit pass (rounds 1-4) against the real Federal Register API
surfaced 12 P1 silent-wrong-data paths + 3 P2 validation gaps. All fixed.

### P1 silent-wrong-data
- `search_documents()` called with NO filter args silently returned the
  Federal Register's 10,000-doc "most recent" default as if those were
  search hits. Now raises "requires at least one filter" with a pointer
  to typical filter combinations.
- `term=""`, `term="   "`, `term="x\x00y"`, `term="x\ny"`, `term="x\ty"`,
  `term="x\ry"` all used to silently reach the API and return matches-
  all (10,000) or near-matches-all results. Now every free-text field
  rejects control characters up front and the at-least-one-filter rule
  rejects the empty-term-alone case.
- `agencies=[""]` or `agencies=["", "  "]` used to silently return
  10,000 default results (filter effectively ignored). The 0.2.0
  validator caught `agencies=[]` but not the all-empty-strings list.
  Now `_reject_empty_strings_in_list` catches both.
- Null byte / control chars in `docket_id` and `regulation_id_number`
  silently reached the API.
- Same for `get_public_inspection`'s `agency_filter` / `keyword_filter`
  and `get_facet_counts`'s `term`.
- `_get` had no response-shape guard. None / int / str responses
  passed through and leaked into tool output as type confusion. Now
  `_ensure_json_container` guarantees a dict OR list (the latter is
  needed for `/agencies.json`) and raises a clear RuntimeError
  otherwise.

### P2 validation
- Inconsistent validation across tools: search_documents, get_facet_counts,
  get_public_inspection all gained the same control-char + empty-list
  rejection so typos surface the same way everywhere.

### Testing
- 20 new offline tests covering every round-1 and round-4 finding.
- 10 new live-gated tests (`FR_LIVE_TESTS=1`): real search, compound
  filters narrowing results, get_document round-trip, list_agencies
  count, facet counts, public inspection, far case history, date range,
  concurrent 5-call, and boolean filters.
- 77 tests total (64 offline + 13 live), all passing. 0.2.1 shipped
  with 44. This closes the audit-depth gap with sam-gov / bls-oews /
  gsa-perdiem / regulationsgov.
- Autouse `_reset_client` fixture added for multi-event-loop safety.

### USER_AGENT
- Bumped to `federal-register-mcp/0.2.2`.

## 0.2.1

Cross-MCP fix discovered during the sam-gov-mcp 0.3.1 live audit.

- FastMCP tools register pydantic argument models with the default
  `extra='ignore'` config, so a typo like
  `search_documents(keyword='acquisition')` (real param is `term`)
  silently dropped the typo'd argument and ran with no filter. Now
  every tool has `extra='forbid'` applied after registration, so
  typos raise "Extra inputs are not permitted" before any HTTP call.
- USER_AGENT bumped to `federal-register-mcp/0.2.1`.
- Added regression test covering the new behavior.

## 0.2.0
Hardening release. Fixes 18 bugs across all 8 tools, including a P0 pydantic
crash on `list_agencies` that blocked the tool from ever being called.

### Crash fix
- `list_agencies`: return type declared `dict[str, Any]` but API returned a
  list, causing pydantic validation to crash on every call. Wrapped response in
  `{total_agencies, returned, query, include_detail, agencies}`.

### Silent-wrong-data and runaway payload fixes
- `list_agencies`: full dump was ~700KB. Added `query` filter (case-insensitive
  substring match on name, short_name, slug) and slim-field default
  (id/name/short_name/slug/parent_id). Full detail available via
  `include_detail=True`.
- `get_public_inspection`: added `limit` param (default 50, max 500).
  Previously could return 170KB+ unfiltered.
- `open_comment_periods`: added `limit` param (default 50, max 100).
  Previously hardcoded `per_page=100` returning ~188KB.
- `far_case_history`: requires minimum `docket_id` length of 3. Previously
  `docket_id='x'` returned 65 unrelated docs via 1-char substring match.
- `get_documents_batch`: each document number now validated against
  `YYYY-NNNNN` or `CN-YYYY-NNNNN` regex. Previously empty-string entries
  became `,,` in the URL and returned all 10,000 docs.
- `search_documents`: clamped `term`, `docket_id`, `regulation_id_number`
  length (500/200/50 chars). Previously 10k-char term triggered HTTP 414
  with raw HTML leak.
- `search_documents`: lowered `per_page` cap from 1000 to 100 to stay within
  MCP response size budgets.

### Validation gaps closed
- `search_documents` and `get_facet_counts`: pub/comment/effective date
  ranges validated to `YYYY-MM-DD`, reversed ranges rejected, empty list
  filters (`agencies=[]`, `doc_types=[]`) rejected explicitly.
- `get_facet_counts`: requires at least one filter (previously unfiltered
  queries returned all-time aggregates).
- `search_documents`: whitespace-only `term`/`docket_id`/`regulation_id_number`
  normalize to `None` instead of being sent as `"+++"` filters.
- `get_document` and `get_documents_batch`: document number format validated
  (prevents confusing 404s from `#`, `?`, `&`, `/`, spaces).
- `search_documents` + `get_facet_counts`: `pub_date_gte` before 1994-01-01
  raises with actionable message (FR API has no pre-1994 data).
- `list_agencies`: empty-string and whitespace-only `query` both normalize
  to `None`.
- `get_public_inspection`: `agency_filter=''` / `keyword_filter=''` normalize
  to `None`.

### Error hygiene
- `_format_error` wraps bodies in `_clean_error_body` which strips HTML and
  extracts title/h1 text. Added HTTP 414 handler. Rewrote 404 message to be
  endpoint-agnostic.

### Release automation
- Added `.github/workflows/publish.yml`. Tagging `v*.*.*` triggers test,
  build, and PyPI publish via Trusted Publisher (no tokens).
- `constants.USER_AGENT` bumped to 0.2.0.

### Tests
- New `tests/test_validation.py` with 43 tests, all through the FastMCP
  registry (`mcp.call_tool`). The prior `stress_test.py` awaited raw
  coroutines and bypassed pydantic, which is why the `list_agencies` crash
  shipped in 0.1.x.

## 0.1.0
Initial release.

- 9 MCP tools covering the Federal Register API
- Core: search_documents, get_document, get_documents_batch, get_facet_counts, get_public_inspection, list_agencies
- Workflows: open_comment_periods, far_case_history (with term-search fallback)
- Flexible search conditions: agency, type, term, docket ID, RIN, publication/comment/effective date ranges, correction flag, significance flag
- Public inspection client-side filtering (API does not support server-side)
- Default field set covering the most common document metadata
- Actionable error messages for 404/422/429
- No authentication required
