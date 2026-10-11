# Test suite map

2,322 tests (1,943 run by default, 379 live-gated), counted including
parametrized cases. Files are named by the audit round or fix release that
produced them; keep those names so each test traces back to its fix in git
history. [../testing.md](../testing.md) explains how to run them.

| File | Origin and purpose | Tests | Live-gated |
|---|---|---:|---:|
| `test_validation.py` | Foundational input validation and live checks | 62 | 10 |
| `test_density_r5.py` | Round 5 density sweep: every input field on every tool | 415 | 0 |
| `test_live_audit_r6.py` | Round 6 live audit of every tool | 157 | 157 |
| `test_live_audit_r7.py` | Round 7 deep live audit: chained IDs, IDV child modes, sorting, paging | 104 | 104 |
| `test_round_8.py` | Round 8 property-based and live cases | 69 | 10 |
| `test_v0_3_features.py` | v0.3 expansion from 17 to 55 tools | 1,244 | 75 |
| `test_search_family_fixes.py` | 1.0.1 search-family fixes | 37 | 8 |
| `test_entity_family_fixes.py` | 1.0.1 entity-family fixes | 63 | 4 |
| `test_audit_r11.py` | Round 11 paced live campaign anchors | 9 | 7 |
| `test_content_fixes_1013.py` | 1.0.13 content corrections | 75 | 4 |
| `test_content_e2e_1014.py` | 1.0.14 scope guidance from the end-to-end audit | 36 | 0 |
| `test_published_scope_1015.py` | 1.0.15 description scope guidance | 2 | 0 |
| `test_new_awards_fiscal_year_1016.py` | 1.0.16 fiscal-year new-award counts; quarter/month unchanged | 6 | 0 |
| `test_subaward_period_scope_1017.py` | 1.0.17 cumulative versus dated FFATA reports | 3 | 0 |
| `test_federal_account_program_scope_1018.py` | 1.0.18 all-year program lists, complete list and single-year followup | 3 | 0 |
| `test_federal_account_available_fy_1020.py` | 1.0.20 unavailable fiscal year guidance | 3 | 0 |
| `test_naics_current_retired_1021.py` | 1.0.21 retired codes versus codes cut by the limit | 3 | 0 |
| `test_award_date_overlap_r6.py` | 1.0.22 award date windows versus dated transactions | 3 | 0 |
| `test_sdk23_expected_guidance.py` | 1.0.23 input-error guidance under MCP SDK 2.3 | 4 | 0 |
| `test_http.py` | Hosted HTTP application | 2 | 0 |
| `test_response_cache_hosted.py` | Hosted response cache | 10 | 0 |
| `test_throughput.py` | Request throughput and pacing | 9 | 0 |
| `test_tool_profiles.py` | Tool profile selection | 3 | 0 |
| **Total** | | **2,322** | **379** |

Live tests need `USASPENDING_LIVE_TESTS=1` (the API is keyless), are paced
1-2 s apart by `conftest.py`, and the minimal anchor set runs via
`pytest -m live_smoke` (~10 calls).

- `scenarios/` holds standalone scenario scripts (not pytest; kept from early rounds).

List the tests without running live checks:

```bash
USASPENDING_LIVE_TESTS=0 uv run --project servers/usaspending-gov-mcp pytest --collect-only -q servers/usaspending-gov-mcp/tests
```
