# SAM.gov MCP: Testing Record

## Executive Summary

This Model Context Protocol server exposes seven SAM.gov REST APIs (Entity Management v3, Exclusions v4, Opportunities v2, Contract Awards v1, Federal Hierarchy v1, Acquisition Subaward Reporting, Assistance Subaward Reporting) plus the PSC lookup as 19 callable tools. It was hardened across nine audit rounds. Live audits surfaced seven catastrophic P1 silent-wrong-data bugs mocks could never catch (apostrophe-rejecting WAF, typo'd-parameter silent drops, empty PIID acceptance, `entityName` vs `exclusionName`, and three Subaward parameter casings). Round 9 (1.0.2), an independent full-source re-audit, found the worst one yet by replaying the documented Entity API response shape through the real pipeline: `get_entity_reps_and_certs` read the wrong JSON key casings, so its default summary mode returned EMPTY clause lists for every entity, and eight prior rounds never noticed because their live assertions only checked `totalRecords`. This MCP is also where the `extra='forbid'` cross-fix pattern was invented and exported to the rest of the suite. The MCP ships with 1,125 regression tests (754 offline, 371 live-gated), the highest count in the 1102tools MCP suite.

| Metric | Value |
|---|---|
| MCP tools exposed | 19 |
| Total regression tests | 1,125 (754 offline, 371 live-gated) |
| Tests per tool | 59.2 |
| Audit rounds completed | 9 |
| Total items addressed | 67 across releases |
| P1 silent-wrong-data bugs (live-audit-only) | 7 |
| Round 9 findings | 13 (8 fixed in 1.0.2, 5 pending live confirmation) |
| Current release | 1.0.2 |
| PyPI status | Published as `sam-gov-mcp`, auto-publishes via Trusted Publisher on tag push |

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

### Pending live confirmation (quota-blocked; exact probes queued)

| # | Suspicion | Confirming probe |
|---|---|---|
| 9 | `search_exclusions` size cap: code allows 100, Exclusions docs say "Allowable values are 1 to 10". The round-6 `max_size_100` live test only asserted `totalRecords` presence, proving nothing about records-per-page. | One live call at size=100 counting `excludedEntity` entries. |
| 10 | PSC param casing: code sends `searchby`; docs say `searchBy`. If the router is case-sensitive, `lookup_psc_code` is silently doing bare-`q` code-prefix matching (masked, same-looking results) and `search_psc_free_text`'s promised name/description search never worked (its live tests passed on totalRecords=0). | Live `q=engineering` bare vs with `searchBy` variants; `searchby=psc` vs `searchBy=psc` deltas. |
| 11 | Opportunities date-span cap: local 364-day limit vs the documented "1 year"; the round-6 test named `exactly_364_day_span` actually probed a 363-day window, so the true boundary has never been tested. | One live call at a 365-day span. |
| 12 | `fiscal_year` floor of 2008 on Contract Awards may reject legitimate older data (docs state no floor). | Live `fiscalYear=2007&limit=1`. |
| 13 | `registration_status` offers D/I beyond the documented A/E; unknown values may be silently ignored upstream, returning wrongly-filtered data. | Live `registrationStatus=D` vs unfiltered totals. |

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

Live coverage spans 11 department-level lookups, CGAC variants (020/097/075), pagination boundaries, response-shape checks, 5-way concurrent calls, and casing-regression canaries. Hypothesis property tests (300 examples each) target `_validate_date_yyyy_mm_dd`, `_normalize_fh_response`, and `_normalize_subaward_response`. Note (round 9): the three subaward casing claims are recorded as tested by named live tests that exist in the repo; their pass status could not be re-reproduced during round 9 because of quota, so they stand on the round-8 record.

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

UEI/CAGE format enforcement everywhere they appear, the opportunities date-span pre-check, length clamps on text filters, country-code uppercasing, WAF detection via status codes rather than body substrings, and calibrated pre-rejection limited to control characters. (Round 9 note: the date-span cap's exact boundary remains unprobed; see pending item 11.)

### Priority 3: Cleanup items

Empty-string filters, code-set validation, NAICS format, case normalization, and the opaque PSC 404 body translation. (Round 9 revised the code-set philosophy for business types: format-check plus pass-through, because the FDD set is far larger than any local table.)

## Test Coverage

The repo ships 1,125 regression tests (754 offline, 371 live-gated). All pass on every release cycle; live tests require `SAM_LIVE_TESTS=1` plus a key with real quota.

| File | Purpose | Test count |
|---|---|---|
| `tests/test_validation.py` | Rounds 1-4 plus live-audit regressions | 80 (74 offline + 6 live-gated) |
| `tests/test_density_r5.py` | Round 5 parameterized failure-mode buckets | 368 |
| `tests/test_live_audit_r6.py` | Round 6 live sweep across every tool | 154 (all live-gated) |
| `tests/test_round_7.py` | Hypothesis property suite | 133 |
| `tests/test_v0_4_features.py` | Round 8 Federal Hierarchy + FFATA (incl. 123 live) | 259 |
| `tests/test_sba_business_type.py` | 1.0.1 SBA code family (validation/mock/live) | 15 |
| `tests/test_audit_r9.py` | Round 9 regressions: documented-shape reps-and-certs replay, set-aside and business-type expansion, Z1-Z5, bracket-range rejection, zip/CGAC padding, PIID sort, version sync | 16 (all offline) |
| `tests/stress_test.py`, `tests/stress_test_r2.py`, `tests/live_test.py` | Scenario scripts (retained for reproducibility) | N/A |

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

## Cross-MCP Context

This MCP is one of eight servers in the 1102tools federal-contracting MCP suite. Patterns that originated here: `extra='forbid'` on every arg model; WAF calibration against reality instead of guesses; `_as_list` and `_safe_int` response normalizers. Round 9 adds the suite's sharpest lesson: **live tests that assert only shape (totalRecords presence) bless catastrophically wrong data.** The reps-and-certs bug survived eight rounds and ~1,100 tests because nothing ever asserted a non-empty summary for an entity known to have certifications.

## What Was Not Tested

- **Rate-limit behavior at scale.** The MCP surfaces 429s but does not throttle client-side. Personal no-role keys get on the order of 10 requests/day per family; a full live pass needs a system or federal key.
- **OASIS+ and login-required transactional endpoints.** Public REST only.
- **The opportunities date-span boundary at exactly 364/365 days** (pending round 9 item 11).
- **The five round-9 pending items** listed above, each with its exact confirming probe, runnable the day quota resets.

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root. The live suite runs with `SAM_LIVE_TESTS=1 SAM_API_KEY=... pytest`; note the quota caveat above.

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 during the hardening playbook (rounds 1-8), and Claude Code Fable 5 for the round 9 independent re-audit (full-source review against official docs and the SAM Functional Data Dictionary, documented-shape replay through the real pipeline, record correction).

Round 9 methodology: re-read the entire server source with no reliance on this document's claims; check every constant table against the FDD and API docs; replay documented response shapes through `mcp.call_tool`; enumerate which prior "live-verified" claims actually asserted semantics vs shape; queue exact confirming probes for everything quota-blocked.

Test count: 1,125 regression tests (754 offline + 371 live-gated). Tests per tool: 59.2. Total items addressed across releases: 67. Current version: 1.0.2. PyPI: `sam-gov-mcp`.

Source: github.com/1102tools/federal-contracting-mcps/tree/main/servers/sam-gov-mcp. License: MIT.
