# Test suite map

456 collected tests (338 offline, 118 live-gated). Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_validation.py` | Foundational input validation: titles, chapters, dates, param shapes | 104 | 13 live |
| `test_round_6.py` | Round 6 live audit: version dates, search semantics, structure walking against production | 138 | 93 live |
| `test_1_0_2_audit.py` | 1.0.2 fix-wave regressions: Title 48 chapter whitelist that was missing 9 chapters (HSAR et al.), XML tables silently dropped from section text, missing appendix parameter | 53 | 7 live |
| `test_audit_r7.py` | Round 7 super-cycle: one-call-per-test live contract anchors (chapter 99 visible, FAR clause lookup, corrections endpoint) | 5 | 5 live_smoke |
| `test_real_xml_fixtures.py` | 1.1.0 (2026-10-10 bug hunt): ten real eCFR responses in `fixtures/ecfr_xml/`; every text node must come out exactly once, in order, under the right section; targeted checks per bug; pages add up to the whole answer; all 253 2.101 definitions found by name | 32 | offline |
| `test_1_1_0.py` | 1.1.0 fix wave (2026-10-10 bug hunt, groups 1-6): every tool change, eCFR mocked | 67 | offline |
| `test_e2e_20261010.py` | October 10 content/usability followups: unavailable snapshots, citation title preservation, changes-only, recovery parameters | 12 | offline |
| `test_content_round4.py` | 1.1.6 missing-source guidance through real stdio, legacy history/dated-text/removal followups and unexpected-error controls | 5 | offline |
| `test_content_round3.py` | 1.1.5 source-backed Section 508 chronological timeline/page followups and available 2016 snapshot comparison | 2 | offline |
| `test_content_round2.py` | 1.1.3 ordinary content research: COR original/canonical/acronym definitions, executable grants-comparison followup, intersected correction scopes using primary-source fixtures | 7 | offline |
| `test_sdk_error_recovery.py` | 1.1.2 delivery correction: real stdio errors retain actionable guidance, then corrected questions complete | 1 | offline |
| `test_http.py` | HTTP transport checks | 2 | offline |
| `test_response_cache_hosted.py` | Hosted response-cache checks | 9 | offline |
| `test_throughput.py` | Durable reservation policy, delayed persistence and concurrency checks | 10 | offline |
| `test_xml_cache.py` | XML cache checks | 9 | offline |

Counts above are actual collected pytest cases under Python 3.12, including parameterized cases. The 1.1.2 offline lane passed 323 with 118 skipped under both frozen MCP 2.0.0 and fresh installed-wheel MCP 2.3.0. The preserved 1.1.1 full live run passed all 118 live-gated tests; the new stdio recovery test uses mocked upstream data and makes no government API call.

The 1.1.3 candidate passed 330 offline tests with 118 live skips under both frozen SDK 2.0.0 and fresh installed-wheel SDK 2.3.0; the complete live lane then passed all 448 tests, including all 118 live cases, with no skips (651.26 seconds). Seven new content regressions use saved source fixtures or mocked upstream responses. The actual candidate CLI completed 73 source-backed original/followup calls.

Live tests need `ECFR_LIVE_TESTS=1 (or MCP_LIVE_TESTS=1); keyless API`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).

The 1.1.4 reservation-contract correction collected 449 tests: both frozen SDK 2.0.0 and fresh candidate-wheel SDK 2.3.0 passed 331 offline cases with 118 live skips. Its new deterministic delay regression preserves permit accounting and the rolling budget; real concurrency and process-crash checks remain. The actual fresh PyPI 1.1.4 installation passed the same 331 offline cases with 118 live skips (15.47 seconds); its installed CLI completed 73 original/followup calls and the public service completed 70. Fifty rerun primary comparisons plus five corrected-original source checks passed. No new full 449-case live run is claimed.

The 1.1.5 candidate collected 451 cases: both frozen SDK 2.0.0 and fresh candidate-wheel SDK 2.3.0 passed 333 with 118 explicit live skips. Two new source-fixture regressions fail against published 1.1.4 and pass after the fixes. The actual candidate CLI completed 80 calls and 83 primary-source comparisons passed; 72 of 73 shared corpus calls stayed exactly equal to the published service. No new full 451-case live-suite run is claimed.

The 1.1.6 candidate collected 456 cases: frozen SDK 2.0.0 and freshly installed candidate-wheel SDK 2.3.0 each passed 338 with 118 explicit live skips. Three of five new cases fail against published 1.1.5; both unexpected-error controls already pass. All five pass after the correction. Actual published CLI/public new research corpora each completed 77 calls (76 valid after one caller-citation exclusion); 96 primary comparisons passed per surface. The candidate installed CLI completed the four affected recovery calls. No new full live-suite run or published 1.1.6 verification is claimed.
