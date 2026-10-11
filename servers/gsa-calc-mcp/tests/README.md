# Test suite map

443 tests (322 offline, 121 live). Files are named by the audit round or fix
release that produced them, so each test traces back to its fix in git history.
[../testing.md](../testing.md) explains how to run them.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_validation.py` | Foundational input validation: query shapes, education levels, price bounds | 117 | 8 live |
| `test_round_5.py` | Round 5 live audit + Hypothesis property rounds against the CALC v3 rates API | 202 | 91 live |
| `test_round_6.py` | 1.0.1 fixes: worksite filter dead upstream (now raises), experience_min corrected to >= from exact-match, 4 dead SINs removed, vendor_rate_card gained paging | 33 | 6 live |
| `test_audit_r7.py` | Round 7 super-cycle: one-call-per-test live anchors (keyword rates, >= experience differential, live SIN) | 4 | 4 live_smoke |
| `test_e2e_audit_2026_10.py` | 1.0.13: cross-field population, unverifiable title lists, capped suggestion counts and undefined statistics | 19 | 0 |
| `test_content_fixes_2026_10.py` | 1.0.12 content-test regressions and direct government API comparisons | 30 | 12 live |
| `test_grade_specific_comparison.py` | 1.0.16: no verdict when grades differ or the exact grade is missing; exact small-sample control | 3 | 0 |
| `test_literal_colon_exact_title.py` | 1.0.17: exact titles containing a colon, MA eligibility, and controls for ordinary, nonexact and approximate results | 5 | 0 |
| `test_sdk_worksite_recovery.py` | 1.0.15: worksite recovery guidance over real stdio on MCP 2.0 and 2.3 | 2 | 0 |
| `test_http.py` | HTTP response handling and upstream error regressions | 2 | 0 |
| `test_throughput.py` | Request pacing, concurrency and budget regressions | 12 | 0 |
| `test_response_cache_hosted.py` | Hosted response-cache behavior and safeguards | 5 | 0 |
| `test_hosted_budget_contract.py` | Hosted budget: each tool call uses one GSA request | 9 | 0 |

Separate hosted Worker tests are not included in this count.

Live tests need `GSA_CALC_LIVE_TESTS=1` (no API key). `conftest.py` paces them
and resets the shared HTTP client between tests. Run the small
one-call-per-test live set with `pytest -m live_smoke`.

- `fixtures/` holds saved GSA responses used by the offline regressions.
- `scenarios/` holds standalone scenario scripts from early rounds (not pytest).
