# Test suite map

300 collected tests. Files are named by the audit round or fix-wave that
produced them and are append-only history mapping to sections of
[../testing.md](../testing.md). Do not consolidate rounds.

| File | Collected |
|---|---|
| `test_1_0_2_audit.py` | 53 |
| `test_audit_r7.py` | 5 |
| `test_round_6.py` | 138 |
| `test_validation.py` | 104 |

Live tests are gated by env var (see conftest.py), paced automatically, and
the one-call-per-test anchor set runs via `pytest -m live_smoke`.
- `scenarios/` holds standalone scenario scripts (not pytest).
