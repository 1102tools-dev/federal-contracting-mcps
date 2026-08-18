# USASpending.gov MCP: Testing Record

## Executive Summary

This Model Context Protocol server exposes the USASpending.gov REST API as 55 callable tools for federal contract, award, subaward, recipient, agency, and federal account research. It was hardened across eleven audit rounds, the eleventh a ~95-call paced live campaign that found ZERO new defects. v0.3 (round 9) tripled the API surface from 17 to 55 tools, adding FFATA subawards, recipient profile/children, agency depth (sub-agencies, federal accounts, object classes, program activities, obligations by award category), award detail rollups, transaction-level and geographic search, IDV depth, autocomplete helpers, reference data, and Treasury federal accounts. Round 10 (1.0.1) was a two-family semantic live audit that found 22 verified defects rounds 1-9 had missed, including one tool that had never worked at all; the methodology change behind it is documented in the Round 10 section. The MCP ships with 2,160 regression tests covering every surface twice (offline shape + live).

| Metric | Value |
|---|---|
| MCP tools exposed | 55 |
| Total regression tests | 2,151 (1,783 offline, 368 live-gated) |
| Tests per tool | 39+ |
| Audit rounds completed | 11 (rounds 1-8, v0.3 expansion, two-family semantic audit, paced live campaign) |
| Initial integration issues (round 1) | 28+ |
| P1 silent-wrong-data bugs found and fixed | 11 (rounds 1-9) |
| P2 validation gaps found and fixed | 7 (rounds 1-9) |
| Round 7 deep live audit findings | 0 |
| Round 8 Hypothesis property tests findings | 0 |
| Round 9 (v0.3) live audit findings | 1 (list_states JSON-array response shape) |
| Round 10 (1.0.1) semantic audit findings | 22 (12 search family, 10 entity family), all fixed |
| Release cycles | 13 (v0.1.2 through v1.0.1) |
| Current release | 1.0.1 |
| PyPI status | Published as `usaspending-gov-mcp`, auto-publishes via Trusted Publisher on tag push |

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

- **Rate-limit behavior: RESOLVED in round 11.** USASpending documents no limits, its open-source Django settings configure no REST Framework throttling at all, and 95 paced calls (plus prior unpaced suite runs) have never seen a 429. Infrastructure-level abuse protection presumably exists; audit-scale use does not approach it.
- **Historical API changes.** Tests validate behavior against the current USASpending API. Breaking changes to the upstream API (field renames, endpoint deprecations) are not caught by offline tests. Live-gated tests will catch them but must be run manually with `USASPENDING_LIVE_TESTS=1`.
- **Payload size limits beyond `limit` capping.** Response sizes over ~95KB are theoretically possible on some endpoints if the caller accepts the default shape. The MCP does not enforce an overall payload size ceiling.
- **Pending API deprecation.** USASpending has signaled that `subawards` award type will be superseded by a `spending_level` parameter. The MCP does not yet expose `spending_level`. When upstream fully deprecates, grants queries may need an adjustment.

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root and can be re-executed by anyone. The live suite runs with `USASPENDING_LIVE_TESTS=1 pytest` and requires no API key (USASpending is a free, public API).

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 (1M context, max effort, Claude Max 20x subscription) through round 9, and Claude Fable 5 for the round 10 two-family semantic audit.

Testing spanned ten rounds from integration stress testing through live API audits, response-shape guards, property testing, and the round 10 semantic audit (parameter effects, enum sweeps, contract-vs-validator diffs). The live regression suite runs against the USASpending.gov production API when enabled with `USASPENDING_LIVE_TESTS=1`.

Test count: 2,151 regression tests (1,783 offline + 368 live-gated) across 55 tools. Tests per tool: 39+. P1 bugs found and fixed rounds 1-9: 11. P2 validation gaps closed rounds 1-9: 7. Round 10 findings fixed: 22. Integration issues closed in round 1: 28+. Release cycles: 13. Current version: 1.0.1. PyPI: `usaspending-gov-mcp`.

Source: github.com/1102tools/federal-contracting-mcps/tree/main/servers/usaspending-gov-mcp. License: MIT.
