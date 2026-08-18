# Test suite map

246 collected tests. Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_validation.py` | Foundational input validation: SOC codes, area codes, series construction | 66 | 5 live |
| `test_live_audit_r6.py` | Round 6 all-live audit: every tool against the production BLS v2 API, including the year-guard behavior (drift-proofed 2026-08: derives the latest OEWS year instead of hardcoding) | 79 | all live |
| `test_audit_r7.py` | Round 7 fix-wave regressions: THE percentile-shift money bug (hourly labels shifted one slot, Hourly Median returned 75th percentile, 26% high) and its cross-foot canary | 23 | 2 live |
| `test_audit_r8.py` | Round 8 super-cycle: one-call-per-test live anchors (hourly x 2080 cross-foot vs annual median, bad-SOC clarity, latest-year sanity) | 3 | 3 live_smoke |

Live tests need `BLS_LIVE_TESTS=1 + BLS_API_KEY`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
