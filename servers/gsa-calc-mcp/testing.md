# GSA CALC+ MCP: Testing Record

## Executive Summary

This Model Context Protocol server exposes the GSA CALC+ Labor Ceiling Rates API as 8 callable tools for IGCE development, price reasonableness analysis, and federal labor market research. It was hardened across six audit rounds. The original 0.2.x audits surfaced 86 bugs total (74 in the initial full audit plus 12 in retroactive deep audits), including the signature `filtered_browse()` bug that returned 265,000 unfiltered records on a zero-argument call. Round 5 added a Hypothesis-driven offline property test suite (~25,000 random probes through every validator) plus 122 new live tests covering all 8 tools. Round 5 found zero new bugs and was read at the time as validating the depth of prior hardening. Round 6 (1.0.1) disproved that read: differential count assertions against the live API surfaced two high-severity silent-wrong-data bugs (the worksite filter is silently ignored upstream, and `experience_min` alone filtered as an exact match) plus four dead hardcoded SINs, none of which shape-only live tests could see. A third high-severity finding arrived from the guide field audit in the same wave: vendor_rate_card had no page parameter, so a large vendor's card truncated mid-alphabet while presenting as complete, and its 500-row default payload overflowed MCP client output limits. The MCP ships with 343 regression tests (240 offline plus 103 live-gated).

| Metric | Value |
|---|---|
| MCP tools exposed | 8 |
| Total regression tests | 343 (240 offline, 103 live-gated) |
| Tests per tool | 42.9 |
| Audit rounds completed | 6 (4 retroactive live + initial WAF pass + Hypothesis/live round 5 + differential-count round 6) |
| P1 crashes (shape-shift) found and fixed | 19 |
| P1 silent-wrong-data bugs found and fixed | 33 (30 in 0.2.x, 3 in round 6) |
| P2 validation gaps found and fixed | 20 (19 in 0.2.x, 1 in round 6) |
| P3 cleanup items found and fixed | 6 |
| Round 5 Hypothesis + live findings | 0 (shape-only assertions; see round 6 for what that missed) |
| Round 6 differential-count findings | 3 high-severity (worksite ignored, experience_min exact-match, vendor_rate_card unpageable) + 4 dead hardcoded SINs + 1 validation gap |
| Retroactive additional findings | 12 |
| Current release | 1.0.1 |
| PyPI status | Published as `gsa-calc-mcp`, auto-publishes via Trusted Publisher on tag push |

## What Was Tested

The MCP exposes 8 tools covering the CALC+ Elasticsearch-backed API. Testing covered all of them end-to-end.

**Core search:** `keyword_search`, `exact_search`, `suggest_contains`, `filtered_browse`

**Workflow tools:** `igce_benchmark`, `price_reasonableness_check`, `vendor_rate_card`, `sin_analysis`

Each tool was exercised for argument validation, input sanitization, response-shape guarantees, error translation, pagination edge cases, Elasticsearch result-window limits, and real-world data handling against the live production CALC+ API.

## How It Was Tested

### Testing discipline

Prior unit tests in v0.1.x awaited raw coroutines and mocked the HTTP layer, which bypassed the FastMCP tool pipeline and skipped whole classes of integration bugs. The hardening program switched to invoking tools through `mcp.call_tool(name, kwargs)` the way a real MCP client does, paired with live calls against the production CALC+ API. That change surfaced the `filtered_browse` unfiltered-return bug and the `sin=True` pydantic coercion bug, neither of which was visible from mocked tests.

### Audit rounds

| Round | Scope | Probe count | Finding class |
|---|---|---|---|
| Initial (pre-0.2.1) | WAF filter calibration with mocked tests | Calibration only | WAF relaxation plus `extra='forbid'` cross-fix |
| Retro Round 1 | Live probing across all 8 tools | Live probes per tool | Control-char slippage, `filtered_browse` unfiltered, `sin` bool trap |
| Retro Round 2 | Compound filters, pagination, NaN/Inf, concurrency | Live stress probes | Response-shape guard gaps, WAF vs exclude parameter, 265K unfiltered fix |
| Retro Round 3 | Length caps, page × page_size overflow | Live probes | `suggest_contains.term` unbounded, ES 10k window overflow |
| Retro Round 4 | Response-shape mock fuzzing | 15+ shape probes | Confirmed defensive guards hold; no new findings |
| Round 5 | Hypothesis property suite + live shape assertions across all 8 tools | ~25,000 offline probes + 122 live calls | Zero findings (assertions were shape-only) |
| Round 6 (1.0.1) | Differential count assertions against the live API and its own aggregation buckets, plus guide field-audit intake | ~60 targeted live probes | worksite filter ignored upstream, experience_min exact-match, vendor_rate_card unpageable, 4 dead SINs, price_max=0 silent zero |

### Live audit status

All retroactive rounds included live calls against the production CALC+ API. The repository includes 103 live-gated regression tests executable via `GSA_CALC_LIVE_TESTS=1 pytest` covering real wildcard search, exact-match lookup, IGCE benchmark stats, price reasonableness, vendor rate card, SIN analysis, filtered browse with real filters applied, and (round 6) differential count assertions. No API key is required; CALC+ is a free, public API behind a WAF. Note: earlier revisions of this document gave the env var as `CALC_LIVE_TESTS=1`, which matches nothing in the test code and silently runs zero live tests.

## Issues Found and Fixed

### Priority 1: Silent wrong-data bugs

Thirty bugs in this class. Representative and signature items below.

| Issue | Fix |
|---|---|
| `filtered_browse()` with zero arguments silently returned the entire 265,000-record CALC+ dataset. Same failure-mode category as the regulationsgov-mcp `agency_id=""` 1.95M-record bug. | At-least-one-filter guard raises "filtered_browse requires at least one filter" with examples (education_level, experience_min, sin, business_size, price_min). |
| Control characters (null byte, newline, carriage return, tab, backspace) slipped through every free-text field: `keyword`, `value`, `term`, `labor_category`, `vendor_name`, `exclude`. URL-encoded and sent silently to the API. | All free-text fields reject control characters up front via a shared `_validate_text` helper. |
| `sin=True` was silently coerced to `sin=1` by pydantic's implicit bool-to-int conversion before any validator ran. The value `"True"` passed the alphanumeric regex and became `filter=sin:1` to the API, returning zero matches. | `BeforeValidator` added to `Union[str, int, None]` fields to reject `bool` at the type layer. Pattern now reused across the suite. |
| `proposed_rate=NaN` produced bogus `price_reasonableness_check` output: `vs_median="equal"` and `iqr_position="above P75"` because NaN comparisons all fall to the `else` branch. | Finite-number check enforced on all float inputs. NaN and Inf rejected at the arg layer. |
| `proposed_rate=Inf` passed pydantic's `float` type (no finite constraint) and leaked into `z_score` and `delta` outputs. | Same finite check applied. |
| `price_min=NaN` or `price_max=Inf` passed pydantic and hit the API as a 406. | Same finite check. |
| `exclude` parameter was not WAF-checked, not control-char checked, and not length-capped. `exclude=<script>` was not pre-rejected. | Same `_validate_text` plus the WAF-angle-bracket filter. |
| Pagination past the end of results silently returned empty. `page=100` of a 2076-record query returned 0 records with no `paged_past_end` flag. | Page-past-end detection added; response now includes a clear flag and guidance. |
| Elasticsearch 10k-result window: `page_size × page > 10000` returned a cryptic 406 "Result window too large". | Pre-clamp added. Combined `page_size × page` is bounded locally before the HTTP call with a clear error. Pattern now reused across ES-backed MCPs in the suite. |

### Priority 1: Crashes and shape-shift defenses

Nineteen bugs in this class. The `_extract_stats` helper crashed on multiple unusual Elasticsearch aggregation shapes that CALC+ occasionally returns under load:

| Issue | Fix |
|---|---|
| `hits.total` returned as bare int instead of `{"value": N, "relation": "eq"}` object shape. Triggered `AttributeError`. | `_safe_dict` and `_safe_number` helpers normalize both shapes. |
| `aggregations` returned with null value. `.get()` crashed with `AttributeError`. | Null-coalescing throughout aggregation parsing. |
| `vendor_rate_card` `hits.hits` returned as null. Triggered `TypeError` on iteration. | `_as_list` helper returns empty list for null or missing. |
| `_source` field was null in individual hits. `AttributeError` on member access. | Same `_safe_dict` guard. |
| `suggest_contains` bucket missing the `key` field. Triggered `KeyError`. | Key presence checked before access; buckets with missing keys are skipped. |
| `price_reasonableness_check` with `avg=0` and `median=None` produced a misleading "above" comparison. | Explicit null and zero checks before comparison; output includes a `reason` field when inputs are degenerate. |

### Priority 2: Validation gaps

Nineteen bugs in this class. Representative items:

| Issue | Fix |
|---|---|
| `igce_benchmark.labor_category` had no length cap. 600-character strings produced upstream 406s. | Capped at 500 characters (GSA 406s above that). |
| `suggest_contains.term` had no length cap. | Capped at 500 characters. |
| `vendor_rate_card.vendor_name` had no length cap. | Capped at 500 characters. |
| `sin_analysis.sin_code` had no length cap. | Capped at 20 characters (real SINs are 10 or fewer). |
| `experience_max` alone (without `experience_min`) was silently ignored. No half-range filter was built. | Half-range filters now construct correctly in both directions. |
| Reversed ranges (`price_min > price_max`, `experience_min > experience_max`) were sent raw to the API. | Reversed ranges raise actionable error locally. |
| Negative `price_min=-50` was accepted and produced `price_range:-50,99999` (pulls everything). | Non-negative constraint enforced. |
| `price_max=0` produced `price_range:0,0` which matched only $0 rates (useless). | Documented as fixed in 0.2.2, but no guard actually existed until round 6; 1.0.1 rejects `price_max <= 0` locally. |
| Hardcoded upper bound of 99999 on `price_min`-only queries excluded rates above $99,999/hr. | Upper bound lifted to 999999; documented. |
| Empty or whitespace-only `keyword` silently returned the full 250K dataset. | Minimum 1-character non-whitespace enforced. |
| Bogus `education_level="XYZ"` silently accepted and returned 0 records. | Validated against the known education-level set. |
| `education_level` was case-sensitive at the API; "ba" vs "BA" silently filtered to nothing. | Lowercase and unknown codes raise a validation error listing the valid codes (an earlier revision of this document claimed uppercase normalization; the implementation rejects instead, which is safe but stricter). |
| `page=0`, `page=-1` were accepted locally and rejected by the API with 406. | Bounded locally to `>= 1`. |

### Response-shape defense

The `_safe_dict`, `_as_list`, and `_safe_number` helpers now wrap every Elasticsearch aggregation path. CALC+ occasionally returns unusual shapes under load that previously produced type-confusion crashes. All shape variants now normalize cleanly to structured Nones. This defensive-parsing pattern was codified here and reused across the other ES-backed MCPs in the suite.

## Round 6 (1.0.1): The Differential-Count Audit

Round 6 re-audited the live API with a different assertion discipline and found what five prior rounds missed. The API itself was confirmed alive and current first (nightly index `ceilingrates-2026-08-17`, no redirects), so every finding is a server-side contract mismatch, not API rot.

### Findings

| Finding | Severity | Evidence | Fix |
|---|---|---|---|
| The `worksite` filter is silently ignored by the v3 API. Every value (Customer, Contractor, Both, the raw data values Customer_Facility / Contractor_Facility / Virtual, a space form, a top-level `worksite=` param, and a `site:` filter) returned the identical unfiltered total: 49,090 for keyword=engineer against worksite buckets of 25,358 / 21,245 / 2,487. Callers asking for site-specific rates got all-site statistics. The old Customer / Contractor / Both enum is also stale; the v3 data vocabulary is Customer_Facility / Contractor_Facility / Virtual, and "Both" no longer exists. | High | 10 live probes, tool layer and raw API | Passing worksite now raises a clear ValueError; a live canary test fails if GSA ever starts honoring the filter |
| `experience_min` alone emitted `min_years_experience:N`, which the API treats as an exact term match. experience_min=5 returned 7,343 records (the exactly-5 bucket) instead of the expected 29,120 (>= 5), silently dropping ~74% of qualifying records from IGCE and price-analysis statistics. | High | Differential probe: `min_years_experience:5` = 7,343 vs `experience_range:5,999` = 29,120 | Min-only now emits `experience_range:N,999`, mirroring the price sentinel |
| 4 of 12 hardcoded COMMON_SINS return zero records (541512, 541513, 541610, 541519; retired or absorbed under MAS consolidation), and the sin_analysis docstring recommended dead 541512, steering callers into silent empty analyses. | Medium | 12 live SIN probes | Dead codes removed; 561210FAC (11,925 records) replaces 541512 in the docstring; sin_analysis appends a retirement note on any zero-record SIN |
| vendor_rate_card had no `page` parameter: rows 501+ of a large vendor's card were unreachable at any size, the 500-row default payload for Booz Allen Hamilton (1,886 categories) was ~114KB and overflowed MCP client output limits, and alphabetical ordering made the truncated slice systematically front-of-alphabet biased (Software / Network / Systems Engineer all sorted past the cutoff) while presenting as complete. | High | Guide field audit (round-2 pricing, CALC-3) plus live probes; also live-verified that the API silently ignores vendor_name and labor_category as filter fields, so no one-call vendor+keyword intersection exists | `page` parameter added, default page_size dropped to 100 (~23KB), response carries returned_range / has_more / next_page and an alphabet-bias truncation note; docstring says to page through and filter client-side |
| `price_max=0` built `price_range:0,0` and returned a silent zero-result response; the guard this document claimed since 0.2.2 never existed. | Low | Live call + code inspection | `price_max <= 0` rejected locally |
| keyword_search's docstring listed 5 ordering fields; 8 are valid and all work (next_year_price, idv_piid, business_size verified sorting live). | Low | 3 live ordering probes | Docstring lists all 8 |

### Verified clean in round 6

Education code translation (BA maps to the Bachelors bucket exactly, HS covers High School plus Equivalent), security_clearance yes/no translation to the boolean field, exclude single and pipe-delimited multi-id arithmetic, pipe-OR education arithmetic (BA|MA equals the sum of both buckets), business_size counts, exact_search exactness and filter composition, suggest_contains count-descending order, page_size=500 honored, percentile key mapping, and every statistic igce_benchmark and price_reasonableness_check derive (avg, std, z-score, deltas, IQR positioning) hand-checked against raw aggregations.

### The methodology lesson

Rounds 1-5 asserted response shape on live calls: `isinstance(data, dict)`. A filter the API silently drops passes every such test. Round 6 asserted counts differentially: a filtered total must differ from the unfiltered total, match the API's own aggregation bucket for that value, and change in the right direction when the filter tightens. Both high-severity bugs were visible only under that discipline. The round 6 live tests bake it in: they compare totals against the response's own buckets rather than checking shape, so a regression to either bug (or a GSA-side change in filter behavior) fails loudly.

## Test Coverage

The repo ships 343 regression tests across the test folder (240 offline, 103 live-gated). All pass on every release cycle.

| File | Purpose | Test count |
|---|---|---|
| `tests/test_validation.py` | Main regression suite covering every round-1 through round-4 finding, plus live-gated integration tests | 117 |
| `tests/test_round_5.py` | Hypothesis property suite plus the round-5 live matrix | 202 |
| `tests/test_round_6.py` | Round-6 regressions: worksite rejection, experience_range wire format, dead-SIN guards, differential live tests | 24 |
| `tests/stress_test.py` | Retro Round 1 live-probe scenarios (historical archive, not collected by pytest; predates the 1.0.1 worksite rejection) | N/A (scenario script) |

Regression tests invoke tools through the FastMCP registry (`mcp.call_tool`) rather than awaiting decorated coroutines directly. This catches bugs in the tool pipeline that raw-coroutine tests miss. An autouse fixture resets `srv._client` between tests so the shared httpx client does not leak across event loops.

## Release History

| Version | Focus | Outcome |
|---|---|---|
| 0.1.1 | Initial release: 8 tools with basic unit tests | Basic coverage |
| 0.2.1 | Minimal cross-fix: WAF filter relaxation (apostrophes, SQL keywords) plus pydantic `extra='forbid'` applied to every tool arg model (back-ported from sam-gov-mcp 0.3.1) | Calibrated WAF, typo'd-param silent drop fix |
| 0.2.2 | Full retroactive 4-round audit through the live CALC+ API: 86 bugs fixed (74 initial full audit + 12 retro deep audit); 117 regression tests including 8 live-gated | 19 P1 crashes, 30 P1 silent-wrong-data, 19 P2, 6 P3 resolved |
| 0.2.6 | Round 5: Hypothesis property suite (~25,000 offline probes) plus 122 live shape assertions | Zero findings under shape-only assertions |
| 1.0.0 | MCP Python SDK v2 migration, bounded `mcp` requirement, version sync | No tool contract changes |
| 1.0.1 | Round 6 differential-count audit | worksite rejection, experience_min range fix, dead SINs removed, price_max guard, 343 regression tests |

## Cross-MCP Context

This MCP is one of eight servers in the 1102tools federal-contracting MCP suite (`bls-oews-mcp`, `ecfr-mcp`, `federal-register-mcp`, `gsa-perdiem-mcp`, `regulationsgov-mcp`, `sam-gov-mcp`, `usaspending-gov-mcp`, and this one). All eight were hardened under the same playbook. Patterns that originated or propagated through this MCP:

- **The `_safe_dict`, `_as_list`, `_safe_number` defensive-parsing helpers** were refined here for Elasticsearch-backed APIs and reused across the suite.
- **The `BeforeValidator` bool-rejection pattern** on `Union[str, int, None]` fields was invented here. Pydantic silently coerces `bool` to `int` before any custom validator runs, so the `sin=True` bug required rejecting `bool` at the type layer. Pattern now reused across the suite.
- **The Elasticsearch 10k-result window pre-clamp pattern** was established here for ES-backed APIs. Applied wherever an API is known to be ES-backed.
- **The finite-number check on float params** was codified here because pydantic has no finite constraint on `float` (unlike its `conint` variants).
- **WAF filter relaxation** was calibrated here against real CALC+ behavior: CALC+ WAF-blocks angle brackets and path traversal but accepts apostrophes and SQL keywords. This is different from SAM.gov's WAF, so this MCP's WAF filter is tuned specifically to CALC+.

## What Was Not Tested

- **Rate-limit behavior.** The MCP's 429 error message cites 1,000 requests/hour, but that figure has not been verified against public GSA documentation, and no 429 was ever observed in testing (round 6 included ~50 rapid probes). The MCP passes through whatever limits the API enforces but does not implement client-side throttling.
- **WAF drift.** GSA may tighten the CALC+ WAF over time. The MCP's WAF-aware filter was calibrated in April 2026; future WAF changes will be caught only via live-gated tests.
- **Historical rate data.** CALC+ surfaces current awarded rates. Historical award data requires separate queries that are not exposed by this MCP.
- **Payload size limits.** Response sizes on `filtered_browse` or `keyword_search` can be large if the caller accepts the default shape. The MCP bounds per-page results but does not enforce an overall payload ceiling.

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root and can be re-executed by anyone. The live suite runs with `GSA_CALC_LIVE_TESTS=1 pytest` and requires no API key (CALC+ is a free, public API).

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 (1M context, max effort, Claude Max 20x subscription) during the hardening playbook execution.

Testing spanned four retroactive rounds plus an initial WAF-calibration pass, a Hypothesis-and-live round 5, and a differential-count round 6. Rounds covered live probing across all 8 tools, compound-filter and pagination edge cases, length caps and ES window overflow, response-shape mock fuzzing, and (round 6) count assertions against the API's own aggregation buckets. The live regression suite runs against the production CALC+ API when enabled with `GSA_CALC_LIVE_TESTS=1`.

Test count: 343 regression tests (240 offline, 103 live-gated). P1 crashes found and fixed: 19. P1 silent-wrong-data bugs found and fixed: 32. P2 validation gaps closed: 20. P3 cleanup items closed: 6. Retroactive additional findings: 12. Current version: 1.0.1. PyPI: `gsa-calc-mcp`.

Source: github.com/1102tools/federal-contracting-mcps/tree/main/servers/gsa-calc-mcp. License: MIT.
