# Test suite map

2,160 collected tests (1,785 offline, 375 live-gated). Files are named by the
audit round or fix-wave that produced them and are append-only history: each
maps to a section of [../testing.md](../testing.md). That traceability is
deliberate; do not consolidate rounds.

| File | Origin | Collected | Live-gated? |
|---|---|---|---|
| `test_validation.py` | Foundational input-validation suite | 62 | mixed |
| `test_density_r5.py` | Round 5 density sweep | 415 | offline |
| `test_live_audit_r6.py` | Round 6 live audit | 157 | live |
| `test_live_audit_r7.py` | Round 7 live audit | 104 | live |
| `test_round_8.py` | Round 8 | 69 | mixed |
| `test_v0_3_features.py` | v0.3 expansion (17 -> 55 tools) | 1,244 | mixed |
| `test_search_family_fixes.py` | Round 10 search-family fixes | 37 | 8 live |
| `test_entity_family_fixes.py` | Round 10 entity-family fixes | 63 | 4 live |
| `test_audit_r11.py` | Round 11 paced live campaign contracts | 9 | 7 `live_smoke` |

Live tests need `USASPENDING_LIVE_TESTS=1` (the API is keyless), are paced
1-2 s apart by `conftest.py`, and the minimal anchor set runs via
`pytest -m live_smoke` (~10 calls).

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).
