# SAM.gov MCP: Testing Record

## Executive Summary

This Model Context Protocol server exposes seven SAM.gov REST APIs (Entity Management v3, Exclusions v4, Opportunities v2, Contract Awards v1, Federal Hierarchy v1, Acquisition Subaward Reporting, Assistance Subaward Reporting) plus the PSC lookup as 19 callable tools. It was hardened across ten audit rounds, the tenth being a ~230-call paced live campaign against production. Live audits surfaced seven catastrophic P1 silent-wrong-data bugs mocks could never catch (apostrophe-rejecting WAF, typo'd-parameter silent drops, empty PIID acceptance, `entityName` vs `exclusionName`, and three Subaward parameter casings). Round 9 (1.0.2), an independent full-source re-audit, found the worst one yet by replaying the documented Entity API response shape through the real pipeline: `get_entity_reps_and_certs` read the wrong JSON key casings, so its default summary mode returned EMPTY clause lists for every entity, and eight prior rounds never noticed because their live assertions only checked `totalRecords`. This MCP is also where the `extra='forbid'` cross-fix pattern was invented and exported to the rest of the suite. The MCP ships with 1,136 regression tests (762 offline, 374 live-gated), the highest count in the 1102tools MCP suite.

| Metric | Value |
|---|---|
| MCP tools exposed | 19 |
| Total regression tests | 1,136 (762 offline, 374 live-gated) |
| Tests per tool | 59.8 |
| Audit rounds completed | 10 |
| Total items addressed | 77 across releases |
| P1 silent-wrong-data bugs (live-audit-only) | 7 |
| Round 9 findings | 13 (8 fixed in 1.0.2; all 5 pending items live-resolved in round 10) |
| Round 10 findings | 10 (fixed/documented in 1.0.4 from a ~230-call paced live campaign) |
| Current release | 1.0.6 |
| PyPI status | Published as `sam-gov-mcp`, auto-publishes via Trusted Publisher on tag push |

## 1.0.6 Safety Release Verification

The complete offline suite passed 762 tests with 374 live tests gated. Shared
pacing tests verified same-key cross-process serialization, distinct-key
isolation, invalid overrides, and `Retry-After` behavior. Composite tools now
receive the same central pacing as direct tools. No SAM.gov request was made.

## Round 9 (1.0.2): Independent re-audit

Round 9 re-read the full source against the official API documentation and the SAM Functional Data Dictionary, replaying documented response shapes through the real tool pipeline. The SAM key's daily quota was exhausted mid-audit (every endpoint family 429'd), so findings split into two groups.

### Fixed in 1.0.2 (documentary evidence + offline replay)

| # | Finding | Fix |
|---|---|---|
| 1 | **`get_entity_reps_and_certs` read wrong JSON keys; default summary mode always returned empty clause lists.** The Entity API documents `certifications.fARResponses` and `certifications.dFARResponses` (mixed case) with `architectEngineerResponses` under `qualifications`; the code read `farResponses`/`dfarsResponses`/`certifications.architectEngineerResponses`, all nonexistent, so `_as_list(None)` produced `[]` for all three and a CO asking for FAR 52.212-3 answers was told the entity certified nothing. Survived 8 rounds because the round-6 live tests asserted only `"totalRecords" in data`. | Case-insensitive key scan resolving the documented casings (and any future drift), with `architectEngineerResponses` sourced from `qualifications` first. Documented-shape replay tests pin non-empty summaries and clause_filter matching. |
| 2 | Opportunities set-aside table had 14 of the 18 documented codes: LAS (Local Area), IEE and ISBEE (Buy Indian Act), and BICiv were unreachable, and the mixed-case BICiv could never have survived the upcasing validator. | All 18 codes accepted case-insensitively; the documented `BICiv` casing goes on the wire. |
| 3 | `business_type_code` whitelist covered 13 of the FDD's dozens of codes, blocking legitimate searches (NB Native American Owned, JV SDVOSB Joint Venture, A3 Labor Surplus Area, 1E/1S Buy Indian, A7 AbilityOne, M8 Educational Institution, ...). | Well-formed 2-character codes pass through to the API; the labeled table remains for docs; SBA certification codes still redirect to `sba_business_type_code`. |
| 4 | `purpose_of_registration` allowed only Z1/Z2/Z5 (Z3 IGT-Only and Z4 Assistance+IGT were pydantic-rejected) and mislabeled Z5 as "Supplemental grants only" (it is All Awards and IGT). | Full Z1-Z5 Literal with corrected descriptions. |
| 5 | Bracketed date ranges passed validation on the Opportunities single-date params, then crashed range-math with "too many values to unpack (expected 3, got 5)". | `allow_range=False` on the four Opportunities date params with a clean error; Contract Awards/Exclusions ranges unaffected. |
| 6 | `lookup_award_by_piid` promised "all modifications, sorted" but hardcoded limit=100, never sorted, and hid truncation. | Client-side modification-number sort (numeric mods in numeric order, then alpha) and a `_note` when totalRecords exceeds the returned page. Docstring states the 100-record page honestly. |
| 7 | Int coercion dropped meaningful leading zeros: `zip_code=6511` searched "6511" (New Haven is 06511), `cgac=75` searched "75" (HHS is 075, the readme's own example). | Digit inputs zero-pad to 5 (zip) and 3 (CGAC). |
| 8 | `__version__` stale at 1.0.0 while pyproject/USER_AGENT said 1.0.1 (the 1.0.0 changelog had claimed they were "now synchronized"); serverInfo.version unset. | All four synchronized at 1.0.2; MCPServer receives the package version; regression test pins it. |

### Round-9 pending items: all five live-resolved in round 10

| # | Suspicion | Live verdict (2026-08, fed-role keys) |
|---|---|---|
| 9 | `search_exclusions` size cap: code allows 100, docs say "1 to 10". | REFUTED. size=100 returned 100 records per page (totalRecords 168,188). Code correct; the docs are wrong. |
| 10 | PSC param casing: code sends `searchby`; docs say `searchBy`. | CLEARED, docs wrong not code. The API honors lowercase `searchby` and IGNORES camelCase `searchBy` (engineering+`searchby` switches to code mode and 404s; engineering+`searchBy` returns the same 126 hits as bare `q`). `lookup_psc_code` is correct; free-text search returns real results. |
| 11 | Opportunities date-span cap: local 364 vs documented "1 year". | CLEARED. 364-day span returns 200; 365- and 366-day spans return 400 "Date range must be no more than 1 year apart". The local cap is exactly the real boundary. |
| 12 | `fiscal_year` floor of 2008 may reject legitimate older data. | CONFIRMED BUG, worse than suspected: FY2007 has 4,112,136 records and data reaches back to FY1970 (FY1980: 634,349). Floor moved to 1970 with a 4-digit guard in 1.0.4 (the API silently returns an empty shape for 2-digit years like 24). |
| 13 | `registration_status` D/I may be silently ignored upstream. | CONFIRMED BUG, opposite failure: D and I are accepted and return 0 records for every query (dead values guaranteeing empty results; A=779,391, E=1,045,202, together the full population). Enum restricted to A/E in 1.0.4. Comma lists like "A,E" also match nothing. |

### Corrections to the prior record (round 9)

- **Test counts were stale and mutually inconsistent:** the header said 1,094 total (729/365), the coverage section said 448 (441 + 7), the live-audit section said 6 live-gated, and the methodology trailer said 816 (574 + 242) at "version 0.3.7". Actual collection: 1,125 (754 offline + 371 live-gated) at 1.0.2.
- "The MCP exposes 15 tools covering four SAM.gov REST APIs" contradicted the header's own 19 tools / 7 APIs. It is 19 and 7.
- The coverage table listed only 5 files, omitting `test_live_audit_r6.py`, `test_round_7.py`, `test_v0_4_features.py`, and `test_sba_business_type.py`; per-file counts were off by one (79 vs 80, 369 vs 368).
- The round-6 claim of covering the "364-day span boundary" is false: the test uses a 363-day window (04/24/2025 to 04/22/2026). The boundary remains unprobed (round 9 item 11).
- "All 14 set-aside codes" tested: circular validation against the server's own incomplete list; the API defines 18.
- The "response-shape guarantees" verification claims were hollow where it mattered most: no test in the repo referenced any fARResponses casing, and the PSC free-text "live" tests pass on zero results or swallowed errors (round 9 items 1 and 10).
- "Can be re-executed by anyone using a free SAM.gov API key" is misleading: a no-role personal key gets on the order of 10 requests/day per endpoint family, and the live suite needs hundreds of calls. A system account or federal key is realistically required for a full live pass.

## Round 8 (v0.4.0): Federal Hierarchy and FFATA Subaward Reporting

Added four new tools across three SAM.gov REST APIs: Federal Hierarchy (`/orgs`, `/org/hierarchy`), Acquisition Subaward Reporting, and Assistance Subaward Reporting, with 278 regression tests (155 offline including Hypothesis property tests, 123 live).

### P1 live-audit bugs found and fixed

1. **`PIID` (uppercase) silently ignored** by the Subaward API: the documented parameter name returned the unfiltered ~2.7M-record universe. Working casing is lowercase `piid`.
2. **`referencedIdvPIID` silently ignored.** Working casing is `referencedIDVPIID`.
3. **`referencedIDVAgencyID` silently ignored.** Working casing is `referencedIDVAgencyId`.

### P2 fixes

4. `fh_org_type` whitelist too strict (real API returns values like `Department/Ind. Agency`); replaced with WAF-safe + length clamp.
5. `status=ACTIVE` on Federal Hierarchy is a no-op (the API defaults to active-only); `INACTIVE` is the value that changes results. Documented.

Live coverage spans 11 department-level lookups, CGAC variants (020/097/075), pagination boundaries, response-shape checks, 5-way concurrent calls, and casing-regression canaries. Hypothesis property tests (300 examples each) target `_validate_date_yyyy_mm_dd`, `_normalize_fh_response`, and `_normalize_subaward_response`. Note (round 9): the three subaward casing claims are recorded as tested by named live tests that exist in the repo; their pass status could not be re-reproduced during round 9 because of quota; round 10 re-ran all three live on a fed-role key and they pass.

## Audit rounds

| Release | Audit context | Findings class |
|---|---|---|
| 0.2.0 | Pre-session baseline hardening | Baseline validation |
| 0.2.1 | First `extra='forbid'` application | Typo'd-parameter silent drops closed |
| 0.3.0 | Rounds 1-4: WAF, response-shape, validation, integrity | 28+ items incl. 5 response-shape crashes |
| 0.3.1 | Live audit with a real SAM.gov key | 3 P1 silent-wrong-data plus 1 P3 |
| 0.3.5 | Round 5: density expansion (368 parameterized tests) | No new bugs; coverage to ~30 tests/tool |
| 0.3.6 | Round 6: live audit, 235 live-gated tests | 1 P1: `entityName` vs `exclusionName` param |
| 0.3.7 | Round 7: Hypothesis property suite (~25,000 probes) | 2 P3 edge cases (`_safe_int` inf/nan; empty `_normalize_awards_response`) |
| 1.0.0/0.4.0 | Round 8: Federal Hierarchy + FFATA tools | 3 P1 casing bugs, 2 P2 |
| 1.0.1 | sbaBusinessTypeCode exposure; XX/A6 SBA code swap fix | 1 P1 (XX is HUBZone, A6 is 8(a)) |
| 1.0.2 | Round 9: independent full-source re-audit | 8 fixed, 5 pending live confirmation |

## Issues Found and Fixed (rounds 1-7)

### Priority 1: Live-audit silent wrong data

| Issue | Fix |
|---|---|
| **WAF filter rejected McDonald's, L'Oreal, and every apostrophe-containing name** based on guessed WAF rules; the real API accepts them all. | WAF filter narrowed to null bytes plus tab/CR/LF. Live probes include both names. |
| **Unknown parameters silently dropped** (`search_entities(keyword=...)` ran unfiltered, returning 736,007 entities). | `extra='forbid'` on every tool's arg model; invented here, exported suite-wide. |
| **`lookup_award_by_piid` accepted empty PIID** and returned an empty result with no warning. | Empty PIID raises with format examples. |
| **`search_exclusions(entity_name=...)` sent the invalid `entityName` parameter** (round 6). | Corrected to `exclusionName`. |

### Priority 1: Response-shape crashes

Five bugs from round-4 fuzzing: `totalRecords: null` crashes, `entityData` dict-vs-list XML collapse, missing `entityData` on partial responses, `excludedEntity` single-dict collapse, and string `"0"` totalRecords. All guarded via `_safe_int` and `_as_list`, both exported suite-wide.

### Priority 2: Validation gaps

UEI/CAGE format enforcement everywhere they appear, the opportunities date-span pre-check, length clamps on text filters, country-code uppercasing, WAF detection via status codes rather than body substrings, and calibrated pre-rejection limited to control characters. (Round 10: boundary live-verified exact; 364-day spans pass, 365 rejects.)

### Priority 3: Cleanup items

Empty-string filters, code-set validation, NAICS format, case normalization, and the opaque PSC 404 body translation. (Round 9 revised the code-set philosophy for business types: format-check plus pass-through, because the FDD set is far larger than any local table.)

## Test Coverage

The repo ships 1,136 regression tests (762 offline, 374 live-gated). All pass on every release cycle; live tests require `SAM_LIVE_TESTS=1` plus a key with real quota, are paced 2-4 s apart by `tests/conftest.py` (a round-10 guard: an unpaced full live pass once burned a key's whole daily quota in 105 seconds), and a minimal anchor subset runs via `pytest -m live_smoke`.

| File | Purpose | Test count |
|---|---|---|
| `tests/test_validation.py` | Rounds 1-4 plus live-audit regressions | 80 (74 offline + 6 live-gated) |
| `tests/test_density_r5.py` | Round 5 parameterized failure-mode buckets | 368 |
| `tests/test_live_audit_r6.py` | Round 6 live sweep across every tool | 154 (all live-gated) |
| `tests/test_round_7.py` | Hypothesis property suite | 133 |
| `tests/test_v0_4_features.py` | Round 8 Federal Hierarchy + FFATA (incl. 123 live) | 259 |
| `tests/test_sba_business_type.py` | 1.0.1 SBA code family (validation/mock/live) | 15 |
| `tests/test_audit_r9.py` | Round 9 regressions: documented-shape reps-and-certs replay, set-aside and business-type expansion, Z1-Z5, bracket-range rejection, zip/CGAC padding, PIID sort, version sync | 16 (all offline) |
| `tests/scenarios/` (stress_test.py, stress_test_r2.py, live_test.py) | Scenario scripts (retained for reproducibility) | N/A |

Regression tests invoke tools through the MCPServer registry (`mcp.call_tool`). An autouse fixture resets `srv._client` between tests.

## Release History

| Version | Focus | Outcome |
|---|---|---|
| 0.2.x | Baseline | Baseline coverage |
| 0.3.0 | Rounds 1-4 full audit | 5 P1 crashes, validation gaps resolved |
| 0.3.1 | First live audit | WAF recalibrated; `extra='forbid'` invented |
| 0.3.5 | Round 5 density | 368 new tests |
| 0.3.6 | Round 6 live sweep | `exclusionName` fix |
| 0.3.7 | Round 7 Hypothesis | 2 P3 edge cases |
| 0.4.0 | Round 8: FH + FFATA tools | 3 P1 casing bugs |
| 1.0.0 | mcp 2.x SDK rebase, packaging | Stable baseline |
| 1.0.1 | SBA business type family | XX/A6 swap fixed, sbaBusinessTypeCode exposed |
| 1.0.2 | Round 9 independent re-audit | Reps-and-certs key casing (data-destroying), set-aside/business-type/Z-code expansion, bracket-crash, PIID sort, padding; 5 items pending live confirmation |
| 1.0.4 | Round 10 paced live campaign | Fiscal-year floor 2008 -> 1970 with 4-digit guard; registration_status enum A/E only; offset documented as a zero-based page index on Opportunities and Contract Awards; 400k paging ceiling documented; past-end phantom-row and hang warnings; bare-string 200 bodies raised as errors instead of normalizing to silent zero results; assistance agency_code 4-digit validation; 429 message decoupled from key roles; UEI non-uniqueness documented (1.0.3 was a no-op pipeline-proof bump) |
| 1.0.5 | Version-marker sync | The 1.0.4 wheel self-reported 1.0.2 in serverInfo: the r9 item-8 pin test compared serverInfo to the same hardcoded `__version__` it was meant to guard (circular). All markers now derive from installed package metadata and the test pins against metadata. |

## Cross-MCP Context

This MCP is one of eight servers in the 1102tools federal-contracting MCP suite. Patterns that originated here: `extra='forbid'` on every arg model; WAF calibration against reality instead of guesses; `_as_list` and `_safe_int` response normalizers. Round 9 adds the suite's sharpest lesson: **live tests that assert only shape (totalRecords presence) bless catastrophically wrong data.** The reps-and-certs bug survived eight rounds and ~1,100 tests because nothing ever asserted a non-empty summary for an entity known to have certifications.

## Round 10: The Paced Live Campaign (2026-08)

Thirteen serialized probe rounds over two nights, ~230 live calls against production, pacing ratcheted from 12-20 s per call down to 2-4 s, zero throttle events. Every call is a one-line entry in a masked ledger; the harness that enforced the discipline (single-threaded, jittered spacing, hard budget, first-429 kill switch) ships in this repo at `tests/live_audit/`. This was the first full live verification in the project's history: every earlier round was quota-starved.

Method notes worth stealing: superset-vs-pair record fingerprinting settles pagination semantics in three calls; capturing real payloads once and replaying them through the pipeline offline makes every subsequent assertion free; and quota discipline is a finding-multiplier, not a tax, because the key that survives tonight also runs tomorrow.

**Confirmed and fixed/documented in 1.0.4** (beyond the round-9 items above):

- **`offset` is a zero-based page index on Opportunities AND Contract Awards** (offset=1, limit=100 returns records 101-200), while Federal Hierarchy's `offset` is a true record offset. Same parameter name, three APIs, two meanings. REST-convention `offset += limit` on the first two silently skips almost everything. Proven by exact record-fingerprint matching; the honestly named `page`/`pageNumber` families all behave as named.
- **Opportunities pages past the end return one arbitrary, unstable record instead of an empty page**, so an empty-page loop terminator never fires. Terminate from totalRecords math.
- **Contract Awards enforces offset x limit < 400,000**: exactly 400,000 returns HTTP 500, beyond it HTTP 400 with a bare-string JSON body. Only the first 400k records of any result set are pageable.
- **Bare-string JSON error bodies on HTTP 200** previously normalized into `totalRecords: 0`, an API error masquerading as an empty result. Now raised as errors.
- **Subaward endpoints hang past the last page** (client timeout, not an error response) while in-range pages return instantly.
- **Assistance `agency_code` requires a four-digit code** (9700, not CGAC 075), now validated client-side with a clear message; Federal Hierarchy accepts 3-digit CGAC for the same concept.
- **A UEI can return multiple (duplicate) registration records**, and `samRegistered=No` reveals a separate ~614k-record "ID Assigned" population.

**Live-validated as already correct**: the reps-and-certs casing fix on real production data (Lockheed Martin: 22 fARResponses, 11 dFARResponses, no lowercase variant; this closed the wave's only shape-replay-only verification); the SBA certification code redirect (raw `businessTypeCode=A6`/`XX` return 0 records, precisely the silent trap the redirect prevents; real populations 4,874 and 4,551 via `sbaBusinessTypeCode`); the subaward casing quartet and apostrophe WAF handling; every filter honesty check across all seven families (state, city, zip, NAICS, structure, purpose, classification, program, set-asides including mixed-case `BICiv`, ptype partitions summing exactly to window totals); batch-vs-single payload fidelity (byte-identical fingerprints); exact PIID/CAGE/solnum/FAIN roundtrips; case-insensitive and whitespace-tolerant matching; loud failures on malformed dates everywhere; and fed-tier FOUO response shapes through every normalizer offline.

## What Was Not Tested

- **OASIS+ and login-required transactional endpoints.** Public REST only.
- **Behavior above the default and personal rate plans.** Key quota is a per-key SAM-side rate plan, independent of data role (a federal FOUO key can sit on the 10/day default). Ten-thousand-a-day system-account behavior remains unobserved.

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root. The live suite runs with `SAM_LIVE_TESTS=1 SAM_API_KEY=... pytest`; note the quota caveat above.

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 during the hardening playbook (rounds 1-8), and Claude Code Fable 5 for the round 9 independent re-audit (full-source review against official docs and the SAM Functional Data Dictionary, documented-shape replay through the real pipeline, record correction).

Round 9 methodology: re-read the entire server source with no reliance on this document's claims; check every constant table against the FDD and API docs; replay documented response shapes through `mcp.call_tool`; enumerate which prior "live-verified" claims actually asserted semantics vs shape; queue exact confirming probes for everything quota-blocked.

Round 10 methodology: thirteen paced probe rounds (harness in `tests/live_audit/`), superset-vs-pair fingerprinting for pagination semantics, live capture plus offline pipeline replay for response shapes, boundary and error-path sweeps per endpoint family, and a canonical re-stamp round so every finding carries a fresh timestamp. Conducted with Claude Code Fable 5.

Test count: 1,142 regression tests (768 offline + 374 live-gated). Tests per tool: 60.1. Total items addressed across releases: 77. Current version: 1.0.8. PyPI: `sam-gov-mcp`.

Source: github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/sam-gov-mcp. License: MIT.

## RC5 pacing remediation (2026-08-22)

Version 1.0.8 carries the suite-wide asynchronous pacing-lock correction on top of the host-neutral missing-key message released in 1.0.7. The full offline lane passed (768 tests; 374 live-gated tests skipped), including deterministic same-process concurrency coverage. The published PyPI wheel was then installed in an isolated cache and completed MCP startup and `tools/list` with 19 tools.
