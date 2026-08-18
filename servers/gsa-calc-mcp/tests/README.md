# Test suite map

356 collected tests. Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_validation.py` | Foundational input validation: query shapes, education levels, price bounds | 117 | 8 live |
| `test_round_5.py` | Round 5 live audit + Hypothesis property rounds against the CALC v3 rates API | 78 | 33 live |
| `test_round_6.py` | 1.0.1 fix-wave regressions: worksite filter dead upstream (now raises), experience_min corrected to >= from exact-match, 4 dead SINs removed, vendor_rate_card gained paging | 28 | 6 live |
| `test_audit_r7.py` | Round 7 super-cycle: one-call-per-test live anchors (keyword rates, >= experience differential, live SIN) | 4 | 4 live_smoke |

Live tests need `GSA_CALC_LIVE_TESTS=1; keyless API`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
