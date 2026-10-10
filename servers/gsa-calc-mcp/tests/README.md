# Test suite map

414 collected tests. Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_validation.py` | Foundational input validation: query shapes, education levels, price bounds | 117 | 8 live |
| `test_round_5.py` | Round 5 live audit + Hypothesis property rounds against the CALC v3 rates API | 202 | 91 live |
| `test_round_6.py` | 1.0.1 fix-wave regressions: worksite filter dead upstream (now raises), experience_min corrected to >= from exact-match, 4 dead SINs removed, vendor_rate_card gained paging | 33 | 6 live |
| `test_audit_r7.py` | Round 7 super-cycle: one-call-per-test live anchors (keyword rates, >= experience differential, live SIN) | 4 | 4 live_smoke |
| `test_e2e_audit_2026_10.py` | Cross-field population, unverifiable title lists, capped suggestion counts and undefined statistics | 19 | 0 |
| `test_content_fixes_2026_10.py` | 1.0.12 content-test regressions and direct government API comparisons | 30 | 12 live |

| `test_http.py` | HTTP response handling and upstream error regressions | 2 | 0 |
| `test_throughput.py` | Request pacing, concurrency and budget regressions | 12 | 0 |
| `test_response_cache_hosted.py` | Hosted response-cache behavior and safeguards | 5 | 0 |
| `test_hosted_budget_contract.py` | Hosted upstream budget defaults and documentation contract | 9 | 0 |

Totals verified by Python 3.12 pytest collection: 433 tests, with 121 live-gated and 312 offline. The 1.0.12 content-fix suite adds 18 offline tests and 12 live source comparisons. Separate Worker tests are not included in this Python total.

Live tests need `GSA_CALC_LIVE_TESTS=1; keyless API`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
