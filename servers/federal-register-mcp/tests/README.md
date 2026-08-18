# Test suite map

232 collected tests. Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_validation.py` | Foundational input validation: document numbers, dates, agency slugs | 77 | 10 live |
| `test_round_5.py` | Round 5 live audit: search semantics, facets, public inspection against production | 42 | 20 live |
| `test_round_6.py` | 1.0.1 fix-wave regressions: pre-2011 document numbers rejected (17-year lockout), open_comment_periods sorted descending and dropped soonest-closing docs, FAR-case history returned partial sets | 26 | 5 live |
| `test_audit_r7.py` | Round 7 super-cycle: one-call-per-test live anchors (FAR Case 2017-016 completeness, 2005 documents reachable, close dates ascending) | 4 | 4 live_smoke |

Live tests need `FR_LIVE_TESTS=1; keyless API`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
