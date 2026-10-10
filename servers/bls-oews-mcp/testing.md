# BLS OEWS MCP: Testing Record

## Executive Summary

This Model Context Protocol server exposes BLS Occupational Employment and Wage Statistics (OEWS) data as callable tools for federal IGCE development, price analysis, and labor market research. It was hardened through a retroactive live audit with a real BLS API key (0.2.2, 22 findings), then re-audited end to end in round 7 (1.0.1) by an independent full-source review with live verification. Round 7 found 13 further bugs, headlined by a money bug the earlier "empirical" round had itself introduced: the four hourly percentile labels were shifted one slot, so requesting the Hourly Median returned the 75th percentile (26% high for Software Developers). The official mapping was pinned by cross-footing hourly x 2080 against the annual percentiles and is now guarded by a live canary test.

| Metric | Value |
|---|---|
| MCP tools exposed | 8 |
| Total regression tests | 298 (297 offline, 1 optional live parity check) |
| Audit rounds completed | 9 |
| P0 usability-breaking bugs found and fixed | 1 |
| P1 silent-wrong-data bugs found and fixed | 14 |
| P1 response-shape crash paths found and fixed | 12 |
| P2 validation gaps found and fixed | 12 |
| P3 cleanup items found and fixed | 8 |
| Content correction version | 1.1.4 (bundled May 2025 OEWS release; release gates recorded below) |
| PyPI status | Published as `bls-oews-mcp`, auto-publishes via Trusted Publisher on tag push |

## 1.1.4 realistic content audit, round 4 (2026-10-10)

No new P0, P1, P2 or P3 findings; no runtime, data, version or tool definition
change. A fresh official PyPI by-name installation with cache disabled resolved
1.1.4 and MCP 2.3.0. Its actual stdio CLI and the public HTTP service each
completed a separate 66-question corpus with identical content answers. The
public version and release SHA remained 1.1.4 and
`5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f`.

New tasks cover civil/environmental engineering, landscape design, environmental
science, planning, social services, paramedics and therapy, office support,
maintenance and transportation, communications and education. They use all
17 source measures across national, state, metro and national industry contexts;
Portland, Raleigh, Reno and Boise comparisons; employment/reliability and local
concentration; explicit supported-year/source discovery; and caller-selected
burdened IGCE anchors. Preschool special education teacher hourly publication
limits lead to successful annual followups and a disclosed hourly conversion.
Musician annual publication limits lead to successful hourly followups and IGCEs
without an invented annual salary. Career/technical postsecondary teachers have
published hourly data; the audit follows actual cells rather than inferring
publication behavior from an occupation title.

All **418 wage/benchmark objects** matched the bundled source, published
footnotes and arithmetic; reference metro mappings are counted separately.
**31 selected fresh official BLS API cells and footnotes** independently matched,
including annual-only/hourly-only publication followups. This does not assert
fresh external verification of every cell. The flat-file footnote refresh
returned **HTTP 403**, recorded as unavailable. General BLS technical-note and
FAQ concepts were reviewed separately; the web retrieval served May 2024 notes,
so those concepts do not establish May 2025 release values or area names.

Separate checks: frozen and fresh MCP 2.3 Python lanes each **297 passed,
1 optional live skipped, 298 collected**; native Worker **31 passed**; typecheck and package build passed;
all **8 reviewed tool definitions unchanged**; Python/Worker parity **227 cases,
216 identical, 11 documented differences, zero unexpected differences**. The
optional live parity test was not run; the 31 fresh API checks are a separate
audit source sample. Existing parity regressions are verification, not new
content questions. No package publication or deployment is required for these
documentation changes. Evidence is in Workspace
`Artifacts/mcp-e2e-20261010/round4/bls-oews/`, including `corpus.json`,
`actual-pypi-cli.json`, `public.json`, `per-question-semantic-review.json`,
`official-current-api.json`, `official-publication-followups.json` and
`official-flat-footnotes.json`. The initial 60-call captures and the question
wording clarification are retained in `initial-60-*` and `harness-notes.json`.

## 1.1.4 realistic content audit, round 3 (2026-10-10)

No new P0, P1, P2 or P3 findings; no package, code or tool metadata change.
58 new ordinary and power-user questions covered all eight tools through the
actual published 1.1.4 CLI (MCP 2.3.0) and public service at release
`5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f`. Each surface completed a separate
58-call corpus; their content answers were identical. This is new audit coverage,
not merely replay of round 2's 46 questions.

The corpus includes nursing, finance, logistics, law, electrical trades and
engineering, chemistry, operations management, purchasing, security, libraries,
recreation and coaching. It covers diverse state/metro comparisons, rural Alaska,
Puerto Rico, national industry filters, wage distributions, employment/RSE,
location quotients and coherent IGCE/source followups. Coaching's annual-only
salary retains the warning about an illustrative 2080-hour conversion; surgeon
percentile bounds retain official publication footnotes.

431 measure/benchmark objects matched the bundled May 2025 source, including
raw values, wage labels, footnotes and caller-selected burden arithmetic. Fresh
primary-source requests independently confirmed 28 current BLS API cells and their
original footnotes. The flat-file footnote URL returned HTTP 403; that check is
unavailable, not passed. Two draft SOC selection mistakes were corrected from the
source occupation table, retained as harness corrections and excluded from product
findings and final corpus counts.

Separate regression checks: **297 passed, 1 optional live skipped, 298 collected**
in the frozen Python lane; native Worker **31 passed**; all eight reviewed tool
definitions unchanged; typecheck passed; Python/Worker parity **227 cases,
216 identical, 11 documented differences, zero unexpected differences**. These
regression counts are separate from the two 58-call content replays and 28 fresh
API source checks. Evidence: Workspace's
`Artifacts/mcp-e2e-20261010/round3/bls-oews/`, including `checkpoint.json`,
`per-question-source-review.json`, `actual-pypi-cli.json`, `public.json`,
`official-current-api.json` and `official-coaching-followups.json`.

## 1.1.4 realistic content audit, round 2 (2026-10-10)

46 ordinary and power-user questions/followups covered all eight tools through
published 1.1.3 CLI, public HTTP service, and connector. Wage cells, percentiles,
employment, ratios, source labels and IGCE burden arithmetic matched the bundled
May 2025 BLS source. One P2 explained real unpublished teacher/performer measures
as possibly retired or unsurveyed occupations, and described a published physician
wage floor as no estimate. The correction preserves actual BLS footnotes and
suggests alternate wage measures for footnote 4; no wages or metadata changed.
Teacher annual and performer hourly followups complete the research task.

Candidate 1.1.4: 298 Python tests collected, 297 passed and one optional live
parity test skipped; native Worker 31 passed; 227 parity cases, 216 identical,
11 documented differences and zero unexpected differences. Both frozen MCP
2.0.0 and fresh candidate MCP 2.3.0 suites had these measured results; the optional
live parity test was skipped in those suites.

Published verification completed after scoped release `bls-oews/v1.1.4`, workflow
run [38069372010](https://github.com/1102tools-dev/federal-contracting-mcps/actions/runs/38069372010),
from source `5ba4a4bac4ecd098da1c48dcd09594d9e38fcf1f`. A fresh official PyPI
installation by package name with cache disabled resolved MCP 2.3.0. The installed
CLI and public HTTP service each passed a separate replay of all 46 original
questions and followups, including the corrected teacher/performer explanations,
successful alternate wage measures, physician lower-bound explanation, and all
numeric/source/IGCE arithmetic checks. The public service reported version 1.1.4
and the exact release SHA; both surfaces preserved all eight reviewed tool definitions.

The published wheel and sdist matched their official PyPI SHA-256 digests. All
nine package payload files were identical across wheel, sdist and installed package:

- Wheel `bls_oews_mcp-1.1.4-py3-none-any.whl`:
  `1cb5182ff1d5486d83919646401aee67fccf04a7b1eb15696eeca6d3e9d46c74`.
- Sdist `bls_oews_mcp-1.1.4.tar.gz`:
  `e28046ec92d7b1ff977fc4410c17731a1d1c488aab7acf881ce73d03de57bb97`.

Twenty current official BLS API cells and their original footnotes independently
matched the bundled May 2025 source. The flat-file footnote refresh returned HTTP
403; that source-access limitation is retained rather than claimed as a successful
refresh. Published content replays are separate from the candidate regression
suite counts above. Evidence is retained in Workspace's
`Artifacts/mcp-e2e-20261010/round2/bls-oews`, including
`published-final-completion.json`, `published-cli-final.json`, `public-final.json`,
`published-payload-final.json` and `official-api-source-check.json`.

## 1.1.3 installed CLI compatibility correction (2026-10-10)

A fresh official PyPI installation of 1.1.2 resolved MCP 2.3.0. A normal
question about national software-developer employment ratios returned only
"Error executing tool get_wage_data", losing the guidance that those ratios
exist only at state/metro scope. The SDK now redacts unexpected ValueError
failures. The public Worker retained the expected message.

Intentional user-input failures now inherit both ValueError (preserving direct
Python callers) and the SDK's anticipated ToolError. Internal series-length
invariant failures remain ordinary exceptions. There is no dependency downgrade
or tool metadata change. A real installed-CLI regression failed against published
1.1.2/MCP 2.3.0 before the patch, then passed against the installed 1.1.3 wheel,
including a valid Virginia ratio followup that completes the user's task.

Measured full suites: **294 passed, 1 skipped, 295 collected** under both frozen
MCP 2.0.0 and freshly resolved MCP 2.3.0. An installed-wheel CLI client called
all eight tools plus the hourly-only musicians/actors and annual-only teacher
controls; all passed. Worker typecheck and **29 tests** passed. Python/Worker
parity remains **222 cases, 211 identical, 11 documented differences, zero
unexpected**. All eight tool definitions are unchanged; wheel/sdist builds,
version consistency, and new-PyPI-version guard passed. These are pre-release
corrective checks; actual 1.1.3 publication and rollout checks remain separate.

## 1.1.2 end-to-end content audit (2026-10-10)

Current-source and live-connector checks covered all eight tools, national/state/
metro wages, industry 999100, all-occupation aggregates, published and suppressed
cells, annual-only and hourly-only jobs, reliability, duplicate normalization,
unsupported years and geographic/industry combinations. Historical round 9
corrections were verified against the current live service.

Two new P2 defects were fixed in Python and the native Worker: hourly-only IGCEs
discarded published hourly wages and falsely claimed no wage estimate; requesting
national ratios 16/17 falsely implied missing occupation data. Hourly-only
benchmarks retain the published rates without fabricating annual salaries;
national ratio requests return an actionable state/metro validation error.

Measured checks: **293 offline passed, 1 live test skipped** in the ordinary run;
the separately enabled **live BLS API parity test passed** for its 25 series.
An additional direct official BLS API check matched all eight mean/median,
hourly/annual series and footnote codes for the musicians original and actors
followup.
The Worker suite passed **29 tests** and typechecking passed. The full-release
Python/Worker harness checked **222 cases: 211 identical, 11 pre-existing
documented transport/format differences, 0 unexpected differences**. All eight
reviewed tool definitions remain unchanged. Version consistency and wheel/sdist
build succeeded for 1.1.2. New regressions failed against the original hourly-only
behavior before the fix; musicians and actors were rerun after the fix.

These are pre-release checks. Published-wheel and deployed-live verification
belongs to the coordinated release and is not claimed here.

## 1.1.0 Bundled release (2026-09-26)

1.1.0 stops calling the BLS API. Every tool answers from the current OEWS
release, bundled as a read-only SQLite database that
`scripts/build_oews_db.py` builds from BLS's flat files
(download.bls.gov/pub/time.series/oe/, published May 15, 2026): 6,023,970
data rows pivoted into 370,172 estimate cells covering 583 areas, 444
industries, and 1,104 occupations. The build fails on schema drift (changed
headers, an unexpected datatype set, more than one release, codes missing
from the mapping files, or row counts moving more than 10%), and two builds
from the same files produce byte-identical output.

Verification, all on 2026-09-26:

| Check | Result |
|---|---|
| Parity with the live BLS v1 API (fixed 25-series sample: national, state, metro, industry, unreleased "-" with footnote 8, top-coded with footnote 5, annual-only pilots) | 25/25 values and footnote codes match |
| A second, random 25-series sample against the live API during development | 25/25 match |
| Offline suite (network blocked in `conftest.py`) | 275 passed |
| Rounds 6 and 8, written against the live API, run against the bundled release | 157 passed, now ungated and part of every run |
| Wheel installed into a clean Python 3.12 environment | Decompresses the database, verifies its SHA-256, answers `get_wage_data` |
| Hosted image (`deploy/bls-oews/Dockerfile`, linux/amd64) run locally | `/health` ok with 8 tools; `scripts/verify_hosted_release.py --no-upstream` passed (version, tool contract, no instructions, bundled source) |

The tool count stays 8: `get_access_status` became `get_data_status`.
Behavior that depended on the live API was retired with it: the v1/v2 key
modes, request pacing, the credential redaction paths, and the
`REQUEST_PARTIALLY_PROCESSED` and non-JSON response handling. Their tests
(`test_access_status.py`, `test_credential_redaction.py`, `test_pacing.py`,
and the API-shape cases in `test_validation.py` and `test_audit_r7.py`) were
removed. Tests that previously called the live API and swallowed errors now
assert exact values from the bundled release.

## 1.0.4 Safety Release Verification

The complete offline suite passed 85 tests with 164 live tests gated. Shared
pacing tests additionally verified 3- and 4-second fake-clock intervals,
cross-process serialization, key isolation, shared `api.data.gov` buckets,
invalid overrides, and all `Retry-After` forms. No federal API was called.

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

The repo ships 291 regression tests (290 offline, 1 optional live parity check). The offline suite runs on every release with the network blocked; the parity check runs with `BLS_LIVE_TESTS=1` and needs no key. See [tests/README.md](tests/README.md) for the per-file map.

| File | Purpose | Test count |
|---|---|---|
| `tests/test_validation.py` | Main regression suite covering rounds 0.2.x, with exact bundled values | 58 |
| `tests/test_audit_r6.py` | Round 6 sweep (written live; runs offline since 1.1.0) | 154 |
| `tests/test_audit_r7.py` | Round 7 regressions: datatype semantics, annual-only detection, normalized dedup, seeded gaps, FIPS validation, plus the cross-foot canary | 19 |
| `tests/test_audit_r8.py` | Round 8 anchors | 3 |
| `tests/test_snapshot.py`, `test_builder.py`, `test_directory_contract.py`, `test_http.py` | 1.1.0 bundled release, builder, directory rules, hosted HTTP app | 41 |
| `tests/test_content_r9.py` | Round 9 content corrections BLS-1 to BLS-9, checked against BLS source values and labels | 15 |
| `tests/test_live_parity.py` | Bundled values vs the live BLS API | 1 |
| `tests/scenarios/stress_test.py` | Scenario script (not pytest) retained for reproducibility | N/A |

Regression tests invoke tools through the MCPServer registry (`mcp.call_tool`).

## Release History

| Version | Focus | Outcome |
|---|---|---|
| 0.1.1 | Initial release (smoke tested, reported "zero bugs"; reality was 22+ lurking) | Baseline coverage |
| 0.2.0 | First hardening pass (mocks only) | Baseline validation |
| 0.2.1 | Cross-MCP `extra='forbid'` back-port from sam-gov-mcp 0.3.1 | +1 regression test |
| 0.2.2 | Full retroactive live audit with real BLS key | 22 findings resolved |
| 1.0.0 | mcp 2.x SDK rebase, version sync, packaging | Stable baseline |
| 1.0.1 | Round 7 independent re-audit with live verification | 13 findings resolved, incl. the datatype label shift money bug; live cross-foot canary added |
| 1.0.3 | Opt-in production pacing for real-key traffic | Concurrent upstream calls serialize and wait after completion; offline concurrency regressions added |
| 1.1.1 | Round 9 content corrections; paired Python/Worker regressions and source-backed repro gates | 291 collected: 290 offline, 1 optional live parity |
| 1.1.0 | Bundled May 2025 OEWS release; no API key or network calls; hosted HTTP entry point | 25/25 live parity; rounds 6 and 8 run offline; 276 tests |

## Cross-MCP Context

This MCP is one of eight servers in the 1102tools federal-contracting MCP suite (`ecfr-mcp`, `federal-register-mcp`, `gsa-calc-mcp`, `gsa-perdiem-mcp`, `regulationsgov-mcp`, `sam-gov-mcp`, `usaspending-gov-mcp`, and this one). All eight were hardened under the same playbook. Patterns reused or established here:

- **"Smoke test said zero, live audit found everything" lesson** was codified here, then extended in round 7: shape-only live assertions are nearly as blind as mocks. Semantic invariants (the 2080 cross-foot) are the durable guard.
- **Response-shape defensive-parsing helpers** `_as_list`, `_extract_first_data_entry`, `_safe_footnotes` were exported to other MCPs that face similar XML-to-JSON collapse edge cases.
- **`_api_key_status` pattern** for warning the user when an API key is empty or whitespace was codified here.
- **`extra='forbid'` on every tool's pydantic arg model** was back-ported from sam-gov-mcp 0.3.1 in the 0.2.1 release.

## What Was Not Tested

- **Historical data years.** Only the current release is bundled. Users needing historical data are directed to `bls.gov/oes/tables.htm`.
- **The next BLS release.** A new release (expected spring 2027) is detected by the weekly source watch and ships as a reviewed package release; the rebuild, golden values, and parity check are repeated then.
- **Parity beyond the sample.** The live comparison covers a fixed 25-series sample plus one random sample; the rest of the release is trusted to the builder's one-to-one copy of BLS's published values.

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root and can be re-executed by anyone. The live parity check runs with `BLS_LIVE_TESTS=1 pytest tests/test_live_parity.py` and needs no key.

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 during the original hardening playbook, and Claude Code Fable 5 for the round 7 independent re-audit (full-source review, live API verification, record correction).

Round 7 methodology: re-read the entire server source with no reliance on this document's claims; verify every constant table and datatype code against production BLS responses; recompute composite-tool math by hand; replay documented API shapes through the real tool pipeline; check every prior claim in this document against the code and live behavior.

Test count: 249 regression tests (85 offline, 164 live-gated). Total findings across all rounds: 35. Current version: 1.0.5. PyPI: `bls-oews-mcp`.

Source: github.com/1102tools-dev/federal-contracting-mcps/tree/main/servers/bls-oews-mcp. License: MIT.


## Round 8 (2026-08-18): suite-wide live verification (super-cycle)

The full live-gated suite ran wholesale against production for the first time
(historically prevented by key quotas): 243 passed after one drift fix (2m41s). No new server
defects. Upstream drift caught and fixed: BLS rolled OEWS to 2025; a test hardcoding year=2024 tripped the server's own (correct) release guard. The test now derives the latest year at runtime. Added `tests/test_audit_r8.py`: 3
one-call-per-test live contract anchors re-stamping this server's headline
fixes against production (all verified green on landing), a suite-wide pacing
conftest with a `live_smoke` marker, and a per-test client reset so batched
live runs cannot hit the cached-AsyncClient/closed-event-loop trap.

## RC5 pacing remediation (2026-08-22)

Version 1.0.5 carries the suite-wide asynchronous pacing-lock correction. The full offline lane passed (85 tests; 164 live-gated tests skipped), including deterministic same-process concurrency coverage. The published PyPI wheel was then installed in an isolated cache and completed MCP startup and `tools/list` with 7 tools.


## 1.1.1 source-backed content corrections (2026-10-10)

Round 9 adds 15 Python regressions in `tests/test_content_r9.py`, paired
with Worker tests. The complete Python 3.12 suite recorded 290 passed and
1 optional live parity check skipped. Worker tests recorded 27 passed and
TypeScript checks passed. Cross-runtime parity recorded 218 cases: 207
identical, 11 documented differences and zero unexpected differences.
The hosted tool contract and package-version validation passed.

| Finding | Regression coverage |
|---|---|
| BLS-1 | IGCE states the release month and escalation guidance; a changed release label changes both fields |
| BLS-7 | Norfolk help desk uses published hourly $19.01, Colorado Springs architects use $64.14; annual-only occupations retain derived-hourly warning |
| BLS-3 | Colorado Springs DBA 25th/75th annual and hourly percentiles match BLS |
| BLS-2 | Employment and both RSEs, high-RSE warning, no warning for a solid estimate, and no numeric benchmark for wageless cells |
| BLS-4 | Top-coded and unreleased wages retain employment and BLS footnotes, with wider-area guidance |
| BLS-5 | Govcon metro/SOC additions and every starter label match the bundled BLS lookup tables |
| BLS-6 | Industry labels match BLS and the description points federal IT searches to 15-1299 |
| BLS-8 | Comparison data year and requested order are retained; ordering already worked before this release |
| BLS-9 | Employment per 1,000 retains BLS's three decimals; location quotient retains two |

The 12 finding repro gates use BLS's May 2025 flat-file values, names and
footnotes, rather than treating our own output as the source of truth.
Python and Worker tests were seen failing before the corresponding fixes.
The data, schema and loader are unchanged, so these corrections require
no D1 reload. No logging, IP-retention or cache-policy changes were made.

Deferred scope: comparison tools remain single-datatype queries (request
01/02/05 separately for reliability); top-coded wage floors do not become
burdened benchmarks; escalation index/rate selection remains with the
analyst; the pre-existing binary-float half-cent rounding remains unchanged.
