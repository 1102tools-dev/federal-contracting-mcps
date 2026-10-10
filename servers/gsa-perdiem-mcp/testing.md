# GSA Per Diem Rates MCP: Testing Record

## Round 3 (2026-10-10): travel worksite content audit, 1.2.4 candidate

A new 101-question corpus exercised all seven tools on published 1.2.3: eighteen new regional destinations, thirteen state inventories, seasonal and historical FY2023/25/26/27 estimates, worksite ZIPs, installations, comparison follow-ups, an ambiguous ZIP county choice and the OCONUS handoff. A fresh by-name PyPI installation replayed 99 keyless answers and two expected key-required city-only paths. The 99 include the two incorrect county refusals documented here, rather than 99 successful rate lookups.

One **P2** finding: valid White Sands Missile Range worksite queries in Doña Ana County were rejected as `invalid_county`, including plain `Dona Ana` and accented county follow-ups. Official Army/USGS geography establishes the headquarters county; the GSA FY2027 workbook assigns its standard $113 lodging/$68 M&IE ceilings, giving $396 for two May nights with actual arrival/departure M&IE. The Census files are UTF-8, but the builder decoded them as Latin-1, corrupting the county key. The corrected builder and Python/Worker accent matching regenerate the place index while preserving every rate snapshot and official source hash.

Seven new Python regressions fail before and pass after. Current candidate validation: **583 collected Python tests: 316 passed, 267 optional live-gated skipped**; **29 Worker passed**; type check passed; **1,368 parity calls: 1,361 identical, seven documented parser differences, zero unexplained differences**. Seven tool contracts remain unchanged. The actual candidate wheel replays the 101 questions, correcting the two blocked originals; publication and hosted D1 activation remain pending root release verification.

Independent fresh official XLSX/Word parsing checked 96 original numeric answers and 98 answers after substituting the two corrected candidate originals, with zero mismatches. The two city-only public API answers remain source-checked public answers; local keyless CLI does not execute those API paths. All 20 unique GSA/Census source files match the manifest hashes (17 GSA and three Census). Evidence, exact questions, original answers, expected answers, source captures and candidate replays are retained in Workspace/Artifacts/mcp-e2e-20261010/round3/gsa-perdiem. The existing GSA Per Diem data-load workflow must activate the new places part in hosted D1; local loader acceptance records the expected snapshot identity. Source limitations and supported-scope enhancements are recorded separately from this confirmed defect.

## Round 2 (2026-10-10): published 1.2.3 content audit

This is round 2 of the October 10 suite-wide content audit; the earlier server audit rounds remain below. Current release: **1.2.3**, verified through the actual published PyPI CLI and public MCP endpoint at source commit `7754923b8c77e51022e2c561856fd6ccf4eab874`. The publication-pending statements in the historical 1.2.3 candidate record below are superseded by this verification.

**59 realistic questions and useful follow-ups exercised all seven tools**, with zero new confirmed P0, P1, P2 or P3 findings. Coverage included multi-site IGCE state inventories; city/county and ZIP work-site resolution; seasonal lodging; installation rates; meal components; historical comparisons; conservative undated estimates; fiscal-year split lodging; and the explicit OCONUS handoff. The corpus contains one data-status call, three M&IE breakdowns, seven state inventories, 25 city lookups, ten ZIP lookups, twelve estimates and one location comparison.

The actual installed published CLI replayed all 59 cases: **55 bundled task answers matched the public answers**, while **four API-dependent cases returned the expected missing-key response** in the keyless local environment. Those four were city-only Denver, Norfolk and Austin queries and an unbundled FY2020 Charleston query; they are not counted as completed keyless rate lookups. County-resolved cities in bundled fiscal years were exercised without an API key.

Independent parsers compared **54 question results** with official GSA workbooks and M&IE documents for **FY2021, FY2024, FY2026 and FY2027**, finding zero mismatches. Checks included seasonal monthly rates, state inventories, meal-table cells and all **twelve estimates independently recomputed** from official lodging and M&IE rates, applying the first/last-day rule once per actual trip. Fresh downloads matched **all 17 saved official source hashes**. These counts describe the checked corpus, not universal source coverage. Source documents are available through [GSA's per diem files](https://www.gsa.gov/travel/plan-a-trip/per-diem-rates/per-diem-files); trip-day treatment follows [41 CFR 301-11.20](https://www.ecfr.gov/current/title-41/subtitle-F/chapter-301/subchapter-B/part-301-11/subpart-A/section-301-11.20).

Source limitations remain explicit. The public FY2020 Charleston fallback reported no rates found, but direct authenticated upstream access could not be independently checked without operator credentials. This is **source-access uncertainty, not authoritative evidence that no historical rate exists**; the official historical workbook is an alternative and expanding the bundle is an enhancement. Date-aware itineraries and multiple-traveler totals remain outside the schema. For a monthly split, add only monthly lodging totals and calculate M&IE once over actual travel days.

Separate regression validation recorded **576 Python tests collected: 309 passed and 267 optional live-gated tests skipped**, **28 Worker tests passed**, and a passing type check. All seven reviewed tool contracts were unchanged. **1,368 parity calls** yielded 1,361 identical answers, seven documented parser-message differences and zero unexpected differences. No new runtime patch or regression test was needed because the content audit found no confirmed defect.

Evidence is retained in Workspace/Artifacts/mcp-e2e-20261010/round2/gsa-perdiem: `checkpoint.json`, `live-corpus.json`, `installed-cli.json`, `source-comparisons.json` and `source-hashes.txt`. An independent BLS peer review checked the corpus distinctions and recomputed all twelve saved estimates without finding a blocker.

## 1.2.3 follow-up: correct published split-trip guidance

The [current official OpenAI maintenance rules](https://developers.openai.com/plugins/deploy/app-review#how-published-mcp-metadata-versions-work) use continuous review for tool-definition updates within an existing plugin. Updated definitions replace previous definitions automatically after checks; a new plugin version or directory resubmission is not required for these description corrections. The `estimate_travel_cost` description now tells callers to add only monthly `lodging_total` and calculate M&IE once over actual travel days. This resolves the description limitation recorded in the 1.2.2 audit below; the runtime arithmetic and guidance are unchanged from that patch.

The established Python 3.12 generator updated the tool contract. The reviewed diff changes the estimate and data-status descriptions; all seven tool names, schemas, annotations and metadata identifiers remain identical. A read-only USAspending peer review found no blocker. The actual Python and Worker `tools/list` responses have explicit regression tests; the Python regression fails against the old 1.2.2 wheel and passes after correction.

Current source validation: **576 Python collected: 309 passed and 267 live-gated skipped**; **28 Worker passed**; type check passed; **1,368 parity calls: 1,361 identical, seven documented parser-message differences, zero unexplained differences**. Publication and actual hosted/PyPI checks await the serial 1.2.3 follow-up release; the in-flight 1.2.2 release remains immutable.

## Round 10 (2026-10-10): realistic content audit, 1.2.2 candidate

1.2.2 validation: **574 collected Python tests: 307 passed, 267 live-gated skipped**; **27 Worker tests passed**; type checks passed; **1,368 parity calls: 1,361 identical, 7 documented parser-message differences, zero unexplained differences**. The seven published tool definitions remain unchanged. A freshly built 1.2.2 wheel passes all ten new content regressions in an isolated environment.

Twenty-five hosted calls covered every tool, current and historical M&IE, seasonal rates, ambiguous ZIPs and county follow-ups, independent cities, unknown cities, OCONUS, malformed inputs, one-night and long-stay estimates, comparisons with partial errors, and split-month arithmetic. All 17 current official GSA source hashes match the bundled data. An independent parser comparison against the verified GSA FY2027 workbooks finds zero mismatches for 40,426 ZIPs and 295 destinations.

Four content findings affected 1.2.1:

- **P2:** adding separate monthly estimates overstated M&IE by 50% of the daily rate per join. Runtime guidance now adds only monthly lodging and calculates M&IE once across actual travel days. The Washington two-plus-two-night example yields $460 when incorrectly summed versus the correct $414 M&IE.
- **P2:** city-limit carve-outs ignored contradictory supplied counties (Cambridge/Essex, Santa Monica/San Diego, Sedona/Maricopa). Known Census place/county conflicts now return `invalid_county` without asserting a rate or estimate. Valid carve-outs and installations remain covered.
- **P3:** malformed ZIP+4 suffixes were silently discarded. Entire ASCII five-digit or five-plus-four-digit inputs are validated before the five-digit lookup.

All ten new Python regressions failed on the original code and pass after the fixes; Worker regressions and an 18-call parity scenario cover the findings and follow-ups. Evidence lives in Workspace/Artifacts/mcp-e2e-20261010/gsa-perdiem.

- **P3:** comparison rows dropped source attribution available to single-location lookups. Resolved and unresolved rows now retain the GSA source link and bundled fiscal year; raw comparison rates and ranking are unchanged.

**1.2.2 description limitation, resolved by the 1.2.3 follow-up above:** the frozen description in 1.2.2 retained the incorrect instruction to add separate monthly estimates. Current official continuous-review rules support correcting it within the existing MCP identity without directory resubmission. The description and baseline are corrected in 1.2.3; actual hosted/PyPI checks await the follow-up publication. Date-aware itinerary pricing and ZIP candidate state/county provenance remain enhancements.

## Round 9 (2026-10-10): content-test corrections and 1.2.1 release verification

Current suite: **564 collected Python regressions: 297 offline passed and 267 live-gated skipped**. The server exposes **7 tools**. Nine audit rounds are documented through this content-test round. Worker validation is separate: **23 tests passed**, type checks passed, and **1,350 parity calls** had 7 documented parser-message differences and zero unexplained differences.

| Finding | Regression evidence |
|---|---|
| Unrecognized Milton, OH must not inherit Hamilton's rate | `test_city_resolution.py`: unresolved city, comparison result, complete slash-part table, and legacy-selector checks; 9 Python and 2 Worker cases failed before the fix |
| ZIP county input must survive the resolved rate definition | `test_snapshot.py::test_zip_county_answer_keeps_the_supplied_county`; matching Worker regression failed before |
| Trips price each night using one month; long stays need an agency-rate note | `test_snapshot.py` estimate notes and citation checks; 3 Python cases and corresponding Worker case failed before |
| FY2025 M&IE filename remains applicable to FY2027 | M&IE source-note regressions in Python and Worker failed before |
| Seasonal state lists need lodging months | Python and Worker seasonal-month regressions failed before |

Independent source comparison found zero differences for all 40,426 FY2027 ZIPs and 295 published destinations. Findings replay covered Q1-Q42 (including Q40b and combined comparison groups) in 42 calls: Python and Worker answers identical; lodging values, estimate arithmetic, five M&IE tiers and targeted resolution behavior passed source-backed assertions. Most replay API envelopes reconstruct the findings' reported resolutions from downloaded GSA rate files; Milton and Bethesda use raw captures. This replay does not prove fresh upstream city behavior. Direct Bedford MA source probes with DEMO_KEY returned HTTP 429 before and after release; that separate direct-source check was skipped. After release, all 42 findings repro calls passed against the real hosted MCP endpoint using its normal publisher-key service path, including Milton unresolved behavior, ZIP county preservation, seasonal monthly rates, trip notes and M&IE labeling. Hosted values were checked against the independently downloaded GSA files and saved M&IE API capture.

Deferred P3 work: month order/calendar-year labels, per-candidate ZIP county/state provenance (requires schema/loader migration), and date-aware per-night pricing. Multi-month guidance, supplied-county preservation, long-stay notes and the current 41 CFR 301-11.20 citation are included. Version **1.2.1** was published as [`gsa-perdiem/v1.2.1`](https://github.com/1102tools-dev/federal-contracting-mcps/releases/tag/gsa-perdiem%2Fv1.2.1) at commit `e9fd0d77ec795bc41498033ffc70ef65f317c087`. [Release workflow 38059809457](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38059809457) completed successfully, including hosted deployment, PyPI, MCP registry and GitHub release. The standard hosted release verifier confirmed that exact SHA, version 1.2.1, the seven-tool contract, admission settings and publisher-key live city lookup. A fresh isolated installation of [the actual PyPI 1.2.1 distribution](https://pypi.org/project/gsa-perdiem-mcp/1.2.1/) confirmed its version and module path outside the checkout, matched all seven tool definitions, and passed bundled ZIP/county, M&IE and seasonal-state checks plus Milton/Gardiner matching with raw captured GSA responses supplied as mocks. The installed-package mock checks made no fresh upstream requests.

## Executive Summary

This Model Context Protocol server exposes the GSA Per Diem Rates API as 7 callable tools for federal travel lodging and M&IE rate lookups used in IGCEs and travel cost estimation. Its original hardening program covered seven audit rounds, three of them live audits against the production API; rounds 8 and 9 are recorded separately below and above. The 0.2.x program surfaced 55 bugs. Round 7 (1.0.1), an independent full-source re-audit with live verification, found 14 more and overturned a round-6 headline: the "catastrophic silent-wrong-data" cases (Penasco returning Taos, Santa Rosa Beach returning Fort Walton Beach) were actually the API's CORRECT city-to-county rate-area resolution, and the round-6 "fix" had been stamping false WARNINGs on right answers, including the tool's own recommended Washington, DC query. The current suite collects 583 Python regression tests (316 offline plus 267 live-gated); the historical audit totals below describe their original rounds.

| Metric | Value |
|---|---|
| MCP tools exposed | 7 |
| Total regression tests | 583 (316 offline, 267 live-gated) |
| Tests per tool | 83.3 (Python only) |
| Audit rounds completed | 10 |
| P0 catastrophic bugs found and fixed | 1 (path traversal) |
| P1 silent-wrong-data bugs found and fixed | 23 |
| P2 validation gaps found and fixed | 21 |
| P3 cleanup items found and fixed | 10 |
| Round 7 (independent re-audit) findings | 14 |
| Current release | 1.2.3 (published CLI and public endpoint verified) |
| PyPI status | Published as `gsa-perdiem-mcp`, auto-publishes via Trusted Publisher on tag push |

## 1.0.4 Safety Release Verification

The complete offline suite passed 186 tests with 255 live tests gated. Shared
pacing tests verified the 4-second default, cross-process serialization, and a
shared `api.data.gov` bucket with Regulations.gov when both use the same key.
No federal API was called.

## What Was Tested

The MCP exposes 7 tools covering published GSA files and the GSA Per Diem API surface. Testing covered all of them end-to-end.

**Data status:** `get_data_status`

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

Rounds 1, 6, and 7 ran against the production Per Diem API. The repository includes 267 live-gated regression tests executable via `MCP_LIVE_TESTS=1 PERDIEM_API_KEY=... pytest`. Note the gate variable: earlier versions of this document said `PERDIEM_LIVE_TESTS=1`, which was never the gate and silently skipped every live test. The `api.data.gov` key is free (1,000 req/hr) and not gated behind an approval workflow.

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
| 1.0.3 | Opt-in production pacing for personal-key traffic | Multi-request and concurrent operations share a completion-to-start gate; offline regressions added |

## Cross-MCP Context

This MCP is one of eight servers in the 1102tools federal-contracting MCP suite (`bls-oews-mcp`, `ecfr-mcp`, `federal-register-mcp`, `gsa-calc-mcp`, `regulationsgov-mcp`, `sam-gov-mcp`, `usaspending-gov-mcp`, and this one). All eight were hardened under the same playbook. Patterns that originated here:

- **The "run a live audit with a real API key, not just mocks" discipline** was formalized here. Round 7 refined it: live tests must assert SEMANTICS (match types, dollar values), not response shape, or they bless wrong answers.
- **The `_normalize_for_match()` helper** was exported to other MCPs that do fuzzy-name matching.
- **The `match_type`/`match_note` taxonomy** originated here; round 7 taught the companion lesson that a "fallback warning" must first check whether the upstream API already resolved the query correctly.
- **Understand the API's resolution model before labeling it broken** (round 7): GSA resolves city to county to rate area server-side; what looked like silent wrong data was the feature working.

## What Was Not Tested

- **OCONUS rates.** This MCP covers CONUS per diem only. Non-foreign OCONUS (AK/HI/territories) rates are DoD (DTMO); foreign rates are State Dept. The tools now say so instead of returning empty successes.
- **Rate-limit behavior at scale.** DEMO_KEY is for exploration; a registered `api.data.gov` key has the published 1,000/hour allowance. Every request now uses a provisional 4-second cross-process gate, shared with Regulations.gov for the same key, and honors `Retry-After` without automatic retries.
- **Fiscal year transition day.** October 1 rollover behavior was tested in principle but not live-audited across a real FY transition.
- **The multi-row ordering contract.** When the API returns several resolved rate areas, round 7 prefers the county mentioning the query and surfaces the rest as `other_candidates`; the upstream ordering itself is undocumented.

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root and can be re-executed by anyone. The live suite runs with `MCP_LIVE_TESTS=1 PERDIEM_API_KEY=... pytest` using a free `api.data.gov` key.

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 during the original hardening playbook, and Claude Code Fable 5 for the round 7 independent re-audit (full-source review, live API verification, hand-recomputed estimate math, record correction).

Round 7 methodology: re-read the entire server source with no reliance on this document's claims; verify match behavior against live API resolution for a dozen city shapes; recompute FTR 301-11.101 estimate math by hand; probe dead fiscal years and OCONUS states live; check every prior claim in this document against the code and live behavior.

Current test count: 583 Python regressions (316 offline + 267 live-gated), with 29 separate Worker tests. The original rounds reported 69 findings; later fixes are recorded above. Current release: 1.2.3 (published CLI and public endpoint verified). PyPI: `gsa-perdiem-mcp`.

Source: github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/gsa-perdiem-mcp. License: MIT.


## Round 8 (2026-08-18): suite-wide live verification (super-cycle)

The full live-gated suite ran wholesale against production for the first time
(historically prevented by key quotas): 435 passed after one drift fix (5m22s). No new server
defects. Upstream drift caught and fixed: GSA published new-FY rates and 'Santa Rosa Beach, FL' began resolving as a real NSA (api_resolved, Okaloosa/Walton, monthly data), which is correct server behavior; the unmatched-city test now uses a town that will stay unmatched. Added `tests/test_audit_r8.py`: 4
one-call-per-test live contract anchors re-stamping this server's headline
fixes against production (all verified green on landing), a suite-wide pacing
conftest with a `live_smoke` marker, and a per-test client reset so batched
live runs cannot hit the cached-AsyncClient/closed-event-loop trap.

## RC5 pacing remediation (2026-08-22)

Version 1.0.5 carries the suite-wide asynchronous pacing-lock correction. The full offline lane passed (186 tests; 255 live-gated tests skipped), including deterministic same-process concurrency coverage. The published PyPI wheel was then installed in an isolated cache and completed MCP startup and `tools/list` with 6 tools.
