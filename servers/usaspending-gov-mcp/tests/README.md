# Test suite map

Frozen Python 3.12.13 and actually installed candidate-wheel Python 3.12.13
full executions for candidate 1.0.23 each collect 2,322 cases and measure
1,943 passed / 379 skipped on MCP SDK 2.0.0 and 2.3.0 respectively. All 855
retained failed node IDs are rerun and pass. Four new source-derived workflow
and unexpected-fault controls are included; content questions are not pytest
cases. Candidate publication remains pending.

The actual published 1.0.22 latest-SDK execution remains 1,084 passed /
855 failed / 379 skipped / 2,318 collected. Its successful 153-question
console/public content campaign is separate. Expected-input assertions retain
visible, specific recovery hints. Unexpected provider/internal fixtures retain
strict wrapper, causal type/status/detail/cleaning and SDK masking assertions;
causes are not credited as client-visible guidance.

Files retain their audit-round and fix-wave history; see [../testing.md](../testing.md).

| File | Origin | Collected | Live-gated |
|---|---|---:|---:|
| `test_audit_r11.py` | Round 11 paced live campaign contracts | 9 | 7 |
| `test_content_e2e_1014.py` | Round 13 full end-to-end scope guidance | 36 | 0 |
| `test_content_fixes_1013.py` | Round 12 content corrections | 75 | 4 |
| `test_density_r5.py` | Round 5 density sweep | 415 | 0 |
| `test_entity_family_fixes.py` | Round 10 entity-family fixes | 63 | 4 |
| `test_http.py` | Hosted HTTP application | 2 | 0 |
| `test_live_audit_r6.py` | Round 6 live audit | 157 | 157 |
| `test_live_audit_r7.py` | Round 7 live audit | 104 | 104 |
| `test_new_awards_fiscal_year_1016.py` | Round 14 captured annual fiscal-year correction; unchanged quarter/month | 6 | 0 |
| `test_published_scope_1015.py` | Round 13 published description guidance | 2 | 0 |
| `test_response_cache_hosted.py` | Hosted response cache | 10 | 0 |
| `test_round_8.py` | Round 8 property and live cases | 69 | 10 |
| `test_search_family_fixes.py` | Round 10 search-family fixes | 37 | 8 |
| `test_throughput.py` | Request throughput and pacing | 9 | 0 |
| `test_tool_profiles.py` | Tool profile selection | 3 | 0 |
| `test_v0_3_features.py` | v0.3 expansion (17 to 55 tools) | 1,244 | 75 |
| `test_validation.py` | Foundational validation and live checks | 62 | 10 |
| `test_subaward_period_scope_1017.py` | Round 15 cumulative/dated FFATA scope | 3 | 0 |
| `test_federal_account_program_scope_1018.py` | Round 16 captured all-year scope, complete program list and financial followup | 3 | 0 |
| `test_federal_account_available_fy_1020.py` | Round 16 actual source availability, supported recovery and unexpected503 control | 3 | 0 |
| `test_naics_current_retired_1021.py` | Round 17 captured current-versus-retired taxonomy, larger-limit recovery and source-row control | 3 | 0 |
| `test_award_date_overlap_r6.py` | Round 18 source interval overlap, actual dated recovery and unchanged explicit/no-window controls | 3 | 0 |
| `test_sdk23_expected_guidance.py` | SDK 2.3 expected guidance | 4 | 0 |
| **Total** | | **2,322** | **379** |

Live tests need `USASPENDING_LIVE_TESTS=1` (the API is keyless), are paced
1-2 s apart by `conftest.py`, and the minimal anchor set runs via
`pytest -m live_smoke` (~10 calls).

- `scenarios/` holds standalone scenario scripts (not pytest; retained for
  reproducibility of early rounds).

Reproduce collection without enabling live checks:

```bash
USASPENDING_LIVE_TESTS=0 uv run --project servers/usaspending-gov-mcp pytest --collect-only -q servers/usaspending-gov-mcp/tests
```
