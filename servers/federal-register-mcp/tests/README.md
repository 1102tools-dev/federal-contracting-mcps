# Test suite map

286 collected tests (181 offline, 105 live-gated), counted by pytest collection
including parametrized cases. Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_validation.py` | Foundational input validation: document numbers, dates, agency slugs | 77 | 13 live |
| `test_round_5.py` | Round 5 live audit: search semantics, facets, public inspection against production | 105 | 78 live |
| `test_round_6.py` | 1.0.1 fix-wave regressions: pre-2011 document numbers rejected (17-year lockout), open_comment_periods sorted descending and dropped soonest-closing docs, FAR-case history returned partial sets | 46 | 5 live |
| `test_audit_r7.py` | Round 7 super-cycle: one-call-per-test live anchors (FAR Case 2017-016 completeness, 2005 documents reachable, close dates ascending) | 4 | 4 live_smoke |
| `test_round_8.py` | 1.0.13 content-test regressions and direct government API comparisons | 30 | 5 live |
| `test_round_9.py` | 1.0.14 MCP-pipeline regressions: disclose partial comment scans, preserve FAR lower-bound metadata, distinguish scan completeness from returned limits | 4 | 0 |
| `test_http.py` | Hosted HTTP tool catalog and request guards | 2 | 0 |
| `test_response_cache_hosted.py` | Hosted response caching, expiry, and issue-date invalidation | 9 | 0 |
| `test_throughput.py` | Shared pacing, cross-process serialization, and budgets | 9 | 0 |

Live tests need `FR_LIVE_TESTS=1; keyless API`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
