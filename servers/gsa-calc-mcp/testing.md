# GSA CALC+ MCP: Testing Record

## September 2026 throughput validation

See [keyless throughput evidence](../../docs/keyless-throughput.md) for the
current bounded experiments, failed candidates and revised policies. These
results supplement the historical live suites below; they do not repeat every
older live test or establish an official provider quota.

## Executive Summary

This Model Context Protocol server exposes the GSA CALC+ Labor Ceiling Rates API as 8 callable tools for IGCE development, price reasonableness analysis, and federal labor market research. It was hardened across six audit rounds. The original 0.2.x audits surfaced 86 bugs total (74 in the initial full audit plus 12 in retroactive deep audits), including the signature `filtered_browse()` bug that returned 265,000 unfiltered records on a zero-argument call. Round 5 added a Hypothesis-driven offline property test suite (~25,000 random probes through every validator) plus 122 new live tests covering all 8 tools. Round 5 found zero new bugs and was read at the time as validating the depth of prior hardening. Round 6 (1.0.1) disproved that read: differential count assertions against the live API surfaced two high-severity silent-wrong-data bugs (the worksite filter is silently ignored upstream, and `experience_min` alone filtered as an exact match) plus four dead hardcoded SINs, none of which shape-only live tests could see. A third high-severity finding arrived from the guide field audit in the same wave: vendor_rate_card had no page parameter, so a large vendor's card truncated mid-alphabet while presenting as complete, and its 500-row default payload overflowed MCP client output limits. The MCP ships with 435 regression tests (314 offline plus 121 live-gated).

| Metric | Value |
|---|---|
| MCP tools exposed | 8 |
| Total regression tests | 435 (314 offline, 121 live-gated) |
| Tests per tool | 54.4 |
| Audit rounds completed | 9 |
| P1 crashes (shape-shift) found and fixed | 19 |
| P1 silent-wrong-data bugs found and fixed | 33 (30 in 0.2.x, 3 in round 6) |
| P2 validation gaps found and fixed | 20 (19 in 0.2.x, 1 in round 6) |
| P3 cleanup items found and fixed | 6 |
| Round 5 Hypothesis + live findings | 0 (shape-only assertions; see round 6 for what that missed) |
| Round 6 differential-count findings | 3 high-severity (worksite ignored, experience_min exact-match, vendor_rate_card unpageable) + 4 dead hardcoded SINs + 1 validation gap |
| Retroactive additional findings | 12 |
| Current release | 1.0.15 |
| PyPI status | Published as `gsa-calc-mcp`, auto-publishes via Trusted Publisher on tag push |

## 1.0.3 Safety Release Verification

The complete offline suite passed 247 tests with 109 live tests gated. Shared
pacing tests verified cross-process serialization, keyless-service protection,
invalid overrides, and `Retry-After` handling. The previously unverified
1,000/hour claim was removed. No federal API was called.

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

The current suite collects 433 regression tests: 312 offline and 121 live-gated. The offline suite passed with all 121 optional live tests skipped; selected live checks are recorded below. Collection counts do not imply every optional live test was run.

| File | Purpose | Test count |
|---|---|---|
| `tests/test_validation.py` | Foundational validation and round-1 through round-4 regressions | 117 |
| `tests/test_round_5.py` | Hypothesis property suite and round-5 live matrix | 202 |
| `tests/test_round_6.py` | Worksite rejection, experience range, dead-SIN and paging regressions | 33 |
| `tests/test_audit_r7.py` | Round-7 live anchors | 4 |
| `tests/test_content_fixes_2026_10.py` | Content regressions and direct GSA comparisons | 30 |
| `tests/test_e2e_audit_2026_10.py` | Cross-field populations, suggestion totals and undefined statistics | 19 |
| `tests/test_http.py` | HTTP response and upstream error handling | 2 |
| `tests/test_throughput.py` | Request pacing, concurrency and budgets | 12 |
| `tests/test_response_cache_hosted.py` | Hosted cache safeguards | 5 |
| `tests/test_hosted_budget_contract.py` | Hosted budget contract | 9 |
| `tests/stress_test.py` | Historical live scenarios, not collected by pytest | N/A |

Python 3.12 collection was repeated on October 10, 2026; the per-file counts match the [test suite map](tests/README.md). Historical release counts below remain the counts recorded for those releases.

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

- **Rate-limit behavior.** GSA does not publish a numeric CALC+ limit. The unverified 1,000/hour claim was removed in 1.0.3. Every request now uses a provisional 3-second cross-process gate and honors `Retry-After` without automatic retries.
- **WAF drift.** GSA may tighten the CALC+ WAF over time. The MCP's WAF-aware filter was calibrated in April 2026; future WAF changes will be caught only via live-gated tests.
- **Historical rate data.** CALC+ surfaces current awarded rates. Historical award data requires separate queries that are not exposed by this MCP.
- **Payload size limits.** Response sizes on `filtered_browse` or `keyword_search` can be large if the caller accepts the default shape. The MCP bounds per-page results but does not enforce an overall payload ceiling.

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root and can be re-executed by anyone. The live suite runs with `GSA_CALC_LIVE_TESTS=1 pytest` and requires no API key (CALC+ is a free, public API).

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 (1M context, max effort, Claude Max 20x subscription) during the hardening playbook execution.

Testing spanned four retroactive rounds plus an initial WAF-calibration pass, a Hypothesis-and-live round 5, and a differential-count round 6. Rounds covered live probing across all 8 tools, compound-filter and pagination edge cases, length caps and ES window overflow, response-shape mock fuzzing, and (round 6) count assertions against the API's own aggregation buckets. The live regression suite runs against the production CALC+ API when enabled with `GSA_CALC_LIVE_TESTS=1`.

Test count: 356 regression tests (247 offline, 109 live-gated). P1 crashes found and fixed: 19. P1 silent-wrong-data bugs found and fixed: 32. P2 validation gaps closed: 20. P3 cleanup items closed: 6. Retroactive additional findings: 12. Current version: 1.0.4. PyPI: `gsa-calc-mcp`.

Source: github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/gsa-calc-mcp. License: MIT.


## Round 7 (2026-08-18): suite-wide live verification (super-cycle)

The full live-gated suite ran wholesale against production for the first time
(historically prevented by key quotas): 352 passed (full live pass, 2m20s). No new server
defects. Added `tests/test_audit_r7.py`: 4
one-call-per-test live contract anchors re-stamping this server's headline
fixes against production (all verified green on landing), a suite-wide pacing
conftest with a `live_smoke` marker, and a per-test client reset so batched
live runs cannot hit the cached-AsyncClient/closed-event-loop trap.

## RC5 pacing remediation (2026-08-22)

Version 1.0.4 carries the suite-wide asynchronous pacing-lock correction. The full offline lane passed (247 tests; 109 live-gated tests skipped), including deterministic same-process concurrency coverage. The published PyPI wheel was then installed in an isolated cache and completed MCP startup and `tools/list` with 8 tools.

## 1.0.12 content-test verification (2026-10-10)

Vendor worksite and contract dates, low-sample price checks, rate/category
counts, matched titles, SIN and clearance filters, nonnegative lower bounds,
truncation flags, current-year price guidance, and worksite counts.

The full Python 3.12 offline suite passed 293 tests with 121 live-gated
tests skipped. All 30 tests in `test_content_fixes_2026_10.py` passed with the live flag
enabled, including 12 comparisons against the government API. Hosted tool
contract checks, version validation for all nine packages, and all 64 release
guard tests passed. The Worker type check passed and all six Worker tests passed.

The README badge and test suite map were reconciled with pytest collection: 414 Python tests (293 offline, 121 live-gated). The saved Q1-Q30 findings gate also passed 43 comparisons against fresh GSA responses, with four explicit deferred rows for raw payload trimming and per-site/future-year statistics.


## 1.0.13 workflow audit (2026-10-10)

The full workflow audit covered all eight tools with 28 realistic question and follow-up cases against the hosted MCP transport and local MCP registry, preserving raw GSA response bodies. It verified exact-title/vendor/contract discovery, compound filters, education OR, experience half-ranges, vendor paging and worksite rows, active/retired SINs, low/no-data checks, and actionable validation errors.

New confirmed findings: capped suggestion `hits.total` was displayed without its lower-bound relation; IGCE keyword searches also matched vendor/contract fields while claiming title-only matching, contaminating price verdicts (Systems Engineering returned Admin/IT Support titles); zero/missing variance produced a fabricated zero z-score, and a missing average fabricated dollar deltas from zero. Statistical edge cases were reproduced through the MCP pipeline with controlled upstream fixtures, not observed as a current live GSA outage.

All 19 new regression cases failed on the original 1.0.12 source and pass after the fixes. Incomplete or approximate title aggregations also suppress price verdicts conservatively. The historical numerical and low-sample fixtures now explicitly supply complete title populations. Tool names, descriptions, schemas and annotations match the reviewed hosted contract without regeneration.

The GSA API still has no supported title-substring-only statistics query. The benchmark therefore labels its pooled field scope and price checks suppress misleading or unverifiable judgments; use `suggest_contains` followed by `exact_search` on labor_category for title-only comparisons. Existing published docstrings are retained to preserve reviewed metadata; response notes and the README document the actual keyword scope.

Validation completed under Python 3.12: **433 collected**, **312 passed / 121
live-gated skipped** in the full offline suite; the content-fix suite with live
access enabled passed **30 tests**, including **12 live government-source
comparisons**. The 28-case question/follow-up replay passed local transport,
source and expected-error checks; hosted baseline responses were preserved to
show the actual pre-release behavior. Six Worker budget tests passed. Wheel
build, all-nine version consistency and the eight-tool reviewed metadata
contract passed. Live published 1.0.13 verification is a release-stage check.


## 1.0.14 discovery-description correction

OpenAI's current [published MCP metadata rules](https://developers.openai.com/plugins/deploy/app-review#how-published-mcp-metadata-versions-work)
use continuous review for changed tool definitions: after deployment, updated
descriptions become available when automated checks pass, without a new plugin
version or manual directory republishing. The earlier frozen-description
assumption was outdated. Both `igce_benchmark` and
`price_reasonableness_check` now describe the cross-field GSA keyword population
and conservative no-verdict statuses at discovery time. The existing Worker
proxies tools/list from this Python server; its reviewed tools-contract baseline
was regenerated with Python 3.12. Machine comparison of the actual tool list
confirmed only these two descriptions changed; all eight tool names, input and
output schemas, annotations, service identities and endpoints are unchanged.
The existing full suite remains 433 collected (312 offline, 121 live-gated).
The in-flight 1.0.13 release remains immutable; 1.0.14 ships this correction.

Validation: full Python 3.12 suite **312 passed / 121 live-gated skipped**;
wheel build, all-nine version consistency and the regenerated eight-tool
contract check passed. Independent internal peer review approved the two
new descriptions and confirmed identical identities, schemas and annotations.


## Round 2 content audit (2026-10-10): no new confirmed findings

A fresh ordinary-user and power-user audit of published `gsa-calc-mcp` 1.0.14
covered all eight tools with **123 question and follow-up cases**, run through
the actual installed package's MCP registry and the public MCP endpoint. The
corpus covered ten labor domains, combined education/experience/price/SIN and
clearance filters, market segments, vendor discovery and card continuation,
exact-title/vendor/contract followups, and qualified IGCE comparisons. Six
illustrative annual-cost followups used exact qualified populations and an
explicit 2,080-hour assumption; these are ceiling benchmarks, not prices paid
or independent price-reasonableness determinations.

The audit retained **152 GSA response captures plus four direct source-proof
calls** and passed **2,521 source and workflow assertions**. Counts, averages,
standard deviations, minimum/maximum values, requested filters, vendor row
fields and proposal arithmetic agreed with primary source data. Mixed or
unverified keyword populations continued to suppress misleading pricing
verdicts. **No new P0, P1, P2 or P3 defect was confirmed**, so no runtime patch,
version bump or new regression test was required.

The package was installed by name from the official PyPI index into a fresh
Python 3.12 environment. The installed console entrypoint completed MCP stdio
startup, discovered all eight tools and correctly handled the original
Systems Engineering comparison. Installed server bytes matched the official
wheel and current source; installed and public descriptions, schemas and
annotations matched the reviewed contract. Public health reported version
1.0.14's release SHA `7754923b8c77e51022e2c561856fd6ccf4eab874`. The current
regression collection remains **433 tests: 312 offline passed and 121 optional
live-gated skipped** in the recorded full-suite verification. Content calls
and audit assertions are separate from pytest collection; this audit does not
claim a new full optional-live-suite run.

Source limitations remain visible. Across equivalent installed/public calls,
**228 scalar percentile values differed**, with a maximum difference of
**$2.2511/hour**. Three fresh direct GSA repeats for SIN 541930 retained the
same 325-rate population and identical wage statistics while P75 varied from
$165.79 to $168.04. These are approximate upstream percentile estimates, not
altered MCP values. Two vendor comparisons also differed under tied labor-title
sorting: Leidos reordered the same rows, while a Booz Allen continuation
shifted a tied row at a page boundary. A larger official 100-row card verified
all local and public rows in the latter comparison. Partial-card and
continuation warnings remained present. Zero unexpected content differences
therefore does **not** mean all responses were identical.

GSA's cross-field keyword population, suggestion/aggregation and result-window
caps, and unsupported worksite filtering remain disclosed source limits.
Worksite counts do not provide a supported per-site price aggregation. Exact
search's current SIN/clearance filter availability and future stable tie-breaking
pagination are potential enhancements, not new defects inferred from this
corpus. Independent read-only peer review confirmed the source approximation
and tied-row evidence and approved the zero-new-findings conclusion within
this scope. Raw questions, responses, source URLs, checks and peer evidence
are retained in the dated `Artifacts/mcp-e2e-20261010/round2/gsa-calc` audit record.


## October 10, 2026 content audit Round 3 — worksite recovery correction

New ordinary and power-user research covers all eight tools, ten labor domains,
qualified market filters, new vendor legal-name discovery and card continuations,
contract follow-ups, and exact-title ceiling cost scenarios. Evidence is retained
in `Artifacts/mcp-e2e-20261010/round3/gsa-calc` outside this repository.

An ordinary request for government-customer-facility Network Engineer rates, and
a small-business engineering worksite comparison, exposed one P2 recovery defect
in a fresh official PyPI 1.0.14 installation using MCP 2.3. Both actual stdio CLI
answers reduced the intended unsupported-worksite guidance to a generic tool
error. The public service still exposed the correct recovery instruction. Fresh
primary GSA requests with no worksite filter, Customer, and Contractor all
returned the same 1,761 eligible rates and site mix (986 customer, 704 contractor,
71 virtual); the unavailable source filter remains a limitation.

Version 1.0.15 classifies existing deliberate caller-validation failures as
anticipated tool errors while preserving ValueError compatibility. It retains the
instructions to remove the worksite argument and inspect individual worksite
fields; it does not offer unavailable worksite-filtered aggregate prices. Two
real stdio regressions failed before and passed after on MCP 2.3. Actual candidate
CLI original questions now retain actionable guidance, and corrected follow-ups
return the same eligible population and worksite breakdown. Current schemas,
descriptions, identities and successful-query behavior are unchanged.

The candidate suite has **435 collected tests: 314 passed and 121 optional live
skipped** in both the frozen MCP 2.0 lane and a separately installed candidate
wheel with fresh MCP 2.3. The live skips are not passes. The completed new
corpus contains **132 unique ordinary/power-user questions and follow-ups
across all eight tools**, with 142 primary GSA response captures and 13
additional direct proofs. The published-baseline and candidate corpora use the
registered MCP tool pipeline in actual installed packages, not direct `.fn`
calls or stdio CLI calls. The baseline has 132 actual public HTTP JSON-RPC
calls. Its source/public checks and the registered installed-candidate replay
pass 3,200 conditions each. Actual stdio checks are recorded separately: the
published baseline has two original worksite errors and two corrected follow-
ups plus a Network Engineer smoke query; the candidate has the four
original/recovery calls. Both discover all eight tools. Ten exact-title cost
scenarios retain eligible counts, thin populations, and the distinction between
ceiling budgets and prices paid. An empty BA/MA armed-guard population leads to
three successful high-school eligibility follow-ups.

The published-baseline/public comparison records 209 approximate percentile scalar
variations (maximum $2.7026/hour) and five distributed bucket-count/list
variations supported by fresh official responses and the source error bound;
the candidate replay documents three bucket variations separately. These are
not identical parity claims. Suggestion caps, unavailable worksite-filtered
statistics, and single-field sort ties remain source limitations. Final actual published verification installed `gsa-calc-mcp==1.0.15` uncached by
name from official PyPI into a fresh Python 3.12 environment with MCP 2.3.0.
The installed registered-tool pipeline and public HTTPS service each completed
132 cases across all eight tools, with 142 current primary GSA captures and
3,200 passing source/workflow checks. These calls are separate from five actual
stdio CLI calls: two original worksite questions, two successful corrected
follow-ups, and one smoke query. All eight installed/public definitions match
the frozen contract; public version 1.0.15 and release SHA
`7e8c4132d8b394e9a4ef7f2f57d1cc0a0d966336` match the successful scoped release.
Installed server bytes also match the official wheel and reviewed source. The
fresh published suite passed 314 tests with 121 optional live skips (435
collected).

The final comparison records 216 approximate percentile variations, at most
$2.9341/hour, and six documented distributed bucket variations. Twelve repeated
primary aggregations, three additional suggestion requests, two exact-title
primary requests, and three worksite proofs reconcile those source differences.
Shared suggestion counts differ by at most four within published error bounds;
the two remaining architecture tail titles were independently confirmed at
14 rates each (public approximate counts 12 and 14). The source still caps
suggestions at 100 even when a larger page size is requested. This is qualified
source equivalence, not a claim of identical responses. No further product
finding was observed in the final verification. Detailed evidence is retained
under `Artifacts/mcp-e2e-20261010/round3/gsa-calc/final-published`.
