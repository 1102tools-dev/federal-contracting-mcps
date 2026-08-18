# Test suite map

438 collected tests. Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_validation.py` | Foundational input validation: cities, states, zips, fiscal years (largest offline set) | 173 | 8 live |
| `test_live_audit_r6.py` | Round 6 all-live audit: every tool against the production GSA per diem API (the unmatched-city test was drift-proofed 2026-08 when new-FY rates made its city a real NSA) | 56 | all live |
| `test_audit_r7.py` | Round 7 fix-wave regressions: the false WARNING stamped on the API's correct city-to-county resolution (Penasco->Taos was right all along) and the OCONUS empty-success trap | 21 | 3 live |
| `test_audit_r8.py` | Round 8 super-cycle: one-call-per-test live anchors (Penasco resolves warning-free, CONUS zip fallback, OCONUS explains itself, M&IE tier table) | 4 | 4 live_smoke |

Live tests need `MCP_LIVE_TESTS=1 + PERDIEM_API_KEY`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
