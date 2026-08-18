# Test suite map

204 collected tests. Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_validation.py` | Foundational input validation: docket ids, document types, date shapes | 51 | 5 live |
| `test_round_4.py` | Round 4 live audit: search semantics, docket/document/comment chains against production | 32 | 16 live |
| `test_audit_r7.py` | Round 7 fix-wave regressions: open_comment_periods sorted DESCENDING and dropped the soonest-closing documents (deadline-critical), live page cap is 40 not the documented 20 | 24 | 4 live |
| `test_audit_r8.py` | Round 8 super-cycle: one-call-per-test live anchors (close dates ascending, docket search, comment search) | 4 | 4 live_smoke |

Live tests need `REGULATIONS_LIVE_TESTS=1 + REGULATIONS_GOV_API_KEY`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
