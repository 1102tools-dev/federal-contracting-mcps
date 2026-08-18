# Test suite map

1,136 collected tests (762 offline, 374 live-gated). Files are named by the
audit round or purpose that produced them and are append-only history: each
maps to a section of [../testing.md](../testing.md), which narrates what every
round found. That traceability is deliberate; do not consolidate rounds.

| File | Origin | Collected | Live-gated? |
|---|---|---|---|
| `test_validation.py` | Foundational input-validation suite | 81 | 6 live |
| `test_density_r5.py` | Round 5 density sweep (every tool, every param) | 367 | offline |
| `test_live_audit_r6.py` | Round 6 live audit (WAF, casings, live semantics) | 235 | live |
| `test_round_7.py` | Round 7 Hypothesis property suite | 133 | offline |
| `test_v0_4_features.py` | v0.4 expansion (subawards, FH, deleted awards) | 278 | 123 live defs |
| `test_sba_business_type.py` | SBA certification code fix (A6/XX/JT/A4/A9/A0) | 15 | 3 live |
| `test_audit_r9.py` | Round 9 documented-shape replays (reps-and-certs casing) | 17 | offline |
| `test_audit_r10.py` | Round 10 paced live campaign regressions | 10 | 3 `live_smoke` |

Live tests need `SAM_LIVE_TESTS=1` plus `SAM_API_KEY`, are paced 2-4 s apart
by `conftest.py`, and the minimal anchor set runs via `pytest -m live_smoke`.
Know your key's daily quota before a full live pass.

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
- `live_audit/` holds the paced live-probe harness behind round 10; it spends
  real quota and is documented in its own README.
