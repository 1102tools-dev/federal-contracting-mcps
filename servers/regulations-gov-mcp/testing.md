# Regulations.gov MCP: Testing Record

## Executive Summary

This Model Context Protocol server exposes the Regulations.gov API as 8 callable tools for federal rulemaking dockets, proposed rules, final rules, public comments, and comment-period tracking. It was hardened across four audit rounds, then re-audited end to end in the suite-wide round-7 wave (1.0.1) by an independent full-source review with live verification. The signature 0.2.0 finding was `agency_id=""` silently returning all 1,951,938 documents. The signature round-7 finding was its ironic sequel: `open_comment_periods` sorted by deadline DESCENDING and truncated at 50, so the soonest-closing documents (the ones the tool exists to surface) were silently dropped; live proof was FDA with 71 open documents where the ones closing in 2 days were among the missing. The MCP ships with 200 regression tests (85 offline plus 115 live-gated).

| Metric | Value |
|---|---|
| MCP tools exposed | 8 |
| Total regression tests | 200 (85 offline, 115 live-gated) |
| Audit rounds completed | 5 (rounds 1-4 plus the suite-wide round-7 wave) |
| P0 catastrophic bugs found and fixed | 1 (`extra='ignore'` silent typo drop) |
| P1 silent-wrong-data bugs found and fixed | 10 |
| P2 validation gaps found and fixed | 7 |
| Round-7 wave findings | 12 |
| Current release | 1.0.1 |
| PyPI status | Published as `regulationsgov-mcp`, auto-publishes via Trusted Publisher on tag push |

## What Was Tested

The MCP exposes 8 tools covering the Regulations.gov API surface. Testing covered all of them end-to-end.

**Core:** `search_documents`, `get_document_detail`, `search_comments`, `get_comment_detail`, `search_dockets`, `get_docket_detail`

**Workflow:** `open_comment_periods`, `far_case_history`

Each tool was exercised for argument validation, input sanitization (null bytes, script injection, path-traversal IDs), empty-string filter detection, date format checking, pagination edge cases (including the live 40-page boundary), response-shape guarantees, error translation, filter-name truth (every filter the code builds verified live to actually change results), and real-world data handling against the live production Regulations.gov API with a real `api.data.gov` key.

## How It Was Tested

### Testing discipline

This MCP had never been hardened before 0.2.0. The hardening program invoked tools through `mcp.call_tool(name, kwargs)` the way a real MCP client does, paired with live audits using a real `api.data.gov` key. The round-7 wave added the harder discipline: verify each documented API limit against live behavior instead of trusting the docs (the "20-page cap" is really 40), verify each of this document's own claims against the code (several were phantom), and end-to-end test the workflow tools' OUTPUT semantics, not just that they return dicts.

### Audit rounds

| Round | Scope | Finding class |
|---|---|---|
| 1 | Broad live sweep across all 8 tools | 1 P0, 8 P1, 6 P2, 3 P3 |
| 2 | Response-shape probes and workflow tools | 2 additional P1, 1 P2 |
| 3 | Deep live stress (pagination, concurrency, compound filters) | `paged_past_end` flag; the round's "no new bugs" claim did not survive round 7 |
| 4 | Property-based (hypothesis) + live suite in `tests/test_round_4.py` | Previously undocumented in this file |
| 7 (suite-wide wave) | Independent full-source re-audit with live verification (stronger model), shipped at 1.0.1 | 12 findings |

### Live audit status

Rounds 1-4 and 7 ran against the production Regulations.gov API. The repository includes 115 live-gated regression tests executable via `REGULATIONS_LIVE_TESTS=1 REGULATIONS_GOV_API_KEY=... pytest`. Note the gate variable: earlier versions of this document said `REGULATIONS_GOV_LIVE_TESTS=1`, which was never the gate and silently skipped every live test. The key is free at `api.data.gov` (1,000 req/hr, live-verified via x-ratelimit headers); DEMO_KEY is 10 req/hr (live-measured; earlier docs said 40).

## Round 7 wave (1.0.1): Independent re-audit

12 findings, all fixed in 1.0.1:

| # | Finding | Fix |
|---|---|---|
| 1 | **`open_comment_periods` silently dropped the soonest-closing documents.** Per agency it fetched one page of 50 sorted `-commentEndDate` (DESCENDING: furthest deadline first), never followed pagination, and reported `total_open=len(fetched)`. Live: FDA has 71 open documents; the tool returned 50 whose soonest deadline was 2026-09-16 while the API's true soonest (closing in 2 days) were absent, and evergreen 2050 notices were kept. | Ascending `commentEndDate` sort, one comma-joined query for all agencies (8 round-trips became 1), page size 250, API-true `total_open` from `meta.totalElements`, `truncated` flag noting the omitted documents all close LATER, undated documents listed last instead of dropped. |
| 2 | `within_comment_period=False` always failed with HTTP 400 (the API accepts only `true`), and the server's 400 handler misdiagnosed it as a casing problem. A prior round enshrined the 400 in a live test instead of fixing the parameter. | `False` is rejected locally with real guidance ("omit the parameter instead"); only `true` is ever sent. |
| 3 | Local page cap of 20 blocked records 5,001-10,000: the live API accepts pages up to 40 (its own 400 at page 1000 says "Maximum value is 40"; page 21 returns real data). | Cap raised to 40; the three stale "~5,000 / 20 pages" strings corrected. |
| 4 | Comma-separated multi-field sort rejected, blocking the API's own deep-pagination recipe (`sort=lastModifiedDate,documentId`). | Sort validator splits on commas and validates each field. |
| 5 | Comma-separated multi-agency filter rejected despite being the documented form (`filter[agencyId]=GSA,EPA`, verified live: FAR,GSA returns both). | Agency validator accepts comma lists, validating each token. |
| 6 | `far_case_history` silently truncated dockets with more than 250 documents while its docstring promised "all documents" (live: EPA-HQ-OAR-2009-0171 reported total 553, returned exactly 250, no flag). | Follows pagination up to 1,000 documents (4 pages), sets `truncated` beyond, docstring states the cap. |
| 7 | Empty-string `docket_id` / `comment_on_id` silently dropped the filter and searched the whole corpus (~2M documents / ~26M comments): the exact empty-string class the 0.2.0 headline fixed for agency_id, left open here. Bonus inconsistency: whitespace-only strings DID raise while `""` did not. | Both now raise, matching the agency_id treatment. |
| 8 | Passing a documentId where `filter[commentOnId]` needs the hex objectId silently returned 0 comments (verified live: the documentId form gives totalElements 0; the objectId gives the real comments), and the no-data hint did not even mention comment_on_id. | Non-hex `comment_on_id` shapes are rejected with directions to `attributes.objectId`; the no-data context includes comment_on_id. |
| 9 | DEMO_KEY rate limit misstated three different ways (40/hr in code and readme, 30/hr + 50/day in smithery.yaml); live header says 10. | Standardized on the live-measured 10/hr. |
| 10 | readme linked TESTING.md; the file is testing.md (404 on GitHub, case-sensitive). | Link lowercased. |
| 11 | Dead code: `_clamp_str_len` referenced only by its own test; `DOCUMENT_TYPES`/`DOCKET_TYPES` imported but unused (tools use Literal types). | Removed. |
| 12 | changelog 0.1.0 claimed "9 MCP tools"; the server has always exposed 8. `serverInfo.version` was empty. | Corrected; MCPServer now receives the package version. |

**Verified clean in the round-7 wave (live-checked, no bug):** every filter param name the code builds is honored live and changes results (agencyId, docketId, documentType, searchTerm, withinCommentPeriod=true, postedDate, commentEndDate, lastModifiedDate, commentOnId, docketType); `filter[docketId]` on /comments works live even though the v4 OpenAPI spec omits it (undocumented-upstream dependency, now noted in the docstring); space and ampersand URL-encoding; agencyId case-insensitivity as the no_data hint claims; `meta.aggregations` present as promised; per-endpoint sort whitelists match the spec; OFPP and DARS are real agency codes; the server boots over stdio and lists all 8 tools.

### Corrections to the prior record (round-7 wave)

- **Wrong live-gate env var, stated twice:** `REGULATIONS_GOV_LIVE_TESTS` was never the gate; both test files gate on `REGULATIONS_LIVE_TESTS`.
- **Phantom test file:** the coverage table listed `tests/stress_test_r3.py` ("retained for reproducibility"); no such file exists. `tests/test_round_4.py`, the bulk of the suite, was absent from this document entirely.
- **Stale version and counts:** "0.2.0" and "51 regression tests"; the 51 figure described test_validation.py alone.
- **"WAF vs auth 403 disambiguation added via header inspection":** false mechanism; the code inspects the response BODY, and the quoted error string "WAF blocked request (not an auth issue)" appears nowhere in the code.
- **"Known-agency list validation ... suggestion to check `list_agencies`":** false twice. No known-agency list exists (format regex only; unknown codes return the no_data flag), and no `list_agencies` tool exists in this server.
- **"API caps total results around 5,000 (20 pages)":** contradicted live; 40 pages are reachable. The published GSA docs do say 20, but this document presented the 20-page cap as live-verified.
- **"Empty-string filter detection" as a closed class:** only agency_id was fixed; docket_id and comment_on_id still silently unfiltered until the round-7 wave.
- **Round 3 "no new bugs":** the round's own later artifact enshrined the withinCommentPeriod=false 400 in a test without fixing it, and both workflow tools carried live-reproducible silent-data-loss bugs.

## Issues Found and Fixed (rounds 1-4)

### Priority 0: Catastrophic silent wrong data

| Issue | Fix |
|---|---|
| **Unknown parameters silently dropped** via pydantic's default `extra='ignore'`. Verified live: `search_documents(agency_id="FAR", bogus_typo="x")` succeeded with the typo dropped and returned unfiltered documents. | `extra='forbid'` applied to every tool's pydantic arg model (cross-fix from sam-gov-mcp 0.3.1). Typos now raise "Extra inputs are not permitted" before the HTTP call. |

### Priority 1: Silent wrong data

| Issue | Fix |
|---|---|
| **`agency_id=""` returned all 1,951,938 Regulations.gov documents.** The empty string was treated as "no filter". | Empty-string and whitespace-only agency values raise. [Extended in round 7] The same guard now covers docket_id and comment_on_id, which had been left open. |
| Unknown agency IDs ("ZZZ") silently returned 0 results with no warning. | [Corrected in round 7] The claimed known-agency list and `list_agencies` pointer never existed. Reality: format validation plus the `no_data` flag with case-guidance; agencyId is case-insensitive at the API. |
| Null byte in `search_term` silently accepted and reached the API. | Null bytes and other control characters rejected locally. |
| `<script>` in `search_term` triggered the WAF 403 but the error said "API key rejected." | [Corrected in round 7] Fixed via BODY-content inspection (not header inspection as previously claimed); WAF 403s surface with a WAF explanation. |
| Date-swapped ranges returned 0 silently. | Reversed ranges raise actionable errors. |
| `_get` returning None crashed downstream consumers. | `_safe_dict` and `_as_list` helpers added throughout. |
| Bogus sort fields produced opaque API 400s. | Sort fields validated against per-endpoint whitelists. [Extended in round 7] Comma-separated multi-field sorts now validate per-field instead of being rejected. |
| `document_id` with slashes produced HTTP 500/301. | ID format validated; path characters rejected. |
| Malformed dates reached the API as 400s. | `YYYY-MM-DD` and `'YYYY-MM-DD HH:MM:SS'` formats enforced at the arg layer. |

### Priority 2: Validation gaps

Seven bugs: defensive parsing helpers, search_term length cap (500), page_number lower bound, empty agency_ids list rejection, `_clean_error_body`, ID length/format validation, per-element agency_ids validation. [Corrected in round 7] The `_clamp_str_len` helper added in this class was never wired to production code and has been removed.

### Priority 3: Cleanup items

Four items: missing publish workflow, missing test_validation.py, missing dev dependency group, stale USER_AGENT. All resolved.

### Round 3 UX enhancement: `paged_past_end` flag

`page_number` past the last page of a non-empty result set now flags `paged_past_end` with the last valid page number, instead of bare empty data. Pattern applied retroactively to `gsa-calc-mcp`.

## Test Coverage

The repo ships 200 regression tests (85 offline, 115 live-gated). All pass on every release cycle; live tests require `REGULATIONS_LIVE_TESTS=1` plus a key.

| File | Purpose | Test count |
|---|---|---|
| `tests/test_validation.py` | Main regression suite covering rounds 1-3 findings, incl. 5 live-gated integration tests | 66 |
| `tests/test_round_4.py` | Property-based (hypothesis) validator suite plus the round-4 live sweep | 110 |
| `tests/test_audit_r7.py` | Round-7 wave regressions: ascending open-comment-periods with truncation metadata, far_case_history pagination, multi-agency and multi-sort commas, withinCommentPeriod=False local rejection, empty-string guards, commentOnId objectId shape guard, 40-page cap; 4 live confirmations | 24 (20 offline, 4 live-gated) |
| `tests/stress_test.py` | Round 1 live-probe scenarios (scenario script, not pytest) | N/A |

Regression tests invoke tools through the MCPServer registry (`mcp.call_tool`). An autouse fixture resets `srv._client` between tests.

## Release History

| Version | Focus | Outcome |
|---|---|---|
| 0.1.1 | Initial release | First-pass coverage |
| 0.2.0 | Rounds 1-3 hardening: 22 findings incl. the 1.95M-record empty-string bug | 1 P0, 10 P1, 7 P2, 4 P3 resolved |
| 0.2.x | Round 4: hypothesis property suite + live sweep (test_round_4.py) | Previously undocumented here |
| 1.0.0 | mcp 2.x SDK rebase, version sync, packaging | Stable baseline |
| 1.0.1 | Round-7 wave independent re-audit with live verification | 12 findings resolved, incl. the open_comment_periods soonest-deadline drop |

## Cross-MCP Context

This MCP is one of eight servers in the 1102tools federal-contracting MCP suite (`bls-oews-mcp`, `ecfr-mcp`, `federal-register-mcp`, `gsa-calc-mcp`, `gsa-perdiem-mcp`, `sam-gov-mcp`, `usaspending-gov-mcp`, and this one). All eight were hardened under the same playbook. Patterns established or reinforced here:

- **The empty-string unfiltered-query class** was discovered here (agency_id) and the round-7 wave closed the stragglers (docket_id, comment_on_id) plus the same class's cousin: a documented-but-wrong ID kind (documentId vs objectId) silently returning zero.
- **Verify documented limits against live behavior** (round-7 wave): the "20-page cap" every doc repeats is 40 live; DEMO_KEY's "40/hr" is 10 live.
- **Workflow tools need output-semantics tests**: `open_comment_periods` passed every shape test while dropping the exact documents it exists to find. The round-7 live tests assert ordering and totals, not dict-ness.

## What Was Not Tested

- **Deep pagination beyond 10,000 records.** The lastModifiedDate windowing recipe is documented in docstrings but not exercised end-to-end in the live suite.
- **Comment posting.** This server is read-only; the /comments POST surface is out of scope.
- **Bulk download endpoints.** Attachment downloads are surfaced as URLs, not fetched.
- **WAF behavior catalog.** The 403-vs-WAF disambiguation is body-heuristic; the WAF's full trigger set is not characterized.

## Verification

All testing artifacts are in the repository. The methodology and fixes are reviewable commit-by-commit in git history. The regression test suite runs via `pytest` in the repo root and can be re-executed by anyone. The live suite runs with `REGULATIONS_LIVE_TESTS=1 REGULATIONS_GOV_API_KEY=... pytest` using a free `api.data.gov` key.

---

**Testing Methodology**

Evaluators: James Jenrette, 1102tools, with Claude Code Opus 4.7 during the original hardening playbook, and Claude Code Fable 5 for the round-7 wave independent re-audit (full-source review, live API verification, record correction).

Round-7 wave methodology: re-read the entire server source with no reliance on this document's claims; verify every filter parameter name live against result deltas; probe documented limits (page cap, DEMO_KEY rate) against live headers and boundary requests; end-to-end test both workflow tools through the real server against known corpora (FDA open comment periods, a 553-document EPA docket); check every prior claim in this document against the code and live behavior.

Test count: 200 regression tests (85 offline + 115 live-gated). Total findings across all rounds: 34. Current version: 1.0.1. PyPI: `regulationsgov-mcp`.

Source: github.com/1102tools/federal-contracting-mcps/tree/main/servers/regulations-gov-mcp. License: MIT.
