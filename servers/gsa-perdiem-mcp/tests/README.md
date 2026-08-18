# Test suite map

438 collected tests. Files are named by the audit round or fix-wave that
produced them and are append-only history mapping to sections of
[../testing.md](../testing.md). Do not consolidate rounds.

| File | Collected |
|---|---|
| `test_audit_r7.py` | 21 |
| `test_audit_r8.py` | 4 |
| `test_live_audit_r6.py` | 240 |
| `test_validation.py` | 173 |

Live tests are gated by env var (see conftest.py), paced automatically, and
the one-call-per-test anchor set runs via `pytest -m live_smoke`.
- `scenarios/` holds standalone scenario scripts (not pytest).
