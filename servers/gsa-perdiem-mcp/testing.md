# GSA Per Diem Rates MCP: Testing Record

## Executive Summary

This Model Context Protocol server exposes the GSA Per Diem Rates API as 6 callable tools for federal travel lodging and M&IE rate lookups used in IGCEs and travel cost estimation. It was hardened across seven audit rounds, three of them live audits against the production API. The 0.2.x program surfaced 55 bugs. Round 7 (1.0.1), an independent full-source re-audit with live verification, found 14 more and overturned a round-6 headline: the "catastrophic silent-wrong-data" cases (Penasco returning Taos, Santa Rosa Beach returning Fort Walton Beach) were actually the API's CORRECT city-to-county rate-area resolution, and the round-6 "fix" had been stamping false WARNINGs on right answers, including the tool's own recommended Washington, DC query. The MCP ships with 434 regression tests (183 offline plus 251 live-gated) at 72.3 tests per tool.

| Metric | Value |
|---|---|
| MCP tools exposed | 6 |
| Total regression tests | 434 (183 offline, 251 live-gated) |
| Tests per tool | 72.3 |
| Audit rounds completed | 7 |
| P0 catastrophic bugs found and fixed | 1 (path traversal) |
| P1 silent-wrong-data bugs found and fixed | 23 |
| P2 validation gaps found and fixed | 21 |
| P3 cleanup items found and fixed | 10 |
| Round 7 (independent re-audit) findings | 14 |
| Current release | 1.0.1 |
| PyPI status | Published as `gsa-perdiem-mcp`, auto-publishes via Trusted Publisher on tag push |

## What Was Tested

The MCP exposes 6 tools covering the GSA Per Diem API surface. Testing covered all of them end-to-end.

**Core lookups:** `lookup_city_perdiem`, `lookup_state_rates`, `lookup_zip_perdiem`, `get_mie_breakdown`

**Workflow tools:** `estimate_travel_cost`, `compare_locations`

Each tool was exercised for argument validation, input sanitization, URL encoding, city-name normalization across punctuation variants, response-shape guarantees, error translation, estimate math recomputed by hand against FTR 301-11.101, and real-world data handling against the live production API with a real `api.data.gov` key.

## How It Was Tested

### Testing discipline

Prior unit tests in v0.1.x awaited raw coroutines and mocked the HTTP layer. The hardening program switched to invoking tools through `mcp.call_tool(name, kwargs)` the way a real MCP client does, and round 6 added live audits with a real `api.data.gov` key. Round 7 exposed the residual failure mode: shape-only live assertions (`isinstance(data, dict)` plus key presence) let a false WARNING ride through 240 "passing" live tests, and a misread of the API's server-side city resolution got canonized as a bug fix. Round 7's tests assert semantics: match types, dollar values, and OCONUS behavior.

### Audit rounds

| Round | Scope | Finding class |
|---|---|---|
| 1 | Live probes with DEMO_KEY (rate-limit constrained) | Bug surface identified across all 6 tools |
| 2 | Deeper probes, response-shape fuzz | 20 response-shape crash paths |
| 3 | Validation gap audit | 21 P2 validation issues |
| 4 | Static review | 10 P3 polish items |
| 5 | Initial patches shipped at 0.2.0 with 52 bugs fixed | First integration of all prior findings |
| 6 | Live audit with a real `api.data.gov` key, then a 240-test live sweep at 0.2.5 | 3 P1 findings (one later overturned; see round 7) |
| 7 | Independent full-source re-audit with live verification (stronger model), shipped at 1.0.1 | 14 findings, incl. reversal of the round-6 unmatched-city diagnosis |

### Live audit status

Rounds 1, 6, and 7 ran against the production Per Diem API. The repository includes 251 live-gated regression tests executable via `MCP_LIVE_TESTS=1 PERDIEM_API_KEY=... pytest`. Note the gate variable: earlier versions of this document said `PERDIEM_LIVE_TESTS=1`, which was never the gate and silently skipped every live test. The `api.data.gov` key is free (1,000 req/hr) and not gated behind an approval workflow.

## Round 7 (1.0.1): Independent re-audit

14 findings, all fixed in 1.0.1:

| # | Finding | Fix |
|---|---|---|
| 1 | **False WARNING on API-resolved cities (reversal of the round-6 headline).** The city endpoint resolves city-to-county-to-NSA server-side: Washington/DC returns "District of Columbia", McLean and Tysons return the DC NSA, Penasco returns Taos (Penasco IS in Taos County; the round-6 story that this was silent wrong data misread correct behavior). The unmatched-name path stamped these correct answers `unmatched_nsa` with "WARNING ... first NSA in the state -- verify", including the docstring's own recommended DC query. Second-order risk: with several resolved rows (Arlington returns DC/Loudoun/Wallops Island) the code took `nsa[0]` on an undocumented ordering. | New `api_resolved` match type: a response with NSA rows and no Standard Rate row is trusted as GSA's own resolution and explained neutrally; among several rows the one whose county mentions the query wins and the rest surface as `other_candidates`. `standard_fallback` still applies when a Standard Rate row is present. |
| 2 | `compare_locations` labeled rows by the MATCHED entry, producing nonsense like "District of Columbia, VA" for Arlington, and stripped all match metadata. | Rows are labeled by the query; `matched_city`, `match_type`, and `is_standard_rate` are included per row. |
| 3 | OCONUS states returned empty success: `lookup_state_rates("HI")` gave `nsa_count: 0, rates: []`, reading as "standard CONUS rate applies in Hawaii", a real IGCE underestimate trap. | AK/HI/AS/GU/MP/PR/VI short-circuit (no API call burned) with an explicit pointer to DoD DTMO (non-foreign OCONUS) and State Dept (foreign) rates, on all city/state/estimate/compare paths; the ZIP empty-result error mentions it. |
| 4 | `travel_month` accepted any word whose first three letters spelled a month: "Mayhem" was May, "Janitor" was Jan. | Exact 3-letter abbreviations or exact full month names only, case-insensitive. |
| 5 | Null or unparseable month values became $0 rates, poisoning `lodging_min`, faking seasonal variation, and pricing lodging at $0 downstream; "107.0" string values also became 0. | Non-positive/unparseable values are tracked as `months_without_data` instead of entering the rate table; float-strings parse correctly. |
| 6 | `estimate_travel_cost` silently priced lodging at $0 when monthly data was absent, and reported the requested `rate_month` even when it had fallen back to the max rate. | $0 lodging or M&IE now refuses with an explicit error instead of emitting a wrong dollar total; `rate_month` reports "MAX" plus a `month_fallback_note` when the requested month had no published rate. |
| 7 | Fiscal-year floor admitted five dead years: FY2015-2019 pass validation but the rates endpoints serve nothing before FY2020 (live-verified). | Floor raised to 2020; empty results for the upcoming FY note that GSA posts new-FY rates in late August. |
| 8 | `lookup_city_perdiem` docstring inverted the fallback priority order. | Docstring now matches the code (exact, composite, api_resolved, standard fallback). |
| 9 | Pasting a real NSA display name ("Boston / Cambridge") was rejected as invalid: GSA's own published composite names contain slashes. | Slashes sanitize to spaces in validation, URL encoding, and match normalization; "Boston / Cambridge" now exact-matches. Backslashes and control characters stay rejected. |
| 10 | DEMO_KEY limit texts audited: the code says ~10 req/hr; api.data.gov's generic docs say 30/hr, 50/day. | Live header check (`x-ratelimit-limit: 10`) confirms this API sets 10/hr, so the code text STANDS and smithery.yaml's "30/hr, 50/day" was corrected to match live reality. |
| 11 | Docs attributed all OCONUS rates to the State Department. | Non-foreign OCONUS (AK/HI/territories) is DoD (DTMO); foreign is State Dept. Corrected in module docstring and readme. |
| 12 | readme linked TESTING.md; the file is testing.md (404 on GitHub, case-sensitive). | Link lowercased. |
| 13 | changelog 0.1.0 claimed "7 MCP tools"; the server has always exposed 6. | Corrected with a note. |
| 14 | `serverInfo.version` reported an empty string. | `MCPServer(..., version=__version__)`; a regression test pins package/server version agreement. |

### Corrections to the prior record (round 7)

The following claims in earlier versions of this document were false and are corrected here; historical tables below are annotated "[Corrected in round 7]" where they repeated them.

- **Wrong live-gate env var, stated twice:** `PERDIEM_LIVE_TESTS=1` was never the gate; both test files gate on `MCP_LIVE_TESTS=1`. Following the documented command silently skipped all live tests while reporting green.
- **Phantom test file:** the coverage table listed `tests/stress_test_r6.py`; the actual round-6 file is `tests/test_live_audit_r6.py`.
- **Round-6 "zero new bugs" was shape-blind:** its 240 tests asserted dict-ness and key presence, not correctness; Arlington, VA was in the tested set while carrying the false WARNING of finding 1.
- **Misdiagnosed round-6 headline:** "Penasco returned Taos" and "Santa Rosa Beach returned Fort Walton Beach" were correct county-based resolutions, not silent wrong data; the resulting "fix" created finding 1.
- **compare_locations claims:** "50-location cap" and "concurrent fetching with a bounded semaphore" were false; the cap is 25 and fetching is sequential with a 0.3s sleep (deliberately, for rate-limit hygiene). The changelog was the accurate record.
- **Phantom 429 retry:** "exponential backoff retry added" was false; no retry exists (deliberate given the quota).
- **Phantom empty-key rejection with logged warning:** empty `PERDIEM_API_KEY` silently falls back to DEMO_KEY; the module has no logging.
- **standardRate-field claims:** the code matches the "Standard Rate" name BY DESIGN because the API's `standardRate` field is always "false" (live-confirmed); prior text claimed the opposite mechanism.
- **Phantom month-int support:** "1-based int accepted" was false; ints raise.
- **Phantom None-month filtering:** "None values filtered with a clear no-data response" was false until round 7 implemented it.
- **Phantom zero-rate flag:** `reason="no_rate_available"` appeared nowhere in the code; round 7 implements an explicit refusal instead.
- **Phantom St/Saint equivalence and unicode normalization:** neither existed in code; live queries like "Saint Louis" and "Penasco" succeed because the API resolves them server-side.
- **Wrong city length cap:** documented 200, code caps at 100.
- **Stale version and counts:** "0.2.5" and "172 regression tests"; and the round numbering conflicted with the changelog (this document called the 240-test sweep "Round 7" while the changelog called it round 6; the changelog wins, and this audit is round 7).
- **Overstated error surfacing:** compare_locations errors are truncated to 200 chars, not surfaced fully.

## Issues Found and Fixed (rounds 1-6)

### Priority 0: Path traversal

| Issue | Fix |
|---|---|
| `urllib.parse.quote(city)` with default `safe='/'` left `/` and `.` unencoded; `city="../../admin"` hit a different GSA endpoint entirely. Affected `lookup_city_perdiem`, `estimate_travel_cost`, `compare_locations`. | All city names URL-encoded with `safe=''`; path-traversal probes cover all three tools. Round 7 relaxed slash INPUT (sanitized to spaces for composite NSA names) while keeping the encoding airtight. |

### Priority 1: Live-audit findings (round 6)

| Issue | Fix |
|---|---|
| **Typographic apostrophe not normalized.** `city="Martha's Vineyard"` with U+2019 mismatched and silently returned Andover, MA. | `_normalize_for_match()` treats apostrophes (straight and curly), hyphens, periods, commas (and, since round 7, slashes) as whitespace. |
| **Unmatched city fell back to `rates[0]`.** [Corrected in round 7] The round-6 evidence cases (Penasco, Santa Rosa Beach) were actually correct API resolutions; the real defect was the missing match-type taxonomy. The `match_type`/`match_note` fields stand, and round 7 replaced the false-warning `unmatched_nsa` path with `api_resolved`. |
| **Punctuation-sensitive matching.** "St Louis" (no period) mismatched. [Corrected in round 7] Punctuation normalization is real, but the claimed St/Saint word-equivalence never existed; the API's own resolution is what makes "Saint Louis" work. |

### Priority 1: Response-shape crashes

Twenty bugs in this class from XML-to-JSON shape collapse. Representative items (all still guarded):

| Issue | Fix |
|---|---|
| `months` as None, single-dict collapse, None entries, missing keys crashed parsing. | `_safe_dict`/`_as_list` coercion throughout. |
| Month value None crashed `min()`. | [Corrected in round 7] The 0.2.x "fix" coerced to $0, which poisoned mins and seasonal flags; round 7 tracks them as `months_without_data`. |
| `meals` None broke arithmetic. | `_safe_int` coercion; round 7 adds the $0-refusal in estimates. |
| `r.json()` on HTML/empty bodies. | Content-type inspection and clear error translation. |
| `compare_locations` unbounded input. | [Corrected in round 7] Cap is 25 and fetching is sequential with a 0.3s sleep; earlier claims of 50 + semaphore were false. |
| `travel_month` silent fallthrough. | [Corrected in round 7] Prefix matching accepted "Mayhem"; exact matching shipped in 1.0.1. Int months were never supported. |
| Zero lodging produced `lodging_total=0`. | [Corrected in round 7] The claimed `no_rate_available` flag never existed; 1.0.1 refuses with an explicit error. |
| `is_standard_rate` derivation. | [Corrected in round 7] Name-matching is the DESIGN because the API's `standardRate` field is always "false"; prior text claiming field-derivation was wrong. |

### Priority 2: Validation gaps

Twenty-one bugs: fiscal-year bounds (round 7 tightened the floor to the live-verified 2020), city length cap (100 chars; earlier text said 200), control-char and null-byte rejection, USPS state validation, `num_nights` 1-365, ZIP+4 truncation, api-key URL-encoding, and docstring/behavior alignment. [Corrected in round 7] The claimed 429 retry and empty-key logged warning were never implemented; unicode normalization does not exist (the API handles non-ASCII server-side).

### Priority 3: Cleanup items

Ten items including the computed fiscal year default, USER_AGENT currency, and client lifecycle. Round 7 added the `serverInfo.version` fix.

## Test Coverage

The repo ships 434 regression tests (183 offline, 251 live-gated). All pass on every release cycle; live tests require `MCP_LIVE_TESTS=1` plus a key.

| File | Purpose | Test count |
|---|---|---|
| `tests/test_validation.py` | Main regression suite covering rounds 1-6 findings, incl. 8 live-gated integration tests | 173 |
| `tests/test_live_audit_r6.py` | Round 6 live sweep: 50 states, 20 ZIPs, all 12 months, FY2020-FY2026 (shape assertions; kept as breadth coverage) | 240 (all live-gated) |
| `tests/test_audit_r7.py` | Round 7 regressions: api_resolved semantics, OCONUS guards, month hygiene, zero-rate refusal, honest compare labels, exact month matching, FY floor, serverInfo version; 3 live confirmations | 21 (18 offline, 3 live-gated) |
| `tests/stress_test.py` | Round 1 DEMO_KEY live-probe scenarios (scenario script, not pytest) | N/A |

Regression tests invoke tools through the MCPServer registry (`mcp.call_tool`). An autouse fixture resets `srv._client` between tests.

## Release History

| Version | Focus | Outcome |
|---|---|---|
| 0.1.1 | Initial release: 6 tools with basic unit tests | Basic coverage |
| 0.2.0 | Full 52-bug fix across 5 audit rounds plus the round-6 live audit | 1 P0, 23 P1, 21 P2, 10 P3 resolved |
| 0.2.1 | Cross-MCP `extra='forbid'` back-port from sam-gov-mcp 0.3.1 | +1 regression test |
| 0.2.5 | 240-test live sweep (round 6 second pass) | Density lifted to 68.8 tests/tool; shape-only assertions (see round 7) |
| 1.0.0 | mcp 2.x SDK rebase, version sync, packaging | Stable baseline |
| 1.0.1 | Round 7 independent re-audit with live verification | 14 findings resolved, incl. reversal of the round-6 unmatched-city diagnosis |

## Cross-MCP Context

This MCP is one of eight servers in the 1102tools federal-contracting MCP suite (`bls-oews-mcp`, `ecfr-mcp`, `federal-register-mcp`, `gsa-calc-mcp`, `regulationsgov-mcp`, `sam-gov-mcp`, `usaspending-gov-mcp`, and this one). All eight were hardened under the same playbook. Patterns that originated here:

- **The "run a live audit with a real API key, not just mocks" discipline** was formalized here. Round 7 refined it: live tests must assert SEMANTICS (match types, dollar values), not response shape, or they bless wrong answers.
- **The `_normalize_for_match()` helper** was exported to other MCPs that do fuzzy-name matching.
- **The `match_type`/`match_note` taxonomy** originated here; round 7 taught the companion lesson that a "fallback warning" must first check whether the upstream API already resolved the query correctly.
- **Understand the API's resolution model before labeling it broken** (round 7): GSA resolves city to county to rate area server-side; what looked like silent wrong data was the feature working.

## What Was Not Tested

- **OCONUS rates.** This MCP covers CONUS per diem only. Non-foreign OCONUS (AK/HI/territories) rates are DoD (DTMO); foreign rates are State Dept. The tools now say so instead of returning empty successes.
- **Rate-limit behavior at scale.** DEMO_KEY is 10 req/hr (live-measured); a real `api.data.gov` key is 1,000 req/hr. No client-side throttling beyond compare_locations' pacing sleep; no retry on 429 (deliberate).
- **Fiscal year transition day.** October 1 rollover behavior was tested in principle but not live-audited across a real FY transition.
- **The multi-row ordering contract.** When the API returns several resolved rate areas, round 7 prefers the county mentioning the query and surfaces the rest as `other_candidates`; the upstream ordering itself is undocumented.

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root and can be re-executed by anyone. The live suite runs with `MCP_LIVE_TESTS=1 PERDIEM_API_KEY=... pytest` using a free `api.data.gov` key.

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 during the original hardening playbook, and Claude Code Fable 5 for the round 7 independent re-audit (full-source review, live API verification, hand-recomputed estimate math, record correction).

Round 7 methodology: re-read the entire server source with no reliance on this document's claims; verify match behavior against live API resolution for a dozen city shapes; recompute FTR 301-11.101 estimate math by hand; probe dead fiscal years and OCONUS states live; check every prior claim in this document against the code and live behavior.

Test count: 434 regression tests (183 offline + 251 live-gated). Tests per tool: 72.3. Total findings across all rounds: 69. Current version: 1.0.1. PyPI: `gsa-perdiem-mcp`.

Source: github.com/1102tools/federal-contracting-mcps/tree/main/servers/gsa-perdiem-mcp. License: MIT.


## Round 8 (2026-08-18): suite-wide live verification (super-cycle)

The full live-gated suite ran wholesale against production for the first time
(historically prevented by key quotas): 435 passed after one drift fix (5m22s). No new server
defects. Upstream drift caught and fixed: GSA published new-FY rates and 'Santa Rosa Beach, FL' began resolving as a real NSA (api_resolved, Okaloosa/Walton, monthly data), which is correct server behavior; the unmatched-city test now uses a town that will stay unmatched. Added `tests/test_audit_r8.py`: 4
one-call-per-test live contract anchors re-stamping this server's headline
fixes against production (all verified green on landing), a suite-wide pacing
conftest with a `live_smoke` marker, and a per-test client reset so batched
live runs cannot hit the cached-AsyncClient/closed-event-loop trap.
