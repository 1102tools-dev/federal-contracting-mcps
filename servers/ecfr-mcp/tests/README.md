# Test suite map

464 tests (346 offline, 118 live-gated), counted by pytest collection
including parametrized cases. Files are named by the audit round or fix release
that produced them; keep those names so each test traces back to its fix in
git history. [../testing.md](../testing.md) explains how to run them.

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
| `test_content_round6.py` | 1.1.8 dioxin MCL scientific notation and genuine footnotes from a saved Title 40 response | 3 | offline |
| `test_content_round5.py` | 1.1.7 numbered FAR 2.101 subtype definitions (individual surety, corporate surety, cosurety) | 5 | offline |
| `test_content_round2.py` | 1.1.3 ordinary content research: COR original/canonical/acronym definitions, executable grants-comparison followup, intersected correction scopes using primary-source fixtures | 7 | offline |
| `test_sdk_error_recovery.py` | 1.1.2 delivery correction: real stdio errors retain actionable guidance, then corrected questions complete | 1 | offline |
| `test_http.py` | HTTP transport checks | 2 | offline |
| `test_response_cache_hosted.py` | Hosted response-cache checks | 9 | offline |
| `test_throughput.py` | Durable reservation policy, delayed persistence and concurrency checks | 10 | offline |
| `test_xml_cache.py` | XML cache checks | 9 | offline |

Live tests need `ECFR_LIVE_TESTS=1` or `MCP_LIVE_TESTS=1` (no API key), are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `fixtures/` holds saved eCFR responses (XML text and JSON history) used by the offline tests.
- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
