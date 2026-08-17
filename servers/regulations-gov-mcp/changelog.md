# Changelog

## 1.0.1

Round-7 wave: independent full-source re-audit with live verification. 12
findings fixed.

### Fixed

- **open_comment_periods no longer drops the soonest-closing documents.**
  It sorted by deadline DESCENDING and truncated at one page of 50, so the
  documents closing soonest (the tool's entire purpose) were silently
  discarded while evergreen 2050 notices were kept. Live proof: FDA had 71
  open documents and the ones closing in 2 days were among the missing.
  Now: ascending commentEndDate, one comma-joined query for all agencies
  (8 round-trips became 1), page size 250, API-true total_open, a
  truncated flag noting omitted documents all close later, and undated
  documents listed last instead of dropped.
- `within_comment_period=False` is rejected locally with real guidance:
  the API accepts only true (false returns HTTP 400), and the old error
  handler misdiagnosed the 400 as a casing problem.
- Page cap raised from 20 to the live-verified 40 (the API's own 400
  names 40 as max; page 21 returns data), doubling reachable records per
  query to 10,000. Three stale "~5,000 / 20 pages" strings corrected.
- Comma-separated multi-field sorts accepted (the API's own deep
  pagination recipe needs sort=lastModifiedDate,documentId) and
  comma-separated multi-agency filters accepted (filter[agencyId]=FAR,GSA
  is the documented form, verified live).
- far_case_history follows pagination up to 1,000 documents and flags
  truncation beyond, instead of silently returning the first 250 of a
  553-document docket while claiming "all documents".
- Empty-string docket_id and comment_on_id now raise instead of silently
  dropping the filter and searching the entire corpus: the exact class
  the 0.2.0 agency_id headline fix left open elsewhere.
- comment_on_id rejects documentId-shaped values with directions to the
  hex objectId (attributes.objectId): the API silently returns 0 comments
  for documentIds, the number-one cause of falsely-empty comment
  searches. The no-data hint now includes comment_on_id.
- DEMO_KEY rate limit standardized on the live-measured 10/hr (code said
  40, smithery.yaml said 30/hr + 50/day).
- readme links testing.md (the TESTING.md link 404'd on GitHub);
  changelog 0.1.0 "9 MCP tools" corrected to 8; dead `_clamp_str_len`
  and unused constant imports removed; `serverInfo.version` populated
  from the package version.

### Testing

- `tests/test_audit_r7.py`: 20 offline regressions plus 4 live
  confirmations (multi-agency comma filter, page 21 reachable,
  multi-field sort accepted, open_comment_periods soonest-first against
  live FDA data).
- testing.md documents the round-7 wave and corrects the prior record
  (wrong live-gate env var, phantom stress_test_r3.py, phantom
  known-agency-list and header-inspection claims, the false 20-page cap).

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

177 regression tests (65 offline, 112 live-gated), all passing
against `mcp` 2.0.0 on Python 3.14, with pass counts identical to the pre-migration
baseline on `mcp` 1.x. Server confirmed to boot over stdio and enumerate all
8 tools.

## 0.2.0

First hardening pass. Live audit with a real api.data.gov key surfaced
22 findings: 1 P0, 10 P1, 7 P2, 4 P3. All fixed.

### P0: unknown-param silent-drop (cross-fix)
- FastMCP tools register pydantic arg models with `extra='ignore'` by
  default, so a typo like `search_documents(keyword='audit')` (real
  param is `search_term`) succeeded with the typo silently discarded
  and ran with no filter. This is the same bug found during the
  sam-gov-mcp 0.3.1 live audit and patched across every other MCP.
  Now every tool has `extra='forbid'` applied after registration.

### P1 silent-wrong-data fixes
- `agency_id=""` returned **all 1,951,938 Regulations.gov documents**.
  The empty string was treated as "no filter." Now explicitly rejected
  with an error pointing out the surprise behavior.
- Unknown agency IDs (`"ZZZ"`, `"FAR DOD"`) silently returned 0 results
  with no warning. Now rejected by format validation, and agencies that
  do make it through but return 0 get a `no_data: true` +
  `no_data_reason` flag.
- Null byte and other control characters in `search_term` were passed
  through to the API. Now rejected up front.
- `<script>` in `search_term` triggered the WAF with HTTP 403, but
  the server reported "API key rejected" -- misleading auth error.
  403 handler now inspects the body to distinguish WAF blocks from
  auth failures.
- Date ranges where `ge > le` silently returned 0. Now rejected with
  "ge bound must be <= le bound."
- Dates in ISO 8601 (`2025-01-01T00:00:00Z`), slash format
  (`2025/01/01`), and invalid calendars (`2025-02-30`) reached the
  API as 400s. Now pre-validated with a real calendar check.
- `last_modified_date` quirk (`YYYY-MM-DD HH:MM:SS` space-separated)
  pre-validated so typos surface locally.
- `document_id` / `docket_id` / `comment_id` with slashes produced
  HTTP 500 or 301 redirects from the API. Now rejected up front.
- Sort fields pre-validated against known whitelists per tool
  (documents, comments, dockets) instead of round-tripping to 400.
- `_get` now defends against None / non-dict API responses and
  JSON-decode failures (ports the helper set from bls-oews / ecfr).

### P2 validation
- `page_size` now also rejects bools and non-int values up front.
- `page_number` bounds enforced locally (1-20; API caps total results
  around 5,000 = 20 pages at page_size=250).
- `search_term` length-clamped to 500 chars.
- `open_comment_periods(agency_ids=[])` rejected instead of silently
  falling through to the default list.
- `agency_ids` list pre-validated per-element.
- `_clean_error_body` strips HTML title/h1 from upstream error bodies
  instead of dumping raw HTML into the error message.

### Release automation
- Added `.github/workflows/publish.yml` for PyPI via Trusted Publisher
  on tag `v*.*.*`. Matches the pattern on the other 7 shipped MCPs.
- Added `[dependency-groups].dev` with pytest + pytest-asyncio.
- USER_AGENT bumped to `regulationsgov-mcp/0.2.0`.

### Round 3 enhancement: paged-past-end differentiation
- A subsequent deep-stress live round (40+ probes) found that callers
  who paginate past the last page (e.g. `page_number=20` at
  `page_size=250` against a 2,152-record collection) got an empty
  `data: []` with no flag. Now emits `paged_past_end: true` + a
  `paged_past_end_reason` that tells the caller exactly which page was
  the last with data. The `no_data` flag continues to fire only when
  `totalElements` is 0 (truly no matches).

### Testing
- `tests/test_validation.py` with 51 tests (46 offline + 5 live gated
  by `REGULATIONS_LIVE_TESTS=1`). Covers every validator, all response-
  shape defense paths, the paged-past-end vs no-data differentiation,
  and regression tests for every round-1 and round-3 finding.
- The older `stress_test.py` awaited raw coroutines and bypassed
  pydantic, which is why the 0.1.1 release looked clean. Kept for
  reference, not run by CI.

## 0.1.0
Initial release.

- 8 MCP tools covering the Regulations.gov API (documents, comments,
  dockets; the original entry claimed 9, but the server has always
  exposed 8)
- Core: search_documents, get_document_detail, search_comments, get_comment_detail, search_dockets, get_docket_detail
- Workflows: open_comment_periods (multi-agency scan), far_case_history (docket + all documents)
- Page size validation (5-250 range enforced client-side)
- Case-sensitive filter value documentation in tool descriptions
- Date format asymmetry documented (postedDate vs lastModifiedDate)
- Aggregations always present in search responses for quick counts
- Actionable error messages for 400/403/404/429
- Falls back to DEMO_KEY when no API key configured
