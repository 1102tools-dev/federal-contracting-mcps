# BLS OEWS MCP: Testing Record

## Executive Summary

This Model Context Protocol server exposes the BLS Occupational Employment and Wage Statistics (OEWS) API as callable tools for federal IGCE development, price analysis, and labor market research. It was hardened through a retroactive live audit with a real BLS API key (0.2.2, 22 findings), then re-audited end to end in round 7 (1.0.1) by an independent full-source review with live verification. Round 7 found 13 further bugs, headlined by a money bug the earlier "empirical" round had itself introduced: the four hourly percentile labels were shifted one slot, so requesting the Hourly Median returned the 75th percentile (26% high for Software Developers). The official mapping was pinned by cross-footing hourly x 2080 against the annual percentiles and is now guarded by a live canary test.

| Metric | Value |
|---|---|
| MCP tools exposed | 7 |
| Total regression tests | 243 (82 offline, 161 live-gated) |
| Audit rounds completed | 7 |
| P0 usability-breaking bugs found and fixed | 1 |
| P1 silent-wrong-data bugs found and fixed | 14 |
| P1 response-shape crash paths found and fixed | 12 |
| P2 validation gaps found and fixed | 12 |
| P3 cleanup items found and fixed | 8 |
| Current release | 1.0.1 |
| PyPI status | Published as `bls-oews-mcp`, auto-publishes via Trusted Publisher on tag push |

## What Was Tested

The MCP exposes 7 tools covering the BLS OEWS API surface. Testing covered all of them end-to-end.

**Core:** `get_wage_data`, `compare_metros`, `compare_occupations`, `igce_wage_benchmark`

**Reference:** `list_common_metros`, `list_common_soc_codes`, `detect_latest_year`

Each tool was exercised for argument validation, SOC code format normalization, state FIPS padding, response-shape guarantees against BLS's occasionally-inconsistent response shapes, error translation (including the REQUEST_PARTIALLY_PROCESSED status that BLS uses for partial data), datatype-code semantics against production data, and real-world data handling against the live production BLS v2 API with a real API key.

## How It Was Tested

### Testing discipline

The 0.1.1 smoke test for this MCP said "zero bugs." The retroactive live audit proved that was wrong (22 findings). Round 7 then proved a subtler failure mode: shape-only live assertions. The round-6 live suite asserted `isinstance(data, dict)` and key presence, which let a wrong-dollar-value bug (the datatype label shift) pass 154 live tests. Round 7 adds semantic live canaries: the cross-foot invariant (each hourly percentile x 2080 must equal its annual counterpart) fails loudly if BLS datatype semantics ever drift again. Regression tests invoke tools through `mcp.call_tool(name, kwargs)` the way a real MCP client does.

### Audit rounds

| Release | Context | Findings |
|---|---|---|
| 0.2.0 | Original hardening with mocks | Baseline validation |
| 0.2.1 | Cross-MCP `extra='forbid'` back-port | 1 cross-fix |
| 0.2.2 | Full retroactive live audit with real BLS key: 5 audit rounds covering format validation, silent suppression, response-shape fuzzing, datatype mapping, validation gaps | 22 real bugs |
| 1.0.1 | Round 7: independent full-source re-audit with live verification (stronger model). Focus: datatype semantics, composite-tool math, silent data loss, testing.md record accuracy | 13 real bugs |

### Live audit status

Rounds 0.2.2 and 7 used a real BLS v2 API key throughout. The repository includes 161 live-gated regression tests executable via `BLS_LIVE_TESTS=1 BLS_API_KEY=... pytest`. A BLS v2 key is free at `data.bls.gov/registrationEngine` and carries a 500-queries-per-day limit.

## Live test quota budget

The BLS v2 API allows **500 requests per day per registration key**. This suite
carries **161 live-gated tests**, and each one costs roughly one request, so a
single full live pass (`BLS_LIVE_TESTS=1`) burns about a third of the daily
budget. Three full passes in a day is the practical ceiling.

**Do not re-run the suite just to re-read output.** On 2026-08-15 the key was
exhausted by running the full live pass four times while diagnosing failures
that the first run had already reported. The tell is `HTTP 429` or `the daily
threshold for total number of requests allocated to the user with registration
key ... has been reached`. Both are rate limiting, not server defects. Capture
the first run's output to a file and read that instead.

For reference, the server itself is efficient: every tool issues exactly one
POST, batching up to `MAX_SERIES_V2` (50) series per request. A 12-metro
`compare_metros` call costs one request, not twelve. Normal use is nowhere near
the cap; a complete IGCE labor basis runs 5 to 15 requests.

## Round 7 (1.0.1): Independent re-audit

Round 7 re-read the full source against the live API with no reliance on this
document's prior claims. 13 findings, all fixed in 1.0.1:

| # | Finding | Fix |
|---|---|---|
| 1 | **Hourly percentile labels shifted one slot** (the round 0.2.2 "empirical relabel" was itself the bug). Labels claimed 07=10th, 08=25th, 09=Median, 10=75th. Live cross-foot proof: 08 = $24.51 x 2080 = $50,980 = the annual MEDIAN (dt13), so 08 is the hourly median. Requesting "Hourly Median" returned 75th-percentile dollars, 26% high for 15-1252. | Official mapping restored (06=10th, 07=25th, 08=Median, 09=75th, 10=90th); regression tests that pinned the wrong labels rewritten; live cross-foot canary added. |
| 2 | Datatype 06 (Hourly 10th Percentile) missing from the valid set entirely; unrequestable. | Added and routed as hourly. |
| 3 | Datatype 16 labeled "Annual 90th Percentile (alt code)"; it is actually Employment per 1,000 Jobs (state/metro only) and was formatted as truncated dollars ("$21" from 21.484). | 16 and 17 (Location Quotient) labeled correctly and formatted as ratios, never dollars. |
| 4 | `igce_wage_benchmark` fabricated hourly rates for annual-only occupations (pilots, teachers) with no warning: BLS deliberately publishes no hourly wage for them. | Requests dt03 alongside the annual set; when hourly is unpublished while annual exists, sets `annual_only: true` plus `_hourly_warning`. |
| 5 | Unpublished cells formatted as "[Capped]" with a docstring claiming '-' means wage >= $239,200. Wage top-coding ended; May 2025 data publishes values far above the old cap. | Neutral "[Not published] {footnote}" formatting; docstrings corrected. |
| 6 | `compare_occupations` lacked the all-no-data flag the other tools have, so fake SOCs looked like privacy suppressions. | Same `no_data` + `no_data_reason` block added. |
| 7 | Dedup ran on raw input strings, so '47900' and '0047900' (or '15-1252' and '151252') sent duplicate series and silently dropped one label from results. | Dedup on the normalized series ID; collapsed inputs reported in `_note`. |
| 8 | Per-series diagnostics under REQUEST_SUCCEEDED ("Series does not exist", "No Data Available for ... Year") were discarded. | Surfaced as `_api_messages`. |
| 9 | `detect_latest_year` probed only current+1, so a 2-year-stale default reported itself current while every query returned empty. | Probes with the API's `latest=true` flag and reports the true newest year at any staleness. |
| 10 | An all-empty API response escaped the `no_data` flag (`if results and not wage_values` with empty `results`). | Flags on `not wage_values`; requested datatypes missing from the response are seeded as explicit "No data" entries. |
| 11 | `_data_year` and `_period` meta keys were interleaved inside the `wages` mapping. | Promoted to top-level `data_year` and `period` fields. |
| 12 | Dead code and phantom guards: `FULL_DATATYPES` and `COMMON_STATES` unused, `_api_key_status` never called, state FIPS not actually validated (`99` burned a query). | Dead constants removed; full state/territory FIPS validation implemented; scope/area mismatch checks added for both directions; `_api_key_status` wired into `detect_latest_year`. |
| 13 | readme.md shipped inverted year guidance ("defaults to 2024... Do NOT query 2025"), guaranteeing failures for anyone following it. | Corrected to the 2025 reality with pointer to `detect_latest_year`. |

### Corrections to the prior record (round 7)

The following claims in earlier versions of this document were false and are
corrected here. They are retained in amended form in the historical tables
below, each tagged "[Corrected in round 7]".

- "Current release 0.2.2" with 60 tests: the file had drifted three releases behind the repo.
- The coverage table listed `tests/stress_test_live.py`, which never existed (the file is `tests/stress_test.py`), and omitted `tests/test_live_audit_r6.py`, the bulk of the suite.
- "State FIPS validated against known set", "Metro codes validated", "Industry codes validated": none of these validations existed. State FIPS validation now exists (round 7); metro and industry codes are format-checked only, with scope-mismatch heuristics.
- "Duplicates now flagged with a clear warning; single-code input handled as pass-through": no warning existed; dedup silently collapsed on raw strings. Real dedup with `_note` reporting shipped in round 7.
- "Response year is now compared against the requested year; mismatch raises actionable error": no such comparison existed. The API serves only the latest year and the validator already pins requests to it; the response year is now reported top-level as `data_year`.
- "Mixed metro and state codes in compare_occupations ... checked for consistent scope": no such check existed. Scope/area shape validation shipped in round 7.
- "`_series_id_from` helper returns None and logs if missing": it returns an empty string and the module has no logging.
- "No retry on 429 ... All resolved": no retry exists, by design. 429s surface with actionable guidance; the daily quota makes client-side retry counterproductive.
- The 0.2.2 claim that dt08 "empirically" returns 25th-percentile values, which drove the mislabeling this round reversed. The round-6 datatype tests asserted only `isinstance(data, dict)` and could never have caught it.
- The changelog 0.2.6 claim that IGCE testing covered an "aging factor": no aging/escalation feature exists, and the test named for it passes vacuously.

## Issues Found and Fixed (rounds through 0.2.2)

### Priority 0: Usability-breaking

One bug in this class, a hard blocker for new users.

| Issue | Fix |
|---|---|
| **SOC code validator rejected the standard BLS format "15-1252" (with dash).** The regex required ASCII digits only, but every example on bls.gov and every BLS publication uses the dashed format (e.g. "15-1252" for Software Developers). Users pasting SOC codes directly from BLS got a hard "must contain only ASCII digits" error. Only the un-dashed "151252" worked. | Validator now accepts both `15-1252` and `151252`. Dash is stripped internally before forwarding. Regression tests cover both forms including mixed case and trailing whitespace. |

### Priority 1: Silent wrong data

| Issue | Fix |
|---|---|
| **`year=2023` (or any non-current year) returned ALL fields marked `suppressed: true`.** BLS's public API only serves the current data year. Users requesting historical data thought the data was privacy-censored when in fact the API was just not serving that year at all. | Year tightened to `current + 1` at the arg layer with an error message pointing to `bls.gov/oes/tables.htm` for historical data. |
| **`occ_code="99-9999"` returned 4 fully-formed "suppressed" benchmarks with `occ_title: "99-9999"`.** | `no_data` flag and `no_data_reason` field added when all values are null. `_title_warning` added to IGCE output when the SOC code is not in the known lookup. |
| **Nonexistent state FIPS ("99") returned all-suppressed with no warning.** | [Corrected in round 7] The claimed known-set validation did not exist until 1.0.1, which validates against the full 54-entry state/territory FIPS table. |
| **Nonexistent metro code ("99999") returned all-suppressed with no warning.** | [Corrected in round 7] Metro codes are format-checked and shape-checked (state-FIPS-shaped inputs rejected); there is no known-MSA whitelist, and the `no_data` flag is the backstop for nonexistent MSAs. |
| **Nonexistent industry ("999999") returned all-suppressed with no warning.** | [Corrected in round 7] Industry codes are format-checked only; the `no_data` flag is the backstop. |
| `compare_metros` silently accepted 2-digit state FIPS mixed with 5-digit MSAs. | Mixed-format input raises `ValueError` pointing at `compare_occupations(scope='state')`. |
| `compare_metros` with duplicate codes silently deduplicated. | [Corrected in round 7] Dedup now runs on the normalized series ID and reports collapsed inputs in `_note`. The previously claimed "clear warning" did not exist. |
| Data-year field in the response was the API's latest regardless of the `year` parameter. | [Corrected in round 7] The claimed response-year comparison never existed. The validator pins requests to the served year, and the response year is reported top-level as `data_year`. |
| Short SOC like "15-125" (6 chars with dash) bypassed validation because length check was pre-strip. | Length check now post-normalization; 6-char input rejected. |
| Mixed metro and state codes in `compare_occupations` silently returned 0 results. | [Corrected in round 7] Scope/area shape validation (state FIPS vs MSA) shipped in 1.0.1. |

### Priority 1: Response-shape crashes

Twelve distinct crash paths in the BLS response parser from round 4 mock fuzzing. BLS's v2 API occasionally collapses single-element lists to dicts and returns partial-processed responses with non-standard status fields.

| Issue | Fix |
|---|---|
| `series` returned as dict instead of list (XML-to-JSON collapse) → `TypeError`. | `_as_list` normalizer wraps `series`. |
| `data` returned as dict instead of list → `KeyError: 0`. | Same `_as_list` coercion. |
| Entry missing `value` field → `KeyError: 'value'`. | `_extract_first_data_entry` helper with `.get()` throughout. |
| Entry missing `year` field → `KeyError: 'year'`. | Guarded. |
| Series item missing `seriesID` → `KeyError: 'seriesID'`. | [Corrected in round 7] `_series_id_from` returns an empty-string fallback; the module does not log. |
| `footnotes` as dict instead of list → `AttributeError`. | `_safe_footnotes` helper normalizes. |
| `footnotes` as string → `AttributeError`. | Same helper. |
| Data array with None entries → `AttributeError`. | None entries filtered. |
| Series list with None entries → `TypeError`. | Same filtering. |
| `JSONDecodeError` unhandled during BLS maintenance windows. | `_clean_error_body` helper catches and re-raises with API context. |
| `REQUEST_PARTIALLY_PROCESSED` silently treated as success. | Partial-processed responses surface per-series errors; round 7 additionally surfaces REQUEST_SUCCEEDED diagnostics as `_api_messages`. |
| Int `seriesID` (non-string) caused `sid[-2:]` slice to crash. | `_coerce_str_digits` helper normalizes to string. |

Helpers wrapping every BLS response parsing path: `_as_list`, `_coerce_str_digits`, `_validate_soc`, `_validate_industry`, `_validate_datatype`, `_validate_year`, `_extract_first_data_entry`, `_safe_footnotes`, `_series_id_from`, `_clean_error_body`, `_api_key_status`, `_check_area_for_scope`.

### Priority 2: Validation gaps

| Issue | Fix |
|---|---|
| Single-digit state FIPS ("6" for California) was rejected. | Auto-pad to 2 digits. |
| Newline, tab, carriage return in `occ_code` slipped through `strip()`. | Control chars rejected before strip. |
| `OEWS_LATEST_FUTURE_YEAR = 2100` allowed years that will never have data. | Tightened to current + 1. |
| `DATATYPE_LABELS["08"]` relabeling. | [Corrected in round 7] The 0.2.2 relabel was itself the bug; see Round 7 finding 1. Official mapping restored and live-guarded. |
| `DATATYPE_LABELS` missing labels for valid datatypes. | [Corrected in round 7] 0.2.2 added 07/09/10/16 under wrong semantics; 1.0.1 adds 06 and 17 and corrects all labels. |
| Bogus datatypes like "99" or "AA" silently accepted, wasting the API call. | Validated against the known datatype set. |
| `igce_wage_benchmark` accepted reversed or non-positive burden ranges. | Reversed range raises actionable error. Negative and zero burdens rejected. |

### Priority 3: Cleanup items

`detect_latest_year` was silently swallowing all exceptions (a 429 became a misleading "no newer data available"); the USER_AGENT was stale; `OEWS_CURRENT_YEAR` requires a bump each release cycle (mitigated in round 7: `detect_latest_year` now detects staleness of any depth via `latest=true`). [Corrected in round 7] The prior claim that a 429 retry was added was false; 429s surface clearly and no client-side retry exists, deliberately.

## Test Coverage

The repo ships 243 regression tests (82 offline, 161 live-gated). All pass on every release cycle; live tests require `BLS_LIVE_TESTS=1` plus a key.

| File | Purpose | Test count |
|---|---|---|
| `tests/test_validation.py` | Main regression suite covering rounds 0.2.x, including 5 live-gated integration tests | 66 |
| `tests/test_live_audit_r6.py` | Round 6 live sweep (shape assertions; kept as breadth coverage) | 154 (all live-gated) |
| `tests/test_audit_r7.py` | Round 7 regressions: datatype semantics, annual-only detection, normalized dedup, seeded gaps, latest-year probe, FIPS validation, plus the live cross-foot canary | 23 (21 offline, 2 live-gated) |
| `tests/stress_test.py` | Scenario script (not pytest) retained for reproducibility | N/A |

Regression tests invoke tools through the MCPServer registry (`mcp.call_tool`). An autouse fixture resets the shared httpx client between tests.

## Release History

| Version | Focus | Outcome |
|---|---|---|
| 0.1.1 | Initial release (smoke tested, reported "zero bugs"; reality was 22+ lurking) | Baseline coverage |
| 0.2.0 | First hardening pass (mocks only) | Baseline validation |
| 0.2.1 | Cross-MCP `extra='forbid'` back-port from sam-gov-mcp 0.3.1 | +1 regression test |
| 0.2.2 | Full retroactive live audit with real BLS key | 22 findings resolved |
| 1.0.0 | mcp 2.x SDK rebase, version sync, packaging | Stable baseline |
| 1.0.1 | Round 7 independent re-audit with live verification | 13 findings resolved, incl. the datatype label shift money bug; live cross-foot canary added |

## Cross-MCP Context

This MCP is one of eight servers in the 1102tools federal-contracting MCP suite (`ecfr-mcp`, `federal-register-mcp`, `gsa-calc-mcp`, `gsa-perdiem-mcp`, `regulationsgov-mcp`, `sam-gov-mcp`, `usaspending-gov-mcp`, and this one). All eight were hardened under the same playbook. Patterns reused or established here:

- **"Smoke test said zero, live audit found everything" lesson** was codified here, then extended in round 7: shape-only live assertions are nearly as blind as mocks. Semantic invariants (the 2080 cross-foot) are the durable guard.
- **Response-shape defensive-parsing helpers** `_as_list`, `_extract_first_data_entry`, `_safe_footnotes` were exported to other MCPs that face similar XML-to-JSON collapse edge cases.
- **`_api_key_status` pattern** for warning the user when an API key is empty or whitespace was codified here.
- **`extra='forbid'` on every tool's pydantic arg model** was back-ported from sam-gov-mcp 0.3.1 in the 0.2.1 release.

## What Was Not Tested

- **Rate-limit behavior beyond 500 queries per day.** The BLS v2 free tier is capped at 500 queries per day. The MCP surfaces 429s but does not implement client-side throttling.
- **Historical data years.** BLS's public API only serves the current year. Users needing historical data are directed to `bls.gov/oes/tables.htm`.
- **Wage data during the annual BLS data release window.** BLS publishes new OEWS data roughly in April each year; the window when the new year's data appears and stabilizes has not been live-audited. `detect_latest_year` now reports the true served year whenever it runs.
- **v1 (legacy) API endpoints.** This MCP uses v2 only (v1 fallback exists for keyless operation but is not live-audited).

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root and can be re-executed by anyone. The live suite runs with `BLS_LIVE_TESTS=1 BLS_API_KEY=... pytest` using a free BLS v2 API key.

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 during the original hardening playbook, and Claude Code Fable 5 for the round 7 independent re-audit (full-source review, live API verification, record correction).

Round 7 methodology: re-read the entire server source with no reliance on this document's claims; verify every constant table and datatype code against production BLS responses; recompute composite-tool math by hand; replay documented API shapes through the real tool pipeline; check every prior claim in this document against the code and live behavior.

Test count: 243 regression tests (82 offline, 161 live-gated). Total findings across all rounds: 35. Current version: 1.0.1. PyPI: `bls-oews-mcp`.

Source: github.com/1102tools/federal-contracting-mcps/tree/main/servers/bls-oews-mcp. License: MIT.


## Round 8 (2026-08-18): suite-wide live verification (super-cycle)

The full live-gated suite ran wholesale against production for the first time
(historically prevented by key quotas): 243 passed after one drift fix (2m41s). No new server
defects. Upstream drift caught and fixed: BLS rolled OEWS to 2025; a test hardcoding year=2024 tripped the server's own (correct) release guard. The test now derives the latest year at runtime. Added `tests/test_audit_r8.py`: 3
one-call-per-test live contract anchors re-stamping this server's headline
fixes against production (all verified green on landing), a suite-wide pacing
conftest with a `live_smoke` marker, and a per-test client reset so batched
live runs cannot hit the cached-AsyncClient/closed-event-loop trap.
