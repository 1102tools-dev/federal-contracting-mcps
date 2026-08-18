# Test suite map

300 collected tests. Files are named by the audit round or fix-wave that
produced them and are append-only history: each maps to a section of
[../testing.md](../testing.md), which narrates what every round found and
fixed. That traceability is deliberate; do not consolidate or rename rounds.

| File | Origin and purpose | Tests | Live |
|---|---|---|---|
| `test_validation.py` | Foundational input validation: titles, chapters, dates, param shapes | 104 | 13 live |
| `test_round_6.py` | Round 6 live audit: version dates, search semantics, structure walking against production | 39 | 19 live |
| `test_1_0_2_audit.py` | 1.0.2 fix-wave regressions: Title 48 chapter whitelist that was missing 9 chapters (HSAR et al.), XML tables silently dropped from section text, missing appendix parameter | 37 | 7 live |
| `test_audit_r7.py` | Round 7 super-cycle: one-call-per-test live contract anchors (chapter 99 visible, FAR clause lookup, corrections endpoint) | 5 | 5 live_smoke |

Live tests need `ECFR_LIVE_TESTS=1 (or MCP_LIVE_TESTS=1); keyless API`, are paced automatically by `conftest.py` (which
also resets the cached async client per test so batched live runs cannot hit
the closed-event-loop trap), and the minimal one-call-per-test anchor set
runs via `pytest -m live_smoke`.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
