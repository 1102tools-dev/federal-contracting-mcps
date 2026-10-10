# USASpending.gov MCP: Testing Record

## Executive Summary

This Model Context Protocol server exposes the USASpending.gov REST API as 55 callable tools for federal contract, award, subaward, recipient, agency, and federal account research. It was hardened across seventeen audit rounds: the eleventh was a ~95-call paced live campaign, the twelfth was the October 2026 content campaign, the thirteenth was the full end-to-end audit and description follow-up, and the fourteenth was the fresh ordinary/power-user Round 2 audit, and the fifteenth was the new Round 3 content audit; the sixteenth was the new Round 4 content audit; the seventeenth is the new Round 5 content audit. v0.3 (round 9) tripled the API surface from 17 to 55 tools, adding FFATA subawards, recipient profile/children, agency depth (sub-agencies, federal accounts, object classes, program activities, obligations by award category), award detail rollups, transaction-level and geographic search, IDV depth, autocomplete helpers, reference data, and Treasury federal accounts. Round 10 (1.0.1) was a two-family semantic live audit that found 22 verified defects rounds 1-9 had missed, including one tool that had never worked at all; the methodology change behind it is documented in the Round 10 section. The current 1.0.21 candidate source collects 2,315 regression cases (1,936 offline and 379 live-gated). Its measured frozen MCP SDK 2.0.0 offline lane passed 1,936 and skipped 379; collection does not execute those live tests. Actual published-package and hosted acceptance are separate records. Published 1.0.20 completed all 150 available Round 4 questions on actual installed CLI and public requests, with all55 tool definitions matched and six guided followups passed. Its separate fresh/latestSDK2.3 full regression execution measured 1,078 passed, 855 failed and 379 skipped; these failures are retained exception/message expectations and are not credited as passing.

| Metric | Value |
|---|---|
| MCP tools exposed | 55 |
| Total regression tests | 2,315 (1,936 offline, 379 live-gated) |
| Collected cases per tool | 42.09 (not a coverage percentage) |
| Server content audits completed | 17 (Round 5 candidate publication pending) |
| Initial integration issues (round 1) | 28+ |
| P1 silent-wrong-data bugs found and fixed | 11 (rounds 1-9) |
| P2 validation gaps found and fixed | 7 (rounds 1-9) |
| Round 7 deep live audit findings | 0 |
| Round 8 Hypothesis property tests findings | 0 |
| Round 9 (v0.3) live audit findings | 1 (list_states JSON-array response shape) |
| Round 10 (1.0.1) semantic audit findings | 22 (12 search family, 10 entity family), all fixed |
| Historical release cycles through 1.0.3 | 15 (v0.1.2 through v1.0.3) |
| Current source package | 1.0.21 candidate; 1.0.20 published |
| PyPI status | Published as `usaspending-gov-mcp`, auto-publishes via Trusted Publisher on tag push |

## 1.0.3 Safety Release Verification

The complete offline suite passed 1,785 tests with 375 live tests gated. All
four upstream request paths are centrally paced. Shared tests verified
cross-process serialization, keyless-service protection, invalid overrides,
and `Retry-After` behavior. No federal API was called.

## Round 11 (2026-08-18): paced live campaign, zero new defects

Ninety-five serialized production calls at ~1 s spacing (harness pattern from
sam-gov-mcp round 10; USASpending needed no key and never throttled once,
consistent with its source code shipping no DRF throttle configuration at
all). Every round-10 fix was re-stamped against live data and every boundary,
differential, and partition probe came back clean. This is the first round in
this server's history to find nothing to fix; the round-10 semantic audit
appears to have caught the tail.

Re-stamped live: recipient_children returns 217 children for the sample UEI
(the tool that had never worked before 1.0.1); recipient_search_text routes
UEIs correctly; the docstring Navy example returns rows; F001/F002 FABS codes
are valid award_type_codes (8,542 F-code awards in FY24 alone, 624,664 for
the grants group as the server sends it); sub_agency's sort enum matches the
API's own valid-values list exactly; uppercase recipient hashes are accepted;
new_awards_over_time still 422s without recipient_id upstream.

Verified clean: 1-based page semantics (page 2 at limit 2 returns records
3-4, proven by fingerprint); past-the-end pages are HONEST (empty or absent
results, hasNext=false), in direct contrast to SAM.gov Opportunities' phantom
rows; monthly spending_over_time buckets partition the fiscal-year total to
the cent; sort order differentials actually reorder; agency/NAICS/geography
filters narrow; every boundary probed fails loud (limit=0/101 and page=0
return 422, bogus sort and award codes return 400 with the valid values
enumerated, malformed dates 400, bad toptier 404).

Intel recorded, no code change needed: the search family enforces an
upstream 2007-10-01 earliest date (422 below it, advisory `messages` above
it, and search tools pass responses through raw so those advisories reach
the caller, now pinned by test); responses already stamp
`spending_level: "awards"` while the server still sends the to-be-superseded
`subawards: false` flag, so the deprecation posture is pinned by test until a
deliberate migration; agency overview endpoints can take 20+ seconds against
the client's 30 s timeout; the full-field limit=100 search response measured
~72 KB, under the ~95 KB concern threshold; the API follows raw path
traversal at the HTTP layer (`awards/../references/` returns the agency
list), confirming the round-10 client-side metacharacter rejection is the
only real defense.

New: `tests/test_audit_r11.py` (2 offline pins + 7 live_smoke contract
anchors), suite-wide live pacing via `tests/conftest.py`, scenario scripts
moved to `tests/scenarios/`, and this file's rate-limit unknown resolved.

## Round 10 (1.0.1): two-family semantic live audit

Two agents audited the full 55-tool surface in parallel against the production API (2026-08-16, Claude Fable 5): one owned the search/spending/autocomplete family, the other the entity/agency/award/reference family. Roughly 100 live probes ran through `mcp.call_tool` (the real client pipeline, pydantic validation included). 22 findings were verified with reproductions and fixed in 1.0.1: 12 in the search family (5 high, 5 medium, 2 low) plus 3 blind-spot follow-ups, and 10 in the entity family (1 high, 2 medium, 2 medium-low, 5 low).

### The methodology lesson

Rounds 1-9 asserted transport success (HTTP 200, dict-shaped response) and validator self-consistency (Hypothesis property tests, ~25,000 random probes). Round 10 asserted parameter SEMANTICS, and that distinction is what surfaced 22 defects in a suite that had just passed 2,076 tests:

- **A zero-result response is not a passing test.** Two search filters could NEVER return data (recipient_uei sent as the API's hash-keyed recipient_id; military departments passed at tier=toptier). Prior rounds recorded "compound filters returning zero" as success. Round 10 root-caused every zero.
- **A 200 with rows is not proof a parameter works.** get_idv_activity's sort/order were silently ignored by the API: opposite sort directions returned byte-identical results. Detecting ignored parameters requires differential probes (flip one parameter, demand a difference), which no prior round ran.
- **A validator can be perfectly self-consistent and wrong.** get_recipient_children validated hashes the API always rejects while rejecting the UEI/DUNS the API requires, so the tool had never once succeeded; property tests certified the validator against its own spec, not the API's contract. Same class: the lowercase-only hash regex rejected uppercase hashes the API accepts, and the fiscal-year ceiling admitted a year the API always 422s.
- **Enum members must be swept against the live API.** get_agency_sub_agencies advertised sort="total_outlays"; the API 400s it. One representative value per parameter was not enough.
- **Hardcoded code tables drift.** AWARD_TYPE_GROUPS was missing all ten FABS F-codes, silently excluding real awards from every group search. Reference tables are now diffed against the live reference endpoints.
- **Docstring examples must be executed as written.** The search_awards docstring's own Navy example returned zero results.
- **Error translation must be re-audited when the surface grows.** The 404 hint written in the 17-tool era told federal-account callers to verify a generated_internal_id.
- **Path-interpolated inputs need metacharacter rejection, not just control-character rejection.** '../references/toptier_agencies' walked get_award_detail onto the agency list endpoint. Round 2 had hardened these ids against null bytes but never URL metacharacters.

### Fixes landed in 1.0.1

See changelog.md for the complete list. Headlines: get_recipient_children rekeyed to uei_or_duns (it had never worked: the endpoint 400s on hashes and returns a JSON array the dict-only guard would have rejected anyway), dead sort/order removed from get_idv_activity with the real hide_edge_cases exposed, FABS F-codes added to every award-type group, recipient_uei routed through recipient_search_text, case-sensitive code filters uppercased, no-filter guards on spending_by_category and spending_by_geography, path-metacharacter rejection on every path-interpolated id, one toptier normalizer across all eight agency tools, and 404 hints conditioned on the request path.

New regression files: `tests/test_search_family_fixes.py` (29 offline + 8 live-gated) and `tests/test_entity_family_fixes.py` (59 offline + 4 live-gated). Pre-existing tests that encoded the broken behaviors were rewritten to assert the fixed behavior, each carrying a comment naming the round 10 change. Suite after the round: 1,783 offline + 368 live-gated, all green.

## Round 9 (v0.3.0): API surface expansion

Tripled the tool count from 17 to 55. Added 38 new tools across nine endpoint groups: subawards (FFATA), recipient depth, agency depth, award detail rollups, transaction/geography/timeline search, IDV depth, autocomplete helpers, reference data, federal accounts.

### Per-group test breakdown (243 new tests in v0.3)

| Group | Tools | Validation | Mock | Live |
|---|---|---|---|---|
| Subawards | 2 | 9 | 4 | 5 |
| Recipients | 5 | 14 | 6 | 8 |
| Agency depth | 6 | 26 | 7 | 14 |
| Award detail | 5 | 12 | 6 | 5 |
| Search depth | 3 | 11 | 3 | 5 |
| IDV depth | 4 | 18 | 4 | 4 |
| Autocomplete | 4 | 16 | 4 | 11 |
| Reference data | 4 | 3 | 4 | 4 |
| Federal accounts | 5 | 12 | 8 | 3 |
| Stress / connection reuse | - | - | - | 13 |
| **v0.3 totals** | **38** | **121** | **46** | **76** |

### P1 bug found in live audit

**`list_states` returned a JSON array but the MCP's `_ensure_dict_response` helper rejected non-dict responses with a clear error.** The endpoint at `/api/v2/recipient/state/` is the only USASpending endpoint in the surface that returns a top-level array. Fixed by special-casing the tool to wrap the array in `{"results": [...], "total": N}`. Without live testing this would have shipped as a guaranteed runtime error every time someone called the tool.

### Endpoint quirks baked in

- `new_awards_over_time` REQUIRES `recipient_id` in filters; the API returns HTTP 422 if omitted. Validator rejects calls without it pre-network with a clearer error.
- Recipient hashes are UUIDs with `-C` (children), `-R` (regular), or `-P` (parent) suffix. Bare UEIs are not valid; `_validate_recipient_hash` rejects them before network.
- Generated award IDs use specific prefixes: `CONT_AWD_` (contract), `CONT_IDV_` (IDV), `ASST_NON_` (assistance non-aggregated), `ASST_AGG_` (assistance aggregated). IDV-specific tools further require `CONT_IDV_` prefix.
- Treasury account symbols are alphanumeric/hyphen (e.g. `097-0100`). Validator rejects special characters.
- Toptier agency codes are 3-4 numeric digits (e.g. `097` for DoD, `075` for HHS). Validator rejects DoD/HHS strings or shorter codes.

### Live tests cover

Department lookups for DoD (097), HHS (075), Treasury (020); recipient-hash chains using real hashes pulled from search results; IDV chain (search → amounts → funding → activity → funding_rollup); pagination consistency for subawards, recipients, sub-agencies; concurrent calls across mixed endpoints (asyncio.gather); autocomplete sanity for awarding/funding agencies, CFDA, glossary, recipient (Lockheed, Boeing); reference data shape (award_types canonical mapping, def_codes list non-empty, glossary paginated); federal account chain (list → detail).

## What Was Tested

Rounds 1-8 covered the original 17-tool surface end-to-end (the v0.3 expansion to 55 tools and its round 9 audit are described above).

**Search and aggregation:** `search_awards`, `get_award_count`, `spending_over_time`, `spending_by_category`

**Award detail:** `get_award_detail`, `get_transactions`, `get_award_funding`, `get_idv_children`

**Workflow convenience:** `lookup_piid` (auto-detects contract vs IDV)

**Autocomplete:** `autocomplete_psc`, `autocomplete_naics`

**Reference:** `list_toptier_agencies`, `get_agency_overview`, `get_agency_awards`, `get_naics_details`, `get_psc_filter_tree`, `get_state_profile`

Each tool was exercised for argument validation, input sanitization, response-shape guarantees, error translation, pagination edge cases, and real-world data handling against the live production API.

## How It Was Tested

### Testing discipline

Prior unit tests in v0.1.x awaited raw coroutines directly, which bypassed the FastMCP tool pipeline and its pydantic validation layer. This skipped whole categories of bugs. The hardening program switched to invoking tools through `mcp.call_tool(name, kwargs)` the way a real MCP client does. That change alone surfaced more than 28 integration issues invisible to the prior test suite.

### Audit rounds

| Round | Scope | Probe count | Finding class |
|---|---|---|---|
| 1 | Integration stress through real MCP client | 83 live probes across all 17 tools | 28+ integration issues |
| 2 | Targeted live probes on edge cases (null bytes, negative amounts, empty-string arrays, whitespace IDs, retired NAICS codes, reversed date ranges) | 49 probes | 9 P1 silent-wrong-data, 4 P2 validation |
| 3 | Deep live stress (compound filters, pagination boundaries at page 200 and 201, leap-year dates, 10-year spans, amount boundaries, unicode, agency name variations, 5 concurrent calls) | 52 probes | 1 additional P1: `search_awards()` with no filter arguments silently returned 25 unfiltered recent contracts |
| 4 | Response-shape mock fuzzing (None, bare list, int, string where a dict was expected) | 15 probes | Response-shape guard gap |
| 5 | Density expansion: 415 new parameterized tests across 19 failure-mode buckets covering every input field on every tool | 415 tests | No new bugs; coverage lifted from 3.6 to 28.1 tests per tool |

### Live audit status

All four rounds included live calls against the production USASpending.gov API. The repository includes 10 live-gated regression tests executable via `USASPENDING_LIVE_TESTS=1 pytest` covering real search with real results, compound filters, leap-year dates, exact-match amount ranges, autocomplete returns, state profile, concurrent searches, unicode keyword handling, and toptier-agency listing.

## Issues Found and Fixed

### Priority 1: Silent wrong-data bugs

These are the most dangerous class: the tool returned data, but the data was wrong or unfiltered in a way the caller could not detect. All ten were found across rounds 1 through 3 and fixed in v0.2.0, v0.2.1, and v0.2.2.

| Issue | Fix |
|---|---|
| `search_awards()` with no filter arguments silently returned 25 unfiltered recent contracts (same failure-mode category as regulations.gov-mcp's `agency_id=""` returning all 1.95 million records) | Raises "at least one filter beyond award_type" with pointer to typical filter combinations |
| Null byte, newline, tab in `keywords` silently accepted or produced upstream 500s | All free-text fields reject control characters up front |
| Null byte in autocomplete `search_text` produced upstream 500s | Rejected locally before HTTP call |
| Null byte in `generated_award_id` / `generated_idv_id` produced upstream 500s | Rejected locally on all detail tools |
| Negative `award_amount_min` / `award_amount_max` silently ignored by USASpending, returning default 25 results | Rejected with explanatory error |
| Lists of empty strings (`naics_codes=[""]`, `psc_codes=[""]`, `award_ids=[""]`) silently dropped to empty, applying no filter | Rejected with "contains only empty / whitespace strings" error |
| Empty or whitespace-only `generated_award_id` round-tripped to cryptic 422 or 404 | Rejected up front with pointer to `search_awards` for valid IDs |
| Pydantic `extra='ignore'` default let typos like `keyword='cyber'` (real param is `search_text`) silently drop the typo'd argument and return unfiltered results | Every tool now applies `extra='forbid'` to its pydantic arg model; typos raise "Extra inputs are not permitted" before any HTTP call |
| Empty filters on `get_award_count` and `spending_over_time` forwarded to the API which then 400'd | Raises `ValueError` locally with filter guidance |
| Short autocomplete queries returned arbitrary first-N alphabetical records (e.g. "R" returning 10 unrelated GUN PSCs, "x" matching substring inside "(except potato)") | Minimum 2-character query enforced; retired NAICS codes filtered by default via `exclude_retired=True` |

### Priority 2: Validation gaps

| Issue | Fix |
|---|---|
| `limit` unbounded on search, autocomplete, and convenience tools | Bounded to API caps (100 for search endpoints, 5000 for transactions) |
| `page` parameter unbounded (accepted 0, negative) | Required `>= 1` across all paginated tools |
| Date parameters accepted ISO 8601 datetimes, slash-separated, reversed ranges | Validated as `YYYY-MM-DD`, reversed ranges raise actionable error |
| `award_amount_min > award_amount_max` silently returned zero results | Raises with clear error message |
| `autocomplete_psc` and `autocomplete_naics` long queries triggered upstream 500s | Capped at 200 characters |

### Response-shape defense

The `_post` and `_get` helpers now guarantee a dict return via `_ensure_dict_response`. USASpending always returns JSON objects for the endpoints this MCP uses. Anything else (None, bare list, int, string) is a CDN or proxy issue that previously leaked into tool output as a type confusion error. It now surfaces clearly as "USASpending returned an empty body at {path}" or "unexpected {type} at {path}".

## Test Coverage

The repo ships 477 regression tests across five files (467 offline + 10 live-gated). All pass on every release cycle.

| File | Purpose | Test count |
|---|---|---|
| `tests/test_validation.py` | Rounds 1-4 plus live-gated integration tests covering every documented finding | 62 (52 offline + 10 live-gated) |
| `tests/test_density_r5.py` | Round 5 density expansion. Parameterized tests across 19 failure-mode buckets. Every date-taking parameter on every search tool, every paginated tool's limit/page boundaries, every text input's control-character safety, every tool's `extra='forbid'` enforcement, all toptier code normalization paths, all fiscal year boundaries, plus direct unit tests on validator helpers | 415 (415 offline) |
| `tests/stress_test.py` | Round 1 stress test scenarios (retained for reproducibility) | N/A (scenario script) |
| `tests/stress_test_r2.py` | Round 2 live-audit scenarios (retained for reproducibility) | N/A (scenario script) |
| `tests/stress_test_r3.py` | Round 3 deep live stress scenarios (retained for reproducibility) | N/A (scenario script) |

Regression tests invoke tools through the FastMCP registry (`mcp.call_tool`) rather than awaiting decorated coroutines directly. This catches bugs in the tool pipeline that raw-coroutine tests miss. An autouse fixture resets `srv._client` between tests so the shared httpx client does not leak across event loops, preventing flaky test results from async state carryover.

## Release History

| Version | Focus | Regression test count |
|---|---|---|
| 0.1.2 | Initial release: 17 tools with basic unit tests | Basic coverage |
| 0.2.0 | Integration stress testing through real MCP client surfaced 28+ integration issues; added comprehensive input validation, bounds checking, and error hygiene | Expanded offline + integration suite |
| 0.2.1 | Cross-MCP fix discovered during sam-gov-mcp audit: pydantic `extra='forbid'` applied to all tool arg models to prevent typo'd-parameter silent filter-drop bugs | +1 regression test |
| 0.2.2 | Live audit surfaced 9 P1 silent-wrong-data paths and 4 P2 validation gaps; all fixed | 46 total (+17 regressions) |
| 0.2.3 | Round 3 deep live stress and round 4 response-shape mock fuzz; added the `search_awards()` no-filter guard and `_ensure_dict_response` guarantee; live-gated regression suite | 62 total (+16 regressions) |
| 0.2.6 | Tool annotations and per-server repository URLs | No code changes affecting tool behavior |
| 0.2.7 | Round 5 density expansion: 415 new tests across 19 failure-mode buckets | 477 total (+415 regressions); 3.6 → 28.1 tests per tool |
| 0.2.8 | Round 6 live audit: 157 new live-gated tests covering every tool against production USASpending API | 634 total (+157 regressions); 28.1 → 37.3 tests per tool. 2 P2 bugs found and fixed: get_psc_filter_tree trailing-slash 301 redirect; list[str] int coercion mismatch on naics_codes/psc_codes/etc across 4 tools. |
| 0.2.9 | Round 7 deep live audit: 104 new live-gated tests targeting round-6 gaps (detail tool chaining with real IDs, IDV all 3 child_types, loans, sort/order variations, deep PSC tree, compound filters returning zero, pagination at depth, real prime+agency combos, all 6 award_types) | 738 total (+104 regressions); 37.3 → 43.4 tests per tool. Zero new bugs found. |
| 0.2.10 | Round 8 Hypothesis-driven property test suite + 10 bonus live tests: 69 new test functions running ~25,000 random probes through every validator (date, clamp, code lists, control chars, toptier normalization, fiscal year, dict response, error body cleaning, strings list); plus async concurrency stress, encoding edge cases (unicode normalization, RTL, BOM, ZWSP, emoji), composite tool deep tests | 807 total (+69 regressions); 43.4 → 47.5 tests per tool. Zero new bugs found - validators clean across the full random input space. |
| 0.3.0 | Round 9 surface expansion: 17 → 55 tools across nine endpoint groups, with live audit. 1 P1 fixed (list_states JSON-array response shape) | 1,050 total (+243) |
| 0.3.1 | Mock density expansion for the v0.3 tools: 20 cross-cutting parametrized batteries x 38 tools plus 30 focused list_states mocks | 2,076 total (1,720 offline + 356 live-gated) |
| 1.0.0 | MCP Python SDK v2 migration (FastMCP → MCPServer), bounded `mcp>=2.0.0,<3` requirement, .mcpb bundles discontinued | 2,076 total, pass counts identical to the 1.x baseline |
| 1.0.1 | Round 10 two-family semantic live audit: 22 verified findings fixed (see the Round 10 section), uv.lock caught up to the bounded mcp requirement | 2,151 total (1,783 offline + 368 live-gated) |

## Cross-MCP Context

This MCP is one of eight servers in the 1102tools federal-contracting MCP suite (`bls-oews-mcp`, `ecfr-mcp`, `federal-register-mcp`, `gsa-calc-mcp`, `gsa-perdiem-mcp`, `regulationsgov-mcp`, `sam-gov-mcp`, and this one). All eight were hardened under the same playbook. Several fixes here originated in another MCP's audit and propagated across the suite:

- **`extra='forbid'` on pydantic arg models** was discovered during the sam-gov-mcp 0.3.1 audit after a typo'd parameter silently returned an unfiltered default. Applied here in 0.2.1 and to every other MCP in the suite.
- **No-filter guard on search tools** (the `search_awards()` fix) used the same pattern as the regulationsgov-mcp fix for `agency_id=""` returning all 1.95 million records. Same failure mode, same fix shape.
- **Response-shape guarantees** via `_ensure_dict_response` use the same defensive-parsing pattern applied across gsa-perdiem-mcp, bls-oews-mcp, and others where upstream APIs occasionally return non-JSON or shape-shifted responses.

## What Was Not Tested

- **Rate-limit behavior.** USASpending documents no numeric limit. Every request now uses a provisional 3-second cross-process gate and honors `Retry-After` without automatic retries. This is a 1102tools anti-burst safeguard, not a provider requirement.
- **Historical API changes.** Tests validate behavior against the current USASpending API. Breaking changes to the upstream API (field renames, endpoint deprecations) are not caught by offline tests. Live-gated tests will catch them but must be run manually with `USASPENDING_LIVE_TESTS=1`.
- **Payload size limits beyond `limit` capping.** Response sizes over ~95KB are theoretically possible on some endpoints if the caller accepts the default shape. The MCP does not enforce an overall payload size ceiling.
- **Pending API deprecation.** USASpending has signaled that `subawards` award type will be superseded by a `spending_level` parameter. The MCP does not yet expose `spending_level`. When upstream fully deprecates, grants queries may need an adjustment.

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root and can be re-executed by anyone. The live suite runs with `USASPENDING_LIVE_TESTS=1 pytest` and requires no API key (USASpending is a free, public API).

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 (1M context, max effort, Claude Max 20x subscription) through round 9, and Claude Fable 5 for the round 10 two-family semantic audit.

Testing spanned ten rounds from integration stress testing through live API audits, response-shape guards, property testing, and the round 10 semantic audit (parameter effects, enum sweeps, contract-vs-validator diffs). The live regression suite runs against the USASpending.gov production API when enabled with `USASPENDING_LIVE_TESTS=1`.

Test count: 2,163 regression tests (1,788 offline + 375 live-gated) across 55 tools. Tests per tool: 39+. P1 bugs found and fixed rounds 1-9: 11. P2 validation gaps closed rounds 1-9: 7. Round 10 findings fixed: 22. Integration issues closed in round 1: 28+. Release cycles: 16. Current version: 1.0.4. PyPI: `usaspending-gov-mcp`.

Source: github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/usaspending-gov-mcp. License: MIT.

## RC5 pacing and tool-profile remediation (2026-08-22)

Version 1.0.4 carries the suite-wide asynchronous pacing-lock correction and the `acquisition-agent` tool profile. The full offline lane passed (1,788 tests; 375 live-gated tests skipped). Isolated published-wheel verification confirmed the standalone default still exposes all 55 tools and the acquisition profile exposes the documented 20-tool allowlist.


## Round 12: 1.0.13 content correction verification (2026-10-10)

The October content campaign found wrong default fiscal years, PIID keyword
lookup masquerading as an exact lookup, missing date modes, missing DoD lag
caveats and incorrect grouped-subaward pagination. Release 1.0.13 corrects
these paths and adds recipient/File C caveats and aggregate filters.

The full Python suite passes 1,880 cases with 379 live-gated skips; the focused content suite passes 71 offline
cases with four live tests gated. Running the focused tests against the
pre-fix c5293fc source demonstrates failures for changed behavior. Worker
TypeScript checks, all 55 hosted tool contracts, nine package version
checks and 64 release guards pass.

A separate source gate repeats 16 content repros against the actual public
API, comparing raw upstream amounts/results with each tool answer, and
checks four descriptions for scope guidance. The source gate passed on
2026-10-10. It includes FY defaults, exact/ambiguous PIIDs, new-award count,
grouped-subaward next-page probing, DoD monthly totals, sole-source/recipient/
funding-agency and pricing filters, Leidos recipient overlap, and both
Booz Allen and Electric Boat File C amounts.

Deferred part of P3 U13: vehicle/parent-IDV totals filtered by fiscal action
date and ordering agency. Upstream search has no equivalent parent filter.
Filtering paginated IDV children by award start dates would not establish
transaction obligations in a fiscal window and would risk silently incomplete
totals. The existing child/activity tools remain available, with reporting-gap
and keyword-completeness guidance. All other U1-U13 items are addressed.

Peer review caught a mixed-role DoD caveat gap: a non-DoD funding filter
could suppress the warning for DoD-awarded contracts (and vice versa).
Either agency role naming DoD now retains the caveat. Eight focused
regressions fail on the previous implementation and pass with the fix.


## Round 13: full end-to-end audit (1.0.14, 2026-10-10)

The source MCP ran 73 realistic question/argument scenarios covering every
one of the 55 tools against the public USAspending API. Coverage includes
all six award categories; exact, ambiguous, fuzzy and nonexistent PIIDs;
award-to-transaction/File C/subaward drilldowns; all three IDV child modes;
agency/program/account structure; time, category and geography aggregation;
recipient parent/child chains; references and all autocomplete tools. Raw
API responses and MCP results were retained separately and compared: every
original upstream field survived unchanged in single-request tools.

The current release still omitted procurement-delay guidance on geography,
transaction, state and new-award timeline results. The official About the
Data disclosure also covers USACE; the previous helper covered only DoD.
File C rollups and IDV amount/funding summaries now explain partial coverage,
and the submission-period answer clarifies that calendar deadlines do not
prove agencies submitted complete data. New-award timelines label fiscal
months/quarters and partial windows. Tool metadata remains unchanged.

The new 36-case offline suite gives 29 failures and seven unaffected passes
against 1.0.13, and 36 passes against the correction. The complete Python
lane passes **1,916 cases, with 379 live-gated skips (2,295 collected)**.
Those skipped cases were not executed by the offline lane; the separately
recorded live campaign is the end-to-end evidence. The source contract check
confirms all 55 tool definitions still match the published baseline. Nine
package version surfaces pass validation, and the 1.0.14 wheel and source
distribution build successfully.

A DoD subagency request with limit=3 returns about 113 KB because the three
subagencies contain all contracting-office children. This is a response-size
enhancement opportunity rather than an incorrect total; no children were
silently discarded. Parent-IDV transaction-window filtering remains an
upstream capability limitation described in Round 12.


## Round 13 description follow-up (1.0.15, 2026-10-10)

Explicit user direction authorized correcting the two remaining descriptions
within the existing server identity. The `get_idv_funding` description now
explains File C association/partial coverage and routes full child-order
questions to the appropriate tools. `get_submission_periods` now describes
global reporting-calendar deadlines and rejects their interpretation as
agency-completion evidence. The established Python 3.12 baseline generator
changes exactly those two description fields; all 55 names, schemas,
annotations and other metadata remain identical. Current [official OpenAI documentation](https://developers.openai.com/plugins/deploy/app-review#how-published-mcp-metadata-versions-work)
uses continuous review for published tool-definition updates: passing updates
replace the previous definitions automatically, without a new plugin version
or manual republication. Previous definitions remain live while automated
checks are pending, so the unchanged names/schemas preserve compatibility.
Internal peer review found no blocker.

Two actual tools/list regressions fail against 1.0.14 and pass corrected.
The full Python lane passes **1,918 cases with 379 live-gated skips (2,297
collected)**. Source55-tool contract and nine-package version checks pass.
Version 1.0.15 leaves the already in-flight 1.0.14 immutable; root coordinates
the serial follow-up release and actual published verification.


## Round 14: fresh ordinary and power-user content audit (1.0.16, 2026-10-10)

A fresh published 1.0.15/public campaign exercised **127 questions across all
55 tools**, with real follow-ups and official API response capture. The scope
covered DHS software-market discovery and continuation; all six award types;
assistance detail and modifications; discovered GSA vehicle hierarchies; HHS
agency/resource/program/account analysis; every category dimension; time and
geography comparisons; FFATA prime/recipient chains; Lockheed parent and child
identifiers; references; and FEMA account drilldowns. All **126 successful
answers matched the fresh official-API-backed installed package**. The one
failed follow-up exposed the recipient-guidance finding below. Transport and
source equality alone did not certify semantic correctness: the annual timeline
still had the wrong fiscal-year interpretation.

Two new findings were confirmed and corrected:

- **P2 annual new-award grouping:** an FY2025 Lockheed request returned 5,911
  under `2024` and 18,081 under `2025`, while the prior 1.0.14+ note asserted
  federal fiscal buckets. The [official endpoint implementation](https://github.com/fedspendingtransparency/usaspending-api/blob/03b9e2554837998c4c261c65e2947dc79f23855a/usaspending_api/search/v2/views/new_awards_over_time.py)
  uses a calendar-year histogram for annual grouping. Fiscal quarter/month
  samples both total 23,992 under FY2025. Annual answers now sum the correctly
  labeled fiscal quarters, keeping the source messages and annual result shape.
  The official exact distinct-award aggregation and one signing date per award
  establish that these quarters are disjoint, so their counts are safely
  additive. A September–October 2024 partial window now returns FY2024=2,574
  and FY2025=2,190, rather than calendar2024=4,764 and FY2025=0. Quarter/month
  rows and counts are unchanged. **The prior monthly corpus passed but did not
  validate annual grouping; this misleading annual guidance was introduced by
  the broad fiscal-note fix.**
- **P3 recipient guidance:** the exposed recipient-search description directed
  its hash into the children tool, and autocomplete guidance made the same
  claim; README copy also falsely advertised hashes from autocomplete. The
  normal catalog-guided Lockheed hash follow-up failed. The parent UEI from
  the same returned row succeeded with 217 children from the official API.
  Two descriptions and README guidance now distinguish the name lookup,
  profile/trend hash, and children UEI/DUNS workflow. Tool names, input schemas,
  annotations and hosted identity remain unchanged. The actual installed CLI
  catalog and discovered-identifier follow-up verify the guidance; no new
  exact-description-string tests are used.

Six captured-API data regressions execute through the MCP pipeline: two annual
cases fail before correction; four unaffected month/quarter cases pass before;
all six pass corrected. Full Python validation: **1,924 passed, 379 live-gated
skipped (2,303 collected)**. Skips are not credited as executed live tests.
Package/contract/version gates and a built-wheel real installed-CLI workflow
are recorded separately in the shared `Artifacts/mcp-e2e-20261010/round2/usaspending`
evidence. At source-validation time, actual 1.0.16 publication and final
public acceptance remained pending; the completed publication record follows.

One prior audit-corpus label is corrected explicitly: the Round 1 hardcoded
children UEI `ZFN2JJXBLZT3` is Lockheed Martin’s, although its question said
Leidos. That was an audit-harness labeling limitation, not a product finding
or a passed Leidos child-mapping workflow. Round 2 derives the UEI from the
actual Lockheed parent result and completes the correctly named chain.


## Round 14 published verification (1.0.16, 2026-10-10)

The [scoped release workflow](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38071313999)
completed successfully on attempt 2 for tag `usaspending/v1.0.16`, source SHA
`d0b3e9883b2a70ac0c250b83f7fdd30234349fd8`, including PyPI, Cloudflare,
registry and release jobs. A new Python 3.12 environment installed
`usaspending-gov-mcp==1.0.16` by name from official PyPI with `--no-cache` and
MCP SDK 2.3.0. No bootstrap index failure or locally built candidate
substitution occurred. The installed module, distribution and CLI paths,
PyPI metadata, initialization identities and workflow result are saved.

Both the actual installed CLI and public deployment passed **127 corpus
questions across all 55 tools**, plus **11 discovered-recipient and fiscal
followup calls per surface**. Both actual tool catalogs exactly match the
approved 55-tool contract. The final replay corpus explicitly records the
old hash-guidance failure and corrected UEI followup; it does not turn the
original failed workflow into a retroactive baseline pass.

The recipient chain discovers Lockheed Martin's parent row from autocomplete
and search, uses its hash for profiles, and uses its returned UEI for 217
subsidiaries, then opens a returned subsidiary profile. Annual FY2025 new
awards total 23,992. The partial September–October 2024 window splits into
FY2024=2,574 and FY2025=2,190. Both surfaces crossfoot those annual counts
against fresh official fiscal-quarter responses; quarter/month rows and
messages remain equal to the fresh official responses. The official children
response also matches both surfaces. These live content checks are separate
from the **1,924 passed / 379 skipped / 2,303 collected** regression lane;
skipped tests are not credited as executed.

Root's initial deploy verification observed a version mismatch after the
health SHA matched. No failed backend header established a concrete cause,
which remains unknown. Attempt 2 and final acceptance passed at the same tag.
Public metadata is verified; propagation into every directory client was not
independently observed. Correcting this README/testing record requires no
new directory submission or republication.

Evidence: `Artifacts/mcp-e2e-20261010/round2/usaspending`, especially
`final-verification-1.0.16.json`, `published-install-provenance.json`,
`published-installed-cli-full-campaign.json`, `final-hosted-campaign.json`,
`published-installed-cli-followups.json`, `published-hosted-followups.json`
and `published-source-semantic-checks.json`. No Round 3 content audit is
claimed by this publication verification.


## Round 15: new realistic content audit (1.0.17 source, 2026-10-10)

A new campaign exercised **130 questions across all 55 tools** on actual
published PyPI/public 1.0.16, with fresh official API captures. Workflows
covered NASA aerospace R&D and engineering markets, new versus modified
awards and continuation; all six award types; a different discovered GSA
vehicle; Transportation grants and agency accountability; VA year/resource
comparison; all category/time/geography dimensions; Northrop parent and child
identity with fiscal timelines; IIJA reference-to-grant funding; Highway and
Federal-Aid Highways accounts; and recent completed-year DoD/USACE activity.
All 130 successful source/public outputs matched. Source parity did not
establish correct period interpretation for the finding below.

Independent checks passed for 15 actual award detail records (new signature
dates, Alabama performance and amount bounds, FFP/full-open engineering),
nonoverlapping award and FFATA pages, and NASA fiscal obligation totals of
$15,784,830,135.01 across annual/quarter/month groups. Northrop new-award
counts crossfoot to FY2025=1,728 and, for July–December 2024, FY2024=504 and
FY2025=418. Agency defaults identify the last completed FY2026, and recent
DoD/USACE results carry the applicable 90-day publication caveat. State
profiles disclose their older population/income source years; these source
limitations are not treated as product defects.

**One new P2 scope-guidance defect**: the FY2025 Transportation grouped
subaward ranking returned FL-2021-064 with 18 reports totaling $327,719,366.
The complete official dated-report response places all 18 on 2021-09-02:
FY2025 has zero reports and $0 reported amounts for this prime. The
[official contract](https://github.com/fedspendingtransparency/usaspending-api/blob/03b9e2554837998c4c261c65e2947dc79f23855a/usaspending_api/api_contracts/contracts/v2/search/spending_by_subaward_grouped.md)
and implementation return cumulative totals for selected prime records,
rather than date-trimming their subaward totals. The arithmetic is an honest
source result; advertising fiscal-period subcontracts without scope guidance
was the product defect.

The candidate description and output note now distinguish matching-prime
filters from cumulative subaward totals, include the requested date window,
and direct users to `search_subawards` with the returned prime ID, complete
pagination and actual `action_date` filtering. Counts, dollar values, IDs,
ratios, source messages and corrected pagination remain intact. A real
installed candidate-wheel catalog-guided workflow retrieves the complete 18
reports and corrects the fiscal interpretation. It also retrieves all 299
reports for KY-2020-011 over three pages: cumulative reported amounts are
$250,924,925, while its seven FY2025 reports sum to $2,374,440. These are
reported amounts, not a claim of net new spending or a global FY2025 ranking.

Three captured-API regressions execute through the MCP pipeline: the scope
warning fails before correction, two unchanged source/recovery checks pass
before, and all three pass after. The full source lane measured **1,927
passed / 379 live-gated skipped / 2,306 collected**. No skipped case is
credited as executed. The installed candidate CLI also passes the complete 130-question replay
across all 55 tools. Version consistency, the approved 55-tool contract,
wheel/sdist build and diff checks pass. Exactly one tool description changes;
all names, input schemas, annotations and identities are preserved. Compatible
metadata updates use OpenAI continuous review and require no manual directory
republication. Actual 1.0.17 PyPI/public acceptance remains pending root's
serial publication, and candidate-wheel checks do not claim a PyPI release.

Evidence: `Artifacts/mcp-e2e-20261010/round3/usaspending`, including the 130-case
`campaign.json`, primary source captures/hash index, `semantic-checks.json`,
`ffata-prime-primary-followup.json`, before/fixed regressions and measured
suite/collection logs. Publication followups will be recorded separately.


## Round 15 published verification (1.0.17, 2026-10-10)

The scoped `usaspending/v1.0.17` workflow
[38076343015](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38076343015)
completed successfully at source `7e8c4132d8b394e9a4ef7f2f57d1cc0a0d966336`.
An actual fresh by-name, uncached installation from official PyPI supplied
1.0.17 and the latest MCP SDK 2.3.0. Its installed server source matched the
frozen source byte for byte. The first install attempt encountered temporary
simple-index unavailability; attempt 2 succeeded. That bootstrap failure is
preserved and excluded from content checks. No candidate package substituted
for the published installation.

The full installed CLI and public campaigns each initially completed **129
questions successfully and one with a timeout**. The CLI CFDA category request
raised an official API `httpx.ReadTimeout`. The public Transportation
program-activities request hit the verifier's 70-second timeout while the
paired official source request succeeded. No public response or backend header
was received for that failed attempt, so its cause remains unconfirmed. Both
questions then passed a targeted same-question CLI/source/public replay; an
additional public replay returned HTTP 200 from the origin backend (0.150
seconds for CFDA and 0.076 seconds for program activities). Those observations
do not establish which backend caused the original timeout. Initial failures
remain unchanged in the evidence. **All 130 questions on each surface were
completed successfully after the targeted retries**, covering all 55 tools.

The actual public health SHA and MCP initialize version matched the release;
both actual catalogs matched the approved 55-tool contract. The primary lane
captured 134 official API responses, plus two targeted retry responses. The
saved response hashes are over canonical JSON, not raw transport bytes. Final
NASA annual/quarter/month obligations crossfoot to $15,784,830,135.01. Northrop
FY2025 annual/quarter/month new awards crossfoot to 1,728; the partial
July–December 2024 window crossfoots to FY2024=504 and FY2025=418.

Six actual installed CLI/public catalog-guided calls verified the corrected
FFATA workflow. FL-2021-064 returns all 18 reports dated 2021-09-02, totaling
$327,719,366 cumulatively, with **zero FY2025 reports and $0**. KY-2020-011
returns all 299 reports over three complete pages, totaling $250,924,925
cumulatively, with **seven FY2025 reports totaling $2,374,440**. The actual
output includes the requested filter dates, explains the cumulative scope and
directs complete pagination followed by `action_date` filtering. Matching-prime
totals are not a fiscal-period subaward ranking; reported amounts can repeat
cumulative values and their sum does not establish net new subcontract spending.

These content checks are separate from the saved source regression execution
of **1,927 passed / 379 live-gated skipped**, reconciled with **2,306 collected**
at the frozen integration source. No skipped case is credited as executed.
Official MCP registry 1.0.17 returned HTTP 200. Public metadata is verified;
propagation into every directory client was not independently observed. This
documentation correction requires no manual directory republication.

Evidence: `Artifacts/mcp-e2e-20261010/round3/usaspending`, especially
`final-verification-1.0.17.json`, `final-install-provenance.json`,
`final-installed-source-parity.json`, original and accepted final CLI/public
campaigns, `final-timeout-recovery.json`,
`final-public-responsiveness-check.json`, `final-cli-guided-workflow.json`,
`final-semantic-crossfoot.json`, official registry/catalog/health responses and
`final-evidence-hashes.json`. The final frozen collection is independently
recorded under `coordinator/round3-final-collection/collection.json`. This is
publication acceptance of Round 3, not a new content-audit round.

## Round 16: new realistic content audit (1.0.18 candidate, 2026-10-10)

The new Round 4 inventory contains **151 supported questions across all 55
substantive tools**. On a fresh official by-name, uncached PyPI 1.0.17 install
with MCP SDK 2.3.0, 150 questions completed through actual installed stdio,
the public service and a registered-tool pipeline capturing fresh official
API responses. All successful responses matched their source counterparts.
The one supported unavailable request is an explicit FY2027 account listing:
the official source returns HTTP 400 while default/explicit FY2026 remain
usable. This is a reporting-availability limitation, not a fabricated FY2027
fallback or a product defect. Two unsupported arguments introduced by the
audit harness are preserved and excluded from the supported-question/pass
counts; corrected funding followups were executed separately.

New workflows cover HHS biotechnology/pharmaceutical procurement, competed
fixed-price market research, new versus modified awards, all six award types,
a different Interior vehicle, Energy science grants and agency accountability,
USDA resources, all category/time/geographic dimensions, reported FFATA grant
primes and complete dated reports, Johns Hopkins recipient disambiguation,
Treasury Science account resources and reporting-calendar/reference followups.
Actual discovered Johns Hopkins Applied Physics Laboratory parent and main
university child are distinct recipients; their totals are not interchanged.
HHS FY2025 contract annual/quarter/month obligations crossfoot to
$21,290,558,265.84. APL FY2025 new awards crossfoot to 360; July–December 2024
partitions into FY2024=157 and FY2025=55. The actual main-university recipient
September–October 2024 counts crossfoot to FY2024=96 and FY2025=3; complete
FY2023/FY2024/FY2025 counts are 636/672/499. These are window-specific source
counts, not estimates for every Johns Hopkins entity.

**Four confirmed findings: P0=0, P1=0, P2=2, P3=2.** The first P2 accepted an
FY2024 Science-account program request without disclosing that the source
ignores fiscal year, lists programs across all reported years and supplies no
amounts. Its list includes AMERICAN SCIENCE CLOUD (PL 119-21), from legislation
approved July 4, 2025. The second P2 returned only the first 10 of 25 programs,
with no existing tool argument capable of retrieving the remaining pages.
Fresh official pages 10/10/5 exactly equal the source's 100-limit response.
The [pinned source implementation](https://github.com/fedspendingtransparency/usaspending-api/blob/03b9e2554837998c4c261c65e2947dc79f23855a/usaspending_api/accounts/v2/views/federal_account_program_activities.py)
and [endpoint contract](https://github.com/fedspendingtransparency/usaspending-api/blob/03b9e2554837998c4c261c65e2947dc79f23855a/usaspending_api/api_contracts/contracts/v2/federal_accounts/federal_account_code/program_activities.md)
confirm the all-year list and source paging. The candidate retrieves pages
internally, up to 2,000 records, and discloses completeness, no amounts and any
requested year that was not applied. It preserves source codes, names and
types. The actual Science list fits on one 100-limit source page; the separate
three-page source comparison establishes completeness, not a claim that this
candidate case exercised multiple internal pages.

The two P3 findings correct catalog claims: agency budgetary resources do not
provide a mandatory/discretionary split, and account listings default to the
source's latest available FY rather than necessarily the current FY. FY affects
account budgetary-resource values, not which account rows are included. The
actual post-rollover source default is FY2026, with FY2027 listing unavailable.
Agency-wide program amounts cannot be relabeled as account-level program
amounts. Single-year account resources remain available through the numeric
account-ID fiscal-year snapshot: Science FY2024 obligations remain
$9,281,790,861.20. No amount or unsupported fiscal program ranking is invented.

Three captured-source regressions yield **two failures and one unchanged
financial-followup pass before correction**, and all three pass afterward.
The complete source suite measures **1,930 passed / 379 live-gated skipped /
2,309 collected**. Skipped tests are not executed content checks. The freshly
installed candidate wheel with latest SDK 2.3.0 completes all 150 available
questions through actual CLI stdio. Unaffected results match the saved fresh
source results; corrected program queries disclose all-year scope and preserve
source records while returning the complete 25-record Science list. All 55
catalogs retain names, input schemas, annotations and identity; exactly three
descriptions change. The six-step actual installed catalog-guided workflow
recovers single-year financial resources with the discovered numeric account
ID, distinguishes agency-wide programs and checks the returned latest FY.
Version checks, wheel/sdist build, approved hosted contract and diff checks
pass. Compatible metadata changes use continuous review and require no manual
directory republication. Candidate checks do not establish published 1.0.18
PyPI/public acceptance; root's serial publication and final replay are pending.

Evidence: `Artifacts/mcp-e2e-20261010/round4/usaspending`, especially
`question-inventory.json`, `coverage.json`, `findings.json`, `audit-summary.json`,
`primary-capture-index.json`, fresh pinned official implementation/contracts,
GPO law provenance, FY2027 source response, original campaign files,
`semantic-checks.json`, before/fixed/full-suite/collection logs,
`candidate-catalog.json`, `candidate-replay.json` and
`candidate-guided-workflow.json`. The 154 pipeline-captured response hashes
are over canonical JSON; separate direct source captures identify their raw
transport-byte hashes explicitly.

## Round 16 publication and SDK reconciliation (1.0.19, 2026-10-10)

The immutable 1.0.18 release attempt stopped at an existing throughput timing
assertion: **1 failed / 1,929 passed / 379 skipped**, with deployment,
publication and registry jobs skipped. The separately reviewed test-only
repair distinguishes durable reservation timestamps from later body-entry
timestamps; the exact failed-run cause remains unknown. No tag was moved or
failed record replaced. Version 1.0.19 released successfully in workflow
[38082477859](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38082477859)
at source `4efbd9fb5fe5ea1f55aeb1682f9e9f7f3cc2c78b`.

An actual official by-name, uncached PyPI installation supplied 1.0.19 and
MCP SDK 2.3.0. Attempt 1 found the version absent from the index; attempt 2
succeeded. The first bootstrap failure is retained and excluded from content
checks. All **150 available original questions** passed through actual
installed CLI and public requests, with all 55 tool definitions and installed
runtime bytes matching the frozen source. Six actual CLI/public catalog-guided
steps passed. The 154 retained original fresh-primary canonical response
hashes were independently recomputed; four additional targeted fresh primary
checks confirm the Science complete25 list, unchanged FY2024 snapshot,
default FY2026 and explicit FY2027 source HTTP400. These retained and fresh
source lanes are separate; the complete primary campaign was not repeated.

The initial final-verifier lookup omitted the tool name from a key shared by
similarly captioned IDV/agency/reference questions, producing wrong expected
comparisons. The original actual responses and initial mismatches remain
saved. Adding the tool name and reconciling those same responses against the
correct retained source yields 150/150 parity. No network replay or actual
answer was altered. One earlier state-profile caption said Massachusetts
while the actual FIPS06 request and answer were California; the record credits
California/Texas coverage and claims no Massachusetts profile pass.

The actual fresh 1.0.19/latestSDK full regression execution measured **1,075
passed / 855 failed / 379 skipped / 2,309 collected**. All 855 failure blocks
contain the SDK2.3 generic tool error masking retained exception/message
expectations. This is not a passing latest-SDK regression lane. The earlier
**1,930 passed / 379 skipped** source execution used frozen SDK2.0.0;
its provenance is retained separately. The installed candidate SDK2.3 checks
were 150 ordinary CLI questions plus six guides, not a full pytest execution.
No prior claim of a full latest-SDK 1,930-pass run is supported. No skipped
test is credited as executed, and the regression failures are distinct from
the actual successful ordinary-question campaign.

The FY2027 query remains an honest source availability limit and is not
counted as a successful retrieval. The fresh official source rejects it with
HTTP400 and available years2001–2026; the public frozen-SDK service exposes
that explanation, while the actual latest-SDK CLI shows only "Error executing
tool list_federal_accounts". The omission of an actionable reason in this
ordinary current-year workflow is a **new P3 guidance finding**, bringing the
Round4 total to **P0=0 / P1=0 / P2=2 / P3=3**. It does not establish incorrect
financial data: the corrected catalog already identifies the latest available
default and the supported omit-year recovery returns FY2026.

## Round 16 narrow availability correction (1.0.20 candidate)

Only `list_federal_accounts` converts the recognized source HTTP400
available-year rejection to a purposeful tool error when an explicit requested
FY is outside the source's dynamically returned range. It preserves the
complete official message and guides omission of `fiscal_year` and checking
the returned `fy`. No year range is hardcoded, no unsupported year's values
are fabricated, and unrelated errors retain their existing path. All55 tool
names, descriptions, schemas, annotations and identity are unchanged.

A fresh installed1.0.19/SDK2.3 captured-provider test yields **one failure and
two passes**: the availability explanation is hidden, while supported default
recovery and an unrelated503 control already pass. All three pass after the
correction on frozenSDK2.0 and freshly installed candidateSDK2.3. The full
frozen source suite measures **1,933 passed / 379 skipped / 2,312 collected**.
This does not replace the failed fresh/latest full regression record above.
The actual fresh candidate1.0.20 CLI exposes the original available-year range
and supported recovery; its followup output equals the fresh official FY2026
response. Wheel/sdist build, version consistency, all55 approved tool contracts
and diff checks pass. Actual1.0.20 publication/public acceptance is pending
root's serial release. Existing directory identity is preserved and no manual
directory republication is required.

Evidence remains under `Artifacts/mcp-e2e-20261010/round4/usaspending`:
`final-verification-1.0.19.json`, install attempts, immutable initial and
reconciled final campaigns, lookup/caption corrections, actual six-step
`final-published-guided-workflow.json`, `final-targeted-primary.json`,
`final-source-availability.json`, `source-suite-provenance.json`, the complete
fresh/latest failure log and 855-entry inventory; plus captured availability
fixture, before/after/full frozen logs, `available-fy-candidate20-console.json`
and independently sealed peer records. Candidate corrections are not credited
as actual published acceptance.

## Round 16 final published verification (1.0.20, 2026-10-10)

The scoped release workflow
[38083846513](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38083846513)
completed successfully at `2a93b7b706d818da647f9d56cacbf543f867fa79`.
A fresh official by-name, uncached PyPI installation supplied 1.0.20 with
latest MCP SDK 2.3.0. The first install attempt found the new version absent
from the index; the second succeeded. The bootstrap failure remains preserved
and excluded from content checks; no candidate package substituted for the
published installation.

**All 150 available original questions passed on actual CLI and public
surfaces**, with zero invocation errors and zero retained-source parity
mismatches. All 55 actual catalogs match the reviewed tool definitions; names,
schemas, descriptions and annotations remain unchanged by the availability
correction. The installed runtime matches the frozen release source. Six
actual installed CLI/public catalog-guided followups passed, recovering the
complete Science program list, accurate single-year account financial values,
agency-wide program scope and latest-available FY semantics.

The 154 retained original fresh-primary canonical JSON hashes were recomputed
and verified. Four additional targeted fresh official requests confirmed the
complete 25-record Science source list, unchanged FY2024 obligations of
$9,281,790,861.20, the default available FY2026 and the exact FY2027 HTTP 400
available-year explanation. The broad primary campaign was not repeated;
retained-source comparisons and fresh targeted requests are distinct lanes.
Both official PyPI wheel and source archive match their advertised digest and
all eight runtime modules byte for byte against the frozen release. The
published-wheel dependency/entry-point/payload guard passes after selection
of the single 1.0.20 wheel; the initial guard failure from a directory containing
both 1.0.19/1.0.20 wheels remains retained and was not a payload mismatch.

The ordinary explicit FY2027 question now returns the source's actual
available-year explanation and supported omit-year/check-returned-fy recovery
on **both actual CLI and public**. The CLI recovery output matches the fresh
official FY2026 response; the six-step public workflow also verifies that
same default. FY2027 data remains unavailable and is not counted as a
successful data retrieval. No year was silently relabeled or fabricated.
All five Round 4 findings are fixed and verified in publication:
**P0=0 / P1=0 / P2=2 / P3=3**, with zero partial or unresolved product findings
in this completed corpus. This is the completion of Round 4, not a new audit.

The actual fresh published 1.0.20/latest SDK full regression run measured
**1,078 passed / 855 failed / 379 skipped / 2,312 collected**. The 855 failed
node IDs exactly match the immutable actual 1.0.19/latest SDK failure set; all
855 failure blocks contain generic SDK 2.3 errors masking retained expected
exception/message assertions. The three new availability regressions pass.
These measured failures are not credited as passing or repaired globally.
The separate frozen SDK 2.0.0 source lane remains **1,933 passed / 379 skipped**,
with 2,312 collected; the release CI/test-only repair provenance is retained.
There is no claim that the latest SDK full suite passed. Skipped tests are not
credited as executed content checks.

Independent SAM review separately verified published 1.0.20 originals/recoveries,
focused captured-source tests, all 55 catalogs and eight runtime modules.
The earlier failed 1.0.18 release, actual 1.0.19 acceptance, 855-failure inventory,
state-caption and expected-lookup corrections remain intact. Public metadata
is observed; propagation into every directory client was not independently
observed. This final documentation-only update changes no runtime or version
and requires no manual directory republication.

Evidence: `Artifacts/mcp-e2e-20261010/round4/usaspending`, especially
`final-verification-1.0.20.json`, `final20-published-provenance.json`,
`final20-published-campaign.json`, `final20-published-guided-workflow.json`,
`final20-source-availability.json`, `final20-targeted-primary.json`,
`final20-official-artifact-payloads.json`, actual install/test/collection logs,
`final20-published-failure-inventory.json`, `evidence-hashes.json` and
`post-release/peer-sam-final20.json`. No later-round work is claimed.


## Round 17 new Round 5 content audit (1.0.21 candidate, 2026-10-10)

A fresh official by-name, uncached PyPI 1.0.20 installation (Python 3.12.13,
MCP SDK 2.3.0) and the public service at source
`2a93b7b706d818da647f9d56cacbf543f867fa79` completed **143 new ordinary and
power-user questions across all 55 tools**. Ten prior Interior vehicle
checks are retained separately and excluded from the new-question count.
The total is 153 actual console calls, 153 public HTTPS tool calls and 153
registered installed-package primary pipelines, with no invocation errors
or substantive source-parity differences. Those matching transports still
exposed the one misleading note below; parity is not a claim that every
before answer was correct.

New tasks covered DOT engineering/highway supplier research, date modes,
competition/pricing/amount/location filters and continuation; Commerce/NOAA
grants, agency financial dimensions and dated FFATA reports; HUD loans and
direct payments; a NASA IT vehicle hierarchy; EPA account/program/resources
comparisons; University of Washington recipient identities and fiscal
trends; Washington/New York geography and code/glossary/reporting-calendar
followups. Broad Environmental account discovery returned Interior account
014-5425 first. Four legacy harness-caption rows called it a science account;
the inventory explicitly evaluates the actual Environmental account instead.
Raw captions, arguments and responses remain unchanged; no Science answer
is credited.

Meaningful financial/source completion includes:

- DOT FY2025 contract obligations crossfoot at **$9,022,534,685.22** across
  annual, quarter and month buckets.
- Main UW child `HD1WMN6945W6` has **425 FY2025 new awards** across all three
  bucket modes; its profile is kept distinct from the Board of Regents
  parent and that parent's separate source rollup.
- EPA Environmental Programs and Management account `068-0108`/numeric ID
  4872 has FY2024/FY2025/FY2026 snapshots whose obligated plus unobligated
  amounts equal resources. Program codes remain all-year lists without
  dollar amounts; snapshots supply the actual fiscal-year comparison.
- Michigan Commerce prime `ASST_NON_2620B109_013` has **92 unique reports**
  totaling **$777,518,213.12** after complete one-page retrieval. Every date
  is July 17–September 18, 2026: the actual dated FY2025 subset is zero.
  Existing cumulative-prime scope guidance correctly prevents a FY2025
  subaward-total claim. These reports are not net new spending.
- The discovered HUD guaranteed loan reports **$72.4 million face value**,
  **−$1,940,320 subsidy cost** and **zero obligations**; those measures are
  not substituted for each other. FY2027 empty agency-resource rows and
  partial FY2026 source reporting remain source limitations.

**USA-R5-001, P3:** “Find five current construction NAICS codes and explain
how many retired codes were excluded.” Published 1.0.20 CLI/public guidance
said “Filtered 10 retired codes” and suggested including retired entries.
The exact fresh official autocomplete response has 15 rows, all with
`year_retired=null`; ten current rows, including Highway/Street/Bridge
Construction `237310`, were omitted only by `limit=5`. Candidate 1.0.21
counts actual retired rows separately, explains current-result truncation
and guides increasing the limit. Source code/name/order, current-code
filtering, include-retired behavior, errors and all 55 tool definitions
remain unchanged. No directory republication is required.

The captured-source registered-tool regression on actual published 1.0.20
failed the ordinary truncation explanation while two controls passed.
All three pass on frozen MCP 2.0.0 and a fresh candidate wheel with MCP
2.3.0. A genuine `5417` source pool contains three retired and four current
research codes; their retirement filtering is preserved. Actual candidate
console originals and larger-limit recovery expose the highway code.
Candidate evidence is not actual published 1.0.21 acceptance.

The candidate frozen Python 3.14.3/MCP 2.0.0 full suite measured **1,936
passed / 379 skipped**; a separate collection in that same environment
measured **2,315 collected**. The latest-SDK focused
lane passed three tests; no latest-SDK full-suite pass is claimed. The
historical actual published 1.0.20 latest-SDK full record remains **1,078
passed / 855 failed / 379 skipped / 2,312 collected**. Legacy negative/error
expectations were not mined or repaired by this content audit. The approved
55-definition contract passes on SDK 2.3; the separately retained SDK 2.0
serialization comparison differs, and no contract baseline was rewritten.
Build, scoped version surfaces and CI passed. PR153 merged at
`15a9a034c99ccad2750e39fcfb9aae46d540945d`; root owns publication after the
complete-content peer and integration gates.

New findings: **P0=0 / P1=0 / P2=0 / P3=1**, fixed in candidate, with no
partial or unresolved product defects in this corpus. Publication and
actual published 1.0.21 originals/recoveries remain pending. Round 6 has not
started. Evidence is `Artifacts/mcp-e2e-20261010/round5/usaspending`:
`question-inventory.json`, `coverage-map.json`, `audit-summary.json`,
`primary-capture-index.json`, `financial-task-completion.json`, caption/
replay classifications, captured NAICS discovery/control, before/after
logs, three runtime/SDK provenance files and the preserved candidate
console evidence. The 160 fresh primary captures are parsed canonical JSON,
not retained raw HTTP bytes; source and content counts remain distinct.
