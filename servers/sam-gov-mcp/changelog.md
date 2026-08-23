# Changelog

## 1.0.9

Redacts raw and URL-encoded SAM.gov credentials from upstream bodies, parsed
payloads, raw-response fallbacks, HTTP and network exceptions, and structured
tool results. Invalid-format guidance no longer echoes even a credential
prefix. Deterministic regressions cover each model-visible failure path.

## 1.0.8

Serializes concurrent same-process requests by API identity before acquiring
the existing cross-process file lock. This preserves configured pacing while
preventing same-process lock contention from deadlocking concurrent calls.

## 1.0.7

Host-neutral credential guidance. The missing-key error no longer names a
specific client application or configuration file. It now states which
environment variable to set and points to the client's own MCP credential
configuration, so the message is correct for any MCP host rather than one
desktop application. No tool, parameter, or response behavior changed.

## 1.0.6

Suite-wide API safety release. Every SAM.gov request, including subrequests
inside composite tools, now passes through a 3-second default cross-process
gate keyed by a one-way credential fingerprint. Provider `Retry-After` is
honored without automatic retries. The 429 message no longer assumes every
limit is a depleted daily quota, and publication now requires the complete
offline test matrix and wheel inspection.

## 1.0.5

Version-marker sync. The 1.0.4 wheel self-reported 1.0.2 in serverInfo:
`__version__` was still hardcoded and the round-9 "version sync" regression
test compared serverInfo to that same constant, so both drifted together.
All version markers (`__version__`, USER_AGENT, serverInfo) now derive from
installed package metadata with pyproject as the single source of truth, and
the test pins against `importlib.metadata`.

## 1.0.4

Round 10: a ~230-call paced live campaign against production over two nights
(13 serialized probe rounds, zero throttle events). All five round-9 pending
items resolved and ten new findings fixed or documented; full narrative in
testing.md "Round 10".

### Fixed

- **Contract Awards fiscal_year floor moved from 2008 to 1970.** The API
  serves data back to FY1970 (FY1980 alone has 634k records); the old floor
  silently walled off four decades. A 4-digit year guard was added because
  the API accepts 2-digit years and returns an empty shape for them.
- **registration_status restricted to A/E.** D and I are accepted by the API
  but return 0 records for every query, guaranteeing empty results; comma
  lists like "A,E" also match nothing.
- **Bare-string JSON error bodies on HTTP 200 now raise instead of
  normalizing into totalRecords=0** (an API error masquerading as an empty
  result set).
- **Assistance subawards agency_code validated as four digits** with a clear
  message; the API rejects 3-digit CGAC codes like 075.
- The 429 message no longer implies the key's role determines quota; the
  rate plan is set per-key on the SAM.gov side and is independent of role.

### Documented

- `offset` is a ZERO-BASED PAGE INDEX on Opportunities and Contract Awards
  (offset=1 with limit=100 returns records 101-200), while Federal
  Hierarchy's `offset` is a true record offset. REST-convention
  `offset += limit` on the first two silently skips almost everything.
- Opportunities pages past the end return one arbitrary record instead of an
  empty page; terminate pagination from totalRecords math.
- Contract Awards enforces offset x limit < 400,000 (exactly 400,000 returns
  HTTP 500 upstream); only the first 400k records of a result set are
  pageable.
- Subaward endpoints hang past the last page rather than erroring.
- A UEI can return multiple registration records; `samRegistered=No` reaches
  a separate ~614k-record "ID Assigned" population.

### Testing

- Suite grew to 1,136 (762 offline, 374 live-gated). Live tests are paced
  2-4 s apart by conftest; a minimal anchor set runs via `-m live_smoke`.
- The paced live-probe harness behind round 10 ships at `tests/live_audit/`.

## 1.0.3

No code changes. Republish to verify the Trusted Publisher pipeline after the repo moved to the 1102tools-dev account.

## 1.0.2

Round 9: independent full-source re-audit against the official API docs and
the SAM Functional Data Dictionary. 8 findings fixed; 5 more are documented
in testing.md pending live confirmation (the audit key's daily quota was
exhausted across every endpoint family).

### Fixed

- **get_entity_reps_and_certs read the wrong JSON key casings and its
  default summary mode returned empty clause lists for every entity.** The
  Entity API documents certifications.fARResponses / dFARResponses (mixed
  case) with architectEngineerResponses under qualifications; the code
  read farResponses / dfarsResponses / certifications.architectEngineer-
  Responses, none of which exist. A CO asking for FAR 52.212-3 or 52.219-1
  answers was told the entity certified nothing. Survived eight audit
  rounds because the round-6 live tests asserted only totalRecords
  presence. Keys now resolve case-insensitively (robust to either casing
  and future drift) and architectEngineerResponses is sourced from
  qualifications first. Documented-shape replay tests pin non-empty
  summaries and clause_filter matching.
- Opportunities set-asides: the table had 14 of the 18 documented codes.
  LAS (Local Area), IEE and ISBEE (Buy Indian Act), and BICiv (IHS Buy
  Indian) were impossible to search; BICiv's documented mixed casing now
  survives validation and goes on the wire as documented.
- business_type_code accepts the full FDD set: the 13-code whitelist
  blocked legitimate filters (NB Native American Owned, JV SDVOSB Joint
  Venture, A3 Labor Surplus Area, 1E/1S Buy Indian, A7 AbilityOne, M8
  Educational Institution, ...). Well-formed 2-character codes pass
  through; SBA certification codes still redirect to
  sba_business_type_code.
- purpose_of_registration accepts Z1-Z5: Z3 (IGT Only) and Z4 (Federal
  Assistance and IGT) were pydantic-rejected, and Z5 was mislabeled
  "Supplemental grants only" (it is All Awards and IGT).
- Bracketed date ranges on the Opportunities single-date params no longer
  pass validation and then crash with "too many values to unpack"; they
  are rejected with guidance to use the _from/_to pair. Endpoints that
  genuinely take ranges (Contract Awards, Exclusions) are unchanged.
- lookup_award_by_piid sorts modifications client-side (numeric mods in
  numeric order, then alpha mods) and flags truncation with a _note when
  totalRecords exceeds the 100-record page, instead of returning an
  unsorted silent first-100 while claiming "all modifications, sorted".
- Leading zeros survive int coercion: zip_code=6511 now searches 06511
  (New Haven) and cgac=75 searches 075 (HHS, the readme's own example);
  both previously searched zero-stripped values that silently return
  nothing or the wrong org.
- Version stamps synchronized at 1.0.2 (__version__ had drifted to 1.0.0
  while pyproject said 1.0.1, one release after the changelog claimed
  they were "now synchronized"); serverInfo.version is now populated and
  pinned by a regression test.

### Testing

- tests/test_audit_r9.py: 16 offline regressions including the
  documented-shape reps-and-certs replay.
- testing.md round 9 corrects the record (four mutually inconsistent
  test counts, the 15-tools claim, the phantom coverage table, the
  363-day test masquerading as the 364-day boundary, the circular
  set-aside coverage claim) and lists the 5 quota-blocked probes with
  exact confirming tests.

## 1.0.1

### Fixed

**`SBA_BUSINESS_TYPE_CODES` had XX mislabeled as "8(a) Certified".** Per the
SAM Functional Data Dictionary ("Business Types" field), XX is SBA Certified
HUBZone Firm and A6 is SBA Certified 8(a) Program Participant. The table now
carries all four SBA-determined codes from the dictionary, A6 (8(a) Program
Participant), JT (8(a) Joint Venture), XX (HUBZone), A4 (Small Disadvantaged
Business), plus two newer codes pinned and live-verified from entity data:
A9 (SBA-Certified WOSB, 13K+ active registrants) and A0 (SBA-Certified
EDWOSB, 4K+). The mislabel is why round-1 guide testing could not find 8(a)
firms.

### Added

**`search_entities` gained `sba_business_type_code`**, mapped to the Entity
Management API's `sbaBusinessTypeCode` query parameter. SAM.gov filters SBA
certifications through that dedicated parameter, so 8(a) and HUBZone searches
were previously impossible: `business_type_code` sends `businessTypeCode`,
which covers self-selected types only. Passing an SBA certification code to
`business_type_code` now raises a redirect error naming the new parameter
instead of silently searching the wrong field.

## 1.0.0

First stable release. The suite is feature-complete for its intended scope and
moves to baseline maintenance from here.

### Breaking

Requires **v2 of the MCP Python SDK** (`mcp>=2.0.0`). Version 2 renamed the
high-level server class from `FastMCP` to `MCPServer` and removed the
`mcp.server.fastmcp` module. No tool name, parameter, or response shape changed.
Installs pinned to `mcp` 1.x should stay on the 0.x line of this package.
The requirement is now bounded (`mcp>=2.0.0,<3`) so a future major release of
the SDK produces a clean resolver error instead of an import-time crash.

**Claude Desktop `.mcpb` bundles are discontinued.** Bundles could not be
signed in a way Claude Desktop recognizes, so every install surfaced an
untrusted-developer warning, and because the bundle shipped without a lockfile
it re-resolved its dependencies on every launch, which is what made it the
install path most exposed to the failure above. Install via `uvx`, `pip`, or
Docker instead; the per-server readme has the client config block. Existing
bundle installs keep working until removed, but will not receive updates.

Earlier releases declared `mcp>=1.0.0` with no upper bound. When `mcp` 2.0.0
published, fresh installs of the 0.x line resolved to it and failed at import
with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. Requiring
`mcp>=2.0.0` closes that gap.

### Changed

- Package version, `__version__`, `USER_AGENT`, and the MCPB manifest version
  are now synchronized. The USER_AGENT currency test derives its expected value
  from package metadata rather than a hardcoded literal, which is why the string
  had drifted a patch behind the package.
- Declares Python 3.10 through 3.14. Classifiers normalized across all eight
  servers.

### Fixed

- `lookup_psc_code` described retired PSCs as invalid. The endpoint defaults to
  `active_only='Y'`, so a real but retired code returns HTTP 404. The translated
  error now explains that and points to `active_only='ALL'`, which returns the
  retired entry and its end date. D302 is the worked example: a genuine PSC,
  retired 2020-10-29.

### Verified

1,094 regression tests (729 offline, 365 live-gated), all passing
against `mcp` 2.0.0 on Python 3.14, with pass counts identical to the pre-migration
baseline on `mcp` 1.x. Server confirmed to boot over stdio and enumerate all
19 tools.

## 0.4.0

Added Federal Hierarchy and FFATA Subaward Reporting endpoints. Tool count
goes from 15 to 19. 278 new regression tests (155 offline, 123 live). All
4 new endpoints have 25+ live tests each.

### New tools

- `search_federal_organizations` - Search the SAM.gov Federal Hierarchy by
  org id, name, type, status, agency code, or CGAC. Useful for normalizing
  agency names to canonical FH IDs before passing them to Contract Awards,
  Opportunities, or Subaward searches.
- `get_organization_hierarchy` - Walk the immediate children of a federal
  organization. Combine with the search tool to traverse the full agency
  tree.
- `search_acquisition_subawards` - Search FFATA subcontract reports
  (acquisition subawards). Maps prime contractors to their subs and surfaces
  the full distribution of a federal procurement dollar.
- `search_assistance_subawards` - Search FFATA grant subaward reports.
  Traces federal grant funds from prime recipient to subrecipients.

### P1 bugs found in live audit (would have shipped silent-wrong-data)

Three Subaward API parameters whose documented casings are silently ignored
by the production SAM.gov API. The ignored variants return the unfiltered
~2.7M-record universe regardless of the value passed. Caught by regression
tests that compare filtered vs. baseline `totalRecords` and assert the
filtered count is strictly smaller. Without live audit, every PIID-,
referenced-IDV-, or referenced-IDV-agency-scoped subaward query would have
silently returned every subaward in the system.

| Tool param | Documented casing (broken) | Working casing |
|---|---|---|
| `piid` | `PIID` | `piid` |
| `referenced_idv_piid` | `referencedIdvPIID` | `referencedIDVPIID` |
| `referenced_idv_agency_id` | `referencedIDVAgencyID` | `referencedIDVAgencyId` |

### P2 fixes

- `fh_org_type` whitelist removed. Initial implementation restricted to enum
  values like `DEPARTMENT`, but the live API returns values like
  `Department/Ind. Agency`. Whitelist was rejecting real values that users
  would copy-paste from response records. Now WAF-safe + length-clamp only.
- `status=ACTIVE` on Federal Hierarchy is a no-op. API defaults to
  ACTIVE-only when no filter is sent. Docstring updated.
- `USER_AGENT` bumped to 0.4.0 (was stale at 0.3.7).

### API surface notes baked in

- Federal Hierarchy uses lowercase `totalrecords` / `orglist` (rest of
  SAM.gov uses camelCase). Normalizer preserves both keys.
- Subaward APIs use ISO `yyyy-MM-dd` dates (rest of SAM.gov uses
  MM/dd/yyyy). New `_validate_date_yyyy_mm_dd` validator enforces this
  with a clear error message that explains the divergence.
- Subaward APIs use `pageNumber`/`pageSize` for pagination (rest of SAM.gov
  uses `limit`/`offset` or `page`/`size`).
- Subaward Acquisition API rejects PIIDs containing hyphens server-side
  ("Piid must be alphanumeric"). Older FSS-style PIIDs like `GS-35F-0119Y`
  return HTTP 400. We surface the API error verbatim rather than
  pre-restricting at the validator.

### Wage Determinations

A spike on adding wage determinations (SCA/DBA) concluded: not viable as
part of `sam-gov-mcp`. No documented public REST API exists at
`api.sam.gov`, no entry on `open.gsa.gov`, and DOL retired WDOL.gov in 2019.
The only working endpoint is the website's internal search
(`https://sam.gov/api/prod/sgs/v1/search/?index=wd`), which is anonymous,
undocumented, and returns metadata only (the actual rate tables live in
PDFs behind the UI). If wage-determination support is added later it will
be a separate, experimental module with isolated client and metadata-only
scope.

## 0.3.7

Round 7: offline property test suite using Hypothesis-driven property-based
testing. 133 new test functions, ~25,000 actual probes generated by
Hypothesis. Two real bugs found and fixed.

### P3 bug: _safe_int crashed on inf/nan floats

`_safe_int(float('inf'))` raised `OverflowError` instead of returning the
default value. The function caught `(TypeError, ValueError)` but not
`OverflowError`, which `int(inf)` raises. If a CDN or proxy ever returned
`inf` as a numeric value (rare but possible), the parser would crash.
Fix: added `OverflowError` to the except clause.

### P3 bug: _normalize_awards_response returned empty dict on empty CDN responses

When the API returned `{}` (no expected fields), `_normalize_awards_response`
passed it through unchanged. Downstream callers that did `response["totalRecords"]`
would then crash with KeyError. Fix: ensure callers always see at least
`totalRecords=0` and `awardSummary=[]` even on unrecognized response shapes,
plus a `_note` field explaining the situation.

### Round 7 coverage (133 test functions, ~25,000 probes)

Bucket | Functions | Hypothesis examples per function
---|---|---
A. UEI validator property tests | 6 | 500 each
B. CAGE validator property tests | 3 | 500 each
C. Date validator property tests | 4 + 9 specific | 500 each
D. NAICS validator property tests | 3 | 500 each
E. Fiscal year property tests | 2 | 500 each
F. WAF validator property tests | 3 | 500 each
G. _clamp property tests | 1 | 500
H. _coerce_str property tests | 2 | 500 each
I. _safe_int property tests | 4 | 500 each
J. _as_list property tests | 3 | 500 each
K. _normalize_awards_response fuzz | 3 | 500 each
L. _clean_error_body fuzz | 3 | 500 each
M. _clamp_str_len property | 1 | 500
N. Async concurrency stress | 4 | mixed
O. Encoding edge cases (emoji, CJK, RTL, normalization) | 3 + 6 + 9 specific | 500 each
P. Composite tool deep tests | 8 specific |
Q. Integer overflow/boundaries | 2 | 500 each
R. String-with-numbers coercion | 1 | 500
S. Mock response shape fuzz | 22 specific shapes |
T. Async event loop isolation (50 sequential runs) | 1 | 50 iterations
U. Historical bug regressions | 4 specific |
V. Deep nested response structures | 4 specific (depths 1-20) |
W. _safe_int specific edge values | 24 specific values |

### Test counts after round 7

- `tests/test_validation.py`: 79 (73 offline + 6 live-gated)
- `tests/test_density_r5.py`: 369 offline parameterized tests
- `tests/test_live_audit_r6.py`: 235 live-gated tests
- `tests/test_round_7.py`: 133 offline Hypothesis + fuzz tests
- **Total: 816 regression tests (574 offline, 242 live-gated)**
- **Density: 54.4 tests per tool** (15 tools)

### Why Hypothesis matters

Hand-written tests only cover the inputs the author thought of. Hypothesis
generates inputs the author never would have written: combining-character
unicode in UEI, surrogate pairs in queries, year 1582 calendar transitions,
inf/nan floats, integer values at sys.maxsize boundaries. The two bugs
found in this round were both inputs no one would write by hand:
`float('inf')` as totalRecords and an empty `{}` response body. Both have
real-world causes (CDN/proxy mishaps, partial API responses) that mocks
never would have surfaced.

## 0.3.6

Round 6: live audit. 235 new live-gated tests covering every tool against
the production SAM.gov API. One P1 bug found and fixed.

### P1 silent-bug found in round 6 live audit

`search_exclusions(entity_name=...)` sent the API parameter `entityName`
which SAM.gov rejects as `INVALID_SEARCH_PARAMETER`. The correct upstream
field is `exclusionName`. Anyone calling search_exclusions with a name
filter got an HTTP 400 with no result. Fix: parameter mapping changed from
`entityName` to `exclusionName` in server.py. The tool's own `entity_name`
parameter name stays the same to preserve the public interface.

### Round 6 live test coverage (235 tests, runtime ~3-5 minutes)

Each test makes a real HTTP call against api.sam.gov and verifies behavior
that mocks cannot see. Skipped automatically when `SAM_LIVE_TESTS=1` is
not set so default pytest runs stay fast.

Bucket | Count | Coverage
---|---|---
A. WAF behavior live | 17 | Apostrophes (McDonald's, L'Oreal, O'Brien, etc.), ampersands, unicode, angle brackets, SQL keywords all confirmed accepted by SAM.gov
B. Entity lookups | 13 | UEI/CAGE lookups across all `include_sections` combinations, lowercase normalization, whitespace stripping, nonexistent UEI handling
C. Entity search | 20 | `legal_business_name` partial matching, `free_text` search, NAICS/state/business-type filters, pagination at high pages, combined filters
D. Exclusions | 10 | Country filters, classification types (Firm/Individual/Vessel/Special Entity), state filtering, exclusion programs, name searches via `exclusionName`
E. Vendor responsibility check | 5 | Real UEIs through the full 2-API-call composite, flag list verification, padding/whitespace handling
F. Opportunities | 21 | All 14 set-aside codes, all 9 notice types, NAICS/state/zip filters, compound filters, 364-day span boundary
G. Contract awards | 16 | All fiscal years FY2008-FY2026, NAICS with `~`/`!` operators, PSC filtering, PIID/UEI/CAGE/awardee lookups, dept code filtering, modification number filtering, AWARD vs IDV distinction
H. PSC lookups | 16 | Real codes across categories (R, D, AJ, B, J, Y, Z), free-text queries (cyber, professional, engineering, etc.), unicode and apostrophe queries
I. Entity deep sections | 5 | Reps and certs (summary + full mode), integrity info (FAPIIS proceedings)
J. Search deleted awards | 5 | Previously zero coverage; now exercises pagination, dept code filtering, max limit
K. Concurrent calls | 3 | 5 concurrent searches, 3 concurrent lookups, mixed-tool concurrency
L. Response shape verification | 10 | Per-tool field presence checks that catch upstream API drift
M. Edge cases | 11 | Unicode CJK, emoji, max-length names, single-day windows, padded UEIs
N-S. Exhaustive coverage | 89 | Every set-aside code, every notice type, every supported FY, top procurement NAICS and states, common PSC categories

### Test counts after round 6

- `tests/test_validation.py`: 79 (73 offline + 6 live-gated, unchanged from rounds 1-4)
- `tests/test_density_r5.py`: 369 offline parameterized tests
- `tests/test_live_audit_r6.py`: 235 live-gated tests
- **Total: 683 regression tests (441 offline, 242 live-gated)**
- **Density: 45.5 tests per tool** (15 tools)

### Why this round mattered

Round 5 was a coverage expansion against the existing code. Round 5 found
zero new bugs because it didn't test the live API. Round 6 hit the live
API hard and immediately found a real bug (entity_name) that had been
shipping broken for at least one release cycle. This is exactly what the
0.3.1 release record predicted: "live audit surfaces bugs mocks cannot
catch." The pattern held.

## 0.3.5

Round 5 density expansion. No code changes to `server.py`. The audit added
369 new regression tests organized into 10 distinct failure-mode buckets,
lifting suite-wide coverage from 79 tests (5.3 per tool) to 448 tests
(29.9 per tool). 

### Coverage by failure-mode bucket
1. UEI format validation across every UEI-taking tool, parameterized
   across 14 invalid format variants per tool (~70 tests)
2. CAGE format validation across every CAGE-taking tool (~15 tests)
3. PIID format validation including embedded control character cases (~9 tests)
4. PSC code format and `active_only` Literal value validation (~16 tests)
5. Date format validation across every date-taking tool, including
   leap year correctness for FY2024 vs FY2025 (~50 tests)
6. Pagination, limit, and offset boundary checks across all 5 search
   tools including the previously-untested `search_deleted_awards` (~30 tests)
7. WAF and control-character safety: null bytes, tab/CR/LF/CRLF rejected;
   apostrophes, angle brackets, SQL keywords, unicode (CJK and emoji)
   verified as accepted (~30 tests)
8. `extra='forbid'` enforcement verified individually on all 15 tools (~18 tests)
9. Filter-code validation: state codes, NAICS, business types, set-aside
   codes, fiscal year boundaries, country codes (~30 tests)
10. Direct unit tests on validator helpers: `_coerce_str`, `_safe_int`,
    `_as_list`, `_normalize_awards_response`, `_validate_uei`, `_validate_cage`,
    `_validate_naics`, `_validate_fiscal_year`, `_validate_date_mmddyyyy`,
    `_clamp`, `_clean_error_body`, `_validate_waf_safe`, `_clamp_str_len`,
    `_current_fiscal_year` (~80 tests)

### Test file structure
- `tests/test_validation.py` (existing 79 tests, unchanged): rounds 1-4
  plus live-key audit regressions
- `tests/test_density_r5.py` (new 369 tests): round 5 density expansion

### Why this matters
Each new test exercises a distinct failure mode. No padding, no shape
duplicates. Engineers reviewing the suite will see that every input field
on every tool has format, boundary, type, and injection coverage. Density
of 29.9 tests per tool.

## 0.3.1

Live-audit follow-up. With a real SAM.gov API key we re-ran every tool
against the live API and found 3 P1 bugs that the 0.3.0 mocked audit
rounds could not have caught. All fixed.

### Silent-wrong-data fixes (P1)
- The WAF pre-filter introduced in 0.3.0 was almost entirely false
  positives. It rejected single quotes (`'`), backticks, angle
  brackets, and SQL keywords on the theory that SAM.gov's upstream WAF
  would drop the connection. Live testing proved SAM.gov accepts all
  of these as literal search text. The filter was blocking legitimate
  company-name searches: McDonald's, L'Oreal, O'Brien, O'Reilly,
  etc. all raised a spurious "WAF triggered" error. Filter narrowed
  to just null bytes and control characters (tab, CR, LF), which
  really do break URL encoding or the API.
- Unknown parameter names were silently dropped. FastMCP tools
  generate pydantic argument models with the default `extra='ignore'`
  config, so a typo like `search_entities(keyword='Lockheed')` (the
  real parameter is `free_text`) succeeded with the typo parameter
  silently discarded -- the tool then hit the API with no filters
  and returned all 700k+ entities. Applied `extra='forbid'` to every
  tool's arg model after registration. Typos now raise
  `Extra inputs are not permitted` before any HTTP call.
- `lookup_award_by_piid` accepted empty / whitespace PIID, making an
  API call that returned empty with no indication of the problem.
  Now raises a clear error up front.

### Error-message clarity (P3)
- PSC lookup 404s used to leak SAM's opaque
  `{"response": "Entered search criteria is not found"}` body. Now
  translated to: "SAM.gov did not find any record matching your
  search. For PSC codes: verify the code exists at
  https://www.acquisition.gov/psc-manual..."

### Testing
- `tests/test_validation.py`: 13 new tests (6 offline regressions for
  the new fixes, 6 live regressions gated by `SAM_LIVE_TESTS=1`). Old
  WAF-rejection tests were replaced with "WAF-accepts" tests to catch
  regression if someone re-adds the overzealous filter.
- Added autouse fixture to reset `srv._client` between tests
  (multi-event-loop safety).

## 0.3.0
Deep hardening release. Four audit rounds surfaced 30+ issues behind SAM.gov's
notoriously temperamental API surface. This release adds aggressive
pre-validation, defensive response parsing, and a WAF pre-filter so tools fail
fast with actionable errors instead of hitting the firewall or crashing on
unusual response shapes.

### Crash fixes (all triggered by plausible SAM responses)
- `_normalize_awards_response`: `int(None)` TypeError when Contract Awards
  returns `totalRecords`/`limit`/`offset` as null. Replaced raw `int()` with
  `_safe_int` helper.
- `get_entity_reps_and_certs`: AttributeError when `entityData` returns as a
  dict instead of list (XML-to-JSON single-item collapse). Added `_as_list`
  normalizer.
- `vendor_responsibility_check`: KeyError when `totalRecords>0` but
  `entityData` missing, AttributeError when `excludedEntity` collapses to
  dict, KeyError when `totalRecords` comes back as string `"0"` (`== 0`
  compare fails). All fixed via `_as_list` + `_safe_int` + isinstance guards.

### Silent-wrong-data and validation-gap fixes
- `get_entity_reps_and_certs`: full payload is ~70KB. Added `summary_only=True`
  default returning provisionId/title/answerCount per clause, plus
  `clause_filter` param. Full detail still available via
  `summary_only=False`.
- `search_contract_awards`: `fiscal_year` now accepts int OR str (was
  str-only), with range validation 2008..current FY.
  `awardee_uei`/`awardee_cage_code` format-validated. NAICS validated to 2-6
  digits with `~`/`!` operator support. `dollars_obligated` bracket
  `[min,max]` format validated.
- `search_opportunities`: pre-enforces SAM's 364-day `posted_from`→`posted_to`
  cap. Rejects reversed date ranges. `title`/`solicitation_number`
  length-clamped. `set_aside` validated against `SET_ASIDE_CODES` dict +
  case-normalized.
- `search_entities`: `business_type_code` validated against
  `BUSINESS_TYPE_CODES` + `SBA_BUSINESS_TYPE_CODES` dicts.
  `legal_business_name`/`free_text` WAF-checked and length-clamped.
  `state_code` 2-letter USPS enforced.
- `search_exclusions`: `entity_name`/`free_text` WAF-checked +
  length-clamped. CAGE format-validated. `country` lowercase auto-normalized
  to uppercase (was rejected). `activation_date_range` MM/DD/YYYY validated.
- `check_exclusion_by_uei`, `get_entity_integrity_info`: UEI format enforced
  (was only checking empty).
- `lookup_psc_code`, `search_psc_free_text`: min-length 2, WAF-checked.
  Empty query rejected locally instead of round-tripping to API.
- `get_opportunity_description`: `notice_id` empty/whitespace rejected
  locally.

### WAF pre-filter (new)
- `_validate_waf_safe` rejects strings containing path traversal (`../`),
  HTML angle brackets, SQL keywords + comment markers, single
  quotes/backticks, null bytes. These trigger SAM.gov's firewall which drops
  the connection silently. Pre-rejecting gives an actionable error instead
  of a generic network timeout. Applied to 6 user-controlled text fields.
- `_get` RequestError branch now also treats empty error strings as WAF
  drops (httpx sometimes surfaces WAF kills with no error text).

### Error hygiene
- `_clean_error_body` strips HTML from 401/403/400 responses (SAM returns
  HTML for auth failures). Error messages stay readable.
- `_format_error` uses cleaned bodies.

### Dates
- `_validate_date_mmddyyyy` handles bracket ranges and recursively validates
  inner dates. Leap year / non-leap year Feb 29 correctly distinguished.
- All date-taking tools reject ISO 8601, YYYY-MM-DD, single-digit months,
  dashes-instead-of-slashes.

### Type coercion
- `_coerce_str` accepts int or str for conceptually-numeric code fields.
  `naics_code`, `psc_code`, `zip_code`, `contracting_*_code`,
  `modification_number`, `fiscal_year` all now accept int transparently.

### Defensive parsing
- `_as_list` normalizes XML-to-JSON single-item collapse wherever SAM
  responses can collapse (`entityData`, `excludedEntity`, `awardSummary`,
  `businessTypeList`, `listOfActions`, `farResponses`, `dfarsResponses`).
- `_safe_int` never crashes on None/"null"/""/bad types.

### Release automation
- Added `.github/workflows/publish.yml`. Tagging `v*.*.*` triggers test,
  build, and PyPI publish via Trusted Publisher (no tokens).
- `constants.USER_AGENT` bumped to 0.3.0.

### Tests
- New `tests/test_validation.py` with 65 tests covering every fix through
  the FastMCP registry (`mcp.call_tool`) so pydantic coercion runs as in
  production. Prior `stress_test.py` awaited raw coroutines and bypassed
  the tool pipeline, which is why the round-4 crashes shipped in 0.2.x.

### Breaking change note
- `get_entity_reps_and_certs` default response shape differs: summary mode
  now on by default. Callers wanting the raw ~70KB response must pass
  `summary_only=False`. This is the reason for the minor version bump
  (0.2.x → 0.3.0) rather than a patch bump.

## 0.2.0
Contract Awards API support (FPDS replacement).

- 3 new tools: search_contract_awards, lookup_award_by_piid, search_deleted_awards
- Contract Awards v1 (/contract-awards/v1/search) covers the full FPDS data set
- Response normalization: empty results use a different JSON wrapper than populated results; all tools return a consistent shape
- Plain text/HTML error handling: Contract Awards returns non-JSON for certain errors (limit>100, bad date format, invalid API key)
- Client-side limit validation (max 100) with actionable error messages
- 15 total tools (was 12)

## 0.1.0
Initial release.

- 12 MCP tools covering three SAM.gov REST APIs plus PSC lookup
- Entity Management v3: lookup_entity_by_uei, lookup_entity_by_cage, search_entities, get_entity_reps_and_certs, get_entity_integrity_info
- Exclusions v4: check_exclusion_by_uei, search_exclusions
- Get Opportunities v2: search_opportunities, get_opportunity_description
- PSC lookup: lookup_psc_code, search_psc_free_text
- Composite workflow: vendor_responsibility_check (FAR 9.104-1 entity + exclusion check)
- Actionable error translation for 400/401/403/404/406/414/429 responses
- 90-day key expiration detection with regeneration instructions
- WAF connection-drop detection with actionable message
- Client-side validation: entity size cap (10), exclusion size cap (100), opportunity limit cap (1000), negative size rejection, 3-char ISO country code enforcement, empty UEI/CAGE guardrails
- Agency post-filter workaround for broken deptname/subtier Opportunities params
- Authentication via SAM_API_KEY environment variable (never enters model context)
